# skill-audit — 스킬/플러그인 2트랙 오디터

per-SKILL.md 단위로 **안전(Track1)** + **품질(Track2)** 동시 감사.

- 안전: skillscan(NL룰, 고recall) + inject-detect L1(regex) = 의심신호 → **skill-guard(LoRA)로 확정**.
  skillscan NL은 보안·메모리 스킬에 오탐 많음 → skill-guard가 정밀 중재(suspect→cleared).
  verdict: 🔴MALICIOUS / 🟠SUSPECT⚠(미확정) / 🟡suspect→cleared / 🟢benign
- 품질: substance = SUBSTANTIVE / THIN(얕음·개선여지) / HOLLOW(포장만·알맹이없음)

## 사용
    skill-audit.py <경로>                 # 로컬 스킬 디렉토리/레포 감사
    skill-audit.py --repo owner/name      # 격리클론(무실행) 후 감사
      [--json] [--no-guard] [--safety-only|--quality-only]

## 의존
- ~/.claude/tools/skillscan/skillscan.py
- ~/.claude/tools/skill-guard/skill-guard.py  (MLX Qwen2.5-3B+LoRA; 의심 유닛에만 호출)
- ~/.claude/tools/inject-detect/pp_detect.py  (선택; 없으면 스킵)

## 검증 (2026-07-06)
- 픽스처 3/3 정확: 악성 SKILL.md→🔴MAL, hype빈→HOLLOW, 짧음→THIN
- 정밀: 사용자 실제 스킬 turnstile(rm-rf)·intake(jailbreak regex) skillscan 오탐 → skill-guard가 suspect→cleared
- 스케일: 스킬유닛 2197개(큐레이션)+35개(롱테일) 트리아지 완주
