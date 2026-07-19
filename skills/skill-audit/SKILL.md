---
name: skill-audit
description: 스킬/플러그인을 per-SKILL.md 단위로 안전(악성)+품질(속빈강정) 동시 감사한다. 안전=skillscan(NL룰)+inject-detect L1 의심신호를 skill-guard(LoRA)로 확정(보안·메모리 스킬 오탐을 정밀 중재), 품질=substance로 SUBSTANTIVE/THIN(얕음·개선여지)/HOLLOW(포장만·알맹이없음) 분류. "스킬 감사", "이 스킬/플러그인 안전한지", "스킬 품질/알맹이 검토", "hollow 스킬 찾아", "속빈 스킬", "스킬 오디터", "audit this skill", "외부 스킬/플러그인 도입 전 검토", "SKILL.md 악성 확인" 시 호출. 로컬 경로 또는 GitHub 레포(--repo owner/name, 격리클론·무실행).
---

# skill-audit — 스킬/플러그인 2트랙 오디터

외부 또는 로컬 스킬/플러그인을 **안전(Track1)** + **품질(Track2)** 두 축으로 감사한다.
엔진은 `~/.claude/tools/skill-audit/skill-audit.py` (기존 skillscan·skill-guard·inject-detect 재사용 + substance).

## 실행

```bash
# 로컬 스킬 디렉토리/레포 (재귀로 모든 SKILL.md 유닛 감사)
python3 ~/.claude/tools/skill-audit/skill-audit.py <경로>

# GitHub 레포 (격리클론 --depth1·훅무력화·무실행 후 감사, 끝나면 자동삭제)
python3 ~/.claude/tools/skill-audit/skill-audit.py --repo owner/name

# 옵션
#   --json           기계판독
#   --safety-only    안전축만 (빠름, skill-guard만 비용)
#   --quality-only   품질축만 (정적·빠름, MLX 불필요)
#   --no-guard       skill-guard 생략(의심=미확정으로 남김)
```

## 판정 읽는 법

**안전(Track1)** — skillscan NL룰은 고recall·저precision(보안·메모리 스킬에 오탐 多)이므로 skill-guard가 정밀 중재:
- `🔴 MALICIOUS` — skill-guard 확정. **청소(유해요소 제거)+clean-room 리빌드** 대상
- `🟠 SUSPECT⚠` — 신호는 있으나 skill-guard 미확정/미가용 → 사람 정독 필요
- `🟡 suspect→cleared` — skillscan은 걸렸으나 skill-guard가 무해 판정(전형적 오탐: 보안스킬이 인젝션 예시 포함)
- `🟢 benign` — 의심신호 없음

**품질(Track2)**:
- `SUBSTANTIVE` — 알맹이 충분
- `THIN` — 얕음·개선여지 → **채워서 유용하게** 대상
- `HOLLOW` — 포장(과장 claim)만·알맹이 없음

## 활용 흐름
- 외부 스킬 도입 전 1차 스크리닝 (INTAKE `receive`에도 품질진단으로 배선됨)
- 악성(🔴)이면 → INTAKE 프로토콜로 격리→정독→clean-room 리빌드→promote
- THIN/HOLLOW이면 → 살릴 가치 판단 후 build-out(깊이 채우기) 또는 폐기

**주의**: 판정은 의사결정 보조. 🔴/🟠는 반드시 사람 정독. skill-guard는 MLX(Apple Silicon) 필요 — 없으면 `--no-guard`.
