---
name: solidworks-addin
description: >-
  Build AND debug SOLIDWORKS API automation in C#/.NET (or VBA macros) — scaffold
  ISwAddin add-ins, register CommandManager tabs/buttons, handle COM registration,
  drive swApp from standalone scripts, and implement or fix batch-automation and
  modeling code (custom properties, materials, batch PDF/STEP/DWG export, geometry
  creation, coordinate systems, hole/point generation from CSV, assembly/component
  traversal, mirror parts). Use this skill whenever the user wants to automate
  SOLIDWORKS, write OR debug a SOLIDWORKS macro/add-in/automation script, extend
  SOLIDWORKS with a custom tool or button, look up or fix a SOLIDWORKS API call
  (e.g. FeatureExtrusion, HoleWizard, SaveAs, SelectByID2, ForceRebuild, or any
  ISldWorks/IModelDoc2/IPartDoc/IAssemblyDoc/IDrawingDoc method), figure out why
  API-created geometry is wrong (e.g. dimensions off by ~1000× from SI-unit
  mistakes) or why a CommandManager callback/button does nothing, traverse or
  batch-edit components in an assembly programmatically, batch-process
  SLDPRT/SLDASM/SLDDRW files, or clone utility features like those in SpeedWorks.
  Trigger even when the user just says "SW macro", "swApp", "솔리드웍스
  애드인/매크로/자동화/스크립트", or names an interop type — and even for short
  debugging questions about existing SOLIDWORKS API code. This covers SOLIDWORKS
  only — not AutoCAD, Inventor, Fusion 360, NX, or non-SOLIDWORKS COM/Office
  add-ins.
---

# SOLIDWORKS Add-in Development (C#/.NET)

This skill builds **SOLIDWORKS API add-ins** — DLLs that load inside SOLIDWORKS,
add buttons to the CommandManager, and automate work through the API. Use it for
both full add-ins and standalone automation (macros, batch scripts that drive
`swApp`).

## What an add-in actually is

A SOLIDWORKS add-in is a COM-visible .NET class that implements `ISwAddin`
(`SolidWorks.Interop.swpublished.SwAddin`). SOLIDWORKS discovers it via registry
keys, calls `ConnectToSW` on load, and the add-in then registers UI and responds
to callbacks. Everything else — creating geometry, editing properties, exporting
files — is plain API calls against the interop objects SOLIDWORKS hands you.

The model to keep in your head:

```
SOLIDWORKS process
  └─ loads your DLL (COM, registry-registered)
       └─ ConnectToSW(swApp, cookie)   ← entry point, you get ISldWorks
            ├─ register CommandManager group + buttons (each button → callback name)
            └─ user clicks button → SOLIDWORKS calls your callback method by name
                 └─ callback does API work on the active IModelDoc2
```

## Hard constraints (state these to the user up front if relevant)

- **Requires a licensed SOLIDWORKS install.** The API is COM in-process — there
  is no standalone engine. Code can only be built referencing the interop
  assemblies, and only *runs* on a machine with SOLIDWORKS. You cannot test
  execution in this environment; you produce code the user runs on their CAD box.
- **Windows + .NET Framework**, x64. Target **.NET Framework 4.7.1+** (matches
  the user's environment). Build as x64 (or "Any CPU" with Prefer-32-bit off) —
  SOLIDWORKS is 64-bit.
- **Internal units are SI**: meters, radians, kilograms. A "100 mm" box is
  `0.1`. This is the #1 source of silently-wrong geometry. Convert at the
  boundary, never mid-calculation.
- **COM lifetime matters**: release interop objects you obtain in loops with
  `Marshal.ReleaseComObject` to avoid SOLIDWORKS holding files open / memory
  bloat during batch runs. See `references/pitfalls.md`.

## Workflow for generating an add-in

1. **Clarify scope** — which features, and add-in (persistent UI buttons) vs.
   one-shot macro/console app (drives `swApp`, no UI registration). Batch-file
   tools are often better as a button that opens a dialog; geometry helpers too.
2. **Scaffold the project** — produce the `.csproj`, the `SwAddin.cs` entry
   point with `ConnectToSW`/`DisconnectFromSW`, COM register/unregister
   functions, and CommandManager setup. Full working template is in
   `references/scaffold-template.md`. Copy it, then strip buttons the user
   doesn't need rather than writing from scratch.
3. **Implement each feature** as a callback method. Map the feature to the right
   API object and call flow using `references/api-recipes.md` — it's organized by
   the SpeedWorks-style feature groups (batch operations, modeling) the user
   cares about, with the exact interop types and method names.
4. **Wire build + deploy** — register for COM interop, set the registry keys (the
   `[ComRegisterFunction]` does this), and explain the debug setup (attach to
   `SLDWORKS.exe`). See `references/build-deploy.md`.
5. **Flag what you couldn't verify** — you cannot run SOLIDWORKS here. Method
   *names* below are real, but exact parameter lists and enum values drift across
   API versions. Tell the user which signatures to confirm against the local API
   help (`SOLIDWORKS API Help`, or the online API docs), and never invent an enum
   member you're unsure of — point them to the `swconst` enum instead.

## Reference files

Read the one matching the task instead of loading everything:

- **`references/scaffold-template.md`** — complete, working add-in skeleton:
  `.csproj`, `SwAddin.cs`, CommandManager registration, COM register/unregister,
  a sample button + callback. Start here for any new add-in.
- **`references/api-recipes.md`** — feature implementation recipes by group.
  Batch operations (custom properties, materials, batch export PDF/DWG/STEP,
  rebuild, configuration/component traversal) and modeling (primitives via
  extrude/revolve, coordinate systems, batch points from CSV, batch holes,
  3D-sketch conversion, mirror part, performance toggles). Each entry: which
  interop object, the call sequence, and gotchas.
- **`references/build-deploy.md`** — project settings, COM-interop registration,
  the registry keys SOLIDWORKS reads, signing, debugging (attach to process),
  and packaging/installer notes.
- **`references/pitfalls.md`** — the recurring traps: units, COM release, version
  signature drift, selection-based vs. direct API, rebuild/EditRebuild timing,
  silent failures when no document is open, threading/STA.

## Style

The user is a senior mechanical/optical defense engineer. Be concise and
direct — give the call flow and the gotcha, not API tutorials. When producing
code, make it compile-ready C# (proper usings, COM attributes, null checks for
"no active doc"), match the scaffold's conventions, and comment only the
non-obvious (unit conversions, why a COM object is released, version caveats).
