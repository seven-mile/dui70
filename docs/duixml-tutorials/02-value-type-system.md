# Value 类型系统：duixml 的动态类型

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 目标：搞清 `Value` 是什么、XML 属性字符串怎么变成 `Value`、
> `rp` 单位为什么"烘死"在值里，以及 `<macro>` / `<bind>` 到底解决了什么问题。
>
> 证据分级：【实锤】/【强推】/【猜想】，规则同`01-duixmlparser-xml-to-element-tree.md`。
> RVA 均相对 `dui70.dll` 基址 0x180000000。

---

## 1. 为什么需要 Value：属性系统没有统一类型

`Element` 有几百个属性（`Schema` 类里有 **173 个**符号【实锤，符号表】），
每个属性的类型都不一样：`int` / `bool` / `wchar_t*` / `RECT` / `SIZE` /
`COLORREF` / `IFill*` / `IGraphic*` / `ILayout*` / 甚至另一个 `Element*`。

C++ 里要在一个 `SetValue(PropertyInfo*, ???)` 里塞下这些，只有两条路：
模板（每个属性一套签名）或**统一的动态类型容器**。DirectUI 选了后者——就是 `Value`。

**所以 `Value` = DirectUI 属性系统的 `VARIANT`**，但比 VARIANT 更严格：
它带 **引用计数**、**类型标签**、**相等比较**，且**不可变**
（`Create*` 之后只能读，改就造新的）【强推：`Create*` 全是 static 返回 `Value*`，
没有 `SetInt`/`SetString` 之类的就地修改方法，符号表可证】。

### 1.1 引用计数

`Value` 有完整的引用计数三件套【实锤，符号表】：

```
AddRef          0x0004ECE0        Release         0x00024600
GetRefCount     0x0009D500        _ZeroRelease    0x00024640
```

外加三个数据常量：

```
c_RefCountBitOffset   0x00125380
c_RefCountMask        0x00125378
c_SingleRefCount      0x0012537C
```

【实锤，符号表】这三个常量说明**引用计数被压进位图**，不是独立字段。
`c_RefCountMask` + `c_RefCountBitOffset` 的组合是"位域提取"的典型形态。

**给开发者的实用含义**：`Create*` 返回的 `Value*` 你**拥有一个引用**，
用完必须 `Release()`。在 `ResolveBindings` 的反汇编里能看到这个模式被严格遵守
（见 §5.3，每个 `Get*` 后面都跟一个 `Release`）【实锤】。

### 1.2 单例零值：避免频繁分配

`Value` 有一大堆 `Get*Zero` / `Get*Null` 静态单例【实锤，符号表】：

| 类别 | 单例 |
|---|---|
| 布尔 | `GetBoolTrue` `GetBoolFalse` |
| 整数 | `GetIntZero` `GetIntMinusOne` |
| 浮点 | `GetFloatZero` `GetFloatOne` |
| 几何 | `GetPointZero` `GetRectZero` `GetSizeZero` |
| 原子 | `GetAtomZero` |
| 颜色 | `GetColorTrans`（透明） |
| 空指针 | `GetNull` `GetExprNull` `GetSheetNull` `GetElementNull` `GetElListNull` |
| 其它 | `GetDblListEmpty` `GetLayoutNull` `GetCursorNull` `GetStringNull` `GetStringRPNull` `GetUnavailable` `GetUnset` |

**为什么这个细节重要**：`GetUnset` 和 `GetUnavailable` 是两个不同的单例，
说明属性状态机至少是三态：**已设置 / 未设置 / 不可用**
（`Unset` = 宿主还没给值，`Unavailable` = 这个属性在这个元素上不适用）
【强推，命名 + 两个独立单例的存在；未见文档描述该状态机】。

---

## 2. Value 的 110 个成员：完整类型表

`pinned/symbols.json` 里 `Value` 有 **110** 个成员【实锤，符号表】。
按"造什么类型"归类，`Create*` 共 **26 个不同名字**（含重载共 38 个符号）：

| Create 工厂 | 类型 | 参数签名（去重后） | RVA |
|---|---|---|---|
| `CreateBool` | bool | `(bool)` | 0x65AC0 |
| `CreateInt` | int | `(int, DynamicScaleValue)` | 0x16770 |
| `CreateFloat` | float | `(float, DynamicScaleValue)` | 0x96B00 |
| `CreateAtom` | ATOM | `(const wchar_t*)` / `(ATOM)` | 0x3DA90 / 0x14080 |
| `CreateString` | string | `(const wchar_t*)` | 0x15210 |
| `CreateStringRP` | string (rp) | `(const wchar_t*)` | 0x156A0 |
| `CreateEncodedString` | string (编码) | — | 0x93950 |
| `CreateColor` | COLORREF | `(unsigned long)` / `(ARGB)` / … | 0x216C0 / 0xB0F10 / 0x7A860 |
| `CreatePoint` | POINT | `(int, int, DynamicScaleValue)` | 0x38CB0 |
| `CreateRect` | RECT | `(int,int,int,int, DynamicScaleValue)` | 0x0F460 |
| `CreateSize` | SIZE | `(int, int, DynamicScaleValue)` | 0x16840 |
| `CreateLayout` | ILayout* | — | 0x614E0 |
| `CreateCursor` | HCURSOR | — | 0x73EF0 / 0xB0F80 |
| `CreateFill` | IFill* | — | 0xB1000 |
| `CreateDTBFill` | 主题背景 | — | 0x144C0 |
| `CreateDFCFill` | 默认前景 | — | 0x88B70 |
| `CreateGraphic` | IGraphic* | **7 个重载** | 0x695C0/0xB10A0/0x78470/0xB1220/0x694E0/0x535E0/0x53820 |
| `CreateIconGraphicHelper` | 图标图形 | — | 0x53980 |
| `CreateStyleSheet` | StyleSheet* | — | 0x37870 |
| `CreateExpression` | Expression* | — | 0xB0FB0 |
| `CreateElementRef` | Element* | — | 0x3C140 |
| `CreateElementScaledValue` | Element 缩放值 | `(Element*, Value*)` | 0x23490 |
| `CreateScaledValue` | 缩放值 | — | 0x16420 |
| `CreateValueList` | 值列表 | `(...)` | 0xB1470 |
| `CreateDoubleList` | double 列表 | `(...)` | 0x58800 |
| `CreateElementList` | Element* 列表 | — | 0x3C190（模板） |

【实锤，符号表 + 签名】

### 2.1 关键观察一：`DynamicScaleValue` 出现在所有几何/数值工厂上

`CreateInt` / `CreateFloat` / `CreatePoint` / `CreateRect` / `CreateSize`
五个工厂的签名末尾都有 `enum DynamicScaleValue`【实锤，符号签名】：

```cpp
static Value* Value::CreateInt  (int, enum DynamicScaleValue);
static Value* Value::CreateFloat(float, enum DynamicScaleValue);
static Value* Value::CreatePoint(int, int, enum DynamicScaleValue);
static Value* Value::CreateRect (int, int, int, int, enum DynamicScaleValue);
static Value* Value::CreateSize (int, int, enum DynamicScaleValue);
```

**这是 rp 烘焙的落点**。解析器算完 `_ScaleRelativePixels` 之后，
把"这个值是怎么来的"（相对像素 / 绝对像素 / 点）作为一个 enum 一起存进 `Value`
——因为运行时 DPI 变化时需要知道**哪些值该重算、哪些不该**
（`Value::IsDynamicScaled` / `GetScaledInt` / `GetScaledRect` /
`GetElementScaledInt/Rect/Size/Float/Point` 这一整族方法的存在，
正是为了这个目的）【强推：方法族命名 + `DynamicScaleValue` 参数自洽；
`enum` 的具体成员名未知，见 §7】。

### 2.2 关键观察二：`CreateGraphic` 有 7 个重载

`CreateGraphic` 是唯一有大量重载的工厂（7 个符号）【实锤】。
其中一个签名能看清：

```cpp
static Value* Value::CreateGraphic(const wchar_t* name, struct ScaledSIZE size,
                                   HINSTANCE module, bool, bool);
```

【实锤，符号签名】—— `(名字, 尺寸, 模块, ...)` 说明它负责
**从资源加载图像**，`HINSTANCE` 决定去哪个 DLL 找。
这与语料里 `background="themeable(dtb(...),...)"` / `<element .../>` 上挂图
的用法吻合。`Macro::_LoadImage32BitsPerPixel`（RVA 0xDAE90）
是它的资源加载辅助【实锤，符号表】。

### 2.3 `Get*` 家族：57 个名字，含"安全读取"重载

`Get*` 有 57 个不同名字【实锤】。重点看几何类型的**双重读取**：

```
GetRect    / GetScaledRect    / GetElementScaledRect
GetSize    / GetScaledSize    / GetElementScaledSize
GetPoint   / GetScaledPoint   / GetElementScaledPoint
GetInt     / GetScaledInt     / GetElementScaledInt
GetFloat   / GetScaledFloat   / GetElementScaledFloat
```

【实锤，符号表】三层含义：
1. **裸值**（`GetRect`）—— 存进去是什么就是什么；
2. **缩放后**（`GetScaledRect`）—— 按当前 DPI 因子换算；
3. **元素上下文缩放**（`GetElementScaledRect`）—— 还要考虑**该元素所在窗口**的 DPI
   （注意它的签名里有 `Element*`）。

**这就是 `DynamicScaleValue` 存在的理由**：没有它，无法区分
"这个 `rect` 用户写的是 `10rp`（该缩放）还是 `10`（不该缩放）"。
【强推，推断链：`Create*` 收 `DynamicScaleValue` → `Get*` 分三档读取 → 语义自洽】

---

## 3. XML 属性字符串 → Value 的完整映射

这是本教程最实用的表。左侧是你在 XML 里写的东西，右侧是解析器和落点。

### 3.1 字面量

| XML 写法 | 例子（语料） | 落点 |
|---|---|---|
| 十进制整数 | `layoutpos="top"`（枚举名） | `ParseIntValue` → `CreateInt` |
| 带 `rp` | `margin="rect(0rp,15rp,0rp,0rp)"` | 先缩放再 `CreateInt`(rp) |
| 带 `pt` | （少数） | `_ScalePointsToPixels` |
| `true`/`false` | `selected="false"` | `CreateBool` |
| 裸字符串 | `class="menupage"` | `CreateString` |
| 枚举名 | `active="mouse\|keyboard\|pointer"` | 按位或的 `CreateInt` |

【实锤，语料 + 符号表】

### 3.2 函数式（表达式）

| XML 写法 | 语料次数 | 解析器 | Value 落点 |
|---|---|---|---|
| `resstr(id)` | 3338 | `ParseResStr` | `CreateString`（本地化后） |
| `atom(name)` | 4082 | `ParseAtomValue` | `CreateAtom` |
| `rect(l,t,r,b)` | 3338 | `ParseRectRect` | `CreateRect` |
| `size(w,h)` | 141 | `ParseSizeSize` | `CreateSize` |
| `rgb(r,g,b)` | 200 | `ParseRGBColor` | `CreateColor` |
| `argb(a,r,g,b)` | 358 | `ParseARGBColor` | `CreateColor` |
| `dtb(class,part,state)` | 1289 | `ParseDTBFill` | `CreateDTBFill` |
| `gtc(class,part,state,prop)` | 1716 | `ParseGTCColor` | `CreateColor` |
| `gtf(...)` | 1667 | `ParseGTFStr` | `CreateString`（字体串） |
| `themeable(a,b)` | 1341 | `_ParseValue` 特判 | 运行时二选一 |
| `library(dll)` | 524 | `ParseLibrary` | 模块上下文 |
| `sysmetric(n)` | 345 | `ParseSysMetricInt/Str` | int 或 string |
| `gtmar()` | 34 | `ParseGTMarRect` | `CreateRect` |
| `gtps()` | 2 | `ParseGTPartSize` | `CreateSize` |
| `ressheet(...)` | 53 | `ParseStyleSheets` | `CreateStyleSheet` |

【实锤，语料频次 + 符号表 RVA】

### 3.3 `themeable` 的真相（`01-duixmlparser-xml-to-element-tree.md` §4.2 的结论，这里展开）

`_ParseValue` 一上来就特判三个名字【实锤，disasm 0x180011ca0 + dump `.rdata`】：

```
0x18011f780 -> 'themeable'
0x18011f798 -> 'valueWithHighContrastFallback'
0x18011f7d8 -> 'composited'
```

`themeable(主值, 回退值)` 的语义是：**指出一个主值和一个回退值**，
让运行时根据主题 / 高对比度状态决定用哪个。

**教学意义**：这是唯一一类"解析期不能定值"的表达式。
普通 `dtb(...)` 在解析期就查主题表定死了；
`themeable()` 必须把**两个候选**都保存下来，等主题变化时重选。

**实用建议**：写自定义控件时，凡是用主题色的地方都应包 `themeable`
并提供可读的回退值，否则高对比度模式下会看不见东西。
语料里 1341 次 `themeable` 与 1289 次 `dtb` 几乎 1:1 配对，就是这个原因
【实锤，两数高度接近是强信号】。

---

## 4. `<macro>` 模板机制：199 次使用

### 4.1 语料现状

我对 149 个 XML 做了精确统计【实锤，`.local/build/p3-parser/counts2.py`】：

| 模式 | 次数 |
|---|---|
| `<macro ...>` | **199** |
| `<bind ...>` | **140** |
| `expand=` 属性 | **231** |
| `connect=` 属性 | **140** |
| `attach=` 属性 | **275** |
| `<repeater ...>` | **5** |

`<bind>` 分布极集中：**只有 28 个文件出现**，其中
`hgcpl/UIFILE_202.xml` 占 36 次，`SpaceControl` 系列占 **66** 次
（每个资源 3–6 次），`autoplay/UIFILE_101.xml` 8 次。

**`<bind>` 总数恰好等于 `connect=` 总数（140）**，说明每个 `<bind>`
都带且只带一个 `connect=`，没有例外【实锤】。

### 4.2 expand 不是预处理，是**运行时元素展开**

关键区分：

- `expand="macroName"` **不是你想象的 C 宏文本替换**。
- `Macro` 是一个**真正的 Element 子类**（有 `Register`、
  `s_pClassInfo`、`BuildElement`、`vftable`）【实锤，符号表】。
- `ClassInfo<Macro, Element, StandardCreator<Macro>>::Register`【实锤】——

所以 `<macro expand="X">` 的流程是：

```
解析期：遇到 <macro expand="X">
          -> 创建 Macro 元素实例（ExpandProp 属性接住 "X"）
          -> 读当前元素身上的同名 attribute X 的值
运行期：Macro::BuildElement() 构造实际的子元素
          -> Macro::ResolveBindings() 把 <bind> 里的值填进去
```

`Macro` 的成员签名印证【实锤】：

```cpp
static const PropertyInfo* Macro::ExpandProp();      // "expand" 属性的元信息
long                        Macro::SetExpand(const wchar_t*);
const wchar_t*              Macro::GetExpand(Value**);
long                        Macro::BuildElement();     // 造子元素
void                        Macro::ResolveBindings();  // ← 见 §5
static long                 Macro::Create(Element*, unsigned long*, Element**);
```

### 4.3 `expand` 的实际写法：属性传递

`autoplay/UIFILE_101.xml` 的真实用法【实锤，语料原文】：

```xml
<!-- 定义处：一个可复用的模板，里面的 <bind> 是占位符 -->
<element id="atom(storageDeviceHandlerSettings)" layoutpos="top"
         layout="borderlayout()" margin="rect(0rp,25rp,0rp,25rp)">
  <macro expand="macroLineDivider">
    <bind connect="title" content="resstr(1117)" id="atom(StorageDevicesTitle)"/>
  </macro>
  <VolumeHandlerSetting ContentType="CT_STORAGE" expand="macroHandlerSetting"/>
</element>
```

**注意**：这里的 `expand="macroLineDivider"` 引用的模板
**不一定在这个文件里定义**——它可能在**另一个资源**、甚至**另一个 DLL**
（`Macro::SetParser` 的存在说明 Macro 持有解析器引用，
可以回到解析器去查别的资源）【强推：`SetParser(DUIXmlParser*)` 签名 + `Macro` 是 Element 子类】。

`VolumeHandlerSetting ContentType="CT_STORAGE" expand="macroHandlerSetting"`
展示了核心用法：**`ContentType` 是模板的参数，模板通过 `expand` 取用**。
这是 DirectUI 版的"模板 + 具名参数"。

### 4.4 三种"宏"的辨析（容易混淆）

| XML 写法 | 是什么 | 机制 |
|---|---|---|
| `<macro expand="X">` | **Macro 元素**（模板实例化） | `Macro` 类，运行期 `BuildElement` |
| `<element .../>` 上的 `expand="X"` | 该元素**也是** Macro | 同上，只是写法合并 |
| `attach="{Dll!Function}"` | **宿主工厂回调** | 275 次，见`03-host-registered-tags.md` |

【实锤，语料 + 符号表】`attach=` 275 次与 `expand=` 231 次是**两套独立机制**，
前者跨 DLL 调宿主函数，后者是纯 XML 内的模板。

---

## 5. `<bind>` 与 `ResolveBindings`：断言的真相

### 5.1 先给结论（可能出乎意料）

**duixml 没有通用数据绑定引擎。**

`<bind>` 不是 WPF 的 `{Binding Path=...}`。它是一个**极窄的机制**：
把宿主提供的 `IDataEntry` 里的某个"连接名"对应的值，
**一次性**拷进某个元素的属性。

没有：
- 绑定表达式 / 路径语法（没有 `{Binding X.Y.Z}`）
- 双向绑定（没有 `Mode=TwoWay`）
- 变更通知驱动的刷新（`IDataEngine` 抽象接口在 dui70 里**只有 vftable，
  实现在宿主 DLL**）【实锤，符号表：`IDataEngine` / `IDataEntry` 只有抽象虚函数】

**所有 140 个 `<bind>` 无一例外都在 `<macro>` 或 `<repeater>` 内部**
——我用括号深度扫描验证了这一点，**零例外**【实锤，`counts2.py`】。

### 5.2 `ResolveBindings` 的真实行为（反汇编）

`Macro::ResolveBindings`（**RVA 0x85270**，150 条指令）【实锤，disasm 0x180085270】：

```asm
; rcx = this (Macro*)，rdi 保存 this
18008528a: cmpl   %r15d, 0xe0(%rcx)         ; ★ this+0xe0 == 0 ? -> 没事可做，返回
180085291: je     <返回>
180085297: movq   0xc8(%rcx), %rcx          ; ★ this+0xc8 = 数据源（IDataEntry*）
18008529e: testq  %rcx, %rcx
1800852a1: je     <返回>                     ; ★ 没有数据源 -> 直接返回
1800852af: callq  0x1800238c0               ; Element::GetChildren(&vals)
...
; 遍历每个子元素
1800852db: testl  $0x10000000, (%r12)       ; ★ 检查 DynamicArray 的 heap 标志
1800852ed: movq   (%r14,%r13), %r14         ; child = children[i]
1800852f1: movq   0x180184b98(%rip), %rbx   ; ★ rbx = s_pClassInfo@Bind（全局）
1800852f8: movq   %r14, %rcx
1800852fb: movq   (%r14), %rax              ; vtable
1800852fe: movq   0x118(%rax), %rax         ; ★ vtable+0x118 = GetClassInfoW
180085305: callq  0x1800ff010
18008530a: cmpq   %rbx, %rax                ; ★ 这个 child 是 Bind 吗？
18008530d: jne    0x180085564               ; 不是 -> 下一个
18008531e: callq  0x1800b80d0               ; ★ Bind::GetConnect(&v)
180085323: movq   %rax, %rcx
180085326: callq  *0x94203(%rip)            ; ★ 0x180119530 = FindAtomW（已解析 IAT!）
180085336: movzwl %ax, %ebx                 ; 连接名 -> ATOM
180085339: callq  0x180024600               ; Value::Release(GetConnect 的输出)
180085344: callq  0x180023420               ; ★ Element::FindDescendent(ATOM)
180085349: testq  %rax, %rax
18008534f: je     <没找到，跳过>
```

**这段代码把机制暴露得干干净净**：

1. **`this+0xc8` 是数据源**。为空则整个函数直接返回——**没有数据源就没有绑定**。
2. **遍历子元素，用 `vtable+0x118`（`GetClassInfoW`）比对 `s_pClassInfo@Bind`**
   来识别 Bind 元素——不是 `dynamic_cast`，是**手写的类身份比较**。
3. **`<bind connect="X">` 的 `X` 被 `FindAtomW` 转成 ATOM**（`0x180119530`
   经我解析导入表确认是 `api-ms-win-core-atoms-l1-1-0.dll!FindAtomW`）【实锤】。
4. **用这个 ATOM 去 `Element::FindDescendent(ATOM)` 找一个真实元素**。

**第 4 步是理解 `<bind>` 的钥匙**：

```xml
<bind connect="title" content="resstr(1117)"/>
```

读作：**"在模板展开出的子树里，找 `id="atom(title)"` 的那个元素，
把 `content` 设成 `resstr(1117)`"**。

`connect` 指的不是"数据源字段名"，而是**目标元素的 id atom**！
这跟 WPF 的绑定语义完全不同。

### 5.3 值的写入路径（反汇编续）

```asm
18008535d: movq   %r14, %rcx
180085360: cmpq   %r15, 0xd0(%rdi)          ; ★ this+0xd0 = DataEntry 提供者
180085367: je     0x1800854a8               ; 空 -> 特殊分支
18008536d: callq  0x1800b8520               ; ★ Bind::GetProperty(&v) -> "property" 属性
180085372: movq   0x48(%rbp), %rcx
180085376: movq   %rax, %rsi                ; rsi = 属性名字符串
180085379: callq  0x180024600               ; Value::Release
18008537e: testq  %rsi, %rsi
180085381: je     <没有 property，跳过>
180085387: movq   0xd0(%rdi), %rcx          ; ★ this+0xd0 = 数据源对象
18008539e: movq   (%rcx), %rdx
1800853a1: movq   0x8(%rdx), %rax           ; ★ vtable[1] = IDataEntry 的方法
1800853a5: movq   %rsi, %rdx                 ; 参数 = 属性名
1800853a8: callq  0x1800ff010               ; 取数据源的值
1800853ad: testl  %eax, %eax
1800853af: js     <失败分支>
1800853b5: cmpb   %r15b, 0x48(%rbp)         ; 检查是否"是图片"
1800853bf: cmpb   $0x1, 0xe4(%rdi)          ; ★ this+0xe4 = 图像模式标志
1800853c6: jne    <非图片分支>
1800853c8: cmpb   %r15b, 0xe5(%rdi)         ; ★ this+0xe5 = 另一标志
1800853cf: je     <跳过加载>
1800853d1: movq   0x50(%rbp), %rcx
1800853d8: callq  0x1800dae90               ; ★ Macro::_LoadImage32BitsPerPixel
180085427: ...                               ; -> CreateGraphic
18008543d: leaq   0x180106e20(%rip), %rdx   ; ★ s_fdGraphic + 0xe0
180085447: callq  0x180022c20               ; ★ Element::_SetValue(prop, ...)
18008544c: callq  0x180024600               ; Value::Release
```

**读法**：拿到属性名后，调 `this+0xd0` 对象的 **vtable[1]** 去取值
（这就是 `IDataEntry` 的纯虚方法），然后：
- 如果是图片类属性（`this+0xe4` / `+0xe5` 标志），走
  `_LoadImage32BitsPerPixel` → `CreateGraphic` → `_SetValue`；
- 否则直接把取到的值 `_SetValue` 写进目标元素。

最后都 `Release()`——**引用计数被严格遵守**【实锤】。

### 5.4 为什么 `<bind>` 只在模板里

因为 `ResolveBindings` 依赖三样东西，只有模板场景才同时具备【实锤，反汇编 + 语料】：

1. **数据源**（`this+0xc8` / `this+0xd0`）——由宿主通过
   `Repeater::SetDataEngine(IDataEngine*)` 或 `Macro::SetDataEntry(IDataEntry*, Element*)`
   注入。签名【实锤】：
   ```cpp
   void Repeater::SetDataEngine(IDataEngine*);
   void Macro::SetDataEntry(IDataEntry*, Element*);
   ```
2. **一个 id atom 命名的目标元素**（`connect` 的值）
3. **一个属性名**（`property` 的值，可选）

**关键结论**：`<bind>` 的 `connect` 属性叫"connect"，
但它的**值是一个元素的 id atom**，不是数据源字段名。
数据源字段名走的是 `property` 属性。

> 我把这一点标为【强推】而非【实锤】：反汇编清楚显示
> `GetConnect` 的结果被送进 `FindAtomW` 再送进 `FindDescendent`（实锤），
> 而 `GetProperty` 的结果被送给 `this+0xd0` 的 vtable[1]（实锤）。
> 但 `this+0xd0` 那个对象的**确切类型**只是从
> `Macro::SetDataEntry(IDataEntry*, Element*)` 推出来的。

### 5.5 诚实结论：`<bind>` 是个窄机制

给应用开发者的实话：

- **想要真数据绑定（双向、路径、通知），duixml 不提供。**
  你得自己实现 `IDataEngine` / `IDataEntry`，宿主**主动推**数据。
- `<bind>` 能做的只是"从 `IDataEntry` 拉一个值，塞进一个属性，一次性"。
- 140 次的使用量（相对 149 个 XML、总共几万个属性）说明
  **连微软自己都很少用它**。主流做法是 `attach=`（275 次）
  + 宿主在 C++ 代码里直接 `SetValue`。

数据流方向是**单向的：宿主推 → 模板拉**，没有反向通道。
`IDataEngine` / `IDataEntry` 在 `dui70` 里只有抽象 vftable【实锤，符号表】，
实现在宿主 DLL——**binding 的智能全在宿主，框架只提供"插槽"**。

---

## 6. 真实例子：一个完整的宏+绑定

来源：`%SYSTEMROOT%\System32\autoplay.dll`，资源 `UIFILE/101`
【实锤，`docs/duixml-corpus/autoplay/UIFILE_101.xml` 第 21-24 行】

```xml
<macro expand="macroLineDivider">
  <bind connect="title" content="resstr(1117)" id="atom(StorageDevicesTitle)"/>
</macro>
<VolumeHandlerSetting ContentType="CT_STORAGE" expand="macroHandlerSetting"/>
```

逐 token 解析：

| token | 机制 | 落点 |
|---|---|---|
| `<macro expand="macroLineDivider">` | `Macro` 元素，`ExpandProp` 接住名字 | `Macro::SetExpand` |
| `<bind connect="title" .../>` | `Bind` 元素 | `ClassInfo<Bind,...>::Register` |
| `connect="title"` | → `FindAtomW("title")` | `Element::FindDescendent(atom)` |
| `content="resstr(1117)"` | → `ParseResStr` | `Value::CreateString`（本地化串） |
| `id="atom(StorageDevicesTitle)"` | → `ParseAtomValue` | `Value::CreateAtom` |
| `VolumeHandlerSetting ... expand=` | 另一个 Macro 实例 | `ContentType` 作为模板参数 |

**注意**：`<bind>` 自己也有 `id`（`atom(StorageDevicesTitle)`），
而 `connect` 指的是**别的**元素的 id。两个 id 在同一个标签上容易看混。

`hgcpl/UIFILE_202.xml` 是最重的用例（36 次 `<bind>`），形态是一批
`<macro expand="...">` 包着若干 `<bind connect="Title/Caption/Button0..."/>`
——典型的"一个设置页模板，绑多个本地化串"【实锤，语料原文】。

### 6.1 对照：fvecpl 的 `volumeInfo`（outline §10 的标本）

`fvecpl/UIFILE_110.xml` 5 次 `<bind>`，是 `<repeater>` 场景
（`Repeater::SetDataEngine` + `IDataEngine`）【实锤，语料；机制同 §5】。
`fvecpl` = BitLocker 加密向导，它的卷列表用 repeater 渲染，
每行靠 bind 填字段——这是 `<bind>` **唯一说得通**的用例：**列表重复渲染**。

---

## 7. 未知问题清单

1. **`enum DynamicScaleValue` 的成员名和取值全部未知。**
   只从签名知道它存在。猜测是 {绝对像素, 相对像素(rp), 点(pt)} 三类，
   但**没有任何直接证据**。这直接影响 `Value::IsDynamicScaled` 的行为。
   （未解决）
2. **`Value` 的类型标签字段在哪、有几个 tag 值？**
   `_ParseValue` 里出现过 `cmpl $0x2, (%rbx)`（节点类型判断），
   但那是 `ParserTools::ExprNode` 的类型，**不是** `Value` 的 tag。
   `Value::GetType`（RVA 0x4ED10）返回什么枚举、有几个值，未查。
3. **`this+0xc8` / `this+0xd0` / `this+0xe0` / `this+0xe4` / `this+0xe5`
   在 `Macro` 里到底是什么字段？** 我从用法推断是
   `pDataEntry` / `pDataProvider` / 若干标志位，但**没有权威依据**。
   `Macro` 的对象布局从未被记录。
4. **`GetUnset` vs `GetUnavailable` 的状态机语义**未验证。
   两个单例的存在是实锤，但"什么时候用哪个"是猜想。
5. **`<bind>` 的 `property` 属性在语料里 0 次使用。**
   140 个 `<bind>` 全部只带 `connect` + `content`。
   反汇编里 `GetProperty` 的路径存在（实锤），但**语料从未走过**。
   所以"property 怎么用"我只能说：**从代码看它存在，但没有任何真实用例**。
6. **`Macro::ResolveBindings` 里 `this+0xe4` / `this+0xe5` 两个图像标志的
   触发条件不明**（疑似 `SetDefaultGraphicType` 设置，
   该方法签名 `(unsigned char, bool)`【实锤】）。
7. **`themeable` 的运行时主题监听机制未知。**
   解析期存下两个候选是实锤（特判 + 语料配对），但
   "主题变化时谁通知、怎么重选"完全没查。`composited` 的语义也未知。
8. **`Value` 的相等比较 `IsEqual`（RVA 0x24DF0）语义未知**：
   `CreateInt(5)` 与 `CreateFloat(5.0f)` 相等吗？跨类型比较规则没查。
9. **`CreateStringRP`（RP = Relative Path? Resource Path?）语义未知。**
   语料里 `resstr` 用得多，但看不出哪个属性会产生 RP 字符串。

---

## 8. 证据索引

| 结论 | 证据 |
|---|---|
| Value = 引用计数动态类型容器 | 110 成员表 + `AddRef`/`Release`/`c_RefCount*`【实锤】 |
| 26 个 `Create*` 类型 | `pinned/symbols.json` 按 `class=Value` 过滤【实锤】 |
| `DynamicScaleValue` 参数 | `CreateInt/Float/Point/Rect/Size` 签名【实锤】 |
| `Get*` 三层读取 | 57 个 `Get*` 名字中的 `Get/GetScaled/GetElementScaled` 三档【实锤】 |
| `themeable` 三特判 | disasm 0x180011ca0 + dump `.rdata`【实锤】 |
| `<macro>` 199 次 / `<bind>` 140 次 / 零例外嵌套 | `counts2.py` 括号深度扫描【实锤】 |
| `ResolveBindings` 用 vtable+0x118 识别 Bind | disasm 0x1800852f1-0x18008530d【实锤】 |
| `connect` → `FindAtomW` → `FindDescendent` | disasm 0x180085326 + PE 导入表解析【实锤】 |
| `property` → `this+0xd0` vtable[1] | disasm 0x180085387-0x1800853a8【实锤】 |
| 图片分支走 `_LoadImage32BitsPerPixel`→`CreateGraphic` | disasm 0x1800853d8-0x180085422【实锤】 |
| 无通用绑定引擎 / 宿主实现 IDataEngine | `IDataEngine`/`IDataEntry` 只有抽象符号【实锤】 |
| 数据单向（宿主推、模板拉） | `SetDataEngine`/`SetDataEntry` 签名 + 上面反汇编【强推】 |

**复现脚本**：`.local/build/p3-parser/` 下 `fd_tables.py`（`s_fd*` 与 Macro/Bind 成员）、
`counts2.py`（语料精确统计+嵌套验证）、`dis_bind.py`（`ResolveBindings`）、
`imports_map.py`（PE 导入表 → `FindAtomW`/`_wcsicmp`）、`value_types.py`（Create/Get 分类）。

**相关材料**：
- `01-duixmlparser-xml-to-element-tree.md`《duixml 是怎么被吃进去的》——解析流程与 two-level lookup
- `03-host-registered-tags.md`《宿主注册标签》——`attach=` 与宿主工厂回调
- `.local/audit/ui-mental-model-outline.md` §10（数据绑定现状）、§11（rp 缩放）
- `docs/duixml-corpus/README.md` §5（值表达式统计）
