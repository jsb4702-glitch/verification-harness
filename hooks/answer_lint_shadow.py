#!/usr/bin/env python3
"""
Stop 훅(섀도·비차단) — 직전 답변 텍스트를 answer_lint로 검사해 G1/G4 누락의심을
화면에 띄우지 않고 JSONL 로그에만 누적. FP율 측정 후 visible advisory 승급 판단용.
출력 없음 → 본동작 무영향. minicheck_autoshadow.py 패턴 차용.
"""
import sys, os, json, re, time, hashlib

sys.path.insert(0, os.path.expanduser("~/answer-lint-shadow"))
try:
    from answer_lint import lint, has_any_claim
except Exception:
    sys.exit(0)
try:
    from hedge_lint import hedge_lint, has_any_hedge   # WFB #1 (2026-07-12)
except Exception:
    hedge_lint = None
    def has_any_hedge(_):  # noqa
        return False

LOG   = os.path.expanduser("~/answer-lint-shadow/findings.jsonl")
DEDUP = os.path.expanduser("~/answer-lint-shadow/.seen")

def read_jsonl(path):
    rows = []
    try:
        for l in open(path):
            l = l.strip()
            if l:
                try: rows.append(json.loads(l))
                except Exception: pass
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

def last_answer(turn):
    ans = ""
    for d in turn:
        if d.get("type") == "assistant":
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip(): ans = t
    return ans

def main():
    p = {}
    try: p = json.load(sys.stdin)
    except Exception: pass
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)):
        return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows: return
    turn = last_turn(rows)
    answer = last_answer(turn)
    if not answer.strip():
        return
    # 본동작 모델 태그 — 모델 전환(Opus→Fable 등) 시 FP 기준선 구간분리용
    model = ""
    for d in turn:
        if d.get("type") == "assistant":
            m = d.get("message", {}).get("model")
            if m: model = m
    if not has_any_claim(answer) and not has_any_hedge(answer):
        return   # 주장·회피문구 신호 0 → 린터 비대상 턴, 스킵(노이즈 방지)

    sig = hashlib.sha1(answer[:400].encode()).hexdigest()[:16]
    try:
        os.makedirs(os.path.dirname(DEDUP), exist_ok=True)
        seen = set(open(DEDUP).read().split()) if os.path.exists(DEDUP) else set()
        if sig in seen: return
        open(DEDUP, "a").write(sig + "\n")
    except Exception:
        pass

    findings = lint(answer)
    # L2 (2026-07-05): L2a 문서 재스캔=억제 적용 / L2b use-mention 판정=기록전용
    # (골드셋 실측: qwen2.5:3b 과억제 0·MENTION recall 1/5 — 억제 승급 미달, annotation 축적용)
    try:
        from lint_l2 import apply_l2
        findings, _ = apply_l2(answer, findings, judge=True)
    except Exception:
        pass  # L2 실패 = L1 결과 그대로 (fail-open)
    # hedge (WFB #1, 2026-07-12) — G1/G4와 직교, L2 미적용(자체 억제 내장).
    # answer_lint.lint()엔 안 섞음(measure_fp/report의 G1/G4 측정 순정 유지).
    if hedge_lint is not None:
        try:
            findings = findings + hedge_lint(answer)
        except Exception:
            pass
    n_kept = sum(1 for f in findings if f.get("l2") != "sup-dedup")  # sup-mention은 기록만, 카운트 유지
    rec = dict(
        ts=int(time.time()), sig=sig,
        session=p.get("session_id", ""),
        model=model,
        n=n_kept,
        gates=sorted({f["gate"] for f in findings if f.get("l2") != "sup-dedup"}),
        findings=findings,
        preview=answer[:160].replace("\n", " "),
    )
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # 출력 없음 — 섀도.

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
