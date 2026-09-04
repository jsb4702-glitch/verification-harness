import bpy, sys, math, time, os
t0=time.time()
a=sys.argv[sys.argv.index("--")+1:]
# body_stl col_stl|none out az el dscale lens mode xe top rx ry samples
body_stl,col_stl,out=a[0],a[1],a[2]; az,el,ds,lens=float(a[3]),float(a[4]),float(a[5]),float(a[6])
mode=a[7]; xe,top=float(a[8]),float(a[9]); RX,RY=int(a[10]),int(a[11]); SMP=int(a[12])
bpy.ops.wm.read_factory_settings(use_empty=True)
S=0.001
def imp(p):
    before=set(bpy.data.objects[:])
    if p.lower().endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=p, forward_axis='Y', up_axis='Z')
    else:
        bpy.ops.wm.stl_import(filepath=p)
    new=[o for o in bpy.data.objects if o not in before]
    assert len(new)==1, f"import ambiguity {p}: {new}"
    return new[0]
o_body=imp(body_stl)
o_col=imp(col_stl) if col_stl!="none" else None
objs=[o for o in (o_col,o_body) if o is not None]
import numpy as np
mins=[];maxs=[]
for o in objs:
    n=len(o.data.vertices); arr=np.empty(n*3); o.data.vertices.foreach_get("co",arr); arr=arr.reshape(-1,3)
    mins.append(arr.min(0)); maxs.append(arr.max(0))
lo=np.min(mins,0); hi=np.max(maxs,0)
if mode=="floor":
    off=np.array([-(lo[0]+hi[0])/2, -(lo[1]+hi[1])/2, -lo[2]])
else:
    off=np.array([-xe, -(lo[1]+hi[1])/2, -top])
for o in objs:
    o.scale=(S,S,S); o.location=tuple(off*S)
    bpy.context.view_layer.objects.active=o; o.select_set(True)
    try: bpy.ops.object.shade_smooth_by_angle(angle=0.6)
    except Exception: bpy.ops.object.shade_smooth()
    o.select_set(False)
ctr=((lo+hi)/2+off)*S; H=(hi[2]-lo[2])*S; diag=float(np.linalg.norm(hi-lo))*S
def mat(name, base, rough, coat=0.0):
    m=bpy.data.materials.new(name); m.use_nodes=True; b=m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value=(*base,1); b.inputs["Metallic"].default_value=0.0
    b.inputs["Roughness"].default_value=rough
    if coat>0:
        try: b.inputs["Coat Weight"].default_value=coat; b.inputs["Coat Roughness"].default_value=0.15
        except Exception: pass
    return m
import os as _o
def carbon_mat(weave_mm):
    m=bpy.data.materials.new("carbon"); m.use_nodes=True; nt=m.node_tree; pb=nt.nodes["Principled BSDF"]
    pb.inputs["Base Color"].default_value=(0.006,0.006,0.007,1)
    pb.inputs["Metallic"].default_value=0.0
    try:
        pb.inputs["Coat Weight"].default_value=float(_o.environ.get("COAT_W","1.0")); pb.inputs["Coat Roughness"].default_value=float(_o.environ.get("COAT_R","0.015"))
        _ct=_o.environ.get("COAT_TINT","")
        if _ct:
            try: pb.inputs["Coat Tint"].default_value=(*[float(x) for x in _ct.split(",")],1)
            except Exception: pass
        pb.inputs["Specular IOR Level"].default_value=float(_o.environ.get("SPEC_LEVEL","0.25"))
    except Exception: pass
    co=nt.nodes.new("ShaderNodeTexCoord"); mp=nt.nodes.new("ShaderNodeMapping")
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    if _o.environ.get("FORGED3D","0")=="1":
        chip=float(_o.environ.get("CHIP_MM","12"))
        vor=nt.nodes.new("ShaderNodeTexVoronoi"); vor.feature='F1'; vor.inputs["Scale"].default_value=1.0/chip
        nt.links.new(mp.outputs["Vector"], vor.inputs["Vector"])
        vr=nt.nodes.new("ShaderNodeMapRange"); vr.inputs["To Min"].default_value=0.30; vr.inputs["To Max"].default_value=0.68
        nt.links.new(vor.outputs["Color"], vr.inputs["Value"]); nt.links.new(vr.outputs["Result"], pb.inputs["Roughness"])
        vc=nt.nodes.new("ShaderNodeMix"); vc.data_type='RGBA'
        vc.inputs[6].default_value=(0.0012,0.0012,0.0015,1); vc.inputs[7].default_value=(0.007,0.007,0.008,1)
        nt.links.new(vor.outputs["Color"], vc.inputs["Factor"]); nt.links.new(vc.outputs[2], pb.inputs["Base Color"])
        w1=nt.nodes.new("ShaderNodeTexWave"); w1.wave_type='BANDS'; w1.inputs["Scale"].default_value=2.5; w1.inputs["Distortion"].default_value=6.0
        nt.links.new(mp.outputs["Vector"], w1.inputs["Vector"])
        vb=nt.nodes.new("ShaderNodeBump"); vb.inputs["Strength"].default_value=0.18
        mixh=nt.nodes.new("ShaderNodeMix"); mixh.data_type='FLOAT'
        nt.links.new(vor.outputs["Distance"], mixh.inputs[2]); nt.links.new(w1.outputs["Fac"], mixh.inputs[3]); mixh.inputs["Factor"].default_value=0.5
        nt.links.new(mixh.outputs["Result"], vb.inputs["Height"]); nt.links.new(vb.outputs["Normal"], pb.inputs["Normal"])
        return m
    if weave_mm>0:
        cmix=nt.nodes.new("ShaderNodeMix"); cmix.data_type='RGBA'
        cmix.inputs[6].default_value=(0.0012,0.0012,0.0015,1); cmix.inputs[7].default_value=(0.006,0.006,0.007,1)
        cell=weave_mm  # object space = raw STL coords = mm
        ck=nt.nodes.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value=1.0/cell
        nt.links.new(mp.outputs["Vector"], ck.inputs["Vector"])
        w1=nt.nodes.new("ShaderNodeTexWave"); w1.wave_type='BANDS'; w1.bands_direction='X'
        w1.inputs["Scale"].default_value=1.0/cell*8; w1.inputs["Distortion"].default_value=1.5
        w2=nt.nodes.new("ShaderNodeTexWave"); w2.wave_type='BANDS'; w2.bands_direction='Y'
        w2.inputs["Scale"].default_value=1.0/cell*8; w2.inputs["Distortion"].default_value=1.5
        nt.links.new(mp.outputs["Vector"], w1.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], w2.inputs["Vector"])
        mix=nt.nodes.new("ShaderNodeMix"); mix.data_type='FLOAT'
        nt.links.new(ck.outputs["Fac"], mix.inputs["Factor"])
        nt.links.new(w1.outputs["Fac"], mix.inputs[2]); nt.links.new(w2.outputs["Fac"], mix.inputs[3])
        bump=nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value=float(_o.environ.get("WEAVE_BUMP","0.28"))
        nt.links.new(mix.outputs["Result"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], pb.inputs["Normal"])
        nt.links.new(ck.outputs["Fac"], cmix.inputs["Factor"]); nt.links.new(cmix.outputs[2], pb.inputs["Base Color"])
        rr=nt.nodes.new("ShaderNodeMapRange"); rr.inputs["From Min"].default_value=0; rr.inputs["From Max"].default_value=1
        rr.inputs["To Min"].default_value=0.40; rr.inputs["To Max"].default_value=0.70
        nt.links.new(ck.outputs["Fac"], rr.inputs["Value"]); nt.links.new(rr.outputs["Result"], pb.inputs["Roughness"])
        try:
            pb.inputs["Anisotropic"].default_value=0.2
            ar=nt.nodes.new("ShaderNodeMapRange"); ar.inputs["To Min"].default_value=0.0; ar.inputs["To Max"].default_value=0.25
            nt.links.new(ck.outputs["Fac"], ar.inputs["Value"]); nt.links.new(ar.outputs["Result"], pb.inputs["Anisotropic Rotation"])
        except Exception: pass
    else:
        w1=nt.nodes.new("ShaderNodeTexWave"); w1.wave_type='BANDS'; w1.bands_direction='X'
        _uds=float(_o.environ.get("UD_SCALE","1.6"))
        if _o.environ.get("UD_ALONG","0")=="1":
            w1.inputs["Scale"].default_value=_uds*1000.0; w1.inputs["Distortion"].default_value=0.3
            nt.links.new(co.outputs["UV"], w1.inputs["Vector"])
        else:
            w1.inputs["Scale"].default_value=_uds; w1.inputs["Distortion"].default_value=0.6
            nt.links.new(mp.outputs["Vector"], w1.inputs["Vector"])
        if _o.environ.get("UD_ALONG","0")!="1" or _o.environ.get("UD_FORGED","0")=="1":
            bump=nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value=float(_o.environ.get("WEAVE_BUMP","0.10"))
            nt.links.new(w1.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], pb.inputs["Normal"])
        elif True:
            ucol=nt.nodes.new("ShaderNodeMix"); ucol.data_type='RGBA'
            ucol.inputs[6].default_value=(0.001,0.001,0.0013,1); ucol.inputs[7].default_value=(0.010,0.010,0.012,1)
            nt.links.new(w1.outputs["Fac"], ucol.inputs["Factor"]); nt.links.new(ucol.outputs[2], pb.inputs["Base Color"])
        ur=nt.nodes.new("ShaderNodeMapRange"); ur.inputs["To Min"].default_value=0.28; ur.inputs["To Max"].default_value=0.78
        nt.links.new(w1.outputs["Fac"], ur.inputs["Value"]); nt.links.new(ur.outputs["Result"], pb.inputs["Roughness"])
        try: pb.inputs["Anisotropic"].default_value=0.3
        except Exception: pass
    return m
def preset_mat(name):
    m=bpy.data.materials.new("preset_"+name); m.use_nodes=True; nt=m.node_tree; pb=nt.nodes["Principled BSDF"]
    co=nt.nodes.new("ShaderNodeTexCoord"); mp=nt.nodes.new("ShaderNodeMapping")
    nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
    if name=="anodized":
        pb.inputs["Metallic"].default_value=1.0; pb.inputs["Roughness"].default_value=0.22
        lw=nt.nodes.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value=0.5
        cr=nt.nodes.new("ShaderNodeValToRGB")
        cr.color_ramp.elements[0].position=0.0; cr.color_ramp.elements[0].color=(0.55,0.12,0.55,1)
        cr.color_ramp.elements[1].position=1.0; cr.color_ramp.elements[1].color=(0.05,0.35,0.55,1)
        e=cr.color_ramp.elements.new(0.5); e.color=(0.9,0.55,0.15,1)
        nt.links.new(lw.outputs["Facing"], cr.inputs["Fac"]); nt.links.new(cr.outputs["Color"], pb.inputs["Base Color"])
    elif name=="chrome":
        pb.inputs["Metallic"].default_value=1.0; pb.inputs["Roughness"].default_value=0.04
        pb.inputs["Base Color"].default_value=(0.9,0.9,0.92,1)
    elif name=="gold":
        pb.inputs["Metallic"].default_value=1.0; pb.inputs["Roughness"].default_value=0.28
        pb.inputs["Base Color"].default_value=(0.82,0.55,0.18,1)
    elif name=="smoke_glass":
        pb.inputs["Transmission Weight"].default_value=1.0
        pb.inputs["Roughness"].default_value=0.06; pb.inputs["IOR"].default_value=1.45
        pb.inputs["Base Color"].default_value=(0.35,0.35,0.38,1)
    elif name=="wood":
        d=_o.environ.get("PBR_DIR","")
        def _f(sfx):
            for f in _o.listdir(d):
                if sfx in f and f.lower().endswith((".jpg",".png")): return _o.path.join(d,f)
        sc=float(_o.environ.get("PBR_SCALE","0.004"))
        mp.inputs["Scale"].default_value=(sc,sc,sc)
        tc=nt.nodes.new("ShaderNodeTexImage"); tc.image=bpy.data.images.load(_f("_Color")); tc.projection='BOX'; tc.projection_blend=0.3
        nt.links.new(mp.outputs["Vector"], tc.inputs["Vector"]); nt.links.new(tc.outputs["Color"], pb.inputs["Base Color"])
        tr=nt.nodes.new("ShaderNodeTexImage"); tr.image=bpy.data.images.load(_f("_Roughness")); tr.image.colorspace_settings.name="Non-Color"; tr.projection='BOX'; tr.projection_blend=0.3
        nt.links.new(mp.outputs["Vector"], tr.inputs["Vector"]); nt.links.new(tr.outputs["Color"], pb.inputs["Roughness"])
        tn=nt.nodes.new("ShaderNodeTexImage"); tn.image=bpy.data.images.load(_f("_NormalGL")); tn.image.colorspace_settings.name="Non-Color"; tn.projection='BOX'; tn.projection_blend=0.3
        nm=nt.nodes.new("ShaderNodeNormalMap"); nm.inputs["Strength"].default_value=0.6
        nt.links.new(mp.outputs["Vector"], tn.inputs["Vector"]); nt.links.new(tn.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], pb.inputs["Normal"])
        try: pb.inputs["Coat Weight"].default_value=0.5; pb.inputs["Coat Roughness"].default_value=0.08
        except Exception: pass
    elif name=="ceramic":
        pb.inputs["Base Color"].default_value=(0.90,0.90,0.88,1); pb.inputs["Roughness"].default_value=0.22
        try: pb.inputs["Coat Weight"].default_value=0.5; pb.inputs["Coat Roughness"].default_value=0.05
        except Exception: pass
    elif name=="rubber_coral":
        _rgb=[float(x) for x in _o.environ.get("RUBBER_RGB","0.72,0.16,0.12").split(",")]
        pb.inputs["Base Color"].default_value=(*_rgb,1); pb.inputs["Roughness"].default_value=0.85
        pb.inputs["Specular IOR Level"].default_value=0.2
    elif name=="flake":
        pb.inputs["Metallic"].default_value=0.95; pb.inputs["Base Color"].default_value=(0.05,0.06,0.10,1)
        vor=nt.nodes.new("ShaderNodeTexVoronoi"); vor.feature='F1'; vor.inputs["Scale"].default_value=4.0
        nt.links.new(mp.outputs["Vector"], vor.inputs["Vector"])
        rr=nt.nodes.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value=0.05; rr.inputs["To Max"].default_value=0.45
        nt.links.new(vor.outputs["Color"], rr.inputs["Value"]); nt.links.new(rr.outputs["Result"], pb.inputs["Roughness"])
        vb=nt.nodes.new("ShaderNodeBump"); vb.inputs["Strength"].default_value=0.06
        nt.links.new(vor.outputs["Distance"], vb.inputs["Height"]); nt.links.new(vb.outputs["Normal"], pb.inputs["Normal"])
        try: pb.inputs["Coat Weight"].default_value=1.0; pb.inputs["Coat Roughness"].default_value=0.03
        except Exception: pass
    return m
def apply_decal(m):
    dp=_o.environ.get("DECAL_IMG","")
    if not dp: return
    nt=m.node_tree; pb=nt.nodes["Principled BSDF"]
    # top-strip projection: U=(y-y0)/w, V=(x-x0)/h, top faces only
    y0=float(_o.environ.get("DECAL_Y0","-200")); w=float(_o.environ.get("DECAL_W","400"))
    x0=float(_o.environ.get("DECAL_X0","-52")); h=float(_o.environ.get("DECAL_H","80"))
    co2=nt.nodes.new("ShaderNodeTexCoord"); sep=nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(co2.outputs["Object"], sep.inputs["Vector"])
    mu=nt.nodes.new("ShaderNodeMath"); mu.operation='SUBTRACT'; mu.inputs[1].default_value=y0
    mus=nt.nodes.new("ShaderNodeMath"); mus.operation='DIVIDE'; mus.inputs[1].default_value=w
    nt.links.new(sep.outputs["Y"], mu.inputs[0]); nt.links.new(mu.outputs[0], mus.inputs[0])
    mv=nt.nodes.new("ShaderNodeMath"); mv.operation='SUBTRACT'; mv.inputs[1].default_value=x0
    mvs=nt.nodes.new("ShaderNodeMath"); mvs.operation='DIVIDE'; mvs.inputs[1].default_value=h
    nt.links.new(sep.outputs["X"], mv.inputs[0]); nt.links.new(mv.outputs[0], mvs.inputs[0])
    cmb=nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(mus.outputs[0], cmb.inputs["X"]); nt.links.new(mvs.outputs[0], cmb.inputs["Y"])
    ti=nt.nodes.new("ShaderNodeTexImage"); ti.image=bpy.data.images.load(dp); ti.extension='CLIP'
    nt.links.new(cmb.outputs["Vector"], ti.inputs["Vector"])
    # top-face mask: geometry normal z
    geo=nt.nodes.new("ShaderNodeNewGeometry"); gsep=nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], gsep.inputs["Vector"])
    gt=nt.nodes.new("ShaderNodeMath"); gt.operation='GREATER_THAN'; gt.inputs[1].default_value=0.15
    nt.links.new(gsep.outputs["Z"], gt.inputs[0])
    fac=nt.nodes.new("ShaderNodeMath"); fac.operation='MULTIPLY'
    nt.links.new(ti.outputs["Alpha"], fac.inputs[0]); nt.links.new(gt.outputs[0], fac.inputs[1])
    # mix over whatever feeds Base Color
    old_link=None
    for l in nt.links:
        if l.to_node==pb and l.to_socket.name=="Base Color": old_link=l; break
    mixd=nt.nodes.new("ShaderNodeMix"); mixd.data_type='RGBA'
    if old_link:
        nt.links.new(old_link.from_socket, mixd.inputs[6]); nt.links.remove(old_link)
    else:
        mixd.inputs[6].default_value=pb.inputs["Base Color"].default_value[:]
    nt.links.new(ti.outputs["Color"], mixd.inputs[7])
    nt.links.new(fac.outputs[0], mixd.inputs["Factor"])
    nt.links.new(mixd.outputs[2], pb.inputs["Base Color"])
    # decal gloss: pull roughness down where decal (gloss-on-matte reads)
    old_r=None
    for l in nt.links:
        if l.to_node==pb and l.to_socket.name=="Roughness": old_r=l; break
    mixr=nt.nodes.new("ShaderNodeMix"); mixr.data_type='FLOAT'
    if old_r:
        nt.links.new(old_r.from_socket, mixr.inputs[2]); nt.links.remove(old_r)
    else:
        mixr.inputs[2].default_value=pb.inputs["Roughness"].default_value
    mixr.inputs[3].default_value=float(_o.environ.get("DECAL_ROUGH","0.07"))
    nt.links.new(fac.outputs[0], mixr.inputs["Factor"])
    nt.links.new(mixr.outputs[0], pb.inputs["Roughness"])
    sp2=_o.environ.get("DECAL_SIDE_IMG","")
    if sp2:
        sx0=float(_o.environ.get("SIDE_X0","-85")); sw=float(_o.environ.get("SIDE_W","60"))
        sz0=float(_o.environ.get("SIDE_Z0","-65")); sh=float(_o.environ.get("SIDE_H","60"))
        su=nt.nodes.new("ShaderNodeMath"); su.operation='SUBTRACT'; su.inputs[1].default_value=sx0
        sus=nt.nodes.new("ShaderNodeMath"); sus.operation='DIVIDE'; sus.inputs[1].default_value=sw
        nt.links.new(sep.outputs["X"], su.inputs[0]); nt.links.new(su.outputs[0], sus.inputs[0])
        sv=nt.nodes.new("ShaderNodeMath"); sv.operation='SUBTRACT'; sv.inputs[1].default_value=sz0
        svs=nt.nodes.new("ShaderNodeMath"); svs.operation='DIVIDE'; svs.inputs[1].default_value=sh
        nt.links.new(sep.outputs["Z"], sv.inputs[0]); nt.links.new(sv.outputs[0], svs.inputs[0])
        scmb=nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(sus.outputs[0], scmb.inputs["X"]); nt.links.new(svs.outputs[0], scmb.inputs["Y"])
        sti=nt.nodes.new("ShaderNodeTexImage"); sti.image=bpy.data.images.load(sp2); sti.extension='CLIP'
        nt.links.new(scmb.outputs["Vector"], sti.inputs["Vector"])
        sab=nt.nodes.new("ShaderNodeMath"); sab.operation='ABSOLUTE'
        nt.links.new(gsep.outputs["Y"], sab.inputs[0])
        sgt=nt.nodes.new("ShaderNodeMath"); sgt.operation='GREATER_THAN'; sgt.inputs[1].default_value=0.45
        nt.links.new(sab.outputs[0], sgt.inputs[0])
        sfac=nt.nodes.new("ShaderNodeMath"); sfac.operation='MULTIPLY'
        nt.links.new(sti.outputs["Alpha"], sfac.inputs[0]); nt.links.new(sgt.outputs[0], sfac.inputs[1])
        old_l=None
        for l in nt.links:
            if l.to_node==pb and l.to_socket.name=="Base Color": old_l=l; break
        smix=nt.nodes.new("ShaderNodeMix"); smix.data_type='RGBA'
        nt.links.new(old_l.from_socket, smix.inputs[6]); nt.links.remove(old_l)
        nt.links.new(sti.outputs["Color"], smix.inputs[7]); nt.links.new(sfac.outputs[0], smix.inputs["Factor"])
        nt.links.new(smix.outputs[2], pb.inputs["Base Color"])
        print("SIDE_DECAL_OK", sp2)
    print("DECAL_OK", dp)
_mode=_o.environ.get("MAT_MODE","")
if _mode=="preset":
    _pm=preset_mat(_o.environ.get("MAT_PRESET","chrome"))
    o_body.data.materials.clear(); o_body.data.materials.append(_pm)
    if o_col is not None:
        o_col.data.materials.clear(); o_col.data.materials.append(_pm)
    print("MAT_OK preset")
elif _mode=="carbon":
    _wv=float(_o.environ.get("WEAVE_MM","1.6"))
    _bm=carbon_mat(_wv); apply_decal(_bm)
    o_body.data.materials.clear(); o_body.data.materials.append(_bm)
    if o_col is not None:
        o_col.data.materials.clear()
        _cp=_o.environ.get("COL_PRESET","")
        o_col.data.materials.append(preset_mat(_cp) if _cp else carbon_mat(_wv))
    print("MAT_OK carbon weave=%.1fmm"%_wv)
else:
    _pc=[float(x) for x in _o.environ.get("PAINT_COLOR","0.008,0.008,0.009").split(",")]
    _ac=[float(x) for x in _o.environ.get("ABS_COLOR","0.011,0.011,0.012").split(",")]
    if o_col is not None:
        o_col.data.materials.clear(); o_col.data.materials.append(mat("paint",tuple(_pc),float(_o.environ.get("PAINT_ROUGH","0.22")),0.8))
    o_body.data.materials.clear(); o_body.data.materials.append(mat("abs",tuple(_ac),float(_o.environ.get("ABS_ROUGH","0.62"))))
    print("MAT_OK")
if mode=="floor":
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0,0,0)); gp=bpy.context.object
    gm=mat("floor",(0.86,0.86,0.87),1.0); gp.data.materials.append(gm)
else:
    bpy.ops.mesh.primitive_cube_add(size=1); blk=bpy.context.object
    blk.scale=(1.2,1.2,1.2); blk.location=(1.2/2, 0, -1.2/2)
    bm=bpy.data.materials.new("blk"); bm.use_nodes=True; nt=bm.node_tree; pb=nt.nodes["Principled BSDF"]
    import os as _os
    _pbr=_os.environ.get("PBR_DIR","")
    if _pbr and _os.path.isdir(_pbr):
        def _find(sfx):
            for f in _os.listdir(_pbr):
                if sfx in f and f.lower().endswith((".jpg",".png")): return _os.path.join(_pbr,f)
            return None
        _map=nt.nodes.new("ShaderNodeMapping"); _uv=nt.nodes.new("ShaderNodeTexCoord")
        _sc=float(_os.environ.get("PBR_SCALE","1.5"))
        _map.inputs["Scale"].default_value=(_sc,_sc,_sc)
        nt.links.new(_uv.outputs["UV"], _map.inputs["Vector"])
        _c=_find("_Color");
        if _c:
            _tc=nt.nodes.new("ShaderNodeTexImage"); _tc.image=bpy.data.images.load(_c)
            nt.links.new(_map.outputs["Vector"], _tc.inputs["Vector"]); nt.links.new(_tc.outputs["Color"], pb.inputs["Base Color"])
        _r=_find("_Roughness")
        if _r:
            _tr=nt.nodes.new("ShaderNodeTexImage"); _tr.image=bpy.data.images.load(_r); _tr.image.colorspace_settings.name="Non-Color"
            nt.links.new(_map.outputs["Vector"], _tr.inputs["Vector"]); nt.links.new(_tr.outputs["Color"], pb.inputs["Roughness"])
        _n=_find("_NormalGL")
        if _n:
            _tn=nt.nodes.new("ShaderNodeTexImage"); _tn.image=bpy.data.images.load(_n); _tn.image.colorspace_settings.name="Non-Color"
            _nm=nt.nodes.new("ShaderNodeNormalMap"); _nm.inputs["Strength"].default_value=0.8
            nt.links.new(_map.outputs["Vector"], _tn.inputs["Vector"]); nt.links.new(_tn.outputs["Color"], _nm.inputs["Color"]); nt.links.new(_nm.outputs["Normal"], pb.inputs["Normal"])
        print("PBR_OK", _pbr)
    else:
        pb.inputs["Base Color"].default_value=(0.72,0.72,0.73,1); pb.inputs["Roughness"].default_value=0.95
        tex=nt.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value=900; tex.inputs["Detail"].default_value=3
        bump=nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value=0.12
        nt.links.new(tex.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], pb.inputs["Normal"])
    blk.data.materials.append(bm)
w=bpy.data.worlds.new("w"); bpy.context.scene.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.85,0.85,0.86,1)
w.node_tree.nodes["Background"].inputs[1].default_value=float(os.environ.get("WORLD_STRENGTH","0.30"))
def area(name,loc,energy,size):
    l=bpy.data.lights.new(name,'AREA'); l.energy=energy; l.size=size
    o=bpy.data.objects.new(name,l); o.location=loc; bpy.context.collection.objects.link(o)
    d=o.location; o.rotation_euler=(math.atan2(math.hypot(d.x,d.y),d.z-ctr[2]),0,math.atan2(d.y,d.x)+math.pi/2)
area("key",(0.9,-0.5,1.4),float(os.environ.get("KEY_W","55")),float(os.environ.get("KEY_SIZE","1.5")))
area("fill",(-1.1,-0.8,0.8),float(os.environ.get("FILL_W","18")),1.4)
area("back",(0.1,1.2,1.1),float(os.environ.get("BACK_W","17")),1.2)
# raking accent along -y face for engraved text (low, from left)
rk=bpy.data.lights.new("rake",'AREA'); rk.energy=7; rk.size=0.25
ro=bpy.data.objects.new("rake",rk); ro.location=(ctr[0]-0.65,-0.45,ctr[2]+0.18); bpy.context.collection.objects.link(ro)
ro.rotation_euler=(math.radians(80),0,math.radians(-55))
tgt=bpy.data.objects.new("tgt",None); tgt.location=tuple(ctr); bpy.context.collection.objects.link(tgt)
cam=bpy.data.cameras.new("c"); cam.lens=lens
co=bpy.data.objects.new("cam",cam); bpy.context.collection.objects.link(co); bpy.context.scene.camera=co
d=diag*ds; azr=math.radians(az); elr=math.radians(el)
co.location=(ctr[0]+d*math.cos(elr)*math.cos(azr), ctr[1]+d*math.cos(elr)*math.sin(azr), ctr[2]+d*math.sin(elr))
tr=co.constraints.new('TRACK_TO'); tr.target=tgt; tr.track_axis='TRACK_NEGATIVE_Z'; tr.up_axis='UP_Y'
sc=bpy.context.scene; sc.render.engine='CYCLES'; sc.cycles.samples=SMP; sc.cycles.use_denoising=True; sc.cycles.device='CPU'
sc.render.resolution_x=RX; sc.render.resolution_y=RY
sc.view_settings.look='AgX - Base Contrast'
sc.render.filepath=out; sc.render.image_settings.file_format='PNG'
bpy.ops.render.render(write_still=True)
print(f"RENDER_OK t={time.time()-t0:.1f}s -> {out}")
