#!/usr/bin/env python3
"""로컬 Hermes(gemma4-hermes) 교차검증 — gemini 슬롯 폴백용(오프라인·무료·민감데이터 로컬보존).

parallel-verify.js 슬롯 규약: `python3 hermes_review.py <file>` → stdout에 비평.
Hermes 강점=G4날조·산술·인과(검증기 평가 실측 recall 1.00/0.92/1.00),
약점=물성/외부사실(파라메트릭 오류) → 물성검증엔 부적합, 논리/날조/산술 폴백 전용.
"""

import sys
import os
import subprocess

HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")
TIMEOUT = int(os.environ.get("HERMES_TIMEOUT", "240"))  # 건당 ~87s 실측 + 여유

SYSTEM_PROMPT = """너는 독립 교차검증 엔지니어다. 아래 [검토대상]을 옳다고 가정하지 말고 처음부터 다시 따져라. 다음을 점검:
- 사실오류·날조(풀PN·DOI·규격번호 등 존재하지 않을 법한 식별자)
- 논리 비약·인과 오류
- 산술·단위·환산 오류(중간값 재계산)
- 명시 안 된 가정, 놓친 경계조건
반증·요주의 항목만 간결히 지적하라. 문제없으면 "이견 없음"이라 하라. 입력과 같은 언어로 답하라.

[검토대상]
"""


def main():
    if not os.path.exists(HERMES_BIN):
        print(f"ERROR: hermes 실행파일 없음: {HERMES_BIN}")
        sys.exit(1)
    if len(sys.argv) < 2:
        print("Usage: hermes_review.py <input_file>")
        sys.exit(1)

    path = sys.argv[1]
    if path == "-":
        content = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    if not content.strip():
        print("ERROR: Input is empty.")
        sys.exit(1)

    prompt = SYSTEM_PROMPT + content

    print("[Hermes] gemma4-hermes 로컬 검증 중...\n")
    try:
        # 비대화 원샷 모드. PYTHONPATH/HOME은 래퍼가 unset.
        proc = subprocess.run(
            [HERMES_BIN, "-z", prompt, "--yolo"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: Hermes 타임아웃({TIMEOUT}s) — 로컬 모델 응답 없음.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Hermes 호출 실패: {e}")
        sys.exit(1)

    out = (proc.stdout or "").strip()
    if not out:
        err = (proc.stderr or "").strip()[:300]
        print(f"ERROR: Hermes 빈 응답 (rc={proc.returncode}). stderr: {err}")
        sys.exit(1)

    print("=" * 60)
    print("Hermes(gemma4-hermes) 교차검증 결과 [로컬·폴백]")
    print("주의: 물성/외부사실 카테고리는 신뢰 제한 — 날조·산술·논리 판정 우선")
    print("=" * 60)
    print(out)


if __name__ == "__main__":
    main()
