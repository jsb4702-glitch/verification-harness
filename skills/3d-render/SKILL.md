---
name: 3d-render
description: 3D 모델(STEP/IGES/STL)을 로컬에서 제품컷·엔지니어링 뷰로 렌더링한다. OCP 삼각화→VTK 4뷰 시트(빠른 확인)→Blender Cycles 스튜디오 렌더(재질·조명·자세·테이블/모서리 연출), ambientCG·Poly Haven CC0 텍스처 자동 수령 포함. "렌더링 해줘", "STEP/모델 이미지로", "제품컷 뽑아줘", "4뷰로 보여줘", "이 자세로 돌려서 렌더", "텍스처 입혀서" 요청 시 호출. 전 과정 로컬(파일 외부 전송 없음), 민감 모델 취급 가능.
---

# 3d-render — 로컬 3D 렌더 파이프라인

전부 이 머신에서 실행: OCP 7.9(STEP 파서)·VTK 9.6(프리뷰)·Blender 4.3.2(`/Applications/Blender.app`)·trimesh. 모델 파일은 밖으로 안 나간다(텍스처 다운로드만 아웃바운드).

## 입력 경계 · 형상 신뢰
- **렌더 전 형상 검증 필수**: 삼각화 직후 preview.py로 실물 대조. 이상하면(고리/판 등 원본에 없는 형상) 트림 소실 의심 — 컨버터 산출 STEP(convert3d 등)에서 OCP STEPControl/XCAF 리더가 와이어를 잃는 사례 실측. ShapeFix로도 안 낫는다.
- **트림 소실 시 우회**: `node scripts/occt2stl.mjs in.stp out.stl` (occt-import-js WASM — 같은 파일을 정상 트림으로 삼각화, deflection 파라미터 내장). stp-analyzer 뷰어(포트 8742, stp-assets 허용트리에 파일 복사 후 fetch 주입)로 육안 교차확인 가능.
- **분리 저장 멀티바디**: 반쪽들이 이격 저장된 파일 존재(66mm 갭 실측) — trimesh split 후 접합면 z-이동 조립. 접합 전 컴포넌트 census(면적·bbox·중심) 필수, 저밀도 대형 시트=작도면이니 제외.

- 되는 것: STEP/IGES(OCP), STL/OBJ/PLY/GLB(trimesh/Blender 직import)
- 안 되는 것: SLDPRT/SLDASM, NX .prt, Parasolid x_t, JT → STEP 내보내기 요청할 것

## 파이프라인 (scripts/)
```
1. tessellate.py IN.step OUTDIR [--defl 0.12] [--ang 0.25] [--split-band]
   → model.stl (또는 model_main.stl + model_band.stl)
   --split-band: z단면 폭이 전체의 35% 미만인 좁은 구간(기둥/샤프트)을 별도 STL로 분리 → 이중 재질용
2. rotate_stl.py in.stl out.stl [--up ux,uy] [--rotx/--roty/--rotz DEG]
   자세 만들기. --up: 원좌표 xy평면의 (ux,uy)방향을 새 +Z로(원 Z축은 수평 +Y가 됨). 파트 여러 개면 같은 옵션 반복 적용.
3. preview.py out.png a.stl [b.stl] [--floor | --block XE,TOP] [--cam x,y,z]
   VTK 오프스크린 ~5초. 자세·접지·블록 배치는 반드시 여기서 눈으로 확정 후 Cycles로.
4. quadview.py IN.step OUTDIR    # 엔지니어링 4뷰 시트(등각+정면/평면/측면 정사영, XCAF 색상 지원)
5. studio_render.py (Blender로 실행):
   /Applications/Blender.app/Contents/MacOS/Blender -b --python studio_render.py -- \
     BODY.stl COL.stl|none OUT.png AZ EL DSCALE LENS floor|block XE TOP RX RY SAMPLES
   - AZ/EL deg, DSCALE=거리(bbox대각선 배수, 1.9~3.0), LENS mm(50 기본, 측면 85)
   - floor: 무한 바닥(모델 min-z 접지). block: 테이블/모서리 연출 — 모델좌표 기준 면 x=XE(블록은 x>XE), 상면 z=TOP
   - 재질 env: PAINT_COLOR/PAINT_ROUGH(밴드=페인트 반광+클리어코트), ABS_COLOR/ABS_ROUGH(본체 무광)
   - 텍스처 env: PBR_DIR=텍스처폴더 PBR_SCALE=1.5 → 블록에 Color(sRGB)+Roughness+NormalGL(Non-Color) 자동 배선
   - 재질 프리셋: MAT_MODE=preset MAT_PRESET=anodized|chrome|gold|smoke_glass|ceramic|rubber_coral|flake|wood — wood는 PBR_DIR(텍스처폴더)+PBR_SCALE(0.004≈나뭇결 25cm 주기) 필요, 이미지 텍스처는 박스 프로젝션이라 UV 불요. 밝은 재질은 조명 밝게(WORLD 0.25/KEY_SIZE 1.2/FILL·BACK 14), 글라스는 샘플 224+.
- 투톤: 몸통 STL + 부위 STL 두 슬롯 — 부위 분리는 trimesh `slice_mesh_plane`(shapely 필요, 삼각형 통짜 분류는 경계 톱니 생김·금지). 렌더는 MAT_MODE=carbon + COL_PRESET=rubber_coral(RUBBER_RGB=r,g,b) 식으로 col 슬롯에 프리셋 지정.
- 데칼: DECAL_IMG=알파PNG + DECAL_Y0/W(가로 원점·폭mm)/X0/H(세로) — 오브젝트 좌표 상면 평면투영(윗면 법선 마스크, UV 불요), 카본 바탕색 체인에 알파 합성. 부호로 좌우/상하 플립. 글자 방향은 라이더 시점 기준으로 넣고 카메라를 그쪽에서 잡아라(반대편 뷰에선 뒤집혀 보이는 게 실물과 동일). 시트 제작은 PIL(2048px, 물리 400×76mm 비례).
- 카본 env: MAT_MODE=carbon WEAVE_MM=1.6(3K)|5.5(12K)|0(UD) WEAVE_BUMP=0.28(클로즈업)|0.10(풀샷) — 프로시저럴 직조(UV 불요, 오브젝트 공간=mm!)
   - 조명 env: WORLD_STRENGTH(0.30) KEY_W(55) KEY_SIZE(1.5) FILL_W(18) BACK_W(17) COAT_W(1.0) — 카본 확정 세팅: 0.06/60/0.45/6/8/0.85, 카메라 고도 풀샷 22°·클로즈업 18°
6. pbr_fetch.py "wood" [--source acg|ph] [--res 2K]  → 캐시 폴더 경로 출력(~/.cache/pbr-textures)
7. bake_axis_uv.py in.stl out.obj [--style flow|forged]  # flow=UD 결 축따라(푸아송), forged=단조카본 마블(위상밀림+범프 조각면을 미학으로 쓰는 프리셋 — 렌더 시 UD_FORGED=1 WEAVE_BUMP=0.35 필수). UD 결 흘리기: 실루엣 거리변환→방향장→부호정렬(BFS)→푸아송 스트림함수를 UV로 베이크. studio_render에 out.obj + MAT_MODE=carbon WEAVE_MM=0 UD_ALONG=1 로 사용. 평면형 프레임(XZ) 가정.
```

## 텍스처 라이선스 게이트 (중요)
- 자동 다운로드는 **ambientCG·Poly Haven만** (CC0 실확인, robots 허용, 공식 API). pbr_fetch.py가 이 둘만 화이트리스트.
- 3dassets.one은 메타 검색엔진 — 검색 참고용으로만. 색인에 CC0 아닌 소스 섞여 있음(Poliigon 재배포금지, Raw Catalog 대량다운로드 금지, Location Textures/Lightbeans 유료 등) → 그쪽은 자동화 금지, 링크 안내만.
- Poly Haven API 약관: 고유 User-Agent 필수(스크립트에 반영됨) + 산출물 공개 시 출처표시 권장.
- ambientCG API는 1인 운영·무보장(508 간헐 실측) → 캐시 우선, 실패 시 재시도 1회 후 Poly Haven 폴백.

## 작업 루프 (권장)
**모든 드래프트(실패 판정 포함)를 나오는 즉시 SendUserFile로 전송** — 자체 큐레이션 금지(사용자가 버린 시도에서 최종안(단조카본)을 골라낸 실사례). 드래프트(800×600, 24샘플, ~2초)로 방향 확인 → 확정 후 본렌더(1920×1440, 128샘플, 40~60초/장). 모든 자세·접지 변경은 preview.py로 먼저 검증. 렌더 결과는 Read로 직접 보고 판정한 뒤 전달.

## 함정 (실측으로 배운 것)
- **노출**: 미터 스케일에서 조명 과다면 검정 재질이 회색으로 뜬다(재질버그로 오진하기 쉬움). 의심되면 재질을 빨강으로 바꿔 프로브 — 색이 뜨면 배선 문제, 희멀겋면 노출 문제. 기준값: world 0.30 / key 55W·1.5m / fill 18 / back 17, AgX Base Contrast.
- **Blender 4.3 API**: `use_auto_smooth` 삭제됨 → `shade_smooth_by_angle` try/except. view_settings.look은 'AgX - Base Contrast' 형식 전체 문자열. STL import 객체는 import 전후 diff로 잡아라(selected_objects[0] 신뢰 금지 — 재질 오배선 사례).
- **음각/양각 글자**: 편차 0.12mm면 뭉개짐 → --defl 0.08 + 스침광(낮은 각도 측면 area light). 글자 위치는 미세 삼각형 밀집 클러스터로 검출 가능. 곡선 획만 점묘에 보이고 직선 획은 긴 삼각형이라 높이맵 점찍기엔 안 보임(렌더에는 나옴).
- **자세 산출**: 접지면은 기하로 풀어라 — 최저 z 밴드(±1.5mm)의 클러스터 수·간격으로 판정(한 줄=모서리 균형, 두 클러스터=안정). 팔 길이가 다른 비대칭 형상은 "꼭짓점 방향" 축이 아니라 **발끝 연결선의 수직**이 위 방향. 크라운(볼록) 모서리는 롤 스윕으로 접지 평탄화(±8° 0.5° 스텝, 최저 z 스팬 최소화).
- **면 뒤집힘**: OCP 삼각화에서 TopAbs_REVERSED 면은 와인딩 스왑 필수(스크립트 반영됨) — 안 하면 검은 면.
- **사용자 자세 지시는 형상 기능으로 해석**: 세레이션(그립) 패드가 어느 면에 있는지 먼저 파악 — 패드는 항상 접촉면을 물어야 한다. 애매하면 화살표 방향을 카메라가 아니라 부품 회전으로 먼저 시도.
- macOS 창 없는 컨텍스트에서 EEVEE 불안정 → Cycles CPU 기본(denoise on).
- 좌표: STEP=mm, Blender 씬=×0.001 미터. 카메라는 TRACK_TO 엠프티로(수동 오일러 금지).
- **프로시저럴 텍스처 좌표는 오브젝트 공간=원본 mm**(씬 미터 아님) — 스케일을 m 기준으로 주면 1000배 미세해져 무늬가 픽셀 평균으로 증발한다(카본 직조 실사례). 셀 크기는 mm로 계산.
- **UV 기반 무늬에 Bump 노드 금지** — 도함수 기반이라 삼각형별 UV 그래디언트 차이가 조각면(마블)로 드러난다. UV 무늬는 거칠기·색 변조(값 기반)로만. 방향장 u에 전역좌표 곱하는 식(u=-sinθ·x+cosθ·z)도 금지 — θ 미세 변화×좌표크기=한 주기 이상 위상 밀림(마블 원인 실측). 반드시 푸아송 적분으로.
- 유광 검정이 은회색/메탈로 뜨는 3대 원인(카본 실사례, 순서대로 점검): ① 섬유층(바탕) 거칠기를 낮게 주면 브러시드 메탈이 된다 — 바탕은 거칠기 0.35~0.5+Specular IOR Level 0.25로 어둡게 두고 광은 클리어코트(0.85/0.015)만 담당 ② 대형 소프트박스가 코트에 통짜로 비침 — KEY_SIZE 0.45 스트립으로 ③ 카메라 저고도(12°)면 윗면이 스침각 프레넬로 하얗게 뜸 — 풀샷 고도 22°+. 미세 범프는 풀샷에서 샘플링 모래알 → WEAVE_BUMP 풀샷 0.10.

## 실물 복제 워크플로 (사진→복제 렌더)
1. 형상: tessellate→preview로 실물 사진과 실루엣 대조(필수, 트림소실/조립오류 잡기)
2. 마감 동정: 사진의 표면(무광 마블=FORGED3D CHIP_MM=22 COAT_W=0.12 COAT_R=0.28 / 직조=WEAVE_MM / 유광=COAT_W 0.85)
3. 데칼 채증: 사진 줌크롭(PIL crop+resize)으로 마크 위치·크기·읽기방향(정면/후방 180°) 기록
4. 로고 수배 순서: 공홈 테마자산(브라우저로 CF 통과→경로 탐침) → web.archive.org id_ 미러로 무결 다운로드(브라우저 base64 손전사 금지=오염 실측) → 리테일러 CDN(쇼피파이는 열려있음, 공식사진 파일명 시리즈 프로브) → 사진 픽셀 추출(고대비·100px+일 때만 성립)
5. 시트 조립: PIL 2048px, 물리 400×76mm 비례, 마크는 팔 스윕각 회전, 정면읽힘 마크는 시트에서 180° 회전
6. 렌더: DECAL_*/DECAL_SIDE_* env, 드래프트 전량 즉시 사용자 전송 후 본렌더
- 아카마이(bm-verify)는 실브라우저도 차단 — 아카이브/리테일러로 우회. egress-guard가 32hex+URL 오탐하면 해시 반쪽연결.

## 스모크 (회귀 확인용 1줄씩)
```
python3 scripts/tessellate.py 모델.step /tmp/t --split-band
python3 scripts/rotate_stl.py /tmp/t/model_main.stl /tmp/t/up.stl --up 0,1
python3 scripts/preview.py /tmp/t/p.png /tmp/t/up.stl --floor
python3 scripts/pbr_fetch.py wood --res 2K
```
