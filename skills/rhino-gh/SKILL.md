---
name: rhino-gh
description: >-
  Rhino 3D · Grasshopper 개발 지식스킬 — Rhino 8 스크립팅(Python 3/C#), Grasshopper
  컴포넌트 개발(C# .gha), Script 컴포넌트(Script-Mode/SDK-Mode), 데이터 트리, rhino3dm,
  rhinocode CLI, Yak 패키징 코드 작성·디버깅·안내. "라이노 스크립트", "그래스호퍼 컴포넌트",
  "GHPython", "RhinoCommon", "rhino3dm", "gh 파일", ".gha", "데이터 트리",
  "Grasshopper 자동화" 질의 시 호출. 지식·코드 생성 전용 — 이 환경에 Rhino가 없으므로
  실행 검증은 못 하고, 사용자 머신에서 돌릴 코드를 만든다. SolidWorks/NX/AutoCAD는 범위 밖
  (SolidWorks는 solidworks-addin 스킬).
---

# Rhino / Grasshopper 개발 (지식형 v1.0)

Rhino 8 기준. 이 스킬의 모든 API 명칭·코드 패턴은 2026-08-25 공식 문서
실조회로 확보한 것이며, 각 항목에 출처 URL이 붙어 있다.

## 정신모형 — 라이브러리 지도

```
Rhino 앱 (Win/Mac)
 ├─ RhinoCommon (.NET SDK) ← Rhino 안에서만 실행, 전체 기능
 │    └─ rhinoscriptsyntax ← RhinoCommon 위의 고수준 파이썬 래퍼
 ├─ Grasshopper (.NET/RhinoCommon 플러그인)
 │    ├─ C# .gha 플러그인 (GH_Component 상속)
 │    └─ Script 컴포넌트 (Python 3 / C#, 캔버스 안)
 └─ ScriptEditor + rhinocode CLI (Rhino 8, Python 3 = CPython 3.9.11)

Rhino 밖 (독립 실행)
 └─ rhino3dm (py/js/.NET, MIT) ← 지오메트리·.3dm 입출력만, GH solve 불가
```

- Grasshopper 정의(.gh) 계산(solve)은 Rhino/Grasshopper 프로세스가 필요하다.
  rhino3dm 단독으로는 안 된다 (README에 solve 기능 언급 자체가 없음,
  https://github.com/mcneel/rhino3dm).
- .gh(바이너리)/.ghx(XML) 파일은 GH_IO.dll이 읽고 쓴다
  (https://wiki.mcneel.com/labs/grasshopper_fileformat).

## 실행경로 — 플랫폼 제약 (사용자에게 선제 고지)

- **macOS 헤드리스 불가**: Rhino.Compute·Rhino.Inside는 Windows/Linux 전용
  (공식 FAQ 직접인용 "only compatible with Windows and Linux",
  https://developer.rhino3d.com/guides/compute/compute-faq/).
  맥에서 자동화는 Rhino 8 앱을 켠 상태에서 rhinocode CLI 또는 MCP 브릿지 경유.
- Rhino 8은 macOS 12.4+ 지원 (https://www.rhino3d.com/8/system-requirements/).
- Rhino 8 Python = CPython 3.9.11 (Win/Mac). Rhino 7 = IronPython 2.7.12
  (Windows 전용) (https://developer.rhino3d.com/guides/rhinopython/what-is-rhinopython/).
  Rhino 8도 두 런타임을 병행 배포한다(~/.rhinocode/py39-rh8/, py27-rh8/).
- Rhino 설치·라이선스가 전제다. 이 환경에서는 실행 검증 불가 —
  코드는 사용자 머신에서 돌린다는 걸 명시해라.

## 핵심 규율 (위반 금지)

1. **API 시그니처는 기억으로 짓지 마라.** 이 스킬 references/ 에 출처와 함께
   실린 명칭·시그니처만 그대로 써도 된다. 그 밖의 클래스/메서드/열거형은
   `references/lookup.md` 레시피로 실조회 후 인용하고, 조회 못 하면
   카테고리만 말하고 확인 경로를 안내해라. 열거형 멤버 추정생성 절대 금지.
2. **버전 명시.** Rhino 7(IronPython)과 Rhino 8(Python 3) 답이 갈리는 지점은
   반드시 버전을 물어보거나 양쪽을 갈라서 답해라.
3. **요약경유 표시 존중.** references/ 에서 "요약경유" 딱지가 붙은 스니펫은
   문자단위 정밀도가 필요할 때(파서 작성 등) 원문 재조회 후 사용.
4. **외부 레포 코드 도입은 INTAKE.** references/lookup.md 의 생태계 레포에서
   코드를 가져오려면 skill-intake 격리검수를 먼저 태워라.

## 캔버스 진입로 (v1.1 — 옵시디언 노코드)

`~/SecondBrain/GH-Palette.canvas` 에서 노드를 배선하면
`scripts/canvas2gh.py` 가 스캐폴드(.py/.cs)+작업명세(.md)를 `~/RhinoScripts` 에
생성한다 (`--write-back` 은 #결과 노드 회신 · `--selftest` 자체검증). 사용자가
명세를 주며 "이 명세 구현해줘" 하면 이 스킬 규율(레퍼런스 실조회·미실행 표기)
그대로 스캐폴드의 TODO 로직을 채워라. 팔레트 원본은
`references/gh-palette-template.canvas`.

## 작업 흐름

1. **분류** — 스크립팅(에디터/CLI) / Script 컴포넌트 / .gha 플러그인 /
   독립 rhino3dm / 파일포맷(.gh 파싱) / 자동화(MCP) 중 어디인지.
2. **레퍼런스 로드** — 해당하는 references/ 파일 하나만 읽어라:
   - `references/scripting.md` — Rhino 8 ScriptEditor·Python 환경·패키지
     지시자·rhinocode CLI.
   - `references/gh-dev.md` — GH_Component 구조·Script 컴포넌트(C#/Py)·
     데이터 트리·Yak 패키징·rhino3dm 사용.
   - `references/lookup.md` — API 문서 URL 패턴·공식 샘플 레포 지도·
     포럼 검색법·생태계(MCP 등) 레포.
3. **코드 생성** — references/ 의 검증된 골격에서 출발해 변형. 새 API가
   필요하면 조회 먼저.
4. **미검증 명시** — 실행 못 해본 코드는 "미실행"을 밝히고, 사용자 쪽
   확인 포인트(단위, 버전, null 처리)를 짚어줘라.

## 함정 (선제 경고)

- Script 컴포넌트 입력 변수명이 파이썬 예약어·내장명(dir, filter, str 등)과
  충돌하면 깨진다 — 공식 가이드가 경고하는 사항
  (https://developer.rhino3d.com/guides/scripting/scripting-gh-python/).
- 컴포넌트 ComponentGuid는 절대 복사·수동편집 금지, 새로 생성
  (https://developer.rhino3d.com/guides/grasshopper/simple-component/).
- Rhino의 파이썬 venv는 진짜 격리가 아니다 — 같은 프로세스·인터프리터 상태
  공유, 재설치 방지 용도 (https://developer.rhino3d.com/guides/scripting/advanced-pyvenvs/).
- 데이터 트리 path는 희소(sparse)할 수 있다 — 연속 인덱스 가정 금지
  (https://developer.rhino3d.com/guides/rhinopython/grasshopper-datatrees-and-python/).
- 공식 가이드 트리가 신구 혼재다: /guides/scripting/(신, Rhino 8)과
  /guides/rhinopython/(구)이 같이 라이브 상태. 신규 트리에 다수 페이지가
  'Coming Soon' — 구 트리 내용을 Rhino 8에 적용할 땐 버전 재확인.
