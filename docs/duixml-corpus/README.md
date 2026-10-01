# duixml-corpus —— Windows 系统 UIFILE 语料库

从 Windows 11（build 26100）System32 中 64 个 DirectUI 消费者 PE 文件里系统性提取的 **149 个 UIFILE 资源**，全部还原为可读 XML。这是 duixml（DirectUI 声明式 UI 标记）的真实写作语料：控制面板页面、对话框、引导菜单、锁屏、任务栏弹窗、相机界面等，全部出自微软各产品团队之手。

## 数字总览

| 指标 | 数值 |
|---|---|
| 来源 PE 文件 | 64（62 DLL + 2 EXE，另有 47 个被扫描的消费者无 UIFILE） |
| UIFILE 资源总数 | 149 |
| 纯文本 XML 资源 | 134 |
| duib v5 二进制资源 | 15（**全部成功反编译为 XML**） |
| 还原成功率 | **149 / 149 = 100%** |
| 原始资源总量 | 约 1.6 MB |

提取范围：`.local/audit/dll-consumer-scan.txt` 列出的全部 109 个 dui70/duser 消费者（加载器扫描得出），加 dui70.dll、duser.dll 本体。duib（二进制 BML 压缩格式）使用自制解码器还原（格式细节见下文"duib 二进制格式"一节），解码器输出已与 `docs/duixml/` 中既有的手工文本（IMMERSIVESTYLES、duser.dll.xml）逐字节核对一致。

## 目录结构

按来源 DLL/EXE 分目录，每个 UIFILE 一个 `UIFILE_<资源名>.xml`，文件头部有元数据注释（来源模块、资源名、语言、原始大小、还原方式）：

```
docs/duixml-corpus/
├── README.md            ← 本文件
├── dui70/               ← 框架自带的沉浸式样式表（IMMERSIVESTYLES / SYSTEMSETTINGSSTYLES）
├── duser/               ← TaskDialog/AeroWizard 公共默认样式表（每个 DUI 线程都加载它）
├── bootux/              ← WinRE/高级启动菜单（BUX* 元素族 + attach 事件绑定，3 个 duib 全解码）
├── WebcamUi/            ← 相机 UI（Touch* 现代控件族，6 个 duib 全解码）
├── SpaceControl/        ← 存储空间控制面板（15 个资源，量最大）
├── DiagCpl/             ← 疑难解答控制面板（14 个）
├── wscapi/              ← 安全中心通知（12 个）
├── autoplay/ bdeunlock/ fvecpl/ werconcpl/ ...（其余 56 个来源）
```

## duixml 语法模式总结（从 149 个真实语料归纳）

### 1. 文档骨架

两种顶层写法并存：

- **元素树 + 样式表**：正文元素树在前，`<stylesheets>` 收尾（现代写法，见 [AuthBrokerUI](AuthBrokerUI/UIFILE_DUI_LAYOUTFILE.xml)）
- **样式表 + 元素树**：`<stylesheets>` 在前（传统写法，见 [duser](duser/UIFILE_1010.xml)）

根元素固定为 `<duixml>`。样式表内 `resid` 命名的 `<style>` 即"样式表"，元素通过 `sheet="样式名"` 挂接。

### 2. 元素标签库（实际出现 200+ 种，按族分组）

**基元**：`element`（出现 3946+2498 次，最通用容器）、`viewer`/`scrollviewer`（视口/滚动）、`clipper`、`textgraphic`、`ptext`

**传统控件**（Win7 时代）：`button`、`pushbutton`、`repeatbutton`、`edit`、`checkbox`、`combobox`、`cccheckbox`/`ccpushbutton`/`ccradiobutton`/`ccsyslink`/`ccprogressbar`（CC* = comctl 封装族）、`expando`、`progress`

**触摸/现代控件**（Win8+，本次语料的大头）：`touchbutton`（350 次）、`touchedit2`、`touchselect`、`touchscrollviewer`、`touchcheckbox`、`touchhyperlink`、`touchcommandbutton`、`modernprogressbar`、`modernprogressring`、`richtext`

**宿主/页面**：`hwndelement`（嵌入原生 HWND）、`nativehwndhost`、`page`/`pages`（向导页框架）、`buxpage`/`buxbutton`/`buxtext`/`buxformattedtext`（bootux 引导菜单专用族）、`desanimatedtouchbutton`（带动画的按钮）

**声明辅助**：`macro`（模板展开）、`bind`（数据绑定槽）、`if`/`unless`（条件样式）、`style`/`stylesheets`

### 3. 通用属性表（出现频次降序）

| 类别 | 属性 |
|---|---|
| 布局 | `layout`（布局函数）、`layoutpos`（top/bottom/left/right/client/none/absolute/nineright...）、`width`/`height`/`minsize`、`padding`/`margin`、`overhang` |
| 视觉 | `background`/`foreground`（颜色/主题表达式）、`bordercolor`/`borderthickness`/`borderstyle`、`contentalign`（topleft/middlecenter/wrapleft \| focusrect...）、`font`、`content`（文本/资源引用） |
| 状态 | `enabled`、`visible`、`active`（mouse\|keyboard\|pointer，输入激活域）、`transparent`、`cursor` |
| 无障碍 | `accessible`、`accrole`、`accname`、`accdesc`、`accdefaction`（UIA 体系，密度极高：accessible 出现 2456 次） |
| 标识/样式 | `id="atom(...)"`（atom 引用 4082 次）、`class`（样式选择器，5468 次）、`resid`（资源外键）、`sheet`（挂接样式表，945 次） |
| 行为 | `behaviors`（行为引擎声明）、`shortcut`、`expand`、`attach`/`connect`/`target`（事件/导航） |

### 4. `<if>` 条件样式（选择器引擎）

样式表中按运行时状态挑属性。语料中的条件维度全表：

`class`（1965 次，最常用）、`mousefocused`（悬停）、`keyfocused`（键盘焦点）、`id`、`pressed`（按下）、`enabled`（禁用态）、`selected`（选中）、`mousewithin`、`captured`、`showkeyfocus`、`keywithin`、`checkedstate`、`expanded`、`visited`、`visible`、`direction`/`vertical`/`isvertical`（方向变体）

经典五态按钮模板（出自 [duser](duser/UIFILE_1010.xml)）：

```xml
<pushbutton background="dtb(button, 1, 1)" contentalign="middlecenter" .../>
<if keyfocused="true"><pushbutton contentalign="middlecenter | focusrect"/></if>
<if selected="true"><pushbutton background="dtb(button, 1, 5)"/></if>
<if mousefocused="true"><pushbutton background="dtb(button, 1, 2)"/></if>
<if pressed="true"><pushbutton background="dtb(button, 1, 3)" padding="rect(21rp,6rp,19rp,4rp)"/></if>
<if enabled="false"><pushbutton background="dtb(button, 1, 4)" foreground="graytext"/></if>
```

条件可叠加嵌套（`<if class="mixed"><if mousefocused="true">...`），等价于 CSS 的组合选择器；`<unless>` 是取反。

### 5. 值表达式函数库

属性值不是字面量而是函数式表达式（语料统计频次）：

| 函数 | 频次 | 语义 |
|---|---|---|
| `rect(l,t,r,b)` | 3338 | 四边距；单位 `rp`（相对像素，随 DPI 缩放）或无单位 |
| `gtc(THEMECLASS, part, state, prop)` | 1716 | 取主题颜色（GetThemeColor）；语料 99% 用 `CONTROLPANELSTYLE` |
| `gtf(THEMECLASS, part, state)` | 1667 | 取主题字体 |
| `themeable(expr, fallback)` | 1341 | "主题可用用主题，否则用回退色"——每一次 dtb 包裹都配 fallback |
| `dtb(THEMECLASS, part, state)` | 1289 | 主题位图背景（DrawThemeBackground） |
| `argb(a,r,g,b)` / `rgb(r,g,b)` | 358/200 | 直接颜色 |
| `sysmetric(n)` | 345 | 系统度量（如 SM_CXICON） |
| `size(w,h)` | 141 | 尺寸对 |
| `resstr(id[, library(x.dll)])` | 3338 | 本地化字符串 |
| `icon(id, w, h[, ...])` | 320 | 图标资源 |
| `atom(name)` | 4082 | 原子 ID 引用（id 的标准写法） |
| `ressheet(name, library(dll), theme)` | 53 | 跨模块引用样式表 |
| `library(dll)` | 524 | 模块定位 |
| `gtmar()` / `gtps()` | 34/2 | 主题边距/尺寸 |

**Immersive 命名色**（Win8+ 系统 accent 体系）：`ImmersiveLightBackground`、`ImmersiveLightPrimaryText`、`ImmersiveSystemAccent`、`ImmersiveSystemAccentDark1`、`ImmersiveSaturatedPrimaryText` 等 100+ 种（完整清单在 [dui70/IMMERSIVESTYLES](dui70/UIFILE_IMMERSIVESTYLES.xml) 里）。

### 6. 样式引用与继承

- `sheet="common"`：元素挂接样式表（`common` 来自 duser UIFILE 1010，是所有 DUI 线程的默认表）
- `base="ressheet(ImmersiveStyles, library(dui70.dll), Light)"`：样式表继承——现代 UI 几乎全部基于 dui70 内置的 ImmersiveStyles 派生（Light/Dark/ImmersiveBase 三系，语料出现 53 次）
- `class="cp_topbox"`：class 选择器 + `<if class="...">` 组合是样式复用的主力模式

### 7. 动画声明

三种机制：

1. **PVL 行为属性**（声明式，Win8+）：`behaviors="PVL::ImplicitAnimation()"`（属性变化自动补间，18 处）、`behaviors="PVL::AnimationTrap()"`（动画陷阱，8 处）、`behaviors="PVL::EnsureLayered()"`
2. **动画控件**：`modernprogressbar`（`determinate="false"` 转圈）、`modernprogressring`、`movie`（帧序列）、`animationstrip`
3. **过渡属性**：样式表里 `TextGlowSize` 等属性配 `<if>` 切换，由 PVL 引擎自动过渡

其他行为引擎：`DUI70::ContextMenuBehavior(...)`、`DUI70::ScrubBehavior(...)`、`Windows.UI.Popups::TouchEditContextMenu()`、`TouchID::TouchConfirmationID()`、`BUX::Timer(0)`（bootux 定时器）。

### 8. 事件/数据绑定

- **`attach="{Module!Function}"`**：C++ 回调绑定（bootux 用了 300+ 处：`attach="{BootMenuUX!CreateShutdownButton}"`）
- **`connect="title"`**：命名连接槽，C++ 侧按名查找填充
- **`<bind connect="title" content="resstr(1117)" id="atom(...)"/>`**：bind 元素 = 可被宿主代码替换内容的占位
- **`target="PageName"`**：页面导航目标（BUXPage 体系）
- **`<macro expand="macroName">`**：模板展开点，配 `<Macro>` 定义复用子树

### 9. duib 二进制格式（本次逆向成果）

dui70 的 UIFILE 资源有两种物理形态：明文 XML（134 个）与 `duib` v5 二进制（15 个）。duib 结构：

```
偏移 0   magic 'duib' (4B)
偏移 4   version = 5 (u32)
偏移 8   entryChunkOffset (u32)   → 条目块
偏移 12  stringChunkOffset (u32)  → 字符串块（0 = 无）
偏移 16  resourceChunkOffset (u32)

entryChunk: chunkSize(u32) entriesCount(u32) 后跟 entriesCount 个变长条目：
  typeAndPropCount(u16)  低 4 位 = 条目类型（0=StartElement 1=EmptyElement 2=EndElement）
                         高 12 位 = 属性数
  nameIndex(u16)         0x8000 位 = 公共串表（duixml/element/if/resid/...62 个固定词），否则字符串块索引
  每属性: nameIndex(u16) + valueIndex(u16)

stringChunk: chunkSize(u32) stringsCount(u32) 偏移表(u32×N，实际未用) 后跟 NUL 结尾 UTF-16LE 字符串
```

解码器（验证输出与已知 XML 逐字节一致）在 `.local/corpus/duib2xml.py`（工作区文件，非交付物）。解码语义参考了 DuiTool 项目的 duib 阅读器结构，公共串表取自其 BDXCommonStringTable。

## 最有教学价值的样例导读（5 个）

1. **[duser/UIFILE_1010.xml](duser/UIFILE_1010.xml)** —— "公共样式表"本体。每个 DirectUI 线程启动时 dui70 自动加载它（`GetParserCommon` → duser 资源 1010）。浓缩了 if 条件选择器全体系、dtb/gtc/gtf 主题表达式、TaskDialog/AeroWizard 的完整按钮五态。**读懂它 = 读懂 duixml 样式引擎**。

2. **[dui70/UIFILE_IMMERSIVESTYLES.xml](dui70/UIFILE_IMMERSIVESTYLES.xml)** —— 25KB 的 ImmersiveStyles，所有现代 Windows 沉浸式 UI 的样式基座。展示 Light/Dark/ImmersiveBase 三主题分支、Immersive* 命名色全集、Touch* 控件族的默认皮肤。跨模块复用的样板：`base="ressheet(ImmersiveStyles, library(dui70.dll), Light)"`。

3. **[autoplay/UIFILE_101.xml](autoplay/UIFILE_101.xml)** —— 教科书级"控制面板页面"模板：borderlayout 页面骨架 + `resstr()` 本地化 + `<macro>` 模板展开 + `<bind connect>` 数据槽 + `sheet="common"` 挂公共样式。想写一个实用 duixml 页面，从这份抄起。

4. **[bootux/UIFILE_600.xml](bootux/UIFILE_600.xml)** —— 70KB 的 WinRE 高级启动菜单（duib 解码）。独有 `BUXPage/BUXButton/BUXText` 页面族 + `attach="{BootMenuUX!CreateXxx}"` C++ 回调绑定 + `target=` 页面导航 + `icon()` 引用 + `ExecStyle` 执行样式。**声明式 UI 与宿主代码交互的最完整范例**。

5. **[WebcamUi/UIFILE_200.xml](WebcamUi/UIFILE_200.xml)** —— 相机界面主布局（duib 解码）。TouchScrollViewer 虚拟化（`behaviors="DUI70::TSVEnableVirtualization()"`）、Zoom/Snap 手势参数、`PVL::AnimationTrap()` 动画、ModernProgressRing 捕获指示，展示触摸时代的复杂交互全用声明完成。

## 提取方法（可复现）

1. 枚举：解析 PE 资源目录（`.local/corpus/enumres.py`），找 `UIFILE` 类型条目（注意 dui70 的两个是**命名资源** IMMERSIVESTYLES/SYSTEMSETTINGSSTYLES，不是数字 ID）
2. 分类：读资源头 4 字节，`duib` = 二进制，`<duixml`/`<?xml` = 明文
3. 解码：duib 走上文格式说明；明文直接保存
4. 归档：每个文件加元数据头注释入库

数据快照：Windows 11 26100（x64，dui70.dll 10.0.26100.8875 系）。系统更新后资源可能变化。

## 相关材料

- `docs/duixml/` —— 早期手工提取的 6 份样例（本语料库是其超集，且 duib 解码与之核对一致）
- `.local/audit/duser-landscape.md` §3.3 —— duser UIFILE 1010 与 dui70 解析器的关系分析
- `.local/audit/dll-consumer-scan.txt` —— 109 个消费者的完整清单（扫描了全部，64 个有 UIFILE）
