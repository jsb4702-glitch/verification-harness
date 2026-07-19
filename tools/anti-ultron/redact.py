"""
redact — 결정론적 시크릿/PII 스크럽 (jarvis utils.redact 설계 참조, 전면 재작성)

순수 stdlib(re)만 의존. 외부콜 0. 저장·로깅·외부전송 직전 호출.
규칙 순서 = 구체적(벤더 키) → 일반(prefix/hex) 순으로 정보량 큰 라벨 우선.
"""
from __future__ import annotations
import re, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics  # noqa: E402  (flat import; tool dir on sys.path)

# (pattern, label). 위에서부터 적용 — 구체 규칙이 일반 규칙보다 먼저.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"), "[REDACTED_STRIPE_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED_GOOG_KEY]"),
    (re.compile(r"\bxox[abpcr]-[A-Za-z0-9\-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
                re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE), "Authorization: Bearer [REDACTED]"),
    (re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE), "Authorization: Basic [REDACTED]"),
    (re.compile(r"\beyJ[0-9A-Za-z._\-]+\b"), "[REDACTED_JWT]"),
    (re.compile(
        r"\b(pass(?:word)?|secret|token|apikey|api_key|"
        r"(?:refresh|access|id|oauth)_?token|session(?:_?id)?|sid)"
        r"\s*[:=]\s*\S+",
        re.IGNORECASE,
    ), r"\1=[REDACTED]"),
    (re.compile(r"\b[0-9A-Fa-f]{32,}\b"), "[REDACTED_HEX]"),
    (re.compile(r"\b\d{6}\b(?=.*(?:otp|2fa|code))", re.IGNORECASE), "[REDACTED_OTP]"),
]


def scrub(text: str) -> str:
    """줄바꿈 보존, 길이제한 없음 — 구조적 콘텐츠(툴출력·다행)용."""
    for pat, repl in _RULES:
        text = pat.sub(repl, text)
    return text


def redact(text: str, max_len: int = 8000) -> str:
    """공백붕괴 + 길이상한 — 짧은 메모/단행 로깅용."""
    text = scrub(text)
    text = " ".join(text.split())
    return text[:max_len]


def has_secret(text: str) -> bool:
    """원문에 시크릿이 있었는지 여부(스크럽 전후 비교)."""
    return scrub(text) != text


def audit(text: str) -> str:
    """scrub + 계측 — 타입별 마스킹 건수를 metrics에 기록(standalone redaction 효율 추적)."""
    t = time.perf_counter()
    hits: dict[str, int] = {}
    out = text
    for pat, repl in _RULES:
        out, n = pat.subn(repl, out)
        if n:
            label = repl if repl.startswith("[REDACTED") else "[REDACTED_KV]"
            hits[label] = hits.get(label, 0) + n
    metrics.log("redact", n_secrets=sum(hits.values()), by_type=hits,
                ms=round((time.perf_counter() - t) * 1000, 3), text_len=len(text))
    return out
