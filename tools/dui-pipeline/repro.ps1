<#
.SYNOPSIS
    Stage-2 CI entry: re-derive pinned/ from msdl and assert byte-equality.

.DESCRIPTION
    Downloads BOTH artefacts named by manifest.dll.source_url and
    manifest.pdb.source_url, hard-asserts their sha256 against the pinned
    manifest, re-runs the DLL+PDB -> pinned derivation in an isolated directory,
    and asserts the result is byte-identical to the committed pinned/.

    The actual assertions live in repro.py; this script only locates the
    toolchain, so the same logic is runnable by a human and by CI.

    Gates (see CI.md 7 and INTERFACE.md 6):
      R1  both source_urls well-formed; downloads byte-identical to manifest
          (sha256+size); PE-derived dll slot and RSDS-derived pdb slot both
          equal the slot stored in source_url.
      R2  no PDB beside the DLL (it changes dumpbin's output); llvm-pdbutil
          produces publics; exports.json byte-identical; manifest
          sha256/size/arch/guid/age match.
      R3  symbols.json byte-identical (11983 rows). No exemptions.

    DLL and PDB are downloaded into SEPARATE directories on purpose -- see the
    trap documented in repro.py and CI.md 7.3.

.PARAMETER Python
    Python interpreter. Defaults to DSH_CI_PYTHON/PATH/well-known locations.

.PARAMETER Dumpbin
    dumpbin.exe. Defaults to DUMPBIN/PATH/vswhere-discovered MSVC.

.PARAMETER Pdbutil
    llvm-pdbutil. Defaults to LLVM_PDBUTIL/PATH/well-known LLVM roots.

.PARAMETER Undname
    llvm-undname. Defaults to LLVM_UNDNAME/PATH/well-known LLVM roots. MSVC's
    undname.exe is deliberately NOT accepted (it silently corrupts the model);
    repro.py proves the tool by its output format.

.PARAMETER SecondsBudget
    Wall-clock budget (default 900 = 15 minutes; the download dominates).

.EXAMPLE
    pwsh -File tools/dui-pipeline/repro.ps1
#>
[CmdletBinding()]
param(
    [string]$Python,
    [string]$Dumpbin,
    [string]$Pdbutil,
    [string]$Undname,
    [int]$SecondsBudget = 900,
    [string]$WorkDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# Forward slashes throughout (ubuntu-safe / no backslash-as-literal traps).
$script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$script:Start = Get-Date

if (-not $WorkDir) { $WorkDir = Join-Path $script:Repo '.local/build/repro' }

function Write-Head([string]$text) {
    Write-Host ''
    Write-Host "==== $text " -NoNewline -ForegroundColor Cyan
    Write-Host ('=' * [Math]::Max(0, 68 - $text.Length)) -ForegroundColor Cyan
}
function Write-Ok([string]$text)   { Write-Host "  [ OK ] $text" -ForegroundColor Green }
function Write-Bad([string]$text)  { Write-Host "  [FAIL] $text" -ForegroundColor Red }
function Write-Info([string]$text) { Write-Host "         $text" -ForegroundColor DarkGray }

function Fail([string]$id, [string]$expected, [string]$actual, [string[]]$detail) {
    # Same machine-greppable shape as ci.ps1 / the Python helpers.
    [Console]::Error.WriteLine("GATE ${id}: FAIL  expected=$expected  actual=$actual")
    Write-Bad "$id"
    Write-Host "         expected: $expected" -ForegroundColor Yellow
    Write-Host "         actual  : $actual"   -ForegroundColor Yellow
    foreach ($d in $detail) { Write-Host "         $d" -ForegroundColor Yellow }
    exit 1
}

# Join-Path with a null/empty base does NOT throw; it emits malformed paths and
# "not recognised" noise when ProgramFiles(x86) is unset. Same helper as ci.ps1.
function Join-Base([string]$Base, [string]$Child) {
    if ([string]::IsNullOrWhiteSpace($Base)) { return $null }
    return (Join-Path $Base $Child)
}

function Resolve-Python {
    if ($Python) {
        if (-not (Test-Path $Python)) { throw "-Python '$Python' does not exist" }
        return (Resolve-Path $Python).Path
    }
    foreach ($ev in @('DSH_CI_PYTHON', 'DUI_PIPELINE_PYTHON')) {
        $v = [Environment]::GetEnvironmentVariable($ev)
        if ($v -and (Test-Path $v)) { return (Resolve-Path $v).Path }
    }
    foreach ($name in @('python', 'python3', 'py')) {
        # Get-Command can return MULTIPLE matches (the GitHub runner has git/bin,
        # git/cmd and git/mingw64 on PATH); .Source on an array stringifies them
        # into a single un-runnable command. Pick the first explicitly.
        $cmd = @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue) |
            Select-Object -First 1
        if ($cmd) {
            if ($name -eq 'py') {
                $ver = & $cmd.Source -3 -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) { return $ver.Trim() }
                continue
            }
            return $cmd.Source
        }
    }
    $candidates = @()
    if ($env:LOCALAPPDATA) {
        foreach ($v in @('Python313', 'Python312', 'Python311', 'Python310')) {
            $candidates += Join-Path $env:LOCALAPPDATA "Programs/Python/$v/python.exe"
        }
    }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        foreach ($v in @('Python313', 'Python312', 'Python311', 'Python310')) {
            $candidates += Join-Path $base "$v/python.exe"
        }
    }
    $candidates += @('C:\Python313\python.exe', 'C:\Python312\python.exe',
                     'C:\Python311\python.exe')
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    throw "Python interpreter not found. Pass -Python <path> or set DSH_CI_PYTHON."
}

function Resolve-Dumpbin {
    if ($Dumpbin) {
        if (-not (Test-Path $Dumpbin)) { throw "-Dumpbin '$Dumpbin' does not exist" }
        return (Resolve-Path $Dumpbin).Path
    }
    # extract.py honours the DUMPBIN environment variable first, so a resolved
    # path here is exported for the child process as well.
    foreach ($ev in @('DUMPBIN', 'DSH_CI_DUMPBIN')) {
        $v = [Environment]::GetEnvironmentVariable($ev)
        if ($v -and (Test-Path $v)) { return (Resolve-Path $v).Path }
    }
    $cmd = @(Get-Command 'dumpbin' -CommandType Application -ErrorAction SilentlyContinue) |
        Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    # vswhere -> newest MSVC toolset (Visual Studio does not PATH its tools)
    $vswhere = Join-Base ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if ($vswhere -and (Test-Path $vswhere)) {
        $install = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null | Select-Object -First 1
        if ($install) {
            $msvcDir = Join-Path $install 'VC/Tools/MSVC'
            if (Test-Path $msvcDir) {
                $cand = Get-ChildItem $msvcDir -Directory |
                    Sort-Object { [version]($_.Name -replace '[^0-9.].*$', '') } -Descending |
                    Select-Object -First 1
                if ($cand) {
                    $exe = Join-Path $cand.FullName 'bin/Hostx64/x64/dumpbin.exe'
                    if (Test-Path $exe) { return $exe }
                }
            }
        }
    }
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        foreach ($ed in @('Enterprise', 'Professional', 'Community', 'BuildTools')) {
            $r = Join-Path $base "Microsoft Visual Studio/2022/$ed/VC/Tools/MSVC"
            if (-not (Test-Path $r)) { continue }
            $cand = Get-ChildItem $r -Directory |
                Sort-Object { [version]($_.Name -replace '[^0-9.].*$', '') } -Descending |
                Select-Object -First 1
            if ($cand) {
                $exe = Join-Path $cand.FullName 'bin/Hostx64/x64/dumpbin.exe'
                if (Test-Path $exe) { return $exe }
            }
        }
    }
    return $null   # repro.py reports a clean failure for a missing dumpbin
}

Write-Head 'repro: re-derive pinned/ from the msdl binary'
$py = Resolve-Python
Write-Info "python  : $py"
$script:db = Resolve-Dumpbin
if ($script:db) { Write-Info "dumpbin : $script:db" } else { Write-Info 'dumpbin : not found (extract.py will report it)' }
if ($Undname) { Write-Info "undname : $Undname" } else { Write-Info 'undname : auto (LLVM probed by output format)' }
if ($Pdbutil) { Write-Info "pdbutil : $Pdbutil" } else { Write-Info 'pdbutil : auto (llvm-pdbutil located by repro.py)' }

# model.py lives in the pipeline dir; resolved tools are passed explicitly so CI
# and local runs take the same path.
$argv = @(
    (Join-Path $PSScriptRoot 'repro.py'),
    '--pinned', (Join-Path $script:Repo 'pinned'),
    '--work', $WorkDir,
    '--python', $py
)
if ($script:db) { $argv += @('--dumpbin', $script:db) }
if ($Pdbutil)  { $argv += @('--pdbutil', $Pdbutil) }
if ($Undname)  { $argv += @('--undname', $Undname) }

$env:PYTHONUTF8 = '1'
& $py @argv
$rc = $LASTEXITCODE
$elapsed = ((Get-Date) - $script:Start).TotalSeconds

if ($rc -ne 0) {
    Write-Head 'SUMMARY'
    Write-Bad ("repro: FAILED (rc=$rc, {0:N1}s)" -f $elapsed)
    exit 1
}

if ($elapsed -gt $SecondsBudget) {
    Fail 'GB' "whole run < $SecondsBudget s" ("{0:N1} s" -f $elapsed) `
        @('Over budget usually means the msdl download was slow or retried.',
          'The assertions themselves are CPU-light.')
}

Write-Head 'SUMMARY'
Write-Ok ("R1+R2+R3 PASS   ({0:N1}s of {1}s budget)" -f $elapsed, $SecondsBudget)
exit 0
