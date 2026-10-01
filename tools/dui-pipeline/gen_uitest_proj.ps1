# Builds UITest.exe against a chosen dui70 import library, WITHOUT modifying UITest/ or the .sln.
#
# Mirrors UITest.vcxproj's Debug|x64 settings:
#   ConfigurationType Application, v143, Unicode, /std:c++20, no PCH, SubSystem Windows
#   TreatWChar_tAsBuiltInType false, IncludePath += WIL + vcpkg detours, link dui70.lib + detours.lib
#
# Toolchain discovery: VS + Windows SDK via vswhere / standard install roots.
# Override with -VcRoot / -SdkVersion / -VcpkgRoot if the defaults don't match.
#
# Usage:
#   pwsh -File gen_uitest_proj.ps1 [-Lib <path>] [-OutDir <dir>] [-VcRoot <msvc>] `
#                                  [-SdkVersion <ver>] [-VcpkgRoot <root>] [-X86]
param(
    [string]$Lib,
    [string]$OutDir,
    [string]$IncludeDir,   # generated headers dir; default DirectUI\include (golden tree)
    [string]$VcRoot,
    [string]$SdkVersion,
    [string]$VcpkgRoot,
    [switch]$X86
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if (-not $IncludeDir) { $IncludeDir = Join-Path $repo 'DirectUI\include' }

$arch = if ($X86) { 'x86' } else { 'x64' }
$hostArch = 'Hostx64'
$targetArch = if ($X86) { 'x86' } else { 'x64' }

# --- toolchain discovery ----------------------------------------------------
if (-not $VcRoot) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path $vswhere) {
        $installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath | Select-Object -First 1
        if ($installPath) {
            $candidate = Get-ChildItem (Join-Path $installPath 'VC\Tools\MSVC') -Directory |
                Sort-Object Name -Descending | Select-Object -First 1
            if ($candidate) { $VcRoot = $candidate.FullName }
        }
    }
    if (-not $VcRoot) { throw "MSVC not found; pass -VcRoot <path to VC\Tools\MSVC\<ver>>" }
}
if (-not $SdkVersion) {
    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Include'
    if (Test-Path $sdkRoot) {
        $SdkVersion = (Get-ChildItem $sdkRoot -Directory -Filter '10.0.*' | Sort-Object Name -Descending |
            Select-Object -First 1).Name
    }
    if (-not $SdkVersion) { throw "Windows SDK not found; pass -SdkVersion <10.0.xxxxx.0>" }
}
if (-not $VcpkgRoot) {
    $detoursPkg0 = if ($X86) { 'x86-windows' } else { 'x64-windows' }
    $probe = Join-Path "installed\$detoursPkg0" 'include\detours'
    $candidates = @($env:VCPKG_ROOT, $env:VCPKG_INSTALLATION,
                    (Join-Path $env:LOCALAPPDATA 'vcpkg'),
                    (Join-Path $env:USERPROFILE 'vcpkg'),
                    'C:\Local\Tools\vcpkg',
                    'C:\vcpkg')
    foreach ($cand in $candidates) {
        if ($cand -and (Test-Path (Join-Path $cand $probe))) { $VcpkgRoot = $cand; break }
    }
    if (-not $VcpkgRoot) {
        throw "vcpkg with detours not found; install detours via vcpkg or pass -VcpkgRoot"
    }
}

$vcBin = Join-Path $VcRoot "bin\$hostArch\$targetArch"
$sdkInc = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\Include\$SdkVersion"
$sdkLib = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\Lib\$SdkVersion"
$sdkBin = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin\$SdkVersion\$targetArch"
$wilInc = Join-Path $repo 'packages\Microsoft.Windows.ImplementationLibrary.1.0.230629.1\include'
$detoursPkg = if ($X86) { 'x86-windows' } else { 'x64-windows' }
$detoursInc = Join-Path $VcpkgRoot "installed\$detoursPkg\include"
$detoursLib = Join-Path $VcpkgRoot "installed\$detoursPkg\lib"

if (-not $Lib) { $Lib = Join-Path $repo '.local\build\lib\dui70.lib' }
if (-not $OutDir) { $OutDir = Join-Path $repo ".local\build\acceptance-$arch" }
# Resolve caller-supplied relative paths against the repo root so cl/pdb
# never see a doubled relative prefix like .local\x\.local\x\UITest.pdb.
# Defaults above are already rooted; only join relative caller input.
if (-not [System.IO.Path]::IsPathRooted($Lib))    { $Lib = Join-Path $repo $Lib }
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path $repo $OutDir }
$Lib = [System.IO.Path]::GetFullPath($Lib)
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
$LibDir = Split-Path -Parent $Lib
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$vcLib = Join-Path $vcRoot "lib\$targetArch"
$ucrtLib = Join-Path $sdkLib "ucrt\$targetArch"
$umLib = Join-Path $sdkLib "um\$targetArch"

# Environment for cl/link/rc
$env:PATH = "$vcBin;$sdkBin;$env:PATH"
# Order matters: generated headers first, so `..\DirectUI\DirectUI.h` inside
# UITest.cpp resolves to the GENERATED aggregate (extern-C APIs).
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

