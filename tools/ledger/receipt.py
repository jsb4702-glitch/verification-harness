#!/usr/bin/env python3
"""
Tool Receipt — 실행 확인 게이트의 강제형. 불변원장 형제 모듈.

착안: arXiv 2603.10060 "Tool Receipts, Not Zero-Knowledge Proofs:
Practical Hallucination Detection for AI Agents" (Abhinaba Basu, 2026-03-09).
에이전트가 툴을 안 돌리고 "돌렸다 / 통과했다 / 완료"라고 주장하는 표면을 막는다.

원 논문은 HMAC 서명 receipt + 실시간 대조. 여기선 최소형 세 가지만 가져온다.
  ① 종료코드를 주장이 아니라 관측으로 확보 (run 이 직접 실행하고 수집)
  ② 산출물 sha256 을 발급 시점에 박고, 대조 시점에 재해시
  ③ 레코드 전체를 HMAC-SHA256 으로 서명 — 사후 편집 시 서명이 깨진다

위조를 막는 실제 근거는 ②다. 존재하지 않는 파일은 해시가 안 나온다.
서명은 이미 발급된 receipt의 사후 조작만 막는다. 둘은 다른 공격을 본다.

ledger.py 는 root 소유 555 + 잠금파일 등재라 편집 불가. 그래서 형제 파일로 둔다.
스토어는 공유하되(같은 store/ 디렉터리) 계측 파일은 분리한다 — ledger stats 의
스킵율 분모를 오염시키지 않기 위해서다.

레코드: {ts, kind:"receipt", key, cmd, exit, artifacts:[{path,sha256,size}], note, sig}

사용:
  receipt.py run    --key "원장 회귀시험" --artifact out.json -- bash test_ledger.sh
  receipt.py attest --key "원장 회귀시험" --require-exit 0
  receipt.py add    --key "수기적재" --cmd "pytest" --exit 0 --artifact report.xml
  receipt.py list  /  stats  /  clear

대조 실패 사유 5종:
  NO_RECEIPT  receipt 자체가 없다 (= 안 돌렸다)
  BAD_SIG     receipt가 사후 편집됐다
  EXIT        종료코드가 요구치와 다르다
  ARTIFACT    산출물이 사라졌거나 해시가 바뀌었다
  STALE       receipt가 신선도 상한을 넘겼다

주의: 선행 대시(-) 값은 argparse 오인 방지 위해 `=`형 필수 (--max-age=-1 등).
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time

STORE_DIR = os.environ.get("RECEIPT_STORE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "store")
RECEIPTS = os.path.join(STORE_DIR, "receipts.jsonl")
METRICS = os.path.join(STORE_DIR, "receipts.metrics.jsonl")
KEYFILE = os.path.join(STORE_DIR, ".receipt_key")
LOGDIR = os.path.join(STORE_DIR, "logs")
DEFAULT_MAX_AGE = 3600.0  # 대조 기본 신선도 상한(초). 0 = 무제한


def _norm_key(k: str) -> str:
    """key 정규화 — ledger.py 와 동일 규칙이라 두 도구의 key 가 정렬된다."""
    k = k.strip().lower()
    k = re.sub(r"\s+", " ", k)
    k = re.sub(r"[^\w가-힣 .%/+-]", "", k)
    return k


def _sigkey() -> bytes:
    """서명키 로드 — 없으면 32바이트 난수로 생성하고 0600 고정."""
    os.makedirs(STORE_DIR, exist_ok=True)
    if not os.path.exists(KEYFILE):
        fd = os.open(KEYFILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32))
    else:
        os.chmod(KEYFILE, 0o600)  # 권한 드리프트 교정
    with open(KEYFILE, "rb") as f:
        return f.read()


def _canon(rec: dict) -> bytes:
    """서명 대상 정규화 — sig 필드 제외, 키 정렬, 공백 제거."""
    body = {k: v for k, v in rec.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _sign(rec: dict) -> str:
    return hmac.new(_sigkey(), _canon(rec), hashlib.sha256).hexdigest()


def _sha256_file(path: str):
    """파일 sha256 + 크기. 파일이 아니면 None."""
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return {"sha256": h.hexdigest(), "size": size}


def _snapshot(paths):
    """산출물 목록 → [{path, sha256, size}]. 미존재는 sha256=None 으로 박제."""
    out = []
    for p in paths or []:
        ap = os.path.abspath(os.path.expanduser(p))
        st = _sha256_file(ap)
        out.append({"path": ap,
                    "sha256": st["sha256"] if st else None,
                    "size": st["size"] if st else None})
    return out


def _metric(event: str, key: str):
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), "event": event, "key": key},
                           ensure_ascii=False) + "\n")


def _write_receipt(key, cmd, exit_code, artifacts, note=""):
    rec = {
        "ts": round(time.time(), 3),
        "kind": "receipt",
        "key": _norm_key(key),
        "cmd": cmd,
        "exit": exit_code,
        "artifacts": artifacts,
        "note": note or "",
    }
    rec["sig"] = _sign(rec)
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(RECEIPTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _load_receipts():
    """[레코드…], {key: 최신 receipt}. append-only 라 뒤가 최신."""
    recs, idx = [], {}
    if not os.path.exists(RECEIPTS):
        return recs, idx
    with open(RECEIPTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") != "receipt" or "key" not in r:
                continue
            recs.append(r)
            idx[r["key"]] = r
    return recs, idx


def cmd_run(a):
    """툴을 직접 실행하고 종료코드를 관측해 receipt 발급.

    종료코드를 인자로 안 받는 게 핵심이다. 주장이 아니라 관측이다.
    stdout/stderr 는 로그 파일로 떨어뜨려 자동 산출물로 박는다.
    """
    argv = list(a.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("실행할 명령이 없다. 사용: receipt.py run --key K -- <명령>", file=sys.stderr)
        return 2

    os.makedirs(LOGDIR, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", _norm_key(a.key))[:60] or "run"
    logpath = os.path.join(LOGDIR, f"{safe}-{int(time.time() * 1000)}.log")

    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=(a.timeout or None))
        out, err, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        def _dec(x):
            if x is None:
                return ""
            return x if isinstance(x, str) else x.decode("utf-8", "replace")
        out, err = _dec(e.stdout), _dec(e.stderr)
        err += f"\n[receipt] 타임아웃 {a.timeout}s 초과"
        code = 124
    except OSError as e:  # FileNotFoundError·PermissionError 포함
        out, err, code = "", f"[receipt] 실행 실패: {e}", 127

    with open(logpath, "w", encoding="utf-8") as f:
        f.write(f"$ {' '.join(argv)}\n--- stdout ---\n{out}\n"
                f"--- stderr ---\n{err}\n--- exit={code} ---\n")

    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)

    arts = _snapshot(list(a.artifact or []) + [logpath])
    rec = _write_receipt(a.key, " ".join(argv), code, arts, a.note)
    _metric("issue_run", rec["key"])
    missing = [x["path"] for x in arts if x["sha256"] is None]
    print(f"\n🧾 receipt 발급 [{rec['key']}] exit={code} "
          f"산출물={len(arts)}개 sig={rec['sig'][:12]}…")
    if missing:
        print(f"   ⚠️ 미존재 산출물 {len(missing)}건: " + ", ".join(missing))
    return code


def cmd_add(a):
    """이미 돈 실행을 수기 적재. 종료코드가 관측이 아니라 주장이라 run 보다 약하다."""
    arts = _snapshot(a.artifact)
    rec = _write_receipt(a.key, a.cmd, a.exit, arts, a.note)
    _metric("issue_manual", rec["key"])
    print(f"🧾 receipt 적재(수기) [{rec['key']}] exit={a.exit} "
          f"산출물={len(arts)}개 sig={rec['sig'][:12]}…")
    print("   ⚠️ 종료코드가 관측이 아니라 주장이다. 가능하면 run 을 써라.")
    missing = [x["path"] for x in arts if x["sha256"] is None]
    if missing:
        print(f"   ⚠️ 미존재 산출물 {len(missing)}건: " + ", ".join(missing))
    return 0


def cmd_attest(a):
    """'돌렸다 / 통과했다' 주장을 receipt와 대조. 뒷받침 없으면 exit 3."""
    _, idx = _load_receipts()
    key = _norm_key(a.key)
    rec = idx.get(key)
    if rec is None:
        _metric("attest_no_receipt", key)
        print(f"NO_RECEIPT 🔴 receipt 없음 [{key}] — 실행 주장 뒷받침 불가", file=sys.stderr)
        return 3

    fails = []
    if not hmac.compare_digest(str(rec.get("sig", "")), _sign(rec)):
        fails.append("BAD_SIG receipt 서명 불일치 — 사후 편집 의심")

    age = time.time() - rec.get("ts", 0)
    max_age = DEFAULT_MAX_AGE if a.max_age is None else a.max_age
    if max_age and age > max_age:
        fails.append(f"STALE receipt 경과 {age:.0f}s > 상한 {max_age:.0f}s")

    if a.require_exit is not None and rec.get("exit") != a.require_exit:
        fails.append(f"EXIT 종료코드 {rec.get('exit')} ≠ 요구 {a.require_exit}")

    drift = []
    for art in rec.get("artifacts", []):
        now = _sha256_file(art["path"])
        if art["sha256"] is None:
            if now is not None:
                drift.append(f"{art['path']} (발급시 미존재 → 현재 존재)")
            continue
        if now is None:
            drift.append(f"{art['path']} (사라짐)")
        elif now["sha256"] != art["sha256"]:
            drift.append(f"{art['path']} (해시 상이)")
    if drift:
        fails.append(f"ARTIFACT 산출물 불일치 {len(drift)}건: " + "; ".join(drift))

    if fails:
        _metric("attest_fail", key)
        print(f"ATTEST_FAIL 🔴 [{key}] cmd={rec.get('cmd')}", file=sys.stderr)
        for r in fails:
            print(f"   - {r}", file=sys.stderr)
        return 3

    _metric("attest_pass", key)
    print(f"ATTEST_PASS ✅ [{key}] exit={rec.get('exit')} 경과={age:.0f}s "
          f"산출물={len(rec.get('artifacts', []))}개 일치 | cmd={rec.get('cmd')}")
    return 0


def cmd_list(a):
    recs, idx = _load_receipts()
    if not recs:
        print("receipt 없음")
        return 0
    print(f"=== receipt {len(recs)}건 / 고유 key {len(idx)}개 ===")
    for k, r in sorted(idx.items(), key=lambda kv: -kv[1].get("ts", 0)):
        age = time.time() - r.get("ts", 0)
        sig_ok = "sig✅" if hmac.compare_digest(str(r.get("sig", "")), _sign(r)) else "sig🔴"
        print(f"[{k}] exit={r.get('exit')} 산출물={len(r.get('artifacts', []))} "
              f"경과={age:.0f}s {sig_ok} | {r.get('cmd')}")
    return 0


def cmd_stats(a):
    """loop-health: 발급·대조 건수, 대조 실패율, 서명 무결성."""
    recs, idx = _load_receipts()
    events = []
    if os.path.exists(METRICS):
        with open(METRICS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not recs and not events:
        print("receipt 원장 비어있음")
        return 0

    print("=== Tool Receipt loop-health ===")
    if recs:
        bad = sum(1 for r in recs
                  if not hmac.compare_digest(str(r.get("sig", "")), _sign(r)))
        nonzero = sum(1 for r in recs if r.get("exit") != 0)
        print(f"발급 receipt: {len(recs)} | 고유 key: {len(idx)}")
        print(f"서명 불일치: {bad}  ← 0 이 아니면 사후 편집 의심")
        print(f"비정상 종료(exit≠0): {nonzero}")
    if events:
        ec = {}
        for e in events:
            ec[e["event"]] = ec.get(e["event"], 0) + 1
        att = sum(v for k, v in ec.items() if k.startswith("attest"))
        print("이벤트: " + " ".join(f"{k}={v}" for k, v in sorted(ec.items())))
        if att:
            fail = ec.get("attest_fail", 0) + ec.get("attest_no_receipt", 0)
            print(f"대조 실패율: {fail / att * 100:.1f}%  ({fail}/{att})"
                  f"  ← 높으면 실행 없는 완료 주장이 잦다는 뜻")
    return 0


def cmd_clear(a):
    removed = []
    for p in (RECEIPTS, METRICS):
        if os.path.exists(p):
            os.remove(p)
            removed.append(os.path.basename(p))
    if os.path.isdir(LOGDIR):
        for fn in os.listdir(LOGDIR):
            os.remove(os.path.join(LOGDIR, fn))
        removed.append("logs/*")
    # 서명키는 남긴다 — 지우면 과거 receipt이 전부 BAD_SIG 로 뜬다
    print("receipt 스토어 비움: " + (", ".join(removed) if removed else "(비어있었음)"))
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Tool Receipt — 실행 확인 게이트 강제형 (불변원장 형제 모듈)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="명령을 직접 실행하고 종료코드를 관측해 receipt 발급")
    sp.add_argument("--key", required=True)
    sp.add_argument("--artifact", action="append", default=[],
                    help="산출물 경로(반복 가능). 실행 로그는 자동 추가된다")
    sp.add_argument("--note", default="")
    sp.add_argument("--timeout", type=float, default=None, help="초 단위 상한")
    sp.add_argument("argv", nargs=argparse.REMAINDER,
                    help="-- 뒤에 실행할 명령")

    sp = sub.add_parser("add", help="이미 돈 실행을 수기 적재(약함)")
    sp.add_argument("--key", required=True)
    sp.add_argument("--cmd", required=True)
    sp.add_argument("--exit", type=int, required=True)
    sp.add_argument("--artifact", action="append", default=[])
    sp.add_argument("--note", default="")

    sp = sub.add_parser("attest", help="실행 주장을 receipt와 대조")
    sp.add_argument("--key", required=True)
    sp.add_argument("--require-exit", type=int, default=None,
                    help="요구 종료코드. 통과 주장이면 보통 0")
    sp.add_argument("--max-age", type=float, default=None,
                    help=f"신선도 상한(초). 기본 {DEFAULT_MAX_AGE:.0f}, 0=무제한")

    sub.add_parser("list", help="receipt 목록")
    sub.add_parser("stats", help="발급·대조 계측")
    sub.add_parser("clear", help="receipt·로그 비움(서명키는 보존)")

    a = p.parse_args()
    return {"run": cmd_run, "add": cmd_add, "attest": cmd_attest,
            "list": cmd_list, "stats": cmd_stats, "clear": cmd_clear}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
