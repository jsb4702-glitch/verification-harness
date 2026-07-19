#!/usr/bin/env python3
"""adversarial-harness-audit 공유 엔진 호출 모듈.

attack(aha_attack.py)·judge(aha_judge.py)가 groq/gemini/agy를 한 곳에서 호출.
설계원칙:
 - 무인(launchd 주간) 기본경로 = groq(attack)/gemini(judge) — 헤드리스 안전(키=secrets.env/멀티키).
 - agy(Gemini 3.1 Pro)는 대화형 opt-in 전용 — 키링 OAuth라 detached bg/launchd서 hang(memory agy-cli-verify-slot).
   → 기본 엔진 아님. --engine agy 명시 시에만, 그리고 무인이 아님을 호출측이 보장.
 - 모든 엔진은 '구조화 JSON만 출력' 지시로 호출하고 extract_json()으로 견고 파싱.
"""
import os, sys, json, re, subprocess

# ── 키 로드 (비대화 셸에서도) ─────────────────────────────
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

import urllib.request, urllib.error

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("AHA_GROQ_MODEL", "llama-3.3-70b-versatile")
AGY_BIN    = os.environ.get("AGY_BIN", "/opt/homebrew/bin/agy")
_AGY_CANON = os.path.expanduser("~/.claude/config/agy_model.txt")  # 단일소스
AGY_MODEL  = os.environ.get("AGY_MODEL") or (open(_AGY_CANON).read().strip() if os.path.exists(_AGY_CANON) else "Gemini 3.1 Pro (High)")
def extract_json(text: str):
    """모델 출력에서 첫 균형 JSON( [..] 또는 {..} ) 블록을 뽑아 파싱. 실패 시 None."""
    if not text:
        return None
    # 코드펜스 제거
    text = re.sub(r"```(?:json)?", "", text)
    # 첫 [ 또는 { 부터 균형 스캔
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:            esc = False
                elif c == "\\":    esc = True
                elif c == '"':     in_str = False
                continue
            if c == '"':           in_str = True
            elif c == open_ch:     depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def call_groq(system: str, user: str, max_tokens: int = 2048, timeout: int = 60) -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set (secrets.env)")
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(GROQ_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "User-Agent": "aha-audit/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def call_gemini(system: str, user: str, timeout: int = 120) -> str:
    sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
    import gemini_keys
    if not gemini_keys.load_keys():
        raise RuntimeError("Gemini 키 없음 (GEMINI_API_KEYS/GEMINI_API_KEY)")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192,
                             "responseMimeType": "application/json"},
    }).encode("utf-8")
    resp, _used = gemini_keys.post_generate(body, model=model, timeout=timeout)
    parts = resp["candidates"][0].get("content", {}).get("parts", [])
    return "\n".join(p["text"] for p in parts if "text" in p)


def call_agy(system: str, user: str, timeout: int = 120) -> str:
    """agy(Gemini 3.1 Pro) — 대화형 opt-in 전용. --sandbox 필수(에이전트 하네스 인젝션 완화)."""
    if not os.path.exists(AGY_BIN):
        raise RuntimeError(f"agy not found at {AGY_BIN}")
    prompt = f"{system}\n\n[DATA]\n{user}"
    proc = subprocess.run(
        [AGY_BIN, "--output-format", "json", "--model", AGY_MODEL,
         "-p", prompt, "--print-timeout", "90s", "--sandbox"],
        capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"agy exit {proc.returncode}: {(proc.stderr or out or 'no output')[:300]}")
    try:
        env = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"agy envelope parse failed (flag drift?): {out[:200]}")
    if env.get("status") != "SUCCESS":
        raise RuntimeError(f"agy status={env.get('status')}: {str(env)[:200]}")
    return env.get("response", "").strip()


def call_engine(engine: str, system: str, user: str) -> str:
    if engine == "groq":   return call_groq(system, user)
    if engine == "gemini": return call_gemini(system, user)
    if engine == "agy":    return call_agy(system, user)
    raise ValueError(f"unknown engine: {engine}")
