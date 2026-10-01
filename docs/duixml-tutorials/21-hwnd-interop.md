# 教程 21:HWND 互操作三层楼 —— NativeHWNDHost / HWNDElement / HWNDHost

> 系列教程第 21 篇(P8 HWND 互操作之半篇,接 ui-mental-model-outline §9 的展开)。前置:`16-startup-and-threading.md`(启动序列、gadget 世界)、`17-events.md`(事件系统)、`19-viewer-family.md`/`20-scroll-physics.md`(Viewer 与滚动——本篇会复用其物理层结论)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:DirectUI 号称"无 HWND 的 UI",但真实程序活在 Win32 世界里——窗口从哪来、消息泵在哪、Win32 控件怎么进 Element 树。答案是一座三层楼:**NativeHWNDHost 造窗口当宿主,HWNDElement 把 HWND 变成 Element 树根,HWNDHost 把 Win32 控件"寄生"进树中**。楼下还有一整个 CC* 家族(语料约 630 处使用)。物理层WndProc 子类化链引自 duser-render-internals.md §3.1(【实锤】沿用),本文的增量是**三层的职责边界逐函数还原 + 寄生模式的实码**。XElement"反向桥"只在末尾点到(X* 家族深挖归 P8 另一篇)。

---

## 0. 全景:一张图看三层

```
Win32 世界                          DirectUI 世界
─────────────────                   ─────────────────

┌──────────────────────┐
│ 顶层 HWND            │ ←── ①NativeHWNDHost::Create(CreateWindowExW)
│ WndProc=NativeHWNDHost::WndProc │   (宿主窗口实体)
└─────────┬────────────┘
          │ 窗口客户区
┌─────────▼────────────┐
│ 同一个 HWND 被子类化  │ ←── ②HWNDElement::Create(hwnd, ...) + Host(root)
│ WndProc=HWNDElement::StaticWndProc │ (HWND → Element 树根;gadget 树挂进来)
└─────────┬────────────┘
          │ Element 树
   ┌──────▼───────────────┐
   │ <CCCheckBox> 等元素   │ ←── ③HWNDHost(及 CC* 子类):CreateHWND 造子 HWND,
   │   各自拥有一个子 HWND │   SetWindowLongPtr 子类化寄生,CtrlSubclassProc 接管
   └──────────────────────┘
```

三句话分工:
1. **NativeHWNDHost = 窗口实体**(Create/ShowWindow/DestroyWindow/WndProc,25 个方法,纯 Win32 外壳);
2. **HWNDElement = 树根适配器**(67 个方法,把 HWND 的消息流接到 gadget/Element 世界:主题、DPI、焦点、颜色同步);
3. **HWNDHost = 控件寄生容器**(79 个方法,给 Win32 控件当 Element 壳:子类化、矩形/字体/颜色同步、通知转发)。

**心智模型(引自 ui-mental-model §9):"HWND 是资源,Element 树是逻辑"**——HWND 的生死由这三层管理,但布局、事件、可访问性全部走 Element 树。

---

## 1. XML 与 C++ 的两个世界

先泼冷水:**这三层楼基本不出现在 UIFILE 里**。语料普查:0 个 `<nativehwndhost>`、`<hwndhost>` 标签的直接使用;而 CC* 家族(CCPushButton 189 / CCCheckBox 157 / CCSysLink 96 / CCRadioButton 89 / CCProgressBar 38 / CCCommandLink 21 / CCListView 16 + 零头,**合计约 630 处**【实锤,语料正则实测;outline §9 的 6279 处 native 元素基数对照:约 10% 的元素是 HWND 寄生】)。

原因:①②层是**宿主程序 C++ 侧的事**(每个程序自己 Create);③层被 CC* 家族**封装成 XML 标签**。XML 作者看见的是:

```xml
<!-- CertEnrollUI UIFILE_130:证书模板列表行,一个寄生 Win32 复选框 -->
<element resid="CspListItem" layout="borderlayout()" layoutpos="top"
         margin="rect(0, 0, 4rp, 4rp)" accRole="ListItem" accessible="true">
    <CCCheckBox id="atom(CheckBox)" layoutpos="top"/>
    <element id="atom(ErrorText)" contentalign="wrapleft" .../>
</element>
```

```xml
<!-- 同文件 style 段:页脚帮助链接,寄生 SysLink 控件 -->
<if id="atom(helplink)">
    <CCSysLink layoutpos="bottom" padding="rect(0, 4rp, 0, 0)"/>
</if>
```

`<CCCheckBox>` 在 XML 里与普通元素无异(布局槽位、id、无障碍属性照写),差异全在运行时:它解析成功后**会多出一个真 HWND 当孩子**。

---

## 2. 第一层:NativeHWNDHost —— 窗口实体【实锤】

### 2.1 类表面(25 方法节选)

| 方法 | RVA | 说明 |
|---|---|---|
| Create | 0x2C6A0 | 静态入口(参数巨多,见 2.2) |
| CreateHostWindow | 0x5F8A0 | 建窗核心 |
| Host | 0x5F8A0 区 | 把根 Element 挂进窗口 |
| ShowWindow / DestroyWindow | — | 直通 Win32 |
| GetHWND / GetElement | — | 双向访问器 |
| SaveFocus / RestoreFocus / SetDefaultFocusID | — | 焦点管理(Win32 焦点 ↔ Element 焦点) |
| WndProc(static) | 0x5F170 | 本层消息入口 |
| DestroyMsg / SyncDestroyWindow | — | 安全销毁 |

### 2.2 Create 的真实形态(反汇编 + UITest 用例双证)

UITest.cpp 499-541 是官方用法(编译通过的活代码):

```cpp
NativeHWNDHost::Create(
    (UCString)L"Microsoft DirectUI Test", NULL, NULL,
    600, 400, 800, 600,               // 初始/最大尺寸
    WS_EX_WINDOWEDGE, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0,
    &pwnd);                            // 出参
...
pWizardMain->SetVisible(true);
pwnd->Host(pWizardMain);               // 根元素入驻
pwnd->ShowWindow(SW_SHOW);
```

反汇编(0x18002C6A0)显示 Create 收拢参数后 `btsl $0x19, r9d`(给 style 补 0x20000000=WS_MINIMIZEBOX 附近的状态位)再跳共享建窗核心 0x18002BDD8,那里**直接 `callq *0x180119468` = USER32!CreateWindowExW**【实锤,IAT 表 iat_map.txt】。窗口类名/样式由虚函数 `GetWindowClassNameAndStyle`(0x7B340,HWNDElement 上也有同名——两层共用一套类注册)提供。

### 2.3 WndProc:窗口消息的顶层闸门【实锤,本次新还原】

```
NativeHWNDHost::WndProc (static)   0x18005F170
  callq *0x180119458                ; GetWindowLongPtrW(hwnd, GWLP_USERDATA?) → this
  callq DestroyMsg 0x18005F780      ; 拿"销毁消息号"(自定义注销消息)
  cmp msg, 销毁消息号 → 同步销毁路径
  msg ≤ 0x1A → 小消息查表(WM_CREATE/WM_DESTROY 族)
  msg == 0x7E / 0x94+ → 主题/设置变化分发(直通默认)
  其余 → DefWindowProc / 下层
```

关键点:NativeHWNDHost 的 WndProc 只管**窗口生命周期与顶层杂务**;一旦窗口客户区归 duser 管,日常消息(绘制/输入/主题)全在第二层的子类化链上。这就是为什么 25 个方法够用——它真就是个壳。

> DestroyMsg/SaveFocus/RestoreFocus 这组方法解决的是"Win32 模态 + Element 焦点"的互操作问题:窗口被系统收走焦点时,Element 世界的键盘焦点要存根(SaveFocus),回来要还(RestoreFocus)。【强推】(方法名与调用时机推断,未逐行读)

---

## 3. 第二层:HWNDElement —— HWND 变树根【实锤为主】

### 3.1 创建序列(UITest 527 行实锤)

```cpp
HWNDElement::Create(pwnd->GetHWND(),   // 借第一层刚造的 HWND
                    true,              // 子类化开关
                    0, NULL,
                    &defer_key,        // 出参:布局事务 key
                    (Element **)&hwnd_element);
pParser->CreateElement(L"WizardMain", hwnd_element, ...);  // XML 树以它为父
pWizardMain->SetVisible(true);
pWizardMain->EndDefer(defer_key);
```

物理层发生了什么(duser-render-internals.md §1.5,【实锤】沿用):HWNDElement::Initialize(0x18002AE68)调 **duser!CreateGadget(type=1)**——type 1 = "HWND 子类化 gadget":duser `SetWindowLongPtrW(hwnd, GWLP_WNDPROC, duser 子类 proc)` 并把旧 proc 存 gadget guts+0x8。从此这个 HWND 的消息先过 duser(0x180008F40 主 switch),duser 处理绘制/输入并把不认识的下发旧 proc——**Element 树的消息泵物理上就是这个子类化**。

### 3.2 StaticWndProc → 虚 WndProc【实锤,本次新还原】

dui70 自己还有一层薄垫:

```
HWNDElement::StaticWndProc   0x1800645C0
  rax = GetWindowLongPtrW(hwnd, 0)          ; GWLP_USERDATA → this
  call [ [rax] + 0x1C0 ]                    ; 虚槽 WndProc = HWNDElement::WndProc 0x18004A120
```

HWNDElement::WndProc(0x18004A120)是**消息大分流**(实测分支):

| 消息 | 分支 | 走向 |
|---|---|---|
| WM_TIMER(0x113) | 0x18004A666 | 定时器分发(动画/惯性) |
| WM_SETFOCUS(0xB)/WM_KILLFOCUS(0x10)+0x15? | 0x18004A370 / 0x18004A606 | 焦点同步(Element 焦点系统) |
| WM_ACTIVATE(0x6) | 0x18004A393 | 激活态 |
| WM_ERASEBKGND(0x14) | 0x18004A191 处 GetCursorPos | 鼠标类输入换算 |
| WM_SETTINGCHANGE/WM_THEMECHANGE | OnWmSettingChanged 0x180076D60 / OnWmThemeChanged 0x18002E180 | 主题同步广播 |
| WM_DPICHANGED | _FireWindowDpiChangeEvent 0x18004C1C0 + _UpdateDesktopScaleFactor | DPI 缩放 |
| 沉浸色 | _HandleImmersiveColorSchemeChange 0x18002E230 | Win8 时代颜色方案 |

这层是**状态翻译层**:Win32 世界的事件(主题变了、DPI 变了、焦点来了)被翻译成 Element 世界的属性与事件,沿树广播。67 个方法里近半是这个方向的同步(FlushWorkingSet 0xA93B0 这种内存管理杂务也在)。

---

## 4. 第三层:HWNDHost —— 控件寄生【实锤,本次新还原】

### 4.1 寄生三步曲

HWNDHost(79 方法)及其 CC* 子类(CCPushButton 等,继承自 CCBase + 各自控件特化)对一个 Win32 控件做的事:

**第一步:造子 HWND。** HWNDHost::CreateHWND(0x180064280)按类名/样式建控件窗口(典型:BUTTON/SYSLINK/PROGRESS),作为**宿主 HWND 的子窗口**——注意是 Win32 意义的父子,不是 Element 意义;Element 树里它是普通节点。

**第二步:子类化接管(寄生本体)。** AttachCtrlSubclassProc(0x18002BF80)完整还原:

```
AttachCtrlSubclassProc(hwnd):
  old = SetWindowLongPtrW(hwnd, GWLP_WNDPROC(-4), CtrlSubclassProc)   ; 换 proc,拿旧值
  jmp  SetWindowLongPtrW(hwnd, GWLP_USERDATA(-21), old)               ; 旧 proc 存 USERDATA!
```

**不用 comctl32 的 SetWindowSubclass,是最朴素的 SetWindowLongPtr 双步子类化**:旧 WNDPROC 指针被塞进 GWLP_USERDATA。对应取回方:

```
CtrlSubclassProc(hwnd, msg, wp, lp)   0x180067030
  old = GetWindowLongPtrW(hwnd, GWLP_WNDPROC→实际读 -21)   ; 从 USERDATA 取旧 proc
  rax = CallWindowProcW(old, hwnd, msg, wp, lp)             ; 先让原控件处理!
  if msg == WM_GETDLGCODE(0x87) && lp != NULL:              ; 事后修正
      if [lp+8](消息) in {WM_CHAR(0x102)..WM_SYSCHAR(0x106) 一带}:
          rax |= 3 ; rax |= 4                                ; 强制 WANTALLKEYS|WANTCHARS 族
  return rax
```

**这个默认 proc 是"先转发、只改 DLGC"的透明寄生**——DirectUI 要的只是"键盘消息别被对话框管理器吞了",控件原行为全保留。真正的业务接管(MessageCallback/OnMessage/OnNotify,三者 RVA 相同 0x66740 = 共享桩,由子类覆盖)在 CC* 子类的覆盖里。

**第三步:外形同步。** Sync* 家族(79 方法里的 12 个):SyncParent/SyncRect/SyncVisible/SyncFont/SyncColorsAndFonts/SyncBackground/SyncForeground/SyncText/SyncStyle/SyncDirection——Element 树的布局/主题变化,被翻译成对子 HWND 的 Win32 调用(SetWindowPos/WM_SETFONT/…)。**方向与第二层相反**:第二层是 Win32→Element,这一层是 Element→Win32。寄生元素在两套世界里各有一个投影,Sync* 负责不让投影打架。

### 4.2 sink 窗口:_SinkWndProc 与 ApplySinkRegion

HWNDHost 还有第二类窗口:**sink**(沉槽)——一个透明子 HWND 负责截获控件背后的绘制合成(_SinkWndProc 0x18004B410 / ApplySinkRegion 0x18009110 / GetSinkRect 0x18008DE0)。【强推】其用途是 CCListView/CCListView 大列表的滚动合成与区域裁剪(名字 + Region 系列调用推断);逐行未读,入未解清单。

### 4.3 g_rgMouseMap:输入的第二次翻译【实锤,本次新还原】

HWNDHost::OnInput(0x1800084E0)对**裸鼠标输入**(InputEvent+0xC==0、+0x10==0)做设备状态→按钮 UID 的矩阵翻译:

```
leaq 0x18011F6C0        ; g_rgMouseMap@HWNDHost
rcx = deviceType*3 + stateKey          ; 行=设备类型(0..5),列=状态(0..2)
ebp = [表 + rcx*4]                     ; → DWORD 结果
```

实测表值(0x18011F6C0 起 18 个 DWORD):

```
行0(基础): 0x200 0x200 0x200      行3: 0x200 0x200 0x200
行1:        0x200 0x200 0x200      行4: 0x2A1 0x2A1 0x2A1   ← 拖拽相位?
行2:        0x201 0x204 0x207      行5: 0x20A 0x20A 0x20A   ← 左键三态?
```

0x200 族是鼠标按钮事件的 UID 基址(`17-events.md` 的 UID=地址机制;0x201/0x204/0x207 = X 按钮三态,0x2A1 = 捕获/拖拽,0x20A = 左键)。**【强推】行/列的确切语义(哪个设备态 × 哪个按钮态)未逐项验证,数值→UID 的对应由 0x200 基址 + 小偏移推断。**

这层翻译只对**到达寄生 HWND 的裸输入**做——普通 gadget 输入在 duser 侧已成形(`20-scroll-physics.md` §1)。寄生窗口的输入要"回到 Element 语义",HWNDHost 是翻译官。

---

## 5. CC* 家族:寄生的产品线

| 类 | 继承(classes.json) | 语料用例数 | 寄生目标(Win32 类)【强推】 |
|---|---|---|---|
| CCPushButton | CCBase 系 | 189 | BUTTON |
| CCCheckBox | 同 | 157 | BUTTON(BS_AUTOCHECKBOX) |
| CCSysLink | 同 | 96 | SYSLINK |
| CCRadioButton | 同 | 89 | BUTTON(BS_AUTORADIOBUTTON) |
| CCProgressBar | 同 | 38 | PROGRESS_CLASS |
| CCCommandLink | 同 | 21 | BUTTON(BS_COMMANDLINK) |
| CCListView | 同 | 16 | WC_LISTVIEW |
| CCBaseScrollBar/CCHScrollBar/CCVScrollBar | BaseScrollBar+CCBase(多继承) | 4/4 | SCROLLBAR |

classes.json 里 `XElement : HWNDHost + IXElementCP`、`XBaby : HWNDElement + IDialogElement + IElementListener`、`DialogElement : HWNDElement` 三条继承行说明:**X* 家族(XElement/XBaby)正是站在本篇三层楼之上的下一层**——XElement 直接继承 HWNDHost(寄生者),XBaby 直接继承 HWNDElement(树根)。它们是"DirectUI 元素反向住进 Win32 对话框"的桥,即 P8 另一篇的主题。本篇止步于此:**HWNDHost/HWNDElement 的机制层已经被 X* 复用,复用的证据就是继承行本身。**【实锤】(继承关系来自 classes.json;功能定位【强推】)

---

## 6. 三层对比总表

| 维度 | NativeHWNDHost | HWNDElement | HWNDHost(CC*) |
|---|---|---|---|
| 核心动作 | CreateWindowExW 造窗 | duser CreateGadget(type=1) 子类化 | CreateHWND 造子窗 + SetWindowLongPtr 寄生 |
| WndProc | 0x18005F170(生命周期) | Static 0x1800645C0→虚 0x18004A120(状态翻译) | CtrlSubclassProc 0x180067030(透明转发+DLGC) |
| 消息方向 | Win32→窗口管理 | Win32→Element(主题/DPI/焦点) | Element→Win32(Sync*)+ Win32→Element(OnNotify/g_rgMouseMap) |
| 在 XML? | 否(C++) | 否(C++) | 否(被 CC* 封装成标签) |
| 方法数 | 25 | 67 | 79(+CC* 各自) |

---

## 7. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | g_rgMouseMap 行/列语义(哪维是设备、哪维是按钮态) | 数值矩阵实锤,语义【强推】 | duser 侧对寄生 HWND 投递的 InputEvent 构造点比对 |
| 2 | _SinkWndProc/ApplySinkRegion 的确切用途 | 【强推】列表滚动合成 | 0x18004B410 全量 + CCListView 使用点 |
| 3 | MessageCallback/OnMessage/OnNotify 共享桩(0x66740)的虚槽号与子类覆盖名单 | 三者同 RVA 实锤,槽号未定 | CC* 子类 vtable 对比 |
| 4 | NativeHWNDHost::Host 的元素挂接细节(0x5F8A0 区) | 【强推】走 HWNDElement::Create+树根 | UITest 已证调用序,内部未读 |
| 5 | GetWindowClassNameAndStyle(0x7B340)注册的窗口类清单 | 未读 | 类名表反汇编 |
| 6 | UnvirtualizePosition / VerifyParentage(奇名方法)的语义 | 未读 | 符号名【强推】为寄生坐标的"去虚拟化"校验 |
| 7 | CC* 语料 630 与 outline §9 的 6279 native 元素之比 | 两数皆实测,比值解释【强推】 | 无需验证,口径一致 |

---

## 附:证据索引

- **三层方法数与符号**:symbols.json NativeHWNDHost 25 / HWNDElement 67 / HWNDHost 79 方法统计;关键 RVA:Create 0x2C6A0、WndProc 0x5F170、DestroyMsg 0x5F780、CreateHWND 0x64280、CtrlSubclassProc 0x67030、AttachCtrlSubclassProc 0x2BF80、_CtrlWndProc 0x4A940、_SinkWndProc 0x4B410、ApplySinkRegion 0x9110、StaticWndProc 0x645C0、HWNDElement::WndProc 0x4A120(vtable+0x1C0 实测)。
- **NativeHWNDHost::Create→CreateWindowExW**:0x18002C6A0(btsl 0x19)→0x18002BDD8→IAT 0x180119468(iat_map.txt: USER32!CreateWindowExW);DestroyMsg 消息号分发 @0x18005F170+。
- **AttachCtrlSubclassProc 寄生双步**:0x18002BF80:SetWindowLongPtrW(GWLP_WNDPROC=-4, CtrlSubclassProc)→SetWindowLongPtrW(GWLP_USERDATA=-21, old);IAT 0x180119460=SetWindowLongPtrW、0x180119458=GetWindowLongPtrW、0x180119318=CallWindowProcW(iat_map.txt)。
- **CtrlSubclassProc 透明转发**:0x180067030:GetWindowLongPtrW→CallWindowProcW(旧 proc 先行)→WM_GETDLGCODE(0x87)特判,字符消息(0x102-0x106 族,`subl $0x102; testl $0xFFFFFFFB`)→ 标志位 |3、|4。
- **HWNDElement::StaticWndProc→虚槽**:0x1800645C0:GetWindowLongPtrW→[vtable+0x1C0]=0x18004A120;WndProc 消息分支(WM_TIMER 0x113 / WM_SETFOCUS 0xB / WM_ACTIVATE 0x6 / GetCursorPos IAT 0x180119340)。
- **duser 物理层引用**:HWNDElement::Initialize 0x18002AE68→CreateGadget(type=1, HWND 子类化,旧 proc 存 guts+0x8);WndProc 链 0x180008DC0→0x180008F40 —— duser-render-internals.md §1.5/§3.1(原【实锤】沿用)。
- **g_rgMouseMap**:数据 0x18011F6C0(18 DWORD 实测:0x200/0x201/0x204/0x207/0x2A1/0x20A 矩阵);消费点 HWNDHost::OnInput 0x1800084E0(设备行×状态列寻址 `leal (%rax,%rax,2); movl (%rbp,%rcx,4)`)。
- **UITest 用例**:UITest.cpp 489-541(InitProcessPriv/RegisterAllControls→NativeHWNDHost::Create→DUIXmlParser→HWNDElement::Create(pwnd->GetHWND(),true)→CreateElement→Host→ShowWindow)。
- **CC* 语料普查**:`docs/duixml-corpus/` 全量 `<cc*/combobox/edit[ >/]` 正则:CCPushButton 189 / CCCheckBox 157 / CCSysLink 96 / CCRadioButton 89 / CCProgressBar 38 / CCCommandLink 21 / CCListView 16 / CCListBox 4 / CCHScrollBar 4 / CCVScrollBar 4 / CCTrackBar 1 / CCRichEdit 2;XML 实例 CertEnrollUI UIFILE_130 line 449/493/369。
- **X* 家族继承行**:classes.json `XElement : HWNDHost+IXElementCP`、`XBaby : HWNDElement+IDialogElement+IElementListener`、`DialogElement : HWNDElement`(深挖归 P8 X* 篇)。
