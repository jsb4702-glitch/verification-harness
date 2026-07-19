#!/usr/bin/env python3
"""
PreToolUse 차단훅 — egress-guard (ironclaw leak_detector/NetworkPolicy 본질로직 이식).

정책(2026-07-06 4후보 재분석 채택분, 후보1+2 통합):
  D1 시크릿 리터럴 + 네트워크 명령/URL 동반  → deny  (외부유출 차단)
  A1 시크릿 리터럴, 네트워크 미동반(로컬기록) → ask   (사람게이트)
  A2 사설IP대역 URL(10./172.16-31/192.168./169.254) → ask (SSRF/내부장비 게이트)
  -- localhost/127.0.0.1 = egress 아님 → 허용 (ollama 11434 등 하네스 인프라 보호)
  -- 판정불가/예외 = fail-open(exit 0) — 오차단이 세션 깨는 리스크 > 미탐 리스크(LuLu 교훈)

시크릿 판정 = anti-ultron redact._RULES 재사용(결정론 regex 15룰).
전 판정 metrics.jsonl 기록(tag=hook:egress). 한계: 호스트명 DNS 리졸브 안 함(리바인딩 미커버).
"""
import sys, os, json, re

TOOLDIR = os.path.expanduser("~/.claude/tools/anti-ultron")
sys.path.insert(0, TOOLDIR)

_URL = re.compile(r"https?://([^/\s:'\"]+)(?::(\d+))?", re.I)
_NETVERB = re.compile(r"\b(curl|wget|nc|ncat|ssh|scp|sftp|rsync|ftp|telnet)\b", re.I)
_PRIVATE = re.compile(
    r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.0\.0\.0)"
)
_LOCAL = re.compile(r"^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?)$", re.I)


def _decision(decision: str, reason: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        p = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = p.get("tool_name", "")
    inp = p.get("tool_input", {}) or {}

    if tool == "Bash":
        surface = inp.get("command", "") or ""
        has_net = bool(_NETVERB.search(surface)) or bool(_URL.search(surface))
    elif tool == "WebFetch":
        surface = inp.get("url", "") or ""
        has_net = True
    else:
        sys.exit(0)
    if not surface:
        sys.exit(0)

    try:
        import redact, metrics  # noqa: E402
        # redact 룰 직접 순회: 매치 스팬에 셸 env참조($VAR)가 있으면 리터럴 시크릿 아님
        # (Authorization/KV 일반룰이 "Bearer $KEY" 권장패턴을 FP로 잡는 것 방지 — 실측 케이스7)
        secret = any(
            "$" not in m.group(0)
            for pat, _ in redact._RULES
            for m in pat.finditer(surface)
        )
    except Exception:
        sys.exit(0)  # fail-open

    # 사설IP 대역 URL 추출(localhost는 egress 아님 → 제외)
    private_hosts = []
    for host, _port in _URL.findall(surface):
        if _LOCAL.match(host):
            continue
        if _PRIVATE.match(host):
            private_hosts.append(host)

    verdict, reason = "allow", ""
    if secret and has_net:
        verdict = "deny"
        reason = ("egress-guard D1: 시크릿 리터럴이 네트워크 명령/URL과 동반됨 — 외부유출 차단. "
                  "키는 env 참조($VAR)로 바꾸거나, 정말 필요하면 사용자에게 직접 실행 요청.")
    elif secret:
        verdict = "ask"
        reason = "egress-guard A1: 명령에 시크릿 리터럴 포함(네트워크 미동반) — 로컬 기록/노출 여부 사람 확인."
    elif private_hosts:
        verdict = "ask"
        reason = f"egress-guard A2: 사설IP 대역 접근 {sorted(set(private_hosts))} — 내부장비(라우터/NAS) 접근 의도 확인."

    try:
        metrics.log("egress_guard", tool=tool, verdict=verdict,
                    secret=bool(secret), private_hosts=sorted(set(private_hosts)),
                    text_len=len(surface), preview=redact.scrub(surface)[:120])
    except Exception:
        pass

    if verdict != "allow":
        _decision(verdict, reason)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open
