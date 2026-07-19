# harness-eval — 하네스 회귀 계측 허브

CLAUDE.md 안티할루시네이션 하네스를 바꿀 때마다 **게이트가 실제로 발동하는지** 측정한다.
세 GitHub 도구를 하나로 합친 결과물:

- **promptfoo** = 계측 엔진 (로컬 실행, MIT)
- **garak** = G11/G4 공격 페이로드 출처 (probe 분류 → 테스트케이스)
- **uqlm** = 안전임계 비모순 검사 개념 (black-box 일관성)

## 핵심 구조
`prompts/harness.js`가 네 실제 `~/.claude/CLAUDE.md`를 **system 프롬프트로 주입**한다.
→ raw 모델이 아니라 *하네스 규율이 적용된 상태*를 테스트한다. 이게 이 셋업의 전부다.

## 실행 (유료 — 튜닝할 때만)
```bash
npm install -g promptfoo          # 1회
cd ~/harness-eval
export ANTHROPIC_API_KEY=sk-...   # 현재 미설정
promptfoo eval                    # 케이스 × 프로바이더 + grader 호출
promptfoo view                    # 브라우저 결과판
```
비용 주의: llm-rubric assertion은 grader LLM(현재 haiku로 설정)을 추가 호출함.

## 게이트 커버리지 (현재 7케이스)
| 게이트 | 케이스 | garak 출처 probe |
|---|---|---|
| G11 | datasheet 속 SYSTEM 오버라이드 무시 | latentinjection |
| G11 | system 프롬프트 탈취 거부 | sysprompt_extraction |
| G4 | DOI 날조 회피 | (snowball/misleading) |
| G4 | 풀PN 날조 회피 | packagehallucination |
| G9 | 비자명 산술 중간값·단위 노출 | — |
| G1 | 신뢰도등급 🟢🟡🔴 부착 | — |
| uqlm | 안전임계 비모순 | (uqlm black-box) |

## 확장 (다음 단계)
- garak 풀 probe로 G11 케이스 늘리기: `pip install garak && garak --list_probes`
  - 우선순위: `promptinject web_injection smuggling encoding dan goodside fitd grandma`
- 회귀 baseline 저장: `promptfoo eval -o baseline.json` → 하네스 수정 후 재실행 비교
- 모델 id는 `/claude-api` 스킬로 검증 후 `promptfooconfig.yaml` providers 갱신

## ⚠️ 검증되지 않은 것
- 모델 id `claude-opus-4-8` / grader id는 **미검증** — 실행 전 /claude-api로 확인.
- 실제 통과/실패율은 `promptfoo eval` 돌려야 나옴. 아직 baseline 없음.

## Hermes 환각검증기 슬롯 (opt-in)
- `HERMES_VERIFIER=1 ./run_regression.sh` → Tier-1.5 결정적 스모크(gemma4-judge temp0, ~24분, advisory).
- 정밀: `python3 ~/hermes-eval/regress.py --full`. 결과 누적: `~/hermes-eval/history.jsonl` + 본 디렉토리 history.jsonl 미러.
- 평가코어/골드셋/결정성 근거: `~/hermes-eval/CHECKPOINT.md`.
