"""anti-ultron — 로컬 입력/궤적 가드 (Guard + Redact + Trajectory). 게이팅·클라우드 0.

Superagent(게이팅) 대체로 자작. 외부코드 복붙 없이 재작성:
  - redact : jarvis utils.redact 설계 참조
  - guard  : Superagent Guard 2계층 설계 참조
  - trajectory : AgentDoG 1.5 taxonomy 참조
모든 호출은 metrics.jsonl에 계측 → report.py로 실효율 집계.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import guard            # noqa: E402
from trajectory import classify    # noqa: E402
from redact import scrub, audit, redact, has_secret  # noqa: E402

__all__ = ["guard", "classify", "scrub", "audit", "redact", "has_secret"]
