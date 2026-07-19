import os, sys, json, urllib.request, urllib.error

# 비대화 셸(rc 미소스)에서도 키 로드 — ~/.config/secrets.env 직접 파싱
_secrets = os.path.expanduser("~/.config/secrets.env")
if os.path.exists(_secrets):
    with open(_secrets) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("export "):
                _line = _line[7:]
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
import gemini_keys  # 멀티키 로테이션 + 429/503 페일오버 (하네스 공유 정본)
if not gemini_keys.load_keys():
    sys.exit("[오류] Gemini 키 없음 (GEMINI_API_KEYS 또는 GEMINI_API_KEY).")
if len(sys.argv) < 2:
    sys.exit("[오류] 사용법: python review.py <검토할_파일.txt>")

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # 무료티어=flash. 유료시 GEMINI_MODEL=gemini-2.5-pro
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

try:
    content = open(sys.argv[1], encoding="utf-8-sig").read()
except FileNotFoundError:
    sys.exit(f"[오류] 파일을 찾을 수 없습니다: {sys.argv[1]}")

# GV 적대적 검증 프롬프트(별도 파일) 로드 — 없으면 경량 기본 SYS로 폴백
_gv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gv_prompt.md")
if os.path.exists(_gv):
    SYS = open(_gv, encoding="utf-8").read()
else:
    SYS = """역할: 너는 제품 기구설계를 독립 검증하는 시니어 검토 엔지니어다.
입력의 결론·계산을 옳다고 가정하지 말고 처음부터 다시 따져라.
1. 모든 수치는 직접 재계산하라. 과정을 보이고 원본값과 대조해 일치/불일치 판정.
2. 규격·물성·상수는 출처 제시 또는 [미검증] 표기. 추측 생성 금지.
3. 가정·경계조건 없으면 '검증불가-정보부족'으로 분류하고 필요한 것 명시.
4. 칭찬·일반론·동어반복 금지.
마지막 줄: 종합판정(합격/조건부/불합격) + 검토 신뢰도(상/중/하) + 이유."""

def call(contents):
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYS}]},
        "contents": contents,
        "tools": [{"google_search": {}}, {"code_execution": {}}],  # VECTOR A(산술)/B·C(규격·날조) 무기 활성
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
    }).encode("utf-8")
    resp, _used = gemini_keys.post_generate(body, model=MODEL, timeout=180)
    return resp

# 에이전트 루프: flash가 도구턴 후 종합 text를 안 쓰는 경우, 도구결과를 되먹여 종합 강제
contents = [{"role": "user", "parts": [{"text": content}]}]
NUDGE = ("위 도구(code_execution/google_search) 결과를 근거로 이제 최종 검증 보고를 작성하라. "
         "GV 출력형식 — 첫 줄 판정(❌/⚠️/🔍) + 결함표 + 심각도. 도구 추가 호출 없이 종합 텍스트만 출력.")
try:
    out = None
    for _round in range(4):
        resp = call(contents)
        cand = resp["candidates"][0]
        parts = cand.get("content", {}).get("parts", [])
        texts = [p["text"] for p in parts if "text" in p]
        if texts:
            out = "\n".join(texts)
            break
        # text 없음 → 모델 도구턴 보존 + 종합 넛지 후 재호출
        contents.append({"role": "model", "parts": parts})
        contents.append({"role": "user", "parts": [{"text": NUDGE}]})
    if out:
        print(out)
    else:
        sys.exit("[오류] 4라운드 내 종합 text 미생성 — 입력을 줄이거나 GEMINI_MODEL=gemini-2.5-pro 시도.")
except urllib.error.HTTPError as e:
    sys.exit(f"[API 오류 {e.code}] {e.read().decode()}")
except (KeyError, IndexError):
    sys.exit("[오류] Gemini 응답 해석 실패(안전필터 차단 가능).")
