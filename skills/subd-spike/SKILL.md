---
name: subd-spike
description: SubD 자유곡면 애드인(Power Surfacing류) 프로젝트의 P0-a 검증 스파이크를 돌린다. all-quad 정규위상 SubD를 bicubic B-spline 패치로 변환→OCCT 봉합→워터타이트 STEP 출력→자체 무결성 검증(자유엣지 0·닫힌 솔리드). "subd 스파이크", "P0 테스트", "워터타이트 step 검증", "서브디비전 변환 테스트" 시 호출. /subd-spike 로 실행.
triggers:
  - "subd 스파이크"
  - "subd spike"
  - "P0 테스트"
  - "P0-a"
  - "워터타이트 step 검증"
  - "서브디비전 변환 테스트"
args:
  - name: n
    description: 면당 제어점 격자 크기(>=4). 곡률 해상도. 기본 6
    required: false
  - name: bulge
    description: 내부 제어점 외향 팽창량(곡률 세기). 기본 0.35
    required: false
  - name: half
    description: 큐브 반변 길이[mm]. 기본 10
    required: false
  - name: tol
    description: 봉합 tolerance[mm]. 기본 1e-4
    required: false
---

# subd-spike — SubD → 워터타이트 STEP 검증 스파이크 (P0-a)

SubD 자유곡면 애드인 프로젝트(설계: `~/subd-addin/docs/DESIGN.md`)의 **B기둥 하류 리스크**를 검증한다.
OpenSubdiv 포럼이 실패한 "패치 워터타이트 봉합"을, D2 all-quad 제약 하에서 정면 테스트.

## 전제
- `cadquery-ocp`(OCP, 풀 OpenCASCADE Python 바인딩)가 설치돼 있어야 함.
  - 확인: `python3 -c "import OCP; print('ok')"`
  - 없으면: `pip install cadquery-ocp`
- 정본 스크립트: `~/subd-addin/spike/subd_spike.py`

## 실행 (Claude가 수행)

1. args가 있으면 플래그로 전달해 실행:
   ```
   python3 ~/subd-addin/spike/subd_spike.py [--n N] [--bulge B] [--half H] [--tol T] [--out PATH]
   ```
   기본값만이면 인자 없이 실행.

2. 출력의 **C4-mac 판정 블록**을 그대로 표로 정리해 보고:
   - 자유엣지 0 / BRepCheck 유효 / 닫힌 솔리드 / STEP 출력 → 각 PASS·FAIL
   - 종합 ✅/❌
   - STEP 경로·크기

3. **반드시 명시(과대주장 금지)**: 이 스파이크는
   - ✅ 증명: "엣지일치 bicubic 패치 → OCCT 워터타이트 봉합 → STEP" 하류 파이프라인.
   - ❌ 미증명: ① 실제 SubD 케이지에서 엣지일치 패치를 뽑는 변환기(P1/P2) ② SW가 실제로 여는지(C4-full = Windows+SolidWorks 필요, P0-b).

4. FAIL 시: 자유엣지>0이면 tol을 키워(예 1e-3) 재시도하거나 패치 엣지일치 로직 점검 안내. 판정은 무손실로 보고(G12: 실제 출력 대조).

## 주의
- 이 스킬은 **맥에서 도는 엔진검증**이다. C4-full(SW 오픈)은 별도 윈도우 단계(P0-b).
- 판정 수치(자유엣지·엔티티수)는 실제 실행출력 그대로 — 날조 금지.
