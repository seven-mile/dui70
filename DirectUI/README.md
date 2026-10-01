# DirectUI — generated bindings for the system dui70.dll

**This directory is machine-generated.** It is produced by
[tools/dui-pipeline](../tools/dui-pipeline/) from the pinned symbol data in
[pinned/](../pinned/). Never edit by hand — run the generator instead:

```
python tools/dui-pipeline/regen.py
git diff DirectUI/     # review what the generator change did
```

## What's here

| Path | Contents |
|---|---|
| `include/` | C++ headers: aggregate `DirectUI.h`, per-class headers, `Interfaces.h` (consumer-side abstract interfaces), `dui_abi_types.h` (ABI scaffolding) |
| `src/` | stub translation units — the ABI golden list (see *Verifying* below) |
| `dui70.def` | every export of the pinned dui70.dll (4321 entries) |

## Using the library

```cpp
#include <DirectUI.h>        // compile with /I DirectUI\include
```

Build the import library (no prebuilt binary is shipped):

```
lib.exe /def:DirectUI\dui70.def /machine:x64 /out:dui70.lib
```

Link `dui70.lib`; at runtime your process loads the **real system
`dui70.dll`** — require Windows 11 26100+ (or a build whose dui70.dll matches
the pinned ABI; see `pinned/manifest.json`).

Compile with `/Zc:wchar_t-` for ABI parity with the original headers
(`wchar_t` is a 16-bit unsigned, not a builtin, in the DirectUI ABI).

## Verifying (optional, no pipeline needed)

The stub sources in `src/` are a machine-checkable ABI manifest:

```
cl /c /std:c++20 /Zc:wchar_t- /EHsc DirectUI\src\*.cpp
dumpbin /symbols *.obj > obj-symbols.txt
:: every decorated name in obj-symbols.txt must appear in dui70.def
```

Any mismatch means the headers disagree with the real DLL — that is a
generator bug.

## Legacy C entry points

`InitProcessPriv`, `UnInitProcessPriv`, `InitThread`,
`RegisterAllControls`, `StartMessagePump`, `StrToID` ... are declared
`extern "C"` inside `namespace DirectUI`, exactly matching the plain-name
exports of the real DLL. No shims, no import-library tricks.

## Coverage

Currently generated classes (see `pinned/classes.json`): Value,
DUIXmlParser, Element, HWNDElement, NativeHWNDHost, TouchButton, Edit,
Button, Progress, PushButton, TouchCheckBox, XProvider — 12 classes,
932 exported methods, 100% decorated-name fidelity.
