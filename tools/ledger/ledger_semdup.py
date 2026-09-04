#!/usr/bin/env python3
"""ledger 의미중복 키 안테나 (semdup) — 그래프 수리 트랙 C (2026-07-26).

같은 실체·속성을 다른 키 표기로 적재해 O(1) 모순대조를 통째로 비켜간 쌍을
사후 검출한다. 완전일치 키 설계의 맹점(간접모순 미탐)에 대한 관측 수단.

원칙:
  - 런타임 스킵판정에는 절대 관여 안 함 — 유사매칭 스킵=날조 통로(설계 유지).
  - 보고 전용. 검출돼도 차단·수정 없음(사람게이트).
한계(정직 고지):
  - 어순 교환·부분집합·구두점/공백 변형만 잡는다.
  - 동의어·한영혼용(예압↔preload)은 못 잡는다 — 이건 의미 정규화 검토 발동 후 과제.
발동 계약:
  - 실사용 스토어 검출 ≥1건 → heartbeat 큐 'ledger-semantic-normalization-trigger'
    항목의 사람게이트 검토를 연다(방향=주장 정규화·동일키 식별, 그래프화 아님).

사용:
  ledger_semdup.py                  # 라이브 store/session.jsonl 검사
  ledger_semdup.py <store.jsonl>..  # 지정 스토어 검사
  ledger_semdup.py --selftest       # 검출기 자기시험 (회귀용, 실패=exit 2)
"""
import itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STORE = os.path.join(HERE, "store", "session.jsonl")
TREND = os.path.join(HERE, "store", "semdup.jsonl")
JACCARD_T = 0.6
# 의미 반전/한정 토큰 — 이 토큰이 차이면 정당한 구분일 확률이 높아 억제 (2차검증 반영)
NEG = frozenset("금지 제외 아님 불가 무시 미적용 해제 not no without disable disabled force strict".split())
SUBSET_MIN = 2  # 부분집합 판정 시 작은 쪽 최소 토큰 수 (1토큰 키 과잉 매칭 억제)


def norm_tokens(key):
    k = (key or "").strip().lower()
    k = re.sub(r"[^\w가-힣 .%/+-]", " ", k)
    return frozenset(t for t in k.split() if t)


def suspicious(a, b):
    """서로 다른 키 a,b가 의미상 동일 실체일 의심 → 사유 문자열 or None."""
    ta, tb = norm_tokens(a), norm_tokens(b)
    if not ta or not tb:
        return None
    if ta == tb:
        return "토큰동일(어순/구두점 변형)"
    if (ta ^ tb) & NEG:
        return None  # 차이 토큰에 반전/한정어 — 정당 구분으로 취급(억제)
    if ta <= tb or tb <= ta:
        if min(len(ta), len(tb)) >= SUBSET_MIN:
            return "부분집합(한정어 추가/누락)"
        return None
    j = len(ta & tb) / len(ta | tb)
    if j >= JACCARD_T:
        return f"고유사(Jaccard {j:.2f})"
    return None


def load_keys(paths):
    keys = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("key"):
                    keys.add(r["key"])
    return sorted(keys)


def scan(paths, quiet=False):
    keys = load_keys(paths)
    hits = []
    for a, b in itertools.combinations(keys, 2):
        why = suspicious(a, b)
        if why:
            hits.append((a, b, why))
    if not quiet:
        if hits:
            print(f"⚠️ 의미중복 의심 키쌍 {len(hits)}건 (모순대조 미도달 가능):")
            for a, b, why in hits:
                print(f"   · {a!r} ↔ {b!r} — {why}")
            print("→ 발동계약: heartbeat 큐 'ledger-semantic-normalization-trigger' 사람게이트 검토를 열 것.")
        else:
            print(f"🟢 semdup 무검출 — 키 {len(keys)}개 전수쌍 대조")
    try:
        os.makedirs(os.path.dirname(TREND), exist_ok=True)
        with open(TREND, "a", encoding="utf-8") as f:
            f.write(json.dumps({"keys": len(keys), "hits": len(hits)}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 트렌드 기록 실패는 검출 결과에 영향 없음
    return len(hits)


def selftest():
    must_flag = [
        ("예압 Fmin", "Fmin 예압"),                 # 어순 교환
        ("진동시험, 규격!", "진동시험 규격"),         # 구두점 변형
        ("M8 예압 Fmin", "예압 Fmin"),              # 부분집합(한정어 누락)
        ("축하중  (kN)", "축하중 kN"),               # 공백/괄호 변형
    ]
    must_pass = [
        ("예압 Fmin", "전단하중"),                   # 완전 상이
        ("논문A DOI", "논문B DOI"),                  # 다른 실체(1토큰 차)
        ("MIL-STD-810H 진동", "MIL-STD-810H 온도"),  # 같은 규격 다른 속성 = 정당 구분
        ("E 모듈러스", "작동온도 범위"),
        ("게이트 실행", "게이트 실행 금지"),           # 의미 반전 한정어 — 억제 필수
        ("예압", "M8 예압"),                         # 1토큰 부분집합 — 과잉 매칭 억제
    ]
    bad = []
    for a, b in must_flag:
        if not suspicious(a, b):
            bad.append(f"미탐: {a!r}↔{b!r}")
    for a, b in must_pass:
        if suspicious(a, b):
            bad.append(f"오탐: {a!r}↔{b!r}")
    if bad:
        print(f"🔴 semdup 자기시험 실패 {len(bad)}건:")
        for x in bad:
            print(f"   ❌ {x}")
        return 2
    print(f"🟢 semdup 자기시험 통과 — 필탐 {len(must_flag)}·필통과 {len(must_pass)}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    if "--selftest" in args:
        sys.exit(selftest())
    paths = args or [DEFAULT_STORE]
    n = scan(paths, quiet="--quiet" in sys.argv)
    sys.exit(0)  # 보고 전용 — 검출은 실패가 아니라 신호
