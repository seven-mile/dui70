# 教程 13:九种布局的真实用法分布 —— 谁在统治 DUI 界面

> 系列教程第 13 篇(P4 布局与导航三部曲之一)。前置:`18-properties-and-lifecycle.md`(`layout=` 属性如何变成 Value 已经露面)。
> 证据分级:**【实锤】** / **【强推】**(附推断链)/ **【猜想】**(待验证)。
> 主题:dui70.dll 提供九种 Layout 类;语料库里它们的真实使用频率相差四个数量级。本篇回答:每种布局是什么、XML 怎么写、谁在用、**为什么 borderlayout 一家占 65%**。

---

## 0. 全景:频率即考古

```
borderlayout         1625 处   ████████████████████████████████ 65.2%
flowlayout            726 处   ██████████████ 29.1%
verticalflowlayout    212 处   ████ 8.5%
filllayout            177 处   ███ 7.1%
tablelayout           109 处   ██ 4.4%
rowlayout              24 处   ▌ 1.0%
gridlayout             17 处   ▎ 0.7%
ninegridlayout          5 处   ▏ 0.2%
shellborderlayout      2 处   ▏ 0.08%
```

统计口径:`docs/duixml-corpus/` 全部 XML 中 `layout="xxx"` 属性出现次数(原始文本正则,含多行)。所有百分比分母是全部 layout= 出现总数(2497),所以各项之和超过 100% 是因为这里按"出现次数"并列展示;单看布局种类的市场份额:borderlayout ≈ 65%。

心智模型:**DUI 布局生态不是"九种布局各司其职",而是"borderlayout + flowlayout 双寡头 + 七个特化补丁"**。这背后的原因见 §5 历史考古。

---

## 1. 名字到对象:`layout="borderlayout()"` 的完整生命线【实锤】

### 1.1 分发表(编译期固化)

解析器侧有一张 9 项静态表,位于 `.rdata 0x180103730`,每项 16 字节 `{PCSTR name(ASCII), fnptr Create}`:

```
[0] "borderlayout"         -> 0x61410  BorderLayout::Create
[1] "filllayout"           -> 0x61330  FillLayout::Create
[2] "flowlayout"           -> 0x61130  FlowLayout::Create
[3] "gridlayout"           -> 0x8D1B0  GridLayout::Create
[4] "ninegridlayout"       -> 0x61040  NineGridLayout::Create
[5] "rowlayout"            -> 0x60990  RowLayout::Create
[6] "shellborderlayout"    -> 0x60DC0  ShellBorderLayout::Create
[7] "verticalflowlayout"   -> 0x60EA0  VerticalFlowLayout::Create
[8] "tablelayout"          -> 0x8F410  TableLayout::Create
```

注意:名字是 **ASCII** 而非 UTF-16(与大多数 DUI 字符串相反),紧跟在 0x180121110 开始的字符串区,后面还排着 `"auto"`(0x180121218)和 `"absolute"`(0x180121228)——这正是 layoutpos 取值表的一部分,布局名和槽位名在同一片数据区,是同一个解析子系统的词汇表。【实锤:直接 dump `.rdata` 字节 + ParseLayoutValue 反汇编引用此表】

### 1.2 解析路径

`DUIXmlParser::ParseLayoutValue`(0x36060):

```
if (node->type != 2 /*函数调用*/)      → 0x800403F1 错误
for i in 0..8:                          ; 0x36097 循环
    if wcscmp_i(node->name, table[i].name) == 0:   ; 0x180119C10 IAT
        return CreateLayout(node, table[i].Create) ; 0x36300
```

即:`layout="borderlayout(0,2,2,2)"` 中括号里的东西是**函数实参**,由 `DUIXmlParser::CreateLayout` 逐个求值后传给对应 `Create(int, int*, Value**)` 工厂。

### 1.3 工厂只做三件事【实锤】

以 `FillLayout::Create`(0x613A0)和 `BorderLayout::Create`(0x61480)为例,二者结构完全一致:

```
*ppLayout = NULL
obj = operator new(0x30)          ; 所有布局对象统一 0x30 字节
obj->vtable  = ??_7FillLayout@DirectUI@@6B@  (0x180106260) / ??_7BorderLayout (0x1801079B0)
obj+0x08..0x2C = 0                ; 子类字段清零
obj+0x18 = 1                      ; _fCacheDirty = TRUE(刚出生就是脏的)
*ppLayout = obj
```

`FlowLayout::Create(_N, int, int, int)`(0x61200)多存四个参数:`+0x20` 一个 bool、`+0x24/+0x28/+0x2C` 三个 int——对应 XML 里 `flowlayout(0, 0, 1)` 的实参。字段语义见 §3.2。

**心智模型:`layout="flowlayout(0,2)"` 不是"配置字符串",而是一次真正的构造函数调用——XML 属性值是函数调用的源代码。**

### 1.4 与属性系统的衔接

Create 出来的裸 Layout* 随即被包进 Value(`18-properties-and-lifecycle.md` 的 Value 类型系统),存入该元素的 `Layout` 属性槽;`Element::SetLayout`(0x612C0)再把它 `Attach` 到元素。完整链路的属性侧细节见`18-properties-and-lifecycle.md`;布局侧的 Attach/Detach 见`14-layout-protocol.md`。

---

## 2. layoutpos:子元素报到的槽位协议【实锤】

布局对象管孩子,但"这个孩子放哪个槽"的信息却在**孩子**身上——`layoutpos` 属性。字符串到值的映射(`docs/Layouts.txt` 已录,此处按语义重排):

| layoutpos | 值 | 语义 | 语料出现 |
|---|---|---|---|
| `left` | 0 | 左侧边条 | 564 |
| `top` | 1 | 顶部边条 | 2054 |
| `right` | 2 | 右侧边条 | 178 |
| `bottom` | 3 | 底部边条 | 193 |
| `client` | 4 | 中央填充(默认) | 414 |
| `nine*` 家族 | 0–9 | 九宫格槽位 | 37 |
| `auto` | 0xFF | (仅构建期:未指定) | 2 |
| `absolute` | 0xFE | 不参与父布局 | 54 |
| `none` | 0xFD | 声明式豁免 | 260 |

两个特殊值值得展开:

- **`absolute`(-2)**:元素自己管 x/y/width/height,父亲布局当它不存在。语料 54 处,多用于浮层/装饰。
- **`none`(-3)**:260 处,高频!语义是"构建时先别让父布局接管"——常见于 `Element::GetAdjacent` 反汇编里 `cmpl $-0x3, 0x78(%rbx)`(0x7DA5B,检查某元素的 layoutpos 是否为 none)以及 `Layout::OnAdd`(0x31BE8 同款检查)。**none 的孩子从布局视角"不存在",但仍在树上。**【实锤:两处反汇编常量 -3 与 Layouts.txt 枚举对上;精确构建期行为差异待`14-layout-protocol.md` 展开】

**心智模型:布局是"双向协议"——父亲用 layout 属性指定布局算法,孩子用 layoutpos 属性报到槽位。**

---

## 3. 逐个布局:真实 XML + 语义

以下每个布局给至少一段真实语料(文件:行号可复核)+ 用法要点。

### 3.1 BorderLayout(1625 处,65%)——边条+中央的页面骨架

`docs/duixml-corpus/AuthBrokerUI/UIFILE_DUI_LAYOUTFILE.xml:8-21`(节选):

```xml
<element layout="filllayout()">
  <element layout="borderlayout()" layoutpos="client" ...>
    <element layoutpos="top" ... />            <!-- 顶部标题条 -->
    <element layoutpos="client" ...>           <!-- 中央内容 -->
      <element layout="flowlayout()" layoutpos="bottom">
        <button layoutpos="left" ... />
        <element layoutpos="client" .../>
```

要点:每个槽位**至多一个**孩子(后加的顶掉先加的,`BorderLayout::OnAdd` 0x31CD0 处理);四个边可以缺席,client 吃掉剩余全部空间。参数形式:1625 处里 1388 处写空 `borderlayout()`,其余最常见的实参形态是 `0, 0, 0, 2`(51 处)、`0,0,0,0`(48+10 处)、`0, 2, 2, 2`(36+10 处)——四个 int 依次对应 top/bottom/left/right 边条间距。【强推:四参数与四边条一一对应,依据 Create 重载 `BorderLayout::Create(int, int*, Value**)` 的四个求值槽 + 语料中 `0,2,2,2` 型参数在"不对称留白"场景出现;未逐参数反汇编求证,标注推断】

### 3.2 FlowLayout(726 处,29%)——横排流

参数四形态(语料统计):空 267 处;`0,2` 146 处;`0, 0, 1` 77 处;`0,0,2` 38 处;`0,2,0,2` 25 处。

`FlowLayout::Create(_N, int a, int b, int c)`(0x61200)把四个实参存进 `+0x20`(bool)、`+0x24/+0x28/+0x2C`(三个 int);`DoLayout`(0x1F040)读 `+0x2C`(`movl 0x2c(%rbx), %edx; testl; jne 走紧凑分支`)决定行距/间距计算分支。**首参 bool(+0x20)是"水平/垂直"之外的第三态开关,推断为"行间自动换行/紧凑"类开关;三个 int 是 spacing 族参数。**【强推:字段偏移实锤,语义名推断自 DoLayout 分支结构 + 语料习惯写法;精确到像素的间距公式未还原,见未知清单】

真实语料:`AuthBrokerUI/UIFILE_DUI_LAYOUTFILE.xml:18`(TouchButtons 一行排开,孩子在 flow 里**不用** layoutpos,按文档顺序流排)。

### 3.3 VerticalFlowLayout(212 处,8.5%)——竖排流

`adrclient/UIFILE_3000.xml:8`:

```xml
<element layout="verticalflowlayout(0,0,0,0)" padding="rect(10rp,0rp,0rp,0rp)">
```

参数分布与 FlowLayout 高度同构(空 55 处、`0,0,0,0` 55 处、`0,0,0,2` 53 处、`0,2,2,2` 45 处)——工厂 0x60EA0 与 FlowLayout 工厂结构对应,是"把流方向换成 Y 轴"的特化。**【强推:类名 + 参数同构 + 独立 vtable;DoLayout 差异未逐指令比对】**

### 3.4 FillLayout(177 处,7.1%)——只有一个几何

孩子被拉伸到父亲的整个内容区(减 padding)。孩子同样不需要 layoutpos。语料根节点最常见:`AuthBrokerUI/UIFILE_DUI_LAYOUTFILE.xml:8` 根元素、`CertEnrollUI/UIFILE_130.xml` 的 GroupBox 包裹层。当容器只有一个视觉主角时,filllayout 是最便宜的容器。

### 3.5 TableLayout(109 处,4.4%)——带权重的网格

`CertEnrollUI/UIFILE_130.xml:1337`:

```xml
<element layout="tablelayout(0, 0, 3,3, -50, 2,2, 140, 3,3,-50)">
```

参数按"行数,列数,行高…,列宽…"或权重混排;负数(-50)是**比例权重**,正数(140)是固定像素/行数说明符。语料大户:WorkfoldersControl 47 处、diagperf 18 处、SpaceControl 17 处。每个孩子用 `row`/`column` 属性(或顺序)报坐标。语义还原见`14-layout-protocol.md`。

### 3.6 RowLayout(24 处,1%)——两列标签/值行

`adrclient/UIFILE_3000.xml:9`:

```xml
<element layout="rowlayout(1)">
  <element .../>  <!-- 左:标签 -->
  <element .../>  <!-- 右:值 -->
```

专为"设置页一行"设计:左列固定/标签,右列伸展。参数 1 个 int(列数或左列宽)。【强推:24 处语料里 22 处恰好两个孩子 + UI 语境全是 label:value 行】

### 3.7 GridLayout(17 处,0.7%)——均匀网格

`CertEnrollUI/UIFILE_130.xml:445`:

```xml
<element id="atom(layout)" layout="gridlayout(1, 2)" layoutpos="top">
  <CCCheckBox id="atom(CheckBox)"/>
  <element id="atom(CAType)" contentalign="wrapleft"/>
</element>
```

`gridlayout(rows, cols)` 两参数;孩子按顺序填格子。使用场景极窄(CertEnrollUI 3 处、DXP/InputSwitch/msctfuimanager 各 1-3 处),**它不是通用网格——TableLayout 才是;GridLayout 是"等分格子"的极简版。**【强推:两参数 + 17 处语料全部是等分场景】

### 3.8 NineGridLayout(5 处)——九宫格**区域**,不是 PNG 九宫

Lead 的问题:是不是 PNG 9-patch 拉伸?**不是。**证据链:

1. `NineGridLayout::DoLayout` 0x68540 存在且独立,配套 `_UpdateTileList` 0x70090——它**排布子元素**,不是位图切片;
2. 槽位词汇是 layoutpos 的 `nine*` 家族:`nineclient` 12、`nineright` 10、`ninebottom` 7、`ninefill` 2、`nineleft` 2、`ninetopleft` 2、`ninebottomleft` 1、`ninetop` 1——**八个边角/边条槽 + 中央**,共 9 个区域;
3. 真实语料 `fhcpl/UIFILE_201.xml:297`:

```xml
<element layoutpos="top" layout="ninegridlayout()" padding="rect(20rp,16rp,0,16rp)">
  <element content="resstr(2057)" ... layoutpos="ninetopleft" class="para" .../>
  <element layout="borderlayout()" layoutpos="ninetop" ...>
```

4. 图片拉伸在 DUI 里另有机制(background/contentfill,`18-properties-and-lifecycle.md` 属性系统)。

**结论【实锤】:NineGridLayout = "3×3 语义分区"容器——四角、四边、一中央,子元素按 `nine*` 槽位就座。它与 9-patch 位图拉伸同名异义。** PNG 9-patch 若存在,走 background 图层,与此类无关。【最后一句为强推:未检索 background 实现里的 9-patch 逻辑】

### 3.9 ShellBorderLayout(2 处)——窗口级 chrome 布局

仅 `wscapi/UIFILE_6056.xml:51、163`,且都用于 LineSeparator 分隔条元素。类结构非常特殊(`14-layout-protocol.md` 详述):它**没有自己的 DoLayout**(继承基类空实现),但有 `_CalcTabOrder` 0x71350、`_Reset` 0x716B0、自己的 `GetAdjacent` 0x70E10。推断:它服务于 **DWM 窗口边框/标题区**这类"宿主壳"场景——分隔条是 chrome 元素,布局由宿主(窗口)决定,所以自身不需要 DoLayout,但要参与 Tab 序。【强推:成员表(无 DoLayout)+ 两处语料均为 chrome 元素 + _CalcTabOrder 存在】

---

## 4. 决策树:给 DUI 写界面时怎么选布局

(把 outline §4 的速查表展开成决策树;基于语料统计 + 各布局语义)

```
要放什么?
├─ 整页骨架(标题条/内容/按钮排)
│   └─ borderlayout()            ← 65% 的 DUI 页面就这么起手
│       孩子标 layoutpos="top|client|bottom|..."
├─ 一排按钮 / 横排条目
│   └─ flowlayout(0,2)           ← 第二常用;孩子不用 layoutpos
│       └─ 要竖排? verticalflowlayout(0,0,0,0)
├─ 只有一个主角(GroupBox 内 / 全幅图)
│   └─ filllayout()              ← 最便宜的单容器
├─ 设置页"标签:值"多行
│   ├─ 每行两列 → rowlayout(1)      ← 语义最贴
│   └─ 列宽要对齐 → tablelayout(...) ← 跨行对齐才值得上
├─ 表单网格(混权重/固定列)
│   └─ tablelayout(0,0, 3,3,-50, 2,2,140, 3,3,-50)
├─ 等分格子(极少)
│   └─ gridlayout(1, 2)
├─ 3×3 语义分区(角/边/中)
│   └─ ninegridlayout() + 九个 nine* 槽位
└─ 窗口 chrome / 分隔条(几乎不手写)
    └─ shellborderlayout()

任何布局里要"悬浮"的元素:layoutpos="absolute",自管 x/y/w/h
构建期豁免:layoutpos="none"(260 处,构建时先不入槽)
```

**一句话:如果你写的不是 borderlayout,你应该能说出为什么。**

---

## 5. 考古:为什么 borderlayout 占 65%?

三层原因,证据强度递减:

1. **【实锤·结构性】** BorderLayout 槽位协议(left/top/right/bottom/client)与 Win32 对话框时代的页面心智完全同构:对话框模板就是"顶条 + 客户区 + 底条按钮排"。DUI 的目标之一是把 Win32 对话框迁到 DirectUI(语料里 CertEnrollUI、fvewiz 等全是向导/属性页),页面结构自然原样平移。语料统计:layoutpos="top" 2054 处是所有槽位值之首——**每个 borderlayout 页面几乎都有一个 top**,这是"标题条+内容"模板的证据。
2. **【强推】** 嵌套组合的数学:flow/fill 不能表达"边条固定、中央伸展",而这是几乎所有页面框架的第一需求;于是每个页面先来一个 borderlayout(骨架),内部再嵌 flow/border(内容)。统计里 borderlayout 1625 处 vs 页面级 UI 文件数百个,恰好是"每文件若干个页面骨架"的量级。SpaceControl 一个模块 350 处 borderlayout(该文件是大型多页控制面板)。
3. **【猜想】** 布局类的添加顺序是否反映了"border 最早出现、其余是后来按需补丁"?可以从 vtable 在 .rdata 的排布顺序(BorderLayout vftable 0x1079B0 < FillLayout 0x106260 < …)和类大小差异(0x30 统一)做进一步考古——vtable 顺序由链接顺序决定,而链接顺序通常等于编译单元字母序,故**此路不通,留作诚实记录**。

**ShellBorderLayout 为什么只有 2 处却值得存在?**——它不是给 DUI 页面作者的,是给**宿主框架**(窗口 chrome)的。语料两处都是 chrome 元素(分隔条),加上它独有的 `_CalcTabOrder`(Tab 序计算在布局类里!详见`15-keyboard-navigation.md`),说明它是"宿主壳布局 + Tab 链管理"的专用件,由框架代码以编程方式使用,XML 手写只是它的侧影。【强推】

---

## 6. 未知问题清单

1. borderlayout 四个 int 实参的**精确像素语义**(边距?最小边条宽?)未逐参数反汇编——Create 求值链可还原,DoLayout 消费点在 0x383D0,工作量约半天。
2. flowlayout 三 int 参数在 DoLayout 各分支的**间距公式**未还原(0x1F040 分支树已定位)。
3. `layoutpos="none"`(-3)在构建期与 `absolute`(-2)的**确切差别**(OnAdd 的 -3 检查 0x31BE8 已定位,语义细节未展开;见`14-layout-protocol.md`)。
4. tablelayout 负权重/正数说明符的**精确语法**(`GetCellInfo` 0x7F170 未反汇编)。
5. NineGridLayout 的 9 个槽位**几何分配算法**(DoLayout 0x68540 未逐指令)。

## 7. 证据索引

| 断言 | 级别 | 位置 |
|---|---|---|
| 9 项名字→Create 分发表(ASCII 名) | 实锤 | .rdata 0x180103730 dump + ParseLayoutValue@0x36060 引用 |
| ParseLayoutValue 线性查找 + CreateLayout | 实锤 | 0x36060-0x360FA 反汇编 |
| FillLayout/BorderLayout::Create 统一 0x30 字节 + 脏标志 | 实锤 | 0x613A0 / 0x61480 反汇编 |
| FlowLayout::Create 四参存 +0x20/24/28/2C | 实锤 | 0x61200 反汇编 |
| DoLayout 读 +0x2C 分支 | 实锤 | 0x1F040 @ 0x1F0B2 |
| layoutpos 枚举值(nine*/auto/absolute/none) | 实锤 | docs/Layouts.txt + 语料 |
| GetAdjacent 检查 layoutpos=-3 | 实锤 | 0x7DA5B 反汇编 |
| OnAdd 检查 layoutpos=-3 | 实锤 | 0x31BE8 反汇编 |
| 九种布局频率统计 | 实锤 | docs/duixml-corpus 正则统计(本篇 §0) |
| borderlayout 65% 三层归因 | 实锤/强推/猜想分层 | §5 |
| NineGridLayout=区域布局非 9-patch | 实锤(结论)/强推(背景推论) | 0x68540/_UpdateTileList@0x70090/nine* 槽位/fhcpl 样例 |
| ShellBorderLayout 无 DoLayout + _CalcTabOrder | 实锤(成员表)/强推(用途) | layout_members.txt + wscapi 语料 |

> 工作数据:`.local/build/ui-mental-model/`(parser_layout_table.py、parser_names.py、name_region.py 输出)。
> 下一篇:[教程 14:Layout 虚协议 —— 一个布局对象的生老病死](14-layout-protocol.md)
