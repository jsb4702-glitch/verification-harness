#!/bin/bash
# ledger.py dirty-rect 스킵룰 스모크 — 격리 스토어, 실세션 무접촉
set -uo pipefail
L="$HOME/.claude/tools/ledger/ledger.py"
D=$(mktemp -d "${TMPDIR:-/tmp}/ledgertest.XXXXXX")
export LEDGER_STORE="$D/session.jsonl"
PASS=0; FAIL=0

chk() { # desc expected_rc expected_substring cmd...
  local desc="$1" exp_rc="$2" pat="$3"; shift 3
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [[ $rc -eq $exp_rc && "$out" == *"$pat"* ]]; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc (rc=$rc exp=$exp_rc, pat='$pat')"; echo "      out: $out"; FAIL=$((FAIL+1))
  fi
}

# T1 신규 key → NEW
chk "T1 NEW 신규key" 0 "NEW" python3 "$L" check --type numeric --key "M8 예압 Fmin" --value 12500 --verdict confirmed
# T2 confirmed 적재
chk "T2 add confirmed" 0 "적재" python3 "$L" add --type numeric --key "M8 예압 Fmin" --claim "12.5 kN" --value 12500 --evidence "VDI2230" --verdict confirmed
# T3 동일값 재등장 → SKIP
chk "T3 SKIP 동일값" 0 "SKIP" python3 "$L" check --type numeric --key "M8 예압 Fmin" --value 12500 --verdict confirmed
# T4 값 2.4% 상이(tol 이내·SKIP_EQ 초과) → REF
chk "T4 REF 값상이" 0 "REF" python3 "$L" check --type numeric --key "M8 예압 Fmin" --value 12800 --verdict confirmed
# T5 값 28% 괴리 → CONTRA exit 3
chk "T5 CONTRA 값괴리" 3 "CONTRA" python3 "$L" check --type numeric --key "M8 예압 Fmin" --value 9000 --verdict confirmed
# T6~T9 비수치(citation): claim 일치=SKIP / 불일치·미제공=REF
chk "T6 add citation" 0 "적재" python3 "$L" add --type citation --key "uqlm 라이선스" --claim "Apache-2.0" --evidence "pyproject+repo 2경로" --verdict confirmed
chk "T7 SKIP claim일치" 0 "SKIP" python3 "$L" check --type citation --key "uqlm 라이선스" --claim "Apache-2.0" --verdict confirmed
chk "T8 REF claim불일치" 0 "REF" python3 "$L" check --type citation --key "uqlm 라이선스" --claim "MIT" --verdict confirmed
chk "T9 REF claim미제공" 0 "REF" python3 "$L" check --type citation --key "uqlm 라이선스" --verdict confirmed
# T10~T11 tentative는 절대 SKIP 불가
chk "T10 add tentative" 0 "적재" python3 "$L" add --type causal --key "임베딩 스킵 위험" --claim "유사도 스킵은 날조 통로" --verdict tentative
chk "T11 REF tentative" 0 "REF" python3 "$L" check --type causal --key "임베딩 스킵 위험" --claim "유사도 스킵은 날조 통로" --verdict tentative
# T12 R1 회귀: confirmed key에 refuted 적재 → 모순 exit 3
chk "T12 R1 add모순" 3 "모순감지" python3 "$L" add --type citation --key "uqlm 라이선스" --claim "GPL" --verdict refuted
# T13~T14 stats: false-skip 의심 2건(m8=skip후 contra, uqlm=skip후 refuted적재) + 스킵율 노출
chk "T13 false-skip 검출" 0 "false-skip 의심 2건" python3 "$L" stats
chk "T14 스킵율 노출" 0 "스킵율" python3 "$L" stats
# T15~T16 음수 =형 회귀
chk "T15 add 음수=형" 0 "적재" python3 "$L" add --type numeric --key "저장온도 하한" --claim="-32°C" --value=-32 --verdict confirmed
chk "T16 SKIP 음수" 0 "SKIP" python3 "$L" check --type numeric --key "저장온도 하한" --value=-32 --verdict confirmed
# T17~T18 단위함정 가드: value 동일·claim 표기 상이 → REF (레드팀 N8 재발방지)
chk "T17 add 단위N" 0 "적재" python3 "$L" add --type numeric --key "축하중" --claim "12500 N" --value 12500 --verdict confirmed
chk "T18 단위함정 REF" 0 "REF" python3 "$L" check --type numeric --key "축하중" --claim "12500 lbf" --value 12500 --verdict confirmed
# T19 clear가 store+metrics 둘 다 삭제
chk "T19 clear" 0 "비움" python3 "$L" clear
M="${LEDGER_STORE%.jsonl}.metrics.jsonl"
if [[ ! -f "$LEDGER_STORE" && ! -f "$M" ]]; then echo "PASS: T20 store+metrics 삭제확인"; PASS=$((PASS+1))
else echo "FAIL: T20 잔존파일 있음"; FAIL=$((FAIL+1)); fi

echo "== 결과: $PASS pass / $FAIL fail =="
rm -rf "$D"
exit $([[ $FAIL -eq 0 ]] && echo 0 || echo 1)
