#!/bin/sh
# graph-memory.sh — 메모리 [[wikilink]] 웹을 graphify 그래프로 재생성 (AST-only, 토큰 0).
# 파생물 → ~/.claude/memory-graph/ (gitignore·PC별 로컬 재생성). Claude 런타임 explain/path 질의용.
# 실제 memory 디렉토리는 안 건드림(격리 corpus 복사본에만 graphify-out 생성).
set -eu
GRAPHIFY="$HOME/.local/bin/graphify"
GDIR="$HOME/.local/share/memory-graph"   # ~/.claude 밖(graphify가 .gitignore 존중→안쪽이면 corpus 무시됨). 밖=동기화 자동제외+정상빌드.
LOG="$HOME/.claude/logs/memory-graph.log"
mkdir -p "$(dirname "$LOG")" "$GDIR"
MEMFILE=$(find "$HOME/.claude/projects" -maxdepth 4 -name MEMORY.md 2>/dev/null | head -1)
[ -x "$GRAPHIFY" ] || { echo "$(date) ERR graphify 없음" >>"$LOG"; exit 1; }
[ -n "$MEMFILE" ] || { echo "$(date) ERR MEMORY.md 못찾음" >>"$LOG"; exit 1; }
MDIR=$(dirname "$MEMFILE")
rm -f "$GDIR"/*.md
cp "$MDIR"/*.md "$GDIR"/
"$GRAPHIFY" update "$GDIR" >>"$LOG" 2>&1
echo "$(date) OK rebuilt $(ls "$GDIR"/*.md 2>/dev/null | wc -l | tr -d ' ') md -> $GDIR/graphify-out/graph.json" >>"$LOG"
