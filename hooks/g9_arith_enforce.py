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

[v2.1 — 2026-07-21] 차단 메시지만 변경(검출 로직 불변): 전문 재송출 대신
  「검증: …」/「⚠️ 산술 미검증: …」 추가 줄만 요구 — 원문은 이미 화면에 렌더된
  상태라 전문 재송출=중복 노출. answer_glossary_enforce.py v2(07-19)와 동일 정책.

[v3 — 2026-07-25 면제 조임] 실사용 3491턴 리플레이로 계측 후 반영.
  A-4 맨몸 '미검증' 면제 폐지: 무관한 문장("이 데이터는 미검증 소스임")으로 게이트
      전체가 꺼지던 경로. 이제 '산술/계산'과 붙은 형태만 면제 (실측 8턴이 이걸로 통과).
  A-3 날짜 스크럽 정밀화: 앞자리를 실제 연도(19xx·20xx)로 한정하고 구분자 일치를
      역참조로 강제. 구판은 '5000 / 25 = 200'을 날짜로 오인해 통째로 지웠다
      (자릿수에 따라 판정이 뒤집힘: 500/25 차단, 5000/25 통과).
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
#   이 파일을 import 하는 도구(test_g9_regression.py 의 단위 시험)가 출력도
#   종료코드도 없이 사라진다(실측: 무출력 exit 0 — 침묵 실패).
#   직접 실행될 때만 승격한다 — 배선은 항상 직접 실행이라 운영 경로는 그대로다.
_SYS_PY = "/usr/bin/python3"
if (__name__ == "__main__"
        and sys.executable != _SYS_PY
        and os.path.exists(_SYS_PY)
        and not os.environ.get("_G9_REEXEC")):
    try:
        os.environ["_G9_REEXEC"] = "1"
        os.execv(_SYS_PY, [_SYS_PY, "-E", "-S", os.path.abspath(__file__)] + sys.argv[1:])
    except Exception:
        pass          # 승격 실패해도 판정은 계속한다 (이 인터프리터로)
# ---------------------------------------------------------------------------

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
# [A-3] 앞자리를 19xx·20xx 로 한정 + 구분자 역참조 일치. 나눗셈 잡아먹기 차단.
_DATE   = re.compile(r"\b(?:19|20)\d{2}\s*([/.\-])\s*\d{1,2}(?:\s*\1\s*\d{1,2})?\b")
_UNITSL = re.compile(r"\d\s*/\s*(?=[A-Za-z가-힣])")                            # km/h, g²/Hz
# [D1a] 과학표기 N×10^±k — 유니코드 위첨자(⁻⁶)·캐럿(^-6)·E표기(E-6) 3형
_SCI    = re.compile(r"\d[\d.,]*\s*[×xX*]\s*10\s*"
                     r"(?:[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\^\s*[-+]?\d+|[Ee][-+]?\d+|[-+]\d+)")
# [D1b] 치수·해상도: 결과(=,≈) 미동반 ×·x 체인.
#   (?![\d.,]|\s*[=≈]) 는 숫자 완전매치 강제 — 부정 룩어헤드 단독이면 백트래킹이
#   '1.8 × 12000 = ...'의 12000을 1200으로 부분매치시켜 진짜 계산까지 스크럽(누탐)됨.
_DIM    = re.compile(r"(?<![\w.])\d[\d.,]*\s*[×xX]\s*\d[\d.,]*(?![\d.,]|\s*[=≈])")

# 산술(강신호): 곱·÷·거듭제곱·√(괄호형 포함). 나눗셈 '/'는 결과(=) 동반 시만.
# [A-4b] 마크다운 굵게 표시 스크럽 — '3. **1답변…**' · 'Method 514.**8**' 을
#   거듭제곱(**)으로 오인하던 오탐 제거. 한 줄 안의 ** 개수가 짝수(2 이상)면
#   강조 마커로 보고 걷어낸다.
#
# [2026-07-25 보정] 거듭제곱을 먼저 빼둔 뒤 개수를 센다.
#   '한 줄에 하나면 홀수라 살아남는다'는 전제가 둘 이상이면 깨진다 —
#   '2**10 = 1024 이고 3**5 = 243' 은 ** 가 짝수라 통째로 지워져 산술을 놓쳤다
#   (실측: 기준선 차단 → 합본 통과, 회귀). 숫자 사이 ** 는 강조가 될 수 없으므로
#   세기 전에 치환해 두고, 강조를 걷은 뒤 되돌린다. 걸러내려던 오탐들은
#   ** 한쪽이 숫자가 아니라 보호 대상이 아니고 그대로 제거된다.
_MDBOLD = re.compile(r"\*\*")
_POW    = re.compile(r"(?<=\d)\*\*(?=\d)")
_POW_HOLD = "\x00POW\x00"

def _strip_md_bold(txt):
    out = []
    for line in txt.split("\n"):
        held = _POW.sub(_POW_HOLD, line)
        n = len(_MDBOLD.findall(held))
        if n >= 2 and n % 2 == 0:
            held = _MDBOLD.sub("", held)
        out.append(held.replace(_POW_HOLD, "**"))
    return "\n".join(out)

# 산술(강신호): 곱·÷·거듭제곱·√(괄호형 포함).
# [A-4c] 나눗셈 '/' 는 결과 단언이 '바로 붙어' 있을 때만 산술로 본다.
#   구판 `[^\n]*=` 는 같은 줄 어디든 '='만 있으면 인정해서, '18/18 케이스 …(Δ=2.4%)'
#   '0.5/0.85 등 … 435(=4.35V)' 같은 비산술을 통째로 먹었다(실측 오탐 3건).
#   인정 형태: 「a/b = c」(뒤 단언) 또는 「x = a/b」(앞 단언).
#   앞자리 0으로 시작하는 두 자리 이상(00·01)은 코드/식별자라 제외 — 'NCB(00/01 = 미국)'.
_NUM     = r"(?!0\d)\d[\d,\.]*"
# [A-4d] √ 는 '결과 단언(= 또는 ≈)이 뒤따를 때'만 산술로 본다.
#   구판 `√\s*[\d(]` 는 기호식 `σred = √(σM²+3τM²) ≤ 0.9·Rp0.2` 까지 먹었다.
#   기호식 통과 정책은 이미 나눗셈 쪽(R08 `FA/(1-Φ)`)에 있으므로 √ 도 맞춘다.
_SQRT    = r"(?:√|\bsqrt)\s*[\d(][^\n]{0,60}?[=≈]"
# [A-4e] '앞쪽 등호'형(x = a/b)은 신호가 약해 두 조건을 더 건다:
#   ① 슬래시에 공백 없음(붙여쓴 나눗셈)  ② 피연산자 하나 이상이 소수점·자릿쉼표 보유.
#   없으면 날짜(≈6/29)·구분자(≈ 2.42 / 12㎛)가 그대로 산술로 오인된다(실측 오탐 2건).
_NUMD    = r"(?!0\d)\d[\d,]*[.,]\d[\d,\.]*"
# [A-2] 덧셈·뺄셈·백분율·한글 연산어 추가.
#   덧뺄셈은 신호가 약하다(페이지범위 12 - 18, 공차 25.0 +0.1 -0.0, 전화번호,
#   버전 v2 + v3, 온도범위 -40 ~ +71). 그래서 나눗셈과 같은 규율을 건다 —
#   '결과 단언(=·≈)이 바로 뒤따를 때'만 산술로 본다.
#   한글 연산어(나누기·곱하기)는 그 자체가 강신호라 결과 단언 없이도 인정.
#   백분율은 '증감어 + 결과 수치'가 같이 있을 때만 (단순 인용 '수율 15%' 제외).
#   피연산자 둘 다 한 자리면 자명연산(6+3=9)이라 제외 — 최소 하나는 두 자리 이상.
_NUM2      = r"(?!0\d)\d[\d,\.]*[\d.]"
_ARITH_ADD = (r"(?<![\w.])" + _NUM2 + r"\s*[+\-−–]\s*" + _NUM + r"\s*[)\]]*\s*[=≈]"
              r"|(?<![\w.])" + _NUM + r"\s*[+\-−–]\s*" + _NUM2 + r"\s*[)\]]*\s*[=≈]")
_ARITH_KO  = (r"(?<![\w.])\d[\d,\.]*[^\n]{0,8}?(?:나누기|곱하기|더하기|빼기)"
              r"[^\n]{0,8}?\d")
_ARITH_PCT = (r"(?<![\w.])\d[\d,\.]*\s*%\s*(?:씩\s*)?(?:증가|감소|상승|하락|늘|줄)"
              r"[^\n,、·|/]{0,14}?(?<![\w.])\d[\d,\.]*")
_ARITH  = re.compile(r"(?<![\w.])\d[\d,\.]*(?:\s*[*×÷]\s*|\*\*|\s*\^\s*)\d"
                     r"|" + _ARITH_ADD + r"|" + _ARITH_KO + r"|" + _ARITH_PCT +
                     r"|" + _SQRT +                                    # [D3b·A-4d]
                     r"|(?<![\w.])" + _NUM + r"\s*/\s*" + _NUM + r"\s*[)\]]*\s*[=≈]"
                     r"|[=≈]\s*" + _NUMD + r"/" + _NUM + r"(?![\d.,])"
                     r"|[=≈]\s*" + _NUM + r"/" + _NUMD + r"(?![\d.,])")
# [A-4] 맨몸 '미검증' 면제 폐지 — 반드시 '산술/계산'과 붙어 있어야 면제.
#   구판의 마지막 대안이 맨몸 `미검증` 이라 "이 데이터는 미검증 소스임" 같은
#   무관한 문장으로도 게이트 전체가 꺼졌다(실측 8턴).
_EXEMPT = re.compile(
    r"(?:산술|계산)\s*(?:결과)?\s*미검증"
    r"|⚠️\s*(?:산술|계산)"
    r"|미검증\s*(?:산술|계산)"
    r"|(?:산술|계산)\s*검증\s*(?:불가|못|안)")

def has_unverified_arith(answer):
    """v2 검출기: 면제 → 스크럽(_DATE→_UNITSL→_SCI→_DIM) → 산술스캔. True=차단대상.
    회귀테스트(test_g9_regression.py)가 import 해 직접 호출한다."""
    if _EXEMPT.search(answer): return False
    scrub = _strip_md_bold(answer)          # [A-4b] 마크다운 굵게 먼저 제거
    scrub = _DATE.sub(" ", scrub)           # [D2] 코드펜스 스트립 없이 전문 스캔
    scrub = _UNITSL.sub("0 ", scrub)
    scrub = _SCI.sub(" ", scrub)
    scrub = _DIM.sub(" ", scrub)
    return bool(_ARITH.search(scrub))
# ────────────────────────────────────────────────────────────────

BLOCK_REASON = ("⛔ G9/G12 하드체크: 답변 본문에 비자명 산술식(곱·나눗셈·거듭제곱·√)이 "
                "노출됐는데 이번 턴 Bash 실행 로그가 0건이고 '⚠️ 산술 미검증' 표식도 없다. "
                "⚠️원문은 이미 사용자 화면에 표시된 상태다 — 답변 전체를 다시 내보내지 "
                "마라(중복 노출됨). 다음 중 하나를 '추가 줄만' 내보내라: "
                "(1) Bash로 해당 계산을 역산/검증한 뒤 「검증: <식>=<값> <단위> ✅」 형식 "
                "1~3줄 (값이 원문과 다르면 「정정: X→Y」 병기), "
                "(2) 검증 불가 사유면 「⚠️ 산술 미검증: <사유 1줄>」만. "
                "(단순 인용·자명연산 오탐이면 「해당 수치는 인용값」 1줄만)")


# [A-1 가] 조회 전용 명령은 계산 근거가 못 된다 — 면제에서 뺀다.
#   구판은 tool_use 이름이 Bash 이기만 하면 명령 내용 불문 면제라, 무관한 `ls`
#   한 번으로 게이트 전체가 꺼졌다(실측: 산술 노출 151턴이 이 경로로 통과).
#   거부목록 방식 — 모르는 명령은 계산 가능으로 보고 면제 유지(보수적).
_INSPECT_ONLY = re.compile(
    r"^\s*(?:sudo\s+)?(?:ls|ll|cat|bat|cd|pwd|echo|printf|head|tail|less|more|"
    r"which|type|command|whoami|id|date|env|printenv|uname|hostname|"
    r"find|fd|grep|rg|ag|wc|file|stat|tree|du|df|ps|top|open|say|"
    r"mkdir|touch|cp|mv|ln|chmod|chown|rm|rmdir|"
    r"shasum|sha256sum|md5|md5sum|diff|cmp|"
    r"git\s+(?:status|log|diff|show|branch|remote|ls-files|ls-remote|rev-parse|config)|"
    r"brew\s+(?:list|info)|pip3?\s+(?:show|list)|npm\s+(?:ls|list)|"
    r"launchctl\s+list|crontab\s+-l|defaults\s+read|codesign|xattr|lsof)\b")


def _cmd_is_inspection_only(cmd):
    """명령 하나가 '조회 전용'인가. 파이프·연쇄가 있으면 각 조각을 모두 본다."""
    if not isinstance(cmd, str) or not cmd.strip():
        return True
    for seg in re.split(r"\|\||&&|\||;|\n", cmd):
        seg = seg.strip()
        if not seg:
            continue
        if not _INSPECT_ONLY.match(seg):
            return False          # 조회로 분류 안 되는 조각이 하나라도 있으면 계산 가능
    return True


def bash_exempts(rec):
    """Bash 면제 판정 [A-1 가]: 조회 전용 명령만 돌린 턴은 면제 안 준다."""
    cmds = rec.get("bash_cmds") or []
    if not cmds:
        return False
    return not all(_cmd_is_inspection_only(c) for c in cmds)


def hook_decide(rec):
    """순수 판정부. 반환 (block:bool, reason:str|None).
    회귀 리플레이(harness-eval/hook-exempt/replay.py)가 직접 호출하므로,
    main() 은 이 함수만 감싼다 — 검사 로직이 두 벌로 갈라지지 않게 한다."""
    answer = rec.get("answer_last", "")
    if bash_exempts(rec) or not answer.strip():
        return (False, None)
    if not has_unverified_arith(answer):
        return (False, None)
    return (True, BLOCK_REASON)


def main():
    p = load_payload()
    if p.get("stop_hook_active"):        # 이미 1회 되먹임 → 무한루프 방지
        return
    tpath = p.get("transcript_path")
    if not tpath or not os.path.exists(os.path.expanduser(tpath)): return
    rows = read_jsonl(os.path.expanduser(tpath))
    if not rows: return
    turn = last_turn(rows)

    bash_cmds = []
    answer = ""
    for d in turn:
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash":
                    cmd = (b.get("input") or {}).get("command")
                    bash_cmds.append(cmd if isinstance(cmd, str) else "")
            t = text_of(d.get("message", {}).get("content", []))
            if t.strip(): answer = t

    block, reason = hook_decide({"answer_last": answer, "bash_cmds": bash_cmds})
    if block:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))

if __name__ == "__main__":
    try: main()
    except Exception: pass
