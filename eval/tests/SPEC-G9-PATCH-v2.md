# G9 훅 패치 명세서 — g9_arith_enforce.py v2

| 항목 | 내용 |
|---|---|
| 문서 ID | SPEC-G9-PATCH-v2 |
| 작성일 | 2026-07-03 |
| 적용 대상 | Anti-Hallucination Harness v5.6.5-core / `hooks/g9_arith_enforce.py` |
| 산출물 | `g9_arith_enforce_v2.py` (드롭인 교체), `test_g9_regression.py` (회귀 25종) |
| 검증 상태 | ✅ 본 명세의 모든 코드·정규식·병합스니펫은 **작성 세션에서 실제 실행 검증 완료** (UNIT 20/20 + E2E 5/5 PASS, exit 0) 🟢 |
| 훅 스펙 근거 | 🟢 Claude Code 공식 훅 문서 (code.claude.com/docs/en/hooks) — Stop `decision:block`+exit 0 JSON 처리, `stop_hook_active` 재진입 플래그, SessionStart `source` 4종(startup/resume/clear/compact), stdout 10,000자 상한. 실조회 2026-07-03 |

**BLUF: ⚠️ 조건부 → ✅ 배포가능.** 결함 4종(D1a·D1b·D2·D3b) 패치 + 설치결함 1종(I1) 교정 + 검증절차 1종(I2) 신설. 회귀 25종 전건 통과 확인 후 설치할 것.

---

## 1. 결함–패치 매핑

| ID | 결함 (원판 실측) | 패치 | 유형 | 회귀 케이스 |
|---|---|---|---|---|
| D1a | 과학표기 `23.6×10⁻⁶` 를 곱셈으로 오탐 → 헛block | `_SCI` 스크럽 신설 | 오탐 제거 | R03, R06, R11 |
| D1b | 해상도 `1920×1080`·치수 `100×100mm` 오탐 → 헛block | `_DIM` 스크럽 신설 + ×곱셈 정책 변경(§2.2) | 오탐 제거 | R04, R05, R12, R13, R14, R15 |
| D2 | 손계산을 ``` 코드펜스에 넣으면 검출 회피 | `strip_codeblocks` 산술스캔 경로에서 제거 | 회피 차단 | R02 |
| D3b | `√(σM²+3τM²)` 괄호형 √ 미검출 | `_ARITH` √ 패턴 `√\s*\d` → `√\s*[\d(]` | 커버리지 확장 | R17, R19 |
| I1 | INSTALL.md 산문("병합")과 명령(`cp` 덮어쓰기) 불일치 → 기존 settings 소실 | 병합 스크립트로 교체 (§3.1) | 설치 안전 | 병합검증 4-assert |
| I2 | VSCode 확장의 `source:"compact"` 오보고 가능성 미검증 → reinject 무음 no-op 리스크 🟡 | 설치 후 1회 검증절차 신설 (§3.2) | 설치 검증 | 수동 1회 |

**패치 제외(의도적 보류):** D3(기호식 나눗셈 `FA/(1-Φ)` 미검출)은 숫자 계산이 아닌 수식 표기라 차단 대상 아님으로 **정책 확정** — R08이 PASS를 회귀로 고정. I3(g12 `if tools: return` 관련성 미매칭)·I4(동일모델 자기점검 한계)는 섀도/[별도 셋업] 설계 의도대로 유지.

---

## 2. 패치 상세 명세

### 2.1 검출기 구조 변경 (v2)

원판의 인라인 검출 로직을 순수함수 `has_unverified_arith(answer) -> bool` 로 추출 — **회귀테스트가 훅 파일을 import해 직접 검증 가능**하게 하는 것이 목적. 파이프라인:

```
면제스캔(_EXEMPT) → 스크럽: _DATE → _UNITSL → _SCI(신설) → _DIM(신설) → 산술스캔(_ARITH)
```

원판 대비 삭제: `strip_codeblocks()` 호출 (D2). 함수 자체도 제거(사용처 0).

### 2.2 신설 정규식 명세

```python
# [D1a] 과학표기: N×10^±k — 유니코드 위첨자(⁻⁶)·캐럿(^-6)·E표기(E-6) 3형 커버
_SCI = re.compile(r"\d[\d.,]*\s*[×xX*]\s*10\s*"
                  r"(?:[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\^\s*[-+]?\d+|[Ee][-+]?\d+|[-+]\d+)")

# [D1b] 치수/해상도: 결과(=, ≈) 미동반 ×·x·X 체인
_DIM = re.compile(r"(?<![\w.])\d[\d.,]*\s*[×xX]\s*\d[\d.,]*(?![\d.,]|\s*[=≈])")

# [D3b] _ARITH 내 √ 패턴만 변경:  √\s*\d  →  √\s*[\d(]
```

**설계 근거 3점 (실측으로 확정한 함정):**

| # | 함정 | 대응 |
|---|---|---|
| 1 | `CTE = 23.6×10⁻⁶` 처럼 앞의 `=`는 **대입**이라 "=있으면 곱셈" 단순화 불가 | 과학표기 **자체를** 스크럽 (`_SCI`가 `_DIM`보다 먼저) |
| 2 | `_DIM` 부정 룩어헤드 단독(`(?!\s*=)`)은 백트래킹이 `12000`을 `1200`으로 부분매치시켜 `1.8 × 12000 = 21600`(진짜 계산)까지 스크럽 → **누탐** | `(?![\d.,]\|\s*[=≈])` 로 숫자 완전매치 강제. R01·R15가 이 경계를 회귀 고정 |
| 3 | `_DIM`의 sub는 전역 — 3축 치수 `100×50×20`은 1차 매치가 `100×50` 소비 후 잔여 `×20`은 좌측 숫자가 없어 `_ARITH` 불발 | 별도 처리 불요, R12가 회귀 고정 |

### 2.3 정책 변경: ×곱셈 = "결과 단언 시만 산술"

| 구분 | 원판 | v2 |
|---|---|---|
| ×, x 곱셈 | 무조건 산술 | **`=` 또는 `≈` 로 결과가 단언된 경우만** 산술 (R14 PASS / R15 BLOCK) |
| / 나눗셈 | 결과(=) 동반 시만 | 동일 (변경 없음) |
| ÷, \*\*, ^, √ | 무조건 | 동일 (강신호 유지) |

근거: G9의 차단 대상은 "검증 안 된 **계산 결과**의 단언"이지 연산 기호 자체가 아님. 결과 미단언 곱셈(`약 1.8 × 12000 N 수준`)은 환각 리스크가 결과값에 있지 않음. 나눗셈에 이미 적용돼 있던 정책을 곱셈으로 통일한 것.

**경계조건(이 정책이 깨지는 지점):** 모델이 결과를 `=` 없이 단언하면(`1.8×12000이니 21600이다`) 미검출. 완전 차단은 정규식으로 불가 — 잔여 리스크로 §6에 등재.

### 2.4 D2 부작용 및 수용 근거

코드펜스 스캔 포함으로 **예시 코드 내 숫자 리터럴 산술**(`range(0, 10*3)`)이 신규 오탐 가능. 수용 근거: ①Bash 실행 턴은 `bashed` 선단락으로 이미 면제 — 남는 케이스는 "코드를 보여주기만 하고 안 돌린" 턴이며, 이는 G12 관점에서도 의심대상 ②오탐 시 비용 = 재송출 1회(Bash 실행 or 면제선언)로 자기해소 ③`stop_hook_active` 가드로 무한루프 불가. CLAUDE.md L5 "표/코드블록 우선" 규율이 원판의 맹점으로 계산을 밀어넣던 구조적 모순이 해소되는 이득이 더 큼.

---

## 3. 설치 명세

### 3.1 [I1] settings.json 병합 (덮어쓰기 금지)

INSTALL.md 2단계의 `cp settings.json ~/.claude/settings.json` 를 아래로 교체. 기존 파일 없으면 그대로 복사, 있으면 훅 이벤트키 단위로 append 병합:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak 2>/dev/null  # 백업
python3 - <<'PYEOF'
import json, os, shutil
home = os.path.expanduser("~/.claude/settings.json")
pkg  = "settings.json"   # 패키지 루트에서 실행
if not os.path.exists(home):
    shutil.copy(pkg, home); print("신규 복사"); raise SystemExit
old = json.load(open(home)); new = json.load(open(pkg))
oh, nh = old.get("hooks", {}), new.get("hooks", {})
for ev, groups in nh.items():
    oh[ev] = oh.get(ev, []) + groups
old["hooks"] = oh
json.dump(old, open(home, "w"), indent=2, ensure_ascii=False)
print("병합 완료:", list(nh.keys()))
PYEOF
```

**검증 완료** 🟢: 기존 `permissions` + `PostToolUse` 훅이 있는 settings에 병합 실행 → 기존 항목 보존 + `SessionStart`(1)·`Stop`(2) 추가, assert 4건 통과. 멱등 아님(재실행 시 훅 중복 등록) — 재설치 시 백업본에서 복원 후 병합할 것.

### 3.2 [I2] compact source 실보고 검증 (설치 후 1회)

배경 🟡: 공식 문서상 SessionStart `source` 4종에 `compact` 포함(🟢 실조회 확인). 단 **VSCode 확장**에서 `/clear`가 `startup`으로 오보고되는 오픈이슈(anthropics/claude-code #26794, #49937) 존재 — `compact` 오보고 여부는 미검증. 오보고 환경이면 `reinject_gates.py`가 **조용히 no-op** = 게이트 재주입(훅 존재이유) 무음 실패.

절차 — 임시 디버그훅 추가:

```json
{"hooks": {"SessionStart": [{"hooks": [{"type": "command",
  "command": "bash -c 'cat >> /tmp/ss-source-probe.log'"}]}]}}
```

① 본인 실사용 클라이언트(터미널 CLI / VSCode 확장)에서 세션 시작 → 긴 컨텍스트 유도 또는 `/compact` 수동 실행 → ② `grep -o '\"source\":\"[a-z]*\"' /tmp/ss-source-probe.log` 로 `"source":"compact"` 실기록 확인 → ③ 확인 후 디버그훅 제거.

| 결과 | 조치 |
|---|---|
| `compact` 기록됨 | 정상 — 조치 불요 |
| `startup` 등으로 오보고 | `reinject_gates.py`의 `if source != "compact": sys.exit(0)` 게이팅을 무매처 전주입으로 완화(토큰 비용 감수) 또는 해당 이슈 해결 대기 |

### 3.3 훅 본체 교체

```bash
cp g9_arith_enforce_v2.py ~/.claude/hooks/g9_arith_enforce.py
```

파일명은 원판 유지(settings.json 커맨드 경로 불변). `reinject_gates.py`·`g12_claim_shadow.py`는 변경 없음.

---

## 4. 회귀테스트 명세 — REG-G9-v2

### 4.1 구성

| 계층 | 건수 | 방식 | 커버 |
|---|---|---|---|
| UNIT | 20 | 훅 파일을 import → `has_unverified_arith()` 직접 호출 | 검출 정규식 전 분기 |
| E2E | 5 | 가짜 transcript JSONL 생성 → 훅을 **subprocess 실제 실행** → stdout `decision:"block"` 유무 판정 | `last_turn`·`bashed` 선단락·`stop_hook_active` 가드·JSON 출력 포함 전체 파이프라인 |

### 4.2 UNIT 케이스 (R01~R20)

| 그룹 | ID | 입력 (대표) | 기대 | 고정하는 것 |
|---|---|---|---|---|
| 정탐 유지 (원판도 잡던 것 — **회귀 금지**) | R01 | `FM = 1.8 × 12000 = 21600 N` | BLOCK | 평문 손계산 |
| | R07 | `듀티 = 3.3/5.0 = 0.66` | BLOCK | 나눗셈+결과 |
| | R16 | `2^10 = 1024` | BLOCK | 거듭제곱 |
| | R19 | `√2 ≈ 1.414` | BLOCK | √ 숫자형 |
| 신규 정탐 (패치 목적) | R02 | 손계산을 ```펜스 안에 | BLOCK | D2 회피차단 |
| | R17 | `σred = √(240² + 3·80²) = 271 MPa` | BLOCK | D3b √( |
| | R15 | `100 × 200 ≈ 20000 mm²` | BLOCK | D1b 경계(≈결과단언) |
| 오탐 제거 (패치 목적) | R03/R06/R11 | `23.6×10⁻⁶ /K`·`396×10⁻⁶`·`23.6 x 10^-6` | PASS | D1a 과학표기 3형 |
| | R04/R05/R12/R13 | `1920×1080`·`100×100mm`·`100×50×20mm`·`3840x2160` | PASS | D1b 해상도·치수 2/3축·소문자x |
| 정책 경계 | R14 | `약 1.8 × 12000 N 수준` (결과 미단언) | PASS | §2.3 정책 |
| 오탐방지 유지 (**회귀 금지**) | R08 | `Fmin = FA/(1-Φ) + FKR` | PASS | D3 보류 정책 |
| | R09 | 손계산 + `⚠️ 산술 미검증` | PASS | 면제 경로 |
| | R10/R18/R20 | 규격인용·날짜·`g²/Hz` | PASS | 기존 스크럽 |

### 4.3 E2E 케이스 (E01~E05)

| ID | transcript 구성 | 기대 | 고정하는 것 |
|---|---|---|---|
| E01 | 손계산 답변, Bash tool_use 0건 | block JSON 출력 | 차단 본선 + JSON 형식 |
| E02 | 동일 답변 + Bash tool_use 1건 | 무출력 | `bashed` 선단락 |
| E03 | 동일 답변 + `stop_hook_active:true` | 무출력 | 무한루프 방지 가드 |
| E04 | `⚠️ 산술 미검증` 선언 답변 | 무출력 | 면제 E2E |
| E05 | 산술 없는 규격인용 답변 | 무출력 | 무산술 통과 |

### 4.4 실행·판정

```bash
python3 test_g9_regression.py                                        # 패치본(동일 폴더) 대상
python3 test_g9_regression.py --hook ~/.claude/hooks/g9_arith_enforce.py   # 설치본 대상
```

- 판정: **25/25 전건 PASS + exit 0** 만 합격. 1건이라도 FAIL → exit 1 (CI·pre-commit 게이트 연동 가능)
- 원판(v1)에 `--hook` 지정 시: `has_unverified_arith` 부재 감지 → UNIT 자동 생략·E2E만 수행 (오판정 방지)
- E2E는 `tempfile` 로 transcript 생성 후 삭제 — 실 세션·로그 무간섭

### 4.5 재실행 의무 시점

| 트리거 | 범위 |
|---|---|
| `_ARITH`·`_SCI`·`_DIM`·`_UNITSL`·`_DATE`·`_EXEMPT` 중 1자라도 수정 | 25종 전건 |
| 훅 파이프라인(`last_turn`·`bashed`·payload 파싱) 수정 | E2E 5종 이상 |
| Claude Code 메이저 업데이트 후 (transcript 스키마 변동 가능 🟡) | E2E 5종 |
| 실사용 중 헛block/누탐 발견 | 해당 입력을 R21+로 **케이스 추가 후** 전건 — 케이스 추가 없는 수정 금지 |

---

## 5. 합격기준 (Definition of Done)

- [ ] `g9_arith_enforce_v2.py` 를 `~/.claude/hooks/g9_arith_enforce.py` 로 교체
- [ ] §3.1 병합 스크립트로 settings.json 반영 (백업 생성 확인)
- [ ] `test_g9_regression.py --hook ~/.claude/hooks/g9_arith_enforce.py` → **ALL PASS, exit 0**
- [ ] 실세션 스모크: ①`"1234 × 5678 얼마?"` → Bash 미실행 답변 시 재송출 요구 확인 ②`"AL6061 CTE 알려줘"` → 과학표기 인용에 **헛block 없음** 확인
- [ ] §3.2 compact source 프로브 1회 수행 (본인 클라이언트 기준)

---

## 6. 잔여 리스크 (패치 범위 외 — 인지 후 수용)

| # | 리스크 | 등급 | 비고 |
|---|---|---|---|
| 1 | `=` 없는 결과 단언(`1.8×12000이니 21600이다`) 미검출 | 🟡 | 정규식 한계. 발견 시 R21+ 추가 |
| 2 | D2 부작용: 미실행 예시코드 내 숫자산술 오탐 | 🟡 | §2.4 — 재송출 1회로 자기해소, 루프 불가 |
| 3 | g12 `if tools: return` — 무관 tool 1건이면 실행주장 면제 | 🟡 | 섀도(로그전용) 설계 의도 — 차단 승급 시 관련성 매칭 필수 |
| 4 | 안전임계 자기점검 = 동일모델(오류 상관) | 🔴 | CLAUDE.md [별도 셋업: 이종모델] 명시대로 — 본 패치 범위 외 |
| 5 | transcript JSONL 스키마는 비공식 내부포맷 — CC 업데이트로 변동 가능 | 🟡 | §4.5 재실행 트리거로 방어. E2E가 조기 감지 |

---

## 부록 A — 본 세션 실행 로그 요약 (2026-07-03)

```
[UNIT] R01~R20: 20/20 PASS
[E2E ] E01~E05:  5/5  PASS   (subprocess 실행, decision:block 판정)
[병합] assert 4건 PASS (permissions·기존훅 보존 / SessionStart·Stop(2) 추가)
=== ALL PASS, exit 0 ===
```
