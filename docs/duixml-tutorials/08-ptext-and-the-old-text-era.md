# PText 与旧文本时代:被样式表钉住的标签

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者,
> 接着`07-richtext-and-the-dwrite-bridge.md`(RichText 与 DWrite 桥)讲它的"前辈":
> **PText(78 次)、TextGraphic(0 次却在册)** 这两个旧时代文本类——
> 它们怎么渲染(纯 GDI,反汇编实锤)、为什么语料里 PText
> **全部躺在样式表里**、以及"迁移到 RichText"这个说法哪里对哪里错。
>
> 证据分级:【实锤】/【强推】/【猜想】,规则同本系列全部 24 篇。
> RVA 相对 dui70.dll(0x180000000);反汇编行号指
> `.local/build/p2-text/` 下的工作文件。

---

## 0. 结论速览

1. **PText 语料 78 次、17 个 DLL,但 78/78 全部在 `<stylesheets>` 里**
   ——它是**只活在样式表里的标签**:没有一处 XML 实例用它造元素
   【实锤,全语料 stylesheets 区间扫描】。渲染?无所谓——
   **如果真有 ptext 元素,它走的是 Element 基类的 GDI 路径**
   (ExtTextOutW/DrawTextW),不是 DWrite【实锤,虚表比对】。
2. **TextGraphic 是"文本+侧图标"复合控件**,不是简单文本:
   Initialize 自动创建 **FlowLayout + 两个子元素**(内文本子元素
   @this+0xc8、侧图标子元素 @this+0xd0)【实锤,disasm】。
   语料零出现的原因:RichText+Element 组合覆盖了它的场景,
   但它作为 PText 的基类仍在注册链里活着【实锤+强推】。
3. **"PText→RichText 迁移"的真相**不是逐个控件的替换,而是
   **模板级的历史沉积**:控制面板家族(cp_*)的样式表里,
   PText 和 Element **并排写着同一套属性**——这是迁移未遂的
   活化石(§4)。
4. InternalRichText"host 注册"的旧说法在`07-richtext-and-the-dwrite-bridge.md` §6 已修正为
   **dui70 内部私有标签(TouchSelect::Register 搭车注册)**;
   本文 §5 给出与`03-host-registered-tags.md` 注册机制的完整对接。

---

## 1. 三个文本类的"户口本"

| | TextGraphic | PText | RichText(对照) |
|---|---|---|---|
| 符号数 | 19 | 15 | 91 |
| 继承 | `: Element` | `: TextGraphic` | `: Element` |
| 注册人 | PText::Register(先注册自己) | PText::Register | RegisterStandardControls 辅助块 |
| vtable 覆盖 | GetContentStringAsDisplayed / OnPropertyChanged / OnPropertyChanging | OnPropertyChanging(slot 4);Initialize 是普通虚方法转发(不在 40 槽 dump 内,由 ClassInfo 调用) | **Paint / GetContentSize / OnHosted / OnPropertyChanged / OnEvent** |
| 渲染路径 | Element::Paint(GDI) | Element::Paint(GDI) | RichText::Paint(DWrite) |
| 语料标签次数 | **0** | 78(全在样式表) | 495 |

【实锤:symbols.json 分类计数、classinfo-inheritance.txt、
vtables-ptext-textgraphic.txt 40 槽比对、全语料正则】

ClassInfo 模板实例的第二参数是基类,继承链权威证据:

```
TextGraphic : Element
PText : TextGraphic
RichText : Element
InternalRichText : RichText
TouchButton : RichText        ← 按钮文字也走 RichText 引擎!
```

【实锤,classinfo-inheritance.txt】

PText 的 15 个符号里值得一提的行为成员
(symbols.json,行为方法全部导出 EXP):
`Create`(0xDD6A0)、`Initialize`(0xDD720)、
`OnPropertyChanging`(0xDD8F0)、`SetDataEntry`(0xDD9D0)、
`Register`(0x79120)、`GetClassInfoW`(0xB8080)——
加上构造(0xB6C30/0xB6CB0)、析构(0xDD660)、
虚表 deleting dtor thunk(0xB7B60)、vftable@0x1118B0、
s_pClassInfo@0x184F80。导出面存在 = 它是宿主程序
可用的公共 API,不是死代码【实锤】。

---

## 2. 渲染路径:纯 GDI,每一行都有实锤

### 2.1 虚表铁证:PText 不碰 Paint

PText(vftable@0x1118B0)和 TextGraphic(vftable@0x111A18)
的虚表与 Element 基类的差异**只在身份槽**:

```
PText vtable(40 槽,@0x1118B0):
  slot 0:  PText::`vector deleting dtor'      ← 自己的(0xB7B60)
  slot 1:  Element::IsRTL
  slot 2:  Element::IsContentProtected
  slot 3:  TextGraphic::GetContentStringAsDisplayed (0xDD700) ← 继承自基类
  slot 4:  PText::OnPropertyChanging (0xDD8F0) ← 自己的
  slot 6:  TextGraphic::OnPropertyChanged (0xDD800) ← 继承
  slot 14: Element::Paint        (0x18000D450) ← 不覆盖!
  slot 15: Element::GetContentSize(0x18000EDB0)← 不覆盖!
  slot 29: Element::OnHosted     (0x18003C1F0) ← 不覆盖(RichText 覆盖了)
  slot 35: PText::GetClassInfoPtr(0xB8080)     ← 自己的
  其余 35 槽 = Element/TextGraphic 基类实现
```

【实锤,vtables-ptext-textgraphic.txt 全 40 槽 dump;
slot 7/27/28 的最近符号匹配(CallstackTracker/Progress 等)
是无名私有函数的误标,已知问题,不影响 slot 14/15/29 的结论
——这三个槽由符号表直接确认】

对照 RichText:slot 14 = RichText::Paint、slot 15 =
RichText::GetContentSize、slot 29 = RichText::OnHosted
(`07-richtext-and-the-dwrite-bridge.md` §3)。**分岔点就在虚表**:同一棵元素树里,
ptext 元素画文本走 Element 的 GDI 管线,richtext 元素走 DWrite。

### 2.2 Element 的 GDI 文本管线(指令级)

调用链(全部实锤,行号见 `.local/build/p2-text/`):

```
Element::Paint (0xD450)
 └─ Element::PaintContent (0xE390)
     └─ Element::PaintStringContent (0xCC40)   ← 文本在这里
```

(PaintContent→PaintStringContent 的调用点:全量反汇编
0x18000E452【实锤】。)

`PaintStringContent` 的完整 GDI 序列:

| 步骤 | 调用 | 反汇编行 |
|---|---|---|
| 取字体属性 | GetFontSize(0x11080)→FontQualityProp→FontStyleProp→FontWeightProp 逐个 GetValue | paintstring:69-109 |
| **取 HFONT** | FontCache 命中或 CreateFontIndirectW | 见 §2.3 |
| SelectObject(HFONT 进 DC) | `*0x180118F58` | paintstring:138 |
| 算颜色 | ARGBColorFromEnumI(0xEB90,gtc 主题色),`btsl $0x19` 设 alpha | paintstring:163-177 |
| SetTextColor | `*0x180119070` | paintstring:175 |
| SetBkMode(TRANSPARENT) | `*0x180119068`(edx=1) | paintstring:182 |
| overhang 内边距 | OverhangProp 读取,字号的 1/3 系数(0x2AAAAAAB 魔数) | paintstring:197-236 |
| SetTextAlign | `*0x180118F40`(对齐映射 contentalign&3) | paintstring:293 |
| **简单对齐分支** | **ExtTextOutW** `*0x1801190B8` | paintstring:318 |
| **复杂分支(主题字体)** | GetTheme→GetTextGlowSize→**BeginBufferedPaint**(延迟导入 0x1953F8)→组装 DTTOPTS(cbSize=0x48、dwFlags=0x2801 含 DTT_GLOWSIZE/DTT_COMPOSITED、iGlowSize@+0x34,uxtheme.h 逐字段核对)→**DrawThemeTextEx**(延迟导入 0x1953D0)→**EndBufferedPaint**(0x195410) | paintstring:398-469 |
| **阴影分支** | GetShadowIntensity→**DrawShadowTextEx**(0xB05E0,导出 C API) | paintstring:473-493 |
| **回落分支** | **DrawTextW** `*0x1801193D8` | paintstring:505 |

IAT/延迟导入槽位全部经 symbols.json 对号:
0x118F58=SelectObject、0x119070=SetTextColor、
0x119068=SetBkMode、0x1190B8=ExtTextOutW、
0x1193D8=DrawTextW、0x1953F8=BeginBufferedPaint、
0x1953D0=DrawThemeTextEx、0x195410=EndBufferedPaint【实锤】。

**这就是"PText 渲染走什么"的完整答案**:不走 DWrite、
不走 GDI+(duser 的 GDI+ 延迟导入只有混合绘制函数,
连 GdipDrawString 都没有——见 duser-render-internals.md §4.1
的 38 函数清单),是**教科书级 GDI 文本管线**,外加
UxTheme 的 BufferedPaint 三明治给主题字体发光效果。

测量侧同样:Element::GetContentSize(0xEDB0)调用
**GetTextExtentPoint32W**(0x18000F071)和
**DrawTextW+DT_CALCRECT**(0x18000F144,`btsl $0xa`
即置 DT_CALCRECT=0x400 位)【实锤】。
PushButton::GetContentSize 还用 GdiGetCharDimensions
(0x1800D7FF6)——GDI 家族的各个测量函数都在用。

### 2.3 HFONT 缓存:FontCacheImpl

GDI 路径的字体对象是 HFONT,dui70 有专门的缓存:

- `FontCacheImpl::CheckOutFont`(0x198C0)——查缓存,
  miss 时 **CreateFontIndirectW**(调用点 0x180019AE8)
  【实锤】;
- `FontCacheImpl::CheckInFont`(0x6E4D0)——归还;
- `HWNDHost::GetFont`(0x1A850)——HWND 宿主侧入口,
  同样 CreateFontIndirectW(0x18001A958)【实锤】。

对照 DWrite 侧的 RichTextCache(字形运行级缓存,
`07-richtext-and-the-dwrite-bridge.md` §5):**两代缓存对应两代排版引擎**——
HFONT 缓存的是"字体选择",RichTextCache 缓存的是
"光栅化结果"。这个对照是"两个时代"最浓缩的注脚【强推】。

### 2.4 诚实标注的部分

§2.2 的链条是**静态分析**结论:每条 call 指令都指到了
正确的 IAT 槽,但**没有运行时断点验证**过 ptext 元素真的
走到 PaintStringContent(语料里没有 ptext 实例,本仓库的
UITest 也没有文本用例)。缺的最后一环是"虚表 slot 14 在
运行时确实解析到 0x18000D450"——这是虚表 dump 的直接推论,
置信度很高,但按分级规矩标【实锤(静态)+未动态验证】。

---

## 3. TextGraphic 解剖:为什么它"零出现"却不能删

### 3.1 Initialize 里的自动组装(反汇编全文)

`TextGraphic::Initialize`(0xDD730):

```asm
1800DD74A: callq 0x18003E190          ; Element::Initialize
1800DD773: callq 0x180061200          ; FlowLayout::Create(false,0,0,0)
1800DD786: callq 0x1800612C0          ; Element::SetLayout —— 自动挂流式布局
1800DD78B: leaq 0xd0(%rdi), %rsi      ; &this->0xd0
1800DD79D: callq 0x180067C24          ; 在 this+0xd0 创建子元素
1800DD7AE: callq 0x18001D670          ; Element::Add —— 挂为子元素
1800DD7B3: leaq 0xc8(%rdi), %rsi      ; &this->0xc8
1800DD7C5: callq 0x180067C24          ; 在 this+0xc8 创建子元素
1800DD7D6: callq 0x18001D670          ; Element::Add
```

【实锤,disasm】**TextGraphic 是复合控件**:构造即自带
FlowLayout、内文本元素(指针存 this+0xc8)、侧图标元素
(this+0xd0)。佐证链:

- `GetContentStringAsDisplayed`(0xDD700,vtable slot 3
  覆盖)= `this->0xc8 子元素->GetContentString()`
  (disasm:`movq 0xc8(%rcx),%rcx; … 0x18(%rax); jmp CFG`
  ——调子元素虚表 slot 3)【实锤】;
- `SideGraphicProp`(0xDDC30,静态方法,EXP)——
  "侧图标"属性的 PropertyInfo 存在【实锤】;
- `OnPropertyChanged`(0xDD800)做**属性转发**,两条道:
  ①ClassProp(0x108858,name 字符串读出 L"Class")变化且
  新值 type==5(**字符串**,§2.2 的枚举:CreateString 写
  `orl $0x5`)→ 把新 class 值 `_SetValue` 给
  **this+0xc8 内文本子元素**(disasm 0x1800DD840-0x1800DD87F);
  ②SideGraphicProp 变化且新值 type==0xB(**图形**,
  CreateGraphic 工厂写 0xB)→ 把图形值 `_SetValue` 给
  **this+0xd0 侧图标子元素**(disasm 0x1800DD88E-0x1800DD8C8,
  用的正是 ContentProp@0x180106E20 的 PropertyInfo——
  给子元素设 content)【实锤】。

也就是说:宿主对 TextGraphic 设的 class 和 sidegraphic,
都被原样转发到两个子元素上——TextGraphic 自己只是个
**转发壳 + FlowLayout 容器**。

### 3.2 PText 在其上加的一层:数据绑定拦截器

`PText::Initialize`(0xDD720)整个函数只有一条指令:
`jmp TextGraphic::Initialize`——**纯转发**【实锤】。

PText 的真正增量在 `OnPropertyChanging`(0xDD8F0):

```asm
1800DD8FA: leaq 0x180106E20(%rip), %rax   ; ContentProp 的 PropertyInfo
1800DD904: cmpq %rax, %rdx                 ; 改的是 content?
1800DD907: jne  转发 TextGraphic::OnPropertyChanging
           ; 是 content 且新值 type==5(字符串!§2.2 枚举):
1800DD91E: callq *0x180195310              ; SysFreeString(this+0xe0)
1800DD92E: callq *0x180195320              ; SysAllocString(新值+0x8 …BSTR)
1800DD93A: movq %rax, 0xe0(%rbx)           ; 存 this+0xe0
1800DD946: movq 0xc8(%rbx), %rcx           ; 内文本子元素
1800DD950: callq 0x180032600               ; Element::SetContentString(子, 新串)
1800DD955: movb $0, %al                    ; return false —— 拦下!
```

【实锤,disasm】语义:**当 content 属性被赋一个字符串值时,
PText 拒绝自己持有它(return false 拦截属性变更),转手
SysAllocString 一份 BSTR 缓存在 this+0xe0,并把字符串
塞给 this+0xc8 的内文本子元素**。PText 自己的 content
永远是空的——**显示文本住在子元素里**。
配合 `SetDataEntry`(0xDD9D0:把 `IDataEntry*` 存 this+0xd8,
读 this+0xe0 的旧 BSTR(SysStringLen),用 0x18001A218
分配助手(len+1 / len+0x104=MAX_PATH 两种规格)拼缓冲,
并扫描 `0x25`(`'%'` 疑似格式占位符)——把数据条目格式化
成显示串,disasm 0x1800DD9D0-0x1800DDAC0)——
**PText 是 TextGraphic 的"数据绑定版"**:接 IDataEntry、
把数据条目转成子元素的显示内容
【实锤:调用序列与 0xd8/0xe0 落点;强推:IDataEntry
完整协议与 % 格式语义未反完】。

### 3.3 为什么语料零出现

TextGraphic/PText 需要**程序侧配合**(SetDataEntry 或
graphic content),XML 声明式用不上它的独门能力;
而它的"文本+侧图标"场景,后来 `<Button>`(含图标+文字)
和 RichText+Element 组合都能覆盖。于是:
标签没人写 → 语料零出现;但类没删(导出面、注册链都在),
因为删导出会破坏二进制兼容【强推】。

---

## 4. 迁移考古:样式表里的活化石

### 4.1 决定性统计:78/78 全在样式表

全语料扫描(149 个 XML,stylesheets 区间内外分别计数):

| 标签 | 样式表内 | 元素树中 |
|---|---|---|
| PText | **78** | **0** |
| RichText | 225 | **270** |

【实锤;初扫时 fontext 报过 1 次元素树,复核是该文件
`<Stylesheets>` 大小写导致区间误判,修正为 0】

PText 的 78 次集中在控制面板家族的 `<style>` 块:
`cp_content_text`(61 次)为绝对大头,其余是
`wuapp_*`(Windows Update 面板,8 次)
【实锤,if-class 统计】。

### 4.2 活化石长什么样(SpaceControl L43-46)

```xml
<if class="cp_content_text">
  <Element font="gtf(CONTROLPANELSTYLE, 6, 0)"
           foreground="gtc(CONTROLPANELSTYLE,6,0,3803)"
           contentalign="wrapleft" accessible="true" accRole="statictext"/>
  <PText  font="gtf(CONTROLPANELSTYLE, 6, 0)"
          foreground="gtc(CONTROLPANELSTYLE,6,0,3803)"
          contentalign="wrapleft" accessible="true" accRole="statictext"/>
</if>
```

【实锤,docs/duixml-corpus/SpaceControl/UIFILE_202.xml】

**两行属性一字不差**。这个模式(SpaceControl/DiagCpl/fhcpl/
RADCUI/fontext/recovery/sdcpl/taskbarcpl/werconcpl/…17 个 DLL)
是同一份"控制面板样式模板"复制传播的结果:
模板的历史主人用过 ptext 元素,后来元素全换成了 Element,
但**样式规则里的 `<PText>` 行没人记得删**——
删了也不报错(样式规则只是"当出现这个标签时应用这些属性",
`01-duixmlparser-xml-to-element-tree.md` §6;标签不出现,规则就是死重)。

PText 属性统计(78 次):font 74、foreground 74、
contentalign 72、accessible 69、accrole 69、background 5、
shortcut 1、enabled 1——**清一色 Element 层通用属性,
没有一条 PText 专属属性**(它没有自己的 PropertyInfo 表!)
【实锤】。这从侧面证实:样式表里的 PText 行已经是
"空壳标签",模板作者只是没清理。

### 4.3 那"迁移"到底发生了吗?

更准确的历史叙事【强推,综合证据】:

1. **早期**(Vista 前后的原型阶段):TextGraphic/PText 是
   正经的文本控件,GDI 渲染,程序侧 SetDataEntry 驱动;
2. **RichText 出现**(Win7 时代,DirectUI 随 dui70 定型):
   DWrite 引擎整体接管文本排版,Paint/GetContentSize 双覆盖;
   新 UI(WebcamUi/phoneactivate/InputSwitch 这些 Win8+ 模块)
   全用 RichText;
3. **旧模板没人动**:控制面板家族的样式表从上一代抄过来,
   PText 死行随模板扩散——这就是今天看到的"17 DLL 还在用
   PText"。**没有任何一个模块在"用"PText;它们只是"带着"
   PText 的尸体**【强推——但这有反证可能:若某宿主程序
   在运行时动态创建 ptext 元素(C++ 侧 Create),语料就看不到。
   列为未知问题 2】。

对照物:RichText 在元素树里 270 次真身实例,
在样式表里还有 225 次规则——**新引擎两种用法都活跃**,
和 PText 的"纯样式表"形成断代差【实锤】。

---

## 5. InternalRichText 的"host 注册"正名

`03-host-registered-tags.md`(宿主注册标签)把 InternalRichText 归进
"dui70 里没有公共认知的标签"一档,并推测与宿主有关。
本任务把注册机制挖穿了,结论(`07-richtext-and-the-dwrite-bridge.md` §6 的补充视角):

1. **注册人**:`TouchSelect::Register`(0x67B0)内部的
   第 4 个子注册块(0x180006BF4)——`ClassExist(...,
   L"InternalRichText", ...)` → 创建
   `ClassInfo<InternalRichText, RichText>` → 存
   `s_pClassInfo@0x183C70`【实锤,
   disasm-touchselect-register.txt:325-350】;
2. **注册时机**:RegisterStandardControls(0x5890)调
   TouchSelect::Register(调用点 0x1800059DE),同一批还有
   RichText 本体的注册(辅助块 0x180006CF4,字符串
   L"RichText"@0x1801233A8)【实锤】;
3. **行为**:InternalRichText 的 40 槽虚表与 RichText
   **只有 2 槽不同**(slot 0 析构、slot 35 GetClassInfoW
   /GetClassInfoPtr)——零行为覆盖,纯"私有标签名"
   【实锤,vtable dump 比对】。

所以"host 注册"的准确说法是:**dui70 私有标签**——
它进了全局类表(所以 msctfuimanager 这种同体系宿主
能在样式表里写它,dui70 自己的 IMMERSIVESTYLES 也用它
画滚动条箭头字形,`07-richtext-and-the-dwrite-bridge.md` §6.1),但它不是面向第三方
的公开标签(不在文档、`03-host-registered-tags.md` §2 的 154 未知标签扫描里
它能被找到恰说明公共认知缺失)。
`03-host-registered-tags.md` §3 的注册契约(ClassExist→new ClassInfo→Initialize)
对它完全适用——它就是那份契约的一个内部使用者
【实锤+`03-host-registered-tags.md` 交叉引用】。

---

## 6. 未知问题清单

1. **PText 运行时实例是否存在**:语料没有 ptext 元素,
   但无法排除某宿主 EXE 在 C++ 侧动态 `PText::Create`。
   若存在,§4.3 的"尸体"叙事要软化成"样式表侧已死"。
   验证方法:对 17 个 DLL 的宿主做符号扫描(本仓库语料
   只有 UIFILE,没有宿主二进制)。
2. **IDataEntry 协议**:PText::SetDataEntry(0xDD9D0)
   反出来的骨架:IDataEntry*@0xd8、BSTR 缓存@0xe0、
   0x25(`'%'`)扫描疑似格式占位符;IDataEntry 接口的完整
   方法表(取字符串/取图标/通知)与 % 格式语义未反完。
   它是"旧数据绑定体系"的钥匙,值得单独一挖。
3. **TextGraphic 两个子元素的类**:0x180067C24 工厂
   造的子元素具体是什么类(Element?专用图形类?)
   没有确认——按槽位偏移反推是普通 Element
   【强推】。
4. **DrawShadowTextEx(0xB05E0)/DUIDrawShadowText(0xB0590)
   的导出意图**:这两个 C API 是导出面里少见的"文本绘制"
   函数,除 PaintStringContent 内部调用外谁在用?
   (猜测:也给第三方宿主画 Aero 风格阴影字。)
5. **FontCacheImpl 的键与上限**:CheckOutFont 缓存键
   (LOGFONT 的哪些字段参与 hash)、缓存上限/LRU 策略
   未反——对性能考古有意义,对语义无影响。
6. **§2.4 所述的动态验证缺失**:整条 GDI 管线是静态证据,
   没有运行时确认(与`07-richtext-and-the-dwrite-bridge.md` 未知问题 8 同源)。

---

## 7. 证据索引

| 结论 | 证据 |
|---|---|
| PText 78 次/17 DLL、全部在 stylesheets 内 | 全语料 stylesheets 区间扫描(fontext 大小写误判已复核修正)【实锤】 |
| RichText 225 样式表/270 元素实例 | 同上【实锤】 |
| cp_content_text 61 次、wuapp_* 8 次 | if-class 块统计【实锤】 |
| PText 无专属 PropertyInfo(属性全是 Element 通用) | 78 次属性正则 + symbols.json(PText 无 *Prop 符号)【实锤】 |
| 双声明并排(SpaceControl L43-46) | 语料原文【实锤】 |
| PText/TextGraphic vtable 不覆盖 Paint/GetContentSize(slot 14/15=Element 实现) | vtables-ptext-textgraphic.txt 40 槽 dump【实锤】 |
| Paint→PaintContent→PaintStringContent 调用链 | 0x18000D5FF、0x18000E452 调用点【实锤】 |
| GDI 管线八调用(SelectObject/SetTextColor/SetBkMode/SetTextAlign/ExtTextOutW/DrawTextW/BufferedPaint×3/DrawShadowTextEx) | disasm-element-paintstring.txt + IAT/延迟导入槽位对号(symbols.json)【实锤】 |
| ExtTextOutW@0x18000D0B6、DrawTextW@0x18000D395 | disasm-element-paintstring.txt:318/505【实锤】 |
| DrawThemeTextEx 参数(DTTOPTS cbSize=0x48、dwFlags=0x2801、iGlowSize@+0x34) | paintstring:424-454 结构组装 + uxtheme.h DTTOPTS 布局【实锤】 |
| Element::GetContentSize 用 GetTextExtentPoint32W+DrawTextW(DT_CALCRECT,bts 0xa) | 0x18000F071、0x18000F144【实锤】 |
| FontCacheImpl::CheckOutFont / HWNDHost::GetFont 调 CreateFontIndirectW | 0x180019AE8、0x18001A958【实锤】 |
| duser 无 GdipDrawString(文本不走 GDI+) | duser 38 个 GDI+ 延迟导入清单(duser-render-internals.md §4.1)【实锤】 |
| TextGraphic::Initialize 自动造 FlowLayout+双子元素 | disasm 0x1800DD730-0x1800DD7D6【实锤】 |
| Value 类型枚举:5=字符串(CreateString `orl $0x5`)、0xB=图形(CreateGraphic 路径 `orl $0xB`) | disasm 0x180015297、0x180053A09【实锤】 |
| TextGraphic::OnPropertyChanged 双转发:ClassProp(type5)→子元素 0xc8;SideGraphicProp(type0xB)→子元素 0xd0(content) | disasm 0x1800DD840-0x1800DD8C8;prop 名 L"Class"@0x108858 读出【实锤】 |
| PText::Initialize = jmp TextGraphic::Initialize | disasm 0x1800DD720【实锤】 |
| PText::OnPropertyChanging 拦截字符串 content→SysAllocString 缓存 0xe0→子元素 SetContentString→return false | disasm 0x1800DD8F0-0x1800DD957【实锤】 |
| 0x180106E20 = "Content" 的 PropertyInfo | 指针链 dump:0x106E20→0x1224B8→L"Content"【实锤】 |
| PText::SetDataEntry 存 IDataEntry 于 +0xd8、BSTR 缓存 +0xe0、'%'(0x25)扫描 | disasm 0x1800DD9D0-0x1800DDAC0【实锤(协议细节强推)】 |
| InternalRichText 注册链(TouchSelect::Register 第 4 子块/ClassExist/RichText 字符串搭车) | disasm-touchselect-register.txt、richtext-register-helper.txt【实锤】 |
| InternalRichText vtable 仅 2 槽异于 RichText | vtable-*.txt 比对【实锤】 |

**复现材料**:`.local/build/p2-text/` 下
disasm-element-paintstring.txt(GDI 管线全文)、
vtables-ptext-textgraphic.txt、vtable-RichText.txt、
vtable-InternalRichText.txt、disasm-ptext-register.txt、
disasm-touchselect-register.txt、disasm-richtext-register-helper.txt、
disasm-checkoutfont.txt、disasm-setdataentry.txt、
disasm-creategraphic.txt / disasm-createstring.txt(Value 类型字);
统计脚本为一次性 pwsh+python 内联
(关键数字都已在正文引用)。

**相关材料**:
- `07-richtext-and-the-dwrite-bridge.md`《RichText 与 DWrite 桥》(新引擎全貌;§6 同源)
- `01-duixmlparser-xml-to-element-tree.md`《duixml 是怎么被吃进去的》§3(标签注册)、§6(样式规则语义)
- `03-host-registered-tags.md`《宿主注册标签》§3(ClassExist 契约;本文 §5 引用)
- `13-layout-landscape.md`/`14-layout-protocol.md`(布局——TextGraphic 自动 FlowLayout 的语境)
- `.local/audit/duser-render-internals.md` §4.1(GDI+ 延迟导入清单)
