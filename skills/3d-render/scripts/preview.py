#!/usr/bin/env python3
"""Fast VTK offscreen preview (~5s) for pose/contact checks BEFORE Cycles.
Usage: preview.py out.png stl1 [stl2 ...] [--floor] [--block XE,TOP] [--cam x,y,z]"""
import sys, argparse, vtk
ap=argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("stls",nargs="+")
ap.add_argument("--floor",action="store_true"); ap.add_argument("--block")
ap.add_argument("--cam",default="1,-1,0.4")
a=ap.parse_args()
ren=vtk.vtkRenderer(); ren.SetBackground(1,1,1)
COLS=[(0.55,0.57,0.6),(0.2,0.2,0.25),(0.8,0.4,0.3)]
zmin=1e18
for i,p in enumerate(a.stls):
    r=vtk.vtkSTLReader(); r.SetFileName(p); r.Update()
    zmin=min(zmin, r.GetOutput().GetBounds()[4])
    m=vtk.vtkPolyDataMapper(); m.SetInputConnection(r.GetOutputPort())
    ac=vtk.vtkActor(); ac.SetMapper(m); ac.GetProperty().SetColor(*COLS[i%3]); ren.AddActor(ac)
cube=None
if a.block:
    xe,top=[float(v) for v in a.block.split(",")]
    cube=vtk.vtkCubeSource(); cube.SetBounds(xe,xe+500,-400,400,top-500,top)
elif a.floor:
    cube=vtk.vtkCubeSource(); cube.SetBounds(-400,400,-400,400,zmin-8,zmin)
if cube:
    cube.Update(); cm=vtk.vtkPolyDataMapper(); cm.SetInputConnection(cube.GetOutputPort())
    ca=vtk.vtkActor(); ca.SetMapper(cm); ca.GetProperty().SetColor(0.85,0.83,0.8); ren.AddActor(ca)
rw=vtk.vtkRenderWindow(); rw.SetOffScreenRendering(1); rw.AddRenderer(ren); rw.SetSize(1200,900); rw.SetMultiSamples(8)
c=ren.GetActiveCamera(); c.SetPosition(*[float(v) for v in a.cam.split(",")]); c.SetViewUp(0,0,1)
ren.ResetCamera(); rw.Render()
w=vtk.vtkWindowToImageFilter(); w.SetInput(rw); w.Update()
wr=vtk.vtkPNGWriter(); wr.SetFileName(a.out); wr.SetInputConnection(w.GetOutputPort()); wr.Write()
print("ok",a.out)
