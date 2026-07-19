# API Recipes by Feature Group

Implementation recipes for the SpeedWorks-style feature groups: **batch
operations** and **modeling**. Each entry gives the interop object, the call
sequence, and the gotcha. Method *names* are real; confirm exact parameter lists
and enum members against the local SOLIDWORKS API Help — signatures drift across
versions (see `pitfalls.md`).

All geometry is in **meters/radians** (SI internal units).

## Contents
- [Batch file traversal (the engine under every batch tool)](#batch-traversal)
- [Custom properties](#custom-properties)
- [Material](#material)
- [Batch export — PDF / DWG / STEP / IGES](#batch-export)
- [Rebuild](#rebuild)
- [Configurations](#configurations)
- [Component / assembly traversal](#component-traversal)
- [Primitives (box, cylinder, cone, sphere, torus)](#primitives)
- [Coordinate systems](#coordinate-systems)
- [Batch points from CSV/TXT](#batch-points)
- [Batch holes from 2D coordinates](#batch-holes)
- [2D → 3D sketch conversion](#sketch-3d)
- [Mirror part](#mirror-part)
- [Performance toggles ("booster")](#performance-toggles)

---

## Batch traversal

Every batch tool ("일괄 ...") is the same shape: enumerate files, open each
**silently**, do the work, save, close, release. Open invisibly to avoid UI churn
and speed up runs.

```csharp
// Speed: open without visible window, suppress dialogs.
int errs = 0, warns = 0;
foreach (string path in filePaths)
{
    int type = path.EndsWith(".sldasm", StringComparison.OrdinalIgnoreCase)
        ? (int)swDocumentTypes_e.swDocASSEMBLY
        : path.EndsWith(".slddrw", StringComparison.OrdinalIgnoreCase)
            ? (int)swDocumentTypes_e.swDocDRAWING
            : (int)swDocumentTypes_e.swDocPART;

    var model = (IModelDoc2)_swApp.OpenDoc6(
        path, type,
        (int)swOpenDocOptions_e.swOpenDocOptions_Silent,
        "", ref errs, ref warns);
    if (model == null) continue;            // log errs and move on

    try
    {
        // ... per-file work ...
        model.Save3((int)swSaveAsOptions_e.swSaveAsOptions_Silent, ref errs, ref warns);
    }
    finally
    {
        _swApp.CloseDoc(model.GetTitle());
        Marshal.ReleaseComObject(model);    // critical in long loops
    }
}
```

> `swOpenDocOptions_Silent` + `swOpenDocOptions_ReadOnly` (bitwise-or) for
> read-only scans. Always `CloseDoc` + `ReleaseComObject`, or SOLIDWORKS keeps
> files locked and leaks memory across a few hundred files.

---

## Custom properties

Object: `IModelDocExtension.CustomPropertyManager[configName]`
(`""` = file-level/document properties; a config name = config-specific).

```csharp
CustomPropertyManager cpm = model.Extension.CustomPropertyManager[""];

// Add or overwrite. swCustomPropertyType: swCustomInfoText, swCustomInfoNumber...
cpm.Add3("DrawnBy", (int)swCustomInfoType_e.swCustomInfoText, "SBJ",
         (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue);

// Read: value vs. resolved value (evaluated expression).
string valOut, resolvedOut; bool wasResolved, link;
cpm.Get6("Material", false, out valOut, out resolvedOut, out wasResolved, out link);

cpm.Delete2("ObsoleteProp");
string[] names = (string[])cpm.GetNames();
```

> "Copy properties" and "property-tab management" are this same API applied across
> a batch. For numeric/date props use the matching `swCustomInfoType_e`. Setting a
> property to an equation string (e.g. `"\"SW-Mass@...\""`) makes it a linked
> resolved value.

---

## Material

Object: `IPartDoc.SetMaterialPropertyName2(configName, database, materialName)`.
The database is the `.sldmat` file name without extension (e.g.
`"solidworks materials"` or a custom DB).

```csharp
var part = model as IPartDoc;
part.SetMaterialPropertyName2("", "solidworks materials", "AISI 1020");

string db;
string current = part.GetMaterialPropertyName2("", out db);
```

> Custom material DBs must be registered in SOLIDWORKS options or referenced by
> full path, else the apply silently fails. Verify with `GetMaterialPropertyName2`.

---

## Batch export

Object: `IModelDocExtension.SaveAs3` (newer) or `SaveAs`. Format is inferred from
the file extension. PDF and DWG of **drawings** need the drawing open.

```csharp
// PDF (works for drawings and 3D). Optional PDF export data lets you pick sheets.
model.Extension.SaveAs3(
    @"C:\out\PART-001.PDF",
    (int)swSaveAsVersion_e.swSaveAsCurrentVersion,
    (int)swSaveAsOptions_e.swSaveAsOptions_Silent,
    null, null, ref errs, ref warns);

// STEP / IGES / Parasolid: just change the extension.
model.Extension.SaveAs3(@"C:\out\PART-001.STEP", 0,
    (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref errs, ref warns);
```

```csharp
// DWG/DXF from a drawing — finer control via the dedicated exporter.
var draw = model as IDrawingDoc;
// SaveToFile3/exports vary by version; the simple path is SaveAs3 with ".DWG".
model.Extension.SaveAs3(@"C:\out\PART-001.DWG", 0,
    (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, ref errs, ref warns);
```

> STEP protocol (AP203/214/242) and PDF sheet selection are set via SOLIDWORKS
> *export options* (`_swApp.SetUserPreferenceIntegerValue(swUserPreferenceIntegerValue_e.swStepAP, ...)`)
> before saving, since `SaveAs3`'s export-data arg is format-specific. Stamps /
> watermarks on PDF output are not a single API call — they're added by drawing a
> note/title-block annotation before export, or post-processing the PDF.

---

## Rebuild

```csharp
model.ForceRebuild3(false);    // false = rebuild this doc (true = top-level only)
// or model.EditRebuild3();    // rebuild + update, returns bool success
```

> For "batch rebuild incl. references", open with references and `ForceRebuild3`,
> then save. Large assemblies: rebuild can be slow — pair with performance toggles.

---

## Configurations

Object: `IConfigurationManager` and `IModelDoc2.GetConfigurationNames()`.

```csharp
string[] cfgs = (string[])model.GetConfigurationNames();
IConfiguration cfg = model.GetConfigurationByName(cfgs[0]);

model.AddConfiguration3("Variant-B", "comment", "altName",
    (int)swConfigurationOptions2_e.swConfigOption_DontShowPartsInBOM);
model.DeleteConfiguration2("Variant-B");
```

> "Configuration manager" (split/clean configs) walks `GetConfigurationNames`,
> reads derived/parent links via `IConfiguration.GetParent`, and deletes unused
> ones. Don't delete the active config without switching first
> (`model.ShowConfiguration2`).

---

## Component traversal

Object: `IAssemblyDoc` + `IComponent2`. Used by "part explorer", show/hide,
suppress, etc.

```csharp
var asm = model as IAssemblyDoc;
object[] comps = (object[])asm.GetComponents(false);   // false = all levels
foreach (IComponent2 c in comps)
{
    if (c.IsSuppressed()) continue;
    c.Visible = (int)swComponentVisibilityState_e.swComponentHidden;  // hide
    // c.SetSuppression2((int)swComponentSuppressionState_e.swComponentSuppressed);
    IModelDoc2 cm = c.GetModelDoc2();   // the component's own doc, for property work
}
```

> `GetComponents(true)` = top level only. Suppression/visibility changes need the
> assembly rebuilt + saved to persist.

---

## Primitives

No single "make box" API — sketch a rectangle/circle then extrude or revolve.
Object: `IFeatureManager.FeatureExtrusion3` / `FeatureRevolve2`,
`ISketchManager` for the profile.

```csharp
var sm = model.SketchManager;
model.Extension.SelectByID2("Front Plane", "PLANE", 0,0,0, false, 0, null, 0);
sm.InsertSketch(true);
sm.CreateCornerRectangle(0,0,0, 0.1,0.1,0);   // 100×100 mm at origin (SI!)
sm.InsertSketch(true);                          // exit sketch (now selected)

// Blind extrude 0.05 m. Many bool flags — confirm against API help per version.
IFeature boss = model.FeatureManager.FeatureExtrusion3(
    true, false, false,
    (int)swEndConditions_e.swEndCondBlind, 0,
    0.05, 0.0,                       // depth1, depth2
    false, false, false, false, 0,0,
    false, false, false, false, true, true, true,
    0, 0, false);
```

- **Box** = rectangle + blind extrude.
- **Cylinder** = circle (`CreateCircleByRadius`) + blind extrude.
- **Cone** = circle + extrude with draft angle, or revolve a triangle.
- **Sphere** = revolve a semicircle 360° about a centerline.
- **Torus** = revolve an offset circle 360° about a centerline.

> `FeatureExtrusion3` is signature-heavy and version-sensitive — the safest move
> is to record a macro of one extrude on the user's machine and copy its exact
> argument list, or look it up in API Help. Flag this to the user.

---

## Coordinate systems

Object: `IFeatureManager.InsertCoordinateSystem` driven by prior selections
(origin point + two axis directions), or via `ICoordinateSystemFeatureData`.

```csharp
// Selection-driven: select origin vertex, then X then Y references, marked.
model.Extension.SelectByID2("", "EXTSKETCHPOINT", x,y,z, false,
    1 /*mark: origin*/, null, 0);
// ...select X-axis ref with mark 2, Y-axis ref with mark 4 ...
IFeature csys = model.FeatureManager.InsertCoordinateSystem(false, false, false);
```

> For "parametric coordinate system" (type in position + angles), create at origin
> then drive its placement with the feature's transform, or build the reference
> geometry (point + axes) from typed values first. Marks encode which selection is
> origin/X/Y — get them wrong and the axes come out swapped.

---

## Batch points

Read TXT/CSV, create points on a selected plane or in a 3D sketch. Object:
`ISketchManager.CreatePoint` (2D, active sketch) or `Insert3DSketch` +
`CreatePoint` for free-space points.

```csharp
sm.Insert3DSketch(true);
foreach (var (x,y,z) in ParseCsv(path))      // parse in mm, convert here
    sm.CreatePoint(x/1000.0, y/1000.0, z/1000.0);
sm.Insert3DSketch(true);   // exit
```

> Reference points (not sketch points) = `IFeatureManager.InsertReferencePoint`.
> Pick based on what the user needs downstream (sketch points for patterns/holes,
> ref points for mates/measurements).

---

## Batch holes

From a 2D coordinate list. Two routes:
1. **Simple holes**: sketch circles at each coord on a face, then cut-extrude
   through-all (one feature, fast).
2. **Hole Wizard** (counterbore/countersink/tapped): `IFeatureManager.HoleWizard5`.

```csharp
// Route 1: sketch circles + single through-all cut.
model.Extension.SelectByID2("", "FACE", fx,fy,fz, false,0,null,0);
sm.InsertSketch(true);
foreach (var (x,y) in coords) sm.CreateCircleByRadius(x,y,0, dia/2.0);
sm.InsertSketch(true);
model.FeatureManager.FeatureCut4(true, false, false,
    (int)swEndConditions_e.swEndCondThroughAll, 0, 0,0,
    false,false,false,false,0,0,false,false,false,false,false,true,true,true,true,
    false,0,0,false, false);
```

> `HoleWizard5` needs a sketch of placement points pre-selected and a long
> standard/type/size argument set — pull the exact enum values from API Help; they
> encode the hole standard and fastener size and are easy to get wrong.

---

## Sketch 3D

"2D → 3D sketch": convert existing 2D sketch entities into a 3D sketch. There's no
one-shot converter — copy the entities into a new 3D sketch, or use
`IModelDoc2.SketchManager` to insert a 3D sketch and recreate segments. For simple
cases, selecting the sketch and `Insert > 3D Sketch` then converting entities
works; programmatically, read segment endpoints and recreate them inside
`Insert3DSketch`. Flag to the user that this one is fiddly and worth prototyping
with a recorded macro.

---

## Mirror part

Creates a new derived (opposite-hand) part from an existing one. This is a
*derived part* operation, not assembly mirror. API path:
`IModelDoc2.InsertMirrorPart2` / the mirror-part feature, driven by a selected
plane in the source part. Confirm the exact method name/signature in API Help for
the installed version — it has changed across releases. For "batch mirror", loop
the source files, select the mirror plane, create the mirrored derived part, save
as a new file.

---

## Performance toggles

"Booster" = flip SOLIDWORKS system options for speed during batch runs, then
restore. Object: `ISldWorks.SetUserPreferenceToggle` /
`SetUserPreferenceIntegerValue`.

```csharp
// Example toggles to save/restore around a batch:
bool prevVerify = _swApp.GetUserPreferenceToggle(
    (int)swUserPreferenceToggle_e.swEnablePerformanceVerification);
_swApp.SetUserPreferenceToggle(
    (int)swUserPreferenceToggle_e.swEnablePerformanceVerification, false);
// ... run batch ...
_swApp.SetUserPreferenceToggle(
    (int)swUserPreferenceToggle_e.swEnablePerformanceVerification, prevVerify);
```

> Always snapshot the user's current values and restore them in a `finally` —
> leaving a user's options changed after a batch run is a support-ticket
> generator. Useful toggles: image quality, verification on rebuild, RealView,
> auto-rebuild of drawings.
