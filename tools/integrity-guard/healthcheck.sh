#!/bin/bash
# integrity-guard 주간 헬스체크 — launchd 침묵드롭 방어 (토 22:15).
# ①보안 launchd 잡 생존 확인 ②무결성 풀체크 1회. 경고전용·자동수정 없음.
NTFY="$HOME/.claude/scripts/ntfy.sh"
LOG="$HOME/.claude/tools/integrity-guard/health.log"
TS="$(date '+%Y-%m-%dT%H:%M:%S')"

JOBS=(
  com.user.claude.integrity
  com.user.skillscan.watch
  com.user.skillscan
)

DEAD=()
for j in "${JOBS[@]}"; do
  launchctl list "$j" >/dev/null 2>&1 || DEAD+=("$j")
done

DRIFT_MSG=""
python3 "$HOME/.claude/tools/integrity-guard/ig.py" check >/dev/null 2>&1
IG_RC=$?
[ "$IG_RC" -eq 1 ] && DRIFT_MSG="드리프트 있음"
[ "$IG_RC" -eq 2 ] && DRIFT_MSG="baseline 없음"

if [ "${#DEAD[@]}" -gt 0 ] || [ -n "$DRIFT_MSG" ]; then
  SUMMARY="감시잡 죽음 ${#DEAD[@]}건 ${DEAD[*]} ${DRIFT_MSG}"
  echo "[$TS] FAIL $SUMMARY" >> "$LOG"
  osascript -e "display notification \"$SUMMARY\" with title \"⚠️ integrity 헬스체크 FAIL\"" 2>/dev/null
  # ntfy엔 상세 미포함 (공용서버)
  [ -x "$NTFY" ] || NTFY_RUN="/bin/bash $NTFY"
  /bin/bash "$NTFY" "integrity 헬스체크 FAIL" "감시잡 ${#DEAD[@]}건 다운/드리프트 — 맥 확인 필요" high rotating_light 2>/dev/null
  exit 1
else
  echo "[$TS] OK jobs=${#JOBS[@]} drift=none" >> "$LOG"
  exit 0
fi
