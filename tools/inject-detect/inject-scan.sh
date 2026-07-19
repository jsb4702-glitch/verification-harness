#!/bin/bash
# inject-detect — 프롬프트 인젝션 2계층 섀도 스캐너 (로그온리·비차단)
#   inject-scan.sh <경로> [--semantic]
#     L1 regex(즉시) + (--semantic 시) L2 gemma. 발견은 shadow.log 누적. 항상 exit 0.
#   --semantic 은 ollama(gemma4-judge) 필요 — 없으면 자동 기동 시도, 실패 시 L1만.
set -u
TOOL="$HOME/.claude/tools/inject-detect"
TARGET="${1:?사용법: inject-scan.sh <경로> [--semantic]}"
shift || true
ARGS="$*"
if echo "$ARGS" | grep -q -- "--semantic"; then
  pgrep -x ollama >/dev/null 2>&1 || { (ollama serve >/dev/null 2>&1 &); sleep 2; }
fi
python3 "$TOOL/scan_path.py" "$TARGET" $ARGS
exit 0   # 섀도: 무슨 일이 있어도 흐름 차단 안 함
