#!/usr/bin/env python3
"""
Stop 훅(차단형) 후보본 — 실행 확인 게이트의 receipt 강제.
CLAUDE.md v5.6.14 GD/G12 [receipt 강제] 조항의 실 집행부.

설치 전 후보본이다. 승급 경로는 같은 디렉터리 INSTALL.md 참조.

발동 조건 = 아래 셋을 **전부** 만족할 때만 block.
  ① 이번 턴에 하네스 자산(~/.claude, ~/harness-eval)을 실제로 고쳤다
  ② 답변에 근거 수치를 동반한 검증 결과 주장이 있다 (회귀 N/N·종료코드 0·전부 통과 류)
  ③ 그 턴에 attest 통과 기록이 receipt 계측 파일에 없다

왜 셋 다 요구하나 — 선행 섀도(g12_claim_shadow.py)는 ②만, 그것도 맨 동사로 봤고
실적 36건 중 눈으로 확인한 12건이 전량 오발동이었다. 접수 응답("기록 확인됨"),
질문("무엇을 돌렸는지 알려야"), 용어 훅에 막혀 낸 정정 한 줄, 시스템 동작 설명
("다시 돌린다")이 전부 걸렸다. 한국어 동사 어미만으로는 주장·질문·설명을 못 가른다.
①이 그 셋을 전부 걸러낸다 — 접수·질문·정정은 파일을 안 고친다.

fail-open 원칙: 내부 오류·파싱 실패는 통과시킨다. 차단형 훅이 자기 버그로
세션을 막는 게 오발동보다 나쁘다.

골드셋: ~/harness-eval/hook-exempt/gold_g12r.py (hook_decide 직접 호출)
"""
import hashlib
import json
import os
import re
import sys
import time

METRICS = os.path.expanduser("~/.claude/tools/ledger/store/receipts.metrics.jsonl")
LOG = os.path.expanduser("~/harness-eval/g12-attest/blocks.jsonl")
HARNESS_DIRS = (os.path.expanduser("~/.claude"), os.path.expanduser("~/harness-eval"))
TURN_WINDOW = 1800  # attest 기록 유효 창(초) — 턴 시작 타임스탬프 미확보 시 폴백

# 근거 수치를 동반한 검증 결과 주장만. 맨 동사("돌렸다")는 일부러 뺐다 — 오발동 원인.
CLAIM = re.compile(r"""(
      회귀\s*\*{0,2}\s*\d+\s*/\s*\d+
    | \d+\s*/\s*\d+\s*(개\s*)?(전부\s*)?(통과|pass)
    | 종료\s*코드\s*\*{0,2}\s*0(?!\d)
    | exit\s*(code\s*)?[=:]?\s*0(?!\d)
    | (전부|전량|모두)\s*통과
    | (테스트|시험|린트|검사|회귀|스모크|빌드)\s*\*{0,2}\s*(는|가|도|를)?\s*\*{0,2}\s*통과
    | ATTEST_PASS
)""", re.X | re.IGNORECASE)

# 미실행·미검증 고백이 이미 있으면 게이트 충족으로 본다.
EXEMPT = re.compile(r"(미실행|미검증|스킵했|스킵함|실행 안 ?했|돌리지 않|검증 불가|"
                    r"산술 미검증|확인 못 했|재현 안 함)")

# 의문문은 주장이 아니다.
INTERROG = re.compile(r"[?？]\s*$|(냐|까|나요|습니까|는지)\s*[?？]?\s*$")

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}

# Bash 쓰기 판정 — 하네스 경로를 **대상으로** 삼는 쓰기만. 맨 `>` 는 뺐다.
# 안 그러면 `2>&1` 이 걸리고, 명령 어딘가에 .claude 가 있기만 해도 읽기 명령이
# 수정으로 잡힌다(코퍼스 실측: 발동 86건 상당수가 이 경로였다).
HP = r"(?:\.claude|harness-eval)"
BASH_WRITE_PATTERNS = [
    re.compile(r">>?\s*[^\s|;&()]*" + HP),            # 리다이렉트 대상이 하네스 경로
    re.compile(r"\btee\b[^\n]*" + HP),
    re.compile(r"\bsed\s+-i\b[^\n]*" + HP),
    re.compile(r"\b(?:cp|mv|rm|mkdir|chmod|touch|ln)\b[^\n]*" + HP),
    re.compile(r"open\([^)]*" + HP + r"[^)]*['\"]w"),  # python 쓰기 열기
]


# ── 순수 판정부 (골드셋이 직접 호출) ─────────────────────────────────────────
def hook_decide(ctx):
    """ctx = {answer:str, wrote_harness:bool, attest_ok:bool} → (block:bool, reason:str|None)"""
    answer = ctx.get("answer") or ""
    if not answer.strip():
        return False, None
    if not ctx.get("wrote_harness"):
        return False, None          # ① 하네스 미변경 → 대상 아님
    if ctx.get("attest_ok"):
        return False, None          # ③ attest 통과 있음 → 충족
    if EXEMPT.search(answer):
        return False, None          # 미실행 고백 있음 → 충족

    hits = []
    in_fence = False
    for line in answer.splitlines():
        st = line.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or st.startswith(">") or st.startswith("|"):
            continue                # 코드블록·인용·표는 주장으로 안 본다
        if INTERROG.search(st):
            continue
        m = CLAIM.search(st)
        if m:
            hits.append(m.group(0).strip())
    if not hits:
        return False, None          # ② 근거 동반 검증주장 없음

    reason = (
        "⛔ 실행 확인 게이트(CLAUDE.md v5.6.14 receipt 강제): 이번 턴에 하네스 자산을 고쳤고 "
        f"검증 결과 주장({', '.join(hits[:3])})이 있는데, receipt 대조 기록이 없다.\n"
        "⚠️ 답변 전체를 다시 내보내지 마라 — 원문은 이미 화면에 표시됐다.\n"
        "해제 경로 둘 중 하나다.\n"
        "1) 실제로 돌렸으면 receipt 경유로 재실행하고 대조해라.\n"
        "   python3 ~/.claude/tools/ledger/receipt.py run --key \"<작업>\" --artifact <산출물> -- <명령>\n"
        "   python3 ~/.claude/tools/ledger/receipt.py attest --key \"<작업>\" --require-exit 0\n"
        "   그 뒤 대조 결과 1~2줄만 추가로 내보내라.\n"
        "2) 안 돌렸거나 못 돌렸으면 그 사실을 1줄로 명시해라(미실행·미검증·스킵)."
    )
    return True, reason


# ── 트랜스크립트 파싱 (g12_claim_shadow.py 검증분 재사용) ────────────────────
ASYNC_MARK = "<task-notification>"


def read_jsonl(path):
    rows = []
    try:
        for l in open(path, encoding="utf-8"):
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


def is_async_notice(d):
    c = d.get("message", {}).get("content")
    if isinstance(c, str):
        return ASYNC_MARK in c[:200]
    if isinstance(c, list):
        return any(isinstance(b, dict) and isinstance(b.get("text"), str)
                   and ASYNC_MARK in b["text"][:200] for b in c)
    return False


def last_turn(rows):
    """턴 시작 = tool_result 아닌 사람 발화. 비동기 완료 알림은 턴을 자르지 않는다."""
    start = 0
    for i, d in enumerate(rows):
        if d.get("type") == "user":
            c = d.get("message", {}).get("content")
            is_tr = isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            if not is_tr and not is_async_notice(d):
                start = i
    return rows[start:]


def _under_harness(path):
    if not isinstance(path, str) or not path:
        return False
    ap = os.path.abspath(os.path.expanduser(path))
    return any(ap.startswith(d + os.sep) or ap == d for d in HARNESS_DIRS)


def bash_writes_harness(cmd):
    if not isinstance(cmd, str) or not cmd:
        return False
    return any(rx.search(cmd) for rx in BASH_WRITE_PATTERNS)


def scan_turn(turn):
    """(answer, wrote_harness, turn_start_ts) 추출."""
    answer, wrote, t0 = "", False, None
    for d in turn:
        if t0 is None:
            ts = d.get("timestamp")
            if isinstance(ts, str):
                try:
                    import datetime
                    t0 = datetime.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass
        if d.get("type") != "assistant":
            continue
        msg = d.get("message", {})
        for b in msg.get("content", []) or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            name, inp = b.get("name", ""), b.get("input") or {}
            if name in WRITE_TOOLS and _under_harness(inp.get("file_path")):
                wrote = True
            elif name == "Bash" and bash_writes_harness(inp.get("command")):
                wrote = True
        t = text_of(msg.get("content", []))
        if t.strip():
            answer = t
    return answer, wrote, t0


def attest_passed_since(t0):
    """턴 시작 이후 attest 통과 기록이 있나."""
    floor = t0 if t0 else (time.time() - TURN_WINDOW)
    try:
        with open(METRICS, encoding="utf-8") as fh:
            for l in fh:
                l = l.strip()
                if not l:
                    continue
                try:
                    e = json.loads(l)
                except Exception:
                    continue
                if e.get("event") == "attest_pass" and e.get("ts", 0) >= floor:
                    return True
    except FileNotFoundError:
        return False
    except Exception:
        return True   # 계측 파일을 못 읽으면 fail-open
    return False


def main():
    p = {}
    try:
        p = json.load(sys.stdin)
    except Exception:
        return
    tpath = p.get("transcript_path")
    if not tpath:
        return
    tpath = os.path.expanduser(tpath)
    if not os.path.exists(tpath):
        return
    rows = read_jsonl(tpath)
    if not rows:
        return

    answer, wrote, t0 = scan_turn(last_turn(rows))
    ctx = {"answer": answer, "wrote_harness": wrote,
           "attest_ok": attest_passed_since(t0)}
    block, reason = hook_decide(ctx)
    if not block:
        return

    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": int(time.time()),
                "session": p.get("session_id", ""),
                "sig": hashlib.sha1(answer[:400].encode()).hexdigest()[:16],
                "preview": answer[:160].replace("\n", " "),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass   # fail-open — 자기 버그로 세션 막지 않는다
