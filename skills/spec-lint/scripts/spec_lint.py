#!/usr/bin/env python3
"""명세서 린트: 로컬 GLM-4.7-Flash(ollama)에게 명세의 모호/누락/모순/미정의를 뽑게 한다.
Claude(컨트롤러)가 호출 → GLM(오퍼레이터)이 1차 추출 → Claude가 검수/정제."""
import sys, json, urllib.request

MODEL = "glm-4.7-flash"
URL = "http://localhost:11434/api/generate"

if len(sys.argv) < 2:
    sys.exit("[오류] 사용법: python spec_lint.py <명세파일.txt>")
try:
    spec = open(sys.argv[1], encoding="utf-8-sig").read()
except FileNotFoundError:
    sys.exit(f"[오류] 파일 없음: {sys.argv[1]}")

SYS = """너는 소프트웨어/엔지니어링 명세서를 코드 구현 직전에 검수하는 엄격한 명세 린터다.
이 명세를 받아 구현자(AI 코더)가 '추측 없이' 코딩할 수 있는지만 따진다. 잘 쓴 부분 칭찬·요약·재진술 금지. 오직 결함만 뽑는다.

검출 항목(각 항목마다 명세 원문 인용 + 이유):
1. 모호(AMBIGUOUS): "적절히/등등/필요시/일반적으로" 같이 구현이 갈리는 표현.
2. 누락(MISSING): 입력/출력/자료형/단위/경계값/에러처리/성능기준/의존성 등 구현에 필요한데 안 적힌 것.
3. 모순(CONTRADICTION): 같은 명세 안에서 서로 충돌하는 요구.
4. 미정의(UNDEFINED): 정의 없이 쓰인 용어·약어·식별자.
5. 검증불가(UNTESTABLE): 수용 기준이 없어 '됐다'를 판정할 수 없는 요구.

규칙:
- 명세에 없는 사실을 지어내지 마라. 추측 금지.
- 결함이 없으면 그 항목은 '없음'으로 적어라.
- 출력은 아래 표 형식만. 서론·결론 쓰지 마라.

출력 형식(마크다운 표):
| # | 분류 | 명세 원문(짧게 인용) | 문제 | 구현자가 물어야 할 것 |
표 다음 줄에: 종합판정(구현가능/조건부/불가) + 가장 치명적인 결함 1개."""

body = json.dumps({
    "model": MODEL,
    "system": SYS,
    "prompt": "다음 명세서를 린트하라:\n\n" + spec,
    "think": False,
    "stream": False,
    "options": {"temperature": 0, "num_ctx": 8192},
}).encode("utf-8")

req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.load(r)
    print(resp.get("response", "").strip())
except Exception as e:
    sys.exit(f"[오류] GLM 호출 실패(ollama 실행 중인지 확인): {e}")
