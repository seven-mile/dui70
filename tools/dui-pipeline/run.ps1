# dui-pipeline orchestrator: one command to reproduce the whole spine.
#
#   1. emit_def.py      -> .local/build/dui70-full.def     (4321 exports from real dui70.dll)
#   2. lib.exe /def     -> .local/build/lib/dui70.lib      (plain-name import library, final)
#   3. codegen          -> .local/build/generated/         (12-class headers + stubs, modname-faithful)
#   4. gen_uitest_proj  -> .local/build/acceptance-x64/UITest.exe
#   5. run + assert window title == 'Microsoft DirectUI Test' (real system dui70.dll)
#
# Legacy C entry points (InitProcessPriv etc.) need NO shim: the generated
# headers declare them extern "C", so the exe imports the plain names the
# real DLL exports directly.
#
# Usage:  pwsh -File tools\dui-pipeline\run.ps1 [-SkipRun] [-SkipCodegen] [-X86]
param(
    [switch]$SkipRun,
    [switch]$SkipCodegen,
    [switch]$X86
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

$vcRoot = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
$vcBin  = "$vcRoot\bin\Hostx64\x64"
$py     = 'C:\Users\7mile\AppData\Local\Programs\Python\Python311\python.exe'
$build  = Join-Path $repo '.local\build'
New-Item -ItemType Directory -Force -Path $build, "$build\lib" | Out-Null

# --- steps 1+2: def + import library ----------------------------------------
Write-Host "==> [1/5] emit .def from real dui70.dll exports" -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot 'emit_def.py') --out (Join-Path $build 'dui70-full.def')
if ($LASTEXITCODE -ne 0) { throw "emit_def failed" }

Write-Host "==> [2/5] lib.exe import library (final: dui70.lib)" -ForegroundColor Cyan
Remove-Item (Join-Path $build 'lib\dui70.lib') -Force -ErrorAction SilentlyContinue
& "$vcBin\lib.exe" /nologo /def:"$build\dui70-full.def" /machine:x64 `
    /out:"$build\lib\dui70.lib" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "lib.exe failed" }

# --- step 3: codegen (headers + stubs + self-verification) ------------------
if (-not $SkipCodegen) {
    Write-Host "==> [3/5] codegen: 12-class headers + stubs (modname fidelity)" -ForegroundColor Cyan
    & $py (Join-Path $PSScriptRoot 'emit_headers.py') --classes ('
        Value,DUIXmlParser,Element,HWNDElement,NativeHWNDHost,TouchButton,Edit,' +
        'Button,Progress,PushButton,TouchCheckBox,XProvider' -replace '\s','') 2>&1 |
        Select-Object -Last 4
    if ($LASTEXITCODE -ne 0) { throw "emit_headers failed" }
    & $py (Join-Path $PSScriptRoot 'emit_stub.py') 2>&1 | Select-Object -Last 4
    if ($LASTEXITCODE -ne 0) { throw "emit_stub failed" }
    # codegen's own verification harness (compiles stubs, compares modnames vs real exports)
    & $py (Join-Path $PSScriptRoot 'verify_codegen.py') 2>&1 | Select-Object -Last 8
    if ($LASTEXITCODE -ne 0) { throw "verify_codegen failed" }
}

# --- step 4: build acceptance exe -------------------------------------------
Write-Host "==> [4/5] build UITest against generated dui70.lib" -ForegroundColor Cyan
& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'gen_uitest_proj.ps1') -Lib "$build\lib\dui70.lib"
if ($LASTEXITCODE -ne 0) { throw "gen_uitest_proj failed" }

# --- step 5: run + assert ---------------------------------------------------
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
