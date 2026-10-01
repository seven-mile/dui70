# 教程 20:滚动的物理层 —— gadget 树上的滚动管线

> 系列教程第 20 篇(P5 Viewer 与滚动之二)。前置:`19-viewer-family.md`(Viewer 家族分工)、`17-events.md`(事件系统三级流水线)、`18-properties-and-lifecycle.md`(属性管道与 StartDefer)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:XML 作者写下一行 `YScrollable="true"`,用户滚一下滚轮,像素最终怎么挪。本篇把这条**用户视角的完整因果链**钉死:Win32 消息 → duser 鼠标映射表 → EventMsg → dui70 翻译 → BaseScrollViewer 的滚轮算术 → ScrollBar 的位置属性 → 布局管线 → `SetGadgetRect` → 重绘。物理层(gadget 树、WM_PAINT 树走)结论来自 duser-render-internals.md,本文引用并标注出处,增量是 **dui70 侧的滚轮算术与滚动条回路**。

---

## 0. 全景:一次滚轮的全旅程

```
用户滚动滚轮
  │
  ▼
[Win32] WM_MOUSEWHEEL 投给焦点 HWND
  │
  ▼ ①duser 子类化 WndProc 拦截(0x180008DC0→0x180008F40 主 switch)
[duser] ctx+mode 鼠标映射表 → 认出 wheel → 造 EventMsg(msg=0x83F8 族, device=wheel)
  │   沿 gadget 树找命中的 HGADGET
  ▼
[dui70] _DisplayNodeCallback 双虚调用:OnEvent + OnInput(InputEvent*)
  │
  ▼ ② BaseScrollViewer::OnInput(0x18002FD80) 识别 wheel 设备
  │     Δ = InputEvent+0x30(滚轮增量) + BSV+0xE8(上次余数)
  │     clicks = |Δ| / 120 (WHEEL_DELTA);余数存回 +0xE8
  │     lines  = SystemParametersInfoW(SPI_GETWHEELSCROLLLINES=0x68)
  │
  ▼ ③ ScrollBar::LineUp/LineDown(clicks × lines)
  │     SetPosition(GetPosition() ± GetLine() × n)
  │
  ▼ ④ ScrollBar::SetPosition → Position 属性 _SetValue → 通知监听者
  │     BaseScrollViewer::OnListenedPropertyChanged(0x180059C10)
  │
  ▼ ⑤ 视口偏移更新 → 布局失效 → StartDefer/EndDefer 事务提交
  │     Viewer::_SelfLayoutDoLayout:内容位置 = -offset(clamp)
  │
  ▼ ⑥ Element::OnGroupChanged(0x180046E00)
  │     duser!SetGadgetRect(gadget, 新矩形)   IAT 0x180195028
  │     duser!InvalidateGadget(...)           IAT 0x1801950E8
  │
  ▼ ⑦ duser WM_PAINT 管线:树走(0x180002320)→ Element::Paint(HDC)
```

`19-viewer-family.md` §2.2 讲过 ⑤⑥(偏移→布局→SetGadgetRect);`17-events.md` 讲过 EventMsg 三级流水线与"不存在 msg→UID 中心翻译表"的结论。**本文的增量是 ①~④:duser 的鼠标映射表实码、InputEvent 结构、BSV 的 120 除法算术、以及"滚轮也要经过滚动条"这个反直觉设计。**

---

## 1. 第一跳:duser 怎么把 WM_MOUSEWHEEL 变成 gadget 事件

### 1.1 物理层事实(引自 duser-render-internals.md,均为【实锤】)

- 每个 DirectUI 窗口的 HWND 被 duser 子类化:WndProc 链 0x180008DC0 → 0x180008F40(主 switch);
- duser 侧有 **ctx+mode 鼠标映射表**:同一 Win32 消息在不同上下文(普通/捕获/触摸)映射成不同的 gadget 事件;
- 命中的 gadget 通过 `FindGadgetFromPoint` 一类查找定位,事件打包成 **EventMsg**(msg id 0x83F8-0x8401 族,见 duser-deep-dive §1.3 / `17-events.md` §6 表);
- EventMsg 走 GPCB(`DUserSendEvent`)回到 dui70 的 `_DisplayNodeCallback`,它做**双虚调用**:OnEvent + OnInput。

### 1.2 InputEvent 结构(dui70 视角,字段偏移为实测消费点)【实锤】

从多个 OnInput 实现的消费点交叉:

| 偏移 | 类型 | 语义 | 证据 |
|---|---|---|---|
| +0x00 | Element* | 目标元素 | TSV::OnInput 0x18006757F 起与 IsDescendent 比较 |
| +0x08 | BYTE | "已处理"标志 | BSV::OnInput 成功处理后 `movb $1, 0x8(%rbx)` |
| +0x0C | DWORD | 事件类型(BSV 过滤 `(x & ~2)==0` → 只处理 0 和 2) | 0x18002FD8C testl 0xFFFFFFFD |
| +0x10 | DWORD | 输入种类(0/1 走不同分支;TSV 里 3=wheel) | 0x180067583 cmpl $3 |
| +0x14 | DWORD | **设备类型**(0=pen? 1/9=触摸、2=鼠标、3=滚轮、5=?) | 0x180067604 起多路分发 |
| +0x20 | WORD | 键状态/虚拟键 | 0x1800677D4 movzwl |
| +0x28 | DWORD | 触点 id | SetContact(this, [rsi+0x28]) |
| +0x30 | DWORD | **wheel delta(有符号)** | 0x18002FDFA movswl |
| +0x34 | DWORD | 横向 wheel delta | TSV::OnInput 0x1800676CF 同读 |

> +0x14 的设备枚举名(pen/touch/mouse/wheel)是【强推】:数值来自分支条件(1/9 成对出现于 `testl $0xFFFFFFF7` ——九种触摸类设备;2 单独处理鼠标;3 带 ±delta 才走到滚轮算术;5 走 SetContactNeeded 路径),名字按 DirectInput/DManip 惯例命名,未在符号里找到枚举名。

### 1.3 dui70 侧没有第二张映射表

`17-events.md` §6 的结论在此再验证一遍:0x83F8 载荷里的 Event/InputEvent **在 duser 投递前就构造完毕**(含设备类型、delta),dui70 的 OnInput 实现者们只是**按字段分支**,不存在"msg id→语义"查表。滚轮语义(除以 120、乘滚动行数)是 BaseScrollViewer 一家的私有算术,不是框架代劳。

---

## 2. 滚轮算术:BaseScrollViewer::OnInput 逐行还原【实锤,本次新还原】

BSV::OnInput(0x18002FD80)的 wheel 分支是全篇最值得读的 40 条指令:

```
testl $0xFFFFFFFD, 0xC(%rdx)      ; 只认事件类型 0/2
jne  → Element::OnInput 基类
cmpl $0x0, 0x10(%rdx)             ; 输入种类 0(裸输入)
cmpl $0x5, 0x14(%rdx)             ; 设备类型 5?? —— 见下方"设备号疑点"
jne  → 基类
call GetYScrollable               ; 纵向不许滚就整个放弃 0x18005A180
call [vtable+0x180]               ; GetVScroll → 滚动条对象非空才继续
StartDefer(&key)                  ; 0x180030FF0 —— 滚轮是布局事务!

; ---- 120 除法(BSV+0xE8 = 余数累加器)----
movswl 0x30(%rbx), %ebp           ; Δ = wheel delta(有符号)
addl 0xE8(%rdi), %ebp             ; 加上次的余数
movl $0x88888889, %eax             ; 除以 120 的 magic number
imull / leal / sarl $6 / shrl $31 / add → esi = |Δ|/120 = clicks
imull $0x78, %esi → subl          ; 余数 edx = Δ mod 120(符号修正 cmovle)
movl %edx, 0xE8(%rdi)             ; 余数存回累加器

; ---- 每格滚几行,问系统 ----
leal 0x68(%rdx), %ecx             ; ecx = 0x68 = 104 = SPI_GETWHEELSCROLLLINES
callq *0x1801194D0                ; USER32!SystemParametersInfoW
                                  ;   (IAT 实锤,iat_map.txt 0x1801194D0)
cmpl $-1, [rsp+0x48]              ; -1 = "按页滚" → 换 PageUp/PageDown
movl [rsp+0x48], %edx             ; lines
imull %esi, %edx                  ; 总行数 = clicks × lines

; ---- 交给滚动条 ----
call [BSV vtable+0x180]           ; 再次 GetVScroll → rax = ScrollBar
movq (%rax), %rcx                 ; ScrollBar vtable
ebp>0 → [rcx+0x68]  LineDown      ; 0x180087B90
ebp≤0 → [rcx+0x60]  LineUp        ; 0x180086480
(-1 特例 → [+0x70/+0x78] PageUp/PageDown)
EndDefer(key)                     ; 0x1800263D0 —— 事务提交,一次布局一次重绘
movb $1, 0x8(%rbx)                ; InputEvent 标记"已处理"(冒泡到此为止)
```

四个设计点,每个都值得写进心智模型:

1. **余数累加器(BSV+0xE8)是个 bug 级细节**:高分辨率滚轮(一格 40)三次才滚一行——120 不整除的 delta 不会丢,存进 +0xE8 下次接着加。这解释了为什么平滑滚轮的"半格"手感存在。
2. **滚轮 = StartDefer/EndDefer 事务**(`18-properties-and-lifecycle.md` 的机制):偏移变化触发的整棵子树重布局被压成一次提交,滚十行也只重绘一帧。
3. **SystemParametersInfoW(SPI_GETWHEELSCROLLLINES)** 是运行时每次滚轮都问的(不是缓存),控制面板改"每次滚动行数"立即生效。【实锤】(IAT 调用点 0x18002FE49)
4. **滚轮不直接改偏移,它命令滚动条**。为什么?因为 ScrollBar::SetPosition 里有 clamp(不能滚出范围)+ 位置属性通知的广播——视口偏移、滚动条滑块位置、无障碍焦点,都订阅 Position 属性,一处改处处跟。滚轮只是 Position 的又一个写者。

### 2.1 设备号疑点(诚实标注)

BSV::OnInput 的 wheel 分支条件是 `设备类型==5`,而 TSV::OnInput 里滚轮 delta 出现在 `设备类型==3` 分支。两种可能:(a) duser 对 BSV 路径(非触摸视口)与 TSV 路径(触摸视口)投递的设备号不同;(b) +0x14 在两个函数里语义不同(不可能,同一结构)。【猜想】倾向于 (a):duser 的 ctx+mode 映射表会因 gadget 是否注册了 manipulation 而改投递形态。验证路径:duser 侧映射表(ctx+mode)的 wheel 行反汇编,或在 dui70!TSV::OnInput 与 BSV::OnInput 下断点比对 +0x14。

---

## 3. 滚动条回路:Position 属性的广播

### 3.1 LineUp/LineDown 的算术【实锤】

```
BaseScrollBar::LineUp(n)   0x180086480:
    line = [this vtable+0x28](this)        ; GetLine(0x1800A9610)
    pos  = [this vtable+0x08](this)        ; GetPosition(0x180081690)
    [this vtable+0x30](this, pos - line*n) ; SetPosition(0x180084B70) —— 尾调用
LineDown 同型,pos + line*n
```

vtable 槽位来自 ScrollBar 主 vtable(0x105BA8)与 TouchScrollBar 主 vtable(0x1059A8)逐槽解析(槽号 +0x8/+0x28/+0x60/+0x68/+0x70/+0x78 全部对上符号表)。

### 3.2 SetPosition 是属性管道的入口【实锤】

```
ScrollBar::SetPosition(pos)   0x180084B70:
    v = Value::CreateInt(pos)
    _SetValue(PositionProp@0x180072910, v, fPurge=1)
```

PositionProp 的 PropertyInfo 布局(Element 属性系统,`17-events.md`/`18-properties-and-lifecycle.md` 的 Value 引用计数与 PropertyInfo 机制)保证:值变化 → 通知所有监听者。谁在监听?**BaseScrollViewer 自己**(它是 IElementListener,第二 vtable)。回落路径:

```
BaseScrollViewer::OnListenedPropertyChanged   0x180059C10
  cmp elem, [this+0x8]  / [this+0x10]         ; 只认两个滚动条
  cmp PropertyInfo, 0x180106C50               ; PositionProp 的规格块
  (r9d == (spec&3))                           ; 确认是 Position 变化
  ...
  call [vtable+0x178/0x180]  GetH/VScroll     ; 拿另一根滚动条(同步显示)
  call GetPinning(0x18005A440) → 位测试      ; pinning 策略分流
  对 content 的 Extent 变化同样反应:重算 range
```

同函数还处理**内容元素 LayoutSize 变化**(内容变高 → 滑块 range 变):+0x178/+0x180 两个 vtable 调用取 H/V 滚动条,调它们 vtable+0x38(SetRange 族)传 `extent - viewport ± pinning`。这就是"动态内容 + 滚动条自动跟随"的机制层。

### 3.3 偏移落位(引用`19-viewer-family.md` §2.2)

Position 新值如何变成 YOffset:【强推】经 Position→YOffset 的属性联动(BSV 的 OnPropertyChanged 里 PositionProp 规格 0x180106C50 与 YOffsetProp 的联动分支,未逐行读完最后一跳),最终走 Viewer/BSV 共用的布局管线:

```
偏移属性变化 → 布局失效 → 事务提交 → _SelfLayoutDoLayout
  内容位置 = -min(offset, 内容尺寸-视口)      ← clamp + 取负
  → _UpdateLayoutPosition → LayoutPosition 属性
  → Element::OnGroupChanged 0x180046E00
     → duser!SetGadgetRect IAT 0x180195028    【实锤,调用点 line 84262】
     → duser!InvalidateGadget IAT 0x1801950E8 【实锤,调用点 line 84275】
```

之后是 duser 的 WM_PAINT 管线(0x180001BD0 入口 → 0x180002320 树走 → Element::Paint(HDC)),全部引自 duser-render-internals.md §3.1,【实锤】继承。

> **为什么滚动便宜**:挪内容不改内容。SetGadgetRect 改的是 gadget 矩形(裁剪与位置),重绘只画视口暴露出来的部分;纯偏移动画(PVL/gesture)甚至可以完全不进 OnPaint——TSV 的 DComp 分层路径(`19-viewer-family.md` §4.2)就是把这个优势拉满。

---

## 4. 虚拟化视口里的滚动(WebcamUi 的 ItemList)

WebcamUi UIFILE_200:`<TouchScrollViewer behaviors="DUI70::TSVEnableVirtualization()">` 包着 `<element id="atom(idItemList)" layout="flowlayout()">`(`19-viewer-family.md` §4.4 已还原标志位 Element+0x12C)。滚动时它多做的事:

1. **手势接管**:TSV::OnInput(0x180067550)先于滚轮逻辑检查设备:触摸(设备 1/9)走 manipulation;**设备 3 且 |delta|>8**(0x1800676C1 处 `neg/cmovsl/cmpl $8`,两轴都查)被当作"触摸板滚动手势",置 TSV+0x130=1(pan 模式)后走 DManip 惯性——**触摸板双指划 != 鼠标滚轮**,前者进手势引擎后者进滚轮算术【实锤,分支实码;"+0x130=pan 模式"的命名是强推】;
2. **视口裁剪元素集**:tile 家族(_RecomputeTiles/_GadgetExistsInRect/_ElementExistsInRect,符号在 195 方法清单)维护"当前可见 tile 集合",布局时虚拟化标志(+0x12C)让视口外的子元素跳过 gadget 建立——**滚动一屏,建/销的是一屏的 gadget,不是全列表**;
3. **布局坐标仍在**:flowlayout 无虚拟化时会给全部子元素算坐标(逻辑树完整),虚拟化是**渲染层与 gadget 层的惰性**,不是逻辑树的裁剪——所以 ItemList 的吸附(SnapMode="Single")仍能按全量坐标算翻页落点。

【强推】第 2 点的"跳过 gadget 建立"细节(_RecomputeTiles 的销毁时机)未逐行还原,列入未解清单。

---

## 5. 本篇心智模型(三句话)

1. **滚轮是滚轮,滚动是属性**:duser 只负责把 WM_MOUSEWHEEL 打包成带 delta 的 InputEvent;除以 120、乘系统行数、clamp、广播,全是 dui70 的 BaseScrollViewer 在 StartDefer 事务里干的;
2. **滚动条是算术中枢不是装饰**:滚轮、键盘、拖滑块、程序翻页,全部收敛到 ScrollBar::Position 属性,一处写处处读(视口偏移、滑块位置、无障碍联动都订阅它);
3. **位移靠负坐标,便宜靠不重绘**:滚动最终是 SetGadgetRect(位置=-offset)+InvalidateGadget 的裁剪重绘;更快路径(TSV DComp 分层)连重绘都省,只剩 visual 矩阵更新。

---

## 6. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | BSV(设备 5)与 TSV(设备 3)的滚轮设备号不一致 | 【猜想】duser 按视口是否注册 manipulation 改投递 | duser ctx+mode 映射表 wheel 行;双断点比对 +0x14 |
| 2 | Position→YOffset 的最后一跳(BSV::OnPropertyChanged 内) | 【强推】属性联动存在(0x180106C50 规格块在 OnListenedPropertyChanged 被比对),最后一跳未读 | 0x180075190 ScrollViewer::OnListenedPropertyChanged / BSV OnPropertyChanged 反汇编 |
| 3 | InputEvent+0x14 设备枚举的官方名字 | 数值分布已测,枚举名未找到 | duser 侧构造点反推或 SDK 头 |
| 4 | TSV+0x130=1 的语义命名(pan 模式?) | 写入点实锤(0x1800676EC),语义名【强推】 | 该字段的读取点枚举 |
| 5 | _RecomputeTiles 的销毁时机与 gadget 重建成本 | 框架已还原,逐行未读 | tile 家族(0x8xxxx 区)反汇编 |
| 6 | 横向滚轮(+0x34)是否有独立映射(XOffset 路径) | TSV 读过它(0x1800676CF),BSV 只读 +0x30 | BSV::OnInput 横向分支确认(当前只见纵向) |

---

## 附:证据索引

- **BSV::OnInput 滚轮分支**:dui70-full-disasm.txt 0x18002FD80-0x18002FF0C(@line 56345 起):事件过滤 testl 0xFFFFFFFD / GetYScrollable 0x18005A180 / StartDefer 0x180030FF0 / 120-magic 0x88888889 除法序列 / SPI_GETWHEELSCROLLLINES(0x68)经 USER32!SystemParametersInfoW(IAT 0x1801194D0,iat_map.txt)/ GetVScroll=[vtable+0x180] / LineUp 0x180086480、LineDown 0x180087B90 虚槽选择 / EndDefer 0x1800263D0 / InputEvent+0x8 置 1。
- **vtable 槽位解析**:ScrollBar 主 vtable 0x105BA8 与 TouchScrollBar 0x1059A8 逐槽(符号 RVA 反查):+0x8 GetPosition 0x180081690、+0x28 GetLine 0x1800A9610、+0x30 SetPosition 0x180084B70、+0x60/68/70/78 = LineUp/LineDown/PageUp/PageDown(TouchScrollBar 同槽位 0x1800CEE10/CED90/CF0E0/CF060)。
- **SetPosition→属性管道**:0x180084B70 → _SetValue(PositionProp@0x180072910)。
- **BSV::OnListenedPropertyChanged**:0x180059C10(@line 107533 起),滚动条身份比对 +0x8/+0x10、PositionProp 规格块 0x180106C50、GetPinning 0x18005A440、H/V 滚动条 vtable+0x178/0x180、SetRange 族 vtable+0x38。
- **TSV::OnInput 设备分发**:0x180067550:+0x10==3 前置、设备 1/9(testl 0xFFFFFFF7)、设备 2(鼠标,可缩放检查)、设备 3(0x1800676B4:|delta|>8 → TSV+0x130=1)、设备 5(0x1800676F8:SetContactNeeded 0x18002E590);SetContact 0x18005D0A0;EnableManipulations 0x18005C84C(0x180067746 处调用)。
- **布局落位链**:Viewer::_SelfLayoutDoLayout 0x18006D260(clamp+取负)→ _UpdateLayoutPosition 0x180038BF0 → OnGroupChanged 0x180046E00 → SetGadgetRect IAT 0x180195028(line 84262)/ InvalidateGadget IAT 0x1801950E8(line 84275)——duser IAT 槽位表 iat-slots.txt(slot 2/26)。
- **duser 物理层引用**:WndProc 子类化链 0x180008DC0→0x180008F40、GPCB EventMsg 0x83F8 族、WM_PAINT 管线 0x180001BD0→0x180002320→Element::Paint —— duser-render-internals.md §3.1/§1.5(原报告【实锤】,本文沿用)。
- **EventMsg 三级流水线与"无中心翻译表"结论**:`17-events.md`(`17-events.md`)§0/§6,本文引用。
- **虚拟化**:TSVEnableVirtualization 工厂 0x1800EAB70 / attach 0x1800EAE50(Element+0x12C=1)/ SetVirtualizeElements 0x1800AABB0;WebcamUi UIFILE_200 line 13 XML 原文。
