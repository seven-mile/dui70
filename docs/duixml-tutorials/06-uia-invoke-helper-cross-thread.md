# InvokeHelper：UIA 的跨线程通道

> 读者设定：会用 dui70 写应用的 C++ 开发者（懂 Win32 消息、懂 COM，但不懂 DirectUI 内部）。
> `04-uia-accessible-bridge.md` 讲了 provider 怎么诞生，`05-uia-pattern-providers.md` 讲了 13 条 pattern 生产线。
> 本文讲**它们怎么跨越线程边界**——UIA 客户端在**别的线程/别的进程**里问问题，
> 而 DirectUI 元素是**有线程亲和性**的，这两件事怎么调和。
>
> **本文含可运行验证**（§5），三条预测逐条实测，含**负向对照**。

---

## 0. 问题：UIA 客户端不在你的 UI 线程上

UIA 的架构是：**辅助工具（Narrator / Inspect.exe）通过 `UIAutomationCore.dll`
来问你的进程**。这条调用链发生在：

```
Narrator.exe（另一个进程，另一个线程）
   │  跨进程 COM 调用
   ▼
你进程里的 UIAutomationCore.dll（RPC 线程，不是 UI 线程！）
   │  调用你注册的 IRawElementProvider*
   ▼
dui70 的 ElementProvider / *Provider / Proxy
   │  ← 到这里，代码跑在 RPC 线程上
   ▼
DirectUI Element（只能被 UI 线程碰！）
```

**矛盾**：`Element` 的属性读写、DUser 上下文、`ElementProvider` 的引用，
都**只能在创建它的 UI 线程上**操作。但 provider 的方法却被 RPC 线程调用。

**dui70 的解法**：一个**每线程一个**的 `InvokeHelper` 对象，
配一个**消息专用（message-only）隐藏窗口**，把调用**编组（marshal）回 UI 线程**：

```
RPC 线程                                     UI 线程
   │                                            │
   │ InvokeHelper::DoInvoke(...)                │
   │   ├─ 打包参数到栈上 InvokeArgs 结构         │
   │   └─ SendMessageW(helper_hwnd,             │
   │         DUI_UIA_InvokeHelperMsg, ...)  ────┼──► InvokeHelper::_WndProc
   │                                            │      └─ 解包 + 真正操作 Element
   │  ← 阻塞等待，直到 UI 线程处理完 ────────────┤
   ▼                                            ▼
```

这就是为什么 dui70 里会有一个
`UIAInvokeHelperWndClass` 窗口和 `DUI_UIA_InvokeHelperMsg` 消息。

---

## 1. 机制总览（一张表）

| 组件 | 位置 | 作用 |
|---|---|---|
| `InvokeManager::GetInvokeHelper` | RVA `0x3A780` | 取**当前线程**的 helper，没有就建 |
| `InvokeHelper::Init(UINT)` | RVA `0x2BBA0` | 创建隐藏窗口、注册类、存 WndProc |
| 窗口类名 | 字符串 `UIAInvokeHelperWndClass` @ `0x11FD68` | 消息专用窗口的类 |
| 窗口消息 | `DUI_UIA_InvokeHelperMsg` @ `0x123868` | `RegisterWindowMessageW` 注册的动态消息 |
| `InvokeHelper::_WndProc` | RVA `0x43DA0` | 收到消息 → 解包并在 UI 线程执行（**不调用 `OnInvoke`**，见 §7.4） |
| `InvokeHelper::DoInvoke` | RVA `0x646F0` | 发起方：打包参数 + `SendMessageW` |
| `InvokeHelper::OnInvoke` | RVA `0x43EE0` | **全镜像零引用**（存在但未被任何代码调用，见 §7.4） |
| `InvokeHelper` 对象 | 堆上，**0x20 字节** | `+0x10` = 拥有者线程 id |

`UiaOnGetObject`（`04-uia-accessible-bridge.md` §2.2）在创建 `ElementProvider` **之前**就调用
`GetInvokeHelper`——说明**provider 一诞生就绑定好跨线程通道**。

---

## 2. 消息是动态注册的【实锤】

`DUI_UIA_InvokeHelperMsg` **不是** `WM_USER` 这类固定值，而是
`RegisterWindowMessageW` 动态注册的（值随系统内已注册消息集变化）。

反汇编（RVA `0x1B10` 起的初始化函数）：

```asm
180001b14:  leaq  0x121d4d(%rip), %rcx    # 0x180123868  "DUI_UIA_InvokeHelperMsg"
180001b1b:  callq *0x11778e(%rip)          # RegisterWindowMessageW  (IAT 0x1801192B0)
180001b27:  movl  %eax, 0x181a0f(%rip)     # 0x18018353c  s_uInvokeHelperMsg
```

上面是 **4 个同构的延迟初始化函数**（`0x1B10`/`0x1B40`/`0x1B70`/`0x1BA0`，各自有独立 `.pdata` 范围）之一——每个函数只注册 **1 条**全局消息 id 后 `retq`，模式完全一致：

| 字符串 RVA | 消息名 | 存入全局 |
|---|---|---|
| `0x180123868` | `DUI_UIA_InvokeHelperMsg` | `s_uInvokeHelperMsg` @ `0x18018353C` |
| `0x180123908` | `XElementUnhandledSyschar` | `0x180183538` |
| `0x1801239A0` | `XElementNavigateOut` | `0x180183530` |
| `0x180123A60` | `XElementButtonFocusChange` | `0x180183534` |

**运行时实测**（§5 观测）：

```
RegisterWindowMessageW('DUI_UIA_InvokeHelperMsg') = 0xC075
```

**为什么用动态注册而不是 `WM_APP+N`？** 【强推】因为这是**跨模块协议**：
`UIAutomationCore.dll` 或另一个 dui70 消费者可能也要发这条消息。
`RegisterWindowMessageW` 保证**全系统同一字符串得到同一 id**，
而 `WM_APP+N` 只在单进程内有意义。

---

## 3. 隐藏窗口：消息专用【实锤】

`InvokeHelper::Init(void*)`（RVA `0x2BBA0`）反汇编：

```asm
18002bbbf:  movl  %edx, 0x10(%rcx)         ; this->+0x10 = 参数（后来用）★
18002bbe2:  callq *0x1801196c0             ; GetModuleHandleW(NULL)  取本模块 hInstance
18002bbee:  leaq  0x18011fd68, %r14        ; 窗口类名字符串 "UIAInvokeHelperWndClass"
18002bbf8:  movq  %r14, %rdx
18002bbff:  callq 0x18002c0ac              ; ← dui70 内部"注册窗口类"辅助函数
18002bc08:  je    <失败返回>
18002bc12:  movq  $-0x3, 0x40(%rsp)        ; 父窗口 = -3 = HWND_MESSAGE ★
18002bc33:  callq 0x18002bdd8              ; ← dui70 内部"创建窗口"辅助函数
18002bc38:  movq  %rax, 0x18(%rdi)         ; this->+0x18 = HWND ★
18002bc3f:  je    <失败>
18002bc44:  leaq  0x180043da0, %rdx        ; InvokeHelper::_WndProc
18002bc4e:  callq *0x180195220             ; DUser.dll!AttachWndProcW ★（延迟导入）
```

**关于上面两个"辅助函数"（要精确定位）**：

| 调用点 | 目标 | 它内部真正做什么 |
|---|---|---|
| `0x2BBFF` → `0x18002C0AC` | dui70 内部封装 | 内部调 `RegisterClassExW`（IAT `0x119470` 在附近被用） |
| `0x2BC33` → `0x18002BDD8` | dui70 内部封装 | 内部在 `0x2BE7B` 处 `callq *0x180119468` = **`CreateWindowExW`**（已核对 IAT） |

⚠️ **一个我自己纠正的错误**：我最初把 `0x2BC33` 直接标成 `CreateWindowExW`。
实际上那是**跳到 dui70 自己的封装函数**，`CreateWindowExW` 在封装体内部
（`0x18002BE7B`）。结论（用 `CreateWindowExW` 建窗）不变，但**指令位置要准**。

另一个纠正：**WndProc 不是用 `SetWindowLongPtrW` 挂的**，
而是 `DUser.dll!AttachWndProcW`（延迟导入槽 `0x180195220`，已解析延迟导入表确认）。
`SetWindowLongPtrW`（IAT `0x119460`）在这一带**只被那个创建窗口的封装内部使用**
（`0x2BF95`），不是挂 WndProc 用的。

三个细节：

1. **窗口类名字符串 `0x18011FD68` 已直接读二进制确认为
   `UIAInvokeHelperWndClass`（UTF-16）**。
2. **父窗口是 `HWND_MESSAGE`（= -3）**：反汇编里 `movq $-0x3, 0x40(%rsp)`
   就是把 -3 放进 `CreateWindowExW` 的 `hWndParent` 参数槽，
   即**消息专用窗口**。这类窗口**不可见、不进 Z 序、不被 `EnumWindows` 枚举**。
3. HWND 存在 `InvokeHelper+0x18`。

> **探测陷阱（我踩过）**：因为它是消息专用窗口，
> `EnumWindows` / `Get-Process | Where MainWindowTitle` 这类的**都找不到它**。
> 必须用 `FindWindowExW(HWND_MESSAGE, 0, 'UIAInvokeHelperWndClass', $null)`
> 直接按类名找——`HWND_MESSAGE` 作为父参数是关键。
> 这是 §5 脚本能观测到它的原因。

---

## 4. 每线程一个 helper，惰性创建【实锤】

### 4.1 `GetInvokeHelper` 的线程匹配

`InvokeManager::GetInvokeHelper`（RVA `0x3A780`）：

```asm
18003a792:  leaq  g_cs@InvokeManager, %rcx        ; 临界区 0x180183188
18003a799:  callq EnterCriticalSection
18003a7a5:  callq GetCurrentThreadId              ; ← 当前线程 id
18003a7ac:  movl  %eax, %ebx
18003a7c8:  movq  g_pArrayInvokeHelper, %rdx      ; UiaArray<InvokeHelper*> 0x1831B0
...
18003a7f1:  movq  (%rdx,%rcx,8), %rdx             ; 取第 i 个 helper
18003a7f5:  cmpl  %ebx, 0x10(%rdx)                ; helper->+0x10 == 当前线程 id ?
18003a7f8:  jne   <下一个>
18003a7fa:  movq  %rdx, %rsi                      ; 命中 → 返回
```

要点：
- 用 `InvokeManager::g_cs`（`RTL_CRITICAL_SECTION`）保护共享数组。
- 遍历 `g_pArrayInvokeHelper`，比较 **`helper + 0x10` 与当前线程 id**。
- 没命中就 new 一个 **0x20 字节**的 `InvokeHelper`（`movl $0x20, %ecx; callq <operator new>`）。

### 4.2 惰性：只有一个调用点

全二进制搜索 `InvokeHelper::Init`（RVA `0x2BBA0`）的调用点，
**只有 1 处**：`GetInvokeHelper` 内部 `0x3A89C`。

**推论**：
- **进程启动时不建隐藏窗口**。第一次有 UIA 访问（走 `UiaOnGetObject`）
  才建。
- 之后**每个访问过 UIA 的线程各有一个** helper 和隐藏窗口。

> 注意 `UiaArray<InvokeHelper*>` 这个类型名：`UiaArray` 是
> **UIA 专用数组**（`+0` 是带标志位的长度：反汇编里
> `andl $0xfffffff, %r9d` 取低 28 位为 count，`btl $0x1c, %r10d`
> 测 bit 28 —— 那是一个"增长中/内联"标志）。
> 说明这套设施完全服务于 UIA 场景。

---

## 5. 运行时验证【实锤·亲测】

反汇编给出了三条**可证伪的预测**。我用脚本逐条实测，并加了**负向对照**。

### 5.1 三条预测

| # | 预测 | 依据 |
|---|---|---|
| ① | UIA 客户端访问**前**，`UIAInvokeHelperWndClass` 窗口**不存在** | `Init` 只在 `GetInvokeHelper` 里被调用，而它由 `UiaOnGetObject` 触发（惰性） |
| ② | **裸发** `WM_GETOBJECT(0x3D, lParam=-25)` **不能**让窗口出现 | 反汇编里 `SendMessageW` 是**出站**方向（用于 invoke），不负责 provider 创建；创建需完整 UIA 路径 |
| ③ | 真实 UIA 客户端访问**后**，窗口**出现**且属于本进程 | `UiaOnGetObject` → `GetInvokeHelper` → `InvokeHelper::Init` |

### 5.2 脚本

**完整脚本已随本文交付**：`docs/duixml-tutorials/probe-uia-invokehelper.ps1`

```powershell
pwsh -File docs/duixml-tutorials/probe-uia-invokehelper.ps1
```

脚本做四件事：
1. 启动 `UITest.exe`（用真实系统 `dui70.dll` + 生成的 import lib 建窗）。
2. 用 `FindWindowExW(HWND_MESSAGE, 0, 'UIAInvokeHelperWndClass', $null)` 查窗口。
3. **负向对照**：`SendMessageTimeoutW(hwnd, 0x3D, 0, -25, ...)` 裸发 WM_GETOBJECT。
4. 用**真实 UIA 客户端**（`System.Windows.Automation`，与 Inspect.exe 同源 API）
   `FromHandle` + `FindAll(Descendants)`，再查一次；并 dump 窗口身份与 UIA 树。

关键几行：

```powershell
$HWND_MESSAGE = [IntPtr](-3)
function Find-Helper {
    [W.U]::FindWindowExW($HWND_MESSAGE, [IntPtr]::Zero, 'UIAInvokeHelperWndClass', $null)
}
# 负向对照：0x3D = WM_GETOBJECT, lParam = -25 = UiaRootObjectId
$null = [W.S]::SendMessageTimeoutW($hwndHost, 0x3D, [IntPtr]::Zero, [IntPtr](-25), 2, 3000, [ref]$res)
# 真实路径
$root = [System.Windows.Automation.AutomationElement]::FromHandle($hwndHost)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                     [System.Windows.Automation.Condition]::TrueCondition)
```

### 5.3 实测输出（原文照录）

```
宿主: UITest.exe(本地构建,见 tools/dui-pipeline/)
主窗口 HWND = 0x8C0B08  pid = 44176

[0] RegisterWindowMessageW('DUI_UIA_InvokeHelperMsg') = 0xC075

[1] UIA 访问前 : 0
    => 不存在? True

[2] 裸发 WM_GETOBJECT(0x3D, -25) 后 : 0   (ret=0x0)
    => 仍不存在? True   （说明只有真实 UIA 客户端路径会创建）

[3] 真实 UIA 客户端访问后 : 14943880
    => 出现了? True

--- UIA 树观测 ---
  root Name='Microsoft DirectUI Test'  ControlType=ControlType.Window
  root ClassName='NativeHWNDHost'  FrameworkId='Win32'
  descendants = 12
    Button         2
    CheckBox       1
    Edit           1
    Hyperlink      2
    Pane           3
    ProgressBar    1
    Text           2

--- 隐藏窗口身份 ---
  hwnd       = 14943880
  class      = 'UIAInvokeHelperWndClass'
  text       = ''
  owner pid  = 44176   (UITest pid = 44176)
  same proc  = True
  parent     = 0   (-3/HWND_MESSAGE => 消息专用窗口)
  visible    = False

===== 判定 =====
  ① 访问前不存在        : True
  ② 裸消息不创建(负向对照): True
  ③ UIA 访问后出现       : True
  => 三条全部符合反汇编预测 PASS
```

### 5.4 这些观测证明了什么

| 观测 | 证明 |
|---|---|
| `[1] = 0`、`[3] = 14943880` | **惰性创建**：窗口确实由 UIA 访问触发（对应 §4.2 的单一调用点） |
| `[2] = 0`（负向对照） | 创建**不是**由 `WM_GETOBJECT` 消息本身引起的；必须走完整 UIA provider 路径（`UiaOnGetObject` → `GetInvokeHelper` → `Init`） |
| `class = 'UIAInvokeHelperWndClass'` | §3 里从二进制读出的类名字符串**在运行时确实被用** |
| `same proc = True` | 隐藏窗口是**宿主进程自己**建的（不是系统代建） |
| `parent = 0`、`visible = False` | **消息专用窗口**：`HWND_MESSAGE` 子窗口 `GetParent` 返回 0，且不可见 |
| `RegisterWindowMessage = 0xC075` | §2 的动态注册真的执行了；`0xC075` 落在系统动态消息区间 |
| UIA 树 12 个后代 / 7 种 ControlType | `04-uia-accessible-bridge.md`/`05-uia-pattern-providers.md` 的 provider + pattern 链路整体跑通 |

> **关于 `[2]` 的诚实说明**：裸发 `WM_GETOBJECT` 返回 `ret=0x0`，
> 说明**这个窗口过程没有处理该消息**（没有 provider 被创建）。
> 这与"`UiaOnGetObject` 不是 WndProc、而是给宿主调用的工具函数"
> （`04-uia-accessible-bridge.md` §2.1）完全自洽——**消息本身不等于 UIA 路径**。
> 我没有进一步用调试器确认 `UITest.exe` 的宿主 WndProc 是否转发了 `-25`；
> 见未知问题 3。

---

## 6. 发起方：`DoInvoke` 怎么打包【实锤】

`InvokeHelper::DoInvoke`（RVA `0x646F0`）反汇编 —— 这是**跨线程调用的发起侧**：

```asm
180064715:  movl  $0x80040201, %ebx        ; 默认返回 E_FAIL 类错误
18006471f:  movq  (%r8), %rax              ; r8 = ? 取 vptr
180064729:  callq <虚调用>                  ; 校验/取 provider
180064733:  movq  0x18(%rsi), %rcx         ; rsi = this(InvokeHelper) → +0x18 = HWND ★
180064737:  testq %rcx, %rcx
18006473a:  je    <失败>                    ; HWND 为空则失败
18006473c:  movq  0x70(%rsp), %rdx
180064741:  leaq  0x20(%rsp), %r9           ; 栈上 InvokeArgs 结构
180064746:  movq  %rdx, 0x38(%rsp)
18006474b:  xorl  %r8d, %r8d                ; wParam = 0
18006474e:  movl  s_uInvokeHelperMsg, %edx ; ← 消息 id 0x18018353C
180064754:  movl  %r14d, 0x20(%rsp)         ; args.methodId
180064759:  movl  $0x80004005, 0x24(%rsp)   ; args.hr = E_FAIL（先置失败）
180064761:  movq  %rbp, 0x28(%rsp)          ; args.?
180064766:  movq  %rdi, 0x30(%rsp)          ; args.?
18006476b:  callq *0x180119490              ; SendMessageW  ★★
180064777:  cmpq  $0x315, %rax              ; 返回 0x315 ?
18006477d:  cmovel 0x24(%rsp), %ebx         ; 取 args.hr 作为最终结果
```

**关键点**：

1. **`callq *0x180119490`** —— 我解析了 IAT，这是
   **`USER32.dll!SendMessageW`**（hint 819）。**实锤**：跨线程转发用的是
   **同步 `SendMessageW`**，不是 `PostMessageW`。
   - 同步 = **调用方阻塞等待结果**。这正是 UIA 需要的语义
     （`IRawElementProviderSimple::GetPropertyValue` 必须立刻返回属性值）。
2. **参数打包在栈上**（`0x20(%rsp)` 起的 `InvokeArgs`），传的是**指针**
   （`SendMessageW` 的 lParam 在另一线程被解引用）。因为 `SendMessageW`
   是同步的，**栈帧在对方处理完之前一直有效**——这是安全的。
   （若是 `PostMessageW` 就会悬垂。）
3. **`wParam = 0`**，消息 id 放在 `edx`（即 `Msg` 参数），lParam = 栈上结构指针。
4. **返回 `0x315`** 这个魔数：如果 `SendMessageW` 返回 `0x315`,
   取 `args.hr` 作为真实 HRESULT。（`0x315` 也是 `_WndProc` 里
   写入 `*(rsp+0x58) = 0x315` 的值——**两侧对上了**，见 §7。）

`DoInvoke` 的**签名**（修饰名）也印证了这套设计：

```
?DoInvoke@InvokeHelper@DirectUI@@QEAAJ
    H                        int (methodId)
    PEAVElementProvider@2@   ElementProvider*
    P6APEAVProviderProxy@2@PEAVElement@2@@Z   ProviderProxy* (*)(Element*)  ← proxy 工厂
    PEAD                     char* (args)
```

即：`DoInvoke(methodId, provider, proxyCreator, args)`。

---

## 7. 接收方：`_WndProc` 怎么解包【实锤】

`InvokeHelper::_WndProc` 的**修饰名**是：

```
?_WndProc@InvokeHelper@DirectUI@@CAH PEAX PEAUHWND__@@ I _K _J PEA_J @Z
                                        │      │        │  │  │   └ 第6参: __int64*
                                        │      │        │  │  └ 第5参: __int64 (lParam)
                                        │      │        │  └ 第4参: WPARAM
                                        │      │        └ 第3参: UINT (msg)
                                        │      └ HWND
                                        └ 第1参: void*（DUser 传入的上下文 = this）
```

**注意**：它**不是**标准 WndProc（4 参）——而是 **6 参**的自定义签名
（多一个上下文 `this` 和一个**输出参数**）。这是 `DUser.dll!AttachWndProcW`
允许的形态（§3）。

反汇编（RVA `0x43DA0`）：

```asm
180043daf:  movq  0x50(%rsp), %rdi         ; rdi = lParam (InvokeArgs*)
180043db6:  cmpl  %r8d, s_uInvokeHelperMsg ; r8d = msg; 是本通道的消息吗?
180043dbd:  jne   <不是 → 返回 0>
180043dbf:  movq  0x10(%rdi), %rcx         ; args+0x10
180043dc3:  movq  (%rcx), %rax
180043dc6:  movq  0x10(%rax), %rax
180043dca:  callq <虚调用>                  ; 取 provider
180043dcf:  movq  %rax, %rbx
180043dd2:  testq %rax, %rax
180043dd5:  je    <hr=E_FAIL 分支>          ; 取不到 → 0x80040201
180043ddb:  movb  0x94(%rax), %al          ; 检查状态位
180043de1:  testb %al, %al
180043de3:  jns   <AdviseEvent 分支>        ; bit7 = 0 → 走事件订阅路径 ★
180043de5:  testb $0x4, %al                ; bit2
180043de7:  je    <AdviseEvent 分支>
180043de9:  movq  0x8(%rdi), %rax          ; args+0x8 = proxy 工厂
180043e0b:  movl  (%rdi), %edx             ; args+0x0 = methodId   ★
180043e07:  movq  0x18(%rdi), %r8          ; args+0x18
180043e10:  callq <虚调用>                  ; 真正执行
180043e18:  movl  %eax, 0x4(%rdi)          ; args+0x4 = 结果 HRESULT  ★
180043e1b:  callq 0x18003aebc              ; 递减引用/清理
180043e20:  movq  0x58(%rsp), %rax         ; rax = 第6参（输出指针）
180043e25:  movl  $0x1, %esi               ; 返回值 = 1
180043e2a:  movq  $0x315, (%rax)           ; *输出 = 0x315  ★
```

### 7.1 意外发现：这条通道还承载"事件订阅"

`_WndProc` 的 `jns` / `je` 分支**不是**普通的失败路径，而是
**调用 `EventManager` 的静态方法**（实测）：

```asm
180043eb2:  cmpl  $0x3, %r8d               ; methodId == 3 ?
180043eb6:  jne   <else>
180043eb8:  callq EventManager::AdviseEventAdded   (0x18004B0F0)   ★
180043ebd:  jmp   <写回 hr>
180043ecb:  callq EventManager::AdviseEventRemoved (0x180049890)   ★
180043ed0:  movl  %eax, 0x4(%rdi)          ; args.hr = 返回值
180043ed3:  jmp   <返回>
```

即：**同一个 `DUI_UIA_InvokeHelperMsg` 通道，既传"调用 pattern 方法"，
也传"订阅/退订 UIA 事件"**——靠 `args.methodId` 区分：

| `methodId` | 语义 |
|---|---|
| `3` | `AdviseEventAdded`（订阅事件，对应 `IRawElementProviderAdviseEvents::AdviseEventAdded`） |
| 其它（走 `_` 分支） | `AdviseEventRemoved`（退订，对应 `AdviseEventRemoved`） |

这解释了为什么 `ElementProvider` **同时**实现 `IRawElementProviderAdviseEvents`
（`04-uia-accessible-bridge.md` §4.1）——订阅请求也要经这条跨线程通道转回 UI 线程。

> ⚠️ **注意区分**：这里调的 `EventManager::AdviseEventAdded` 是
> **DirectUI 的 `EventManager` 静态方法**（RVA `0x4B0F0`），不是
> `ElementProvider::AdviseEventAdded`（RVA `0x4B350`，`04-uia-accessible-bridge.md` §4.2）。
> 后者是 UIA COM 接口实现，内部会 `DoInvoke`（实测 `0x4B384`
> `callq ElementProvider::DoInvoke`）——也就是**绕回同一条通道**。

### 7.2 `_WndProc` 的错误路径

```asm
180043e74:  movl  $0x80040201, 0x4(%rdi)   ; args.hr = 0x80040201
180043e7d:  movl  (%rdi), %r8d             ; methodId
180043e80:  movl  $0x80040201, 0x4(%rdi)   ; 同上（两处都置）
180043e87:  leal  -0x3(%r8), %eax          ; methodId - 3
180043e8b:  cmpl  $0x1, %eax
180043e8e:  ja    <返回>                    ; 不在 {3,4} 就直接返回
180043ebf:  movl  $0x8007000e, 0x4(%rdi)   ; args.hr = E_OUTOFMEMORY
```

- **`0x80040201`** 出现两次：`0x8004xxxx` 段的 facility 是
  **`FACILITY_ITF`**（`(0x80040201 >> 16) & 0x1FFF = 4` = 自定义接口错误）。
  dui70 用它表示"这个元素不支持该操作"。
  （对照：`E_NOINTERFACE = 0x80004002`，`05-uia-pattern-providers.md` §2.1 的失败返回值。）
- **`0x8007000E`** = `E_OUTOFMEMORY`，在 `AdviseEvent` 分支的失败路径上。
- `leal -0x3(%r8)` + `cmpl $0x1` + `ja` = **判断 `methodId` 是否在 `{3, 4}`**
  （`methodId - 3 <= 1`）。这正是 §7.1 的分派依据。

> ⚠️ **一个我自己纠正的错误**：我最初写 `_WndProc` 未命中消息时会
> "交给 `DefWindowProc`"。**这是错的**——我在整个 `0x43DA0..0x43EE0` 范围内
> 扫描，**没有任何 `callq` 指向 `DefWindowProcW`（IAT `0x180119478`）**。
> 未命中时它只是 `xorl %esi,%esi` 初始化为 0 然后返回
> （`movl %esi,%eax`），即**不处理、返回 0**。`DefWindowProcW` 在 dui70 里
> 存在，但**不在这条路径上**。

**`InvokeArgs` 结构（从两侧反汇编推出）**：

```
+0x00  int32   methodId        ← DoInvoke 写 (0x64754)；_WndProc 读 (0x43E0B)
+0x04  int32   hr              ← 初始 0x80004005(E_FAIL)，结果写回 (0x43E18)
+0x08  ptr     proxy 工厂函数   ← DoInvoke 写 (0x64766)；_WndProc 读 (0x43DE9)
+0x10  ptr     ElementProvider*← DoInvoke 写 (0x64761)；_WndProc 读 (0x43DBF)
+0x18  ptr     参数/Element     ← _WndProc 读 (0x43E07)
```

### 7.3 关于 `0x315`（诚实标注）

`0x315` 在两侧都出现：
- `_WndProc` 把它写进**第 6 个参数指向的输出槽**（`0x43E2A`）。
- `DoInvoke` 在 `SendMessageW` 返回后拿**返回值**与它比较（`0x64777`）。

`_WndProc` 自身的返回值是 `1`（`0x43E25`），**不是** `0x315`。
所以要让 `DoInvoke` 的 `cmpq $0x315, %rax` 成立，必须有一个中间环节把
*输出槽里的 `0x315`* 变成 `SendMessageW` 的返回值。

【强推】中间环节就是 **`DUser.dll!AttachWndProcW` 注册的 trampoline**：
DUser 的消息派发器调用我们的 6 参函数，然后**返回 `*输出槽`**。
这样 `SendMessageW` 才会返回 `0x315`，`DoInvoke` 的检查才有意义。

但我**没有反汇编 DUser 的 trampoline**（它在另一个 DLL 里），
所以这一步是推断。**见未知问题 1。**

### 7.4 `OnInvoke`：存在，但全镜像零引用【实锤】

`InvokeHelper::OnInvoke`（RVA `0x43EE0`）**确实是一个真实函数**
（有 `.pdata` 展开信息，`start=0x43EE0 end=0x43FE9`，共 0x109 字节），
且它的代码形状与 `_WndProc` 高度相似（同样的
"取 `args+0x10` → 虚调用 → 检查 `0x94(%rax)` 状态位"序列）。

**但它在整个 `dui70.dll` 里没有任何引用。** 我做了三重穷尽扫描：

| 扫描方式 | 结果 |
|---|---|
| 全 `.text` 里的 `call rel32` / `jmp rel32` 指向 `0x43EE0` | **0 处** |
| 全 `.text` 里的 `lea/mov r64,[rip+disp32]` 指向 `0x43EE0`（取函数地址） | **0 处** |
| 全镜像中被**重定位**的 8 字节槽等于 `0x180043EE0`（vtable/表项） | **0 处** |
| 全 `pinned/symbols.json` 的 vftable 槽扫描（24 槽/表） | **0 处** |

**结论**：`OnInvoke` 是**编译器/链接器保留下来但未被引用的死代码**
（很可能是 `_WndProc` 重构后遗留的旧实现，或某个被 `#if` 掉/内联掉的路径 ——
因为 PDB 符号存在，说明它被真实编译过）。

**这纠正了我之前的假设**：
- ❌ 我曾在流水线图上画 `_WndProc → OnInvoke(args)` —— **这是错的**。
- ✅ 实际是 `_WndProc` **自己**完成解包和执行（§7 的反汇编就是它的全部内容，
  函数体 `0x43DA0..0x43ED8`，里面没有任何对 `OnInvoke` 的调用）。
- ✅ `OnInvoke` 的真实性仅体现在：它是 `InvokeHelper` 的一个成员函数，
  签名是 `void OnInvoke(InvokeArgs*)`（修饰名
  `?OnInvoke@InvokeHelper@DirectUI@@AEAAXPEAUInvokeArgs@12@@Z`，
  `AEAA` = private 非虚）。

> 这条是**"矛盾最有价值"的实例**：符号表说有这么个方法、`_WndProc` 的代码
> 形状又高度相似，很容易顺手写成"`_WndProc` 调用 `OnInvoke`"。
> 只有做**引用计数扫描**才能发现它根本没被链接进任何路径。

---

## 8. 为什么用"隐藏窗口 + SendMessage"，而不是别的方案

| 备选方案 | 为什么不用 / 为什么用这个 |
|---|---|
| 直接加锁访问 Element | `Element` 不是线程安全的；且 DUser 上下文有线程亲和性 |
| `PostMessage` + 回调 | UIA 的属性读取必须**同步返回**值，`Post` 是异步的，不行 |
| `SendMessage` 到一个**已有**的宿主窗口 | 宿主的 WndProc 是**用户代码**，dui70 不能要求它处理内部消息 |
| 自建**消息专用窗口** | ✅ 不污染宿主窗口；不参与 Z 序/绘制；**不需要宿主配合**；`SendMessage` 天然同步 |

这正是 **`HWND_MESSAGE` 的标准用途**：内部 IPC/编组点。
`DUI_UIA_InvokeHelperMsg` 用 `RegisterWindowMessageW` 注册，
保证跨模块一致（§2）。

### 8.1 与 `CSafeElementProxy` 的关系

`05-uia-pattern-providers.md` §4.1 提到 `CSafeElementProxy` 有
`Invoke` / `InvokeAsync` / `s_SyncCallback` / `_InitDUserContext`。
**它们是同一套机制的两侧**：

```
CSafeElementProxy::Invoke(...)          ← 调用方（可能在别的线程）
        │
        ▼
InvokeHelper::DoInvoke(...)             ← SendMessageW 编组
        │
        ▼
InvokeHelper::_WndProc(...)             ← UI 线程执行（解包 + 派发）
        │
        ▼
CSafeElementProxy::s_SyncCallback       ← 回到"安全代理"语义
```

`_InitDUserContext` 表明代理需要**每线程的 DUser 上下文**
（DirectUI 的绘制/资源上下文），这进一步解释了为什么不能随便跨线程碰 Element。

---

## 9. 作为应用开发者，你该怎么做

1. **你不需要做任何事**。这套通道是 dui70 内部自动建立的；
   你写 `accessible="true"` 就会有。
2. **不要在 UIA 事件回调里做重活**。`DoInvoke` 是**同步 `SendMessageW`**：
   UIA 线程会**阻塞**等你的 UI 线程处理完。若你的 UI 线程卡住，
   Narrator 也会卡住（表现为"朗读无响应"）。
3. **别在自己的 WndProc 里吞掉动态注册消息**。虽然它发往 dui70 自己的
   隐藏窗口（不会到你手上），但**不要**用 `RegisterWindowMessageW` 注册同名
   字符串后再期望拦截——那会拿到同一个 id。
4. **调试多条线程时的现象**：若你的进程有多个线程都访问过 UIA，
   会有**多个** `UIAInvokeHelperWndClass` 窗口（每线程一个，§4.1）。
   用 §5 的 `FindWindowExW` 只能拿到**第一个**；要枚举全部需要遍历。

---

## 未知问题清单（诚实边界）

1. **`0x315` 这个协议常量的确切含义**：本文确认它在 `DoInvoke`/`_WndProc`
   两侧成对出现（实锤），但**没有**找到它的符号名或定义处。
   【猜想】是一个哨兵返回值（避免与真实 `HRESULT`/窗口过程返回值混淆）。
2. **`InvokeArgs` 结构的精确字段语义**：`+0x08`/`+0x10`/`+0x18` 三个指针
   我按读写位置推断为 proxy 工厂 / ElementProvider / 参数，但**没有**
   完整恢复结构定义（例如是否还有 `+0x20` 之后的部分）。
3. **裸发 `WM_GETOBJECT` 为何无效**：§5.4 已诚实说明——`SendMessageTimeoutW`
   发到 `MainWindowHandle` 时返回 `ret=0`，未创建 provider。
   我**没有**用调试器确认 `UITest.exe` 的 `NativeHWNDHost` WndProc
   是否把 `-25` 转给了 `UiaOnGetObject`。可能是转发了但走了不同分支，
   也可能是根本没转发。**这是本文最大的未闭合点。**
4. **`OnInvoke`（`0x43EE0`）为何是死代码**：本文**已实锤**它全镜像零引用
   （§7.4：三重扫描 + vftable 扫描 = 0；`.pdata` 证明 `0x43EE0..0x43FE9`
   是真函数）。但**为什么**它存在——是重构遗留？还是某个未启用的
   代码路径（`#if` 分支 / 被内联）？**未解**。
5. **`InvokeHelper<lambda...>` 三个模板实例的用途**：符号表里有
   `<lambda_292352157681e3a79870c349076e3c4a>` 等三个，且与
   `CSafeElementProxy::Invoke`/`InvokeAsync` 的模板参数相同。
   与本文通道的确切关系未解。
6. **`ISafeElementProxyInvokeHelper`**：一个带 `InvokeHelper` 名字的独立类，
   与 `InvokeHelper` 的关系（基类？委托？）未定。
7. **多线程访问的行为**：本文只观测了单线程场景。
   "每线程一个 helper + 每线程一个隐藏窗口"是【实锤】（`GetInvokeHelper`
   的线程比较 + `Init` 的单一调用点），但**多线程下的实测未做**。
8. **`UiaArray` 的位 28 标志**：反汇编显示 `btl $0x1c` 测试一位，
   本文按"增长中/内联"理解，未确证。
9. **`DUser.dll!AttachWndProcW` 的 trampoline 语义**（§7.3）：
   我推断它把 6 参函数的"输出槽"值变成窗口消息返回值，但**未反汇编
   DUser 验证**。这直接影响 `0x315` 协议成立的解释。
   **这是本文第二大未闭合点。**
10. **`methodId == 4` 的确切语义**：§7.1 证明 `{3,4}` 走
    `AdviseEventAdded`/`AdviseEventRemoved` 分支，但哪个是哪个
    （`cmpl $0x3` + `jne` 表明 3 = Added、其余 = Removed）只是**强推**。

## 证据索引

| 结论 | 证据 |
|---|---|
| `UiaOnGetObject` 调 `GetInvokeHelper` | RVA `0x4B2BB`（`04-uia-accessible-bridge.md` §2.2） |
| 消息动态注册 + 4 个消息名 | 反汇编 RVA `0x1B14`/`0x1B1B`/`0x1B27`；字符串 `0x180123868` |
| 窗口类名 `UIAInvokeHelperWndClass` | 字符串 RVA `0x18011FD68`（UTF-16，直读二进制） |
| `GetModuleHandleW` + 父窗口 `-3` | IAT `0x1196C0`；`movq $-0x3, 0x40(%rsp)` @ `0x2BC12` |
| `CreateWindowExW`（在 dui70 封装 `0x2BDD8` 内部） | `callq *0x180119468` @ `0x2BE7B` |
| WndProc 用 **`DUser!AttachWndProcW`** 挂（非 `SetWindowLongPtrW`） | `callq *0x180195220` @ `0x2BC4E`（延迟导入表解析） |
| `_WndProc` = RVA `0x43DA0`，**6 参**自定义签名 | 修饰名 `?_WndProc@InvokeHelper@DirectUI@@CAHPEAXPEAUHWND__@@I_K_JPEA_J@Z` |
| `_WndProc` 比消息 id、回填 `0x315`、返回 1 | RVA `0x43DB6` / `0x43E2A` / `0x43E25` |
| `_WndProc` **不调** `DefWindowProcW` | 全范围 `0x43DA0..0x43ED8` 无 `callq` 指向 IAT `0x180119478` |
| `_WndProc` 走 `EventManager::AdviseEventAdded/Removed` | `callq 0x4B0F0`/`0x49890` @ `0x43EB8`/`0x43ECB` |
| **`OnInvoke` 全镜像零引用** | 三重扫描（call/jmp rel32、rip-relative lea/mov、重定位槽）+ vftable 扫描 = 0；`.pdata` 证明 `0x43EE0..0x43FE9` 是真函数 |
| `DoInvoke` 用 **`SendMessageW`** | RVA `0x6476B`，IAT `0x180119490` = `USER32!SendMessageW`（hint 819，PE 导入表解析） |
| `DoInvoke` 检查 `rax==0x315` | RVA `0x64777` |
| `GetInvokeHelper` 线程匹配 `+0x10` | RVA `0x3A7F5`（`cmpl %ebx, 0x10(%rdx)`） |
| `g_cs` / `g_pArrayInvokeHelper` | RVA `0x183188`（`RTL_CRITICAL_SECTION`）/ `0x1831B0` |
| 新对象 **0x20 字节** | RVA `0x3A849`（`movl $0x20, %ecx`） |
| `Init` 只有 1 个调用点 | 全符号表：`InvokeHelper::Init`（`0x2BBA0`）唯一调用者 `GetInvokeHelper` @ `0x3A89C` |
| `ElementProvider::AdviseEventAdded` 会 `DoInvoke` | `callq 0x4B7B0` @ `0x4B384` |
| `0x80040201` = FACILITY_ITF；`0x8007000E` = E_OUTOFMEMORY | RVA `0x43E74`/`0x43E80`；`0x43EBF` |
| **运行时三条预测全 PASS** | `docs/duixml-tutorials/probe-uia-invokehelper.ps1` 实测输出（§5.3） |
| `RegisterWindowMessageW = 0xC075` | §5.3 观测 `[0]` |
| UIA 树 12 后代 / 7 ControlType | §5.3 观测（与`04-uia-accessible-bridge.md` §5 一致） |
