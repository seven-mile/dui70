<#
.SYNOPSIS
    dui-pipeline CI gate. One command, no arguments, green/red verdict.

.DESCRIPTION
    Turns the pipeline's regression discipline ("re-run regen.py, then
    `git diff --exit-code DirectUI/`") from a verbal convention into an
    executable gate. Consumer only: this script NEVER edits pinned/ or
    DirectUI/, and never touches the pipeline's core logic.

    Gates, run in order, first failure stops:
      G1  input integrity   pinned/ matches tools/dui-pipeline/pinned.sha256
      G2  golden regen      regen.py is byte-stable: git diff --exit-code
      G3  structure         classes.json class count == generated tree
      G4  ABI fidelity      modname N/N + extern-C N/N (compile-derived)
      G4-Y Option D yield   R1 symbol-exactness + R2 slot order + R5
                            compile matrix + N1-N4 tamper controls
      G5  headers           random sample syntax-checked with cl /Zs
      J1  vtable slots      report-only: slot-order verdict recorded, exit 0

    Exit code 0 = all green. Non-zero = the first failing gate; the message
    names the gate, what was expected, and what was actually observed.
    (J1 is transitional: it records its verdict -- currently 40/103 classes
    have header virtual order different from J1's first-occurrence heuristic
    (the fold-pair constraint solver fixed the OnNotify/OnMessage family to
    the DLL-proven order, which the heuristic cannot see) --
    into the log and a JSON artifact without failing the run. The printed
    verdict is "REPORT-ONLY: FAIL", never a masked PASS.)

.PARAMETER SkipHeaderCheck
    Skip G5 (useful on a machine without MSVC; G4 still needs it).

.PARAMETER SkipJ1
    Skip J1 (the report-only vtable slot-order gate).

.PARAMETER GoldenOnly
    Run G1+G2 only -- the fast (<20s) subset that needs neither MSVC nor a
    compiler. This is what the ubuntu GitHub job can run.

.PARAMETER AllowDirty
    Skip G2's "tree must be clean" precheck. regen.py rewrites the files it
    generates, so running the gates on a tree with uncommitted edits would
    silently destroy them; the precheck refuses by default. Set this only when
    you accept that (e.g. to inspect the golden diff of a generator change).

.PARAMETER SelfTest
    Verify the gate logic itself detects corruption (does not run the gates).

.PARAMETER Python / VcRoot / SdkVersion
    Explicit toolchain overrides. All are auto-discovered when omitted.

.PARAMETER SecondsBudget
    Wall-clock budget for the whole run (default 600 = 10 minutes).

.EXAMPLE
    pwsh -File tools\dui-pipeline\ci.ps1
.EXAMPLE
    pwsh -File tools\dui-pipeline\ci.ps1 -GoldenOnly
#>
[CmdletBinding()]
param(
    [string]$Python,
    [string]$VcRoot,
    [string]$SdkVersion,
    [switch]$SkipHeaderCheck,
    [switch]$SkipAbiCheck,
    [switch]$SkipJ1,
    [switch]$GoldenOnly,
    [switch]$AllowDirty,
    [switch]$SelfTest,
    [int]$HeaderSample = 12,
    [int]$HeaderSeed = 20261002,
    [int]$SecondsBudget = 600,
    [string]$WorkDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# Forward slashes throughout: they work on Windows AND on the Linux runner that
# the `golden` GitHub job uses. On Linux a backslash is an ordinary filename
# character, so `'..\..'` would not resolve as a parent traversal.
$script:Repo   = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$script:Checks = Join-Path $PSScriptRoot 'ci_checks.py'
$script:Start  = Get-Date
$script:GateTable = New-Object System.Collections.ArrayList

if (-not $WorkDir) { $WorkDir = Join-Path $script:Repo '.local/build/ci' }

# ------------------------------------------------------------------ presentation
function Write-Head([string]$text) {
    Write-Host ''
    Write-Host "==== $text " -NoNewline -ForegroundColor Cyan
    Write-Host ('=' * [Math]::Max(0, 68 - $text.Length)) -ForegroundColor Cyan
}
function Write-Ok([string]$text)   { Write-Host "  [ OK ] $text" -ForegroundColor Green }
function Write-Bad([string]$text)  { Write-Host "  [FAIL] $text" -ForegroundColor Red }
function Write-Info([string]$text) { Write-Host "         $text" -ForegroundColor DarkGray }

function Add-Gate([string]$id, [string]$name, [string]$status,
                  [double]$seconds, [string]$note = '') {
    $null = $script:GateTable.Add([pscustomobject]@{
        Id = $id; Name = $name; Status = $status
        Seconds = [Math]::Round($seconds, 1); Note = $note
    })
}

function Fail-Gate([string]$id, [string]$name, [string]$expected,
                   [string]$actual, [string[]]$detail, [double]$seconds) {
    # Machine-greppable single line, same shape as the Python helpers' output, so
    # both sides of the CI are parseable by one pattern:  GATE <id>: FAIL  expected=.. actual=..
    [Console]::Error.WriteLine("GATE ${id}: FAIL  expected=$expected  actual=$actual")
    Write-Bad "$id $name"
    Write-Host "         expected: $expected" -ForegroundColor Yellow
    Write-Host "         actual  : $actual"   -ForegroundColor Yellow
    foreach ($d in $detail) { Write-Host "         $d" -ForegroundColor Yellow }
    Add-Gate $id $name 'FAIL' $seconds $actual
    Show-Summary
    exit 1
}

function Show-Summary() {
    $total = ((Get-Date) - $script:Start).TotalSeconds
    Write-Head 'SUMMARY'
    foreach ($g in $script:GateTable) {
        $tag = if ($g.Status -eq 'PASS') { 'PASS' }
               elseif ($g.Status -eq 'FAIL') { 'FAIL' }
               else { $g.Status }
        $color = if ($g.Status -eq 'PASS') { 'Green' }
                 elseif ($g.Status -eq 'FAIL') { 'Red' } else { 'DarkGray' }
        $line = "  {0,-4} {1,-4} {2,-22} {3,7:N1}s" -f $g.Id, $tag, $g.Name, $g.Seconds
        if ($g.Note) { $line += "  $($g.Note)" }
        Write-Host $line -ForegroundColor $color
    }
    Write-Host ''
    $failed = @($script:GateTable | Where-Object Status -eq 'FAIL').Count
    $verdict = if ($failed -eq 0) { 'ALL GATES PASS' } else { "$failed GATE(S) FAILED" }
    $color = if ($failed -eq 0) { 'Green' } else { 'Red' }
    Write-Host ("  {0}   ({1:N1}s of {2}s budget)" -f $verdict, $total, $SecondsBudget) `
        -ForegroundColor $color
    Write-Host ''
}

# Budget gate. Must run on EVERY exit path (including -GoldenOnly), so it is a
# function called just before each exit rather than inline at the end.
function Test-Budget {
    $total = ((Get-Date) - $script:Start).TotalSeconds
    if ($total -gt $SecondsBudget) {
        $slowest = $script:GateTable | Sort-Object Seconds -Descending | Select-Object -First 1
        $note = if ($slowest) { "slowest: $($slowest.Id) $($slowest.Name) $($slowest.Seconds)s" } else { '' }
        Fail-Gate 'GB' 'time budget' "whole run < $SecondsBudget s" `
            "$([Math]::Round($total,1)) s" `
            @("$note",
              'Over budget usually means a gate became nondeterministic (network,',
              'fresh full recompile, antivirus). Investigate that gate first.') 0
    }
    Add-Gate 'GB' 'time budget' 'PASS' $total "under ${SecondsBudget}s"
}

function Finish([int]$code) {
    if ($code -eq 0) { Test-Budget }
    Show-Summary
    exit $code
}

# ------------------------------------------------------------------ toolchain
# Join-Path with a $null/-empty base does NOT throw: it binds the literal string
# to -ChildPath and leaves -Path null, which then emits "cannot be recognised as
# a cmdlet" errors and yields a bogus path. On a machine where ProgramFiles(x86)
# is unset (or under a stripped PATH) that turned discovery into noise instead of
# a clean "not found". Every probe therefore goes through this helper.
function Join-Base([string]$Base, [string]$Child) {
    if ([string]::IsNullOrWhiteSpace($Base)) { return $null }
    return (Join-Path $Base $Child)
}

function Resolve-Python {
    if ($Python) {
        if (-not (Test-Path $Python)) { throw "python not found at -Python '$Python'" }
        return $Python
    }
    # explicit env override beats PATH
    foreach ($ev in @('DSH_CI_PYTHON', 'DUI_PIPELINE_PYTHON', 'PYTHON')) {
        $v = [Environment]::GetEnvironmentVariable($ev)
        if ($v -and (Test-Path $v)) { return $v }
    }
    foreach ($name in @('python', 'python3', 'py')) {
        # Select-Object -First 1: Get-Command can return multiple matches, and
        # $c.Source on an array stringifies all of them into one bad path.
        $c = @(Get-Command $name -ErrorAction SilentlyContinue) | Select-Object -First 1
        if ($c) {
            # `py -3` is a launcher, not an interpreter path; verify it runs
            try {
                $exe = $c.Source
                if ($name -eq 'py') {
                    $ver = & $exe -3 -c "import sys;print(sys.executable)" 2>$null
                    if ($LASTEXITCODE -eq 0 -and $ver) { return $ver.Trim() }
                    continue
                }
                return $exe
            } catch { continue }
        }
    }
    # Windows-specific fallbacks, built defensively: on Linux these env vars are
    # unset, and Join-Path with a $null Path throws. Only build an entry from a
    # base directory that exists, so this block is a no-op off Windows.
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

function Resolve-VcRoot {
    # Read the -VcRoot PARAMETER explicitly. The caller also declares a local
    # named $vcToolsRoot; a bare `$VcRoot` read would resolve correctly today but
    # is exactly the kind of shadowing that silently ignored -VcRoot before.
    $explicit = $VcRoot
    if ($explicit) {
        if (-not (Test-Path (Join-Path $explicit 'bin\Hostx64\x64\cl.exe'))) {
            throw "-VcRoot '$explicit' has no bin\Hostx64\x64\cl.exe -- pass the versioned MSVC toolset dir, e.g. <VS>\VC\Tools\MSVC\14.44.35207"
        }
        return $explicit
    }
    # env override: a VS developer prompt sets VCToolsInstallDir
    foreach ($ev in @('DSH_CI_VCROOT', 'DUI_PIPELINE_VCROOT')) {
        $v = [Environment]::GetEnvironmentVariable($ev)
        if ($v -and (Test-Path (Join-Path $v 'bin\Hostx64\x64\cl.exe'))) { return $v }
    }
    $vct = [Environment]::GetEnvironmentVariable('VCToolsInstallDir')
    if ($vct -and (Test-Path (Join-Path $vct 'bin\Hostx64\x64\cl.exe'))) {
        return $vct.TrimEnd('\')
    }
    # vswhere: the supported way to locate VS installs
    $vswhere = Join-Base ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if ($vswhere -and (Test-Path $vswhere)) {
        $install = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null | Select-Object -First 1
        if ($install) {
            $msvcDir = Join-Path $install 'VC\Tools\MSVC'
            if (Test-Path $msvcDir) {
                $cand = Get-ChildItem $msvcDir -Directory |
                    Sort-Object { [version]($_.Name -replace '[^0-9.].*$','') } -Descending |
                    Select-Object -First 1
                if ($cand -and (Test-Path (Join-Path $cand.FullName 'bin\Hostx64\x64\cl.exe'))) {
                    return $cand.FullName
                }
            }
        }
    }
    # common literal fallbacks (Build Tools / Community / Enterprise / Preview),
    # assembled via Join-Base so an unset ProgramFiles(x86) cannot inject a
    # malformed path.
    $roots = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        foreach ($ed in @('Enterprise', 'Professional', 'Community', 'BuildTools')) {
            $roots += (Join-Path $base "Microsoft Visual Studio/2022/$ed/VC/Tools/MSVC")
        }
        $roots += (Join-Path $base 'Microsoft Visual Studio/2019/Community/VC/Tools/MSVC')
        $roots += (Join-Path $base 'Microsoft Visual Studio/2019/BuildTools/VC/Tools/MSVC')
    }
    foreach ($r in $roots) {
        if ($r -and (Test-Path $r)) {
            $cand = Get-ChildItem $r -Directory |
                Sort-Object { [version]($_.Name -replace '[^0-9.].*$','') } -Descending |
                Select-Object -First 1
            if ($cand -and (Test-Path (Join-Path $cand.FullName 'bin\Hostx64\x64\cl.exe'))) {
                return $cand.FullName
            }
        }
    }
    throw "MSVC (x64) not found. Pass -VcRoot <...\VC\Tools\MSVC\<ver>> or set DSH_CI_VCROOT."
}

function Resolve-SdkVersion {
    $sdkRoot = Join-Base ${env:ProgramFiles(x86)} 'Windows Kits/10/Include'
    if ($SdkVersion) {
        $p = Join-Base $sdkRoot $SdkVersion
        if (-not $p -or -not (Test-Path $p)) {
            throw "-SdkVersion '$SdkVersion' not under Windows Kits\10\Include (root: '$sdkRoot')"
        }
        return $SdkVersion
    }
    foreach ($ev in @('DSH_CI_SDKVERSION', 'DUI_PIPELINE_SDKVERSION')) {
        $v = [Environment]::GetEnvironmentVariable($ev)
        if ($v -and ($p = Join-Base $sdkRoot $v) -and (Test-Path $p)) {
            return $v
        }
    }
    $wsd = [Environment]::GetEnvironmentVariable('WindowsSDKVersion')
    if ($wsd) {
        $clean = $wsd.TrimEnd('\')
        if (($p = Join-Base $sdkRoot $clean) -and (Test-Path $p)) {
            return $clean
        }
    }
    if ($sdkRoot -and (Test-Path $sdkRoot)) {
        $cand = Get-ChildItem $sdkRoot -Directory -Filter '10.0.*' |
            Where-Object { $_.Name -notmatch '\.0\.0$' } |
            Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
        if ($cand) { return $cand.Name }
    }
    throw "Windows SDK not found. Pass -SdkVersion <10.0.xxxxx.0> or set DSH_CI_SDKVERSION."
}

# ------------------------------------------------------------------ run helper
# Runs a native command, streams nothing, returns @{ Rc; Out }.
function Invoke-Tool {
    param([string]$Exe, [string[]]$ToolArgs, [string]$Label, [switch]$Echo)
    $out = & $Exe @ToolArgs 2>&1 | Out-String
    $rc = $LASTEXITCODE
    if ($Echo -and $out) { $out.TrimEnd() -split "`r?`n" | ForEach-Object { Write-Info $_ } }
    return @{ Rc = $rc; Out = $out }
}

# ------------------------------------------------------------------ self test
if ($SelfTest) {
    Write-Head 'CI gate-logic self-test'
    $py = Resolve-Python
    $r = Invoke-Tool $py @($script:Checks, 'selftest') -Echo
    if ($r.Rc -ne 0) {
        Write-Bad "self-test failed (rc=$($r.Rc))"
        exit 1
    }
    Write-Ok "gate logic self-test passed"
    exit 0
}

# ============================================================================
Write-Host ''
Write-Host '  dui-pipeline CI' -ForegroundColor White
Write-Info "repo   : $($script:Repo)"
$py = Resolve-Python
Write-Info "python : $py"
$env:PYTHONUTF8 = '1'   # generated trees are UTF-8; keep stdout/io deterministic

# G2 is git-based, so fail fast with a clear message rather than letting a
# missing git surface as a confusing "clean tree" or empty diff.
#
# `Get-Command git -CommandType Application` can return SEVERAL matches -- on the
# GitHub Windows runner, PATH has Git\bin, Git\cmd and Git\mingw64\bin, so it
# returns an ARRAY. Taking `$gitCmd.Source` off an array stringifies the whole
# array into one un-runnable command
# ("C:\...\bin\git.exe C:\...\cmd\git.exe ... is not recognized"), which broke
# every gate on CI while passing locally where there is exactly one match.
# Select the first match explicitly, and verify the resolved path is a real file.
$gitCmd = @(Get-Command git -CommandType Application -ErrorAction SilentlyContinue) |
    Select-Object -First 1
if (-not $gitCmd -or -not $gitCmd.Source -or -not (Test-Path -LiteralPath $gitCmd.Source)) {
    [Console]::Error.WriteLine('GATE G0: FAIL  expected=git on PATH  actual=git not found')
    Write-Bad 'git is required by G2 (golden diff) but was not found on PATH'
    exit 2
}
$script:Git = $gitCmd.Source
Write-Info "git    : $script:Git"

$needMsvc = -not $GoldenOnly -and (-not $SkipAbiCheck -or -not $SkipHeaderCheck)
# NOTE: PowerShell variable names are case-INSENSITIVE, so a local here must not
# be named $vcToolsRoot/$sdkversion etc. -- that would silently clobber the
# corresponding -VcRoot/-SdkVersion parameter and make explicit overrides be
# ignored (a real bug this comment prevents regressing).
$vcToolsRoot = $null; $sdkVer = $null; $clExe = $null
if ($needMsvc) {
    $vcToolsRoot = Resolve-VcRoot
    $sdkVer = Resolve-SdkVersion
    $clExe  = Join-Path $vcToolsRoot 'bin/Hostx64/x64/cl.exe'
    Write-Info "msvc   : $vcToolsRoot"
    Write-Info "sdk    : $sdkVer"
}
if (-not (Test-Path $WorkDir)) { $null = New-Item -ItemType Directory -Force -Path $WorkDir }

# ---------------------------------------------------------------- G1 integrity
Write-Head 'G1  input integrity (pinned/ sha256)'
$t0 = Get-Date
$r = Invoke-Tool $py @($script:Checks, 'hash') -Echo
$dt = ((Get-Date) - $t0).TotalSeconds
if ($r.Rc -ne 0) {
    Fail-Gate 'G1' 'input integrity' `
        'every pinned/ file matches tools/dui-pipeline/pinned.sha256' `
        "hash mismatch or manifest unreadable (rc=$($r.Rc))" `
        @('', 'pinned/ is the frozen contract input. If the change was intentional,',
          're-pin explicitly and update the manifest in the SAME commit:',
          '  python tools/dui-pipeline/ci_checks.py hash --write') $dt
}
Write-Ok 'pinned/ matches the sha256 manifest (LF-canonical, checkout-independent)'
$env:DUI_G1_DONE = '1'
Add-Gate 'G1' 'input integrity' 'PASS' $dt

# ------------------------------------------------------------------- G2 golden
Write-Head 'G2  golden regen (pinned/ -> DirectUI/ must be byte-stable)'
$t0 = Get-Date

# Record the pre-regen dirty state.
#
# This precheck is not merely hygiene -- it closes a real hole. regen.py
# rewrites every file it generates, so an UNCOMMITTED hand-edit to the golden tree
# would be silently reverted by the regen step, and `git diff` would then
# (correctly, but uselessly) report the tree as clean. The precheck is what
# catches uncommitted edits. A COMMITTED hand-edit is caught by the diff below,
# because regen reproduces the generator's output while HEAD holds the edit.
$preStatus = @(& $script:Git -C $script:Repo status --porcelain -- DirectUI pinned)
if ($preStatus.Count -gt 0 -and -not $AllowDirty) {
    $dt = ((Get-Date) - $t0).TotalSeconds
    Fail-Gate 'G2' 'golden regen' `
        'a clean DirectUI/ + pinned/ working tree before regenerating' `
        "$($preStatus.Count) path(s) already modified/untracked" `
        (@('', 'regen.py rewrites each file it generates: an uncommitted hand-edit',
           'would be silently reverted and the golden diff would look clean.',
           'Commit/stash first (or pass -AllowDirty to accept the risk).',
           '', 'Offending paths:') +
         ($preStatus | Select-Object -First 10 | ForEach-Object { "    $_" })) $dt
}

$r = Invoke-Tool $py @((Join-Path $PSScriptRoot 'regen.py'))
if ($r.Rc -ne 0) {
    $dt = ((Get-Date) - $t0).TotalSeconds
    $tail = ($r.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 12)
    Fail-Gate 'G2' 'golden regen' 'regen.py exits 0' "rc=$($r.Rc)" $tail $dt
}

# Two complementary checks, neither of which mutates the index:
#   * `git diff --exit-code` catches modified/deleted TRACKED files
#   * `git ls-files --others` catches NEW untracked generated files, which a
#     bare `git diff` would silently miss
$diff = & $script:Git -C $script:Repo diff --exit-code -- DirectUI pinned 2>&1 | Out-String
$diffRc = $LASTEXITCODE
$untracked = @(& $script:Git -C $script:Repo ls-files --others --exclude-standard -- DirectUI pinned)
$dt = ((Get-Date) - $t0).TotalSeconds
if ($diffRc -ne 0 -or $untracked.Count -gt 0) {
    $lines = @($diff -split "`r?`n" | Select-Object -First 60)
    $nFiles = @($diff -split "`r?`n" | Where-Object { $_ -match '^diff --git' }).Count
    $detail = @('', 'The generator output is not reproducible, OR the committed tree is',
                'stale. A generator change MUST ship with its regenerated golden diff',
                'in the same commit.')
    if ($untracked.Count -gt 0) {
        $detail += @('', "New untracked generated file(s): $($untracked.Count)")
        $detail += ($untracked | Select-Object -First 10 | ForEach-Object { "    $_" })
    }
    if ($nFiles -gt 0) { $detail += @('', 'Diff:') + $lines }
    Fail-Gate 'G2' 'golden regen' `
        'git diff --exit-code DirectUI/ pinned/ empty AND no new untracked files' `
        "$nFiles modified + $($untracked.Count) untracked file(s) differ from golden" `
        $detail $dt
}
Write-Ok 'regen.py reproduced the committed tree byte-for-byte (git diff empty)'
Add-Gate 'G2' 'golden regen' 'PASS' $dt

if ($GoldenOnly) {
    Write-Info '(-GoldenOnly: skipping G3/G4/G5)'
    Finish 0
}

# ---------------------------------------------------------------- G3 structure
Write-Head 'G3  structural assertions (classes.json vs generated tree)'
$t0 = Get-Date
$r = Invoke-Tool $py @($script:Checks, 'struct') -Echo
$dt = ((Get-Date) - $t0).TotalSeconds
if ($r.Rc -ne 0) {
    $tail = ($r.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 14)
    Fail-Gate 'G3' 'structure' `
        'class count == classes.json (read from file, never hardcoded)' `
        "structural mismatch (rc=$($r.Rc))" $tail $dt
}
Write-Ok 'class count and per-class artefacts agree with classes.json'
Add-Gate 'G3' 'structure' 'PASS' $dt

# ------------------------------------------------------------- G4 ABI fidelity
if ($SkipAbiCheck) {
    Write-Head 'G4  ABI fidelity (skipped: -SkipAbiCheck)'
    Add-Gate 'G4' 'ABI fidelity' 'SKIP' 0 'via -SkipAbiCheck'
} else {
    Write-Head 'G4  ABI fidelity (modname + extern-C, compile-derived)'
    $t0 = Get-Date

    # Derive the expected totals from pinned data (never hardcoded).
    $rt = Invoke-Tool $py @($script:Checks, 'totals', '--json')
    if ($rt.Rc -ne 0) {
        $dt = ((Get-Date) - $t0).TotalSeconds
        Fail-Gate 'G4' 'ABI fidelity' 'pinned totals derivable' `
            "ci_checks.py totals failed (rc=$($rt.Rc))" @($rt.Out) $dt
    }
    $tot = $rt.Out | ConvertFrom-Json
    Write-Info ("derived from pinned/: modname={0}  capi={1}  classes={2}" -f `
        $tot.modname_total, $tot.capi_total, $tot.class_count)

    $sdkInc = Join-Base ${env:ProgramFiles(x86)} "Windows Kits/10/Include/$sdkVer"
    $vcBin  = Join-Path $vcToolsRoot 'bin/Hostx64/x64'
    $report = Join-Path $WorkDir 'verify_codegen-report.md'

    # verify_codegen.py compiles every stub TU and compares decorated names
    # against pinned exports -- the authoritative fidelity check.
    $r = Invoke-Tool $py @(
        (Join-Path $PSScriptRoot 'verify_codegen.py'),
        '--vcbin', $vcBin, '--sdk', $sdkInc, '--report', $report)
    $dt = ((Get-Date) - $t0).TotalSeconds

    $out = $r.Out
    $m = [regex]::Match($out, 'TOTAL real-export match:\s*(\d+)\s*/\s*(\d+)')
    $capi = [regex]::Match($out, 'extern-C purity:\s*OK[^\r\n]*?all\s+(\d+)\s+plain-name')
    $tail = @($out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)

    if ($r.Rc -ne 0) {
        Fail-Gate 'G4' 'ABI fidelity' `
            "verify_codegen rc=0 (modname $($tot.modname_total)/$($tot.modname_total), extern-C $($tot.capi_total)/$($tot.capi_total))" `
            "verify_codegen rc=$($r.Rc) -- see $report" $tail $dt
    }
    if (-not $m.Success) {
        Fail-Gate 'G4' 'ABI fidelity' `
            'a "TOTAL real-export match: N/N" line' 'not found in verify_codegen output' `
            ($tail + @('', "full report: $report")) $dt
    }
    $gotMatch = [int]$m.Groups[1].Value
    $gotTotal = [int]$m.Groups[2].Value
    $expTotal = [int]$tot.modname_total
    if ($gotMatch -ne $gotTotal -or $gotTotal -ne $expTotal) {
        Fail-Gate 'G4' 'ABI fidelity' `
            "modname $expTotal/$expTotal (derived from pinned/classes.json)" `
            "verify_codegen reported $gotMatch/$gotTotal" `
            ($tail + @('', "full report: $report")) $dt
    }
    Write-Ok "modname fidelity $gotMatch/$gotTotal (100%), matches pinned-derived total"

    $expCapi = [int]$tot.capi_total
    if (-not $capi.Success) {
        Fail-Gate 'G4' 'ABI fidelity' `
            "extern-C purity OK with all $expCapi plain-name exports defined" `
            'extern-C check line not found' ($tail + @('', "full report: $report")) $dt
    }
    $gotCapi = [int]$capi.Groups[1].Value
    if ($gotCapi -ne $expCapi) {
        Fail-Gate 'G4' 'ABI fidelity' `
            "extern-C $expCapi/$expCapi (derived from pinned/exports.json)" `
            "verify_codegen reported $gotCapi/$gotCapi" `
            ($tail + @('', "full report: $report")) $dt
    }
    Write-Ok "extern-C fidelity $gotCapi/$gotCapi (plain-name exports, undecorated)"
    Add-Gate 'G4' 'ABI fidelity' 'PASS' $dt `
        "modname $gotMatch/$gotTotal, extern-C $gotCapi/$gotCapi"

    # ---- G4-Y: Option D yield verification (R1/R2/R5 + N1-N4) ----
    # uia_yield_verify.py compiles the CApi shape + 13 provider stubs +
    # ElementProvider/Schema/ElementProxy under /Zc:wchar_t-, proves
    # every stub symbol exact-matches pinned exports (R1), checks all
    # 13 primary vftable slot orders vs mi-tables.json fold-tolerantly
    # (R2), and exercises the four tamper negative controls
    # (N1 guard-removed C2011, N2 default-wchar C3668, N3 REQUIRED
    # C1189, N4 wrong-guard C2011). Enforced: any red kills the run.
    $t0y = Get-Date
    $rY = Invoke-Tool $py @((Join-Path $PSScriptRoot 'uia_yield_verify.py'))
    $dty = ((Get-Date) - $t0y).TotalSeconds
    if ($rY.Rc -ne 0) {
        $tailY = @($rY.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 24)
        Fail-Gate 'G4-Y' 'Option D yield verification' `
            'R1 symbol-exactness + R2 slot order + R5 compile matrix + N1-N4 tamper controls all green' `
            "uia_yield_verify rc=$($rY.Rc)" $tailY $dty
    }
    Write-Ok 'Option D yield: R1 13/13 symbol-exact, R2 13/13 fold-tolerant, R5 full matrix, N1-N4 fail as designed'
    Add-Gate 'G4-Y' 'Option D yield verification' 'PASS' $dty
}

# ------------------------------------------------------------------- G5 headers
if ($SkipHeaderCheck) {
    Write-Head 'G5  header compile (skipped: -SkipHeaderCheck)'
    Add-Gate 'G5' 'headers' 'SKIP' 0 'via -SkipHeaderCheck'
} else {
    Write-Head "G5  header compile (sample of $HeaderSample, cl /Zs)"
    $t0 = Get-Date
    $vcInc  = Join-Path $vcToolsRoot 'include'
    $sdkInc = Join-Base ${env:ProgramFiles(x86)} "Windows Kits/10/Include/$sdkVer"
    $r = Invoke-Tool $py @(
        $script:Checks, 'headers',
        '--cl', $clExe, '--vc-include', $vcInc, '--sdk-root', $sdkInc,
        '--sample', "$HeaderSample", '--seed', "$HeaderSeed",
        '--workdir', (Join-Path $WorkDir 'hdrcheck')) -Echo
    $dt = ((Get-Date) - $t0).TotalSeconds
    if ($r.Rc -ne 0) {
        $tail = ($r.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)
        Fail-Gate 'G5' 'headers' `
            "all $HeaderSample sampled headers parse with cl /Zs" `
            "compile error(s) (rc=$($r.Rc))" $tail $dt
    }
    Write-Ok 'sampled headers compile (syntax-only)'
    Add-Gate 'G5' 'headers' 'PASS' $dt
}

# --------------------------------------------------------------------- J1 vtable
# Report-only transitional mode: the vtable slot-order gate records its verdict
# (currently 40/103 different-order after the fold-pair constraint solver) into
# the CI log and a JSON artifact, but exit 0 -- the known ordering debt must
# not redden this PR. The verdict is printed as "REPORT-ONLY: FAIL" and never
# masked as PASS. Note: J1's "real" order uses FIRST OCCURRENCE of a name in
# the contract table, which is a heuristic -- when a name appears both in an
# early inherited fold and as a later own singleton (e.g. PostCreate in
# fold@7/27 + singleton@59; OnMessage/OnNotify in fold@2 + slots 46/47), the
# first-occurrence order can disagree with the DLL-proven header order. The
# full-mangled identity gate (object probe vs pinned DLL deref) is the
# authority for those cases; J1 remains report-only. Switching to enforced
# mode is a separate, deliberate decision after the ordering fix.
if ($SkipJ1) {
    Write-Head 'J1  vtable slot-order (skipped: -SkipJ1)'
    Add-Gate 'J1' 'vtable slot-order' 'SKIP' 0 'via -SkipJ1'
} else {
    Write-Head 'J1  vtable slot-order (report-only)'
    $t0 = Get-Date
    $slots = Join-Path $script:Repo 'pinned/vtable-slots.json'
    $j1Json = Join-Path $WorkDir 'j1-report.json'
    if (-not (Test-Path $slots)) {
        $dt = ((Get-Date) - $t0).TotalSeconds
        # Report-only still requires its INPUT to exist; a missing ground-truth
        # table is a tooling error (exit 2 semantics), not a verdict.
        Fail-Gate 'J1' 'vtable slot-order' `
            'pinned/vtable-slots.json exists (derive: extract-vtable-slots.py)' `
            'missing' @(
                'The table is a pure function of the pinned DLL + symbols.json;',
                'regenerate: python tools/dui-pipeline/extract-vtable-slots.py',
                "  --dll <pinned dui70.dll> --symbols pinned/symbols.json --slots $slots") $dt
    }
    $r = Invoke-Tool $py @($script:Checks, 'j1',
        '--slots', $slots, '--report-only', '--json-out', $j1Json) -Echo
    $dt = ((Get-Date) - $t0).TotalSeconds
    if ($r.Rc -ne 0) {
        $tail = ($r.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)
        # rc != 0 in report-only mode means a tooling/input error (exit 2), not
        # a verdict -- that still fails the run.
        Fail-Gate 'J1' 'vtable slot-order' `
            'report-only gate runs (tooling rc=0; verdict recorded, not enforced)' `
            "tooling error (rc=$($r.Rc))" $tail $dt
    }
    $line = @($r.Out -split "`r?`n" | Where-Object { $_ -match '^GATE J1:' } | Select-Object -First 1)
    $verdict = if ($line) { ($line -replace '^GATE J1:\s*','').Trim() } else { 'NO VERDICT LINE' }
    if ($verdict -notmatch 'REPORT-ONLY: (PASS|FAIL)') {
        Fail-Gate 'J1' 'vtable slot-order' `
            'a "GATE J1: REPORT-ONLY: <verdict>" line' "got: $verdict" `
            @('report-only mode must print the true verdict, never mask it as PASS') $dt
    }
    Write-Info "verdict recorded: $verdict (artifact: $j1Json)"
    Add-Gate 'J1' 'vtable slot-order' 'REPORT' $dt "$verdict (report-only)"
}

# ----------------------------------------------------------- J1-IF interface gate
# IClassInfo interface contract gate (single-point, ENFORCED). Ground truth is
# pinned/vtable-slots.json classes.ClassInfoBase (R3-protected): 19 slots =
# business 0-17 + tail vdtor 18; slots 2/7 _purecall; slot 17 fold-tolerant.
# The gate checks the generated Interfaces.h IClassInfo against that table
# (declaration order == slot order; dtor LAST + protected; purecall slots
# stay pure). Negative controls exercised before shipping: dtor-first FAIL,
# slot2 non-pure FAIL, slot order swap FAIL (see .local/audit).
if ($SkipJ1) {
    Write-Head 'J1-IF  IClassInfo contract (skipped: -SkipJ1)'
    Add-Gate 'J1-IF' 'IClassInfo contract' 'SKIP' 0 'via -SkipJ1'
} else {
    Write-Head 'J1-IF  IClassInfo interface contract (enforced)'
    $t0 = Get-Date
    $slots = Join-Path $script:Repo 'pinned/vtable-slots.json'
    $j1ifJson = Join-Path $WorkDir 'j1if-report.json'
    if (-not (Test-Path $slots)) {
        $dt = ((Get-Date) - $t0).TotalSeconds
        Fail-Gate 'J1-IF' 'IClassInfo contract' `
            'pinned/vtable-slots.json exists' 'missing' @() $dt
    }
    $r = Invoke-Tool $py @($script:Checks, 'j1-if',
        '--slots', $slots, '--json-out', $j1ifJson) -Echo
    $dt = ((Get-Date) - $t0).TotalSeconds
    if ($r.Rc -ne 0) {
        $tail = ($r.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)
        Fail-Gate 'J1-IF' 'IClassInfo contract' `
            'Interfaces.h IClassInfo == ClassInfoBase table contract' `
            "gate rc=$($r.Rc)" $tail $dt
    }
    Write-Ok 'IClassInfo interface matches the pinned ClassInfoBase contract'
    Add-Gate 'J1-IF' 'IClassInfo contract' 'PASS' $dt
}

# ------------------------------------------------------- A1 slot-ABI identity
# Full-mangled vtable slot-identity audit (tracked tool
# tools/dui-pipeline/slot_abi_audit.py). REPORT-ONLY for now: the real
# verdict (N failed / N fold-UNKNOWN) is recorded into the log and a
# JSON artifact, exit 0 -- the known residual failures (check-family
# intermediate-class debt, foreign-class bodies) must not redden PRs
# until adjudicated, but they are NEVER masked as PASS. Enforced mode
# is a separate deliberate decision. The selftest (paired negative
# controls: own-virtual swap + overload swap, each FAIL on the mutated
# side and PASS on the clean side -- never vacuous) IS enforced: a
# vacuous or failing control reddens the run.
if ($SkipJ1) {
    Write-Head 'A1  slot-ABI identity (skipped: -SkipJ1)'
    Add-Gate 'A1' 'slot-ABI identity' 'SKIP' 0 'via -SkipJ1'
} else {
    Write-Head 'A1  slot-ABI identity (report + enforced selftest)'
    $t0 = Get-Date
    $audit = Join-Path $PSScriptRoot 'slot_abi_audit.py'
    $a1Json = Join-Path $WorkDir 'a1-report.json'
    if (-not (Test-Path $audit)) {
        $dt = ((Get-Date) - $t0).TotalSeconds
        Fail-Gate 'A1' 'slot-ABI identity' `
            'tools/dui-pipeline/slot_abi_audit.py exists' 'missing' @() $dt
    } else {
        # 1) selftest: PAIRED negative controls (ENFORCED)
        $rs = Invoke-Tool $py @($audit, '--pinned',
            (Join-Path $script:Repo 'pinned'), '--include',
            (Join-Path $script:Repo 'DirectUI/include'), '--workdir',
            (Join-Path $WorkDir 'a1-selftest'), '--selftest') -Echo
        $dts = ((Get-Date) - $t0).TotalSeconds
        if ($rs.Rc -ne 0) {
            $tail = ($rs.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)
            Fail-Gate 'A1' 'slot-ABI selftest' `
                'paired negative controls: swap FAILs, clean PASSes (non-vacuous)' `
                "selftest rc=$($rs.Rc)" $tail $dts
        } else {
            Write-Ok 'selftest: paired negative controls non-vacuous (swap FAILs, clean PASSes)'
        }
        # 2) full audit: REPORT-ONLY verdict, true FAILs printed, never masked
        $t1 = Get-Date
        $ra = Invoke-Tool $py @($audit, '--pinned',
            (Join-Path $script:Repo 'pinned'), '--include',
            (Join-Path $script:Repo 'DirectUI/include'), '--workdir',
            (Join-Path $WorkDir 'a1-audit'), '--json-out', $a1Json) -Echo
        $dta = ((Get-Date) - $t1).TotalSeconds
        # rc 0 = all pass; rc 1 = real divergences (recorded, not fatal
        # in report-only mode); rc >= 2 = tooling error (fatal)
        if ($ra.Rc -ge 2) {
            $tail = ($ra.Out.TrimEnd() -split "`r?`n" | Select-Object -Last 20)
            Fail-Gate 'A1' 'slot-ABI identity' `
                'audit runs (rc 0/1 = verdicts; rc>=2 = tooling error)' `
                "tooling error (rc=$($ra.Rc))" $tail $dta
        } else {
            $summary = @($ra.Out -split "`r?`n" |
                Where-Object { $_ -match 'checked \d+ classes' } |
                Select-Object -First 1)
            $verdict = if ($ra.Rc -eq 0) { 'REPORT-ONLY: PASS' } else { 'REPORT-ONLY: FAIL' }
            Write-Info "verdict recorded: $verdict -- $summary"
            Add-Gate 'A1' 'slot-ABI identity' 'REPORT' $dta "$verdict -- $summary (report-only)"
        }
    }
}

# ------------------------------------------------------------------- budget
Finish 0
