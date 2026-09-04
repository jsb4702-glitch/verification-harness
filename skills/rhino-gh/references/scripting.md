# Rhino 8 스크립팅 (ScriptEditor · Python 환경 · rhinocode CLI)

수록 내용 전부 2026-08-25 공식 문서 실조회 발췌. "요약경유" 표시는
WebFetch 요약모델을 거친 것 — 문자단위 정밀도 필요 시 출처 재조회.

## ScriptEditor 기본

- 실행: Rhino 명령프롬프트에 `ScriptEditor` 입력.
- 스크립트 실행: Run 버튼 또는 F5, 출력은 하단 Terminal 탭.
- Terminal은 기본이 실행완료 후 일괄 출력(디버깅 시 실시간),
  Line by Line 토글로 일반 실행도 실시간 가능.
- 출처: https://developer.rhino3d.com/guides/scripting/scripting-command/ ,
  https://developer.rhino3d.com/guides/scripting/editor-terminal/

최소 예제 (출처 위 scripting-command 페이지):

```python
print(Rhino.RhinoApp.Version)
```

## Python 런타임 사실관계

- Rhino 8 = CPython **3.9.11** (Windows/Mac). Rhino 7 = IronPython **2.7.12**
  (Windows 전용). 원문 인용 확보됨.
  출처: https://developer.rhino3d.com/guides/rhinopython/what-is-rhinopython/
- Rhino 8은 두 런타임 병행 배포: Python 3 → `~/.rhinocode/py39-rh8/`,
  Python 2 → `~/.rhinocode/py27-rh8/`. 언어 첫 로드 시 일회성 초기화(진행바).
  출처: https://developer.rhino3d.com/guides/scripting/advanced-langinit/
- rhinoscriptsyntax는 RhinoScript 복제 목적의 고수준 래퍼이고, 그 소스는
  "단순히 RhinoCommon을 사용하는 파이썬 스크립트다"(원문 인용).
  RhinoCommon은 저수준 .NET SDK.
  출처: https://developer.rhino3d.com/guides/rhinopython/using-rhinocommon-from-python/

## 패키지·참조 지시자 (Rhino 8 Script)

출처: https://developer.rhino3d.com/guides/scripting/scripting-gh-python/ (표),
https://developer.rhino3d.com/guides/rhinopython/python-packages/

- `# requirements:` 와 `# r:` 는 동등 문법 (PyPI 설치, pip 사용).
  다중 패키지는 같은 줄 나열(예: numpy, scipy).
  ⚠️ `# r:` 공백 유무가 요약 내 혼재 표기 — 문자단위는 출처 재확인.
- `# env:` 모듈 경로 추가.
- `# venv: <name>` 가상환경 지정, 특수값 `# venv: site-packages`.
  기본환경은 site-envs/default-<unique-id>. Rhino venv는 진짜 격리 아님
  (같은 프로세스/인터프리터 상태 공유, 재설치 방지 용도).
  출처: https://developer.rhino3d.com/guides/scripting/advanced-pyvenvs/
- `#r "nuget: ..."` NuGet 참조, `#r "/path/to/..."` DLL 직접 참조.
- `#! python 3` 언어 지정(공유 스크립트에 필수).

예제 (출처 python-packages 페이지, 요약경유):

```python
# r: numpy

import numpy

print(f"using numpy: {numpy.version.full_version}\n")

for i in numpy.random.rand(10):
   print(i)
```

## rhinocode CLI (Rhino >= 8.11)

출처: https://developer.rhino3d.com/guides/scripting/advanced-cli/ (직접 fetch)

- 위치: macOS `/Applications/Rhino 8.app/Contents/Resources/bin` 을 PATH에
  추가(또는 그 폴더에서 `./rhinocode`). Windows `%PROGRAMFILES%\Rhino 8\System`.
- 전제: Rhino 안에서 `StartScriptServer` 명령으로 스크립트 서버를 켜야 한다
  (성능상 자동시작 안 됨). 즉 CLI는 실행 중인 Rhino 인스턴스와 통신한다 —
  Rhino 없이 단독 실행하는 물건이 아니다.
- 하위명령: `list`(실행중 인스턴스 나열), `command`(Rhino 명령 실행),
  `script`(.py/.cs/.py2 실행), `project`(프로젝트 관리/빌드/발행 —
  산출물 .yak/.rhp/.rui/.gha).
- 옵션: `-V/--version`, `-v/--verbose`, `-r/--rhino <ID>`, `-d/--debug`,
  `-t/--trace`. 프로젝트 빌드: `-bv/--buildversion`, `-bt/--buildtarget`,
  `-bp/--buildpath`.
- .gh 파일을 CLI로 직접 실행하는 기능은 이 페이지에 명시돼 있지 않다(미확인).

페이지 게재 예제 명령 (Windows 경로 표기, macOS 예제는 페이지에 없음):

```bash
rhinocode -V
rhinocode --help
rhinocode list --json
rhinocode command "_circle 0 0 0 20"
rhinocode --rhino rhinocode_remotepipe_75029 script C:\path\to\script.py
rhinocode project build C:\path\to\projects\MyTools.rhproj
```

## RhinoCommon을 파이썬에서 직접 쓰기

예제 (출처: https://developer.rhino3d.com/guides/rhinopython/using-rhinocommon-from-python/ ,
구 트리 소속 — Rhino 8 적용 시 동작 재확인):

```python
import Rhino
import System.Drawing

def GetPointDynamicDrawFunc( sender, args ):
  pt1 = Rhino.Geometry.Point3d(0,0,0)
  pt2 = Rhino.Geometry.Point3d(10,10,0)
  args.Display.DrawLine(pt1, args.CurrentPoint, System.Drawing.Color.Red, 2)
  args.Display.DrawLine(pt2, args.CurrentPoint, System.Drawing.Color.Blue, 2)

gp = Rhino.Input.Custom.GetPoint()
gp.DynamicDraw += GetPointDynamicDrawFunc
gp.Get()
```

## 미확인 목록 (답변 시 단정 금지)

- ScriptEditor 매크로·비동기 실행·Publishing 페이지 내용(미조회).
- IronPython "지원 종료" 단정 문구 — 공식 페이지에서 미발견, Rhino 8도
  py27 런타임을 병행 배포하므로 "구식이지만 병행 지원"이 확인 범위.
- 신규 /guides/scripting/ 트리의 다수 페이지가 'Coming Soon' 상태였음
  (2026-08-25 시점) — 재조회 시 채워졌을 수 있다.
