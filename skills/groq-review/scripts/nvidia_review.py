#!/usr/bin/env python3
"""Cross-validate content via NVIDIA NIM (build.nvidia.com, OpenAI-compatible).

groq 슬롯이 llama-3.3-70b라 탈상관 위해 기본 모델은 비-llama(nemotron) 계열.
모델 id는 NVIDIA_MODEL 환경변수로 오버라이드 가능 — build.nvidia.com 카탈로그의
정확한 id로 바꿔 쓰면 됨(잘못된 id면 NIM이 HTTP 400/404 반환 → 그대로 노출).
"""

import sys
import os
import json
import urllib.request
import urllib.error

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

# OpenAI 호환 엔드포인트 (build.nvidia.com / NIM 호스티드)
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# 기본 모델: groq(llama-3.3-70b)와 탈상관 위해 nemotron 계열.
# build.nvidia.com 카탈로그에서 본인이 쓸 모델 id로 바꾸려면 NVIDIA_MODEL 설정.
MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")

SYSTEM_PROMPT = """You are an expert cross-validator. Critically review the provided content for:
- Factual accuracy
- Logical consistency
- Calculation errors
- Unstated assumptions
- Missing edge cases

Only assert an error when you are more than 75% confident it is actually wrong - a false accusation costs three times more than staying silent. When uncertain, mark the point as "unverified" instead of asserting.

Respond in the same language as the input. Be concise and direct. Flag specific issues with line references where possible."""


def call_nvidia(content: str, api_key: str) -> str:
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }).encode("utf-8")

    req = urllib.request.Request(
        NVIDIA_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "nvidia-review/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def main():
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not set.")
        print("Get a free key at https://build.nvidia.com (key starts with nvapi-)")
        print('Then add to ~/.config/secrets.env:  NVIDIA_API_KEY="nvapi-..."')
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: nvidia_review.py <input_file>")
        sys.exit(1)

    input_path = sys.argv[1]
    if input_path == "-":
        content = sys.stdin.read()
    else:
        with open(input_path, "r", encoding="utf-8") as f:
            content = f.read()

    if not content.strip():
        print("ERROR: Input is empty.")
        sys.exit(1)

    print(f"[NVIDIA NIM] Sending to {MODEL}...\n")
    try:
        result = call_nvidia(content, api_key)
        print("=" * 60)
        print("NVIDIA NIM 교차검증 결과")
        print("=" * 60)
        print(result)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}")
        print(f"(model={MODEL} — 모델 id가 맞는지 build.nvidia.com 카탈로그에서 확인)")
        sys.exit(1)


if __name__ == "__main__":
    main()
