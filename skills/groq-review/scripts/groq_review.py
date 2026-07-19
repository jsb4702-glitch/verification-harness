#!/usr/bin/env python3
"""Cross-validate content via Groq API (llama-3.3-70b-versatile)."""

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

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are an expert cross-validator. Critically review the provided content for:
- Factual accuracy
- Logical consistency
- Calculation errors
- Unstated assumptions
- Missing edge cases

Respond in the same language as the input. Be concise and direct. Flag specific issues with line references where possible."""


def call_groq(content: str, api_key: str) -> str:
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
        GROQ_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "groq-review/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def main():
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set.")
        print("Get a free key at https://console.groq.com")
        print("Then run: export GROQ_API_KEY=\"gsk_...\"")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: groq_review.py <input_file>")
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

    print(f"[Groq] Sending to {MODEL}...\n")
    try:
        result = call_groq(content, api_key)
        print("=" * 60)
        print("Groq 교차검증 결과")
        print("=" * 60)
        print(result)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}")
        sys.exit(1)


if __name__ == "__main__":
    main()
