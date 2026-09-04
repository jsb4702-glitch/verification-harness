#!/usr/bin/env python3
"""Fetch CC0 PBR texture set. WHITELIST: ambientCG, Poly Haven ONLY (license-verified CC0).
Usage: pbr_fetch.py "wood" [--source acg|ph] [--res 2K] [--cache DIR]
Prints the extracted folder path (Color/Roughness/NormalGL maps) on success."""
import sys, os, json, argparse, urllib.request, zipfile, re
UA={"User-Agent":"3d-render-skill/1.0 (Claude Code local render pipeline; personal use)"}
def get(url, binary=False):
    req=urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read() if binary else json.loads(r.read().decode())
def fetch_acg(q, res, cache):
    d=get(f"https://ambientcg.com/api/v2/full_json?q={urllib.parse.quote(q)}&type=Material&limit=5&include=downloadData")
    for a in d.get("foundAssets",[]):
        aid=a.get("assetId")
        try:
            dls=a["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
        except (KeyError,TypeError): continue
        want=f"{res}-JPG"
        for dl in dls:
            if dl.get("attribute")==want:
                out=os.path.join(cache,f"{aid}_{res}")
                if os.path.isdir(out) and os.listdir(out): return out
                zp=os.path.join(cache,f"{aid}_{res}.zip")
                data=get(dl.get("downloadLink") or dl.get("fullDownloadPath"), binary=True)
                os.makedirs(cache,exist_ok=True); open(zp,"wb").write(data)
                zipfile.ZipFile(zp).extractall(out); os.remove(zp)
                return out
    return None
def fetch_ph(q, res, cache):
    assets=get("https://api.polyhaven.com/assets?type=textures")
    ql=q.lower()
    cand=[k for k,v in assets.items() if ql in k.lower() or any(ql in t for t in v.get("tags",[]))]
    if not cand: return None
    aid=sorted(cand, key=lambda k:-assets[k].get("download_count",0))[0]
    files=get(f"https://api.polyhaven.com/files/{aid}")
    r=res.lower().replace("k","k")
    out=os.path.join(cache,f"ph_{aid}_{res}")
    if os.path.isdir(out) and os.listdir(out): return out
    os.makedirs(out,exist_ok=True)
    picks={"Diffuse":"_Color","Rough":"_Roughness","nor_gl":"_NormalGL"}
    got=0
    for key,sfx in picks.items():
        node=files.get(key,{}).get(r) or files.get(key,{}).get("2k")
        if not node: continue
        fmt=node.get("jpg") or node.get("png")
        if not fmt: continue
        data=get(fmt["url"], binary=True)
        ext=".jpg" if "jpg" in (fmt["url"])[-5:] else ".png"
        open(os.path.join(out,f"{aid}{sfx}{ext}"),"wb").write(data); got+=1
    return out if got>=2 else None
ap=argparse.ArgumentParser()
ap.add_argument("query"); ap.add_argument("--source",choices=["acg","ph","auto"],default="auto")
ap.add_argument("--res",default="2K"); ap.add_argument("--cache",default=os.path.expanduser("~/.cache/pbr-textures"))
a=ap.parse_args()
res=None
if a.source in ("acg","auto"):
    try: res=fetch_acg(a.query,a.res,a.cache)
    except Exception as e: print(f"acg fail: {e}", file=sys.stderr)
if res is None and a.source in ("ph","auto"):
    try: res=fetch_ph(a.query,a.res,a.cache)
    except Exception as e: print(f"ph fail: {e}", file=sys.stderr)
if res: print(res)
else: print("NOT_FOUND", file=sys.stderr); sys.exit(1)
