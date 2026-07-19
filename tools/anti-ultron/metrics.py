"""metrics — anti-ultron 실효율 계측 (호출마다 JSONL 1행, fail-safe).

원칙:
- 절대 본 흐름을 막지 않음(로깅 예외는 삼킴).
- 입력 원문·시크릿 저장 금지 — preview는 호출측에서 redact.scrub 후 넘김.
- env ANTIULTRON_METRICS=0 이면 비활성.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

LOG_PATH = Path(__file__).with_name("metrics.jsonl")
_ENABLED = os.environ.get("ANTIULTRON_METRICS", "1") != "0"


def log(module: str, **fields) -> None:
    if not _ENABLED:
        return
    try:
        rec = {"ts": round(time.time(), 3), "module": module, **fields}
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 계측 실패가 가드 동작을 깨지 않게
