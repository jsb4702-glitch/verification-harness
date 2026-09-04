#!/usr/bin/env python3
"""adversarial-harness-audit 공유 엔진 호출 모듈.

attack(aha_attack.py)·judge(aha_judge.py)가 cdx/gemini/agy를 한 곳에서 호출.
설계원칙:
 - 무인(launchd 월간) 기본경로 = cdx(attack)/gemini(judge) — 헤드리스 안전(파일 기반 OAuth/멀티키).
   attack=cdx(OpenAI)·defend=gemma4(로컬)·judge=gemini(Google)로 3계열 분리 = 공격·방어·판정 탈상관.
 - groq 엔진은 2026-09-02 폐기. 사유 둘: ①기본 모델 llama-3.3-70b-versatile이 계정에서 소멸(404
   model_not_found 실조회) ②살아있는 대체 모델로 바꿔도 무료등급 분당토큰 한도 8000이 하네스 전문
   요청(8857~9245 tok)보다 작아 413 상시 발생. 구조적으로 이 워크로드를 못 태운다.
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

AGY_BIN    = os.environ.get("AGY_BIN", "/opt/homebrew/bin/agy")
CDX_BIN    = os.environ.get("CODEX_BIN", os.path.expanduser("~/.codex/plugins/.plugin-appserver/codex"))
_CDX_CANON = os.path.expanduser("~/.claude/config/cdx_model.txt")  # 단일소스(cdx_review.py와 공유)
CDX_MODEL  = os.environ.get("CDX_MODEL") or (open(_CDX_CANON).read().strip() if os.path.exists(_CDX_CANON) else "")
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
    # 균형 스캔 실패 = 대개 출력 상한으로 끝이 잘린 경우.
    # 마지막으로 '온전히 닫힌 원소'까지만 살리고 나머지 괄호를 닫아 부분 복구한다.
    # 잘린 원소는 버린다 — 반쪽 판정을 채워 넣는 것보다 건수가 주는 편이 안전하다.
    return _repair_truncated_json(text)


def _repair_truncated_json(text: str):
    """출력이 중간에 끊긴 JSON을 '마지막 완결 원소'까지 잘라 복구. 실패 시 None."""
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        if start < 0:
            continue
        stack, in_str, esc = [], False, False
        cuts = []  # (마지막 완결 위치, 그 시점의 미닫힘 스택)
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:          esc = False
                elif c == "\\":  esc = True
                elif c == '"':   in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "[{":
                stack.append(c)
            elif c in "]}":
                if not stack:
                    break
                stack.pop()
                if stack:
                    cuts.append((i, list(stack)))
        for cut_i, st in reversed(cuts):
            closers = "".join("]" if o == "[" else "}" for o in reversed(st))
            try:
                obj = json.loads(text[start:cut_i + 1] + closers)
                sys.stderr.write(
                    f"[aha_engines] ⚠️ 잘린 JSON 부분복구 — {cut_i - start + 1}자까지만 유효, "
                    f"이후 미완결분 폐기\n")
                return obj
            except json.JSONDecodeError:
                continue
    return None


def call_cdx(system: str, user: str, timeout: int = None) -> str:
    """Codex CLI(OpenAI GPT) — 무인 기본 공격엔진(2026-09-02 groq 승계).

    ~/.codex/auth.json 파일 기반 OAuth라 헤드리스에서 동작(agy의 키링 hang 문제 없음).
    cdx_review.py와 동일한 격리 규약: read-only 샌드박스 + 빈 스크래치 작업루트.
    적대감사는 하네스 전문을 입력으로 태우므로, 에이전트가 실제 파일을 건드리지 못하게 막는 게 필수다(G11).
    """
    if not os.path.exists(CDX_BIN):
        raise RuntimeError(f"codex binary not found at {CDX_BIN} (set CODEX_BIN)")
    to = timeout if timeout is not None else int(os.environ.get("CDX_TIMEOUT", "600"))
    prompt = f"{system}\n\n[DATA]\n{user}"
    import tempfile
    with tempfile.TemporaryDirectory(prefix="aha_cdx_") as scratch:
        out_file = os.path.join(scratch, "_last.txt")
        cmd = [CDX_BIN, "exec", "-s", "read-only", "--skip-git-repo-check",
               "-C", scratch, "-o", out_file]
        if CDX_MODEL:
            cmd += ["-m", CDX_MODEL]
        cmd += [prompt]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=to, stdin=subprocess.DEVNULL)
        last = ""
        if os.path.exists(out_file):
            with open(out_file, encoding="utf-8") as f:
                last = f.read().strip()
        if proc.returncode != 0 and not last:
            raise RuntimeError(f"codex exit {proc.returncode}: "
                               f"{(proc.stderr or proc.stdout or 'no output').strip()[:300]}")
        if not last:
            last = (proc.stdout or "").strip()
        if not last:
            raise RuntimeError(f"codex returned empty (stderr: {(proc.stderr or '')[:200]})")
        return last


def call_gemini(system: str, user: str, timeout: int = 120) -> str:
    sys.path.insert(0, os.path.expanduser("~/.claude/tools"))
    import gemini_keys
    if not gemini_keys.load_keys():
        raise RuntimeError("Gemini 키 없음 (GEMINI_API_KEYS/GEMINI_API_KEY)")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    # 출력예산은 '사고 토큰 + 본문'이 함께 쓴다(2026-09-02 실측: thoughtsTokenCount 2468).
    # 8192로는 후보가 장황할 때 사고가 예산을 먹고 JSON이 중간에 잘려 parse 실패했다.
    # ①상한 상향 ②사고예산에 별도 캡을 걸어 본문 몫을 보장 ③잘림을 조용히 넘기지 말고 예외로 올림.
    max_out = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "32768"))
    think_budget = int(os.environ.get("GEMINI_THINKING_BUDGET", "8192"))
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_out,
                             "responseMimeType": "application/json",
                             "thinkingConfig": {"thinkingBudget": think_budget}},
    }).encode("utf-8")
    resp, _used = gemini_keys.post_generate(body, model=model, timeout=timeout)
    cand = resp["candidates"][0]
    parts = cand.get("content", {}).get("parts", [])
    text = "\n".join(p["text"] for p in parts if "text" in p)
    fr = cand.get("finishReason")
    if fr and fr != "STOP":
        # MAX_TOKENS·SAFETY·RECITATION 등 — 본문이 불완전하다. 조용한 부분출력 금지(G12 취지).
        u = resp.get("usageMetadata", {})
        raise RuntimeError(
            f"gemini finishReason={fr} (사고 {u.get('thoughtsTokenCount', 0)} tok / "
            f"본문 {u.get('candidatesTokenCount', 0)} tok / 상한 {max_out}) — 응답 불완전")
    return text


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
    if engine == "cdx":    return call_cdx(system, user)
    if engine == "gemini": return call_gemini(system, user)
    if engine == "agy":    return call_agy(system, user)
    raise ValueError(f"unknown engine: {engine}")
