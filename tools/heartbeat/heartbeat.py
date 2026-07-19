#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness-heartbeat — 주기잡 헬스 + 섀도로그 델타 + 판정대기열 주간 점검.

경고전용·자동수정 없음(사람게이트). 산출물:
  reports/YYYY-MM-DD.md + stdout 요약 + macOS 알림.
설계 제약: launchd 컨텍스트에서 돌므로 iCloud(~/Library/Mobile Documents) 경로 검사 금지(TCC EPERM).
"""
import json, os, subprocess, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
STATE_P = os.path.join(BASE, "state.json")
STATE = json.load(open(STATE_P)) if os.path.exists(STATE_P) else {"shadows": {}}
NOW = datetime.datetime.now()
TODAY = NOW.date()
ex = os.path.expanduser


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
    slots = check_slots()
    shadows = check_shadows()
    overdue, due_soon, backlog = check_queue()

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
    summary = f"잡 FAIL {len(fails)} · 슬롯 FAIL {len(slot_fails)} · 판정 due {len(overdue)+len(due_soon)} · 섀도신규 {new_total}건"
    if flags:
        summary += f" · 플래그 {len(flags)}"
    L.append(f"## 요약\n\n{summary}")

    rp = os.path.join(BASE, "reports", f"{TODAY.isoformat()}.md")
    open(rp, "w", encoding="utf-8").write("\n".join(L) + "\n")
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
