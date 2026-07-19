#!/usr/bin/env python3
"""cite_lookup 텔레메트리 리포터 — NVD/CVE 붙인 이득 실측검증용.

cite_lookup_telemetry.jsonl 을 집계해서:
  - 타입별 빈도 (CVE가 실제로 얼마나 뜨나 = "빈도 낮음" 가설 검증)
  - 상태 분포 (confirmed/refuted/unverified — refuted가 있으면 = 날조 실제로 잡음 = 이득 실증)
  - 타입별 지연·rate-limit(403·unverified) 비율
사용: python3 cite_lookup_report.py
"""
import json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
T = os.path.join(HERE, "cite_lookup_telemetry.jsonl")


def main():
    if not os.path.exists(T):
        print("텔레메트리 없음 (아직 조회 0건):", T)
        return
    rows = []
    for line in open(T):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    if not rows:
        print("텔레메트리 비어있음")
        return

    n = len(rows)
    by_type = collections.Counter(r.get("type") for r in rows)
    by_status = collections.Counter(r.get("status") for r in rows)
    ts = [r["ts"] for r in rows if r.get("ts")]
    span_d = (max(ts) - min(ts)) / 86400 if len(ts) > 1 else 0

    print(f"# cite_lookup 텔레메트리  (총 {n}건 / 기간 {span_d:.1f}일)\n")

    print("## 타입별 빈도  ← 'CVE 빈도 낮음' 가설 검증")
    for t, c in by_type.most_common():
        print(f"  {t:8s} {c:4d}  ({c/n*100:.0f}%)")

    print("\n## 상태 분포  ← refuted>0 이면 날조 실제로 잡은 것(이득 실증)")
    for s, c in by_status.most_common():
        print(f"  {s or '?':10s} {c:4d}  ({c/n*100:.0f}%)")

    print("\n## 타입별 상세 (지연·문제율)")
    for t in by_type:
        sub = [r for r in rows if r.get("type") == t]
        lat = [r["latency_ms"] for r in sub if r.get("latency_ms") is not None]
        avg = sum(lat) / len(lat) if lat else 0
        conf = sum(1 for r in sub if r.get("status") == "confirmed")
        refu = sum(1 for r in sub if r.get("status") == "refuted")
        unv = sum(1 for r in sub if r.get("status") == "unverified")
        print(f"  [{t}] n={len(sub)}  confirmed={conf} refuted={refu} unverified={unv}"
              f"  avg={avg:.0f}ms")

    # CVE 특화 판정
    cve = [r for r in rows if r.get("type") == "CVE"]
    print("\n## NVD/CVE 이득 판정")
    if not cve:
        print("  ⚠️  아직 CVE 조회 0건 — 빈도 검증 불가(내 '빈도 낮음' 평가와 정합이면 정상)")
    else:
        refu = sum(1 for r in cve if r.get("status") == "refuted")
        rate = sum(1 for r in cve if r.get("status") == "unverified"
                   and "rate-limit" in (r.get("found", "") or ""))
        print(f"  CVE {len(cve)}건 / 전체의 {len(cve)/n*100:.0f}%")
        print(f"  날조적발(refuted): {refu}건  ← 이게 순이득의 핵심")
        print(f"  rate-limit 걸림: {rate}건  ← 무료키 필요신호")


if __name__ == "__main__":
    main()
