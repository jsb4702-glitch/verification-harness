#!/usr/bin/env python3
"""read-cache — session-scoped duplicate-Read suppressor for Claude Code.

Clean-room rebuild of the "re-read skeleton" idea from token-optimizer.
No code copied from the original. Behavior:

  pre-read    PreToolUse[Read]   : deny a full re-read of a file whose
                                   fingerprint (mtime_ns+size) is unchanged
                                   since the last successful full read this
                                   session. Partial reads (offset/limit)
                                   always pass — that is the escape hatch.
  post-read   PostToolUse[Read]  : record fingerprint after a successful
                                   full read.
  invalidate  PostToolUse[Edit*] : drop the entry for an edited file
                                   (belt-and-suspenders; fingerprint drift
                                   already forces a pass).
  clear       PreCompact / SessionStart : wipe session state so post-compact
                                   re-reads always return full content.

Safety invariants:
  - Deny ONLY when we can prove the identical bytes were already delivered
    to this session's context: same session_id, full read, fingerprint match.
  - Any doubt (missing state, unreadable file, small file, partial read,
    JSON error) → exit 0 silently → Claude Code proceeds normally.
  - Never touches file contents; state lives under READ_CACHE_STATE_DIR.
"""

import json
import os
import sys
import time
from pathlib import Path

MIN_SIZE_BYTES = 1000          # below this, the deny notice costs more than it saves
STATE_TTL_SECS = 48 * 3600     # prune abandoned session state files
CHARS_PER_TOKEN = 4            # rough estimate for the savings figure


def state_dir() -> Path:
    env = os.environ.get("READ_CACHE_STATE_DIR", "").strip()
    base = Path(env) if env else Path.home() / ".claude" / "tools" / "read-cache" / "state"
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:80]
    return state_dir() / f"{safe}.json"


def load_state(session_id: str) -> dict:
    try:
        with open(state_path(session_id), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session_id: str, state: dict) -> None:
    p = state_path(session_id)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def fingerprint(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]


def read_hook_input() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def is_partial(tool_input: dict) -> bool:
    return tool_input.get("offset") is not None or tool_input.get("limit") is not None


def cmd_pre_read(hook: dict) -> None:
    session = hook.get("session_id") or ""
    tool_input = hook.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not session or not path or is_partial(tool_input):
        return
    fp = fingerprint(path)
    if fp is None or fp[1] < MIN_SIZE_BYTES:
        return
    entry = load_state(session).get(os.path.abspath(path))
    if entry != fp:
        return
    saved_est = fp[1] // CHARS_PER_TOKEN
    notice = (
        f"[read-cache] {os.path.basename(path)} is byte-identical to the version "
        f"already read in this session (~{saved_est:,} tokens not re-sent). "
        f"The earlier Read result is still valid. If you genuinely need the "
        f"content again (e.g. it was compacted away), re-Read with offset=1, "
        f"or Read a specific range."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": notice,
        }
    }))


def cmd_post_read(hook: dict) -> None:
    session = hook.get("session_id") or ""
    tool_input = hook.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not session or not path or is_partial(tool_input):
        return
    resp = hook.get("tool_response")
    if isinstance(resp, dict) and resp.get("is_error"):
        return
    fp = fingerprint(path)
    if fp is None or fp[1] < MIN_SIZE_BYTES:
        return
    state = load_state(session)
    state[os.path.abspath(path)] = fp
    save_state(session, state)


def cmd_invalidate(hook: dict) -> None:
    session = hook.get("session_id") or ""
    tool_input = hook.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not session or not path:
        return
    state = load_state(session)
    if state.pop(os.path.abspath(path), None) is not None:
        save_state(session, state)


def cmd_clear(hook: dict) -> None:
    session = hook.get("session_id") or ""
    if session:
        try:
            state_path(session).unlink(missing_ok=True)
        except OSError:
            pass
    now = time.time()
    try:
        for f in state_dir().glob("*.json"):
            try:
                if now - f.stat().st_mtime > STATE_TTL_SECS:
                    f.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        pass


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre-read"
    hook = read_hook_input()
    try:
        if mode == "pre-read":
            cmd_pre_read(hook)
        elif mode == "post-read":
            cmd_post_read(hook)
        elif mode == "invalidate":
            cmd_invalidate(hook)
        elif mode == "clear":
            cmd_clear(hook)
    except Exception:
        pass  # any internal failure must never block the user's tool call
    return 0


if __name__ == "__main__":
    sys.exit(main())
