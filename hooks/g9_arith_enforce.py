#!/usr/bin/env python3
"""
Stop 훅 — G9/G12 하드엔포스먼트 v2 (INTAKE 리빌드 2026-07-03).
이번 턴 답변 본문에 '비자명 산술식'이 노출됐는데 같은 턴 Bash tool_use 0건이고
'⚠️ 산술 미검증' 표식도 없으면 → block.

provenance: 외부 패치패키지 corecheck.zip(SPEC-G9-PATCH-v2)를 INTAKE 검증
  (skillscan HIGH=0 · 전문 정독 · 회귀 25종 실측 PASS · v1 결함 5/5 재현확인) 후
  원본 복붙이 아닌 클린 재작성으로 반영. 원판 백업: g9_arith_enforce.py.v1.bak-20260703

[v2 — 원판(v1) 대비 변경]
  D1a 과학표기 스크럽 신설: 23.6×10⁻⁶ / 23.6x10^-6 / 2.5E+8 → 곱셈 오탐 제거
  D1b 치수·해상도 스크럽 신설: 결과(=,≈) 미동반 ×·x 는 산술 아님 — 1920×1080, 100×50×20mm
      정책: ×곱셈은 결과가 단언된 경우만 산술 (기존 / 나눗셈 정책과 통일)
  D2  코드펜스 스트립 제거: ``` 안 손계산 회피 차단 (Bash 턴은 bashed 선단락으로 이미 면제)
  D3b √ 검출 확장: √( 괄호형 — σred = √(σM²+3τM²) 류

[불변 — v1 유지]
  산술식 없음 → 통과 / Bash 돌림 → 통과 / '산술 미검증' 명시 → 통과
  stop_hook_active → 통과(무한루프 방지) / 훅 예외는 조용히 통과(세션 불차단)
"""
import sys, os, json, re

def load_payload():
    try: return json.load(sys.stdin)
    except Exception: return {}

def read_jsonl(path):
    rows = []
    try:
        for l in open(path):
            l = l.strip()
            if l:
                try: rows.append(json.loads(l))
                except Exception: pass
    except Exception: pass
    return rows

def text_of(content):
    if isinstance(content, str): return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") in ("text", None) and isinstance(b.get("text"), str):
                    out.append(b["text"])
                elif isinstance(b.get("content"), (str, list)):
                    out.append(text_of(b["content"]))
            elif isinstance(b, str): out.append(b)
    return "\n".join(out)

def last_turn(rows):
    start = 0
    for i, d in enumerate(rows):
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr: start = i
    return rows[start:]

# ── 검출 정규식 (v2) ─────────────────────────────────────────────
# 스크럽(오탐 제거) — 산술 스캔 전 아래 순서로 제거. _SCI 가 _DIM 보다 먼저
# (CTE = 23.6×10⁻⁶ 의 '='는 대입이라, 과학표기 자체를 통째로 걷어내야 함).
_DATE   = re.compile(r"\b\d{4}\s*[/.\-]\s*\d{1,2}(\s*[/.\-]\s*\d{1,2})?\b")   # 날짜
_UNITSL = re.compile(r"\d\s*/\s*(?=[A-Za-z가-힣])")                            # km/h, g²/Hz
# [D1a] 과학표기 N×10^±k — 유니코드 위첨자(⁻⁶)·캐럿(^-6)·E표기(E-6) 3형
_SCI    = re.compile(r"\d[\d.,]*\s*[×xX*]\s*10\s*"
                     r"(?:[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\^\s*[-+]?\d+|[Ee][-+]?\d+|[-+]\d+)")
# [D1b] 치수·해상도: 결과(=,≈) 미동반 ×·x 체인.
#   (?![\d.,]|\s*[=≈]) 는 숫자 완전매치 강제 — 부정 룩어헤드 단독이면 백트래킹이
#   '1.8 × 12000 = ...'의 12000을 1200으로 부분매치시켜 진짜 계산까지 스크럽(누탐)됨.
_DIM    = re.compile(r"(?<![\w.])\d[\d.,]*\s*[×xX]\s*\d[\d.,]*(?![\d.,]|\s*[=≈])")

# 산술(강신호): 곱·÷·거듭제곱·√(괄호형 포함). 나눗셈 '/'는 결과(=) 동반 시만.
_ARITH  = re.compile(r"(?<![\w.])\d[\d,\.]*\s*(?:[*×÷]|\*\*|\^)\s*\d"
                     r"|√\s*[\d(]|\bsqrt\s*\("                       # [D3b]
                     r"|(?<![\w.])\d[\d,\.]*\s*/\s*\d[\d.,]*[^\n]*=")
_EXEMPT = re.compile(r"산술\s*미검증|⚠️\s*산술|미검증")

def has_unverified_arith(answer):
    """v2 검출기: 면제 → 스크럽(_DATE→_UNITSL→_SCI→_DIM) → 산술스캔. True=차단대상.
    회귀테스트(test_g9_regression.py)가 import 해 직접 호출한다."""
    if _EXEMPT.search(answer): return False
    scrub = _DATE.sub(" ", answer)          # [D2] 코드펜스 스트립 없이 전문 스캔
    scrub = _UNITSL.sub("0 ", scrub)
    scrub = _SCI.sub(" ", scrub)
    scrub = _DIM.sub(" ", scrub)
    return bool(_ARITH.search(scrub))
# ────────────────────────────────────────────────────────────────

def main():
    p = load_payload()
    if p.get("stop_hook_active"):        # 이미 1회 되먹임 → 무한루프 방지
        return
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)): return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows: return
    turn = last_turn(rows)

    bashed = False
    answer = ""
    for d in turn:
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                    bashed = True
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip(): answer = t
    if bashed or not answer.strip(): return

    if not has_unverified_arith(answer): return

    reason = ("⛔ G9/G12 하드체크: 답변 본문에 비자명 산술식(곱·나눗셈·거듭제곱·√)이 "
              "노출됐는데 이번 턴 Bash 실행 로그가 0건이고 '⚠️ 산술 미검증' 표식도 없다. "
              "자기보고 '검증 통과'는 신뢰 불가 — 다음 중 하나로 재송출하라: "
              "(1) Bash로 해당 계산을 역산/검증하고 중간값·단위 노출, "
              "(2) 검증 불가 사유면 본문에 '⚠️ 산술 미검증' 명시. "
              "(단순 인용·자명연산이면 식 표기를 정리)")
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))

if __name__ == "__main__":
    try: main()
    except Exception: pass
