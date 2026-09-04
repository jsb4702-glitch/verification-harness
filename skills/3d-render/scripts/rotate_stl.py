#!/usr/bin/env python3
"""Rigid-rotate binary STL(s). Composable ops applied in order:
--up ux,uy       : make in-plane direction (ux,uy,0) the new +Z (old Z becomes horizontal +Y)
--rotx/--roty/--rotz DEG : axis rotations
Usage: rotate_stl.py in.stl out.stl [ops...]   (repeat for each STL with same ops to keep parts aligned)"""
import sys, struct, math, argparse
import numpy as np
def read_stl(p):
    with open(p,"rb") as f:
        f.seek(80); n=struct.unpack("<I",f.read(4))[0]
        d=np.frombuffer(f.read(n*50),dtype=np.uint8).reshape(n,50)
    return np.frombuffer(d[:,12:48].copy().tobytes(),dtype="<f4").reshape(n,3,3).astype(np.float64)
def write_stl(tris, p):
    with open(p,"wb") as f:
        f.write(b"\0"*80); f.write(struct.pack("<I",len(tris)))
        for t in tris:
            nv=np.cross(t[1]-t[0],t[2]-t[0]); L=np.linalg.norm(nv)
            if L>0: nv/=L
            f.write(struct.pack("<3f",*nv))
            for v in t: f.write(struct.pack("<3f",*v))
            f.write(b"\0\0")
ap=argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--up"); ap.add_argument("--rotx",type=float); ap.add_argument("--roty",type=float); ap.add_argument("--rotz",type=float)
a=ap.parse_args()
R=np.eye(3)
def rot(axis,deg):
    t=math.radians(deg); c,s=math.cos(t),math.sin(t)
    if axis=="x": return np.array([[1,0,0],[0,c,-s],[0,s,c]])
    if axis=="y": return np.array([[c,0,s],[0,1,0],[-s,0,c]])
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])
if a.up:
    ux,uy=[float(v) for v in a.up.split(",")]
    Z=np.array([ux,uy,0.0]); Z/=np.linalg.norm(Z)
    Y=np.array([0.0,0.0,1.0]); X=np.cross(Y,Z)
    R=np.vstack([X,Y,Z])@R
for ax,val in (("x",a.rotx),("y",a.roty),("z",a.rotz)):
    if val is not None: R=rot(ax,val)@R
T=read_stl(a.src)
T2=np.einsum('ij,nkj->nki',R,T)
write_stl(T2,a.dst)
P=T2.reshape(-1,3)
print(f"ok tris={len(T2)} bbox x[{P[:,0].min():.0f},{P[:,0].max():.0f}] y[{P[:,1].min():.0f},{P[:,1].max():.0f}] z[{P[:,2].min():.0f},{P[:,2].max():.0f}]")
