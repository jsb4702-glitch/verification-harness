# Grasshopper 개발 (컴포넌트 · Script 컴포넌트 · 데이터 트리 · 배포)

수록 내용 전부 2026-08-25 공식 문서 실조회 발췌. "요약경유" 표시는
WebFetch 요약모델을 거친 것 — 문자단위 정밀도 필요 시 출처 재조회.

## C# .gha 플러그인 — GH_Component 구조

SDK 문서 직접 조회로 확정 (출처:
https://developer.rhino3d.com/api/grasshopper/html/T_Grasshopper_Kernel_GH_Component.htm ):

- `GH_Component` = `Grasshopper.Kernel` 네임스페이스의 추상 기반클래스.
  `GH_ActiveObject` 상속, `IGH_Component`·`IGH_RenderAwareObject` 구현.
- 오버라이드 대상: `RegisterInputParams()` / `RegisterOutputParams()` /
  `SolveInstance()`. 라이프사이클 훅: `BeforeSolveInstance()` /
  `AfterSolveInstance()` / `PostConstructor()`.
- base 생성자를 호출하는 public 빈 생성자 필수(문서 명시 취지).
- 속성: Params, InConstructor, Message, RunCount.

튜토리얼 골격 (출처:
https://developer.rhino3d.com/guides/grasshopper/your-first-component-windows/ ,
https://developer.rhino3d.com/guides/grasshopper/simple-component/ — 요약경유,
인용부호 안 명칭은 원문):

```csharp
public class HelloGrasshopperComponent : GH_Component
{
    // base(컴포넌트명, 축약명, 설명, 카테고리, 서브카테고리)
    public MyFirstComponent() : base("MyFirst", "MFC", "My first component", "Extra", "Simple")
    {
    }

    protected override void RegisterInputParams(GH_Component.GH_InputParamManager pManager)
    {
        // 예: pManager.AddTextParameter(...) / 
        // pManager.AddPlaneParameter("Plane", "P", "Base plane for spiral", GH_ParamAccess.item, Plane.WorldYZ);
    }

    protected override void RegisterOutputParams(GH_Component.GH_OutputParamManager pManager)
    {
    }

    protected override void SolveInstance(IGH_DataAccess DA)
    {
        string data = null;
        if (!DA.GetData(0, ref data)) { return; }
        if (data == null || data.Length == 0) { return; }

        char[] chars = data.ToCharArray();
        System.Array.Reverse(chars);
        DA.SetData(0, new string(chars));
    }

    public override Guid ComponentGuid
    {
        get { return new Guid("419c3a3a-cc48-4717-8cef-5f5647a5ecfc"); }
    }
}
```

- ComponentGuid는 온라인 생성기나 guidgen.exe로 새로 생성 — 복사·수동편집
  절대 금지(공식 안내). 위 GUID는 튜토리얼 예시값이니 그대로 쓰지 마라.
- 프로젝트 타입은 Class Library, 참조 어셈블리에 RhinoCommon.dll·GH_IO.dll·
  GH_Util.dll (출처:
  https://developer.rhino3d.com/guides/grasshopper/what-is-a-grasshopper-component/ ).
- 툴체인(공식 페이지가 Rhino 7 시대 표기 — 버전 드리프트 주의):
  Visual Studio 2022 Community 권장, VS Code 미지원 명시, '.NET desktop
  development' 워크로드, Marketplace에서 'RhinoCommon' 템플릿 설치,
  템플릿명 'Grasshopper Assembly for Rhino (C#)' (출처:
  https://developer.rhino3d.com/guides/grasshopper/installing-tools-windows/ ).
- 컴파일→.gha 생성 자체의 공식 서술은 이번 조회에서 미확인 — 빌드 산출물
  확장자 처리 방식은 답하기 전에 조회해라.

## Script 컴포넌트 (캔버스 안, C#/Python)

- 생성: Maths 탭 Script 패널에서 드래그. 언어는 Python 3(기본 지정 가능)/C#.
  줌인(ZUI) 시 입출력 파라미터 추가/제거 컨트롤 노출. 입력 우클릭 >
  Type Hints. (출처: https://developer.rhino3d.com/guides/scripting/scripting-component/ )
- Python은 Script-Mode(입출력 자동 정의, 기본 x,y → out,a)와
  SDK-Mode(클래스 작성) 두 방식 (출처:
  https://developer.rhino3d.com/guides/scripting/scripting-gh-python/ ):

```python
class MyComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, x: int, y: Rhino.Geometry.Plane):
        a = x + 10
        return a
```

- `print()` 출력 각 줄이 out 파라미터 항목이 된다. 접근모드 Item/List/Tree.
  필수 입력(Required Inputs)은 Rhino 8.14+.
- rhinoscriptsyntax는 관례상 `rs`로 import, ghdoc 타입힌트 입력과
  문서요소 marshalling이 자동으로 붙는다. Python 3 타입힌트는 정적분석용 —
  Grasshopper Parameter Type Hints와 별개.
- C# Script 컴포넌트: RunScript 시그니처에 접근모드가 반영된다 (출처:
  https://developer.rhino3d.com/guides/grasshopper/csharp-essentials/1-grasshopper-csharp-component/ —
  요약경유):

```csharp
// Item
private void RunScript( double x, ref object a ) { a = x + 10; }
// List
private void RunScript( List<double> xList, ref object Sum) { /* ... */ }
// Tree
private void RunScript( DataTree<Point3d> ptTree, ref object Spheres) { /* branch 반복 */ }
```

  출력 파라미터는 항상 System.Object, Out 문자열은 컴파일/런타임 메시지용.
  C# 쪽 상속 클래스명 명시 서술은 미확인(파이썬 쪽만 GH_ScriptInstance 확정).

## 데이터 트리

- 트리 = GH_Path 키 + .NET 리스트(branch)의 dict 유사 구조. path는
  희소(sparse) 가능. (출처:
  https://developer.rhino3d.com/guides/rhinopython/grasshopper-datatrees-and-python/ )
- 표기: 경로 {0}, {2;4;6}(중괄호+세미콜론), 항목 인덱스 {2;4;6}[10].
  "path는 음이 아닌 정수 1개 이상의 모음", 첫 요소 인덱스 0. 매핑 4범주
  1:1, 1:N, N:1, N:N. (출처: David Rutten 글,
  https://developer.rhino3d.com/guides/grasshopper/the-why-and-how-of-data-trees/ )

파이썬 순회 (출처 datatrees 페이지, 요약경유):

```python
a = []
for i in range(x.BranchCount):
    branchList = x.Branch(i)
    branchPath = x.Path(i)
    for j in range(branchList.Count):
        s = str(branchPath) + "[" + str(j) + "] "
        s += type(branchList[j]).__name__ + ": "
        s += str(branchList[j])
        a.append(s)
```

중첩리스트 ↔ 트리 변환 (출처 동일, 요약경유):

```python
import ghpythonlib.treehelpers as th
layerTree = th.list_to_tree(layerTree, source=[0,0])
```

## rhino3dm (Rhino 없이 지오메트리)

- MIT, `pip install rhino3dm`. PyPI 최신 8.32.1(릴리스 2026-08-24 표기,
  단일출처). 지원 파이썬 버전이 소스별 상이(README 3.8-3.14 / docs 3.7+ /
  PyPI 3.9-3.14) — 단정하지 말고 PyPI 기준 안내. (출처:
  https://pypi.org/project/rhino3dm/ , https://github.com/mcneel/rhino3dm )
- 기하 생성·조작·.3dm 입출력·Compute 클라이언트 용도. GH solve 불가.

```python
from rhino3dm import *
center = Point3d(1,2,3)
arc = Arc(center, 10, 1)
nc = arc.ToNurbsCurve()
start = nc.PointAtStart
print(start)
```

(출처: https://github.com/mcneel/rhino3dm/blob/8.x/docs/python/RHINO3DM.PY.md —
이 문서에 파일 입출력 예제는 없음이 명시돼 있음)

## Yak 패키징 (.gha 배포)

출처: https://developer.rhino3d.com/guides/yak/creating-a-grasshopper-plugin-package/
(주의: /guides/grasshopper/ 인덱스에 미등재 — 검색으로 찾아야 하는 페이지)

- 배포 폴더에서 중요한 건 .gha와 icon.png 뿐("The only files that matter...").
- `"C:\Program Files\Rhino 8\System\Yak.exe" spec` → manifest.yml 자동생성
  (name/version/authors/description/url/icon/keywords).
- `Yak.exe build` → 예: marmoset-1.0.0-rh6_18-any.yak. distribution tag의
  rh6_18은 참조한 Grasshopper.dll/RhinoCommon.dll 버전에서 자동 추론.
  플랫폼 지정 `--platform win|mac`.
- push(서버 업로드) 명령의 정확한 문법은 미확인 — 답하기 전에 조회해라.
