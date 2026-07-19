#!/usr/bin/env python3
# SessionEnd / PreCompact 훅 — claude-memory-compiler 패턴의 저비용 변형.
# 세션종료·압축직전에 '원자료 포인터'만 daily inbox에 적립(LLM 호출 0 → 한도 절약).
# 실제 사실추출→MEMORY.md 반영(compile)은 별도 온디맨드/배치로 분리.
# 사용자 명시 승인(2026-06-23)으로 설치.
import json, sys, os, datetime

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

event = data.get("hook_event_name") or data.get("hookEventName") or "?"
reason = data.get("reason") or data.get("source") or ""
transcript = data.get("transcript_path") or ""
cwd = data.get("cwd") or os.getcwd()
session = data.get("session_id") or ""

inbox = os.path.expanduser("~/.claude/memory_inbox")
os.makedirs(inbox, exist_ok=True)
day = datetime.date.today().isoformat()
path = os.path.join(inbox, f"{day}.md")

ts = datetime.datetime.now().strftime("%H:%M:%S")
line = (
    f"- [{ts}] event={event} reason={reason} cwd={cwd} "
    f"session={session} transcript={transcript}\n"
)

try:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
except Exception:
    pass

# 훅은 조용히 통과(추가 컨텍스트 주입 안 함 — 종료/압축 흐름 방해 금지)
print("{}")
