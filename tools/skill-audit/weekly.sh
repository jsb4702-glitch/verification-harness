#!/bin/bash
# launchd 래퍼 — PATH/HOME 세팅 후 weekly.py 실행. mlx-capable python3(framework) 우선.
export HOME="~"
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LOG="$HOME/skill-audit-weekly/weekly.log"
mkdir -p "$HOME/skill-audit-weekly"
echo "===== $(date) 시작 =====" >> "$LOG"
python3 "$HOME/.claude/tools/skill-audit/weekly.py" >> "$LOG" 2>&1
rc=$?
echo "===== $(date) 종료 (exit $rc) =====" >> "$LOG"
exit $rc
