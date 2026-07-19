#!/usr/bin/env python3
"""
Stop 훅 — 외부자료(WebFetch/WebSearch)를 가져온 턴에서만, 직전 답변 문장들이
그 출처에 grounding 되는지 MiniCheck 섀도로 비차단 백그라운드 채점.
훅은 파싱만(가벼움) → minicheck_run.py가 detached로 채점·JSONL 누적.
인용 없는 턴/추출 claim 없음 → 조용히 종료(본동작 무영향).
"""
import sys, os, json, re, time, subprocess, hashlib

RUN = os.path.expanduser("~/minicheck-shadow/minicheck_run.py")
WEB_TOOLS = {"WebFetch", "WebSearch", "web_search"}
MAX_CLAIMS = 6
MAX_DOC = 20000
DEDUP = os.path.expanduser("~/harness-eval/minicheck/.auto_seen")  # 같은 답변 중복채점 방지

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
                try: rows.append(json.loads(l))
                except Exception: pass
    except Exception:
        pass
    return rows

def text_of(content):
    """tool_result/assistant content(str|list) → 텍스트 평탄화"""
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
    """마지막 사용자 프롬프트(tool_result 아님) 이후 레코드들"""
    start = 0
    for i, d in enumerate(rows):
        if d.get("type") == "user":
            msg = d.get("message", {})
            c = msg.get("content")
            is_toolresult = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_toolresult:
                start = i
    return rows[start:]

def collect(turn):
    """이번 턴의 web 출처 텍스트(doc) + 마지막 답변 텍스트"""
    web_ids, tool_names = set(), {}
    for d in turn:
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in WEB_TOOLS:
                    web_ids.add(b.get("id")); tool_names[b.get("id")] = b.get("name")
    docs, used_tool = [], None
    for d in turn:
        if d.get("type") == "user":
            for b in (d.get("message", {}).get("content", []) or []):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in web_ids:
                    docs.append(text_of(b.get("content"))); used_tool = tool_names.get(b.get("tool_use_id"))
    answer = ""
    for d in turn:
        if d.get("type") == "assistant":
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip(): answer = t
    return ("\n\n".join(docs))[:MAX_DOC], answer, used_tool

# 사실주장스러운 문장만 claim 후보로
_SENT = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*|\n")
_SKIP = re.compile(r"^\s*(#{1,6}\s|[-*>|]\s|```|\|)")
_META = re.compile(r"^(BLUF|결론|정리하|요약하|참고로|아래|다음과|즉|따라서 정리|먼저|우선)")
_PLAIN = re.compile(r"[.다음함됨임)]$")   # 평서·서술 종결(질문/미완 제외)

def extract_claims(answer):
    # 코드블록/표 라인 제거
    lines = []
    in_code = False
    for ln in answer.splitlines():
        if ln.strip().startswith("```"): in_code = not in_code; continue
        if in_code: continue
        if _SKIP.match(ln): continue
        lines.append(ln)
    flat = " ".join(lines)
    cands, seen = [], set()
    for s in _SENT.split(flat):
        s = re.sub(r"[*_`#]", "", s).strip()
        if not (25 <= len(s) <= 300): continue
        if s.endswith("?") or s.endswith("까") or s.endswith("나요") or s.endswith("줘"): continue
        if _META.match(s): continue               # 메타/지시 서두 제외
        if not _PLAIN.search(s): continue         # 평서·서술 종결만(미완·구어 제외)
        k = s[:60]
        if k in seen: continue
        seen.add(k); cands.append(s)
        if len(cands) >= MAX_CLAIMS: break
    return cands

def main():
    p = load_payload()
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)):
        return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows: return
    turn = last_turn(rows)
    doc, answer, tool = collect(turn)
    if not doc or not answer.strip():
        return                       # 외부 출처 없는 턴 → 스킵
    claims = extract_claims(answer)
    if not claims:
        return
    # 같은 답변 중복채점 방지
    sig = hashlib.sha1((doc[:200] + answer[:400]).encode()).hexdigest()[:16]
    try:
        os.makedirs(os.path.dirname(DEDUP), exist_ok=True)
        seen = set(open(DEDUP).read().split()) if os.path.exists(DEDUP) else set()
        if sig in seen: return
        open(DEDUP, "a").write(sig + "\n")
    except Exception:
        pass
    # 본동작 모델 태그 — 모델 전환 시 grounding 기준선 구간분리용 (tag에 인코딩: run 스크립트 무수정 전파)
    model = ""
    for d in turn:
        if d.get("type") == "assistant":
            m = d.get("message", {}).get("model")
            if m: model = m
    cases = [dict(doc=doc, claim=c, lang="auto", tag=f"auto:{tool or 'web'}:{model}") for c in claims]
    tmp = f"/tmp/minicheck_auto_{int(time.time())}_{sig}.json"
    json.dump(cases, open(tmp, "w"), ensure_ascii=False)
    try:
        subprocess.Popen(["python3", RUN, "--input", tmp],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass
    # 훅은 조용히 종료(본동작 무영향). 출력 없음.

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass   # 훅 실패가 세션을 막지 않도록
