# 明暗切换全链路:从 ImmersiveColorSet 到样式表重载

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 读完你能完整说出:用户在设置里把 Windows 切到深色模式之后,一个 DirectUI 窗口内部依次发生了什么,
> 每一步在 dui70.dll 的哪个地址。
>
> 证据分级:【实锤】= 反汇编定位到指令 / 语料 XML 原文 / 可运行验证之一;
> 【强推】= 符号名 + 结构自洽的推断,写明推断链;【猜想】= 明确标注为猜测。
> 反汇编地址均为 RVA(dui70.dll 10.0.26100 x64,基址 0x180000000),
> disasm 行号指 `.local/audit/dui70-full-disasm.txt`。

---

## 1. 一句话心智模型

**明暗切换不是属性系统的成员,它是一条独立的 HWND 消息驱动链路**:

```
WM_SETTINGCHANGE(lParam="ImmersiveColorSet")
  → HWNDElement::OnWmSettingChanged 字符串过滤
  → UxTheme ord104/ord106 查询新模式
  → 根节点广播 ImmersiveColorSchemeChange UID(宿主可监听)
  → FlushThemeHandles 丢弃 uxtheme 主题句柄缓存
  → UpdateStyleSheets → parser 重载样式表(第①层皮肤换表)
  → 布局/渲染失效,重绘
```

与 WPF 的对照:WPF 里主题是资源字典切换;DirectUI 里是"**消息 → 广播 → 换表**"三段式,
前半段走 Win32 消息泵,后半段走框架自己的 UID 事件系统。

---

## 2. 全链路时序图(每步附 RVA)

先看语料里这条链的"声明侧"。一个模块要参与明暗切换,只需在样式表里声明派生关系
(这是宿主唯一要做的事):

```xml
<!-- wscapi.dll UIFILE 6010(通知对话框):从 dui70 官方表派生 Dark 皮肤 -->
<stylesheets>
<style resid="NotificationDialog" base="ressheet(ImmersiveStyles, library(dui70.dll), Dark)">
    <if class="DialogText">
        <RichText foreground="ImmersiveSaturatedPrimaryText" font="resstr(6027)" ... />
    </if>
    <!-- TouchHyperLink 的 mousefocused/pressed 态用 Immersive 具名色,继承自 Dark 表 -->
</style>
</stylesheets>
```
【实锤,`docs/duixml-corpus/wscapi/UIFILE_6010.xml`;写法详解见`09-stylesheet-three-layers.md` §2】

切换发生时,上表的 `base=` 会被 parser 沿继承链重新求值(Dark 侧数值重新生效),
`ImmersiveSaturatedPrimaryText` 等具名色查到的 RGB 随 immersive 色表整体翻面。
下面是框架内部让这一切发生的完整指令链:

```
用户:设置 → 个性化 → 深色模式
────────────────────────────────────────────────────────────────────
[Win32]    系统广播 WM_SETTINGCHANGE(wParam=0,lParam→"ImmersiveColorSet")
              │
              ▼
dui70 ①   HWNDElement::OnWmSettingChanged(wParam, lParam)   RVA 0x76D98(disasm 147024)
              │  rdx = lParam(设置名字符串)
              │  CompareStringOrdinal(ordinal=1 即 IGNORE_CASE,
              │                       str1=lParam, str2=L"ImmersiveColorSet" @0x180122D80)   ── IAT 0x180119890
              │  if (结果 == CSTR_EQUAL 即 2)                      (disasm 147037: cmpl $0x2, %eax)
              │      call [UxTheme!ord104]                        ── IAT 0x1801953E8
              │  call [UxTheme!ord106](1)  ← 无论匹配与否都调       ── IAT 0x1801953F0 (disasm 147039/147042)
              │  return bool(是否命中)
              ▼ 命中(经 ThemeChange 事件路径汇入串联函数)
dui70 ★   HWNDElement::OnThemeChanged(ThemeChangedEvent*)     RVA 0x2D430(disasm 53291)
              │  —— 串联者:以下 ③→④→② 按此顺序依次直调 ——
              │
              ├─→ ③ FlushThemeHandles 内部块(+0x60 直调)      0x18002D290(disasm 53298)
              │      if (hmod == -2) return
              │      EnterCriticalSection                    ── IAT 0x180119988
              │      在 ResourceModuleHandles 全局表(0x1801812F0/300/330)里比对/移除该模块的
              │      主题句柄缓存条目 → Destroy@ResourceModuleHandles+0x2C
              │      LeaveCriticalSection                   ── IAT 0x180119980
              │
              ├─→ ④ UpdateStyleSheets()                       RVA 0x2D230(disasm 53300)
              │      从 this 取 parser(vtable+0x1B8 间接取对象,disasm 53106)
              │      DUIXmlParser::UpdateSheets(rootElement)  RVA 0x32330(disasm 59321)
              │          ├─ _EnterOnCurrentThread@DUIXmlParser
              │          ├─ GetDeferObject@Element → defer+0x38/+0x60 计数(批量事务)
              │          ├─ GetValue@Element(SheetProp)       (disasm 59352)
              │          ├─ 遍历元素数组(递归对每个子元素 UpdateSheets,disasm 59377)
              │          └─ EndDefer@Element(cookie=0xABCDEF42)(disasm 59394)
              │
              ├─→ 两处 vtable+0x168 间接调用 + IAT 0x180119400(消息分发,
              │      携带回调 0x18007CAF0、消息号 0x31A、事件参数)    (disasm 53303-53331)
              │
              └─→ ② _HandleImmersiveColorSchemeChange()      RVA 0x2E230(disasm 53334)
                     call [UxTheme!ord106](ecx=1)            ── IAT 0x1801953F0(disasm 54310)
                     GetRoot@Element                         RVA 0xB540
                     ImmersiveColorSchemeChange 取 UID        RVA 0x2E810(blob @0x18011FDE5)
                     _BroadcastEventWorker(root, Event)      RVA 0x2E890
                         → 整树广播(此时树已换好装)
              ▼
渲染      ⑤ 失效 → 重绘:gadget 层 Invalidate(参看 DPI 链路同名调用,12-dpi-scaling-rp-units.md)
────────────────────────────────────────────────────────────────────
```

【实锤,以上每步的指令地址均已核对;③④ 的调用关系由直接 callq/jmp 指令证明;
②→③④ 的串联者已定位:`HWNDElement::OnThemeChanged`(RVA 0x2D430,disasm 53291),
该函数以固定顺序依次调用 ③的内部块(0x2D290,+0x60 直调)→ ④(0x2D230)→
两处 vtable+0x168 间接调用与 IAT 0x180119400(消息 0x31A 分发,含 0x18007CAF0 回调)→
②(0x2E230 _HandleImmersiveColorSchemeChange 收尾)。即:**③④② 的实际执行顺序是
"先刷句柄重载表,最后广播"**——广播事件发出时,树已经换完装】

几个读图要点:

- **ord104/ord106 是谁**:UxTheme 的两个未文档化导出(IAT 槽 0x1801953E8/0x1801953F0)。
  从用法看:①里 ord104 仅在字符串匹配命中时调用、ord106 无条件调用并再调一次;
  ②里 ord106(1) 在广播前调用。综合形态高度吻合
  `ShouldSystemUseDarkMode` / `GetImmersiveColorTypeFromIndex` 一类 immersive 模式查询,
  但**真实名字未证实**——这是本链路唯一悬而未决的点(见 §6)。【用法实锤,名字猜想】
- **`ImmersiveColorSet` 过滤是大小写不敏感的**(CompareStringOrdinal 第 3 参传 1 = 忽略大小写,
  disasm 147031 的 `movl $0x1, 0x20(%rsp)`)。【实锤】
- **FlushThemeHandles 是导出 C API**——宿主(如 comdlg32,见`11-xfamily-xbaby.md` §3)可以主动调它
  强制刷新主题句柄缓存,不必等消息。【实锤,导出表 + comdlg32 导入实测】

---

## 3. 为什么样式表要由 parser 重载?

回忆`09-stylesheet-three-layers.md` 的三层皮肤:第①层(StyleSheet)在解析期由 parser 装载、元素通过
`Element+0x80 → +0x8` 指到表(`GetSheet` @0x97AD0)。明暗相关的值有两类都"住在"表里:

1. **immersive 色表编号**(如 `background="20662"`)——数字本身不变,
   但编号→RGB 的映射随明暗换表;
2. **`themeable(light_expr, dark_expr)` 表达式**——求值时二选一。

所以切换 = 让 parser 对**整棵已建成的元素树**重新过一遍样式表(UpdateSheets 的递归遍历,
disasm 59377 的自调用),再让第②层(uxtheme)的主题句柄缓存全部作废(FlushThemeHandles)。
两步分别对应 disasm 链的 ④ 和 ③——串联函数 `OnThemeChanged` 证明了顺序是
**先刷句柄(③)再重载表(④)再广播(②)**,宿主在 OnEvent 里收到
ImmersiveColorSchemeChange 时看到的是**已经换好装的树**。

UpdateSheets 里的 `0xABCDEF42` 是 defer 事务的 magic cookie(disasm 59343):
批量重载在 EndDefer 时一次性提交,避免重载过程中间态被渲染出来
(defer 事务语义见`18-properties-and-lifecycle.md`/生命周期)。【实锤,cookie 字面值;defer 复用语义见既有教程】

---

## 4. 主题与动画的隐藏耦合:timingfunction

一条容易被忽略的链:主题切换不只换颜色,**PVL 动画的缓动曲线也是主题定义的**。

`AddAnimationToStoryboard`(RVA 0x45A90,全库 62 处调用)会:

```
OpenThemeData(hwnd, L"animations")        ← 动画参数主题类
OpenThemeData(hwnd, L"timingfunction")    ← 缓动曲线主题类
  → GetThemeTimingFunction(...)           ── IAT 0x195350
      填 GTRANS_DESC+0x60..0x6C 的三段贝塞尔控制点
  → GetThemeAnimationTransform(...)       ── IAT 0x195358(失败重试 0x800700EA)
  → GetThemeAnimationProperty(...)        ── IAT 0x195390
```

即:**换一套 msstyles/immersive 主题 = 换全系统的过渡手感**(曲线斜率、时长比例),
不只是换色板。这条结论与动画五层栈的关系在 animation-expressiveness.md §1 已完整论证
(本篇不重复推导,引用之)——明暗切换链路的 ③(FlushThemeHandles)同样让这些
`timingfunction`/`animations` 句柄作废重建,所以深浅切换的瞬间,连动画曲线都换了。【实锤,
引用 animation-expressiveness.md §1;句柄失效与重建的时序对齐为【强推】】

---

## 5. 宿主侧怎么消费这条链

给写应用的开发者三条实操结论:

1. **想在明暗切换时改自己的 UI**:监听 `ImmersiveColorSchemeChange` UID
   (UID 工厂 RVA 0x2E810,blob @0x18011FDE5),在 `IElementListener::OnEvent` 里处理。
   同族还有 `ThemeChange`(工厂 0x2E830,普通 WM_THEMECHANGED 触发,disasm 88246 处
   WndProc 的 0x83FE 分支)——**两个事件是两条链**,前者管 immersive 色表,后者管经典主题。【实锤】
2. **自定义 immersive 颜色的最稳路径**:样式表里用 `themeable(light, dark)` 双值声明 +
   基表派生(`base="ressheet(ImmersiveStyles, library(dui70.dll), Dark)"`),
   让框架的重载机制替你换装,别在元素属性上硬编码 RGB(语料 1341 处 themeable 用法背书,见`09-stylesheet-three-layers.md` §4)。
3. **手动强制刷新**:`FlushThemeHandles(hModule)` 是导出 API,宿主换完自己的资源后可直调
   (comdlg32 就这么用,见`11-xfamily-xbaby.md` §3)。【实锤,导出表】

---

## 6. 未知问题清单(诚实边界)

1. **ord104/ord106 的真实名字与精确语义**(本篇最大遗留)。
   候选方向:用带符号的旧版 UxTheme.dll/公开符号服务器比对 ordinal。
   用法侧(104 条件调、106 无条件调+广播前调)已实锤,名字属【猜想】。
2. ~~②→③→④ 的调用者是谁~~ **已解决(本轮补证)**:串联函数是
   `HWNDElement::OnThemeChanged`(RVA 0x2D430,disasm 53291-53338),固定顺序
   ③内部块→④→(消息分发 0x31A)→②。仍悬置的一小节:①OnWmSettingChanged 的 bool
   返回值经哪条调用路径汇入 OnThemeChanged(推测经 ThemeChange 事件分发/虚调用,
   未定位到直接 callq)。【汇入点【强推】,串联者【实锤】】
3. immersive 色表编号(20xxx/21xxx)的本体在哪个资源、切换时编号→RGB 的重映射表怎么换,
   未提取(`09-stylesheet-three-layers.md` §6 同问)。
4. `GetThemeTimingFunction` 句柄在 Flush 后的惰性重建时机(首次动画 or 立即预取)未验证。
5. WM_SETTINGCHANGE 的其它 lParam 值(非 ImmersiveColorSet)在 OnWmSettingChanged 里
   是否还有旁路处理(函数只暴露了这一条字符串比较,但入口分发在 WndProc 更早处,未穷举)。

## 证据索引

- disasm:OnWmSettingChanged @0x76D98(L147024-147048);**OnThemeChanged 串联函数 @0x2D430
  (L53291-53338,依次调 0x2D290/0x2D230/0x31A 消息分发/0x2E230)**;
  _HandleImmersiveColorSchemeChange @0x2E230(L54304-54329);
  ImmersiveColorSchemeChange 工厂 @0x2E810;
  FlushThemeHandles @0x82BA0(L164315-164317);UpdateStyleSheets@HWNDElement @0x2D230(L53099);
  UpdateSheets@DUIXmlParser @0x32330(L59321-59395);ThemeChange 工厂 @0x2E830(L88246 附近调用)
- IAT:CompareStringOrdinal 0x180119890;UxTheme ord104 0x1801953E8 / ord106 0x1801953F0;
  Enter/LeaveCriticalSection 0x180119988/0x180119980(`iat_map.txt`);
  消息分发槽 0x180119400
- 字符串:L"ImmersiveColorSet" @0x180122D80
- UID blob:ImmersiveColorSchemeChange @0x18011FDE5、ThemeChange @0x18011FDE6
  (`.local/build/ui-mental-model/uid_table.txt`)
- 引用报告:animation-expressiveness.md §1(timingfunction 三函数与 GTRANS_DESC 贝塞尔布局)、
  duser-landscape.md §3.3(默认样式表);`09-stylesheet-three-layers.md`(三层皮肤)、`11-xfamily-xbaby.md`(X* 家族)、
  `12-dpi-scaling-rp-units.md`(DPI 链路共用 UpdateStyleSheets)
