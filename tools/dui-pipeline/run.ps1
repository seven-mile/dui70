# dui-pipeline orchestrator: one command from pinned inputs to a verified window.
#
# Default mode (pinned -> golden -> build -> run):
#   1. regen.py        -> DirectUI/            (def + include + src, from pinned/)
#   2. lib.exe /def    -> .local/build/lib/dui70.lib
#   3. verify_codegen  -> modname fidelity     (stub TUs vs pinned exports)
#   4. gen_uitest_proj -> .local/build/acceptance-x64/UITest.exe
#   5. run + assert window title == 'Microsoft DirectUI Test' (real system dui70.dll)
#
# Refresh mode (-RefreshPin; needs MSVC + dumpbin + llvm tools + the exact pinned
# DLL/PDB by sha256): re-derives pinned/ from the system DLL, then continues.
#
# Legacy C entry points (InitProcessPriv etc.) need NO shim: generated headers
# declare them extern "C", matching the real DLL's export form.
#
# Usage:
#   pwsh -File tools\dui-pipeline\run.ps1 [-SkipRun] [-SkipCodegen] [-RefreshPin] [-X86]
param(
    [switch]$SkipRun,
    [switch]$SkipCodegen,
    [switch]$RefreshPin,
    [switch]$X86
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

$vcRoot = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
$vcBin  = "$vcRoot\bin\Hostx64\x64"
$py     = 'C:\Users\7mile\AppData\Local\Programs\Python\Python311\python.exe'
$build  = Join-Path $repo '.local\build'
$pinned = Join-Path $repo 'pinned'
New-Item -ItemType Directory -Force -Path $build, "$build\lib" | Out-Null

# --- step 0 (optional): refresh pinned from the system DLL -------------------
if ($RefreshPin) {
    Write-Host "==> [0] refresh pinned/ from system dui70.dll (sha256-verified)" -ForegroundColor Magenta
    & $py (Join-Path $PSScriptRoot 'extract.py') --pinned $pinned
    if ($LASTEXITCODE -ne 0) { throw "extract.py failed" }
    & $py (Join-Path $PSScriptRoot 'model.py') --pinned $pinned
    if ($LASTEXITCODE -ne 0) { throw "model.py failed" }
}

# --- step 1: regenerate the golden tree --------------------------------------
if (-not $SkipCodegen) {
    Write-Host "==> [1/5] regen DirectUI/ from pinned/" -ForegroundColor Cyan
    & $py (Join-Path $PSScriptRoot 'regen.py') 2>&1 | Select-Object -Last 4
    if ($LASTEXITCODE -ne 0) { throw "regen failed" }
}

# --- step 2: import library from the golden def ------------------------------
Write-Host "==> [2/5] lib.exe import library from DirectUI\dui70.def" -ForegroundColor Cyan
Remove-Item (Join-Path $build 'lib\dui70.lib') -Force -ErrorAction SilentlyContinue
& "$vcBin\lib.exe" /nologo /def:"$repo\DirectUI\dui70.def" /machine:x64 `
    /out:"$build\lib\dui70.lib" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "lib.exe failed" }

# --- step 3: modname fidelity ------------------------------------------------
if (-not $SkipCodegen) {
    Write-Host "==> [3/5] verify_codegen: stub modnames vs pinned exports" -ForegroundColor Cyan
    & $py (Join-Path $PSScriptRoot 'verify_codegen.py') 2>&1 | Select-Object -Last 8
    if ($LASTEXITCODE -ne 0) { throw "verify_codegen failed" }
}

# --- step 4: build acceptance exe --------------------------------------------
Write-Host "==> [4/5] build UITest against generated dui70.lib" -ForegroundColor Cyan
& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'gen_uitest_proj.ps1') -Lib "$build\lib\dui70.lib"
if ($LASTEXITCODE -ne 0) { throw "gen_uitest_proj failed" }

# --- step 5: run + assert ----------------------------------------------------
if ($SkipRun) { Write-Host "==> [5/5] skipped (-SkipRun)"; return }
Write-Host "==> [5/5] run acceptance exe, assert window" -ForegroundColor Cyan
$exe = Join-Path $build 'acceptance-x64\UITest.exe'
$p = Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -PassThru
Start-Sleep -Seconds 5
try {
    if ($p.HasExited) { throw "UITest exited prematurely: 0x$('{0:X}' -f $p.ExitCode)" }
    $proc = Get-Process -Id $p.Id -ErrorAction Stop
    $title = $proc.MainWindowTitle
    $dui = (Get-Process -Id $p.Id -Module -ErrorAction SilentlyContinue |
            Where-Object ModuleName -eq 'dui70.dll').FileName
    Write-Host "    title : $title"
    Write-Host "    dui70 : $dui"
    if ($title -ne 'Microsoft DirectUI Test') { throw "unexpected window title: '$title'" }
    if ($dui -notmatch 'SYSTEM32') { throw "dui70.dll not loaded from system32: $dui" }
    $null = $proc.CloseMainWindow()
    Start-Sleep -Seconds 2
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -Confirm:$false }
    Write-Host "ACCEPTANCE PASS: window created via real system dui70.dll" -ForegroundColor Green
}
finally {
    if (-not $p.HasExited -and (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue
    }
}
