"""canvas2gh.py — 옵시디언 캔버스(.canvas)를 Grasshopper/Rhino 작업 산출물로 컴파일 (rhino-gh 스킬용 v1).

topogen canvas2spec (v2.162) 의 문법·규율 이식판: 노드 = 컴포넌트, 엣지 = 와이어. 이 환경엔
Rhino 가 없으므로 "실행" = **산출물 생성**이다 — ①작업명세서(.md, LLM 구현 패스용) ②스캐폴드
코드(GHPython SDK-Mode .py / C# .gha 골격 .cs / Rhino 단독 .py). 로직 본문은 명세서를 Claude 에
넘겨 rhino-gh 스킬로 구현한다 ("이 명세 구현해줘"). 캔버스 텍스트는 데이터로만 — eval 없음.

스킬 규율 준수:
· C# 파라미터 등록 메서드(AddXxxParameter)는 references/ 에 시그니처가 없는 것을 추정 생성하지
  않는다 — TODO 주석 + lookup.md 실조회 포인터로 남긴다 (G4).
· ComponentGuid 는 uuid4 로 **신규 생성** (복사·수동편집 금지 규율의 이행 — 예시값 재사용 아님).
· 파이썬 입력 이름의 예약어/내장명 충돌(dir, filter, str …)은 컴파일 에러로 차단 (공식 가이드 함정).
· 생성 코드는 전부 "미실행" 표기 — 사용자 머신 검증 포인트 동봉.

노드 문법 (첫 줄 = #타입 단독 · 키는 다음 줄부터 '키: 값' · 장식 카드는 '# ' 또는 # 없이):
  #GH작업   이름: div_curve (파일명 안전 문자) · 형태: script|gha|rhino · 설명(선택) ·
            카테고리/서브카테고리(gha 용, 기본 Extra/Custom)
  #입력     이름: crv · 타입: Curve · 접근: item|list|tree (기본 item) · 기본값(선택) · 설명(선택)
  #출력     이름: pts · 타입(선택) · 설명(선택)
  #로직     (둘째 줄부터 자유 텍스트 — 무엇을 계산할지. 여러 노드면 캔버스 y 순서)
  #환경     rhino: 8 · 언어: python3 (기본)
  #산출     폴더: ~/RhinoScripts (기본) · 파일(선택, 기본 이름.py/.cs)
배선: 전 컴포넌트 → #GH작업. 입·출력 순서 = 캔버스 y 좌표 (위→아래). 동일쌍 중복 엣지는 접는다.

실행: python3 canvas2gh.py <경로.canvas> [--task 이름] [--write-back]
      python3 canvas2gh.py --selftest        # 내장 예제 컴파일 + 생성 py 문법검사"""
import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

_FREE_TEXT = {"#로직"}                          # 둘째 줄부터 자유 텍스트인 타입
_KEYS = {"#GH작업": {"이름", "형태", "설명", "카테고리", "서브카테고리"},
         "#입력": {"이름", "타입", "접근", "기본값", "설명"},
         "#출력": {"이름", "타입", "설명"},
         "#로직": None, "#환경": {"rhino", "언어"},
         "#산출": {"폴더", "파일"}, "#결과": None}
_KNOWN = set(_KEYS)
_PY_RESERVED = {"and", "as", "assert", "async", "await", "break", "class", "continue", "def",
                "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
                "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
                "return", "try", "while", "with", "yield",
                # 내장명 충돌 대표 (공식 가이드 경고: dir, filter, str 등)
                "dir", "filter", "str", "list", "dict", "set", "type", "id", "input", "print",
                "len", "min", "max", "sum", "range", "object", "out"}


def _parse_node(text: str):
    lines = [ln.strip() for ln in text.strip().splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines or not lines[0].startswith("#") or lines[0].startswith("# "):
        return None, {}
    head = lines[0].split()
    typ = head[0]
    if typ not in _KNOWN:
        raise ValueError(f"모르는 노드 타입 {typ!r} — 지원: {sorted(_KNOWN)} · 장식 카드는 "
                         "'# '(공백) 또는 # 없이 시작")
    if typ == "#결과":
        return None, {}
    if typ in _FREE_TEXT:
        return typ, {"본문": "\n".join(lines[1:])}
    if len(head) > 1:
        raise ValueError(f"{typ} 첫 줄에 내용이 더 있다: {lines[0]!r} — 첫 줄은 #타입 단독")
    kv = {}
    for ln in lines[1:]:
        ln = ln.replace("：", ":")
        if ":" not in ln:
            raise ValueError(f"{typ} 줄 해석 불가: {ln!r} — '키: 값' 형식")
        k, v = ln.split(":", 1)
        k = k.strip()
        if _KEYS[typ] is not None and k not in _KEYS[typ]:
            raise ValueError(f"{typ} 미지 키 {k!r} — 허용: {sorted(_KEYS[typ])}")
        if k in kv:
            raise ValueError(f"{typ} 중복 키 {k!r}")
        kv[k] = v.strip()
    return typ, kv


def compile_canvas(canvas: dict, task_name: str | None = None):
    nodes = {n["id"]: n for n in canvas.get("nodes", []) if n.get("type") == "text"}
    parsed, errs = {}, []
    for nid, n in nodes.items():
        try:
            typ, kv = _parse_node(n.get("text", ""))
        except ValueError as e:
            errs.append(str(e))
            continue
        if typ is not None:
            parsed[nid] = (typ, kv, n.get("y", 0))
    into = {}
    for e in canvas.get("edges", []):
        lst = into.setdefault(e["toNode"], [])
        if e["fromNode"] not in lst:
            lst.append(e["fromNode"])
    tasks = {nid: kv for nid, (typ, kv, _y) in parsed.items() if typ == "#GH작업"}
    if not tasks:
        raise ValueError("컴파일 실패:\n  - " + "\n  - ".join(errs + ["#GH작업 노드 필요"]))
    if task_name is not None:
        sel = [nid for nid, kv in tasks.items() if kv.get("이름") == task_name]
        if not sel:
            raise ValueError(f"작업 {task_name!r} 없음 — 캔버스: {[kv.get('이름') for kv in tasks.values()]}")
        tid = sel[0]
    elif len(tasks) == 1:
        tid = next(iter(tasks))
    else:
        raise ValueError(f"작업이 여럿 — --task 지정: {[kv.get('이름') for kv in tasks.values()]}")
    tk = tasks[tid]
    members = [nid for nid in into.get(tid, []) if nid in parsed]
    spec = {"이름": tk.get("이름", ""), "형태": tk.get("형태", ""), "설명": tk.get("설명", ""),
            "카테고리": tk.get("카테고리", "Extra"), "서브카테고리": tk.get("서브카테고리", "Custom"),
            "입력": [], "출력": [], "로직": [], "환경": {"rhino": "8", "언어": "python3"},
            "산출": {"폴더": "~/RhinoScripts", "파일": None}}
    if not re.fullmatch(r"[A-Za-z0-9_\-가-힣]+", spec["이름"] or ""):
        errs.append(f"#GH작업 이름 {spec['이름']!r} — 파일명 안전 문자 필요")
    if spec["형태"] not in ("script", "gha", "rhino"):
        errs.append(f"#GH작업 형태 {spec['형태']!r} — script|gha|rhino")
    by_y = sorted(members, key=lambda nid: parsed[nid][2])       # 캔버스 y 순서 (위→아래)
    for nid in by_y:
        typ, kv, _y = parsed[nid]
        if typ == "#입력":
            nm = kv.get("이름", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nm):
                errs.append(f"#입력 이름 {nm!r} — 파이썬 식별자 필요")
            elif nm in _PY_RESERVED:
                errs.append(f"#입력 이름 {nm!r} — 예약어/내장명 충돌 (공식 가이드 경고: 컴포넌트가 깨진다)")
            if "타입" not in kv:
                errs.append(f"#입력 {nm}: 타입 필요")
            acc = kv.get("접근", "item")
            if acc not in ("item", "list", "tree"):
                errs.append(f"#입력 {nm}: 접근 {acc!r} — item|list|tree")
            spec["입력"].append({"이름": nm, "타입": kv.get("타입", ""), "접근": acc,
                                 "기본값": kv.get("기본값"), "설명": kv.get("설명", "")})
        elif typ == "#출력":
            nm = kv.get("이름", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nm) or nm in _PY_RESERVED:
                errs.append(f"#출력 이름 {nm!r} — 파이썬 식별자·비예약어 필요")
            spec["출력"].append({"이름": nm, "타입": kv.get("타입", ""), "설명": kv.get("설명", "")})
        elif typ == "#로직":
            if kv.get("본문", "").strip():
                spec["로직"].append(kv["본문"].strip())
        elif typ == "#환경":
            spec["환경"].update({k: str(v) for k, v in kv.items()})
        elif typ == "#산출":
            if "폴더" in kv:
                spec["산출"]["폴더"] = kv["폴더"]
            if "파일" in kv:
                spec["산출"]["파일"] = kv["파일"]
    dup = [n for n in [i["이름"] for i in spec["입력"]] + [o["이름"] for o in spec["출력"]]
           if ([i["이름"] for i in spec["입력"]] + [o["이름"] for o in spec["출력"]]).count(n) > 1]
    if dup:
        errs.append(f"입·출력 이름 중복: {sorted(set(dup))}")
    if spec["형태"] in ("script", "gha") and not spec["입력"] and not spec["출력"]:
        errs.append("입력/출력이 전부 없다 — 컴포넌트 형태(script/gha)엔 최소 1개")
    if not spec["로직"]:
        errs.append("#로직 노드 필요 (무엇을 계산할지 자유 텍스트)")
    if errs:
        raise ValueError("컴파일 실패 (주황 컴포넌트 목록):\n  - " + "\n  - ".join(errs))
    return spec, tid


def _gen_script_py(spec):
    """GHPython SDK-Mode 골격 (references/gh-dev.md 검증 스켈레톤 기반). 타입힌트는 GH 쪽
    Parameter Type Hints 가 정본(UI 우클릭 지정 — 레퍼런스 명시)이라 주석으로 안내만 한다."""
    ins = ", ".join(i["이름"] for i in spec["입력"])
    outs = [o["이름"] for o in spec["출력"]]
    lines = [f"# {spec['이름']} — GH Script 컴포넌트 (SDK-Mode, Rhino {spec['환경']['rhino']} / Python 3)",
             "# 생성: canvas2gh v1 · ⚠️ 미실행 — 사용자 머신(GH ZUI 입출력·Type Hints 지정) 검증 필요",
             "# 입력 (캔버스 정의 — GH 접근모드/Type Hint 는 입력 우클릭으로 맞춰라):"]
    for i in spec["입력"]:
        d = f" · 기본값 {i['기본값']}" if i.get("기본값") else ""
        lines.append(f"#   {i['이름']}: {i['타입']} ({i['접근']}){d} — {i['설명']}")
    lines.append("# 출력: " + ", ".join(f"{o['이름']}({o['타입']})" for o in spec["출력"]))
    lines += ["import Rhino", "import Grasshopper", "", "",
              f"class {spec['이름']}_Component(Grasshopper.Kernel.GH_ScriptInstance):",
              f"    def RunScript(self, {ins}):"]
    for k, lg in enumerate(spec["로직"], 1):
        lines.append(f"        # TODO 로직 {k}: " + " / ".join(lg.splitlines()))
    lines += [f"        {o} = None  # TODO" for o in outs]
    lines.append(f"        return {', '.join(outs) if outs else 'None'}")
    return "\n".join(lines) + "\n"


def _gen_rhino_py(spec):
    lines = [f"# {spec['이름']} — Rhino {spec['환경']['rhino']} 단독 스크립트 (ScriptEditor/Python 3)",
             "# 생성: canvas2gh v1 · ⚠️ 미실행 — 사용자 머신 검증 필요",
             "import rhinoscriptsyntax as rs", ""]
    for k, lg in enumerate(spec["로직"], 1):
        lines.append(f"# TODO 로직 {k}: " + " / ".join(lg.splitlines()))
    lines.append("")
    return "\n".join(lines) + "\n"


def _gen_gha_cs(spec):
    """C# GH_Component 골격 (references/gh-dev.md 튜토리얼 스켈레톤). 파라미터 등록 메서드
    시그니처는 레퍼런스 밖이라 **추정 생성하지 않는다** — lookup 포인터 TODO."""
    gid = str(uuid.uuid4())                     # 신규 생성 (복사 금지 규율 이행)
    nm = spec["이름"]
    L = [f"// {nm} — GH_Component 골격 (Rhino {spec['환경']['rhino']}) · canvas2gh v1 · ⚠️ 미컴파일",
         "// 파라미터 등록: AddXxxParameter 시그니처는 references/lookup.md 로 실조회 후 작성 (추정 금지)",
         "using System;", "using Grasshopper.Kernel;", "",
         f"public class {nm}Component : GH_Component",
         "{",
         f"    public {nm}Component() : base(\"{nm}\", \"{nm[:4].upper()}\", "
         f"\"{spec['설명'] or nm}\", \"{spec['카테고리']}\", \"{spec['서브카테고리']}\")",
         "    {", "    }", "",
         "    protected override void RegisterInputParams(GH_Component.GH_InputParamManager pManager)",
         "    {"]
    for i in spec["입력"]:
        L.append(f"        // TODO: {i['이름']} ({i['타입']}, {i['접근']}) — pManager.Add…Parameter 실조회")
    L += ["    }", "",
          "    protected override void RegisterOutputParams(GH_Component.GH_OutputParamManager pManager)",
          "    {"]
    for o in spec["출력"]:
        L.append(f"        // TODO: {o['이름']} ({o['타입']})")
    L += ["    }", "",
          "    protected override void SolveInstance(IGH_DataAccess DA)",
          "    {"]
    for k, lg in enumerate(spec["로직"], 1):
        L.append(f"        // TODO 로직 {k}: " + " / ".join(lg.splitlines()))
    L += ["    }", "",
          "    public override Guid ComponentGuid",
          "    {",
          f"        get {{ return new Guid(\"{gid}\"); }}   // uuid4 신규 생성 — 재사용 금지",
          "    }", "}"]
    return "\n".join(L) + "\n"


def _gen_spec_md(spec, files):
    L = [f"# GH 작업명세 — {spec['이름']} ({spec['형태']})",
         "", f"{spec['설명'] or ''}", "",
         f"- 환경: Rhino {spec['환경']['rhino']} · {spec['환경']['언어']}",
         f"- 스캐폴드: {files}", "", "## 입력", ""]
    for i in spec["입력"]:
        L.append(f"- `{i['이름']}` : {i['타입']} · 접근 {i['접근']}"
                 + (f" · 기본값 {i['기본값']}" if i.get("기본값") else "") + f" — {i['설명']}")
    L += ["", "## 출력", ""]
    for o in spec["출력"]:
        L.append(f"- `{o['이름']}` : {o['타입']} — {o['설명']}")
    L += ["", "## 로직 (구현 지시)", ""]
    for k, lg in enumerate(spec["로직"], 1):
        L.append(f"{k}. {lg}")
    L += ["", "> Claude 에 이 파일을 주고 \"이 명세 구현해줘\" — rhino-gh 스킬이 스캐폴드의 TODO 를",
          "> 채운다 (API 시그니처는 references/ 실조회, 미실행 표기 유지).", ""]
    return "\n".join(L)


def write_back(canvas_path: Path, task_id: str, summary: str):
    c = json.loads(canvas_path.read_text())
    ts = next(n for n in c["nodes"] if n["id"] == task_id)
    rid = f"result_{task_id}"
    ex = [n for n in c["nodes"] if n.get("id") == rid]
    if ex:
        ex[0]["text"] = f"#결과\n{summary}"
    else:
        c["nodes"].append({"id": rid, "type": "text", "text": f"#결과\n{summary}",
                           "x": ts["x"] + ts.get("width", 260) + 60, "y": ts["y"],
                           "width": 420, "height": 180, "color": "4"})
        c.setdefault("edges", []).append({"id": f"e_{rid}", "fromNode": task_id,
                                          "fromSide": "right", "toNode": rid, "toSide": "left"})
    fd, tmp = tempfile.mkstemp(dir=str(canvas_path.parent), suffix=".canvas.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(c, ensure_ascii=False, indent=1))
        os.replace(tmp, canvas_path)
    except BaseException:
        try:
            os.unlink(tmp)
        finally:
            raise


_EXAMPLE = {"nodes": [
    {"id": "t", "type": "text", "x": 400, "y": 100, "width": 280, "height": 140,
     "text": "#GH작업\n이름: div_curve\n형태: script\n설명: 곡선 등분점"},
    {"id": "i1", "type": "text", "x": 0, "y": 0, "width": 260, "height": 140,
     "text": "#입력\n이름: crv\n타입: Curve\n접근: item\n설명: 대상 곡선"},
    {"id": "i2", "type": "text", "x": 0, "y": 160, "width": 260, "height": 140,
     "text": "#입력\n이름: n\n타입: int\n기본값: 10\n설명: 분할 수"},
    {"id": "o1", "type": "text", "x": 0, "y": 320, "width": 260, "height": 120,
     "text": "#출력\n이름: pts\n타입: Point3d[]\n설명: 등분점"},
    {"id": "lg", "type": "text", "x": 0, "y": 460, "width": 300, "height": 140,
     "text": "#로직\ncrv 를 n 등분한 파라미터에서 점을 뽑아 pts 로 반환.\n곡선이 None 이면 빈 리스트."}],
    "edges": [{"id": "e1", "fromNode": "i1", "toNode": "t"}, {"id": "e2", "fromNode": "i2", "toNode": "t"},
              {"id": "e3", "fromNode": "o1", "toNode": "t"}, {"id": "e4", "fromNode": "lg", "toNode": "t"}]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("canvas", nargs="?", help=".canvas 경로")
    ap.add_argument("--task", default=None)
    ap.add_argument("--write-back", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="내장 예제 컴파일 + 생성 py 문법검사")
    a = ap.parse_args()
    if a.selftest:
        import py_compile
        spec, _ = compile_canvas(_EXAMPLE)
        assert spec["입력"][0]["이름"] == "crv" and spec["입력"][1]["기본값"] == "10"
        py = _gen_script_py(spec)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(py); tmp = f.name
        py_compile.compile(tmp, doraise=True); os.unlink(tmp)
        cs = _gen_gha_cs(dict(spec, 형태="gha"))
        assert "GH_Component" in cs and "RegisterInputParams" in cs
        try:                                     # 예약어 입력 차단 확인
            bad = json.loads(json.dumps(_EXAMPLE))
            bad["nodes"][1]["text"] = "#입력\n이름: filter\n타입: Curve"
            compile_canvas(bad)
            raise AssertionError("예약어 미차단")
        except ValueError as e:
            assert "예약어" in str(e)
        print("selftest PASS — 컴파일·py 문법·C# 골격·예약어 차단")
        return 0
    if not a.canvas:
        ap.error("canvas 경로 또는 --selftest")
    cpath = Path(a.canvas).expanduser()
    spec, tid = compile_canvas(json.loads(cpath.read_text()), a.task)
    outdir = Path(spec["산출"]["폴더"]).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    ext = ".cs" if spec["형태"] == "gha" else ".py"
    code_p = outdir / (spec["산출"]["파일"] or f"{spec['이름']}{ext}")
    gen = {"script": _gen_script_py, "rhino": _gen_rhino_py, "gha": _gen_gha_cs}[spec["형태"]]
    code_p.write_text(gen(spec))
    spec_p = outdir / f"{spec['이름']}_ghspec.md"
    spec_p.write_text(_gen_spec_md(spec, str(code_p)))
    print(f"[{spec['이름']}] 컴파일 OK → 스캐폴드 {code_p} · 명세 {spec_p}")
    print("다음 수: Claude 에 명세 파일을 주고 \"이 명세 구현해줘\" (rhino-gh 스킬이 TODO 를 채운다)")
    if a.write_back:
        write_back(cpath, tid, f"작업: {spec['이름']} ({spec['형태']})\n스캐폴드: {code_p}\n명세: {spec_p}\n"
                               "다음 수: 명세를 Claude 에 넘겨 로직 구현")
        print(f"캔버스 회신 완료 → {cpath.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
