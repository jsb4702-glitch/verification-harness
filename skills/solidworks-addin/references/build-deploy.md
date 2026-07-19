# Build, Register, Debug, Deploy

How to get the add-in from source to a button in SOLIDWORKS, and how to debug it.
The user runs all of this on their CAD machine — you produce the steps and the
project settings.

## Build settings (must-haves)

- **Platform: x64.** SOLIDWORKS is 64-bit; a 32-bit/AnyCPU-with-prefer-32 build
  won't load.
- **Target .NET Framework 4.7.1+** (the user's environment baseline).
- **Register for COM interop = ON** (Project ▸ Build tab, or
  `<RegisterForComInterop>true</RegisterForComInterop>`). This runs `regasm`
  automatically on build, so the `[ComRegisterFunction]` writes the registry keys.
- **Sign the assembly** (strong name) if you'll GAC it or distribute — optional
  for local use.
- Interop references with **Embed Interop Types = False** (embedding breaks
  callback marshaling).

## How SOLIDWORKS finds the add-in

On launch it scans `HKLM\SOFTWARE\SolidWorks\Addins\{guid}` for registered add-ins
and `HKCU\Software\SolidWorks\AddInsStartup\{guid}` for the per-user load flag.
The `[ComRegisterFunction]` in the scaffold writes both. So the chain is:

```
build (Register for COM interop) → regasm runs → [ComRegisterFunction] fires
   → registry keys written → SOLIDWORKS shows "MyAddin" in Tools ▸ Add-Ins
   → user ticks it (or LoadAtStartup=true) → ConnectToSW called
```

If the add-in doesn't appear:
- Built x64? regasm ran (check build output)? Run VS **as admin** (HKLM write).
- Manually: `"%windir%\Microsoft.NET\Framework64\v4.0.30319\regasm.exe" /codebase MyAddin.dll`
- Check the keys exist with `regedit`.

## Debugging

Add-ins run *inside* SOLIDWORKS, so you attach to the process:

1. Build the add-in (registers it).
2. In Visual Studio: **Debug ▸ Attach to Process ▸ SLDWORKS.exe**
   (or set it as the Start External Program in Debug settings to launch+attach).
3. Set breakpoints in `ConnectToSW` / your callbacks.
4. Toggle the add-in off/on in Tools ▸ Add-Ins to re-hit `ConnectToSW` without
   restarting SOLIDWORKS — but note a *rebuild* needs SOLIDWORKS fully closed,
   because the DLL is locked while loaded.

> The lock-while-loaded problem is the main dev friction: close SOLIDWORKS →
> rebuild → reopen. Keep iteration tight by testing logic in a separate console
> app driving `swApp` where possible (see below), and only moving stable code into
> the add-in.

## Standalone alternative (faster iteration, no UI)

For pure batch logic, a console/WinForms app that connects to a running (or new)
SOLIDWORKS instance avoids the register/lock cycle entirely:

```csharp
// Connect to a running instance, or start one.
var swApp = (ISldWorks)(Marshal.GetActiveObject("SldWorks.Application"));
// or: Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application"))
swApp.Visible = true;
// ... same IModelDoc2 API as in callbacks ...
```

Develop and debug the feature here, then port the method body into an add-in
callback once it works. Same API objects, no COM-registration dance.

## Packaging / distribution

- **Simplest**: ship the DLL + a `.reg` file or a small installer that runs
  `regasm /codebase`. Per-machine install needs admin.
- **Installer** (WiX / Inno Setup / Advanced Installer): the SpeedWorks manual
  shows exactly this pattern — an MSI that drops files and writes the add-in
  registry keys, plus a license/activation step. The installer doing the registry
  write means you don't strictly need "Register for COM interop" on the end-user
  machine.
- **Versioning**: keep the `[Guid]` stable across releases (changing it makes
  SOLIDWORKS treat it as a different add-in and the old keys orphan). Bump the
  CommandGroup "registry id" int when you change the toolbar layout so SOLIDWORKS
  rebuilds the tab.
- **Licensing/activation** (if commercial like SpeedWorks): gate `ConnectToSW`
  (or feature callbacks) on a license check — machine-locked key, online
  activation, or a dongle. Out of scope here, but that's where it hooks in.
