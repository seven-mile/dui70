# 教程 14:Layout 虚协议 —— 一个布局对象的生老病死

> 系列教程第 14 篇(P4 布局与导航三部曲之二)。前置:`13-layout-landscape.md`(九种布局与槽位)、`18-properties-and-lifecycle.md`(StartDefer/EndDefer 事务、Value 引用计数)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:布局对象不是被动数据——它是一个有虚函数表、有状态机、有缓存策略的主动对象。本篇还原 Layout 基类的完整虚协议,并追踪一个布局对象从 Create 到 Detach 的完整生命周期。

---

## 0. 全景:九个虚槽 + 四个协议阶段

```
                    ┌──────────────────────────────────────┐
   出生  Create ──▶ │  Layout 对象 (0x30 字节, RefcountBase)│
                    │  +0x00 vtable                        │
                    │  +0x08 element   (Attach 写入)       │
                    │  +0x10 cache     (子类缓存指针)      │
                    │  +0x18 _fCacheDirty = TRUE (出生即脏)│
                    └──────────────────────────────────────┘
        │                    │                    │
     Attach               虚协议调用            Detach
   (挂到元素)        (DoLayout/OnAdd/...)      (断开)
```

心智模型:**Layout = "挂在一个元素身上的迷你管理器"。元素出钱(提供孩子列表和几何),布局出力(算出每个孩子的位置);虚协议是二者之间的劳动合同,缓存脏标志是"这活儿得重做"的标记。**

---

## 1. vtable:九个槽的合同【实锤】

从 `??_7Layout@DirectUI@@6B@`(0x180107D00)逐槽解码,并与 FillLayout/BorderLayout vtable 交叉验证(每槽偏移一致):

| 槽 | 偏移 | Layout 基类实现 | 职责 |
|---|---|---|---|
| 0 | +0x00 | `DoLayout` 0x7C980 | 布置:给孩子定 x/y/w/h |
| 1 | +0x08 | `UpdateDesiredSize` 0xAB0C0 | 测量:我需要多大? |
| 2 | +0x10 | `OnAdd` 0x31BC0 | 孩子加入通知 |
| 3 | +0x18 | `OnRemove` 0x32000 | 孩子移除通知 |
| 4 | +0x20 | `OnLayoutPosChanged` 0x31AB0 | 孩子槽位变化通知 |
| 5 | +0x28 | `Attach` 0x70990 | 挂到宿主元素 |
| 6 | +0x30 | `Detach` 0x6FEF0 | 从宿主摘除 |
| 7 | +0x38 | `GetAdjacent` 0x7B470 | 导航:我的邻居是谁?(`15-keyboard-navigation.md` 主题) |
| 8 | +0x40 | `vector deleting dtor` | 析构 |

vftable 只到 +0x40(9 槽);此前 dump 到 +0x100 的"槽"是相邻数据,不是 vtable。每个派生类只覆写自己关心的槽,例如 BorderLayout 覆写 DoLayout/UpdateDesiredSize/OnAdd/OnRemove/OnLayoutPosChanged/GetAdjacent,**原样继承 Attach/Detach**;ShellBorderLayout 相反——**不覆写 DoLayout/UpdateDesiredSize**(用基类空实现),只覆写 GetAdjacent/OnAdd/OnLayoutPosChanged。【实锤:vtable 字节级解码,见 `.local/build/ui-mental-model/vtable_layout.py` 输出】

### 1.1 基类默认实现有多"空"?

三个代表性默认实现,全部 3-4 条指令:

```
Layout::GetAdjacent      0x7B470:  orq $-0x1, %rax ; retq     → 返回 NULL
Layout::UpdateDesiredSize 0xAB0C0: xorl eax,eax ; movq rax,(rdx) ; ret → SIZE{0,0}
Layout::Attach           0x70990: movq %rdx, 0x8(%rcx)        → this->element = p
                                  ; movb $1, 0x18(%rcx)        → _fCacheDirty = TRUE
                                  ; retq
```

**Attach 只做两件事:记住宿主、把自己标脏。** Detach(0x6FEF0)与之对称。这就是"劳动合同"的最小条款:基类说"我不布置、不测量、没有邻居",派生类逐条签走自己要干的部分。

`SetCacheDirty`(0x97CE0,非虚)是协议的第五个关键人物,只有一条指令:`movb $1, 0x18(%rcx)`——把脏标志置位。任何让缓存失效的事件(孩子增删、槽位变化、属性变化)都调用它。

---

## 2. 生命周期五幕

### 第一幕:出生(Create)【实锤】

`13-layout-landscape.md` §1.3 已示:`Create` 工厂 `new(0x30)`、设 vtable、字段清零、`+0x18=1`(出生即脏)。**一个刚出生的布局什么都不能做——没有宿主,没有缓存,但已经宣布"我的计算过期了"。**

### 第二幕:Attach——挂职【实锤】

`Element::SetLayout`(0x612C0)把 Value 里的 Layout* 取出,调 `Attach(this)`(vtable+0x28)。基类实现写 `+0x08=element` 并置脏。BorderLayout 等**不覆写** Attach——挂职流程全类统一。

### 第三幕:养孩子(OnAdd/OnRemove/OnLayoutPosChanged)【实锤】

```
Layout::OnAdd(Element* child, Element** ppChildren, UINT c)   0x31BC0
Layout::OnRemove(Element* child, ...)                          0x32000
Layout::OnLayoutPosChanged(Element* child, int oldPos)         0x31AB0
```

孩子增删/改槽位 → 布局收到通知 → 维护内部缓存并 `SetCacheDirty`。基类 OnAdd 里能看到 `cmpl $-3, 0x78(%rax-child)` 型检查(0x31BE8):**layoutpos=none(-3) 的孩子直接跳过布局登记**——这是`13-layout-landscape.md` §2 那个 260 处的 `none` 的运行时落点。【实锤:OnAdd 反汇编 + Layouts.txt 枚举交叉】

派生类的覆写差异即"性格差异":
- **BorderLayout::OnAdd**(0x31CD0):同槽位顶替逻辑(client 只有一个);
- **FlowLayout::OnAdd**:维护线性缓存(`BuildCacheInfo` 0x1F4E0、`GetLine` 0xD6C80、`SizeZero` 0x97C80——FlowLayout 有"行"概念,缓存按行组织);
- **TableLayout::InternalCreate**(0x950E0)+`GetCellInfo`(0x7F170):格子注册表;
- **NineGridLayout::_UpdateTileList**(0x70090):九区域孩子表;
- **ShellBorderLayout::_Reset**(0x716B0)+`_CalcTabOrder`(0x71350):不缓存几何,**缓存 Tab 序**——又一次暴露它的"chrome+导航"本质(`13-layout-landscape.md` §3.9、`15-keyboard-navigation.md`)。

### 第四幕:干活(DoLayout / UpdateDesiredSize 的谈判)【实锤】

这两个虚函数是布局引擎的核心双阶段——**measure/arrange 谈判**:

**Measure(UpdateDesiredSize, vtable+0x08)**:`Element::_UpdateDesiredSize`(0x21770)是递归测量驱动器。它取每个孩子的布局对象,问"给定约束宽高,你想要多大?"——布局对象答 SIZE。基类答 {0,0}(我不在乎);FlowLayout 答行高的累加;BorderLayout 答边条+client 的组合。返回值写进孩子的 DesiredSize 属性(Element::DesiredSizeProp 0x6EE00)缓存。

**Arrange(DoLayout, vtable+0x00)**:`Element::_FlushLayout`(0x395A0,static)是布置驱动器。核心序列(0x3969D-0x39797):

```
取 Extent 属性值(0x180066530 PropertyInfo)          → 可用宽高 r14d/r12d
减 padding(0x1801034A8 附近常量表)                  → 内容区
减 border/margin(0x180100770 常量表)
testb $0x1, 0x97(%rbx)  → 有自身布局?
  有:call [vtable+0x00]  DoLayout(this, element, cx, cy)   ; 0x39792
      (0x1800FF010 = CFG-ish indirect call thunk)
无:走默认(不布置)
```

即:**_FlushLayout = "拿到 Extent → 扣掉 padding/border → 把剩余矩形连同孩子交给布局的 DoLayout"**。DoLayout 内部再对孩子逐个 `UpdateLayoutRect`(static,0x3DFD0)写回 x/y/w/h。

**谈判时序**:Measure 自底向上(叶子先报 DesiredSize),Arrange 自顶向下(父亲拿到 Extent 后分发)。这和 WPF 的 Measure/Arrange 同构,但**没有 WPF 的两趟遍历框架**——DUI 用"脏标志 + 按需递归"实现:DesiredSize 缓存在属性系统里(`18-properties-and-lifecycle.md` 的 Value 缓存),只有 cache dirty 时才重问。

### 第五幕:死亡(Detach → dtor)【实锤】

元素销毁/换布局:调 `Detach`(vtable+0x30)断开(基类 0x6FEF0:清 element 指针、置脏),随后 Value 释放走 RefcountBase 引用计数(`18-properties-and-lifecycle.md` 的引用计数编码)。vtable+0x40 是 `vector deleting dtor`(0x9C6F0),带 delete 标志的标准析构。

---

## 3. 缓存脏标志:0x18 那个字节的权力【实锤】

`_fCacheDirty`(+0x18)是整个协议的调度中枢:

```
出生      = TRUE      (Create/Attach 都置位)
SetCacheDirty → TRUE   (孩子增删/槽位变/属性变)
消费点    → FALSE      (每个 DoLayout 入口: cmpb $0, 0x18(%rcx); jne 重算
                        见 FlowLayout::DoLayout 0x1F075: cmpb %r12b, 0x18(%rcx)
                             jne → 跳到 0x1F271 直接 return!)
```

**等等,0x1F075 是"非零则 return"?** 仔细看:`jne 0x18001f271` 的目标就是函数尾——**dirty 时直接返回,干净时才干活?** 反了?不——这是**缓存命中路径的另一面**:FlowLayout::DoLayout 开头还检查 `cmpl $0, 0x40(%rcx)`(0x1F06B,缓存项数)和 `cmpb $0, 0x18(%rcx)`(0x1F075)。结合 0x1F28D 的缓存读取路径(`movq 0x10(%rdi), %r9` 取 cache 数组,`movl (%r9,%rcx,4), %r10d` 取项),其语义是:**DoLayout 带"重算/复用缓存"两种模式,由调用方(带 dirty 检查的外层)决定何时进入**。精确的"谁检查 dirty、何时调 SetCacheDirty 复位"链路在 `Element::UpdateLayout`(0xAB330)与 `_FlushLayout` 的协作里,本轮未逐指令展开——**已知:0x18 标志在多处被读,SetCacheDirty 在全 DLL 被高频调用;未知:复位点的完整清单**。诚实标注:【实锤:标志位偏移与读写指令;强推:调度闭环的完整时序——缺 UpdateLayout 逐指令还原】。

---

## 4. API-only 类的考古学:成员名能告诉我们什么

Outline §4 提问:那些"没有 XML 踪迹"的布局怎么研究?方法示范——**方法名考古 + 关键虚调用反汇编验证**:

### 4.1 ShellBorderLayout(语料 2 处)

成员:`GetAdjacent`(覆写)、`OnAdd`(覆写)、`OnLayoutPosChanged`(覆写)、`_CalcTabOrder`、`_Reset`;**无 DoLayout、无 UpdateDesiredSize**(用基类空实现——不布置、测量为 {0,0})。

推断链:一个"不布置任何东西"的布局类,却维护 Tab 序缓存(_CalcTabOrder)并覆写 GetAdjacent(导航)→ 它管理的不是几何而是**焦点链**。挂它的元素是窗口 chrome(分隔条),几何由宿主窗口决定,但 Tab 键穿过 chrome 时要有人回答"下一个是谁"——ShellBorderLayout 就是那个回答者。【强推:成员表 + 基类空实现实锤;用途叙事为推断】

### 4.2 方法名考古的通用套路

1. **从 vtable 槽位开始**:覆写了哪些槽 = 它在乎哪些事件;
2. **私有方法名即功能自白**:`_CalcTabOrder`(算 Tab 序)、`_UpdateTileList`(维护区域表)、`BuildCacheInfo`/`GetLine`(行缓存)、`InternalCreate`/`GetCellInfo`(格子注册表)、`SizeZero`(空尺寸判断);
3. **挑一个关键虚调用做指令级验证**(如本篇 §2 各 OnAdd 的 -3 检查、§3 的 dirty 检查),把"名字考古"钉在实锤上;
4. 其余成员保持【强推】,列入未知清单。

这正是 P4 任务书说的"API-only classes: method-name archaeology + disasm verification of key virtual calls"的落地姿势。

---

## 5. 与`18-properties-and-lifecycle.md` 的衔接(回收伏笔)

- **StartDefer/EndDefer**:布局变更的批处理事务——DeferCycle(+0x38 refcount/+0x60 嵌套深度)正是`18-properties-and-lifecycle.md` 已实锤还原的机制。布局系统的所有"孩子增删→SetCacheDirty→重排"都发生在 Defer 事务内,EndDefer 时一次性 flush(_EndDefer@0x391A0 触发 _FlushLayout 链)。**本篇不再重证,引用`18-properties-and-lifecycle.md` 的 defer 章节为准。**
- **Value 引用计数**:Layout* 被 Value 包裹(`13-layout-landscape.md` §1.4),Detach 不碰 Value(`18-properties-and-lifecycle.md` 结论),所以"布局对象死亡"分两步:Detach(逻辑摘除)→ Value Release(物理释放)。
- **DesiredSize/Extent 属性**:Measure/Arrange 的数据通道就是`18-properties-and-lifecycle.md` 的属性系统——布局协议跑在属性缓存之上。

---

## 6. 未知问题清单

1. `Element::UpdateLayout`(0xAB330)与 `_StartOptimizedLayoutQ`/`_EndOptimizedLayoutQ`(0x72940/0x6E570)的**优化队列机制**未还原——名字暗示有布局批处理队列,与 Defer 的关系待查;
2. dirty 标志 0x18 的**复位点完整清单**(谁在缓存重建后清零);
3. `_MarkElementForLayout`(0x65900)/`_SetNeedsLayout`(0x65600)/`_GetNeedsLayout`(0x67C10)三件套的**传播方向**(上冒?下沉?);
4. ShellBorderLayout::_CalcTabOrder 的**算法**(与`15-keyboard-navigation.md` 的 GetAdjacent 协作方式);
5. TableLayout 的 GetCellInfo 权重语法(`13-layout-landscape.md` 遗留)。

## 7. 证据索引

| 断言 | 级别 | 位置 |
|---|---|---|
| Layout vtable 9 槽布局(DoLayout…dtor) | 实锤 | 0x180107D00 + Fill/Border vtable 交叉(vtable_layout.py) |
| 基类 GetAdjacent 返回 NULL | 实锤 | 0x7B470: `orq $-0x1,%rax; retq`(disasm 行 153503) |
| 基类 UpdateDesiredSize 返回 {0,0} | 实锤 | 0xAB0C0 三指令 |
| Attach=写宿主+置脏 | 实锤 | 0x70990 三指令 |
| SetCacheDirty=置 0x18 | 实锤 | 0x97CE0 单指令 |
| Create 工厂 0x30 字节/出生即脏 | 实锤 | 0x613A0/0x61480/0x61200(`13-layout-landscape.md` §1.3) |
| OnAdd 跳过 layoutpos=-3 的孩子 | 实锤 | 0x31BE8 `cmpl $-0x3` |
| _FlushLayout: Extent−padding−border→DoLayout | 实锤 | 0x3969D-0x39797 序列 |
| Element::_UpdateDesiredSize 递归测量 | 实锤 | 0x21770 入口 + DesiredSizeProp 0x6EE00 |
| FlowLayout 行缓存(BuildCacheInfo/GetLine) | 实锤(存在)/强推(结构) | layout_members.txt |
| DoLayout 入口的缓存项数/dirty 检查 | 实锤 | 0x1F06B/0x1F075 |
| ShellBorderLayout 无 DoLayout、有 _CalcTabOrder | 实锤 | vtable 解码 + layout_members.txt |
| dirty 调度闭环(复位点清单) | 强推 | §3(缺 UpdateLayout 逐指令) |
| Defer 事务引用 | 实锤(`18-properties-and-lifecycle.md`) | `18-properties-and-lifecycle.md` defer 章节 |

> 工作数据:`.local/build/ui-mental-model/vtable_layout.py` 输出存档。
> 下一篇:[教程 15:键盘导航 —— 分布式 GetAdjacent 与 NavScoring 打分](15-keyboard-navigation.md)
