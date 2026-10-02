# 三层皮肤:样式表系统

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 读完你能回答:我的 `<stylesheets>` 块到底怎么生效?`<if>` 状态伪类有哪些?明暗两套颜色从哪来?
>
> 证据分级:【实锤】= 反汇编定位到指令 / 语料 XML 原文 / 可运行验证之一;
> 【强推】= 符号名 + 结构自洽的推断,写明推断链;【猜想】= 明确标注为猜测。
> 反汇编地址均为 RVA(dui70.dll 10.0.26100 x64,基址 0x180000000),
> 可用 `llvm-objdump -d --start-address=0x180000000+<RVA> C:\Windows\System32\dui70.dll` 复现。
> 语料统计来自 `docs/duixml-corpus/`(64 模块 149 个 UIFILE)的本次全量扫描。

---

## 1. 一句话心智模型:三层皮肤

一个 DirectUI 元素的最终外观由三层叠加决定,每层有不同的数据来源和失效机制:

| 层 | 是什么 | 数据来自 | 何时变 |
|---|---|---|---|
| ① StyleSheet | XML 声明的状态样式规则表 | 宿主模块的 UIFILE 资源 | 解析时装载;明暗切换/主题切换时整表重载 |
| ② visual style | uxtheme 主题句柄(dtb/gtc/gtf 表达式求值) | 当前 msstyles / immersive 主题 | 主题句柄 Flush 后重新求值 |
| ③ 系统颜色/度量 | syscolor、sysmetric | Win32 全局 | WM_SYSCOLORCHANGE |

**明暗切换同时打击 ① 和 ②**——这是理解下一章(明暗切换全链路)的钥匙:样式表重载
(parser 侧)+ 主题句柄重建(uxtheme 侧)双管齐下。【实锤,disasm 链见`10-dark-mode-switch-chain.md`;本篇先立模型】

为什么说"三层"而不是一层?看语料里的一个真实颜色值就能体会:

```xml
<if id="atom(instructions)">
    <element
        background="themeable(dtb(TaskDialog, 1, 0), threedface)"
        font="gtf(TaskDialogStyle, 2, 0)"
        foreground="gtc(TaskDialogStyle, 2, 0, 3803)" />
</if>
```
(【实锤,`docs/duixml-corpus/duser/UIFILE_1010.xml`】

这个 `background` 里同时有第②层(`dtb(TaskDialog,1,0)` = DrawThemeBackground 取主题位图)、
第③层(`threedface` = 系统颜色兜底)、以及一个把两层串起来的开关函数 `themeable(light, dark)`。
而整个 `<if id=...>` 块本身住在第①层的样式表里。

---

## 2. 第①层:StyleSheet 是什么

### 2.1 一个最小的完整例子

来自 wscapi.dll(安全与维护的通知对话框),语料里最干净的 `<stylesheets>` 样本:

```xml
<duixml>
<stylesheets>
<style resid="NotificationDialog" base="ressheet(ImmersiveStyles, library(dui70.dll), Dark)">
<if class="DialogText">
<RichText
background          = "argb(0,0,0,0)"
contentalign        = "wrapleft | pathellipsis | wordellipsis"
foreground          = "ImmersiveSaturatedPrimaryText"
accessible          = "true"
accrole             = "statictext"
padding             = "rect(0rp,1rp,0rp,1rp)"
font                =  "resstr(6027)"
/>
</if>
<TouchHyperLink
foreground           = "ImmersiveControlDarkLinkRest"
contentalign         = "middleleft"
accessible           = "true"
accrole              = "link"
accdefaction         = "click"/>
<if mousefocused="true">
<TouchHyperLink foreground = "ImmersiveControlDarkLinkHover"/>
</if>
<if pressed="true">
<TouchHyperlink foreground="ImmersiveControlDarkLinkPressed"/>
</if>
</style>
</stylesheets>
...
```
【实锤,`docs/duixml-corpus/wscapi/UIFILE_6010.xml`,全文 60 行】

读法(三条规则):

1. **`<style resid="名字">` 定义一张表;元素用 `sheet="名字"` 挂表**(语料里 `sheet=` 共出现
   约 950 次,最高频值:cp_style 416、common 95、local 79、expando_style 42——【实锤,本次语料统计】)。
2. **表内每条规则 = "标签名 + 条件"双键匹配**。`<TouchHyperLink ...>` 无条件,匹配所有该类元素;
   `<if mousefocused="true"><TouchHyperLink .../></if>` 只在鼠标悬停态叠加。
3. **`base=` 继承另一张表**。上例的 base 是 `ressheet(ImmersiveStyles, library(dui70.dll), Dark)`
   ——去 dui70.dll 的资源里找名为 ImmersiveStyles 的样式表,取其中 resid=Dark 的那张。

### 2.2 继承链:系统自带的"官方样式表"

dui70.dll 自带一份 25KB 的 UIFILE 资源 `IMMERSIVESTYLES`(duib v5 二进制,已解码为
`docs/duixml-corpus/dui70/UIFILE_IMMERSIVESTYLES.xml`,1135 行)。它的骨架是一条继承链:

```
ImmersiveBase(基础规则)
   ├── Light(base="ImmersiveBase",亮色数字颜色 20xxx)
   ├── Dark (base="ImmersiveBase",暗色数字颜色 20xxx 另一组)
   └── Default(base="Light",空壳,指向 Light)
```
【实锤,语料原文:第 9/99/586/1133 行】

系统其它模块引用它的方式(本次语料统计,`base=` 值频次):

| base= 值 | 次数 |
|---|---|
| `ressheet(ImmersiveStyles, library(dui70.dll), Dark)` | 26 |
| `ressheet(ImmersiveStyles, library(dui70.dll), Light)` | 19 |
| `ressheet(ImmersiveStyles, library(dui70.dll), dark)`(小写,同样有效) | 3 |
| `ressheet(ImmersiveStyles, library(dui70.dll), ImmersiveBase)` | 2 |
| `ImmersiveBase`(同模块直引) | 2 |
| `ressheet(205, webcamui_style)`(跨模块按资源 ID 引) | 2 |
| `Light` | 1 |

引用方覆盖 wscapi、msctfuimanager、WebcamUi、WpcMon、DeviceElementSource、InputSwitch、
phoneactivate、RADCUI、AuthBrokerUI、bdeunlock、CloudNotifications、DisplaySwitch 等 15+ 模块
【实锤,语料统计】。**这就是"三层皮肤"第①层的生态:dui70 发一张官方基础表,各系统模块派生定制**。

SystemSettings 用的另一张 `SYSTEMSETTINGSSTYLES`(3.6KB)只有一行开头,足以证明派生方式:

```xml
<style resid="moset" base="ressheet(ImmersiveStyles, Light)">
```
【实锤,`docs/duixml-corpus/dui70/UIFILE_SYSTEMSETTINGSSTYLES.xml`】

### 2.3 运行时形态:元素 → 表指针

反汇编看元素怎么拿到表。`Element::GetSheet`(RVA 0x97AD0)全长 9 字节:

```asm
180097ad0: mov rax, [rcx+0x80]   ; Element+0x80 → 某个持有者对象
180097ad7: mov rax, [rax+0x8]    ; 持有者+0x8    → StyleSheet*
180097adb: ret
```
【实锤,disasm 195715-195718】

即:每个 Element 在 +0x80 处挂一个间接持有结构,+8 偏移就是 StyleSheet 指针。
StyleSheet 本身是个 RefcountBase 系对象(符号表只有 ctor/operator=/Create/vftable 7 个导出,
内部规则结构未导出——规则如何索引属于未知,见 §6)。【实锤,符号表;内部结构未知】

样式表由 **parser 持有**(解析 `ParseStyleSheets` 装载,符号 `DUIXmlParser::ParseStyleSheets`
`AddRulesToStyleSheet` `_ResolveStyleSheet` 均在符号表)——这句话的运行时含义在`10-dark-mode-switch-chain.md`
(明暗切换)里展开:主题切换 = parser 重载样式表。【实锤,符号表 + `10-dark-mode-switch-chain.md` 的 disasm 链】

---

## 3. `<if>` 状态伪类:与 CSS 最大的心智差异

### 3.1 没有结构选择器,只有"元素自身状态"

语料全量统计:`<if>` 共 **3865** 个,`<unless>` 仅 19 个。条件维度全集(频次降序):

| 维度 | 频次 | 典型值 | 语义 |
|---|---|---|---|
| `class` | 1950 | `cp_content_instruction` 等 | 元素的 class 属性包含该值(多值 class 用空格分) |
| `mousefocused` | 388 | `true` | 鼠标悬停(即 CSS :hover) |
| `keyfocused` | 368 | `true`(352)/`false`(16) | 键盘焦点(即 :focus) |
| `id` | 301 | `atom(TouchSwitch_TrackChild)` | 原子 ID 精确匹配 |
| `pressed` | 243 | `true` | 按下(即 :active) |
| `enabled` | 223 | `false`(216)/`true`(7) | 可用性(即 :disabled 的反向) |
| `selected` | 179 | `true`(130)/`false`(49) | 选中态 |
| `mousewithin` | 62 | `true` | 鼠标在元素矩形内(含子元素,比 hover 宽) |
| `captured` | 35 | `true` | 鼠标捕获(按住拖动中) |
| `TextGlowSize` | 33 | 数值 | 属性值条件(控件特化) |
| `showkeyfocus` | 12 | bool | 键盘焦点可见性(触控时代新增) |
| `vertical` | 11 | `true`/`false` | 滚动条方向 |
| `custom` | 11 | — | 宿主自定义位 |
| `keywithin` | 9 | `true` | 焦点在子树内 |
| `checkedstate` | 6 | `checked`/`unchecked` | 复选三态 |
| `expanded` | 5 | `true` | 展开/折叠(expando) |
| `multiline` | 4 | bool | 文本多行 |
| `IsVertical` | 4 | bool | vertical 的驼峰别名 |
| `visible` | 4 | bool | 可见性 |
| `direction` | 4 | `LTR` 等 | 文字方向 |
| `visited` | 2 | `true` | 超链接已访问 |
| `ButtonFocusStyle` | 2 | — | 焦点样式开关 |
| `checked` | 1 | `true` | 布尔选中 |
| `passwordCharacter` | 2(仅 unless) | — | 密码框字符集 |

【实锤,本次对 149 个 XML 的全量正则统计;大小写变体(`KeyFocused` 5 次/`Expanded` 3 次)
按同维度合并计数后单列】

与 CSS 的核心差异一句话:**全部是"元素自身状态"谓词,没有任何后代/兄弟/属性通配结构选择器**。
所以 DirectUI 样式表是 O(元素 × 规则) 的状态匹配,不是 DOM 树查询。

### 3.2 状态是活的——样式表是"活文档"

这些维度(mousefocused/pressed/selected/…)全是**运行时可变状态**。状态翻转时框架重新匹配
规则并叠加属性——这与"XML 是一次性构造说明书"(见`01-duixmlparser-xml-to-element-tree.md`)形成鲜明对照:
**元素树构造完之后,样式规则仍然持续生效**。【实锤,语料形态 + duser UIFILE 1010 的
pushbutton 全状态覆盖;重匹配的失效粒度(逐属性 or 整表)未知,见 §6】

### 3.3 完整状态覆盖的范例:duser UIFILE 1010 的 pushbutton

每个 DUI 线程默认装载的基础样式表住在 **duser.dll 的 UIFILE 1010** 资源里
(由 `DUIXmlParser::GetParserCommon` 跨模块加载,详见 duser-landscape.md §3.3,不重复推导)。
它的 pushbutton 一节是"状态伪类全覆盖"教科书:

```xml
<pushbutton background="dtb(button, 1, 1)" foreground="buttontext"
            contentalign="middlecenter" padding="rect(20rp,5rp,20rp,5rp)"
            margin="rect(10rp, 10rp, 10rp, 10rp)" />
<if keyfocused="true">
    <pushbutton contentalign="middlecenter | focusrect" />
</if>
<if selected="true">
    <pushbutton background="dtb(button, 1, 5)" />
</if>
<if mousefocused="true">
    <pushbutton background="dtb(button, 1, 2)" />
</if>
<if pressed="true">
    <pushbutton background="dtb(button, 1, 3)" padding="rect(21rp,6rp,19rp,4rp)" />
</if>
<if enabled="false">
    <pushbutton background="dtb(button, 1, 4)" foreground="graytext" />
</if>
```
【实锤,`docs/duixml-corpus/duser/UIFILE_1010.xml` 第 47-62 行】

注意细节:pressed 态连 `padding` 都换了(视觉下沉 1px 的老 Win32 手法)——
**条件规则叠加的是任意属性,不只是颜色**。

### 3.4 嵌套与组合

`<if>` 可任意嵌套,语义是 AND;duser 1010 的 CheckBox 段有四层嵌套:

```xml
<if id="atom(CheckBox)">
    <button background="dtb(button, 3, 1)" ... />
    <if selected="true">
        <button background="dtb(button, 3, 5)" />
        <if mousefocused="true">  <!-- selected AND hovered -->
            <button background="dtb(button, 3, 6)" />
        </if>
        ...
    </if>
    <if class="mixed">...</if>
</if>
```
【实锤,同上文件 63-98 行;主题 part/state 编号 3,x 是 classic checkbox 家族】

`<unless>` 是反向条件(语料仅 19 处,dui70 自家样式表里用于 `unless class="commandrow"`
排除命令行按钮的高度规则)。【实锤,dui70/UIFILE_IMMERSIVESTYLES.xml 第 104 行】

---

## 4. 第②层:主题表达式函数库

样式表属性值是一门小型表达式语言,主题相关的函数族(语义来自符号名 + 语料用法互证,
【强推→实锤混合】,函数与 UXTheme API 的对应为【强推】):

| 函数 | 展开为(UXTheme API) | 语料例子 |
|---|---|---|
| `dtb(class, part, state)` | DrawThemeBackground 系取图形/颜色 | `dtb(TaskDialog, 1, 0)` |
| `gtc(class, part, state, prop)` | GetThemeColor | `gtc(TaskDialogStyle, 2, 0, 3803)` |
| `gtf(class, part, state)` | GetThemeFont | `gtf(TEXTSTYLE, 1, 0)` |
| `gtmar(class, part, state, prop)` | GetThemeMargins | `gtmar(TaskDialog, 1, 0, 3602)` |
| `gtps(class, part, state)` | GetThemePartSize | `gtps(button, 3, 1)` |
| `gtmet(class, part, state, prop)` | GetThemeMetric | `gtmet(TaskDialog, ...)` 104 处 |
| `themeable(light, dark)` | 按明暗模式二选一 | `themeable(dtb(AeroWizard,3,0), threedface)` |
| `sysmetric(i)` | GetSystemMetrics | `sysmetric(71)` |
| `ressheet(name, lib, Light/Dark)` | 引用另一张样式表 | §2.2 |
| `resstr(id[, lib])` | 资源字符串(本地化) | `resstr(6027)` |
| `library(mod.dll)` | 资源模块定位 | `library(dui70.dll)` |

主题类名字符串(`TaskDialogStyle`/`AeroWizardStyle`/`ControlPanelStyle`/`FlyoutStyle`/
`TextStyle`/`TooltipStyle`)以 UTF-16 形式存在 dui70 的 .rdata(如 TaskDialogStyle @VA 0x180120808、
AeroWizardStyle @0x1801206F8),并被多张 `ThemeClassInfo` 指针表(文件偏移 0x101938 起,每 0x28 字节一项)
引用——即 parser 内置"类名 → OpenThemeData 句柄"的注册表。【实锤,字符串与指针表 dump;
表结构布局细节为【强推】】

`themeable(a, b)` 是明暗切换的声明式入口:求值时按当前模式取 a 或 b。
全语料 1341 处使用(SpaceControl 392 / DiagCpl 231 / fhcpl 148 / WorkfoldersControl 144 …),
首选参数 70% 是 `dtb(CONTROLPANEL...)`。【实锤,统计】

主题句柄的获取链:`GetThemeHandle`(导出,RVA 0x886D0)尾跳进 `Element::GetTheme`
(RVA 0xC590)的 +0x148 处;GetTheme 先沿树找 root、在临界区(IAT 0x180119988/0x180119980 =
Enter/LeaveCriticalSection)保护下查每元素缓存表,miss 时 0xC754 helper 分配缓存条目
(0x18/0x50 字节对象、vftable 0x180101d70),最终经 `OpenThemeDataForDpi` 延迟导入
(IAT 0x1801953B8;参数重排 thunk @0x180079C10)开句柄。【实锤,disasm;OpenThemeDataForDpi
的调用归属由 IAT 槽位 + thunk 形态定位】

---

## 5. 颜色从哪来:三种写法的分工

语料里颜色属性有三种形态,正好对应三层皮肤:

1. **数值 ID(immersive 色表)**:`background="20575"`、`foreground="20115"` ——
   语料共 20xxx 段 919 处 + 21xxx 段 180 处。这些是 dui70 内部 immersive 色表的索引,
   **明暗两套各占一段编号**(同一控件在 Light/Dark 表里换成另一组数字,
   见 IMMERSIVESTYLES 第 99 行起 Light 段与第 586 行起 Dark 段的同名规则对照)。
   【实锤,语料 + 资源对照】
2. **具名 immersive 色**:`foreground="ImmersiveSaturatedPrimaryText"` ——
   语料 142 个不同名字(ImmersiveSaturatedPrimaryText 26 次、ImmersiveSystemAccent 19 次…)。
   这些名字最终也解析进同一 immersive 色表。【实锤,语料;名字→表项的映射机制未定位,§6】
3. **主题表达式**:`dtb(...)`/`gtc(...)`/`themeable(dtb(...), threedface)` —— 走第②层 uxtheme。

一套典型的"亮暗全态"控件写法(IMMERSIVESTYLES 的 TouchButton,节选):

```xml
<!-- Light 表(第 99 行起):五态各配三色 -->
<TouchButton background="20662" foreground="20670" bordercolor="20666" />
<if mousewithin="true"><TouchButton background="20663" foreground="20671" bordercolor="20667" /></if>
<if pressed="true">  <TouchButton background="20664" foreground="20672" bordercolor="20668" /></if>
<if enabled="false"> <TouchButton background="20665" foreground="20673" bordercolor="20669" /></if>
<!-- class="default" 的默认按钮、class="appcolorlight"/"appcolordark" 的强调色变体各再配五态 -->
```
【实锤,dui70/UIFILE_IMMERSIVESTYLES.xml 第 104-164 行】

**心智模型:明暗切换不是"改颜色属性",而是"换一张编号映射不同的表 + 重求值主题表达式"。**
(切换链路的完整时序图在`10-dark-mode-switch-chain.md`。)

---

## 6. 未知问题清单(诚实边界)

1. **StyleSheet 内部规则索引结构未知**——符号表只有 ctor/Create/vftable 7 个导出,
   规则按标签名建哈希还是线性扫?匹配复杂度?(需运行时实验或 PDB 类型信息)
2. **状态翻转 → 重匹配的失效粒度未知**:mousefocused 变化是整表重算还是只重算该元素的
   附加属性?defer 周期内是否合并?
3. **`Immersive*` 具名色 → 色表项的解析机制未定位**(parser 的具名色查找表在哪、
   是否走 FindStdColor 类似 duser 借道,未反汇编确认)。
4. **base= 合并语义的细节**:子表覆盖父表是逐属性覆盖还是整规则替换?
   (语料形态强烈暗示逐属性叠加——同一标签在子表只写差量——但未见反汇编级证明,【强推】)
5. **20xxx/21xxx 色表本体住在哪个资源/全局区**,本篇未提取(只统计了使用侧)。
6. `<if>` 里出现过的 `TextGlowSize`/`ButtonFocusStyle`/`custom` 等长尾维度
   是通用引擎谓词还是宿主自定义回调,未逐一验证。

## 证据索引

- 语料统计脚本与输出:本次会话全量扫描 `docs/duixml-corpus/`(正则 `<if\s+attr=`);
  if 3865 / unless 19 / style 267 / stylesheets 199(模块覆盖 58/57 文件)
- `docs/duixml-corpus/wscapi/UIFILE_6010.xml`(60 行完整样本)
- `docs/duixml-corpus/dui70/UIFILE_IMMERSIVESTYLES.xml`(1135 行,base 链 9/99/586/1133 行)
- `docs/duixml-corpus/dui70/UIFILE_SYSTEMSETTINGSSTYLES.xml`(moset 派生)
- `docs/duixml-corpus/duser/UIFILE_1010.xml`(默认样式表;GetParserCommon 加载链见
  duser-landscape.md §3.3)
- disasm:Element::GetSheet @0x97AD0(L195715);GetThemeHandle @0x886D0(L173182);
  GetTheme@Element @0xC590(L14245 起);OpenThemeDataForDpi thunk @0x7 9C10、IAT 0x1801953B8
- 主题类名字符串:TaskDialogStyle @0x180120808、AeroWizardStyle @0x1801206F8;
  ThemeClassInfo 表 @文件偏移 0x101938 起
- 相关报告:duser-landscape.md §3.3(默认样式表跨模块加载)、animation-expressiveness.md
  §1(timingfunction 主题耦合)、`10-dark-mode-switch-chain.md`(明暗切换链路)
