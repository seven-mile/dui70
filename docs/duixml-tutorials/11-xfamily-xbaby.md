# X* 家族:XBaby 是谁的孩子

> 本教程面向"懂 Win32、但不懂 DirectUI 内部"的 C++ 开发者。
> X* 家族是 dui70 里最神秘的一组类:语料 0 次出现(没有任何 XML 标签直接用它们),
> 却全家族导出、且被 `RegisterXControls` 注册进全局类表。本篇用方法签名考古 +
> 反汇编交叉 + vftable 布局(逆向生成流水线时逐类分析过)把这四类拼成一个完整的
> "跨 HWND 对话框"机制,并正面回答:XBaby 的 Baby 是什么意思?
>
> 证据分级:【实锤】= 反汇编定位到指令 / 语料 XML 原文 / 可运行验证之一;
> 【强推】= 符号名 + 结构自洽的推断,写明推断链;【猜想】= 明确标注为猜测。
> 反汇编地址均为 RVA(dui70.dll 10.0.26100 x64,基址 0x180000000)。

---

## 1. 一句话心智模型

**X* 家族 = "把一棵 DirectUI 元素树装进别人家的 HWND"的互操作协议**,
四个类各守一角:

| 类 | 导出方法数 | 职责(从方法名考古) | 继承(classes.json) |
|---|---|---|---|
| **XHost** | 13 | 宿主壳:把 Element 树挂到一个 HWND 上,转发 WndProc | (无基类条目,独立壳) |
| **XElement** | 32 | 反向桥:在 DUI 树里嵌一个"会自己收消息的 HWND 岛" | HWNDHost + IXElementCP |
| **XProvider** | 28 | 外部驱动接口:宿主程序通过它操纵整棵树 | IXProvider |
| **XBaby** | 40 | 嵌入式对话框:小型的自足对话框树 | HWNDElement + IDialogElement + IElementListener |

【实锤,导出计数来自 pinned/symbols.json;继承来自 pinned/classes.json】

X = "external/cross"(跨 HWND)——四个类全部围绕"DirectUI 树与外部 HWND 世界之间的边界"。

---

## 2. 逐类深挖

### 2.1 XHost(13 方法):最薄的壳

完整方法面(全部导出):

```
Create(IXElementCP*, XHost**)   Initialize(IXElementCP*)
Host(Element*)   GetElement()   GetHWND()
ShowWindow(int)  HideWindow()   DestroyWindow()
Destroy()        WndProc(HWND, UINT, WPARAM, LPARAM)  [static]
ctor/dtor/operator=
```
【实锤,符号表】

`Host(Element*)`(RVA 0x81ED0,disasm 163167)的反汇编把"壳"字演绎得明明白白:

```asm
mov [rcx+8], rdx              ; this+0x8 = 目标元素树根
testb $0x40, 0x98(%rdx)       ; 元素标志位 0x40(HWNDElement 位)
je  skip
  ; HWNDElement 特殊路径:
  SetWindowLongPtrW(hwnd, -20 /*GWLP_ID*/, ...)   ── IAT 0x180119438/0x180119430
  ;   (先读旧值 | 0x500000 再写回——把 HWND 的 ID 槽位标成"DirectUI 托管")
GetWindowRect(hwnd, &rect)                       ── IAT 0x1801192A8
StartDefer@Element(&key)
SetWidth@Element(rect.w)   SetHeight@Element(rect.h)   ; 窗口尺寸 → 元素尺寸
EndDefer
```
【实锤,disasm 163167-163205;IAT 槽位已对表】

即:**Host = "记住树根 + 若树根是 HWNDElement 就把它认领成窗口的非客户区内容,
并把窗口客户区尺寸同步成元素尺寸"**。之后 ShowWindow/HideWindow 只是壳上的便捷开关,
`WndProc` 是静态注册给窗口的消息泵接口。

### 2.2 XElement(32 方法):反向桥

与 XHost 方向相反:XElement 是**一个元素**(能进 DUI 树、有 layoutpos),
但它内部藏着一个真 HWND。方法面的关键词:

```
CreateHWND()  GetInnerHWND()  GetNotificationSinkHWND()
OnMessage()  OnInput()  OnEvent()  OnSinkThemeChanged()  OnSysChar()
GetProvider()  SetProvider(IUnknown*)  FreeProvider()
s_uNavigateOutMsg  s_uButtonFocusChangeMsg  s_uUnhandledSyscharMsg  [3 个静态注册消息]
```
【实锤,符号表;3 个 s_u*Msg 是 RegisterWindowMessage 风格的自定义消息槽,static data 导出】

继承 `HWNDHost + IXElementCP` 的双 vftable(`??_7XElement@@6BHWNDHost@1@@` 与
`??_7XElement@@6BIXElementCP@1@@`,均为导出符号)——**它同时是"元素侧的 HWND 容器"
和"CP 协议的实现者"**。【实锤,导出表 vftable 形态】

典型用途推断:在 DirectUI 界面里嵌一个 Win32 原生控件(比如编辑框、浏览器帧),
消息先经 `OnMessage` 过滤,主题变化经 `OnSinkThemeChanged` 与宿主同步(名字直译:
"宿主 HWND 的主题变了,通知岛内")。【强推,方法名 + 消息三件套形态】

### 2.3 XProvider(28 方法):外部驱动接口

XProvider 是**宿主程序握在手里的方向盘**。它是纯接口实现(继承 IXProvider,
own-vptr vftable `??_7XProvider@@6B@` 为导出符号——这正是逆向流水线里需要 MASM 伴随文件的
15 个 own-vftable 类之一,该 ABI 细节见 width-expansion.md §2.1,本篇不重复)。

核心方法按对话流程分组:

```
装配:  Create(Element*, IXProviderCP*, XProvider**)   CreateDUI(IXElementCP*, HWND**)
        CreateParser(DUIXmlParser**)                   CreateXBaby(IXElementCP*, HWND*, Element*, ULONG*, IXBaby**)
驱动:  SetFocus(Element*)  Navigate(dir, bool*)  ClickDefaultButton()
        SetParameter(GUID, void*)   GetDesiredSize(w, h, SIZE*)   GetHostedElementID(wchar_t**)
对话框语义: SetDefaultButtonTracking  SetRegisteredDefaultButton(Element*)
        SetButtonClassAcceptsEnterKey  SetHandleEnterKey  CanSetFocus(bool*)
杂项:  ForceThemeChange(WPARAM, LPARAM)  FindElementWithShortcutAndDoDefaultAction(uchar, uint)
COM:   QueryInterface/AddRef/Release(XProvider 实现了 IUnknown 形状)
```
【实锤,符号表签名】

`CreateDUI`(RVA 0x81D00,disasm 163019)的骨架:

```
if (!pCP || !phwnd) return E_POINTER(0x80040303);
if (!this->[0x20])  return E_FAIL(0x80004005);
XHost::Create(pCP, &host);                        // ① 先造壳
// ② 一串间接虚调用(经 0x1800FF010 thunk):在 CP 接口上协商/取元素
//    (CreateHWND/构建根元素/挂 provider——即 IXElementCP 的虚方法序列)
XHost::Host(element);                             // ③ 把树挂进壳
EndDefer@Element(...);                            // ④ 一次性提交
*phwnd = host 窗口句柄;                            // ⑤ 返回给宿主
```
【实锤,disasm 163036-163136;②的具体虚方法序号未逐个解码,见 §6】

注意 `CreateXBaby` 的返回类型(从修饰名 `PEAPEAUIXBaby@2@@` 反解):**返回的是 `IXBaby*`
接口指针**——XBaby 对外只暴露接口,与 IXElementCP/IXProviderCP 的"CP 协议"对称。
IXBaby 在符号表里仅作为返回类型出现(无成员符号),是纯前向接口。【实锤,修饰名反解】

### 2.4 XBaby(40 方法):嵌入式对话框

XBaby 是四类里唯一"三继承"的:`HWNDElement + IDialogElement + IElementListener`,
四个 vftable 形态(裸 `6B@` + 三个基类限定)全部导出——MI + own-vptr 布局,
同样是流水线里分析过的老朋友。【实锤,导出表】

方法面直接把"对话框"三个字写满:

```
按钮/回车协议:  ClickDefaultButton()  SetRegisteredDefaultButton  SetDefaultButtonTracking
                SetButtonClassAcceptsEnterKey  SetHandleEnterKey  GetDefaultButtonTracking
焦点协议:       SetKeyFocus  CanSetFocus  GetFocusableElement  OnChildReceivedFocus  OnChildLostFocus
快捷键:         OnNoChildWithShortcutFound(KeyboardEvent*)
尺寸:           GetContentDesiredSize(w, h) → SIZE
导航:           GetAdjacent(...)  [键盘导航协议]
装配:           Create  Create(IXElementCP*, XProvider*, HWND*, Element*, ULONG*, XBaby**)
                Initialize  SetToHost(Element*)  CacheParser(DUIXmlParser*)  CreateStyleParser
主题:           OnThemeChanged  OnWmThemeChanged  ForceThemeChange
无障碍:         GetElementProviderImpl(InvokeHelper*, ElementProvider**)
```
【实锤,符号表】

`Create` 六参版(RVA 0x89B30,disasm 175259)一望而知是个工厂:
`operator new(0x150 /*336 字节*/)` → 构造 → `Initialize(pCP, pProvider, hwnd, parent, flags)`
→ 失败即 `Destroy(true)`。**336 字节的对象上驮着三份基类子对象 + 对话框协议状态**,
是标准的"重量级根元素"。【实锤,disasm;字段布局未逐字节还原】

`SetToHost`/`CacheParser`/`GetContentDesiredSize` 这三个方法的导出状态有一段演化史线索:
outline §F1 曾记录它们出现在某个"removed"名单里,而本轮符号表复核三者**均在导出表**
(EXP)。需要诚实说明:outline 引用的 `removed_symbols` 数据源在本轮 pinned 数据
(symbols.json 顶层仅有 `symbols` 键)中**不存在**,该历史断言无法独立核实;
可实锤的现状是——这三个方法与 `TouchXBaby`(34 个方法**全部内部符号、零导出**,
vftable 形态 `6BTouchHWNDElement@1@@` 等)的存在一起,说明 XBaby/TouchXBaby 这对
"桌面/触控双生"在版本间公开面调整频繁,是活跃演化区。【现状【实锤】(符号表);
"曾收回又恢复"的历史过程为【猜想】(outline 线索 + 数据源缺失,按分级规范降格处理)】

顺带展示"无 X 的镜像"在 XML 侧的样子——`DialogElement` 与 XBaby 三继承完全同形
(见 §3),语料里它以 `<DialogElement>` 标签出现,按钮区状态伪类与 XBaby 的
默认按钮协议一一对应:

```xml
<!-- duser UIFILE 1010(每个 DUI 线程的默认样式表):TaskDialog 形态的样式侧 -->
<stylesheets>
<style resid="common">
    <if id="atom(taskdialogroot)">
        <element background="themeable(dtb(TaskDialog, 1, 0), threedface)"
                  padding="rect(11rp, 11rp, 11rp, 11rp)"/>
        <if id="atom(instructions)">
            <element font="gtf(TaskDialogStyle, 2, 0)"
                      foreground="gtc(TaskDialogStyle, 2, 0, 3803)"
                      contentalign="topleft | wrap | wordellipsis | endellipsis"/>
        </if>
        <if id="atom(buttonzone)">
            <button background="dtb(button, 1, 1)" margin="rect(10rp,10rp,10rp,10rp)"
                    padding="rect(20rp,5rp,20rp,5rp)" .../>
            <if keyfocused="true"> <button contentalign="middlecenter | focusrect"/> </if>
            <if mousefocused="true"> <button background="dtb(button, 1, 2)"/> </if>
            <if pressed="true">      <button background="dtb(button, 1, 3)"/> </if>
            <if enabled="false">     <button background="dtb(button, 1, 4)"
                                             foreground="graytext"/> </if>
        </if>
    </if>
</style>
</stylesheets>
```
【实锤,`docs/duixml-corpus/duser/UIFILE_1010.xml`(节选重组,原文为完整 UIFILE;
`taskdialogroot`/`instructions`/`buttonzone` 三个原子 id 与 pushbutton 五态覆盖均在)】
——XBaby 的 Enter 键/默认按钮方法面(§2.4)服务的正是这样一棵按钮树。

---

## 3. 加分项验证:comdlg32 的 TaskDialog 是这套骨架吗?

**假说**(duser-landscape.md §3.3 提出):TaskDialog 的按钮区是 dui70 搭的,
XProvider::CreateDUI + XBaby 是实现骨架。

**实测**(dumpbin /imports comdlg32.dll,本机 26100):

comdlg32.dll 从 DUI70.dll 导入的**全部**符号只有 5 个 C API:

```
InitProcessPriv(10C0)  InitThread(10C1)  UnInitProcessPriv(10DE)  UnInitThread(10DF)
FlushThemeHandles(10B5)
```

【实锤,dumpbin /imports;无任何 X* 装饰名、无 CreateDUIWrapper*】

**结论分两半**:

1. **"TaskDialog 的内容树由 dui70 生态构建"成立,但不是 comdlg32 亲手调 XProvider**——
   comdlg32 只做初始化和主题刷新,树必然由 dui70 内部路径构建。已实锤的内部路径是:
   `DUIXmlParser::GetParserCommon`(RVA 0x71CB0)从 **duser.dll 的 UIFILE 1010** 资源加载
   `taskdialogroot`/`instructions`/`buttonzone` 样式表(duser-landscape.md §3.3 已完整论证),
   即"样式住在下层 duser、解释器住在上层 dui70"。
2. **"XProvider::CreateDUI + XBaby 就是 TaskDialog 骨架"得不到直接证据支持,降级为形态对应**:
   谁在内部调 CreateDUIWrapperEx(RVA 0x8C5A0,即 XProvider::Create 的 C 包装)?全库
   仅两处调用者——`CreateDUIWrapperFromResource`(RVA 0xDAA10)和
   `TaskPage::DUICreatePropertySheetPage`(RVA 0xDDE90,disasm 296928)。
   **后者是 AeroWizard/属性页的入口,不是 TaskDialog 的**。
   TaskDialog 自身的构建入口在本轮反汇编中未定位(见 §6)。

形态侧的有力旁证:XBaby 的三继承(HWNDElement + IDialogElement + IElementListener)
与 **DialogElement 完全同形**(classes.json 里两者继承列表逐项相同)——
"对话框语义元素"在 dui70 里有两种落地:XML 可用的 `DialogElement` 与 X* 协议里的 `XBaby`,
后者多了"被外部宿主经 XProvider 驱动"的整个方法面。TaskDialog 形态(buttonzone、默认按钮、
Enter 协议)与 XBaby 的方法面高度吻合,但**吻合不是调用证据**。【形态对应【强推】,调用链【未证实】】

### XBaby 的 Baby 是什么意思?

**诚实结论:不知道。**可摆出的证据:

- XBaby 是 X* 家族里唯一"小树/子树"语义的类(嵌入宿主窗口的自足对话框,相对宿主的主树);
  "Baby = 主树的孩子"的读法与 `CreateXBaby` 从 XProvider(宿主侧方向盘)生出的方向一致;
- 存在 TouchXBaby(34 方法,**全部内部符号、零导出**,vftable 形态
  `6BTouchHWNDElement@1@@` 等)——触控时代的内部克隆,Baby 家族确有繁殖痕迹;
- 对称命名证据:IXElementCP / IXProviderCP / IXBaby 的"CP/接口对"结构说明 X* 是一组
  有协议设计感的外部 API,**X 大概率是"external/cross-HWND"前缀**(XHost/XElement/XProvider
  三个名字都能自然代入),而 **Baby 的具体词源无任何符号/字符串/文档证据**。

【以上全部为【猜想】级,按证据分级规范以问题形式收尾:XBaby 的"Baby"是"主树的孩子树",
还是某个内部代号的遗迹?】

---

## 4. 装配全景:一次跨 HWND 对话的完整流程

把四类串起来(宿主 = 任何想用 DirectUI 做弹窗的 Win32 程序):

```
宿主进程                                    dui70 内部
────────                                    ─────────
InitProcessPriv / InitThread
RegisterAllControls ────────────────────→ RegisterXControls(RVA 0x8880)
                                             ├─ XElement::Register(写 s_pClassInfo@XElement @0x180184B50)
                                             └─ XBaby 注册(共享 ClassInfo 工厂 @0x2F80,
                                                写 s_pClassInfo@XBaby @0x180184B40)
                                                [类名宽字符串 L"XBaby" @0x18011F5F8,
                                                 L"XElement" @0x180122FD8]

XProvider::Create(...) ← 或 C 包装 CreateDUIWrapper/Ex/FromResource(导出 4243/4244/4245)
  │
  ├─ CreateDUI(pCP, &hwnd) ────────────→ XHost::Create → IXElementCP 协商 → XHost::Host
  │                                        (宿主拿到 hwnd,自己 ShowWindow)
  ├─ CreateParser(&parser) ────────────→ parser 装载宿主提供的 UIFILE
  ├─ CreateXBaby(...) ──────────────────→ XBaby::Create(new 336B + Initialize)
  │                                        返回 IXBaby* 接口
  │
  ├─ SetFocus / Navigate / ClickDefaultButton / SetParameter(GUID,...)
  │    ……对话框生命周期内持续驱动……
  └─ Destroy ───────────────────────────→ XHost::Destroy / XBaby 析构
```

【实锤:CreateDUI/CreateXBaby/Host 的内部已逐段反汇编(§2);RegisterXControls 的两个
Register 调用与 ClassInfo 写入已实锤;CreateDUIWrapper 三兄弟的包装关系已实锤;
完整时序 = 各实锤段的组合,属【强推】】

给开发者的提示:如果只是想在普通应用里弹一个 DirectUI 对话框,更平的路是
`CreateDUIWrapperFromResource`(一个调用同时完成 XResourceProvider + XProvider 装配),
或干脆走 XML 侧的 `DialogElement`(不需要跨 HWND 协议时)。

---

## 5. X* 家族速查表

| 问题 | 答案 | 证据级 |
|---|---|---|
| X 是什么意思 | external/cross-HWND(家族全体围绕 HWND 边界) | 强推(命名模式) |
| XBaby 是什么 | 宿主窗口里嵌入的自足对话框树,经 IXBaby 接口暴露 | 实锤(方法面+继承) |
| Baby 词源 | 未知;候选"主树的孩子树" | 猜想 |
| 谁该用 XProvider | 想在自己的 HWND 里装 DirectUI 树、并用方向盘 API 驱动的外部宿主 | 实锤(方法面) |
| TaskDialog 用的是它吗 | 内容树在 dui70 生态内构建成立;但"经 XProvider::CreateDUI"无调用证据;确证的是 AeroWizard/属性页路径(TaskPage::DUICreatePropertySheetPage → CreateDUIWrapperEx) | 混合(见 §3) |
| TouchXBaby 是什么 | XBaby 的触控时代内部克隆,34 方法零导出 | 实锤(符号表) |
| IXElementCP 的 CP | Creation Provider(创建协商接口:XProvider::CreateDUI 经它向宿主要元素/HWND) | 强推(用法形态) |

---

## 6. 未知问题清单(诚实边界)

1. **TaskDialog 的构建入口**:comdlg32 只导入 5 个初始化 C API,树必在 dui70 内建;
   但本轮未找到"TaskDialogIndirect → dui70 内部某入口"的直接调用链。
   候选:GetParserCommon 路径的进一步调用者,或 CCAPI 层某个未排查的导出。
2. **CreateDUI 中段(②)的虚方法序列**:IXElementCP 的 vtable 槽位→方法名映射未解码
   (接口无成员符号,只有 vftable 导出),各槽调用次序待运行时验证。
3. **XBaby 的 336 字节字段布局**未逐字节还原(三基类子对象偏移可推,业务字段未标定)。
4. **XHost 与 NativeHWNDHost/TaskPage 的分工边界**:XHost(自由窗口壳)vs
   TaskPage(直接吐 HPROPSHEETPAGE 给 comctl32 的属性页壳)分工清楚,但
   XHost 与 NativeHWNDHost 是否有 Composition 关系未验证。
5. XBaby 的 `GetElementProviderImpl(InvokeHelper*, ElementProvider**)` 把无障碍桥
   (`04-uia-accessible-bridge.md`/`05-uia-pattern-providers.md`/`06-uia-invoke-helper-cross-thread.md` 的 UIA 线)接进对话框——跨 HWND 场景下 UIA 树如何拼合,未展开。
6. IXBaby 接口的完整方法表(符号表只有返回类型处的引用,接口本体无符号)。

## 证据索引

- 符号:`pinned/symbols.json`(XHost 13/XElement 33/XProvider 29/XBaby 41/XResourceProvider 12/
  TouchXBaby 34/TouchXProvider 5/XDummyProvider 4;IXElementCP/IXProviderCP 伪类各 6)
- 继承:`pinned/classes.json`(XBaby/XElement/XProvider/DialogElement 条目)
- vftable 形态:导出表(XBaby 4 形态、XElement 2 形态、XProvider 裸 6B@);
  own-vptr ABI 细节见 width-expansion.md §2.1
- disasm:XProvider::CreateDUI @0x81D00(L163019);XHost::Host @0x81ED0(L163167);
  XBaby::Create @0x89B30(L175259);CreateDUIWrapperEx 调用者(L291975/L296928);
  RegisterXControls @0x8880(L9414);XBaby ClassInfo 工厂 @0x2F80(L2710-2728,写 0x180184B40);
  XElement::Register @0x7AB30(写 0x180184B50,L152679-152707)
- comdlg32 导入:dumpbin /imports(本机 10.0.26100),DUI70 段 5 符号
- 字符串:L"XBaby" @0x18011F5F8、L"XElement" @0x180122FD8(UTF-16)
- 引用报告:duser-landscape.md §3.3(UIFILE 1010/GetParserCommon)、width-expansion.md
  §2.1(own-vftable 工具链差异)、outline §F1(任务来源;其 removed_symbols 断言因
  pinned 数据无此键而未采用,见 §2.4 的诚实说明)
