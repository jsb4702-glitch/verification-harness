---
name: pn-verify
description: DOI·논문·부품 PN을 외부 권위 소스로 실조회해 실재 확인(G4 "회피→조회확정"). "DOI 확인", "이 논문 진짜 있나", "부품번호 검증", "PN 조회", "논문 찾아줘", "인용 검증" 또는 DOI/풀PN을 인용하기 직전 호출. 기억 인용 금지·조회된 것만 인용.
---

# pn-verify — DOI/부품 실조회 검증

G4(날조차단)를 "지어내지 마"에서 "**조회해서 확정**"으로 승격. DOI·PN은 기억으로 답하지 말고 아래로 대조.

## 1. DOI / 논문 (Crossref, 무가입·작동)
```
python3 scripts/crossref.py doi <DOI>          # 실재 검증(404=날조)
python3 scripts/crossref.py search "<질의>"     # 후보 반환→일치만 인용
```
- 검색 결과 없음 = "해당 논문 없음"으로 확정(인용 회피). 후보 중 정확 일치만 인용.

## 2. 상용부품 COTS (DigiKey — 키 필요)
```
python3 scripts/digikey.py "<PN 또는 검색어>"
```
- 환경변수 `DIGIKEY_CLIENT_ID`/`DIGIKEY_CLIENT_SECRET` 필요(developer.digikey.com 무료등록).
- 결과 없음 = COTS 미등재 → 단종/특주 의심, 제조사 공식채널 확인으로.

## 3. 상용부품 COTS (Mouser — 키 필요)
```
python3 scripts/mouser.py "<검색어>" [--limit 5]   # 키워드
python3 scripts/mouser.py --pn "<Mouser PN>"        # PN 정확검색
```
- 환경변수 `MOUSER_API_KEY` 필요. 무료발급: My Mouser 로그인 → mouser.com/api-hub → Search API 폼 → 키 즉시발급(결제 불요).
- 엔드포인트 `api.mouser.com/api/v1.0/search/{keyword,partnumber}?apiKey=` (POST). 결과 없음 = 미등재/단종.

## 4. 상용부품 보조 (Arrow — 미활성)
```
python3 scripts/arrow.py "<검색어>"
```
- `ARROW_API_KEY` + 엔드포인트 확정(`ARROW_BASE`,`ARROW_VERIFIED=1`) 후 활성. 미확정 시 날조방지로 차단됨.

## 5. 미스미 / 나비엠알오 (공개 API 없음 → site-extract 스크래핑)
- 둘 다 공개 REST API 없음. `site-extract` 스킬로 폴백.
- **미스미(kr.misumi-ec.com)**: ✅ **site-extract `jina` 모드로 가능**(2026-06 검증). robots `*:Disallow:/`라 직접/stealth는 막히지만, Jina Reader 프록시(브라우저엔진)가 서버사이드 렌더로 우회. 가격 공개·인증불요.
  ```
  SK=~/.claude/skills/site-extract
  Q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "베어링")
  "$SK/venv/bin/python" "$SK/fetch.py" \
      "https://kr.misumi-ec.com/vona2/result/?Keyword=$Q" \
      --mode jina --jina-target '#seriesListContents' --ignore-robots --max-chars 60000
  ```
  - `--jina-target '#seriesListContents'` = 상품그리드만 반환(토큰 7.6K→4K, 47%↓). 검색결과 컨테이너 id.
  - ⚠️ ToS 그레이존(Jina=제3자 프록시) → 저빈도 개인 리서치만, 벌크 ❌. 안정성은 `JINA_API_KEY` env로.
- **나비엠알오(navimro.com)**: ✅ 검증완료(2026-06). robots 허용, static 0.4초 추출.
  ```
  SK=~/.claude/skills/site-extract
  Q=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "베어링")
  "$SK/venv/bin/python" "$SK/fetch.py" "https://www.navimro.com/s/q-$Q/" \
      --mode static --css '.item__title' --css '.item__brand'
  ```
  - 검색 URL: `https://www.navimro.com/s/q-<URL인코딩 쿼리>/` (정식 패턴, robots OK)
  - 셀렉터: 상품명 `.item__title`, 브랜드 `.item__brand`, 상세링크 `/g/<id>`
  - ⚠️ **가격·재고는 로그인벽**(기업전용가) → 비로그인 추출 시 가격 "미확인". 인증우회 금지(G11/ToS).

## ⚠️ 도메인 한계 (정직)
- 위 API는 **COTS·학술** 커버. 특수/비공개 PN 체계는 미커버 → 해당 발행기관 공식 검색 안내로 대체(추정생성 금지).
- 조회 실패 시 답: "미검증 — 조회 불가" (날조 금지). 절대 기억으로 PN/DOI 메우지 말 것.
