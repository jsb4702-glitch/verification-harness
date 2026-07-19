#!/usr/bin/env python3
"""하네스 변경 기계판정 — CRITERIA.md 수치기준(C1~C3)의 자동 적용.

history.jsonl에서 현재 CLAUDE.md 해시의 최신 기록(after)과
직전 다른 해시의 최신 기록(before)을 찾아 비교한다.
C4(골드셋 케이스)·C5(섀도승급)는 수동 확인 항목으로 표시만.

usage: change_verdict.py [--history PATH]
exit: 0=채택가능, 1=보류/관찰, 2=원복권고, 3=판정불가(기록부족)
"""
import argparse, hashlib, json, os, sys

HARNESS = os.path.expanduser("~/.claude/CLAUDE.md")
HIST = os.path.expanduser("~/harness-eval/history.jsonl")


def cur_hash():
    return hashlib.sha256(open(HARNESS, "rb").read()).hexdigest()[:12]


def rate_num(s):
    """'62%' -> 62.0, 'skip'/None -> None"""
    if not s or not str(s).rstrip("%").replace(".", "").isdigit():
        return None
    return float(str(s).rstrip("%"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=HIST)
    args = ap.parse_args()

    if not os.path.exists(HARNESS):
        print("🔴 CLAUDE.md 없음 — 판정불가")
        return 3
    h = cur_hash()
    chars = len(open(HARNESS, encoding="utf-8").read())

    entries = []
    if os.path.exists(args.history):
        for l in open(args.history, encoding="utf-8"):
            l = l.strip()
            if l:
                try:
                    entries.append(json.loads(l))
                except json.JSONDecodeError:
                    pass

    after = next((e for e in reversed(entries) if e.get("harness") == h), None)
    before = next((e for e in reversed(entries) if e.get("harness") != h), None)

    print(f"== 현재 하네스 {h} | {chars:,} chars ==")
    if not after:
        print("🔶 현재 해시의 회귀 기록 없음 — 먼저 ./run_regression.sh 실행 후 재판정")
        return 3
    if not before:
        print("🔶 비교 대상(다른 해시) 기록 없음 — 첫 기록이면 이게 baseline")
        return 3

    print(f"before: {before['harness']} @{before['ts']} lint={before.get('lint_rc')} smoke={before.get('smoke_rate')}")
    print(f"after : {after['harness']} @{after['ts']} lint={after.get('lint_rc')} smoke={after.get('smoke_rate')}")

    verdict = 0
    reasons = []

    # C1 구조무결 (경성)
    if after.get("lint_rc") == 2:
        reasons.append("C1 ❌ 구조 린트 실패 → 즉시 원복")
        verdict = 2
    else:
        reasons.append("C1 ✅ 구조 린트 통과")

    # C2 게이트발화
    b, a = rate_num(before.get("smoke_rate")), rate_num(after.get("smoke_rate"))
    if b is None or a is None:
        reasons.append("C2 ⚠️ 스모크 측정 누락(skip) — ollama 켜고 재실행 필요")
        verdict = max(verdict, 1)
    else:
        d = a - b
        if d <= -8:
            reasons.append(f"C2 ❌ 스모크 {b:.0f}%→{a:.0f}% ({d:+.0f}%p) — 재실행 1회로 재현 확인 후 원복")
            verdict = max(verdict, 2)
        elif d < 0:
            reasons.append(f"C2 🔶 스모크 {b:.0f}%→{a:.0f}% ({d:+.0f}%p) — 관찰(재실행 권장)")
            verdict = max(verdict, 1)
        else:
            reasons.append(f"C2 ✅ 스모크 {b:.0f}%→{a:.0f}% ({d:+.0f}%p)")

    # C3 토큰비용 — history에 크기 기록이 없어 현재값만 보고, 증감은 수동 대조
    reasons.append(f"C3 ℹ️ 현재 {chars:,} chars — 변경 전 스냅샷과 대조 (+1%↑면 상쇄이득 명시 필요)")

    # C4/C5 수동 게이트
    reasons.append("C4 ☐ 신규 규칙이면 골드셋 케이스 ≥1 추가했나? (g13_case.py / g13_ledger.jsonl 확인)")
    reasons.append("C5 ☐ 섀도 승급 판단이면 FP율·표본수 기준 대조")

    print()
    for r in reasons:
        print(" " + r)
    print()
    print(["🟢 채택 가능 (C4·C5 수동 확인 전제)",
           "🔶 보류/관찰 — 재실행 또는 측정 보강 후 재판정",
           "🔴 원복 권고 — C1 즉시 / C2는 재현 확인 후"][verdict])
    return verdict


if __name__ == "__main__":
    sys.exit(main())
