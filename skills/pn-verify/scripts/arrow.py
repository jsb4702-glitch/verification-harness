#!/usr/bin/env python3
"""Arrow 부품 검증 — 골격(ENDPOINT 미확인 상태).
⚠️ 솔직 고지: Arrow API의 정확한 base URL·인증헤더·검색 경로를 빌드시점에 확정 못 함(🔴).
   가짜 엔드포인트를 박으면 G4(날조) 위반이라 의도적으로 막아둠.

활성화 절차:
  1) Arrow 개발자/파트너 API 접근 신청 → API 키 수령.
  2) 받은 개발자 문서에서 ENDPOINT/AUTH 확인 후 아래 ARROW_BASE/헤더 채우기.
  3) ARROW_VERIFIED=1 환경변수로 잠금 해제.
필요 환경변수: ARROW_API_KEY (+ 확인 후 ARROW_VERIFIED=1)
"""
import os, sys, json, urllib.request, urllib.parse, urllib.error

KEY = os.environ.get("ARROW_API_KEY")
VERIFIED = os.environ.get("ARROW_VERIFIED") == "1"

# TODO(사용자): Arrow 개발자 문서로 확정 후 교체. 현재는 미확인 placeholder.
ARROW_BASE = os.environ.get("ARROW_BASE", "")   # 예: 문서에서 확인된 검색 엔드포인트

if not KEY:
    sys.exit("[미설정] ARROW_API_KEY 없음 → Arrow API 접근 신청·키 발급 후 ~/.zshrc export. (현재 조회 불가)")
if not (VERIFIED and ARROW_BASE):
    sys.exit("[엔드포인트 미확인 🔴] Arrow API base/auth 미확정 → 개발자 문서 확인 후 "
             "ARROW_BASE 설정 + ARROW_VERIFIED=1 로 잠금해제. 그 전엔 날조 방지 위해 조회 차단.")
if len(sys.argv) < 2:
    sys.exit("용법: arrow.py <검색어 또는 PN>")

q = " ".join(sys.argv[1:])
url = f"{ARROW_BASE}?{urllib.parse.urlencode({'q': q})}"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}",
                                           "Accept": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    print(json.dumps(d, ensure_ascii=False, indent=2)[:1500])
except urllib.error.HTTPError as e:
    sys.exit(f"[검색 실패 {e.code}] {e.read().decode()[:200]} — 엔드포인트/인증 재확인")
