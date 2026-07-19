---
name: stp-analyzer
description: STEP 파일을 브라우저 단독 도구로 분석·정밀측정한다. full opencascade.js(WASM)로 OCC 해석적 부피·표면적·반지름·최소거리(점/선/면) 측정 + 3D 뷰어. /stp-analyzer 로 실행.
triggers:
  - "stp 분석"
  - "step 파일 분석"
  - "step 측정"
  - "치수 측정"
  - "형상 분석"
  - "cad 파일 분석"
args:
  - name: port
    description: 로컬 서버 포트 (기본 8742)
    required: false
---

# STEP 분석기 (브라우저 단독 · OCC 정밀측정)

`/stp-analyzer` 실행 시 — 로컬 서버를 띄우고 브라우저로 분석 도구를 연다. 파일은 서버 전송 없이 전부 브라우저(로컬)에서 처리된다.

## 실행 절차

1. 자산 존재 확인 (`~/stp-analyzer.html`, `~/stp-worker.js`, `~/stp-assets/opencascade.wasm.{js,wasm}`).
2. 포트(기본 8742)에 서버가 떠 있지 않으면 `~` 에서 띄운다:

```bash
PORT=${1:-8742}
cd ~
if ! curl -s -o /dev/null "http://localhost:$PORT/stp-analyzer.html"; then
  (python3 ~/.claude/skills/stp-analyzer/scripts/br_server.py "$PORT" >/tmp/stp_server.log 2>&1 &)
  sleep 1
fi
open "http://localhost:$PORT/stp-analyzer.html"
```

3. 사용자에게 안내: 브라우저 창에서 `.stp/.step` 드래그 → 분석. **고속 미리보기(occt-import-js)가 수초 내 색상 포함 표시**되고, OCC 정밀 분석(측정·부피·토폴로지)은 백그라운드로 이어짐(완료 전 측정 클릭 시 안내 표시). 첫 로드 시 OCC 엔진 다운로드 1회(`br_server.py`가 brotli 사전압축본을 서빙 → 정밀엔진 62.8MB가 **9.0MB로 전송**, 6.9x↓).

## 기능

| 레벨 | 항목 |
|------|------|
| L1 | 스키마(AP203/214/242)·단위·author·생성일시·엔티티 수 (헤더 파싱) |
| L2 | 부피·표면적·무게중심·바운딩박스(AddOptimal) — **OCC 해석적 정확값** |
| L3 | Solid/Face/Edge/Vertex 유니크 카운트, 면·엣지 종류 분포 |
| L4 | 자유엣지 |
| 측정 | 📐 ON → 점/선/면 클릭. 2개 선택 시 **BRepExtrema 최소거리**(선-선/선-점/점-면 등 임의 조합), 원호 1개 선택 시 **정확 ⌀/R/축**, 두 직선 사잇각. 측정 중에도 회전·이동 가능(클릭/드래그 구분) |

## 구성

- `~/stp-analyzer.html` — 메인 UI (three.js r128, 렌더·픽킹·측정)
- `~/stp-worker.js` — OCC 모듈 워커 (STEP 파싱·삼각화·토폴로지·BRepExtrema)
- `~/stp-assets/` — opencascade.js 1.1.1 (WASM 62.8MB) + brotli 사전압축 `.br`(9.0MB) 병치. `br_server.py`가 `Accept-Encoding: br`에 `Content-Encoding: br`로 서빙(브라우저 투명 해제, glue 무수정), 미지원/미압축 시 원본 폴백. `.br` 재생성: `brotli -f -q 10 -o F.wasm.br F.wasm`

## CLI 정밀분석 (보조)

빠른 텍스트 분석이 필요하면 Python 스크립트도 유지:

```bash
python3 ~/.claude/skills/stp-analyzer/scripts/analyze_stp.py <file_path> [output_dir]
```
