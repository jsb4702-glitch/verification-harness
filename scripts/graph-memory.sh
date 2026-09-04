#!/bin/sh
# graph-memory.sh — 메모리 [[wikilink]] 웹을 graphify 그래프로 재생성 (AST-only, 토큰 0).
# 파생물 → ~/.claude/memory-graph/ (gitignore·PC별 로컬 재생성). Claude 런타임 explain/path 질의용.
# 실제 memory 디렉토리는 안 건드림(격리 corpus 복사본에만 graphify-out 생성).
set -eu
GRAPHIFY="$HOME/.local/bin/graphify"
GDIR="$HOME/.local/share/memory-graph"   # ~/.claude 밖(graphify가 .gitignore 존중→안쪽이면 corpus 무시됨). 밖=동기화 자동제외+정상빌드.
LOG="$HOME/.claude/logs/memory-graph.log"
mkdir -p "$(dirname "$LOG")" "$GDIR"
[ -x "$GRAPHIFY" ] || { echo "$(date) ERR graphify 없음" >>"$LOG"; exit 1; }

# 메모리 디렉토리 고르기 — md 파일이 가장 많은 곳.
#   구판은 find 결과의 첫 줄을 썼는데, 프로젝트마다 자기 MEMORY.md 가 생기면서
#   후보가 넷으로 늘었고 파일시스템 순서에 따라 엉뚱한 곳(md 6개)을 집었다.
#   그러면 graphify 가 "새 그래프 6노드 vs 기존 161노드" 로 덮어쓰기를 거부해
#   그래프가 조용히 옛 상태로 굳는다(2026-07-23 이후 2일간 그랬다).
#   개수로 고르면 경로 하드코딩 없이 메인 메모리를 집는다.
MDIR=$(find "$HOME/.claude/projects" -maxdepth 4 -name MEMORY.md 2>/dev/null \
  | while IFS= read -r f; do
      d=$(dirname "$f")
      printf '%s\t%s\n' "$(ls -1 "$d"/*.md 2>/dev/null | wc -l | tr -d ' ')" "$d"
    done | sort -rn | head -1 | cut -f2-)
[ -n "$MDIR" ] || { echo "$(date) ERR MEMORY.md 못찾음" >>"$LOG"; exit 1; }

SRC_N=$(ls -1 "$MDIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
rm -f "$GDIR"/*.md
cp "$MDIR"/*.md "$GDIR"/
# 증분 update 는 md 코퍼스에서 고장 형태 둘을 보였다 (2026-08-15 실측):
# ① md 전용 변경을 "코드 무변경" 으로 no-op (8일 조용한 스테일 — OK 로그는
#   기존 graph.json 을 읽어 갱신처럼 보였다)
# ② 변경 감지 시 부분 재추출이 인덱스 스타 엣지를 통째로 떨굼 (697→510,
#   손실 187 = MEMORY.md 차수와 일치).
# 그래서 증분 경로를 버리고 **항상 임시 트리 신선 재빌드 → sanity → 스왑**
# 한다 (186 md ~20초·토큰 0). sanity(신규 nodes·links ≥ 기존의 절반)는
# 2026-07-23 "작은 그래프 덮어쓰기 금지" 방어의 승계 — 코퍼스 오선택·추출
# 실패가 정상 그래프를 지우지 못한다.
TMP="$GDIR.rebuild.$$"
rm -rf "$TMP"; mkdir -p "$TMP"
cp "$GDIR"/*.md "$TMP"/
"$GRAPHIFY" update "$TMP" >>"$LOG" 2>&1
NEW=$(/usr/bin/python3 -c "import json;d=json.load(open('$TMP/graphify-out/graph.json'));print(len(d.get('nodes') or []),len(d.get('links') or []))" 2>/dev/null || echo "0 0")
OLD=$(/usr/bin/python3 -c "import json;d=json.load(open('$GDIR/graphify-out/graph.json'));print(len(d.get('nodes') or []),len(d.get('links') or []))" 2>/dev/null || echo "0 0")
set -- $NEW; NEW_N=$1; NEW_L=$2
set -- $OLD; OLD_N=$1; OLD_L=$2
if [ "$NEW_N" -gt 0 ] && [ "$NEW_N" -ge "$((OLD_N / 2))" ] && [ "$NEW_L" -ge "$((OLD_L / 2))" ]; then
  rm -rf "$GDIR/graphify-out"
  mv "$TMP/graphify-out" "$GDIR/graphify-out"
else
  echo "$(date) ERR 신선 재빌드 sanity 실패 (nodes $OLD_N→$NEW_N links $OLD_L→$NEW_L) — 기존 유지" >>"$LOG"
fi
rm -rf "$TMP"

# 덮어쓰기 거부는 조용한 실패다 — 링크 수까지 남겨 다음에 바로 보이게 한다.
LINKS=$(/usr/bin/python3 -c "
import json,sys
try:
    d=json.load(open('$GDIR/graphify-out/graph.json'))
    print(f\"nodes={len(d.get('nodes') or [])} links={len(d.get('links') or [])}\")
except Exception as e:
    print('graph.json 읽기 실패:', e)
" 2>/dev/null)
echo "$(date) OK src=$MDIR ($SRC_N md) -> $LINKS" >>"$LOG"
