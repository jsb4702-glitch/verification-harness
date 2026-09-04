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

v3 변경(2026-07-25, 면제조임 감사):
  B-1 답변측 '전체 면제 스위치'(_ANSWER_EXEMPT) 폐지 → 국소 면제(scrub_excused)로 대체.
      '용어집'·'치환'·'CNC' 한 낱말로 답변 전체 검사가 꺼지던 자기면제 경로 제거.
      실측 48턴 중 표본 14건 라벨링: '치환' 트리거 5건 중 4건이 무관 오작동
      (관절치환·경로치환·placeholder 치환).
  B-3 하이픈·공백 변형(G-9 · G 9) 검출 추가. 다른 변형은 오탐 실측으로 기각(아래 주석).
  검사부를 hook_decide(rec) 순수함수로 분리 — 회귀 리플레이가 같은 코드를 탄다.

계측(실사용 3491턴 리플레이, harness-eval/hook-exempt/):
  차단해제 0건(약화 없음) · 신규차단 37건(전부 훅 설치 이전 이력)
  최근 구간(2026-07-20~, 580턴) 기준선과 완전 동일 — 신규 0·해제 0
  골드셋 22/22 (기존 14 + B-1 우회 재현 8). 기준선은 17/22.

g9_arith_enforce.py 패턴 차용(동일 transcript 파서·block 출력형식).
"""
import sys, os, json, re

# --- 인터프리터 승격 (배선 독립, 2026-07-25) --------------------------------
# 이 파일을 root 555 로 잠가도, 배선이 부르는 파이썬이 사용자 쓰기 가능하면
# 표준 라이브러리나 usercustomize.py 로 판정을 바꿀 수 있다. 파일 해시·소유자·권한은
# 그대로라 무결성 검사도 통과한다 — 잠금이 지키는 것은 내용이지 실행 환경이 아니다.
# 그래서 판정은 SIP 보호를 받는 시스템 파이썬에서 돈다(egress_guard 와 같은 방식).
#   -S : site 를 끊어 usercustomize 자동 import 를 막는다
#   -E : PYTHON* 환경변수를 무시한다
# 승격 실패는 조용히 넘긴다 — 이 훅은 fail-open 이 설계다(세션을 잠그지 않는다).
#
# [2026-07-25 가드 추가] __name__ 조건이 앞에 온다.
#   os.execv 는 프로세스 이미지를 통째로 교체한다. 모듈 최상위에서 무조건 돌면
#   이 파일을 import 하는 검증 도구가 출력도 종료코드도 없이 사라진다
#   (실측: 무출력 exit 0 — 침묵 실패).
#   직접 실행될 때만 승격한다 — 배선은 항상 직접 실행이라 운영 경로는 그대로다.
_SYS_PY = "/usr/bin/python3"
if (__name__ == "__main__"
        and sys.executable != _SYS_PY
        and os.path.exists(_SYS_PY)
        and not os.environ.get("_GLOSSARY_REEXEC")):
    try:
        os.environ["_GLOSSARY_REEXEC"] = "1"
        os.execv(_SYS_PY, [_SYS_PY, "-E", "-S", os.path.abspath(__file__)] + sys.argv[1:])
    except Exception:
        pass          # 승격 실패해도 판정은 계속한다 (이 인터프리터로)
# ---------------------------------------------------------------------------

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
# [B-3 2026-07-25] 하이픈·공백 낀 변형(G-9 · G 9)까지 검출.
#   실사용 3491턴 실측: 두 변형의 추가 차단 0턴 = 오탐 없이 구멍만 닫는다.
#   기각한 변형(측정 근거):
#     소문자 g9  → 4턴 전부 오탐(g12-shadow 파일명·g13 골드셋·URL 조각 #g9)
#     GATE9      → 1턴 오탐(FT 체인 도식 노드명)
#     게이트4     → 47턴 전부 오탐("회귀 게이트 10/10"·"절대게이트 3대"). 계수어를
#                  빼도 30턴 남아 한국어에선 성립 불가.
#     지9(음차)   → 76턴 전부 오탐("자유엣지 1"·"나머지 4개"). 사용 불가.
_GATE  = re.compile(r"\bG[\s-]?(?:1[0-3]|[1-9])(?![0-9])")
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

# [B-1 수정 2026-07-25] 답변측 '전체 면제 스위치' 폐지.
#   구 구조: 답변 어딘가에 '용어집'·'치환'·'CNC' 한 마디만 있으면 답변 전체 검사가 꺼졌다.
#     → 모델이 자기 게이트를 스스로 끌 수 있는 경로(실측 48턴 중 표본 14건 라벨링:
#       '치환' 트리거 5건 중 4건이 관절치환/경로치환/placeholder치환 등 무관 오작동).
#   새 구조: 면제는 '그 자리'에서만 성립한다 — 아래 두 스크럽으로 해당 출현만 지우고,
#     남은 맨몸 코드는 그대로 검출한다. 전체 스위치는 없다.
#
# (a) 인라인 뜻풀이: G4(날조 차단) · G9=산술 검증 · G7 → 앞말 정정 · 「… (예전 G4)」
#     답변규칙 L5 "부득이하면 그 자리에 한 줄 뜻"이 허용하는 형태.
#     ⚠ 콜론(G4: …)은 뺀다 — 실측상 그 형태 48회 중 대부분이 검증로그 나열이라
#       (「G4: CWE …」·「G11: 외부 깃허브…」) 인정하면 검증로그 누출이 통째로 뚫린다.
_GLOSSED = re.compile(
    r"\bG(?:1[0-3]|[1-9])(?![0-9])\s*[=→]\s*\S|"
    r"\bG(?:1[0-3]|[1-9])(?![0-9])\s*\([^)\n]{1,40}\)|"
    r"예전\s*G(?:1[0-3]|[1-9])(?![0-9])")
# (b) CNC 기계가공 맥락: 가공 어휘가 있는 '그 줄'에서만 G숫자를 면제한다.
#     맨몸 'CNC' 한 단어로 답변 전체를 끄던 경로를 없앤다.
_MACHINING = re.compile(
    r"G-?code|지-?코드|가공|밀링|선반|공작기계|머시닝|툴패스|스핀들|"
    r"이송속도|절삭|NC\s*프로그램|M\s*코드")
_GNUM = re.compile(r"\bG\d{1,3}\b")
# (c) 'G0x'는 게이트 번호(G1~G13)와 표기가 겹치지 않는 순수 CNC 표기 — 맥락 무관 유지.
_GCODE_ZERO = re.compile(r"\bG0[0-9]?\b")


def scrub_excused(txt):
    """'그 자리에서 정당한' 게이트코드 출현만 지운다. 전체 면제 스위치는 없다."""
    txt = _GLOSSED.sub(" ", txt)
    txt = _GCODE_ZERO.sub(" ", txt)
    out = []
    for line in txt.split("\n"):
        if _MACHINING.search(line):
            line = _GNUM.sub(" ", line)       # 가공 맥락 줄에서만 국소 면제
        out.append(line)
    return "\n".join(out)


def gate_codes(txt):
    codes = set(_GATE.findall(txt)) | set(_GROUP.findall(txt))
    if _BLUF.search(txt):
        codes.add("BLUF")
    return sorted(codes)


def hook_decide(rec):
    """순수 판정부. 반환 (block:bool, reason:str|None).
    회귀 리플레이(harness-eval/hook-exempt/replay.py)가 직접 호출하므로,
    main() 은 이 함수만 감싼다 — 검사 로직이 두 벌로 갈라지지 않게 한다."""
    answer = rec.get("answer_last", "")
    user_txt = rec.get("user_txt", "")
    if not answer.strip():
        return (False, None)

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
        return (True, reason)

    # ── (B) 게이트 코드 누출 검사 ──
    #   코드블록·인라인코드·따옴표 인용은 리터럴(로그명·파일명)로 보고 벗겨낸다.
    #   [B-1] 이어서 '그 자리에서 정당한' 출현(인라인 뜻풀이·CNC 국소)만 추가로 지운다.
    #        답변 전체를 끄는 스위치는 없앴다.
    codes = gate_codes(scrub_excused(_QUOTED.sub(" ", body)))
    if not codes:
        return (False, None)                  # 위반 없음(또는 전부 리터럴/국소면제)
    if _USER_META.search(user_txt):
        return (False, None)                  # 규칙/게이트 자체를 논하는 턴

    reason = (
        "⛔ 답변규칙(용어 치환): 가시 답변에 내부 코드 [" + ", ".join(codes) + "] 가 "
        "날것으로 노출됐다. ⚠️원문은 이미 사용자 화면에 표시된 상태다 — 답변 전체를 "
        "다시 내보내지 마라(중복 노출됨). 걸린 표현만 용어집(~/.claude/GLOSSARY.md)의 "
        "평이한 말로 바꾼 정정 1~2줄(예: 「정정: X→Y」)만 내보내라 — "
        "G1=등급 표시, G2=확인 필요, G3=검색 확인, G3v=외부 수치 검증, G4=날조 차단, "
        "G5=표현 강등, G6=교차 검증, G7=앞말 정정, G8=가정 노출, G9=계산 검증, "
        "G10=자기 비판, G11=입력 격리, G12=실행 확인, G13=재발 방지, GA~GG=그룹명(쓰지 말 것), "
        "BLUF=결론. 로그명·파일명 리터럴을 꼭 써야 하면 따옴표로 감싸라(인용 리터럴은 통과). "
        "굳이 코드를 써야 하면 그 자리에 뜻을 달아라 — 「G9(계산 검증)」처럼 붙은 건 통과한다. "
        "(CNC 가공 G코드는 가공 맥락 단어가 같은 줄에 있으면 통과.)")
    return (True, reason)


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

    block, reason = hook_decide({"user_txt": user_txt, "answer_last": answer})
    if block:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
