# Skill Card — {{NAME}}

> 거버넌스 카드. promote 시 자동생성, 사람검증자가 빈칸(❓)·[VERIFY] 마커 해소 후 확정.
> 스키마는 NVIDIA governance skill card(CC-BY-4.0)에서 발췌·개조 — 검증신호 섹션은 자작 하네스 고유.

## 1. Identity / 정체
| 항목 | 값 |
|------|-----|
| Skill | {{NAME}} |
| Owner (원저작자) | {{OWNER}} |
| Source (출처) | {{SOURCE}} |
| License | {{LICENSE}}  ← [VERIFY] 원본 LICENSE 실확인 |
| Version | {{TREE_HASH}} @ {{DATE}} |

## 2. Provenance / 도입경로  (← PROVENANCE.tsv 연동)
| 항목 | 값 |
|------|-----|
| Status | {{STATUS}}  (PENDING / PROMOTED / REJECTED) |
| Via | {{VIA}}  (rebuild=깨끗재작성 / extract=발췌+해시잠금 / sandbox=격리) |
| Reviewer | {{BY}} |
| Intake date | {{DATE}} |

## 3. Verification Signals / 검증신호  ★자작 하네스 고유 — 카드의 핵심
| 게이트 | 결과 | 임계(promote 조건) |
|--------|------|-------------------|
| skillscan IOC | HIGH={{H}} MED={{M}} LOW={{L}} | **HIGH=0 필수** |
| dyntrace | {{DYN_EXIT}} (net/proc 차단위반 {{DYN_VIOL}}) | HIGH 아님 |
| inject-detect | L1={{INJ_L1}} L2={{INJ_L2}} | 지시성 콘텐츠 0 |
| 사람정독 | {{HUMAN}} | 은닉지시·exfil·정체성접근·난독화·과권한 5항 all-clear |

## 4. Governance / 거버넌스  (← NVIDIA 스키마 차용)
| 항목 | 값 |
|------|-----|
| Use case (용도) | {{USECASE}} |
| Known risks & mitigations | {{RISKS}} |
| **Export control (민감)** | {{EXPORT}}  ← 수출통제 규정/수출통제 규정 저촉 여부 ❓ |
| Boundary / 경계 | {{BOUNDARY}}  (스킬이 건드리면 안 되는 것) |

## 5. Attribution
Card schema adapted from **NVIDIA Governance Skill Card** (github.com/nvidia/skills, CC-BY-4.0).
Verification-signal section: original (skillscan/dyntrace/inject-detect harness).
