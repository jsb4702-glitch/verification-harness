#!/usr/bin/env python3
"""인용 결정론 조회기 — DOI(Crossref) / arXiv(export API) / CVE(NVD) 실재 확인.
G4 "조회 강제": 기억·추정 금지, 공개 API 실호출 결과만 반환.
사용: python3 cite_lookup.py <DOI|arXiv|CVE> <value>
출력: stdout에 JSON {type,value,status,found,source,raw_*}.
  status: confirmed=실재 / refuted=존재안함(404·0건) / unverified=조회불가(네트워크·파싱실패)
주의: claimed 메타데이터와의 '불일치(mismatch)' 판정은 호출측(에이전트)이 found와 대조해 수행.
텔레메트리: 매 조회를 TELEMETRY(JSONL)에 append — type·status·지연·ts. 평가검증용(cite_lookup_report.py).
"""
import sys, json, os, time, urllib.request, urllib.parse, urllib.error, re

MAILTO = "you@example.com"  # Crossref polite pool
TIMEOUT = 25
TELEMETRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cite_lookup_telemetry.jsonl")
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.I)


def out(d):
    print(json.dumps(d, ensure_ascii=False))
    sys.exit(0)


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": f"cite-lookup/1.0 (mailto:{MAILTO})"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace"), r.status


def _doi_ra_fallback(doi):
    """Crossref 404 ≠ refuted. DataCite 등 타 등록기관(RA) DOI는 Crossref 미등록
    (실측 FP 2026-07-09: 10.5281/zenodo.* → Crossref 404, doi.org 200). RA 조회 후 확정."""
    try:
        body, _ = fetch(f"https://doi.org/ra/{urllib.parse.quote(doi)}")
        ra = json.loads(body)
        agency = ra[0].get("RA") if isinstance(ra, list) and ra else None
    except Exception:
        return {"status": "unverified", "found": "Crossref 404 + RA 조회실패 — 판정불가", "source": "doi.org/ra"}
    if not agency:
        return {"status": "refuted", "found": "없음 (Crossref 404 + RA 미등록 DOI)", "source": "api.crossref.org+doi.org/ra"}
    try:
        body, _ = fetch(f"https://doi.org/{urllib.parse.quote(doi)}",
                        headers={"User-Agent": f"cite-lookup/1.0 (mailto:{MAILTO})",
                                 "Accept": "application/vnd.citationstyles.csl+json"})
        m = json.loads(body)
        title = m.get("title", "(제목없음)")
        year = (m.get("issued", {}).get("date-parts", [[None]]) or [[None]])[0][0]
        return {"status": "confirmed", "found": f"제목='{title}' / 연도={year} / 등록기관={agency}(Crossref 밖)",
                "source": f"doi.org({agency})", "raw_title": title, "raw_year": year}
    except Exception:
        return {"status": "confirmed", "found": f"실재 (등록기관={agency}, Crossref 밖) — 메타데이터 협상 실패, 서지는 doi.org 직접확인",
                "source": f"doi.org/ra({agency})"}


def lookup_doi(value):
    doi = value.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}?mailto={MAILTO}"
    try:
        body, status = fetch(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _doi_ra_fallback(doi)
        return {"status": "unverified", "found": f"HTTP {e.code}", "source": "api.crossref.org"}
    except Exception as e:
        return {"status": "unverified", "found": f"조회실패: {e}", "source": "api.crossref.org"}
    try:
        m = json.loads(body)["message"]
        title = (m.get("title") or ["(제목없음)"])[0]
        year = (m.get("published", {}).get("date-parts", [[None]]) or [[None]])[0][0]
        authors = m.get("author") or []
        a1 = (authors[0].get("family", "") if authors else "")
        journal = (m.get("container-title") or [""])[0]
        found = f"제목='{title}' / 저자1={a1} / 연도={year} / 저널={journal}"
        return {"status": "confirmed", "found": found, "source": "api.crossref.org",
                "raw_title": title, "raw_year": year, "raw_author1": a1, "raw_journal": journal}
    except Exception as e:
        return {"status": "unverified", "found": f"파싱실패: {e}", "source": "api.crossref.org"}


def lookup_arxiv(value):
    aid = value.strip().replace("arXiv:", "").replace("arxiv:", "")
    aid = re.sub(r"^https?://arxiv\.org/abs/", "", aid)
    url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(aid)}"
    try:
        body, status = fetch(url)
    except Exception as e:
        return {"status": "unverified", "found": f"조회실패: {e}", "source": "export.arxiv.org"}
    total = re.search(r"<opensearch:totalResults[^>]*>(\d+)</opensearch:totalResults>", body)
    if total and total.group(1) == "0":
        return {"status": "refuted", "found": "없음 (arXiv 0건 — 미등록 ID)", "source": "export.arxiv.org"}
    entry = re.search(r"<entry>(.*?)</entry>", body, re.S)
    if not entry:
        return {"status": "refuted", "found": "없음 (entry 부재)", "source": "export.arxiv.org"}
    e = entry.group(1)
    title = re.search(r"<title>(.*?)</title>", e, re.S)
    title = re.sub(r"\s+", " ", title.group(1)).strip() if title else "(제목없음)"
    if title.lower().startswith("error"):
        return {"status": "refuted", "found": f"없음 (arXiv error: {title})", "source": "export.arxiv.org"}
    pub = re.search(r"<published>(\d{4})", e)
    year = pub.group(1) if pub else None
    a1 = re.search(r"<author>\s*<name>(.*?)</name>", e, re.S)
    a1 = a1.group(1).strip() if a1 else ""
    found = f"제목='{title}' / 저자1={a1} / 연도={year}"
    return {"status": "confirmed", "found": found, "source": "export.arxiv.org",
            "raw_title": title, "raw_year": year, "raw_author1": a1}


def lookup_cve(value):
    cid = value.strip().upper()
    if not CVE_RE.match(cid):
        return {"status": "unverified", "found": f"CVE-ID 형식오류('{value}') — CVE-YYYY-NNNN+ 필요",
                "source": "services.nvd.nist.gov"}
    url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={urllib.parse.quote(cid)}"
    try:
        body, status = fetch(url, {"User-Agent": "cite-lookup/1.0"})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "refuted", "found": "없음 (NVD 404 — 미등록 CVE)", "source": "services.nvd.nist.gov"}
        if e.code == 403:
            return {"status": "unverified", "found": "HTTP 403 (NVD rate-limit — 30초후 재시도/무료키)", "source": "services.nvd.nist.gov"}
        return {"status": "unverified", "found": f"HTTP {e.code}", "source": "services.nvd.nist.gov"}
    except Exception as e:
        return {"status": "unverified", "found": f"조회실패: {e}", "source": "services.nvd.nist.gov"}
    try:
        d = json.loads(body)
        if d.get("totalResults", 0) == 0 or not d.get("vulnerabilities"):
            return {"status": "refuted", "found": "없음 (NVD 0건)", "source": "services.nvd.nist.gov"}
        cve = d["vulnerabilities"][0]["cve"]
        desc = next((x["value"] for x in cve.get("descriptions", []) if x.get("lang") == "en"), "(설명없음)")
        desc = re.sub(r"\s+", " ", desc)[:180]
        # CVSS: v3.1 우선, 없으면 v3.0/v2
        metrics = cve.get("metrics", {})
        score, sev, vec = None, None, None
        for k in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if metrics.get(k):
                cd = metrics[k][0]["cvssData"]
                score = cd.get("baseScore"); sev = cd.get("baseSeverity") or metrics[k][0].get("baseSeverity"); vec = cd.get("vectorString")
                break
        cwes = []
        for w in cve.get("weaknesses", []):
            for de in w.get("description", []):
                if de.get("value", "").startswith("CWE-"):
                    cwes.append(de["value"])
        cwes = sorted(set(cwes))
        found = f"CVSS={score}({sev}) / CWE={','.join(cwes) or '없음'} / desc='{desc}'"
        return {"status": "confirmed", "found": found, "source": "services.nvd.nist.gov",
                "raw_cvss": score, "raw_severity": sev, "raw_vector": vec, "raw_cwe": cwes, "raw_desc": desc}
    except Exception as e:
        return {"status": "unverified", "found": f"파싱실패: {e}", "source": "services.nvd.nist.gov"}


def log_telemetry(rec):
    try:
        with open(TELEMETRY, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 텔레메트리 실패가 조회를 막지 않음


def main():
    if len(sys.argv) < 3:
        out({"status": "unverified", "found": "사용법: cite_lookup.py <DOI|arXiv|CVE> <value>", "source": ""})
    ctype, value = sys.argv[1].upper(), sys.argv[2]
    t0 = time.time()
    if ctype == "DOI":
        res = lookup_doi(value)
    elif ctype in ("ARXIV", "ARX"):
        res = lookup_arxiv(value)
    elif ctype == "CVE":
        res = lookup_cve(value)
    else:
        res = {"status": "unverified", "found": f"결정론 조회 미지원 종류({ctype}) — agent+web 경로 사용", "source": ""}
    res.update({"type": ctype, "value": value})
    log_telemetry({"ts": round(time.time()), "type": ctype, "value": value,
                   "status": res.get("status"), "source": res.get("source", ""),
                   "latency_ms": round((time.time() - t0) * 1000)})
    out(res)


if __name__ == "__main__":
    main()
