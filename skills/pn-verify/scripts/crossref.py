#!/usr/bin/env python3
"""Crossref 조회 — DOI 검증 또는 논문 검색. 무가입.
용법:
  python3 crossref.py doi 10.1117/12.2304117      # DOI 실재 검증
  python3 crossref.py search "bolt preload relaxation vibration 2024"  # 검색→후보 반환
G4 연동: 기억으로 DOI/인용 생성 금지. 이 스크립트로 조회된 것만 인용.
"""
import sys, json, urllib.request, urllib.parse, os

MAILTO = os.environ.get("CROSSREF_MAILTO", "you@example.com")  # polite pool
BASE = "https://api.crossref.org/works"
UA = f"pn-verify/1.0 (mailto:{MAILTO})"

def get(url, accept=None):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def doi_fallback(doi):
    """Crossref 404 ≠ 날조. DataCite 등 타 등록기관(RA) DOI는 Crossref에 없다
    (실측 FP: 10.5281/zenodo.* → Crossref 404, doi.org 200). RA 조회 후 판정."""
    try:
        ra = get(f"https://doi.org/ra/{urllib.parse.quote(doi)}")
        agency = ra[0].get("RA") if isinstance(ra, list) and ra else None
    except Exception:
        agency = None
    if not agency:
        return False
    try:
        m = get(f"https://doi.org/{urllib.parse.quote(doi)}",
                accept="application/vnd.citationstyles.csl+json")
        title = m.get("title", "(제목 없음)")
        year = (m.get("issued", {}).get("date-parts", [[None]]) or [[None]])[0][0]
        pub = m.get("publisher", "")
        print(f"✅ DOI 실재 확인 (등록기관: {agency}, Crossref 밖):")
        print(f"- ({year}). \"{title}.\" {pub}. DOI: {doi}")
    except Exception:
        print(f"⚠️ DOI 실재 (등록기관: {agency}, Crossref 밖) — 메타데이터 협상 실패, "
              f"서지는 https://doi.org/{doi} 직접 확인")
    return True

def fmt(item):
    authors = item.get("author", []) or []
    aus = ", ".join(f"{a.get('family','')}" for a in authors[:4]) or "(저자 미상)"
    if len(authors) > 4:
        aus += " et al."
    title = (item.get("title") or ["(제목 없음)"])[0]
    year = (item.get("issued", {}).get("date-parts", [[None]]) or [[None]])[0][0]
    cont = (item.get("container-title") or [""])[0]
    doi = item.get("DOI", "")
    return f"- {aus} ({year}). \"{title}.\" {cont}. DOI: {doi}"

def main():
    if len(sys.argv) < 3:
        sys.exit("용법: crossref.py doi <DOI> | crossref.py search <질의>")
    mode, arg = sys.argv[1], " ".join(sys.argv[2:])
    try:
        if mode == "doi":
            url = f"{BASE}/{urllib.parse.quote(arg)}"
            try:
                d = get(url)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    if not doi_fallback(arg):
                        print(f"❌ DOI 미존재(Crossref 404 + RA 미등록): {arg} → 인용 금지/날조 의심")
                    return
                raise
            print("✅ DOI 실재 확인:")
            print(fmt(d["message"]))
        elif mode == "search":
            q = urllib.parse.urlencode({"query.bibliographic": arg, "rows": 5,
                                        "select": "DOI,title,author,issued,container-title"})
            d = get(f"{BASE}?{q}")
            items = d["message"]["items"]
            if not items:
                print(f"⚠️ 검색 결과 없음: '{arg}' → 해당 논문 인용 불가(없음으로 확정)")
                return
            print(f"🔎 후보 {len(items)}건 (이 중 일치하는 것만 인용, 없으면 인용 회피):")
            for it in items:
                print(fmt(it))
        else:
            sys.exit("mode는 doi 또는 search")
    except Exception as e:
        sys.exit(f"[조회 실패] {e} — 실패 시 '미검증'으로 표기, 날조 금지")

if __name__ == "__main__":
    main()
