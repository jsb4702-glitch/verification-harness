---
name: gemini-review
description: 기구설계 검토 결과·계산·도면 해석을 Gemini로 교차검증한다. 사용자가 "제미나이로 교차검증", "이거 검토해줘", "second opinion", "검증" 요청 시 호출. 설계 판단의 사실오류·논리비약·누락 식별용.
---

# Gemini 교차검증 스킬

교차검증 요청 시 실행 절차:

1. 검토 대상(내 답변/계산/설계 판단)을 임시 파일 `_review_input.txt`로 저장
2. `python3 scripts/review.py _review_input.txt` 실행 (윈도우는 `python scripts\review.py _review_input.txt`)
3. Gemini 반환 비평을 받아 내 원답변과 대조:
   - 일치 항목: 신뢰도 상향
   - 불일치 항목: 양측 근거 제시 후 재검토
   - Gemini가 지적한 누락: 보완
4. 결론을 "교차검증 결과" 블록으로 정리(합의/이견 구분)

주의: 검토 관점은 제품 기구설계(공차·체결·재료·구조·DFM). 기초 개념 재설명 금지.

## 구조화 출력 (필수 — 답변 맨 끝에 항상 포함)

검토 텍스트 이후 반드시 아래 JSON 블록을 출력:

```json
{
  "tool": "gemini-review",
  "model": "gemini-2.5-flash",
  "verdict": "PASS|WARN|FAIL",
  "confidence": "HIGH|MED|LOW",
  "findings": [
    {"claim": "검토 대상 주장", "status": "confirmed|refuted|unverified", "detail": "근거 1줄", "severity": "INFO|WARN|ERROR"}
  ],
  "summary": "종합 판정 1줄"
}
```

- `verdict`: PASS=이견 없음, WARN=조건부/수정 권고, FAIL=명확한 오류 발견
- `findings`: 불일치·요주의 항목만 포함 (일치 항목 생략)
- Workflow/자동파이프라인이 이 블록을 파싱해 교차판정에 사용함
