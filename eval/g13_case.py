#!/usr/bin/env python3
"""G13 재발방지 영구화 — 적발된 환각/결함을 골드셋 케이스로 박제.

G13 원칙: 검증경로 없는 규칙 금지. 이 스크립트가 그 검증경로를 강제한다 —
실패사례 1건 = 재현 가능한 회귀 케이스 1건. 케이스 없으면 규칙 없다.

usage:
  # (a) 판정기 케이스 (claim-level) -> ~/hermes-eval/goldset.jsonl
  #     h/c 쌍 권장: 틀린 주장(-h)과 올바른 주장(-c)을 같이 박제
  g13_case.py judge --id g9-xxx-h --category G9_arithmetic \
      --claim "..." --label hallucination --span "틀린 부분" \
      --why "정답 X, 오답 Y" --verifiable bash --source "2026-07-02 세션: ..."

  # (b) 거동 케이스 (gate-level, promptfoo) -> ~/harness-eval/tests/harness_cases.yaml
  g13_case.py gate --desc "G4 xxx — ..." --query "던질 프롬프트" \
      --rubric "PASS=..., FAIL=..." [--not-contains "금지문자열"] \
      [--js "output 판정식 → 1/0"] [--var compact_summary="압축요약 본문"] \
      --source "2026-07-02 세션: ..."
      # --var KEY=TEXT : prompts/harness.js 가 읽는 추가 vars (반복 가능).
      #   compact_summary = 압축 직후 continuation 턴 주입(2026-08-23, arXiv 2606.22528 대응)
      # --js : 결정론 트립와이어(javascript assert). rubric 채점 노이즈와 독립.

  --dry-run : 파일에 안 쓰고 결과만 출력

어느 쪽이냐 판단:
  판정기(judge) = "이 주장 자체가 틀렸다"를 잡는 케이스 (산술오류·물성왜곡·날조인용·인과비약)
  거동(gate)    = "이 입력에 게이트가 발화해야 한다"를 잡는 케이스 (날조유도·인젝션·등급누락)

추가 후 할 일 (스크립트가 리마인드 출력):
  1. feedback 메모리 파일 작성 (재발방지 규칙 + 이 케이스 id를 검증경로로 명기)
  2. 대표성 있으면 ~/hermes-eval/regress.py SMOKE 목록에 id 반영
  3. 거동 케이스면 다음 run_3way.sh / Tier-2 eval에서 자동 포함됨
"""
import argparse, json, os, sys, time

GOLD = os.path.expanduser("~/hermes-eval/goldset.jsonl")
CASES = os.path.expanduser("~/harness-eval/tests/harness_cases.yaml")
LEDGER = os.path.expanduser("~/harness-eval/g13_ledger.jsonl")

VALID_LABELS = {"hallucination", "clean"}
KNOWN_CATS = {"G4_fabrication", "G9_arithmetic", "material_property",
              "causal_logic", "context_misapply", "G11_injection"}

# 실수 3분류 (2026-07-21, 3자 합의): 반복-회수실패 / 반복-집행실패 / 신규유형.
# 근거 애매하면 unresolved — 억지 분류가 통계를 더 망친다(cdx 지적).
# 10건 누적 후 `stats`로 분포 보고 다음 처방(트리거태그/선별훅/유지) 결정.
VALID_FAILURE_CLASSES = {"recall", "enforcement", "novel", "unresolved"}


def validate_failure_class(a):
    errs = []
    if a.failure_class not in VALID_FAILURE_CLASSES:
        errs.append(f"--failure-class는 {sorted(VALID_FAILURE_CLASSES)} 중 하나")
        return errs
    if a.failure_class in ("recall", "enforcement") and not a.matched_lesson:
        errs.append(f"'{a.failure_class}'(반복 실수)는 --matched-lesson(매칭된 기존 교훈 메모리 이름) 필수")
    if a.failure_class == "novel" and a.matched_lesson:
        errs.append("'novel'인데 --matched-lesson이 있다 — 기존 교훈과 매칭되면 recall/enforcement로 분류해라")
    return errs


def existing_gold_ids():
    ids = set()
    if os.path.exists(GOLD):
        for l in open(GOLD, encoding="utf-8"):
            l = l.strip()
            if not l:
                continue
            try:
                ids.add(json.loads(l)["id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return ids


def add_judge(a):
    errs = validate_failure_class(a)
    if a.label not in VALID_LABELS:
        errs.append(f"label은 {VALID_LABELS} 중 하나")
    if a.label == "hallucination" and not a.span:
        errs.append("hallucination 케이스는 --span(틀린 부분) 필수")
    if not a.verifiable:
        errs.append("--verifiable 필수 (bash/crossref/handbook/qpl/reasoning/gen 등) — 검증경로 없는 케이스 금지(G13)")
    if a.id in existing_gold_ids():
        errs.append(f"id 중복: {a.id} (goldset.jsonl에 이미 존재)")
    if a.category not in KNOWN_CATS:
        print(f"⚠️ 신규 카테고리 '{a.category}' — regress.py SMOKE/집계엔 자동 반영 안 됨, 의도 확인")
    if errs:
        for e in errs:
            print(f"❌ {e}")
        return 2

    rec = {"id": a.id, "category": a.category, "claim": a.claim,
           "label": a.label, "span": a.span or None, "why": a.why,
           "verifiable": a.verifiable}
    line = json.dumps(rec, ensure_ascii=False)
    if a.dry_run:
        print(f"[dry-run] goldset.jsonl에 추가될 라인:\n{line}")
        print(f"[dry-run] ledger 분류: failure_class={a.failure_class} matched_lesson={a.matched_lesson}")
        return 0
    with open(GOLD, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    ledger("judge", a.id, a.source, a.verifiable, a.failure_class, a.matched_lesson)
    print(f"✅ goldset.jsonl에 박제: {a.id} ({a.category}/{a.label})")
    remind(a.label)
    return 0


def yaml_quote_block(text, indent):
    pad = " " * indent
    return "\n".join(pad + l for l in text.splitlines())


def add_gate(a):
    errs = validate_failure_class(a)
    if not a.rubric:
        errs.append("--rubric 필수 (PASS/FAIL 판정문) — 검증경로 없는 케이스 금지(G13)")
    if os.path.exists(CASES) and a.desc in open(CASES, encoding="utf-8").read():
        errs.append(f"desc 중복: '{a.desc}' 이미 harness_cases.yaml에 존재")
    if errs:
        for e in errs:
            print(f"❌ {e}")
        return 2

    extra_vars = []
    for kv in (a.var or []):
        if "=" not in kv:
            print(f"❌ --var 형식은 KEY=TEXT: {kv!r}")
            return 2
        k, v = kv.split("=", 1)
        if not k.strip() or k.strip() == "query":
            print(f"❌ --var 키 오류(빈 키 또는 query 예약어): {kv!r}")
            return 2
        extra_vars.append((k.strip(), v))

    stamp = time.strftime("%Y-%m-%d")
    block = [f"\n# --- G13 capture {stamp}: {a.source or '(source 미기재)'} ---",
             f'- description: "{a.desc}"',
             "  vars:",
             "    query: |",
             yaml_quote_block(a.query, 6)]
    for k, v in extra_vars:
        block += [f"    {k}: |", yaml_quote_block(v, 6)]
    block += ["  assert:"]
    if a.not_contains:
        block += ["    - type: not-contains",
                  f'      value: "{a.not_contains}"']
    if a.js:
        block += ["    - type: javascript",
                  "      value: |",
                  yaml_quote_block(a.js, 8)]
    block += ["    - type: llm-rubric",
              "      value: >",
              yaml_quote_block(a.rubric, 8)]
    text = "\n".join(block) + "\n"
    if a.dry_run:
        print(f"[dry-run] harness_cases.yaml에 추가될 블록:\n{text}")
        print(f"[dry-run] ledger 분류: failure_class={a.failure_class} matched_lesson={a.matched_lesson}")
        return 0
    with open(CASES, "a", encoding="utf-8") as f:
        f.write(text)
    ledger("gate", a.desc, a.source,
           "llm-rubric" + ("+not-contains" if a.not_contains else "") + ("+js" if a.js else ""),
           a.failure_class, a.matched_lesson)
    print(f"✅ harness_cases.yaml에 박제: {a.desc}")
    remind(None)
    return 0


def ledger(kind, key, source, verifiable, failure_class="unresolved", matched_lesson=None):
    rec = {"ts": time.strftime("%Y%m%d-%H%M"), "kind": kind, "key": key,
           "source": source or "", "verifiable": verifiable,
           "failure_class": failure_class, "matched_lesson": matched_lesson}
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def stats(a):
    # 분류 분포 집계 — 10건 누적이 다음 처방 판단 컷(통계 확정치 아님, 운영 임계값).
    if not os.path.exists(LEDGER):
        print("원장 없음:", LEDGER)
        return 1
    counts, lessons, legacy = {}, {}, 0
    for l in open(LEDGER, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            rec = json.loads(l)
        except json.JSONDecodeError:
            continue
        fc = rec.get("failure_class")
        if fc is None:
            legacy += 1  # 분류 필드 도입(2026-07-21) 이전 레코드
            continue
        counts[fc] = counts.get(fc, 0) + 1
        ml = rec.get("matched_lesson")
        if ml:
            lessons[ml] = lessons.get(ml, 0) + 1
    total = sum(counts.values())
    print(f"분류 레코드 {total}건 (미분류 legacy {legacy}건 제외)")
    for fc in ("recall", "enforcement", "novel", "unresolved"):
        n = counts.get(fc, 0)
        pct = f" ({n/total*100:.0f}%)" if total else ""
        print(f"  {fc:12s} {n}건{pct}")
    if lessons:
        print("반복 매칭된 교훈 (재발 핫스팟):")
        for ml, n in sorted(lessons.items(), key=lambda x: -x[1]):
            print(f"  {n}× {ml}")
    if total >= 10:
        print("\n✅ 10건 도달 — 분포 보고 다음 처방 결정 시점 (recall 우세=인덱스 트리거태그 / enforcement 우세=선별 훅 기계화 / novel 우세=현행 유지)")
    else:
        print(f"\n{10 - total}건 더 쌓이면 처방 판단 시점")
    return 0


def remind(label):
    print("\n다음 3개 잊지 마라:")
    print("  1. feedback 메모리 작성 — 규칙 + 이 케이스 id를 검증경로로 명기")
    if label == "hallucination":
        print("  2. 짝이 되는 clean 케이스(-c)도 추가 권장 (판정기 편향 방지)")
    print("  3. 대표 케이스면 ~/hermes-eval/regress.py SMOKE 목록 갱신 + baseline 재생성")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    j = sub.add_parser("judge", help="claim-level 케이스 -> hermes goldset")
    j.add_argument("--id", required=True)
    j.add_argument("--category", required=True)
    j.add_argument("--claim", required=True)
    j.add_argument("--label", required=True)
    j.add_argument("--span", default=None)
    j.add_argument("--why", required=True)
    j.add_argument("--verifiable", required=True)
    j.add_argument("--source", default=None)
    j.add_argument("--failure-class", default="unresolved",
                   help="recall(반복-회수실패)/enforcement(반복-집행실패)/novel(신규)/unresolved(애매)")
    j.add_argument("--matched-lesson", default=None,
                   help="반복 실수면 매칭된 기존 교훈 메모리 이름 (예: feedback-verify-live-not-stale-dump)")
    j.add_argument("--dry-run", action="store_true")

    g = sub.add_parser("gate", help="gate-level promptfoo 케이스 -> harness_cases.yaml")
    g.add_argument("--desc", required=True)
    g.add_argument("--query", required=True)
    g.add_argument("--rubric", required=True)
    g.add_argument("--not-contains", default=None)
    g.add_argument("--js", default=None,
                   help="javascript assert 식(결정론 트립와이어). output 변수 사용, 1=PASS 0=FAIL")
    g.add_argument("--var", action="append", default=None,
                   help="추가 vars KEY=TEXT (반복 가능). 예: compact_summary=... → 압축 continuation 턴 주입")
    g.add_argument("--source", default=None)
    g.add_argument("--failure-class", default="unresolved",
                   help="recall(반복-회수실패)/enforcement(반복-집행실패)/novel(신규)/unresolved(애매)")
    g.add_argument("--matched-lesson", default=None,
                   help="반복 실수면 매칭된 기존 교훈 메모리 이름")
    g.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("stats", help="실수 3분류 분포 집계 (10건=처방 판단 컷)")

    a = ap.parse_args()
    if a.cmd == "stats":
        return stats(a)
    return add_judge(a) if a.cmd == "judge" else add_gate(a)


if __name__ == "__main__":
    sys.exit(main())
