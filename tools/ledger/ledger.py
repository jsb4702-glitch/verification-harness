#!/usr/bin/env python3
"""
불변원장 (Invariant Ledger) — {Claim–Evidence–Verdict} 경량 심볼테이블.
CLAUDE.md v5.6.9 G13 불변원장 스펙의 실 checker.

목적: 검증턴 주장을 ≤5종 타입으로 적재하고, 신규 주장을 dict 인덱스로
O(1) 대조해 세션 내 모순(G7 연동)을 결정론적으로 검출. PKM 아님 — 컴파일러
심볼테이블급 경량 불변. 스토어=런타임상태(gitignore 대상).

레코드: {ts, type, key, claim, value, evidence, verdict}
  type   ∈ numeric | citation | causal | decision | constraint   (정확히 5종)
  verdict∈ confirmed(🟢) | tentative(🟡) | refuted(🔴) | unverified

모순 규칙(O(1), 동일 key 대조):
  R1 verdict 충돌   : confirmed ↔ refuted            → CONTRADICTION
  R2 numeric 값괴리 : 같은 key·numeric, |Δ|/base > tol → CONTRADICTION (기본 tol=0.10, G9 경계 ±10%)
  R3 재확인        : 그 외 동일 key 재적재            → OK (verdict 승격만 기록)

사용:
  ledger.py add   --type numeric --key "M8 예압 Fmin" --claim "12.5 kN" --value 12500 --evidence "VDI2230 표" --verdict confirmed
  ledger.py check --type numeric --key "M8 예압 Fmin" --value 9000 --verdict confirmed   # → 모순 exit 3
  ledger.py stats     # loop-health: 모순율·타입분포·스킵율
  ledger.py clear     # 세션 스토어 비움

check 3단 스킵룰 (dirty-rect · 보수적 컬링 — 완전일치+confirmed만 스킵):
  SKIP   = key 일치 + 기존 confirmed + 동일성 확정
           (numeric: |Δ|/base ≤ SKIP_EQ_TOL, claim 제공 시 표기 일치도 요구=단위함정 가드
            / 그 외: claim 정규화 일치) → 재검증 스킵 가능
           ※ numeric check에 --claim 미제공 시 value만으로 판정 — 단위 상이 잔존위험, claim 병기 권장
  REF    = key 일치하나 동일성 미확정 또는 기존 tentative → 참고만·경량 재확인
  NEW    = key 미존재 → 풀검증 경로
  CONTRA = 모순(R1/R2) → exit 3 (기존 동일)
  임베딩/유사도 매칭 의도적 배제 — 유사≠동일(false-hit=날조 통로). 스킵은 정확일치만.
  check 이벤트는 metrics.jsonl에 적재 → stats가 스킵율·false-skip 의심 계측.
  환경변수 LEDGER_STORE=경로 로 스토어 오버라이드(테스트용).

주의: 선행 대시(-) 값(음수온도·음수공차)은 argparse 오인 방지 위해 `=`형 필수:
  --claim="-32~+49°C"  --value=-0.05   (공백형 --claim "-32.." 는 플래그로 오인됨)
"""
import argparse, json, os, sys, time, re

TYPES = ("numeric", "citation", "causal", "decision", "constraint")
VERDICTS = ("confirmed", "tentative", "refuted", "unverified")
STORE = os.environ.get("LEDGER_STORE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "store", "session.jsonl")
METRICS = os.path.splitext(STORE)[0] + ".metrics.jsonl"  # check 이벤트 로그(스킵율 계측)
DEFAULT_TOL = 0.10  # G9 경계 ±10%
SKIP_EQ_TOL = 1e-3  # SKIP 동일성 판정 — 모순경계(tol)와 별개로 훨씬 엄격


def _norm_key(k: str) -> str:
    """key 정규화 — 소문자·공백붕괴·구두점제거로 O(1) 대조 안정화."""
    k = k.strip().lower()
    k = re.sub(r"\s+", " ", k)
    k = re.sub(r"[^\w가-힣 .%/+-]", "", k)
    return k


def _load():
    """JSONL 로드 → 레코드 리스트 + {key: 최신레코드} 인덱스(O(1))."""
    recs, idx = [], {}
    if not os.path.exists(STORE):
        return recs, idx
    with open(STORE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            recs.append(r)
            idx[r["key"]] = r  # 최신이 이김(append-only, 뒤가 최신)
    return recs, idx


def _contradiction(prev, new_verdict, new_value, tol):
    """prev(기존 최신 레코드) vs 신규 → 모순사유 문자열 or None."""
    if prev is None:
        return None
    pv, nv = prev.get("verdict"), new_verdict
    # R1 verdict 충돌
    if {pv, nv} == {"confirmed", "refuted"}:
        return f"R1 verdict 충돌: 기존 {pv} ↔ 신규 {nv}"
    # R2 numeric 값괴리
    if prev.get("type") == "numeric" and new_value is not None and prev.get("value") is not None:
        base = abs(prev["value"])
        if base == 0:
            if abs(new_value) > 0:
                return f"R2 값괴리: 기존 0 ↔ 신규 {new_value}"
        else:
            rel = abs(new_value - prev["value"]) / base
            if rel > tol:
                return (f"R2 값괴리: 기존 {prev['value']} ↔ 신규 {new_value} "
                        f"(Δ={rel*100:.1f}% > tol {tol*100:.0f}%)")
    return None


def _metric(event, key):
    """check 이벤트 적재 — stats 스킵율/false-skip 계측용."""
    os.makedirs(os.path.dirname(METRICS), exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), "event": event, "key": key},
                           ensure_ascii=False) + "\n")


def _tier(prev, a):
    """모순 아님 전제에서 SKIP/REF 판정. 보수적: 완전일치+confirmed만 SKIP."""
    if prev.get("verdict") != "confirmed":
        return "REF", f"기존 verdict={prev.get('verdict')} (confirmed 아님)"
    if prev.get("type") == "numeric":
        if a.value is None or prev.get("value") is None:
            return "REF", "value 미제공 — 동일성 미확정"
        base = abs(prev["value"])
        rel = abs(a.value - prev["value"]) / base if base else (0.0 if a.value == 0 else 1.0)
        if rel <= SKIP_EQ_TOL:
            claim = getattr(a, "claim", None)
            if claim and prev.get("claim") and _norm_key(claim) != _norm_key(prev["claim"]):
                return "REF", "value 동일하나 claim 표기 상이(단위함정 가드) — 동일성 미확정"
            return "SKIP", f"value 동일(Δ={rel*100:.2f}%)"
        return "REF", f"tol 이내 정합이나 값 상이(Δ={rel*100:.1f}%) — 동일 주장 아님"
    claim = getattr(a, "claim", None)
    if claim:
        if _norm_key(claim) == _norm_key(prev.get("claim") or ""):
            return "SKIP", "claim 정규화 일치"
        return "REF", "동일 key·다른 claim — 동일성 미확정"
    return "REF", "claim 미제공 — 동일성 미확정"


def cmd_add(a):
    recs, idx = _load()
    prev = idx.get(_norm_key(a.key))
    key = _norm_key(a.key)
    reason = _contradiction(prev, a.verdict, a.value, a.tol)
    rec = {
        "ts": round(time.time(), 3),
        "type": a.type, "key": key, "claim": a.claim,
        "value": a.value, "evidence": a.evidence, "verdict": a.verdict,
    }
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if reason:
        print(f"⚠️ 적재됨 + 모순감지 vs 기존 [{key}]: {reason}", file=sys.stderr)
        print(f"   기존 claim: {prev.get('claim')} | 신규 claim: {a.claim}", file=sys.stderr)
        return 3
    print(f"✅ 적재: [{a.type}] {key} = {a.claim} ({a.verdict})")
    return 0


def cmd_check(a):
    """적재 없이 대조만 — 송출 전 모순 프리체크 + dirty-rect 스킵 판정."""
    _, idx = _load()
    key = _norm_key(a.key)
    prev = idx.get(key)
    if prev is None:
        _metric("new", key)
        print(f"NEW 🟢 신규 key (기존 없음): {key} → 풀검증 경로")
        return 0
    reason = _contradiction(prev, a.verdict, a.value, a.tol)
    if reason:
        _metric("contra", key)
        print(f"CONTRA 🔴 모순 vs 기존 [{key}]: {reason}", file=sys.stderr)
        print(f"   기존: {prev.get('claim')} ({prev.get('verdict')})", file=sys.stderr)
        return 3
    tier, why = _tier(prev, a)
    _metric(tier.lower(), key)
    if tier == "SKIP":
        print(f"SKIP ✅ 재검증 스킵 가능 [{key}]: {prev.get('claim')} (confirmed · {why})")
    else:
        print(f"REF ⚠️ 참고만·경량 재확인 권장 [{key}]: {prev.get('claim')} ({prev.get('verdict')}) — {why}")
    return 0


def cmd_stats(a):
    """loop-health: 모순율(회귀지표)·타입분포·check 스킵율. 메모리 개수 아님."""
    recs, idx = _load()
    if not recs and not os.path.exists(METRICS):
        print("원장 비어있음"); return 0
    tcount = {t: 0 for t in TYPES}
    contradictions = 0
    seen = {}
    for r in recs:
        tcount[r["type"]] = tcount.get(r["type"], 0) + 1
        prev = seen.get(r["key"])
        if _contradiction(prev, r.get("verdict"), r.get("value"), DEFAULT_TOL):
            contradictions += 1
        seen[r["key"]] = r
    total = len(recs)
    print(f"=== 불변원장 loop-health ===")
    if total:
        rate = contradictions / total * 100
        print(f"총 레코드: {total} | 고유 key: {len(idx)}")
        print(f"모순 적재: {contradictions} ({rate:.1f}%)  ← 낮을수록 세션 정합↑")
        print(f"타입분포: " + " ".join(f"{t}={c}" for t, c in tcount.items() if c))
    events = []
    if os.path.exists(METRICS):
        with open(METRICS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if events:
        ec = {}
        for e in events:
            ec[e["event"]] = ec.get(e["event"], 0) + 1
        n = len(events)
        print(f"check 이벤트: {n}회 | " + " ".join(f"{k}={v}" for k, v in sorted(ec.items())))
        print(f"스킵율: {ec.get('skip', 0) / n * 100:.1f}%  ← 재검증 절감분")
        # false-skip 의심: SKIP 판정 이후 같은 key에 모순 이벤트 또는 refuted 적재 발생
        skip_ts = {}
        for e in events:
            if e["event"] == "skip":
                skip_ts.setdefault(e["key"], e["ts"])
        suspects = set()
        for e in events:
            if e["event"] == "contra" and e["key"] in skip_ts and e["ts"] > skip_ts[e["key"]]:
                suspects.add(e["key"])
        for r in recs:
            if r.get("verdict") == "refuted" and r["key"] in skip_ts and r["ts"] > skip_ts[r["key"]]:
                suspects.add(r["key"])
        if suspects:
            print(f"⚠️ false-skip 의심 {len(suspects)}건: " + ", ".join(sorted(suspects)))
        else:
            print("false-skip 의심: 0건")
    return 0


def cmd_clear(a):
    for p in (STORE, METRICS):
        if os.path.exists(p):
            os.remove(p)
    print("원장 세션 스토어 비움 (+metrics)")
    return 0


def main():
    p = argparse.ArgumentParser(description="불변원장 checker (CLAUDE.md v5.6.9 G13)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, need_claim):
        sp.add_argument("--type", required=True, choices=TYPES)
        sp.add_argument("--key", required=True)
        if need_claim:
            sp.add_argument("--claim", required=True)
            sp.add_argument("--evidence", default="")
        else:
            sp.add_argument("--claim", default=None,
                            help="(선택) 비수치 SKIP 판정용 — 기존 claim과 정규화 일치 대조")
        sp.add_argument("--value", type=float, default=None, help="numeric 타입 정량값")
        sp.add_argument("--verdict", required=True, choices=VERDICTS)
        sp.add_argument("--tol", type=float, default=DEFAULT_TOL, help="numeric 허용 상대오차(기본 0.10)")

    common(sub.add_parser("add"), True)
    common(sub.add_parser("check"), False)
    sub.add_parser("stats")
    sub.add_parser("clear")

    a = p.parse_args()
    return {"add": cmd_add, "check": cmd_check, "stats": cmd_stats, "clear": cmd_clear}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
