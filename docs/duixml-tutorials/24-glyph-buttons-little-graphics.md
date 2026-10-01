# 教程 24:Glyph 们 —— 按钮的小图形搭档

> 系列教程第 24 篇(P1 按钮与选择三部曲之三)。前置:`22-buttons-three-generations.md`(按钮三代)、`23-selector-and-itemlist.md`(Selector)。
> 主题:复选勾、单选点、折叠箭头——这些小图形为什么是独立的类?CheckBoxGlyph/RadioButtonGlyph/ExpandoButtonGlyph/TouchCheckBoxGlyph 四个类,三个语料零出现、一个 14 处。本文用 vtable 逐槽比对证明:**传统三 Glyph 是行为全空的"样式标签"**,TouchCheckBoxGlyph 也几乎如此——拆分动机是样式而非命中测试。这是"方法名考古"路线(API-only 类)的标准示范。

## 0. 全景:四个 Glyph 一张表

| 类 | 继承(.g.txt 实测) | 语料标签数 | vftable | 符号数 |
|---|---|---|---|---|
| CheckBoxGlyph | Button | **0** | 0x10F368 | 16 |
| RadioButtonGlyph | Button | **0** | 0x10F1F0 | 16 |
| ExpandoButtonGlyph | Button | **0** | 0x10F078 | 16 |
| TouchCheckBoxGlyph | TouchCheckBox | **14**(全部 dui70) | 0x112B80 | 13 |

四个类的符号表几乎一模一样:ctor ×2、Create ×2、GetClassInfoPtr/W、Initialize、Register、SetClassInfoPtr、dtor、vftable、operator=、s_pClassInfo——**没有 Click、没有 OnInput、没有 Paint(传统三件)/只有转发 Paint(Touch 版)**。这张"空"符号表本身就是第一个证据:它们不带行为。

(频次实测 `.local/corpus/class-usage.json`;传统三 Glyph 的标签在 149 个 UIFILE 里零出现——但注意,这不代表没人用,见 §2 的"匿名用法"之谜。)

---

## 1. 方法名考古:类名在说什么

**Glyph = 字形/小图形**。四个类名把用途说得直白:CheckBox 的勾、RadioButton 的点、Expando 的折叠箭头、TouchCheckBox 的勾。方法名考古(按 COMMON-CONTEXT §4.3 的 API-only 路线)在本文里**无事可做**——方法表里只有标配(Create/Register/Initialize…),没有任何自有方法名可供解读。这本身就是结论的一半:**Glyph 类的全部信息量在类名里,不在方法里**。

另一半信息在 .g.txt 的自有属性:

| 类 | 自有属性(排除 Button/Element 基类属性后) |
|---|---|
| CheckBoxGlyph | 无 |
| RadioButtonGlyph | 无 |
| ExpandoButtonGlyph | 无 |
| TouchCheckBoxGlyph | 无(TouchCheckBox 的 CheckedState 由父类持有) |

传统三 Glyph 连一个自有属性都没有。TouchCheckBoxGlyph 唯一的"内容"是继承来的:TouchCheckBox 的 CheckedState 属性(docs/TouchCheckBoxGlyphClass.g.txt 标注 Base Class TouchCheckBox,继承链 TouchCheckBoxGlyph → TouchCheckBox → TouchButton → RichText)。

---

## 2. 行为验证:与传统三 Glyph 的 vtable 逐槽比对【实锤】

理论假设"Glyph 是样式标签"必须经过行为验证。方法:**vtable 槽位比对**——如果 Glyph 类的虚函数全部与 Button 基类同地址,它就是零行为覆盖。

### 2.1 反汇编证据

- CheckBoxGlyph::Initialize(0x8B1D0)被 **ICF 折叠**为 `jmp Button::Initialize` 链上的一环(RadioButtonGlyph/ExpandoButtonGlyph/Thumb 的 Initialize 同为 0x8B1D0——四个"空"类共享同一个转发体);
- CheckBoxGlyph 的 OnLostDialogFocus/OnReceivedDialogFocus(0x66740)与 Button 的同名槽同址(同样是共享桩);
- 唯一不同址的槽:析构(每个类要销毁自己的 vftable/ClassInfo 注册)。

即:**CheckBoxGlyph/RadioButtonGlyph/ExpandoButtonGlyph 的 vtable 与 Button 的逐槽相同,仅析构槽例外**。这是编译器/链接器(ICF)对"零覆盖类"的标准产物——如果你写一个 `class CheckBoxGlyph : public Button {};`(不覆盖任何虚函数),得到的二进制就长这样。【实锤:vftable 数据比对 + ICF 同址】

### 2.2 那它们存在干什么?——样式表选择器

DirectUI 的样式系统按**类名(标签名)+ class/id 条件**匹配规则(`22-buttons-three-generations.md` §1.3 的 `<if id="atom(CheckBox)"><button …/>` 模式)。一个独立标签名 = 一个独立的样式挂钩。dui70 注册这四个类,等于在样式系统里预埋了四个语义槽:宿主可以写 `<checkboxglyph background="dtb(button,3,1)"/>`,规则匹配按标签精确命中,不用碰 `class=` 字符串。

但语料里**零处**这么用——真实代码用的是两条别的路线:

**路线 A:普通元素 + id 命中**(sharemediacpl/UIFILE_201.xml:203-205,宿主自建复选框视觉树):

```xml
<if id="atom(CheckBoxGlyph)">
  <element width="sysmetric(71)" height="sysmetric(72)"
           margin="rect(0rp,0rp,3rp,0rp)" contentalign="middleleft" layoutpos="left"/>
</if>
<if id="atom(CheckBoxLabel)">
  <element contentalign="middleleft" layoutpos="client"/>
</if>
```

sharemediacpl 的 CheckBoxButton(宿主注册标签)内部用两个**普通 element** 挂 id=atom(CheckBoxGlyph)/atom(CheckBoxLabel),样式表按 id 给"字形位"和"标签位"分别配属性——**名字叫 Glyph,身体是 element**。

**路线 B:普通 button + dtb 皮肤**(CertEnrollUI/UIFILE_130.xml:11-66 + 198-217):

```xml
<!-- 样式表:checkmark 的 12 态(dtb(button,3,1..12))与 radiomark 的 8 态(dtb(button,2,1..8)) -->
<if id="atom(checkmark)">
  <button width="sysmetric(71)" height="sysmetric(72)" background="dtb(button, 3, 1)"/>
  <if selected="true"> <button background="dtb(button, 3, 5)"/> … </if>
</if>
<!-- 实例:accessible 容器 + 两个子元素(mark 是 inactive button,文字在旁边) -->
<element resid="CheckBoxVisualTree" accessible="true" layout="borderlayout()" accRole="checkbutton">
  <button id="atom(checkmark)" layoutpos="left" active="inactive"/>
  <element id="atom(ButtonText)" layoutpos="left"/>
</element>
```

CertEnrollUI 的复选/单选字形是 `active="inactive"` 的**普通 button**(不收输入,纯显示 uxtheme 位图),外面包一个 accRole 的容器。duser 公共样式表(duser/UIFILE_1010.xml:63-146)的 atom(CheckBox)/class(CheckBox)/class(RadioButton)同款——`22-buttons-three-generations.md` §1.3 已引。

**结论**:传统三 Glyph 是 dui70 **注册了但生态没用**的样式挂钩——真实代码全部用"普通元素/button + id/class + dtb 皮肤"组合表达同样的结构。它们是语言设计者预留的语义化路线,实践选择了更轻的组合式路线。【实锤:语料零出现 + 路线 A/B 语料原文;"预留"定性为【强推】】

---

## 3. TouchCheckBoxGlyph:唯一有语料的 Glyph

### 3.1 XML 实例:dui70 的 TCB_Glyph 规则【实锤,语料】

TouchCheckBoxGlyph 的 14 处出现**全部在 dui70/UIFILE_IMMERSIVESTYLES.xml**(Light/Dark 两套 × 7 处)——它是 TouchCheckBox 的**官方皮肤**的一部分:

```xml
<!-- dui70/UIFILE_IMMERSIVESTYLES.xml:165-198(Light 套) -->
<TouchCheckBox contentalign="endellipsis" background="20575" foreground="20642"
               accessible="true" accrole="checkbutton" font="resstr(113, library(dui70.dll))"
               minsize="size(100rp,50rp)" padding="rect(0rp,12rp,0rp,0rp)"/>
<if checkedstate="unchecked"> <TouchCheckBox accdefaction="resstr(105,…)"/> </if>
<if checkedstate="checked">   <TouchCheckBox accdefaction="resstr(106,…)"/> </if>
<if enabled="false">          <TouchCheckBox foreground="20645"/> </if>
<if id="atom(TCB_Glyph)">
  <TouchCheckBoxGlyph contentalign="middlecenter" height="21rp" width="21rp"
                      background="20634" foreground="20646"
                      borderthickness="rect(2rp,2rp,2rp,2rp)" bordercolor="20638"
                      constrainlayout="NarrowClip" font="resstr(114, library(dui70.dll))"/>
  <if keyfocused="true">  <TouchCheckBoxGlyph contentalign="middlecenter|focusrect"/> </if>
  <if mousefocused="true"><TouchCheckBoxGlyph background="20635" …/> </if>
  <if pressed="true">     <TouchCheckBoxGlyph background="20636" …/> </if>
  <if enabled="false">    <TouchCheckBoxGlyph background="20637" …/> </if>
  <if checkedstate="checked">
    <TouchCheckBoxGlyph content="resstr(115, library(dui70.dll))"/>   <!-- ★ 勾 = 字体字形 -->
  </if>
</if>
<if id="atom(TCB_Label)">
  <richtext contentalign="wrapleft|endellipsis" padding="rect(8rp,0rp,8rp,0rp)"
            background="20575" constrainlayout="narrow"/>
</if>
```

**关键设计**:勾选态的"勾"不是位图——`content="resstr(115)"` 把字体字形(Segoe UI Symbol 的 ✓)设为内容,由 `font="resstr(114)"` 渲染。**未选中 = 空内容 + 边框盒子;选中 = 换内容**。这就是 Touch 时代 Glyph 的"字形"本义:它真的是 glyph(字体字符),而传统 Glyph 是 dtb 位图。

### 3.2 谁创建它:TouchCheckBox::Initialize 内建子树【实锤,反汇编】

TouchCheckBoxGlyph 不是 XML 写的——TouchCheckBox::Initialize(0x18005FFF0)自动创建:

```asm
18005fffd: callq TouchButton::Initialize      ; 先走基类
18006002b: callq FlowLayout::Create           ; 造 FlowLayout
180060050: callq _SetValue(LayoutProp, …)     ; 设给自己
…
18006005e: callq …                            ; _CreateAndAddGlyph(0x90D0C):
180090d26: callq …(0x180095cd8 区)            ;   Create(TouchCheckBoxGlyph)——创建 glyph 子元素
180090d36: leaq …# 0x180124138                ; L"TCB_Glyph"
180090d3d: callq SetID                        ;   glyph.SetID(L"TCB_Glyph")
180090d50: callq Element::Add                 ;   加为自己的子元素
; 随后 _CreateAndAddLabel(0xBC6A0)同构:richtext 子元素,SetID(L"TCB_Label")
```

字符串直读:0x180124138 = L"TCB_Glyph"。**TouchCheckBox 一出生就自带 TCB_Glyph(TouchCheckBoxGlyph)+ TCB_Label(RichText)两个孩子**——§3.1 的样式规则 `<if id="atom(TCB_Glyph)">` 正是为这棵内建子树准备的。宿主写 `<TouchCheckBox/>` 一个标签,得到完整的"勾盒 + 标签"结构。bdeunlock/UIFILE_201.xml:24/170 的用法印证:`<TouchCheckBox id="atom(checkboxautounlock)" content="resstr(4205)"/>` 只写 content(进 TCB_Label),皮肤全由 ImmersiveStyles 基表接管。

### 3.3 行为验证:TouchCheckBoxGlyph 也是"薄"类【实锤,反汇编】

- OnPropertyChanging(0x8F270)= `jmp Element::OnPropertyChanging`(无行为——注意不是 TouchCheckBox 的,是 Element 的);
- Paint(0xBC180)= 转发体(与 TouchCommandButton::Paint 0xBC190 相邻,同一 ICF 家族;真实绘制走 RichText 继承链的 DWrite 管线,`07-richtext-and-the-dwrite-bridge.md`);
- 有意思的对照:父类 TouchCheckBox 自己有真行为(OnEvent 的 ToggleOnClick 门控翻转、OnPropertyChanging、Paint 覆写,`22-buttons-three-generations.md` §3.4),**Glyph 子类把这些全部丢弃,只留壳**。

TouchCheckBoxGlyph 与传统三 Glyph 的唯一实质差异:**它有消费者**(dui70 自己的 IMMERSIVESTYLES 规则)和**它被父类自动实例化**(TCB_Glyph)。定性:同样是样式挂钩,但这个挂钩真的被挂上了东西。

---

## 4. 核心问题:拆 Glyph 是为了样式还是命中测试?

这是 outline §B5 的原题。两条假设的对决:

**假设"命中测试"**:拆出独立元素让勾/箭头可以单独响应点击(点勾才算,点文字不算)。
**假设"样式"**:拆出独立元素让小图形有自己的背景/边框/尺寸规则,与文字分开画。

裁决证据:

1. **传统 Glyph 是 Button 的零覆盖子类**——Button 本来就整块命中测试,拆一个"更小的 Button"不带来任何命中语义增益;若为命中测试,Glyph 应有独立 OnInput/命中区域覆写——**没有**(§2.1 vtable 全同);
2. **CertEnrollUI 的实践反例**:mark 用 `active="inactive"` 的 button——**显式关掉输入**,恰恰排除命中测试;
3. **sharemediacpl 的 glyph 拆分只配尺寸**:id=atom(CheckBoxGlyph) 规则里是 width/height/margin/contentalign/layoutpos——纯布局样式;
4. **TouchCheckBoxGlyph 的规则全部是视觉属性**:background/bordercolor/content/font 五态——勾盒的"状态皮肤"只有拆出独立元素才能写(一个元素的 background 在同一时刻只能有一个值,"盒子的底色"和"勾的颜色"必须分开);
5. **命中测试从来没有按 glyph 边界发生**:TouchCheckBox 的翻转门控在父类的 OnEvent(`22-buttons-three-generations.md` §3.4),比较的是 sender==self;点击落在 TCB_Glyph 或 TCB_Label 上,事件冒泡到 TouchCheckBox 后同样翻转——**子元素边界与命中语义无关**。

**结论:样式,不是命中测试。**【实锤:证据 1-3 为指令/语料级;证据 4-5 语料级。整体定性【强推】——"为什么拆"没有文档,但五条证据全部指向样式侧,命中测试侧零支持证据】

深层原因【强推,推断链】:DirectUI 的属性系统是"每元素一个 specified 值栈"(`18-properties-and-lifecycle.md`),没有 CSS 那种"一个元素多背景/伪元素"的表达力。要让"勾盒"和"标签"有独立的状态皮肤,唯一办法是**物理拆成两个元素**。Glyph 类就是给这个拆分提供语义化标签名的语言设施。WPF 后来用 ControlTemplate(单控件多部件模板)解决同一问题,DirectUI 时代还没有模板机制,拆元素是唯一路线——TouchCheckBox::Initialize 内建子树(§3.2)实际上就是"手写的 ControlTemplate":类即模板,Initialize 即 Instantiate。

---

## 5. 顺带发现(边界记录,不扩大调查)

- ExpandoButtonGlyph 的兄弟 Expando/Expandable 是真正的行为类(Expandable 有 ExpandedProp/SetExpanded 0x78C10,Expando 有 Arrow/Clipper 原子对)——折叠箭头的"行为版本"不在 Glyph 里,在 Expando 组合里。Expando 语料 45 处(SpaceControl 11 + CertEnrollUI 16 + WorkfoldersControl 14…),全部配 accessiblebutton 当箭头容器(SpaceControl/UIFILE_201.xml:213-226 的 ExpandoBar 模式)。Glyph 三兄弟与 Expando 是"同名不同命":一个留在语言层,一个活在生态里。
- msctfuimanager 的候选条目把 TouchButton 当"文字元素"用(`active="inactive"`,样式表按 CandidateItemText 规则配 foreground)——TouchButton 不当按钮、只当富文本标签。这印证`22-buttons-three-generations.md` 的论断:TouchButton : RichText 的真正含义是**按钮即文本**。

---

## 6. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | 传统三 Glyph 注册进 ClassInfo 却零语料——是"曾经有用法后被淘汰"还是"从未被用"? | 无法从二进制区分【猜想:预留未用?还是老版本 dui 语料缺失?】 | 考古旧版 Windows 的 UIFILE(win7 dui70 语料不在本仓库) |
| 2 | CheckBoxGlyph 的 Create 有两个(0xB2550/0xA91E0)——双工厂的分工? | 符号实锤;与其他类(Create×2)同构,语义未读 | 两个 Create 反汇编对照 |
| 3 | TouchCheckBoxGlyph::Paint 的转发目标链(经 0xBC180 到真实绘制) | 转发体实锤;完整到 DWrite 的路径未逐段跟 | 沿 0xBC180 单步(预计落进 RichText::Paint,`07-richtext-and-the-dwrite-bridge.md` §5) |
| 4 | ExpandoButtonGlyph 与 Expando 的 Arrow 原子(_atmArrow)是否共享 id 空间 | 两套符号各自实锤;关系未验证 | Expando::Initialize 反汇编 |

---

## 7. 小结

- **传统三 Glyph(CheckBox/RadioButton/ExpandoButtonGlyph)= Button 的零覆盖子类**,vtable 逐槽与 Button 相同(仅析构槽异),无自有属性无自有方法——纯样式挂钩,且**生态没用它**(真实代码用普通元素 + id/class + dtb 皮肤);
- **TouchCheckBoxGlyph = 有消费者的样式挂钩**:TouchCheckBox::Initialize 内建 TCB_Glyph/TCB_Label 子树,glyph 的勾是**字体字形**(content=resstr(115)),不是位图;但它同样薄(OnPropertyChanging 转发 Element、Paint 转发);
- **拆 Glyph 的动机是样式不是命中测试**:五条证据(vtable 零覆盖、active="inactive" 反例、纯布局/纯视觉规则、命中不按 glyph 边界)全部指向样式侧;
- 方法论示范:API-only 类的"行为验证"要落到 vtable 逐槽比对——符号表相同不等于行为相同,ICF 折叠地址是判据。

至此 P1 三部曲收官:按钮(`22-buttons-three-generations.md`)住在容器里(`23-selector-and-itemlist.md`),身边带着小图形(本文)。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| 四 Glyph 继承链(3×Button、1×TouchCheckBox) | .g.txt | docs/CheckBoxGlyphClass.g.txt、RadioButtonGlyphClass.g.txt、ExpandoButtonGlyphClass.g.txt、TouchCheckBoxGlyphClass.g.txt |
| 语料频次(0/0/0/14,14 全在 dui70) | 语料统计 | .local/corpus/class-usage.json |
| 传统 Glyph vtable ≈ Button(仅析构槽异;Initialize ICF 同址 0x8B1D0) | vftable 数据 + ICF 地址 | CheckBoxGlyph vftable 0x10F368、RadioButtonGlyph 0x10F1F0、ExpandoButtonGlyph 0x10F078;OnLost/OnReceivedDialogFocus 共享桩 0x66740 |
| 路线 A(普通元素 + id=Glyph) | 语料 | sharemediacpl/UIFILE_201.xml:174-205 |
| 路线 B(普通 button + dtb 12/8 态 + active="inactive") | 语料 | CertEnrollUI/UIFILE_130.xml:11-66/198-217;duser/UIFILE_1010.xml:63-146 |
| TCB_Glyph 规则五态 + 勾=字体字形 | 语料 | dui70/UIFILE_IMMERSIVESTYLES.xml:165-198(Light)、683-701(Dark) |
| TouchCheckBox::Initialize 内建 TCB_Glyph/TCB_Label | 反汇编 | 0x18005FFF0 → _CreateAndAddGlyph 0x180090D0C(SetID(L"TCB_Glyph")@0x180090D3D,字符串 0x180124138 直读)、_CreateAndAddLabel 0x1800BC6A0 |
| TouchCheckBoxGlyph 薄行为 | 反汇编 | OnPropertyChanging 0x18008F270 = jmp Element::OnPropertyChanging;Paint 0x1800BC180(转发体) |
| TouchCheckBox 的翻转在父类不在 Glyph | 引用 | `22-buttons-three-generations.md` §3.4(OnEvent 0x1800BBE80) |
| Expando 家族对照(行为在 Expando 不在 Glyph) | 符号 | Expando 23 符号(Arrow/Clipper/_atmArrow)、Expandable 17(ExpandedProp 0x71D50/SetExpanded 0x78C10)、语料 45 处 |
| TouchButton 当富文本标签用 | 语料 | msctfuimanager/UIFILE_16001.xml:86-95/277-289 |
