# Pitfalls

The recurring traps in SOLIDWORKS add-in work, roughly in order of how often they
bite. Read this before shipping anything that creates geometry or runs over many
files.

## 1. Units are SI internally — always

Lengths in **meters**, angles in **radians**, mass in **kg**, regardless of the
document's display units. A "50 mm" depth is `0.05`. Convert at the boundary (when
reading user input or files) and keep everything in SI inside the logic. Mixing
display units into API calls produces geometry that's 1000× off and "looks like a
unit bug" — because it is. This is the single most common mistake.

## 2. COM object lifetime in loops

Interop objects you obtain (`OpenDoc6`, `GetModelDoc2`, components, features) hold
native references. In a batch over hundreds of files, not releasing them keeps
files locked and balloons memory until SOLIDWORKS chokes. Pattern:

```csharp
try { /* work */ }
finally {
    _swApp.CloseDoc(model.GetTitle());
    Marshal.ReleaseComObject(model);
}
```

Don't over-release objects SOLIDWORKS still owns (like the main `ISldWorks` while
connected) — release what *you* obtained, in reverse order, and let the add-in's
`DisconnectFromSW` release the long-lived ones.

## 3. API signature drift across versions

Method *names* are stable, but parameter lists and enum members change between
releases (`FeatureExtrusion3`, `HoleWizard5`, `SaveAs3`, mirror-part). Code that
compiles against 2024 interop may need tweaks on 2022. Mitigations:
- Reference the interop DLLs from the **user's installed version**.
- For signature-heavy calls, **record a macro** of the operation on the target
  machine and copy its exact argument list — the recorder always emits the
  correct version-specific signature.
- Never invent an enum member. Point to the `swconst` enum
  (`swEndConditions_e`, `swSaveAsOptions_e`, etc.) and let the user pick the real
  one if you're unsure.

## 4. No active document / wrong document type

Callbacks fire even when nothing useful is open. Always:
- Guard `_swApp.ActiveDoc != null`.
- Check the type before casting (`as IPartDoc` returns null for an assembly).
- Use the `enable` callback to grey out buttons when they don't apply, so users
  don't hit a no-op.

## 5. Selection-based APIs depend on selection marks

Many feature creators (coordinate system, hole wizard, mirror) consume prior
selections, and **marks** (the int in `SelectByID2`) encode the *role* of each
selection (origin vs. X-axis vs. Y-axis, placement points, etc.). Wrong marks =
axes swapped or feature fails silently. `SelectByID2` returns a bool — check it;
a failed selection (bad name/coords) means the next feature call builds on nothing.

## 6. Rebuild / save timing

Changes to suppression, visibility, configs, and many features don't persist until
the doc is rebuilt and saved. After batch edits: `ForceRebuild3(false)` then
`Save3(..._Silent, ...)`. Reading mass/BOM properties before a rebuild can return
stale values.

## 7. Silent failures

SOLIDWORKS API rarely throws — it returns `null`, `false`, or an `errors` out-int.
Check return values and the `ref errs/warns` from open/save. Surface failures to
the user (a log file for batch runs is far better than a popup per file). The
classic "button does nothing" bug is a typo'd callback/enable method name string
in `AddCommandItem2` — those are bound by string and fail without error.

## 8. Threading / STA

SOLIDWORKS API is STA COM. Do API work on the main thread (the thread that called
`ConnectToSW`). Don't fan batch file processing across worker threads touching
interop objects — you'll get cross-thread COM exceptions. Keep the loop
single-threaded; parallelize only pure CPU/IO that doesn't touch `swApp`.

## 9. Performance options left changed

The "booster" pattern flips system options for speed. If you don't restore them in
a `finally`, the user's SOLIDWORKS stays altered after your batch — a confusing
support issue. Snapshot every toggle you change and restore it unconditionally.

## 10. Registry / load issues are almost always build config

If the add-in won't appear or load: it's x64 vs 32-bit, "Register for COM interop"
off, regasm not run as admin (HKLM), or a GUID that changed. Re-check
`build-deploy.md` before debugging code — the code is rarely the problem when the
button never shows up.
