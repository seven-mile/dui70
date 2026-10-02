# 教程 16:一个 DirectUI 程序的诞生 —— 启动序列与线程模型

> 系列教程第 16 篇。读者假设:熟悉 Win32(GUI 消息循环、HWND、COM),没读过 DirectUI 内部。
> 证据分级:**【实锤】** = 反汇编指令/语料 XML/可运行样本直接验证;**【强推】** = 符号名+结构强推断(附推断链);**【猜想】** = 待验证问题。
> 本文所有反汇编行号指 `dui70-full-disasm.txt`(343968 行);可运行样本为 `UITest/UITest.cpp`。

---

## 0. 全景图:三层结构里你站在哪

一个 DirectUI 程序从开机到出画面,跨三层:

```
┌─ 你的代码 (C++ 宿主:bootux.dll / fvecpl.dll / 你的 exe)
│    InitProcessPriv → InitThread → RegisterAllControls → NativeHWNDHost::Create
│    → DUIXmlParser::SetXMLFromResource → CreateElement → EndDefer → Host → Show
├─ 声明层 dui70.dll: DUIXmlParser + ClassInfo 注册表 + Element 树/属性/事件
└─ 引擎层 duser.dll: gadget 树(HGADGET)/ EventMsg 路由 / 每线程合成上下文
```

关键认知:**dui70 不是自绘控件库,是"行为库 + HWND 寄生树"**。Element 树依附在一个真实 HWND(HWNDElement)之下;输入、焦点、系统消息经 Win32 消息进入,再被翻译成框架事件(`17-events.md` 主题)。渲染则下沉到 duser 的 gadget 世界。

dui70 与 duser 之间唯一的官方通道是一小组导出函数(经 dui70 的 IAT 调用),本篇会遇到的:`InitGadgets`(创建线程 gadget 根)与 `DUserSendEvent/DUserPostEvent`(`17-events.md`)。完整 ABI 分析见 `duser-deep-dive.md` §1-§2,本文只引用不重推。

---

## 1. 标准启动序列:UITest.cpp 逐行

这是全仓库唯一可运行的完整样本(`UITest/UITest.cpp:480-541`),也是微软自家宿主(bootux 等)的标准姿势。【实锤】

```cpp
// UITest.cpp WinMain —— 行号为原文行号
480:  CoInitializeEx(...)                      // 宿主自己的事(COINIT_APARTMENTTHREADED)
487:  HookDUserExports();                      // 可选:IAT 探针,必须在 InitProcessPriv 之前
489:  InitProcessPriv(14, NULL, 0, true);      // 进程一次:TLS 槽 + 全局状态
490:  InitThread(2);                           // 线程一次:每线程上下文 + gadget 根
494:  RegisterAllControls();                   // 级联注册 166 个元素类
499:  NativeHWNDHost::Create(...);             // 顶层 HWND 壳(真实窗口)
508:  DUIXmlParser::Create(&pParser, ...);     // 解析器
521:  pParser->SetXMLFromResource(...);        // 装载 UIFILE XML 资源
527:  HWNDElement::Create(pwnd->GetHWND(), true, 0,
                          NULL, &defer_key, &hwnd_element);
                                              // HWND → 元素树根;输出 defer_key
532:  pParser->CreateElement(L"WizardMain", hwnd_element,
                              NULL, NULL, &pWizardMain);
                                              // 按 resid 实例化子树
537:  pWizardMain->SetVisible(true);
538:  pWizardMain->EndDefer(defer_key);        // 构建事务提交(见 §3)
539:  pwnd->Host(pWizardMain);                 // 元素树挂到宿主窗口
541:  pwnd->ShowWindow(SW_SHOW);
      ... StartMessagePump();                 // GetMessage/Translate/Dispatch
689:  UnInitProcessPriv(NULL);                 // 退出清理
```

顺序不可随意调换的三条硬约束(后文逐条展开):

1. **InitProcessPriv → InitThread**:后者读前者分配的 TLS 槽;
2. **RegisterAllControls 在 CreateElement 之前**:解析器按类名查 ClassInfo 注册表;
3. **HWNDElement::Create → CreateElement → EndDefer**:defer 事务包裹整个构建期。

---

## 2. 两级初始化:进程一次,线程一次

### 2.1 InitProcessPriv:TLS 槽与全局状态【实锤】

`InitProcessPriv(14, NULL, 0, true)` 的真身在内部 worker(RVA 0x180009720,disasm 行 10641 起):

```
TlsAlloc()                          ← 经 IAT 0x1801197e0
g_dwElSlot = 结果                    ← 存入全局 0x180181de4
[0x180181de8] = 1                   ← 已初始化标志
[0x180181dec] = 0x47                ← 语义未知(见 §6 未知清单)
InitializeCriticalSection(&...)     ← IAT 0x1801198f0,保护 ClassInfo 注册表
```

细节:

- **幂等靠引用计数**:重复调用 InitProcessPriv 会在 `0x18018365c` 上 `lock xaddl` 递增,不会重复 TlsAlloc。这意味着"进程一次"其实是"配对一次"——`UnInitProcessPriv` 递减,归零才真清理。
- `FontCache::InitProcess` 会**再** TlsAlloc 一个独立槽(disasm 行 9557):字体缓存与元素上下文是两条 TLS 线。
- 参数 `14` 的含义未还原(可能是版本/能力位掩码), UITest 用 14、`true` 两个实参与符号签名 `(int, void*, DWORD, bool)` 吻合。

### 2.2 InitThread:每线程一个 gadget 世界【实锤】

`InitThread(2)`(RVA 0x43040,disasm 行 79529-79622)是理解 DirectUI 线程模型的钥匙:

```
slot = g_dwElSlot                    ← 读 InitProcessPriv 存的槽号
ctx  = TlsGetValue(slot)             ← 已有则直接返回(幂等)
ctx  = 分配 0x1F0 字节               ← 每线程上下文
InitGadgets(&{0x18, flags, word})    ← duser IAT 0x180195240,创建该线程 gadget 根
mode = 按 flags 位选择               ← 存 ctx+0x1c
ctx+0x58 = InitGadgets 出参 bool      ← 语义未明
```

**flags 模式位**(disasm 精读结论):

| flags 位 | mode(存 ctx+0x1c) | 选择的鼠标消息映射表(.rdata) |
|---|---|---|
| bit 0x40000 | 1 | 0x180120400 |
| bit 0x20000 | 3 | 0x1801268a0 |
| bit 0x10000 | 2 | 0x180120418 |
| 其余(含 UITest 的 2) | 4 | 0x1801268b0 |

四张表内容是鼠标消息 id → 过滤行为的映射(表区相邻字符串 "Desktop"/"Primary"/"Unavailable" 是 duser 侧标识)。**这个 mode 决定了本线程的鼠标输入以什么"手势方言"进入框架**——它是后面`17-events.md` 输入事件管线的第一道闸门。

另一处调用样本:`CreateTouchTooltip` 内部以 `(flag<<16)|2` 调 InitThread(disasm 行 78574)——**上位 16 位是 mode 位,低位是另一组语义**(UITest 的 2 与 Tooltip 的低位 2 一致,推测低位是"输入可用"类基础开关)。【强推,推断链:两处调用的位域拆分】

### 2.3 心智模型:线程即世界

> **每线程一个 gadget 世界。** Element 树、它的 gadget 镜像、输入过滤表、字体缓存,全部归创建它们的线程私有。跨线程访问框架不提供封送——唯一已知的显式跨线程通道是 UIA 的 InvokeHelper 隐藏窗口(§8 无障碍主题,超出本篇)。

推断依据【强推】:0x1F0 上下文与 gadget 根都挂 TLS;`StartMessagePump`(RVA 0x72950)就是裸的 `GetMessageW/TranslateMessage/DispatchMessageW` 循环,输入路由发生在 duser 对宿主 HWND 的子类化里——哪个线程的 HWND,哪个线程的世界。反例未发现:整个 dui70 没有跨线程投递 Element 操作的 API 符号。

实践含义:多窗口多线程 DUI(同进程)时,每个线程各自 InitThread,各自一套 0x1F0 上下文;但 **ClassInfo 注册表是进程共享的**(InitProcessPriv 的临界区保护的就是它——EnterCriticalSection/LeaveCriticalSection IAT 0x180119988/980,注册表写路径全程持锁),所以 RegisterAllControls 只需一个线程调一次,后续线程直接受益。注册表共享本身是【强推】(临界区+全局变量的存在强烈暗示,但未做多线程运行实验)。

---

## 3. defer 事务:构建期对用户不可见

### 3.1 defer_key 的生命周期【实锤,本次新升级】

`HWNDElement::Create(..., &defer_key, ...)` 输出一个事务句柄。反汇编还原的真实机制(Element::StartDefer@0x30FF0 / EndDefer@0x263D0 / GetDeferObject@0x3D220):

**StartDefer 内部**(以 HWNDElement::Create 的内部调用为例):

```
1. 沿 0x48(parent)链爬到根元素
2. 若根的 +0x38(DeferCycle*)为空 → DeferCycle::Create(0x47500) 新建事务对象
3. 事务对象 +0x38 引用计数 +1;  +0x60(嵌套深度) +1
4. 写入调用者的 defer_key: 正常路径 0xABCDEF42
```

**EndDefer 内部**:

```
1. defer_key == 0xDEAD1234? → 无效 key,直接返回(错误路径标记)
2. 事务对象 +0x60(嵌套深度)递减;不为 0 → 还在嵌套内,返回
3. 归零 → DeferCycle::_EndDefer(0x391A0):
   a. 事务 +0x58(世代号)递增,+0x3c 置"正在提交"
   b. 遍历登记的结构/几何/可见性变更,逐个提交
   c. 根元素 +0x38 清 NULL → 事务关闭
```

两个 sentinel 值直接写进 defer_key:`0xABCDEF42`(有效)/`0xDEAD1234`(无效)。【实锤,反汇编常量】这就是"事务句柄"的全部魔法——一个可校验的 cookie,配根元素上的 DeferCycle 引用。

**嵌套语义**:StartDefer 可以嵌套(BaseScrollViewer::OnInput 内部就自行 Start/EndDefer 包裹滚动事务,disasm 行 56382),只有最外层 EndDefer 真正提交。事务对象 +0x60 是嵌套计数,+0x38 是外部引用计数——两者分离说明 DeferCycle 对象本身可以在事务结束后被复用持有。

**提交时做什么**:DeferCycle::_EndDefer 遍历两张登记表(事务对象 +0x28/+0x30 链),提交期间 `0x180182e80` 全局的 bit0 被检查(疑似"批处理进行中"标志,提交完清位)。具体逐项提交顺序(布局→可见性→渲染?)未完整还原,见 §6 未知。

### 3.2 使用者视角

把 §1 的序列翻译成事务语义:

```
HWNDElement::Create  → 事务开启(defer_key 发放)
    CreateElement    →   子树构建(所有中间态不可见)
    SetVisible       →   可见性变更登记(不立即生效)
EndDefer(defer_key)  → 事务提交(布局+显示一次完成)
Host + ShowWindow    → 真正上屏
```

**为什么"中间态不可见"是【实锤】**:不是猜的——构建期所有 InvalidateGadget(失效标记)都登记在 DeferCycle 里而非直接发给 duser。运行时探针(duser-call-counts,UITest DUser probe)的数字佐证:树构建完成后、消息泵启动前,`InvalidateGadget` 计数为 26 次(登记),而 `DUserSendEvent` 为 0——真正的事件流要等泵转起来。

### 3.3 运行时证据:每个阶段 duser 被调了什么【实锤】

UITest 的 IAT 探针(`HookDUserExports`,汇编 stub 计数器,ABI 安全转发)在六个时间点采样:

| 阶段 | InitGadgets | CreateGadget | SetGadgetStyle | SetGadgetMessageFilter | InvalidateGadget | DUserSendEvent |
|---|---|---|---|---|---|---|
| 注册类后 | 1 | 0 | 0 | 0 | 0 | 0 |
| NativeHWNDHost::Create 后 | 1 | 0 | 0 | 0 | 0 | 0 |
| **SetXMLFromResource 后** | **2** | 0 | 0 | 0 | 0 | 0 |
| HWNDElement::Create 后 | 2 | 1 | 1 | 1 | 0 | 0 |
| 树构建完、泵前 | 3 | 27 | 199 | 38 | 26 | 0 |
| 泵退出后 | 3 | 27 | 205 | 38 | 580 | **161** |

(节选;完整 16 列见 `.local/audit/duser-call-counts.txt`)

读法:

- **InitGadgets 出现 3 次而非 1 次**:InitThread 之外,parser/HWNDElement 内部还有两处按需初始化(惰性"确保线程世界存在"模式);同一 TLS 幂等,所以无害。
- **27 个 gadget 对 27 个元素**:CreateElement 生成的每个元素在 duser 侧各有一个 gadget 镜像。元素树与 gadget 树是**两棵平行树**——这是`17-events.md` 事件路由的物理基础。
- **DUserSendEvent 161 次全部发生在泵期**:构建期零事件。鼠标移动/点击经 duser 翻译成 161 次 EventMsg 回调,dui70 在 `_DisplayNodeCallback`(0x18002EDB0)里分发(`17-events.md` 详述)。

---

## 4. RegisterAllControls:166 个类的级联注册【实锤】

`RegisterAllControls`(RVA 0x180008c60,disasm 行 9782-9807)是一串级联:

```
RegisterBaseControls → RegisterStandardControls → RegisterExtendedControls
→ RegisterMacroControls → RegisterBrowserControls → RegisterXControls
→ RegisterMiscControls → RegisterCommonControls
```

每级把自己命名空间的类 `ClassInfo::Register()` 进全局注册表(带名→IClassInfo 映射,解析器按 XML 标签查这张表)。166 个类是数出来的(符号表 `Register` 静态方法计数 + 类继承清单 `classinfo-inheritance.txt` 交叉)。

宿主可以注册自己的类(bootux 的 BUX* 家族、DeviceElementSource 的自定义标签都这么来的)——`CClassFactory::Register` 是公开路径,UITest 甚至用 Detours 挂了它来 dump 每个类的 PropertyInfo 表(`HookClassFactoryRegister`,UITest.cpp:192-209)。**这个 hook 是本系列教程属性表(`18-properties-and-lifecycle.md`)的数据来源之一**。

---

## 5. 常见坑(启动序列)

1. **CoInitializeEx 的模型**:DirectUI 样本用 APARTMENTTHREADED。STA 意味着消息泵线程就是所有 COM 对象的 home 线程——与 §2.3 "线程即世界"一致。
2. **InitThread 的 flags**:UITest 传 2(裸值)。若你的窗口要在触控/精确笔环境,参考 CreateTouchTooltip 的 `(flag<<16)|2` 组合——mode 位影响鼠标过滤表(§2.2)。传错不一定崩,但输入行为(比如右键语义)会不对。
3. **先 parser 后 XML**:SetXMLFromResource 只是装载字符串;元素实例化在 CreateElement。XML 里 `<style>`/`<macro>` 定义在这个阶段进入 parser 的内存结构(样式表持续生效、宏延迟展开——`09-stylesheet-three-layers.md` 主题,不在本篇)。
4. **EndDefer 的 key 一次性**:EndDefer 后 defer_key 对应的事务已关闭(根元素 +0x38 清 NULL)。同一个 key 二次 EndDefer 走 0xDEAD1234 拒绝路径。新一轮批量要重新 StartDefer 取新 key。【实锤,反汇编;复用旧 key 的行为未单独实验】
5. **退出**:UnInitProcessPriv(NULL) 传 NULL 与样本一致;内部按引用计数递减(§2.1),别的模块还持有初始化时不会真清理——DLL 卸载顺序敏感的宿主要注意。

---

## 6. 未解问题(诚实清单)

| # | 问题 | 现状 | 可能的验证路径 |
|---|---|---|---|
| 1 | 0x1F0 每线程上下文除 +0x1c(mode)/+0x58(bool)外的字段布局 | 未知 | x64dbg 硬件断点观察 ctx 各字段读写 |
| 2 | InitProcessPriv 写入的 0x47 全局(0x180181dec)语义 | 未知;同函数还写 1(已初始化标志),0x47 疑似槽数或版本 | 与 duser InitGadgets 入参对照;交叉引用该全局的读取者 |
| 3 | InitThread 低位 flags(值为 2)的语义 | 只有"两处调用都是 2"的归纳【强推:基础输入开关】 | 位拆开试(1/4/8)观察 InitGadgets 入参第三字段差异 |
| 4 | ctx+0x58(InitGadgets 出参 bool)语义 | 未知 | 断点看谁读它 |
| 5 | DeferCycle 提交项的完整顺序(布局/可见性/渲染谁先) | 只还原到"两张登记表遍历" | 继续读 _EndDefer 循环体(0x1800391A0 后半) |
| 6 | 多线程共享 ClassInfo 注册表 | 临界区存在【强推】 | 双线程 DUI 窗口实验 + 注册表计数 |
| 7 | DUserSendEvent 与 DUserPostEvent 的分工比例(161:1 是鼠标驱动样本) | 泵期统计已有,按事件类型分解未做 | 探针按 EventMsg.msg 分桶 |

---

## 7. 小结与下一篇

- 启动 = **两级初始化(进程/线程)+ 类注册 + HWND 壳 + XML 实例化 + defer 事务提交**。
- 线程模型 = **每线程一个 gadget 世界**,ClassInfo 注册表进程共享。
- defer_key = **根元素上的 DeferCycle 引用 + 0xABCDEF42 cookie**,构建期中间态对用户不可见。

启动完成后,程序进入消息泵。下一件事就是:鼠标点下去之后发生了什么?——`17-events.md`《事件系统:从 Win32 消息到 UID 比较》。

---

## 附:证据索引

| 结论 | 证据 | 位置 |
|---|---|---|
| 启动序列 | UITest.cpp 可运行样本 | UITest/UITest.cpp:480-541, 689 |
| InitProcessPriv 内部(TlsAlloc/0x47/临界区/引用计数) | 反汇编 | dui70-full-disasm.txt 行 10641-10725 |
| FontCache 独立 TLS | 反汇编 | 行 9557 |
| InitThread 0x1F0 ctx/InitGadgets/4 mode 表 | 反汇编 | 行 79529-79622 |
| CreateTouchTooltip 的 (flag<<16)\|2 | 反汇编 | 行 78574 |
| RegisterAllControls 级联 | 反汇编 | 行 9782-9807 |
| StartDefer/EndDefer/DeferCycle 机制(含 0xABCDEF42/0xDEAD1234) | 反汇编 | Element::StartDefer@0x30FF0, EndDefer@0x263D0, GetDeferObject@0x3D220, DeferCycle::Create@0x47500, _EndDefer@0x391A0 |
| 构建期零事件/27 gadget/161 SendEvent | 运行时探针 | .local/audit/duser-call-counts.txt |
| 166 类注册表 | 符号+继承清单 | pinned/symbols.json + .local/build/p2-text/classinfo-inheritance.txt |
| EventMsg ABI(引用) | 既有报告 | .local/audit/duser-deep-dive.md §1 |
