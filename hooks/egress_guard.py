#!/usr/bin/env python3
"""
PreToolUse 차단훅 — egress-guard v10 (2026-09-03) — v9 + URL 경로 세그먼트 해시 오탐 제외.

v10: 콘텐츠 해시가 경로 세그먼트로 박힌 CDN URL(www-cdn.anthropic.com/<sha1>/x.pdf 류)을
범용 16진 규칙(32자 이상)이 시크릿 리터럴로 오인해 WebFetch·curl 을 D1 로 막았다
(2026-09-02 research-scout 실측, 시스템카드 PDF 2건). 화이트리스트(도메인)를 넓히지 않고
"URL 경로부(호스트 뒤 첫 / 부터 ?·# 앞까지) 안에서 세그먼트 전체를 이루는 다이제스트 길이
(32·40·64) 16진"만 범용 16진 규칙에서 제외한다. 쿼리스트링·프래그먼트·헤더·환경변수
대입·세그먼트 일부(key-<hex>)·다이제스트가 아닌 길이는 그대로 D1. 다른 시크릿 규칙
(AWS·GitHub·JWT·Bearer·token= …)은 손대지 않는다.
남는 구멍: 다이제스트 길이의 맨 16진 토큰을 경로 세그먼트 통째로 실어 보내는 반출.
회귀: a0/parity_check.py V10_CASES(오탐 1·진양성 1) + a0/egress_pathhash_probe.py(10건).

v9: 격주감사 A1이 3회 연속 지적한 정지경로를 닫는다 — 감시 주기잡 unload 계열과
LaunchAgents plist 바꿔치기, 무결성 감시(integrity-guard)·상태점검(heartbeat) 파괴.
전부 "쓰기 대상" 원칙(v8) 유지: 읽기·실행·load 는 통과, ask 등급(세션 안 잠금).

v1 대비 변경 두 가지. 정책(D1/A1/A2)과 판정 결과는 v1과 동일하게 유지한다.

  1) 의존성 제거 — 판정에 필요한 시크릿 규칙을 이 파일 안에 인라인했다.
     v1은 ~/.claude/tools/anti-ultron/redact.py 를 import 했고, 그 모듈은 일반
     작업 경로에 있어 훅 본체를 한 글자도 안 바꾸고 규칙만 비우면 판정이
     통째로 무력화됐다(A0-1 실측 S6). 이제 이 파일 하나 + 표준 라이브러리만으로
     판정이 닫힌다. 계측 로깅은 여전히 외부 모듈을 쓰지만 best-effort이며
     실패해도 판정에 영향을 주지 않는다.

  2) fail-closed — 판정 불가 시 자동 통과를 금지하고 사람에게 넘긴다(ask).
     v1은 예외·입력파손·import실패에서 전부 exit 0(=통과)이었다(실측 S2·S3·S4).
     deny가 아니라 ask인 이유: 훅 결함이 세션 전체를 잠그면 우회 습관이 생기고,
     그게 더 큰 구멍이 된다. 자동 통과만 막고 판단은 사람이 한다.

  못 막는 것: 훅 파일 자체가 삭제·교체되거나 프로세스가 강제 종료되면 이 파일
  안의 어떤 코드도 실행되지 않는다. 그 계층은 배선 무결성 감시(A0-2)의 몫이다.
"""
import sys


def _fail_closed(reason):
    """판정 불가 시 자동 통과를 막는다. import 단계에서도 쓸 수 있어야 하므로
    표준 라이브러리에 의존하지 않고 문자열을 직접 만든다."""
    sys.stdout.write(
        '{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
        '"permissionDecision":"ask","permissionDecisionReason":"' + reason + '"}}')
    sys.exit(0)


try:
    import json
    import os
    import re
except Exception:
    _fail_closed("egress-guard: 판정에 필요한 모듈을 불러오지 못했다 — 자동 통과를 막고 사람 확인으로 넘긴다.")

# --- 인터프리터 승격 (배선 독립) -------------------------------------------
# 배선이 어떤 파이썬을 가리키든, 판정은 SIP 보호를 받는 시스템 파이썬에서 돈다.
# 사용자 PATH의 파이썬은 admin 그룹 쓰기가 열려 있어 표준 라이브러리까지 수정 가능하다
# (2026-07-25 실측: 54개 파일). 배선 파일은 앱이 자기 상태로 덮어쓰므로 거기에
# 인터프리터 지정을 걸어둘 수 없다 — 그래서 훅 스스로 승격한다.
_SYS_PY = "/usr/bin/python3"
if sys.executable != _SYS_PY and os.path.exists(_SYS_PY) and not os.environ.get("_EGRESS_REEXEC"):
    try:
        os.environ["_EGRESS_REEXEC"] = "1"
        os.execv(_SYS_PY, [_SYS_PY, "-E", "-S", os.path.abspath(__file__)] + sys.argv[1:])
    except Exception:
        pass          # 승격 실패해도 판정은 계속한다 (이 인터프리터로)
# ---------------------------------------------------------------------------

# --- 판정 규칙 (인라인 — 외부 모듈 의존 없음) ---------------------------------
# 시크릿 "리터럴" 탐지용. v1이 쓰던 redact._RULES 중 자격증명 계열만 가져왔다.
# 이메일·카드번호 같은 PII 규칙은 egress 판정 대상이 아니라서 뺐다(v1 동작과 동일:
# v1도 $VAR 참조는 제외했고, PII 매치는 실질적으로 D1을 유발하지 않았다).
_SECRET_RULES = [
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bxox[abpcr]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.DOTALL),
    re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE),
    re.compile(r"\beyJ[0-9A-Za-z._\-]+\b"),
    re.compile(
        r"\b(pass(?:word)?|secret|token|apikey|api_key|"
        r"(?:refresh|access|id|oauth)_?token|session(?:_?id)?|sid)"
        r"\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[0-9A-Fa-f]{32,}\b"),
]

# --- v10: URL 경로 세그먼트 해시 오탐 제외 ------------------------------------
# 범용 16진 규칙(위 목록 마지막 항목)만 대상. 다른 규칙은 이 예외를 타지 않는다.
# 경로부 = 호스트 뒤 첫 "/" 부터 "?"/"#" 앞까지. 쿼리·프래그먼트는 경로가 아니다.
_HEX_RULE = _SECRET_RULES[-1]
_URL_SPAN = re.compile(r"https?://[^\s'\"<>]+", re.I)
_DIGEST_LENS = (32, 40, 64)      # md5 · sha1 · sha256 — 콘텐츠 해시로 통용되는 길이만


def _url_path_spans(surface: str):
    """표면 안 각 URL 의 경로부 (시작, 끝) 구간. 시작 위치의 글자는 항상 "/" 다."""
    spans = []
    for m in _URL_SPAN.finditer(surface):
        url = m.group(0)
        p = url.find("/", url.find("://") + 3)
        if p < 0:
            continue
        end = len(url)
        for stop in "?#":
            i = url.find(stop, p)
            if i >= 0:
                end = min(end, i)
        spans.append((m.start() + p, m.start() + end))
    return spans


def _is_path_segment_hash(m, surface: str, path_spans) -> bool:
    """16진 매치가 URL 경로부 안에서 세그먼트 전체(/<hex>/ · /<hex>.ext · /<hex>$)를
    이루는 다이제스트 길이인가. 하나라도 어긋나면 시크릿 판정으로 되돌린다."""
    s, e = m.span()
    if (e - s) not in _DIGEST_LENS:
        return False
    for ps, pe in path_spans:
        if ps < s and e <= pe and surface[s - 1] == "/" \
                and (e == pe or surface[e] in "/."):
            return True
    return False
# ---------------------------------------------------------------------------

_URL = re.compile(r"https?://([^/\s:'\"]+)(?::(\d+))?", re.I)
_NETVERB = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|rsync|ftp|telnet)\b", re.I)
_PRIVATE = re.compile(r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.0\.0\.0)")
_LOCAL = re.compile(r"^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?)$", re.I)

# --- v4: 셸 변형 우회 대응 ---------------------------------------------------
# v3까지는 시크릿 '리터럴'만 봤다. 그런데 셸은 실행 직전에 문자열을 바꾼다 —
# 파일에서 읽고, 변수로 담고, 인코딩을 풀어서 조립한다. 그러면 리터럴이 안 보인다.
# 2026-07-25 실측에서 11종 중 7종이 이 방식으로 통과했다.
#
# 리터럴 대신 '자격증명이 있는 자리'와 '숨기는 동작'을 본다. 셸 연산자 자체를
# 의심하지는 않는다 — 명령치환·파이프는 일상적으로 쓰는 것이라 그걸 막으면
# 확인 프롬프트가 남발되고, 그 습관이 정작 위험한 순간을 무디게 만든다.

# 자격증명이 사는 자리. 경로 형태로만 매칭해 일반 단어와 섞이지 않게 한다.
_SECRET_PATH = re.compile(
    r"(?:^|[\s'\"=@:])~?[\w./\-]*"
    r"(?:\.ssh/|\.aws/credentials|\.gnupg/|\.netrc|"
    r"id_rsa|id_ed25519|id_ecdsa|"
    r"secrets?\.(?:env|json|ya?ml|txt)|"
    r"credentials?\.(?:json|ya?ml|ini)|"
    r"\.(?:pem|p12|pfx|jks|keystore))\b",
    re.I)

# 목적지나 페이로드를 실행 시점에만 드러내는 동작.
_OBFUSCATE = re.compile(r"\b(?:base64\s+(?:-d|--decode)|xxd\s+-r|openssl\s+enc\s+-d)\b", re.I)

# URL 형태가 아닌 맨 IP (ssh·scp·ping 등에서 쓰인다).
_BARE_IP = re.compile(r"(?:^|[\s'\"@:=])(\d{1,3}(?:\.\d{1,3}){3})\b")

FAIL_CLOSED_REASON = (
    "egress-guard: 판정을 끝내지 못했다(훅 내부 오류 또는 입력 파손). "
    "자동 통과를 막고 사람 확인으로 넘긴다 — 명령에 자격증명이나 외부 전송이 "
    "섞여 있지 않은지 직접 보고 결정해라."
)


def _emit(decision: str, reason: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    sys.exit(0)



# --- 앵커 경로 사전 차단 -----------------------------------------------------
# 배선(settings.json)이 지워지면 그 즉시 훅이 안 돈다(실측: 세션 중 변경이 즉시 반영).
# 주기 검사는 사후 탐지라 그 사이가 비고, 상주 감시자를 두면 그 감시자도 앵커가 된다.
# 그래서 지워지기 전에 막는다 — 통제 자신을 고치는 명령은 사람에게 물어본다.
#
# 읽기는 막지 않는다. 해시 확인·비교·백업 같은 정상 작업이 대부분이고,
# 그걸 막으면 확인 프롬프트가 남발되어 결국 무시하게 된다.
# [v8 · 2026-07-26] 판정 기준을 "쓰기 대상이 앵커인가" 로 바꿨다.
#   v7 은 '쓰기 동사가 있고 어딘가 앵커 경로가 있으면' 잡았다. 그건 소스와 대상을 구분하지
#   못한다. 앵커에서 읽어 다른 데 쓰는 정상 작업이 계속 막혔다 — 2026-07-25 앵커 작업 중
#   백업·드라이런 준비가 네 번 걸렸고, 그때마다 확인 프롬프트를 넘겼다. 그 피로가 쌓이면
#   가드는 있어도 없는 것과 같아진다.
#   동시에 재현율도 낮았다(실측 9/16). 대상 기준으로 바꾸니 16/16 · 오탐 0/20 이 됐다.
#   측정 코퍼스는 실사용 명령 로그(PERMISSION_LOG)에서 뽑았다.
#
#   경로도 둘 넓혔다 — v7 은 `settings\.json` 리터럴이라 settings.local.json 을 통째로
#   놓쳤고(그 파일 한 줄로 훅 전체를 끌 수 있다), 관리자 설정 디렉토리도 없었다.
#
#   남은 한계(v7 과 동일, 정규식으로는 못 막음): 경로가 실행 시점에 조립되는 형태 —
#   `P=~/.claude/settings.json; echo x > $P` / `cd ~/.claude && echo x > settings.json`.
#   변수 추적을 시도했으나(v9) 우회 1건을 잡는 대신 오탐 1건이 늘어 순이득 0이라 기각했다.
#   이 층은 무결성 검사(해시 대조)가 사후에 잡는다. 근본 해결은 셸 토큰 파싱이다.
_HOME_RE = r"(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s'\"]+)"
_ANCHOR_BODY = (
    # [v9] integrity-guard(해시 감시)·heartbeat(상태점검 등재부) 추가 — baseline.json 삭제나
    # config.json 에서 감시잡을 빼는 게 감시 무력화 1순위 경로인데 v8 은 안 봤다.
    r"\.claude/(?:settings(?:\.local)?\.json|hooks/"
    r"|tools/(?:anchor-watch|ledger|integrity-guard|heartbeat)/)"
    r"|/Library/AnchorTCB"
    r"|/Library/Application Support/ClaudeCode"
    # [v9] plist 바꿔치기 = 제일 쉬운 감시 우회로(ig.py 주석과 동일 판단). 쓰기만 잡는다.
    r"|Library/LaunchAgents"
)
_ANCHOR_PATH = re.compile(rf"(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})", re.I)

# 경로 앞에 낄 수 있는 잡음: 따옴표·클로버(>|)·공백
_LEAD = r"[\s'\"|]*"

# ① 리다이렉트 대상이 앵커 (>, >>, 1>, >| 모두)
_REDIR_TO_ANCHOR = re.compile(
    rf"(?:^|[\s;&|)])\d?>>?{_LEAD}(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})", re.I)
# ② cp/mv/install/ln 의 마지막 인자가 앵커 — 소스로 쓰인 앵커는 잡지 않는다
_COPY_TO_ANCHOR = re.compile(
    rf"\b(?:cp|mv|install|ln)\b[^;&|\n]*?[\s'\"](?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})"
    rf"[^\s;&|'\"]*['\"]?\s*(?:$|[;&|\n])", re.I)
# ③ 제자리 수정 — 대상이 곧 앵커
_INPLACE_ANCHOR = re.compile(
    rf"\b(?:sed\s+-i|truncate|dd\b[^;&|\n]*\bof=)[^;&|\n]*?(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})", re.I)
# ④ 삭제·권한 — 인자가 곧 대상
_DESTRUCT_ANCHOR = re.compile(
    rf"\b(?:rm|rmdir|chmod|chown|chflags)\b[^;&|\n]*?(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})", re.I)
# ⑤ 인라인 스크립트 — 쓰기 모드로 여는 경로가 앵커
_PYWRITE_ANCHOR = re.compile(
    rf"open\s*\(\s*['\"](?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})[^'\"]*['\"]\s*,\s*['\"][wax+]"
    rf"|(?:shutil\.(?:copy\w*|move)|os\.(?:replace|rename))\s*\([^)]*['\"]"
    rf"(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})[^'\"]*['\"]\s*\)"
    rf"|Path\s*\(\s*['\"](?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})[^'\"]*['\"]\s*\)\s*\.\s*write_", re.I)
# ⑥ tee 는 인자가 곧 대상
_TEE_ANCHOR = re.compile(
    rf"\btee\b(?:\s+-\S+)*\s+{_LEAD}(?:{_HOME_RE})?/?(?:{_ANCHOR_BODY})", re.I)

# ⑦ [v9] 감시 주기잡 정지 — unload/bootout/remove/disable + 감시 라벨 계열만.
#    load 는 정지가 아니라 통과. 비감시 잡(com.local.* 등)의 unload 도 통과 —
#    전 unload 를 물면 확인 피로로 가드가 죽는다(v8 교훈: 재현율보다 오탐이 가드를 죽인다).
#    라벨 없이 plist 파일을 지우고 바꿔치는 경로는 ①~⑥이 LaunchAgents 경로로 잡는다.
_LAUNCH_STOP = re.compile(
    r"\blaunchctl\s+(?:unload|bootout|remove|disable)\b[^;&|\n]*"
    r"(?:com\.anchor\.|com\.user\.claude\.|com\.harness\.)", re.I)

_ANCHOR_WRITE_RULES = (_REDIR_TO_ANCHOR, _COPY_TO_ANCHOR, _INPLACE_ANCHOR,
                       _DESTRUCT_ANCHOR, _PYWRITE_ANCHOR, _TEE_ANCHOR, _LAUNCH_STOP)


def _touches_anchor(surface: str) -> bool:
    """통제 자신을 '고치려는' 명령인가. 앵커가 소스일 뿐이면 잡지 않는다."""
    # [v9] 라벨만 쓰는 정지(bootout gui/501/<라벨>)는 경로가 없어 경로 게이트를 못 넘는다.
    if not (_ANCHOR_PATH.search(surface) or _LAUNCH_STOP.search(surface)):
        return False
    return any(rx.search(surface) for rx in _ANCHOR_WRITE_RULES)
# ---------------------------------------------------------------------------

def _has_secret(surface: str) -> bool:
    """셸 env 참조($VAR)만 있는 매치는 리터럴 시크릿이 아니다(v1과 동일 규칙).
    [v10] 범용 16진 매치가 URL 경로 세그먼트 전체를 이루는 다이제스트면 콘텐츠 해시로 본다."""
    path_spans = _url_path_spans(surface)
    for pat in _SECRET_RULES:
        for m in pat.finditer(surface):
            if "$" in m.group(0):
                continue
            if pat is _HEX_RULE and path_spans and _is_path_segment_hash(m, surface, path_spans):
                continue
            return True
    return False


def _log(**kw):
    """계측은 best-effort — 실패해도 판정에 영향 없음."""
    try:
        sys.path.insert(0, os.path.expanduser("~/.claude/tools/anti-ultron"))
        import metrics
        metrics.log("egress_guard", **kw)
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _emit("ask", FAIL_CLOSED_REASON)

    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}

    if tool == "Bash":
        surface = inp.get("command", "") or ""
        has_net = bool(_NETVERB.search(surface)) or bool(_URL.search(surface))
    elif tool == "WebFetch":
        surface = inp.get("url", "") or ""
        has_net = True
    elif tool in ("Write", "Edit", "NotebookEdit"):
        # 경로만 본다. 내용은 보지 않는다 —
        # 코드 파일에는 예시 키·테스트 페이로드가 흔히 들어 있어 내용을 검사하면
        # 정상적인 파일 작성이 줄줄이 막힌다. 여기서 막으려는 것은 유출이 아니라
        # '통제 장치를 고치는 것'이므로 대상 경로만으로 판정이 선다.
        target = inp.get("file_path", "") or inp.get("notebook_path", "") or ""
        if target and _ANCHOR_PATH.search(target):
            _emit("ask", "egress-guard A6: 편집 도구로 하네스의 통제 장치"
                         f"({target})를 고치려 한다 — 지워지면 그 즉시 보호가 사라진다. "
                         "의도한 변경인지 확인해라.")
        sys.exit(0)          # 앵커가 아니면 판정 없음(내용 미검사)
    else:
        sys.exit(0)          # 감시 대상 툴 아님 — 판정 없음
    if not surface:
        sys.exit(0)

    secret = _has_secret(surface)

    private_hosts = []
    for host, _port in _URL.findall(surface):
        if _LOCAL.match(host):
            continue
        if _PRIVATE.match(host):
            private_hosts.append(host)

    # v4 신호들 — 리터럴이 안 보여도 자격증명이 나갈 자리인가
    secret_path = _SECRET_PATH.search(surface)
    obfuscated = _OBFUSCATE.search(surface)
    bare_private = []
    for m in _BARE_IP.finditer(surface):
        ip = m.group(1)
        if _LOCAL.match(ip) or not _PRIVATE.match(ip):
            continue
        if ip not in private_hosts:
            bare_private.append(ip)

    verdict, reason = "allow", ""
    if secret and has_net:
        verdict = "deny"
        reason = ("egress-guard D1: 시크릿 리터럴이 네트워크 명령/URL과 동반됨 — 외부유출 차단. "
                  "키는 env 참조($VAR)로 바꾸거나, 정말 필요하면 사용자에게 직접 실행 요청.")
    elif secret:
        verdict = "ask"
        reason = "egress-guard A1: 명령에 시크릿 리터럴 포함(네트워크 미동반) — 로컬 기록/노출 여부 사람 확인."
    elif secret_path and has_net:
        verdict = "ask"
        reason = (f"egress-guard A3: 자격증명 파일 경로({secret_path.group(0).strip()})가 "
                  "네트워크 명령과 함께 쓰였다 — 리터럴이 안 보여도 셸이 실행 시점에 읽어 보낼 수 있다. "
                  "어디로 무엇이 나가는지 확인해라.")
    elif obfuscated and has_net:
        verdict = "ask"
        reason = ("egress-guard A4: 인코딩을 푸는 동작이 네트워크 명령과 함께 쓰였다 — "
                  "목적지나 보낼 내용이 실행 시점에만 드러난다. 무엇이 조립되는지 확인해라.")
    elif _touches_anchor(surface):
        verdict = "ask"
        reason = ("egress-guard A5: 이 명령이 하네스의 통제 장치(배선·훅·검사기·원장)를 "
                  "고치려 한다 — 지워지면 그 즉시 보호가 사라진다. 의도한 변경인지 확인해라.")
    elif private_hosts or bare_private:
        hosts = sorted(set(private_hosts) | set(bare_private))
        verdict = "ask"
        reason = f"egress-guard A2: 사설IP 대역 접근 {hosts} — 내부장비(라우터/NAS) 접근 의도 확인."

    _log(tool=tool, verdict=verdict, secret=bool(secret),
         private_hosts=sorted(set(private_hosts)), text_len=len(surface), v=2)

    if verdict != "allow":
        _emit(verdict, reason)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # v1은 여기서 exit 0(통과)였다. v2는 사람에게 넘긴다.
        _emit("ask", FAIL_CLOSED_REASON)
