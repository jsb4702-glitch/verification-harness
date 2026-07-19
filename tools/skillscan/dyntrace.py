#!/usr/bin/env python3
"""dyntrace.py - mini dynamic sandbox for Claude Code skill/plugin scripts.

Runs a Python script under a PEP-578 audit hook inside an isolated subprocess
and reports every RISKY operation the script *attempted*:
  - network        (socket.* / urllib / http.client)   -> BLOCKED by default
  - process        (subprocess / os.system / os.exec*)  -> BLOCKED by default
  - sensitive_file (open of ~/.ssh, ~/.claude, .credentials, keychain, .aws ...)
  - dynamic_code   (runtime exec/eval/compile of strings -> deobfuscation point)
  - suspect_import (ctypes / marshal / pickle)

Why this beats base64/eval obfuscation:
  Static grep is blind to `exec(base64.b64decode(...))`. But when that payload
  actually runs, ITS OWN socket.connect / open('~/.ssh/..') still fire audit
  events -- the deobfuscated code cannot hide its syscalls. We catch the intent
  at the syscall boundary, not in the source text.

Isolation: subprocess runs with a FAKE empty HOME and a SANITIZED env (no
inherited secrets/API keys), stdin=/dev/null, and a wall-clock timeout. Network
and process-spawn attempts are recorded then blocked, so nothing actually
exfiltrates or executes during the trace.

LIMITS (honest): dynamic analysis only sees code paths that actually run.
Logic/time bombs gated on a date or C2 command, and sandbox-evasive payloads,
can stay dormant. Use together with the static skillscan pass and an egress
firewall (LuLu). This raises detection; it is not a proof of safety.

Usage:
  dyntrace.py <script.py | skill_dir> [--json] [--allow-net] [--timeout N] [-- args...]
    --json       machine-readable report
    --allow-net  observe instead of block (ONLY in a throwaway VM)
    --timeout N  per-script wall-clock seconds (default 15)
    -- args...   argv passed through to the target script
"""
import sys, os, json


# --------------------------------------------------------------------------
# INNER: runs inside the isolated subprocess, installs the audit hook.
# --------------------------------------------------------------------------
def _inner():
    import runpy  # noqa: F401  (kept available for callers that prefer it)

    # Target packages live under ~/.claude/skill-intake, so import-machinery
    # __pycache__ writes/reads inside the quarantine tree would trip the
    # "/.claude" sensitive-path rule. Disable bytecode caching entirely:
    # no pyc artifacts, zero detection loss (SENS rules untouched).
    sys.dont_write_bytecode = True

    report_path = os.environ["_DYNTRACE_REPORT"]
    target = os.environ["_DYNTRACE_TARGET"]
    allow_net = os.environ.get("_DYNTRACE_ALLOWNET") == "1"
    passthrough = json.loads(os.environ.get("_DYNTRACE_ARGV", "[]"))

    events = []
    state = {"armed": False, "reentry": False}

    SENS = (
        "/.ssh", "/.claude", ".credentials", "id_rsa", "id_ed25519", "id_dsa",
        "keychain", "/.aws", "/.config/gcloud", "/.netrc", "/.docker/config",
        "/.gnupg", "/.kube", "/.npmrc", "/.pypirc", "/.git-credentials",
    )

    # Self-tree exemption: the quarantine tree lives under ~/.claude/skill-intake,
    # so the target reading its OWN files (import of its .py sources / pycache)
    # would trip the "/.claude" rule. Reads inside the scan root are the code's
    # own content (already quarantined) = not exfil. Everything outside the
    # scan root -- including OTHER pending intake trees -- still flags.
    SCANROOT = os.environ.get("_DYNTRACE_SCANROOT", "")
    if SCANROOT:
        SCANROOT = os.path.realpath(SCANROOT).lower().replace("\\", "/")

    def _in_scanroot(rawpath):
        # realpath defeats symlink-out-of-tree dodges; on failure fail closed.
        if not SCANROOT:
            return False
        state["reentry"] = True  # realpath fires audit events; drop them
        try:
            rp = os.path.realpath(rawpath).lower().replace("\\", "/")
        except Exception:
            return False
        finally:
            state["reentry"] = False
        return rp == SCANROOT or rp.startswith(SCANROOT + "/")

    def classify(event, args):
        e = event
        # network
        if e.startswith("socket.") or e.startswith("urllib") \
                or e.startswith("http.client") or e == "socket.getaddrinfo":
            return ("network", "high")
        # process / command execution
        if e.startswith("subprocess.") or e == "os.system" \
                or e.startswith("os.exec") or e.startswith("os.spawn") \
                or e == "os.posix_spawn" or e.startswith("os.fork") \
                or e == "pty.spawn":
            return ("process", "high")
        # runtime dynamic code (deobfuscation point). The import machinery uses
        # exec/compile/marshal on real .py module files at load time -- that is
        # noise. Genuine runtime codegen (exec of a string built at runtime) has
        # a synthetic co_filename like "<string>"/"<stdin>"/"" -- THAT is signal.
        def _is_real_module_file(fname):
            f = (fname or "").lower()
            return f == target.lower() or f.endswith(".py") or f.endswith(".pyc")
        if e == "compile":
            try:
                fname = str(args[1])
            except Exception:
                fname = ""
            if _is_real_module_file(fname):
                return (None, None)
            # collections.namedtuple compiles `lambda _cls,...: _tuple_new(...)`
            # at import time for many stdlib types (urllib/ssl/...) -> noise.
            try:
                src = args[0]
                src_txt = src.decode("utf-8", "replace") if isinstance(src, (bytes, bytearray)) else str(src)
            except Exception:
                src_txt = ""
            if "_tuple_new(" in src_txt and "lambda _cls" in src_txt:
                return (None, None)
            return ("dynamic_code", "medium")
        # NOTE: we intentionally do NOT flag bare `exec` events. String code
        # (incl. exec(base64.b64decode(...))) is always preceded by a `compile`
        # event carrying the readable source -- that is the better signal point.
        # Flagging exec too just doubles up and adds <module>-load noise.
        # pickle/ctypes are real RCE vectors and (unlike marshal) are not part
        # of the normal import path, so flag them. marshal.loads is dropped:
        # zipimport/frozen stdlib uses it constantly -> pure noise.
        if e in ("pickle.find_class", "ctypes.dlopen", "ctypes.dlsym"):
            return ("dynamic_code", "medium")
        # sensitive file access
        if e == "open":
            try:
                path = str(args[0]).lower().replace("\\", "/")
            except Exception:
                path = ""
            if any(s in path for s in SENS):
                if _in_scanroot(str(args[0])):
                    return (None, None)  # self-tree read = target's own code
                return ("sensitive_file", "high")
            return (None, None)  # ordinary file I/O = noise, ignore
        # suspicious imports
        if e == "import":
            try:
                mod = str(args[0])
            except Exception:
                mod = ""
            # socket/urllib imports are ubiquitous+benign; real network intent
            # is caught at socket.connect (high). Flag only the unusual RCE/
            # deserialization-capable modules here.
            if mod in ("ctypes", "marshal", "pickle"):
                return ("suspect_import", "low")
            return (None, None)
        return (None, None)

    def hook(event, args):
        if not state["armed"] or state["reentry"]:
            return
        cat, sev = classify(event, args)
        if cat is None:
            return
        state["reentry"] = True
        try:
            try:
                detail = repr(args)
                if len(detail) > 240:
                    detail = detail[:240] + "...(truncated)"
            except Exception:
                detail = "<unrepr>"
            blocked = (not allow_net) and cat in ("network", "process")
            events.append({
                "event": event, "category": cat,
                "severity": sev, "detail": detail, "blocked": blocked,
            })
            if blocked:
                raise PermissionError("dyntrace: BLOCKED %s" % event)
        finally:
            state["reentry"] = False

    # compile the target BEFORE arming so its own load doesn't self-report
    try:
        with open(target, "r") as f:
            src = f.read()
        code = compile(src, target, "exec")
    except Exception as ex:
        with open(report_path, "w") as f:
            json.dump({"target": target, "error": "load: %r" % ex,
                       "events": []}, f)
        return

    sys.addaudithook(hook)

    g = {"__name__": "__main__", "__file__": target,
         "__builtins__": __builtins__}
    tdir = os.path.dirname(os.path.abspath(target))
    if tdir not in sys.path:
        sys.path.insert(0, tdir)
    sys.argv = [target] + passthrough

    err = None
    state["armed"] = True
    try:
        exec(code, g)
    except SystemExit:
        pass
    except PermissionError as ex:
        err = "halted by block: %s" % ex
    except BaseException as ex:  # noqa: BLE001 - we want to record anything
        err = "%s: %s" % (type(ex).__name__, ex)
    finally:
        state["armed"] = False

    with open(report_path, "w") as f:
        json.dump({"target": target, "error": err, "events": events}, f)


# --------------------------------------------------------------------------
# OUTER: CLI, spawns the isolated subprocess, aggregates the report.
# --------------------------------------------------------------------------
def _light_static(path):
    """Cheap static obfuscation indicator to correlate with dynamic findings."""
    import re, math
    try:
        src = open(path, "r", errors="replace").read()
    except Exception:
        return {}
    flags = {
        "eval(": src.count("eval("),
        "exec(": src.count("exec("),
        "b64decode": src.count("b64decode") + src.count("base64"),
        "compile(": src.count("compile("),
        "__import__": src.count("__import__"),
        "fromhex/unhexlify": src.count("unhexlify") + src.count("fromhex"),
        "getattr-chains": len(re.findall(r"getattr\([^)]*getattr", src)),
    }
    # longest contiguous base64-ish literal + its Shannon entropy
    longest, ent = "", 0.0
    for m in re.findall(r"['\"]([A-Za-z0-9+/=]{60,})['\"]", src):
        if len(m) > len(longest):
            longest = m
    if longest:
        from collections import Counter
        n = len(longest)
        ent = -sum((c / n) * math.log2(c / n) for c in Counter(longest).values())
    flags = {k: v for k, v in flags.items() if v}
    return {"indicators": flags, "max_b64_blob_len": len(longest),
            "blob_entropy_bits": round(ent, 2)}


def _run_one(target, timeout, allow_net, passthrough):
    import tempfile, subprocess, shutil
    tmphome = tempfile.mkdtemp(prefix="dyntrace_home_")
    fd, report = tempfile.mkstemp(prefix="dyntrace_rep_", suffix=".json")
    os.close(fd)
    env = {"_DYNTRACE_INNER": "1", "_DYNTRACE_TARGET": os.path.abspath(target),
           "_DYNTRACE_REPORT": report, "_DYNTRACE_ARGV": json.dumps(passthrough),
           "_DYNTRACE_SCANROOT": os.environ.get("_DYNTRACE_SCANROOT", ""),
           "HOME": tmphome, "TMPDIR": tmphome}
    if allow_net:
        env["_DYNTRACE_ALLOWNET"] = "1"
    for k in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SystemRoot"):
        if k in os.environ:
            env[k] = os.environ[k]
    timed_out = False
    out = ""
    try:
        p = subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, text=True, errors="replace",
        )
        out = p.stdout or ""
    except subprocess.TimeoutExpired as ex:
        timed_out = True
        out = (ex.stdout or "") if isinstance(ex.stdout, str) else ""
    rep = {"target": target, "error": None, "events": []}
    try:
        with open(report) as f:
            rep = json.load(f)
    except Exception:
        pass
    finally:
        shutil.rmtree(tmphome, ignore_errors=True)
        try:
            os.remove(report)
        except OSError:
            pass
    rep["timed_out"] = timed_out
    rep["stdout_tail"] = out[-400:] if out else ""
    rep["static"] = _light_static(target)
    return rep


def _collect_targets(path):
    if os.path.isfile(path):
        return [path]
    skip = {"__pycache__", ".git", "node_modules", ".venv", "venv", "site-packages"}
    found = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if fn.endswith(".py"):
                found.append(os.path.join(root, fn))
    return sorted(found)[:50]


def _any_high(reps):
    return any(e.get("severity") == "high"
               for rep in reps for e in rep.get("events", []))


def _print_report(reps, as_json):
    if as_json:
        out = {"any_high": _any_high(reps), "reports": reps}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return _any_high(reps)
    SEV = {"high": 3, "medium": 2, "low": 1}
    any_high = False
    for rep in reps:
        print("=" * 70)
        print("TARGET : %s" % rep["target"])
        st = rep.get("static") or {}
        if st.get("indicators") or st.get("max_b64_blob_len", 0) >= 60:
            print("STATIC : %s | max_b64_blob=%s entropy=%s bits"
                  % (st.get("indicators", {}), st.get("max_b64_blob_len", 0),
                     st.get("blob_entropy_bits", 0)))
        if rep.get("timed_out"):
            print("WARN   : timed out (possible dormant/long-running payload)")
        if rep.get("error"):
            print("EXIT   : %s" % rep["error"])
        evs = rep.get("events", [])
        # dedupe identical (event, detail) with a count
        agg = {}
        for e in evs:
            key = (e["category"], e["severity"], e["event"], e["detail"], e["blocked"])
            agg[key] = agg.get(key, 0) + 1
        if not agg:
            print("DYNAMIC: clean - no risky operations observed")
        else:
            print("DYNAMIC: %d risky operation(s) observed:" % len(evs))
            for (cat, sev, ev, det, blk), n in sorted(
                    agg.items(), key=lambda kv: -SEV.get(kv[0][1], 0)):
                if sev == "high":
                    any_high = True
                tag = "[BLOCKED]" if blk else ""
                cnt = (" x%d" % n) if n > 1 else ""
                print("  %-6s %-15s %-22s %s %s%s"
                      % (sev.upper(), cat, ev, tag, det, cnt))
    print("=" * 70)
    print("VERDICT: %s" % ("SUSPICIOUS - high-severity behavior observed, review before trusting"
                           if any_high else
                           "no high-severity dynamic behavior observed (NOT a safety proof)"))
    return any_high


def _outer():
    args = sys.argv[1:]
    as_json = False
    allow_net = False
    timeout = 15
    target = None
    passthrough = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--allow-net":
            allow_net = True
        elif a == "--timeout":
            i += 1
            timeout = int(args[i])
        elif a == "--":
            passthrough = args[i + 1:]
            break
        elif a.startswith("-"):
            sys.stderr.write("unknown flag: %s\n" % a)
            sys.exit(2)
        elif target is None:
            target = a
        i += 1
    if not target:
        sys.stderr.write(__doc__)
        sys.exit(2)
    if not os.path.exists(target):
        sys.stderr.write("no such path: %s\n" % target)
        sys.exit(2)
    # Self-tree exemption root: dir scans exempt the whole tree; single-file
    # scans exempt only that file (siblings still count as sensitive).
    os.environ["_DYNTRACE_SCANROOT"] = os.path.realpath(os.path.abspath(target))
    targets = _collect_targets(target)
    if not targets:
        sys.stderr.write("no .py files found under %s\n" % target)
        sys.exit(1)
    reps = [_run_one(t, timeout, allow_net, passthrough) for t in targets]
    any_high = _print_report(reps, as_json)
    # exit 3 signals "high-severity dynamic behavior found" for shell gates
    sys.exit(3 if any_high else 0)


if __name__ == "__main__":
    if os.environ.get("_DYNTRACE_INNER") == "1":
        _inner()
    else:
        _outer()
