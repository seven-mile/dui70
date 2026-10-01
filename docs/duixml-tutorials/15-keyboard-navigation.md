# 教程 15:键盘导航 —— 分布式 GetAdjacent 与 NavScoring 打分

> 系列教程第 15 篇(P4 布局与导航三部曲之三)。前置:`17-events.md`(Event/UID 机制)、`14-layout-protocol.md`(Layout 虚协议,GetAdjacent 是 vtable 第 7 槽)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:按 Tab/方向键时发生了什么?答案不是一张全局 Tab 序表,而是一场**分布式问询**:每个元素被问"你的邻居是谁",它再问自己的布局对象,布局对象用**几何打分器 NavScoring** 在孩子里选最优。本篇指令级还原打分算法。

---

## 0. 全景:一次方向键的全部旅程

```
用户按 ↓
  │
  ▼
HWNDElement::OnEvent (0x2E3F0) 识别 KeyboardNavigate 事件
  │  (Event.uid == Element::KeyboardNavigate(), 工厂 0x2E750)
  ▼
Element::OnEvent (0x2E5B0) KeyboardNavigate 分支 (0x2E69E-0x2E71D)
  │  组装 NavReference{0x18 字节: cb, target, refPos}
  │  调虚槽 vtable+0x98 = Element::GetAdjacent(this, target, dir, &navRef, 1)
  ▼
Element::GetAdjacent (0x7DA10)                        ← 每个元素一份
  │  委托给自己的布局对象:vtable+0x38 = Layout::GetAdjacent
  ▼
FlowLayout::GetAdjacent (0x87460) 等                  ← 每个布局一份
  │  NavScoring::Init  →  对每个候选:NavScoring::Try
  │                          └─ Try → TrackScore(几何打分)
  ▼
胜者 Element::SetKeyFocus (vtable+0xA8)
```

心智模型(承接 outline §7):**焦点是元素属性而非窗口状态;导航是"问布局要邻居"的分布式协议;布局用几何打分选邻居。** 没有任何全局 Tab 表——"Tab 序"是每次按键时现场算出来的。

---

## 1. 事件侧:KeyboardNavigate UID【实锤】

`17-events.md` 已实锤 `Element::KeyboardNavigate()` 工厂(0x2E750,`leaq 0x18011FDE3` 返回 UID 常量)。本篇补上消费侧:

`HWNDElement::OnEvent`(0x2E3F0)在 0x2E418 检查 `testl $0xfffffffd, 0x14(%rdi)`(Event.phase,`17-events.md` 的 Event 布局 +0x14 是 phase:1=Preview,2=Bubble,3=???)——**KeyboardNavigate 默认只在特定 phase 处理**。命中后 0x2E430 比对 UID,走 `Element::OnEvent`。

`Element::OnEvent` KeyboardNavigate 分支(0x2E69E-0x2E71D),指令级:

```
0x2E6B3:  movq $0x18, 0x30(%rsp)     ; NavReference.cb = 0x18(24 字节)
0x2E6BC:  movq %rdx, 0x38(%rsp)      ; .target = 事件 sender
0x2E6C1:  movq %rbp, 0x40(%rsp)      ; .refPos  = 参考点(鼠标位?)
0x2E6C6:  cmpq %rsi, %rdx            ; target == this?
0x2E6D6:  movl 0x20(%rdi), %r8d      ; dir = Event+0x20(方向码,见 §2)
0x2E6DA:  movl $0x1, 0x20(%rsp)      ; flags = 1
0x2E6E2:  movq 0x98(%rcx), %rax      ; vtable+0x98 → Element::GetAdjacent
0x2E6EC:  call                       ; GetAdjacent(this, target, dir, &navRef, 1)
0x2E6F1:  testq %rax,%rax ; je done  ; 找不到邻居 → 事件到此为止
0x2E6FD:  cmpb %bpl, 0x24(%rdi)      ; sender 的某 bool(Event 已处理位)
0x2E703:  call [vtable+0xA8]         ; SetKeyFocus(胜者)
0x2E715:  movb $1, 0x10(%rdi)        ; Event.fHandled = TRUE
```

(target != this 时先经 `GetImmediateChild` 0x2E732 折算成"this 的直接孩子"再传——树上非直接孩子也能当导航锚点。)

**与`17-events.md` 的衔接**:UID 机制(工厂常量 + Event+0x08 比对)在 P7 已实锤;本篇新增的是 Event+0x20=方向码、Event+0x24=bool、flags=1 三个字段语义。

---

## 2. 方向码:dir 参数的编码【实锤+强推】

`DuiNavigate::Navigate` 内部函数(0xAB1D4)对第 4 参(edi 保存的 dir)做枚举分发:

```
0xAB24A:  cmpl $0x8,  %edi → 左右?  见 0xAB28D 分支
0xAB24F:  cmpl $0xa,  %edi
0xAB254:  cmpl $0xc,  %edi
0xAB259:  cmpl $0xe,  %edi
```

四个值 8/0xA/0xC/0xE,等距 2——枚举 {8,10,12,14}。结合 `ElementProvider::Navigate`(0x4F5B0 起,UIA 入口)的映射:`navdir=1→0xC`、`2→0xE`、`3→0x8`、`4→0xA`(UIA NavigationDirection:1=Parent→?? 实际看 0x4F5C6 的 switch:esi=1 → 0xC;esi=2 → 0xE;esi=3 → 0x8;esi=4 → 0xA;esi=5+0x9)。**【实锤:四值存在 + UIA 映射;哪值对应上下左右,依据 DuiNavigate::Navigate 各分支对目标矩形的比较方向(0xAB28D: `cmpl 0x4(%rbx), %edx; jl 拒绝`——目标必须在锚点矩形某侧)推断:8/0xC 是垂直对(上下),0xA/0xE 是水平对(左右);具体谁上谁下未单独钉死,标注强推】**

Tab/Shift+Tab 不走这四值——它们是 GetAdjacent 的另一种调用(flags 或 dir 的其他值),或者直接走 Selector/ShellBorderLayout 的 _CalcTabOrder(`14-layout-protocol.md` §4.1)。【猜想:Tab 与方向键在协议里是否同槽?未见 Tab 专用码,见未知清单】

---

## 3. NavScoring:打分算法指令级还原【实锤——本篇核心交付】

三个函数:`Init`(0xAAE60)、`Try`(0xAB050)、`TrackScore`(0xAAF90)。NavScoring 结构(0x20 字节):

```
+0x00  int    _curScore    (当前最佳分数,Init 置 0)
+0x08  void*  _pBest       (当前最佳候选,Init 置 NULL)
+0x10  int    _axis        (主轴索引 0/1)
+0x14  int    _min         (主轴下界)
+0x18  int    _max         (主轴上界)
+0x1c  int    _maxScore    (分数上限 = Init 时 (max-min+1)/2)
```

### 3.1 Init:量出锚点的"走廊"【实锤】

`Init(Element* anchor, int dir, NavReference* ref)`(0xAAE60):

1. 取锚点 `GetExtent`(0x5B860)→ 锚点矩形 w/h(0xAAED9 存 -0x10/-0xC);
2. 若 ref 里有参考矩形(+0x10 所指,0xAAEA9 movups 读 16 字节 = {x,y,w,h}),则用参考矩形叠加锚点位置(`MapElementPoint` 0x49BF0 把 ref 坐标映射进锚点坐标系,0xAAF0C-0xAAF1A 累加);
3. **算主轴**:`shrl $0x2, %r15d; notl; andl $0x1`(0xAAF22)——即 `axis = (~dir >> 2) & 1`。dir=8/0xC(垂直对)时 axis=0?算一下:8>>2=2,~2&1=1;0xA>>2=2→axis=1;0xC>>2=3,~3&1=0;0xE>>2=3→axis=0。**等等,重新算:0xA=10,10>>2=2,~2=…101, &1=1;0xE=14>>2=3,~3&1=0。所以 {8→1, 0xA→1, 0xC→0, 0xE→0}——同轴配对是 (8,0xA) 和 (0xC,0xE)!** 这修正了 §2 的猜测:垂直对是 8/0xA,水平对是 0xC/0xE。【实锤:位运算指令直读;§2 的"哪对是垂直"以此为准修正】
4. 存 `_min/_max`:`-0x18(%rbp,%r15,4)` / `-0x10(%rbp,%r15,4)`(0xAAF35/0xAAF3A)——即锚点矩形在 axis 轴上的两个坐标(x 或 y 起止);
5. `_maxScore = (_max - _min + 1) / 2`(0xAAF44 `subl %ecx,%eax; incl; idivl $2`,0xAAF5B 存 0x1C)——**锚点在该轴跨度的一半**;
6. `_curScore=0`、`_pBest=NULL`(0xAAF55 `andq $0, 0x8(%r12)`、0xAAF1D `andl $0` 等)。

### 3.2 Try:问一个候选【实锤】

`Try(Element* candidate, int dir, NavReference* ref, ULONG flags)`(0xAB050):

```
1. 候选为 NULL → 返回 0
2. 先递归问候选自己的孩子:vtable+0x98(GetAdjacent 虚槽,0xAB074)!
   —— Try 会先让候选"代答"(继续向深处导航),若孩子给出结果,拿孩子的结果继续打分
3. TrackScore(this, 候选(或其代答者), ref)
```

第 2 步是**分布式协议的递归枢纽**:每个候选先被问"你自己有更好的邻居吗",答案再交给打分器。这就是"没有全局表"的实现方式——导航结果是整棵树现场递归投票投出来的。

### 3.3 TrackScore:打分公式【实锤】

`TrackScore(NavScoring* this, Element* candidate, NavReference* ref)`(0xAAF90),逐指令还原:

```
GetLocation(candidate)  → 0xAAFBE → loc(POINT*)
axisX = loc[axis]                          ; edi  (0xAAFCF: (%r9,%rax,4))
GetExtent(candidate)    → 0xAAFE0 → ext(SIZE*)
axisE = ext[axis] + axisX                  ; ebx  = 终点坐标 (0xAAFF4: addl)
max = max(this->_max, axisE)               ; 0xAAFFF cmpl+cmovle: eax
min = min(this->_min, axisX)               ; 0xAB008 cmpl+cmovge: ecx
score = max - min                          ; 0xAB00D subl
if (score <= this->_curScore) return 0     ; 0xAB00F cmpl (%r14) + jle
this->_curScore = score                    ; 0xAB017
if (!this->_pBest) this->_pBest = candidate; 0xAB01A cmoveq
this->_pBest = ref?ref:candidate           ; 0xAB022 存 0x8(%r14)
return (score > this->_maxScore)           ; 0xAB01E cmpl 0x1c + setg
```

**打分公式:`score = max(锚走廊上界, 候选终点) − min(锚走廊下界, 候选起点)`——即"候选与锚点在主轴上的合并跨度"。分数越小越好(首次 TrackScore 必收:score>0=curScore 初始),早停条件:一旦 score 超过 _maxScore(锚点跨度一半),返回 TRUE 通知调用方"这个方向不可能再有更好的了"。**

直觉解读:沿导航方向找邻居,离锚点**在主轴上跨度越小**的候选越好——这就是"视觉上最近"的几何近似。_maxScore 早停防止在长列表里扫完全程。

### 3.4 布局侧怎么用打分器:FlowLayout::GetAdjacent【实锤】

`FlowLayout::GetAdjacent(this, from, to, dir, ref, flags)`(0x87460)骨架:

```
flags&1 → 直接走别的路径(0x8785B)
缓存必须存在且非脏(0x8749B 检查 0x40 项数 / 0x874A0 检查 0x18 脏标志)
GetChildren(from) → 孩子数组
NavScoring::Init(from, dir, ref)            ; 0x874CB
候选遍历:
  dir&2(反向)→ 从缓存尾/头起倒扫(0x874ED testb $0x4 / 0x874F7 testl $0x2 分支决定起点与步进)
  每候选: NavScoring::Try(candidate, dir, ref, flags)  ; 0x8754E 等 4 处
  (0x875B1 区域:按缓存行的 x/y 分组比较——FlowLayout 的行缓存在这里参与剪枝)
返回 _pBest
```

四个 Try 调用点(0x8754E/0x87604/0x876C8/0x87742)对应正/反向 × 行内/跨行的候选枚举路径。**注意:方向值 dir 的位 0x2 = 反向、位 0x4 = ?,与 §2 的 8/0xA/0xC/0xE 对上:同轴一对恰好差 2!(8 与 0xA 差 2,0xC 与 0xE 差 2)——位 1 就是方向符号位。**【实锤:位测试指令 + 枚举值差;flags 位 0x1 的旁路(0x8748B testb $1 → 0x8785B)语义未展开】

---

## 4. 消费侧:谁触发导航?

### 4.1 UIA 无障碍入口【实锤】

`ElementProvider::Navigate`(调用点 0x4F5F7):UIA 的 NavigateDirection(1-4)映射到 8/0xC/0xA/0xE 四码后调 `DuiNavigate::Navigate`(0xAB0D0)。即**屏幕阅读器/无障碍客户端的方向导航与键盘导航共用同一条分布式协议**——本文与 UIA 桥(P6 教程)在此接轨。

### 4.2 DuiNavigate::Navigate:外层循环【实锤】

外层(0xAB0D0):遍历候选 DynamicArray,逐个调内部函数(0xAB1D4)。内部函数做四方向几何门(§2 各分支:目标矩形必须在锚点矩形的正确一侧,否则 `orl $-0x1,%eax` 返回 -1 拒绝),通过后把结果交给打分流程。**外层无递归,递归全在 Try 的"候选代答"里(§3.2)。**

### 4.3 语料侧唯一足迹:bootux 的 target=【实锤】

键盘导航协议在 XML 语料里的**唯一可见足迹**是 bootux(启动菜单)的 `target=` 属性(20+ 处):

```
bootux\UIFILE_101.xml:13   <button ... target="{back}" .../>
bootux\UIFILE_600.xml:23   <button id="atom(...)" target="AdvancedBootOptions_ChooseDevicePage"
                             attach="AdvancedBootOptions_OnChooseDevice" .../>
```

target 指向**页面名**(Navigator/Browser 页系统的 TargetPage,nav_members.txt:Navigator::TargetPageProp 0xDD500/GetTargetPage/SetTargetPage;Browser 事件 Entered/Leaving/StartNavigate)——这是**页面级导航**,不是元素级邻居导航。两个"导航"同名不同层:**元素级 = 本篇的 GetAdjacent 分布式协议;页面级 = Navigator/Page 的 ID 跳转。** 键盘方向键协议本身**没有任何 XML 足迹**——它是纯运行时几何计算,这正是 outline §7 说"语料里看不见它"的原因。【实锤:target= 语料 + Navigator 成员表;两层关系为架构陈述】

---

## 5. 焦点属性族:协议的另一半

outline §7 列的状态属性对(语料频率):`active="mouse|keyboard|pointer"`(mouse 123 / keyboard 71)、`shortcut="auto"` 157 处、`<focusindicator>` 标签 25 处、KeyFocused/MouseFocused/KeyWithin/MouseWithin 状态属性对。它们是**焦点协议的属性面**:

- `Element::SetKeyFocus`(vtable+0xA8,0x72D60)是导航的终点动作(§1 0x2E703);
- `OnKeyFocusMoved`(vtable+0x50,0x6E200)是焦点迁移通知——DialogElement/Selector/TouchScrollViewer 等各有覆写(成员表);
- `HWNDElement::GetWrapKeyboardNavigate`(0x2A11B0 附近,实为 0xA11B0)+`WrapKeyboardNavigateProp`(0x88FC0):0x2E547 处 `GetWrapKeyboardNavigate` 返回真时,`andl $0x9, %eax; cmpb $0x9`——**dir 8|1=9 的组合码触发"环绕导航"**(到边回头)。【实锤:0x2E544-0x2E562 指令序列;环绕的完整行为未追】

心智模型回收:**"焦点是元素属性"——KeyFocused 是 Property,导航只是改这个 Property 的事务;"导航是问布局要邻居"——没有焦点管理器,只有每个元素的 GetAdjacent 虚槽和 NavScoring 几何投票。**

---

## 6. 未知问题清单

1. dir 四码到"上下左右"的**精确语义命名**(8/0xA 垂直对、0xC/0xE 水平对已实锤,哪只是"上"哪只是"下"需跑 UITest 或逆 ElementProvider 映射注释);
2. flags 位 0x1(FlowLayout::GetAdjacent 的旁路 0x8785B)与位 0x4(0x874ED)的**确切语义**;
3. Tab/Shift+Tab 的**完整路径**(是否也走 GetAdjacent,还是 Selector::_CalcTabOrder 专线;ShellBorderLayout 的 Tab 序如何并入);
4. `NavReference.refPos`(0x2E6C1 存的 rbp)的**来源**(鼠标位置?上次焦点?)——Init 对 ref 矩形的叠加逻辑暗示"参考点走廊"可偏移;
5. Try 的"候选代答"递归(§3.2)与布局自身枚举(§3.4)的**分工边界**(谁先谁后、去重逻辑);
6. KeyWithin/MouseWithin 的**进入/退出判定**(outline 遗留,本轮未触及);
7. `focusindicator` 标签 25 处——框架级绘制机制还是纯视觉样式?未查。

## 7. 证据索引

| 断言 | 级别 | 位置 |
|---|---|---|
| Element::OnEvent KeyboardNavigate 分支(组 NavReference/调 vtable+0x98/SetKeyFocus/handled) | 实锤 | 0x2E69E-0x2E71D 反汇编 |
| HWNDElement::OnEvent 的 phase 门 + WrapKeyboardNavigate 环绕 | 实锤 | 0x2E418/0x2E544-0x2E562 |
| Element vtable+0x98=GetAdjacent, +0xA8=SetKeyFocus | 实锤 | Element vftable 0x1037C0 解码 |
| Layout vtable+0x38=GetAdjacent(基类返回 NULL) | 实锤 | 0x180107D00 解码 + 0x7B470 |
| dir 枚举 {8,0xA,0xC,0xE},位 1=方向符号 | 实锤 | 0xAB24A-0xAB259 + 0x874ED/0x874F7 位测试 + 差 2 观察 |
| UIA NavigateDirection→四码映射 | 实锤 | 0x4F5C6-0x4F5E8 switch |
| NavScoring 结构 6 字段布局 | 实锤 | Init/Try/TrackScore 全反汇编交叉 |
| axis = (~dir>>2)&1;(8,0xA)=垂直对 | 实锤 | 0xAAF22 位运算直读 |
| _maxScore=(max-min+1)/2 早停 | 实锤 | 0xAAF44-0xAAF5B |
| 打分公式 score=max(锚上界,候选终点)−min(锚下界,候选起点),越小越好 | 实锤 | 0xAAFFB-0xAB012 |
| Try 的候选代答递归(先问孩子的 vtable+0x98) | 实锤 | 0xAB074 |
| FlowLayout::GetAdjacent 四路径 Try 调用 | 实锤 | 0x8754E/0x87604/0x876C8/0x87742 |
| DuiNavigate::Navigate 内部几何门(目标须在锚点正确一侧) | 实锤 | 0xAB242-0xAB2DD 各 cmpl/jl 拒绝分支 |
| bootux target= 页面导航与元素导航分层 | 实锤(语料+成员表)/架构陈述 | §4.3 |
| 哪只码是"上" | 强推未钉死 | 未知清单 1 |

> 本篇为 P4 任务书"NavScoring 打分算法还原"的交付:Init/Try/TrackScore 三函数全部指令级还原,打分公式与早停阈值均为实锤级。
> 系列回顾:[教程 13 布局版图](13-layout-landscape.md) · [教程 14 Layout 虚协议](14-layout-protocol.md) · [教程 17 事件与 UID](17-events.md)
