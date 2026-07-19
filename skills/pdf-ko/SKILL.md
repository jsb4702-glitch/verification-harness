---
name: pdf-ko
description: 영문 PDF를 한글로 in-place 치환(레이아웃 그대로 보존)한다. pdf2zh-next(BabelDOC)로 텍스트 블록만 번역해 원위치 재조판 — 표·수식·그림·인용·페이지레이아웃 유지, 한글 폰트 임베딩. 트리거: "이 PDF 한글로 번역", "영문 pdf 한글 치환", "논문/규격서 번역해줘(PDF)", "pdf 한국어로", "/pdf-ko". mono(한글전용)/dual(영한대역) 출력. 엔진: Claude Sonnet 5(메인·고품질·클라우드) 또는 로컬 gemma4(민감·오프라인). 입력이 PDF이고 한글 번역 의도일 때 사용.
---

# pdf-ko — 영문 PDF → 한글 in-place 치환

레이아웃을 유지한 채 영문 텍스트를 한글로 갈아끼운다. 엔진은 `pdf2zh-next`(BabelDOC, EMNLP 2025 Demo 계열)를 격리 venv(`~/.local/share/pdf-ko/venv`, `pdf2zh-next==2.9.0` 핀)에서 호출.

## ⛔ 실행 전 필수: 민감도 분류 (수출통제 게이트)
**Claude 엔진은 클라우드 전송이다.** 기밀 규격서·통제기술자료(수출통제 규정)를 Claude 엔진으로 돌리면 유출이다.

착수 전 반드시 문서 성격을 판정하라. **애매하면 사용자에게 물어라 (기본=민감측=로컬).**
- **공개/비통제** (공개논문·데이터시트·오픈규격 등) → `--public` → Claude(Sonnet 5)
- **민감/미지 출처** → `--sensitive` → 로컬 gemma4 강제 (오프라인, 클라우드 안 씀)

`--public`/`--sensitive` 둘 다 없으면 스크립트가 **거부**한다(오분류 방지). 자동 추측 금지.

## 사용법
```bash
PY=~/.local/share/pdf-ko/venv/bin/python
SK=~/.claude/skills/pdf-ko/scripts/pdf_ko.py

# 공개문서, 전체, 영한대역+한글전용 둘 다 (메인 엔진=Claude Sonnet 5)
"$PY" "$SK" "/path/to/paper.pdf" --public

# 민감 문서 → 로컬 gemma4 강제 (오프라인)
"$PY" "$SK" "/path/to/spec.pdf" --sensitive

# 페이지 제한 + 한글전용만
"$PY" "$SK" "/path/to/doc.pdf" --public --pages 1-10 --out mono
```

### 플래그
| 플래그 | 기본 | 설명 |
|---|---|---|
| `--public` / `--sensitive` | (없음=거부) | 민감도. 게이트 필수 |
| `--engine auto\|claude\|gemma` | auto | auto=민감도로 결정. claude는 --public 필수 |
| `--pages "A-B"` | 전체 | 예 `1-3` |
| `--out mono\|dual\|both` | both | mono=한글전용, dual=영한대역 |
| `--model` | `claude-sonnet-5` | Claude 엔진 모델 (품질↑ `claude-opus-4-8`, 저렴 `claude-haiku-4-5-20251001`) |
| `--outdir` | `<입력>_ko/` | 출력 폴더 |

출력: `<name>.no_watermark.ko.mono.pdf`, `...ko.dual.pdf`. 실행 후 자동 검증(페이지수·두부(□)0·오염0·한글밀도).

## 엔진 실측 (3페이지 학술논문 기준)
| 엔진 | 시간/3p | 품질 | 클라우드 | 비용 |
|---|---|---|---|---|
| **Claude Sonnet 5** (메인) | ~78s (8-병렬) | 최상 | ⚠️ 구독 | 구독 |
| 로컬 gemma4 | ~302s | 양호 | ❌ 오프라인 | $0 |

Claude 엔진은 `claude -p --max-turns 1 --disallowedTools <전체>`로 호출 → **G11: 툴 전부 차단**이라 문서 내 인젝션이 툴실행으로 승격 불가. 번역출력 오염(페르소나/게이트) 없음(실측 CLEAN).

## 대량문서 주의
Claude/gemma 모두 페이지당 여러 LLM 콜. 수십 페이지면 시간 소요(Claude는 병렬로 완화). 먼저 `--pages`로 일부만 시험 권장.

## 공급망 메모 (INTAKE)
`pdf2zh-next`는 대형 PyPI 패키지라 전체 정독 불가 → 완화책: **격리 venv + 버전핀(2.9.0) + 이 스킬 래퍼만 skillscan 통과 + LuLu egress 런타임 게이팅**. 업스트림 잔여리스크 있음(대형 OSS 불가피). 자작 스크립트(`scripts/`)는 정적검증 대상.
```
