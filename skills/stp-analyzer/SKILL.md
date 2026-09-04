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
| L4 | 자유엣지 · 퇴화엣지 분리집계(합법 BRep — 자유엣지 오보고 방지) · 표시 삼각형 수 |
| 측정 | 📐 ON → 점/선/면 클릭. 2개 선택 시 **BRepExtrema 최소거리**(선-선/선-점/점-면 등 임의 조합), 원호 1개 선택 시 **정확 ⌀/R/축**, 두 직선 사잇각. 측정 중에도 회전·이동 가능(클릭/드래그 구분) |

## 대형파일 — 네이티브 모드 (2026-07-21)

- **280MB 초과 파일은 자동으로 네이티브 모드**: 브라우저가 파일을 127.0.0.1 로컬서버로 스트리밍(POST body=File — JS 힙에 전체 미적재)하고, 서버가 네이티브 OCC(파이썬 OCP)로 파싱·삼각화·집계해 바이너리 버퍼로 돌려준다. 뷰어·측정 UI는 동일, 측정(BRepExtrema)·엣지상세는 서버 API 라우팅. 파일은 localhost 밖으로 안 나감(로컬 전용 원칙 유지). `?native=1`로 소형파일도 강제 가능(회귀시험용).
- **650MB 실측(m2n 200k STEP)**: 네이티브 분석 **352~379s**·피크 메모리 **7.25GB**(네이티브)·전송버퍼 39.5MB. UI E2E 완주 — 12.4만면/28만엣지/130만 삼각형 렌더+측정 정상. 같은 파일 25MB판은 네이티브 24s(WASM 364s 대비 15배).
- WASM 경로(≤280MB)의 **힙 상한 2GB는 엔진 바이너리 선언 고정값** — 글루 JS 4GB 패치 무효 실증(롤백됨). 피크 7.25GB 실측이라 4GB 재빌드로도 650MB급은 원리상 불가 → 네이티브 모드가 유일해.
- 함정(박제): ①OCC 네이티브 호출이 파이썬 전역락을 쥐어 파싱 중 상태폴링이 수십초 굳음 — 클라이언트 폴러는 타임아웃 무시·재시도 필수(m2n 서버와 동일 교훈) ②서버는 세션 1개만 상주 — 새 분석이 이전 세션 교체 ③crease/엔티티 카운트는 서버 C레벨 바이트스캔(클라 JS 정규식은 650MB에서 분 단위) ④br_server는 127.0.0.1 바인딩(구버전 전인터페이스 노출 수리) + ThreadingHTTPServer.
- **200MB↑ 미리보기 자동 생략** (occt-import-js 이중파싱 힙압박 회피), 미리보기 실패는 침묵 대신 상태줄 표면화.
- 메모리: STEP 파싱 직후 WASM 파일사본 즉시 해제 + 리더 엔티티그래프 해제(파일크기 2~3배 절감).
- 속도: 면수 기반 **적응 삼각화**(표시용 — 측정은 해석값이라 무영향), 엣지식별 TShape 동일성 레지스트리(기하키 곡선평가 제거), 대형모델 엣지 길이/곡선 **클릭 시 lazy 산출**.
- 렌더: 무색상=1 드로우콜, 다색=연속면 그룹병합, 엣지 전체를 타입별 3버킷 병합 LineSegments(개별 Line 객체 제거). 4,283면/1.2만엣지 실측 검증 — 초대형(10만면급)은 파싱 힙한계로 미실측.
- 진행률: 파싱→변환→삼각화→면/엣지 수집 단계별 카운트 표시.

## 구성

- `~/stp-analyzer.html` — 메인 UI (three.js r128, 렌더·픽킹·측정)
- `~/stp-worker.js` — OCC 모듈 워커 (STEP 파싱·삼각화·토폴로지·BRepExtrema)
- `~/stp-assets/` — opencascade.js 1.1.1 (WASM 62.8MB) + brotli 사전압축 `.br`(9.0MB) 병치. `br_server.py`가 `Accept-Encoding: br`에 `Content-Encoding: br`로 서빙(브라우저 투명 해제, glue 무수정), 미지원/미압축 시 원본 폴백. `.br` 재생성: `brotli -f -q 10 -o F.wasm.br F.wasm`

## CLI 정밀분석 (보조)

빠른 텍스트 분석이 필요하면 Python 스크립트도 유지:

```bash
python3 ~/.claude/skills/stp-analyzer/scripts/analyze_stp.py <file_path> [output_dir]
```
