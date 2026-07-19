#!/usr/bin/env python3
"""DigiKey 부품 검증 — OAuth2 client_credentials → 키워드 검색(V4).
필요 환경변수(발급 후 ~/.zshrc에 export):
  DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET
발급: https://developer.digikey.com → 앱 생성 → Product Information V4 구독.
용법: python3 digikey.py "LM317" 또는 정확 PN
G4 연동: 부품 PN은 기억 인용 금지. 이 조회로 실재 확인된 것만.
"""
import os, sys, json, urllib.request, urllib.parse, urllib.error

CID = os.environ.get("DIGIKEY_CLIENT_ID")
SEC = os.environ.get("DIGIKEY_CLIENT_SECRET")
if not (CID and SEC):
    sys.exit("[미설정] DIGIKEY_CLIENT_ID/SECRET 없음 → developer.digikey.com 등록 후 ~/.zshrc에 export. (현재 조회 불가)")
if len(sys.argv) < 2:
    sys.exit("용법: digikey.py <검색어 또는 PN>")

TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

def token():
    body = urllib.parse.urlencode({
        "client_id": CID, "client_secret": SEC,
        "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]

def main():
    try:
        tok = token()
    except urllib.error.HTTPError as e:
        sys.exit(f"[토큰 실패 {e.code}] {e.read().decode()[:200]} — 키 확인 필요")
    q = " ".join(sys.argv[1:])
    body = json.dumps({"Keywords": q, "Limit": 5, "Offset": 0}).encode()
    req = urllib.request.Request(SEARCH_URL, data=body, headers={
        "Authorization": f"Bearer {tok}", "X-DIGIKEY-Client-Id": CID,
        "Content-Type": "application/json", "X-DIGIKEY-Locale-Site": "US",
        "X-DIGIKEY-Locale-Currency": "USD"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"[검색 실패 {e.code}] {e.read().decode()[:200]}")
    products = d.get("Products", [])
    if not products:
        print(f"⚠️ DigiKey 결과 없음: '{q}' → COTS 미등재(단종/특주 가능). 인용 회피 또는 제조사 공식채널 확인")
        return
    print(f"🔎 DigiKey 후보 {len(products)}건 (실재 확인된 것만 인용):")
    for p in products:
        mpn = p.get("ManufacturerProductNumber", "?")
        mfr = (p.get("Manufacturer") or {}).get("Name", "?")
        desc = (p.get("Description") or {}).get("ProductDescription", "")
        print(f"- {mpn} | {mfr} | {desc}")

if __name__ == "__main__":
    main()
