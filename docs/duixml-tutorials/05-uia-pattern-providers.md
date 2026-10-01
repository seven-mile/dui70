# 13 个 PatternProvider：dui70 内置的 UIA 生产线

> 读者设定：会用 dui70 写应用的 C++ 开发者（懂 Win32、懂 COM，但不懂 DirectUI 内部）。
> `04-uia-accessible-bridge.md` 讲了"`accessible="true"` 之后 provider 怎么诞生"。本文接着讲**下半段**：
> UIA 客户端问"你支持什么模式（pattern）"时，dui70 拿什么回答。
>
> 证据分级同`04-uia-accessible-bridge.md`。【实锤】= 反汇编 RVA / 符号表修饰名 / 可运行观测。

---

## 0. 一句话结论

dui70 里有 **13 条 UIA pattern 生产线**，每条是一个
`PatternProvider<TProvider, IUiaPattern, N>` 模板实例：

```
PatternProvider<ValueProvider,  IValueProvider,  12>
PatternProvider<InvokeProvider, IInvokeProvider,  0>
... 共 13 条 ...
```

每条生产线由**两个类**组成：

| 角色 | 类 | 职责 |
|---|---|---|
| **业务端**（dui 侧） | `ValueProvider` | 实现 UIA 的 `IValueProvider`；方法体做真正的事（读写元素属性） |
| **包装端**（模板） | `PatternProvider<ValueProvider, IValueProvider, 12>` | 持有业务端、把 vtable 调用转发下去、管理生命周期 |

**这里有一个常见误解要先纠正**（见 §2）：dui 侧的 `ValueProvider`
**不是**"内部协议"再桥接——它**本身就是** UIA 的 `IValueProvider` 实现。
`QueryInterface(IID_IValueProvider)` 直接返回自己。

---

## 1. 13 条生产线清单（实测）

从 `pinned/symbols.json` 的**修饰名**里提取模板参数，得到完整清单：

| N | dui 侧实现 | UIA 接口 | 备注 |
|---|---|---|---|
| 0 | `InvokeProvider` | `IInvokeProvider` | 按钮"点击" |
| 1 | `ExpandCollapseProvider` | `IExpandCollapseProvider` | 树节点展开/折叠 |
| 2 | `GridItemProvider` | `IGridItemProvider` | 网格项 |
| 3 | `GridProvider` | `IGridProvider` | 网格 |
| 4 | `RangeValueProvider` | `IRangeValueProvider` | 滑块/进度 |
| 5 | `ScrollProvider` | `IScrollProvider` | 滚动容器 |
| 6 | `ScrollItemProvider` | `IScrollItemProvider` | 滚动到可见 |
| 7 | `SelectionItemProvider` | `ISelectionItemProvider` | 选中项 |
| 8 | `SelectionProvider` | `ISelectionProvider` | 选择容器 |
| 9 | `TableProvider` | `ITableProvider` | 表格 |
| 10 | `TableItemProvider` | `ITableItemProvider` | 表格项 |
| 11 | `ToggleProvider` | `IToggleProvider` | 开关/复选框 |
| 12 | `ValueProvider` | `IValueProvider` | 文本/数值 |

**每个实例恰好 9 个符号**（实测）：1 `ctor` + 2 `dtor`（+vector deleting）
+ 2 `vftable`（primary + IProvider 子对象）+ 4 个 `template` 成员：

```
Create(ElementProvider*, IUnknown**)     ← 静态工厂
Init(ElementProvider*)                   ← 绑定
GetProxyCreator()                        ← 拿 Proxy 工厂
DoInvoke(int, ...)                       ← 统一的调用入口（变参，见 §1.1）
```

### 1.1 上表的 N 是怎么读出来的（重要，别读错）

MSVC 对**非类型模板参数** `int N` 的修饰名**不是直觉的十六进制**：

| 模板实参 | 修饰名后缀 |
|---|---|
| `TP<0>` | `$0A` ← 注意！0 是 `$0A`，不是 `$00` |
| `TP<1>` … `TP<10>` | `$00` … `$09` |
| `TP<11>` / `TP<12>` | `$0L` / `$0M`（`A`=0, `B`=1, …, `L`=11, `M`=12） |

规则是：**`A`..`P` 表示 0..15**（`$0X`，X 是 `A`+值）；
**1..10 另用 `$00`..`$09` 表示**（`$0` 前缀 + 十进制数字）。
所以 `$0A` 与 `$00` 的语义正好"错开一位"。

**这是实测校准的**，不是查文档 —— 我用本机 MSVC 14.44 编译了一个
`template <int N> struct TP` 探针（`.local/build/p6-uia/mangle-probe.cpp`），
`dumpbin /SYMBOLS` 读出的对应关系如上表。

> 如果按直觉把 `$0A` 读成 10、`$00` 读成 0，**整张表会错位**。
> 我用校准后的映射回代 dui70 的 13 个后缀，**13/13 全部吻合，0 处冲突**
> （脚本 `.local/build/p6-uia/crosscheck-n.py`）。
> 这正是本文表格里 N 值的依据。

**`DoInvoke` 的真实签名**（从修饰名读）：

```
?DoInvoke@?$PatternProvider@...@@IEAAJHZZ
  IEAA = protected 非虚（__cdecl）
  J    = 返回 int
  HZZ  = (int, ...)   ← 变参！
```

即 `protected int DoInvoke(int, ...)` —— **可变参数**的统一入口，
而非我最初以为的 `DoInvoke(int, char*)`。

> **两个模板参数的作用**：`TProvider` 是**具体的业务实现**（编译期多态用），
> `IUiaPattern` 只是**类型标签**（用于区分 13 个特化、并让人读懂对应哪种 UIA 模式）。
> `N` 是 pattern 的序号（0..12），与`04-uia-accessible-bridge.md` 里 `g_patternInfoTable` 的索引同源。

### 1.2 与 `accrole` 的对应关系

`04-uia-accessible-bridge.md` §3.2 的表里有一列"**有 pattern?**"。现在可以把它讲通了：
那一列标记为"是"的 role，就是会挂上这 13 条生产线的 role。例如：

| accrole | → ControlType | 挂哪条生产线 |
|---|---|---|
| `pushbutton`(43) | Button | `InvokeProvider`（N=0） |
| `checkbutton`(44) | CheckBox | `ToggleProvider`（N=11） |
| `text`(42) | Edit | `ValueProvider`（N=12） |
| `scrollbar`(3) | ScrollBar | `RangeValueProvider`（N=4） |
| `slider`(51) | Slider | `RangeValueProvider`（N=4） |
| `combobox`(46) | ComboBox | `ExpandCollapseProvider`（N=1） |
| `outlineitem`(36) | TreeItem | `ExpandCollapseProvider` + `SelectionItemProvider` |
| `listitem`(34) | ListItem | `SelectionItemProvider`（N=7） |
| `progressbar`(48) | ProgressBar | `RangeValueProvider`（N=4） |

> 注意同一个 ControlType / role 可以挂**多条**生产线（`outlineitem` 就挂两条）。
> **一条生产线 ≠ 一个控件**；它是"一种能力"。

---

## 2. 关键更正：UIA 接口就在 dui 侧 `*Provider` 类上【实锤】

`ui-mental-model-outline.md` §G1 的表述是：

> "dui70 的 ValueProvider 实现 dui 内部 IProvider 协议，
> PatternProvider<ValueProvider, IValueProvider, 12> 模板再桥到 COM"

**这个方向对，但"UIA 接口在 PatternProvider 上"的理解不准确。** 实测证据：

### 2.1 `QueryInterface` 只认自己的 UIA IID

对 `ValueProvider::QueryInterface`（RVA `0x82890`）反汇编，它比较**两个 IID**：

```asm
1800828ae:  movq  0x1801221f0, %rax       ; GUID#1
1800828b5:  subq  (%rdx), %rax            ; 与请求的 riid 比较
...
1800828ca:  movq  0x180123348, %rax       ; GUID#2
1800828d1:  subq  (%rdx), %rax            ; 再比一次
```

读出这两个 GUID：

| 地址 | IID | 身份 |
|---|---|---|
| `0x1801221F0` | `00000000-0000-0000-C000-000000000046` | `IID_IUnknown` |
| `0x180123348` | `C7935180-6FB3-4201-B174-7DF73ADBF64A` | **`IID_IValueProvider`** |

第二个 GUID 与 Windows SDK `UIAutomationCore.h:4306` 里
`MIDL_INTERFACE("c7935180-6fb3-4201-b174-7df73adbf64a") IValueProvider` **逐字节一致**。

**所以 `ValueProvider` 就是 UIA 的 `IValueProvider`**，它只暴露 `IUnknown` 和
`IValueProvider` 两个接口——没有第三个"dui 内部协议"。

### 2.2 13 条生产线的 IID 全部对得上

对每个 `*Provider::QueryInterface` 都做同样提取，结果（**全部与 SDK 头文件核对过**）：

| 类 | QueryInterface 接受的 pattern IID | SDK `MIDL_INTERFACE` 对照 |
|---|---|---|
| `ValueProvider` | `C7935180-6FB3-4201-B174-7DF73ADBF64A` | `IValueProvider` ✅ |
| `InvokeProvider` | `54FCB24B-E18E-47A2-B4D3-ECCBE77599A2` | `IInvokeProvider` ✅ |
| `ExpandCollapseProvider` | `D847D3A5-CAB0-4A98-8C32-ECB45C59AD24` | `IExpandCollapseProvider` ✅ |
| `ToggleProvider` | `56D00BD0-C4F4-433C-A836-1A52A57E0892` | `IToggleProvider` ✅ |
| `RangeValueProvider` | `36DC7AEF-33E6-4691-AFE1-2BE7274B3D33` | `IRangeValueProvider` ✅ |
| `GridProvider` | `B17D6187-0907-464B-A168-0EF17A1572B1` | `IGridProvider` ✅ |
| `TableProvider` | `9C860395-97B3-490A-B52A-858CC22AF166` | `ITableProvider` ✅ |
| `GridItemProvider` | `D02541F1-FB81-4D64-AE32-F520F8A6DBD1` | `IGridItemProvider` |
| `ScrollProvider` | `B38B8077-1FC3-42A5-8CAE-D40C2215055A` | `IScrollProvider` |
| `ScrollItemProvider` | `2360C714-4BF1-4B26-BA65-9B21316127EB` | `IScrollItemProvider` |
| `SelectionProvider` | `FB8B03AF-3BDF-48D4-BD36-1A65793BE168` | `ISelectionProvider` |
| `SelectionItemProvider` | `2ACAD808-B2D4-452D-A407-91FF1AD167B2` | `ISelectionItemProvider` |
| `TableItemProvider` | `B9734FA6-771F-4D78-9C90-2517999349CD` | `ITableItemProvider` |

另一个佐证：这些类的方法名**与 SDK 完全同名**。`ValueProvider` 的方法：

```
SetValue          get_Value         get_IsReadOnly     ← 正是 IValueProvider 的三个方法
AddRef            Release           QueryInterface     ← IUnknown
GetProxyCreator                                      ← dui 扩展
```

`ToggleProvider` → `Toggle`；`ExpandCollapseProvider` → `Expand`/`Collapse`；
`InvokeProvider` → `Invoke`；`SelectionItemProvider` → `Select`/`AddToSelection`/
`RemoveFromSelection`。**这些全是 SDK 里对应接口的方法名。**

### 2.3 那 `PatternProvider` 到底做什么？

它是**外层包装**。看它的 primary vtable（`PatternProvider<ValueProvider, IValueProvider, 12>`
@ RVA `0x109A68`）的 slot 指向（实测）：

| slot | 指向 | 说明 |
|---|---|---|
| 0 | `PatternProvider<...>::vector deleting dtor` | 模板自己的析构 |
| 1 | `Init` | 模板自己的 Init |
| 2 | **`ValueProvider::GetProxyCreator`** | **转发到底层** |
| 3 | `ValueProvider::vector deleting dtor` | 转发 |
| 4 | `Init` | ← ICF 折叠（见 §3.2） |
| 5 | `ValueProvider::QueryInterface` | **转发** |
| 6 | `ExpandCollapseProvider::AddRef` | ← ICF 折叠 |
| 7 | `ExpandCollapseProvider::Release` | ← ICF 折叠 |

**结论**：`PatternProvider` 的 vtable 槽位直接指向底层 `TProvider` 的方法。
它是一个**薄适配层**：统一 13 种 pattern 的创建/绑定/析构流程，
把真正的 UIA 调用转发给业务实现。

> 那 `IProvider` 这个基类是什么？它是 dui **内部的抽象基类**（修饰名里是
> **`class`** —— `??0IProvider@DirectUI@@QEAA@XZ`，即 `V` 形态），
> 提供 `DoInvoke` 等统一入口。**它不是 UIA 接口**，而是模板用来做统一调度的内部基类。
> `04-uia-accessible-bridge.md` 里 `ElementProvider` 用 `TossPatternProvider` 管理这 13 条生产线的生命周期。

---

## 3. 为什么 `PatternProvider` 的 MI 布局天生适合 COM 桥接【实锤】

这一节讲**内存布局**。如果你做过 COM 或看过 vtable，
这里会发现 dui70 的选择很自然。

### 3.1 ctor 反汇编：两个 vptr

`PatternProvider<ValueProvider, IValueProvider, 12>::ctor`（RVA `0x7E260`）：

```asm
18007e266:  leaq  ??_7RefcountBase@DirectUI@@6B@, %rax
18007e26d:  movl  $0x1, 0x8(%rcx)          ; _cRef = 1
18007e274:  movq  %rax, (%rcx)             ; +0x00 ← RefcountBase vptr
18007e277:  movq  %rcx, %rbx
18007e27a:  callq RefcountBase ctor
18007e27f:  leaq  ??_7PatternProvider<...>@@6BRefcountBase@1@@, %rax
18007e286:  movq  %rax, (%rbx)             ; +0x00 ← 换成派生类 primary vptr
18007e289:  leaq  ??_7PatternProvider<...>@@6BIProvider@1@@, %rax
18007e290:  movq  %rax, 0x10(%rbx)         ; +0x10 ← IProvider 子对象 vptr  ★
18007e294:  movq  %rbx, %rax
18007e297:  andq  $0x0, 0x18(%rbx)         ; +0x18 = 0
18007e29c:  addq  $0x20, %rsp
```

推出对象布局：

```
偏移     内容
+0x00    vptr_primary   (RefcountBase 链 → PatternProvider<...>)
+0x08    _cRef          (引用计数，ctor 里初始化为 1)
+0x10    vptr_IProvider (第二个基类 IProvider 的独立 vptr)   ← MI own-vptr
+0x18    状态/TProvider* （清零）
```

**这就是多继承（MI）的 own-vptr 形态**：类继承了 `RefcountBase` 和 `IProvider`
两个**有虚函数的多态基类**，编译器为**第二个**基类生成独立 vptr，
对象里出现两个 vptr。

### 3.2 完整布局：**三个** vptr，第三个就是 UIA 接口

只看到基类 `PatternProvider` 的 ctor 会以为了只有两个 vptr。
**再看派生类 `ValueProvider` 的 ctor**（RVA `0x7E220`）就清楚了 ——
它先调基类 ctor，然后**覆盖 +0x00/+0x10 并新增 +0x20**：

```asm
18007e229:  callq PatternProvider<ValueProvider,..,12>::ctor   ; 基类先建好
18007e22e:  leaq  ??_7ValueProvider@DirectUI@@6BRefcountBase@1@@, %rax
18007e235:  movq  %rax, (%rbx)             ; +0x00 ← RefcountBase 子对象 vptr
18007e238:  leaq  ??_7ValueProvider@DirectUI@@6BIProvider@1@@, %rax
18007e23f:  movq  %rax, 0x10(%rbx)         ; +0x10 ← IProvider 子对象 vptr
18007e243:  leaq  ??_7ValueProvider@DirectUI@@6B@, %rax
18007e24a:  movq  %rax, 0x20(%rbx)         ; +0x20 ← ★ UIA COM 接口 vtable ★
```

对象真实布局（**0x28 = 40 字节**，由 `Create` 的 `leal 0x28(%rbx), %ecx`
分配大小实测）：

```
偏移     内容                                  vtable
+0x00    vptr (RefcountBase 子对象)    →  ??_7ValueProvider@@6BRefcountBase@1@@  (0x109A80)
+0x08    _cRef = 1
+0x10    vptr (IProvider 子对象)       →  ??_7ValueProvider@@6BIProvider@1@@     (0x109A78)
+0x18    状态（基类 ctor 里被清零）
+0x20    vptr (UIA COM 接口)  ★        →  ??_7ValueProvider@@6B@                 (0x109A90)
        └── 这个 vtable 有 6 槽 = IUnknown(3) + IValueProvider(3)
```

**`??_7ValueProvider@@6B@`（0x109A90）的 6 个槽**（实测，槽序与 SDK 完全一致）：

| 槽 | 函数 |
|---|---|
| 0 | `ValueProvider::QueryInterface` |
| 1 | `AddRef` |
| 2 | `Release` |
| 3 | `ValueProvider::SetValue` |
| 4 | `ValueProvider::get_Value` |
| 5 | `ValueProvider::get_IsReadOnly` |

### 3.3 `Create` 返回的是 **+0x20 那个指针**

`PatternProvider<...>::Create(ElementProvider*, IUnknown**)`（RVA `0x7E1A0`）：

```asm
18007e1bf:  leal  0x28(%rbx), %ecx         ; 分配 0x28 字节
18007e1c2:  callq <operator new>
18007e1d2:  callq ValueProvider::ctor       ; 构造
18007e1d7:  movq  (%rdi), %rax
18007e1e0:  movq  0x8(%rax), %rax
18007e1e4:  callq <虚调用>                  ; Init(provider)
18007e1e9:  leaq  0x20(%rdi), %rcx          ; ★ rcx = obj + 0x20
18007e1ed:  negq  %rdi
18007e1f0:  sbbq  %rax, %rax
18007e1f3:  andq  %rcx, %rax                ; 非空则取 obj+0x20
18007e1f6:  movq  %rax, (%rsi)              ; *ppv = obj + 0x20  ★
```

即 **`Create` 交给 UIA 的是 `obj+0x20`** —— 正是那个 UIA 接口子对象。
UIA 拿到这个指针后调 `QueryInterface`/`SetValue`，全部落在 §3.2 那张 6 槽表上。

**这完美解释了 `QueryInterface` 里的 `leaq -0x20(%rcx), %r9`**：
它收到的 `this` 是 **+0x20 的子对象指针**，减 0x20 才是**对象起点**。
MSVC 为"接口子对象在 +0x20"的类生成这种**指针回退**，是 MI/COM 的标准产物。

**所以**："`PatternProvider` 的多继承布局"不是随手选的——它是
**在 C++ 里同时暴露多个 COM 接口的标准做法**：
`+0x00` 供内部引用计数、`+0x10` 供模板统一调度、`+0x20` **就是给 UIA 的接口**。
与 `ElementProvider` 继承 `IRawElementProviderSimple2/Fragment/AdviseEvents`
三个 MIDL 接口是同一套机制（`04-uia-accessible-bridge.md` §4.1 的四个基类子对象 vftable 就是证据）。

### 3.4 ICF：13 个实例共享同一个 IProvider vtable

实测一个反直觉的现象：符号表里**全部 13 个**实例的
`??_7?$PatternProvider@...@@6BIProvider@1@@` **都指向 RVA `0x109600`**。

这不是 bug，而是**链接器 ICF（Identical COMDAT Folding，/OPT:ICF）**：
这 13 个 `IProvider` 子对象的 vtable 内容完全相同（都是转发到 `DoInvoke` 等），
被合并成一份以省空间。

**ICF 会骗人**，两个实例：

1. **`GetProxyCreator` 的 RVA 不可信**。13 个实例的
   `PatternProvider<...>::GetProxyCreator` 都是 RVA `0x64280`，
   而 `0x64280` 处机器码是 `33 C0 C3`（`xor eax,eax; ret`，**返回 0**）。
   **不能**因此说"PatternProvider 不提供 proxy"——真相是**模板自己那份被折叠成了
   trivial stub**，真正的工厂在**内层 `TProvider`** 上。
 2. RVA `0x64280` 被 **60 个不同符号**共享（`pinned/symbols.json` 实测：38 method + 13 template + 9 free_function）：`HWNDHost::CreateHWND`、
   `Element::DefaultAction`、`TaskPage::OnWizNext`、13 个
   `PatternProvider::GetProxyCreator` … 它们的机器码都是同一个平凡 stub。

**真正的 proxy 工厂**（内层 `TProvider::GetProxyCreator`，实测是
`lea rax, <Create函数>; ret`）：

| 类 | `GetProxyCreator` RVA | 返回 |
|---|---|---|
| `ValueProvider` | `0x8C3F0` | `ValueProxy::Create`（`0x899A0`） |
| `InvokeProvider` | `0xEC1D0` | `InvokeProxy::Create`（`0xEDCA0`） |
| `RangeValueProvider` | `0xEC1E0` | `RangeValueProxy::Create`（`0xEDD90`） |

**教训（也是给逆向者的提醒）**：读 MSVC 二进制时，
**符号表 RVA 相同不代表语义相同**——先看机器码，认清 ICF。

---

## 4. Proxy 层：从 pattern 到元素属性

`GetProxyCreator` 返回一个 `ProviderProxy*` 的工厂函数
（修饰名签名：`?GetProxyCreator@...UEAAP6APEAVProviderProxy@2@PEAVElement@2@@ZXZ`
= 返回"接收 `Element*`、返回 `ProviderProxy*` 的函数指针"）。

Proxy 家族实测（符号表）：

| Proxy | 对应生产线 |
|---|---|
| `ValueProxy` / `RangeValueProxy` | `ValueProvider` / `RangeValueProvider` |
| `ProgressRangeValueProxy` / `ScrollBarRangeValueProxy` / `ModernProgressBarRangeValueProxy` / `TouchSliderRangeValueProxy` | `RangeValueProvider` 的**特化** |
| `InvokeProxy` | `InvokeProvider` |
| `ExpandCollapseProxy` | `ExpandCollapseProvider` |
| `ToggleProxy` / `TouchSwitchToggleProxy` / `PasswordRevealToggleProxy` | `ToggleProvider` 特化 |
| `ScrollProxy` / `ScrollItemProxy` | `ScrollProvider` / `ScrollItemProvider` |
| `SelectionProxy` / `SelectionItemProxy` | `SelectionProvider` / `SelectionItemProvider` |
| `SelectorSelectionProxy` / `SelectorSelectionItemProxy` / `NavigatorSelectionItemProxy` | 选择特化 |
| `GridProxy` / `GridItemProxy` / `TableProxy` / `TableItemProxy` | 表格/网格 |
| `ElementProxy` / `HWNDElementProxy` / `ConcreteElementProxy` | 元素本身 |

**`RangeValueProvider` 一个生产线为什么有 4 个特化 Proxy？**
——这回答了 outline §G3 的疑问：**每个数值控件一个**。
进度条（`ProgressRangeValueProxy`）、滚动条（`ScrollBarRangeValueProxy`）、
现代进度条（`ModernProgressBarRangeValueProxy`）、触摸滑块
（`TouchSliderRangeValueProxy`）的"范围/步进/只读"语义各不相同，
所以各自特化 `DoMethod` 处理。

`ValueProxy` 的 vtable（RVA `0x1174F0`）实测 **slot[0] = `ValueProxy::DoMethod`**（槽数因 ICF 折叠不能从相邻符号机械推断，见 §3.4 的教训），
所有 pattern 调用都汇到 `DoMethod`，
由它按"方法 id + 参数"分发。这就是 `IProvider::DoInvoke` 那套统一入口的落地：

```
UIA 客户端                  dui 侧
   │                          │
   │ IValueProvider::SetValue │
   ▼                          ▼
ValueProvider::SetValue  ──► ValueProxy::DoMethod(methodId, args)
                                   │
                                   ▼
                             Element 的 Acc* 属性 / 具体控件逻辑
```

### 4.1 `CSafeElementProxy`：跨线程安全

`CSafeElementProxy`（15 个符号）的方法透露出线程模型：

```
static_method  CreateInstance
static_method  s_SyncCallback       ← 同步回调（配合06-uia-invoke-helper-cross-thread.md 的 InvokeHelper）
method         Detach
method         Initialize
method         Release
method         _InitDUserContext    ← 每线程 DUser 上下文
template       GetElement<class DirectUI::TouchHWNDElement>
template       Invoke<class <lambda_...>>
template       InvokeAsync<class <lambda_...>>
```

`Invoke` / `InvokeAsync` / `s_SyncCallback` + `_InitDUserContext`
= **代理把调用编组回 UI 线程**。这正是`06-uia-invoke-helper-cross-thread.md` 的主题。

---

## 5. 13 条生产线怎么被挂上元素

回顾`04-uia-accessible-bridge.md` §4.2 的 `ElementProvider::GetPatternProvider`（RVA `0x4AFE0`）。
它的流程（【强推】，依据是符号 + `TossPatternProvider` 的存在）：

```
UIA: "这个元素支持 IValueProvider 吗？"
  │
  ▼
ElementProvider::GetPatternProvider(patternId)
  │  ① 看 element 的 accrole → Schema::LookupAccessibleRole 的 flag（04-uia-accessible-bridge.md §3.2 那列）
  │  ② 若该 role 声明支持 → 创建/取出对应 PatternProvider 实例
  │  ③ 返回其 UIA 接口指针（QueryInterface 到具体 IID）
  ▼
（元素销毁时）ElementProvider::TossPatternProvider 回收
```

三条实测依据：
1. `_roleMapping` 每项第 +0x04 字节的 flag 与该 role 是否有 pattern 一一对应（`04-uia-accessible-bridge.md` §3.2）。
2. `ElementProvider` 有 `GetPatternProvider`（`0x4AFE0`）与 `TossPatternProvider`（`0x7D3D0`）一对。
3. 13 个实例每个都提供 `Create` 静态工厂 + `Init(ElementProvider*)` 绑定。

---

## 6. 双轨之下：为什么还留完整 MSAA

`04-uia-accessible-bridge.md` §6 已给 MSAA 轨的规模（`DuiAccessible` 实现 5 个接口 +
`HWNDElementAccessible`/`HWNDHostAccessible`/`HWNDHostClientAccessible` +
`IsMSAAEnabled` 两份实现）。这里补一个**与 pattern 层相关的观察**：

MSAA 轨**没有** PatternProvider 这套东西——`IAccessible` 是一个"大"接口
（`accDoDefaultAction`/`accHitTest`/`accNavigate`/`get_accValue`… 全在一个 vtable 里），
而 UIA 轨是**按能力拆分**的 13 个小接口。

**这解释了为什么 UIA 轨需要 PatternProvider**：COM 的"接口隔离"原则下，
一个"能滚动的列表项"要暴露 `IScrollItemProvider` + `ISelectionItemProvider`
两个接口，就必须有两个可独立 `QueryInterface` 的 vtable —— 正是 §3 讲的 MI own-vptr。

【强推】MSAA 轨保留的原因：老 AT 工具与 `oleacc` 体系（`LresultFromObject`）
仍走 `IAccessible`；dui70 要同时服务两代。

---

## 7. 作为应用开发者，你该怎么做

1. **你不需要写 provider**。写对 `accrole`，dui70 自动挂上对应的 PatternProvider。
2. **选对 accrole 就是选对 pattern**。要让 Narrator 能"点击"你的自定义按钮，
   用 `accrole="pushbutton"`（→ `InvokeProvider`）；要能被"切换"，
   用 `checkbutton`（→ `ToggleProvider`）。
3. **数值控件用 `slider`/`progressbar`/`scrollbar`**，它们都落到
   `RangeValueProvider`，但会按控件类型选不同的特化 Proxy
   （`ProgressRangeValueProxy` / `ScrollBarRangeValueProxy` / …）。
4. **自定义控件要特殊 pattern 行为时**，才需要碰 Proxy/Provider 层。
5. `PatternProvider` 的 13 条线路**每条都能被 `QueryInterface` 到标准 UIA IID**
   （§2.2 表）—— 用 Inspect.exe 看 "Patterns" 一栏，看到的就是这些。

---

## 未知问题清单（诚实边界）

1. **`IProvider` 抽象基类的完整方法表**：本文确认它存在（`class IProvider`，
   `DoInvoke` 等），但没有反汇编出它的完整 vtable 槽位含义。
2. **`PatternProvider::DoInvoke`（RVA `0x64670`）的分发逻辑**：
   签名是 `protected int DoInvoke(int, ...)`（变参，§1.1），
   未逐步反汇编 `methodId` → 具体动作的映射表。
3. **`Create` 静态工厂的选择逻辑**：UIA 请求某个 pattern 时，
   `ElementProvider` 如何决定"这个元素该创建哪些 pattern provider"——
   §5 的流程是【强推】而非【实锤】（依据是 `_roleMapping` flag + 存在
   `TossPatternProvider`，但没有逐指令跟踪 `GetPatternProvider`）。
4. **`g_patternInfoTable`（RVA `0x104670`）的 13 项元素结构**：
   本文只 dump 出指针数组，未解析每项指向的结构体字段。
5. **4 个 `RangeValueProxy` 特化的差异化行为**：本文只列出类名，
   未逐个反汇编 `DoMethod` 说明它们的范围/步进语义差异。
6. **`XProvider`（IID `1E3D87CB-...`）的定位**：它是一个
   `class`（`X` 前缀=实验/扩展？），IID 不在标准 UIA 表里。
   【猜想】是 dui70 私有扩展接口（X 前缀与 `XElement`/`XHost` 同族）。
7. **`SinkProvider` 与 `ElementProvider` 共用 IID `D6DD68D1-...`** 的含义：
   是同一个接口的两种实现，还是一个的委托？

## 证据索引

| 结论 | 证据 |
|---|---|
| 13 个实例 + 模板参数 + N 值 | `pinned/symbols.json`，`??_7?$PatternProvider@...` 修饰名 |
| 每实例 9 符号 / 4 template 成员 | 同上（脚本 `.local/build/p6-uia/analyze-patternprovider.py`） |
| `ValueProvider::QueryInterface` 只认 IUnknown + IValueProvider | RVA `0x82890` 反汇编 + IID `0x180123348` |
| 13 条生产线的 UIA IID | `.local/build/p6-uia/dump-provider-qis2.py` + SDK `UIAutomationCore.h` 逐条核对 |
| `ValueProvider::SetValue`/`get_Value`/`get_IsReadOnly` | 符号表（与 SDK 方法名一致） |
| MI 三 vptr 布局（+0x00/+0x10/+0x20） | `ValueProvider::ctor` RVA `0x7E220`（三条 `movq %rax, off(%rbx)`） |
| 对象大小 **0x28** | `PatternProvider<...>::Create` RVA `0x7E1A0`（`leal 0x28(%rbx), %ecx`） |
| `Create` 返回 **obj+0x20** | 同上 `leaq 0x20(%rdi), %rcx` @ `0x7E1E9` |
| UIA 接口 vtable 6 槽（槽序同 SDK） | `??_7ValueProvider@DirectUI@@6B@` RVA `0x109A90` |
| `QueryInterface` 的 `-0x20` 指针回退 | RVA `0x7E218`（+0x20 是 UIA 子对象偏移） |
| N 值读法（`$0A`=0 … `$0M`=12） | MSVC 探针 `.local/build/p6-uia/mangle-probe.cpp` + `crosscheck-n.py`（13/13 吻合） |
| `DoInvoke` 是变参 `(int, ...)` | 修饰名 `...IEAAJHZZ` |
| 13 实例共享 IProvider vtable（ICF） | 全部 `??_7...6BIProvider@1@@` = RVA `0x109600` |
| ICF 折叠 60 个符号 | RVA `0x64280` 符号列表；机器码 `33 C0 C3` |
| 内层 `GetProxyCreator` 真实实现 | `0x8C3F0`→`ValueProxy::Create`；`0xEC1D0`→`InvokeProxy::Create`；`0xEC1E0`→`RangeValueProxy::Create` |
| primary vtable 转发到底层 | vtable `0x109A68` slot[2]=`0x8C3F0`(ValueProvider::GetProxyCreator)、slot[5]=`0x82890`(ValueProvider::QueryInterface) |
| Proxy 家族清单 | `pinned/symbols.json`，`*Proxy` 类名 |
| `ValueProxy` vtable slot[0]=`DoMethod` | RVA `0x1174F0`（槽数不可机械推断，见 §3.4） |
| `CSafeElementProxy` 线程方法 | 符号表（`Invoke`/`InvokeAsync`/`s_SyncCallback`/`_InitDUserContext`） |
| `GetPatternProvider`/`TossPatternProvider` | RVA `0x4AFE0` / `0x7D3D0` |
| MSAA 轨规模 | `04-uia-accessible-bridge.md` §6 + `DuiAccessible` 五接口 vftable |
