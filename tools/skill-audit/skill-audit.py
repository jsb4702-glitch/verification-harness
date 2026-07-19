#!/usr/bin/env python3
"""skill-audit — 스킬/플러그인 2트랙 오디터 (안전 + 품질) / per-SKILL.md 단위.

안전(Track1): skillscan NL룰 + inject-detect L1(regex) = 의심신호 → skill-guard(LoRA)로 확정.
              skillscan NL은 고recall·저precision(보안·메모리 스킬 FP) → skill-guard가 정밀 중재.
              verdict: MALICIOUS(guard 확정) / SUSPECT⚠(신호 있으나 guard 미확정·미가용) / BENIGN.
품질(Track2): substance = SUBSTANTIVE / THIN(얕음·개선여지) / HOLLOW(포장만·알맹이 없음).

외부 레포는 --repo 로 격리클론(--depth1·훅무력화·무실행) 후 감사. skill-guard는 의심 유닛에만(비용가드).

usage:
  skill-audit.py <path> [--json] [--no-guard] [--safety-only|--quality-only]
  skill-audit.py --repo owner/name [옵션...]
"""
import sys, os, re, json, subprocess, pathlib, shutil, tempfile, importlib.util

HOME = os.path.expanduser("~")
SKILLSCAN = f"{HOME}/.claude/tools/skillscan/skillscan.py"
GUARD = f"{HOME}/.claude/tools/skill-guard/skill-guard.py"
INJECT_DIR = pathlib.Path(f"{HOME}/.claude/tools/inject-detect")
NL_MAL = {"NL-INJECT", "NL-OVERRIDE", "NL-EXFIL-SECRET", "NL-MEMINJECT", "C-CURLPIPE", "C-DESTRUCT"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
SRC_EXT = {".py", ".js", ".ts", ".sh", ".go", ".rb", ".rs", ".mjs", ".cjs"}

# ---------- 품질(substance) ----------
HYPE = re.compile(r"\b(powerful|ultimate|seamless|revolutionary|cutting.?edge|state.of.the.art|"
                  r"effortless|magic(al)?|amazing|best.in.class|next.gen|blazing|supercharg\w*|"
                  r"robust|comprehensive|advanced|intelligent|smart|simply|easily|instantly|"
                  r"professional|enterprise.grade|world.class|game.chang\w*)\b", re.I)
STUB = re.compile(r"(TODO|FIXME|NotImplemented|coming soon|placeholder|your (code|logic) here|"
                  r"lorem ipsum|example only|\bWIP\b|not implemented|^\s*pass\s*$|\bstub\b)", re.I | re.M)
CONCRETE = re.compile(r"(^\s*\d+\.\s|^\s*[-*]\s+\S|```|`[^`]+`|(?<![\w])/[\w.-]+/[\w.-]+|https?://|\$\s?\w)", re.M)

def _loc(p):
    try: return sum(1 for ln in open(p, errors="replace") if ln.strip())
    except Exception: return 0

def code_loc_in(d):
    n = 0
    for root, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in fs:
            if pathlib.Path(f).suffix.lower() in SRC_EXT:
                n += _loc(os.path.join(root, f))
    return n

def substance(skill_md):
    doc = open(skill_md, errors="replace").read()
    doc_lines = sum(1 for ln in doc.splitlines() if ln.strip())
    hype, stubs, concrete = len(HYPE.findall(doc)), len(STUB.findall(doc)), len(CONCRETE.findall(doc))
    impl = code_loc_in(os.path.dirname(skill_md))
    has_sub = (impl >= 25) or (concrete >= 8)
    packaged = (hype >= 3) or (doc_lines >= 50)
    if packaged and not has_sub:
        tier = "HOLLOW"
    elif impl < 50 and concrete < 15:
        tier = "THIN"
    else:
        tier = "SUBSTANTIVE"
    return {"tier": tier, "impl_loc": impl, "concrete": concrete, "hype": hype,
            "doc_lines": doc_lines, "stubs": stubs}

# ---------- 안전 ----------
_pp = None
def _pp_load():
    global _pp
    if _pp is None:
        try:
            spec = importlib.util.spec_from_file_location("pp_detect", INJECT_DIR / "pp_detect.py")
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); _pp = m
        except Exception:
            _pp = False
    return _pp

def inject_l1(text):
    m = _pp_load()
    if not m:
        return {"flagged": None, "signals": []}
    try:
        s, h = m.scan(text); v = m.verdict(s)
        return {"flagged": (v.startswith("🚨") or "REVIEW" in v), "score": s, "signals": list(h.keys())}
    except Exception:
        return {"flagged": None, "signals": []}

def skillscan_unit(d):
    r = subprocess.run(["python3", SKILLSCAN, d, "--include-official", "--json", "/dev/stdout"],
                       capture_output=True, text=True, timeout=90)
    try:
        t = r.stdout; s = t.find("{"); e = t.rfind("}")
        finds = json.loads(t[s:e+1]).get("findings", []) if s >= 0 else []
    except Exception:
        finds = []
    return [f"{f['rule']}@{os.path.basename(f['file'])}:{f['line']}" for f in finds if f["rule"] in NL_MAL]

def guard(d):
    try:
        r = subprocess.run(["python3", GUARD, d, "--json"], capture_output=True, text=True, timeout=300)
        return "MAL" if r.returncode == 2 else ("BEN" if r.returncode == 0 else None)
    except Exception:
        return None

def audit_unit(skill_md, base, use_guard, quality_only, safety_only):
    d = os.path.dirname(skill_md)
    rec = {"unit": os.path.relpath(skill_md, base)}
    if not quality_only:
        nl = skillscan_unit(d)
        inj = inject_l1(open(skill_md, errors="replace").read())
        suspect = bool(nl) or bool(inj.get("flagged"))
        g = guard(d) if (suspect and use_guard) else None
        if g == "MAL":
            safety = "🔴 MALICIOUS"
        elif suspect and g == "BEN":
            safety = "🟡 suspect→cleared"
        elif suspect:
            safety = "🟠 SUSPECT⚠(미확정)"
        else:
            safety = "🟢 benign"
        rec.update({"safety": safety, "nl_hits": nl, "inject": inj.get("signals", []), "guard": g})
    if not safety_only:
        rec["quality"] = substance(skill_md)
    return rec

def find_skills(root):
    out = []
    for r, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in fs:
            if f.lower() == "skill.md":
                out.append(os.path.join(r, f))
    return out

def clone(repo, dest):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--depth", "1", "--quiet",
                        f"https://github.com/{repo}.git", dest], capture_output=True, text=True,
                       timeout=250, env=env)
    return r.returncode == 0

def main():
    a = sys.argv[1:]
    flags = {x for x in a if x.startswith("--")}
    use_guard = "--no-guard" not in flags
    quality_only = "--quality-only" in flags
    safety_only = "--safety-only" in flags
    as_json = "--json" in flags
    tmp = None
    if "--repo" in flags:
        repo = a[a.index("--repo") + 1]
        tmp = tempfile.mkdtemp(prefix="skill-audit-")
        base = os.path.join(tmp, repo.replace("/", "__"))
        if not clone(repo, base):
            print(f"clone 실패: {repo}"); sys.exit(1)
    else:
        pos = [x for x in a if not x.startswith("--")]
        base = pos[0] if pos else "."

    try:
        units = [audit_unit(s, base, use_guard, quality_only, safety_only) for s in find_skills(base)]
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    if as_json:
        print(json.dumps({"base": base, "n_units": len(units), "units": units}, ensure_ascii=False, indent=2))
        return
    # 표
    print(f"\n=== skill-audit: {len(units)} SKILL.md 유닛 ===")
    print(f"{'SAFETY':22} {'QUALITY':12} {'impl/concrete':14} UNIT")
    for u in units:
        saf = u.get("safety", "-")
        q = u.get("quality", {})
        qt = q.get("tier", "-")
        ic = f"{q.get('impl_loc','?')}/{q.get('concrete','?')}" if q else "-"
        print(f"{saf:22} {qt:12} {ic:14} {u['unit']}")
    # 2×2 요약
    if not quality_only and not safety_only:
        mal = [u for u in units if "MALICIOUS" in u.get("safety", "")]
        sus = [u for u in units if "SUSPECT" in u.get("safety", "")]
        hollow = [u for u in units if u.get("quality", {}).get("tier") == "HOLLOW"]
        thin = [u for u in units if u.get("quality", {}).get("tier") == "THIN"]
        t1 = [u for u in units if "MALICIOUS" in u.get("safety", "") and u.get("quality", {}).get("tier") != "HOLLOW"]
        t2 = [u for u in units if u.get("quality", {}).get("tier") in ("HOLLOW", "THIN") and "MALICIOUS" not in u.get("safety", "") and "SUSPECT" not in u.get("safety", "")]
        print(f"\n[요약] 악성 {len(mal)} · 미확정의심 {len(sus)} · HOLLOW {len(hollow)} · THIN {len(thin)}")
        print(f"  Track1(청소+리빌드 후보): {len(t1)}  |  Track2(채워서 유용하게 후보): {len(t2)}")

if __name__ == "__main__":
    main()
