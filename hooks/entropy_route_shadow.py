#!/usr/bin/env python3
"""
Stop 훅 — entropy-route 섀도 트리거 (2026-07-21, v0).

직전 턴이 '짧은 질문 + 등급 🟡/🔴 포함 답변'이면 의미 엔트로피 샘플링을
detached로 발사한다(비차단·jsonl 로그만). 판정·개입 없음 — 섀도 전용.

발동조건:
  사용자 프롬프트 300자 미만, '/' 시작 아님(스킬 호출 제외)
  답변에 🟡 또는 🔴 존재(불확실 주장 존재 신호)
  stop_hook_active 아님 / 훅 예외는 조용히 통과(fail-open)

샘플러: 기본 claude(구독 CLI·Haiku). 민감 키워드 감지 시 ollama(로컬, 유출 0).
       ENTROPY_ROUTE_SAMPLER 환경변수로 강제 가능(mock=파이프테스트용).
minicheck_autoshadow.py의 detached Popen 패턴 차용.
"""
import sys, os, json, re, subprocess

TOOL = os.path.expanduser("~/.claude/tools/entropy-route/entropy_route.py")
_GRADE = re.compile(r"[\U0001F7E1\U0001F534]")   # 🟡 🔴
# 민감 도메인 감지 — 자기 업무 도메인에 맞게 조정해서 쓸 것.
# 여기 걸리면 외부 샘플러 대신 로컬 ollama 로 라우팅한다(유출 0).
_SENSITIVE = re.compile(r"기밀|대외비|수출통제|반출제한|민감|고객사|내부자료|사내한정")


def load_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def read_jsonl(path):
    rows = []
    try:
        for l in open(path):
            l = l.strip()
            if l:
                try:
                    rows.append(json.loads(l))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") in ("text", None) and isinstance(b.get("text"), str):
                    out.append(b["text"])
                elif isinstance(b.get("content"), (str, list)):
                    out.append(text_of(b["content"]))
            elif isinstance(b, str):
                out.append(b)
    return "\n".join(out)


def last_turn(rows):
    start = 0
    for i, d in enumerate(rows):
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr:
                start = i
    return rows[start:]


def main():
    p = load_payload()
    if p.get("stop_hook_active"):
        return
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)):
        return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows:
        return
    turn = last_turn(rows)

    user_txt = ""
    answer = ""
    for d in turn:
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr:
                user_txt += "\n" + text_of(c)
        elif d.get("type") == "assistant":
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip():
                answer = t

    q = user_txt.strip()
    if not q or not answer:
        return
    if len(q) > 300 or q.startswith("/"):
        return
    if not _GRADE.search(answer):
        return

    sampler = os.environ.get("ENTROPY_ROUTE_SAMPLER") or (
        "ollama" if _SENSITIVE.search(q) else "claude")
    subprocess.Popen(
        ["python3", TOOL, "--question", q[:280], "--sampler", sampler, "--n", "3"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
