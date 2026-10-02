# =============================================================================
#  UIAInvokeHelperWndClass 隐藏窗口探针  —— 教程3 配套可运行验证
#
#  验证目标（三条）：
#    ① UIA 客户端访问前，窗口不存在            （惰性创建）
#    ② UIA 客户端访问后，窗口出现              （被 UIA 路径拉起）
#    ③ 伪造 WM_GETOBJECT 不能让窗口出现         （只有真实 UIA 路径才建）
#
#  用法：  pwsh -File docs/duixml-tutorials/probe-uia-invokehelper.ps1
#  依赖：  .local/build/acceptance-x64/UITest.exe（用真实系统 dui70.dll + 生成 import lib）
#
#  原理：  消息专用窗口（parent = HWND_MESSAGE = -3）不会被 EnumWindows 枚举，
#          必须用 FindWindowExW(HWND_MESSAGE, 0, 类名, $null) 直接找。
# =============================================================================
[CmdletBinding()]
param(
    [string]$Exe = "$PSScriptRoot\..\..\.local\build\acceptance-x64\UITest.exe"
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowExW(IntPtr p, IntPtr c, string cls, string win);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern uint RegisterWindowMessageW(string s);
'@

$HWND_MESSAGE = [IntPtr](-3)
$CLASS = 'UIAInvokeHelperWndClass'

function Find-Helper {
    [W.U]::FindWindowExW($HWND_MESSAGE, [IntPtr]::Zero, $CLASS, $null)
}

$Exe = (Resolve-Path $Exe).Path
Write-Host "宿主: $Exe"
$proc = Start-Process $Exe -PassThru
try {
    Start-Sleep -Seconds 3
    $proc.Refresh()
    $hwndHost = $proc.MainWindowHandle
    Write-Host "主窗口 HWND = 0x$('{0:X}' -f $hwndHost.ToInt64())  pid = $($proc.Id)"
    Write-Host ""

    # --- 消息 id（dui70 用 RegisterWindowMessageW 注册，进程内一致）--------
    $msg = [W.U]::RegisterWindowMessageW('DUI_UIA_InvokeHelperMsg')
    Write-Host "[0] RegisterWindowMessageW('DUI_UIA_InvokeHelperMsg') = 0x$('{0:X}' -f $msg)"
    Write-Host ""

    # --- ① 访问前 -----------------------------------------------------------
    $before = Find-Helper
    Write-Host "[1] UIA 访问前 : $before"
    $r1 = ($before -eq [IntPtr]::Zero)
    Write-Host "    => 不存在? $r1"
    Write-Host ""

    # --- ③ 负向对照：伪造 WM_GETOBJECT --------------------------------------
    Add-Type -Namespace W -Name S -MemberDefinition @'
[DllImport("user32.dll")] public static extern IntPtr SendMessageTimeoutW(IntPtr h, uint m, IntPtr w, IntPtr l, uint f, uint t, out IntPtr r);
'@
    $res = [IntPtr]::Zero
    # 0x3D = WM_GETOBJECT, lParam = -25 = UiaRootObjectId
    $null = [W.S]::SendMessageTimeoutW($hwndHost, 0x3D, [IntPtr]::Zero, [IntPtr](-25), 2, 3000, [ref]$res)
    Start-Sleep -Milliseconds 700
    $afterRaw = Find-Helper
    Write-Host "[2] 裸发 WM_GETOBJECT(0x3D, -25) 后 : $afterRaw   (ret=0x$('{0:X}' -f $res.ToInt64()))"
    $r2 = ($afterRaw -eq [IntPtr]::Zero)
    Write-Host "    => 仍不存在? $r2   （说明只有真实 UIA 客户端路径会创建）"
    Write-Host ""

    # --- ② 真实 UIA 客户端访问 ---------------------------------------------
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwndHost)
    $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                         [System.Windows.Automation.Condition]::TrueCondition)
    Start-Sleep -Milliseconds 900
    $after = Find-Helper
    Write-Host "[3] 真实 UIA 客户端访问后 : $after"
    $r3 = ($after -ne [IntPtr]::Zero)
    Write-Host "    => 出现了? $r3"
    Write-Host ""

    Write-Host "--- UIA 树观测 ---"
    Write-Host "  root Name='$($root.Current.Name)'  ControlType=$($root.Current.ControlType.ProgrammaticName)"
    Write-Host "  root ClassName='$($root.Current.ClassName)'  FrameworkId='$($root.Current.FrameworkId)'"
    Write-Host "  descendants = $($all.Count)"
    $hist = @{}
    foreach ($e in $all) {
        $ct = $e.Current.ControlType.ProgrammaticName -replace '^ControlType\.', ''
        $hist[$ct] = 1 + ($hist[$ct] | ForEach-Object { $_ })
    }
    $hist.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host ("    {0,-14} {1}" -f $_.Key, $_.Value) }
    Write-Host ""

    if ($after -ne [IntPtr]::Zero) {
        $sb = New-Object System.Text.StringBuilder 256
        [void][W.U]::GetClassNameW($after, $sb, 256)
        $sb2 = New-Object System.Text.StringBuilder 256
        [void][W.U]::GetWindowTextW($after, $sb2, 256)
        $pid2 = 0
        [void][W.U]::GetWindowThreadProcessId($after, [ref]$pid2)
        Write-Host "--- 隐藏窗口身份 ---"
        Write-Host "  hwnd       = $after"
        Write-Host "  class      = '$($sb.ToString())'"
        Write-Host "  text       = '$($sb2.ToString())'"
        Write-Host "  owner pid  = $pid2   (UITest pid = $($proc.Id))"
        Write-Host "  same proc  = $($pid2 -eq $proc.Id)"
        Write-Host "  parent     = $([W.U]::GetParent($after))   (-3/HWND_MESSAGE => 消息专用窗口)"
        Write-Host "  visible    = $([W.U]::IsWindowVisible($after))"
    }

    Write-Host ""
    Write-Host "===== 判定 ====="
    Write-Host "  ① 访问前不存在        : $r1"
    Write-Host "  ② 裸消息不创建(负向对照): $r2"
    Write-Host "  ③ UIA 访问后出现       : $r3"
    if ($r1 -and $r2 -and $r3) { Write-Host "  => 三条全部符合反汇编预测 PASS" }
    else { Write-Host "  => 有偏差，请检查" }
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
