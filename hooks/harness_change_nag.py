#!/usr/bin/env python3
"""PostToolUse(Edit|Write) 훅 — ~/.claude/CLAUDE.md 또는 workflows/*.js 가 수정되면
회귀 스모크 미실행 상태임을 클로드에게 1줄 상기. (실행 자체는 안 함 — 비차단)
"""
import json, sys, os

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

fp = (data.get("tool_input", {}) or {}).get("file_path", "") or ""
home = os.path.expanduser("~")
targets = (
    fp == os.path.join(home, ".claude", "CLAUDE.md")
    or "/.claude/workflows/" in fp and fp.endswith(".js")
)
if not targets:
    sys.exit(0)

msg = ("하네스 파일이 수정됨. 변경의 비용대비실익 판정을 위해 회귀 스모크를 돌려라: "
       "`bash ~/harness-eval/run_regression.sh` (무료·로컬). "
       "회귀(exit 2) 나오면 유료 API eval로 확정.")
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": msg}}))
sys.exit(0)
