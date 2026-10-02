# DirectUI

`dui70.dll` 是 Windows 自带的 DirectUI 实现——UxTheme 时代的原生 UI 框架，随系统
ship、被 explorer 等大量组件使用。本仓库把它的**完整导出面**做成可编译、可复现、
可验证的 C++ 绑定，并附一份基于真实系统资源的 duixml 语料与逆向教程。

目标是**二进制级诚实**：结论有证据等级（实锤/强推/猜想）、生成物可 byte 级复现、
换系统版本时的 ABI 变化在一个 diff 里可见。

## 工作方式

两段式流水线，中间用 `pinned/` 冻结契约：

```
            ┌── 第一段：确定性、纯 Python、无工具链依赖 ──┐
 pinned/  ──┤  emit_def.py  ──► DirectUI/dui70.def         ├──►  DirectUI/
 (合同)     │  emit_headers.py ─► DirectUI/include/*.h     │     (golden, 入库)
            │  emit_stub.py   ─► DirectUI/src/*.cpp        │
            └──────────────────────────────────────────────┘
                         CI 的 golden job 只测这一段

            ┌── 第二段：需要 MSVC + dumpbin/llvm-pdbutil ──┐
 DLL+PDB  ──┤  extract.py → model.py  ──► pinned/ 刷新     │
            └──────────────────────────────────────────────┘
                       只在换版本时跑，用 manifest 指纹锁定
```

第一段是**纯函数**：`regen.py` 从 `pinned/` 重产 `DirectUI/`，产物 byte 级确定，
所以在任意平台都能当 golden test 跑。第二段依赖工具链与网络，只在刷新时执行。

```
CI 四个 job（.github/workflows/pipeline.yml）
  golden  G1 输入完整性 + G2 regen 后 git diff 必须为空   ← 不需要 MSVC
  abi     G3/G4/G5 双向类相等、modname/extern-C 保真、头文件编译
  smoke   run.ps1 端到端：建 lib → 编 UITest → 起窗口并断言 dui70.dll 来自 System32
  repro   R1 从 msdl 重下 DLL+PDB → R2 重推 pinned/ → R3 符号逐字节比对（PR/手动）
```

## 仓库结构

| 路径 | 是什么 |
|---|---|
| `pinned/` | **契约输入（冻结）**：`manifest.json` 源指纹、`exports.json` 导出表、`symbols.json` 符号模型、`classes.json` 195 类 + 继承表 |
| `DirectUI/` | **生成物**（入库的 golden）：聚合头 `DirectUI.h`、逐类头、`dui70.def`（4321 条导出）、ABI 自证用 stub 源码。**不要手改**，改生成器后 `regen.py` |
| `tools/dui-pipeline/` | 生成器 + 门禁：`regen.py`、`extract.py`、`model.py`、`verify.py`、`ci.ps1`、`repro.ps1`、`run.ps1` |
| `UITest/` | 可读的 DirectUI 使用示范（客户区 listener ×2、反射 dump、动画系统），也是 smoke 的被测程序 |
| `docs/duixml-corpus/` | **149 份真实系统 UIFILE 资源**的全量语料：候选 111 个 dui70/duser 消费者（含本体），其中 64 个含 UIFILE；含 15 份 duib 二进制资源的解码还原 |
| `docs/duixml-classinfo/` | 89 份运行期反射 dump（dui70 自报的类/属性/枚举表，动画枚举等结论的一手来源）+ `Layouts.txt`（`.rdata` 布局名数组，非反射 dump） |
| `docs/duixml-tutorials/` | 24 篇逆向教程，全部结论按证据分级 |
| `tools/dui-pipeline/INTERFACE.md` | **流水线唯一权威契约**（字段语义、门禁层次、刷新流程） |
| `tools/dui-pipeline/CI.md` | CI 细节：各 job 的依赖、失败模式、已知边界 |

## 快速开始

```powershell
git clone https://github.com/seven-mile/dui70
cd dui70

# 只用生成的绑定（不需要跑流水线）
lib.exe /def:DirectUI\dui70.def /machine:x64 /out:dui70.lib
# 然后 #include <DirectUI.h>，编译加 /I DirectUI\include /Zc:wchar_t-

# 跑全套门禁（golden 不需要 MSVC；abi/smoke 需要）
pwsh -File tools/dui-pipeline/ci.ps1

# 只想验第一段（秒级、任意平台）
pwsh -File tools/dui-pipeline/ci.ps1 -GoldenOnly

# 从微软符号服务器重下 DLL+PDB，重推 pinned/ 并逐字节比对
pwsh -File tools/dui-pipeline/repro.ps1

# 端到端：重产 → 建 lib → 编 UITest → 起窗口断言
pwsh -File tools/dui-pipeline/run.ps1
```

运行时加载的是**系统里真实的 `dui70.dll`**（需要 Windows 11 26100+，或 dui70.dll
与 `pinned/manifest.json` 指纹相符的版本）。

想读而不是跑，从 [`docs/duixml-tutorials/README.md`](docs/duixml-tutorials/README.md)
开始——24 篇按"解析 → 绘制 → 交互 → 家族 → 实践"分组，每篇标注证据等级。

## 背景

这一版是从早期手写绑定演进来的，脉络值得记一笔：

- 早期是**手写**的 `DirectUI` 项目（101 个头文件 + 万行 stub + vcxproj），靠人读
  反汇编补接口。它证明了可行性，但无法证明**完整性**——漏了哪个导出没人知道。
- 现在 `pinned/` 接管了整个面：导出表直接来自 DLL，符号模型来自 PDB，生成物可
  byte 级复现。"覆盖了多少"变成一个可计算的数，而不是一句自述。
- 早期探索留下的结论仍然有效，它们解释了这套 API 的形状：
  - `DirectUI::Value` 的类型系统是整棵树的地基（教程 02 篇）。
  - `IClassInfo`/`PropertyInfo`/`EnumMap` 构成的**运行期反射**是 dui70 最有价值的
    特性之一——本仓库直接消费它：`docs/duixml-classinfo/` 就是这套反射的 dump，
    而 `DuiEnums.h` 的枚举表也来自它（dui70 自报，不是猜的）。
  - 事件系统只要把 `IElementListener` 的接口对上就能跑；`InputEvent` 覆盖了主要
    交互，普通 `Event` 按消息种类细分。
  - 布局：`BorderLayout` 已足够支撑大部分自适应布局；`gtc`/`gtf` 等 duixml 指令
    实际是 uxtheme 的 API。
  - 动画：插值方法多但可动画属性少，位域取值见 `DirectUI/include/DuiEnums.h`。
  - 自制控件可以自己实现 `IClassInfo` 并重写 `Element` 虚方法，此时既能子类化
    `WndProc`，也能用 `Host` 套娃做 UserControl。
  - 兼容性：dui70 作为随系统 ship 的库（还有 ieui 等 fork），旧接口从版本 8 到
    14 仍可用。
- 被淘汰的中间产物：`demangler/`（早期手工符号解码工具，已被 `llvm-undname` +
  流水线取代）、`docs/duixml/`（6 份手工提取样例，已归并/清理，见语料 README）。

UxTheme 的时代还没开始就已经结束，Qt、yue 和 dui70 是三个仅存的火种。
