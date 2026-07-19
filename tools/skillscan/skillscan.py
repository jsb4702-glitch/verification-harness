#!/usr/bin/env python3
"""
skillscan v2 — 로컬 Agent Skill / 플러그인 공급망 보안 스캐너 (정적 전용·네트워크 0)

설계 출처(참고만, 외부코드 미실행):
  - USENIX Security 2026, "Do Not Mention This to the User" (arXiv 2602.06547)
    : 98,380 스킬→157 악성, 13 공격기법. 코드층+자연어 지시층 동시 악용.
  - NVIDIA SkillSpector 17 카테고리(설계도로만 참조, 패키지 미설치)

v2 변경(fp-check 반영): 약한 토큰(token/secret/leak) HIGH 제외→강결합만,
  강한 비밀경로(.ssh/id_*/.credentials/.env)만 HIGH, --skip-official 기본 ON,
  산문(.md)은 강신호 NL룰만 적용(README/CHANGELOG FP 차단).

차별점 = 운영자 환경 특화: MEMORY.md/CLAUDE.md(정체성) 탈취·사칭을 별도 추적.

용법:
  python3 skillscan.py [경로 ...]          # 기본 ~/.claude/skills (+plugins는 --with-plugins)
  python3 skillscan.py --with-plugins       # 플러그인 캐시까지(공식은 여전히 스킵)
  python3 skillscan.py --include-official    # 공식 캐시도 포함(노이즈 많음)
  python3 skillscan.py --json report.json
판정: HIGH 1건+ = 격리/리뷰 전까지 신뢰금지. 정적 휴리스틱이라 FP 가능(사람이 최종판단).
"""
import os, re, sys, json, pathlib

HOME = os.path.expanduser("~")
SKILLS = os.path.join(HOME, ".claude", "skills")
PLUGINS = os.path.join(HOME, ".claude", "plugins")

# 강한 비밀/키 경로 — 단독 등장도 위협신호 (FP 거의 없음)
SECRET_STRONG = r"(\.ssh/|id_rsa|id_ed25519|id_ecdsa|authorized_keys|" \
                r"\.aws/credentials|\.claude/\.credentials|\.netrc|" \
                r"\.env\b|settings\.local\.json|private[_-]?key)"
# 정체성 파일 — 동사/유출 맥락에서만 위협 (단독은 정상 언급 많음)
# 2026-07-05: 내 환경 맥락적합 확장 — AGENTS.md(agy)·HEARTBEAT·memory dir·.cursor/rules
IDENTITY = r"(MEMORY\.md|USER\.md|SOUL\.md|CLAUDE\.md|AGENTS\.md|HEARTBEAT\.md|\.claude/memory|\.cursor/rules|persona\.(md|json)|\.credentials)"

# 자연어 지시층 IOC — 산문에도 적용(강신호)
NL_RULES = [
    ("NL-HIDE",  r"\b(do\s?n['o]?t|never)\s+(mention|tell|inform|reveal|disclose|notify|let)\b[^.\n]{0,45}\b(user|owner|operator|human)\b",
     "HIGH", "사용자 은닉 지시(논문 표제 archetype)", "prose+code"),
    ("NL-INJECT", r"ignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above|earlier|foregoing)[^.\n]{0,30}(instruction|prompt|rule|gate|guard)",
     "HIGH", "선행지시 무시 인젝션", "prose+code"),
    ("NL-EXFIL-SECRET", r"\b(read|cat|open|load|exfiltrat|send|upload|post|copy|dump)\b[^.\n]{0,40}" + SECRET_STRONG,
     "HIGH", "비밀/키 경로 접근·유출 지시(SSH키 탈취 등)", "prose+code"),
    ("NL-IDEXFIL", r"\b(exfiltrat|send|upload|post|transmit|copy)\b[^.\n]{0,30}" + IDENTITY,
     "HIGH", "정체성 파일 외부유출 지시(사칭 표적)", "prose+code"),
    ("NL-OVERRIDE", r"(developer\s+mode|jailbreak|unrestricted\s+mode|bypass\s+(the\s+)?(safety|filter|gate|guard|restriction))",
     "MED", "게이트/세이프티 우회 표현", "prose+code"),
    ("NL-AUTORUN", r"(automatically|silently|without\s+(asking|confirmation|telling))[^.\n]{0,25}(delete|exfiltrat|send|push|commit|curl|wget)",
     "MED", "무확인 자동 비가역/전송 행동", "prose+code"),
    # 2026-07-05: memory-poisoning/cognitive-rootkit (prompt-guard v3.5 SKILL_COGNITIVE_ROOTKIT 의도흡수·리빌드)
    # NL-IDEXFIL(유출)의 역방향 — 정체성/메모리 파일에 지시를 *주입*하는 지속성 백도어
    ("NL-MEMINJECT", r"\b(write|append|inject|implant|insert|echo|add|modify|overwrite)\b[^.\n]{0,45}(into|to|in)?\s*[^.\n]{0,15}" + IDENTITY,
     "HIGH", "정체성/메모리 파일 주입(persistent implant·memory poisoning)", "prose+code"),
    ("NL-PERSIST", r"(instruction|prompt|rule|directive|context|persona|payload|jailbreak)s?\s+[^.\n]{0,20}(persist|survive|stay\s+loaded|remain\s+(loaded|active))\b|"
                   r"(permanent(ly)?|always[_\-\s]?(loaded|injected)|auto[_\-\s]?inject)[^.\n]{0,30}(instruction|prompt|rule|directive|context|memory|persona)",
     "MED", "지시 지속화/자동주입(cognitive rootkit)", "prose+code"),
]

# 코드층 IOC — 실행파일 위주(산문에선 curl|bash 등 강한 것만)
CODE_RULES = [
    ("C-CURLPIPE", r"\b(curl|wget)\b[^\n|]{0,200}\|\s*(bash|sh|zsh|python3?|node)\b",
     "HIGH", "원격 다운로드→직접 실행(curl|bash)", "code-strong"),
    ("C-B64EXEC", r"base64\s+(-d|--decode|-D)\b[^\n|]{0,80}\|\s*(bash|sh|python3?|node)\b",
     "HIGH", "base64 디코드→실행(난독)", "code-strong"),
    ("C-REVSHELL", r"(/dev/tcp/\d|nc\s+-e|ncat\s+-e|bash\s+-i\b[^\n]{0,20}/dev/tcp)",
     "HIGH", "리버스셸 신호", "code-strong"),
    ("C-SSHREAD", r"(cat|cp|scp|base64|tar)\s+[^\n]{0,40}(\.ssh/(id_|authorized)|id_rsa|id_ed25519)",
     "HIGH", "SSH 개인키/권한키 추출", "code-strong"),
    ("C-ENVEXFIL", r"(printenv|os\.environ|process\.env)[^\n#]{0,60}(\|\s*(curl|wget|nc)\b|requests\.post|urllib\.request\.urlopen|fetch\(\s*['\"]https?)",
     "HIGH", "환경변수 덤프→전송", "code-strong"),
    ("C-NETPOST", r"(requests\.post|urllib\.request\.urlopen|axios\.post|http\.client)[^\n]{0,120}https?://",
     "MED", "외부 POST(하드코딩 URL)", "code-only"),
    ("C-EVAL", r"\b(eval|exec)\s*\(\s*(base64|requests\.|urllib\.|__import__|open\()",
     "MED", "동적 eval/exec + 외부소스", "code-only"),
    ("C-DESTRUCT", r"rm\s+-rf\s+(~|\$HOME|/\s|/\*|\"\$)|shutil\.rmtree\(\s*['\"]?(/|~)",
     "MED", "광범 파괴적 삭제", "code-only"),
    # 2026-07-19 신설: MalSkillBench 외부계측서 C-REVSHELL(셸원라이너 전용)이 놓친
    #   파이썬/네트워크 페이로드 계열. 변별력 50배+·정상오탐 0.05%(잔존2건=보안툴 문서예시).
    #   (C-DOWNLOAD-EXEC 후보는 좁힌창서 악성매치 0=죽은룰이라 폐기. exec(requests.get())
    #    직결형은 실전엔 없고 변수경유가 대부분 — 넓히면 오탐만 늘어 미채택.)
    ("C-PYREVSHELL", r"pty\.spawn|pty\.fork|os\.dup2\s*\(\s*\w+\.fileno|socket\.socket[\s\S]{0,400}(os\.dup2|pty\.spawn|/bin/(sh|bash))",
     "HIGH", "파이썬 리버스셸(dup2/pty+socket)", "code-strong"),
    ("C-SHELL-CALLBACK-IP", r"(connect|AF_INET)[\s\S]{0,120}\b\d{1,3}(\.\d{1,3}){3}\b[\s\S]{0,60}(444|4444|1337|9001|8080)",
     "HIGH", "하드코딩 IP 셸 콜백", "code-strong"),
]

BROAD_TRIGGER = re.compile(r"(any input|all (inputs|requests|messages)|every (input|message|request)|"
                           r"\bintercept\b|always (run|trigger|activate))", re.I)

CODE_EXT = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".ts", ".rb", ".pl", ".ps1"}
TEXT_EXT = {".md", ".markdown", ".txt", ".mdx"}
OFFICIAL_HINTS = ("claude-plugins-official", "/marketplaces/", "anthropics/")

def iter_files(root, skip_official):
    VENDOR = ("/.git/", "/node_modules/", "/__pycache__", "/.venv/", "/venv/",
              "/site-packages/", "/dist-info/", "/share/doc/", "/.tox/", "/vendor/")
    for dp, _, fns in os.walk(root):
        if any(seg in dp for seg in VENDOR):
            continue
        if skip_official and any(h in dp for h in OFFICIAL_HINTS):
            continue
        for fn in fns:
            yield os.path.join(dp, fn)

# --- 탐지기 자기매치 면제 (2026-07-18) ---------------------------------------
# 인젝션 탐지기의 시그니처 배열이 자기 룰에 걸리는 고전 self-match FP 차단.
# 경로 화이트리스트는 파일명 흉내로 우회되므로 쓰지 않고, 3조건 AND 구조판별:
#   ① 코드파일  ② 패턴목록 선언이 파일에 존재  ③ 매치줄이 "정규식투" 문자열 리터럴
# ③ 때문에 평문 영어 페이로드를 리스트에 숨겨도 면제되지 않는다(정규식 메타문자 요구).
DETECTOR_DECL = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*(?:PATTERN|SIGNATURE|RULE|IOC|REGEX|INJECT)[A-Za-z0-9_]*\s*[:=]",
    re.M | re.I)
LITERAL_LINE = re.compile(r"""^\s*(?:r|rb|br|f)?(['"]).*\1\s*,?\s*(?:#.*)?$""")
REGEXY = re.compile(r"\(\?i\)|\\[sSbBwWdD]|\[\^|\.\*|\.\+|\+\?|\{\d|\|")

def _detector_literal(line):
    """정규식 시그니처 리터럴 한 줄인가?"""
    if not LITERAL_LINE.match(line):
        return False
    s = line.lstrip()
    return s.startswith(("r'", 'r"', "rb", "br")) or bool(REGEXY.search(line))


def scan_file(path, rel):
    out = []
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read()
    except Exception:
        return out
    lines = text.splitlines()
    ext = pathlib.Path(path).suffix.lower()
    is_code = ext in CODE_EXT
    is_text = ext in TEXT_EXT
    base = os.path.basename(path).lower()
    is_skillmd = base in ("skill.md", "skill.markdown", "agent.md")

    # NL 룰: 산문/코드 모두. 단 산문에선 그대로(이미 강신호), 코드에도 적용.
    detector_ctx = is_code and bool(DETECTOR_DECL.search(text))
    for rid, pat, sev, desc, scope in NL_RULES:
        for m in re.finditer(pat, text, re.I):
            ln = text[:m.start()].count("\n") + 1
            raw = lines[ln-1] if ln-1 < len(lines) else ""
            if detector_ctx and _detector_literal(raw):
                continue   # 탐지기 시그니처 자기매치 — 면제
            snip = raw.strip()[:120]
            out.append({"rule": rid, "severity": sev, "desc": desc, "file": rel, "line": ln, "snippet": snip})
    # 코드 룰: 코드파일은 전체. 산문(.md)은 code-strong만(curl|bash 등) — README의 진짜 위협만.
    for rid, pat, sev, desc, scope in CODE_RULES:
        if is_text and scope != "code-strong":
            continue
        for m in re.finditer(pat, text, re.I):
            ln = text[:m.start()].count("\n") + 1
            snip = (lines[ln-1].strip()[:120] if ln-1 < len(lines) else "")
            out.append({"rule": rid, "severity": sev, "desc": desc, "file": rel, "line": ln, "snippet": snip})
    # 과광범 트리거: SKILL.md frontmatter
    if is_skillmd and is_text:
        fm = text.split("---", 2)
        head = fm[1] if len(fm) >= 3 else text[:600]
        if BROAD_TRIGGER.search(head):
            out.append({"rule": "T-BROAD", "severity": "LOW", "desc": "과광범 트리거(무차별 활성화)",
                        "file": rel, "line": 1, "snippet": "frontmatter"})
    return out

def fingerprint(f):
    snip = re.sub(r"\s+", " ", f.get("snippet", "")).strip()
    return f"{f['rule']}::{f['file']}::{snip}"

def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    def opt_val(name):
        if name in flags:
            i = sys.argv.index(name)
            return sys.argv[i+1] if i+1 < len(sys.argv) else None
        return None
    json_out = opt_val("--json")
    baseline_path = opt_val("--baseline")          # 이 파일의 finding은 "알려진것"→제외
    update_baseline = opt_val("--update-baseline")  # 현 finding을 baseline으로 저장 후 종료
    for v in (json_out, baseline_path, update_baseline):
        if v in pos:
            pos.remove(v)
    skip_official = "--include-official" not in flags
    targets = pos or ([SKILLS, PLUGINS] if "--with-plugins" in flags else [SKILLS])
    # 2026-07-18: cdx 실행표면도 공급망 대상 (번들 플러그인이 자동갱신됨 — 22:44 리프레시 실측)
    if "--with-codex" in flags and not pos:
        targets = targets + [os.path.join(HOME, ".codex", d) for d in ("skills", "plugins", "hooks")]
    # 자동실행 표면(SessionStart/PreToolUse 훅·에이전트 정의) — 최고권한 경로인데 스코프 밖이었다.
    # tools/·workflows/ 는 의도적 제외: 보안툴 코퍼스라 공격문자열이 테스트픽스처 = 구조적 FP.
    # 그쪽은 integrity-guard 해시 감시가 담당한다.
    if "--with-plugins" in flags and not pos:
        targets = targets + [os.path.join(HOME, ".claude", d) for d in ("hooks", "agents")]

    findings, scanned = [], 0
    for t in targets:
        if not os.path.exists(t):
            continue
        for fp in iter_files(t, skip_official):
            if pathlib.Path(fp).suffix.lower() not in (CODE_EXT | TEXT_EXT):
                continue
            scanned += 1
            findings.extend(scan_file(fp, os.path.relpath(fp, HOME)))

    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    findings.sort(key=lambda x: (order.get(x["severity"], 9), x["file"]))

    # --update-baseline: 현재 finding을 알려진 기준선으로 저장 후 종료
    if update_baseline:
        # 2026-07-18: 교체 → 병합. 좁은 스코프로 뜨면 넓은 스코프 기준선이 증발하던 함정 차단
        # (targets는 위치인자로 바뀌므로 --with-plugins 스캔이 tools/ 항목을 통째로 날렸음).
        cur = set(fingerprint(x) for x in findings)
        prior = set()
        if os.path.exists(update_baseline):
            try:
                prior = set(json.load(open(update_baseline)).get("fingerprints", []))
            except Exception:
                prior = set()
        merged = sorted(cur | prior)
        with open(update_baseline, "w") as f:
            json.dump({"fingerprints": merged}, f, indent=2, ensure_ascii=False)
        print(f"baseline saved: {update_baseline} ({len(merged)} fingerprints — "
              f"신규 +{len(cur - prior)}, 기존유지 {len(prior)})")
        return 0

    # --baseline: 알려진 finding 제외(새로 생긴 위협만 남김)
    new_count = len(findings)
    if baseline_path and os.path.exists(baseline_path):
        try:
            known = set(json.load(open(baseline_path)).get("fingerprints", []))
            findings = [x for x in findings if fingerprint(x) not in known]
        except Exception:
            pass

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    if json_out:
        with open(json_out, "w") as f:
            json.dump({"scanned_files": scanned, "counts": counts, "findings": findings}, f, indent=2, ensure_ascii=False)
        print(f"JSON written: {json_out} (HIGH={counts.get('HIGH',0)} MED={counts.get('MED',0)} LOW={counts.get('LOW',0)})")
    else:
        print(f"\n=== skillscan v2: {scanned} files, targets={targets}, skip_official={skip_official} ===")
        print(f"HIGH={counts.get('HIGH',0)}  MED={counts.get('MED',0)}  LOW={counts.get('LOW',0)}\n")
        if not findings:
            print("clean — no IOC matched.")
        for f in findings:
            print(f"[{f['severity']:4}] {f['rule']:16} {f['file']}:{f['line']}")
            print(f"        {f['desc']}")
            if f['snippet']:
                print(f"        > {f['snippet']}")
    return 2 if counts.get("HIGH") else (1 if counts.get("MED") else 0)

if __name__ == "__main__":
    sys.exit(main())
