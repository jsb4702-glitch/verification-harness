---
name: groq-review
description: Groq API(llama-3.3-70b-versatile)로 내용을 교차검증한다. "Groq로 검증", "그록으로 교차검증", "groq review" 요청 시 호출.
---

# Groq 교차검증 스킬

교차검증 요청 시:
1. 검토 대상을 `_review_input.txt`로 저장 (가정·요구사항도 함께 포함)
2. `python3 scripts/groq_review.py _review_input.txt` 실행
3. Groq 비평을 내 답변과 대조: 일치=신뢰도↑, 반증=재검토, 검증불가=정보 보완
4. 결론을 "Groq 교차검증 결과"로 정리

## 구조화 출력 (필수 — 답변 맨 끝에 항상 포함)

검토 텍스트 이후 반드시 아래 JSON 블록을 출력:

```json
{
  "tool": "groq-review",
  "model": "llama-3.3-70b-versatile",
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

## API 키 설정

GROQ_API_KEY 환경변수가 없으면 사용자에게 안내:
- 무료 키 발급: https://console.groq.com
- 설정: `export GROQ_API_KEY="gsk_..."` (셸 프로파일에 추가)

## 검토 관점

범용 사실·논리 검증. 기술 계산, 코드 정확성, 설계 판단 등 도메인 무관하게 적용.
