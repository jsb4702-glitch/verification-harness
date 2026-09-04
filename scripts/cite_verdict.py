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
  python3 cite_verdict.py ARXIV 2409.15771 --year 2025 --venue "ICLR"  # 학회연도=게재처 축
  python3 cite_verdict.py --title "..." --author "Smith"        # ID 없음 → OpenAlex fuzzy
출력: JSON {verdict, subtests{...}, lookup{...}, candidates[...]}

2026-07-25 거짓반증 수리(wf_69bfc458 동클래스 — cite_lookup 신규 필드 반영):
  저자 = raw_authors 전체 목록 대조(전체 목록 어디에도 없을 때만 불일치. 종전 raw_author1
         단독 대조는 공저자 인용을 content_mismatch로 오판).
  연도 = raw_year(제출)·raw_year_updated(최근판) 2축 허용. 학회연도(venue year)는 별개 축 —
         게재처 단서(raw_comment=arXiv / raw_journal=DOI)에 청구 학회명 확인되면 일치,
         단서 부재면 불일치 단정 대신 판정보류(year_match=null).
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
    """청구 저자가 조회 저자 '전체 목록'과 성(토큰)을 공유하는가.
    거짓반증 수리(2026-07-25): 제1저자만 대조하면 공저자 인용("Morstatter")을 불일치로
    오판 → found는 전체 목록(raw_authors) 우선, 문자열(단일 저자)도 허용.
    양방향 토큰 교집합 — Crossref는 family만("LeCun"), OpenAlex는 풀네임("Ashish Vaswani")을
    주므로 'in' 단방향은 방향 버그가 남. 전체 목록 어디에도 토큰 공유가 없을 때만 False.
    (흔한 성 동명이인 FP 가능하나 인용검증 목적엔 허용 — 최종은 사람게이트)."""
    if not claimed or not found:
        return None  # 판정 불가 → 서브테스트 제외
    if isinstance(found, str):
        found = [found]
    ct = _tokens(claimed)
    ft = set().union(*(_tokens(f) for f in found))
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


def verdict(ctype, value, claimed_title=None, claimed_author=None, claimed_year=None,
            claimed_venue=None):
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
    r_year_upd = lk.get("raw_year_updated")

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
        # 거짓반증 수리: 전체 목록(raw_authors) 우선 대조, 구버전/RA폴백 응답은 raw_author1 폴백
        am = _author_match(claimed_author, lk.get("raw_authors") or r_author1)
        if am is not None:
            subtests["author_match"] = am
    if claimed_year and (r_year or r_year_upd):
        try:
            cy = int(claimed_year)
            ym = cy in [int(y) for y in (r_year, r_year_upd) if y is not None]
        except Exception:
            ym = "unparsable"  # 연도 파싱불가 → 서브테스트 제외 (종전 거동 유지)
        if ym is False:
            # 학회연도(venue year)는 제출연도와 별개 축(2026-07-25 수리): 게재처 단서에
            # 청구 학회명이 확인되면 일치, 단서 부재면 불일치가 아니라 판정보류(null).
            evidence = " ".join(x for x in (lk.get("raw_comment"), lk.get("raw_journal")) if x)
            vt = _tokens(claimed_venue) if claimed_venue else set()
            if vt:
                if evidence and vt <= _tokens(evidence):
                    ym = True
                    subtests["year_note"] = "제출·최근판연도와 불일치하나 게재처 확인 — 학회연도 축 일치"
                else:
                    ym = None
                    subtests["year_note"] = "제출·최근판연도 불일치·게재처 단서 미확인 — 불일치 단정 금지(판정보류)"
        if ym != "unparsable":
            subtests["year_match"] = ym

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


SHADOW_LOG = os.path.expanduser("~/.claude/logs/cite_verdict_shadow.jsonl")


def _shadow_log(ctype, value, claimed, res):
    """실행될 때마다 판정을 남긴다 — 승급 판정에 쓸 실사용 데이터.

    2026-07-26 신설. 이 판정기는 citation-verify 워크플로에 미배선이라 실사용이 0건이었고,
    데이터가 없으니 승급 판정을 못 하고, 판정을 못 하니 배선을 안 하는 순환에 갇혀 있었다.
    호출측이 아니라 여기서 남기는 이유: 누가 어떤 경로로 부르든 데이터가 쌓인다.

    판정 자체에는 영향이 없다(섀도). 기록 실패도 판정을 막지 않는다.
    인용 식별자와 등급만 남긴다 — 청구 제목·저자 원문은 남기지 않는다(로그 비대·불필요).
    """
    try:
        import datetime
        os.makedirs(os.path.dirname(SHADOW_LOG), exist_ok=True)
        row = {
            "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": ctype,
            "value": value,
            "verdict": res.get("verdict"),
            "subtests": res.get("subtests"),
            "has_claim": {k: bool(v) for k, v in claimed.items()},
        }
        with open(SHADOW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass          # 계측 실패가 판정을 막지 않는다


def main():
    args = sys.argv[1:]
    ctype = value = None
    claimed = {"title": None, "author": None, "year": None, "venue": None}
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
        elif a == "--venue":
            claimed["venue"] = args[i + 1]; i += 2
        else:
            pos.append(a); i += 1
    if len(pos) >= 2:
        ctype, value = pos[0].upper(), pos[1]
    res = verdict(ctype, value, claimed["title"], claimed["author"], claimed["year"],
                  claimed["venue"])
    _shadow_log(ctype, value, claimed, res)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
