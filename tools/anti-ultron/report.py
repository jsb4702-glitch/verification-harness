#!/usr/bin/env python3
"""report — metrics.jsonl 집계해 anti-ultron 실효율 리포트.
사용: python3 report.py [metrics.jsonl경로]
"""
from __future__ import annotations
import json, sys, statistics, datetime
from collections import Counter
from pathlib import Path

PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("metrics.jsonl")


def load(p: Path):
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows


def pct(n, d): return f"{100*n/d:.0f}%" if d else "—"
def ms_stats(xs):
    if not xs: return "—"
    xs = sorted(xs)
    p95 = xs[min(len(xs)-1, int(len(xs)*0.95))]
    return f"mean {statistics.mean(xs):.0f} / med {statistics.median(xs):.0f} / p95 {p95:.0f} ms"


def main():
    rows = load(PATH)
    if not rows:
        print(f"(기록 없음: {PATH})"); return
    ts = [r["ts"] for r in rows if "ts" in r]
    span = ""
    if ts:
        a = datetime.datetime.fromtimestamp(min(ts)).strftime("%Y-%m-%d %H:%M")
        b = datetime.datetime.fromtimestamp(max(ts)).strftime("%Y-%m-%d %H:%M")
        span = f"{a} → {b}"
    g = [r for r in rows if r.get("module") == "guard"]
    tj = [r for r in rows if r.get("module") == "trajectory"]
    rd = [r for r in rows if r.get("module") == "redact"]

    print("═══════════ anti-ultron 실효율 리포트 ═══════════")
    print(f"기간: {span}   총이벤트: {len(rows)}")

    if g:
        blocks = sum(r.get("classification") == "block" for r in g)
        l1 = sum(r.get("layer") in ("L1", "L1-fallback") for r in g)
        l2 = sum(r.get("layer") == "L2" for r in g)
        l2ms = [r["ms"] for r in g if r.get("layer") == "L2" and "ms" in r]
        viol = Counter(v for r in g for v in r.get("violations", []))
        print(f"\n■ GUARD  호출 {len(g)}")
        print(f"   차단율      : {blocks}/{len(g)} ({pct(blocks,len(g))})")
        print(f"   L1 무료처리 : {l1}/{len(g)} ({pct(l1,len(g))})  ← 모델 안 띄우고 즉시 (비용 0)")
        print(f"   L2 모델판정 : {l2}/{len(g)} ({pct(l2,len(g))})  {ms_stats(l2ms)}")
        print(f"   L2 누적비용 : {sum(l2ms)/1000:.1f} model-sec")
        if viol: print(f"   상위 위반   : " + ", ".join(f"{k}×{n}" for k, n in viol.most_common(5)))

    if tj:
        sd = Counter(r.get("safety") for r in tj)
        esc = sum("gemma4" in str(r.get("model", "")) for r in tj)
        tms = [r["ms"] for r in tj if "ms" in r]
        rs = Counter(r.get("risk_source") for r in tj if r.get("safety") == "unsafe")
        print(f"\n■ TRAJECTORY  호출 {len(tj)}")
        print(f"   판정분포    : " + ", ".join(f"{k}={v}" for k, v in sd.items()))
        print(f"   unsafe율    : {pct(sd.get('unsafe',0), len(tj))}   gemma4 에스컬: {esc}")
        print(f"   레이턴시    : {ms_stats(tms)}")
        if rs: print(f"   위험원 top  : " + ", ".join(f"RS{k}×{n}" for k, n in rs.most_common(3)))

    if rd:
        tot = sum(r.get("n_secrets", 0) for r in rd)
        bt = Counter()
        for r in rd:
            for k, n in (r.get("by_type") or {}).items(): bt[k] += n
        withsec = sum(r.get("n_secrets", 0) > 0 for r in rd)
        print(f"\n■ REDACT  호출 {len(rd)}")
        print(f"   시크릿 마스킹 총 {tot}건  (시크릿 포함 입력 {withsec}/{len(rd)}, {pct(withsec,len(rd))})")
        if bt: print(f"   타입별      : " + ", ".join(f"{k}×{n}" for k, n in bt.most_common(8)))

    # 한줄 실익 요약
    saved = sum(r.get("layer") in ("L1", "L1-fallback") for r in g)
    print(f"\n▶ 요약: 차단 {sum(r.get('classification')=='block' for r in g)}건 · "
          f"시크릿 {sum(r.get('n_secrets',0) for r in rd)}건 마스킹 · "
          f"위험궤적 {sum(r.get('safety')=='unsafe' for r in tj)}건 적발 / "
          f"L1이 {saved}건을 무료·즉시 처리(모델호출 절약)")


if __name__ == "__main__":
    main()
