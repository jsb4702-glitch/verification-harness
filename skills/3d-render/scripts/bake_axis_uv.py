#!/usr/bin/env python3
"""Bake tube-axis flow UV for UD stripes. Axis field from silhouette distance-transform gradient
(exact for any tube width; assumes frame roughly planar in XZ). Usage: bake_axis_uv.py in.stl out.obj"""
import sys, struct, argparse
import numpy as np
from scipy import ndimage
ap=argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--cell",type=float,default=2.0)
ap.add_argument("--style",choices=["flow","forged"],default="flow")
ap.add_argument("--sigma",type=float,default=10.0,help="angle field smoothing (mm)")
a=ap.parse_args()
def read_stl(p):
    with open(p,"rb") as f:
        f.seek(80); n=struct.unpack("<I",f.read(4))[0]
        d=np.frombuffer(f.read(n*50),dtype=np.uint8).reshape(n,50)
    return np.frombuffer(d[:,12:48].copy().tobytes(),dtype="<f4").reshape(n,3,3).astype(np.float64)
T=read_stl(a.src); soup=T.reshape(-1,3)
key=np.round(soup/0.01).astype(np.int64)
uniq,inv=np.unique(key,axis=0,return_inverse=True)
V=np.zeros((len(uniq),3)); np.add.at(V,inv,soup)
cnt=np.zeros(len(uniq)); np.add.at(cnt,inv,1); V/=cnt[:,None]
x0,z0=V[:,0].min()-10,V[:,2].min()-10
W=int((V[:,0].max()-x0+20)/a.cell); H=int((V[:,2].max()-z0+20)/a.cell)
mask=np.zeros((H,W),bool)
ix=((V[:,0]-x0)/a.cell).astype(int).clip(0,W-1)
iz=((V[:,2]-z0)/a.cell).astype(int).clip(0,H-1)
mask[iz,ix]=True
mask=ndimage.binary_closing(mask, structure=np.ones((5,5)), iterations=3)
# fill only small holes (keep frame windows open)
inv_m=~mask
lab,n=ndimage.label(inv_m)
sizes=ndimage.sum(inv_m,lab,range(1,n+1))
border=set(np.unique(np.concatenate([lab[0,:],lab[-1,:],lab[:,0],lab[:,-1]])))
for li in range(1,n+1):
    if li in border: continue
    if sizes[li-1] < 800:   # <3200 mm^2
        mask[lab==li]=True
if a.style=="forged":
    # forged-carbon look (historic d8 recipe): fill ALL holes, EDT-gradient angle field,
    # u = -sin(th)*x + cos(th)*z  (global-coordinate phase drift IS the aesthetic)
    mfull=ndimage.binary_fill_holes(mask)
    df=ndimage.distance_transform_edt(mfull)
    gz,gx=np.gradient(ndimage.gaussian_filter(df,2.0))
    c2=(-gz)**2-gx**2; s2=2*(-gz)*gx
    c2=ndimage.gaussian_filter(c2,a.sigma/a.cell); s2=ndimage.gaussian_filter(s2,a.sigma/a.cell)
    thf=0.5*np.arctan2(s2,c2)
    thv=thf[iz,ix]
    u=(-np.sin(thv)*V[:,0]+np.cos(thv)*V[:,2])*0.001
else:
    u=None
if u is None:
  # axis field from EDT gradient (doubled angle), then Poisson stream function:
 # solve min |grad u - e_perp|^2  ->  Lap u = div(e_perp), u iso-lines flow along tubes.
 d=ndimage.distance_transform_edt(mask)
 gz,gx=np.gradient(ndimage.gaussian_filter(d,2.0))
 c2=(-gz)**2-gx**2; s2=2*(-gz)*gx
 c2=ndimage.gaussian_filter(c2,a.sigma/a.cell); s2=ndimage.gaussian_filter(s2,a.sigma/a.cell)
 th=0.5*np.arctan2(s2,c2)          # tube axis angle (mod pi)
 pex=np.cos(th+np.pi/2); pez=np.sin(th+np.pi/2)   # perp direction (sign ambiguous)
 # orientation resolve: BFS align signs with neighbors
 from collections import deque
 sign=np.zeros_like(th); Hm,Wm=mask.shape
 seed=tuple(np.argwhere(mask)[0])
 sign[seed]=1.0; qd=deque([seed]); seen=np.zeros_like(mask); seen[seed]=True
 while qd:
     i,j=qd.popleft()
     for di,dj in ((1,0),(-1,0),(0,1),(0,-1)):
         ni,nj=i+di,j+dj
         if 0<=ni<Hm and 0<=nj<Wm and mask[ni,nj] and not seen[ni,nj]:
             dot=pex[i,j]*pex[ni,nj]+pez[i,j]*pez[ni,nj]
             sign[ni,nj]=sign[i,j]*(1.0 if dot*sign[i,j]*sign[i,j]>=0 else -1.0)
             sign[ni,nj]=sign[i,j]*(1.0 if dot>=0 else -1.0)
             seen[ni,nj]=True; qd.append((ni,nj))
 pex*=sign; pez*=sign
 pex[~mask]=0; pez[~mask]=0
 # Poisson on masked grid, Neumann boundary
 idx=-np.ones(mask.shape,dtype=np.int64)
 cells=np.argwhere(mask); idx[mask]=np.arange(len(cells))
 import scipy.sparse as sp
 import scipy.sparse.linalg as spl
 rows=[];cols=[];vals=[];rhs=np.zeros(len(cells))
 for k,(i,j) in enumerate(cells):
     deg=0
     for di,dj,comp,sgn in ((1,0,'z',1),(-1,0,'z',-1),(0,1,'x',1),(0,-1,'x',-1)):
         ni,nj=i+di,j+dj
         if 0<=ni<Hm and 0<=nj<Wm and mask[ni,nj]:
             if pex[i,j]*pex[ni,nj]+pez[i,j]*pez[ni,nj] < 0:
                 continue   # frustrated pair: cut coupling -> clean seam
             deg+=1; rows.append(k); cols.append(idx[ni,nj]); vals.append(1.0)
             # flux of v across the face between cells (midpoint average)
             if comp=='z': rhs[k]+= sgn*0.5*(pez[i,j]+pez[ni,nj])
             else:         rhs[k]+= sgn*0.5*(pex[i,j]+pex[ni,nj])
     rows.append(k); cols.append(k); vals.append(-float(deg))
 L=sp.csr_matrix((vals,(rows,cols)),shape=(len(cells),len(cells)))
 # fix gauge: pin first cell
 L=L.tolil(); L[0,:]=0; L[0,0]=1; rhs[0]=0; L=L.tocsr()
 u_sol,info=spl.cg(L,rhs,rtol=1e-6,maxiter=4000)
 print("poisson info",info)
 U=np.zeros(mask.shape); U[mask]=u_sol
 u=U[iz,ix]*a.cell*0.001
with open(a.dst,"w") as f:
    f.write("o frame\n")
    for v in V: f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
    for uu in u: f.write(f"vt {uu:.6f} 0.0\n")
    for t in inv.reshape(-1,3):
        f.write(f"f {t[0]+1}/{t[0]+1} {t[1]+1}/{t[1]+1} {t[2]+1}/{t[2]+1}\n")
print(f"grid {W}x{H} verts={len(V)} wrote {a.dst} u[{u.min():.3f},{u.max():.3f}]")
