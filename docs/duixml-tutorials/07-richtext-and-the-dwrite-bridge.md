# RichText 与 DWrite 桥:DirectUI 的富文本引擎

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 目标:搞清 `<RichText>` 背后那台 **DWrite 富文本引擎**怎么运转——
> DWrite 的 COM 对象模型(factory / TextFormat / TextLayout / TextRenderer)
> 是怎么嵌进 Element 生命周期的:布局协商、渲染路径、资源释放三阶段,
> 以及 Run 系统、typography、路径省略号这些"富文本专属"行为的底层实现。
>
> 证据分级:【实锤】(反汇编/语料原文/可运行验证)/【强推】(符号+继承自洽推断)/【猜想】(写成未知问题)。
> RVA 相对 dui70.dll 基址(x64 系统 DLL ImageBase = 0x180000000);
> 反汇编行号指 `.local/build/p2-text/` 下的工作文件。

---

## 0. 结论速览

1. **RichText 是 DirectUI 的文本绝对主力**:语料 149 个 XML 里 `<RichText>` 出现
   **495 次、横跨 33 个 DLL**(InputSwitch 96 次、WebcamUi 56、wscapi 56、
   phoneactivate 43、PicturePassword 41、dui70 自己 30 次)【实锤,全语料扫描】。
   同期 `<PText>` 78 次且几乎全部躺在样式表里(见`08-ptext-and-the-old-text-era.md`),
   `<TextGraphic>` **零次**——文本世界已经完全被 RichText 接管。
2. **RichText 类 = 91 个符号**(67 方法 + 19 静态 + 构造/析构/虚表/静态数据),
   背后还拖着一个引擎家族:GdiTextRenderer(19)、RichTextShared(13)、
   RichTextCache(22)、RichTextCacheEntry(5)——合计 156 个符号【实锤,symbols.json】。
3. **"半数方法是 DWrite 互操作"名不虚传**:`_CreateDWriteLayout`、
   `_EnsureTextFormat`、`_SetTypographyRun`、`_SetFontColorRun`、
   `_SetFontSizeRun`、`_SetFontWeightRun`、`GetVerticalScript`、
   `_EnsureDWriteLoaded`……每个都直接调用 IDWrite* 虚表槽位
   (本文 §3-§5 逐个给出反汇编行号)。
4. **双引擎并存**:Element 基类保留了 GDI 文本路径
   (`Element::PaintStringContent` 走 ExtTextOutW/DrawTextW),
   RichText **同时覆盖了 `Paint` 和 `GetContentSize` 两个虚表槽**
   (vtable slot 14/15),把文本测量和渲染整体换成 DWrite
   【实锤,RichText/PText/TextGraphic 三张虚表对比】。
5. dui70 **不静态导入 dwrite.dll**——它在第一次需要时
   `LoadLibraryW("dwrite.dll") + GetProcAddress("DWriteCreateFactory")`
   手动加载,并以 **IDWriteFactory2** 起步【实锤,§2.1】。

---

## 1. 语料里的 RichText:从最简到最富

### 1.1 最简实例(15 行,WindowsActionDialog)

`docs/duixml-corpus/WindowsActionDialog/UIFILE_201.xml` 全文:

```xml
<duixml>
<RichText resid="PlatformRoot" id="atom(ModalDialogElement)"
          accessible="true" contentalign="endellipsis|wrapleft" sheet="DialogStyle"/>
<stylesheets>
  <style resid="DialogStyle">
    <RichText font="resstr(1004)"/>
  </style>
</stylesheets>
</duixml>
```

一个根元素 + 一个样式规则,就撑起一个对话框。注意两件事:
- `font="resstr(1004)"`——**字体本身是资源字符串**
  (`resstr(id[, library(x)])` 由 `ParseResStr`(RVA 0x15540)解析,
  生成一个**惰性**的 resource-string `Value`——`Value::CreateStringRP`(0x156A0)
  只是把 Value 的类型位标成 0x19,字符串在取值时才从资源里取
  【实锤,disasm 0x1800156A0;机制详见`01-duixmlparser-xml-to-element-tree.md` §4.1】)。
- 标签名直接用类名 `RichText`,大小写随意(解析器 `_wcsicmp` 匹配,
  详见`01-duixmlparser-xml-to-element-tree.md` §3)。

### 1.2 属性全景(全语料 495 次统计)

| 属性 | 次数 | 归属 |
|---|---|---|
| `id` / `class` / `layoutpos` / `padding` / `margin` | 225/190/142/100/30 | Element 通用 |
| `contentalign` | 204 | Element 通用(但对 RichText 有 DWrite 映射,§3.3) |
| `content` | 159 | Element 通用 |
| `foreground` / `font` / `background` | 154/121/76 | Element 通用 |
| `accessible` / `accrole` / `accname` | 149/139/12 | 无障碍(`04-uia-accessible-bridge.md`/`05-uia-pattern-providers.md`) |
| `constrainlayout` | 39 | **RichText 专属**(ConstrainLayoutProp) |
| `linespacing` / `baseline` | 9/8 | **RichText 专属** |
| `overhang` | 8 | **RichText 专属** |
| `typography` | 5 | **RichText 专属**(OpenType 特性,§4.2) |

【实锤,正则统计】RichText 自己的 PropertyInfo 表共 **15 张**
( symbols.json):AliasedRendering / Baseline / ColorFontPaletteIndex /
ConstrainLayout / DisableAccTextExtend / FontColorRuns / FontSizeRuns /
FontWeightRuns / LineSpacing / Locale / MapRunsToClusters /
OverhangOffset / Typography / TypographyRuns / VerticalScript。

### 1.3 一个"富"的实例:typography 等宽数字(WebcamUi)

`docs/duixml-corpus/WebcamUi/UIFILE_205.xml:74`:

```xml
<RichText accessible="true" contentalign="middlecenter"
          margin="rect(0rp,0rp,20rp,0rp)" constrainlayout="normal"
          typography="tnum=1"
          font="resstr(602, library(WebcamUi.dll))"
          foreground="20405" background="20575"/>
```

`typography="tnum=1"` = 打开 OpenType **tnum**(tabular numbers)特性,
让计时器的数字宽度对齐。更复杂的写法见
`msctfuimanager/UIFILE_16000/16002/16003.xml`:

```xml
typography="ss20=1,kern=1,dlig=1,liga=1"
```

四个特性:风格集 20、字距微调(kern)、自由连字(dlig)、标准连字(liga)。
这行字符串怎么被吃掉,见 §4.2——里面藏着一个**分隔符之谜**。

---

## 2. 引擎家族:五个类的分工

```
RichText (91 符号)                     ← Element 子类,XML 标签
 ├── RichTextShared (13)               ← 进程级单例:持有 IDWriteFactory
 │     └── s_pShared @ 0x183C60
 ├── GdiTextRenderer (19)              ← IDWriteTextRenderer 实现(DWrite→GDI 桥)
 ├── RichTextCache (22)                ← 文本+字形运行缓存(多约束复用)
 │     └── RichTextCacheEntry (5)      ← 单条缓存(一段文本的一组 glyph run)
 └── InternalRichText (6)              ← "私有别名"(见 §6)
```

RichText 对象里这些指针的落点【实锤,以下反汇编交叉验证】:

| this+ | 内容 | 证据 |
|---|---|---|
| 0x110 | RichTextCache*(GetContentSize 读它) | disasm 0x18004C924 |
| 0x118 | RichTextShared* | disasm 0x180019B75(`movq 0x118(%rcx),%rax`)、0x180018799 |
| 0x120 | CComPtr(用途未定,见未知问题) | 析构序列 |
| 0x128 | IDWriteTextFormat* | disasm 0x180018C0D(`leaq 0x128(%rcx),%r15`) |
| 0x130 | IDWriteTextLayout* | disasm 0x180018707(`leaq 0x130(%rcx),%r12`)+0x18001880E(存 CreateTextLayout 结果) |
| 0x138 | trimming sign(IDWriteInlineObject*) | disasm 0x180018A3A(`leaq 0x138(%rsi),%rbx`) |
| 0x140 | GdiTextRenderer* | 析构 0x180019XXX 序列(见 §5) |
| 0xc8 | 缓存的 font style | disasm 0x180018852(`cmpl %eax,0xc8(%rbx)`) |
| 0xd0 | 缓存的 line count | disasm 0x180018B70(`cmpl %edi,0xd0(%rbx)`) |
| 0xe0/0xdc/0xe4/0xcc | 布局状态位(FlushDWrite 重置) | disasm 0x180018B3A-0x180018B5A |

### 2.1 RichTextShared:进程级单例与"手动加载 dwrite.dll"

`RichTextShared::GetShared`(RVA 0x61BFC)读静态指针
`s_pShared @ 0x180183C60`;首次调用走 `RichTextShared::Initialize`
(0x62118),核心是 `_EnsureDWriteLoaded`(0x621A8):

```asm
; .local/build/p2-text/disasm-shared-init.txt
1800621DB:  movl  $0x104, %edx            ; MAX_PATH
1800621E5:  callq *0x180119A18            ; GetSystemDirectoryW
1800621FA:  leaq  0x180126F88(%rip), %r8  ; L"dwrite.dll"
18006220B:  callq *0x1801197A0            ; PathCchAppend
180062229:  movq  0x10(%rbx), %rcx        ; shared+0x10 = HMODULE
180062232:  leaq  0x180121EA8(%rip), %rdx ; L"DWriteCreateFactory"
180062239:  callq *0x1801196D0            ; LoadLibraryW / GetProcAddress
180062245:  movq  %rax, 0x18(%rbx)        ; shared+0x18 = DWriteCreateFactory*
```

【实锤】dui70 的导入表(含延迟导入)里**没有 dwrite.dll**——
这是纯动态加载。设计动机【强推】:DirectUI 要在无 DWrite 的环境
(安全模式、早期 Win7 之前壳层)也能跑,DWrite 是"能加载就上"的增强。

拿到函数指针后,Initialize 用 **IDWriteFactory2** 的 IID 造工厂:

```asm
; disasm-shared-init.txt
18006213F:  movq 0x18(%rbx), %rax         ; DWriteCreateFactory
180062143:  leaq 0x180121E30(%rip), %rdx  ; IID 0439fc60-ca44-4994-8dee-3a9af7b732ec
18006214D:  xorl  %ecx, %ecx              ; factoryType = ISOLATED
18006214F:  callq ...                     ; DWriteCreateFactory(0, IID, &shared+0x20)
```

IID `0439fc60-ca44-4994-8dee-3a9af7b732ec` = **IDWriteFactory2**(dwrite_2.h)
【实锤,GUID 字节 + SDK 头文件互证】。但注意:后续所有工厂调用
(CreateTextFormat +0x78 / CreateTextLayout +0x90 / CreateEllipsisTrimmingSign
+0xA0 / CreateTypography +0x80)用的都是 **IDWriteFactory 基类槽位**——
请求 Factory2 只是为了"确保宿主 DWrite 不低于 Win8.1 水平"
【强推,请求高版本 IID 但只用基类方法,这是常见的版本门槛写法】。

单例还缓存两套渲染参数(都在 dui70 里现造,不用系统默认):

- `GetAliasedRenderingParams`(0x95A74)——走 `IDWriteFactory::CreateCustomRenderingParams`
- `GetGdiNaturalRenderingParams`(0xB8254)——GDI 自然度量的对齐版

这两套参数在 GdiTextRenderer::DrawGlyphRun 里按文本模式选择(§5)。

### 2.2 GdiTextRenderer:DWrite 回调落到 GDI

DWrite 的渲染协议是**控制反转**:`IDWriteTextLayout::Draw(clientDrawingContext,
renderer, originX, originY)` 不直接画,而是回调你提供的
`IDWriteTextRenderer`。GdiTextRenderer(0x80 字节对象,存 RichText+0x140)
就是 dui70 的实现:

| IDWriteTextRenderer 方法 | GdiTextRenderer 实现 | RVA |
|---|---|---|
| DrawGlyphRun | 0x6F360(§5 详解) | 主路径 |
| DrawInlineObject | 0xB7F90 | 省略号 sign 等 |
| DrawUnderline / DrawStrikethrough | 0xB7FF0(同一个函数!) | 下划线/删除线共用 |
| IsPixelSnappingDisabled | 0x848F0 | 像素对齐 |
| GetCurrentTransform | 0x81670 | DPI 变换 |
| GetPixelsPerDip | 0x85DC0 | DPI |

【实锤,symbols.json + 虚表 0x1065C8】

它内部还实现了 `IDWriteBitmapRenderTarget` 的持有逻辑:
`_EnsureRenderTarget`(0x196F4)按需造 GDI 位图渲染目标;
`Begin`(0x18F08)/`End`(0x1933C)包一段绘制;
`_InitDCBrush`(0xB948C)把 DC 画刷同步进目标;
`_UpdateDrawingEffects`(0x6F778)处理 Run 的 drawing effect(§4.1);
`_DrawEffectRect`(0xB932C)给 effect 画底色块(比如荧光笔效果)。

**为什么需要这座桥?** DirectUI 的合成/绘制栈是 GDI/BufferedPaint 时代的
(见 `.local/audit/duser-render-internals.md` §3:duser 回落路径就是
GDI + BufferedPaint + GDI+)。DWrite 光栅化结果要进 GDI surface,
`IDWriteBitmapRenderTarget`(32bpp 位图 DC)是最官方的通道
【强推:架构动机;实锤:DrawGlyphRun 确实调用其 vtable+0x18
DrawGlyphRun 槽位,§5】。

---

## 3. 生命周期三阶段

### 3.0 初始化:RichText::Initialize → _InitDWrite

`RichText::Initialize`(虚表槽内,EXP)先走 Element 初始化,然后
`_InitDWrite`(0x61B80)做三件事【实锤,disasm-initDWrite.txt】:

1. `_FlushDWrite`(0x18B30)——先清场(§3.2);
2. `RichTextShared::GetShared()`——确保进程级 factory 就绪;
3. `new GdiTextRenderer`(构造 0x61CF8,大小 0x80)存入 this+0x140。

`OnHosted`(0x492F0,vtable slot 29)在元素挂进树时若
`this+0xd0 == 0`(没有缓存行数)也调 `_FlushDWrite`——
**宿主变化即布局作废**,这是 Element 生命周期和 DWrite 布局
绑定的第一个钩子【实锤】。

### 3.1 阶段一:布局协商(GetContentSize → _CreateDWriteLayout)

布局系统(`13-layout-landscape.md`/`14-layout-protocol.md`)调 `GetContentSize` 测"这段文本要多大"。
RichText 覆盖了它(0x4C890,vtable slot 15):

```asm
; disasm 0x18004C890
18004C8E0: leaq  ContentProp(%rip), %rdx
18004C8FB: callq GetValue                    ; 读 content
18004C906: andl $0x3f, %eax
18004C909: cmpb $0x5, %al
18004C90B: jne  0x18004CD85                  ; type!=5 → Element 基类回落
18004C924: movq 0x110(%rdi), %rcx            ; this->RichTextCache
18004C92E: jne  0x18004CE8A                  ; 缓存命中→GetCachedTextMetrics
```

**Value 类型语义**(关键!):`Value::CreateString` 写类型字
`orl $0x5`(disasm 0x180015297)——**type 5 = 字符串**;
图形相关工厂写 `0xB`(disasm 0x180053A09)。所以上面分支是:
**字符串内容(type==5)进 RichTextCache(DWrite 布局);
非字符串(图形/位图,type 0xB)回落 `Element::GetContentSize**
(0xEDB0,GDI 测量,调用点 0x18004CDA0)。缓存未命中时由
`_CreateDWriteLayout`(0x186E8)现造布局:

```asm
; .local/build/p2-text/disasm-createDWriteLayout.txt
180018799: movq 0x118(%rbx), %rax      ; this->RichTextShared
18001879F: movq 0x20(%rax), %rcx       ; shared->IDWriteFactory
1800187A7: movq 0x90(%rax), %r10       ; ★ factory vtable+0x90 = CreateTextLayout
...
1800187D5: movq 0x128(%rbx), %r9       ; this->IDWriteTextFormat
1800187FB: callq 0x1800FF010           ; __guard_dispatch_icall_fptr(CFG)
18001880E: movq %rax, (%r12)           ; 结果存 this+0x130 = IDWriteTextLayout*
```

`CreateTextLayout(string, len, format, maxWidth, maxHeight, &layout)`
的 maxWidth/maxHeight 来自**布局约束矩形**(r14 指向的 rect 0x4/0x8 与
0xC/0x0 相减,disasm 0x1800187AE-0x1800187C4)——这就是
`constrainlayout` 属性的用武之地:它决定"测量时用哪个约束"
(narrow/normal 对应不同 max width 策略,由 RichTextCache 管理
约束集合,见 `SetLayoutConstraints` 0xBA6AC)【强推:属性语义;
实锤:缓存类确实按约束存多份 entry】。

**TextFormat 的构造**(`_EnsureTextFormat`,0x18BD8)把 XML 属性
翻译成 DWrite 参数:

| XML/属性 | DWrite 调用 | 反汇编证据 |
|---|---|---|
| locale 属性(LCIDToLocaleName@0x180119740) | CreateTextFormat 的 localeName 参数 | 0x180018DCC-0x180018DE6 |
| font(face/size/weight/style) | CreateTextFormat(familyName, size, weight, style, stretch) | 0x180018CF2-0x180018D5E(GetFontSize 0x11080 / GetFontStyle 0x1A810 先取值) |
| (factory) | **vtable+0x78 = CreateTextFormat** | 0x180018D5E |
| contentalign 低 2 位(水平) | format **vtable+0x18 = SetTextAlignment** | 0x18001899C |
| contentalign 位 2-3(垂直) | format **vtable+0x20 = SetParagraphAlignment** | 0x1800189D7(4→2, 8→1) |
| RTL(Element::IsRTL 虚调用) | format **vtable+0x30 = SetReadingDirection** | 0x180018A1C |
| wordwrap(contentalign & 0xC) | format **vtable+0x28 = SetWordWrapping** | 0x18001893F |
| linespacing/baseline 属性 | **vtable+0x50 = SetLineSpacing** | LineSpacingProp/BaselineProp |

【实锤:dwrite.h 虚表槽位逐一核对——IDWriteTextFormat:
slot3=SetTextAlignment(0x18)、slot4=SetParagraphAlignment(0x20)、
slot5=SetWordWrapping(0x28)、slot6=SetReadingDirection(0x30)、
slot10=SetLineSpacing(0x50);IDWriteFactory slot15=CreateTextFormat(0x78)、
slot18=CreateTextLayout(0x90)、slot20=CreateEllipsisTrimmingSign(0xA0)】

**这就是"布局协商"的完整闭环**:布局系统给出约束矩形 →
CreateTextLayout 用约束造布局 → `RichText::GetContentSize` 从
layout 拿 metrics(RichTextCacheEntry::CalculateMetrics 0xBA020 /
GetCachedTextMetrics 0xBA3C0,缓存的就是 DWRITE_TEXT_METRICS 形状的
结构,disasm 0x180018B3EE 附近整块 xmm0/xmm1 拷贝)→
SIZE 返回给布局系统。**DWrite 从测量阶段就接管了文本**。

### 3.2 失效路径:_FlushDWrite

任何影响布局的属性变化(content/font/contentalign/…)最终都会
`_FlushDWrite`(0x18B30):

```asm
; disasm-flushDWrite.txt
180018B3A: orl  $-1, 0xe0(%rcx)      ; 布局状态位 → -1(脏)
180018B43: movb $0,   0xdc(%rcx)
180018B4D: movw $0,   0xe4(%rcx)
180018B54: movl $0,   0xc8(%rcx)     ; font style 缓存清零
180018B5A: movl $0x7fffffff, 0xcc(%rcx)
180018B64: addq $0x128, %rcx         ; &this->0x128 (TextFormat)
180018B6B: callq 0x180018BAC         ; ★ SafeRelease:CComPtr 风格置空+Release
180018B70: cmpl %edi, 0xd0(%rbx)     ; lineCount == 0?
180018B78: jne  0x180018B97
180018B7F: callq *0x180119498        ; (走 RichTextCache 清理)
180018B8B: leaq 0x130(%rbx), %rcx    ; &this->0x130 (TextLayout)
180018B92: callq 0x180018BAC         ; SafeRelease
```

0x180018BAC 就是内联的 SafeRelease 助手:`if (*p) { tmp=*p; *p=0;
tmp->Release(vtable+0x10); }`【实锤,disasm-flushDWrite.txt:40-50】。
TextFormat/TextLayout 都是"脏了就整个扔掉重建"——**没有增量更新**。
这个简单粗暴的策略解释了为什么 Run 系统(§4)在设置时也全量重放:
反正都要重建布局,重放一遍 Run 字符串成本可以接受【强推】。

### 3.3 阶段二:渲染路径(Paint → _PaintStringContentDWrite)

`RichText::Paint`(0x64290,vtable slot 14)的分支结构
【实锤,disasm-paint.txt:19-56】:

```asm
1800642B8: leaq  ContentProp(%rip), %rdx
1800642CA: callq GetValue              ; 读 content
1800642DE: andl $0x3f, %r10d
1800642E2: cmpb $0x5, %r10b
1800642E6: jne  0x18006434D            ; type!=5(非字符串)→ 只走基类
; ── type==5(字符串内容):DWrite 主场 ──
1800642FF: callq 0x18000D450           ; Element::Paint(背景/边框)
18006431C: callq 0x1800643A0           ; PaintFocusRect
180064321: testb $0x40, 0x95(%rbx)     ; 需要画内容?
18006432A: cmpl $0x0, 0xd0(%rbx)       ; lineCount==0 → 没文本可画
180064346: callq 0x1800183C4           ; ★ _PaintStringContentDWrite
; ── type!=5(图形/位图):回落基类 ──
180064364: callq 0x18000D450           ; Element::Paint(其 PaintContent
                                     ;   内部会走 PaintStringContent GDI 管线)
```

即:**字符串内容(type==5,§3.1 的枚举)走 `_PaintStringContentDWrite`
(0x183C4,调 `layout->Draw` 回调 GdiTextRenderer,§5);图形/位图
内容(type 0xB)回落 Element 基类的 GDI 路径**——这和`08-ptext-and-the-old-text-era.md` 的
PText/TextGraphic(永远 GDI)形成两代引擎的完整对照。

`_PaintStringContentDWrite`(0x183C4)的骨架:

1. `_EnsureTextFormat`(§3.1)+ `_CreateDWriteLayout`(§3.1)
   ——渲染前保证布局新鲜;
2. `GdiTextRenderer::Begin`(0x18F08)——绑定 DC、初始化
   IDWriteBitmapRenderTarget(需要时 QueryInterface
   **IDWriteBitmapRenderTarget1**,IID `791e8298-3ef3-4230-9880-c9bdecc42064`,
   dwrite_1.h 证实;用它的灰度抗锯齿能力)【实锤】;
3. `layout->Draw(ctx, GdiTextRenderer, x, y)`
   ——vtable slot 49(0x188)【实锤,槽位核对】;
4. DWrite 逐 Run 回调 `GdiTextRenderer::DrawGlyphRun`(§5);
5. `End`(0x1933C)——把位图目标 blit 回元素 DC。

**与 GDI 路径的分岔点**就在 vtable:RichText 覆盖 slot 14(Paint),
PText/TextGraphic 不覆盖(= Element::Paint → PaintStringContent →
ExtTextOutW 族,`08-ptext-and-the-old-text-era.md` 详解)。两条路径都以
"content 非字符串(Value type 0xB 图形)→ Element 基类回落"兜底【实锤】。

### 3.4 阶段三:资源释放(析构序列)

`RichText::~RichText`(0x1C410)按成员顺序释放
【实锤,disasm-richtext-dtor.txt 全文】:

```asm
18001C430: movq 0x118(%rbx), %rcx   ; RichTextShared*
18001C43C: andq $0x0, 0x118(%rbx)   ; 置空后调 vtable+0x10(Release)
18001C44B: callq CFG                ; → Release(单例自身管理生命周期,
                                   ;   这里确实调 Release —— 但单例
                                   ;   有自己的引用计数,不会死)
18001C450: leaq 0x138(%rbx), %rcx  ; trimming sign → SafeRelease 助手
18001C45C: leaq 0x128(%rbx), %rcx  ; IDWriteTextFormat → SafeRelease
18001C468: movq 0x140(%rbx), %rcx  ; GdiTextRenderer*
18001C474: andq $0x0, 0x140(%rbx)
18001C47C: callq 0x18001C4D0       ; → GdiTextRenderer::~GdiTextRenderer
                                   ;   (它再 Release 自己的 render target)
18001C481: leaq 0x130(%rbx), %rcx  ; IDWriteTextLayout → SafeRelease
18001C48D: leaq 0x120(%rbx), %rcx  ; CComPtr(0x120)→ SafeRelease 类助手
18001C499: leaq 0x110(%rbx), %rcx  ; RichTextCache → delete 类助手
18001C4AD: jmp  Element::~Element  ; 基类收尾
```

两个 SafeRelease 助手各司其职:0x180018BAC
(`*p ? { tmp=*p; *p=0; tmp->vtable+0x10() }`,§3.2)
负责 COM 指针;0x18001707C 负责 delete 类指针
(RichTextCache/0x120/0x138 走它,内部带 vtable dtor 调用)。
0x118(RichTextShared)虽然也调了 Release,
但单例由 `GetShared` 的惰性初始化管理,
析构它不会消灭进程单例【实锤:调用序列;强推:单例
生命周期细节】。

三个阶段串起来看,**DWrite 对象被完整缝合进 Element 生命周期**:
Initialize 造共享基础设施 → 布局协商(CreateTextLayout 即测即抛)→
Paint 走回调桥 → 属性变化全量失效 → 析构逆序释放。
DWrite 对象从不逃逸出 RichText 的私有指针域——Element 树的其它部分
(布局器、合成器)只知道 SIZE 和像素,完全无感 DWrite 的存在。
**这就是"嵌入"的确切含义**【强推:对三阶段证据的综合】。

---

## 4. Run 系统:富文本的灵魂

### 4.1 字符串编码的范围属性

RichText 有 5 个"Runs"属性:FontColorRuns / FontSizeRuns /
FontWeightRuns / TypographyRuns / MapRunsToClusters(bool)。
前四个的 setter 全是同一形态【实锤,SetTypography(0xAAAE0)/
SetFontColorRuns(0x78560)反汇编】:

```cpp
HRESULT SetFontColorRuns(PCWSTR runs) {
    Value* v = Value::CreateString(runs);      // 0x180015210
    return _SetValue(FontColorRunsProp, v);    // 0x180011490
}
```

**Run 字符串格式**由 `_SetRangedStringRunsWithValue`(0x19F1C)解码
【实锤,disasm-rangedstringruns.txt】:

```
段分隔: ';'   (wcschr, disasm 0x18001A029)
段内:    "起,止=值"  (逗号 wcschr@0x180019FAC/'0x180019FE4,
                     数字 wcstol@0x180119B60)
分发:    kind==0 → _SetFontColorRun (0x1B44C)
         kind==1 → _SetFontSizeRun   (0x1AEDC)
         kind==2 → _SetTypographyRun (0x19B50)
         kind==3 → _SetFontWeightRun (0xB9514)
```

例如 `"0,4=red;4,8=blue"` = 前 4 个字符红、后 4 个蓝(示意)。
每个 `_SetXXXRun` 把值应用到 layout 的
[DWRITE_TEXT_RANGE](start, len) 上:FontSize/Weight 走
IDWriteTextLayout 的 SetFontSize(slot 26 / vtable+0xD0)/
SetFontWeight(slot 25 / +0xC8)等槽位;FontColor 走
SetDrawingEffect(slot 31 / +0xF8)——颜色不是 DWrite 内建概念,
被包成 drawing effect 对象,由 GdiTextRenderer 在
`_UpdateDrawingEffects`(0x6F778)里解开【实锤:槽位核对;
强推:effect 对象的内部布局】。

`MapRunsToClusters` 属性为 true 时,每个 Run 先过
`_UpdateRangeForClusterMetrics`(0xB993C)——**把字符下标换算成
字形簇下标**(代理对、连字会让 1 簇 ≠ 1 字符)。这是给 IME/合字
场景的对齐补偿【强推:语义;实锤:调用点 disasm-rangedstringruns.txt:133-136】。

### 4.2 typography:OpenType 特性的文本 DSL

`_SetTypographyRun`(0x19B50)是 Run 家族里最讲究的
【实锤,disasm-settypographyrun*.txt】:

```asm
180019B75: movq 0x118(%rcx), %rax       ; this->RichTextShared
180019B98: movq 0x20(%rax), %rcx        ; shared->IDWriteFactory
180019B9F: movq 0x80(%rax), %rax        ; ★ factory vtable+0x80 = CreateTypography
180019BA6: callq (CFG thunk)            ; → IDWriteTypography*
...
180019BB5: leaq 0x18011F8B8(%rip), %rdx ; L"subscript"
180019BBF: callq 0x1800FDBCA            ; _wcsicmp 变体
180019BD1: leaq 0x18011F8A0(%rip), %rdx ; L"superscript"
...
180019BEE: callq *0x180119BA8           ; wcschr(str, '+')  ← 0x2B!
...
180019C4F: movl $0x2C, %edx
180019C5B: callq *0x180119BA8           ; wcschr(feature, ',')
...
180019CA2: callq *0x180119B78           ; _snwscanf_s(feature, 4, "%4lc=%d",
                                        ;              &tag, &param)
180019CB7-0x180019CE8: (4 字节 tag 打包成 UINT32 nameTag,
                        与 param 组成 DWRITE_FONT_FEATURE)
180019CF2: movq 0x18(%rax), %rax        ; ★ typography vtable+0x18
                                        ;   = AddFontFeature(slot 3)
```

特性语法由此完全确定:

- **4 字符 OpenType tag = 十进制参数**,如 `tnum=1`、`ss20=1`;
- 单个特性里多个参数用**逗号**分隔(0x2C);
- 前缀 `+` 有特殊分支(0x180019BEE 搜 `'+'`)——
  【强推】对应语料中未出现的 `+liga` 简写(默认参数 1);
- `superscript`/`subscript` 是**命名单选特性**(先于 tag 解析,
  分别映射到 `sups`/`subs` tag)【强推:字符串实锤,映射表未 dump】;
- 每个特性 AddFontFeature 进 IDWriteTypography,
  最后 layout->SetTypography(槽 33)应用到 range
  【实锤:调用序列】。

**分隔符之谜**:语料写 `typography="ss20=1,kern=1,dlig=1,liga=1"`
(逗号分隔**特性**),但 §4.1 的 Run 段分隔是分号、
段内范围又用逗号——那 typography 属性(非 Runs)的**顶层**分隔符是什么?
`_SetTypographyInternal`(0x1A120)里能看到的分隔符是 `0x3B`(`;`,
disasm 0x18001A1C5)。两种可能:(a) XML 解析层把逗号归一化成分号;
(b) 语料写法实际不生效。**我没有找到归一化代码,诚实标注为未知
问题 1**。唯一**确定**有效的是单特性写法 `tnum=1`(无分隔符问题)。

### 4.3 XML 层暴露了吗?——结论

Run 系统**没有 content 内联标记**(语料 0 命中 markup 语法),
也不是纯 C++ API:`FontColorRunsProp` 等是注册过的 PropertyInfo,
**理论上 XML 可写** `fontcolorruns="0,4=red"`。但全语料 495 个
RichText 里 **0 次**使用任何 Runs 属性【实锤,全语料扫描】。
它们是给宿主程序(C++ 侧)准备的 API 面——
`SetFontColorRuns` 等全是导出函数(EXP)。
XML 作者实际拥有的富文本能力只有:typography(5 次)、
linespacing/baseline(9/8 次)、constrainlayout(39 次)、overhang(8 次)。
**"富文本引擎"的富,主要富在引擎侧,不在标记侧**【实锤:频次;
强推:解释——DirectUI 的 XML 定位是布局/样式,动态内容走 bind/程序注入】。

---

## 5. GdiTextRenderer::DrawGlyphRun 逐行解码

这是"DirectUI 怎么把 DWrite 装进 GDI 时代"的最直接证据
【实锤,disasm-drawGlyphRun.txt 全文已核】:

```asm
; this = GdiTextRenderer
18006F3A4: movq 0x50(%rcx), %rcx       ; this->currentRenderTarget
18006F3BD: jne  0x18006F667
18006F667: ...
18006F674: callq 0x1800B9EC0           ; → RichTextCache::AddGlyphRun(缓存路径!)

; 非缓存路径:
18006F3E6: movq 0x10(%rdi), %rax       ; this->RichTextShared
18006F3FF: callq 0x180095A74           ; GetAliasedRenderingParams(模式 0)
18006F6BF: callq 0x1800B8254           ; GetGdiNaturalRenderingParams(模式 1)
18006F44C: movq 0x20(%rax), %rcx       ; shared->IDWriteFactory
18006F462: movq 0xE0(%rax), %rax       ; factory vtable+0xE0
                                        ;   = IDWriteFactory2::CreateGlyphRunAnalysis
18006F469: callq (CFG)                 ; → IDWriteGlyphRunAnalysis*
18006F569: movq 0x18(%rax), %rax       ; analysis vtable+0x18 = GetAlphaTextureBounds
18006F593: movq 0x20(%rax), %rax       ; analysis vtable+0x20 = CreateAlphaTexture
...
18006F49B: movq 0x40(%rdi), %rcx       ; this->IDWriteBitmapRenderTarget
18006F4A2: movq 0x18(%rax), %rdx       ; ★ renderTarget vtable+0x18 = DrawGlyphRun
18006F4D3: callq (CFG)                 ; 位图目标上画字形
```

关键点:

1. **两条腿**:渲染目标已绑定时字形直接进
   `RichTextCache::AddGlyphRun`(0xB9EC0)——**字形运行级缓存**,
   同一段文本反复 Paint 不重走 DWrite 光栅化;
   没绑定时现造 `IDWriteGlyphRunAnalysis`。
2. **文本渲染模式三分**(`this+0x5c`):0=aliased(锯齿,
   用 GetAliasedRenderingParams)、1=GDI-natural(用
   GetGdiNaturalRenderingParams)、2=natural(乘 0xB2E25 浮点系数的
   对比度补偿,disasm 0x18006F412/0x18006F425)——对应经典
   GDI 的 ClearType 配置策略【强推:模式命名;实锤:三分支】。
3. **彩色字体**:`glyphRun+0x40` 非零时走 0x18006F6FA 分支,
   把 DWRITE_GLYPH_RUN 的 colorPaletteIndex × 调色板颜色算出
   COLORREF(三个 shufps/mulss/cvttss2si 序列打包 R/G/B,
   disasm 0x18006F6FA-0x18006F769),并且 renderTarget
   **vtable+0x40(slot 8)= Resize**——彩字形可能超出当前
   目标尺寸,先扩位图【实锤:槽位与指令序列;ColorFontPaletteIndexProp
   的存在佐证这是 RichText 的正式能力】。
4. **像素对齐/DPI** 由 IsPixelSnappingDisabled(0x848F0)/
   GetPixelsPerDip(0x85DC0) 回调配合,xmm8(从 0x180122240 装载的
   常量,值≈0.5)做半像素修正【实锤:指令;强推:常量语义】。

顺带一提:**duser 侧还有一层 DWrite 缓存**——duser 延迟导入表里
dui70 导出的 `CacheDWriteRenderTarget`(ordinal 54)/
`GetCachedDWriteRenderTarget`(ordinal 55)【实锤,delay-imports 解析】。
即位图渲染目标本身也可以跨元素复用(由 duser 的绘制循环托管)。
两个缓存层次的关系是**未验证点**(未知问题 5)。

---

## 6. InternalRichText:为什么"host 注册"其实 registrations 都在 dui70

### 6.1 语料用法

`<InternalRichText>` 全语料 **11 次**:
dui70/UIFILE_IMMERSIVESTYLES.xml 5 次 + msctfuimanager 6 次
(3 文件 × 2)【实锤】。dui70 的用法最说明问题——
沉浸式滚动条的**箭头字符**:

```xml
<!-- dui70/UIFILE_IMMERSIVESTYLES.xml:41-54 -->
<if class="Line_Arrow">
  <InternalRichText background="20575" constrainlayout="narrow"
                    direction="LTR" overhang="true"/>
  <if id="atom(LineUp_Arrow)">
    <InternalRichText content="resstr(131, library(dui70.dll))"
                      contentalign="bottomcenter"
                      linespacing="33rp" baseline="27rp"/>
  </if>
  ...LineDown/LineLeft/LineRight 同款(resstr 132/133/134)
```

**滚动条箭头不是图标,是字符串资源里的字形字符**,由 InternalRichText
按 linespacing/baseline 微调到按钮中央。这是 RichText 引擎做
"单字形精确摆放"的极端用例。

### 6.2 注册机制:注册人不是"宿主",是 TouchSelect::Register

`03-host-registered-tags.md` §3 讲了标签注册的通用机制(`ClassExist` →
`new ClassInfo` → `Initialize`)。InternalRichText 的注册人
**藏在 TouchSelect::Register 里**【实锤,disasm-touchselect-register.txt:325-350】:

```asm
; TouchSelect::Register (0x67B0) 的第 4 个子注册块(0x180006BF4):
180006C3F: leaq 0x18011F380(%rip), %r8   ; L"InternalRichText"
180006C48: callq 0x180036C6C             ; ClassInfoBase::ClassExist(...)
180006C6D: callq 0x18008020              ; (创建 ClassInfo<InternalRichText, RichText>)
180006C80: callq 0x1800369A0             ; ClassInfoBase::Register
180006C8B: movq %rdi, 0x180183C70        ; InternalRichText::s_pClassInfo
```

为什么是 TouchSelect::Register?看注册拓扑:它由
`RegisterStandardControls`(0x5890)调用(disasm 0x1800059DE),
同批还有 RichText 自己的注册(经 0x180006CF4 辅助块,
引用 L"RichText" @0x1801233A8,存 s_pClassInfo@0x183A78)
【实锤】。**InternalRichText 是 RichText 注册的"搭车客"**——
直接挂在 TouchSelect(一个富文本重度用户)的注册函数里,
省一个独立 Register 函数。

那"host 注册"的说法哪来的?`03-host-registered-tags.md` §2 的原始观察是:
InternalRichText **不在 dui70 导出面**(86 个 C 导出里没有它)
且不在公共标签认知里。现在机制清楚了,更准确的表述是:
**InternalRichText 是 dui70 内部的私有标签**——注册进全局表
(所以 msctfuimanager 这种 dui70 系宿主也能写它),
但没有公开文档/导出背书,微软自己也在 dui70 内部样式里用它
画滚动条箭头。`03-host-registered-tags.md` 的 §3.1 结论(154 个未知标签里它有类)
不变;本节给出的是**注册人归属的精确答案**【实锤】。

### 6.3 vtable 铁证:InternalRichText 就是 RichText 的马甲

把两个类的虚表(RichText@0x1062A8 / InternalRichText@0x106638)
逐槽比对【实锤,.local/build/p2-text/vtable-*.txt,40 槽全 dump】:

```
40 个槽位中仅 2 处不同:
slot 0:  RichText::`vector deleting dtor'   vs InternalRichText::`vector deleting dtor'
slot 35: RichText::GetClassInfoPtr          vs InternalRichText::GetClassInfoW
```

**零行为覆盖**——同名方法一个都没换。InternalRichText 连方法表都
懒得写新行为,只换了析构和类身份。它是"同一个引擎、私有标签名"
的最纯粹证据。ClassInfo 模板第二参数也确认继承链
`InternalRichText : RichText`【实锤,classinfo-inheritance.txt】。

---

## 7. 三个"好奇点"的答案

### 7.1 _AdjustRangeForPathJoinCharacters:路径省略号的排版故事

(0x1A26C)当 contentalign 含 0x240 位族(endellipsis 类省略号)时,
对 content 做**预扫描**【实锤,反汇编】:

```
循环: 找 L'\\'(0x5C) 或 L'/'(0x2F)
      检查前一个字符 iswspace(0x180119B80)
      命中 → 记录为"路径连接点"
```

故事:显示文件路径时省略号不能瞎截——`C:\Users\me\Doc...ts\a.txt`
要保头尾、断中间。`_CreateDWriteLayout` 里对应实锤
(disasm-createDWriteLayout.txt:286-308):

```asm
180018AC8: andl $0x240, %eax          ; contentalign 的省略号族位
180018AD0: cmpl $0x40, %eax           ; 0x40 = endellipsis?
180018AD5: btl  $0x8, %r14d           ; 0x200 = pathellipsis?
180018AF3: (pathellipsis 分支)
180018AFF: callq GetContentString     ; 0x6DD50
180018B13: orl $-1, -0x10(%rbp)       ; delimiterCount = -1 → 整串?
180018B17: movl %eax, -0x14(%rbp)     ; delimiter = content 首字符!
```

省略号实现走 DWrite 的 **SetTrimming**(format vtable+0x48,
disasm 0x180018A6D)+ `CreateEllipsisTrimmingSign`(factory
vtable+0xA0,disasm 0x180018ABA)——sign 对象就存在 this+0x138。
0x180018A55 一带把 trimming 粒度设为 1/2(endellipsis→CHARACTER、
wordellipsis→WORD),pathellipsis 再叠加上面的路径保留范围。
**"PathJoin"=路径分隔符**(backslash/slash 的连接语义)【实锤:
字符常量;强推:0x40/0x200 位含义从位测试+分支结构反推】。

### 7.2 GetVerticalScript:竖排的"半成品"

`GetVerticalScript`(0x194A0)读 VerticalScriptProp(0x89850),
导出方法 `SetVerticalScript`(0xAAB50)也存在——机制完整。
但全语料 **0 次** `verticalscript=` 属性【实锤,全语料正则】。
且 `_EnsureTextFormat` 里没找到 SetFlowDirection(format vtable+0x38)
与该属性的联动调用(唯一一次 +0x38 的调用在 Win11 新接口的
QI 之后,见未知问题 2)。结论:竖排**引擎侧有钩子、XML 侧未启用**
【强推】。顺带:IMMERSIVESTYLES 里的 `direction="LTR"` 是
Element 层的阅读方向属性(§3.1 的 SetReadingDirection),不是竖排。

### 7.3 TextGraphic 语料零出现之谜

TextGraphic(19 方法,vftable@0x111A18)在 149 个 XML 里
**0 次作为标签出现**【实锤】。它没有被淘汰——`PText::Register`
(0x79120)**先注册 TextGraphic 再注册 PText**(disasm-ptext-register.txt:
引用 L"TextGraphic"@0x180122ED0 和 L"PText"@0x180122EC0 各一次,
ClassExist 各一次),它仍在标准控件集里。
TextGraphic 的三个自有行为:SideGraphicProp(侧图标)、
GetContentStringAsDisplayed 覆盖(vtable slot 3)、
OnPropertyChanged 覆盖——它是"文本+侧边小图标"的复合控件基类。
**谜底在`08-ptext-and-the-old-text-era.md` 揭晓**(PText:TextGraphic 的样式表马甲)——
这里先给结论:TextGraphic 是 RichText 之前的"图文复合"方案,
RichText+Element 图标属性组合出现后失去存在感,但作为 PText
的基类存活在注册链里【强推:考古证据链在`08-ptext-and-the-old-text-era.md` §4】。

---

## 8. 未知问题清单

1. **typography 顶层分隔符**:语料用逗号分隔多特性
   (`ss20=1,kern=1,dlig=1,liga=1`),但 `_SetTypographyInternal`
   可见分隔符是 `;`。XML 层是否存在逗号→分号归一化未找到;
   msctfuimanager 的 4 特性写法**是否实际生效**未验证
   (需要运行时实验或找到归一化代码)。
2. **Win11 新接口 QI**:`_EnsureTextFormat` 在 this+0x120 非空时
   对 TextFormat QueryInterface GUID `28d5197f-3940-4535-b315-e327e13d845b`
   (dwrite.dll 里存在、26100 SDK 头文件里没有——Win11 时代接口,
   疑似 IDWriteTextFormat4/5),然后调其 vtable+0x38(参数 1)。
   接口确切身份、this+0x120 存的是什么,均未定。
3. **`+` 前缀特性的确切语义**(§4.2 的 wcschr('+') 分支):
   是"参数默认 1"的简写还是别的,没 dump 到映射表。
4. **drawing effect 对象布局**:FontColorRuns 的颜色如何包装成
   IUnknown* effect、`_DrawEffectRect` 画的是什么效果
   (荧光笔?背景块?),只确认了调用关系,没反出结构体。
5. **两层 DWrite 缓存的关系**:RichTextCache(glyph run 级,
   dui70 内)与 duser 延迟导入的 CacheDWriteRenderTarget
   (ordinal 54/55,渲染目标级)如何配合,未验证。
6. **RichTextCacheEntry 的条目键**:按什么键存多份
   (约束矩形?字号?)——`_EnsureEntry`(0xBA894)没细读,
   constrainlayout 的 narrow/normal 语义只能强推。
7. **vtable 个别槽位的符号归属**:slot 7/27/28 在最近符号匹配里
   落到 CallstackTracker/Progress 等无关符号(它们是未导出的
   thunk),RichText 虚表 40 槽中约 3 槽函数名未定,
   不影响本文结论(关键槽 6/13/14/15/29/35 全部实锤)。
8. **UITest 未覆盖文本**:本仓库的 UITest 探针没有 RichText 用例,
   §5 的 DrawGlyphRun 解码是纯静态分析;动态验证(断点看
   renderTarget 指针)未做。

---

## 9. 证据索引

| 结论 | 证据 |
|---|---|
| RichText 495 次/33 DLL、属性频次表 | 全语料正则统计【实锤】 |
| 引擎家族 5 类 156 符号 | pinned/symbols.json 分类计数【实锤】 |
| 手动加载 dwrite.dll(GetSystemDirectory+PathCchAppend+LoadLibraryW+GetProcAddress) | disasm-shared-init.txt:68-91,导入表无 dwrite【实锤】 |
| DWriteCreateFactory 请求 IDWriteFactory2 | IID 0439fc60… @0x180121E30 字节 dump + dwrite_2.h【实锤】 |
| CreateTextFormat=+0x78/CreateTypography=+0x80/CreateTextLayout=+0x90/CreateEllipsisTrimmingSign=+0xA0 | dwrite.h 槽位表 × disasm-createDWriteLayout/ensureTextFormat/settypographyrun【实锤】 |
| TextFormat 槽位(SetTextAlignment 等 6 个) | dwrite.h 槽位表 × disasm-createDWriteLayout:184-265【实锤】 |
| 成员偏移表(0x110/0x118/0x128/0x130/0x138/0x140…) | §3 各 disasm 文件交叉引用【实锤】 |
| Value 类型枚举:5=字符串(CreateString `orl $0x5`@0x180015297)、0xB=图形(0x180053A09) | Value 工厂 disasm【实锤】 |
| GetContentSize/Paint 的 type==5 分支 = 字符串→DWrite、非字符串→Element 基类 | disasm-paint.txt:28-56、0x18004CDA0 调用点【实锤】 |
| _FlushDWrite 全量失效+SafeRelease | disasm-flushDWrite.txt 全文【实锤】 |
| 析构序列(0x118/0x138/0x128/0x140/0x130/0x120/0x110 顺序释放) | disasm-richtext-dtor.txt 全文(0x18001C410-0x18001C4AD)【实锤】 |
| Run 字符串格式 "起,止=值;…" 与四分发 | disasm-rangedstringruns.txt(wcschr 0x3B/0x2C、wcstol、4 分发调用)【实锤】 |
| typography "%4lc=%d" + AddFontFeature(vtable+0x18) | 格式串 0x18011F8D0 dump + disasm-settypographyrun2.txt【实锤】 |
| subscript/superscript 命名特性 | 字符串 0x18011F8B8/0x18011F8A0 dump + wcsicmp 调用【实锤】 |
| DrawGlyphRun 双路径(缓存/CreateGlyphRunAnalysis)+IDWriteBitmapRenderTarget+0x18 | disasm-drawGlyphRun.txt 全文 + dwrite.h 槽位【实锤】 |
| 彩色字体路径(RGB 打包+Resize) | disasm-drawGlyphRun.txt:241-267【实锤】 |
| IDWriteBitmapRenderTarget1 QI(灰度 AA) | IID 791e8298… @0x18011F8F0 + dwrite_1.h【实锤】 |
| InternalRichText 注册人=TouchSelect::Register | disasm-touchselect-register.txt:325-350("InternalRichText"字符串@0x18011F380)【实锤】 |
| RichText 注册走 RegisterStandardControls 0x180006CF4 辅助块 | "RichText"字符串@0x1801233A8 引用点 0x180006D3F【实锤】 |
| InternalRichText vtable=RichText vtable(仅 slot0/35 不同) | vtable-*.txt 40 槽 dump 比对【实锤】 |
| 路径省略号(SetTrimming+CreateEllipsisTrimmingSign+0x5C/0x2F 扫描) | disasm-createDWriteLayout.txt:286-308 + _AdjustRangeForPathJoinCharacters 反汇编【实锤】 |
| verticalscript 语料 0 次 | 全语料正则【实锤】 |
| TextGraphic 标签 0 次 | 全语料正则【实锤】 |
| constrainlayout/linespacing 语义 | 【强推】(属性存在实锤,取值语义未反完) |

**复现材料**:`.local/build/p2-text/` 下 disasm-createDWriteLayout /
ensureTextFormat / flushDWrite / paint / paintStringContentDWrite /
drawGlyphRun / shared-init / initDWrite / settypographyrun×2 /
rangedstringruns / parsefeature / touchselect-register /
ptext-register / richtext-register-helper / richtext-dtor /
vtable-RichText / vtable-InternalRichText / vtables-ptext-textgraphic
(GdiTextRenderer 虚表在 symbols.json+vtable dump);
llvm-objdump 命令均 `--start-address=0x180000000+RVA`。

**相关材料**:
- `01-duixmlparser-xml-to-element-tree.md`《duixml 是怎么被吃进去的》§3(标签注册/两级查找)、§4(resstr)
- `03-host-registered-tags.md`《宿主注册标签》§3(ClassExist 注册契约;本文 §6.2 修正其"host 注册"表述)
- `13-layout-landscape.md`/`14-layout-protocol.md`(布局协商的调用方)
- `08-ptext-and-the-old-text-era.md`《PText 与旧文本时代》(双引擎 GDI 侧 + 迁移考古)
- `.local/audit/duser-render-internals.md` §3(duser 绘制栈回落路径)
