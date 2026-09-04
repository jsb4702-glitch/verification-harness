#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness-heartbeat — 주기잡 헬스 + 섀도로그 델타 + 판정대기열 + 앵커 상태 점검.

경고전용·자동수정 없음(사람게이트). 산출물:
  reports/YYYY-MM-DD.md + stdout 요약 + macOS 알림.
설계 제약: launchd 컨텍스트에서 돌므로 iCloud(~/Library/Mobile Documents) 경로 검사 금지(TCC EPERM).

사용법:
  heartbeat.py                주간 점검(launchd). 상태 갱신 + 리포트 저장 + 알림.
  heartbeat.py --now          지금 보기. 상태를 건드리지 않고 전문을 화면에 뿌린다.
                              섀도 델타 기준선이 밀리지 않으므로 아무 때나 돌려도 된다.
  --slots                     검증슬롯 실핑까지(느리다 — 외부 API 왕복).
  --regression                회귀 스모크까지(느리다).
  --no-anchor                 앵커 검사·드리프트 조회 생략.

--now 는 슬롯과 회귀를 기본으로 건너뛴다. 즉시성이 목적이라 무거운 검사는 명시할 때만 돈다.
"""
import json, os, subprocess, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STATE_P = os.path.join(BASE, "state.json")
STATE = json.load(open(STATE_P)) if os.path.exists(STATE_P) else {"shadows": {}}
NOW = datetime.datetime.now()
TODAY = NOW.date()
ex = os.path.expanduser

ARGS = set(sys.argv[1:])
NOW_MODE = "--now" in ARGS                       # 읽기 전용 즉시 보기
WANT_SLOTS = ("--slots" in ARGS) or not NOW_MODE
WANT_REGRESSION = "--regression" in ARGS
WANT_ANCHOR = "--no-anchor" not in ARGS

ANCHOR_CHECKER = "/Library/AnchorTCB/integrity_check.py"
IG_PY = ex("~/.claude/tools/integrity-guard/ig.py")
REGRESSION = ex("~/harness-eval/run_regression.sh")


def launchctl_map():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    m = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            pid, st, label = parts
            m[label] = (None if pid == "-" else pid, st)
    return m


def check_jobs():
    lmap = launchctl_map()
    rows = []  # (level, name, msg)
    for j in CFG["jobs"]:
        name, msgs, level = j["name"], [], "OK"
        if j.get("label"):
            if j["label"] not in lmap:
                level, msgs = "FAIL", ["launchctl 미로드"]
            else:
                pid, st = lmap[j["label"]]
                if j.get("daemon"):
                    if pid is None:
                        level, msgs = "FAIL", [f"상주 데몬 다운(last exit {st})"]
                    else:
                        msgs.append(f"PID {pid}")
                elif st != "0":
                    if j.get("expect_nonzero"):
                        msgs.append(f"exit {st} (감지형 잡 — 정상 범주)")
                    else:
                        level, msgs = "FAIL", [f"last exit {st}"]
        if j.get("detect_artifact"):
            # 감지형 잡의 검출 결과를 exit 대신 산출물 counts로 노출(HIGH>0=WARN·사람검증).
            # skillscan HIGH=2가 3주간 FAIL 표시에 묻혀 미트리아지된 사례(2026-08-16 점검).
            dp = ex(j["detect_artifact"])
            try:
                cnt = json.load(open(dp, encoding="utf-8")).get("counts", {}) if os.path.exists(dp) else {}
                hi = int(cnt.get("HIGH", 0) or 0)
                md = int(cnt.get("MED", 0) or 0)
                if hi > 0:
                    if level == "OK":
                        level = "WARN"
                    msgs.append(f"⚠️ HIGH {hi}건 검출 — 사람검증 필요 (MED {md})")
                else:
                    msgs.append(f"검출 HIGH 0 / MED {md}")
            except (OSError, ValueError, TypeError) as e:
                if level == "OK":
                    level = "WARN"
                msgs.append(f"검출 산출물 판독 실패: {e}")
        if j.get("artifact"):
            p = ex(j["artifact"])
            if not os.path.exists(p):
                if level == "OK":
                    level = "WARN"
                msgs.append("산출물 없음")
            else:
                age = (NOW - datetime.datetime.fromtimestamp(os.path.getmtime(p))).total_seconds() / 86400
                if age > j.get("max_age_days", 9):
                    level = "FAIL"
                    msgs.append(f"산출물 {age:.1f}d 경과(허용 {j['max_age_days']}d)")
                else:
                    msgs.append(f"산출물 {age:.1f}d")
        rows.append((level, name, "; ".join(msgs) or "정상"))
    order = {"FAIL": 0, "WARN": 1, "OK": 2}
    rows.sort(key=lambda r: order[r[0]])
    return rows


def check_slots():
    """검증슬롯 기능핑 — 프로세스 생존이 아니라 실응답을 본다. 경고전용."""
    rows = []  # (level, name, msg)
    for s in CFG.get("slots", []):
        t0 = datetime.datetime.now()
        try:
            proc = subprocess.run(["/bin/sh", "-c", s["cmd"]],
                                  capture_output=True, text=True,
                                  timeout=s.get("timeout_s", 60))
            out = (proc.stdout or "") + (proc.stderr or "")
            tail = " ".join(out.split())[-120:]
            dur = (datetime.datetime.now() - t0).total_seconds()
            if proc.returncode != 0:
                rows.append(("FAIL", s["name"], f"exit {proc.returncode}: {tail}"))
            elif s.get("expect") and s["expect"] not in out:
                rows.append(("FAIL", s["name"], f"기대문자열 '{s['expect']}' 미검출: {tail}"))
            elif s.get("warn_if") and s["warn_if"] in out:
                rows.append(("WARN", s["name"], f"부분이상({dur:.0f}s): {tail}"))
            else:
                rows.append(("OK", s["name"], f"응답 정상 ({dur:.0f}s)"))
        except subprocess.TimeoutExpired:
            rows.append(("FAIL", s["name"], f"타임아웃 {s.get('timeout_s', 60)}s"))
        except Exception as e:
            rows.append(("FAIL", s["name"], f"실행오류: {e}"))
    order = {"FAIL": 0, "WARN": 1, "OK": 2}
    rows.sort(key=lambda r: order[r[0]])
    return rows


def check_shadows():
    rows = []  # (name, total, delta, note)
    for s in CFG["shadows"]:
        p = ex(s["path"])
        if not os.path.exists(p):
            rows.append((s["name"], 0, 0, "파일 없음"))
            continue
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        total = len(lines)
        prev = STATE["shadows"].get(s["name"], {}).get("lines")
        delta = (total - prev) if prev is not None else None
        note = ""
        if s.get("flag") == "g12_toolzero":
            new = lines[prev:] if prev is not None else lines
            n = 0
            for ln in new:
                try:
                    d = json.loads(ln)
                    if d.get("tool_count") == 0 and d.get("claims"):
                        n += 1
                except (json.JSONDecodeError, TypeError):
                    pass
            if n:
                note = f"⚠️ tool_count:0 완료주장 {n}건 — 검토 필요"
        STATE["shadows"][s["name"]] = {"lines": total}
        rows.append((s["name"], total, delta, note))
    return rows


def check_anchor():
    """앵커 무결성 — 검사기를 그대로 부른다. 판정 로직을 두 벌로 만들지 않는다."""
    if not os.path.exists(ANCHOR_CHECKER):
        return [("FAIL", "앵커 검사기", "파일 없음 — 앵커층이 설치되지 않았다")]
    try:
        r = subprocess.run(["/usr/bin/python3", "-E", "-S", ANCHOR_CHECKER, "--json"],  # A3 경화 2026-09-01
                           capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout)
    except Exception as e:
        return [("FAIL", "앵커 검사기", f"실행/파싱 실패: {type(e).__name__}: {e}")]

    rows = []
    crit = [f for f in d.get("findings", []) if f["severity"] == "critical"]
    warn = [f for f in d.get("findings", []) if f["severity"] != "critical"]
    for f in crit:
        rows.append(("FAIL", f["id"], f["msg"]))
    for f in warn:
        rows.append(("WARN", f["id"], f["msg"]))

    probe = d.get("probe") or {}
    if probe:
        n, blocked, over = probe.get("n_hooks", 0), probe.get("blocked", 0), probe.get("over_block", 0)
        lv = "OK" if blocked else "FAIL"
        msg = f"차단 훅 {n}개 중 {blocked}개가 막음"
        if over:
            lv, msg = "WARN", msg + f" · 과차단 {over}건"
        rows.append((lv, "능동 프로브", msg))
    if not rows:
        rows.append(("OK", "앵커 무결성", "이상 없음"))
    return rows


def check_drift():
    """기준선 드리프트 — ig.py 를 import 해 스냅샷만 비교한다.

    ig.py check 를 그대로 부르면 알림(osascript·ntfy)이 나간다. 여기서는 보기만
    하려는 것이라, 판정 함수 대신 스냅샷 비교만 재사용한다.
    """
    if not os.path.exists(IG_PY):
        return ("WARN", "기준선 감시기가 없다", [])
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ig", IG_PY)
        ig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ig)
        base = json.load(open(ig.BASELINE, encoding="utf-8"))["files"]
        now = ig.snapshot()
    except Exception as e:
        return ("FAIL", f"드리프트 조회 실패: {type(e).__name__}: {e}", [])

    changed = sorted(p for p in base if p in now and base[p] != now[p])
    removed = sorted(p for p in base if p not in now)
    added = sorted(p for p in now if p not in base)
    total = len(changed) + len(removed) + len(added)
    if total == 0:
        return ("OK", "드리프트 없음", [])
    paths = [("~", p) for p in changed] + [("-", p) for p in removed] + [("+", p) for p in added]
    return ("WARN", f"변경 {len(changed)} / 삭제 {len(removed)} / 추가 {len(added)}",
            [f"{t} {p.replace(ex('~'), '~')}" for t, p in paths])


def check_regression():
    """회귀 스모크 — 무겁다. 명시할 때만 돈다."""
    if not os.path.exists(REGRESSION):
        return ("WARN", "회귀 러너가 없다")
    try:
        r = subprocess.run(["/bin/bash", REGRESSION], capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return ("FAIL", "타임아웃 900s")
    except Exception as e:
        return ("FAIL", f"실행 실패: {type(e).__name__}")
    tail = " ".join((r.stdout or "").split())[-160:]
    if r.returncode == 0:
        return ("OK", tail or "통과")
    return ("FAIL", f"exit {r.returncode}: {tail}")


def check_queue():
    overdue, due_soon, backlog = [], [], []
    for q in CFG["queue"]:
        if q.get("done"):
            continue
        if q["due"]:
            d = datetime.date.fromisoformat(q["due"])
            if d < TODAY:
                overdue.append((q, (TODAY - d).days))
            elif (d - TODAY).days <= 7:
                due_soon.append((q, (d - TODAY).days))
        else:
            backlog.append(q)
    return overdue, due_soon, backlog


def main():
    jobs = check_jobs()
    slots = check_slots() if WANT_SLOTS else []
    shadows = check_shadows()
    overdue, due_soon, backlog = check_queue()
    anchor = check_anchor() if WANT_ANCHOR else []
    drift = check_drift() if WANT_ANCHOR else None
    regression = check_regression() if WANT_REGRESSION else None

    fails = [r for r in jobs if r[0] == "FAIL"]
    warns = [r for r in jobs if r[0] == "WARN"]
    slot_fails = [r for r in slots if r[0] == "FAIL"]
    slot_warns = [r for r in slots if r[0] == "WARN"]
    new_total = sum(d for _, _, d, _ in shadows if d)
    flags = [f"{n}: {note}" for n, _, _, note in shadows if note.startswith("⚠️")]

    L = [f"# harness-heartbeat {TODAY.isoformat()}", ""]
    L.append(f"## ① 주기잡 헬스 — FAIL {len(fails)} / WARN {len(warns)} / OK {len(jobs)-len(fails)-len(warns)}")
    L.append("")
    L.append("| 상태 | 잡 | 근거 |")
    L.append("|------|----|------|")
    ico = {"FAIL": "❌", "WARN": "⚠️", "OK": "✅"}
    for lv, name, msg in jobs:
        L.append(f"| {ico[lv]} {lv} | {name} | {msg} |")
    L.append("")
    if WANT_SLOTS:
        L.append(f"## ② 검증슬롯 헬스 — FAIL {len(slot_fails)} / WARN {len(slot_warns)} / OK {len(slots)-len(slot_fails)-len(slot_warns)}")
        L.append("")
        L.append("| 상태 | 슬롯 | 근거 |")
        L.append("|------|------|------|")
        for lv, name, msg in slots:
            L.append(f"| {ico[lv]} {lv} | {name} | {msg} |")
        L.append("")
    L.append(f"## ③ 섀도로그 델타 — 신규 {new_total}건")
    L.append("")
    L.append("| 로그 | 총건수 | +신규 | 비고 |")
    L.append("|------|-------|-------|------|")
    for n, t, d, note in shadows:
        dv = "기준선 설정" if d is None else f"+{d}" if d >= 0 else str(d)
        L.append(f"| {n} | {t} | {dv} | {note} |")
    L.append("")
    L.append("## ④ 판정 대기열")
    L.append("")
    for q, days in overdue:
        L.append(f"- 🔴 **OVERDUE +{days}d** [{q['id']}] {q['desc']} ({q['source']})")
    for q, days in due_soon:
        L.append(f"- 🟠 **D-{days}** [{q['id']}] {q['desc']} ({q['source']})")
    for q in backlog:
        L.append(f"- ⚪ 백로그 [{q['id']}] {q['desc']}")
    L.append("")

    anchor_fails = [r for r in anchor if r[0] == "FAIL"]
    if WANT_ANCHOR:
        L.append(f"## ⑤ 앵커 무결성 — FAIL {len(anchor_fails)}")
        L.append("")
        L.append("| 상태 | 항목 | 근거 |")
        L.append("|------|------|------|")
        for lv, name, msg in anchor:
            L.append(f"| {ico[lv]} {lv} | {name} | {msg} |")
        L.append("")
        dl, dmsg, dpaths = drift
        L.append(f"## ⑥ 기준선 드리프트 — {ico.get(dl, '')} {dmsg}")
        L.append("")
        for p in dpaths[:20]:
            L.append(f"- `{p}`")
        if len(dpaths) > 20:
            L.append(f"- … 외 {len(dpaths)-20}건")
        L.append("")
    else:
        drift = ("OK", "생략", [])

    if regression:
        rl, rmsg = regression
        L.append(f"## ⑦ 회귀 스모크 — {ico.get(rl, '')} {rl}")
        L.append("")
        L.append(f"```\n{rmsg}\n```")
        L.append("")

    parts = [f"잡 FAIL {len(fails)}"]
    if WANT_SLOTS:
        parts.append(f"슬롯 FAIL {len(slot_fails)}")
    parts.append(f"판정 due {len(overdue)+len(due_soon)}")
    parts.append(f"섀도신규 {new_total}건")
    if WANT_ANCHOR:
        parts.append(f"앵커 FAIL {len(anchor_fails)}")
        parts.append(f"드리프트 {drift[1]}")
    if regression:
        parts.append(f"회귀 {regression[0]}")
    if flags:
        parts.append(f"플래그 {len(flags)}")
    summary = " · ".join(parts)
    L.append(f"## 요약\n\n{summary}")

    body = "\n".join(L) + "\n"

    if NOW_MODE:
        # 읽기 전용 — 상태를 갱신하지도, 리포트를 남기지도, 알림을 보내지도 않는다.
        # 섀도 델타 기준선이 밀리면 다음 주간 점검이 '신규 0' 으로 거짓 보고한다.
        print(body)
        skipped = []
        if not WANT_SLOTS:
            skipped.append("검증슬롯 실핑(--slots)")
        if not WANT_REGRESSION:
            skipped.append("회귀 스모크(--regression)")
        if not WANT_ANCHOR:
            skipped.append("앵커 검사(--no-anchor 로 생략됨)")
        if skipped:
            print("생략: " + " · ".join(skipped))
        return 0

    rp = os.path.join(BASE, "reports", f"{TODAY.isoformat()}.md")
    open(rp, "w", encoding="utf-8").write(body)
    STATE["last_run"] = NOW.isoformat(timespec="seconds")
    json.dump(STATE, open(STATE_P, "w"), ensure_ascii=False, indent=1)

    print(f"[{STATE['last_run']}] {summary}\n리포트: {rp}")
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{summary}" with title "harness-heartbeat"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
