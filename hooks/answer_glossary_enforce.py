#!/usr/bin/env python3
"""
Stop 훅 — 답변규칙(용어 치환) 하드엔포스먼트 v2 (2026-07-19).

목적: 새 세션에서도 무조건, 직전 가시 답변에 내부 게이트 코드(G1~G13·GA~GG)나
'BLUF'가 날것으로 노출됐고 이번 턴이 하네스-메타/CNC 맥락이 아니면 → block.
용어집(~/.claude/GLOSSARY.md)의 평이한 말로 재작성 요구.

v2 변경(2026-07-19, 중복송출 사고 후):
  ① 인용 리터럴 예외 — 따옴표("…"·“…”·‘…’·「…」·『…』)나 인라인코드로 감싼
    게이트코드는 로그명·파일명 인용으로 보고 통과. (하트비트 리포트의
    "G12 완료주장" 로그명 인용을 막던 오탐 제거)
  ② 차단 메시지가 전문 재송출 대신 정정 1~2줄만 요구 — 차단돼도 원문은
    이미 사용자 화면에 렌더된 상태라 전문 재송출=중복 노출(실측).

불변:
  게이트코드/BLUF 없음 → 통과
  하네스-메타(사용자 질의가 규칙/게이트/용어집/훅 언급) → 통과
  CNC G코드 맥락(가공 G0/G1·M코드 등) → 통과   ← 기계 도메인 오탐 방지
  글로서리 교습 답변(G4→날조 차단 식 매핑·용어집/치환 논의) → 통과
  따옴표/인라인코드로 감싼 게이트코드(리터럴 인용) → 통과
  stop_hook_active → 통과(무한루프 방지)
  훅 예외 → 조용히 통과(fail-open·세션 불차단)

g9_arith_enforce.py 패턴 차용(동일 transcript 파서·block 출력형식).
"""
import sys, os, json, re


def load_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def read_jsonl(path):
    rows = []
    try:
        for l in open(path):
            l = l.strip()
            if l:
                try:
                    rows.append(json.loads(l))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") in ("text", None) and isinstance(b.get("text"), str):
                    out.append(b["text"])
                elif isinstance(b.get("content"), (str, list)):
                    out.append(text_of(b["content"]))
            elif isinstance(b, str):
                out.append(b)
    return "\n".join(out)


def last_turn(rows):
    start = 0
    for i, d in enumerate(rows):
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr:
                start = i
    return rows[start:]


# ── 검출 ─────────────────────────────────────────────────────────
# 게이트 코드 G1~G13 (G3v·G8가정 등 접미 포함). 뒤에 또 숫자 오면 제외(G1000 오탐 방지).
_GATE  = re.compile(r"\bG(?:1[0-3]|[1-9])(?![0-9])")
_GROUP = re.compile(r"\bG[A-G](?![A-Za-z0-9])")     # GA~GG
_BLUF  = re.compile(r"\bBLUF\b", re.I)

# 토큰 오염(2026-07-19 추가): 한국어 답변에 새어나온 한자·플래닝 접두어.
#   원인=토큰 생성단계 오염(答←답, course_←먼저). 의미없음·신뢰도 훼손.
#   코드블록/인라인코드는 벗겨낸 뒤 검사(파일명·변수명 오탐 방지).
_CJK      = re.compile(r"[一-鿿㐀-䶿]")   # CJK 통합한자
# 줄머리 플래닝 접두어 누출. 파일명(run_guard.py) 오탐 방지 위해 2조건으로 한정:
#   (1) 영문접두어_ 뒤에 한글이 바로 (course_먼저)  (2) 알려진 플래닝어_로 시작 (course_search)
_PLANLEAK = re.compile(
    r"(?m)^\s{0,3}(?:[a-z]{3,}_[가-힣]|(?:course|plan|step|next|first|then|note)_\S)")
_FENCE    = re.compile(r"```.*?```", re.S)
_INLINE   = re.compile(r"`[^`]*`")
# 인용 리터럴(로그명·파일명 인용) — 게이트코드 검출에서만 제외. 길이 80자 상한=
# 짝 안 맞는 따옴표가 문서 통째로 삼키는 폭주 방지. 줄바꿈 넘는 스팬 불허.
_QUOTED   = re.compile(
    r"\"[^\"\n]{1,80}\"|“[^”\n]{1,80}”|‘[^’\n]{1,80}’|「[^」\n]{1,80}」|『[^』\n]{1,80}』")

def _strip_code(txt):
    return _INLINE.sub(" ", _FENCE.sub(" ", txt))

# 사용자 질의가 하네스-메타면 코드 언급이 정당(누출 아님). 'G+숫자'도 신호.
_USER_META = re.compile(
    r"게이트|하네스|harness|용어집|glossary|답변\s*규칙|답변규칙|검증\s*로그|검증로그|"
    r"CLAUDE\.md|치환|약어|훅|hook|린터|린트|\blint|섀도|shadow|\bsettings\b|"
    r"규칙\s*업데이트|규칙\s*지켜|\bG\d")

# 답변측 예외 — 오직 '누출이 아님이 명백한' 맥락만. (검증로그/게이트 같은 '누출 어휘'는 넣지 않음)
#   1) CNC G코드/M코드   2) 글로서리 교습(G4→..., G7=..., 예전 G, 용어집/치환 논의)
_ANSWER_EXEMPT = re.compile(
    r"G-?code|지-?코드|\bCNC\b|M\s*코드|\bG0[0-9]?\b|"
    r"용어집|치환|예전\s*G|G(?:1[0-3]|[1-9])\s*[=→(]")


def gate_codes(txt):
    codes = set(_GATE.findall(txt)) | set(_GROUP.findall(txt))
    if _BLUF.search(txt):
        codes.add("BLUF")
    return sorted(codes)


def main():
    p = load_payload()
    if p.get("stop_hook_active"):            # 이미 1회 되먹임 → 무한루프 방지
        return
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)):
        return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows:
        return
    turn = last_turn(rows)

    user_txt = ""
    answer = ""
    for d in turn:
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr:
                user_txt += "\n" + text_of(c)
        elif d.get("type") == "assistant":
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip():
                answer = t
    if not answer.strip():
        return

    # ── (A) 토큰 오염 검사 — 게이트코드와 독립, 항상 우선 ──
    #   한자를 논하는 턴(사용자가 한자/토큰/오염 언급)만 예외. CNC/규격은 코드스트립으로 이미 안전.
    body = _strip_code(answer)
    cjk = _CJK.findall(body)
    leak = _PLANLEAK.findall(body)
    discussing = re.search(r"한자|漢字|토큰\s*오염|오염|접두어|course_|글자\s*깨|CJK", user_txt)
    if (cjk or leak) and not discussing:
        parts = []
        if cjk:
            parts.append("한자 [" + "".join(sorted(set(cjk)))[:12] + "]")
        if leak:
            parts.append("플래닝 접두어 [" + ", ".join(sorted(set(x.strip()[:12] for x in leak))[:3]) + "]")
        reason = (
            "⛔ 답변규칙(토큰 오염): 한국어 답변에 " + " · ".join(parts) + " 가 새어나왔다. "
            "이건 토큰 생성단계 오염(答←답, course_←먼저 류)으로 의미가 없고 신뢰도를 깎는다. "
            "⚠️원문은 이미 사용자 화면에 표시된 상태다 — 답변 전체를 다시 내보내지 말고, "
            "오염 글자→올바른 한국어 정정 줄만 내보내라(예: 「정정: 答→답」). "
            "(한자·토큰 오염 자체를 논하는 턴이면 예외 — 지금은 아니다.)")
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return

    # ── (B) 게이트 코드 누출 검사 ──
    #   코드블록·인라인코드·따옴표 인용은 리터럴(로그명·파일명)로 보고 벗겨낸 뒤 검사.
    codes = gate_codes(_QUOTED.sub(" ", body))
    if not codes:
        return                                # 위반 없음(또는 전부 리터럴 인용)
    if _USER_META.search(user_txt):
        return                                # 규칙/게이트 자체를 논하는 턴
    if _ANSWER_EXEMPT.search(answer):
        return                                # CNC G코드 / 글로서리 교습

    reason = (
        "⛔ 답변규칙(용어 치환): 가시 답변에 내부 코드 [" + ", ".join(codes) + "] 가 "
        "날것으로 노출됐다. ⚠️원문은 이미 사용자 화면에 표시된 상태다 — 답변 전체를 "
        "다시 내보내지 마라(중복 노출됨). 걸린 표현만 용어집(~/.claude/GLOSSARY.md)의 "
        "평이한 말로 바꾼 정정 1~2줄(예: 「정정: X→Y」)만 내보내라 — "
        "G1=등급 표시, G2=확인 필요, G3=검색 확인, G3v=외부 수치 검증, G4=날조 차단, "
        "G5=표현 강등, G6=교차 검증, G7=앞말 정정, G8=가정 노출, G9=계산 검증, "
        "G10=자기 비판, G11=입력 격리, G12=실행 확인, G13=재발 방지, GA~GG=그룹명(쓰지 말 것), "
        "BLUF=결론. 로그명·파일명 리터럴을 꼭 써야 하면 따옴표로 감싸라(인용 리터럴은 통과). "
        "(하네스/CNC 얘기를 실제로 하는 중이면 그 맥락 단어를 답변에 남겨라 — 예외 인정됨.)")
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
