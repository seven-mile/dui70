# duixml 是怎么被吃进去的：DUIXmlParser 从 XML 到元素树

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 目标：读完你能看懂 `<duixml>` 文档被 `DUIXmlParser` 消费的全过程，
> 知道标签名怎么变成 C++ 类、属性字符串怎么变成 Value、表达式在哪里求值。
>
> 证据分级：【实锤】= 反汇编定位到指令 / 语料原文 / 可运行验证之一；
> 【强推】= 符号名 + 结构自洽的推断，写明推断链；【猜想】= 明确标注为猜测。
> 反汇编地址均为 RVA（`dui70.dll` 10.0.26100.8875 x64，基址 0x180000000），
> 可用 `llvm-objdump -d --start-address=0x180000000+<RVA> C:\Windows\System32\dui70.dll` 复现。

---

## 1. 一句话心智模型

**duixml 是"一次性的构造函数说明书"，不是活文档。**

`SetXML` 装载 → `CreateElement` 实例化子树 → 之后 XML 就"用完即弃"。
运行时再改属性要走 `Element::SetValue` / 属性系统，跟 XML 无关了。

这不是猜测，是 UITest 的调用序列实证：【实锤，`UITest/UITest.cpp:506-538`】
先 `SetXMLFromResource`，再 `CreateElement`，之后全程操作的是 `Element*`，不再回看 XML。

---

## 2. DUIXmlParser 的 154 个成员：职责地图

`pinned/symbols.json` 里 `DUIXmlParser` 有 **154** 个成员符号【实锤，符号表】。
把它们按职责分堆，这个类其实是一台"五合一"的机器：

| 职责 | 代表成员 | 说明 |
|---|---|---|
| **装载** | `SetXML` `SetXMLFromResource` `SetPreprocessedXML` `_SetBinaryXml` | 拿到 XML 文本或资源 ID |
| **读取驱动** | `CreateXmlReader` `CreateXmlReaderFromHGLOBAL` `InitializeParserFromXmlReader` | 造 IXmlReader（xmllite 或自研二进制） |
| **建树** | `CreateElement` `_BuildElement` `_BuildChildren` `_BuildFromBinary` | XML 节点 → Element 对象树 |
| **取类** | `_GetClassForElement` `_GetClassForElementByName` `LookupElement` | 标签名 → IClassInfo |
| **解值** | `_ParseValue` + 30 余个 `Parse*` | 属性字符串 → Value 对象 |
| **样式** | `ParseStyleSheets` `_ResolveStyleSheet` `_SetProperties` `AddRulesToStyleSheet` | 样式表挂接与解析 |
| **缩放** | `_ScalePointsToPixels` `_ScaleRelativePixels` `SetScaleFactor` `IsDynamicScaling` | rp/pt → px（见 §6） |
| **错误** | `SendParseError` `SetParseErrorCallback` `_GetLineInfo` | 解析失败上报（带行号） |
| **宿主钩子** | `SetGetSheetCallback` `SetUnknownAttrCallback` `SetParseErrorCallback` | 回调注入点 |

装载 API 的签名（从修饰名反解，`pinned/symbols.json`）：

```cpp
long DUIXmlParser::SetXML(const wchar_t* xml, HINSTANCE res, HINSTANCE unknown);
long DUIXmlParser::CreateElement(const wchar_t* resid, Element* parent,
                                 Element* unknown, unsigned long* /*flags*/, Element** out);
```

【实锤，符号签名 + UITest 调用】

### 2.1 装载：XML 文本从哪来

三条入口，都最终落到 `_SetXMLFromResource` / `_SetBinaryXml`：

- **`SetXML(text,...)`** — 直接给字符串。
- **`SetXMLFromResource(resid,...)`** — 从 PE 资源取 `UIFILE`（这是绝大多数系统组件的用法）。
  语料里 149 个 XML 全是这么被系统组件带在资源里的【实锤，语料库 README】。
- **`SetPreprocessedXML`** — 给已经预处理过的文本（见 §5 的 Macro）。

### 2.2 读取驱动：同一个接口，两种物理形态

这是本教程最关键的一个发现。

`CreateXmlReader` 造出来的 reader **不一定是 xmllite**。`dui70` 内部有一个
`CBinaryXmlReader`（35 个成员），它的方法名是 **`IXmlReader` 接口的完整实现**：

```
GetAttributeCount  GetDepth  GetLineNumber  GetLinePosition  GetLocalName
GetNamespaceUri    GetNodeType  GetPrefix  GetQualifiedName  GetValue
IsDefault  IsEOF  IsEmptyElement  MoveToAttributeByName  MoveToElement
MoveToFirstAttribute  MoveToNextAttribute  Read  ReadValueChunk  SetInput
PushState  PopState  SeekToResource  GetResource
```

【实锤，`pinned/symbols.json` 的 `CBinaryXmlReader` 成员表】

也就是说，`_BuildElement` 这一层的代码**不需要知道**它在读文本 XML 还是读 duib 二进制
——两者都通过 `IXmlReader` 暴露。这正是 duib 能被透明支持的原因。

`CBinaryXmlReader::Create` 的签名直接印证：

```cpp
static long CBinaryXmlReader::Create(const unsigned char* buf, unsigned __int64 len,
                                     IXmlReader** out);
static bool CBinaryXmlReader::IsBufferBinaryDUI(const unsigned char* buf, unsigned __int64 len);
```

【实锤，符号签名】`IsBufferBinaryDUI` 是个嗅探函数——判断这段 buffer 是不是 duib。
duib 的物理格式（magic `'duib'` + version 5 + 三个 chunk 偏移）见
`docs/duixml-corpus/README.md` §9，我方解码器 `.local/corpus/duib2xml.py` 输出
与既有手工 XML 逐字节一致【实锤】。

> **给应用开发者的启示**：你不需要关心这个分支。`SetXMLFromResource` 会自动
> 嗅探 `IsBufferBinaryDUI`，明文和 duib 都能吃。duib 只是体积优化，语义等价。

---

## 3. 标签名 → C++ 类：两级查找

这是"duixml 为什么是开放 schema"的机制基础（`03-host-registered-tags.md` 会展开）。

`_GetClassForElementByName` 的完整反汇编在 **RVA 0x34900**【实锤，disasm 0x180034900】。
关键指令序列：

```asm
; rcx = this (DUIXmlParser*), rdx = 标签名 (wchar_t*), r8 = out (IClassInfo**)
18003491f: cmpq   0x180118bc0(%rip), %rdx     ; 与一个全局常量比较
18003492f: je     0x18003499e                  ; 相等 -> 走特殊分支
180034931: movq   0xb0(%rcx), %rcx             ; ★ parser + 0xb0 = per-parser 扩展表
180034938: movq   (%rcx), %rax                 ; 取 vtable
18003493b: movq   0x18(%rax), %rax             ; ★ vtable + 0x18 = lookup 方法
18003493f: callq  0x1800ff010                  ; 间接调用（guard check + call）
180034944: testl  %eax, %eax
180034946: js     0x180034966                  ; 失败(<0) -> 落全局表
...
180034966: movl   $0x800403ee, %edi            ; 错误码 E_INVALIDARG 系
```

**两级结构**：

1. **per-parser 扩展表**（`parser+0xb0` 指向的对象，方法在 vtable+0x18 lookup / +0x28 insert）
   —— 查不到（返回 < 0）就落第 2 级；查到则 `0x800403ee` 路径用于**注册**新类。
2. **全局排序表**（`0x180183088`，16 字节项）—— 二分查找。

### 3.1 全局表的二分：ClassExist

`ClassExist`（RVA `0x36c10`）内部 `callq` 到 **`CClassFactory::GetExact`**（RVA `0x36c6c`，
PDB 符号确认两者是独立函数），后者是教科书式二分【实锤，disasm 0x180036c6c】：

```asm
180036c89: movq   0x180183088(%rip), %rcx     ; ★ 全局类表基址
180036ca0: movq   (%rcx), %r14                ; r14 = 表头
180036ca3: cmpq   %rbx, 0x8(%r14)             ; 表头+8 = 元素个数，为 0 则返回
...
180036ca9: movl   (%r14), %edi                ; edi = count
180036cae: decl   %edi
180036cb0: cmpl   %edi, %ebp                  ; lo <= hi ?
180036cb2: jg     ...                         ; 越界退出
180036cb4: leal   (%rdi,%rbp), %eax           ; mid = (lo+hi)
180036cb7: movl   $0x2, %ecx
180036cbc: cltd
180036cbd: idivl  %ecx                        ; mid /= 2
180036cbf: movslq %eax, %r13
180036cc2: movq   %r13, %rsi
180036cc5: shlq   $0x4, %rsi                  ; ★ mid * 16 —— 16 字节一项
180036cc9: addq   0x8(%r14), %rsi             ; + 数组基址
180036cdd: callq  *0xe2f2c(%rip)              ; ★ 比较函数 = msvcrt!_wcsicmp（已解析 IAT）
180036ce9: testl  %eax, %eax
180036ceb: je     ...                         ; 相等 -> 命中
180036ced: js     0x180036cf5                  ; <0 -> hi = mid-1
180036cef: leal   0x1(%r13), %ebp             ; >0 -> lo = mid+1
```

**16 字节一项**，与 ui-mental-model §6 记的 `{name, IClassInfo*}` 结构一致【实锤】。

我解析了 `dui70.dll` 的导入表，`0x180119c10` 这个 IAT 槽指向
**`msvcrt.dll!_wcsicmp`**【实锤，本教程解析 PE 导入目录得出】：

```
0x119C10 -> msvcrt.dll!_wcsicmp
0x119988 -> api-ms-win-core-synch-l1-1-0.dll!EnterCriticalSection
0x119980 -> api-ms-win-core-synch-l1-1-0.dll!LeaveCriticalSection
0x119530 -> api-ms-win-core-atoms-l1-1-0.dll!FindAtomW
```

所以二分 + **`_wcsicmp`** 意味着**标签名查找大小写不敏感**
（语料里 `<element>` / `<Element>` 混用能工作，与此吻合）。
顺带也确认了 §3.3 里 `Register` 用的 `0x180119988` / `0x180119980`
**确实是 `EnterCriticalSection` / `LeaveCriticalSection`**——注册路径上确实有锁【实锤】。

### 3.2 这条路径的导出线索

`ClassExist` 是**导出**的（ordinal 1044，RVA 0x36c10）【实锤，`pinned/exports.json`】。
谁导入它？**bootux.dll 和 DeviceElementSource.dll 都导入了**【实锤，
`llvm-objdump -p` 的导入表】：

```
bootux.dll:             1043  ?ClassExist@ClassInfoBase@DirectUI@@SA_NPEAPEAUIClassInfo@2@...
DeviceElementSource.dll:1043  ?ClassExist@ClassInfoBase@DirectUI@@SA_NPEAPEAUIClassInfo@2@...
```

签名展开：

```cpp
static bool ClassInfoBase::ClassExist(
    IClassInfo** out,
    const PropertyInfo* const* props,   // 属性表
    unsigned int propCount,
    IClassInfo* base,                   // 基类
    HINSTANCE module,                   // 本 DLL
    const wchar_t* name,                // ★ 标签名
    bool isGlobal);
```

【实锤，符号签名】这就是**第三方注册自定义标签的入口**——详细调用契约见`03-host-registered-tags.md`。

### 3.3 内建控件也是"注册"进来的

`dui70` 自己的类不是天然存在的，而是启动时通过 `Register*Controls` 家族注册：

```
RegisterAllControls (RVA 0x8c60)          ← 总入口
 ├─ RegisterBaseControls        (0x8c00)
 ├─ RegisterStandardControls    (0x5890)
 ├─ RegisterExtendedControls    (0x47c0)
 ├─ RegisterMacroControls       (0x87e0)
 ├─ RegisterBrowserControls     (0x8840)
 ├─ RegisterXControls           (0x8880)
 ├─ RegisterMiscControls        (0x8810)
 └─ RegisterCommonControls      (0x4fa0)
```

【实锤，符号表 + disasm 0x180008c60】`RegisterAllControls` 就是依次调用它们，
每个都检查返回值 `< 0` 就提前返回（错误短路）。

每个具体类则通过 **`ClassInfo<T, Base, Creator>::Register`** 模板注册【实锤，符号表】：

```
ClassInfo<Button, Element, StandardCreator<Button>>::Register
ClassInfo<HWNDElement, ElementWithHWND, EmptyCreator<HWNDElement>>::Register
ClassInfo<Bind, Element, StandardCreator<Bind>>::Register
...
```

`pinned/symbols.json` 里 **166 个静态 `ClassInfo<...>::Register` 符号**，
分布在 **169 个类**上（有些类有多个重载/cv 变体）【实锤，符号表统计】。
`ClassInfo` 模板三个参数的含义一目了然：
**目标类 / 基类 / 工厂**。`EmptyCreator` 表示"不可从 XML 创建"（如抽象基类）。

单个 `Register` 的反汇编（以 `Button` 为例，RVA 0x5348）【实锤，disasm 0x180005348】：

```asm
180005357: movq   0x180183090(%rip), %rcx    ; ★ s_pClassInfo@Element 全局指针
180005361: je     <失败>                      ; 基类未注册 -> 失败（级联依赖）
180005367: movq   (%rcx), %rax
18000536a: movq   (%rax), %rax                ; vtable[0] = AddRef
18000536d: callq  0x1800ff010                  ; 给基类加引用
180005379: callq  *0x180119988                ; 取锁（CRITICAL_SECTION 系）
18000538f: orq    $-0x1, %r9                   ; 第 5 参数
180005393: leaq   0x18011f5a8(%rip), %r8       ; 第 4 参数
18000539a: movb   $0x1, %dl
18000539c: callq  0x180036c6c                  ; ★ 复用 ClassExist 的内部实现！
1800053a1: testq  %rax, %rax
1800053a7: jne    <已存在分支>
1800053a9: andq   $0x0, 0x180183688(%rip)      ; ★ s_pClassInfo@Button = NULL
1800053c1: callq  0x18007d0c0                  ; 造新的 ClassInfo 实例
1800053f5: callq  0x1800369a0                  ; ★ ClassInfoBase::Register
```

**读法**：`ClassInfo<T,...>::Register` 先给基类 `AddRef`，再拿全局锁，
然后**复用 `ClassExist` 的内部实现**检查是否已注册，没注册就 `new` 一个
`ClassInfo` 并调 `ClassInfoBase::Register()` 入表【实锤】。

> 注意 `0x180005361: je <失败>` —— **基类必须先注册**。这解释了为什么
> `RegisterAllControls` 的调用顺序（Base → Standard → Extended → …）不能乱：
> 它是一条拓扑排序。

### 3.4 `DuiCreateObject`：绕开 XML 的命令式入口

`DuiCreateObject`（导出，RVA 0x8b00）走的是**同一张全局表的二分查找**
【实锤，ui-mental-model §6 记录的 disasm 行 9651；本教程复核了符号与导出表】。
找不到类名时兜底到 `UnknownElement` / `HWNDElement`。

含义：**XML 只是 `DuiCreateObject` 的批量前端**。你完全可以纯命令式建 UI。
这也解释了 `CreateDUIWrapper` 等导出为什么能独立工作。

---

## 4. Parse* 方法族 ↔ 语料表达式函数：一一对应

这是最能验证"符号表 ↔ 真实语料"对应关系的地方。

### 4.1 对照表

| duixml 表达式 | 语料频次 | 解析器实现（`pinned/symbols.json`） | RVA |
|---|---|---|---|
| `gtc(class,part,state,prop)` | 1716 | `ParseGTCColor` | 0x141C0 |
| `gtf(class,part,state)` | 1667 | `ParseGTFStr` | 0x14A50 |
| `dtb(class,part,state)` | 1289 | `ParseDTBFill` | 0x14320 |
| `argb(a,r,g,b)` | 358 | `ParseARGBColor` | 0x14F20 |
| `rgb(r,g,b)` | 200 | `ParseRGBColor` | 0x7E500 |
| `resstr(id[,library(x)])` | 3338 | `ParseResStr` | 0x15540 |
| `atom(name)` | 4082 | `ParseAtomValue` | 0x13FD0 |
| `sysmetric(n)` | 345 | `ParseSysMetricInt` / `ParseSysMetricStr` | 0x73F40 / 0xDE6B0 |
| `rect(l,t,r,b)` | 3338 | `ParseRectRect` / `ParseRectValue` | 0x14400 / 0x66950 |
| `size(w,h)` | 141 | `ParseSizeSize` / `ParseSizeValue` | 0x7A100 / 0x18260 |
| `library(dll)` | 524 | `ParseLibrary` | 0x71830 |
| `gtmar()` | 34 | `ParseGTMarRect` | 0x7FE60 |
| `gtps()` | 2 | `ParseGTPartSize` | 0x82E80 |
| `ressheet(...)` | 53 | `ParseStyleSheets` | 0x378E0 |

（语料频次来自 `docs/duixml-corpus/README.md` §5 与本次对 149 个 XML 的复核。
解析器成员来自 `pinned/symbols.json`，`DUIXmlParser` 类。）【实锤】

**注意命名规律的偏移**：语料写 `gtc`，实现叫 `ParseGTCColor`；
语料写 `dtb`，实现叫 `ParseDTBFill`（DTB = **D**raw**T**heme**B**ackground）。
`gtc/gtf` = **G**et**T**heme**C**olor/**F**ont。这些不是凭空命名，
是 Win32 `GetThemeColor` / `DrawThemeBackground` 的直译【强推，命名 + 语义吻合】。

### 4.2 表达式求值的驱动：`_ParseValue` 与 `FunctionDefinition<T>`

`_ParseValue`（RVA 0x11CA0）签名：

```cpp
long DUIXmlParser::_ParseValue(const PropertyInfo* prop, const wchar_t* text, Value** out);
```

【实锤，符号签名】它接收**属性元信息 + 属性字符串**，吐出一个 `Value*`。

反汇编（**RVA 0x11ca0**）显示它是"先试函数、失败再试字面量"的结构【实锤，disasm 0x180011ca0】：

```asm
180011cfc: callq  0x180012490                  ; 第一步：尝试解析为函数调用
180011d03: movl   $0x800403f1, %r12d           ; 预设错误码
180011d09: testl  %eax, %eax
180011d0b: js     0x180011e6b                  ; 失败 -> 走别的分支
180011d15: cmpl   $0x2, (%rbx)                 ; ★ 检查节点类型 == 2
180011d1a: movq   0x8(%rbx), %rcx              ; 取名
180011d1e: leaq   0x18011f780(%rip), %rdx     ; ★ 函数名比较：字符串 1
180011d25: callq  *0x180119c10                 ; 间接调用（wcscmp 类）
180011d33: je     <命中分支 1>
180011d39: movq   0x8(%rbx), %rcx
180011d3d: leaq   0x18011f798(%rip), %rdx     ; ★ 字符串 2
180011d63: callq  *0x180119c10                 ; ...
180011d71: je     <命中分支 2>
```

**三次字符串比较**对应三个**特殊函数名**，我 dump 了这三个常量
【实锤，本教程读取 `.rdata` 得出】：

| 常量 RVA | 字符串 | 语义 |
|---|---|---|
| `0x18011f780` | `themeable` | 主题色 + 高对比度回退（语料 1341 次） |
| `0x18011f798` | `valueWithHighContrastFallback` | 同上，完整拼写形式 |
| `0x18011f7d8` | `composited` | 合成值 |

**重要修正**：`_ParseValue` 的前三次比较**不是**通用函数分派，
而是**特判这三个"需要特殊求值语义"的函数名**——它们不是简单求值，
而是要拿"当前主题 + 高对比度状态"来决定用哪个值。

这是一个**手写的 if-else 特判链**，不是哈希表
【强推：三处连续的 `leaq <字符串常量>` + 比较 + 条件跳转，是编译后的 if-else 形态】。
通用函数（`gtc`/`dtb`/`rect`/`resstr`…）走的是后面的 `ParseFunction` 路径。

**教学意义**：`themeable(a, b)` 的语义是"能用主题色就用 a，否则用 b"，
它必须在解析期知道主题和高对比度开关——所以被提到最前面特判。
语料里 1341 次 `themeable` 几乎每次 `dtb` 都配一个 fallback
（`docs/duixml-corpus/README.md` §5），原因在此【实锤，语料 + 反汇编互证】。

顺带 dump 出邻近字符串：`atom`（`0x18011f7f8`）——`ParseAtomValue` 的锚点，
以及格式串 `%d;%d;%d;%s;%d`（`0x18011f818`，像是某种序列化/调试格式）【实锤】。

`FunctionDefinition<T>` 有**五个实例化**，与任务书描述一致【实锤，符号表】：

```
FunctionDefinition<int>
FunctionDefinition<unsigned long>
FunctionDefinition<class Value*>
FunctionDefinition<struct ScaledRECT>
FunctionDefinition<struct ScaledSIZE>
```

每个只导出 `operator=` 两个符号（编译器合成的赋值），**没有方法符号**——
说明它们是**薄模板，逻辑全在头文件内联**【强推：符号表只有 operator=，
是 header-only 模板的典型符号残留形态】。

**为什么恰好这五类？** 因为表达式求值结果就这五种落点：
整数、无符号（原子/颜色）、Value*、带缩放的矩形、带缩放的尺寸。
与 `Value::Create*` 工厂一一呼应（见`02-value-type-system.md` 类型表）【强推，结构自洽】。

### 4.3 函数名表在二进制里是可验证的

在 `dui70.dll` 里搜 UTF-16LE 字符串，函数名**确实存在**，且多为
NUL 前缀（即独立的 C 字符串）【实锤，本教程实测】：

| 名字 | UTF-16 出现次数 | NUL 前缀次数 |
|---|---|---|
| `resstr` | 44 | 44 |
| `atom` | 47 | 44 |
| `rect` | 121 | 42 |
| `library` | 43 | 1 |
| `sysmetric` | 2 | 2 |
| `gtc` / `gtf` / `dtb` | 2 / 1 / 1 | 2 / 1 / 1 |
| `ressheet` | 2 | 2 |
| `gtmar` / `gtps` | 1 / 1 | 1 / 1 |

复现命令：
```powershell
python -c "d=open(r'C:\Windows\System32\dui70.dll','rb').read(); print(d.count('resstr'.encode('utf-16-le')))"
```

**`dtbf` / `dtbcolor` 出现 0 次**——说明这些不是真实函数名，
写进 XML 会解析失败【实锤】。

---

## 5. 真实例子：一次完整的解析

### 5.1 autoplay 的资源 101（明文 XML）

来源：`%SYSTEMROOT%\System32\autoplay.dll`，资源 `UIFILE/101`
【实锤，`docs/duixml-corpus/autoplay/UIFILE_101.xml`】

```xml
<element id="atom(storageDeviceHandlerSettings)" layoutpos="top"
         layout="borderlayout()" margin="rect(0rp,25rp,0rp,25rp)">
  <macro expand="macroLineDivider">
    <bind connect="title" content="resstr(1117)" id="atom(StorageDevicesTitle)"/>
  </macro>
  <VolumeHandlerSetting ContentType="CT_STORAGE" expand="macroHandlerSetting"/>
  <CCCheckBox id="atom(checkboxEnableContentDiscovery)" selected="false"
              padding="rect(10rp,10rp,0rp,10rp)" content="resstr(1122)"
              shortcut="auto" background="themeable(dtb(CONTROLPANEL,2,0),window)"
              layoutpos="top"/>
```

这一次解析里同时出现了：

- `layout="borderlayout()"` —— 零参函数，走 `ParseFunction` + `Value::CreateLayout`
- `margin="rect(0rp,25rp,0rp,25rp)"` —— 四参函数，`rp` 单位要缩放（§6）
- `background="themeable(dtb(CONTROLPANEL,2,0),window)"` —— **嵌套函数**：
  `themeable` 的第 1 参又是一个 `dtb(...)` 调用
- `content="resstr(1117)"` —— 走 `ParseResStr`
- `id="atom(...)"` —— 走 `ParseAtomValue`
- `<macro expand=...>` / `<bind connect=...>` —— 模板机制（`02-value-type-system.md` §4）

**关键观察**：`themeable(dtb(...), window)` 证明解析器必须支持
**递归的表达式树**，不是"一个函数名 + 平铺参数"。这与 `FunctionDefinition<T>`
和 `ParserTools::ExprNode` 的存在吻合【强推：`ExprNode` 在符号表里以
`DynamicArray<ParserTools::ExprNode,0>` 出现，是树节点容器的形态】。

### 5.2 bootux 的资源 600（duib 二进制）

来源：`%SYSTEMROOT%\System32\bootux.dll`，资源 `UIFILE/600`，**70984 字节 duib v5**
【实锤，`docs/duixml-corpus/bootux/UIFILE_600.xml` 头部元数据】

```xml
<BUXPage resid="AdvancedBootOptionsPage" flags="ResetTravelog"
         attach="{BootMenuUX!CreateSelectOSPage}" class="menupage">
  <BUXTitle content="resstr(1601)" />
  <element layoutpos="top" layout="verticalflowlayout()" class="menupage::content">
    <BUXButton class="menutile" id="atom(BareMetalRecovery)"
               attach="{BootMenuUX!CreateBareMetalRecoveryButton}">
      <element class="menutile::spacer" />
```

这份走的是 `_BuildFromBinary` 分支（`IsBufferBinaryDUI` 为真），
但**产出的元素树与明文完全同构**——`BUXPage` 标签必须能被
`_GetClassForElementByName` 解析成 `IClassInfo`，而 `BUX*` 类**不在 dui70 里**
（语料中有 136 个这样的标签，见`03-host-registered-tags.md`）。这就是开放 schema 的直接证据。

---

## 6. rp 单位：解析期烘焙

`rp` = relative pixel。语料里 `rect(0rp,10rp,40rp,10rp)` 遍地，
`docs/duixml-corpus/README.md` §5 统计 `rect` 3338 次【实锤】。

### 6.1 换算指令

`_ScaleRelativePixels`（**RVA 0x718F0**）完整反汇编【实锤，disasm 0x1800718f0】：

```asm
1800718f0: subq   $0x28, %rsp
1800718f4: movd   %edx, %xmm0            ; 入参 int -> xmm
1800718f8: cvtdq2ps %xmm0, %xmm0         ; int -> float
1800718fb: mulss  0x5c(%rcx), %xmm0      ; ★ × (this + 0x5c)  —— 缩放因子！
180071900: addss  0xb0938(%rip), %xmm0   ; ★ + 0.5f（已 dump 确认，见下）
180071908: callq  0x1800fdb52            ; 取整（round）
18007190d: cvttss2si %xmm0, %eax         ; float -> int（截断）
180071915: retq
```

**读法**：`rp` 值的换算就是 `(int)(value * scaleFactor + 0.5f)`。

我 dump 了 `addss` 引用的常量 `0x180122240`，字节为 `00 00 00 3f` = **`0.5f`**
【实锤，本教程读取 `.rdata`】。因为 `cvttss2si` 是**截断**取整，
先加 `0.5` 就把截断变成了**四舍五入**——这是编译器生成
`(int)(x + 0.5f)` 的标准形态。

缩放因子存在 **`this + 0x5c`**，是个 float，与 ui-mental-model §11
记录的"parser+0x5c 存 scale 因子、disasm 行 139403 有 `mulss 0x5c(%rcx)`"**完全一致**
【实锤，两处独立反汇编互证】。

### 6.2 心智模型

**rp 是在 `CreateElement` / `_ParseValue` 期间一次性算成 px 的。**
之后 Value 里存的就是像素整数，元素树里再也看不到 `rp` 了。

这解释了一个常见困惑：**为什么改 DPI 后要重建 UI**——因为值已经烘焙死了。
运行时 DPI 变化走的是另一条路：`WindowDpiChanged` UID 广播 + 宿主重建
（`HWNDElement::WindowDpiChanged`）【强推，ui-mental-model §11；本教程未独立复现该广播】

因子来源与动态缩放开关：
`IsDynamicScaling` / `SetDynamicScaling` / `SetScaleFactor` / `GetOverrideScaleFactor`
【实锤，符号表】；注册表键 `Software\Microsoft\DirectUI\DynamicScaling`
见 ui-mental-model §11【强推，未独立复现】。

---

## 7. 装配全流程（把上面串起来）

```
SetXMLFromResource(resid, hinst)
  │
  ├─ LoadResource 取 UIFILE 字节
  │
  ├─ IsBufferBinaryDUI(buf,len)?  ── 是 ──> CBinaryXmlReader::Create(buf,len,&reader)
  │                                  └─ 否 ──> CreateXmlReader(text,...)  [xmllite]
  │                                                    │
  │            ┌───────────────────────────────────────┘
  │            ▼
  │   reader->Read() 逐节点            （两者共用 IXmlReader 接口）
  │            │
  │            ├─ StartElement: name ──> _GetClassForElementByName(name, &ci)
  │            │                            ├─ parser+0xb0 扩展表 lookup (vtable+0x18)
  │            │                            └─ 失败 -> 全局表 0x180183088 二分
  │            │                                  （ClassExist / ClassInfoBase）
  │            ├─ ci->Create(...) ──> new Element 子类
  │            │
  │            ├─ 每属性: _GetPropertyForAttribute(name) -> PropertyInfo*
  │            │            _ParseValue(prop, valueText, &v)
  │            │              ├─ FunctionDefinition<T> 分派 (五类)
  │            │              ├─ Parse* 实现（gtc/dtb/resstr/rect/...）
  │            │              └─ rp 缩放: _ScaleRelativePixels(v) * parser[0x5c]
  │            │            element->SetValue(prop, v)
  │            │
  │            ├─ EndElement -> 挂到 parent
  │            └─ 失败 -> SendParseError(0x800403EE, lineInfo)
  │
  └─ 解析完成后 XML 即可丢弃；后续全走 Element 属性系统
```

`0x800403EE` 这个错误码在 `_GetClassForElementByName` 里**明文出现**
（disasm 0x18003496d: `movl $0x800403ee, %edi`）【实锤】——
**标签找不到时就是这个错误**，与 ui-mental-model §6 的记录一致。

---

## 8. 未知问题清单（诚实边界）

1. **`parser+0xb0` 那个对象的真实类型是什么？** 只确认了它有 vtable，
   +0x18 是 lookup、+0x28 是 insert。类名不在 `pinned/symbols.json` 里
   （可能是内部 `ParserCommon` 的无名实现，或纯虚接口）。
   这直接影响"宿主怎么拿注册入口"（`03-host-registered-tags.md` §4 有部分答案）。
2. **表达式函数完整清单未收敛。** §4.1 是"语料用到的" ∪ "符号表 `Parse*` 名字"
   的交集。二进制里可能还有语料未覆盖的函数。`parser_members.txt` 的
   `ParseLiteral` / `ParseMagnitude` / `ParseQuotedString` 等看起来是
   词法层（被函数调用复用），不是顶层函数名。
3. ~~`_ParseValue` 的三次字符串比较具体是哪三个函数名？~~
   **已解决（见 §4.2）**：`themeable` / `valueWithHighContrastFallback` / `composited`。
   但这引出一个新问题：**主题与高对比度状态从哪读？**（`parser+0x78`
   在 `_ParseValue` 里被反复读写，疑似当前 PropertyInfo 或主题上下文，
   未确认。）
4. **`ParseFunction` 的 `ParsedArg` union 布局未知。**
   签名里有 `union DUIXmlParser::ParsedArg*`，但该 union 无独立符号。
5. **duib 与明文在语义上是否 100% 等价？** 结构上同构（§5.2），
   但 duib 的公共串表只有 62 个固定词（README §9），
   是否意味着某些明文写法无法二进制编码？未验证。
6. **`0x800403F1`（`_ParseValue` 里的错误码）与 `0x800403EE` 的区别**未查。
7. ~~`_ScaleRelativePixels` 的 `+0.5` 常量~~ **已解决**：dump `0x180122240`
   得到 `0.5f`（字节 `00 00 00 3f`）【实锤】。所以换算是
   `(int)(v * scale + 0.5f)` —— **标准四舍五入**，且 `cvttss2si` 截断，
   `+0.5` 正是为了把截断变成四舍五入。负面含义：**负的 rp 值会向零取整
   （round-half-up 对负数是 round-half-toward-zero）**，
   `rect(-10rp,...)` 的边界行为需要实测。

---

## 9. 证据索引

| 结论 | 证据 |
|---|---|
| 解析器即工厂、XML 非活文档 | `UITest/UITest.cpp:506-538`【实锤】 |
| DUIXmlParser 154 成员 | `pinned/symbols.json` 按 `class` 过滤【实锤】 |
| CBinaryXmlReader 实现 IXmlReader | 成员表 35 项与 IXmlReader 方法名逐一对齐【实锤】 |
| `IsBufferBinaryDUI` 嗅探 | 符号签名 `(const u8*, u64) -> bool`【实锤】 |
| 两级标签查找 | disasm 0x180034900（`0xb0` + vtable+0x18 / +0x28）【实锤】 |
| 全局表 16 字节项二分 | disasm 0x180036c6c（`shlq $0x4`, `idivl`）【实锤】 |
| `ClassExist` 导出且被第三方导入 | `pinned/exports.json` ord 1044 + objdump 导入表【实锤】 |
| 注册级联顺序 | disasm 0x180008c60 + 符号表【实锤】 |
| `ClassInfo<T,B,C>::Register` 复用 ClassExist | disasm 0x180005348【实锤】 |
| 查找比较用 `_wcsicmp`（大小写不敏感） | 本教程解析 PE 导入表：`0x119C10 -> msvcrt!_wcsicmp`【实锤】 |
| 注册路径有临界区锁 | `0x119988/0x119980 -> Enter/LeaveCriticalSection`【实锤】 |
| `_ParseValue` 特判的三个名字 | 本教程 dump `.rdata`：`themeable`/`valueWithHighContrastFallback`/`composited`【实锤】 |
| rp 换算里的 `+0.5f` | 本教程 dump `.rdata` `0x180122240` = `00 00 00 3f`【实锤】 |
| `DuiCreateObject` 同表二分 | ui-mental-model §6（disasm 行 9651）【实锤】 |
| Parse* ↔ 语料函数对应 | 符号表 RVA + 语料 README §5【实锤】 |
| 函数名在二进制里的存在性 | 本教程 UTF-16 检索【实锤】 |
| rp 换算 = round(v × parser[0x5c]) | disasm 0x1800718f0【实锤】 |
| 值解析期烘焙 | disasm 形态 + `CreateElement` 时序【强推】 |
| 错误码 0x800403EE | disasm 0x18003496d【实锤】 |

**复现脚本**（本次调查产出，工作区文件非交付物）：
`.local/build/p3-parser/` 下 `disasm_key.py`（两级查找）、`disasm_parse.py`
（`_ParseValue` / `_ScaleRelativePixels`）、`strings.py`（函数名检索）、
`members_full.txt`（全部成员表）。

**相关材料**：
- `pinned/symbols.json`、`pinned/classes.json` — 符号与类体系
- `docs/duixml-corpus/README.md` — 语料语法总结（§5 值表达式、§9 duib 格式）
- `.local/corpus/duib2xml.py` — duib 解码器（解析器语义的活文档）
- `.local/audit/ui-mental-model-outline.md` §6 — 声明式 vs 命令式双轨
- 后续教程：《Value 类型系统》（属性字符串 → Value 的映射表）、
  《宿主注册标签》（`ClassExist` 的调用契约）
