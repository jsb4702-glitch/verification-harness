#!/usr/bin/env bash
# Simulated Claude Code hook-input tests for read_cache.py. Each case pipes
# the JSON a real hook invocation would receive and asserts on stdout.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
RC="~/.claude/tools/read-cache/read_cache.py"
export READ_CACHE_STATE_DIR="$DIR/test-state"
rm -rf "$READ_CACHE_STATE_DIR"

TESTFILE="$DIR/fixture.txt"
python3 -c "print('line ' * 200)" > "$TESTFILE"   # ~1.2KB > MIN_SIZE
SMALL="$DIR/small.txt"
echo "tiny" > "$SMALL"

SID="sess-test-1"
pass=0; fail=0

j() { # j <mode> <json>  -> stdout of hook
  printf '%s' "$2" | python3 "$RC" "$1"
}

check() { # check <name> <expect_deny:yes|no> <output>
  local name="$1" expect="$2" out="$3"
  local got="no"
  [[ "$out" == *'"permissionDecision": "deny"'* ]] && got="yes"
  if [[ "$got" == "$expect" ]]; then
    echo "PASS  $name"; pass=$((pass+1))
  else
    echo "FAIL  $name (expect deny=$expect, got deny=$got) out=$out"; fail=$((fail+1))
  fi
}

IN_READ="{\"session_id\":\"$SID\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$TESTFILE\"}}"
IN_READ_OFF="{\"session_id\":\"$SID\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$TESTFILE\",\"offset\":1}}"
IN_READ_SMALL="{\"session_id\":\"$SID\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$SMALL\"}}"
IN_EDIT="{\"session_id\":\"$SID\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$TESTFILE\"}}"
IN_READ_S2="{\"session_id\":\"sess-other\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$TESTFILE\"}}"
IN_MISSING="{\"session_id\":\"$SID\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$DIR/nope.txt\"}}"

# 1. first read: pre passes, post records
check "1a first pre-read passes"            no  "$(j pre-read  "$IN_READ")"
j post-read "$IN_READ" >/dev/null
# 2. identical re-read: denied
check "2  re-read denied"                   yes "$(j pre-read  "$IN_READ")"
# 3. offset read: escape hatch passes
check "3  offset read passes"               no  "$(j pre-read  "$IN_READ_OFF")"
# 4. other session unaffected
check "4  other session passes"             no  "$(j pre-read  "$IN_READ_S2")"
# 5. file modified externally (bash append): fingerprint drift -> passes
sleep 0.01; echo extra >> "$TESTFILE"
check "5  modified file passes"             no  "$(j pre-read  "$IN_READ")"
j post-read "$IN_READ" >/dev/null
check "5b re-read after re-record denied"   yes "$(j pre-read  "$IN_READ")"
# 6. invalidate via Edit hook: next read passes
j invalidate "$IN_EDIT" >/dev/null
check "6  post-edit invalidated passes"     no  "$(j pre-read  "$IN_READ")"
j post-read "$IN_READ" >/dev/null
# 7. clear (compact): everything passes again
j clear "{\"session_id\":\"$SID\"}" >/dev/null
check "7  post-compact clear passes"        no  "$(j pre-read  "$IN_READ")"
# 8. small file never intercepted (even after post-read)
j post-read "$IN_READ_SMALL" >/dev/null
check "8  small file passes"                no  "$(j pre-read  "$IN_READ_SMALL")"
# 9. missing file passes
check "9  missing file passes"              no  "$(j pre-read  "$IN_MISSING")"
# 10. garbage stdin never blocks
check "10 garbage stdin passes"             no  "$(printf 'not json' | python3 "$RC" pre-read)"
# 11. partial read is not recorded as full
j clear "{\"session_id\":\"$SID\"}" >/dev/null
j post-read "$IN_READ_OFF" >/dev/null
check "11 partial read not recorded"        no  "$(j pre-read  "$IN_READ")"
# 12. error tool_response not recorded
j clear "{\"session_id\":\"$SID\"}" >/dev/null
IN_READ_ERR="{\"session_id\":\"$SID\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$TESTFILE\"},\"tool_response\":{\"is_error\":true}}"
j post-read "$IN_READ_ERR" >/dev/null
check "12 error read not recorded"          no  "$(j pre-read  "$IN_READ")"

echo "----"
echo "pass=$pass fail=$fail"
[[ $fail -eq 0 ]]
