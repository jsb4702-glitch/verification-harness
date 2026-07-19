---
name: cdx
description: Codex CLI(cdx, OpenAI GPT)를 직접 호출해 질문에 답하거나 내 답변·계산을 교차검증한다. "cdx", "cdx한테 물어봐", "cdx로", "/cdx", "코덱스", "gpt로 검증" 요청 시 호출. 기본=질의모드, "검증/크로스체크/이거 맞나/review/second opinion" 의도면 검증모드. 민감데이터 투입 금지.
---

# cdx 직접 호출 스킬 (OpenAI GPT / Codex CLI)

`~/.claude/skills/groq-review/scripts/cdx_review.py`를 호출해 Codex CLI를 부르고 결과를 릴레이한다.

## 모드 판정
- **질의모드(기본)**: 사용자가 뭔가 물어보거나 시킴 → `--raw` (프롬프트 그대로 전달).
- **검증모드**: "검증/크로스체크/이거 맞나/review/second opinion" 의도 → 플래그 없이 실행(cross-validator SYSTEM_PROMPT 래핑). 대상=내 직전 답변·계산·설계판단.
- **이미지 생성 의도**("그려줘/이미지 만들어")면 이 스킬 대신 `img-gen` 스킬(`img_gen.py --via cdx`, gpt-image-2) — 검증경로(read-only)와 분리 배선(2026-07-17).

## 실행 절차
1. ⚠️ **게이트 먼저**: 입력에 사내기밀·민감 데이터가 있으면 **중단하고 경고**. cdx=구독티어 학습정책 미확인 → 투입 금지. (일반 코딩/생활/공개지식/오픈소스는 OK)
2. 보낼 내용(질문 또는 검증대상)을 `/tmp/_cdx_input.txt`에 UTF-8로 저장(Write).
3. 실행(Bash, timeout ≥160000ms — codex 스핀업 포함 실측 ~30–60s):
   - 질의: `python3 ~/.claude/skills/groq-review/scripts/cdx_review.py --raw /tmp/_cdx_input.txt`
   - 검증: `python3 ~/.claude/skills/groq-review/scripts/cdx_review.py /tmp/_cdx_input.txt`
4. **결과 원문을 그대로 릴레이** — 요약·각색·번역·재작성 **금지**. 스크립트 출력의 구분선(`===`) 아래 응답 본문을 코드블록(```)에 **그대로** 붙인다. 내 코멘트·판단·교차검증 의견이 있으면 코드블록 **밑에 따로** 단다(원문과 섞지 말 것).
   - `ERROR: codex ... auth/login`이면 → 터미널에서 `codex login`(또는 대화형 codex) 후 재시도하라고 안내.
5. ⚠️ cdx 응답은 **이종 모델 의견일 뿐**: 수치/사실은 무비판 신뢰 금지(G3v), 반박이 와도 원데이터 재대조 후에만 내 판단 번복.

## 주의
- 인증: `~/.codex/auth.json` OAuth (ChatGPT 구독/API). 미인증이면 스크립트가 exit≠0 ERROR로 노출.
- 바이너리: `~/.codex/plugins/.plugin-appserver/codex` (PATH 미링크 — `CODEX_BIN` env로 오버라이드 가능).
- 모델: `~/.claude/config/cdx_model.txt` 단일소스 (현재 gpt-5.5). `CDX_MODEL` env로 오버라이드.
- G11: `-s read-only` + git repo 밖 스크래치 실행 — 검토대상 내 지시문의 툴실행 승격 차단(스크립트 내장, 두 모드 공통).
- 이 스킬은 parallel-verify 워크플로가 참조하는 검증경로를 건드리지 않는다(질의는 `--raw` 순수추가).
