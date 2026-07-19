#!/usr/bin/env python3
"""skillscan_shadow.py — supplement 룰(WS2)의 섀도 러너.

skillscan.py 본체를 건드리지 않고(차단판정 불변), supplement 룰만 스킬/플러그인 트리에
돌려 히트를 JSONL 로그로만 남긴다. 격리·차단 없음 = 비차단 섀도. 1주 관찰용.

정상 스킬 트리에서의 히트 = FP 후보(현 스냅샷은 전부 정상이므로). FP=0 유지되면 승급.
사용: python3 skillscan_shadow.py [--targets DIR ...]  (기본: ~/.claude/skills + plugins)
로그: shadow/skillscan_shadow.jsonl 에 {ts, rule, file, line, snippet} append + 요약 stdout.
"""
import os, sys, re, json, time, pathlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from skillscan_rules_supplement import NL_RULES_SUPPLEMENT, CODE_RULES_SUPPLEMENT

HOME = os.path.expanduser("~")
SKILLS = os.path.join(HOME, ".claude", "skills")
PLUGINS = os.path.join(HOME, ".claude", "plugins")
LOGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow")
LOG = os.path.join(LOGDIR, "skillscan_shadow.jsonl")
CODE_EXT = {".py", ".js", ".ts", ".sh", ".rb", ".go", ".ps1", ".json", ".yaml", ".yml"}
TEXT_EXT = {".md", ".markdown", ".txt"}
# skillscan과 동일: 공식/vendored 스킬·서드파티 의존성 스킵(FP 소음원)
# 섀도 실측(2026-07-12): venv/site-packages 미스킵 시 벤더 minified JS서 X-HIDDEN-UNICODE 54 FP.
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "references",
             "venv", ".venv", "site-packages", "dist", "build", ".tox", "vendor"}


def iter_files(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if pathlib.Path(fn).suffix.lower() in (CODE_EXT | TEXT_EXT):
                yield os.path.join(dp, fn)


def scan(text, rel):
    hits = []
    is_text = pathlib.Path(rel).suffix.lower() in TEXT_EXT
    for rid, pat, sev, desc, scope in NL_RULES_SUPPLEMENT + CODE_RULES_SUPPLEMENT:
        # scope=text-strong 룰은 자연어 문서에만 (코드파일 FP 방지)
        if scope == "text-strong" and not is_text:
            continue
        for m in pat.finditer(text):
            ln = text[:m.start()].count("\n") + 1
            line = text.splitlines()[ln-1].strip()[:120] if ln-1 < len(text.splitlines()) else ""
            hits.append({"rule": rid, "severity": sev, "desc": desc,
                         "file": rel, "line": ln, "snippet": line})
    return hits


def main():
    args = sys.argv[1:]
    targets = [a for a in args if not a.startswith("--")] or [SKILLS, PLUGINS]
    os.makedirs(LOGDIR, exist_ok=True)
    ts = round(time.time())
    all_hits, scanned = [], 0
    for t in targets:
        if not os.path.exists(t):
            continue
        for fp in iter_files(t):
            scanned += 1
            try:
                with open(fp, "r", errors="replace") as f:
                    text = f.read()
            except Exception:
                continue
            all_hits.extend(scan(text, os.path.relpath(fp, HOME)))
    with open(LOG, "a") as f:
        for h in all_hits:
            f.write(json.dumps({"ts": ts, **h}, ensure_ascii=False) + "\n")
    # 요약
    by_rule = {}
    for h in all_hits:
        by_rule[h["rule"]] = by_rule.get(h["rule"], 0) + 1
    print(f"[shadow {ts}] scanned={scanned} files, hits={len(all_hits)} "
          f"(정상 트리이므로 hits=FP 후보)")
    for r, n in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {r}: {n}")
    if all_hits:
        print("--- 히트 상세(FP 검토용) ---")
        for h in all_hits[:20]:
            print(f"  {h['rule']} :: {h['file']}:{h['line']} :: {h['snippet'][:80]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
