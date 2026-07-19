#!/usr/bin/env python3
# SessionStart hook — Fable 5 세션 감지기.
# 목적: 사용자가 Fable 5를 골라 새 세션을 열면, 준비된 3way 하네스 비교
#       (Fable5 / Opus4.8 / Sonnet5)를 돌리라고 어시스턴트에게 상기시킨다.
# 특성: 순수 로컬·네트워크 0·의존성 0. 무장(sentinel) 있을 때만, Fable일 때만 발화.
#       그 외 모든 경우 완전 침묵(다른 세션 노이즈 0).
import json, sys, os

SENTINEL = os.path.expanduser("~/harness-eval/.fable_watch")

def emit(ctx):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ctx,
        }
    }))

def main():
    # 무장 안 돼 있으면 아무것도 안 함.
    if not os.path.exists(SENTINEL):
        return
    raw = ""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    # model 필드(널세이프) + 원문 폴백 이중 감지.
    model = (data.get("model") or "")
    is_fable = ("fable" in str(model).lower()) or ("fable" in raw.lower())
    if not is_fable:
        return

    emit(
        "🟣 Fable 5 세션 감지됨. 사용자가 사전요청한 작업: 하네스 게이트 3way 비교"
        "(Fable5 / Opus4.8 / Sonnet5)를 실행할 준비가 돼 있음.\n"
        "→ 실행: `cd ~/harness-eval && export ANTHROPIC_API_KEY=sk-... && ./run_3way.sh`\n"
        "  (promptfoo가 3모델을 API로 직접 때려 동일 골든셋 대조 → 웹 매트릭스)\n"
        "사용자에게 지금 돌릴지 한 줄로 물어보고, OK면 실행해라. 3way 완료되면 감시는 자동 해제됨."
    )

if __name__ == "__main__":
    main()
