#!/bin/bash
# receipt 회귀시험 — 격리 스토어에서 9케이스.
# 성공/실패/변조/삭제/미발급/사후편집/만료/로그자동첨부/종료코드전파 를 전부 실측한다.
set -u
cd "$(dirname "$0")" || exit 1

TMP="$(mktemp -d)"
export RECEIPT_STORE_DIR="$TMP/store"
R="python3 ./receipt.py"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
# expect <기대종료코드> <설명> <명령...>
expect() {
  local want="$1" desc="$2"; shift 2
  local out; out="$("$@" 2>&1)"; local got=$?
  if [ "$got" = "$want" ]; then ok "$desc (exit=$got)"
  else bad "$desc — 기대 exit=$want 실제 exit=$got"; echo "$out" | sed 's/^/       /'; fi
}
# expect_match <패턴> <설명> <명령...>
expect_match() {
  local pat="$1" desc="$2"; shift 2
  local out; out="$("$@" 2>&1)"
  if echo "$out" | grep -q "$pat"; then ok "$desc"
  else bad "$desc — 패턴 '$pat' 없음"; echo "$out" | sed 's/^/       /'; fi
}

echo "=== receipt 회귀시험 (스토어: $RECEIPT_STORE_DIR) ==="

echo "[1] 정상 실행 → 대조 통과"
ART="$TMP/out.txt"
$R run --key "시험 정상" --artifact "$ART" -- bash -c "echo hello > $ART; exit 0" >/dev/null 2>&1
expect 0 "attest 통과" $R attest --key "시험 정상" --require-exit 0

echo "[2] 종료코드 불일치 → EXIT 실패"
$R run --key "시험 실패" -- bash -c "exit 7" >/dev/null 2>&1
expect 3 "attest 차단" $R attest --key "시험 실패" --require-exit 0
expect_match "EXIT 종료코드 7" "사유가 EXIT 로 찍힘" $R attest --key "시험 실패" --require-exit 0

echo "[3] 산출물 변조 → ARTIFACT 실패"
echo "tampered" > "$ART"
expect 3 "변조 감지" $R attest --key "시험 정상" --require-exit 0
expect_match "해시 상이" "사유가 해시 상이" $R attest --key "시험 정상" --require-exit 0

echo "[4] 산출물 삭제 → ARTIFACT 실패"
rm -f "$ART"
expect_match "사라짐" "삭제 감지" $R attest --key "시험 정상" --require-exit 0

echo "[5] receipt 미발급 → NO_RECEIPT"
expect 3 "미발급 차단" $R attest --key "돌린적 없는 작업" --require-exit 0
expect_match "NO_RECEIPT" "사유가 NO_RECEIPT" $R attest --key "돌린적 없는 작업" --require-exit 0

echo "[6] receipt 사후 편집 → BAD_SIG"
$R run --key "시험 위조" -- bash -c "exit 1" >/dev/null 2>&1
python3 - "$RECEIPT_STORE_DIR/receipts.jsonl" <<'PY'
import json, sys
p = sys.argv[1]
lines = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
for r in lines:
    if r["key"] == "시험 위조":
        r["exit"] = 0          # 실패를 성공으로 위조
with open(p, "w", encoding="utf-8") as f:
    for r in lines:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
PY
expect 3 "위조 차단" $R attest --key "시험 위조" --require-exit 0
expect_match "BAD_SIG" "사유가 BAD_SIG" $R attest --key "시험 위조" --require-exit 0

echo "[7] 신선도 상한 초과 → STALE"
$R run --key "시험 만료" -- bash -c "exit 0" >/dev/null 2>&1
expect 3 "만료 차단" $R attest --key "시험 만료" --require-exit 0 --max-age=0.0001
expect 0 "무제한(0)이면 통과" $R attest --key "시험 만료" --require-exit 0 --max-age=0

echo "[8] 실행 로그가 산출물로 자동 첨부"
expect_match "산출물=1개" "로그 1건 자동 첨부" $R attest --key "시험 만료" --max-age=0

echo "[9] run 이 피실행 명령의 종료코드를 그대로 전파"
expect 7 "종료코드 전파" $R run --key "시험 전파" -- bash -c "exit 7"

echo
$R stats
echo
echo "=== 결과: 통과 $PASS · 실패 $FAIL ==="
rm -rf "$TMP"
[ "$FAIL" = 0 ]
