# dui-pipeline 契约 —— pinned 输入与 DirectUI 生成物

> 本文是流水线的唯一权威契约。任何模块不得擅自更改字段名/语义；确需变更须先修订本文件再改实现。

## 0. 总体架构

```
[pinned/]                [tools/dui-pipeline/]         [DirectUI/]
 契约输入(冻结)     生成器(纯函数)            产品(golden, git-tracked)
 exports.json  ──►  emit_def.py    ──►  dui70.def
 symbols.json  ──►  emit_headers.py ──►  include/*.h
 symbols.json  ──►  emit_stub.py   ──►  src/*.cpp

 刷新(需 MSVC+DLL): extract.py / model.py 重产 pinned/
 验证(需 MSVC):     verify.py / verify_codegen.py
 Golden(任意平台):   regen.py 后 git diff --exit-code DirectUI/
```

**两段式是本设计的核心不变量**：
- `pinned → DirectUI/` 段是**纯 Python、确定性、无工具链依赖**——CI 的 golden test 只测这段
- `DLL → pinned` 段需要 dumpbin/llvm-pdbutil，只在刷新时跑，用 manifest 指纹锁定

## 1. pinned/ —— 契约输入

```
pinned/
  manifest.json         源指纹 + 生成环境声明
  exports.json          导出表（emit_def 的唯一输入）
  symbols.json          符号模型（emit_headers/emit_stub 的唯一输入）
  classes.json          目标类清单 + 继承表（覆盖成本显式化）
  class-inventory.csv   类名普查（来自旧 build 的白名单，供 model.py 分类用）
  vtable-slots.json     虚表槽位真值（J1 门禁输入；DLL+symbols 纯函数）
```

### 1.0 `class-inventory.csv` 是什么（不是生成依据，是分类 hint）

248 行 `类名,方法数` 的**历史普查产物**：早期一次 build 里 dump 出的类清单，用来在
`model.py` 里给符号做**类归属分类的辅助输入**（与 PDB publics 交叉比对），**不是**
代码生成逻辑的一部分，也**不是**契约：

- **谁定契约**：`classes.json`（195 类，人工策展、作为冻结输入）才是。改它才会改变
  生成结果（G3/G4 的 `modname_total` 就由它推导）。
- **改了 `class-inventory.csv` 会怎样**：只影响 `model.py` 把某些符号归到哪个类名下
  （分类 hint），不会凭空增删导出或改 ABI；若与 `classes.json` 冲突，以
  `classes.json` 为准。它**不是自动生成**的，也没有随 DLL 刷新而重建——它记录的是
  当时那份 build 的观测。
- **它参与 `repro.py` 的 R2→R3 链，只是不作为独立产物被比较**。R2 调 `model.py` 时
  用 `--inventory` 把 `pinned/class-inventory.csv` 传进去；`model.py` 只读它的
  `Class` 列作**类名白名单**（`MethodCount` 列明确不读，见 `load_class_inventory`），
  R2 由此产出的 `symbols.json` 再由 R3 **逐字节**比较（该比较的 docstring 即写
  "BYTE-IDENTICAL"）。所以它不参与的是"独立比对"，不是"整条断言链"。
- **改动它可能让 R3 失败**：把行删空或只留一半，实测 `symbols.json` 的字节会变
  （11983 行不变，但有 15 个类的归属丢失：`BehaviorStore`、`BinaryFile`、`ByteCode`、
  `CLocalClasses`、`ClassData`、`DUIParsePlayer`、`HandleCache`、`Impl`、`Internal`、
  `PropNotify`、`PropertyData`、`SinkProvider`、`SmoothDot`、`TouchEditAccessible`、
  `TouchTooltipTimings`——它们没有任何 ctor/dtor/vftable 可供自举，只能由这张表命名）。
  反之，只改 `MethodCount` 列**完全不影响**输出（全改 0 / 全改 99999 实测 `symbols.json`
  逐字节不变），删改可自举的类名（如首行 `AccessibleButton`）同样无影响。
- 在 `pinned.sha256` 里有指纹（5 个条目之一）表示它是**冻结输入**——改它就必须同步重生成
  `symbols.json` 并重新冻结，而不是"冻结不要动、可随意忽略"。它仍**不是契约**：
  契约是 `classes.json`（195 类，人工策展），二者冲突时以 `classes.json` 为准。
  它也不代表"可从 msdl 重建"：它是当时那份 build 的观测。

### 1.1 manifest.json

```json
{
  "dll": {
    "name": "dui70.dll",
    "arch": "x64",
    "file_version": "10.0.26100.9278",
    "size": 1732608,
    "sha256": "2080E43F5D997A3BD9827F38D8F3029D88F77A7F301966FBA10EC0ACAD9AA556",
    "source_url": "https://msdl.microsoft.com/download/symbols/dui70.dll/3D7534841aa000/dui70.dll",
    "msdl_slot": "3D7534841aa000",
    "obtain_hint": "msdl 只需 source_url；本地 Win11 26100 为 C:\\Windows\\System32\\dui70.dll（注意 System32 路径的 file_version 查询会被 WRP 服务元数据回答，见 CI.md §7.5）；刷新前必须校验 sha256"
  },
  "pdb": {
    "guid": "F1920C0E-D3DE-254F-E969-E8E8CC4435CE",
    "age": 1,
    "size": 1912832,
    "sha256": "198608E557573D8242A50C2313CAF3DD95323053FB99CEFDB08BB3C5E014033F",
    "source_url": "https://msdl.microsoft.com/download/symbols/dui70.pdb/F1920C0ED3DE254FE969E8E8CC4435CE1/dui70.pdb",
    "msdl_slot": "F1920C0ED3DE254FE969E8E8CC4435CE1",
    "obtain_hint": "msdl 只需 source_url（槽位 = GUID 去连字符直接拼 age）；这份 PDB 的 publics 是 symbols.json 能达到 11983 行的输入"
  },
  "toolchain": {
    "dumpbin": "14.44.35228 (VS2022 17.14)",
    "note": "undname 输出为只读消费，版本差异理论上不影响 pinned 内容"
  },
  "pinned_utc": "2026-10-01T00:00:00Z"
}
```

**规则**：刷新 pinned 前必须校验 DLL/PDB 的 sha256 与 manifest 一致；不符则要求显式
`--new-pin` 并更新整个 manifest。这是 golden 可比性的锚。

### 1.2 exports.json

```json
{
  "exports": [
    {"ordinal": 1, "name": "?AbsorbsShortcutProp@Element@DirectUI@@SAPEBUPropertyInfo@2@XZ", "rva": "0x000A3440"}
  ]
}
```

导出按 ordinal 排序，稳定且确定。`name` 为真实导出名（C++ 修饰名或纯 C 名）。

### 1.3 symbols.json

```json
{
  "symbols": [
    {
      "mangled": "?Add@Element@DirectUI@@QEAAJPEAV12@@Z",
      "kind": "method",
      "class": "Element",
      "member": "Add",
      "is_exported": true,
      "is_virtual": false,
      "is_static": false,
      "is_const": false,
      "return_type": "long",
      "params": ["class DirectUI::Element *"],
      "rva": "0x000A3440"
    }
  ]
}
```

- 每条记录 11 个字段，**显式存在**（值可为 null；不做 sparse 省略，避免 `.get()` 与 `["k"]` 语义分歧）
- kind 枚举：`method|static_method|ctor|dtor|operator|c_api|free_function|data|vftable|template|unknown`
  （`template`：实例化成员。无 `?$` 前缀的 9 个"模板类参数"方法沿用此值）
- `rva`：导出符号为导出表 RVA；publics 为节 VA+偏移换算的真实 RVA。**543 个 vftable 的 RVA
  是未来"反汇编推导继承链"的原料，必须保留**
- 导出符号条数恒等于 exports.json（4321）；publics（is_exported=false）来自 PDB
- **access 不在 schema 里**：从修饰名推导（成员 `@@` 后字母：A/C/E=private，I/K/M=protected，
  Q/S/U=public；静态数据看数字位 0/1/2）。矩阵已经全量交叉验证
- **undecorated 不在 schema 里**：params/return_type 是可信的结构化签名。需要原始
  undname 文本时由 mangled 即时重跑 llvm-undname

### 1.4 classes.json

```json
{
  "classes": ["Value","DUIXmlParser","Element","HWNDElement","NativeHWNDHost","TouchButton","Edit",
              "Button","Progress","PushButton","TouchCheckBox","XProvider"],
  "inheritance": {
    "HWNDElement": "Element", "Edit": "Element", "TouchButton": "Element",
    "Button": "Element", "Progress": "Element",
    "PushButton": "Button", "TouchCheckBox": "TouchButton",
    "XProvider": "IXProvider"
  }
}
```

生成器为无状态纯函数。扩类 = 改此文件 + regen（覆盖成本显式化、可 review）。

### 1.5 vtable-slots.json（J1 门禁的真值；**DLL bytes + symbols.json 的纯函数**）

```json
{
  "schema": 1,
  "classes": {
    "Button": {
      "rva": "0x00107F18",
      "slots": ["_EButton",
                ["IsRTL", "IsRTLReading"],
                ["IsContentProtected", "IsMSAAEnabled", "OnCustomDraw"],
                "GetContentStringAsDisplayed",
                "OnPropertyChanging"]
    }
  },
  "icf_groups": {"0x00104ED0": ["HWNDElementProvider", "TouchSelectPopupProvider"]}
}
```

**性质（这是它作为契约的真义）**：

- **纯函数、可重推导**：输出 = `dui70.dll 字节` + `pinned/symbols.json` 的
  纯函数（`extract-vtable-slots.py`）。**不读** `DirectUI/include/**`
  （读了自己要检测的排序 bug 就继承 bug）、**不读** `classes.json`
  （hand-curated、不可重推导）。它**不是手写真值表**：repro 门禁 **R3'**
  重推导并**逐字节比对**——手改表再重签 `pinned.sha256` 也逃不过 R3'
  （G1 只证"与签名一致"，无外部真值；原型实测过这条攻击路径）。
- **每槽恰一个元素，位置 == slot 序号**：`"Name"`（唯一解析）/
  `["N1",...]`（ICF 多候选，**取并集**，绝不取 `[0]`）/
  `[]`（未解析：thunk/int3/unknown）。`len(slots)` 恒等于真实槽数，
  结构上不可能发生序列位移。
- **icf_groups 是派生不是声明**：按 `rva` 等值分组（当前 4 组 / 9 类）。
  **没有 icf-groups.json 豁免表**——门禁读一张不受重推导约束的手写豁免表
  是新漏洞（把 103 类全写进去就能让 J1 空过）。改 rva 伪造共享关系会被
  R3' 抓住。
- **规模**（26100 pin）：175 类 / 4645 槽 / 830,595 B；ModernProgressBar
  超 400 槽上限会**截断并打印告警**（绝不静默）。
- **刷新流程**：换 DLL 版本后 `extract-vtable-slots.py --slots
  pinned/vtable-slots.json` 重跑 + `ci_checks.py hash --write` 重签
  （与产物同 commit）。

## 2. DirectUI/ —— 产品（golden）

```
DirectUI/
  include/          生成头文件（聚合 DirectUI.h + N 类 + Interfaces.h + dui_abi_types.h）
  src/              生成 stub TU（ABI 黄金清单：可独立 cl /c + dumpbin 验证）
  dui70.def         4321 导出
  README.md         面向库消费者
```

- **dui70.lib 不进 git**（二进制）。自建：`lib.exe /def:DirectUI\dui70.def /machine:x64 /out:dui70.lib`
- 生成物头部带 `// Generated by tools/dui-pipeline — DO NOT EDIT. Pin: <sha256[:12]>`
- 手工修改 DirectUI/ 会被 golden test 打回——它只属于生成器
- 接口类的符号纪律：真实 DLL 无接口本体符号的（IXProvider）用
  `struct __declspec(novtable)` + protected ctor 只声明不定义；真实 DLL **有**导出的
  接口（IXProviderCP/IXElementCP）保持普通 class 不加 novtable。判据永远是 pinned 数据

## 3. 工具脚本

| 脚本 | 职责 | 依赖 |
|---|---|---|
| `extract.py` | DLL+PDB → pinned/exports.json + manifest 校验 | dumpbin, llvm-pdbutil |
| `model.py` | exports+publics → pinned/symbols.json + classes.json | llvm-undname |
| `emit_def.py` | pinned/exports.json → DirectUI/dui70.def | 纯 Python |
| `emit_headers.py` | pinned/symbols.json + classes.json → DirectUI/include/ | 纯 Python |
| `emit_stub.py` | 同上 → DirectUI/src/ | 纯 Python |
| `regen.py` | 一键 pinned → DirectUI/ | 纯 Python |
| `run.ps1` | 端到端：regen + 自建 lib + UITest + 建窗断言 | MSVC |
| `verify.py` | A1-A6 独立验证（读 pinned/） | MSVC(部分) |
| `verify_codegen.py` | modname 保真 | MSVC |

**路径解耦**：脚本支持 `--pinned <dir>` / `--out <dir>`，默认仓库根的 `pinned/` `DirectUI/`。
`.local/` 只存缓存（原始 dump、PDB、审计报告），tracked 产物不路过它。

## 4. CI（GitHub Actions）

四个 job（详见 `CI.md` §8；门禁实现全部委托给 `ci.ps1` / `repro.ps1`）：

| job | runner | 触发 | 断言 |
|---|---|---|---|
| golden | ubuntu | push / PR | `ci.ps1 -GoldenOnly`：G1 pinned 完整性 + G2 regen 逐字节可复现 |
| abi | windows-latest | push / PR | `ci.ps1` 全量：G3/G4/G5（双向类相等、modname/extern-C 保真、头文件编译） |
| smoke | windows-latest | push / PR | `run.ps1` 全流程，窗口标题 + SYSTEM32 断言 |
| repro | windows-latest | PR / 手动 | `repro.ps1`：从 msdl 重下 DLL+PDB → 重推 pinned/ → **逐字节**比对（R1/R2/R3） |

`repro` 故意**不**在 push 上跑：它联网且耗时，开着 PR 的 push 会重复触发。

顺序纪律：任何验证前必须 regen → lib.exe → 重链 exe（陈旧产物会假 PASS，
verify.py 的 mtime 守卫会拦截）。`gen_uitest_proj.ps1 -Lib` 必须传绝对路径。

### 5.1 为什么是 `AdditionalIncludeDirectories` 而不是 `ProjectReference`

迁移前 `UITest.vcxproj` 用 `ProjectReference` 指向**手写的** `DirectUI.vcxproj`，那是
"DirectUI 是源码项目"时代的形态。该 vcxproj 已在 `dd1fd41` 删除，而且**生成树里
根本不存在 vcxproj**——`DirectUI/` 是 `emit_headers.py`/`emit_stub.py` 的产物，随
`regen.py` 只会重写它生成的
那些文件（`dui70.def`、`include/*.h`、`src/*.cpp`），**不会删除**目录里别的东西
——往 `DirectUI/` 放一个 vcxproj 它不会抹掉你，但会被 G2 的"regen 前工作树必须干净"
预检拦下（未跟踪文件同样触发），而放进 `include/` 的额外头还会被 G3 的精确相等
判为 extra。真正的护栏是这两道门禁，不是 regen 的删除行为。

所以迁移后正确的形态只有一个：把 `DirectUI\include` 放进
`AdditionalIncludeDirectories`、把 `dui70.lib` 作为链接输入（`DirectUI\dui70.def`
经 `lib.exe` 生成，见 §5）。引用一个不存在的项目文件不是"更规范"，是坏的。

另外注意：**CI 的 smoke 路径根本不经过 `UITest.vcxproj`**——`run.ps1` 调
`gen_uitest_proj.ps1` 直接驱动 `cl.exe`/`link.exe`（见该脚本头注释及 `CI.md` §5.4）。
因此 vcxproj 只服务本机 VS 用户，它是否过时不影响 CI 结论。

## 5. 使用者指南（DirectUI/README.md 摘要）

```cpp
#include <DirectUI.h>                     // /I DirectUI\include
// 自建导入库：
//   lib.exe /def:DirectUI\dui70.def /machine:x64 /out:dui70.lib
// 链接 dui70.lib；运行时加载系统 dui70.dll（>= Win11 26100）
// 可选 ABI 自证：cl /c DirectUI\src\*.cpp + dumpbin /symbols 与 def 比对
```

## 6. 刷新流程（换新版 dui70.dll 时）

```
1. extract.py --verify-pin（SHA256 不符则要求显式 --new-pin）
2. 重跑 extract --pinned + model --pinned → pinned/ 更新
3. regen → DirectUI/ 更新
4. 一个 commit 同时含 pinned + golden → review 看到的 diff 就是
   "这次 Windows 更新对 ABI 意味着什么"（新增类/签名变化全部可见）
```

**刷新约束**：

- **PDB 与 DLL 一样可从公共符号服务器复现**。msdl 上 dui70 的 PDB（含历史版本）
  都能取到，前提是用**规范地址形态**：
  ```
  https://msdl.microsoft.com/download/symbols/<name>.pdb/<GUID 去连字符><age>/<name>.pdb
  ```
  槽位是 GUID 去掉连字符后**直接拼接** age（中间没有分隔符、没有空格）。
  换版刷新因此可以走**全量 publics 路径**：`extract.py --pdb-publics`
  （配合 `llvm-pdbutil dump -publics`）→ `model.py`，`exports.json` 与
  `symbols.json` 都能 byte 级重建（当前 4321 + 11983 条）。
- **刷新铁则：DLL 与 PDB 必须放在不同目录**。`dumpbin /exports` 在 DLL 旁存在
  同名 PDB 时会改变输出——追加 ` = <mangled>` 注解，而 `parse_dumpbin_exports`
  会把这些注解行的名字错配到 ordinal 上（实测 707 条错位）。pinned 是在**无注解**
  形态下建立的，所以 PDB 与 DLL 同目录必然导致 `exports.json` 不一致。
  `repro.py` 的下载层已按分目录实现，并有断言守住这个前提。（注解行解析错位
  本身是已知边界，修它属于流水线核心改动，尚未处理。）
- PDB 走 msdl 时必须同样做 **sha256 硬断言**：`manifest.pdb` 记录
  `sha256`/`size`/`guid`/`age`，repro 会现算 RSDS 槽位并与 `source_url` 交叉核对。
- 附带事实：WIN10 时代构建（1507/1607/2004）的 CODEVIEW 调试目录中
  AddressOfRawData ≠ PointerToRawData，pe_info 按 RVA 语义取址（历史 bug 已修，
  详见 git log）；26100/28000 两字段恰好相等是当年侥幸工作的原因。

**另见**：`manifest.dll.file_version` 的口径（FixedFileInfo vs System32 路径的
WRP 服务元数据）、repro 门禁的断言层次与负向测试，见 `CI.md` §7。

## pinned/mi-tables.json (schema 3) -- order-contract track

Produced by `extract-mi-tables.py --dll <dui70.dll> --symbols
pinned/symbols.json --lengths pinned/mi-interface-lengths.json`.
Two sections:

- `derived` -- a function of DLL bytes + symbols.json + the manual
  lengths input. repro.py gate R3'' proves CONDITIONAL
  re-derivability (same committed manual input -> byte-identical
  derived section) and asserts manual == committed lengths input
  verbatim + schema == 3; it is NOT an independent proof of the
  manual values themselves. Per class:
  `primary` / `secondaries` tables with `identity`, `rva`, `slots`,
  `length_provenance` (`next-vftable` | `manual` | `manual-conflict`
  | `ignored-redundant` | `hard-stop` | `unknown`), plus
  `ctor_vftable_references`: the rip-relative LEA references to the
  class's OWN vftables, bounded by the ctor's function extent --
  `scan: pdata-bounded` when .pdata covers the ctor, else
  `scan: symbol-bounded-safe` (the ctor symbol's own extent from the
  pinned symbols table, conservative cap); on this binary: 84
  pdata-bounded + 84 symbol-bounded-safe, 0 refused. ALL alias
  candidates at a target RVA kept, none dropped. SEMANTICS:
  reference-only evidence, order=ORDER-UNKNOWN; these are NOT stores
  (no this+offset write is traced) and NO base order, emission order,
  or declaration order is derived from the field. Move constructors
  (`$$QEAV` by-value&& parameter) count as constructors when a class
  has no other ctor.
- `manual` -- verbatim copy of mi-interface-lengths.json: human ABI
  inputs (G1-locked). Family-wide `interface_lengths` apply only
  where no `class_interface_lengths` entry exists. A manual value
  SHORTER than an in-binary visible bound is a CONFLICT: the table is
  emitted with its visible slots and `length_provenance:
  manual-conflict`, and consumers (R6, emitter) must refuse the class
  -- a human input may tighten an unobservable tail, never deny
  visible slots.

Consumers: `uia_order_verify.py` (R6 gate), the stage-2 MI emission
track (PR #15 branch), length_input_control.py (negative controls).
