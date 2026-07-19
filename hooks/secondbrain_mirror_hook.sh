#!/bin/bash
# SecondBrain iCloud 미러 리프레시 — SessionStart 훅.
# launchd 컨텍스트 python3은 ~/Library/Mobile Documents TCC EPERM으로 크래시(26-06~07 실측)
# → Claude 앱 컨텍스트(FDA 보유)에서 실행. 20h 스로틀, 항상 exit 0(비차단).
STAMP="$HOME/.claude/logs/secondbrain-mirror.last"
LOG="$HOME/.claude/logs/secondbrain-mirror.log"
now=$(date +%s)
last=$(cat "$STAMP" 2>/dev/null || echo 0)
[ $((now - last)) -lt 72000 ] && exit 0
if /usr/bin/python3 "$HOME/.claude/scripts/build_vault.py" >> "$LOG" 2>&1; then
  echo "$now" > "$STAMP"
else
  echo "[$(date '+%Y-%m-%dT%H:%M:%S')] mirror hook FAIL — heartbeat가 .last 스테일로 포착" >> "$LOG"
fi
exit 0
