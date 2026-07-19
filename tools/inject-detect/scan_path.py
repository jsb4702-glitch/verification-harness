#!/usr/bin/env python3
"""inject-detect 2계층 섀도 스캐너 — 경로(파일/디렉토리) 재귀 스캔, 로그온리·비차단.
 L1 regex(pp_detect): 구조화포맷·인코딩(중첩) 인젝션 — 고정밀(FP0), 즉시.
 L2 gemma(judge): L1 미탐 freeform persona — 의미판정, --semantic 일 때만, ollama 필요.
항상 exit 0 (섀도=차단 안 함). 발견은 shadow.log에 누적."""
import sys, os, json, pathlib, importlib.util

TOOL = pathlib.Path(__file__).resolve().parent
LOG  = TOOL / "shadow.log"
JLOG = TOOL / "shadow.jsonl"   # 구조화 병행기록(2026-07-05, 승급심사용) — 스캔 1회=1레코드
SKIP_EXT = {".png",".jpg",".jpeg",".gif",".webp",".pdf",".zip",".gz",".tar",".whl",
            ".so",".dylib",".bin",".woff",".woff2",".ttf",".ico",".mp4",".mov",".wasm"}
MAX_BYTES = 400_000
MAX_SEMANTIC = 25   # gemma 호출 상한(섀도 비용가드)

def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOL / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def text_files(target):
    p = pathlib.Path(target)
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    for f in files:
        if "/.git/" in str(f) or f.suffix.lower() in SKIP_EXT: continue
        try:
            if f.stat().st_size > MAX_BYTES: continue
            yield f, f.read_text(errors="ignore")
        except Exception: continue

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    semantic = "--semantic" in sys.argv
    D = _load("pp_detect")
    J = _load("judge_gemma") if semantic else None
    import datetime; ts = datetime.datetime.now().isoformat(timespec="seconds")
    def logline(s):
        with open(LOG, "a") as lg: lg.write(s + "\n")
    logline(f"\n# {ts}  target={target}  semantic={'on' if semantic else 'off'}")
    findings = []; l1_pass = []; sem_calls = 0
    # ── L1 regex: 전 파일, 발견 즉시 flush (L2가 죽어도 L1은 보존) ──
    for f, txt in text_files(target):
        s, h = D.scan(txt); v = D.verdict(s)
        if v.startswith("🚨") or "REVIEW" in v:
            rec = ("L1", v.split()[-1], s, str(f), list(h.keys()))
            findings.append(rec); logline(f"  [L1] {rec[1]:10} {s}  {f}  {list(h.keys())}")
        else:
            l1_pass.append((f, txt))
    # ── L2 gemma: L1 통과분만 회수 (옵션·느림·콜드스타트 가능) ──
    if J is not None:
        for f, txt in l1_pass:
            if sem_calls >= MAX_SEMANTIC: break
            sem_calls += 1
            verdict, typ, conf, bad = J.judge(txt)
            if verdict == "JAILBREAK":
                rec = ("L2", "JAILBREAK", conf, str(f), [typ])
                findings.append(rec); logline(f"  [L2] JAILBREAK  {conf}  {f}  [{typ}]")
    # 구조화 기록 — 스캔 1회=1레코드 (관측/발동 분리 계측)
    try:
        with open(JLOG, "a") as jf:
            jf.write(json.dumps({"ts": ts, "target": target, "semantic": semantic,
                                 "n_findings": len(findings),
                                 "findings": [{"layer": l, "verdict": v, "score": s,
                                               "path": p, "signals": sig}
                                              for l, v, s, p, sig in findings]},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass
    # 콘솔 요약(1줄, 비차단)
    if findings:
        n1 = sum(1 for x in findings if x[0]=="L1"); n2 = sum(1 for x in findings if x[0]=="L2")
        print(f"  ⚠️ inject-detect[섀도]: L1(regex)={n1} L2(gemma)={n2} 의심 → {LOG}")
        for layer, verd, sc, path, sig in findings[:8]:
            print(f"     [{layer}] {verd} {pathlib.Path(path).name} {sig}")
    else:
        print("  ✅ inject-detect[섀도]: 의심 인젝션 신호 없음")
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"  (inject-detect 섀도 스킵: {e})"); sys.exit(0)   # 섀도는 절대 흐름 안 깸
