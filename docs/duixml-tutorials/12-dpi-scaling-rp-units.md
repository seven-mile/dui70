# DPI 与缩放:rp 单位从解析期烘焙到运行时通知

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> 读完你能回答:XML 里的 `rect(0rp,10rp,40rp,10rp)` 是什么时候变成像素的?
> 拖动窗口跨显示器(DPI 变了)之后框架自动做了什么、哪些必须宿主自己做?
>
> 证据分级:【实锤】= 反汇编定位到指令 / 语料 XML 原文 / 可运行验证之一;
> 【强推】= 符号名 + 结构自洽的推断,写明推断链;【猜想】= 明确标注为猜测。
> 反汇编地址均为 RVA(dui70.dll 10.0.26100 x64,基址 0x180000000)。

---

## 1. 一句话心智模型

**缩放是"解析期一次性烘焙,运行时通知+宿主响应"的两幕剧**:

- **第一幕(解析期)**:`10rp` 在 `CreateElement` 期间被乘以 parser 的缩放因子、
  四舍五入成像素整数,存进 Value——之后元素树里再也看不到 rp。
- **第二幕(运行时)**:窗口 DPI 变化 → `HWNDElement::WndProc` 更新 ScaleFactorProp 属性 →
  广播 `WindowDpiChanged` UID → **重载样式表** → invalidate 两层——
  但已烘焙的布局值不会自动重算,需要宿主响应(见 §4)。

这与 WPF(设备无关单位 + 全自动重布局)是根本性的心智差异。

---

## 2. 第一幕:rp 的解析期烘焙

### 2.1 语料面

`rp`(relative pixel)是语料里最常见的单位:全 149 个 XML 共 **14360 处** rp 值,
`rect()` 函数 3338 处(`docs/duixml-corpus/README.md` §5)——每个 margin/padding/边框/
minsize 都用它。本地化字符串 `resstr()` 3338 处(数字资源串,常用于 font 引用)。【实锤,语料统计】

看一段真实用法(wscapi 通知对话框,RichText 文本的排版全用 rp):

```xml
<RichText
    layoutpos="client"
    contentalign="wrapleft | pathellipsis | wordellipsis"
    padding="rect(0rp,1rp,0rp,1rp)"
    margin="rect(0rp,0rp,12rp,0rp)"
    font="resstr(6027)"
    foreground="ImmersiveSaturatedPrimaryText"/>
<!-- 同文件 TouchHyperLink:
     padding="rect(4rp,4rp,4rp,4rp)"  width="70rp"  minwidth="40rp" -->
```
【实锤,`docs/duixml-corpus/wscapi/UIFILE_6010.xml`,rp 值原样摘录】

解析这行 XML 时,`rect(0rp,1rp,0rp,1rp)` 的四个数字在进入 Value 系统前,
每个都经过下面这条指令路径:

### 2.2 换算指令(一条乘法 + 半个加法)

`DUIXmlParser::_ScaleRelativePixels(int v)`(RVA 0x718F0)的完整逻辑:

```asm
movd   %edx, %xmm0            ; int v → xmm
cvtdq2ps %xmm0, %xmm0         ; → float
mulss  0x5c(%rcx), %xmm0      ; × (this+0x5c) ← parser 的 float 缩放因子
addss  [0x180122240], %xmm0   ; + 0.5f(常量已 dump:字节 00 00 00 3F)
call   round-helper
cvttss2si %xmm0, %eax         ; → int(截断;先 +0.5 即四舍五入)
```

即 **`px = (int)(rp_value × scaleFactor + 0.5f)`**。缩放因子是 parser+0x5c 处的 float,
默认 1.0f(常量 @0x18011F844)。【实锤,disasm + .rdata 常量字节 dump;本篇与已交付的
`01-duixmlparser-xml-to-element-tree.md` §6 双重独立验证(同一函数,两轮反汇编一致)】

### 2.3 因子从哪来:`GetScaleFactor`

`GetScaleFactor()`(RVA 0x29640)按进程 DPI 感知模式三路分发:

```
默认 xmm6 = 1.0f(@0x18011F844)
检查感知模式(内部 helper 0x296BC,经 TLS 上下文):
  mode == 1(GetProcessDpiAwareness 系统 DPI):
      dpi = GetDesktopDPI()                    (0x29700)
      return dpi / 96.0f                       ← 常量 96.0 @0x18011F748
  mode == 2(per-monitor DPI):
      scale = GetScaleFactorForDevice(...)     ── IAT 0x180195498(shcore 延迟导入)
      return scale / 100.0f                    ← 常量 100.0 @0x18011FBBC
```
【实锤,disasm 0x29640-0x296B4 + 常量 dump;两个感知模式分支由 ebx==1/==2 的比较证明】

即:**系统 DPI 感知 → dpi/96;per-monitor → 系统给的百分比/100**。parser 的 0x5c 因子
由 `SetScaleFactor`/`GetOverrideScaleFactor` 等 API 设定(符号表),`EnableDesignMode`
的设计期缩放也走同一条 mulss(`01-duixmlparser-xml-to-element-tree.md` §6 已证)。

### 2.4 烘焙的后果

`_ParseValue` 解析 `rect(0rp,10rp,...)` 时对每个数字调 `_ScaleRelativePixels`,
之后 Value 里只有整数像素。**换 DPI 不改已建树**——这就是"为什么跨屏拖动后界面糊/错位
要靠宿主重建"的机制根源(`01-duixmlparser-xml-to-element-tree.md` §6.2 同结论)。【实锤,指令级;运行时行为见 §3】

---

## 3. 第二幕:运行时 DPI 变化的响应链

### 3.1 完整时序(WM_DPICHANGED / 显示器变更)

```
[Win32] WM_DPICHANGED(或跨显示器移动)
   │
   ▼
dui70 ①  HWNDElement::WndProc 的 DPI 分支(disasm 88212-88227)
   │    _UpdateDesktopScaleFactor()                       RVA 0x178A0
   │      ├─ ShouldUseDesktopPerMonitorScaling()          RVA 0x29970
   │      ├─ _GetPerMonitorScaleFactorForDesktopWindow(hwnd)  RVA 0x17E00
   │      ├─ Value::CreateInt(DynamicScaleValue 枚举)     RVA 0x16770
   │      └─ _SetValue@Element(ScaleFactorProp @0x180103600)   ← 属性系统更新缩放!
   │    _FireWindowDpiChangeEvent()                       RVA 0x4C1C0
   │      ├─ WindowDpiChanged UID(blob @0x180120638,工厂 0x4C220)
   │      └─ GetRoot → _BroadcastEventWorker              ← 整树广播
   │    UpdateStyleSheets()                               RVA 0x2D230
   │      └─ DUIXmlParser::UpdateSheets(root)             RVA 0x32330
   │           (递归重载样式表——与明暗切换共用同一条链!10-dark-mode-switch-chain.md §2)
   │    InvalidateGadget ── IAT 0x1801950E8(DUser)
   │    InvalidateLayeredDescendants ── IAT 0x1801950F0(DUser)
   ▼
宿主 ②  OnEvent 里收 WindowDpiChanged → 重建/重设自己的内容(见 §4)
```
【实锤,disasm 88212-88227 的连续 callq 序列;UpdateSheets 内部见`10-dark-mode-switch-chain.md` §2 的同段反汇编】

三个关键读法:

- **ScaleFactorProp 是真属性**——DPI 变化先写属性系统(0x178A0 的 _SetValue),
  意味着布局表达式中依赖 scale 的部分(如果用 DynamicScaleValue)会走属性失效。
  `DynamicScaleValue` 枚举名直接出现在 `Value::CreateInt(H, W4DynamicScaleValue)` 的
  修饰名里——**Value 类型系统知道"这是随缩放变的整数"**。【实锤,修饰名】
- **样式表重载被 DPI 复用**:UpdateStyleSheets 链与明暗切换(`10-dark-mode-switch-chain.md`)完全同一条——
  因为样式表里的 `sysmetric()`/rp 系值在重载时会用新因子重烘焙(parser 侧 0x5c 因子
  已被 ① 更新)。【链路共用实锤;"重载用新因子"一步为【强推】(UpdateSheets 走 parser
  重建表,表内表达式按当前 parser 状态求值)】
- **两层 invalidate 后,渲染面自动跟上**(gadget 树/分层后代),但**元素自身的 width/height
  等"已烘焙属性"不动**——这就是第二幕需要宿主的原因。

### 3.2 注册通知:Touch 时代与 shcore

经典路径之外,`TouchHWNDElement`(触控窗口根)还接了 shcore 的通知:

```
TouchHWNDElement::Initialize(RVA 0x2A8A0, disasm 50090):
    RegisterScaleChangeNotifications(NULL, 0x403 /*DISPLAY_DEVICE?,
        hwnd, perMonitor?, &this+0x140)   ── IAT 0x180195490
UsePerMonitorScaling(RVA 0x47FD0, disasm 85508):
    RegisterScaleChangeEvent(&this+0x190) ── IAT 0x1801954B8
析构/OnDestroy:Revoke/Unregister 成对                    ── 0x180195488 / 0x1801954B0
```
【实锤,disasm + iat_delay_map;0x403 参数语义为【强推】】

Touch 家族有专属 UID `ScaleChanged`(`TouchHWNDElement::ScaleChanged`,blob @0x18011FDE8,
工厂 RVA 0x2E870)——与经典 `WindowDpiChanged`(@0x180120638)**是两个不同事件**,
触控树监听前者。两个 UID blob 的字节形态明显不同(前者全零+84ff 模式,后者 40 00 00 10 04 02
20 00 01 带 flags 位),暗示事件携带负载不同。【实锤,uid_table;负载语义未解码,§5】

### 3.3 动态缩放开关

注册表键 `Software\Microsoft\DirectUI\DynamicScaling`(UTF-16 串 @0x18011FBC0)+
符号 `DUIXmlParser::IsDynamicScaling` / `SetDynamicScaling`:解析期行为开关,
决定某些值是否用"动态"(随 ScaleFactorProp 失效重算)的 Value 形态。默认值与取值语义未验证。【实锤,
字符串+符号;语义细节【强推】】

---

## 4. DPI 变化时,三类资源的完整响应对照表

| 资源 | 框架自动做的 | 需要宿主做的 | 证据 |
|---|---|---|---|
| **样式表里的 rp/themeable/sysmetric 值** | UpdateStyleSheets 整树重载(§3.1 ③)——重载即按新因子/新主题重求值 | 无 | 实锤(链路);重烘焙细节强推 |
| **uxtheme 主题句柄** | (若走 WM_THEMECHANGED)FlushThemeHandles 链(`10-dark-mode-switch-chain.md` §2);OpenThemeDataFor**Dpi** 本身带 DPI 参(IAT 0x1801953B8) | 无(或主动调 FlushThemeHandles) | 实锤 |
| **元素布局属性(width/margin 已烘焙的 px)** | **什么都不做**——值是整数,不随 DPI 变 | 监听 WindowDpiChanged(或 ScaleChanged),重建子树/手动重设属性 | 实锤(烘焙指令 §2.2)+ 广播实锤;响应模式为语料无、API-only 推断 |
| **位图/图标资源** | 框架层面无 DPI 自动换图机制(无 LoadImageForDpi 类 IAT) | 宿主按新 DPI 自行选资源 | 实锤(IAT 缺位) |
| **字体** | 样式表 font=resstr(...) 重载时重新求值;GetThemeFont 系走新主题句柄 | 直接创建的字体自行处理 | 强推 |

(表内"框架无自动换图"的证据:全库 IAT 无 LoadImageForDpi/GetIconInfoEx 类按 DPI 分派的
图像 API;位图装载走宿主模块资源 + `_LoadImage32BitsPerPixel` 类私有路径。)

---

## 5. 未知问题清单(诚实边界)

1. **ScaleChanged 与 WindowDpiChanged 的负载差异**:两个 UID blob 字节形态不同,
   事件结构里携带了什么(新 DPI?旧 DPI?显示器句柄?)未解码。
2. **DynamicScaleValue 枚举全集与生效范围**:`Value::CreateInt(H, W4DynamicScaleValue)`
   证明存在这个枚举,但哪些属性(字号?margin?)在 DynamicScaling 开启时会用它
   (即"能自动跟着 DPI 重算的 Value"),未逐一验证——这直接决定 §4 表第三行的
   "什么都不做"在 DynamicScaling=on 时放宽到什么程度。
3. **0x403 通知参数语义**(RegisterScaleChangeNotifications 的第 2 参):按 shcore
   惯例猜 DISPLAY_DEVICE 类常量,未对照 SDK 头证实。
4. **多显示器下每 parser 的因子独立性**:parser+0x5c 是每 parser 一份,
   两个不同 DPI 的窗口共用一个 parser 时怎么办(SetParser 复用场景),未验证。
5. rp 之外的单位全景:语料只见 px(无单位)/rp;pt 由 `_ScalePointsToPixels` 处理(符号表),
   换算指令未单独反汇编(与 rp 的差异点未知);负值/百分比不存在于语料。

## 证据索引

- disasm:_ScaleRelativePixels @0x718F0(L139403;`01-duixmlparser-xml-to-element-tree.md` §6 亦引);
  GetScaleFactor @0x29640;GetDesktopDPI @0x29700;
  WndProc@HWNDElement DPI 分支(L88212-88227);_UpdateDesktopScaleFactor @0x178A0;
  _FireWindowDpiChangeEvent @0x4C1C0(L90463);WindowDpiChanged 工厂 @0x4C220(L90506);
  TouchHWNDElement::Initialize @0x2A8A0(L50090);UsePerMonitorScaling @0x47FD0(L85508);
  ScaleChanged 工厂 @0x2E870(L85500 附近)
- 常量 dump:.rdata 0x180122240=0.5f、0x18011F844=1.0f、0x18011F748=96.0f、0x18011FBBC=100.0f
- IAT(iat_delay_map.txt):RegisterScaleChangeNotifications 0x180195490 / Revoke 0x180195488 /
  GetScaleFactorForDevice 0x180195498 / RegisterScaleChangeEvent 0x1801954B8 /
  UnregisterScaleChangeEvent 0x1801954B0 / GetScaleFactorForMonitor 0x1801954C8;
  DUser InvalidateGadget 0x1801950E8 / InvalidateLayeredDescendants 0x1801950F0(iat_map.txt)
- 字符串:Software\Microsoft\DirectUI\DynamicScaling @0x18011FBC0
- UID blob:WindowDpiChanged @0x180120638、ScaleChanged @0x18011FDE8
  (`.local/build/ui-mental-model/uid_table.txt`)
- 语料统计:rp 14360 处、resstr() 3338 处(本次全量扫描);
  rect() 3338 处(docs/duixml-corpus/README.md §5)
- 引用报告/教程:`01-duixmlparser-xml-to-element-tree.md` §6(rp 烘焙的双重验证)、`10-dark-mode-switch-chain.md` §2(UpdateStyleSheets 共用链)、
  ui-mental-model-outline §11(任务来源)
