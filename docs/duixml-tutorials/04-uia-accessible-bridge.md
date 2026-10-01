# accessible="true" 之后发生了什么：DirectUI 的 UIA 桥

> 读者设定：会用 dui70 写应用的 C++ 开发者（懂 Win32、懂 COM，但不懂 DirectUI 内部）。
> 本文讲清一件事：**你在 XML 里写下一个 `accessible="true"`，到 Narrator / Inspect.exe
> 能读出这个控件，中间经过了哪些代码**。
>
> 证据分级：每个结论标注【实锤】（反汇编 RVA / 语料原文 / 可运行观测）、
> 【强推】（符号结构自洽推断）、【猜想】（纯推测，写成问题）。
> 本文只对 `dui70.dll` **26100**（资源管理器所在系统）负责。

---

## 0. 先看结论：一张图

```
 你的 dui.xml
   <button accessible="true" accrole="checkbutton" accname="resstr(1613)"/>
        │
        │ ① DUIXmlParser 把 acc* 属性变成 Element 上的 Value
        ▼
   Element { accessible=true, accrole=43, accname=... }
        │
        │ ② 宿主窗口收到 WM_GETOBJECT(lParam = -25 / UiaRootObjectId)
        ▼
   UiaOnGetObject()            ← dui70 导出，宿主 WndProc 调用
        │  ├─ Schema::Init()            惰性加载 UIAutomationCore.dll
        │  ├─ InvokeManager::GetInvokeHelper()   取每线程的跨线程通道
        │  └─ 创建 ElementProvider（每元素的 UIA Provider COM 对象）
        ▼
   ElementProvider  ──implements──►  IRawElementProviderSimple2
                                     IRawElementProviderFragment
                                     IRawElementProviderAdviseEvents
        │
        │ ③ UIA 客户端问"你支持什么模式？"
        ▼
   GetPatternProvider() → PatternProvider<ValueProvider, IValueProvider, 12>
        │
        │ ④ UIA 客户端读属性 / 调方法
        ▼
   Schema::LookupAccessibleRole(accrole) → UIA ControlType
```

关键点：**`accessible="true"` 本身不创建任何 COM 对象**。它只是让元素"进入 UIA 视野"；
真正的 COM provider 是在 UIA 客户端**第一次来问**时才按需创建的。

---

## 1. 语料侧：真实系统 UI 是怎么写的

### 1.1 acc* 属性族的使用频次（实测）

对 `docs/duixml-corpus/` 全部 **149** 个 UIFILE（来自 64 个系统 DLL，即资源管理器/设置/
任务栏等真实界面）做全量统计：

| 属性 | 出现次数 | 说明 |
|---|---|---|
| `accessible` | **2463** | 主开关，`"true"`/`"false"`（含全部 `="true"`/`="false"` 形态，其中 `="true"` 大小写不敏感 2388 处 / 大小写敏感 2384 处（差额 4 来自 `fontext/UIFILE_8006.xml` 的 4 处大写 `Accessible`）/143 文件，见 §1.2） |
| `accrole` | **1822** | MSAA role 名或数字 |
| `accname` | **604** | 朗读文本（字面量或 `resstr()`） |
| `accdesc` | **181** | 补充描述 |
| `accstate` | **63** | 状态位（大小写不敏感口径；大小写敏感的 `accstate` 写法为 0，语料中存在其它大小写形态） |
| `accvalue` | 0 | — |
| `accdefaultaction` | 0 | — |
| `acckeyboardshortcut` | 0 | — |
| `accChildCount` | 0 | — |
| `accSelect` | 0 | — |
| `accessiblebutton` 标签 | **129** | 语义化按钮（大小写不敏感口径，见 §1.4） |

> **统计口径**：本表为**大小写不敏感**计数（`accessible` 要求带 `=`，即 `ci_eq` 口径）。
> 直接 `grep -c accstate` 这类大小写敏感查法会得到不同数字。
>
> 注：`duixml-tutorials-outline.md` §G1 记的是 "accessible 2456"，本次实测是 **2463**
> （统计口径/语料快照略有差异）。以后者为准。

### 1.2 `accessible` 分布：143 个文件在用

149 个文件里 **143 个**至少有一处 `accessible="true"`。用得最多的前几名：

| 文件 | `accessible="true"` 次数 |
|---|---|
| `fvewiz/UIFILE_20.xml` | 147 |
| `CertEnrollUI/UIFILE_130.xml` | 127 |
| `bootux/UIFILE_100.xml` | 78 |
| `RADCUI/UIFILE_2052.xml` | 56 |
| `fvecpl/UIFILE_110.xml` | 44 |

**这告诉你**：无障碍不是"给个别控件补丁"，而是**整个 UI 定义里普遍存在的属性**。
BitLocker 向导（fvewiz）、证书注册（CertEnrollUI）这类流程型界面用得最密。

### 1.3 `accrole` 全表：28 种取值（实测）

| accrole | 次数 | | accrole | 次数 |
|---|---|---|---|---|
| `statictext` | 668 | | `outlinebutton` | 6 |
| `link` | 360 | | `ProgressBar` | 5 |
| `pushbutton` | 207 | | **`16`** | 4 |
| `text` | 130 | | `toolbar` | 4 |
| `graphic` | 129 | | `radiobutton` | 3 |
| `pane` | 74 | | `indicator` | 2 |
| `client` | 66 | | `dialog` | 1 |
| `List` | 46 | | `separator` | 1 |
| `Grouping` | 34 | | `slider` | 1 |
| `ListItem` | 27 | | `cell` | 1 |
| `titlebar` | 17 | | `StatusBar` | 1 |
| `combobox` | 13 | | `animation` | 1 |
| `checkbutton` | 10 | | **`34`** | 1 |
| `scrollbar` | 8 | | `window` | 1 |

三个立刻值得注意的点：

1. **大小写混用**：`List` / `list`、`Grouping`/`grouping`、`ListItem`/`listitem`、
   `ProgressBar`/`progressbar`、`StatusBar` 都出现过。解析器**大小写不敏感**。
   `ui-mental-model-outline.md` §8 也记了 `DeviceElementSource/UIFILE_200.xml` 里
   "tile accrole=listitem + RichText accRole=statictext 混用大小写"。
2. **有数字形式**：`accrole="16"`（4 处，`fvecpl/UIFILE_110.xml`）和
   `accrole="34"`（1 处，`racpldlg/UIFILE_1000.xml`）。
3. 共 **28** 种（outline 记 26 种；差异来自大小写归并口径）。

数字形式的存在说明：**accrole 接受的是 MSAA `ROLE_SYSTEM_*` 的数值**，
字符串名只是它的可读别名。§3.2 会把 `16`/`34` 翻译出来。

### 1.4 两个真实用例

**用例 A：`accessiblebutton` 标签**（129 处）。`CertEnrollUI/UIFILE_130.xml:129`：

```xml
<accessiblebutton contentalign="middlecenter"
```

这个标签是 dui70 内置的语义化按钮——**你不需要写 `accrole="pushbutton"`，
标签名本身就声明了角色**。对应 `AccessibleButton` 类（见 §4.1）。

**用例 B：accname 用资源字符串**。`resstr()` 是 duixml 的表达式求值，
在运行时从当前模块（或指定 library）取字符串资源：

```xml
<CCSysLink layoutpos="none" id="atom(ChangeUser)" content="resstr(1612)"
           accessible="true" accname="resstr(1613)" accdesc="resstr(1614)"/>
```

`accname` 的取值形态实测分两类：**59 种字面量**（107 次，如 `"BitLocker Drive Encryption Hub"`；
即便把全部 `acc*` 属性的字面量合并也只有 99 种）
和**大量 `resstr(...)` 表达式**（497/604 是 resstr，含 `resstr(125, library(dui70.dll))` 这种跨模块形式）。
**给可本地化的产品写 duixml 时应该用 `resstr()`**，字面量只适合调试。

---

## 2. 触发链：WM_GETOBJECT → UiaOnGetObject

### 2.1 入口是 dui70 的导出函数

`UiaOnGetObject` 是 dui70 的**公开导出**（`pinned/exports.json`，ordinal 4317，
RVA `0x0004B240`）。它的签名从生成头 `DirectUI.h:277` 可见：

```c
void* WINAPI UiaOnGetObject(void* element, unsigned int childId, void* riid);
```

**注意它不是 WndProc**——不要以为 WM_GETOBJECT 直接被它处理。它是给宿主在自己的
窗口过程里调用的工具函数。名字里的 `OnGetObject` 指的是"处理完这次 GetObject 请求"。

### 2.2 反汇编：它做了什么【实锤】

对 `UiaOnGetObject`（RVA `0x4B240`）反汇编，关键路径如下：

```asm
18004b28a:  cmpl  $-0x19, %r15d          ; 比较 childId == -25
18004b28e:  jne   0x18004b31a
18004b294:  callq GetRoot@Element         ; 取元素树根
18004b2a5:  callq Init@Schema             ; ← 惰性加载 UIAutomationCore.dll
18004b2bb:  callq GetInvokeHelper@InvokeManager  ; ← 取跨线程通道（06-uia-invoke-helper-cross-thread.md 主角）
18004b2d9:  callq <创建 provider>
18004b2ec:  movq  UiaReturnRawElementProvider@Schema, %rax   ; 0x180183428
18004b2f9:  callq *%rax                   ; ← 把 provider 交给 UIAutomationCore
18004b301:  movb  $0x1, (%rdi)            ; 置"已处理"标志
```

三个关键事实：

1. **`-0x19`（= -25）是硬编码的判断值。** 这就是 `UiaRootObjectId`
   （见 Windows SDK `UIAutomationCore.h`）。所以只有在**请求整棵 UIA 树的根**时，
   dui70 才动手建 provider；请求别的 childId 走另一条路。
2. **`Schema::Init` 在这条路径上**——UIA 支持是**惰性初始化**的。进程启动时不加载
   `UIAutomationCore.dll`，第一次有人来问才加载。对启动性能是好事。
3. **`GetInvokeHelper` 也在这条路径上**，在返回 provider **之前**。这说明 provider
   一诞生就与"跨线程通道"绑定（`06-uia-invoke-helper-cross-thread.md` 会展开）。

> 勘误/澄清：`ui-mental-model-outline.md` §8 写"lParam==-0x19(OBJID_CLIENT)"。
> `OBJID_CLIENT` 实际是 **-4**；**-25 是 `UiaRootObjectId`**。方向（用 -25 判）是对的，
> 常量名贴错了。建议以本文为准。

### 2.3 `Schema::Init`：dui70 内置了一份 UIA 定义

`Schema` 类有 **173** 个符号（符号表实测），其中 **160 个 data 成员**。
`Schema::Init`（RVA `0x4B870`）负责加载 `UIAutomationCore.dll` 并按名字取过程地址，
`Schema::GetProcs`（RVA `0x2C490`）持有那个名字表。

分类统计这 160 个常量：

| 类别 | 数量 | 判据（成员名后缀） |
|---|---|---|
| ControlType（控件类型） | 41 | `*ControlType` |
| Pattern（模式 id） | 21 | `*Pattern` |
| Property（属性 id） | 63 | `*Property` + `FrameworkId`/`Orientation`/`IsOffscreen`/`IsPeripheral` |
| Event（事件 id） | 24 | `*Event` |
| 其他（过程指针/表/状态） | 11 | 见附录 A.5 |

**合计 41 + 21 + 63 + 24 + 11 = 160**（与脚本抽取结果逐一核对，见附录 A）。
注意 Property 是 **63** 而不是 59、其他是 **11** 而不是 15 ——
本表的数字由 `.local/build/p6-uia/dump-schema.py` 直接分类得到，**可复现**。

**这就是"dui70 内置完整 UIA schema"的实质**：它把这些 id 全部缓存在 `.data`，
避免每次询问都调用 `UiaLookupId`。完整 173 项清单见本文 **附录 A**。

---

## 3. 从 `accrole` 到 UIA ControlType

### 3.1 映射表就在二进制里【实锤】

`Schema::LookupAccessibleRole`（`?LookupAccessibleRole@Schema@DirectUI@@SAHHPEA_N@Z`，
RVA `0x6EEE0`）的签名是 `(int accrole, bool* hasPattern) -> int ControlType`。

反汇编显示它线性扫描一张 **64 项、步长 0x10** 的表 `_roleMapping`
（RVA `0x107510`，符号 `?s_pClassInfo...` 附近，实际符号名
`?_roleMapping@Schema@DirectUI@@0QBURoleMap@12@B`）。每项结构：

```
+0x00  int32   accrole          (MSAA ROLE_SYSTEM_* 数值)
+0x04  uint8   标志位            (1 = 该 role 有默认 pattern)
+0x08  ptr      指向 ControlType 缓存槽
```

```asm
18006eee0:  xorl  %eax, %eax                     ; i = 0
18006eeea:  leaq  _roleMapping, %r11
18006eef7:  movslq %r8d, %rcx                    ; 索引
18006eefa:  cmpq  $0x40, %rcx                    ; i < 64 ?
18006eefe:  jae   ...ret                         ; 超出 → 返回 0
18006ef00:  cmpl  %r10d, (%r9)                   ; role == target ?
18006ef03:  je    命中
18006ef05:  incl  %r8d ; addq $0x10, %r9 ; jmp    ; 线性前进
```

命中后返回 `*(指向的缓存槽)` ——即 UIA ControlType 的数值。

### 3.2 完整对照表【实锤】

把 64 项表逐项 dump，并把 `+0x08` 指针解析成 `Schema` 常量名，得到下表
（左列是 dui70 表里的数值，即 MSAA role）：

| accrole | ROLE_SYSTEM | 有 pattern? | → UIA ControlType |
|---|---|---|---|
| 1 | TITLEBAR | 否 | TitleBar |
| 2 | MENUBAR | 是 | MenuBar |
| 3 | SCROLLBAR | 否 | ScrollBar |
| 4–8 | GRIP/SOUND/CURSOR/CARET/ALERT | 否 | Null |
| 9 | WINDOW | 是 | Window |
| 10 | CLIENT | 是 | **Pane** |
| 11 | MENUPOPUP | 是 | Menu |
| 12 | MENUITEM | 是 | MenuItem |
| 13 | TOOLTIP | 否 | ToolTip |
| 14 | APPLICATION | 否 | Null |
| 15 | DOCUMENT | 是 | Document |
| 16 | PANE | 是 | **Pane** |
| 17–19 | CHART/DIALOG/BORDER | 否 | Null |
| 20 | GROUPING | 是 | Group |
| 21 | SEPARATOR | 否 | Separator |
| 22 | TOOLBAR | 是 | ToolBar |
| 23 | STATUSBAR | 是 | StatusBar |
| 24 | TABLE | 是 | Table |
| 25 | COLUMNHEADER | 否 | Header |
| 26 | ROWHEADER | 否 | Header |
| 27 | COLUMN | 否 | HeaderItem |
| 28 | ROW | 否 | HeaderItem |
| 29 | CELL | 是 | DataItem |
| 30 | LINK | 是 | Hyperlink |
| 31–32 | HELPBALLOON/CHARACTER | 否 | Null |
| 33 | LIST | 是 | List |
| 34 | LISTITEM | 是 | ListItem |
| 35 | OUTLINE | 是 | Tree |
| 36 | OUTLINEITEM | 是 | TreeItem |
| 37 | PAGETAB | 是 | TabItem |
| 38–39 | PROPERTYPAGE/INDICATOR | 否 | Null |
| 40 | GRAPHIC | 是 | Image |
| 41 | STATICTEXT | 是 | **Text** |
| 42 | TEXT | 是 | **Edit** |
| 43 | PUSHBUTTON | 是 | **Button** |
| 44 | CHECKBUTTON | 是 | **CheckBox** |
| 45 | RADIOBUTTON | 是 | RadioButton |
| 46 | COMBOBOX | 是 | ComboBox |
| 47 | DROPLIST | 否 | Null |
| 48 | PROGRESSBAR | 是 | ProgressBar |
| 49–50 | DIAL/HOTKEYFIELD | 否 | Null |
| 51 | SLIDER | 是 | Slider |
| 52 | SPINBUTTON | 是 | Spinner |
| 53–55 | DIAGRAM/ANIMATION/EQUATION | 否 | Null |
| 56 | BUTTONDROPDOWN | 否 | Button |
| 57–59 | BUTTONMENU/BUTTONDROPDOWNGRID/WHITESPACE | 否 | Null |
| 60 | PAGETABLIST | 是 | Tab |
| 61 | CLOCK | 否 | Null |
| 62 | SPLITBUTTON | 是 | SplitButton |
| 63 | IPADDRESS | 否 | Null |
| 64 | OUTLINEBUTTON | 否 | Null |

**这就解释了两件事**：

- 语料里的 `accrole="16"` → **Pane**，`accrole="34"` → **ListItem**。
  直接用数字和写名字等价。
- 语料里的 `accrole="checkbutton"` → **CheckBox ControlType**
  （不是 Button！这点很反直觉：`checkbutton` 是 MSAA 的"复选框"，不是"可点的按钮"）。

### 3.3 `accrole` 是唯一必须记住的词汇表

`ui-mental-model-outline.md` §8 的判断是对的：**accrole 是使用者唯一需要记的无障碍词汇表**。
上表证明了这个判断——28 个语料取值全部落在 MSAA `ROLE_SYSTEM_*` 命名空间内，
dui70 再从它映射到 UIA。**你写 duixml 时不需要知道 UIA 的 ControlType 名字**。

---

## 4. ElementProvider：每元素的 UIA COM 对象

### 4.1 它实现了哪三个 UIA 接口【实锤】

`ElementProvider` 的**基类子对象 vftable**（修饰名直接暴露继承）在符号表里是：

```
??_7ElementProvider@DirectUI@@6BIRawElementProviderAdviseEvents@@@
??_7ElementProvider@DirectUI@@6BIRawElementProviderFragment@@@
??_7ElementProvider@DirectUI@@6BIRawElementProviderSimple2@@@
??_7ElementProvider@DirectUI@@6BRefcountBase@1@@
```

即 `ElementProvider : IRawElementProviderSimple2 + IRawElementProviderFragment
+ IRawElementProviderAdviseEvents + RefcountBase`。

> 注意 `Simple2` 是 **struct**（`U`）而 `RefcountBase` 是 **class**（`V`）——
> 这符合 MIDL 生成的 UIA 接口都是 `struct`（`MIDL_INTERFACE` 展开为
> `struct __declspec(uuid()) __declspec(novtable)`）。

三个接口的分工：

| 接口 | 职责 | 代表方法 |
|---|---|---|
| `IRawElementProviderSimple2` | 元素自身的属性/模式 | `GetPropertyValue`、`GetPatternProvider` |
| `IRawElementProviderFragment` | 在元素树中定位 | `Navigate`、`get_BoundingRectangle`、`get_FragmentRoot` |
| `IRawElementProviderAdviseEvents` | 订阅事件 | `AdviseEventAdded`、`AdviseEventRemoved` |

### 4.2 方法清单（32 个符号）【实锤】

除了 COM 接口方法，还有几个透露设计的成员：

| 方法 | 含义 |
|---|---|
| `Create` | 静态工厂（`ElementProvider::Create`） |
| `GetElement` / `GetElementKey` | provider → Element 的反向映射 |
| `GetPatternProvider` | UIA 询问"支持哪个 pattern" |
| `TossElement` / `TossPatternProvider` | 释放（`Toss` 是 dui 的"丢弃"命名习惯） |
| `Init` | 绑定到 Element |
| `GetProxyCreator` | 拿"代理"工厂（见`05-uia-pattern-providers.md`） |
| `SetFocus` / `ShowContextMenu` | 直接动作 |

`GetElement`/`GetElementKey` 说明 provider 与 Element 是**双向可查**的——
这解释了为什么 UIA 线程能安全地引用 UI 线程的元素（键 + 通道）。

### 4.3 生命周期：不是每个元素都有 provider

**provider 是按需创建的**：只有被 UIA 访问到的元素才会拿到一个 `ElementProvider`。
`ElementProviderManager` 负责缓存/查找：

```
ElementProviderManager::GetProvider<IRawElementProviderSimple>     RVA 0x3AB48
ElementProviderManager::GetProvider<IRawElementProviderFragment>    RVA 0xC20C
ElementProviderManager::GetProvider<IRawElementProviderFragmentRoot> RVA 0xC0E4
```

三个特化分别对应 UIA 的三种请求粒度。**`TossElement`/`TossPatternProvider` +
manager 缓存**合起来就是一套池化——元素滚动出视野后 provider 被回收。

---

## 5. 一次真实访问的完整观测【实锤·可运行验证】

前面的机制都来自反汇编。为了不"只信静态证据"，我用**真实 UIA 客户端**
（`System.Windows.Automation`，即 Inspect.exe / Narrator 用的同一套 API）
挂上本仓库的 `UITest.exe`（用生成的 import lib + 真实系统 `dui70.dll` 建窗，
窗口标题 `Microsoft DirectUI Test`）。

**步骤**：

```powershell
# 1. 启动宿主
$p = Start-Process Z:\repos\DirectUI\.local\build\acceptance-x64\UITest.exe -PassThru
Start-Sleep 3

# 2. 用真实 UIA 客户端挂上窗口
Add-Type -AssemblyName UIAutomationClient
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)

# 3. 遍历子树（真实走 provider 的 Fragment/Property 路径）
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                      [System.Windows.Automation.Condition]::TrueCondition)
```

**观测结果**：

```
Name         = 'Microsoft DirectUI Test'
ControlType  = ControlType.Window
ClassName    = 'NativeHWNDHost'
FrameworkId  = 'Win32'
descendants  = 12
ControlType histogram:
  Pane           3
  Button         2
  Hyperlink      2
  Text           2
  CheckBox       1
  ProgressBar    1
  Edit           1
```

子树前 12 个元素（Name / ControlType）：

```
[0]  Pane         (empty)
[1]  Text         Click the buttons to get started
[2]  Text         This is subtitle, or instruction, or body text.
[3]  Hyperlink    Get support
[4]  Hyperlink    Legal information
[5]  Button       Accept
[6]  Button       Reject
[7]  CheckBox     HHHHH
[8]  Pane         Vertical
[9]  ProgressBar  繁忙指示器
[10] Pane         (empty)
[11] Edit         Fonts
Article ...
```

**这个结果验证了整条链**：

1. `ControlType` **确实存在且是正确的 UIA 类型**（Button/Hyperlink/CheckBox/ProgressBar/Edit）
   —— 说明 §3 的 roleMapping 真的在跑。
2. `Name` 来自 `accname`（`"Accept"`/`"Reject"` 对应 `UITest/dui.xml` 里的按钮文本）。
3. `[7] CheckBox HHHHH` 与 `[9] ProgressBar 繁忙指示器` 说明角色的确由 XML 声明驱动。
4. `FrameworkId = 'Win32'` 是 dui70 上报的框架标识。
5. **根节点是 `ControlType.Window` 且 `ClassName = 'NativeHWNDHost'`** ——
   印证了 §2.2 里 `-25` 那条"整棵树根"的路径。

> 复现脚本：`.local/build/p6-uia/probe-uia-client.ps1`

---

## 6. 双轨：为什么 26100 还留着完整 MSAA

`ui-mental-model-outline.md` §G2/§8 记了这个问题，这里给出**实测的规模证据**：

MSAA 轨 `DuiAccessible` 的基类子对象 vftable（符号表）：

```
??_7DuiAccessible@DirectUI@@6BIAccessible@@@          RVA 0x107D78
??_7DuiAccessible@DirectUI@@6BIAccessIdentity@@@      RVA 0x1070A0
??_7DuiAccessible@DirectUI@@6BIEnumVARIANT@@@         RVA 0x107068
??_7DuiAccessible@DirectUI@@6BIOleWindow@@@           RVA 0x107040
??_7DuiAccessible@DirectUI@@6BIServiceProvider@@@     RVA 0x1070C0
```

即 `DuiAccessible : IAccessible + IAccIdentity + IEnumVARIANT + IOleWindow + IServiceProvider`。
`accHitTest`/`accNavigate`/`accDoDefaultAction`/`get_accName`/`put_accValue` 等
标准 MSAA 方法**全部实现了**（`put_accName` 与 `ContextSensitiveHelp` 在
`DuiAccessible` 与 `HWNDHostAccessible` 上共用同一实现地址 `0x6DD20`，说明是继承来的默认行为）。

还有三个 MSAA 侧子类：

| 类 | 说明 |
|---|---|
| `DuiAccessible` | 通用 |
| `HWNDElementAccessible` | HWNDElement 专用 |
| `HWNDHostAccessible` | 宿主窗口（`Create` 收 `IAccessible*` 参数） |
| `HWNDHostClientAccessible` | 宿主客户区 |

**还有 MSAA 的开关**（这是 outline 的疑问，有确切答案）：

```
HWNDElement::IsMSAAEnabled       RVA 0x3BBE0
TouchHWNDElement::IsMSAAEnabled  RVA 0x66740
```

`IsMSAAEnabled` 是**真实存在的每类方法**（`HWNDElement` 与 `TouchHWNDElement`
各一份重写）。所以"`HWNDElement::IsMSAAEnabled` 是切换开关吗"——**是**，且 `TouchHWNDElement`
可以独立于 `HWNDElement` 决定自己的取值（【实锤】存在两个实现；**具体策略**见未知问题清单）。

**为什么双轨并存？** 【强推】MSAA 轨服务于
`CreateStdAccessibleObject`/`LresultFromObject` 这条老路径（`oleacc` 体系），
而 UIA 轨是新的。系统里仍有只实现 MSAA 的辅助工具与旧 AT，且 dui70 需要向
宿主 HWND 提供 `WM_GETOBJECT` 的 MSAA 应答（`OBJID_CLIENT = -4`，与 §2.2 的
`UiaRootObjectId = -25` 是**两条不同的请求**）。这个分工与 §2.2 反汇编里
`UiaOnGetObject` 只在 `-25` 时动手是自洽的。【猜想】是否需要 IAccessible2、
以及两轨的取舍是否有运行时开关，见未知问题。

---

## 7. 作为应用开发者，你该怎么做

1. **要 UIA 支持，就在元素上写 `accessible="true"`**，并用 `accrole` 声明语义。
   不需要写任何 COM 代码。
2. **`accname` 优先用 `resstr(...)`**（可本地化），字面量只用于调试。
3. **`accrole="checkbutton"` 是复选框**（→ CheckBox / Toggle pattern），
   不是"按钮"。要按钮用 `pushbutton`（→ Button / Invoke pattern）。
4. **`accessiblebutton` 标签**（129 处真实用例）是语义化按钮，省去手写 accrole。
5. **UIA 是惰性初始化的**：不访问就不加载 `UIAutomationCore.dll`，
   不创建 provider。所以"加了 accessible 会不会拖慢启动"——**不会**。
6. 需要自定义控件行为时才需要碰 provider（`ElementProvider::Create`/`Init`）。

---

## 未知问题清单（诚实边界）

1. **`accstate` 的 63 处取值语义**：语料里有，但本文没逐项解析它如何映射到
   UIA 的 `IsEnabled`/`IsOffscreen`/`ToggleState` 等属性。
2. **`_roleMapping` 的 `flag`（+0x04）字节的精确含义**：本文按"该 role 有默认
   pattern"理解（依据是与被标记项的组合形态），但**没有**反汇编消费它的代码路径
   来确证。列为待验证。
3. **`ElementProviderManager` 的缓存淘汰策略**：`TossElement` 何时被调用、
   provider 存活多久、滚动出视野后是否立即回收——未测。
4. **`HWNDElement::IsMSAAEnabled` / `TouchHWNDElement::IsMSAAEnabled` 的返回值
   与判定条件**：两处实现存在【实锤】，但返回 true/false 的依据（是否读某个全局/
   属性）未反汇编确证。
5. **双轨取舍**：是否存在运行时开关决定走 MSAA 还是 UIA；UIA 客户端读属性时
   是否**同时**走两轨。
6. **"UIASinkProvider"（字符串 `0x120618`）的角色**：本文字符串已确认存在，
   但它是 `SinkProvider` 的别名还是独立类，未定。
7. **`accvalue`/`accdefaultaction`/`acckeyboardshortcut` 在语料里 0 次**：
   可能是不用，可能是走别的属性名（如 `accvalue` 被 `Value` 属性取代）——
   未在语料中找到替代写法。

## 证据索引

| 结论 | 证据 |
|---|---|
| acc* 频次 / accrole 全表 / 分布 | `grep docs/duixml-corpus/`（149 XML，实测） |
| `accessiblebutton` 129 处 | `docs/duixml-corpus/CertEnrollUI/UIFILE_130.xml:129` 等 |
| 数字 accrole 16/34 | `fvecpl/UIFILE_110.xml:139,141,206,208`；`racpldlg/UIFILE_1000.xml:72` |
| `UiaOnGetObject` 签名 | `DirectUI/include/DirectUI.h:277` |
| `UiaOnGetObject` 反汇编（`-0x19`/Schema::Init/GetInvokeHelper） | RVA `0x4B240`，`UiaOnGetObject+0x4A..+0xC1` |
| `UiaReturnRawElementProvider` 指针 | RVA `0x183428`（`Schema` 静态成员） |
| `Schema` = 173 符号 / 160 data | `pinned/symbols.json`，`class == "Schema"` |
| `Schema::Init` / `GetProcs` | RVA `0x4B870` / `0x2C490` |
| `_roleMapping` 64 项 / 步长 0x10 | RVA `0x107510`，符号 `?_roleMapping@Schema@DirectUI@@0QBURoleMap@12@B` |
| `LookupAccessibleRole` 线性扫描 | RVA `0x6EEE0` 反汇编 |
| ElementProvider 三 UIA 接口 | `??_7ElementProvider@DirectUI@@6BIRawElementProvider{Simple2,Fragment,AdviseEvents}@@@` |
| ElementProvider 32 方法 | `pinned/symbols.json`，`class == "ElementProvider"` |
| ElementProviderManager 三特化 | RVA `0xB6CC`/`0xC20C`/`0xC0E4`/`0x3A5BC`/`0x3AB48` |
| DuiAccessible 五 MSAA 接口 | `??_7DuiAccessible@DirectUI@@6B{IAccessible,IAccIdentity,IEnumVARIANT,IOleWindow,IServiceProvider}@@@` |
| `IsMSAAEnabled` 两份实现 | RVA `0x3BBE0`（HWNDElement）/ `0x66740`（TouchHWNDElement） |
| **运行时 UIA 实测** | `.local/build/p6-uia/probe-uia-client.ps1`（12 后代，7 种 ControlType） |

---
## 附录 A：Schema 的 160 个 data 常量（完整清单）

> **本清单由脚本从 `pinned/symbols.json` 直接抽取**（`class == "Schema"` 且 `kind == "data"`），未手工录入，共 **160** 项。
> 这是 dui70 内置 UIA 词汇表的本体。
> 复现：`python .local/build/p6-uia/dump-schema.py`

### A.1 ControlType（41 项）

```
ButtonControlType                   CalendarControlType                 CheckBoxControlType
ComboBoxControlType                 CustomControlType                   DataGridControlType
DataItemControlType                 DocumentControlType                 EditControlType
GroupControlType                    HeaderControlType                   HeaderItemControlType
HyperlinkControlType                ImageControlType                    ListControlType
ListItemControlType                 MenuBarControlType                  MenuControlType
MenuItemControlType                 NullControlType                     PaneControlType
ProgressBarControlType              RadioButtonControlType              ScrollBarControlType
SemanticZoomControlType             SeparatorControlType                SliderControlType
SpinnerControlType                  SplitButtonControlType              StatusBarControlType
TabControlType                      TabItemControlType                  TableControlType
TextControlType                     ThumbControlType                    TitleBarControlType
ToolBarControlType                  ToolTipControlType                  TreeControlType
TreeItemControlType                 WindowControlType
```

### A.2 Pattern（21 项）

```
DockPattern                         DragPattern                         ExpandCollapsePattern
GridItemPattern                     GridPattern                         InvokePattern
ItemContainerPattern                MultipleViewPattern                 RangeValuePattern
ScrollItemPattern                   ScrollPattern                       SelectionItemPattern
SelectionPattern                    TableItemPattern                    TablePattern
TextPattern                         TogglePattern                       TransformPattern
ValuePattern                        VirtualizedItemPattern              WindowPattern
```

### A.3 Property（63 项）

```
AcceleratorKeyProperty              AccessKeyProperty                   AutomationIdProperty
BoundingRectangleProperty           ClassNameProperty                   ClickablePointProperty
ControlTypeProperty                 CultureProperty                     Drag_DropEffect_Property
Drag_DropEffects_Property           Drag_IsGrabbed_Property             ExpandCollapse_ExpandCollapseState_Property
FrameworkId                         GridItem_ColumnSpan_Property        GridItem_Column_Property
GridItem_Parent_Property            GridItem_RowSpan_Property           GridItem_Row_Property
Grid_ColumnCount_Property           Grid_RowCount_Property              HasKeyboardFocusProperty
HelpTextProperty                    IsContentElementProperty            IsControlElementProperty
IsEnabledProperty                   IsKeyboardFocusableProperty         IsOffscreen
IsPasswordProperty                  IsPeripheral                        ItemStatusProperty
ItemTypeProperty                    LabeledByProperty                   LocalizedControlTypeProperty
NameProperty                        NewNativeWindowHandleProperty       Orientation
ProcessIdProperty                   RangeValue_IsReadOnly_Property      RangeValue_LargeChange_Property
RangeValue_Maximum_Property         RangeValue_Minimum_Property         RangeValue_SmallChange_Property
RangeValue_Value_Property           RuntimeIdProperty                   Scroll_HorizontalScrollPercent_Property
Scroll_HorizontalViewSize_Property  Scroll_HorizontallyScrollable_Property  Scroll_VerticalScrollPercent_Property
Scroll_VerticalViewSize_Property    Scroll_VerticallyScrollable_Property  SelectionItem_IsSelected_Property
SelectionItem_SelectionContainer_Property  Selection_CanSelectMultiple_Property  Selection_IsSelectionRequired_Property
Selection_Selection_Property        TableItem_ColumnHeaderItems_Property  TableItem_RowHeaderItems_Property
Table_ColumnHeaders_Property        Table_RowHeaders_Property           Table_RowOrColumnMajor_Property
Toggle_ToggleState_Property         Value_IsReadOnly_Property           Value_Value_Property
```

### A.4 Event（24 项）

```
AsyncContentLoadedEvent             AutomationFocusChangedEvent         AutomationPropertyChangedEvent
DragDragCancelEvent                 DragDragCompleteEvent               DragDragStartEvent
InvokeInvokedEvent                  LayoutInvalidatedEvent              MenuClosedEvent
MenuOpenedEvent                     SelectionInvalidatedEvent           SelectionItemElementAddedToSelectionEvent
SelectionItemElementRemovedFromSelectionEvent  SelectionItemElementSelectedEvent   StructureChangedEvent
SystemAlertEvent                    TextTextSelectionChangedEvent       ToolTipClosedEvent
ToolTipOpenedEvent                  UiaRaiseAutomationEvent             UiaRaiseAutomationPropertyChangedEvent
UiaRaiseStructureChangedEvent       WindowWindowClosedEvent             WindowWindowOpenedEvent
```

### A.5 其他（过程指针/表/状态）（11 项）

```
UiaHostProviderFromHwnd             UiaLookupId                         UiaReturnRawElementProvider
_roleMapping                        g_controlInfoTable                  g_eventInfoTable
g_eventMapping                      g_fInited                           g_patternInfoTable
g_patternMapping                    g_propertyInfoTable
```

**合计**：41 + 21 + 63 + 24 + 11 = **160**。

> 另注：`Schema` 还有 **11 个 static_method**（`Init` / `GetProcs` /
> `LookupAccessibleRole` / `LookupControlInfos` / `LookupEventInfos` /
> `LookupPatternInfos` / `LookupPropertyInfos` 等）与 **2 个 operator**，
> 合计 **173** 个符号 —— 与 `pinned/symbols.json` 实测一致。
