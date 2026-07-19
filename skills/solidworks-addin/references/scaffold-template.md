# Add-in Scaffold Template

A complete, working SOLIDWORKS add-in skeleton. Copy it, change the GUID, title,
and buttons, then delete what you don't need. This compiles against the SOLIDWORKS
interop assemblies and loads as a CommandManager tab.

## Contents
- [Project file (.csproj)](#project-file)
- [Entry point (SwAddin.cs)](#entry-point)
- [A feature callback](#feature-callback)
- [Generating a GUID](#generating-a-guid)

---

## Project file

Classic-style `.csproj` (most reliable for COM-interop registration). Reference
the interop DLLs from the local SOLIDWORKS install, not NuGet, so versions match
the user's machine. They live under e.g.
`C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\`.

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net471</TargetFramework>
    <Platforms>x64</Platforms>
    <PlatformTarget>x64</PlatformTarget>
    <UseWindowsForms>true</UseWindowsForms>   <!-- if you use WinForms dialogs -->
    <RegisterForComInterop>true</RegisterForComInterop>
    <EnableComHosting>false</EnableComHosting>
    <GenerateAssemblyInfo>true</GenerateAssemblyInfo>
  </PropertyGroup>

  <ItemGroup>
    <!-- Adjust paths/versions to the installed SOLIDWORKS -->
    <Reference Include="SolidWorks.Interop.sldworks">
      <HintPath>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll</HintPath>
      <EmbedInteropTypes>false</EmbedInteropTypes>
    </Reference>
    <Reference Include="SolidWorks.Interop.swconst">
      <HintPath>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swconst.dll</HintPath>
      <EmbedInteropTypes>false</EmbedInteropTypes>
    </Reference>
    <Reference Include="SolidWorks.Interop.swpublished">
      <HintPath>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swpublished.dll</HintPath>
      <EmbedInteropTypes>false</EmbedInteropTypes>
    </Reference>
    <Reference Include="SolidWorks.Interop.swcommands">
      <HintPath>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swcommands.dll</HintPath>
      <EmbedInteropTypes>false</EmbedInteropTypes>
    </Reference>
  </ItemGroup>
</Project>
```

> `EmbedInteropTypes` must be **false** for SOLIDWORKS interop — embedding breaks
> callback marshaling. If you prefer the old `<Project ToolsVersion>` format with
> `packages.config`, that also works; the key flags are x64, .NET 4.7.1, and
> "Register for COM interop" in the Build tab.

---

## Entry point

`SwAddin.cs` — implements `ISwAddin`, registers/unregisters the COM keys
SOLIDWORKS reads, and builds the CommandManager group on connect.

```csharp
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swpublished;

namespace MyAddin
{
    [Guid("PUT-A-FRESH-GUID-HERE")]            // unique per add-in; see bottom
    [ComVisible(true)]
    [SwAddin(                                    // metadata SW shows in Add-Ins dialog
        Description = "My SOLIDWORKS utilities",
        Title = "MyAddin",
        LoadAtStartup = true)]
    public class SwAddin : ISwAddin
    {
        private ISldWorks _swApp;
        private ICommandManager _cmdMgr;
        private int _cookie;
        private int _cmdGroupId = 1;            // arbitrary, unique within this add-in

        // ---- COM registration: writes the keys SOLIDWORKS scans on launch ----
        [ComRegisterFunction]
        public static void RegisterFunction(Type t)
        {
            string guid = "{" + t.GUID.ToString() + "}";
            // Add-in entry SOLIDWORKS reads
            using (var k = Registry.LocalMachine.CreateSubKey(
                       $@"SOFTWARE\SolidWorks\Addins\{guid}"))
            {
                k.SetValue(null, 0);                       // 0 = not VBA
                k.SetValue("Description", "My SOLIDWORKS utilities");
                k.SetValue("Title", "MyAddin");
            }
            // Per-user startup flag (1 = load at startup)
            using (var k = Registry.CurrentUser.CreateSubKey(
                       $@"Software\SolidWorks\AddInsStartup\{guid}"))
            {
                k.SetValue(null, 1);
            }
        }

        [ComUnregisterFunction]
        public static void UnregisterFunction(Type t)
        {
            string guid = "{" + t.GUID.ToString() + "}";
            Registry.LocalMachine.DeleteSubKey($@"SOFTWARE\SolidWorks\Addins\{guid}", false);
            Registry.CurrentUser.DeleteSubKey($@"Software\SolidWorks\AddInsStartup\{guid}", false);
        }

        // ---- Lifecycle ----
        public bool ConnectToSW(object ThisSW, int Cookie)
        {
            _swApp = (ISldWorks)ThisSW;
            _cookie = Cookie;

            // Required so SOLIDWORKS can route callbacks back to this instance.
            _swApp.SetAddinCallbackInfo2(0, this, _cookie);

            _cmdMgr = _swApp.GetCommandManager(_cookie);
            BuildCommandGroup();
            return true;
        }

        public bool DisconnectFromSW()
        {
            _cmdMgr.RemoveCommandGroup2(_cmdGroupId, true);
            Marshal.ReleaseComObject(_cmdMgr); _cmdMgr = null;
            Marshal.ReleaseComObject(_swApp);  _swApp = null;
            GC.Collect(); GC.WaitForPendingFinalizers();
            return true;
        }

        // ---- UI ----
        private void BuildCommandGroup()
        {
            int err = 0;
            // Last two bools: ignorePrevious, out errors. The "registry id" int
            // lets SW detect layout changes between versions of your add-in.
            ICommandGroup grp = _cmdMgr.CreateCommandGroup2(
                _cmdGroupId, "MyAddin", "My utilities tooltip", "My utilities", -1,
                false, ref err);

            // AddCommandItem2(name, position, hint, tooltip, imageListIndex,
            //   callbackFn, enableFn, userId, menuTBoption)
            // callbackFn/enableFn are METHOD NAMES on this class, resolved by string.
            int idEdit = grp.AddCommandItem2(
                "Batch Properties", -1, "Edit custom properties in bulk",
                "Batch Properties", 0, "OnBatchProperties", "EnableWithDoc", 0,
                (int)swCommandItemType_e.swMenuItem | (int)swCommandItemType_e.swToolbarItem);

            grp.HasToolbar = true;
            grp.HasMenu = true;
            grp.Activate();

            // Show the tab in Part/Assembly/Drawing CommandManager.
            foreach (int docType in new[] {
                (int)swDocumentTypes_e.swDocPART,
                (int)swDocumentTypes_e.swDocASSEMBLY,
                (int)swDocumentTypes_e.swDocDRAWING })
            {
                ICommandTab tab = _cmdMgr.GetCommandTab(docType, "MyAddin")
                                  ?? _cmdMgr.AddCommandTab(docType, "MyAddin");
                ICommandTabBox box = tab.AddCommandTabBox();
                box.AddCommands(
                    new[] { grp.get_CommandID(idEdit) },
                    new[] { (int)swCommandTabButtonTextDisplay_e.swCommandTabButton_TextBelow });
            }
        }

        // ---- Enable handler: grey out buttons when no doc is open ----
        // Return 1 = enabled, 0 = disabled. Bound by name "EnableWithDoc".
        public int EnableWithDoc()
        {
            return _swApp.ActiveDoc != null ? 1 : 0;
        }

        // ---- Button callback (bound by name "OnBatchProperties") ----
        public void OnBatchProperties()
        {
            var model = _swApp.ActiveDoc as IModelDoc2;
            if (model == null)
            {
                _swApp.SendMsgToUser2("Open a document first.",
                    (int)swMessageBoxIcon_e.swMbWarning,
                    (int)swMessageBoxBtn_e.swMbOk);
                return;
            }
            // ... feature work here (see api-recipes.md) ...
        }
    }
}
```

> Callback and enable functions are resolved **by string name** at click time, so
> a typo fails silently (button does nothing / stays greyed). Keep the strings in
> `AddCommandItem2` exactly matching the public method names.

---

## Feature callback

Each toolbar button = one public method on the add-in class, named to match the
`callbackFn` string. Pull the active document, guard for null, do API work, then
release any COM objects you grabbed in loops. The actual API call flows live in
`api-recipes.md`.

```csharp
public void OnCreateBox()
{
    var part = _swApp.ActiveDoc as IPartDoc;          // null if not a part
    var model = part as IModelDoc2;
    if (model == null) { /* warn + return */ return; }

    // Remember: SI units. 100 mm box → 0.1 m.
    const double L = 0.1;
    // ... sketch + FeatureExtrusion3 (see api-recipes.md "Primitives") ...
}
```

---

## Generating a GUID

Each add-in class needs a unique, stable GUID (changing it orphans the registry
keys). Generate one and paste it into the `[Guid(...)]` attribute:

- PowerShell: `[guid]::NewGuid()`
- Visual Studio: Tools ▸ Create GUID ▸ Registry Format
- .NET: `System.Guid.NewGuid()`

Use lowercase, no braces inside the attribute string:
`[Guid("3f2504e0-4f89-41d3-9a0c-0305e82c3301")]`.
