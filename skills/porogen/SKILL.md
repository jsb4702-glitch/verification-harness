---
name: porogen
description: >-
  음함수 다공/격자 조형 킷(~/porogen) — 형상×격자×영역 자유 합성으로 다공성 구조를
  생성한다. 임의 STL 기재 임포트, TPMS(기브로이드 시트/네트워크·다이아몬드·슈바르츠P)+
  보로노이 해면골+임의 수식 격자, 등각 표피·깊이창·다층 구배, 목표 기공률 자동 튜닝,
  검증(기공률·기공지름·스켈레톤 진두께·수밀성) 내장. "다공성 구조 만들어", "격자 채워",
  "TPMS/자이로이드", "임플란트 표면 다공", "해면골 격자", "이 STL에 격자 입혀",
  "기공률 X%로" 요청 시 호출. 로컬 전용(파일 외부 전송 없음), 민감 형상 취급 가능.
---

# porogen 사용법

위치 `~/porogen`. 파이썬 환경: numpy·scipy·scikit-image·trimesh 필요
(세션 venv 또는 시스템 python3 — rhino3dm 있으면 .3dm 수출 가능).

핵심 API와 규율은 `~/porogen/README.md`가 정본 — **작업 전에 반드시 읽어라.**
특히 검증 규율 5개(스켈레톤 두께·본질 셀 측정·원본 연결성 수밀검사·복셀≤부재/3·
정확0 넛지)는 과거 오판 사례에서 나온 것이라 생략 금지.

## 빠른 패턴

- 부품에 표피 다공층: `Model(shape).add(surface_band(shape,t), lattice.X(cell), porosity=p)`
- 임의 STL 기재: `sdf.mesh_sdf(path, voxel)` (수밀 필수)
- 다층 구배: `depth_window(shape, d0, d1)` 겹쳐 add
- 검증: `verify.band_report`(부품), `verify.unit_cell_report`(설계 참값),
  `verify.watertight`

## 설계 창 (골유착/L-PBF 기준값 — 출처는 메모리 implant-porous-demo)

기공 300~700µm·기공률 50~65%·벽 240µm 이상. 창 대조는 unit_cell_report 수치로.

## 함정

- 격자 셀 대비 복셀 과대 → 핀치/비다양체. 복셀 ≤ 최소 부재의 1/3.
- 대역 내 두께 측정은 클리핑 저평가 — 창 판정은 본질 셀 값으로.
- 보로노이는 bounds 밖에서 스트럿 없음(영역이 bounds 안인지 확인).
- E2E 스모크: `python examples/spacer_reproduce.py` (수밀 True·기공률 60% 나와야 정상).
