# 教程 23:Selector 与列表选择 —— 单选容器、ItemList 与虚拟化配合

> 系列教程第 23 篇(P1 按钮与选择三部曲之二)。前置:`17-events.md`(Event/UID 机制)、`18-properties-and-lifecycle.md`(属性系统)、`15-keyboard-navigation.md`(键盘导航)、`19-viewer-family.md`(Viewer 家族与 TSVEnableVirtualization)。
> 主题:按钮住在容器里,而"从一组里选一个"的容器语义由 Selector 家族承担。本文还原 Selection 属性的真实类型、SelectionChange 事件的发射路径、以及一个反直觉发现:**基类 Selector 自己不响应点击选择**——点击选择只活在 SelectorNoDefault 的覆盖里。再讲 ItemList 与 TouchScrollViewer 的虚拟化配合,以及 WrappingList/Repeater 在这条线上的位置。

## 0. 全景:家族树与语料分布

```
Element
 └── Selector                     (22 符号;Selection 属性 + SelectionChange 事件)
      ├── SelectorNoDefault       (18 符号;点击选择 + 焦点选择特化)
      └── ItemList                (14 符号;KeyWithin 同步 + Reorderable)
           └── WrappingList       (21 符号;循环列表,TouchSelect 弹层用它)
Element → TouchScrollViewer(视口;虚拟化引擎)      ← 19-viewer-family.md
Element → Repeater(: Macro;数据模板引擎)          ← 本文 §6 简述
```

| 标签 | 语料数 | 分布 |
|---|---|---|
| selector | 14 | CertEnrollUI 10、fvewiz 2、hgcpl 1、sharemediacpl 1 |
| SelectorNoDefault | 1 | DiagCpl(UIFILE_217) |
| ItemList | 5 | InputSwitch 1、msctfuimanager 4 |
| WrappingList | 0(标签层;dui70 样式表 2 处按 id 命中) | —(由 TouchSelect 内部创建) |
| repeater | 5 | fvecpl(全部) |

(频次实测 `.local/corpus/class-usage.json`;继承链 `docs/SelectorClass.g.txt`/`ItemListClass.g.txt`/`WrappingListClass.g.txt`。)

一个诚实的开场:**这个家族在语料里是稀有动物**。Selector 只有 14 处,SelectorNoDefault 全语料 1 处——因为大多数"列表"场景走了别的路(CCListView 寄生系统控件、Repeater 数据模板、或宿主 C++ 侧动态构建)。但 Selector 家族的机制恰恰是理解 DirectUI"选择语义"的钥匙:它把"选中"实现为一个**指向子元素的属性**,这个设计贯穿了 UIA 的 SelectionProvider 桥(`05-uia-pattern-providers.md` §4 的 SelectorSelectionProxy/SelectorSelectionItemProxy 特化)。

---

## 1. XML 实例:三种真实用法

### 1.1 用法一:单选按钮组(最常见)

fvewiz/UIFILE_20.xml:378-381(BitLocker 加密类型单选):

```xml
<selector id="atom(selectorEncryptionType)" layoutpos="top" layout="borderlayout()" accessible="true">
  <CCRadioButton id="atom(radioDataOnlyEncryption)" layoutpos="top" content="resstr(2174)"
                 accname="resstr(2173)" shortcut="auto" accessible="true" sheet="local"/>
  <CCRadioButton id="atom(radioFullEncryption)" layoutpos="top" content="resstr(2176)"
                 accname="resstr(2175)" shortcut="auto" accessible="true" sheet="local"/>
</selector>
```

hgcpl/UIFILE_202.xml:255-267 是同款(网络发现单选组,CCRadioButton Button0/1/2 + 各自的选项区);CertEnrollUI/UIFILE_130.xml:1829-1841(密钥格式单选组,`selected="true"` 给出**XML 层的初始选中**)。

**为什么单选组要 selector 包?**CCRadioButton 是寄生 HWND(`22-buttons-three-generations.md` §2),Win32 单选的自动互斥依赖 WS_GROUP——而 selector 在 Element 层再给一道互斥:SelectorNoDefault 的 SetSelection 只接受直接子元素(§3.2),选中一个就自动取消前一个。【强推:语料模式 + 机制一致;Win32 侧分组与 dui 侧互斥的分工未逐行验证】

### 1.2 用法二:静态候选列表(手写子元素)

CertEnrollUI/UIFILE_130.xml:909-930(密钥用途九选一):

```xml
<Selector id="atom(AvailableKeyUsage)" sheet="mainss" layout="borderlayout()">
  <button class="ListItem" content="resstr(1228)"/>
  <button class="ListItem" content="resstr(1229)"/>
  …(共 9 个,样式表 158-169 行给 class="ListItem" 配 selected/keyfocused 皮肤)
</Selector>
```

注意子元素是**普通 button**——selector 不挑子元素类型,任何 Element 都行。选中态皮肤(CertEnrollUI 样式表 162-168 行 `<if selected="true"><button background="highlight"/>`)靠 Selector 把子元素的 Selected 属性写真(§2.2)。

### 1.3 用法三:空壳列表(运行时填充)

CertEnrollUI/UIFILE_130.xml:723-725(序列号列表):

```xml
<ScrollViewer … accRole="List" accName="resstr(1202)" height="100rp">
  <selector id="atom(SNListBox)" Layout="BorderLayout()">
  </selector>                          <!-- 空!子元素全由 C++ 侧运行时 Add -->
</ScrollViewer>
```

同一个文件里 SANListBox/CustExtList/AvailableEKU 等共 6 处都是这个模式。**XML 里的 selector 只声明容器与无障碍语义(accRole="List" 在 ScrollViewer 上),内容是宿主的**。这就是 Selector 语料稀少却重要的原因:它是 C++ 动态列表的容器协议。

### 1.4 全语料唯一的 SelectorNoDefault

DiagCpl/UIFILE_217.xml:173-176(疑难解答"自动修复"开关):

```xml
<SelectorNoDefault id="atom(autoSelector)" layoutpos="top" layout="borderlayout()">
  <CCRadioButton id="atom(autoOn)" layoutpos="top" accname="resstr(213)" content="resstr(54)"
                 shortcut="auto" background="themeable(dtb(CONTROLPANEL,2,0),window)"/>
  <CCRadioButton id="atom(autoOff)" layoutpos="top" accname="resstr(214)" content="resstr(55)"
                 shortcut="auto" background="themeable(dtb(CONTROLPANEL,2,0),window)"/>
</SelectorNoDefault>
```

同样是单选组——但它选了 NoDefault 变体。§3 会解释两者差异,以及为什么"名字看起来更弱"的 NoDefault 反而是**功能更全**的那个。

### 1.5 ItemList:Win8 触控列表

InputSwitch/UIFILE_104.xml:10-14(输入法切换弹层,最小实例):

```xml
<TouchScrollViewer id="atom(ConsentUXListScrollViewer)" AllowArrowOut="true" layoutpos="client"
                   InteractionMode="TranslateY|Inertia" YScrollable="false" XScrollable="false"
                   xbarvisibility="never" YBarVisibility="AsNeeded" accessible="true"
                   accrole="pane" active="mouse|pointer">
  <element id="atom(InputMethodsListContainer)" behaviors="PVL::ImplicitAnimation()"
           layoutpos="client" layout="borderlayout()" active="pointer" accessible="true" accrole="list">
    <ItemList id="atom(InputMethodsList)" behaviors="PVL::ImplicitAnimation()"
              active="pointer" layoutpos="none" accrole="list" accessible="true"
              layout="gridlayout(-1, 1)"/>
  </element>
</TouchScrollViewer>
```

msctfuimanager/UIFILE_16001.xml:40-58(输入法候选词列表)是更丰满的版本——ItemList 里 SnapMode="Single" 让弹层吸附到候选词条:

```xml
<TouchScrollViewer id="atom(CandidateList.ScrollViewer)" active="Pointer | Mouse | nosyncfocus"
                   layout="ninegridlayout()" layoutpos="top" sheet="ScrollViewerStyle"
                   XScrollable="false" YScrollable="true" YBarVisibility="asneeded"
                   InteractionMode="TranslateY | Inertia" SnapMode="Single">
  <ItemList id="atom(CandidateList.ScrollViewer.Items)" active="mouse | pointer | nosyncfocus"
            layout="gridlayout(-1,1)" layoutpos="nineclient" sheet="VerticalCandidatePaneItemsStyle"
            visible="true"/>
</TouchScrollViewer>
```

两个语料实例 ItemList 全部用 `layout="gridlayout(-1, 1)"`(单列网格;-1 = 自动行数)。候选词条目是宿主注册的 CCandidateItem 模板(resid,运行时展开),内部包 TouchButton(msctfuimanager 16001:73-96)。

---

## 2. Selector 基类:Selection 属性与 SelectionChange 事件

### 2.1 属性/方法表(22 符号)

| 成员 | RVA | 说明 |
|---|---|---|
| SelectionProp | 0x80720 | **Selection 属性的 PropertyInfo(类型 ElementRef!)** |
| SelectionChange | 0x73010 | 事件 UID 工厂 |
| SetSelection / GetSelection | 0x7C130 / 0x73030 | 属性对(虚槽 0x168) |
| OnPropertyChanged | 0x72E20 | Selection 变化 → 发事件 + 同步子元素(§2.2) |
| OnKeyFocusMoved | 0x6E1B0 | 焦点迁移 → 选中(§3.1) |
| OnInput | 0x86D10 | **只吞 Tab**(§3.3) |
| OnEvent | 0x82CD0 | ICF 折叠为 `jmp Element::OnEvent`——**基类不处理点击!**(§3.2) |
| GetAdjacent | 0xD38B0 | 导航:从当前选中项出发找邻居(§4) |
| Initialize / Create / Register | 0x8EFB0 / 0xD3880 / 0x3560 | 标配 |
| vftable | 0x10ADF0 | — |

XML 属性面(.g.txt):自有属性只有一个 `[Selection]: Element`——**一个指向子元素的引用型属性**。这与"selected 布尔们撒在每个子元素上"的 CSS 式思路完全不同:选择态的**权威副本在容器上**,子元素的 Selected 只是它的投影。

### 2.2 行为机制【实锤,反汇编】

**SetSelection(0x18007C130)——把子元素包成 Value 再走标准属性管道**:

```asm
18007c140: callq Value::CreateElementRef   ; 子元素指针 → ElementRef 型 Value
18007c148: testq %rax, %rax
18007c14b: je    …                         ; 分配失败 → 0x8007000E(E_OUTOFMEMORY)
18007c15b: leaq  0x180080720 …             ; SelectionProp
18007c165: callq _SetValue                ; 标准 SetValue 漏斗(18-properties-and-lifecycle.md §3)
18007c16f: callq Value::Release
```

即 `SetSelection(child)` = `SetValue(Selection, ElementRef(child))`——没有任何私有状态,选择就是一个普通属性值,走完整的属性系统(事务登记、OnPropertyChanged、监听器通知)。

**OnPropertyChanged(0x180072E20)——两个分支**:

Selection 分支(比较 PropertyInfo 指针与 0x18010A208 处的 SelectionProp 数据):

```asm
180072eb9: callq SelectionChange          ; 0x73010 → 取事件 UID
180072ee3: …取 Value 内的 Element 引用(旧值 r14/新值 r13)
180072ef2: leaq 0x18006a630 …             ; Element::SelectedProp
180072ef9: callq _SetValue               ; 旧子元素 Selected=false(单例 bool)
180072f2c: movl $0x83fe, …               ; EventMsg.msg = 0x83FE(通用 Element 事件)
180072f3f: callq *0x122142(%rip) # 0x180195088  ; DUserSendEvent → SelectionChange 事件发出
…随后新子元素 Selected=true(对称的 _SetValue)
```

完整语义:**Selection 属性变化 → 旧子元素 Selected 置假 → 发 SelectionChange 事件(标准 FireEvent 0x83FE 路径,`17-events.md` §3)→ 新子元素 Selected 置真**。子元素的 selected 皮肤(`<if selected="true">`)和 UIA 的 SelectionItemProxy 都由这个投影驱动。

Children 分支(比较与 0x1801035D0 = Element::ChildrenProp):子元素被移除时,GetSelection 查当前选中——若其 index 已是 -1(已销毁),则对**宿主自己** `_RemoveLocalValue(SelectionProp)` 并对**那个陈旧子元素** `_RemoveLocalValue(SelectedProp)`(0x180072F8E-FAD 两次调用)。这是**悬空选择清理**:被删的子元素不会留下指向冥界的 Selection。【实锤:指令级;ChildrenProp 身份经 Element::ChildrenProp@0x180071D70 交叉验证】

### 2.3 消费侧:SelectionChange 怎么听

UID 机制全文见`17-events.md` §2.1(16 字节 .rdata blob 地址、指针相等比较),此处只给 Selector 特有的消费模式。宿主 C++ 侧在祖先元素挂 listener,回调里比较 `ev->type == Selector::SelectionChange`(UID 指针比较);`17-events.md` §5.2 的 EventListener lambda 模式直接适用。XML 层没有任何 onclick 类语法——**选择事件的消费永远在 C++**(§1.3 的空壳列表模式正是为此设计)。

---

## 3. 三个反直觉发现

### 3.1 发现一:基类 Selector 没有点击选择【实锤】

Selector::OnEvent(0x180082CD0)反汇编只有一条 `jmp Element::OnEvent`——ICF 折叠把两者合一(objdump 标签甚至错标成 Viewer::OnEvent;以 symbols.json 为准)。"点击某个子元素 → 自动选中它"这个你在 WPF ListBox 里理所当然的行为,**基类 Selector 没有**。它对事件唯一做的事是 OnKeyFocusMoved:焦点移进直接子元素就选中(0x18006E1B0:调 Element::OnKeyFocusMoved 后,若新焦点元素 `+0x50 == this`(是直接子元素),虚调 slot 0x168 SetSelection(该子元素)——**无条件**)。

那 fvewiz 的 selector 单选组怎么工作?CCRadioButton 的选中由系统 HWND 的 BS_AUTORADIOBUTTON 自身处理(Win32 单选互斥),dui 侧的 Selection 属性由宿主在 SelectionChange/CcradioButton 通知里同步——或者宿主根本只用 Win32 语义、dui Selection 留空。【猜想:哪个路径未在反汇编中验证,诚实标注;静态候选列表(CertEnrollUI 的 button 子元素)没有系统控件,基类 Selector 下点击是否选择**无机制可用**——这解释了 SelectorNoDefault 的存在】

### 3.2 发现二:点击选择在 SelectorNoDefault 里,而"Default"指的是焦点行为【实锤】

**SelectorNoDefault::OnEvent(0x18002D5F0)**才是点击选择的实现:

```asm
18002d5ff: cmpl $0x2, 0x14(%rdx)        ; phase 分发
18002d633: leaq 0x18004f7c0 …           ; Button::Click UID
18002d638: callq …                       ; 比较 Event+0x8
18002d646: leaq 0x18004f7a0 …           ; TouchButton::Click UID
18002d64b: callq …                       ; 再比较
; 命中任一 → GetImmediateChild(event->sender) → 虚调 slot 0x168 = SetSelection(该子元素)
; phase==2 分支(0x18002D697)另处理 KeyboardNavigate(方向键导航)
```

同时它覆盖 SetSelection(0x180083A20)做参数校验:

```asm
180083a20: testq %rdx, %rdx              ; target == NULL?
180083a25: cmpq %rcx, 0x50(%rdx)         ; target->Parent == this?(直接子元素?)
180083a2b: movl $0x80070057, %eax        ; 否则 E_INVALIDARG!
180083a32: jmp   Selector::SetSelection  ; 校验通过 → 尾跳基类实现
```

**只接受 NULL 或直接子元素**——这是 SelectorNoDefault 的"安全名单":事件冒泡上来的 sender 可能是孙元素(列表行内嵌的按钮),直接选中会破坏"单选容器"的不变量。

**那 "NoDefault" 到底否定什么?** 看另一个覆盖 OnKeyFocusMoved(0x1800D3950):

```asm
18002d3965: callq Element::OnKeyFocusMoved
1800d396f: cmpq %rdi, 0x50(%rbx)        ; 焦点目标是否直接子元素?
1800d3975: 虚调 slot 0x118              ; IsTypeOf 类查询
1800d3987: 比对 Button::s_pClassInfo    ; 是 Button 系?
1800d39a2: jne …(是 → 直接返回,不选中!)
1800d39a7: 比对 BaseScrollViewer::s_pClassInfo  ; 是滚动视图系?
1800d39bc: jne …(是 → 直接返回!)
1800d39c7: 虚调 slot 0x168              ; 否则 SetSelection(焦点子元素)
```

对照 §3.1:基类的 OnKeyFocusMoved **无条件**选中焦点子元素;SelectorNoDefault 把"焦点移到 Button 系/ScrollViewer 系子元素"排除在外。**"Default" = 焦点跟随选择的默认行为;NoDefault = 按钮和滚动条获得焦点不代表列表选择变了**。这才是准确的语义:Tab 键在列表项的按钮间游走时,列表的 Selection 不应被焦点拖着走。【实锤:两个 OnKeyFocusMoved 对照】

把三个类的行为差异并排(全部指令级实锤):

| 行为 | Selector | SelectorNoDefault | ItemList |
|---|---|---|---|
| 点击子元素 → 选中 | ✗(OnEvent 空转发) | ✓(Click/MultipleClick UID + 直接子元素校验) | 继承 SelectorNoDefault ✓ |
| 焦点移到子元素 → 选中 | ✓ 无条件 | ✓ 仅非 Button/非 ScrollViewer | 继承 ✓ |
| SetSelection 校验 | 无 | NULL 或直接子元素,否则 E_INVALIDARG | 继承 |
| 键盘方向键 | — | KeyboardNavigate 分支 | GetAdjacent 覆写(§4) |
| 特有 | — | — | KeyWithin→SetSelection(NULL)、Reorderable |

DiagCpl 用 SelectorNoDefault 的动机【强推】:autoSelector 里两个 CCRadioButton 都是 Button 系子元素——若用基类,焦点移入单选钮就会强制 Selection;NoDefault 版让选择严格由点击(系统单选语义)驱动。

### 3.3 发现三:Selector 吞 Tab 键【实锤】

Selector::OnInput(0x180086D10)极小:

```asm
; 键盘设备 + type==1(KeyDown)+ key==0x9(Tab)→ 直接 return(不调基类 = 吞掉)
; 其余一切 → Element::OnInput
```

**Tab 在 Selector 上被吞**:列表内的导航只认方向键(KeyboardNavigate),Tab 永远跳出列表(去宿主窗口的 Tab 序,`15-keyboard-navigation.md` §3/`14-layout-protocol.md` §4.1 的 ShellBorderLayout._CalcTabOrder)。这与 §3.2 的焦点语义设计一脉相承:焦点循环(横向)与列表选择(纵向)是两条正交通道。

---

## 4. ItemList:键盘进入时重同步 + 可重排

### 4.1 属性/方法表(14 符号)

| 成员 | RVA | 说明 |
|---|---|---|
| ReorderableProp | 0xB3F80 | 自有属性:Bool(拖拽重排开关) |
| IsReorderable / SetReorderable | 0xB3F40 / 0xB3F90 | 属性对 |
| OnPropertyChanged | 0x81530 | KeyWithin 分支(§4.2) |
| GetAdjacent | 0xB3F10 | 导航覆写:dir bit0==1 → Selector 版,否则 Element 版(§4.3) |
| vftable | 0x10B278 | — |

### 4.2 KeyWithin 同步【实锤,反汇编】

ItemList::OnPropertyChanged(0x180081530)先比较 PropertyInfo 与 0x180103C30(经 Element::KeyWithinProp@0x180072AA0 交叉验证 = KeyWithinProp):命中后做类型匹配(Value 首 dword 低 2 位),然后:

```asm
1800815af: movq (%rcx), %rax
1800815b2: xorl %edx, %edx            ; target = NULL
1800815b4: movq 0x168(%rax), %rax     ; slot 0x168 = SetSelection
1800815bb: callq …                    ; SetSelection(NULL)
```

**键盘焦点进入列表(KeyWithin 变真)→ SetSelection(NULL) 清空当前选择**。动机【强推】:输入法候选列表这类场景,键盘进入意味着新的输入会话开始,旧的选中项已无意义——清空选择让 UI 回到"无默认选中"状态,避免旧高亮误导用户。这与 SelectorNoDefault 的"No(默认选中)"哲学呼应:**这个家族整体反对"总有一个默认选中"的隐式行为**。

### 4.3 导航覆写

ItemList::GetAdjacent(0x1800B3F10):方向参数 bit0==1(纵向?)→ 调 Selector::GetAdjacent(0xD38B0),否则 → Element::GetAdjacent。而 Selector::GetAdjacent 的逻辑(0x1800D38B0):起点为 NULL 时,先 GetSelection——**从当前选中项出发**问它的 GetAdjacent(vtable+0x98,`15-keyboard-navigation.md` §2);无选中或没找到 → 回退 Element 版(从自身几何出发)。方向键导航与 Selection 的联动由此闭环:选中项就是导航锚点。

---

## 5. ItemList × TouchScrollViewer:虚拟化配合

`19-viewer-family.md` §4.4 已还原 TSVEnableVirtualization(行为注册表 0x109BA0 → 工厂 0xEAB70 → `Element+0x12C = 1` 视口外子元素不建 gadget),本文引用它并补 Selector 侧的配合事实:

1. **ItemList 做内容根,TSV 做视口**——§1.5 两个实例全是这个嵌套。ItemList 提供 gridlayout(-1,1) 的逻辑坐标与选择语义;TSV 的 tile 引擎(_RecomputeTiles/_GadgetExistsInRect)决定哪些子元素真的实例化。两份职责正好互补:Selector 家族的"子元素集合"逻辑上永远完整(SetSelection 可指向任何逻辑项),物理上只有视口内的有 gadget。
2. **语料边界**:InputSwitch/msctfuimanager 的 ItemList **都没有**写 `behaviors="DUI70::TSVEnableVirtualization()"`(那是 WebcamUi UIFILE_200 的用法,`19-viewer-family.md` §1)——即这两个语料场景是**非虚拟化的** ItemList(条目数少:输入法列表/一屏候选词)。虚拟化 ItemList 的组合(长列表 + TSV 行为)在语料中无直接实例,是 API 能力而非已观测用法。【实锤:语料检索;组合可行性【强推】——机制两侧(Selection 的逻辑性 + TSV 的物理性)各自实锤,配合点无实例】
3. **SnapMode="Single"** 只出现在 msctfuimanager 的 TouchScrollViewer 上(InputSwitch 没有)——滚动惯性停止后吸附到单个条目边界,候选词列表的"翻页感"。SnapMode 是 TSV 的属性而非 ItemList 的(`19-viewer-family.md` §1 语料普查:Single 共 4 处)。

---

## 6. 边界邻居:WrappingList 与 Repeater

**WrappingList : ItemList**(0x112FF8 vftable;.g.txt 实测),自有属性 Circular/TopIndex/FirstItemOffset/SeparatorHeight(Bool/Int×3)+ GetItemHeight/CalculateTopIndex/SetTopIndex/_SelfLayoutDoLayout/_SelfLayoutUpdateDesiredSize(自带布局!)。语料标签 0 次,但 dui70 的 IMMERSIVESTYLES 390-392 行 `<if id="atom(TouchSelect_ItemList)"><WrappingList accessible="true" accrole="list" background="20742"/></if>` 证明它活在 **TouchSelect 的弹层里**——TouchSelectInitialize 内建一棵 TouchSelectPopup 子树(Label/Arrow 是 TouchButton,滚动容器里是 WrappingList),候选内容循环滚动(Circular)。【实锤:样式表命中 + 继承;TouchSelect 的内建子树结构见 IMMERSIVESTYLES 319-437】

**Repeater : Macro**(.g.txt)——不在 Selector 树上!它是数据模板引擎:BuildElement(0xDAB20)/SetDataEngine(0x967B0)/SetGraphicType(0xDAD50),把 IDataEngine 的每条数据展开成一个元素。语料 5 处全在 fvecpl(UIFILE_110:171-196,`<repeater expand="volumeInfo">` + `<bind connect="volumeExpandoDrive"/>`——磁盘列表)。Repeater 是"数据 → 元素"的方向,Selector 是"元素 → 单选"的方向,两者正交;完整数据绑定链(IDataEngine/IDataEntry/Macro/Bind)归 P3 教程,本文只标记边界。【实锤:继承与语料;深挖移交 P3】

---

## 7. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | 基类 Selector(非 NoDefault)下,静态候选列表(button 子元素)的点击选择由谁驱动? | 基类 OnEvent 空转发是实锤;CCRadioButton 场景可由 Win32 语义解释,纯 Element 子元素场景**无已验证机制** | 挂 UITest 探针跑一个 selector+button 组合,观测 Selection 是否变化 |
| 2 | fvewiz/hgcpl 单选组里 dui Selection 与 Win32 单选态的同步路径 | 未反汇编(可能宿主手动 SetSelection,也可能根本不同步) | 宿主 DLL(hgcpl)逆向或运行时探针 |
| 3 | ItemList 的 Reorderable=true 时拖拽重排的输入处理 | 属性与 setter 实锤;OnInput 无覆写——重排逻辑可能在 PVL 行为或宿主侧 | 反汇编 msctfuimanager 宿主侧行为注册 |
| 4 | 虚拟化 TSV + ItemList 的完整组合(长列表)无语料实例 | 机制两侧各自实锤,组合【强推】 | 构造实验 XML + UITest |
| 5 | WrappingList 的 Circular 滚动算法(CalculateTopIndex/FirstItemOffset) | 符号与属性实锤;算法未读 | 0xBCFA4/0xBF700 反汇编(TouchSelect 弹层深挖时顺带) |
| 6 | Selector::GetAdjacent 的"起点为 NULL"语义(何时发生) | 反汇编已见 NULL 分支;触发场景未定 | 键盘导航教程(`15-keyboard-navigation.md`)的 NavReference 协议交叉 |

---

## 8. 小结

- **Selection 是指向子元素的 ElementRef 属性**(CreateElementRef + 标准 SetValue 漏斗)——权威副本在容器,子元素 Selected 只是投影;
- **SelectionChange 走标准 FireEvent 0x83FE 路径**,旧子元素置假 → 发事件 → 新子元素置真;Children 变化时还有悬空选择清理;
- 三个反直觉:基类 Selector **没有**点击选择(OnEvent 是 ICF 空转发);点击选择活在 SelectorNoDefault(Click UID + 直接子元素校验 E_INVALIDARG);"NoDefault" 否定的是**焦点跟随选择**对 Button/ScrollViewer 子元素的适用,不是"无默认选中项";Selector 吞 Tab,选择与焦点循环正交;
- ItemList = SelectorNoDefault 之孙 + KeyWithin 进入时 SetSelection(NULL) 重同步 + Reorderable;配 TouchScrollViewer 时,Selection 的逻辑性与 TSV 虚拟化的物理性互补(组合无语料实例,诚实标注);
- WrappingList(TouchSelect 弹层)与 Repeater(fvecpl 数据模板)是这条线上的两个边界邻居,各自归属不同的问题域。

下一篇(三部曲之三)看按钮身边的小图形搭档:Glyph 们。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| Selector/ItemList/WrappingList 继承链 | .g.txt | docs/SelectorClass.g.txt、ItemListClass.g.txt、WrappingListClass.g.txt、RepeaterClass.g.txt |
| 标签频次(14/1/5/5) | 语料统计 | .local/corpus/class-usage.json |
| SetSelection = CreateElementRef + _SetValue(SelectionProp) | 反汇编 | 0x18007C130(CreateElementRef 0x18003C140;失败 0x8007000E) |
| OnPropertyChanged 双分支(SelectionChange + Selected 投影;Children 悬空清理) | 反汇编 | 0x180072E20(SelectionProp 数据 0x18010A208、ChildrenProp 0x1801035D0、SelectedProp 0x18006A630、EventMsg 0x83FE @0x180072F2C、DUserSendEvent IAT 0x180195088、_RemoveLocalValue 0x180031070) |
| 基类 Selector::OnEvent 空转发(ICF) | 反汇编 + symbols.json | 0x180082CD0(单条 jmp;objdump 标签因 ICF 不可信) |
| Selector::OnKeyFocusMoved 无条件选中 | 反汇编 | 0x18006E1B0(slot 0x168 虚调用) |
| SelectorNoDefault::OnEvent 点击选择(Click/TouchButton::Click UID) | 反汇编 | 0x18002D5F0-0x18002D660(UID 0x18004F7C0/0x18004F7A0) |
| SelectorNoDefault::SetSelection 直接子元素校验(E_INVALIDARG) | 反汇编 | 0x180083A20(0x80070057) |
| SelectorNoDefault::OnKeyFocusMoved 排除 Button/BaseScrollViewer | 反汇编 | 0x1800D3950(s_pClassInfo 比对 0x180183688/0x180183F40) |
| Selector::OnInput 吞 Tab | 反汇编 | 0x180086D10(key 0x9) |
| ItemList KeyWithin → SetSelection(NULL) | 反汇编 | 0x180081530(KeyWithinProp 0x180103C30 交叉验证自 Element::KeyWithinProp@0x180072AA0;slot 0x168 @0x1800815B4) |
| ItemList::GetAdjacent 双路分发 / Selector::GetAdjacent 从选中项出发 | 反汇编 | 0x1800B3F10 / 0x1800D38B0(GetSelection→vtable+0x98) |
| XML 实例 | 语料 | fvewiz/UIFILE_20.xml:378-381、hgcpl/UIFILE_202.xml:255-267、CertEnrollUI/UIFILE_130.xml:723/909/1829、DiagCpl/UIFILE_217.xml:173-176、InputSwitch/UIFILE_104.xml:10-14、msctfuimanager/UIFILE_16001.xml:40-58、fvecpl/UIFILE_110.xml:171-196 |
| WrappingList = TouchSelect 弹层内容 | 语料 | dui70/UIFILE_IMMERSIVESTYLES.xml:390-392 |
| TSVEnableVirtualization 机制 | 引用 | `19-viewer-family.md` §4.4(行为工厂 0xEAB70、Element+0x12C) |
| UID 比较机制 / FireEvent 0x83FE | 引用 | `17-events.md` §2.1/§3 |
