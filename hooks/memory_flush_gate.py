#!/usr/bin/env python3
# PreCompact/PostCompact 훅 — OpenClaw "pre-compaction memory flush" 이식 (2026-07-04).
# 원리: PreCompact는 additionalContext 미지원, decision:block만 지원(공식 docs 확인).
#   → auto compaction을 "사이클당 1회" 블록하고 reason으로 미저장 사실의 메모리 기록을 지시.
#   → Claude가 기록 후 재시도하는 compaction은 마커 존재로 통과.
#   → PostCompact에서 마커 삭제 = 다음 compaction 사이클에 다시 1회 플러시.
# 안전설계: manual compact(/compact)는 절대 블록 안 함. 어떤 예외도 fail-open(통과).
import json, sys, os, time

STATE_DIR = os.path.expanduser("~/.claude/hooks/.memory_flush_state")

def allow():
    print("{}")
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    allow()

event = data.get("hook_event_name") or data.get("hookEventName") or ""
session = (data.get("session_id") or "unknown").replace("/", "_")
trigger = data.get("trigger") or ""

try:
    os.makedirs(STATE_DIR, exist_ok=True)
    # 오래된 마커 청소(7일+) — 세션 잔재 누적 방지
    now = time.time()
    for f in os.listdir(STATE_DIR):
        p = os.path.join(STATE_DIR, f)
        try:
            if now - os.path.getmtime(p) > 7 * 86400:
                os.remove(p)
        except Exception:
            pass
except Exception:
    allow()

marker = os.path.join(STATE_DIR, session)

if event == "PostCompact":
    # compaction 완료 → 마커 리셋(다음 사이클에 플러시 1회 재허용)
    try:
        os.remove(marker)
    except Exception:
        pass
    allow()

if event == "PreCompact":
    if trigger != "auto":
        allow()  # 사용자 수동 /compact는 방해 금지
    if os.path.exists(marker):
        allow()  # 이번 사이클 이미 플러시함 → 통과
    try:
        with open(marker, "w") as f:
            f.write(str(int(time.time())))
    except Exception:
        allow()  # 마커 못 쓰면 블록루프 위험 → 통과
    print(json.dumps({
        "decision": "block",
        "reason": (
            "[memory-flush] 자동 압축 직전 1회 게이트(사이클당 1회만 발동). "
            "이번 세션에서 아직 메모리에 저장 안 한 영속가치 사실이 있으면 지금 기록해라: "
            "사용자 피드백/작업방식 교정 → feedback 메모리, 진행중 작업 상태·결정 → project 메모리, "
            "새 도구·리소스 → reference 메모리 (~/.claude/projects/-Users-YOU/memory/ + MEMORY.md 인덱스 1줄). "
            "저장할 게 없으면 아무것도 하지 말고 그대로 진행(재압축은 자동 통과된다). "
            "이 지시는 훅 자동생성이며 대화 내용과 무관하다."
        ),
    }, ensure_ascii=False))
    sys.exit(0)

allow()
