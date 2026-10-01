# Builds UITest.exe against a chosen dui70 import library, WITHOUT modifying UITest/ or the .sln.
#
# Mirrors UITest.vcxproj's Debug|x64 settings:
#   ConfigurationType Application, v143, Unicode, /std:c++20, no PCH, SubSystem Windows
#   TreatWChar_tAsBuiltInType false, IncludePath += WIL + vcpkg detours, link dui70.lib + detours.lib
#
# Usage:
#   pwsh -File gen_uitest_proj.ps1 [-Lib <path to dui70.lib>] [-OutDir <dir>] [-X86]
param(
    [string]$Lib,
    [string]$OutDir,
    [string]$IncludeDir,   # generated headers dir; default .local/build/generated/include
    [switch]$X86
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if (-not $IncludeDir) { $IncludeDir = Join-Path $repo '.local\build\generated\include' }

$arch = if ($X86) { 'x86' } else { 'x64' }
$hostArch = 'Hostx64'
$targetArch = if ($X86) { 'x86' } else { 'x64' }

$vcRoot = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
$vcBin = Join-Path $vcRoot "bin\$hostArch\$targetArch"
$sdkVersion = '10.0.26100.0'
$sdkInc = "C:\Program Files (x86)\Windows Kits\10\Include\$sdkVersion"
$sdkLib = "C:\Program Files (x86)\Windows Kits\10\Lib\$sdkVersion"
$sdkBin = "C:\Program Files (x86)\Windows Kits\10\bin\$sdkVersion\$targetArch"
$wilInc = Join-Path $repo 'packages\Microsoft.Windows.ImplementationLibrary.1.0.230629.1\include'
$detoursPkg = if ($X86) { 'x86-windows' } else { 'x64-windows' }
$detoursInc = "C:\Local\Tools\vcpkg\installed\$detoursPkg\include"
$detoursLib = "C:\Local\Tools\vcpkg\installed\$detoursPkg\lib"

if (-not $Lib) { $Lib = Join-Path $repo '.local\build\lib\dui70.lib' }
if (-not $OutDir) { $OutDir = Join-Path $repo ".local\build\acceptance-$arch" }
$LibDir = Split-Path -Parent $Lib
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$vcLib = Join-Path $vcRoot "lib\$targetArch"
$ucrtLib = Join-Path $sdkLib "ucrt\$targetArch"
$umLib = Join-Path $sdkLib "um\$targetArch"

# Environment for cl/link/rc
$env:PATH = "$vcBin;$sdkBin;$env:PATH"
# Order matters: generated headers first, so `..\DirectUI\DirectUI.h` inside
# UITest.cpp resolves to the GENERATED aggregate (extern-C legacy APIs) —
# the hand-written baseline is not consumed on this path.
$env:INCLUDE = @(
    $IncludeDir,
    (Join-Path $vcRoot 'include'),
    (Join-Path $sdkInc 'ucrt'),
    (Join-Path $sdkInc 'shared'),
    (Join-Path $sdkInc 'um'),
    (Join-Path $sdkInc 'winrt'),
    $wilInc,
    $detoursInc
) -join ';'
$env:LIB = @($vcLib, $ucrtLib, $umLib, $detoursLib) -join ';'

Write-Host "=== building UITest against $Lib ===" -ForegroundColor Cyan
Write-Host "out: $OutDir"

Push-Location $OutDir
try {
    # 1. compile
    $clArgs = @(
        '/nologo', '/c', '/W3', '/Zi', '/Od', '/MDd',
        '/std:c++20', '/EHsc', '/Zc:wchar_t-', '/D_UNICODE', '/DUNICODE',
        '/DWIN32', '/D_DEBUG', '/D_WINDOWS',
        "/Fo$OutDir\\", "/Fd$OutDir\UITest.pdb",
        (Join-Path $repo 'UITest\UITest.cpp')
    )
    & cl.exe @clArgs
    if ($LASTEXITCODE -ne 0) { throw "cl failed: $LASTEXITCODE" }

    # 2. resources (UITest.rc embeds dui.xml as IDR_UIFILE1)
    $rcArgs = @('/nologo', "/I$repo\UITest", "/Fo$OutDir\UITest.res", (Join-Path $repo 'UITest\UITest.rc'))
    & rc.exe @rcArgs
    if ($LASTEXITCODE -ne 0) { throw "rc failed: $LASTEXITCODE" }

    # 3. link
    $linkArgs = @(
        '/nologo', '/DEBUG', '/SUBSYSTEM:WINDOWS',
        "/OUT:$OutDir\UITest.exe",
        "/PDB:$OutDir\UITest.pdb",
        "/LIBPATH:$vcLib", "/LIBPATH:$ucrtLib", "/LIBPATH:$umLib", "/LIBPATH:$detoursLib", "/LIBPATH:$LibDir",
        "$OutDir\UITest.obj", "$OutDir\UITest.res",
        'dui70.lib', 'detours.lib',
        'comctl32.lib', 'ole32.lib', 'oleacc.lib', 'uuid.lib',
        'uxtheme.lib', 'gdi32.lib', 'user32.lib', 'shlwapi.lib',
        'dwmapi.lib', 'windowscodecs.lib', 'propsys.lib', 'advapi32.lib'
    )
    & link.exe @linkArgs
    if ($LASTEXITCODE -ne 0) { throw "link failed: $LASTEXITCODE" }
}
finally { Pop-Location }

$exe = Join-Path $OutDir 'UITest.exe'
if (Test-Path $exe) {
    Write-Host "=== OK: $exe ($((Get-Item $exe).Length) bytes) ===" -ForegroundColor Green
} else {
    throw "UITest.exe not produced"
}
