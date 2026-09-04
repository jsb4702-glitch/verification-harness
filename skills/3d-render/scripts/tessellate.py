#!/usr/bin/env python3
"""STEP/IGES -> binary STL via OCP. Optional narrow-band segmentation (e.g. cylindrical column).
Usage: tessellate.py input.step outdir [--defl 0.12] [--ang 0.25] [--split-band]
Outputs: outdir/model.stl  (with --split-band: model_main.stl + model_band.stl)"""
import sys, os, argparse, struct
import numpy as np
def write_stl(tris, path):
    with open(path,"wb") as f:
        f.write(b"\0"*80); f.write(struct.pack("<I",len(tris)))
        for t in tris:
            nv=np.cross(t[1]-t[0],t[2]-t[0]); L=np.linalg.norm(nv)
            if L>0: nv/=L
            f.write(struct.pack("<3f",*nv))
            for v in t: f.write(struct.pack("<3f",*v))
            f.write(b"\0\0")
ap=argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("outdir")
ap.add_argument("--defl",type=float,default=0.12,help="linear deflection mm (0.08 for engraved text)")
ap.add_argument("--ang",type=float,default=0.25,help="angular deflection rad")
ap.add_argument("--split-band",action="store_true",help="split narrow z-band geometry (column/shaft) into separate STL")
ap.add_argument("--no-heal",action="store_true",help="skip ShapeFix healing (default: heal)")
a=ap.parse_args()
os.makedirs(a.outdir,exist_ok=True)
from OCP.STEPControl import STEPControl_Reader
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
rdr = IGESControl_Reader() if a.src.lower().endswith((".igs",".iges")) else STEPControl_Reader()
assert rdr.ReadFile(a.src)==IFSelect_RetDone, "read fail"
rdr.TransferRoots(); shape=rdr.OneShape()
if not a.no_heal:
    from OCP.ShapeFix import ShapeFix_Shape
    fx=ShapeFix_Shape(shape); fx.Perform(); shape=fx.Shape()
    print("healed (ShapeFix)")
BRepMesh_IncrementalMesh(shape, a.defl, False, a.ang, True)
faces=[]
exp=TopExp_Explorer(shape, TopAbs_FACE)
while exp.More():
    f=TopoDS.Face_s(exp.Current()); loc=TopLoc_Location(); tri=BRep_Tool.Triangulation_s(f,loc)
    if tri is not None:
        trsf=loc.Transformation()
        V=np.array([[(p:=tri.Node(i).Transformed(trsf)).X(),p.Y(),p.Z()] for i in range(1,tri.NbNodes()+1)])
        rev=(f.Orientation()==TopAbs_REVERSED); T=[]
        for i in range(1,tri.NbTriangles()+1):
            x,y,z=tri.Triangle(i).Get()
            T.append((x-1,z-1,y-1) if rev else (x-1,y-1,z-1))
        faces.append((V,np.array(T)))
    exp.Next()
allv=np.vstack([V for V,_ in faces])
if not a.split_band:
    tris=np.vstack([V[T] for V,T in faces])
    write_stl(tris, os.path.join(a.outdir,"model.stl"))
    print(f"model.stl tris={len(tris)} bbox={allv.min(0).round(1)}..{allv.max(0).round(1)}")
else:
    zmin,zmax=allv[:,2].min(),allv[:,2].max()
    zs=np.linspace(zmin,zmax,120); ext=[]
    full=max(np.ptp(allv[:,0]), np.ptp(allv[:,1]))
    for i in range(len(zs)-1):
        m=(allv[:,2]>=zs[i])&(allv[:,2]<zs[i+1])
        ext.append(max(np.ptp(allv[m][:,0]),np.ptp(allv[m][:,1])) if m.sum()>10 else 0)
    narrow=np.array(ext)<full*0.35
    runs=[]; s0=None
    for i,n in enumerate(narrow):
        if n and s0 is None: s0=i
        if (not n or i==len(narrow)-1) and s0 is not None:
            runs.append((s0, i if not n else i+1)); s0=None
    runs=[(p,q) for p,q in runs if zs[p]>zmin+0.05*(zmax-zmin) and zs[q]<zmax-0.05*(zmax-zmin)]
    band=[]; main=[]
    if runs:
        p,q=max(runs,key=lambda r:r[1]-r[0]); lo,hi=zs[p]+1.0,zs[q]-1.0
        for V,T in faces:
            cz=(V[T[:,0],2]+V[T[:,1],2]+V[T[:,2],2])/3.0
            m=(cz>=lo)&(cz<=hi)
            if m.any(): band.append(V[T[m]])
            if (~m).any(): main.append(V[T[~m]])
        print(f"band z=[{lo:.1f},{hi:.1f}]")
    else:
        main=[V[T] for V,T in faces]; print("no narrow band found -> all main")
    mt=np.vstack(main); write_stl(mt, os.path.join(a.outdir,"model_main.stl"))
    print(f"model_main.stl tris={len(mt)}")
    if band:
        bt=np.vstack(band); write_stl(bt, os.path.join(a.outdir,"model_band.stl"))
        print(f"model_band.stl tris={len(bt)}")
