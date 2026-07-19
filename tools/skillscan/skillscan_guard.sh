#!/bin/bash
# skillscan_guard.sh — skillscan 자동 가드 래퍼 (훅·launchd 공용, DRY)
# 모드:
#   (없음)        풀스캔. launchd 격주용. 항상 스캔.
#   --if-changed  ~/.claude/skills+plugins 트리 해시 변경시에만 스캔. SessionStart 훅용(저비용).
# HIGH>0 이면: 로그 + macOS 알림 + stderr 경고. 종료코드 2(HIGH)/1(MED)/0(clean).

DIR="$HOME/.claude/tools/skillscan"
SCAN="$DIR/skillscan.py"
LOG="$DIR/scan.log"
OUT="$DIR/last_scan.json"
HASHFILE="$DIR/.tree_hash"
TS="$(date +%FT%H:%M:%S)"

# 2026-07-18: cdx 표면 추가 — 변경감지도 같이 넓혀야 자동갱신을 잡는다
targets=("$HOME/.claude/skills" "$HOME/.claude/plugins" \
         "$HOME/.codex/skills" "$HOME/.codex/plugins" "$HOME/.codex/hooks")

# --- 변경감지(훅 저비용 모드) ---
if [ "$1" = "--if-changed" ]; then
  newhash="$(find "${targets[@]}" -type f \
      \( -name '*.md' -o -name '*.sh' -o -name '*.py' -o -name '*.js' -o -name '*.ts' \) \
      ! -path '*/.venv/*' ! -path '*/site-packages/*' ! -path '*/node_modules/*' \
      -exec stat -f '%m %N' {} + 2>/dev/null | sort | shasum | cut -d' ' -f1)"
  oldhash="$(cat "$HASHFILE" 2>/dev/null)"
  if [ "$newhash" = "$oldhash" ]; then
    exit 0   # 변경 없음 → 조용히 통과
  fi
  echo "$newhash" > "$HASHFILE"
fi

# --- 스캔 실행 (정적·네트워크0, baseline 제외→새 위협만) ---
BASE="$DIR/baseline.json"
python3 "$SCAN" --with-plugins --with-codex --baseline "$BASE" --json "$OUT" >/dev/null 2>&1
HIGH="$(python3 -c "import json,sys;print(json.load(open('$OUT'))['counts'].get('HIGH',0))" 2>/dev/null || echo 0)"
MED="$(python3 -c "import json,sys;print(json.load(open('$OUT'))['counts'].get('MED',0))" 2>/dev/null || echo 0)"
echo "$TS HIGH=$HIGH MED=$MED" >> "$LOG"

if [ "${HIGH:-0}" -gt 0 ]; then
  # 백스톱 역할: 경고만. 자동이동(격리) 안 함 — 판정은 사람(Claude)검증+리빌드가 1차게이트.
  # 활성트리에서 HIGH가 떴다는 건 INTAKE 프로토콜을 우회해 직접 들어왔다는 신호 → 사람 개입 요구.
  osascript -e "display notification \"skillscan: HIGH=$HIGH 위협후보(활성트리). intake 프로토콜 우회 의심\" with title \"⚠️ 하네스 스킬 보안\" sound name \"Basso\"" 2>/dev/null
  echo "⚠️ [skillscan] HIGH=$HIGH MED=$MED — 활성트리 공급망 위협. INTAKE 우회 의심, 사람검증 요구: $OUT" >&2
  exit 2
fi
exit 0
