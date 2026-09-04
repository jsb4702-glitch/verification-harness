#!/usr/bin/env python3
"""
memory-decay — osaurus MemoryDatabase.swift 감쇠수식(salience×0.5^(Δd/halfLife)) 이식.
2026-07-06 Agentic OS 4후보 재분석 후보3 변형채택분: per-turn 주입(REJECT) 대신
주기 consolidation 후보선별용. 자동삭제 없음 — 리포트만(사람게이트).

나이 신호: git 최종 콘텐츠커밋일(1순위) > frontmatter created(2순위) > 오늘(0d).
  mtime은 신호 아님(전체파일 주기터치 실측 2026-07-06 — 최고 16d로 균질, 무의미).
  git 허브 init=2026-07-01이라 그 이전 진짜 나이는 소실 — 하한으로만 취급.

half-life(타입별): project 90d / reference 60d / feedback·user 면제(재발방지 규칙은
사용빈도 감쇠 부적용). floor 0.2 → project 약 209d·reference 약 139d 무갱신 시 후보.

사용:
  decay.py stamp    # created: 백필(git 최초커밋일, 없으면 오늘) — 멱등
  decay.py report   # salience 전산출 + floor 미만 후보 리포트(stdout+REPORT.md)
  decay.py touch <name> [...]  # last_used 갱신(메모리 실사용 시 수동/Claude 호출)
"""
import os, re, sys, glob, math, json, subprocess, datetime

MDIR = os.path.expanduser("~/.claude/projects/-Users-user/memory")
REPORT = os.path.join(MDIR, "DECAY_REPORT.md")
GRAPH = os.path.expanduser("~/.local/share/memory-graph/graphify-out/graph.json")
HALF_LIFE = {"project": 90.0, "reference": 60.0}   # feedback/user = 면제
FLOOR = 0.2
ORPHAN_MIN_AGE_D = 14      # 신규 메모리는 아직 링크가 안 붙었을 뿐 — 고아 판정 제외
ORPHAN_COMPONENT_MAX = 2   # 고립 약연결요소 크기 1~2 = 후보 (단독 + 서로만 참조하는 쌍)
TODAY = datetime.date.today()


def _git(*args):
    r = subprocess.run(["git", "-C", MDIR] + list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _fm(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


def _field(fm, key):
    m = re.search(rf"^\s*{key}:\s*(\S+)", fm, re.M)
    return m.group(1).strip("\"'") if m else ""


def _files():
    return sorted(f for f in glob.glob(MDIR + "/*.md")
                  if os.path.basename(f) not in ("MEMORY.md", "DECAY_REPORT.md"))


def _date_of(f, fm):
    """나이 기준일: last_used > git 최종커밋 > created > 오늘."""
    for key in ("last_used", None, "created"):
        if key:
            v = _field(fm, key)
        else:
            v = _git("log", "-1", "--format=%as", "--", os.path.basename(f))
        if v:
            try:
                return datetime.date.fromisoformat(v), ("frontmatter:" + key if key else "git")
            except ValueError:
                pass
    return TODAY, "none(오늘로 간주)"


def stamp():
    n = 0
    for f in _files():
        text = open(f).read()
        fm = _fm(text)
        if not fm or _field(fm, "created"):
            continue
        first = _git("log", "--follow", "--format=%as", "--diff-filter=A",
                     "--", os.path.basename(f))
        created = (first.splitlines()[-1] if first else str(TODAY))
        # metadata: 블록 바로 아래 삽입(없으면 frontmatter 끝에)
        if re.search(r"^metadata:", fm, re.M):
            new_fm = re.sub(r"^(metadata:\s*\n)", rf"\1  created: {created}\n", fm, count=1, flags=re.M)
        else:
            new_fm = fm + f"\nmetadata:\n  created: {created}"
        open(f, "w").write(text.replace(fm, new_fm, 1))
        n += 1
    print(f"stamp: {n}건 백필 (git init 2026-07-01 이전 나이는 소실 — 하한값)")


def graph_orphans():
    """그래프 고립 신호 — 참고신호 전용(자동조치 없음).
    파일 단위 무향 성분 분해: 서로 다른 메모리 파일의 노드를 잇는 링크만 파일간 엣지로 침.
    성분 크기 ≤ ORPHAN_COMPONENT_MAX 이고 나이 ≥ ORPHAN_MIN_AGE_D 인 파일만 후보.
    반환: (후보 리스트[(name, 성분크기, 동반자, age)], 경고문 or None)"""
    if not os.path.exists(GRAPH):
        return [], f"그래프 파일 없음({GRAPH}) — graph-memory.sh 확인"
    warn = None
    age_g = (datetime.datetime.now()
             - datetime.datetime.fromtimestamp(os.path.getmtime(GRAPH))).days
    if age_g >= 2:
        warn = f"그래프 스테일 의심(갱신 {age_g}d 전) — 고아 판정 신뢰도 낮음"
    g = json.load(open(GRAPH))
    memfiles = {os.path.basename(f) for f in _files()}
    node_file = {n["id"]: n.get("source_file", "")
                 for n in g.get("nodes", []) if n.get("source_file") in memfiles}
    # 파일 단위 무향 인접 (서로 다른 파일 사이 링크만)
    adj = {f: set() for f in memfiles}
    for e in g.get("links", []):
        a, b = node_file.get(e.get("source")), node_file.get(e.get("target"))
        if a and b and a != b:
            adj[a].add(b); adj[b].add(a)
    # 약연결요소
    seen, comps = set(), []
    for f in memfiles:
        if f in seen:
            continue
        comp, stack = [], [f]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x)
            stack += [y for y in adj[x] if y not in seen]
        comps.append(sorted(comp))
    out = []
    for comp in comps:
        if len(comp) > ORPHAN_COMPONENT_MAX:
            continue
        for f in comp:
            fp = os.path.join(MDIR, f)
            fm = _fm(open(fp).read())
            d, _src = _date_of(fp, fm)
            age = max(0, (TODAY - d).days)
            if age < ORPHAN_MIN_AGE_D:
                continue
            partner = [x for x in comp if x != f]
            out.append((f[:-3], len(comp), partner[0][:-3] if partner else "-", age))
    out.sort(key=lambda r: (r[1], -r[3]))
    return out, warn


def report():
    rows = []
    for f in _files():
        text = open(f).read()
        fm = _fm(text)
        typ = _field(fm, "type") or "??"
        name = _field(fm, "name") or os.path.basename(f)[:-3]
        hl = HALF_LIFE.get(typ)
        d, src = _date_of(f, fm)
        age = max(0, (TODAY - d).days)
        sal = 0.5 ** (age / hl) if hl else 1.0
        rows.append((sal, age, typ, name, src, hl))
    rows.sort()
    cands = [r for r in rows if r[5] and r[0] < FLOOR]
    lines = [f"# DECAY_REPORT — {TODAY} (floor={FLOOR}, 자동조치 없음·사람게이트)",
             "", f"총 {len(rows)}건 / 후보 {len(cands)}건 (salience<{FLOOR}, feedback·user 면제)", ""]
    if cands:
        lines += ["| salience | 경과일 | type | name | 기준일소스 |", "|---|---|---|---|---|"]
        lines += [f"| {s:.3f} | {a}d | {t} | [[{n}]] | {src} |" for s, a, t, n, src, _ in cands]
        lines += ["", "→ 조치는 사람판정: 병합(merge) / archive/ 이동 / 유지(touch로 갱신)"]
    else:
        nxt = min((r for r in rows if r[5]), key=lambda r: r[0], default=None)
        if nxt:
            need = int(nxt[5] * math.log(1 / FLOOR, 2)) - nxt[1]
            lines.append(f"후보 없음. 최저 salience={nxt[0]:.3f}([[{nxt[3]}]], {nxt[1]}d) — "
                         f"현행 유지 시 약 {need}d 후 첫 후보 발생.")
    o_rows, o_warn = graph_orphans()
    lines += ["", f"## 그래프 고립 신호 (참고전용 — 자동조치 없음, 성분≤{ORPHAN_COMPONENT_MAX}·나이≥{ORPHAN_MIN_AGE_D}d)"]
    if o_warn:
        lines.append(f"⚠️ {o_warn}")
    if o_rows:
        lines += ["| name | 성분크기 | 동반자 | 경과일 |", "|---|---|---|---|"]
        lines += [f"| [[{n}]] | {c} | {p} | {a}d |" for n, c, p, a in o_rows]
        lines.append("→ salience 표와 결합해 사람판정 입력으로만. 링크 없음=무가치 아님(독립 레퍼런스 가능).")
    else:
        lines.append("고립 파일 없음.")
    out = "\n".join(lines) + "\n"
    open(REPORT, "w").write(out)
    print(out)


def touch(names):
    n = 0
    for f in _files():
        text = open(f).read()
        fm = _fm(text)
        if _field(fm, "name") not in names:
            continue
        if re.search(r"^\s*last_used:", fm, re.M):
            new_fm = re.sub(r"^(\s*last_used:\s*)\S+", rf"\g<1>{TODAY}", fm, count=1, flags=re.M)
        elif re.search(r"^metadata:", fm, re.M):
            new_fm = re.sub(r"^(metadata:\s*\n)", rf"\1  last_used: {TODAY}\n", fm, count=1, flags=re.M)
        else:
            continue
        open(f, "w").write(text.replace(fm, new_fm, 1))
        n += 1
    print(f"touch: {n}건 last_used={TODAY}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "stamp":
        stamp()
    elif cmd == "touch":
        touch(set(sys.argv[2:]))
    else:
        report()
