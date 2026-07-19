#!/usr/bin/env python3
"""Mouser 부품 검증/검색 — Search API v1.0 (apiKey 쿼리파람, OAuth 불요).
필요 환경변수(발급 후 ~/.zshrc에 export):
  MOUSER_API_KEY
발급(무료): My Mouser 계정 로그인 → https://www.mouser.com/api-hub/ →
  "Search API" 신청 폼 작성 → 키 즉시 발급. 결제정보 불요.
용법:
  python3 mouser.py "STM32F407" [--limit 5]        # 키워드 검색
  python3 mouser.py --pn "595-TLV2372IDR"          # Mouser PN 정확검색
G4 연동: 부품 PN은 기억 인용 금지. 이 조회로 실재 확인된 것만 인용.
엔드포인트/필드명 출처: sparkmicro/mouser-api 소스 + api.mouser.com 문서.
"""
import os, sys, json, argparse, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("MOUSER_API_KEY")
BASE = "https://api.mouser.com/api/v1.0"


def call(path, body):
    url = f"{BASE}{path}?apiKey={urllib.parse.quote(KEY)}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def show(parts, q):
    if not parts:
        print(f"⚠️ Mouser 결과 없음: '{q}' → 미등재/단종 가능. 인용 회피 또는 타 벤더 확인")
        return
    print(f"🔎 Mouser 후보 {len(parts)}건 (실재 확인된 것만 인용):")
    for p in parts:
        mpn = p.get("ManufacturerPartNumber") or "?"
        mfr = p.get("Manufacturer") or "?"
        desc = p.get("Description") or ""
        avail = p.get("Availability") or "?"
        breaks = p.get("PriceBreaks") or []
        price = ""
        if breaks:
            b = breaks[0]
            price = f" | {b.get('Price','?')}@{b.get('Quantity','?')}"
        print(f"- {mpn} | {mfr} | {desc} | 재고:{avail}{price}")


def main():
    if not KEY:
        sys.exit("[미설정] MOUSER_API_KEY 없음 → mouser.com/api-hub 에서 무료 발급 후 "
                 "~/.zshrc에 export MOUSER_API_KEY=... (현재 조회 불가)")
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*", help="키워드")
    ap.add_argument("--pn", help="Mouser PN 정확검색")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()

    try:
        if a.pn:
            d = call("/search/partnumber", {
                "SearchByPartRequest": {
                    "mouserPartNumber": a.pn, "partSearchOptions": "None"}})
            q = a.pn
        else:
            q = " ".join(a.query)
            if not q:
                sys.exit("용법: mouser.py <키워드> 또는 --pn <MouserPN>")
            d = call("/search/keyword", {
                "SearchByKeywordRequest": {
                    "keyword": q, "records": a.limit, "startingRecord": 0,
                    "searchOptions": "None", "searchWithYourSignUpLanguage": "en"}})
    except urllib.error.HTTPError as e:
        sys.exit(f"[조회 실패 {e.code}] {e.read().decode()[:200]} — 키/쿼터 확인")
    except urllib.error.URLError as e:
        sys.exit(f"[연결 실패] {e}")

    errs = d.get("Errors") or []
    if errs:
        print(f"⚠️ API Errors: {json.dumps(errs, ensure_ascii=False)[:200]}")
    parts = (d.get("SearchResults") or {}).get("Parts", [])
    show(parts, q)


if __name__ == "__main__":
    main()
