# 教程 17:事件系统 —— 从 Win32 消息到 UID 比较

> 系列教程第 17 篇。前置:`16-startup-and-threading.md`(启动序列、每线程 gadget 世界)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> EventMsg ABI 的完整推导在 `duser-deep-dive.md` §1/§1.3,本文**只引用不重推**;本文的增量是 **dui70 侧的翻译链**:哪个函数把 EventMsg 变成 Element 事件、UID 怎么构造、监听器怎么被遍历。

---

## 0. 全景:三级流水线

鼠标点了一下按钮,在 DirectUI 内部走了三级:

```
第1级 duser(gadget 层)
    Win32 消息 → duser 子类化 WndProc → 翻译成 EventMsg{msg≥0x8000, hGadget, ...}
    队列/同步派发:DUserSendEvent(同步)/ DUserPostEvent(异步)
第2级 dui70(翻译层)★ 本文主战场
    _DisplayNodeCallback(0x18002EDB0)按 EventMsg.msg 分发:
      0x83F8  → DUI 路由事件(带 UID)
      0x83FE  → 通用 Element 事件(FireEvent 出口)
      0x83FB  → 属性查询(pResult 写回)
      0x83FF  → 延迟销毁
    翻译产物:Element::Event 结构,UID 在 Event+0x8
第3级 使用者代码
    IElementListener::OnListenedEvent / EventListener lambda
    ev->type == TouchButton::Click   ← UID 指针比较
```

第 1 级的 EventMsg ABI(`{cbSize, msg, hGadget, flags, pad, pResult@+0x18, payload@+0x20}`,三种 cbSize 0x10/0x20/0x28)与 msg id 全表(0x8001-0x8401)见 duser-deep-dive.md §1/§1.3。本文从第 2 级开始。

---

## 1. 入口:_DisplayNodeCallback 按 msg id 分发【实锤】

dui70 把 `_DisplayNodeCallback` 注册为 gadget 回调(GPCB),duser 每投递一个 EventMsg 就进这里(r14 = EventMsg 指针)。反汇编还原的 switch 骨架(disasm 行 55580-55710):

```
ecx = EventMsg.msg
switch (msg):
  case 0x83F8:                       // DUI 路由事件
      s_HandleDUIEventMessage(element, EventMsg)   ← 行 55684
  case 0x83FE:                       // 通用 Element 事件
      ecx&3 → Event+0x14(低两位 = 路由相位)
      element->vtable+0x158(OnEvent)  ← 行 55594
      element->vtable+0x68 (OnInput)  ← 行 55599
  case 0x83FC:  → 默认动作队列路径    // 行 55583 起
  case 0x3EC:                        // gadget 层辅助消息
  default:     → 忽略
```

两个关键细节【实锤】:

1. **0x83FE 的相位搬运**:`movl 0x10(%r14), %ecx; andl $0x3, %ecx; movl %ecx, 0x14(%rax)` —— EventMsg.flags 的**低 2 位**被搬进 Event+0x14。对照 duser-deep-dive §1:flags+0x10 的 bit0 是 HandleNotify 前置条件、bit1 是 swallow;dui70 侧把它们作为"路由相位"接收。
2. **双虚调用**:同一条 0x83FE 消息先调 vtable+0x158(OnEvent,元素语义处理)再调 vtable+0x68(OnInput,输入处理)——这就是"行为类(Button 子类)重写 OnEvent 改变语义,基类 OnInput 兜底翻译"的机制基础。

**s_HandleDUIEventMessage**(0x18002FD20,行 56310-56334)是 0x83F8 的处理器,完整还原(很短,值得全贴):

```
rax = EventMsg+0x18                    // 指向 DUI 侧 Event 结构
r8  = EventMsg.flags & 3
rax->0x14 = r8                         // 相位写入 Event
call [element->vtable+0x158]           // OnEvent(element, Event)
call [element->vtable+0x68]            // OnInput(element, Event)
return Event+0x10 的 bool              // 处理者是否吞掉
```

——**dui70 侧"翻译"本身极薄**:EventMsg 的 payload 在发送前就已是 DUI Event 结构(由 dui70 构造、塞进 EventMsg),回调侧只做相位搬运 + 双虚调用。真正的事件**语义合成**发生在 FireEvent(§3)。

---

## 2. UID:16 字节不透明 blob 的地址【实锤】

### 2.1 机制

每个事件类型对应一个**静态工厂函数**,签名 `?X@Class@DirectUI@@SA?AVUID@@XZ`(返回 UID 按值)。反汇编(TouchButton::Click@0x18004F7A0):

```
TouchButton::Click:
  leaq 0x180121C08, %rax     ← .rdata 常量地址
  movq %rax, (%rcx)          // 写入返回槽(sret)
  movq %rcx, %rax
  retq
Button::Click:
  leaq 0x180121C09, %rax     ← 相邻地址,差 1 字节!
```

76 个这样的 blob 分布在 .rdata 的六个聚集区(0x18011FDEx / 0x180120xxx / 0x180121Cxx / 0x180122Cxx / 0x180126Dxx-0x180129xxx)。**blob 内容无语义**——它与相邻的字符串数据重叠(0x180121C08 起的 16 字节里能看到 UTF-16 "behavior" 的片段;PVLAnimation::NotifyStart 系列干脆排进一个 GUID 样式的 16 字节序列,但那是数据复用,不是语义)。

所以:**事件类型标识 = blob 的地址;两个事件相等 = 指针相等**。UID 既不是 GUID 也不是整数枚举——链接器布局即身份。这也解释了为什么 UID 工厂必须内联展开(每次调用同一个 leaq),以及为什么跨 DLL 比较安全(dui70 内自洽)。

全表:`.local/build/ui-mental-model/uid_table.txt`(76 blob 地址 + 字节dump)、`eventids.txt`(78 个工厂按类分组)。

### 2.2 使用者侧的事件字典

78 个事件工厂按类分组(节选,全表见 eventids.txt):

| 家族 | 事件 | 使用者何时遇到 |
|---|---|---|
| Element | AnimationChange / DCompDeviceRebuilt / KeyboardNavigate | 动画/DComp/键盘导航 |
| Button / TouchButton | Click / Context / RightClick / MultipleClick | 所有按钮交互 |
| Edit / TouchEditBase | Enter / CaretMoved / Cut / Paste / UserTextChanged | 文本输入 |
| Selector / Combobox / TouchSelect | SelectionChange | 下拉/列表选择 |
| TouchScrollViewer | ManipulationStarting/Delta/Started/Completed 等 12 个 | 触控滚动手势全生命周期 |
| TouchScrollBar | InteractionStart/End / AnimateScroll / ActiveStateChanged | 滚动条直接交互 |
| PVLAnimation | NotifyStart/Complete/Implicit 等 11 个 | 动画引擎回调(见 animation-expressiveness.md) |
| HWNDElement | ThemeChange / ImmersiveColorSchemeChange / WindowDpiChanged / CompositionChange | 系统变化广播 |
| Thumb / PushButton / Browser / ... | Drag / Hosted / Entered ... | 特定控件语义 |

**没有中心化注册 API**——你的"事件字典"就是这张 78 项表,比较用 UID 指针相等(UITest.cpp:565 `ev->type == TouchButton::Click`)。【实锤】

---

## 3. FireEvent:Event 结构的构造现场【实锤,本次新升级】

`Element::FireEvent(Event* ev, bool, bool)`@0x1800459C0 反汇编完整还原(这是 dui70→duser 方向的出口,与 §1 的入口对称):

```
rax = this->+0x8                          // 元素自己的 gadget 句柄(HGADGET)
栈上构造 EventMsg:
  +0x00 cbSize  = 0x20                    // 一指针 payload
  +0x04 msg     = 0x83FE                  // 通用 Element 事件
  +0x20 payload = rax(?) — 实为 EventMsg+0x28 存 Event 指针
若 bool 参数1: ev->+0x00 = this           // 反填 sender
ev->+0x18 = 0; ev->+0x10 = 0              // 清 uFlags/cancel
edx = bool 参数2(bBubble 零扩展)
call [IAT 0x180195088] = DUserSendEvent   // 同步投递
```

对照 duser-deep-dive §1.5 的陷阱提示,这里**明确**了两个长期【强推】:

1. **Event+0x10/+0x18 属于 DUI 侧 Event 结构**(uFlags / cancel),FireEvent 在投递前清零它们——不是 EventMsg 的字段。之前从"回调侧双 bool 清零"推断过这一布局,现在从构造侧独立验证。【实锤(升级)】
2. **Event+0x8 = UID 指针**:FireEvent 不写它(构造者负责),但回调侧的比较指令 `cmpq uid_addr, 0x8(%rdx)`(遍布 OnEvent 家族,如 Element::OnEvent 行 56322 附近的 KeyboardNavigate 比较 `movq 0x8(%rdi), %rax; cmpq %rax, ...`)+ 本节的 sender/gadget 关系,把 Event 布局钉死为 `{+0x00 sender, +0x08 uid, +0x10 uFlags, +0x14 phase, +0x18 cancel, ...}`。【实锤(升级);+0x1c 之后的字段仍未知】

`BroadcastEvent`(0x180072D40)是兄弟出口:先把 Event+0x14 置 4(相位=广播),然后进 `_BroadcastEventWorker`。

---

## 4. 冒泡与广播:两个遍历方向【实锤】

### 4.1 _BroadcastEventWorker:祖先方向(冒泡)

`_BroadcastEventWorker`(0x18002E890)的循环骨架:

```
loop:
  ev->+0x10(uFlags) 有"停止"位? → 结束
  element 有关注能力?           // 检查元素状态位 0x95 的 bit1
  children = element->GetValue(ChildrenProp)   // 拿子链
  for child in children:
      if child 状态位(0x95 bit1) 开:
          _BroadcastEventWorker(child, ev)      // 深度优先,先子后父
```

注意这是**递归下降再回升**的遍历(先整棵子树再回到祖先监听者),配合 `GMF_BUBBLED` 相位位,监听器可以区分"事件来自我"与"事件途经我"。

### 4.2 系统广播的惯用法

主题切换等系统变化走"取根→广播":

```
HWNDElement::_HandleImmersiveColorSchemeChange:
    GetRoot() → _BroadcastEventWorker(root, Event{ImmersiveColorSchemeChange UID})
```

(disasm 行 54304-54325;ThemeChange/WindowDpiChanged/CompositionChange 同构。)

### 4.3 监听器遍历:OnEvent 的默认实现【实锤,本次新还原】

`Element::OnEvent`@0x18002E5B0 默认实现(监听器分发的真身):

```
if (ev->+0x14 相位 & ~2) == 0 且 uid == Element::KeyboardNavigate:
    → 键盘导航特化路径(取 0x98 状态字、0xa8 虚槽,标记 ev->+0x10=1)
listeners = element->+0x40                    // 监听器数组(见18-properties-and-lifecycle.md §AddListener)
saved = listeners->+0x00; listeners->+0x00 = &迭代器快照   // 快照迭代防遍历中修改
for i in 0..listeners->+0x08(count):
    p = listeners->+0x10[i*8]
    call p->vtable+0x28                       // = IElementListener::OnListenedEvent
    if ev->+0x10(cancel/handled 位): break
恢复快照;若遍历期间列表变更 → 走 0x18001E250 的慢路径重整
```

三个使用者可感知的结论【实锤】:

1. **监听器按注册顺序正序调用**(数组 0x10 起、count 在 +0x08);
2. **任一监听器置 ev 的 handled 位即可截断**后续监听器(同元素内);
3. **遍历有快照保护**:OnListenedEvent 里 AddListener/RemoveListener 当前元素监听器不会崩(变更走慢路径)。

RemoveListener@0x18001E1C0 的实现还揭示一个细节:移除时槽位不真删除,而是**填入一个静态空监听器**(0x180103438 处的 `??_7HWNDHost` 邻接 vtable,即"哑元 vtable"),count 不减——所以已注册监听器索引稳定。这解释了为什么 IElementListener 的 vtable 顺序是公开 ABI(UITest.cpp:52-104 注释的 0-5 槽):哑元必须实现同一接口。

---

## 5. 使用者三件套(全部 UITest 实锤)

### 5.1 树级监听:IElementListener

```cpp
// UITest.cpp:26-104(LogListener 精简)
struct LogListener : IElementListener {          // vtable 槽位注释见原文
  void OnListenerAttach(Element*) override {}
  void OnListenerDetach(Element*) override {}
  bool OnPropertyChanging(Element* elem, const PropertyInfo* prop,
                           int, Value* v1, Value* v2) override {
    // prop->name 可直接打印(见18-properties-and-lifecycle.md PropertyInfo)
    return true;                                 // true=放行,false=拒绝修改
  }
  void OnListenedPropertyChanged(Element*, const PropertyInfo*, Value*, Value*) override {}
  void OnListenedEvent(Element* elem, Event* ev) override {
    // 这里收到整棵子树的冒泡事件
  }
  void OnListenedInput(Element*, InputEvent*) override {}
};
pWizardMain->AddListener(&lis);                  // 挂共同祖先
```

### 5.2 便捷监听:EventListener lambda 双构造

```cpp
// 仅事件:UITest.cpp:562
EventListener click_listener([&](Element *elem, Event *ev) {
  if (ev->flag != GMF_BUBBLED) return;          // 只要"冒泡途经"相位? 反例见下
  if (ev->type == TouchButton::Click) { ... }   // UID 指针比较
  if (ev->type == Edit::Enter)        { ... }
});
// 事件+属性双 handler:UITest.cpp:633
EventListener anim_listener(
    [](Element*, Event*) {},
    [](Element*, const PropertyInfo* prop, Value*, Value*) { ... });
```

### 5.3 为什么"监听器挂在共同祖先上"是惯用法

因为**没有 per-event 订阅 API**:AddListener 收的是"该元素子树的全部事件"(冒泡 + 广播),你在 handler 里按 UID 过滤。三个推论:

- 一个祖先监听器 + 一串 `if (ev->type == ...)` 是标准写法(bootux 的 attach 回调同构);
- 挂载点越靠根,收得越多——性能敏感路径(每帧事件)挂近一些;
- `ev->flag == GMF_BUBBLED` 用来区分相位,但注意它过滤的是"非目标相位"——判断"事件目标是不是我"用 `ev->sender` 或直接比较 elem 参数。

### 5.4 XML 侧的痕迹

事件**不在 XML 声明**(没有 `onclick=` 属性);唯一例外是 bootux 的 `attach="{Module!Callback}"`(语料 100+ 处)在解析期把 C++ 回调挂上——**声明式构造、命令式行为**。语料里能观察到的事件痕迹只有状态属性(enabled/selected/pressed)与消费它们的 `<if>` 样式规则——事件语义被降格为"可样式化的状态",与 CSS `:hover` 同构。【实锤,语料】

---

## 6. msg id → UID 映射:dui70 侧翻译表(任务包核心目标)

0x83F8-0x8401 消息族(duser-deep-dive §1.3)中,dui70 侧只消费固定几个:

| EventMsg.msg | dui70 侧处理 | 产生/消费的 UID |
|---|---|---|
| 0x83F8 | s_HandleDUIEventMessage → OnEvent+OnInput 双虚调用 | **UID 直通**:EventMsg.payload 就是已构造的 Event(含 UID)——不查表,原样上楼 |
| 0x83FE | FireEvent 的出口;回调侧同样双虚调用 | 任意 FireEvent 的 UID(控件语义层:Click/SelectionChange/...) |
| 0x83FB | 属性查询(payload+0x20=code 0xe → ElementFromGadget) | 无 UID(查询协议) |
| 0x83FF | 延迟销毁(cbSize=0x10) | 无 UID(生命周期,`18-properties-and-lifecycle.md`) |
| 0x83FC/0x8400/0x8401 | 默认动作队列/Proxy 回调/异步回调 | 未逐个还原 |

**核心结论(诚实的边界)**:dui70 侧**不存在**"msg id → UID"的查表翻译——0x83F8 载荷里的 Event 在 duser 投递前就带着 UID(由 dui70 的 FireEvent 系构造)。真正的"翻译"发生在两个更早的位置:

1. **输入→语义**:按钮类控件(Button/TouchButton 子类)在 OnEvent 里把鼠标相位事件合成为 Click UID——这是**每个控件类自己的代码**,没有中心表;
2. **duser 侧 Win32→EventMsg.msg**:鼠标过滤表(`16-startup-and-threading.md` §2.2 的四张表)决定哪条 Win32 消息成形为哪个 gadget 事件——表在 duser,超出 dui70 范围(见 duser-render-internals.md)。

哪些 UID 直接对应 gadget 消息、哪些是纯 dui70 合成:输入类(Element::MouseWithin 系、KeyboardNavigate)接近前者;控件语义类(Click/SelectionChange/Toggle)是后者。逐 UID 的归属分类因需要逐个控件类的 OnEvent 反汇编,本文标记为【猜想】待验证(见 §7)。

---

## 7. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | 逐控件 OnEvent 的"输入→Click"合成代码(Button vs TouchButton 差异) | 机制位置已知(虚槽 0x158),逐类未读 | 反汇编 Button::OnEvent / TouchButton::OnEvent 对照 |
| 2 | Event 结构 +0x1c 之后字段(payload?缓存?) | +0x00/0x08/0x10/0x14/0x18 已钉死 | x64dbg 观察构造后内存 |
| 3 | GMF_BUBBLED 之外的全部相位值语义(+0x14 的 0/1/2/4 已见) | 部分还原 | 在 _BroadcastEventWorker/FireEvent 里追相位写入点 |
| 4 | 0x83FC/0x8400/0x8401 的 dui70 侧消费者 | 未还原 | _DisplayNodeCallback switch 剩余分支精读 |
| 5 | 键盘导航特化路径(OnEvent 里 uid==KeyboardNavigate 分支的 0x98/0xa8 状态) | 位置已找到 | 与`15-keyboard-navigation.md`(导航)合流 |
| 6 | InputEvent 结构(OnListenedInput 的参数)与 Event 的关系 | 未还原 | OnInput 虚槽 +0x68 的实现者枚举 |
| 7 | 每帧事件的监听器遍历成本(冒泡全树 × 监听器数组) | 结构已知,量化未做 | 探针统计 OnListenedEvent 调用次数/秒 |

---

## 8. 小结与下一篇

- 事件管线 = **EventMsg(duser)→ 相位搬运 + 双虚调用(dui70 入口)→ OnEvent 监听器遍历(使用者)**;
- **UID = .rdata 16 字节 blob 的地址**,比较是指针相等;78 个工厂就是事件字典;
- FireEvent 是 dui70→duser 的出口:构造 0x83FE EventMsg、清 Event 的 uFlags/cancel、同步投递;
- **没有 msg→UID 中心翻译表**——语义合成分散在每个控件类的 OnEvent 里;
- 惯用法:**监听挂共同祖先 + UID 指针比较过滤**;handled 位可截断;监听器数组有快照保护。

下一篇(`18-properties-and-lifecycle.md`):OnListenedEvent 的姊妹回调 OnPropertyChanging 已经剧透了另一个系统——属性。Value/PropertyInfo/引用计数,是 Element 的另一半灵魂。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| _DisplayNodeCallback switch(0x83F8/0x83FE/0x83FC/0x3EC) | 反汇编 | dui70-full-disasm.txt 行 55580-55710 |
| s_HandleDUIEventMessage 全文(相位搬运+双虚调用) | 反汇编 | 行 56310-56334 |
| FireEvent 构造(0x83FE/cbSize 0x20/清 uFlags/cancel/DUserSendEvent) | 反汇编 | Element::FireEvent@0x1800459C0 |
| UID 工厂 = leaq .rdata 地址 | 反汇编 | TouchButton::Click@0x18004F7A0, Button::Click@0x18004F7C0 等 |
| 76 UID blob 地址与字节 | 数据dump | .local/build/ui-mental-model/uid_table.txt |
| 78 事件工厂分组 | 符号表 | .local/build/ui-mental-model/eventids.txt |
| _BroadcastEventWorker 递归遍历 | 反汇编 | 0x18002E890 |
| Element::OnEvent 监听器循环/快照/截断 | 反汇编 | 0x18002E5B0 |
| RemoveListener 哑元替换 | 反汇编 | 0x18001E1C0 |
| AddListener 数组结构(+0x40/+0x08/+0x10) | 反汇编 | 0x18001E8E0(`18-properties-and-lifecycle.md` 详述) |
| 系统广播取根惯用法 | 反汇编 | 行 54304-54325 |
| EventMsg ABI / msg id 表 / flags 位语义(引用) | 既有报告 | .local/audit/duser-deep-dive.md §1, §1.3, §1.5 |
| 使用者三件套(AddListener/EventListener/UID 比较) | 可运行样本 | UITest/UITest.cpp:26-104, 556-583, 633-656 |
| attach= 惯用法 / 事件无 XML 声明 | 语料 | docs/duixml-corpus(bootux 模块) |
