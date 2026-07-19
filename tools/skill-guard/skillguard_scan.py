#!/usr/bin/env python3
"""skillguard_scan.py — skill-guard(4층 악성분류)를 활성 스킬트리에 증분 상시스캔.

skill-guard.py는 호출당 모델 1회 로드(≈5.2s/건). 여기선 모델을 1회만 로드하고
변경분만 루프 → 배치비용 = load 1회 + N×generate.

증분: 스킬 디렉토리별 내용해시를 manifest.json에 보관. 해시가 바뀐(또는 신규) 디렉토리만 태운다.
모드: shadow 고정(비차단·경고전용). 자동격리 안 함 — 판정은 사람게이트(G11 백스톱 원칙).

usage:
  skillguard_scan.py                # 증분(변경분만). 훅용.
  skillguard_scan.py --all          # 전량 재스캔(baseline 수립용)
  skillguard_scan.py --seed-only    # 태우지 않고 manifest만 기록(초기 무비용 배선)
  skillguard_scan.py --dry-run      # 대상만 출력, 모델 로드 안 함
"""
import sys, os, json, glob, time, hashlib, datetime, argparse

HOME = os.path.expanduser("~")
TOOLDIR = os.path.join(HOME, ".claude", "tools", "skill-guard")
MANIFEST = os.path.join(TOOLDIR, "scan_manifest.json")
# 알려진 오탐: 판정은 계속 기록하되 알림/경고만 억제(알람 피로 방지). 사람이 명시 등재만.
ALLOWLIST = os.path.join(TOOLDIR, "scan_allowlist.json")
# 실행도장(무변경이라 조용히 끝나도 찍힘) — 훅이 실제로 돌았는지 확인용
STAMP = os.path.join(HOME, ".claude", "logs", "skillguard-scan.last")
SHADOW_LOG = os.path.join(TOOLDIR, "shadow.jsonl")
LOG = os.path.join(TOOLDIR, "scan.log")

SKILL_ROOTS = [
    os.path.join(HOME, ".claude", "skills"),
    os.path.join(HOME, ".claude", "plugins"),
]
# 서드파티 벤더링(venv 안에 딸려온 SKILL.md 등)은 스킬트리가 아님 — 제외
EXCLUDE_PARTS = ("/site-packages/", "/.venv/", "/venv/", "/node_modules/", "/__pycache__/")
HASH_GLOBS = ["SKILL.md", "*.md", "*.py", "*.sh", "*.js", "*.ts", "*.json", "*.toml", "*.yaml", "*.yml"]

# 검사창 분할 (2026-07-19 실측). 24000자 조각 2개까지 = 최대 47000자 커버.
# 조각을 6000자로 잘게 쪼개면 파편이 스킬 문서처럼 안 보여 오탐 9~16%로 폭증하지만,
# 24000자 조각은 그 자체로 문서처럼 보여 2번째 조각 오탐도 5.1%에 머문다(1번째 4.3%).
MAX_CHUNKS = 2
CHUNK_OVERLAP = 1000

sys.path.insert(0, TOOLDIR)


def excluded(path):
    return any(p in path for p in EXCLUDE_PARTS)


def discover_skills():
    """SKILL.md를 가진 디렉토리 = 스킬 1단위."""
    out = []
    for root in SKILL_ROOTS:
        if not os.path.isdir(root):
            continue
        for sm in glob.glob(os.path.join(root, "**", "SKILL.md"), recursive=True):
            if excluded(sm):
                continue
            out.append(os.path.dirname(sm))
    return sorted(set(out))


def dir_hash(d):
    """스킬 디렉토리의 지시층+코드층 내용해시. mtime 아닌 내용 기반(touch 오탐 회피)."""
    h = hashlib.sha256()
    files = set()
    for pat in HASH_GLOBS:
        for fp in glob.glob(os.path.join(d, "**", pat), recursive=True):
            if os.path.isfile(fp) and not excluded(fp):
                files.add(fp)
    for fp in sorted(files):
        h.update(os.path.relpath(fp, d).encode())
        try:
            with open(fp, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def load_manifest():
    try:
        return json.load(open(MANIFEST, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(m):
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, MANIFEST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="전량 재스캔")
    ap.add_argument("--seed-only", action="store_true", help="태우지 않고 manifest만 기록")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력")
    # 2026-07-19 실측으로 6000 -> 24000. 6000자 창은 앞에 무해한 글 6000자만 깔면
    # 탐지 35%->0%로 무너짐(악성 20샘플). 24000자면 같은 조건서 40%, 오탐은 4.3% 그대로(신규 0건).
    # 분할검사(6000x겹침)는 탐지 65%로 더 높지만 문서 중간을 자른 파편이 스킬처럼 안 보여
    # 오탐 23.7%로 폭증 -> 기각. 지연 2.5s -> 6.4s/건(비동기라 체감 없음).
    ap.add_argument("--max-chars", type=int, default=24000)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    skills = discover_skills()
    man = load_manifest()
    hashes = {d: dir_hash(d) for d in skills}

    if a.all:
        targets = skills
    else:
        targets = [d for d in skills if man.get(d, {}).get("hash") != hashes[d]]

    ts = datetime.datetime.now().isoformat(timespec="seconds")

    # 실행도장 — 변경분이 없으면 이 스캐너는 조용히 끝나므로, 도장이 없으면
    # '훅이 안 돌았다'와 '돌았는데 할 일이 없었다'를 구분할 수 없다.
    # secondbrain_mirror_hook 패턴 차용(heartbeat가 스테일 감지에 씀).
    if not a.dry_run:
        try:
            os.makedirs(os.path.dirname(STAMP), exist_ok=True)
            with open(STAMP, "w", encoding="utf-8") as f:
                f.write(f"{ts} n_targets={len(targets)} n_skills={len(skills)}\n")
        except OSError:
            pass

    if a.seed_only:
        for d in skills:
            man[d] = {"hash": hashes[d], "seeded": ts}
        save_manifest(man)
        print(f"skillguard_scan: manifest seed {len(skills)}개 (미스캔)")
        return 0

    if a.dry_run:
        print(f"대상 {len(targets)}/{len(skills)}:")
        for d in targets:
            print("  " + os.path.relpath(d, HOME))
        return 0

    # 사라진 스킬은 manifest에서 제거(무한증식 방지)
    stale = [k for k in man if k not in hashes]
    if stale:
        for k in stale:
            man.pop(k)
        save_manifest(man)

    if not targets:
        return 0  # 변경 없음 → 조용히 통과

    # 모델 1회 로드 (여기서부터가 비싼 구간)
    t_load0 = time.time()
    from mlx_lm import load, generate
    import importlib.util
    spec = importlib.util.spec_from_file_location("skillguard", os.path.join(TOOLDIR, "skill-guard.py"))
    sg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sg)

    system = sg.load_system_prompt()
    model, tok = load(sg.BASE_MODEL, adapter_path=sg.resolve_adapter())
    t_load = round(time.time() - t_load0, 2)

    try:
        allow = set(json.load(open(ALLOWLIST, encoding="utf-8")).get("known_fp", []))
    except (OSError, ValueError):
        allow = set()

    def classify(text):
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"<<<SKILL>>>\n{text}\n<<<END>>>"}],
            add_generation_prompt=True, tokenize=False,
        )
        t0 = time.time()
        out = generate(model, tok, prompt=prompt, max_tokens=80, verbose=False)
        dt = round(time.time() - t0, 2)
        if not isinstance(out, str):
            out = getattr(out, "text", str(out))
        mv = sg.VERDICT_RE.search(out)
        mc = sg.CAT_RE.search(out)
        mf = sg.CONF_RE.search(out)
        return {
            "verdict": mv.group(1) if mv else "PARSE_FAIL",
            "category": mc.group(1) if mc else "",
            "confidence": float(mf.group(1)) if mf else None,
            "latency_s": dt, "chars": len(text),
            "raw": (None if mv else out.strip()[:200]),
        }

    flagged, results = [], []
    for d in targets:
        full = sg.gather_content(d, a.max_chars * MAX_CHUNKS)
        # 조각 나누기: 앞에서 한 창, 넘치면 '문서 끝에서' 한 창 더.
        # 뒤 조각을 끝에 붙여 잡는 이유 — step으로 밀면 마지막에 자투리가 남는데,
        # 자투리는 문장 중간에서 시작하는 작은 파편이라 오탐 덩어리다.
        # (실측: m5-onboard 23,778자에서 778자 자투리가 3/3 악성 오판. 끝기준이면 안 생긴다.)
        pieces = [full[:a.max_chars]]
        if len(full) > a.max_chars and MAX_CHUNKS >= 2:
            pieces.append(full[-a.max_chars:])
        res, hit_chunk = None, None
        for j, piece in enumerate(pieces):
            r = classify(piece)
            if res is None or r["verdict"] != "BENIGN":
                res, hit_chunk = r, j
            if r["verdict"] != "BENIGN":
                break        # 하나라도 걸리면 악성 — 나머지 조각 생략
        res = dict(res, src="always-on-scan", chunk=hit_chunk, n_chunks=len(pieces),
                   total_chars=len(full))
        sg.append_shadow(d, res)
        results.append((d, res))
        # allowlist는 알림만 억제 — shadow.jsonl 기록은 그대로(감사추적 보존)
        if res["verdict"] != "BENIGN" and os.path.basename(d) not in allow:
            flagged.append((d, res))
        # 스캔 성공한 것만 manifest 갱신 → 중단돼도 다음 회차에 재시도
        man[d] = {"hash": hashes[d], "scanned": ts, "verdict": res["verdict"]}

    save_manifest(man)

    total_gen = round(sum(r["latency_s"] for _, r in results), 2)
    line = f"{ts} skillguard_scan n={len(targets)} load={t_load}s gen={total_gen}s flagged={len(flagged)}"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

    if not a.quiet:
        print(f"  skill-guard[상시·shadow]: {len(targets)}개 검사, "
              f"이상 {len(flagged)}건 (load {t_load}s + gen {total_gen}s)")

    if flagged:
        names = ", ".join(os.path.basename(d) for d, _ in flagged[:5])
        msg = f"skill-guard: 활성트리 {len(flagged)}건 이상판정({names}) — 섀도, 사람검증 요구"
        print("⚠️ [skill-guard] " + msg + f"  로그: {SHADOW_LOG}", file=sys.stderr)
        os.system(f'''osascript -e 'display notification "{msg}" with title "⚠️ 하네스 스킬 보안" sound name "Basso"' 2>/dev/null''')

    return 0  # shadow: 항상 비차단


if __name__ == "__main__":
    sys.exit(main())
