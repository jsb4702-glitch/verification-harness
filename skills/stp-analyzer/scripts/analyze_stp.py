#!/usr/bin/env python3
"""
Multi-format CAD analyzer — STEP, IGES, BREP, STL, OBJ
L1 metadata, L2 geometry, L3 topology, L4 quality.
Outputs a standalone interactive HTML report with embedded Three.js 3D viewer.
"""

import sys
import os
import json
import math
import tempfile
import base64
from pathlib import Path
from datetime import datetime

# Supported extensions
OCP_FORMATS  = {".stp", ".step", ".igs", ".iges", ".brep"}
MESH_FORMATS = {".stl", ".obj"}
ALL_FORMATS  = OCP_FORMATS | MESH_FORMATS


def detect_format(file_path: str) -> str:
    """Return lowercase extension."""
    return Path(file_path).suffix.lower()


# ─────────────────────────────────────────────
# L1 — Metadata
# ─────────────────────────────────────────────

def parse_metadata_mesh(file_path: str) -> dict:
    """Metadata for mesh formats (STL/OBJ) — file stats only."""
    ext = detect_format(file_path)
    stat = os.stat(file_path)
    return {
        "schema": ext.upper().lstrip("."),
        "author": "",
        "organization": "",
        "created": "",
        "preprocessor": "",
        "unit": "mm (assumed)",
        "unit_factor": 1.0,
        "entity_count": 0,
        "entity_types": {},
        "file_size_kb": round(stat.st_size / 1024, 1),
        "format_note": "메시 포맷 — 위상 분석 제한적, 볼륨은 밀폐 메시 기준",
    }


def parse_metadata_iges(file_path: str) -> dict:
    """Basic IGES header parse."""
    result = {
        "schema": "IGES",
        "author": "",
        "organization": "",
        "created": "",
        "preprocessor": "",
        "unit": "mm",
        "unit_factor": 1.0,
        "entity_count": 0,
        "entity_types": {},
    }
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(10)]
        for line in lines:
            if line.startswith("1"):
                result["preprocessor"] = line[8:16].strip()
                break
        # Unit flag in Global Section
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            global_sec = ""
            for line in f:
                if line[72:73] == "G":
                    global_sec += line[:72]
                elif global_sec:
                    break
        import re
        parts = re.split(r"[,;]", global_sec)
        if len(parts) > 14:
            unit_flag = parts[14].strip()
            unit_map = {"1": "inch", "2": "mm", "3": "ft", "4": "mi",
                        "5": "m", "6": "km", "7": "mil", "8": "um",
                        "9": "cm", "10": "nm", "11": "angstrom"}
            u = unit_map.get(unit_flag, "mm")
            result["unit"] = u
            result["unit_factor"] = {"inch": 25.4, "m": 1000.0, "cm": 10.0,
                                     "ft": 304.8, "km": 1e6, "um": 0.001}.get(u, 1.0)
    except Exception:
        pass
    return result


def parse_metadata_brep(file_path: str) -> dict:
    return {
        "schema": "BREP (OpenCASCADE native)",
        "author": "", "organization": "", "created": "", "preprocessor": "",
        "unit": "mm (assumed)", "unit_factor": 1.0,
        "entity_count": 0, "entity_types": {},
    }


def parse_metadata(step_path: str) -> dict:
    try:
        import steputils.p21 as p21
    except ImportError:
        return {"error": "steputils not installed — run: pip3 install steputils"}

    result = {
        "schema": "unknown",
        "author": "",
        "organization": "",
        "created": "",
        "preprocessor": "",
        "unit": "mm",
        "unit_factor": 1.0,
        "entity_count": 0,
        "entity_types": {},
    }

    try:
        with open(step_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception as e:
        result["error"] = str(e)
        return result

    # Schema
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("FILE_SCHEMA"):
            import re
            m = re.search(r"'([^']+)'", line)
            if m:
                result["schema"] = m.group(1)
            break

    # Header section
    header_block = ""
    in_header = False
    for line in raw.splitlines():
        if line.strip() == "HEADER;":
            in_header = True
        if in_header:
            header_block += line + "\n"
        if line.strip() == "ENDSEC;" and in_header:
            break

    import re
    m = re.search(r"FILE_NAME\s*\([^,]*,\s*'([^']*)'", header_block)
    if m:
        result["created"] = m.group(1)
    m = re.search(r"FILE_NAME\s*\([^)]*\)\s*;", header_block, re.DOTALL)
    if m:
        fields = re.findall(r"'([^']*)'", m.group(0))
        if len(fields) >= 3:
            result["author"] = fields[2]
        if len(fields) >= 4:
            result["organization"] = fields[3]
        if len(fields) >= 6:
            result["preprocessor"] = fields[5]

    # Unit detection — SI_UNIT(.MILLI.,.METRE.) format or plain text
    raw_upper = raw.upper()
    if re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", raw_upper):
        result["unit"] = "mm"
        result["unit_factor"] = 1.0
    elif "MILLIMETRE" in raw_upper or "MILLIMETER" in raw_upper:
        result["unit"] = "mm"
        result["unit_factor"] = 1.0
    elif re.search(r"SI_UNIT\s*\(\s*\$\s*,\s*\.INCH\.\s*\)", raw_upper) or "INCH" in raw_upper:
        result["unit"] = "inch"
        result["unit_factor"] = 25.4
    elif re.search(r"SI_UNIT\s*\(\s*\$\s*,\s*\.METRE\.\s*\)", raw_upper) or re.search(r"\bMETRE\b|\bMETER\b", raw_upper):
        result["unit"] = "m"
        result["unit_factor"] = 1000.0
    else:
        result["unit"] = "mm"
        result["unit_factor"] = 1.0

    # Entity count
    data_entities = re.findall(r"^#\d+\s*=\s*(\w+)\s*\(", raw, re.MULTILINE)
    result["entity_count"] = len(data_entities)
    type_counts: dict[str, int] = {}
    for t in data_entities:
        type_counts[t] = type_counts.get(t, 0) + 1
    result["entity_types"] = dict(sorted(type_counts.items(), key=lambda x: -x[1])[:20])

    return result


# ─────────────────────────────────────────────
# OCP helpers
# ─────────────────────────────────────────────

def load_ocp_shape(file_path: str):
    """Load shape from STEP / IGES / BREP."""
    from OCP.IFSelect import IFSelect_RetDone
    ext = detect_format(file_path)

    if ext in (".stp", ".step"):
        from OCP.STEPControl import STEPControl_Reader
        reader = STEPControl_Reader()
        status = reader.ReadFile(file_path)
        if status != IFSelect_RetDone:
            raise RuntimeError(f"STEP read failed: status={status}")
        reader.TransferRoots()
        return reader.OneShape()

    elif ext in (".igs", ".iges"):
        from OCP.IGESControl import IGESControl_Reader
        reader = IGESControl_Reader()
        status = reader.ReadFile(file_path)
        if status != IFSelect_RetDone:
            raise RuntimeError(f"IGES read failed: status={status}")
        reader.TransferRoots()
        return reader.OneShape()

    elif ext == ".brep":
        from OCP.BRepTools import BRepTools
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Shape
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        ok = BRepTools.Read_s(shape, file_path, builder)
        if not ok or shape.IsNull():
            raise RuntimeError("BREP read failed")
        return shape

    raise ValueError(f"Unsupported OCP format: {ext}")


def map_shapes(shape, shape_type):
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopExp import TopExp
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, shape_type, m)
    return m


def iter_map(m):
    for i in range(1, m.Size() + 1):
        yield m.FindKey(i)


# ─────────────────────────────────────────────
# L2 — Geometry
# ─────────────────────────────────────────────

def analyze_geometry(shape, unit_factor: float = 1.0) -> dict:
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    result: dict = {}

    # Volume & surface
    vol_props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol_props)
    surf_props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, surf_props)

    f = unit_factor
    f3 = f ** 3
    f2 = f ** 2

    result["volume_mm3"] = round(vol_props.Mass() * f3, 4)
    result["surface_mm2"] = round(surf_props.Mass() * f2, 4)

    cog = vol_props.CentreOfMass()
    result["centroid"] = {
        "x": round(cog.X() * f, 4),
        "y": round(cog.Y() * f, 4),
        "z": round(cog.Z() * f, 4),
    }

    # Inertia
    mat = vol_props.MatrixOfInertia()
    result["inertia"] = {
        "Ixx": round(mat.Value(1, 1) * f2 * f3, 4),
        "Iyy": round(mat.Value(2, 2) * f2 * f3, 4),
        "Izz": round(mat.Value(3, 3) * f2 * f3, 4),
    }

    # Bounding box — AddOptimal: 곡면(BSpline) 부품에서 폴 기준 과대추정 방지(실제 외곽)
    bbox = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    result["bbox"] = {
        "xmin": round(xmin * f, 4), "xmax": round(xmax * f, 4),
        "ymin": round(ymin * f, 4), "ymax": round(ymax * f, 4),
        "zmin": round(zmin * f, 4), "zmax": round(zmax * f, 4),
        "dx": round((xmax - xmin) * f, 4),
        "dy": round((ymax - ymin) * f, 4),
        "dz": round((zmax - zmin) * f, 4),
    }

    return result


# ─────────────────────────────────────────────
# L3 — Topology
# ─────────────────────────────────────────────

def analyze_topology(shape) -> dict:
    from OCP.TopAbs import (
        TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE,
        TopAbs_EDGE, TopAbs_VERTEX
    )
    from OCP.BRep import BRep_Tool
    from OCP.GeomAbs import (
        GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
        GeomAbs_Sphere, GeomAbs_BSplineSurface, GeomAbs_Torus
    )
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    result: dict = {}
    result["solids"] = map_shapes(shape, TopAbs_SOLID).Size()
    result["shells"] = map_shapes(shape, TopAbs_SHELL).Size()
    result["faces"] = map_shapes(shape, TopAbs_FACE).Size()
    result["edges"] = map_shapes(shape, TopAbs_EDGE).Size()
    result["vertices"] = map_shapes(shape, TopAbs_VERTEX).Size()

    # Face type distribution
    face_types = {"Plane": 0, "Cylinder": 0, "Cone": 0, "Sphere": 0,
                  "Torus": 0, "BSpline": 0, "Other": 0}
    type_map = {
        GeomAbs_Plane: "Plane", GeomAbs_Cylinder: "Cylinder",
        GeomAbs_Cone: "Cone", GeomAbs_Sphere: "Sphere",
        GeomAbs_Torus: "Torus", GeomAbs_BSplineSurface: "BSpline",
    }
    face_map = map_shapes(shape, TopAbs_FACE)
    for face in iter_map(face_map):
        try:
            adaptor = BRepAdaptor_Surface(face)
            t = adaptor.GetType()
            face_types[type_map.get(t, "Other")] += 1
        except Exception:
            face_types["Other"] += 1

    result["face_types"] = {k: v for k, v in face_types.items() if v > 0}
    return result


# ─────────────────────────────────────────────
# L4 — Quality
# ─────────────────────────────────────────────

def analyze_quality(shape, bbox: dict) -> dict:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopExp import TopExp

    result: dict = {"warnings": []}

    # BRep validity
    checker = BRepCheck_Analyzer(shape)
    result["brep_valid"] = checker.IsValid()
    if not checker.IsValid():
        result["warnings"].append("BRep 유효성 검사 실패 — 형상에 결함이 있을 수 있음")

    # Free edges (edges shared by only one face — non-manifold indicator)
    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_face_map)
    free_edges = 0
    for i in range(1, edge_face_map.Size() + 1):
        if edge_face_map.FindFromIndex(i).Size() < 2:
            free_edges += 1
    result["free_edges"] = free_edges
    if free_edges > 0:
        result["warnings"].append(f"자유 엣지 {free_edges}개 감지 — 열린 솔리드 또는 비매니폴드 형상")

    # Bounding box sanity
    dx, dy, dz = bbox.get("dx", 0), bbox.get("dy", 0), bbox.get("dz", 0)
    dims = sorted([dx, dy, dz])
    if dims[2] > 0 and dims[0] / dims[2] < 0.0001:
        result["warnings"].append(f"극단적 종횡비 감지 ({dims[0]:.3f} vs {dims[2]:.3f} mm) — 단위 확인 필요")
    if dx > 100000 or dy > 100000 or dz > 100000:
        result["warnings"].append(f"바운딩박스 과대 ({max(dx,dy,dz):.1f} mm) — inch/m 단위 오파싱 가능성")

    return result


# ─────────────────────────────────────────────
# Per-solid breakdown (assembly support)
# ─────────────────────────────────────────────

def analyze_per_solid(compound, unit_factor: float) -> list:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    solids = []
    explorer = TopExp_Explorer(compound, TopAbs_SOLID)
    idx = 0
    while explorer.More():
        solid = explorer.Current()
        try:
            geo = analyze_geometry(solid, unit_factor)
            topo = analyze_topology(solid)
            solids.append({"index": idx, "geometry": geo, "topology": topo})
        except Exception as e:
            solids.append({"index": idx, "error": str(e)})
        idx += 1
        explorer.Next()
    return solids


# ─────────────────────────────────────────────
# Mesh format analysis (STL / OBJ) via trimesh
# ─────────────────────────────────────────────

def analyze_mesh_file(file_path: str) -> tuple[dict, dict, dict, str]:
    """Returns (geometry, topology, quality, stl_b64) for mesh formats."""
    import trimesh
    import numpy as np

    mesh = trimesh.load(file_path, force="mesh")

    bb = mesh.bounds  # [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    dx = float(bb[1][0] - bb[0][0])
    dy = float(bb[1][1] - bb[0][1])
    dz = float(bb[1][2] - bb[0][2])
    cog = mesh.center_mass

    geo = {
        "volume_mm3": round(float(mesh.volume), 4) if mesh.is_watertight else None,
        "surface_mm2": round(float(mesh.area), 4),
        "centroid": {"x": round(float(cog[0]), 4), "y": round(float(cog[1]), 4), "z": round(float(cog[2]), 4)},
        "inertia": {},
        "bbox": {
            "xmin": round(float(bb[0][0]), 4), "xmax": round(float(bb[1][0]), 4),
            "ymin": round(float(bb[0][1]), 4), "ymax": round(float(bb[1][1]), 4),
            "zmin": round(float(bb[0][2]), 4), "zmax": round(float(bb[1][2]), 4),
            "dx": round(dx, 4), "dy": round(dy, 4), "dz": round(dz, 4),
        },
    }

    topo = {
        "solids": 1,
        "shells": len(mesh.split()),
        "faces": len(mesh.faces),
        "edges": len(mesh.edges_unique),
        "vertices": len(mesh.vertices),
        "face_types": {"Triangle": len(mesh.faces)},
    }

    warnings = []
    if not mesh.is_watertight:
        warnings.append("메시가 밀폐되지 않음(non-watertight) — 부피 미산출")
    if not mesh.is_winding_consistent:
        warnings.append("면 법선 방향 불일치 — 렌더링 또는 볼륨 계산 오류 가능")
    dims = sorted([dx, dy, dz])
    if dims[2] > 0 and dims[0] / dims[2] < 0.0001:
        warnings.append(f"극단적 종횡비 — 단위 확인 필요 ({dims[0]:.3f} vs {dims[2]:.3f})")

    quality = {
        "brep_valid": mesh.is_watertight and mesh.is_winding_consistent,
        "free_edges": int(mesh.edges_unique.shape[0] - 3 * len(mesh.faces) // 2) if not mesh.is_watertight else 0,
        "warnings": warnings,
    }

    # STL b64 for viewer
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    mesh.export(tmp, file_type="stl")
    with open(tmp, "rb") as f:
        stl_b64 = base64.b64encode(f.read()).decode("ascii")
    os.unlink(tmp)

    return geo, topo, quality, stl_b64


# ─────────────────────────────────────────────
# STL tessellation (OCP shapes) → base64
# ─────────────────────────────────────────────

def tessellate_to_stl_b64(shape) -> str:
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    BRepMesh_IncrementalMesh(shape, 0.5).Perform()

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp_path = f.name

    StlAPI_Writer().Write(shape, tmp_path)

    with open(tmp_path, "rb") as f:
        data = f.read()
    os.unlink(tmp_path)
    return base64.b64encode(data).decode("ascii")


# ─────────────────────────────────────────────
# HTML report generation
# ─────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STP 분석 리포트 — {filename}</title>
<script type="importmap">
{{
  "imports": {{
    "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
  }}
}}
</script>
<style>
  :root {{
    --bg: #f8f9fa; --surface: #ffffff; --border: #dee2e6;
    --text: #212529; --muted: #6c757d; --accent: #0d6efd;
    --sidebar-w: 340px;
  }}
  [data-theme="dark"] {{
    --bg: #1a1d21; --surface: #25282d; --border: #3d4147;
    --text: #e9ecef; --muted: #adb5bd; --accent: #4dabf7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background: var(--bg); color: var(--text); display: flex;
         flex-direction: column; height: 100vh; overflow: hidden; }}
  header {{ display: flex; align-items: center; justify-content: space-between;
            padding: 10px 16px; background: var(--surface);
            border-bottom: 1px solid var(--border); flex-shrink: 0; }}
  header h1 {{ font-size: 15px; font-weight: 600; }}
  header .meta {{ font-size: 12px; color: var(--muted); }}
  .theme-btn {{ background: none; border: 1px solid var(--border); border-radius: 6px;
                padding: 4px 10px; cursor: pointer; font-size: 12px; color: var(--text); }}
  .main {{ display: flex; flex: 1; overflow: hidden; }}
  #viewer {{ flex: 1; background: #e8eaed; position: relative; }}
  #viewer canvas {{ display: block; width: 100% !important; height: 100% !important; }}
  .sidebar {{ width: var(--sidebar-w); background: var(--surface);
              border-left: 1px solid var(--border);
              overflow-y: auto; padding: 12px; flex-shrink: 0; }}
  .section {{ margin-bottom: 14px; }}
  .section-title {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.5px; color: var(--muted);
                    padding-bottom: 4px; border-bottom: 1px solid var(--border);
                    margin-bottom: 8px; }}
  .kv {{ display: flex; justify-content: space-between; align-items: baseline;
         padding: 3px 0; font-size: 13px; }}
  .kv .k {{ color: var(--muted); flex-shrink: 0; margin-right: 8px; }}
  .kv .v {{ font-weight: 500; text-align: right; word-break: break-all; }}
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px;
             font-size: 11px; font-weight: 600; }}
  .badge-ok {{ background: #d1e7dd; color: #0a3622; }}
  .badge-warn {{ background: #fff3cd; color: #664d03; }}
  .badge-err {{ background: #f8d7da; color: #58151c; }}
  [data-theme="dark"] .badge-ok {{ background: #0a3622; color: #75b798; }}
  [data-theme="dark"] .badge-warn {{ background: #332701; color: #ffda6a; }}
  [data-theme="dark"] .badge-err {{ background: #2c0b0e; color: #ea868f; }}
  .warn-item {{ background: #fff3cd; color: #664d03; border-radius: 4px;
                padding: 6px 8px; font-size: 12px; margin-bottom: 4px; }}
  [data-theme="dark"] .warn-item {{ background: #332701; color: #ffda6a; }}
  .bar-row {{ display: flex; align-items: center; gap: 6px;
              font-size: 12px; margin-bottom: 3px; }}
  .bar-label {{ width: 70px; text-align: right; color: var(--muted); flex-shrink: 0; }}
  .bar-track {{ flex: 1; background: var(--border); border-radius: 2px; height: 8px; }}
  .bar-fill {{ height: 8px; border-radius: 2px; background: var(--accent); }}
  .bar-val {{ width: 40px; font-weight: 500; }}
  .solid-item {{ border: 1px solid var(--border); border-radius: 6px;
                 padding: 8px; margin-bottom: 6px; font-size: 12px; }}
  .solid-title {{ font-weight: 600; margin-bottom: 4px; }}
  .loading {{ position: absolute; inset: 0; display: flex; flex-direction: column;
              align-items: center; justify-content: center; font-size: 14px;
              color: #555; background: #e8eaed; gap: 12px; }}
  .loading-spinner {{ width: 36px; height: 36px; border: 3px solid #ccc;
                      border-top-color: #0d6efd; border-radius: 50%;
                      animation: spin 0.8s linear infinite; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body data-theme="light">
<header>
  <div>
    <h1>STP 분석 리포트</h1>
    <div class="meta">{filename} &nbsp;·&nbsp; {schema} &nbsp;·&nbsp; 분석일시: {analyzed_at}</div>
  </div>
  <button class="theme-btn" id="theme-btn">다크 모드</button>
</header>
<div class="main">
  <div id="viewer">
    <div class="loading" id="loading-msg">
      <div class="loading-spinner"></div>
      <span>3D 모델 로딩 중...</span>
    </div>
  </div>
  <div class="sidebar" id="sidebar"></div>
</div>

<script>
var DATA = {data_json};
var STL_B64 = "{stl_b64}";
</script>

<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ STLLoader }} from 'three/addons/loaders/STLLoader.js';

let renderer, camera, controls, scene;

function initViewer() {{
  const container = document.getElementById('viewer');
  const w = container.clientWidth;
  const h = container.clientHeight;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe8eaed);

  camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 1000000);

  renderer = new THREE.WebGLRenderer({{ antialias: true }});
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dir1 = new THREE.DirectionalLight(0xffffff, 0.9);
  dir1.position.set(1, 2, 3);
  scene.add(dir1);
  const dir2 = new THREE.DirectionalLight(0xaaaaff, 0.4);
  dir2.position.set(-2, -1, -2);
  scene.add(dir2);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;

  const loadMsg = document.getElementById('loading-msg');

  if (window.STL_B64 && window.STL_B64.length > 0) {{
    try {{
      const raw = atob(window.STL_B64);
      const buf = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);

      const loader = new STLLoader();
      const geometry = loader.parse(buf.buffer);
      geometry.computeVertexNormals();

      const material = new THREE.MeshPhongMaterial({{
        color: 0xc8c8c8,
        specular: 0x444444,
        shininess: 40,
        side: THREE.DoubleSide,
      }});
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      const edges = new THREE.EdgesGeometry(geometry, 20);
      const lineMat = new THREE.LineBasicMaterial({{ color: 0x222222, linewidth: 1 }});
      const edgeLines = new THREE.LineSegments(edges, lineMat);
      scene.add(edgeLines);

      geometry.computeBoundingBox();
      const box = geometry.boundingBox;
      const center = new THREE.Vector3();
      box.getCenter(center);
      const size = new THREE.Vector3();
      box.getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z);

      camera.near = maxDim * 0.0001;
      camera.far = maxDim * 100;
      camera.updateProjectionMatrix();
      camera.position.set(
        center.x + maxDim * 1.2,
        center.y + maxDim * 0.8,
        center.z + maxDim * 1.2
      );
      controls.target.copy(center);
      controls.update();

      loadMsg.style.display = 'none';
    }} catch (err) {{
      loadMsg.querySelector('span').textContent = '3D 로드 오류: ' + err.message;
      loadMsg.querySelector('.loading-spinner').style.display = 'none';
    }}
  }} else {{
    loadMsg.querySelector('span').textContent = '3D 데이터 없음';
    loadMsg.querySelector('.loading-spinner').style.display = 'none';
  }}

  window.addEventListener('resize', () => {{
    const w2 = container.clientWidth;
    const h2 = container.clientHeight;
    camera.aspect = w2 / h2;
    camera.updateProjectionMatrix();
    renderer.setSize(w2, h2);
  }});

  function animate() {{
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }}
  animate();
}}

window.toggleTheme = function() {{
  const dark = document.body.getAttribute('data-theme') === 'dark';
  document.body.setAttribute('data-theme', dark ? 'light' : 'dark');
  document.getElementById('theme-btn').textContent = dark ? '다크 모드' : '라이트 모드';
  if (scene) scene.background = new THREE.Color(dark ? 0xe8eaed : 0x1a1d21);
}};

document.getElementById('theme-btn').addEventListener('click', window.toggleTheme);

initViewer();
</script>

<script>
function fmt(v, decimals) {{
  decimals = decimals === undefined ? 2 : decimals;
  if (v === undefined || v === null) return '—';
  if (typeof v === 'boolean') return v ? '✓' : '✗';
  if (typeof v === 'number') return v.toLocaleString('ko-KR', {{maximumFractionDigits: decimals}});
  return String(v);
}}
function kv(k, v) {{
  return '<div class="kv"><span class="k">' + k + '</span><span class="v">' + v + '</span></div>';
}}
function badge(text, type) {{
  return '<span class="badge badge-' + type + '">' + text + '</span>';
}}

(function buildSidebar() {{
  const d = window.DATA || {{}};
  let html = '';

  const m = d.metadata || {{}};
  html += '<div class="section"><div class="section-title">L1 메타데이터</div>'
    + kv('스키마', m.schema || '—')
    + kv('단위', m.unit || '—')
    + kv('Author', m.author || '—')
    + kv('Organization', m.organization || '—')
    + kv('생성일', m.created || '—')
    + kv('프리프로세서', m.preprocessor || '—')
    + kv('엔티티 수', fmt(m.entity_count, 0))
    + '</div>';

  if (m.entity_types && Object.keys(m.entity_types).length) {{
    const maxVal = Math.max.apply(null, Object.values(m.entity_types));
    html += '<div class="section"><div class="section-title">엔티티 유형 (상위 10)</div>';
    Object.entries(m.entity_types).slice(0, 10).forEach(function(entry) {{
      const pct = Math.round(entry[1] / maxVal * 100);
      html += '<div class="bar-row"><span class="bar-label">' + entry[0] + '</span>'
        + '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>'
        + '<span class="bar-val">' + entry[1] + '</span></div>';
    }});
    html += '</div>';
  }}

  const g = d.geometry || {{}};
  const bb = g.bbox || {{}};
  const cen = g.centroid || {{}};
  const ine = g.inertia || {{}};
  html += '<div class="section"><div class="section-title">L2 지오메트리</div>'
    + kv('부피', fmt(g.volume_mm3) + ' mm³')
    + kv('표면적', fmt(g.surface_mm2) + ' mm²')
    + kv('무게중심 X', fmt(cen.x) + ' mm')
    + kv('무게중심 Y', fmt(cen.y) + ' mm')
    + kv('무게중심 Z', fmt(cen.z) + ' mm')
    + kv('BBox', fmt(bb.dx) + ' × ' + fmt(bb.dy) + ' × ' + fmt(bb.dz) + ' mm')
    + kv('Ixx', fmt(ine.Ixx))
    + kv('Iyy', fmt(ine.Iyy))
    + kv('Izz', fmt(ine.Izz))
    + '</div>';

  const t = d.topology || {{}};
  html += '<div class="section"><div class="section-title">L3 토폴로지</div>'
    + kv('Solid', fmt(t.solids, 0))
    + kv('Shell', fmt(t.shells, 0))
    + kv('Face', fmt(t.faces, 0))
    + kv('Edge', fmt(t.edges, 0))
    + kv('Vertex', fmt(t.vertices, 0))
    + '</div>';

  if (t.face_types && Object.keys(t.face_types).length) {{
    const maxv = Math.max.apply(null, Object.values(t.face_types));
    html += '<div class="section"><div class="section-title">면 종류 분포</div>';
    Object.entries(t.face_types).forEach(function(entry) {{
      const pct = Math.round(entry[1] / maxv * 100);
      html += '<div class="bar-row"><span class="bar-label">' + entry[0] + '</span>'
        + '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>'
        + '<span class="bar-val">' + entry[1] + '</span></div>';
    }});
    html += '</div>';
  }}

  const q = d.quality || {{}};
  html += '<div class="section"><div class="section-title">L4 품질 검사</div>'
    + kv('BRep 유효성', q.brep_valid ? badge('PASS', 'ok') : badge('FAIL', 'err'))
    + kv('자유 엣지', q.free_edges === 0 ? badge('없음', 'ok') : badge(q.free_edges + '개', 'warn'))
    + '</div>';

  if (q.warnings && q.warnings.length) {{
    html += '<div class="section"><div class="section-title">경고</div>';
    q.warnings.forEach(function(w) {{
      html += '<div class="warn-item">⚠ ' + w + '</div>';
    }});
    html += '</div>';
  }}

  if (d.solids && d.solids.length > 1) {{
    html += '<div class="section"><div class="section-title">솔리드별 분석 (' + d.solids.length + '개)</div>';
    d.solids.forEach(function(s) {{
      if (s.error) {{
        html += '<div class="solid-item"><div class="solid-title">Solid #' + s.index + '</div>오류: ' + s.error + '</div>';
        return;
      }}
      const sg = s.geometry || {{}};
      const sbb = sg.bbox || {{}};
      html += '<div class="solid-item"><div class="solid-title">Solid #' + s.index + '</div>'
        + kv('부피', fmt(sg.volume_mm3) + ' mm³')
        + kv('BBox', fmt(sbb.dx) + ' × ' + fmt(sbb.dy) + ' × ' + fmt(sbb.dz) + ' mm')
        + kv('Face', fmt((s.topology || {{}}).faces, 0))
        + '</div>';
    }});
    html += '</div>';
  }}

  document.getElementById('sidebar').innerHTML = html;
}})();
</script>
</body>
</html>
"""


def generate_report(file_path: str, output_dir: str | None = None) -> str:
    file_path = str(Path(file_path).resolve())
    filename = Path(file_path).name
    ext = detect_format(file_path)

    if ext not in ALL_FORMATS:
        raise ValueError(f"지원하지 않는 포맷: {ext}\n지원: {', '.join(sorted(ALL_FORMATS))}")

    if output_dir is None:
        output_dir = str(Path(file_path).parent)
    output_dir = str(Path(output_dir).resolve())
    stem = Path(file_path).stem
    output_path = os.path.join(output_dir, f"{stem}_report.html")

    print(f"[CAD Analyzer] File: {file_path}  (format: {ext})")

    # ── Mesh path (STL / OBJ) ──────────────────
    if ext in MESH_FORMATS:
        print(f"[L1] Metadata (mesh)...")
        meta = parse_metadata_mesh(file_path)
        print(f"     Format: {meta['schema']}, Size: {meta.get('file_size_kb')} KB")

        print(f"[Mesh] Loading via trimesh...")
        geo, topo, qual, stl_b64 = analyze_mesh_file(file_path)
        bb = geo["bbox"]
        vol = geo.get("volume_mm3")
        print(f"     Volume: {vol} mm³, Surface: {geo['surface_mm2']} mm²")
        print(f"     BBox: {bb['dx']} × {bb['dy']} × {bb['dz']} mm")
        print(f"     Faces: {topo['faces']}, Vertices: {topo['vertices']}")
        for w in qual.get("warnings", []):
            print(f"     WARNING: {w}")
        solids_data = []

    # ── OCP path (STEP / IGES / BREP) ──────────
    else:
        print(f"[L1] Parsing metadata...")
        if ext in (".stp", ".step"):
            meta = parse_metadata(file_path)
        elif ext in (".igs", ".iges"):
            meta = parse_metadata_iges(file_path)
        else:
            meta = parse_metadata_brep(file_path)
        unit_factor = meta.get("unit_factor", 1.0)
        print(f"     Schema: {meta.get('schema')}, Unit: {meta.get('unit')}, Entities: {meta.get('entity_count')}")

        print(f"[OCP] Loading shape...")
        shape = load_ocp_shape(file_path)

        print(f"[L2] Geometry analysis...")
        geo = analyze_geometry(shape, unit_factor)
        bb = geo["bbox"]
        print(f"     Volume: {geo['volume_mm3']} mm³, Surface: {geo['surface_mm2']} mm²")
        print(f"     BBox: {bb['dx']} × {bb['dy']} × {bb['dz']} mm")

        print(f"[L3] Topology analysis...")
        topo = analyze_topology(shape)
        print(f"     Solids: {topo['solids']}, Faces: {topo['faces']}, Edges: {topo['edges']}")

        print(f"[L4] Quality check...")
        qual = analyze_quality(shape, bb)
        print(f"     BRep valid: {qual['brep_valid']}, Free edges: {qual['free_edges']}")
        for w in qual.get("warnings", []):
            print(f"     WARNING: {w}")

        solids_data = []
        if topo["solids"] > 1:
            print(f"[Assembly] Analyzing {topo['solids']} solids individually...")
            solids_data = analyze_per_solid(shape, unit_factor)

        print(f"[STL] Tessellating for 3D viewer...")
        try:
            stl_b64 = tessellate_to_stl_b64(shape)
            print(f"     STL size: {len(stl_b64) // 1024} KB (base64)")
        except Exception as e:
            print(f"     WARNING: tessellation failed: {e}")
            stl_b64 = ""

    data = {
        "metadata": meta,
        "geometry": geo,
        "topology": topo,
        "quality": qual,
        "solids": solids_data,
    }

    html = HTML_TEMPLATE.format(
        filename=filename,
        schema=meta.get("schema", ""),
        analyzed_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        data_json=json.dumps(data, ensure_ascii=False),
        stl_b64=stl_b64,
    )

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Report saved: {output_path}")
    return output_path


def main():
    if len(sys.argv) < 2:
        exts = ", ".join(sorted(ALL_FORMATS))
        print(f"Usage: analyze_stp.py <file> [output_dir]")
        print(f"Supported: {exts}")
        sys.exit(1)

    file_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) >= 3 else None

    if not os.path.exists(file_path):
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    ext = detect_format(file_path)
    if ext not in ALL_FORMATS:
        print(f"ERROR: 지원하지 않는 포맷: {ext}")
        print(f"지원 포맷: {', '.join(sorted(ALL_FORMATS))}")
        sys.exit(1)

    generate_report(file_path, output_dir)


if __name__ == "__main__":
    main()
