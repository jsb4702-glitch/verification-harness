import os, sys, json, subprocess, urllib.request, urllib.error

PROJECT = os.environ.get("GCP_PROJECT_ID")
if not PROJECT:
    sys.exit("[오류] GCP_PROJECT_ID 환경변수가 없습니다.")
if len(sys.argv) < 2:
    sys.exit("[오류] 사용법: python review_oauth.py <검토할_파일.txt>")

try:
    token = subprocess.check_output(
        "gcloud auth application-default print-access-token",
        shell=True, text=True).strip()
except Exception as e:
    sys.exit(f"[오류] gcloud 토큰 발급 실패. 'gcloud auth application-default login' 먼저 실행: {e}")

MODEL = "gemini-2.5-flash"   # 무료티어 호환(pro는 free-tier limit:0). 유료시 "gemini-2.5-pro" 가능
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

try:
    content = open(sys.argv[1], encoding="utf-8-sig").read()
except FileNotFoundError:
    sys.exit(f"[오류] 파일을 찾을 수 없습니다: {sys.argv[1]}")

SYS = """역할: 너는 제품 기구설계를 독립 검증하는 시니어 검토 엔지니어다.
입력의 결론·계산을 옳다고 가정하지 말고 처음부터 다시 따져라.

검증 규칙:
1. 모든 수치는 직접 재계산하라. 과정을 보이고 원본값과 대조해 일치/불일치 판정.
2. 규격·물성·상수는 출처 제시 또는 [미검증] 표기. 규격 조항번호·부품 PN·물성 수치를 추측해 생성하지 마라.
3. 판단에 필요한 가정·요구사항·경계조건이 없으면 '검증불가-정보부족'으로 분류하고 무엇이 필요한지 명시. 빠진 값을 임의 가정하지 마라.
4. 칭찬·일반론·동어반복 금지.

출력(항목별): 분류(공차/체결/재료/구조/DFM/계산) | 심각도(치명/중대/경미) | 원본주장 → 독립검증결과(검증됨/반증/검증불가) | 근거(재계산 또는 규격/출처) | 권고
마지막 줄: 종합판정(합격/조건부/불합격) + 검토 신뢰도(상/중/하) + 이유."""

body = json.dumps({
    "system_instruction": {"parts": [{"text": SYS}]},
    "contents": [{"parts": [{"text": content}]}],
    "generationConfig": {"temperature": 0},
}).encode("utf-8")

req = urllib.request.Request(URL, data=body, headers={
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}",
    "x-goog-user-project": PROJECT,
})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.load(r)
    print(resp["candidates"][0]["content"]["parts"][0]["text"])
except urllib.error.HTTPError as e:
    sys.exit(f"[API 오류 {e.code}] {e.read().decode()}")
except (KeyError, IndexError):
    sys.exit("[오류] Gemini 응답 해석 실패.")
