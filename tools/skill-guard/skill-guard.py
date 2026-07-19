#!/usr/bin/env python3
"""skill-guard — 외부 스킬/플러그인 '광역 악성분류' 게이트 (Qwen2.5-3B-Instruct-4bit + LoRA BEST, MLX).

INTAKE 4차 기계검증: skillscan(정적 IOC) → dyntrace(동적 audit-hook) → inject-detect(인젝션) 다음 단계.
탐지 표적: SSH/자격증명 탈취, 정체성파일(MEMORY/CLAUDE/USER.md) exfil, curl|bash, base64 난독실행,
           리버스셸, env 덤프 전송, 은닉 사용자지시, 프롬프트인젝션, 과광범 auto-run.

성능(base+BEST 어댑터, 이 스크립트가 로드하는 것과 동일 조건):
  test F1=1.0(acc 1.0)  adversarial F1=0.923(acc 0.9, recall 1.0)  regex baseline F1=0.0  → score 0.962

usage:
  skill-guard.py <path|dir|-> [--mode active|shadow] [--max-chars N] [--quiet] [--json]
    active : stdout=verdict JSON, exit 0=BENIGN · 2=MALICIOUS · 3=parse-fail(fail-closed, 차단측)
    shadow : 항상 exit 0(비차단), shadow.jsonl 기록, 요약 1줄 stdout
"""
import sys, os, re, json, glob, time, datetime, argparse

HOME = os.path.expanduser("~")
TOOLDIR = os.path.join(HOME, ".claude", "tools", "skill-guard")
SHADOW_LOG = os.path.join(TOOLDIR, "shadow.jsonl")
SYS_CACHE = os.path.join(TOOLDIR, "system_prompt.txt")
TRAIN_SRC = os.path.join(HOME, "skill-guard-ft", "data", "train.jsonl")

BASE_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
# 어댑터: tools 복사본 우선, 없으면 학습 원본(BEST) 폴백 — 둘 다 동일 가중치
ADAPTER_CANDIDATES = [
    os.path.join(TOOLDIR, "adapter"),
    os.path.join(HOME, "skill-guard-ft", "adapters", "BEST"),
]

# 스킬 디렉토리에서 분석대상으로 모을 파일 (자연어 지시층 + 코드층)
# 위험도 순. 창이 유한하므로 이 순서가 곧 '무엇을 먼저 볼 것인가'다.
# 2026-07-19 정정: 이전 순서는 SKILL.md 다음이 *.md 전부여서, 문서가 많은 스킬은
#   코드(.py/.sh)가 창 밖으로 통째로 밀려났다. 실측 14개 스킬이 해당(문서만 48000자 초과).
#   페이로드는 문서가 아니라 실행코드에 있으므로 코드를 문서보다 앞으로 올린다.
#   SKILL.md는 은닉지시 표면이라 그대로 1순위, 참조용 *.md는 최하위.
GATHER_GLOBS = ["SKILL.md",                                    # 지시층(은닉지시)
                "*.py", "*.sh", "*.js", "*.ts",                # 실행코드(페이로드)
                "*.json", "*.toml", "*.yaml", "*.yml",         # 설정(훅·자동실행)
                "*.md"]                                        # 참조문서

# 벤더링(딸려온 남의 코드) 경로 조각 — 제외가 아니라 '뒤로 미루기'용. 위 gather_content 주석 참조.
VENDOR_PARTS = ("/site-packages/", "/.venv/", "/venv/", "/node_modules/",
                "/__pycache__/", "/dist-info/", "/vendor/", "/third_party/")


def resolve_adapter():
    for p in ADAPTER_CANDIDATES:
        if os.path.isfile(os.path.join(p, "adapters.safetensors")):
            return p
    sys.exit("❌ skill-guard: 어댑터를 못 찾음 (tools/skill-guard/adapter 또는 ~/skill-guard-ft/adapters/BEST)")


def load_system_prompt():
    """전사 리스크 회피: 캐시 있으면 사용, 없으면 train.jsonl 첫 레코드 system에서 추출+캐시."""
    if os.path.isfile(SYS_CACHE):
        return open(SYS_CACHE, encoding="utf-8").read()
    if os.path.isfile(TRAIN_SRC):
        with open(TRAIN_SRC, encoding="utf-8") as f:
            rec = json.loads(f.readline())
        sysmsg = rec["messages"][0]["content"]
        try:
            os.makedirs(TOOLDIR, exist_ok=True)
            open(SYS_CACHE, "w", encoding="utf-8").write(sysmsg)
        except OSError:
            pass
        return sysmsg
    sys.exit("❌ skill-guard: system prompt 소스 없음 (system_prompt.txt / train.jsonl 둘 다 부재)")


def gather_content(target, max_chars):
    """파일=그대로, 디렉토리=지시층+코드층 파일 연결(파일명 헤더 포함, max_chars 상한)."""
    if target == "-":
        return sys.stdin.read()[:max_chars]
    if os.path.isfile(target):
        return open(target, encoding="utf-8", errors="replace").read()[:max_chars]
    if os.path.isdir(target):
        # 파일 수집 후 '스킬 자기 파일 먼저, 벤더링(venv/node_modules 등) 나중' 순으로 정렬.
        # 벤더링을 제외하지 않는 이유 — 공격자가 디렉토리를 venv/ 로 이름지어 숨기면
        # 통째 제외는 그대로 free pass가 된다. 순서만 미뤄 창을 뺏기지 않게 한다.
        # (2026-07-19 실측: prompt-compress의 6000자 창에 들어간 8개 파일 중 6개가
        #  httpx LICENSE·tqdm completion.sh·urllib3 워커js 등 라이브러리 잡동사니였다.)
        seen, cands = set(), []
        for gi, pat in enumerate(GATHER_GLOBS):
            for fp in sorted(glob.glob(os.path.join(target, "**", pat), recursive=True)):
                if fp in seen or not os.path.isfile(fp):
                    continue
                seen.add(fp)
                vendored = any(p in fp for p in VENDOR_PARTS)
                cands.append((1 if vendored else 0, gi, fp))
        cands.sort()

        parts, total = [], 0
        for _, _, fp in cands:
            try:
                body = open(fp, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            chunk = f"\n### FILE: {os.path.relpath(fp, target)}\n{body}\n"
            if total + len(chunk) > max_chars:
                parts.append(chunk[: max_chars - total])
                parts.append("\n[...truncated...]")
                break
            parts.append(chunk)
            total += len(chunk)
        return "".join(parts) if parts else "(빈 스킬 — 분석할 텍스트 없음)"
    sys.exit(f"❌ skill-guard: 대상 없음: {target}")


VERDICT_RE = re.compile(r'"verdict"\s*:\s*"(MALICIOUS|BENIGN)"')
CAT_RE = re.compile(r'"category"\s*:\s*"([^"]*)"')
CONF_RE = re.compile(r'"confidence"\s*:\s*([0-9.]+)')


def classify(target, max_chars):
    from mlx_lm import load, generate
    system = load_system_prompt()
    adapter = resolve_adapter()
    content = gather_content(target, max_chars)
    user = f"<<<SKILL>>>\n{content}\n<<<END>>>"
    model, tok = load(BASE_MODEL, adapter_path=adapter)
    prompt = tok.apply_chat_template(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        add_generation_prompt=True, tokenize=False,
    )
    t0 = time.time()
    out = generate(model, tok, prompt=prompt, max_tokens=80, verbose=False)
    dt = round(time.time() - t0, 2)
    if not isinstance(out, str):  # 일부 mlx_lm 버전은 응답객체 반환
        out = getattr(out, "text", str(out))
    mv = VERDICT_RE.search(out)
    mc = CAT_RE.search(out)
    mf = CONF_RE.search(out)
    verdict = mv.group(1) if mv else "PARSE_FAIL"
    cat = mc.group(1) if mc else ""
    conf = float(mf.group(1)) if mf else None
    return {
        "verdict": verdict, "category": cat, "confidence": conf,
        "latency_s": dt, "chars": len(content), "raw": (None if mv else out.strip()[:200]),
    }


def append_shadow(target, res):
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "target": os.path.abspath(target) if target != "-" else "-", **res}
    try:
        os.makedirs(TOOLDIR, exist_ok=True)
        with open(SHADOW_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("target", help="스킬 파일/디렉토리 경로 또는 - (stdin)")
    ap.add_argument("--mode", choices=["active", "shadow"], default="active")
    # 2026-07-19 실측으로 6000 -> 24000. 6000자 창은 앞에 무해한 글 6000자만 깔면
    # 탐지 35%->0%(악성 20샘플). 24000자면 같은 조건서 40%, 오탐은 4.3% 그대로(신규 0건).
    # 지연 2.5s -> 6.4s/건. INTAKE는 사람이 기다리는 관문이라 이 정도는 감수.
    ap.add_argument("--max-chars", type=int, default=24000)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="active에서 전체 결과 JSON 출력")
    a = ap.parse_args()

    res = classify(a.target, a.max_chars)
    v, cat, conf = res["verdict"], res["category"], res["confidence"]
    confs = f"{conf:.2f}" if conf is not None else "n/a"

    if a.mode == "shadow":
        append_shadow(a.target, res)
        if not a.quiet:
            icon = "🟥" if v == "MALICIOUS" else ("🟨" if v == "PARSE_FAIL" else "🟩")
            print(f"  skill-guard[shadow]: {icon} {v} {cat} (conf {confs}, {res['latency_s']}s) — logged, 비차단")
        sys.exit(0)

    # active
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(json.dumps({"verdict": v, "category": cat, "confidence": conf}, ensure_ascii=False))
    if v == "MALICIOUS":
        sys.exit(2)
    if v == "PARSE_FAIL":
        sys.exit(3)  # fail-closed: 판정불가=차단측
    sys.exit(0)


if __name__ == "__main__":
    main()
