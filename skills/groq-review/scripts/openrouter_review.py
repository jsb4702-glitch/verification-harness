#!/usr/bin/env python3
"""OpenRouter 무료모델 교차검증 — gemini 429 폴백/보조 이종슬롯용.
OpenAI 호환 chat/completions. 무료모델 폴백루프(프로바이더 큐밀림·모델제거 대비).
사용: python3 openrouter_review.py <검토할_파일.txt>
출력: stdout에 비평 텍스트.

⚠️ 무료모델은 프로바이더 학습 활용 가능 — 민감데이터 금지(호출측에서 게이트).
   이 스크립트 자체는 콘텐츠 판단 안 함. allow 게이트는 워크플로(parallel-verify)가 책임.
"""
import os, sys, json, urllib.request, urllib.error

# secrets.env 로드(gemini/groq와 동일 방식)
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

API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    sys.exit("[오류] OPENROUTER_API_KEY 없음. ~/.config/secrets.env에 'export OPENROUTER_API_KEY=sk-or-...' 추가.")
if len(sys.argv) < 2:
    sys.exit("[오류] 사용법: openrouter_review.py <검토할_파일.txt>")

try:
    content = open(sys.argv[1], encoding="utf-8-sig").read()
except FileNotFoundError:
    sys.exit(f"[오류] 파일 없음: {sys.argv[1]}")

# 실재 확인된 무료모델(2026-06-29 /models 조회). 환경변수로 override 가능.
# Claude/Gemini/Llama(groq)와 결 다른 순서 — 이종성 우선.
MODELS = os.environ.get("OPENROUTER_MODELS", ",".join([
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
])).split(",")

SYS = ("너는 독립 교차검증자다. 아래 주장을 비판적으로 검토하라. "
       "수치·규격이 실제와 다르면 반증, 확인되면 확인, 알 수 없으면 미검증으로 명시. "
       "반증/요주의 항목만 간결히. 마지막 줄에 종합판정 PASS/WARN/FAIL 1줄.")

URL = "https://openrouter.ai/api/v1/chat/completions"


def call(model):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": content}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost/harness",  # OpenRouter 권장 헤더
        "X-Title": "harness-cross-verify",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        resp = json.load(r)
    return resp["choices"][0]["message"]["content"]


last_err = ""
for m in MODELS:
    m = m.strip()
    if not m:
        continue
    try:
        out = call(m)
        if out and out.strip():
            print(f"[OpenRouter:{m}]\n{out}")
            sys.exit(0)
    except urllib.error.HTTPError as e:
        last_err = f"{m}: HTTP {e.code} {e.read().decode()[:200]}"
        continue
    except Exception as e:
        last_err = f"{m}: {e}"
        continue

sys.exit(f"[오류] 모든 무료모델 실패. 마지막: {last_err}")
