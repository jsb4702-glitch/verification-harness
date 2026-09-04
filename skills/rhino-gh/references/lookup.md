# API 실조회 레시피 + 생태계 지도

이 스킬의 핵심 규율: references/ 밖의 API 시그니처는 여기 레시피로
실조회 후에만 인용한다. 전부 2026-08-25 실측 검증된 경로.

## API 문서 조회

- 전체 개요: https://developer.rhino3d.com/api/ 에 11개 레퍼런스 링크
  (RhinoCommon, RhinoScriptSyntax, Grasshopper, RhinoScript, C++, Eto.Forms,
  compute 파이썬/JS, rhino3dm .NET/py/js). 직접 fetch 정상.

- **RhinoCommon (신형)**: 인덱스 페이지는 WebFetch로 본문이 안 잡힌다
  (SPA 추정, 실측 2회 실패). 대신 WebSearch로
  `site:developer.rhino3d.com/api/rhinocommon {ClassName}` 검색해 URL 확보.
  URL 패턴: `/api/rhinocommon/{namespace.classname 소문자.점구분}/{member 소문자}`
  (예: /api/rhinocommon/rhino.geometry.point3d/transform).
  ⚠️ 이 신형 페이지 본문도 직접 fetch가 안 될 수 있다(제목만 반환된 실측) —
  그 경우 아래 구형 URL로 우회.

- **RhinoCommon (구형)**: `developer.rhino3d.com/api/RhinoCommon/html/T_{Namespace}_{ClassName}.htm`
  (밑줄 구분). rhino3dm 문서 페이지가 이 형식으로 링크하는 것 실측 확인.

- **Grasshopper SDK**: `developer.rhino3d.com/api/grasshopper/html/` 아래
  접두사 규칙 — 클래스 `T_...htm`, 메서드 `M_...htm`, 속성 `P_...htm`
  (예: T_Grasshopper_Kernel_GH_Component.htm — 직접 fetch 성공 실측).
  정확 URL은 WebSearch `site:developer.rhino3d.com/api/grasshopper {명칭}` 로.
  인덱스는 GUID 리다이렉트라 탐색 불가.

- **rhino3dm 파이썬**: `mcneel.github.io/rhino3dm/python/api/{ClassName}.html`
  (예: Point3d.html, File3dm.html), 전체 색인 genindex.html.
  확인 시점 문서 버전 8.17.0 (PyPI 배포 8.32.1과 갭 있음 — 버전 민감 사항은
  주의).

## 공식 예제 코드 찾기

https://github.com/mcneel/rhino-developer-samples (실측 폴더 지도):
최상위 SDK별 폴더 cpp / grasshopper(cs·py·vb) / opennurbs(cpp·cs) /
rhinocommon(cs·py·vb) / rhino3dm(cs·py·js) / compute(cs·py·js) /
rhino.inside / rhinomobile / rhinopython / rhinoscript / zoo.
브랜치가 Rhino 버전에 대응(master=작업중, '7'=Rhino 7).
rhino3dm 파이썬 샘플 직행: /tree/8/rhino3dm/py (PyPI 페이지가 공식 링크).

## 포럼(discourse.mcneel.com)

- 개별 토픽 페이지(/t/{slug}/{id})는 직접 fetch 정상 동작 실측.
- /search 엔드포인트는 봇차단 추정 플레이스홀더만 반환(실측) —
  검색은 WebSearch `site:discourse.mcneel.com {키워드}` 로 해라.

## 생태계 지도 (자동화·AI 연동, 2026-08-25 실재검증)

전부 코드 도입 전 INTAKE 격리검수 필수. 상세는 메모리
rhino-gh-skill-survey 참조.

- mcneel/RhinoMCP — 제작사 공식 MCP 서버(MIT). Claude Code 전용 설정문서:
  https://mcneel.github.io/RhinoMCP/docs/getting-started/cc-plugin/
  macOS 지원은 공식 문서 미명시(비공식 요약만) — 도입 전 실측 1회.
- jingcheng-chen/rhinomcp — 커뮤니티 최대(약 1,000★). TCP 127.0.0.1:1999
  브릿지 + RhinoScript/RhinoCommon 실행.
- alfredatnycu/grasshopper-mcp — GH 특화, 컴포넌트 지식베이스 JSON.
- gramaziokohler/lamcp — Claude Code 명시 타겟, 라이브 GH 세션
  조작(캔버스 조회·배선·슬라이더). 릴리즈에 Lamcp_Bridge.ghuser.
- enmerk4r/GHPT — 텍스트→GH 정의 생성 원조(JSON 스키마).
- .gh/.ghx 포맷: GH_IO.dll이 담당
  (https://wiki.mcneel.com/labs/grasshopper_fileformat),
  변환기 Metallbau-Windeck/gh2ghx-converter.
- 대형 플러그인 코드 사례: ladybug-tools 생태계(⚠️ AGPL-3.0),
  compas-dev/compas.

## 한계 재확인

- Rhino.Compute·Rhino.Inside = Windows/Linux 전용(공식 FAQ) — 맥 헤드리스
  경로 없음. 헤드리스가 필요하면 Windows 머신에서 compute.rhino3d
  (개인 PC 무료, 서버는 Core-Hour 과금,
  https://developer.rhino3d.com/guides/compute/compute-faq/ ).

## 자동화 연결 런북 (RhinoMCP, 2026-08-25 격리검수 완료)

상태: mcneel/RhinoMCP commit b0e3f486eb9ce8590cc06fd7e8585d06216ccd33 을
`~/.claude/skill-intake/rhinomcp` 에 격리검수(INTAKE) 후 봉인
(tree f54da98d41840d55). 기계검증 청정(HIGH 0)·정독 완료·MIT·무텔레메트리
(PRIVACY.md 명시). **활성화 안 함** — 이 맥에 Rhino 미설치.

정독으로 확정한 사실:
- macOS 지원은 소스 레벨 확정: 런처가 osx-arm64 rid 명시, 맥 전용 테스트
  (MacSharedProcessTests) 존재, yak 경로 /Applications/Rhino 8.app 탐색.
- 구조: Claude Code ←stdio→ node router-launcher.mjs ←spawn→
  rhino-mcp-router(yak 패키지 내 바이너리) ←→ Rhino 플러그인(루프백
  localhost 포트, Kestrel ListenLocalhost). 외부 네트워크 콜 없음.
- run_python/run_csharp/run_command = 설계상 임의코드 실행 도구 —
  로컬 Rhino 프로세스 안. PRIVACY.md가 정직하게 고지.
- GH solve 메커니즘 확정: 실행 중인 Rhino 안 플러그인이 GH1/GH2 캔버스를
  직접 조작(place/connect/slider/solve 툴군) — Compute 불필요.

활성화 절차 (라이노 설치 뒤, 사람게이트):
1. Rhino 8 설치+라이선스 (macOS 12.4+).
2. Rhino 패키지관리자(yak)에서 Rhino-MCP-Platform 설치.
3. Rhino에서 MCPConnect 실행 → Install 탭에서 Claude Code 선택
   (~/.claude.json에 rhino 엔트리 기록 — 멱등·기존항목 불덮어쓰기 확인됨).
   대안: Claude Code에서 /plugin marketplace add mcneel/RhinoMCP →
   /plugin install mcneel@rhino-mcp.
4. 실측 1회: list_objects 호출 응답으로 연결 확인.

함정:
- 레포 클론에서 cc-plugin 직설치 시 router-launcher.mjs가 cc-plugin/ 안에
  없다(패키징 때 shared/ 에서 스테이징) — 로컬 설치는 shared/router-launcher.mjs
  복사 선행. 봉인본 수정 시 재정독+재봉인 필요.
- 레포가 봉인 커밋보다 앞서가면 갱신분은 재INTAKE.
