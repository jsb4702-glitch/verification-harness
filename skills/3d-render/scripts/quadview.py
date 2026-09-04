import sys, os, time, math
t0=time.time()
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf
from OCP.TDF import TDF_LabelSequence, TDF_Label
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.Quantity import Quantity_Color
from OCP.XCAFDoc import XCAFDoc_ShapeTool
import vtk

src, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)

doc = TDocStd_Document(TCollection_ExtendedString("doc"))
rdr = STEPCAFControl_Reader(); rdr.SetColorMode(True); rdr.SetNameMode(True)
assert rdr.ReadFile(src) == IFSelect_RetDone, "read fail"
assert rdr.Transfer(doc), "transfer fail"
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

# collect free shapes -> leaf solids with color
labels = TDF_LabelSequence(); st.GetFreeShapes(labels)
parts = []  # (shape, (r,g,b))
def get_color(lbl, shape):
    c = Quantity_Color()
    for tool_type in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
        try:
            if ct.GetColor(shape, tool_type, c):
                return (c.Red(), c.Green(), c.Blue())
        except TypeError: pass
    return None
def walk(lbl):
    if st.IsAssembly_s(lbl):
        comps = TDF_LabelSequence(); st.GetComponents_s(lbl, comps)
        for i in range(1, comps.Length()+1):
            ref = comps.Value(i); rl = TDF_Label()
            if st.GetReferredShape_s(ref, rl):
                # accumulate location
                walk_with_loc(rl, st.GetLocation_s(ref))
            else: walk(ref)
    else:
        sh = st.GetShape_s(lbl); col = get_color(lbl, sh)
        parts.append((sh, col))
def walk_with_loc(lbl, loc):
    if st.IsAssembly_s(lbl):
        comps = TDF_LabelSequence(); st.GetComponents_s(lbl, comps)
        for i in range(1, comps.Length()+1):
            ref = comps.Value(i); rl = TDF_Label()
            if st.GetReferredShape_s(ref, rl):
                walk_with_loc(rl, loc.Multiplied(st.GetLocation_s(ref)))
            else: pass
    else:
        sh = st.GetShape_s(lbl).Moved(loc); col = get_color(lbl, st.GetShape_s(lbl))
        parts.append((sh, col))
for i in range(1, labels.Length()+1):
    walk(labels.Value(i))
print(f"parts={len(parts)} colored={sum(1 for _,c in parts if c)}")

# global bbox for deflection
bb = Bnd_Box()
for sh,_ in parts: BRepBndLib.Add_s(sh, bb)
xmin,ymin,zmin,xmax,ymax,zmax = bb.Get()
dx,dy,dz = xmax-xmin, ymax-ymin, zmax-zmin
diag = (dx*dx+dy*dy+dz*dz)**0.5
print(f"bbox mm: {dx:.2f} x {dy:.2f} x {dz:.2f} diag={diag:.2f}")

PALETTE = [(0.72,0.75,0.78),(0.55,0.65,0.80),(0.80,0.65,0.50),(0.60,0.78,0.62),(0.78,0.60,0.70),(0.85,0.80,0.55)]
ren = vtk.vtkRenderer(); ntri_total=0
# face colors possible too: build per-part polydata with per-face color override
for idx,(sh,col) in enumerate(parts):
    BRepMesh_IncrementalMesh(sh, diag*0.0015, False, 0.35, True)
    # per-face colors?
    face_cols = {}
    exp = TopExp_Explorer(sh, TopAbs_FACE)
    pts = vtk.vtkPoints(); polys = vtk.vtkCellArray()
    cols = vtk.vtkUnsignedCharArray(); cols.SetNumberOfComponents(3)
    base_col = col or PALETTE[idx % len(PALETTE)]
    while exp.More():
        f = TopoDS.Face_s(exp.Current()); loc = TopLoc_Location(); tri = BRep_Tool.Triangulation_s(f, loc)
        fc = None
        c = Quantity_Color()
        if ct.GetColor(f, XCAFDoc_ColorSurf, c): fc = (c.Red(),c.Green(),c.Blue())
        use = fc or base_col
        if tri is not None:
            trsf = loc.Transformation(); base = pts.GetNumberOfPoints()
            for i in range(1, tri.NbNodes()+1):
                p = tri.Node(i).Transformed(trsf); pts.InsertNextPoint(p.X(), p.Y(), p.Z())
            rev = (f.Orientation() == TopAbs_REVERSED)
            for i in range(1, tri.NbTriangles()+1):
                a,b,cc = tri.Triangle(i).Get()
                if rev: b,cc = cc,b
                polys.InsertNextCell(3)
                for k in (a,b,cc): polys.InsertCellPoint(base+k-1)
                cols.InsertNextTuple3(int(use[0]*255),int(use[1]*255),int(use[2]*255)); ntri_total+=1
        exp.Next()
    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(polys); pd.GetCellData().SetScalars(cols)
    nrm = vtk.vtkPolyDataNormals(); nrm.SetInputData(pd); nrm.SetFeatureAngle(30); nrm.Update()
    m = vtk.vtkPolyDataMapper(); m.SetInputConnection(nrm.GetOutputPort())
    a = vtk.vtkActor(); a.SetMapper(m); a.GetProperty().SetSpecular(0.25); a.GetProperty().SetSpecularPower(25)
    # silhouette edges
    ren.AddActor(a)
print(f"tris={ntri_total} tessellate+build t={time.time()-t0:.1f}s")

ren.SetBackground(1,1,1); ren.GradientBackgroundOn(); ren.SetBackground2(0.86,0.89,0.93)
rw = vtk.vtkRenderWindow(); rw.SetOffScreenRendering(1); rw.AddRenderer(ren); rw.SetSize(1600,1200); rw.SetMultiSamples(8)
cx,cy,cz = (xmin+xmax)/2,(ymin+ymax)/2,(zmin+zmax)/2
views = {"iso":((1,-1,0.7),(0,0,1),False), "front":((0,-1,0),(0,0,1),True), "top":((0,0,1),(0,1,0),True), "right":((1,0,0),(0,0,1),True)}
cam = ren.GetActiveCamera()
for name,(dirv,up,ortho) in views.items():
    n = (dirv[0]**2+dirv[1]**2+dirv[2]**2)**0.5
    cam.SetParallelProjection(ortho)
    cam.SetFocalPoint(cx,cy,cz); cam.SetPosition(cx+dirv[0]/n*diag*2.2, cy+dirv[1]/n*diag*2.2, cz+dirv[2]/n*diag*2.2); cam.SetViewUp(*up)
    ren.ResetCamera(); ren.ResetCameraClippingRange()
    if ortho: cam.SetParallelScale(cam.GetParallelScale()*0.85)
    else: pass  # ResetCamera margin is enough for iso
    rw.Render()
    w2i = vtk.vtkWindowToImageFilter(); w2i.SetInput(rw); w2i.ReadFrontBufferOff(); w2i.Update()
    wr = vtk.vtkPNGWriter(); wr.SetFileName(os.path.join(outdir,f"view_{name}.png")); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
    print(f"view {name} done")

# contact sheet
from PIL import Image, ImageDraw
imgs = {n: Image.open(os.path.join(outdir,f"view_{n}.png")) for n in views}
W,H = 1600,1200
sheet = Image.new("RGB",(W*2+30,H*2+30),(255,255,255))
posmap = {"iso":(10,10),"front":(W+20,10),"top":(10,H+20),"right":(W+20,H+20)}
d = ImageDraw.Draw(sheet)
for n,(x,y) in posmap.items():
    sheet.paste(imgs[n],(x,y)); d.text((x+18,y+14), n.upper(), fill=(40,40,40))
sheet.save(os.path.join(outdir,"sheet.png"))
print(f"TOTAL t={time.time()-t0:.1f}s -> {outdir}/sheet.png")
