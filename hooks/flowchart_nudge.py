#!/usr/bin/env python3
"""
UserPromptSubmit 훅 — 흐름도 선행 넛지 (2026-07-21).

사용자 프롬프트가 작업형(구현/배선/수정/셋업 등 동사 포함)이면
"착수 전 진행흐름도 먼저" 리마인더를 additionalContext로 주입한다.
넛지 전용(비차단) — 판단은 모델 몫, 오탐 비용 = 리마인더 1줄.
누탐은 CLAUDE.md L5 [흐름도 선행] 규칙이 백스톱.

통과(주입 안 함):
  작업동사 없음 / 질문·조회형 단서 / "바로"·"그냥 해"·"생략" 명시 /
  흐름도 자체 언급(이미 인지) / 8자 미만 한마디
"""
import sys, json, re

_WORK = re.compile(
    r"구현|배선|만들어|만들자|수정해|고쳐|고치자|리팩|셋업|설치|추가해|붙여|"
    r"통합|자동화|마이그|빌드|배포|짜줘|짜자|작성해|돌려|실행해|적용해|바꿔|"
    r"개선해|최적화|스킬화|툴화|규칙화")
_SKIP = re.compile(
    r"흐름도|바로|그냥\s*해|생략|뭐냐|뭐야|뭔데|어때|왜\s|되나|될까|할까|맞나|"
    r"알려줘|설명해|찾아봐|조사|보여줘")


def main():
    try:
        p = json.load(sys.stdin)
    except Exception:
        return
    prompt = (p.get("prompt") or "").strip()
    if len(prompt) < 8:
        return
    if not _WORK.search(prompt) or _SKIP.search(prompt):
        return
    ctx = ("작업형 지시 감지 — 착수 전에 진행흐름도 1장을 먼저 보여줘라"
           "(위젯 가용 시 show_widget, 아니면 단계 리스트). "
           "재량이 큰 다단계 작업은 흐름도 후 사용자 확인을 기다리고, "
           "사용자가 명시한 단순 작업은 흐름도만 보이고 바로 진행. "
           "단순 조회·질문·한 파일 단발 수정은 흐름도 면제.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ctx}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
