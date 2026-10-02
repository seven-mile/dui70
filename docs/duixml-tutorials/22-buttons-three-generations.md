# 教程 22:按钮编年史 —— Button → CC* → Touch* 三代演进

> 系列教程第 22 篇(P1 按钮与选择三部曲之一)。前置:`17-events.md`(Event/UID 机制)、`18-properties-and-lifecycle.md`(属性系统)、`21-hwnd-interop.md`(HWND 互操作三层楼)、`07-richtext-and-the-dwrite-bridge.md`(DWrite 管线)。
> 主题:"简简单单的 button"在 DirectUI 里其实有三个家族、三条技术路线:纯自绘的传统族、寄生 comctl32 的 CC* 封装族、Win8 时代基于 RichText/DWrite 重写的 Touch* 族。本文用语料 + 反汇编把三条路线的边界、动机与真实机制钉死,并回答四个经典好奇点:AutoButton 的 auto、CC 是子类化还是 owner-draw、TouchButton 是平行还是替代、bootux 为什么用 BUXButton。

## 0. 全景:一张表看三代

| | 第一代:传统族 | 第二代:CC* 封装族 | 第三代:Touch* 重写族 |
|---|---|---|---|
| 代表标签 | `button`(1732)/`pushbutton`(18)/`repeatbutton`(25)/`autobutton`(1)/`accessiblebutton`(129) | `ccpushbutton`(194)/`cccheckbox`(160)/`ccsyslink`(100)/`ccradiobutton`(89)/`ccprogressbar`(38)/`cccommandlink`(21)/`cclistview`(16)… | `touchbutton`(379)/`touchhyperlink`(91)/`touchcommandbutton`(25)/`touchrepeatbutton`(18)/`touchcheckbox`(15)… |
| 继承根 | `Element → Button → …` | `Element → ElementWithHWND → HWNDHost → CCBase → …` | `Element → RichText → TouchButton → …` |
| 渲染方式 | 纯 DirectUI 自绘,uxtheme `dtb()` 背景 | **真实 comctl32 HWND 岛** + uxtheme 主题 | 纯自绘 + DWrite 文本 + ImmersiveStyles 命名色 |
| 文本引擎 | GDI DrawText 系(`08-ptext-and-the-old-text-era.md`) | 控件 HWND 自己画 | RichText/DWrite 管线(`07-richtext-and-the-dwrite-bridge.md`) |
| 使用者画像 | 老控制面板/向导/对话框(26 个 DLL) | 控制面板全家桶(22 个 DLL) | Win8+ 现代 UI:bootux、msctfuimanager、InputSwitch、WebcamUi、bdeunlock… |

(标签频次均为语料实测,`.local/corpus/class-usage.json`;继承链来自 `docs/duixml-classinfo/*.g.txt` + symbols.json vtable 验证。)

一个直接印象:**三个家族不是前后替代,而是长期共存**——duser.dll 的公共样式表(2009 年代)同时定义 pushbutton 与 CCHScrollBar;bootux(2012)同时用 TouchButton(96 处)和 BUXButton;今天的 dui70 里三套代码都在。

---

## 1. 第一代:传统按钮族 —— 纯自绘的 Element 子类

### 1.1 类表面与继承链

从 symbols.json + `docs/duixml-classinfo/*.g.txt` 实测的继承结构:

```
Element
 └── Button                          (27 符号;核心:Click/Pressed/Captured)
      ├── accessiblebutton           (19 符号;无障碍角色特化)
      │    └── autobutton            (17 符号;Toggle 事件 + 自动翻转)
      │         └── pushbutton       (22 符号;宿主事件 + Enter 默认按钮)
      ├── repeatbutton               (17 符号;按住重复触发)
      ├── thumb                      (17 符号;滚动条滑块,Drag 事件)
      ├── checkboxglyph / radiobuttonglyph / expandobuttonglyph   (16 符号 ×3;见24-glyph-buttons-little-graphics.md Glyph 篇)
      └── selector 不是 Button!Selector : Element(单选容器,见三部曲之二)
```

要点:**Button 家族全员是纯 Element 子类,没有 HWND**。它们的"按钮感"全部来自三件事:Pressed/Captured 两个属性、OnInput 的鼠标状态机、样式表里的五态背景。

### 1.2 属性/方法表(逐类)

**Button(基类,27 符号)**

| 成员 | RVA | 说明 |
|---|---|---|
| Click | 0x4F7C0 | 事件 UID 工厂(16 字节 blob 地址比较,`17-events.md` §2.1) |
| Context | 0xB2530 | 事件 UID(右键上下文菜单) |
| PressedProp / CapturedProp | 0x6FCB0 / 0x7E4A0 | 状态属性对 |
| OnInput | 0x309D0 | 鼠标状态机入口 |
| OnPropertyChanged | 0x65AF0 | 属性管道 |
| OnLostDialogFocus / OnReceivedDialogFocus | 0xB2630 / 0xB26B0 | 对话框焦点联动 |
| DefaultAction | 0x4ED70 | 无障碍默认动作(Invoke 语义) |

自有属性只有 Pressed/Captured 两个 Bool;Selected/Enabled/KeyFocused 等 70 个属性全部继承自 Element(`18-properties-and-lifecycle.md` §1)。**Button 本身不"知道"自己是复选框还是单选钮**——那是样式表 + accrole 的事。

**accessiblebutton(129 处语料,8 个 DLL)**

| 成员 | RVA | 说明 |
|---|---|---|
| FindAccessibleRole | 0x6EC10 | 线性查表 c_rgar |
| Recalc | 0x6EA30 | 角色变化后重算 |
| OnPropertyChanged | 0x6E990 | 监听 AccRole 属性 |
| c_rgar | 0x122A80 | 5 项角色表(.rdata) |

c_rgar 实测 5 项,每项 0x14 字节,首 DWORD 是 MSAA 角色:43(PushButton)/44(CheckButton)/45(RadioButton)/64(OutlineButton)/30(Link)。AccessibleButton = "标签名即角色"的语义化按钮——XML 里不用写 `accrole="pushbutton"`(`04-uia-accessible-bridge.md` §1.4 已引用此例)。尾随 4 个 dword 的编码(-792/-795 一类负数)未解,入未知清单。

**autobutton(1 处语料:sharemediacpl)**

| 成员 | RVA | 说明 |
|---|---|---|
| OnEvent | 0xD7BD0 | **auto 的全部秘密**(§1.4) |
| Toggle | 0xD7C90 | 事件 UID 工厂 |

**pushbutton(18 处:CertEnrollUI 12 + duser 6)**

| 成员 | RVA | 说明 |
|---|---|---|
| GetContentSize | 0xD7F70 | 文本测量走 GdiGetCharDimensions 快捷路径(P2 结论,见 §1.5) |
| FireHostEvent / Hosted | 0xD7F00 / 0xD8100 | 宿主(DialogElement)默认按钮联动 |
| OnHosted / OnUnHosted | 0xD8120 / 0xD8160 | 挂进/摘出对话框树 |
| EnforceSizeProp | 0xD7EF0 | 强制按钮尺寸约束 |

**repeatbutton(25 处,全部在 duser 公共样式表)**

| 成员 | RVA | 说明 |
|---|---|---|
| OnInput | 0xB6350 | 按住重复的输入状态机 |
| _RepeatButtonActionCallback | 0xB6440 | GMA_ACTIONINFO 静态回调(duser gadget 消息动作) |
| SetStopThumbBehavior | 0xB6420 | 停止滑块(thumb)时的行为开关 |

### 1.3 XML 实例:duser 公共样式表是第一代的"博物馆"

duser/UIFILE_1010.xml(8688 字节 duib)是 DirectUI 自带的共享样式表,第一代全家的五态样式都在这:

```xml
<!-- duser/UIFILE_1010.xml:47-62 —— pushbutton 五态:dtb(button,1,1..5) -->
<pushbutton background="dtb(button, 1, 1)" foreground="buttontext"
            contentalign="middlecenter" padding="rect(20rp,5rp,20rp,5rp)"/>
<if keyfocused="true"> <pushbutton contentalign="middlecenter | focusrect"/> </if>
<if selected="true">  <pushbutton background="dtb(button, 1, 5)"/> </if>
<if mousefocused="true"> <pushbutton background="dtb(button, 1, 2)"/> </if>
<if pressed="true">   <pushbutton background="dtb(button, 1, 3)" padding="rect(21rp,6rp,19rp,4rp)"/> </if>
<if enabled="false">  <pushbutton background="dtb(button, 1, 4)" foreground="graytext"/> </if>

<!-- 同文件 63-97 —— 同一个 <button> 标签,靠 class 切换复选框皮肤:dtb(button,3,X) -->
<if id="atom(CheckBox)">
  <button minsize="themeable(gtps(button, 3, 1), size(sysmetric(71), sysmetric(72)))"
          background="dtb(button, 3, 1)" accessible="true" accrole="checkbutton"/>
  <if selected="true"> <button background="dtb(button, 3, 5)"/> … </if>
  <if class="mixed">   <button background="dtb(button, 3, 9)"/> … </if>   <!-- 三态复选 -->
</if>
<!-- 123-146:单选皮肤 dtb(button,2,1..8);205-279:repeatbutton 滚动条箭头 dtb(scrollbar,…);
     280-284:ScrollViewer 模板里的 CCHScrollBar/CCVScrollBar —— 二代与一代同堂 -->
```

【实锤,语料】这就是第一代的设计哲学:**一个 Button 类 + N 套样式皮肤 + accrole 语义标签** = N 种控件。dtb(button,part,state) 的 part 1/2/3 正是 uxtheme 的 PUSHBUTTON/RADIOBUTTON/CHECKBOX 三个 part——DirectUI 只是借 uxtheme 的位图,不借 comctl32 的窗口。

按钮当"链接"用也在这一代:同文件 147-162 行 `<if class="link">` 给 accessiblebutton 换链接字体和手型光标。Corpus 里大量 `class="cp_content_link"` 的 `<button>` 就是这个套路(如 DiagCpl/UIFILE_217.xml:123-133)。

### 1.4 好奇点一:AutoButton 的 "auto" 是什么?【实锤,反汇编】

全语料唯一实例(sharemediacpl/UIFILE_201.xml:335):

```xml
<autobutton id="atom(MainButton)" resid="macro_sharing_list_item" layoutpos="top"
            accessible="true" accrole="ListItem" accname="resstr(96)"
            layout="borderlayout()" active="mouse|keyboard" class="ListItem"
            sheet="ListItemEffects" accdefaction="invoke">
    …整块列表行内容(图标 + 链接 + 复选框)都包在这个 autobutton 里…
</autobutton>
```

用法:整个"共享列表行"包成一个 autobutton,`accrole="ListItem"`——它本质是**可点整行**。反汇编 AutoButton::OnEvent(0x1800D7BD0):

```asm
1800d7bda: cmpl $0x0, 0x14(%rdx)        ; Event+0x14 phase:只处理非冒泡相位
1800d7bea: leaq 0x18004f7c0 …           ; Button::Click UID
1800d7bff: callq …                      ; UID 比较(Event+0x8 指针相等,17-events.md §2.1)
1800d7c0b: callq GetAccRole             ; 取自己的 AccRole
1800d7c10: subl $0x2c, %eax             ; 0x2c = 44 = CheckButton?
1800d7c13: je   0x1800d7c21             ;   是 → 走 Toggle 分支
1800d7c15: cmpl $0x1, %eax              ; 0x2d = 45 = RadioButton?
1800d7c18: jne  …                       ;   都不是 → 什么都不做
…
1800d7c21: leaq 0x1800d7c90 …           ; AutoButton::Toggle UID
1800d7c48: movb 0x94(%rdi), %al         ; 读当前 Selected(this+0x94 bit4)
1800d7c51: shrb $0x4, %al
1800d7c57: notb %al                     ; 取反
1800d7c5f: callq FireEvent              ; 发 Toggle 事件
1800d7c6b: callq SetSelected            ; 写回 !Selected
; RadioButton 分支(0x2d):直接 SetSelected(true),不取反
```

**结论:"auto" = 收到 Click 事件后,按自己当前 AccRole 自动翻转 Selected 属性**——CheckButton 角色就取反(Toggle),RadioButton 角色就置真,其他角色不动。它是"Button 皮肤 + 自动翻转逻辑"的整行可点容器:sharemediacpl 用它做整行点击,同时行内的按钮/复选框照常工作(子元素先消费输入,整行的 auto 是兜底)。这解释了为什么它只出现 1 次:常规复选/单选有更便宜的路线(Button + 样式或 CCCheckBox),autobutton 服务的是"列表行整体可点"这个特殊场景。

### 1.5 好奇点二:PushButton 的尺寸测量(P2 交接线索,直接引用)

PushButton::GetContentSize(0xD7F70)不走 Element 基类的 DrawTextW DT_CALCRECT,而是 **GdiGetCharDimensions 快捷路径**(0x1800D7FF6 调用点,P2 反汇编结论)——按钮文本通常是单行,GdiGetCharDimensions 一次拿字符高度/平均宽度比整段 DT_CALCRECT 便宜。按钮文字宽度计算可直接引用此结论(P2 教程文本篇有完整还原)。

---

## 2. 第二代:CC* 封装族 —— comctl32 的 HWND 岛

### 2.1 类表面:16 个类一张表

继承链(全部 .g.txt 实测):`Element → ElementWithHWND → HWNDHost → CCBase → 各控件类`。

| 类 | 语料数 | 寄生 Win32 类(ctor 反汇编,§2.2) | 默认 WinStyle(ctor) |
|---|---|---|---|
| CCPushButton | 194 | `"Button"`(0x11F5A8) | 0x50000000 = WS_CHILD\|WS_VISIBLE |
| CCCheckBox | 160 | `"Button"` | 0x50002000(+BS_ 位族) |
| CCRadioButton | 89 | `"Button"` | 0x50002409(+BS_AUTORADIOBUTTON=9) |
| CCCommandLink | 21 | `"Button"` | 0x50002000(+0x2000=BS_COMMANDLINK 族) |
| CCBaseCheckRadioButton(基) | 0(仅 API) | `"Button"` | 0x50002000 |
| CCSysLink | 100 | `"SysLink"`(0x128EC8) | 0x50000001 |
| CCProgressBar | 38 | `"msctls_progress32"`(0x123E88) | 0x50000000 |
| CCTrackBar | 1 | `"msctls_trackbar32"`(0x128E38) | 0x50001000(+TBS 位) |
| CCListBox | 4 | `"ListBox"`(0x128E78) | 0x50000000 |
| CCListView | 16 | `"SysListView32"`(0x128E88) | 0x50000000 |
| CCTreeView | 0(仅 API) | `"SysTreeView32"`(0x126788) | 0x50000000 |
| CCAVI | 0(仅 API) | `"SysAnimate32"`(0x128EA8) | 0x50000000 |
| CCBaseScrollBar(基) | 0(仅 API) | `"ScrollBar"`(0x1230B8) | 0x50000000 |
| CCHScrollBar / CCVScrollBar | 4 / 4 | `"ScrollBar"` | 0x50000000 / 0x50000001(SBS_VERT=1) |

(语料数 = class-usage.json;"仅 API" = 注册进 dui70 但 149 个 UIFILE 里零标签出现。)

### 2.2 好奇点三:CC 封装是子类化 HWND 还是 owner-draw?【实锤:是子类化寄生,不是 owner-draw】

`21-hwnd-interop.md` §4 已给出 HWNDHost 三层楼的寄生模式;这里把 CCBase 的证据链补完整:

**CCBase::CreateHWND(0x18002BD50)完整反汇编**:

```asm
18002bd60: callq GetWinStyle            ; 读 WinStyle 属性(0x2BF40 → GetValue(WinStyleProp@0x81010))
18002bd6e: orl  0x140(%rdi), %eax      ; OR 上 ctor 预置的默认 style(this+0x140)
18002bd76: movq 0x148(%rdi), %rdx      ; 类名指针(this+0x148,ctor 里 leaq 写入)
…
18002bd99: callq 0x18002bdd8            ; 内联 thunk →
18002be7b: callq *0xed5e6(%rip)  # 0x180119468 = USER32!CreateWindowExW   ← 实锤
…
18002bda9: callq AttachCtrlSubclassProc ; 0x2BF80:SetWindowLongPtrW(GWLP_WNDPROC)
                                        ;   换 WndProc 为 CtrlSubclassProc(0x67030)
```

**ctor 侧证据**(以 CCPushButton 0x180086200 为例,全家族同构):

```asm
180086202: orl  $0x50000000, %edx       ; 默认 style = WS_CHILD|WS_VISIBLE
180086228: leaq …, %rax  # 0x18011f5a8  ; L"Button"
18008622f: movq %rax, 0x148(%rcx)       ; 类名 → this+0x148
180086243: movl %edx, 0x140(%rcx)       ; style → this+0x140
```

各 ctor 的类名指针直接解 UTF-16:0x11F5A8='Button'、0x1230B8='ScrollBar'、0x123E88='msctls_progress32'、0x128E38='msctls_trackbar32'、0x128E78='ListBox'、0x128E88='SysListView32'、0x128EA8='SysAnimate32'、0x128EC8='SysLink'、0x126788='SysTreeView32'。

**结论**:CC* 是**真实的 comctl32 HWND 岛**——CreateWindowExW 按系统类名造子窗口,再 AttachCtrlSubclassProc 子类化寄生(`21-hwnd-interop.md` §4.1 的"寄生三步曲":造窗 → 子类化 → Sync* 外形同步)。**不是 owner-draw**:绘制发生在系统控件自己的 WndProc 里,dui70 只在 CtrlSubclassProc 里转发消息 + 调 OnNotify/OnCustomDraw 钩子(CCBase 有 OnCustomDraw 0x66740,但那是 NM_CUSTOMDRAW 通知钩子,不是 owner-draw 绘制路径)。

**XML 侧最直白的证据:WinStyle 属性直接可见**。UserAccountControlSettings/UIFILE_203.xml:153:

```xml
<CCTrackBar id="atom(StateSlider)" layoutpos="client" background="window"
            accessible="true" accrole="slider" accname="resstr(83)"
            height="220rp" WinStyle="0x0000021A" padding="rect(0rp,0rp,0rp,0rp)"/>
```

`WinStyle="0x0000021A"` 就是 GetWinStyle() 读的那个属性的 XML 写入——0x21A = TBS_VERT|TBS_TOP|TBS_AUTOTICKS 之类的 trackbar 位置刻度位,与 ctor 默认 0x50001000 相 OR 后交给 CreateWindowExW。【实锤,语料 + 反汇编闭环】

### 2.3 XML 实例:控制面板全家桶的典型用法

```xml
<!-- fvewiz/UIFILE_20.xml:98 —— CCCommandLink:向导大选项按钮(BS_COMMANDLINK 箭头+两行) -->
<CCCommandLink id="atom(usepin)" accessible="true" accrole="pushbutton"
               class="commandLink" sheet="local" transparent="true" layoutpos="left"
               minsize="size(563rp,0)" content="resstr(1935)"/>

<!-- CertEnrollUI/UIFILE_130.xml:1719 —— CCPushButton 常规按钮 -->
<CCPushButton id="atom(ChooseCert)" content="resstr(1241)" accessible="true" layoutpos="right"/>

<!-- DiagCpl/UIFILE_217.xml:182 —— CCCheckBox 带 selected 初始态 -->
<CCCheckbox id="atom(skipCheckbox)" selected="true" layoutpos="top" content="resstr(151)" shortcut="auto"/>

<!-- autoplay/UIFILE_101.xml:17 —— CCCheckBox + selected + shortcut -->
<CCCheckBox id="atom(checkboxEnableAutoplay)" selected="true" content="resstr(1100)"
            shortcut="auto" background="themeable(dtb(CONTROLPANEL,2,0),window)"/>

<!-- Narrator/UIFILE_10002.xml:16 —— CCListView:运行时填充数据的视图 -->
<CCListView id="atom(NarratorCommandsListView)" layoutpos="top" borderstyle="Solid"
            bordercolor="windowtext" borderthickness="rect(1rp, 1rp, 1rp, 1rp)"
            height="200rp" accessible="true" accname="resstr(3058)"/>

<!-- SpaceControl/UIFILE_201.xml:292 —— CCProgressBar:容量条 -->
<CCProgressBar width="200rp" height="15rp" id="atom(CapacityProgress)"/>
```

注意 CC* 的样式面貌:**没有五态 `<if pressed>` 皮肤**——那是系统控件自己的主题。宿主样式表只调边框/字体/背景这类外围属性(fhcpl/UIFILE_201.xml:13-17 的 CCSysLink/CCListView/CCListBox 全是 bordercolor/font 一类)。

### 2.4 属性/方法表(CCBase 与两个代表子类)

**CCBase(26 符号,家族地基)**

| 成员 | RVA | 说明 |
|---|---|---|
| CreateHWND | 0x2BD50 | §2.2 的造窗核心 |
| GetWinStyle / SetWinStyle | 0x2BF40 / 0x8D040 | WinStyle 属性对(Int) |
| WinStyleProp | 0x81010 | 属性工厂 |
| OnNotify | 0x6CF40 | WM_NOTIFY → Element 事件翻译 |
| OnCustomDraw | 0x66740 | NM_CUSTOMDRAW 钩子 |
| OnInput | 0x890D0 | 寄生 HWND 裸输入 → UID 矩阵翻译(`21-hwnd-interop.md` §4) |
| OnPropertyChanged | 0x6EFE0 | 属性 → Sync* 转发 |
| PostCreate | 0x7C980 | 造窗后的初始化钩子 |
| SetNotifyHandler | 0xAA380 | 宿主通知回调挂接 |
| OnLostDialogFocus / OnReceivedDialogFocus | — | 对话框焦点联动(与 DialogElement 耦合,outline §B2 好奇点;符号实锤存在,机制未逐行读) |

**CCRadioButton(15 符号)**:AutoGroupingProp/AutoGrouping——radiobutton 的 WS_GROUP 自动分组开关;**CCCommandLink(19 符号)**:NoteProp/SetNote/SetDefaultState/SyncNoteAndGlyph——命令链接的第二行说明文本(BCS_NOTE 消息封装)。这两个是 CC* 里少数有"自己的属性"的类;其余(CCCheckBox/CCSysLink/CCProgressBar)几乎纯寄生,方法表就是 ctor+Create+Register 标配。

### 2.5 二代的技术动机【强推】

没有文档直说"为什么造 CC*"。但证据拼图高度一致:

1. **功能覆盖面**:CC* 家族恰好 = comctl32 独有能力的清单——SysLink 富链接、trackbar 拖动、AVI 播放、listview/listbox 数据视图、progressbar 动画。这些用第一代的"样式皮肤"路线做不出来(自绘复刻 SysLink 的内联链接命中测试、listview 的虚拟化,成本都极高)。
2. **使用者画像**:CC* 的用户全是控制面板/系统属性页 DLL——它们要的不是 DirectUI 的酷,而是**与老 Win32 属性页 100% 一致的原生控件行为**(无障碍、输入法、主题切换全由系统控件兜底)。
3. **WinStyle 逃生门**:XML 层留了 WinStyle 属性,说明设计者明确预期"宿主要传 comctl32 位"——这是给原生控件的接口,不是给自绘的。

【强推:三条均为证据一致推断,无文档;诚实标注】

---

## 3. 第三代:Touch* 重写族 —— RichText 基座上的现代按钮

### 3.1 继承革命:基类从 Element 换成 RichText

三代最大的结构差异在继承根:`docs/duixml-classinfo/TouchButtonClass.g.txt` 实测:

```
Element → RichText → TouchButton
                            ├── touchcheckbox(→ touchcheckboxglyph)
                            ├── touchhyperlink
                            ├── touchrepeatbutton
                            └── touchcommandbutton
Element → TouchSwitch(不是 TouchButton!见 §3.5)
Element → Selector → …(三部曲之二)
```

**TouchButton : RichText** 意味着按钮文本直接走 DWrite 管线(_CreateDWriteLayout/_FlushDWrite,`07-richtext-and-the-dwrite-bridge.md`)——按钮内容是真正的富文本(可含 colorfont/typography run),不再是 GDI DrawText 单行。这就是为什么 TouchButton 的样式表大量出现 `font="resstr(112, library(dui70.dll))"`(字体资源引用)和 foreground 命名色。

### 3.2 属性/方法表(TouchButton 及子类)

**TouchButton(54 符号,本族最大)**

| 成员 | RVA | 说明 |
|---|---|---|
| Click / MultipleClick / RightClick | 0x4F7A0 / 0x85B60 / 0xBC230 | 三个事件 UID 工厂 |
| OnInput | 0x64930 | 按设备分发(下 §3.3) |
| _OnMouseEvent / _OnPointerEvent / _OnKeyboardEvent | 0x6499C / 0xBC8B0 / 0xBC81C | 设备处理器 |
| _StartClick / _FinishClick / _UpdateClick / CancelClick | 0x64898 / 0x64A58 / 0x91044 / 0x64CE0 | 点击状态机 |
| FireClickEvent | 0x83190 | clickCount==1→Click,否则 MultipleClick(cmovne 选择,§3.3) |
| HandleEnterProp / HandleGlobalEnterProp | 0xBBC30 / 0x8F000 | Enter 默认按钮(继承 pushbutton 语义) |
| ShowKeyFocusProp | 0xBC570 | 键盘焦点可见性(TouchSelect 用它做"仅键盘时显边框") |
| TreatRightMouseButtonAsLeftProp | 0x929D0 | 触屏场景右键当左键 |
| _SyncDefaultEnterHandling | 0x64E78 | 与宿主 DialogElement 的默认按钮同步 |
| PressedProp / CapturedProp | 0x7C5E0 / 0x86760 | 与一代 Button 同名状态属性 |

**TouchCheckBox(27 符号)**:CheckedStateProp(0xBB830,枚举 unchecked=0/checked=1)、ToggleOnClickProp(0xBC590,§3.4)、_CreateAndAddGlyph(0x90D0C)/_CreateAndAddLabel(0xBC6A0)——Initialize 时自建 glyph+label 子元素(TCB_Glyph/TCB_Label,见`24-glyph-buttons-little-graphics.md`)。**TouchHyperLink(16 符号)**:VisitedProp(0xBC5A0)——访问态是属性,样式表 `<if visited="true">` 消费。**TouchCommandButton(20 符号)**:SubContentProp(0xBC580)+_GetSubContentElement——命令按钮的第二行说明文本(CCCommandLink 的 Touch 版对位)。**TouchRepeatButton(23 符号)**:RepeatClick(0xBC210)、DisableMouseInRectCheckProp(0xBB950)、_OnRepeatClickTimer/_ContinueRepeat/_FireRepeatClickEvent(§3.4)。

### 3.3 行为机制:点击状态机【实锤】

**分发**——TouchButton::OnInput(0x64930)按 InputEvent 的 device 字段分发到 _OnMouseEvent(mouse)/_OnPointerEvent(pointer)/_OnKeyboardEvent(keyboard);pointer 是 Win8 新输入设备类(与 Active 枚举的 `active="pointer"` 对应)。

**收尾**——_FinishClick(0x64A58):

```asm
callq GetPressed          ; 仍处于按下态?
…
callq CancelClick         ; 清理点击状态
testb %al, %al            ; CancelClick 成功才继续
jne   …                   ; (未按下 → 直接返回,不发事件)
testb %sil, %sil          ; GetPressed 结果
je    …                   ; 未曾按下 → 不发
→ 虚调用 FireClickEvent(clickCount, device, point)
```

**发事件**——FireClickEvent(0x83190):

```asm
1800831b7: leaq 0x18004f7a0 …           ; TouchButton::Click UID
1800831c1: cmpl $0x1, %edx              ; clickCount == 1?
1800831c4: leaq 0x180085b60 …           ; TouchButton::MultipleClick UID
1800831ce: cmovneq %rcx, %rax           ; ≠1 → 换成 MultipleClick UID
…      ; 构造 Event{uid, clickCount, device, point} → FireEvent(0x459C0, 17-events.md §3)
```

即:**单击发 Click,双击及以上发 MultipleClick**——事件类型在发射侧按 clickCount 分流,消费侧只比 UID。UID 比较机制本身见`17-events.md` §2.1(16 字节 .rdata blob 地址,OnEvent 里 `cmpq uid_addr, 0x8(%rdx)`),本文不重复推导。

### 3.4 两个子类机制:TouchCheckBox 的门控与 TouchRepeatButton 的定时器【实锤】

**TouchCheckBox::OnEvent(0xBBE80)**——"点击 → 翻转 CheckedState"有三重门:

```asm
1800bbe90: testl $0xfffffffd, 0x14(%rdx)  ; phase ∈ {1,2}(目标/冒泡前)
1800bbe9f: cmpq %rcx, (%rdx)              ; sender == 自己?
1800bbea4..d5: UID == Click 或 MultipleClick?
1800bbee1: callq GetToggleOnClick          ; ToggleOnClick 属性为真?
1800bbee8: je …                            ; 假 → 不翻转!(设计者可关掉点击翻转)
1800bbeed: callq GetCheckedState           ; state==1(checked)?
1800bbefa: setne %dl                       ; checked → 0(unchecked);否则 → 1
1800bbefd: callq SetCheckedState           ; 写回
```

即:`Click → if ToggleOnClick: CheckedState = (CheckedState==1 ? 0 : 1)`。CheckedState 只有 0/1 两态(unchecked/checked)——Touch 族没有"mixed"三态(那是 CC 侧/一代样式的事)。

**TouchRepeatButton 的重复触发**——与一代 RepeatButton 走 duser GMA_ACTIONINFO 回调(_RepeatButtonActionCallback 0xB6440)完全不同,Touch 版用**dui70 自己的定时器三件套**:

- `_OnRepeatClickTimer`(0xBCA98):`GetPressed() → GetDisableMouseInRectCheck() → _ContinueRepeat() → 否则 CancelClick`;通过后 `incl 0x188(%rbx)`(重复计数 this+0x188 自增)→ _FireRepeatClickEvent(count)。定时器周期写在 0x180(%rbx) 处(0x3D4CCCCD = float 0.05——50ms 重复间隔,IEEE754 单精度直读)。
- `_ContinueRepeat`(0xBC5B0):GetRoot → IAT 0x180119340(GetTickCount 系)做时间校验,再虚调 slot 0x168(SetSelection 家族的槽,此处是滑块位置续算)。
- `_FireRepeatClickEvent`(0xBC710):构造 Event{uid=RepeatClick(0xBC210), count, device=ClickDevice}→ FireEvent。

USER32 SetTimer/KillTimer 在 dui70 IAT 中存在(0x1801191A0/A8);完整调度链(谁调 SetTimer、间隔参数从哪来)未逐行追,入未知清单。

### 3.5 好奇点四:TouchSwitch 为什么不叫 TouchToggleButton?

**因为它根本不是"按钮"——是组合控件行**。三层证据:

1. **继承**:`TouchSwitch : Element`(.g.txt 实测)——不在 TouchButton 树下,没有 Click 事件、没有 Pressed 属性。
2. **结构**(TouchSwitch::Initialize 0xD2A80 反汇编):它自建一整棵子树——`TouchSwitch_TitleText`(RichText)、`TouchSwitch_ContentElement`、`TouchSwitch_SignalText`(RichText)、`TouchSwitch_SliderContainer`、`TouchSwitch_TouchSlider`(调 TouchSlider::Initialize 0xD0310,SetIsVertical(false),SetIsShowOnOffFeedback(true)),再把 TouchSlider 内部的五个子元素 FindDescendent+SetID 改名为 TouchSwitch_Track/TrackChild/Buffering/Thumb/Fillpart。SetAccRole(0x33=51 Slider)给自己。布局 BorderLayout。**这是一个"标题 + 状态文本 + 滑轨"的开关行,不是可点击的 toggle 按钮**。
3. **交互**(OnEvent 0xD3010):只比较子滑块的 TouchSlider::SliderUpdated UID(0xD1BF0),命中 → SetToggleValue。开关值翻转由滑块拖动驱动,不是按钮点击。

"开关"语义由 UIA 侧补齐:ToggleProvider 有一个特化 Proxy **TouchSwitchToggleProxy**(`05-uia-pattern-providers.md` §4 表)——名字里的 Toggle 是给无障碍客户端的 pattern,不是类名语义。XML 实例(Utilman/UIFILE_202.xml:11-16,4 个开关全展示):

```xml
<TouchSwitch id="atom(Narrator)" class="EOA_TouchSwitch" active="mouse|keyboard|pointer"
             layoutpos="top" padding="rect(20rp,10rp,20rp,0rp)"
             ontext="resstr(518)" offtext="resstr(519)" titletext="resstr(500)"
             custom="resstr(501)" accname="resstr(502)" accessible="true" accrole="PushButton"/>
```

onText/offText/titleText 三个 String 属性(.g.txt 自有属性表)喂给 SyncOnOffText(0xD36B0)——按 CurrentToggleValue 选 OnText/OffText 写进 SignalText 子元素和 AccValue。**WebcamUi/UIFILE_202.xml 是 TouchSwitch+TouchSlider 成对阵列**(亮度/对比度/聚焦/曝光,每个 section 一个 switch 一个 slider),演示两个类的分工:switch 是"自动/手动"布尔开关,slider 是数值轨。

### 3.6 好奇点五:TouchButton 是平行还是替代?bootux 为什么 BUXButton?

**平行共存,不是替代**。三个数字:

- Button(一代)在今天(26100)的语料里仍有 **1732 处**,分布在 26 个 DLL——全部是老控制面板/向导/对话框;
- TouchButton 379 处,集中在 bootux(96)/msctfuimanager(112)/dui70 样式(117)/InputSwitch/WebcamUi/Utilman/bdeunlock——**Win8+ 触控场景的新 UI**;
- 两代几乎零交集:没有一个 DLL 同时大量使用 Button 和 TouchButton(msctfuimanager 的 25 个 TouchHyperLink 与 0 个 button;fhcpl 的 130 个 button 与 0 个 touch*)。

【实锤,class-usage.json 分布】也就是说:微软从没把老界面的 button 迁到 TouchButton——Touch* 是给新场景(触控、DWrite、ImmersiveStyles)的新平行家族,旧家族冻结但不删除。这与 §2 的 CC* 同理:**三个家族对应三代技术背景,在二进制里长期共存**。

**bootux 与 BUXButton**:bootux.dll(启动菜单,WinRE 环境)同时用 TouchButton(96 处)和 BUXButton(约 1377 处 BUX* 家族)。BUXButton 是**宿主注册标签**,不是 dui70 内建类——bootux 的 UIFILE 里每个 BUXButton 都带 `attach="{BootMenuUX!CreateBareMetalRecoveryButton}"` 属性,由 BootMenuUX.dll 的导出工厂在解析期接管(`03-host-registered-tags.md` §4:attach 语法 275 处全在 bootux、81/81 工厂函数在导出表验证、bootux 不静态导入 BootMenuUX)。为什么这样设计?bootux 是极早启动环境,它的"按钮"需要 BootMenuUX 侧的完整业务逻辑(启动项、恢复工具),宿主工厂直接把 C++ 回调挂进元素是最省的路线;TouchButton 只用于纯 UI 装饰部分。【强推:机制全部实锤(`03-host-registered-tags.md`),动机部分为推断】

---

## 4. 三代对照:方法表并排

选三代的"按钮本体"类做方法数对比(符号数,含 ctor/dtor/vftable):

| 维度 | Button(一代) | CCPushButton(二代) | TouchButton(三代) |
|---|---|---|---|
| 符号总数 | 27 | 28 | 54 |
| 渲染 | 自绘(uxtheme 位图背景) | 系统 HWND 自绘 | 自绘 + DWrite 文本 |
| 点击事件 | Click/Context | (系统 BN_CLICKED→OnNotify 翻译) | Click/MultipleClick/RightClick |
| 状态属性 | Pressed/Captured | (Selected 映射系统 check 态) | Pressed/Captured + ShowKeyFocus/HandleEnter/TreatRightMouseButtonAsLeft |
| Enter 默认按钮 | —(pushbutton 子类补) | OnLost/OnReceivedDialogFocus | HandleEnter/HandleGlobalEnter + _SyncDefaultEnterHandling |
| 输入设备 | mouse | mouse(寄生 HWND) | mouse/**pointer**/keyboard 三处理器 |
| 文本 | GDI DrawText(GdiGetCharDimensions 快捷路径,P2) | 系统 HWND 绘制 | DWrite 管线(`07-richtext-and-the-dwrite-bridge.md`) |

TouchButton 方法数翻倍的主因:**输入设备的显式三分**(Win8 pointer 输入)+ **默认按钮的自行管理**(一代靠 DialogElement 宿主,三代自带 HandleEnter 族)+ **焦点可见性控制**(ShowKeyFocus——TouchSelect 用它在"仅键盘操作时"才显边框,IMMERSIVESTYLES 327-341 行的 `<if showkeyfocus="true">` 皮肤)。

---

## 5. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | AccessibleButton c_rgar 每项尾随 4 个 dword(如 43/0/-792/0/-792)的编码 | 字节已 dump,语义未解(疑似 PropertyInfo RVA 的负偏移) | 找一个消费第 2-5 dword 的调用点反汇编 |
| 2 | CC* 家族的二代技术驱动是否有文档依据 | §2.5 全部为证据一致推断【强推】 | 无公开文档;只能靠更多旁证 |
| 3 | TouchRepeatButton 定时器的完整调度链(谁调 SetTimer、初次延迟 vs 重复间隔) | _OnRepeatClickTimer/0x3D4CCCCD(50ms)已实锤,SetTimer 调用点未定位 | 反汇编 Initialize 0x62770 与 _StartClick 路径 |
| 4 | TouchSwitch 的 Thumb 是普通 `<Button>`(IMMERSIVESTYLES 463 行)——它收输入还是纯展示? | 样式表实锤是 Button;TouchSlider 是否把输入路由给它未读 | TouchSlider::OnInput 反汇编 |
| 5 | CCOnLostDialogFocus/OnReceivedDialogFocus 与 DialogElement 的耦合机制 | 符号实锤(一代 Button 和 CCBase 都有);调用链未读 | DialogElement::OnKeyFocusMoved 侧反汇编 |
| 6 | 一代 Button 的 OnInput 鼠标状态机细节(Pressed/Captured 置位时序) | RVA 0x309D0 已知,未逐行还原 | 按需反汇编(本文聚焦三代差异,不深入单代) |

---

## 6. 小结

- **一代(传统族)= 纯自绘 Element 子类**:"一个 Button + N 套 dtb() 皮肤 + accrole" 撑起 1732 处语料;duser 公共样式表是活博物馆;
- **二代(CC*)= comctl32 HWND 岛**:CreateWindowExW + AttachCtrlSubclassProc 子类化寄生【实锤】,不是 owner-draw;WinStyle 属性在 XML 里直通 CreateWindowExW;覆盖的恰是 comctl32 独有能力(SysLink/trackbar/AVI/listview);
- **三代(Touch*)= RichText/DWrite 基座的重写**:TouchButton : RichText 让按钮文本走 DWrite;pointer 输入 + ImmersiveStyles 命名色;与一、二代平行共存而非替代;
- 四个好奇点全部落地:AutoButton auto = 按 AccRole 自动翻转 Selected【实锤】;CC = 子类化【实锤】;TouchButton 平行【实锤,分布数据】;BUXButton = bootux 宿主工厂【实锤,`03-host-registered-tags.md`】;TouchSwitch 不是按钮而是组合开关行【实锤,Initialize 反汇编】。

下一篇(三部曲之二)讲这些按钮"住在哪个容器里":Selector 与列表选择。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| 三代标签频次(1732/194/379 等) | 语料正则统计 | `.local/corpus/class-usage.json` |
| 一代继承链(Button→accessiblebutton→autobutton→pushbutton 等) | .g.txt + symbols.json | `docs/duixml-classinfo/ButtonClass.g.txt`、`docs/duixml-classinfo/AutoButtonClass.g.txt` 等 |
| AutoButton::OnEvent 按 AccRole 翻转 | 反汇编 | 0x1800D7BD0(subl 0x2c/0x2d 分支、notb、SetSelected) |
| AccessibleButton c_rgar 5 项角色表(43/44/45/64/30) | .rdata dump | 0x180122A80,每项 0x14 字节 |
| CCBase::CreateHWND = CreateWindowExW + 子类化 | 反汇编 | 0x18002BD50 → thunk 0x18002BDD8 → IAT 0x180119468(iat_map.txt: USER32!CreateWindowExW);AttachCtrlSubclassProc 0x18002BF80 |
| CC* 16 类的 Win32 类名与默认 style | 各 ctor 反汇编 + UTF-16 直读 | CCPushButton 0x180086200('Button', 0x50000000)、CCRadioButton 0x1800DB950(0x50002409)、CCSysLink 0x1800DB9A0(0x50000001)、CCTrackBar 0x1800DB9F0(0x50001000)、CCAVI 0x1800DB860、CCListBox 0x1800DB8B0、CCListView 0x1800DB900、CCTreeView 0x1800A8400('SysTreeView32')、CCCommandLink 0x1800A81E0(0x50002000)、CCBaseCheckRadioButton 0x1800A8060、CCVScrollBar 0x180093A60(0x50000001)、CCProgressBar 0x18008EED0、CCHScrollBar 0x180089420、CCBaseScrollBar 0x18007D520('ScrollBar');字符串地址 0x11F5A8/0x1230B8/0x123E88/0x128E38/0x128E78/0x128E88/0x128EA8/0x128EC8/0x126788 |
| WinStyle 属性 XML 直用 | 语料 | UserAccountControlSettings/UIFILE_203.xml:153 `WinStyle="0x0000021A"` |
| CCBase GetWinStyle 读属性 | 反汇编 | 0x18002BF40 → GetValue(WinStyleProp@0x81010) |
| TouchButton : RichText | .g.txt | docs/duixml-classinfo/TouchButtonClass.g.txt:2 |
| TouchButton 点击状态机(OnInput 分发/_FinishClick/FireClickEvent cmovne) | 反汇编 | 0x180064930 / 0x180064A58 / 0x180083190 |
| TouchCheckBox 三重门控翻转 | 反汇编 | 0x1800BBE80(phase/sender/UID/ToggleOnClick/CheckedState) |
| TouchRepeatButton 定时器三件套 + 50ms(0x3D4CCCCD) | 反汇编 | 0x1800BCA98 / 0x1800BC5B0 / 0x1800BC710(RepeatClick UID 0x1800BC210) |
| TouchSwitch 组合结构(子树创建 + 改名五件套 + SliderUpdated 监听) | 反汇编 | Initialize 0x1800D2A80、OnEvent 0x1800D3010、SyncOnOffText 0x1800D36B0 |
| TouchSwitch : Element(非 TouchButton) | .g.txt | docs/duixml-classinfo/TouchSwitchClass.g.txt:2 |
| bootux BUXButton = 宿主工厂 | 引用 | `03-host-registered-tags.md` §4(attach 275 处、81/81 工厂验证) |
| duser 公共样式表一代五态/复选/单选皮肤 | 语料 | duser/UIFILE_1010.xml:47-62/63-97/123-146 |
| 一代 pushbutton 文本测量 GdiGetCharDimensions | 引用(P2 交接) | PushButton::GetContentSize 0xD7F70,调用点 0x1800D7FF6 |
| TouchButton 文本走 DWrite | 引用 | `07-richtext-and-the-dwrite-bridge.md`(RichText 引擎家族与 _CreateDWriteLayout) |
