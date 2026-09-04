#!/bin/bash
# skill-intake.sh — 외부 스킬/플러그인 도입 프로토콜 (신뢰경계: 검증·리빌드 전엔 활성불가)
#
# 불변식: 외부출처는 activate 전 INTAKE 격리 → 기계+사람 이중검증 → 리빌드/잠금 → 승격.
#         직접 ~/.claude/skills 직행 금지. promote는 기계검증(skillscan HIGH=0) 통과시에만.
#
# 흐름:
#   skill-intake.sh receive <소스경로> [이름] [출처설명]
#       외부자료를 intake/<이름>/ 으로 격리복사 + skillscan 1차(기계) + 사람검증 체크리스트.
#       ※ 이후 Claude가 intake/<이름>/ 안에서 정독 → 악성요소 제거 → 깨끗본으로 리빌드.
#   skill-intake.sh seal <이름>
#       사람검증(정독·리빌드) 완료 시점의 트리해시 봉인. promote의 필수 선행단계.
#       봉인 후 내용이 1바이트라도 바뀌면 promote 거부(TOCTOU 차단 — OpenClaw 해시바인딩 이식).
#   skill-intake.sh promote <이름> --via <rebuild|extract|sandbox> [--by <검증자>]
#       봉인해시 일치 + 기계 재검증(HIGH=0) 통과시 skills/<이름> 으로 승격 + provenance 기록.
#   skill-intake.sh list                현황
#   skill-intake.sh reject <이름>       intake에서 폐기(quarantine 이동)
set -u
DIR="$HOME/.claude/tools/skillscan"
SCAN="$DIR/skillscan.py"
DYN="$DIR/dyntrace.py"
BASE="$DIR/baseline.json"
INTAKE="$HOME/.claude/skill-intake"
SKILLS="$HOME/.claude/skills"
QDIR="$HOME/.claude/skillscan-quarantine"
PROV="$INTAKE/PROVENANCE.tsv"
mkdir -p "$INTAKE" "$QDIR"
[ -f "$PROV" ] || printf 'name\tstatus\tsource\tdate\tvia\tby\n' > "$PROV"
TS="$(date +%FT%H:%M:%S)"

scan_dir() { python3 "$SCAN" "$1" --baseline "$BASE"; }
# 결정론적 트리해시(상대경로 기준·정렬 — 위치 무관, 내용+구조에만 결박)
# 심링크도 "L 경로 -> 타깃" 행으로 포함 — 링크는 -type f에 안 잡혀 seal 후 추가돼도
# 해시가 안 깨지는 TOCTOU 갭 차단. 무심링크 트리는 기존 해시와 동일.
tree_hash() { (cd "$1" && { find . -type f -exec shasum {} \; ; \
  find . -type l -exec sh -c 'printf "L %s -> %s\n" "$1" "$(readlink "$1")"' _ {} \; ; } \
  | sort | shasum | cut -c1-16); }
# 심링크 게이트: 트리 밖을 가리키거나 깨진 심링크 검출·거부(정적·결정론).
# dyntrace SENS가 open()의 raw 경로 서브스트링 매칭이라 무해한 이름의 심링크로
# ~/.ssh 등을 열면 미탐 — 링크 자체를 intake 단계에서 원천 거부한다.
symlink_gate() {
  python3 - "$1" <<'PY'
import os, sys
root = os.path.realpath(sys.argv[1])
bad = 0
for dp, dns, fns in os.walk(root):
    for n in dns + fns:
        p = os.path.join(dp, n)
        if os.path.islink(p):
            t = os.path.realpath(p)
            inside = t == root or t.startswith(root + os.sep)
            if not inside or not os.path.exists(t):
                print(f"  ⛔ 심링크 이탈/깨짐: {p} -> {os.readlink(p)} (해석: {t})")
                bad = 1
sys.exit(bad)
PY
}
# dynamic trace: runs .py under PEP-578 audit hook in an isolated subprocess
# (fake HOME, sanitized env, network/proc BLOCKED). exit 3 = high-sev behavior.
dyn_dir() { python3 "$DYN" "$1" --timeout 12; }

# render_card <name> <dest> <via> <by> <H> <M> <L> <dyn_exit> <source> <inj_l1> <inj_l2>
# promote 성공시 거버넌스 카드 생성. 검증신호=실측, 사람판단 항목=❓/[VERIFY] 마커.
render_card() {
  local NAME="$1" DEST="$2" VIA="$3" BY="$4" H="$5" M="$6" L="$7" DRC="$8" SRC="$9"
  local INJ1="${10:-❓}" INJ2="${11:-❓}"
  local TPL="$DIR/references/skillcard.template.md" OUT="$2/CARD.md"
  [ -f "$TPL" ] || { echo "  (⚠️ 카드 템플릿 없음 — 스킵)"; return; }
  SRC="$(printf '%s' "$SRC" | tr -d '\n' | sed 's/[&|]/ /g')"; SRC="${SRC:-❓}"
  local TH DS DV
  TH="$(find "$DEST" -type f ! -name CARD.md -exec shasum {} \; 2>/dev/null | shasum | cut -c1-12)"
  # dyntrace 표시: 3만 HIGH(차단). 0=추적완료, 그외(대상 .py 없음/무해 종료)=n/a — exit=1 오해소지 제거
  case "$DRC" in
    3) DS="HIGH(차단)"; DV="관찰됨";;
    0) DS="ok(추적완료)"; DV="없음";;
    *) DS="ok(.py없음/무해)"; DV="없음";;
  esac
  sed -e "s|{{NAME}}|$NAME|g" -e "s|{{OWNER}}|❓[VERIFY]|g" -e "s|{{SOURCE}}|$SRC|g" \
      -e "s|{{LICENSE}}|❓[VERIFY]|g" -e "s|{{TREE_HASH}}|$TH|g" -e "s|{{DATE}}|$TS|g" \
      -e "s|{{STATUS}}|PROMOTED|g" -e "s|{{VIA}}|$VIA|g" -e "s|{{BY}}|$BY|g" \
      -e "s|{{H}}|$H|g" -e "s|{{M}}|$M|g" -e "s|{{L}}|$L|g" \
      -e "s|{{DYN_EXIT}}|$DS|g" -e "s|{{DYN_VIOL}}|$DV|g" \
      -e "s|{{INJ_L1}}|$INJ1|g" -e "s|{{INJ_L2}}|$INJ2|g" -e "s|{{HUMAN}}|❓검증자확정|g" \
      -e "s|{{USECASE}}|❓|g" -e "s|{{RISKS}}|❓|g" \
      -e "s|{{EXPORT}}|❓ 수출통제 규정/수출통제 규정 저촉여부|g" -e "s|{{BOUNDARY}}|❓|g" \
      "$TPL" > "$OUT"
  echo "  🪪 카드 생성: $OUT  (❓·[VERIFY] 마커는 사람검증서 해소)"
}

case "${1:-}" in
  receive)
    SRC="${2:?소스경로 필요}"; NAME="${3:-$(basename "$SRC")}"; SRCDESC="${4:-unspecified}"
    [ -e "$SRC" ] || { echo "❌ 소스 없음: $SRC"; exit 1; }
    DEST="$INTAKE/$NAME"
    [ -e "$DEST" ] && { echo "❌ 이미 intake에 존재: $DEST (reject 후 재시도)"; exit 1; }
    cp -R "$SRC" "$DEST"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$NAME" "PENDING" "$SRCDESC" "$TS" "-" "-" >> "$PROV"
    echo "📥 격리완료: $DEST  (출처: $SRCDESC)"
    echo "── 기계 0차검증(symlink gate: 트리 밖/깨진 심링크 정적 거부) ──"
    if ! symlink_gate "$DEST"; then
      echo "❌ 수령거부: 트리 밖을 가리키는(또는 깨진) 심링크 검출 — dyntrace 민감파일 탐지 우회벡터."
      echo "   폐기: skill-intake.sh reject $NAME   (링크 제거본으로 재수령 가능)"
      exit 5
    fi
    echo "  ✅ 심링크 이탈 없음"
    echo "── 기계 1차검증(skillscan: 정적 IOC) ──"
    scan_dir "$DEST"; rc=$?
    echo
    echo "── 기계 2차검증(dyntrace: 동적 audit-hook, 난독화 무력화) ──"
    dyn_dir "$DEST"; [ $? -eq 3 ] && rc=3
    echo
    echo "── 기계 3차검증(inject-detect: 프롬프트인젝션 섀도 L1, 비차단) ──"
    if [ -x "$HOME/.claude/tools/inject-detect/inject-scan.sh" ]; then
      "$HOME/.claude/tools/inject-detect/inject-scan.sh" "$DEST" 2>/dev/null
      echo "  (L2 의미판정 회수: inject-scan.sh \"$DEST\" --semantic  — gemma 느려 온디맨드)"
    else
      echo "  (inject-detect 미설치 — 스킵)"
    fi
    echo
    echo "── 기계 4차검증(skill-guard: 광역 악성분류 Qwen2.5-3B FT, 섀도, 비차단) ──"
    if [ -f "$HOME/.claude/tools/skill-guard/skill-guard.py" ]; then
      HF_HUB_DISABLE_PROGRESS_BARS=1 python3 "$HOME/.claude/tools/skill-guard/skill-guard.py" "$DEST" --mode shadow 2>/dev/null \
        || echo "  (skill-guard 실행오류 — 스킵, 비차단)"
      echo "  (능동판정 회수: skill-guard.py \"$DEST\" --mode active --json  — 섀도 FP 누적후 승급 예정)"
    else
      echo "  (skill-guard 미설치 — 스킵)"
    fi
    echo
    echo "── 품질 진단(skill-audit: substance, 비차단) — 청소할지·채울지·버릴지 판단보조 ──"
    if [ -f "$HOME/.claude/tools/skill-audit/skill-audit.py" ]; then
      python3 "$HOME/.claude/tools/skill-audit/skill-audit.py" "$DEST" --quality-only 2>/dev/null \
        || echo "  (skill-audit 실행오류 — 스킵)"
      echo "  (SUBSTANTIVE=알맹이O / THIN=얕음·개선여지 / HOLLOW=포장만·알맹이없음)"
    else
      echo "  (skill-audit 미설치 — 스킵)"
    fi
    echo
    echo "── 사람검증 체크리스트(Claude 정독 필수) ──"
    echo "  □ 자연어 지시층: 'do not mention to user'·정체성파일(MEMORY/CLAUDE.md/.ssh) 접근지시·인젝션"
    echo "  □ 코드층: curl|bash·base64 디코드실행·리버스셸·env덤프전송·외부 POST"
    echo "  □ 권한/트리거: 과광범 트리거, 불필요한 네트워크/파일 권한"
    echo "  □ 난독화: 긴 base64·비가시 유니코드·동적 eval"
    echo "  □ 의존성: venv/바이너리/WASM = 리빌드 불가분 → 출처고정+해시잠금+샌드박스"
    echo "→ 정독·리빌드 완료시: skill-intake.sh seal $NAME  →  promote $NAME --via <rebuild|extract|sandbox> --by Claude"
    exit $rc ;;

  seal)
    NAME="${2:?이름 필요}"; SRCD="$INTAKE/$NAME"
    [ -d "$SRCD" ] || { echo "❌ intake에 없음: $SRCD"; exit 1; }
    H="$(tree_hash "$SRCD")"
    printf '%s\n' "$H" > "$INTAKE/.seal.$NAME"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$NAME" "SEALED" "-" "$TS" "-" "-" >> "$PROV"
    echo "🔏 봉인: $NAME tree=$H — 이후 내용 변경시 promote 거부(재정독→재seal 필요)"
    exit 0 ;;

  promote)
    NAME="${2:?이름 필요}"; VIA=""; BY="Claude"
    shift 2
    while [ $# -gt 0 ]; do case "$1" in
      --via) VIA="$2"; shift 2;; --by) BY="$2"; shift 2;; *) shift;; esac; done
    SRCD="$INTAKE/$NAME"
    [ -d "$SRCD" ] || { echo "❌ intake에 없음: $SRCD"; exit 1; }
    [ -n "$VIA" ] || { echo "❌ --via <rebuild|extract|sandbox> 필수 (검증방식 명시)"; exit 1; }
    echo "── 봉인해시 대조(TOCTOU 게이트) ──"
    SEALF="$INTAKE/.seal.$NAME"
    if [ ! -f "$SEALF" ]; then
      echo "❌ 승격거부: 봉인 없음 — 사람검증(정독·리빌드) 완료 후 'skill-intake.sh seal $NAME' 먼저"; exit 4
    fi
    CUR="$(tree_hash "$SRCD")"; SEALED="$(cat "$SEALF")"
    if [ "$CUR" != "$SEALED" ]; then
      echo "❌ 승격거부: 봉인해시 불일치 (sealed=$SEALED now=$CUR) — 검증 완료 후 내용이 변경됨(TOCTOU 의심). 재정독 후 seal 재실행"; exit 4
    fi
    echo "  ✅ 봉인 일치: $CUR"
    echo "── 승격 전 심링크 게이트(receive 이후 추가분 방어) ──"
    if ! symlink_gate "$SRCD"; then
      echo "❌ 승격거부: 트리 밖/깨진 심링크 검출 — 제거 후 재정독→seal→promote."; exit 5
    fi
    echo "  ✅ 심링크 이탈 없음"
    echo "── 승격 전 기계 재검증 ──"
    OUTJSON="$DIR/.promote_$NAME.json"
    python3 "$SCAN" "$SRCD" --baseline "$BASE" --json "$OUTJSON" >/dev/null 2>&1
    read HIGH MED LOW <<EOF
$(python3 - "$OUTJSON" <<'PY'
import json,sys
try: c=json.load(open(sys.argv[1]))['counts']
except Exception: c={}
def g(*ks):
    for k in ks:
        if k in c: return c[k]
    return 0
print(g('HIGH'), g('MED','MEDIUM'), g('LOW'))
PY
)
EOF
    rm -f "$OUTJSON"
    HIGH="${HIGH:-0}"; MED="${MED:-0}"; LOW="${LOW:-0}"
    if [ "${HIGH:-0}" -gt 0 ]; then
      echo "❌ 승격거부: 정적 HIGH=$HIGH (skillscan 실패). 리빌드로 위협 제거 후 재시도."; exit 2
    fi
    echo "── 승격 전 동적 재검증(dyntrace) ──"
    dyn_dir "$SRCD"; DRC=$?
    if [ "$DRC" -eq 3 ]; then
      echo "❌ 승격거부: 동적 HIGH (dyntrace가 네트워크/프로세스/민감파일 접근 관찰). 리빌드 후 재시도."; exit 3
    fi
    # inject-detect L1 실캡처 — mv 전, 아직 $SRCD일 때 스캔
    INJ_L1="미설치"; INJ_L2="미실행(--semantic)"
    ISCAN="$HOME/.claude/tools/inject-detect/inject-scan.sh"
    if [ -x "$ISCAN" ]; then
      INJOUT="$("$ISCAN" "$SRCD" 2>/dev/null)"
      if echo "$INJOUT" | grep -q "신호 없음"; then INJ_L1=0
      elif echo "$INJOUT" | grep -qE 'L1\(regex\)='; then
        INJ_L1="$(printf '%s' "$INJOUT" | sed -nE 's/.*L1\(regex\)=([0-9]+).*/\1/p')"
      else INJ_L1="?"; fi
    fi
    # skill-guard 4차(섀도, 비차단) — 승격 막지 않고 shadow.jsonl에 기록만
    if [ -f "$HOME/.claude/tools/skill-guard/skill-guard.py" ]; then
      echo "── 승격 전 skill-guard 섀도(비차단) ──"
      HF_HUB_DISABLE_PROGRESS_BARS=1 python3 "$HOME/.claude/tools/skill-guard/skill-guard.py" "$SRCD" --mode shadow 2>/dev/null \
        || echo "  (skill-guard 실행오류 — 스킵)"
    fi
    [ -e "$SKILLS/$NAME" ] && { echo "❌ skills/$NAME 이미 존재"; exit 1; }
    mv "$SRCD" "$SKILLS/$NAME"
    rm -f "$SEALF"
    # provenance: 최신행 갱신(append 방식, 마지막 상태가 유효)
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$NAME" "PROMOTED" "-" "$TS" "$VIA" "$BY" >> "$PROV"
    echo "✅ 승격: skills/$NAME  (방식: $VIA, 검증: $BY, HIGH=0)"
    SRCLINE="$(awk -F'\t' -v n="$NAME" '$1==n && $3!="-"{s=$3} END{print s}' "$PROV")"
    render_card "$NAME" "$SKILLS/$NAME" "$VIA" "$BY" "$HIGH" "$MED" "$LOW" "$DRC" "$SRCLINE" "$INJ_L1" "$INJ_L2"
    exit 0 ;;

  reject)
    NAME="${2:?이름 필요}"; SRCD="$INTAKE/$NAME"
    [ -d "$SRCD" ] || { echo "❌ intake에 없음"; exit 1; }
    mv "$SRCD" "$QDIR/${NAME}.rejected.$(date +%s)"
    rm -f "$INTAKE/.seal.$NAME"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$NAME" "REJECTED" "-" "$TS" "-" "-" >> "$PROV"
    echo "🗑️  폐기→quarantine: $NAME"; exit 0 ;;

  list)
    echo "=== INTAKE 현황 ($INTAKE) ==="
    ls -1 "$INTAKE" 2>/dev/null | grep -v PROVENANCE || echo "(비어있음)"
    echo; echo "=== PROVENANCE (최근 10) ==="
    tail -10 "$PROV" | column -t -s "$(printf '\t')" 2>/dev/null || tail -10 "$PROV"
    exit 0 ;;

  *)
    echo "용법: skill-intake.sh {receive <소스> [이름] [출처] | seal <이름> | promote <이름> --via <방식> [--by 검증자] | reject <이름> | list}"
    exit 1 ;;
esac
