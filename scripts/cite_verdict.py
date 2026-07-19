#!/usr/bin/env python3
"""cite_verdict.py — 인용 '검증등급' 판정기 (cite_lookup.py 위에 얹는 add-on).

짜깁기 출처(3개 레포 메커니즘 재작성, 원본 복붙 없음):
  - Vikranth3140/Citation-Hallucination-Detection: 3등급 valid/partial/hallucinated + OpenAlex 폴백
  - rpatrik96/hallmark: 필드별 서브테스트 벡터(doi_resolves/title/author/venue) — 단일 bool이 아닌 벡터
  - chrisryugj/korean-law-mcp: CONTENT_MISMATCH = 실재 ID인데 청구 메타데이터가 다른 '제목 환각'

기존 cite_lookup.py의 confirmed/refuted/unverified는 "ID가 실재하나?"만 답한다(mismatch 판정은
호출측이 하라고 docstring에 명시됨). 이 파일이 그 mismatch 판정을 결정론화한다.

verdict 등급:
  valid        — ID 실재 + 청구 제목·저자·연도가 조회결과와 일치
  partial      — ID 실재 + 일부 메타 근접(near-miss) — 오타/판본차 의심(hallmark near_miss_title 대응)
  content_mismatch — ID 실재하나 청구 메타가 명백히 다름 — 실재 DOI에 엉뚱한 제목/저자 붙인 환각
  hallucinated — ID 자체가 refuted(없음)
  uncertain    — 조회불가(unverified) 또는 ID 없이 제목만 → OpenAlex fuzzy 후보 제시

사용:
  python3 cite_verdict.py DOI 10.1/x --title "..." --author "Smith" --year 2020
  python3 cite_verdict.py --title "..." --author "Smith"        # ID 없음 → OpenAlex fuzzy
출력: JSON {verdict, subtests{...}, lookup{...}, candidates[...]}
"""
import sys, os, json, re, subprocess, urllib.request, urllib.parse

MAILTO = "you@example.com"
_here = os.path.dirname(os.path.abspath(__file__))
CITE_LOOKUP = os.path.expanduser("~/.claude/scripts/cite_lookup.py")
for _c in (os.path.join(_here, "cite_lookup.py"), CITE_LOOKUP):
    if os.path.exists(_c):  # 같은 디렉토리(라이브 scripts/) 우선, 없으면 라이브 경로
        CITE_LOOKUP = _c
        break

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _norm(s):
    """소문자·문장부호제거·공백정규화 — 제목 비교 canonical form."""
    return _WS.sub(" ", _PUNCT.sub(" ", (s or "").lower())).strip()


def _tokens(s):
    return set(_norm(s).split())


def _jaccard(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _title_sim(claimed, raw):
    """대칭 jaccard + claimed기준 containment 동시 반환.
    결함 C 수정: 축약인용(claimed⊂raw, 예 'Deep learning'⊂'Deep learning for X')은
    jaccard가 낮지만 containment≈1.0 → content_mismatch 오판 방지."""
    tc, tr = _tokens(claimed), _tokens(raw)
    if not tc or not tr:
        return 0.0, 0.0
    j = len(tc & tr) / len(tc | tr)
    cont = len(tc & tr) / len(tc)  # claimed 토큰이 raw에 얼마나 포함되나
    return j, cont


def _author_match(claimed, found):
    """청구 저자와 조회 저자가 성(토큰)을 공유하는가.
    양방향 토큰 교집합 — Crossref는 family만("LeCun"), OpenAlex는 풀네임("Ashish Vaswani")을
    주므로 'in' 단방향은 방향 버그가 남. 교집합이면 first-author 성 공유로 판정.
    (흔한 성 동명이인 FP 가능하나 인용검증 목적엔 허용 — 최종은 사람게이트)."""
    if not claimed or not found:
        return None  # 판정 불가 → 서브테스트 제외
    ct, ft = _tokens(claimed), _tokens(found)
    if not ct or not ft:
        return None
    return bool(ct & ft)


def run_cite_lookup(ctype, value):
    """기존 결정론 조회기 재사용 (RA폴백·텔레메트리 그대로 활용)."""
    try:
        p = subprocess.run([sys.executable, CITE_LOOKUP, ctype, value],
                           capture_output=True, text=True, timeout=40)
        return json.loads(p.stdout.strip())
    except Exception as e:
        return {"status": "unverified", "found": f"cite_lookup 실행실패: {e}", "source": ""}


def openalex_fuzzy(title, author=None, k=3):
    """ID 없는 인용의 제목 fuzzy 검색 (citation-detection의 OpenAlex 소스).
    정확 ID 조회가 불가한 인용을 '실재 후보'와 대조 — 완전 날조 vs 실재 구분."""
    q = urllib.parse.quote(title)
    url = f"https://api.openalex.org/works?filter=title.search:{q}&per_page={k}&mailto={MAILTO}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"cite-verdict/1.0 (mailto:{MAILTO})"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"error": f"OpenAlex 조회실패: {e}", "candidates": []}
    cands = []
    for w in d.get("results", [])[:k]:
        wt = w.get("display_name") or ""
        sim = _jaccard(title, wt)
        a1 = ""
        auths = w.get("authorships") or []
        if auths:
            a1 = (auths[0].get("author") or {}).get("display_name", "")
        cands.append({"title": wt, "sim": round(sim, 3), "author1": a1,
                      "doi": w.get("doi"), "year": w.get("publication_year")})
    return {"candidates": cands}


def verdict(ctype, value, claimed_title=None, claimed_author=None, claimed_year=None):
    # ── ID 없는 인용 → OpenAlex fuzzy 경로 ──
    if not ctype or not value:
        if not claimed_title:
            return {"verdict": "uncertain", "reason": "ID·제목 둘 다 없음", "subtests": {}, "candidates": []}
        oa = openalex_fuzzy(claimed_title, claimed_author)
        cands = oa.get("candidates", [])
        best = cands[0] if cands else None
        best_sim = best["sim"] if best else 0.0
        subtests = {"title_exists": best_sim >= 0.5}
        # 결함 A/D 수정: 최고후보의 저자·연도도 대조 (제목만 맞으면 valid 금지)
        if best and claimed_author:
            am = _author_match(claimed_author, best.get("author1", ""))
            if am is not None:
                subtests["author_match"] = am
        if best and claimed_year and best.get("year"):
            try:
                subtests["year_match"] = int(claimed_year) == int(best["year"])
            except Exception:
                pass
        meta = [v for k, v in subtests.items() if isinstance(v, bool) and k != "title_exists"]
        if best_sim < 0.5:
            v, why = "uncertain", "OpenAlex 후보 약함 (G4: 없다고 단정 못함)"
            if cands:  # agy 지적 부분수용: 후보는 있으나 약함을 신호
                subtests["low_confidence"] = True
        elif meta and not all(meta):
            v, why = "content_mismatch", "제목 근접하나 저자/연도 불일치 (하이재킹/환각 의심)"
        elif best_sim >= 0.9:
            # 제목 강일치. 메타 대조가 있어야 valid, 없으면 저자검증 안 됐으니 partial (cdx 우려 반영)
            v = "valid" if meta else "partial"
            why = "제목·메타 일치" if meta else "제목 강일치·청구저자 미제공(저자 미검증)"
        else:
            v, why = "partial", "제목 근접 (0.5≤sim<0.9)"
        return {"verdict": v, "reason": f"ID없음·최고sim={best_sim}·{why}",
                "subtests": subtests, "lookup": oa, "candidates": cands}

    # ── ID 있는 인용 → 결정론 조회 ──
    lk = run_cite_lookup(ctype, value)
    st = lk.get("status")

    if st == "refuted":
        return {"verdict": "hallucinated", "reason": lk.get("found"),
                "subtests": {"id_resolves": False}, "lookup": lk}
    if st == "unverified":
        return {"verdict": "uncertain", "reason": lk.get("found"),
                "subtests": {"id_resolves": None}, "lookup": lk}

    # confirmed → 필드별 서브테스트 벡터 (hallmark 방식)
    subtests = {"id_resolves": True}
    r_title = lk.get("raw_title")
    r_author1 = lk.get("raw_author1")
    r_year = lk.get("raw_year")

    title_sim = title_cont = None
    title_unverifiable = False
    if claimed_title:
        if r_title:
            title_sim, title_cont = _title_sim(claimed_title, r_title)
            subtests["title_sim"] = round(title_sim, 3)
            subtests["title_containment"] = round(title_cont, 3)
            subtests["title_match"] = title_sim >= 0.9
        else:
            # 결함 B 수정: RA폴백 메타협상 실패 등으로 raw_title 부재 → 제목 검증불가
            subtests["title_match"] = None
            title_unverifiable = True
    if claimed_author is not None:
        am = _author_match(claimed_author, r_author1)
        if am is not None:
            subtests["author_match"] = am
    if claimed_year and r_year:
        try:
            subtests["year_match"] = int(claimed_year) == int(r_year)
        except Exception:
            pass

    checks = [v for k, v in subtests.items() if isinstance(v, bool) and k != "id_resolves"]

    # 결함 B 수정: 제목 검증불가 & 다른 확증 없음 → valid 단정 금지
    if title_unverifiable and not any(checks):
        return {"verdict": "uncertain", "reason": "ID 실재하나 raw 제목 부재로 청구제목 검증불가",
                "subtests": subtests, "lookup": lk}

    if not checks:
        # gemini 지적 부분수용: ID만 확인, 청구메타 전무 → valid이되 '내용 미검증' 명시
        return {"verdict": "id_verified_only", "reason": "ID 실재 (청구 메타 미제공 — 내용 미검증)",
                "subtests": subtests, "lookup": lk}
    if all(checks):
        v = "valid"
    # 결함 C 수정: jaccard 근접(0.5~0.9) 또는 축약인용(containment≥0.9) + 저자 명시일치 → partial
    # partial author None 수정: is not False → is True (저자 미제공 시 partial 못 감)
    elif ((title_sim is not None and 0.5 <= title_sim < 0.9)
           or (title_cont is not None and title_cont >= 0.9)) \
            and subtests.get("author_match") is True:
        v = "partial"
    else:
        v = "content_mismatch"  # 실재 ID인데 청구 메타 명백 불일치 (제목/저자 환각)
    return {"verdict": v, "reason": f"서브테스트 {sum(checks)}/{len(checks)} 통과",
            "subtests": subtests, "lookup": lk}


def main():
    args = sys.argv[1:]
    ctype = value = None
    claimed = {"title": None, "author": None, "year": None}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--title":
            claimed["title"] = args[i + 1]; i += 2
        elif a == "--author":
            claimed["author"] = args[i + 1]; i += 2
        elif a == "--year":
            claimed["year"] = args[i + 1]; i += 2
        else:
            pos.append(a); i += 1
    if len(pos) >= 2:
        ctype, value = pos[0].upper(), pos[1]
    res = verdict(ctype, value, claimed["title"], claimed["author"], claimed["year"])
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
