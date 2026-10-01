# dui-pipeline CI —— 门禁语义与排障

> 本文回答三件事：**怎么跑**、**每个门禁在守什么**、**失败时怎么读**。
> 工具本身在 `tools/dui-pipeline/ci.ps1` + `ci_checks.py`；
> 第二阶段的来源复现门禁在 `repro.ps1` + `repro.py`（见 §7）。

## 0. 一句话

把"重跑 `regen.py` → `git diff DirectUI/ == 0`"这条**口头纪律**变成一条可执行门禁：

```powershell
pwsh -File tools\dui-pipeline\ci.ps1
```

退出码 `0` = 全绿；非 0 = **第一个失败的门禁**，stderr 给出
`GATE <id>: FAIL  expected=…  actual=…`。

---

## 1. 怎么跑

### 1.1 全量（推荐，默认）

```powershell
pwsh -File tools\dui-pipeline\ci.ps1
```

无参数即可跑。Python / MSVC / Windows SDK 全部自动探测
（见 §4），探测不到会明确报缺哪一项、怎么覆盖。

### 1.2 快速子集（无需 MSVC，约 2 秒）

```powershell
pwsh -File tools\dui-pipeline\ci.ps1 -GoldenOnly
```

只跑 G1 + G2。适合：改生成器时快速自检、Linux/无编译器环境、
pre-commit 钩子。

### 1.3 其他开关

| 开关 | 作用 |
|---|---|
| `-SelfTest` | 只验证**门禁逻辑本身**能否测出损坏（含篡改/新增/删除/删类四种），不跑门禁 |
| `-SkipAbiCheck` | 跳过 G4 |
| `-SkipHeaderCheck` | 跳过 G5 |
| `-HeaderSample N` | 抽样头文件数（默认 12） |
| `-SecondsBudget N` | 总时长预算秒数（默认 600） |
| `-AllowDirty` | 跳过 G2 的"工作树必须干净"前置检查（**有风险，见 §3.2**） |
| `-Python` / `-VcRoot` / `-SdkVersion` | 显式指定工具链 |

### 1.5 repro（第二阶段：`pinned/` 的来源）

```powershell
pwsh -File tools\dui-pipeline\repro.ps1
```

从 msdl 重下载 DLL+PDB → 硬校验 sha256 → 隔离目录重推 `pinned/` → **全量逐字节**断言。
需要联网、`dumpbin`、`llvm-pdbutil`，约 27 秒。语义见 **§7**。

### 1.4 单独用某个检查

`ci_checks.py` 的每个子命令都能独立跑，便于定位：

```powershell
python tools\dui-pipeline\ci_checks.py hash      # G1
python tools\dui-pipeline\ci_checks.py struct    # G3
python tools\dui-pipeline\ci_checks.py totals    # 看从 pinned/ 推导出的期望值
python tools\dui-pipeline\ci_checks.py headers --help   # G5
```

---

## 2. 门禁清单与语义

执行顺序固定，**第一处失败即停**（后续门禁不再跑）。

| ID | 门禁 | 守什么 | 期望 | 依赖 |
|---|---|---|---|---|
| **G1** | 输入完整性 | `pinned/` 是冻结契约；任何未声明的改动都必须显式重新 pin | 每个文件 sha256 == `tools/dui-pipeline/pinned.sha256` | 无 |
| **G2** | golden 再生 | `pinned/ → DirectUI/` 必须**逐字节可复现** | `regen.py` 后 `git diff` 为空且无新增未跟踪文件 | 无 |
| **G3** | 结构性断言 | 生成树与 `classes.json` **精确一致** | 类数 + 每类产物双向相等 | 无 |
| **G4** | ABI 保真 | 编译出的装饰名 vs `pinned/` 导出表 | modname N/N、extern-C N/N | MSVC |
| **G5** | 头文件可编译 | 抽样头文件语法自洽 | `cl /Zs` rc=0 | MSVC |
| **GB** | 时长预算 | 门禁不能悄悄变慢/变不稳 | 全链 < `-SecondsBudget`（默认 600s） | 无 |

实测本机全量约 **60 秒**（G4 编译 190 个 TU 占 54s）。

第二阶段的 **repro** 门禁（R1–R3）独立运行、不复用上表编号，语义见 §7。

### 2.1 G1 —— 输入完整性

`pinned/` 是流水线的**唯一契约输入**。G1 用 sha256 清单锁定它，
使"本次生成物变了"与"输入变了"两个原因**不可能混淆** —— 这正是
`model.py` 覆写 `classes.json` 事故能造成混乱的根源。

```powershell
# 有意重新 pin 时（务必与产物同 commit）：
python tools\dui-pipeline\ci_checks.py hash --write
```

**哈希口径：LF 规范化**（`\r\n` → `\n`）。原因见 §3.3 —— 这是本 CI 交付前
实测发现的一个真实坑。

### 2.2 G2 —— golden 再生（本 CI 的核心）

比原来的 `git diff` 多了两层保护：

1. **前置脏树检查**：`regen.py` 会**整体覆写** `DirectUI/`。
   若工作树里有**未提交**的手改，regen 会把它悄悄冲掉，随后 `git diff`
   报告"干净" —— 一个**假绿**。前置检查专门堵这个洞。
2. **未跟踪文件检查**：裸 `git diff` **看不见新增文件**。
   若生成器新增了一个 `.h`，`git diff` 仍为空。G2 额外用
   `git ls-files --others` 抓这种情况。

已提交的手改仍然由 `git diff` 抓（regen 复现的是生成器输出，HEAD 里是手改）。

### 2.3 G3 —— 结构性断言

**期望值一律从 `pinned/classes.json` 读取，绝不硬编码**（`195` 只是当前值）。
审核时用的指标：

- `standalone` 类：各需 1 个 `.h` + 1 个 `.cpp`
- `nested` 类（`ACCESSIBLEROLE` 内嵌结构、`FunctionDefinition<T>` 模板特化）：
  只在宿主 TU 内生成，不单独出文件
- 关系是**双向精确相等**：既查"缺"，也查"多"

> 为什么必须双向：早期实现只查"contract 里的类是否都有产物"（子集检查），
> 结果 `classes.json` 被砍到 12 类时**照样通过** —— 正是要防的那起事故。
> 现改为精确相等后，砍到 12 类会立刻报
> `178 header(s) present but not implied by classes.json`。
> （`docs` 无此记录，这是负向测试实测出来的，见 §5。）

### 2.4 G4 —— ABI 保真

调 `verify_codegen.py` 编译全部 stub TU，比对装饰名。两个指标的**期望值从
`pinned/` 现算**，不是写死的常量：

```powershell
python tools\dui-pipeline\ci_checks.py totals --json
# {"modname_total": 4227, "capi_total": 86, "class_count": 195, ...}
```

- `modname_total` = Σ(每个 `classes.json` 类名下 `is_exported` 且属 DirectUI 作用域的
  符号数)，与 `verify_codegen.py` 的口径逐字节一致
- `capi_total` = `exports.json` 中非 `?` 开头的纯 C 名导出数

### 2.5 G5 —— 头文件可编译

随机抽 `N` 个头文件（**固定随机种子**，保证可复现），各写一个
`#include <X.h>` 的 TU，用 `cl /Zs`（仅语法，不产码）检查。
`DirectUI.h` 与 `dui_abi_types.h` **每次都测**（公共入口）。
不要求全量，测得动即可。

### 2.6 GB —— 时长预算

超预算时报出**最慢的门禁**。超预算通常不是"机器慢"，而是某个门禁变得
不确定（联网、全量重编、杀软扫描）—— 那才是要查的。

---

## 3. 失败时怎么读

### 3.1 输出形态

每个门禁一行，末行给总判定：

```
==== G3  structural assertions (classes.json vs generated tree) ==========
         G3      classes.json declares 195 classes (51 inheritance edges)
                 ...
  [ OK ] class count and per-class artefacts agree with classes.json

==== SUMMARY =============================================================
  G1   PASS input integrity            0.1s
  G2   PASS golden regen               1.1s
  G3   PASS structure                  0.1s
  G4   PASS ABI fidelity              54.3s  modname 4227/4227, extern-C 86/86
  G5   PASS headers                    3.7s
  GB   PASS time budget               59.5s  under 600s

  ALL GATES PASS   (59.5s of 600s budget)
```

失败时长这样（**期望 / 实际 / 怎么办** 三段齐全）：

```
GATE G2: FAIL  expected=git diff --exit-code DirectUI/ pinned/ empty AND no new untracked files  actual=1 modified + 0 untracked file(s) differ from golden
  [FAIL] G2 golden regen
         expected: ...
         actual  : ...
         The generator output is not reproducible, OR the committed tree is
         stale. A generator change MUST ship with its regenerated golden diff
         in the same commit.
```

`GATE <id>: FAIL  expected=…  actual=…` 走 **stderr** 且格式固定，
供机器 grep / CI 注解。

### 3.2 按门禁排障

| 失败 | 常见原因 | 处理 |
|---|---|---|
| **G1** `CHANGED` / `MISSING` / `UNTRACKED` | 有人改了 `pinned/` 却没更新清单；或清单过期 | 若改动**有意**：`ci_checks.py hash --write` 并**与产物同 commit**。若无意的改动，`git checkout -- pinned/` 还原 |
| **G2** 前置"path(s) already modified/untracked" | 工作树有未提交改动（含手改 `DirectUI/`） | 先 commit / stash。确认可接受才用 `-AllowDirty`（**会丢改动**） |
| **G2** `diff --exit-code` 非空 | ①生成器改了但没重生成 golden ②生成器不确定（乱序、时间戳、路径泄漏） | 先 `python tools\dui-pipeline\regen.py` 看 diff 内容：是**语义变化**就一并提交；是**无意义抖动**说明生成器有不确定性，要修生成器 |
| **G2** `New untracked generated file(s)` | 生成器新增了文件但没 `git add` | `git add DirectUI/` 后重跑 |
| **G3** `missing from include/` | 生成器漏产某类的头/TU | 检查生成器；若是**有意**改生成范围，那是改 `classes.json`（同 commit） |
| **G3** `present but not implied by classes.json` | `classes.json` 被缩减（**事故特征**），或生成器产出残留 | **先确认 `pinned/classes.json` 没被意外覆写**。`git diff pinned/classes.json` 一看便知 |
| **G4** modname 非 N/N | 生成的声明与真实 DLL 导出不符 | 报告在 `.local/build/ci/verify_codegen-report.md`，里面逐类列出 missing 的修饰名 |
| **G5** 某头文件 `cl rc!=0` | 头文件语法错误（通常是生成器模板问题） | 报错里直接给了 `cl` 的前 12 行输出，含文件名与行号 |
| **GB** 超预算 | 某门禁变不确定/变慢 | 报错点名最慢的门禁；优先查它 |

### 3.3 关于行尾（一个真实的坑）

G1 的哈希是 **LF 规范化**后的内容，不是磁盘原始字节。原因：

`.gitattributes` 声明了 `* text=auto`，在 `core.autocrlf=true`（Windows 默认）
下，**checkout 会把 LF 改写成 CRLF**。所以同一个 blob：

| 位置 | `pinned/manifest.json` |
|---|---|
| 本仓库工作树 | LF，836 字节 |
| 同机 `git clone` | **CRLF，858 字节** |
| Linux CI checkout | LF，836 字节 |

若按原始字节哈希，G1 会在"本机工作树"通过、在"干净 clone"和"Linux CI"失败 ——
而任务要求**必须能在干净 checkout 上跑通**。因此改为哈希 git 眼中的内容
（CRLF→LF）。`git diff` 本来就忽略纯行尾差异（实测：把 `classes.json`
CRLF→LF 后 `git status` 仍为 clean），G1 与之一致。

> 这条是交付前用**干净 clone 负向测试**打出来的，不是推理出来的。

### 3.3.1 跑完 `ci.ps1`/`repro.ps1` 后 `git status` 出现 382 个 `M`（正常现象）

Windows 上跑完 regen 类脚本后，`git status` 常会列出 `DirectUI/` 下 **382 个
`" M"`**。这不是产物被改动：`.gitattributes` 的 `* text=auto` 使 checkout 得到
CRLF，而 `regen.py` 写回 LF；G2 用的是**内容规范化**后的 `git diff --exit-code`
（rc=0，真 PASS），`git status` 显示的只是行尾视图差异。恢复工作树：

```powershell
git checkout -- DirectUI
```

**但要注意一个真实的可用性边界**：G2 的前置检查要求工作树干净，而
`git add -A`（内容无差异，只是刷新 index）和 `git update-index --refresh`
都**不能**清掉这些 `M`，只有 `git checkout --` 能。因此**在同一工作树里连续
跑第二次 `ci.ps1` 会被 G2 前置检查拒绝**：

```
GATE G2: FAIL  expected=a clean DirectUI/ + pinned/ working tree before regenerating
               actual=382 path(s) already modified/untracked
```

这不是误报——G2 拒绝对脏工作树做 regen（否则被改动的产物会被静默覆盖、diff
看起来却是干净的）。CI 上每个 job 都在全新 clone 上只跑一次，因此不受影响；
本地要重跑时先 `git checkout -- DirectUI` 即可。`repro.ps1` 跟着
`ci.ps1 -GoldenOnly` 跑的组合（正是 repro job 的形态）同理。

---

## 4. 工具链发现

三样都能自动探测，也可用参数/环境变量覆盖（优先级从高到低）：

| 工具 | 参数 | 环境变量 | 自动探测顺序 |
|---|---|---|---|
| Python | `-Python` | `DSH_CI_PYTHON` > `DUI_PIPELINE_PYTHON` > `PYTHON` | PATH 上的 `python`/`python3`/`py -3` → 常见安装位置 |
| MSVC | `-VcRoot` | `DSH_CI_VCROOT` > `DUI_PIPELINE_VCROOT` | `VCToolsInstallDir`（VS 开发者提示符）→ `vswhere` → 常见字面路径（Enterprise/Professional/Community/BuildTools/2019） |
| Windows SDK | `-SdkVersion` | `DSH_CI_SDKVERSION` > `DUI_PIPELINE_SDKVERSION` | `WindowsSDKVersion` → `Windows Kits\10\Include` 下最高版本 |
| git | — | — | PATH（G2 必需） |

探测失败会明确说明缺什么、怎么覆盖，例如：

```
MSVC (x64) not found. Pass -VcRoot <...\VC\Tools\MSVC\<ver>> or set DSH_CI_VCROOT.
```

**显式覆盖一旦给出就绝不被静默忽略**：`-VcRoot` / `-SdkVersion` / `-Python`
指向不存在的路径时会**直接报错**，而不会悄悄回退到探测结果。

无 `git` 时在跑任何门禁**之前**以 `GATE G0: FAIL` 快速失败，而不是让 G2
产出一个可疑的"干净"结论。

---

## 5. 门禁自身的可信度

**一个不能失败的门禁不是门禁。** 本 CI 交付时带三套自证测试
（均在 `.local/build/ci-probe/`，非 tracked）：

### 5.1 负向测试：16 项，全部通过

在**一次性 clone** 里注入单一故障，断言：非零退出、输出含对应
`GATE <id>: FAIL`、消息含"期望"。

| # | 注入的故障 | 期望门禁 | 结果 |
|---|---|---|---|
| 1 | 基线（无故障） | — | PASS |
| 2 | `pinned/classes.json` 翻转 1 字节 | G1 | ✅ 触发 |
| 3 | `pinned/` 放入未跟踪文件 | G1 | ✅ 触发 |
| 4 | 未提交手改 `DirectUI/include/Element.h` | G2 前置 | ✅ 触发 |
| 5 | **已提交**手改 golden | G2 diff | ✅ 触发 |
| 6 | 生成器输出漂移但未重生成 golden | G2 diff | ✅ 触发 |
| 7 | 生成器漂移 **+** 同步重生成（合规流程） | — | ✅ PASS（不误报） |
| 8 | `-SecondsBudget 1` | GB | ✅ 触发 |
| 9 | 删掉 `Element.h` | G3 | ✅ 触发 |
| 10 | `classes.json` 砍到 12 类（**事故复现**） | G3 | ✅ 触发 |
| 11 | 多一个残留 TU | G3 | ✅ 触发 |
| 12 | `DirectUI.h` 语法损坏 | G5 | ✅ 触发 |
| 13–16 | 各"干净"对照组 | — | ✅ PASS（不误报） |

### 5.2 工具链发现测试：12 项，全部通过

| 场景 | 断言 |
|---|---|
| 剥离 PATH，仅留 `DSH_CI_PYTHON` | 覆盖生效；**且不产生任何 "not recognized" 噪声** |
| 清空所有 VS/SDK 环境变量 | MSVC 经 `vswhere`/字面路径探到；全链仍绿 |
| `-Python` 指向不存在路径 | 明确报错 |
| `-VcRoot` 指向不存在路径 | 明确报错，**且不静默回退到探测结果** |
| `-VcRoot` 指向**有效**路径 | 该路径被**采用**（防 shadowing 回归） |
| `-SdkVersion` 指向不存在版本 | 明确报错 |
| `DSH_CI_VCROOT` 值无效 | 忽略并继续探测，不中断 |

### 5.3 干净 checkout 测试，通过

在一个**全新 clone** 上、无参数、无覆盖地跑全链 → 全绿。
这条测试专门锁住 §3.3 的行尾修复：工作树里 `pinned/manifest.json` 是 LF（836B），
而新 clone 里是 CRLF（858B）。按原始字节哈希会在 clone/CI 上**失败**。

### 5.4 `-SelfTest`：门禁逻辑的受控夹具

```powershell
pwsh -File tools\dui-pipeline\ci.ps1 -SelfTest
```

对受控夹具验证篡改/新增/删除/删类四种检测，并确认
`modname_total` 会随 `classes.json` 变化（证明指标是**推导**的，不是常量）。

### 5.5 repro 的负向测试：15 项，全部通过

对 `pinned/` 的**一次性副本**注入单一故障，断言 `repro.py` 非零退出、
输出含对应 `GATE R*: FAIL`（脚本 `.local/build/ci-probe/repro-negtest2.py`）：

| # | 注入的故障 | 期望门禁 | 结果 |
|---|---|---|---|
| 1 | **对照**：不改任何东西 | — | ✅ PASS（不误报） |
| 2 | 删掉 `manifest.dll.source_url` | R1 | ✅ 触发 |
| 3 | 删掉 `manifest.pdb.source_url` | R1 | ✅ 触发 |
| 4 | PDB URL 用**带连字符**的槽位形态 | R1 | ✅ 触发（非法 URL 形态，先于下载被拦） |
| 5 | `source_url` 换成非 msdl URL | R1 | ✅ 触发 |
| 6 | DLL 的 `sha256` 改假 | R1 | ✅ 触发 |
| 7 | PDB 的 `sha256` 改假 | R1 | ✅ 触发 |
| 8 | PDB 槽位改一个字符（伪造凭证） | R1 | ✅ 触发 |
| 9 | DLL `size` 改假 | R1 | ✅ 触发 |
| 10 | PDB `size` 改假 | R1 | ✅ 触发 |
| 11 | manifest 的 DLL `size` 改假 | R1 | ✅ 触发 |
| 12 | 从已提交 `exports.json` 删 1 条导出 | R2 | ✅ 触发 |
| 13 | `manifest.pdb.age` 改假（R1 的 sha256/size 不覆盖它） | R2 | ✅ 触发（证明 R2 指纹比对有效） |
| 14 | 改 1 个符号的 1 个字段 | R3 | ✅ 触发 |
| 15 | 删 1 个符号 | R3 | ✅ 触发 |
| 16 | 把某符号退化成 `class=None`/`kind=free_function` | R3 | ✅ 触发 |

另有 `undname` 守卫测试 3 项（`.local/build/ci-probe/undname-guard.py`）：
自动探测到 LLVM、显式传 MSVC 工具被拒绝、PATH 上只有 MSVC 时拒绝并给可操作报错。

---

## 6. 交付过程中实测发现并修掉的问题

以下都是**实测打出来的**，不是推理出来的；记录在此以免回归：

| # | 问题 | 后果 | 修法 |
|---|---|---|---|
| 1 | **G1 按原始字节哈希** | `.gitattributes` 的 `* text=auto` 会在 checkout 时把 LF 改写为 CRLF，导致 G1 在**干净 clone / Linux CI 上失败** | 改为哈希 **LF 规范化**后的内容，与 `git` 口径一致（§3.3） |
| 2 | **G3 只做子集检查** | `classes.json` 被砍到 12 类时**照样通过** —— 正是要防的那起事故 | 改为**双向精确相等**：既查缺，也查多（§2.3） |
| 3 | **`$VcRoot` 被局部变量遮蔽** | PowerShell 变量名大小写不敏感，`$vcRoot = $null` 覆写了 `-VcRoot` 参数 → 用户显式指定的工具链被**静默忽略** | 局部改名 `$vcToolsRoot`，`Resolve-VcRoot` 显式读参数 |
| 4 | **`Join-Path $null ...` 不报错** | PATH 被剥离 / `ProgramFiles(x86)` 未设时，它把字符串绑成 `-ChildPath`，产生一堆 "not recognized" 噪声与畸形路径 | 新增 `Join-Base` 助手，`$null`/空白基路径返回 `$null` |
| 5 | **预算门禁不在 `-GoldenOnly` 路径上** | 该模式下 `GB` 永不执行，等于不是门禁 | 抽出 `Test-Budget`，由统一的 `Finish` 在每个出口调用 |
| 6 | **G2 依赖 `git add -N` 副作用** | 会改动 index（污染开发者工作区），且新增文件仍可能漏检 | 改为 `git diff --exit-code` + `git ls-files --others`，**不碰 index** |
| 7 | **`-VcRoot`/`-SdkVersion` 校验过松** | 无效值被当成"没给"，静默回退 | 显式给出即严格校验并报错（§4） |
| 8 | **ubuntu job 用反斜杠路径** | Linux 上 `\` 是普通字符，`'..\..'` 不做父目录回溯 | 全流程改用正斜杠（Windows 同样接受） |
| 9 | **无 `git` 时静默跑** | G2 会给出可疑结论 | 增加 G0 前置检查 |
| 10 | **`manifest.dll.file_version` 记的是路径元数据** | 记成 `10.0.26100.8875`，但该串在文件字节里出现 **0 次**（文件真实版本是 9278）；它是 System32 路径的 WRP 服务栈应答，换机器/换路径就变 → **契约字段不可复现** | 口径改为 `FixedFileInfo`（字节口径）+ 硬断言收窄（§7.5） |
| 11 | **`extract.py` 的 `file_version()` 旧注释描述错误** | 8875 vs 9278 的差异被记成"文件自身两个版本号矛盾"，与真实机制（路径元数据 vs 文件字节）不符 | 注释改为实测结论版；主口径改 FixedFileInfo，字符串版降为 `detail` 留痕 |
| 12 | **MSVC 的 `undname.exe` 在 `model.py` 候选表里** | repro job 为 dumpbin 必须上 MSVC PATH → `model.py` 会**静默**选错工具：rc=0、4321 条全错（§7.4） | `repro.py` 实测探测输出格式，只接受 LLVM 形态 |
| 13 | **`Get-Command` 会返回数组** | runner 的 PATH 有多个 git/python 目录时，`$cmd.Source` 把数组字符串化成**空格连接的一个路径** → 每个 job 在任何门禁前就崩（本机只有单个匹配，测不出来） | 四处（`ci.ps1` G0/Python、`repro.ps1`、`run.ps1`）显式取 `Select-Object -First 1`，git 另校验解析路径是真实文件 |
| 14 | **PDB 与 DLL 同目录会改变 `dumpbin` 输出** | 追加 ` = ` 注解使 707 条 ordinal→name 错位 → `exports.json` 必然不一致（§7.3） | repro 下载层分目录 + 显式断言守住前提；注解解析错位本身留档为已知边界 |

> 注：第 10–11 条是**唯一的**流水线核心改动（`extract.py` 的
> `file_version()` 口径 + `source_url` 组装 + 注释/报告文案），已由 lead 显式批准。
> 其余仍是**零改动**：`model.py` / `emit_def.py` / `emit_headers.py` /
> `emit_stub.py` 全程未动，CI 是**消费者**。

---

## 7. repro 门禁（第二阶段）—— `pinned/` 的**来源**可复现

G1 锁住"`pinned/` 没被改过"，G2 锁住"`pinned/ → DirectUI/` 可复现"。
两者都建立在**已提交的 `pinned/` 是可信的**这一前提上，但都没证明它**从哪来**。
repro 门禁补这一段：只凭 `manifest.json` 记的两个 URL 重新下载 DLL 与 PDB、
硬校验 sha256、重跑 `DLL+PDB → pinned` 推导，证明 `pinned/` 不是手编的。

```powershell
pwsh -File tools\dui-pipeline\repro.ps1
```

实现：`repro.ps1`（工具链发现 + 预算）+ `repro.py`（断言）。实测 **约 27 秒**
（两份下载 ~13s + `llvm-pdbutil` 抽 publics ~10s + 推导 ~4s），预算 900s。

### 7.1 单层口径：全量 byte-identical

`pinned/` 的两个产物都必须**逐字节**重建，没有容忍差异、没有"解释层"：

| 产物 | 行数 | 来源 |
|---|---|---|
| `exports.json` | 4321 | DLL 导出表（`dumpbin /exports`） |
| `symbols.json` | 11983 | 4321 导出表 + 7662 条 publics-only（PDB） |

两个输入都可从公共符号服务器复现，所以断言可以是全等的。R1/R2/R3 三段：

| 门禁 | 断言 |
|---|---|
| **R1** | ①`dll.source_url` 与 `pdb.source_url` 都存在且是合法 msdl 形态 ②两份下载的 sha256/size == manifest（**硬断言，绝不静默接受别的修订**——19041 的教训）③DLL 的 PE 头现算槽位 == URL 里的槽位 ④DLL 内 RSDS 现算的 PDB 槽位 == URL 里的槽位 |
| **R2** | ⑤**DLL 旁没有同名 PDB**（见 §7.3）⑥`llvm-pdbutil dump -publics` 成功且非空 ⑦`extract.py` 重推的 `exports.json` **逐字节相同** ⑧manifest 的 dll `sha256`/`size`/`arch` 与 pdb `sha256`/`size`/`guid`/`age` 全部一致 ⑨`model.py` 用**实测形态**确认过的 LLVM `undname` 重推 |
| **R3** | ⑩重建的 `symbols.json` 与已提交版 **逐字节相同**（11983 行） |

`classes.json` 有意**不**参与比对：它是人工策展的 pinned 输入（195 类），
不是 `model.py` 从 DLL/PDB 推导出来的东西，要求"重建"它是概念错误。

### 7.2 符号服务器地址的规范形态（易错点）

PDB 的槽位是 **GUID 去掉连字符后直接拼接 age**，中间没有分隔符、没有空格：

```
https://msdl.microsoft.com/download/symbols/dui70.pdb/F1920C0ED3DE254FE969E8E8CC4435CE1/dui70.pdb
                                                         └──────── GUID (32) ────────┘└age┘
```

**带连字符的形态不是合法路径，请求必然 404。** 这是个值得防重犯的坑：把请求失败当成
"上游没有这个文件"，会得出完全错误的结论（例如"PDB 不可复现"）。
`repro.py` 因此**现算 RSDS 槽位并与 `manifest.pdb.source_url` 交叉核对**，
`manifest.pdb.msdl_slot` 也一并落盘，使 URL 是一份**可验证的派生凭证**
而不是一个手打的字符串。

DLL 侧槽位语义不同（`<TimeDateStamp:8位大写HEX><SizeOfImage:小写HEX>`，混合
大小写是 winbindex `makeSymbolServerUrl` 的原样语义），两侧各自核对。

### 7.3 必须避开的陷阱：DLL 旁的 PDB 会改变 `dumpbin` 输出

`dumpbin /exports` 在 DLL 旁存在**同名 PDB** 时会追加 ` = <mangled>` 注解，
而 `parse_dumpbin_exports` 会把注解行里的名字**错配到 ordinal 上**。实测：

| 布局 | ` = ` 注解行 | ordinal→name 错位 |
|---|---|---|
| DLL 单独一个目录 | 0 | **0** |
| DLL 旁放同名 PDB | 4321 | **707** |

pinned 是在**无注解**形态下建立的，所以"PDB 与 DLL 同目录"必然导致
`exports.json` 不一致 —— 而失败会表现为**莫名其妙的 707 条名字错位**，
不是一句"环境不对"。

**铁则：DLL 与 PDB 必须放在不同目录。** `repro.py` 的下载层按此实现
（`dll-only/` 与 `pdb-only/`），并且有一条显式断言守着这个前提，失败时
直接把上面这张表的意思讲出来。`extract.py --pdb-publics` 收的是 publics **文本**
路径，天然支持分目录。

> 已知边界：注解行解析错位本身是 `extract.py` 的真 bug，但它只在"PDB 旁放"时
> 触发；修它属于流水线核心改动，本阶段不动，此处留档。

### 7.4 另一个陷阱：MSVC 的 `undname.exe` 会**静默**毁掉整个模型

`model.py` 的工具候选表含 MSVC 自带的 `undname.exe`，而 repro job 为了
`dumpbin` 必须让 MSVC 上 PATH。两者输出格式不同：

```
llvm-undname : 第 1 行 = 原样回显 mangled 名，第 2 行 = 反修饰结果
MSVC undname : 2 行 banner，然后 'Undecoration of :- "X"' / 'is :- "Y"'
```

`model.py` 靠"回显行 == 输入名"对齐，于是 MSVC 工具会**逐符号回退**。实测后果：

```
MSVC undname : rc=0，"4321 per-symbol fallbacks"，4321/4321 符号全错
               (class 全为 None, params=['C'] 而应为 [])
llvm-undname : rc=0，"0 per-symbol fallbacks"
```

**rc=0 + 全模型损坏**，是最危险的一类失败。所以 `repro.py` 不靠名字猜工具：
`resolve_undname()` **实测探测输出格式**（第 1 行是否等于输入名），只接受
LLVM 形态的工具；探测不到就给出可操作的报错。

同理 `llvm-pdbutil` 也由 `resolve_pdbutil()` 定位。实测 runner 上：
`llvm-pdbutil` 在 `C:\Program Files\LLVM\bin`，而官方 Windows LLVM 发行版
**不含** `llvm-undname.exe`（它只在 mingw 风格的树里，例如 GHC 自带的那个），
所以搜索路径两者都要覆盖。

### 7.5 `manifest.dll.file_version` 为什么不作硬断言

已提交版的 `file_version` 记的是 `10.0.26100.9278`（**FixedFileInfo**，文件字节口径）。
同一份字节按不同**路径**查询会得到不同答案：

| 路径 | sha256(前16) | 手解析 FixedFileInfo | Win32 StringFileInfo | `8875` 在字节中出现 |
|---|---|---|---|---|
| `C:\Windows\System32\dui70.dll` | 2080e43f5d997a3b | 9278 | **8875** | **0** |
| WinSxS `…9278…` 原件 | 2080e43f5d997a3b | 9278 | 9278 | 0 |
| 复制到别处（同字节） | 2080e43f5d997a3b | 9278 | 9278 | 0 |

机制：`System32\dui70.dll` 是**硬链接**到
`WinSxS\…dui70_…10.0.26100.9278_…\dui70.dll`，而该路径的版本查询由
**服务栈/WRP 元数据**回答（该 slot 记录的原始安装修订是 8875），**不读文件字节**。
WinSxS 现存版本系列（26100.1/8117/8972/9168/9278）里**没有** 8875。

**结论**：8875 是"System32 这条路径 + 本机服务栈状态"的元数据，换机器换路径就变。
manifest 是"这份 binary 的指纹契约"，每个字段都应能从**字节**复现 ——
所以口径定为 FixedFileInfo（9278），8875 仅作注记留在
`file_version()` 的 `detail` 与 `obtain_hint` 里。`file_version` 因此只作
**信息输出**，不作硬断言。

## 8. 与 GitHub Actions 的关系

`.github/workflows/pipeline.yml` 的职责分工（门禁实现全部委托给 `ci.ps1` / `repro.ps1`）：

| job | runner | 跑什么 |
|---|---|---|
| `golden` | ubuntu | `ci.ps1 -GoldenOnly`（G1+G2，秒级） |
| `abi` | windows | `ci.ps1` 全量（G1–G5+GB），另加 `verify.py --assertion A3` 的 import-lib 门禁 |
| `smoke` | windows | `run.ps1` 端到端（建窗断言，需要 detours） |
| `repro` | windows | `repro.ps1`（R1–R3，联网），收尾再跑 `ci.ps1 -GoldenOnly` |

`abi` job 保留了原有的 `lib.exe /def` + `dumpbin` + `verify.py A3` 步骤 ——
它从 `.def` 侧验证导入库可用性，与 G4 的"从源码侧验证装饰名"互补，未删除。

`repro` 触发条件：`pull_request` + `workflow_dispatch`（**不含** `push`：
它联网下载 ~3.6 MB（DLL+PDB）且耗时分钟级，PR 上跑足够；`workflow_dispatch` 便于手动重试）。
manifest 的 `dll.source_url` / `pdb.source_url` 是**唯一**的 URL 出处，workflow 与脚本里
**不硬编码任何 URL**。

> `repro` 里 `DLL 与 PDB 分目录`、`undname 按输出格式实测探测` 两条都写在脚本注释里，
> 因为它们都是"环境看起来正常但结果全错"的陷阱，见 §7.3 / §7.4。

---

## 9. 文件清单

| 文件 | 说明 |
|---|---|
| `tools/dui-pipeline/ci.ps1` | CI 入口（编排 + 摘要 + 预算 + 工具链发现） |
| `tools/dui-pipeline/ci_checks.py` | 可检查部分的实现（hash/struct/totals/headers/selftest） |
| `tools/dui-pipeline/repro.ps1` | repro 入口（工具链发现 + 预算） |
| `tools/dui-pipeline/repro.py` | repro 断言（R1 重下 DLL+PDB / R2 重推导 / R3 全量逐字节） |
| `tools/dui-pipeline/pinned.sha256` | `pinned/` 的 sha256 清单（LF 规范化） |
| `tools/dui-pipeline/CI.md` | 本文 |
| `.github/workflows/pipeline.yml` | 四个 job 委托到 `ci.ps1` / `repro.ps1` |

CI 自身**不写** `pinned/` 或 `DirectUI/`；唯一会写的文件是
`pinned.sha256`（仅显式 `hash --write`）与 `.local/` 下的临时产物
（repro 把下载件与隔离重建结果放在 `.local/build/repro/`）。
**不修改 git index。**
