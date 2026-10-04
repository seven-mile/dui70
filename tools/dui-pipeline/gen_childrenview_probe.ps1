# Builds and runs the W1 ChildrenView fixture -- a tracked test that PROVES which
# dui70.dll it exercised, instead of implicitly depending on the OS copy.
#
# Why this script exists rather than reusing run.ps1:
#   run.ps1 builds the UITest acceptance demo and asserts a window appears. This
#   fixture is a GATE: it must run against the PINNED dui70.dll and must FAIL if
#   the pinned DLL is absent, so that a PASS is evidence about the pinned binary
#   and not about whatever System32 happens to contain. Making that a separate
#   script keeps the pin discipline out of the demo path.
#
# Pin discipline (see tests/w1-childrenview/README.md for the measured reasons):
#   * A1  loaded module path == the expected pinned directory
#   * A2  sha256 of the LOADED .text == the anchor derived from the manifest-verified
#         DLL (never a re-read of the file: that would be a TOCTOU check)
#   * A3  the module was not loaded from System32/SysWOW64
#   The expected .text digest is DERIVED, not hardcoded: pe-digest.py asserts the
#   source DLL's whole-file sha256 against pinned/manifest.json first, and refuses
#   to emit an anchor whose .text is not rebase-invariant.
#
# Usage:
#   pwsh -File gen_childrenview_probe.ps1                       # uses .local/build/repro
#   pwsh -File gen_childrenview_probe.ps1 -PinnedDll <path>      # explicit pinned DLL
#   pwsh -File gen_childrenview_probe.ps1 -RunNegative           # also run NEGCTL + NOPIN
param(
    [string]$PinnedDll,
    [string]$Lib,
    [string]$OutDir,
    [string]$WorkDir,
    [switch]$RunNegative,
    [switch]$SkipRun
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py = (Get-Command python -ErrorAction SilentlyContinue |
       Select-Object -First 1).Source
if (-not $py) { throw "python not found on PATH; pass it via PATH" }

$testDir = Join-Path $repo 'tests\w1-childrenview'
$manifest = Join-Path $repo 'pinned\manifest.json'
if (-not $WorkDir) { $WorkDir = Join-Path $repo '.local\build\w1-childrenview' }
if (-not $OutDir) { $OutDir = Join-Path $WorkDir 'x64' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# --- locate the PINNED dll ---------------------------------------------------
# Default is where repro.ps1 leaves the DLL it downloaded and sha256-asserted.
# Deliberately never falls back to C:\Windows\System32: silently accepting the OS
# copy is exactly the failure mode A1/A3 exist to catch.
if (-not $PinnedDll) {
    $PinnedDll = Join-Path $repo '.local\build\repro\dll-only\dui70.dll'
}
if (-not (Test-Path $PinnedDll)) {
    throw @"
pinned dui70.dll not found: $PinnedDll
Run the repro stage first (pwsh -File tools/dui-pipeline/repro.ps1), which
downloads it from msdl and asserts its sha256 against pinned/manifest.json.
This script will NOT fall back to the System32 copy: a fixture that silently
tests the OS DLL would report a PASS that says nothing about pinned bytes.
"@
}
$PinnedDll = (Resolve-Path $PinnedDll).Path

# --- toolchain discovery (mirrors gen_uitest_proj.ps1) -----------------------
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = $null
if (Test-Path $vswhere) {
    $installPath = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
    if ($installPath) {
        $vsRoot = Get-ChildItem (Join-Path $installPath 'VC\Tools\MSVC') -Directory |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($vsRoot) { $vsRoot = $vsRoot.FullName }
    }
}
if (-not $vsRoot) { throw "MSVC not found; install the C++ tools or pass a dev prompt" }
$vcBin = Join-Path $vsRoot 'bin\Hostx64\x64'

$sdkIncRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
$sdkVer = (Get-ChildItem $sdkIncRoot -Directory -Filter '10.0.*' |
           Sort-Object Name -Descending | Select-Object -First 1).Name
if (-not $sdkVer) { throw "Windows SDK not found under $sdkIncRoot" }
$sdkInc = Join-Path $sdkIncRoot $sdkVer
$sdkLib = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\Lib\$sdkVer"
$sdkBin = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin\$sdkVer\x64"

$includeDir = Join-Path $repo 'DirectUI\include'

# --- import library ----------------------------------------------------------
# Built from the golden .def so the fixture links the same extern-C surface the
# generated tree declares. Kept local to this fixture so it does not depend on
# run.ps1 having run first.
if (-not $Lib) {
    $Lib = Join-Path $WorkDir 'dui70.lib'
    & (Join-Path $vcBin 'lib.exe') /nologo /def:"$repo\DirectUI\dui70.def" `
        /machine:x64 /out:"$Lib" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "lib.exe failed building the import library" }
}
$libDir = Split-Path -Parent $Lib

# --- derive the A2 anchor (asserts the manifest first) -----------------------
# A1's expected directory is the STAGING dir, not the location the pinned DLL was
# downloaded to: the whole point is that we copy the pinned bytes next to the exe
# and require the loader to pick that copy up. So:
#   A1 -> the module came from the directory we control (staging)
#   A2 -> the bytes in that copy are the pinned ones
#   A3 -> it did not come from System32
# Passing the download dir here instead would make A1 fail by construction.
$anchor = Join-Path $WorkDir 'w1-pin-anchor.h'
Write-Host '==> derive A2 anchor from the manifest-verified DLL' -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot 'pe-digest.py') derive `
    --dll $PinnedDll `
    --manifest $manifest `
    --out-header $anchor `
    --expect-dir $OutDir
if ($LASTEXITCODE -ne 0) { throw "pe-digest.py derive failed: refusing to emit an anchor" }

# --- build ------------------------------------------------------------------
$env:PATH = "$vcBin;$sdkBin;$env:PATH"
# vc\include comes FIRST: excpt.h/vcruntime.h live there, not in the SDK.
$vcruntimeInc = Join-Path $vsRoot 'include'
$env:INCLUDE = "$vcruntimeInc;$includeDir;$sdkInc\ucrt;$sdkInc\shared;$sdkInc\um;$sdkInc\winrt"
$env:LIB = "$(Join-Path $vsRoot 'lib\x64');$(Join-Path $sdkLib 'ucrt\x64');$(Join-Path $sdkLib 'um\x64')"

Write-Host "==> build fixture against $Lib" -ForegroundColor Cyan
$exe = Join-Path $OutDir 'w1-childrenview.exe'
# /Zc:wchar_t- is the DirectUI consumer ABI mode (Option D): the SDK UIA
# interfaces pulled in via the generated headers declare wchar_t params;
# under this flag they mangle PEBG/PEAPEAG == the pinned dui70.dll
# exports. The default wchar_t mode diverges (PEB_W) and the
# ValueProvider overrides stop matching their SDK base (C3668).
$clArgs = @(
    '/nologo', '/W3', '/O2', '/EHsc', '/std:c++17', '/Zc:wchar_t-',
    "/I$includeDir", "/I$WorkDir",
    "/Fo$OutDir\\", "/Fe:$exe", "/Fd$OutDir\w1-childrenview.pdb",
    (Join-Path $testDir 'w1-childrenview-probe.cpp'),
    $Lib, 'ole32.lib', 'bcrypt.lib',
    '/link', '/SUBSYSTEM:CONSOLE'
)
& (Join-Path $vcBin 'cl.exe') @clArgs
if ($LASTEXITCODE -ne 0) { throw "cl.exe failed building the fixture" }
if (-not (Test-Path $exe)) { throw "fixture exe not produced at $exe" }

# --- stage the PINNED dll beside the exe ------------------------------------
# App-local placement is what makes the loader pick the pinned copy over
# System32 (dui70.dll is not a KnownDLL, so its directory is searched first).
Copy-Item $PinnedDll (Join-Path $OutDir 'dui70.dll') -Force
Write-Host "==> staged pinned dui70.dll beside the exe (app-local wins over System32)" -ForegroundColor Cyan

if ($SkipRun) { Write-Host '==> skipped run (-SkipRun)'; return }

# --- run pinned (must PASS) -------------------------------------------------
Write-Host '==> run (pinned)' -ForegroundColor Cyan
& $exe
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "fixture FAILED against the pinned DLL (exit $rc)" }

if (-not $RunNegative) {
    Write-Host '==> negative controls skipped (-RunNegative to enable)' -ForegroundColor DarkGray
    return
}

# --- X86 NEGCTL: the header must REFUSE to build for 32-bit -------------------
# ChildrenView encodes an x64-measured layout (sizeof(void*)==8 -> 24-byte array,
# inline capacity 2). On x86 the header would still COMPILE -- the offsets are
# plain integers and the accesses are memcpy on an opaque blob, so there is no
# type error -- and every read would then be silently wrong. A static_assert is
# the only thing standing between "wrong feature" and "wrong bytes", so this
# control requires it to actually fire.
#
# It is a compile-only check (/Zs: syntax only, no object, no link), so it needs
# no x86 libs and costs ~0.1s.
$vcBinX86 = Join-Path $vsRoot 'bin\Hostx64\x86'
$clX86 = Join-Path $vcBinX86 'cl.exe'
if (Test-Path $clX86) {
    Write-Host '==> X86 negative control (static_assert must REJECT 32-bit)' -ForegroundColor Cyan
    $x86Tu = Join-Path $OutDir 'x86-layout-control.cpp'
    Set-Content -Path $x86Tu -Encoding ascii -NoNewline -Value "#include <ChildrenView.h>`n"
    # Preserve the x64 INCLUDE order (vc\include first: excpt.h lives there).
    $x86Out = & $clX86 /nologo /Zs /std:c++17 /EHsc /I $includeDir $x86Tu 2>&1
    $x86Rc = $LASTEXITCODE
    Remove-Item $x86Tu -Force -ErrorAction SilentlyContinue
    if ($x86Rc -eq 0) {
        throw ("x86 negative control PASSED: ChildrenView.h compiled for a 32-bit " +
               "target. The measured x64 offsets would be applied to a 4-byte " +
               "pointer layout, silently reading the wrong bytes. The " +
               "static_assert(sizeof(void*)==8) guard is missing or ineffective.")
    }
    # Accept both spellings: MSVC has emitted "static assertion failed" and, in
    # newer toolsets, "static_assert failed". Pinning one exact string would make
    # this control fail for the wrong reason on a different compiler.
    if (-not (($x86Out | Out-String) -match 'static[_ ]assert(ion)? failed')) {
        throw ("x86 build failed, but NOT on the layout static_assert -- so the " +
               "guard is not what refused it. Output: " + (($x86Out | Select-Object -First 6) -join ' | '))
    }
    Write-Host '    X86 correctly refused by static_assert' -ForegroundColor Green
} else {
    throw ("x86 cl.exe not found at $clX86 -- cannot run the 32-bit negative " +
           "control. Install the x86 toolset, or the x64-only guarantee is " +
           "unverified. Refusing to report a PASS without it.")
}

# --- NEGCTL: wrong expectations must FAIL -----------------------------------
Write-Host '==> NEGCTL (must exit non-zero)' -ForegroundColor Cyan
& $exe NEGCTL | Out-Null
if ($LASTEXITCODE -eq 0) {
    throw "NEGCTL passed: the fixture cannot detect wrong expectations, so its PASS is not evidence"
}
Write-Host '    NEGCTL correctly failed' -ForegroundColor Green

# --- NOPIN: pinned DLL absent must FAIL (A1/A3) -----------------------------
# Move the app-local DLL aside so the loader falls back to System32. The A2
# digest must notice; A1/A3 must also fire. A PASS here would mean the fixture
# cannot tell pinned from System32.
$staged = Join-Path $OutDir 'dui70.dll'
$aside = Join-Path $OutDir 'dui70.dll.pinned-aside'
Move-Item $staged $aside -Force
try {
    Write-Host '==> NOPIN (pinned DLL hidden; must exit non-zero)' -ForegroundColor Cyan
    & $exe NOPIN 2>&1 | Select-String -Pattern 'A1|A2|A3|FAIL|LIVE-' | Select-Object -First 12
    if ($LASTEXITCODE -eq 0) {
        throw "NOPIN passed: with the pinned DLL hidden the fixture still passed, so it cannot tell pinned from System32"
    }
    Write-Host '    NOPIN correctly failed' -ForegroundColor Green
} finally {
    Move-Item $aside $staged -Force
}

Write-Host ''
Write-Host 'W1 ChildrenView fixture: PASS (pinned) + negative controls correctly failed' -ForegroundColor Green
