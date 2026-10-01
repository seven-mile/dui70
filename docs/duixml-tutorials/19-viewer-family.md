# 教程 19:Viewer 家族分工 —— 从视口原语到手势引擎

> 系列教程第 19 篇(P5 Viewer 与滚动之一)。前置:`13-layout-landscape.md`(九种布局与槽位)、`18-properties-and-lifecycle.md`(StartDefer/EndDefer 事务、Value 引用计数)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:XML 里 `<viewer>`、`<scrollviewer>`、`<touchscrollviewer>` 三个标签背后是三层递进的抽象——视口原语(Viewer)、滚动条合成(ScrollViewer)、手势引擎(TouchScrollViewer)。本篇把每一层的职责边界、XML 属性面、以及"到底谁在滚内容"的物理机制讲清楚。物理层(gadget 树)引用本系列第 10 篇《滚动的物理层》与 duser-render-internals.md,本文**只引用不重推**。

---

## 0. 全景:三个数字背后的分工

| 标签 | 语料出现(30 个 UIFILE DLL,大小写不敏感) | dui70 侧类 | 方法数 | 一句话职责 |
|---|---|---|---|---|
| `viewer` | 309 | `Viewer` | 21(含 4 个属性 getter/setter 对) | 视口原语:偏移 + 裁剪,不带任何滚动 UI |
| `scrollviewer` | 69 | `ScrollViewer` | 19 | 在视口上**合成滚动条**并做滚轮语义 |
| `touchscrollviewer` | 19(13 个文件) | `TouchScrollViewer` | **195**(dui70 第二大类) | 手势/惯性/缩放/吸附/虚拟化/DComp 分层全套 |

> 注:outline §A2 里的 312/69/23 与我的实测 309/69/19 有小出入(统计口径不同,见附录证据索引)。下文一律用实测值并注明方法。

三个类不是三层继承那么简单。**先给结论,后给证据**:

```
Element
   ├── Viewer                    (视口原语;自身即 self-layout 实现者)
   ├── BaseScrollViewer          (滚动语义骨架:偏移属性 + 滚轮处理 + 监听联动)
   │      ├── ScrollViewer       (合成 ScrollBar 经典滚动条)
   │      ├── StyledScrollViewer (样式化滚动条,仅 API 无语料)
   │      └── TouchScrollViewer  (TouchScrollBar + DirectManipulation 手势引擎)
   └── (HWNDElement / 其它分支...)
```

其中 **Viewer 与 BaseScrollViewer 是兄弟分支**;ScrollViewer / TouchScrollViewer **确实**继承 BaseScrollViewer(下面 §1.3 有反汇编实锤,这推翻了 classes.json 继承表的字面读法——那张表缺行,PDB 完整类列表没收录部分中间基类)。

---

## 1. XML 实例:三个真实用例

### 1.1 Viewer:控制面板对话框里的"页主体"

DiagCpl UIFILE_201(系统属性对话框)中的典型形态:

```xml
<element layout="borderlayout()">
    ...
    <Viewer layoutpos="client" sheet="common">
        <element layout="filllayout()">
            <!-- 内容比视口大,但没有任何滚动 UI -->
        </element>
    </Viewer>
</element>
```

关键观察:**语料里 `<viewer>` 的属性面只有布局属性**(layoutpos/layout/margin/width/height/background/sheet 等,309 处无一例外)。`XOffset` / `YOffset` / `XScrollable` / `YScrollable` **不出现在任何 UIFILE 里**——它们是 C++ 属性(Viewer::SetXOffset → XOffsetProp),XML 解析器不认识这些名字。**【实锤】**(语料全量扫描,方法见附录)

这正是 Viewer 的定位:它给宿主程序一个"可编程偏移的裁剪窗口",偏移怎么变(按钮翻页?动画?)是宿主的事。Aero 向导左侧列表的滚动、任务栏缩略图换页,都是 C++ 代码在驱动 SetXOffset/SetYOffset。

### 1.2 ScrollViewer:经典滚动区域

DiagCpl UIFILE_201 第 216 行起(无障碍语义完整,滚动条未显式配置):

```xml
<ScrollViewer xscrollable="false" layoutpos="client"
              accrole="pane" accname="resstr(202)" accessible="true"
              sheet="common">
```

taskbarcpl UIFILE_103 的显式配置(横条永不、竖条常显):

```xml
<ScrollViewer xscrollable="false" yscrollable="true"
              xbarvisibility="never" ybarvisibility="always" .../>
```

racpldlg UIFILE_1000 用 `asneeded`:

```xml
<ScrollViewer xbarvisibility="asneeded" ybarvisibility="asneeded" .../>
```

**属性面(语料实测)**:`xscrollable` / `yscrollable` / `xbarvisibility` / `ybarvisibility`(`never` | `always` | `asneeded`)+ 通用布局/无障碍属性。注意:**没有 XOffset/YOffset**——同 Viewer,偏移是 API 属性。

### 1.3 TouchScrollViewer:从最简到全家桶

**最简**(bdeunlock UIFILE_201,BitLocker 解锁对话框——内容可能超高,一根手指推走):

```xml
<TouchScrollViewer layoutpos="client"
                   XScrollable="false" YScrollable="true"
                   XBarVisibility="never" YBarVisibility="asneeded"
                   InteractionMode="TranslateY|Inertia"
                   active="mouse|pointer"
                   accessible="true" accrole="pane">
```

**全家桶**(WebcamUi UIFILE_200 第 13 行,相机胶卷横向翻页):

```xml
<TouchScrollViewer id="atom(idTSV)"
                   xscrollable="true" yscrollable="false"
                   layoutpos="client"
                   xbarvisibility="never" ybarvisibility="never"
                   accessible="true" accrole="list"
                   ZoomMaximum="1.0" ZoomMinimum="0.6"
                   InteractionMode="TranslateX|Zoom|Inertia"
                   SnapMode="Single"
                   active="mouse|pointer"
                   behaviors="DUI70::TSVEnableVirtualization()">
    <element id="atom(idItemList)" layout="flowlayout()" .../>
</TouchScrollViewer>
```

**InteractionMode 语料普查**:`TranslateY|Inertia` 13 处、`TranslateY | Inertia` 3 处(竖线两侧带空格——**解析器容忍空格**【实锤】,两种写法语义相同)、`TranslateX | Inertia` 1 处、`TranslateX|Zoom|Inertia` 1 处(WebcamUi)。**SnapMode** 语料只有 `Single` 4 处。**ZoomMaximum/ZoomMinimum** 语料只有 WebcamUi 一处。

> 注意大小写:bdeunlock 写 `XScrollable`(首字母大写),WebcamUi 写 `xscrollable`(全小写)。解析器对属性名同样不区分大小写——这是整个 DUI XML 解析器的统一行为(`16-startup-and-threading.md`)。

---

## 2. Viewer:最小视口的完整解剖

### 2.1 类表面(全部 21 个方法,symbols.json 实测)

| 方法 | RVA | 说明 |
|---|---|---|
| GetXOffset / SetXOffset | 0x6D510 / 0x6D920 | 偏移属性对 |
| GetYOffset / SetYOffset | 0x6D320 / 0x6D990 | 同上 |
| GetXScrollable / SetXScrollable | 0x6D450 / 0x6DA00 | 可滚开关 |
| GetYScrollable / SetYScrollable | 0x6D410 / 0x6DA60 | 同上 |
| EnsureVisible | 0xD3A00 | 尾跳 `_InternalEnsureVisible` |
| _InternalEnsureVisible | 0x6D050 | 见 §2.3 |
| _GetContent | 0x6D490 | 取唯一子元素 |
| _SelfLayoutDoLayout | 0x6D260 | **核心**:布局期应用偏移 |
| _SelfLayoutUpdateDesiredSize | 0x6D360 | 视口期望尺寸 |
| OnEvent / OnInput | 0x82CD0 / 0x80450 | 事件/输入虚槽 |
| OnPropertyChanged / OnPropertyChanging | 0x7EC40 / 0x8F270 | 属性管道 |
| SetEnsureVisibleUseLayoutCoordinates | 0xA9E40 | EnsureVisible 坐标系开关 |
| Initialize / GetClassInfoW | 0x61AC0 / 0x70BD0 | 注册构造 |

### 2.2 偏移如何变成像素位移【实锤,本次新还原】

`SetXOffset(v)` 不是直接挪窗口,而是走标准属性管道:

```
Viewer::SetXOffset(v)                    0x18006D920
  → Value::CreateInt(v)
  → Element::_SetValue(XOffsetProp@0x180071A60, ...)   0x180011490
      → OnPropertyChanged 派发(Element 基类 0x18003C350 按 PropertyInfo+0xC 规格跳表)
        → 布局失效(脏标记)
          → 布局事务提交时:Viewer::_SelfLayoutDoLayout   0x18006D260
              content 尺寸 = min(内容期望, 视口)          (cmovl 序列)
              content 位置 = -min(offset, 内容尺寸-视口)   ← 偏移取负 = 滚动方向
              → Element::_UpdateLayoutPosition           0x180038BF0
                → LayoutPosition 属性 _SetValue(位置对)
                  → Element::OnGroupChanged               0x180046E00
                      → duser!SetGadgetRect(gadget, ...)   IAT 0x180195028
                      → duser!InvalidateGadget(...)        IAT 0x1801950E8(紧随其后)
```

两个细节值得点破:

1. **位置取负号**:`cmovle`+`neg` 序列把 offset 变成 `-offset`。内容向下滚(YOffset 增大)意味着内容元素向上移。这就是"滚动 = 负平移"在 DirectUI 里的物理形态。
2. **clamp 而不是自由滚动**:`min(offset, 内容尺寸-视口)` 保证不会滚出边界。Viewer 是**硬边界**视口,没有橡皮筋(TouchScrollViewer 的手势层才有)。

**为什么这不与`13-layout-landscape.md`/`14-layout-protocol.md` 冲突**:Viewer 同时是"容器 + 自己的 Layout"(self-layout 实现者,`14-layout-protocol.md` 的虚协议),它不挂外部 Layout 对象,`_SelfLayoutDoLayout` 就是布局本身。

### 2.3 EnsureVisible:滚到看得见【实锤,本次新还原】

`EnsureVisible` 尾跳 `_InternalEnsureVisible`(0x18006D050),逻辑:

```
content = _GetContent()
loc     = GetValue(LocationProp)      // {x, y}
extent = GetValue(ExtentProp)         // {cx, cy}
对每个轴(先查 XScrollable/YScrollable 决定是否处理):
    delta = 视口起点 - loc            // 内容在视口上方/左方
    if delta > 0: 需要回滚 delta
    else:
        delta2 = (loc + extent) - (视口起点 + 视口尺寸)  // 内容在下方/右方溢出
        if delta2 > 0: 前滚 delta2
    offset -= delta (相应更新)
返回"是否发生了滚动"(bool),供宿主决定是否续动画
```

汇编证据:0x18006D1ED 处 `eax = ebp(loc/extent 差) - [rsp+0x30](视口起点) + [rsp+0xA8](视口尺寸)`,随后 `cmovsl/cmovg` 双向 clamp、`r15d -= eax / ebp -= eax` 把位移并进循环变量。`SetEnsureVisibleUseLayoutCoordinates`(0x18004A9E40)切换"传进来的是布局坐标还是屏幕坐标"。

---

## 3. ScrollViewer:把滚动条"合成"进视口

### 3.1 继承疑点的最终裁决【实锤】

classes.json(来自 PDB)里 ScrollViewer 的继承行写的是 `ScrollViewer : Element + IElementListener`,**不含 BaseScrollViewer**。之前这被当作"兄弟重实现"的疑点。反汇编给出了相反答案:

```
ScrollViewer::Create                    0x18007CEB0
  ...
  callq 0x180060680  ; ← BaseScrollViewer::Initialize!
```

**ScrollViewer::Create 显式调用 BaseScrollViewer::Initialize(0x180060680),后者再调 Element::Initialize(0x18003E190)。**这是标准的 C++ 基类构造链。同理 TouchScrollViewer::Initialize(0x18008D300)第一条基类调用也是 0x180060680。

结论(三级):
- **ScrollViewer : BaseScrollViewer【实锤】**(Create→Initialize 调用链,0x18007CEB0 处 callq);
- **TouchScrollViewer : BaseScrollViewer【实锤】**(0x18008D31B 处 callq);
- classes.json 继承表**缺行**是 PDB 完整类列表的收录缺口(它只记录了 51 个类的直接基类,不含"经中间基类"链)——**数据源缺陷,代码证据优先**。

BaseScrollViewer 自己的骨架(49 个方法):偏移/可滚属性对、XBarVisibility/YBarVisibility、Pinning、CheckScroll(0x5A200)、FireAnimationChangeEvent,以及 **IElementListener 双重身份**(第二张 vtable 0x105978,`??_7BaseScrollViewer@DirectUI@@6BIElementListener@1@@`)——它同时是"内容元素的监听者",内容尺寸一变就要重算滚动条范围(见`20-scroll-physics.md` §4)。

### 3.2 滚动条是"合成的子元素"

ScrollViewer::CreateScrollBars(0x1800628D0)在 Initialize 后创建 ScrollBar 对象存到 +0xF0/+0xF8 槽,并 `SetID` 固定 ID(字符串在 0x180121ED8)。**这些滚动条不在 XML 里**——你在 UIFILE 里永远只写 `<ScrollViewer>`,滚动条是运行时合成的。`xbarvisibility` 只是合成参数:

- `never`(=2):TSV::Initialize 里的默认值就是 `SetXBarVisibility(2)/SetYBarVisibility(2)`(0x1800AABD0/0x18007D870,Initialize 0x18008D300 序列中可见)——**"never"是代码默认,XML 里写出来只是显式化**【实锤】;
- `asneeded`(=1?):内容溢出才显示;
- `always`(=0?):常显。

> 具体枚举值 0/1/2 的对应关系是【强推】:never=2 由 TSV::Initialize 默认调用实锤,其余两个值由 taskbarcpl(always)与 racpldlg(asneeded)的语料行为反推,未逐值验证。

滚轮如何变成滚动(完整因果链)放在`20-scroll-physics.md`,这里只给一句:**BaseScrollViewer::OnInput(0x18002FD80)处理 wheel 设备输入,把"滚轮格数 × SPI 滚动行数"转成 ScrollBar::LineUp/LineDown(0x180086480/0x180087B90),即 `SetPosition(GetPosition() ± GetLine()*n)`,再经 Position 属性变化回到视口偏移。**滚动条在这里不是 UI 装饰,而是**滚动的算术中枢**——滚轮走的也是它。

### 3.3 StyledScrollViewer

只有 vtable 对(0x10F510/0x10F4E0)与 18 个方法符号,**无语料、无语料属性**。职责按命名与继承位置推断:换用"样式化"滚动条(主题绘制路径)的 ScrollViewer 变体。【猜想】(未读实现)

---

## 4. TouchScrollViewer:195 个方法的手势引擎

### 4.1 体量与家族分组

195 个方法(dui70 第二大类,仅次于 Element)按符号名分组:

| 家族 | 代表符号 | 干什么 |
|---|---|---|
| 操作(manipulation) | Get/SetInteractionMode, ManipulationStarting/Started/Delta/Completed, EnableManipulations, InitializeManipulationHelper, InitializeViewport, ReleaseViewport | DirectManipulation COM 生命周期 |
| 吸附(snap) | SnapMode/IntervalX/Y/OffsetX/Y/SnapPointCollectionX/Y, _UpdateSnapType, _TranslateSnapPoints | 翻页吸附(WebView 缩略图分页) |
| 缩放(zoom) | ZoomMaximum/Minimum, ZoomToRect, _ExecuteZoomToRect, OverrideZoomThreshold | 双指缩放边界 |
| 虚拟化 | SetVirtualizeElements, _InvalidateVirtualizedContainersEvent, _GadgetExistsInRect, _ElementExistsInRect | 只实例化视口内元素 |
| 瓦片(tile) | _RecomputeTiles, _UpdateTiles, _AddTileRect, CreateTile, RemoveTile, IsTileMember | 内容分块 |
| DComp 分层 | _GoLayered(0x8BD7C)/_GoUnlayered(0x8A3B8), _LayerContent/_LayerViewer/_LayerList, _SetLayeredTiles, **_CommitDCompDevice(0x8A2F0)**, _MapVisuals(0x2CE78), _SetElementContentVisualTransform, _ReinsertDManipIntoVisualTree | 独立合成层 |
| 指示器 | _CreateIndicatorContents(0x5B128)/_DeleteIndicatorContents(0x58BB0) + TouchScrollBar::_UpdateIndicatorTransforms(0xCF3D0) | 滚动指示条 |
| 滚动条 | _ShowScrollbars, _HideScrollbarsForSemanticZoom, _OnHideScrollbarTimer, _SetScrollbarStates, GetHScrollbar/GetVScrollbar | 触屏滚动条的显隐节奏 |

### 4.2 手势引擎 = 真 Windows DirectManipulation【实锤,本次新还原】

TSV 的 GetManipulationManager/GetManipulationViewport/GetManipulationCompositor 等符号已经直说了一切,反汇编把闭环补齐:

```
TouchScrollViewer::InitializeViewport         0x18005AAD4
  检查 TSV+0x198(viewport 对象槽)为空才建
  读取 [TSV+0x188](已存在的 manager,InitializeManipulationHelper 建的)
  callq *0x180195448                        ; delay-import CoCreateInstance
      rcx = 0x180124440                      ; CLSID {79DEA627-A08A-43AC-8EF5-6900B9299126}
                                            ;   = CLSID_DirectManipulationManager(公开文档)
      rdx = 0x180121CA0                      ; IID {537A0825-0387-4EFA-B62F-71EB1F085A7E}
                                            ;   = IID_IDirectManipulationManager
  ... 随后对 [TSV+0x190] 调 vtable+0x28 / +0x10 等(Update/Activate 序列)
```

**dui70 不自己实现惯性物理——它 CoCreateInstance 系统的 DirectManipulation 管理器**,把 TSV 的 viewport 注册进去,DManip 在系统侧跑手势识别与惯性积分,通过回调(TSV 的 ManipulationDelta 等)把增量送回 dui70,后者改 XOffset/YOffset 走 §2.2 的同一条布局管线。`InteractionMode="TranslateX|Zoom|Inertia"` 就是往 DManip interaction 注册的能力集。

DComp 侧的桥:**TSV::_CommitDCompDevice(0x18008A2F0)第一件事就是 `callq *0x1801951D8` = duser!GetGadgetVisual**——把自己的 gadget 换成 DComp visual,再交给 DManip compositor 挂内容。这与 duser-render-internals.md §2 的 AddLayeredRef/分层机制对接:TSV 滚动时内容在独立合成层上平移,**不动主 gadget 树的重绘**——这是 195 个方法里 tile/layer 两个家族存在的理由(大内容滚动不能每帧 OnPaint)。

### 4.3 指示器(indicator)是什么,以及任务书里那两个名字

任务包问过 `_UpdateIndicatorTransforms / _CreateDotVisuals` 与 DComp visual 的关系。符号表的诚实答案:

- `_CreateIndicatorContents`(0x5B128)/`_DeleteIndicatorContents`(0x58BB0)在 **TouchScrollViewer** 上:创建/销毁"指示器内容"(配合 CLSID_HorizontalIndicatorContent/CLSID_VerticalIndicatorContent 两个 COM 类对象,0x1282D8/0x1282E8);
- `_UpdateIndicatorTransforms`(0xCF3D0)在 **TouchScrollBar** 上(不是 TSV),另有一个 0x57C94 的薄封装。**dui70 里不存在叫 `_CreateDotVisuals` 的符号**——任务书里的名字是记岔了(或来自别的分支版本)。
- `_UpdateIndicatorTransforms` 的实现【实锤,本次新还原】:先 `duser!GetGadgetRect`(IAT 0x180195040)取滚动条 gadget 矩形,`GetVertical()` 分横竖,算出可见轨道长度/内容总长比例,然后 `duser!GetGadgetVisual`(IAT 0x1801951D8)拿指示器内容的 visual,**在栈上拼一个 float 矩阵**(可见段 `1.0f`、比例缩放、偏移)后调 `[visual+0x40]`(visual 虚表 SetTransform)。

也就是说:**触摸滚动条(指示器)不是画出来的子元素,是挂在 gadget visual 上、靠 SetTransform 挪位置的轻量 visual**。滚动时只有矩阵更新,没有内容重绘——和 §4.2 的分层是同一套哲学。

### 4.4 虚拟化:behaviors="DUI70::TSVEnableVirtualization()"【实锤,本次新还原】

WebcamUi 200 里那句 behaviors 是**行为(behavior)工厂调用**。还原链:

```
dui70 .rdata 0x109BA0 行为注册表: {L"TSVEnableVirtualization" @0x1801231A8 → 工厂 0x1800EAB70}
                                      {L"TSVVirtualizedContainer" @0x1801231D8 → 工厂 0x1800EABE0}
工厂 0x1800EAB70: 分配 0x10 字节 {vtable 0x180116AA8, DWORD 引用计数@+8}
  vtable+0x28 = 0x1800EAE50(attach):
      解析目标元素 → **置 Element+0x12C = 1**(单字节标志)
      已为 1 则跳过(幂等)
  vtable+0x30 = 0x1800EAE90(detach):
      若元素未销毁(+0x97 bit2)→ Element+0x12C = 0
```

而 `TouchScrollViewer::SetVirtualizeElements`(0x1800AABB0)整个函数就是 `Element+0x12C = dl`——**同一个字节**。

结论:**Element+0x12C 就是"允许虚拟化"标志位。TSVEnableVirtualization 行为在解析期把它置 1,TSV 的布局/瓦片引擎(_RecomputeTiles/_GadgetExistsInRect 等)读它决定"视口外的子元素不实例化/不建 gadget"**。TSVVirtualizedContainer(容器侧伴生行为)共用同一注册表。与 `<element id="atom(idItemList)" layout="flowlayout()">` 的配合:flowlayout 提供"逻辑上存在"的子元素坐标,TSV 只为进视口的元素付 gadget 成本——这是大列表(相机胶卷)在 2009 年硬件上滚得动的全部秘密。

---

## 5. 三层对比总表

| 维度 | Viewer | ScrollViewer | TouchScrollViewer |
|---|---|---|---|
| XML 偏移属性 | 无(API-only) | 无(API-only) | 无(API-only) |
| XML 特有属性 | 无(纯布局) | x/yscrollable, x/ybarvisibility | + InteractionMode/SnapMode/Zoom*/behaviors |
| 滚动条 | 无 | 合成 ScrollBar(经典) | 合成 TouchScrollBar(visual 指示器) |
| 滚轮 | 不管(宿主自己接) | BaseScrollViewer::OnInput→LineUp/Down | 同左 + 手势接管 |
| 手势/惯性 | 无 | 无 | DirectManipulation COM(CoCreateInstance 实锤) |
| 虚拟化 | 无 | 无 | Element+0x12C 标志 + tile 引擎 |
| 物理层 | 布管线→SetGadgetRect | 同左 | 可选 DComp 分层(_GoLayered/GetGadgetVisual) |

**给 XML 作者的心智模型**:Viewer 是"你喂它偏移它就裁剪显示"的原语;ScrollViewer 是"滚轮和滚动条都替你接好"的成品;TouchScrollViewer 是"手指一划整个 DManip 引擎开动、内容进独立合成层、视口外的东西不存在"的重机械。三层的 XML 越写越少,引擎越写越大。

---

## 6. 未解问题(诚实清单)

| # | 问题 | 现状 | 验证路径 |
|---|---|---|---|
| 1 | XBarVisibility 枚举 0/1 的确切语义(only never=2 实锤) | 【强推】never=2,always/asneeded 待定值 | SetXBarVisibility(0x1800AABD0) 读 Value 的消费点反汇编 |
| 2 | Viewer 语料 309 vs outline 312 的差异来源 | 疑为统计口径(是否含 `viewer/` 闭合标签误计) | 复跑 outline 原始命令 |
| 3 | StyledScrollViewer 的滚动条样式差异 | 【猜想】 | 反汇编 CreateScrollBars 对比 0x1800628D0 |
| 4 | DManip → TSV 回调的具体接口(ManipulationDelta 的注入点:是窗口消息还是 COM 回调线程) | 位置锁定在 TSV+0x188/0x190/0x198 三个对象槽,接口方法号未读 | IDirectManipulationViewport 交互注册处(IDirectManipulationInteraction)反汇编 |
| 5 | tile 引擎(_RecomputeTiles)与虚拟化标志的完整协作(何时销毁 gadget) | 机制框架已还原,时机未逐行读 | 0x18008xxx tile 家族反汇编 |
| 6 | _CreateIndicatorContents 创建的具体内容(横/竖指示器的 visual 树形状) | CLSID_H/VIndicatorContent 已定位,内容未读 | 0x18005B128 全量反汇编 |
| 7 | Pinning 属性(GetPinning 0x18005A440)的位语义(bit0/bit2 在 OnListenedPropertyChanged 里分流) | 位已知,语义名未定 | 对照公头注释/使用处枚举 |

---

## 附:证据索引

- **语料统计**:`docs/duixml-corpus/` 全量 `<tag[ >/]` 正则(大小写不敏感),viewer=309 / scrollviewer=69 / touchscrollviewer=19(13 文件);InteractionMode/SnapMode/Zoom 值普查同法。outline §A2 的 312/69/23 与此有 ±3 差异,统计口径不同。
- **Viewer::SetXOffset→SetGadgetRect 链**:dui70-full-disasm.txt 0x18006D920 / 0x180011490 / 0x18003C350 / 0x18006D260 / 0x180038BF0 / 0x180046E00(SetGadgetRect 调用点 @line 84262,InvalidateGadget @line 84275;duser IAT 槽位表 iat-slots.txt slot2=0x180195028 / slot26=0x1801950E8)。
- **Viewer::_InternalEnsureVisible**:0x18006D050,LocationProp@0x180068D10 / ExtentProp@0x180066530 双 GetValue + 0x18006D1ED clamp 序列。
- **继承裁决**:ScrollViewer::Create 0x18007CEB0→callq 0x180060680(BSV::Initialize)→callq 0x18003E190(Element::Initialize);TSV::Initialize 0x18008D300 同链(dui70-full-disasm.txt @line 180485 起;BSV::Initialize callq @0x18008D31B)。vftable 命名:`??_7BaseScrollViewer@DirectUI@@6BElement@1@@` 等(symbols.json vftable 条目)。
- **滚动条合成**:ScrollViewer::CreateScrollBars 0x1800628D0(SetID 字符串 @0x180121ED8);TSV::CreateScrollBars 0x180062AA0(TouchScrollBar 0x1B0 字节,构造 0x180062C30)。TSV::Initialize 默认 SetX/YBarVisibility(2) @0x1800AABD0/0x18007D870。
- **LineUp/LineDown**:BaseScrollBar 0x180086480/0x180087B90(GetPosition@+0x8 / GetLine@+0x28 / SetPosition@+0x30 虚槽,ScrollBar 主 vtable 0x105BA8)。
- **DManip**:InitializeViewport 0x18005AAD4,CoCreateInstance delay-IAT 0x180195448,CLSID/IID @0x180124440/0x180121CA0;GetManipulation* 符号名含 IDirectManipulationManager/Viewport/Compositor(.rdata 符号串 @0x15C5DC 起)。
- **_CommitDCompDevice→GetGadgetVisual**:0x18008A2F0→IAT 0x1801951D8(iat-slots.txt slot 56)。
- **指示器**:TouchScrollBar::_UpdateIndicatorTransforms 0x1800CF3D0(GetGadgetRect IAT 0x180195040 @line 对应处;GetGadgetVisual 0x1801951D8;矩阵常量 0x3F800000=1.0f、[visual+0x40] SetTransform);CLSID_H/VIndicatorContent @0x1282D8/0x1282E8。**注:dui70 无 `_CreateDotVisuals` 符号**。
- **虚拟化**:行为注册表 .rdata 0x109B00-0x109BC0 区(名字指针→工厂);TSVEnableVirtualization 工厂 0x1800EAB70、对象 vtable 0x180116AA8、attach 0x1800EAE50 / detach 0x1800EAE90;SetVirtualizeElements 0x1800AABB0 = `Element+0x12C = dl`;XML 实例 WebcamUi UIFILE_200 line 13。
- **类表面**:symbols.json Viewer 21 / BaseScrollViewer 49 / ScrollViewer 19 / TouchScrollViewer 195 方法数统计。
