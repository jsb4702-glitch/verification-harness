#!/usr/bin/env python3
"""
PostToolUse 섀도훅(비차단·로그only) — WebFetch/WebSearch가 가져온 *외부 콘텐츠*를
anti-ultron guard L1(결정론 regex, 모델 안 띄움)로 검사해 metrics.jsonl에만 누적.
inject-detect 섀도(외부콘텐츠=인젝션 표면)의 라이브 트래픽 확장. 출력 없음 → 본동작 무영향.
항상 exit 0. answer_lint_shadow.py 패턴 차용.
"""
import sys, os, json

TOOLDIR = os.path.expanduser("~/.claude/tools/anti-ultron")
sys.path.insert(0, TOOLDIR)
try:
    import guard  # noqa: E402
except Exception:
    sys.exit(0)

MAXLEN = 20000  # regex 안전상한


def text_of(x):
    if isinstance(x, str):
        return x
    out = []
    if isinstance(x, dict):
        for k in ("content", "text", "result", "output", "results"):
            if k in x:
                out.append(text_of(x[k]))
    elif isinstance(x, list):
        for b in x:
            out.append(text_of(b))
    return "\n".join(s for s in out if s)


def main():
    try:
        p = json.load(sys.stdin)
    except Exception:
        return
    tool = p.get("tool_name", "")
    if tool not in ("WebFetch", "WebSearch"):
        return
    content = text_of(p.get("tool_response", "")) or text_of(p.get("tool_input", ""))
    content = content.strip()
    if not content:
        return
    # L1만(deep=False) — 즉시·무료. guard() 내부서 metrics.jsonl에 자동기록.
    try:
        guard.guard(content[:MAXLEN], tag=f"hook:{tool}")
    except Exception:
        pass
    # 출력 없음 — 섀도.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
