# 宿主注册标签：duixml 的开放 schema

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者，
> 特别是**想在你自己应用里注册自定义标签**的人。
> 目标：搞清 duixml 的开放 schema 怎么工作、第三方 DLL 怎么注册自定义类、
> `attach="{Dll!Factory}"` 是什么机制、以及**哪些做法有实证、哪些是猜测**。
>
> 证据分级：【实锤】/【强推】/【猜想】，规则同`01-duixmlparser-xml-to-element-tree.md`、`02-value-type-system.md`。
> RVA 均相对各自 DLL 基址（x64 系统 DLL 通常 0x180000000）。

---

## 1. 现象：语料里 154 个标签在 dui70 里根本不存在

这是本教程的起点。我扫了 `docs/duixml-corpus/` 全部 149 个 XML，
提取所有元素标签，与 `pinned/classes.json` + `pinned/symbols.json`
的 710 个类名（**大小写不敏感**）比对
【实锤，`.local/build/p3-parser/unknown4.py`】：

| 分类 | 标签数 | 使用次数 |
|---|---|---|
| 解析器关键字（`element`/`if`/`style`/`macro`/`bind`/`stylesheets`/`unless`/`duixml`） | 16 | 11239 |
| 大小写不匹配但**类存在**（`button`→`Button` 等） | 38 | ~1000 |
| 精确匹配类名 | 49 | — |
| **完全找不到对应类** | **154** | **2109** |

**`<element>` 3946 次、`<if>` 3865 次排在前面**——它们是解析器关键字
（`element` 对应 `Element` 类但写法固定，`if` 是条件样式指令），
不属于"自定义标签"。真正的开放 schema 证据是那 **154 个标签、2109 次使用**。

### 1.1 Top 20 未注册标签（附归属模块）

| 标签 | 次数 | 模块 |
|---|---|---|
| `BUXText` | 658 | bootux |
| `BUXButton` | 201 | bootux |
| `BUXPage` | 169 | bootux |
| `BUXTitle` | 136 | bootux |
| `NavigateButton` | 113 | SpaceControl(30), fhcpl(18), DiagCpl(15), sdcpl(15), RADCUI, taskbarcpl, … |
| `BUXFormattedText` | 88 | bootux |
| `LegacyButton` | 82 | bootux |
| `CommandButton` | 63 | WebcamUi |
| `BUXStatus` | 27 | bootux |
| `FocusIndicator` | 25 | SpaceControl(15), WorkfoldersControl(6) |
| `CategoryListPaneItem` | 24 | msctfuimanager |
| `BUXButtonCollectionFlipper` | 23 | bootux |
| `BUXAnchor` | 22 | bootux |
| `VolumeHandlerSetting` | 21 | autoplay |
| `BUXButtonCollection` | 20 | bootux |
| `DESAnimatedTouchButton` | 18 | DeviceElementSource |
| `BUXLiveText` | 14 | bootux |
| `OSButtonCollection` | 13 | bootux |
| `DiagCplPage` | 13 | DiagCpl |
| `CandidateButton` | 13 | msctfuimanager |

【实锤，本次扫描】

**观察一**：`BUX*` 家族 15 个标签、**1377 次使用**，全部集中在 `bootux.dll`
（Windows 启动/恢复界面）。这是一个**完整的自研控件库**。
**观察二**：`NavigateButton` 跨 20+ 个模块出现——它是**共享控件**，
必然由某个公共 DLL 注册（见 §2）。

---

## 2. 谁能注册：`ClassInfoBase::ClassExist` 是唯一入口

### 2.1 注册原语的完整签名

`ClassExist` 是**导出**函数（`dui70.dll` ordinal 1044，RVA `0x36C10`）
【实锤，`pinned/exports.json`】：

```cpp
static bool ClassInfoBase::ClassExist(
    IClassInfo** out,                    // 出参：拿到注册好的类
    const PropertyInfo* const* props,    // 属性表
    unsigned int propCount,              // 属性个数
    IClassInfo* base,                    // ★ 基类
    HINSTANCE module,                    // ★ 本 DLL 的 HINSTANCE
    const wchar_t* name,                 // ★ 标签名（XML 里写的那个）
    bool isGlobal);                      // 是否进全局表
```

【实锤，`pinned/symbols.json` 修饰名反解】

配套还有两个：

```cpp
long ClassInfoBase::Initialize(HINSTANCE module, const wchar_t* name, bool,
                               const PropertyInfo* const*, unsigned int);  // RVA 0x37320
long ClassInfoBase::Register();                                              // RVA 0x369A0
```

**`ClassExist` 名字的误导性**：它叫 "Exist"（存在吗），但实际语义是
**"查一下，不存在就创建并注册，返回是否已存在"**——是
**get-or-create 语义**，不是纯查询。§3 的反汇编会证明这一点。

### 2.2 注册表是全局二分表

`ClassExist`（RVA `0x36C10`）内部 `callq` 到 **`CClassFactory::GetExact`**（RVA `0x36C6C`，
PDB 符号确认两者是独立函数），后者是二分查找
【实锤，disasm 0x180036c6c，详见`01-duixmlparser-xml-to-element-tree.md` §3.1】：

```asm
180036c89: movq   0x180183088(%rip), %rcx     ; ★ 全局类表
180036ca0: movq   (%rcx), %r14                ; 表头（count 在 +0）
180036ca9: movl   (%r14), %edi
180036cb4: leal   (%rdi,%rbp), %eax           ; mid = (lo+hi)/2
180036cbd: idivl  %ecx
180036cc5: shlq   $0x4, %rsi                  ; ★ mid * 16 = 16 字节一项
180036cdd: callq  *0xe2f2c(%rip)              ; = msvcrt!_wcsicmp（已解析导入表）
```

**16 字节一项**、比较用 **`_wcsicmp`**（大小写不敏感）
【实锤，PE 导入表解析：`0x119C10 -> msvcrt.dll!_wcsicmp`】。

`isGlobal` 参数控制进哪张表：
- `isGlobal = true` → 进全局表 `0x180183088`（所有 parser 可见）
- `isGlobal = false` → 进 **parser 私有扩展表**（`parser+0xb0`，
  方法在 vtable+0x18 lookup / +0x28 insert）

**两级查找**在 `_GetClassForElementByName`（RVA `0x34900`）里实现
【实锤，disasm 0x180034900，`01-duixmlparser-xml-to-element-tree.md` §3】：

```asm
180034931: movq   0xb0(%rcx), %rcx        ; parser 私有表
18003493b: movq   0x18(%rax), %rax        ; vtable+0x18 = lookup
18003493f: callq  0x1800ff010
180034944: testl  %eax, %eax
180034946: js     0x180034966             ; 失败 → 全局表
180034966: movl   $0x800403ee, %edi       ; 错误码
```

**这是第三方扩展的关键**：宿主可以给**自己的 parser 实例**
挂私有标签表，不污染全局；也可以注册到全局让所有 parser 都能用。

---

## 3. 铁证：一个真实的第三方注册序列

`DeviceElementSource.dll`（设备元素源，注册了 `DESAnimatedTouchButton` 等）
导入表里有【实锤，本教程解析其导入目录】：

```
0x01AFB0 -> DUI70.dll!ClassInfoBase::Initialize
0x01AFC8 -> DUI70.dll!ClassInfoBase::ClassExist
```

各 3 个调用点。看 `ClassExist` 的第一个调用点（RVA `0x8989`）
【实锤，disasm，完整序列见 §3.1】：

```asm
18000896b: leaq   0x18001c418(%rip), %rbx    ; ★ 类名字符串
180008972: movq   %rbx, 0x28(%rsp)           ; 栈上传参：name
180008977: movq   %rbp, 0x20(%rsp)           ; 栈上传参：module (this 的 HINSTANCE)
18000897c: movq   %rax, %r9                  ; 第 5 参 = property 表
18000897f: xorl   %r8d, %r8d                 ; 第 4 参 = base = NULL
180008982: xorl   %edx, %edx                 ; 第 3 参 = propCount = 0
180008984: leaq   0x70(%rsp), %rcx           ; 第 1 参 = &out（出参）
180008989: callq  *0x12638(%rip)             ; ★ ClassExist
180008995: testb  %al, %al
180008997: jne    0x180008a88                ; 返回 true = 已存在，跳过注册
18000899d: andq   $0x0, 0x180026958(%rip)    ; s_pClassInfo = NULL
1800089a7: callq  *0x18001b308               ; 分配器
1800089d8: callq  *0x18001af88               ; 构造 ClassInfo
1800089e4: leaq   0x18001a6c8(%rip), %rax    ; ★ vftable
1800089eb: movq   %rax, (%rsi)               ; 装 vtable
1800089f7: movb   $0x1, %r9b                 ; 第 6 参 = isGlobal = true
1800089fa: movq   %rbx, %r8                  ; 第 5 参 = name
1800089fd: movq   %rbp, %rdx                 ; 第 4 参 = module
180008a00: movq   %rsi, %rcx                 ; 第 1 参 = &this
180008a03: callq  *0x18001afb0               ; ★ ClassInfoBase::Initialize
180008a0f: testl  %eax, %eax
180008a13: js     <失败>
180008a15: movq   %rsi, %rdi                 ; 保存类对象
```

### 3.1 我验证了那个类名字符串

`leaq 0x18001c418` 指向的 RVA 里，我 dump 出的字节是
【实锤，本教程直接从 DLL 二进制读取】：

```
44004500530041006e0069006d00610074006500640054006f0075006300680042007500740074006f006e00...
```

UTF-16LE 解码 = **`DESAnimatedTouchButton`**！

而语料 `DeviceElementSource/UIFILE_200.xml` 里恰好写着
【实锤，语料原文】：

```xml
<DeviceInterfaceTile resid="DeviceInterfaceTile" sheet="DeviceInterfaceTileStyle"
                     layoutpos="none" layout="borderlayout()"
                     behaviors="PVL::ImplicitAnimation()">
  <DESAnimatedTouchButton id="atom(idMainButton)" layoutpos="top"
                          layout="borderlayout()" class="des_itfMainButton"
                          active="mouse|keyboard|pointer">
```

**闭环了**：XML 里的 `<DESAnimatedTouchButton>` → 该 DLL 用
`ClassExist(&out, props, n, NULL, hInst, L"DESAnimatedTouchButton", true)` 注册 →
解析器两级查找命中 → 实例化。**这是【实锤】级别的完整证据链**。

### 3.2 注册契约总结（给应用开发者的可操作结论）

从上面反汇编 + 签名，得出注册自定义标签的**必备步骤**
【实锤：调用序列来自 DES 的反汇编；签名来自符号表】：

```cpp
// 1) 定义属性表（NULL 结尾的 PropertyInfo* 数组）
static const PropertyInfo* const s_props[] = {
    &MyControl::ContentProp, &MyControl::EnabledProp, /* ... */ nullptr
};

// 2) 注册（get-or-create；返回 true 表示已存在，说明你该跳过创建）
IClassInfo* pci = nullptr;
if (!ClassInfoBase::ClassExist(&pci, s_props, _countof(s_props),
                               NULL,                 // base：依赖其它类时填它的 IClassInfo*
                               g_hInst,              // 你的 DLL HINSTANCE
                               L"MyControl",         // XML 里写的标签名
                               true))                // true = 注册进全局表
{
    // 3) 首次注册：造 ClassInfo，装 vtable（ClassInfo<MyControl, Element, StandardCreator<MyControl>>）
    // 4) ClassInfoBase::Initialize(hInst, L"MyControl", /*bool*/, s_props, count)
    // 5) 若基类不是 NULL，必须先确保基类已注册（§3.3）
}
```

**【强推】** 这个调用顺序是从 DES 反汇编的**参数装配顺序**反推的
（先 `ClassExist` 判存在 → 再 `new` + 装 vtable + `Initialize`），
我自己没有写过第三方 DLL 验证过。**这是本教程最大的未验证点**，
见 §8 未知问题 1。

### 3.3 级联依赖：基类必须先注册

`dui70` 自己的注册也是同一套。`ClassInfo<Button, Element, StandardCreator<Button>>::Register`
（RVA 0x5348）【实锤，disasm 0x180005348，`01-duixmlparser-xml-to-element-tree.md` §3.3】：

```asm
180005357: movq   0x180183090(%rip), %rcx    ; s_pClassInfo@Element
180005361: je     <失败>                      ; ★ 基类没注册 → 直接失败
18000536d: callq  0x1800ff010                ; 给基类 AddRef
180005379: callq  *0x180119988               ; EnterCriticalSection（已解析导入表）
18000539c: callq  0x180036c6c                ; ★ 复用 ClassExist 内部实现
1800053c1: callq  0x18007d0c0                ; new ClassInfo
1800053f5: callq  0x1800369a0                ; ClassInfoBase::Register
```

**这就是为什么 `RegisterAllControls` 的调用顺序不能乱**：

```
RegisterAllControls → Base → Standard → Extended → Macro → Browser → X → Misc → Common
```

【实锤，disasm 0x180008c60 + 符号表】这是一条**拓扑排序**：
后面每个类都依赖前面注册过的基类。你注册自定义控件时同理——
**你的基类（通常是 `Element` / `Button` / `TouchButton`）必须先注册**。

注册路径有 **`EnterCriticalSection` / `LeaveCriticalSection`**
【实锤，PE 导入表：`0x119988/0x119980`】——说明注册是**线程安全**的。

### 3.4 `isGlobal` 两种模式

| 模式 | 表 | 可见范围 | 用途 |
|---|---|---|---|
| `true` | 全局表 `0x180183088` | 所有 parser | 通用控件（DES 用这个） |
| `false` | `parser+0xb0` | 该 parser 实例 | 私有/沙箱化标签 |

【实锤，`_GetClassForElementByName` 的两级结构 + `ClassExist` 的 `isGlobal` 参数】
`parser+0xb0` 那个对象的确切类型**未知**（`01-duixmlparser-xml-to-element-tree.md` §8 问题 1 已记），
但它的 vtable+0x18/+0x28 分别是 lookup/insert【实锤】。

**实用建议**【强推】：宿主应用应优先用 `isGlobal = false`，
避免污染进程内其它 DirectUI 使用者（比如同一进程里另一个组件的 parser）。

---

## 4. `attach="{Dll!Factory}"`：宿主工厂回调

### 4.1 现象与统计

`attach=` 在语料里出现 **275 次**，但**只在一个模块**里
【实锤，`.local/build/p3-parser/attach.py`】：

```
modules using attach= (1 modules, 275 uses):
   bootux   275
```

**这是极其重要的信号**：`attach` 不是通用 duixml 语法，
而是 **bootux 专用**的宿主扩展。

### 4.2 语法

值一律是 `{模块名!导出函数名}` 形式：

```xml
<BUXPage resid="AdvancedBootOptionsPage" flags="ResetTravelog"
         attach="{BootMenuUX!CreateSelectOSPage}" class="menupage">
  <BUXTitle content="resstr(1601)" />
  <BUXButton id="atom(BareMetalRecovery)"
             attach="{BootMenuUX!CreateBareMetalRecoveryButton}">
```

共 **92 个不同的 (模块, 函数) 对**，只引用两个模块：

```
BootMenuUX   ! CreatePBRCancelButton                       x54
BootMenuUX   ! CreateCSRTFinalPage                         x25
...
FveRecoverUX ! FveCreateSkipUnlockPage                     ...
```

### 4.3 我验证了 81/81 个函数真的存在

对每个 `attach="{Dll!Func}"`，我去 `C:\Windows\System32\<Dll>.dll`
解析导出表，检查 `Func` 是否为**真实导出**
【实锤，`.local/build/p3-parser/attach_verify.py`】：

```
BootMenuUX  exports parsed: 102
verified pairs: 81   unverified: 0
```

`BootMenuUX.dll` 确实导出了 `CreateSelectOSPage`、`CreateBareMetalRecoveryButton`、
`CreateAdvancedStartupButton`……**与 XML 里写的一字不差**。

`FveRecoverUX.dll` 在这台机器的 System32 里**不存在**
（`Get-ChildItem C:\Windows\System32\FveRecoverUX*` 无结果）——
它是 WinRE 环境的 DLL。所以它的 11 对无法验证，
但**语法一致**，且 bootux 的其余部分全部验证通过。

### 4.4 机制：运行时 `LoadLibrary` + `GetProcAddress`

关键否证：**bootux 并不静态导入 BootMenuUX**
【实锤，`llvm-objdump -p bootux.dll` 的 47 个导入 DLL 里没有 BootMenuUX】。
而 `dui70.dll` 导入了【实锤，导入表】：

```
LoadLibraryW / LoadLibraryExW / GetProcAddress
```

所以流程是【强推，推断链见下】：

```
解析期：遇到 attach="{BootMenuUX!CreateSelectOSPage}"
  -> 解析出模块名 "BootMenuUX" 和函数名 "CreateSelectOSPage"
  -> LoadLibraryW("BootMenuUX.dll")   [或已加载则复用]
  -> GetProcAddress(h, "CreateSelectOSPage")
运行期：调用该函数，让它返回一个 Element*（或负责创建/填充该元素）
```

**为什么是【强推】而不是【实锤】**：
我证明了 (a) `attach` 字符串只存在于 bootux 的 duib 资源里；
(b) bootux 不静态导入 BootMenuUX；(c) dui70 有 `LoadLibrary`/`GetProcAddress`；
(d) 92 对里 81 对函数真实存在于导出表。
但我**没有**在反汇编里定位到"解析 `{A!B}` 语法的那段代码"
（`attach` 是 UTF-16 字符串，在 bootux 里只有 1 处，位于 `.rsrc` 的 duib 数据内），
也没有抓到 `LoadLibraryW` 的调用点。

**注意 `attach` 在 dui70 里完全不存在**【实锤】：

```
dui70.dll:  'attach' utf16=0
```

这意味着 `attach` 的解析**不在 dui70 里**，而是在 bootux 或
BootMenuUX 自己的代码里——它很可能通过
**`DUIXmlParser::SetUnknownAttrCallback`** 钩子接住
【猜想：`SetUnknownAttrCallback(bool(*)(const wchar_t*, void*), void*)`
签名存在且语义吻合（"遇到不认识的属性时回调"），但**没有证据**表明 attach 使用了它】。

### 4.5 对比：`attach` 与 `behaviors`

语料里另有 `behaviors=` **65 次**（按 `behaviors=` 字面统计），
语法是 `namespace::func(args)`：

```xml
<DeviceInterfaceTile ... behaviors="PVL::ImplicitAnimation()">
```

**这是两套完全不同的扩展机制**：

| | `attach="{Dll!Func}"` | `behaviors="NS::Func(args)"` |
|---|---|---|
| 次数 | 275 | 65 |
| 作用域 | 仅 bootux | 跨模块（DeviceElementSource 等） |
| 语法 | 模块 + 导出函数 | 命名空间 + 函数 + 参数 |
| 实现 | `LoadLibrary`/`GetProcAddress`【强推】 | `RegisterPVLBehaviorFactory`（RVA 0x8A50）【实锤，导出表】 |
| 语义 | 创建/接管元素 | 挂行为（动画等） |

`RegisterPVLBehaviorFactory` 是**导出**的【实锤，`pinned/exports.json`】，
说明行为工厂是**公开的扩展点**——这是比 `attach` **更正规**的扩展方式。

---

## 5. 宿主扩展点全景（按"有证据"排序）

| 扩展点 | 证据等级 | 说明 |
|---|---|---|
| `ClassInfoBase::ClassExist` + `Initialize` | 【实锤】导出 + DES 调用序列 + 类名字符串验证 | 注册自定义标签 |
| `ClassInfo<T,Base,Creator>::Register` | 【实锤】符号表 166 个静态 Register 符号 / 169 个类 + disasm | 内部类注册模板 |
| `RegisterAllControls` 家族 | 【实锤】导出 + disasm | 初始化内建控件 |
| `DuiCreateObject` | 【实锤】导出（RVA 0x8B00） | 按名命令式创建（同表二分） |
| `RegisterPVLBehaviorFactory` | 【实锤】导出（RVA 0x8A50） | 注册行为工厂 |
| `DUI70_*` C API（86 个） | 【实锤】导出表 | 扁平 C 包装 |
| `SetUnknownAttrCallback` | 【实锤】签名 | 未知属性回调 |
| `SetGetSheetCallback` | 【实锤】签名 | 样式表回调 |
| `SetParseErrorCallback` | 【实锤】签名 | 解析错误回调 |
| `attach="{Dll!Func}"` | 【强推】81/81 导出验证 | bootux 专用工厂 |

### 5.1 C API 面（86 个扁平导出）

`dui70` 导出了 **86 个非修饰名函数**【实锤，`pinned/exports.json`】。
与建树相关的：

```
DUI70_DUIXmlParserCreate            DUI70_DUIXmlParserCreateElement
DUI70_DUIXmlParserDestroy           DUI70_DUIXmlParserSetXMLFromResource
DUI70_ElementFindDescendent         DUI70_ElementGetChildren
DUI70_ElementGetRoot                DUI70_ElementSetID
DUI70_ElementSetContentString       DUI70_ElementSetVisible
DUI70_ElementSetLayoutPos           DUI70_ValueRelease
DuiCreateObject                     CreateDUIWrapper
GetElementMacro                     GetElementDataEntry
```

**给开发者的建议**：如果你在写 C 代码或跨语言绑定，
用 `DUI70_*` 这套扁平 API 比去调 C++ 修饰名可靠得多
（修饰名跨编译器版本会变）。

### 5.2 `GetElementMacro` / `GetElementDataEntry`：反向拿 Macro 数据

两个导出值得单独提【实锤，导出表】：

```cpp
GetElementMacro(Element*)      // RVA 0xDB050
GetElementDataEntry(Element*)  // RVA 0xDB020
```

结合`02-value-type-system.md` 的 `<bind>` 机制，这是宿主**检查/驱动模板实例**的官方入口：
拿到一个 `Element*`，问"你是不是 Macro"、"你的 DataEntry 是什么"。

---

## 6. 教学案例：如果你要在自己的应用里注册自定义标签

综合以上证据，一个**基于实锤的最小流程**：

### 6.1 准备

```cpp
// 你的控件
class MyTile : public DirectUI::TouchButton { /* ... */ };
```

### 6.2 属性表（必须有，可为空）

`ClassExist` 的第 2/3 参是 `PropertyInfo* 数组 + 个数`。
DES 传的是 `propCount = 0` + `base = NULL`
（因为它注册的 `DESAnimatedTouchButton` 属性全继承自基类）
【实锤，disasm：`xorl %r8d,%r8d` / `xorl %edx,%edx`】。

### 6.3 注册

```cpp
// 前提：基类已注册（通常由框架 InitProcessPriv / RegisterAllControls 完成）
IClassInfo* ci = nullptr;
BOOL existed = ClassInfoBase::ClassExist(
    &ci,
    props, nProps,
    /*base*/ NULL,
    /*module*/ g_hInst,
    /*name*/ L"MyTile",
    /*isGlobal*/ FALSE);      // 建议 FALSE，避免污染
if (!existed) {
    // new ClassInfo<MyTile, TouchButton, StandardCreator<MyTile>>
    // vtable = &ClassInfo<...>::`vftable'  ← DES 里那个 leaq 0x18001a6c8
    // ClassInfoBase::Initialize(g_hInst, L"MyTile", false, props, nProps)
}
```

### 6.4 在 XML 里用

```xml
<MyTile id="atom(tile1)" layoutpos="top" class="mtile"/>
```

### 6.5 三件必须注意的事（均有实锤支撑）

1. **基类必须先注册**——否则 `Register` 在
   `movq s_pClassInfo@Base; je <失败>` 处直接失败【实锤，disasm 0x180005361】。
2. **`ClassExist` 返回 true 不代表失败**——那是"类已存在，别重复注册"，
   而且此时出参 `out` 已被填好，**直接用它即可**
   （DES 在 `jne 0x180008a88` 分支里就是这么做的）【实锤，disasm 0x180008997】。
3. **注册路径有锁**——你不需要自己加锁【实锤，Enter/LeaveCriticalSection】。

---

## 7. 真实例子汇总

### 7.1 bootux：一个完整的自研控件库

```xml
<!-- docs/duixml-corpus/bootux/UIFILE_600.xml (duib v5, 70984 字节) -->
<BUXPage resid="AdvancedBootOptionsPage" flags="ResetTravelog"
         attach="{BootMenuUX!CreateSelectOSPage}" class="menupage">
  <BUXTitle content="resstr(1601)" />
  <element layoutpos="top" layout="verticalflowlayout()" class="menupage::content">
    <BUXButton class="menutile" id="atom(BareMetalRecovery)"
               attach="{BootMenuUX!CreateBareMetalRecoveryButton}">
      <element class="menutile::spacer" />
```

- `BUX*` 15 个标签、1377 次使用：bootux **自己注册**的类【实锤，
  bootux 导入 `ClassExist` + `Initialize`，且 `.rdata` 里有 `BUXPage` 字符串】。
- `attach` 275 次：调 `BootMenuUX.dll` / `FveRecoverUX.dll` 的导出函数【强推】。
- 这份 XML 是 **duib 二进制**，说明自研控件库 + 二进制格式可以并存。

### 7.2 DeviceElementSource：现代触控控件（有完整证据链）

```xml
<!-- docs/duixml-corpus/DeviceElementSource/UIFILE_200.xml -->
<DeviceInterfaceTile resid="DeviceInterfaceTile" sheet="DeviceInterfaceTileStyle"
                     layoutpos="none" layout="borderlayout()"
                     behaviors="PVL::ImplicitAnimation()">
  <DESAnimatedTouchButton id="atom(idMainButton)" layoutpos="top"
                          layout="borderlayout()" class="des_itfMainButton"
                          active="mouse|keyboard|pointer">
```

`DESAnimatedTouchButton` 的注册反汇编我逐条读过（§3），
类名字符串 dump 验证过。**这是教程里证据最硬的一个例子。**

### 7.3 NavigateButton：跨 20+ 模块的共享控件

`NavigateButton` 113 次，出现在 `shell32.dll`、`SpaceControl`、
`DiagCpl`、`fhcpl`、`sdcpl`、`RADCUI`、`autoplay`、`fontext`、`hgcpl` 等
【实锤，本教程 System32 全盘字符串扫描：29 个 DLL 含 UTF-16 字符串
`NavigateButton`】。

**关键观察**：这些模块**大多自己不导入 `ClassExist`**
（如 `DXP`、`werconcpl`、`fontext`、`hgcpl`、`InputSwitch`）
【实锤，导入表】——它们用的是 **delay-load DUI70**
【实锤，我解析了 delay import 目录：DXP/werconcpl/fontext/
UserAccountControlSettings/hgcpl/InputSwitch 全部 delay-load `DUI70.dll`】。

所以 `NavigateButton` 必然由**某个公共 DLL** 注册
（候选：`shell32.dll`，它的 `.rdata` 里有该字符串）
——**具体是谁，我没有确证**（见 §8 问题 3）。

`NavigateButton` 在 shell32 的 `.rdata` 里有字符串
【实锤，本教程 section 定位：`shell32.dll` @ `0x68cd20`，`.rdata`】，
但 `shell32.dll` **不导入** `ClassExist`【实锤】——它可能通过
`GetProcAddress` 动态取，或该字符串另有用途。**这条链没闭合。**

---

## 8. 未知问题清单

1. **`ClassExist` 的调用契约中，"已存在"分支该怎么用？**
   代码显示返回 true 时 `out` 已被填充、直接跳到使用（实锤），
   但**参数 `props`/`propCount` 在已存在时是否必须仍有效**、
   `isGlobal` 不一致时会怎样，都没有验证。
   §3.2 的示例代码是**从反汇编反推的，我没有编写并运行过一个第三方注册 DLL**。
2. **`attach="{A!B}"` 的解析代码在哪？** `attach` 字符串在 dui70 里
   **完全不存在**（实锤，UTF-16 计数 0），在 bootux 里只有 1 处且在
   `.rsrc` duib 数据内。所以解析器可能是 bootux 的，也可能是
   BootMenuUX 的。**没有定位到那段代码。**
3. **`NavigateButton` 由谁注册？** 29 个 DLL 含该字符串，
   但导入 `ClassExist` 的没有 shell32。链未闭合。
4. **`parser+0xb0` 那个对象的确切类型**（`01-duixmlparser-xml-to-element-tree.md` §8 问题 1 同）。
   这直接决定"私有表怎么挂"。
5. **`ClassInfo<T,Base,Creator>` 的 `Creator` 策略有几种？**
   我见到 `StandardCreator` / `EmptyCreator`，**是否还有别的、各自语义**
   未查。`EmptyCreator` 为什么存在（"不可从 XML 创建"？）只是猜想。
6. **`isGlobal=false` 的私有表，第三方能否访问？**
   如果只有 dui70 内部能 insert 到 `parser+0xb0`，
   那第三方就**只能**用 `isGlobal=true`——这是一个**关键的可用性问题**，
   我没有答案。
7. **`behaviors="NS::Func(args)"` 与 `RegisterPVLBehaviorFactory` 的
   绑定关系**未验证。我只知道两者都存在（实锤），
   "PVL" 是什么的缩写（**P**er-**V**iew **L**ibrary?）也不知道。
8. **`SetUnknownAttrCallback` 是否就是 `attach` 的实现机制？**
   签名 `bool(*)(const wchar_t* attrName, void* ctx)` 语义吻合，但无证据。
9. ~~`DESAnimatedTouchButton` 注册时 `propCount=0`、`base=NULL`，
   那它的属性从哪来？~~
   **部分解决**：DES 有 **3 个** `ClassExist` 调用点，我把三个都读了，
   **三个形态完全一致**（`xorl %r8d,%r8d` / `xorl %edx,%edx` =
   `base=NULL` / `propCount=0`），只是类名字符串不同【实锤】：

   | 调用点 RVA | `leaq` 的 RVA | 类名（已 dump 验证） |
   |---|---|---|
   | 0x180008989 | 0x18001c418 | `DESAnimatedTouchButton` |
   | 0x180008b75 | 0x18001c3f0 | `DeviceContainerTile` |
   | 0x180008d61 | 0x18001c3c8 | `DeviceInterfaceTile` |

   后两个名字与语料 `DeviceElementSource/UIFILE_200.xml` 里的
   `<DeviceInterfaceTile ...>` 完全对应【实锤，语料 + 二进制互证】。

   **但仍未解决的是机制问题**：`base=NULL` + `propCount=0` 时
   这些类怎么获得 `id`/`layoutpos`/`class` 等属性？
   两种可能：（a）`ClassExist` 内部对 `base=NULL` 有默认行为；
   （b）属性其实不通过 `ClassExist` 注册，而是另有路径。
   **我没有答案**，这是本教程最需要补的一点。
10. **`FveRecoverUX.dll` 不在本机 System32**，所以那 11 对
    `attach` 无法验证。它属于 WinRE 环境。

---

## 9. 证据索引

| 结论 | 证据 |
|---|---|
| 154 个标签找不到对应类 | `unknown4.py` 全语料扫描（大小写不敏感）【实锤】 |
| `BUX*` 15 标签 1377 次全在 bootux | 同上 + 模块归属统计【实锤】 |
| `ClassExist` 签名 | `pinned/symbols.json` 修饰名反解【实锤】 |
| `ClassExist` = 16 字节项二分 + `_wcsicmp` | disasm 0x180036c6c + PE 导入表【实锤】 |
| 两级查找（parser+0xb0 / 全局表） | disasm 0x180034900【实锤】 |
| DES 导入并调用 `ClassExist`/`Initialize` | 导入目录解析 + disasm 0x180008989【实锤】 |
| `leaq 0x18001c418` = `"DESAnimatedTouchButton"` | 直接从 DLL 读 UTF-16 字节【实锤】 |
| DES 三个注册点的类名全部 dump 验证 | `DESAnimatedTouchButton` / `DeviceContainerTile` / `DeviceInterfaceTile`【实锤】 |
| 基类必须先注册 | disasm 0x180005361 (`je <失败>`)【实锤】 |
| 注册有临界区锁 | 导入表 `0x119988/0x119980` = Enter/LeaveCriticalSection【实锤】 |
| `RegisterAllControls` 级联 | disasm 0x180008c60 + 符号表【实锤】 |
| `attach` 仅 bootux、275 次 | `attach.py` 模块统计【实锤】 |
| `attach` 的 81 个函数真实存在 | `attach_verify.py` 导出表比对【实锤】 |
| bootux 不静态导入 BootMenuUX | objdump 导入表 47 个 DLL【实锤】 |
| 6 个模块 delay-load DUI70 | 本教程解析 delay import 目录【实锤】 |
| 86 个扁平 C 导出 | `pinned/exports.json`【实锤】 |
| `attach` 用 LoadLibrary/GetProcAddress | 【强推】间接证据链，未定位调用点 |
| §3.2 注册示例代码 | 【强推】从 DES 反汇编反推，未实机验证 |

**复现脚本**：`.local/build/p3-parser/` 下
`unknown4.py`（标签分类）、`correlate.py`（模块×ClassExist 关联）、
`attach.py` + `attach_verify.py`（attach 统计与导出验证）、
`des_callsites.py`（DES 的 ClassExist 调用点 + IAT 解析）、
`delay.py`（delay import 目录）、`where_string.py`（字符串所在 section）、
`api_surface.py`（导出面）、`find_registrant.py`（System32 全盘字符串扫描）。

**相关材料**：
- `01-duixmlparser-xml-to-element-tree.md`《duixml 是怎么被吃进去的》§3（两级查找、`Register` 级联）
- `02-value-type-system.md`《Value 类型系统》§5（`<bind>` 的窄机制）
- `.local/audit/ui-mental-model-outline.md` §6（声明式 vs 命令式双轨）
- `docs/duixml-corpus/README.md` §3（元素标签家族分类）
