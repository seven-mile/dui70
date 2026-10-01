# dui-pipeline 接口契约（冻结版 v1）

本文件是流水线各模块之间的**唯一契约**。任何模块都不得擅自更改字段名/语义；确需变更须先由 Lead 更新本文件。

## 目标

从真实 `dui70.dll` 的导出表（+公开 PDB）**自动生成**：
1. 全量 `.def`（4321 个导出）→ 用 `lib.exe` 直接生成导入库（**无需 C++ 源码**，spine 保证）
2. 各类的 C++ 头文件声明（用于替代手写 header）
3. stub `.cpp` 实现（`{ return 0; }` 风格）
4. 验收：`UITest.exe` 用生成的库链接 → 运行 → 成功创建窗口

## 职责与文件所有权（互斥写域）

| 所有者 | 文件 | 说明 |
|---|---|---|
| lead | `INTERFACE.md`, `emit_def.py`, `run.ps1`, `gen_uitest_proj.ps1` | 契约、def/导入库、编排、验收工程 |
| symbols | `extract.py`, `model.py` | 导出表+PDB 提取、反修饰、结构化 |
| codegen | `emit_headers.py`, `emit_stub.py` | 头文件与 stub 源码生成 |
| verifier | `verify.py`, `baseline_diff.py` | 独立校验、基线对照 |

**不要修改**：`DirectUI/**`（手写基线，含用户未提交改动）、`UITest/**`、`DirectUI Library.sln`。
所有生成物一律写入 `.local/build/`（已在 `.git/info/exclude` 排除），报告写入 `.local/audit/`。

## 关键路径常量

```
REPO          Z:\repos\DirectUI
REAL_DLL_X64  C:\Windows\System32\dui70.dll      (10.0.26100.8875, x64)
REAL_DLL_X86  C:\Windows\SysWOW64\dui70.dll      (10.0.26100.9278, x86)
PDB_X64       <repo>\.local\symbols\dui70-26200-x64.pdb   (GUID F1920C0E-D3DE-254F-E969-E8E8CC4435CE, age 1)
PDB_X86       <repo>\.local\symbols\dui70-26200-x86.pdb   (GUID 392F1D99-88B3-43C6-B310-5DED322BD83A, age 1)
BASELINE_LIB  <repo>\x64\Debug\Dui\dui70.lib      (手写基线的导入库；C-API 别名归一后与 DLL 等价)
BASELINE_DLL  <repo>\x64\Debug\Dui\dui70.dll      (手写基线的 stub DLL —— oracle 的权威载体)
BASELINE_EXE  <repo>\x64\Debug\UITest.exe         (可用基线，能正常建窗)
BASELINE_HDRS <repo>\DirectUI\*.h
MSDEF         <repo>\DirectUI\msdef.txt            (作者旧 dump, 3261 条)
BUILD         <repo>\.local\build\
REPORTS       <repo>\.local\audit\
```

工具（绝对路径，勿依赖 PATH）：
```
MSBUILD   C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe
VCBIN     C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64
          (dumpbin.exe, lib.exe, link.exe)
LLVM      C:\Local\Tools\mingw64\bin  (llvm-undname.exe, llvm-pdbutil.exe)
PYTHON    C:\Users\7mile\AppData\Local\Programs\Python\Python311\python.exe
CURL      C:\Windows\system32\curl.exe
```

## UITest 的真实符号需求（验收的最小目标集）

`UITest.exe` 从 `dui70.dll` 导入 **26 个符号**（清单：`.local\cache\uitest-imports-dui70.txt`），涉及类：
`Value`, `DUIXmlParser`, `Element`, `HWNDElement`, `NativeHWNDHost`, `TouchButton`, `Edit`
自由函数：`StrToID`, `StartMessagePump`, `RegisterAllControls`, `InitThread`, `InitProcessPriv`,
`UnInitProcessPriv`, `DumpDuiTree`（后者由 stub 自身提供，非导出）。

**阶段一（spine）目标** = 仅靠 def+lib 生成让 `UITest` 链接通过并运行建窗。
**阶段二（headers）目标** = 上述 7 个类的头文件由生成器产出，能编译、且修饰名与真实 DLL 完全一致。

## 产物 1：`exports.json`

```json
{
  "meta": {
    "dll": "C:\\Windows\\System32\\dui70.dll",
    "file_version": "10.0.26100.8875",
    "arch": "x64",
    "pdb_guid": "F1920C0E-D3DE-254F-E969-E8E8CC4435CE",
    "pdb_age": 1,
    "generated_utc": "2026-09-30T00:00:00Z"
  },
  "exports": [
    { "ordinal": 1905, "rva": "0x00026D5A", "mangled": "?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z", "forwarded": null }
  ],
  "publics": [
    { "rva": "0x0004B258", "mangled": "??4DuiNavigate@DirectUI@@QEAAAEAV01@AEBV01@@Z" }
  ]
}
```
- `exports`：来自 `dumpbin /exports`，**权威导出集合**（4321 条）。
- `publics`：来自 PDB（11981 条），含非导出的内部符号，仅供分析，不用于定义导出。

## 产物 2：`symbols.json`（核心）

```json
{
  "meta": { "...": "同 exports.json，另加 source_exports_count / source_publics_count" },
  "symbols": [
    {
      "mangled":      "?SetVisible@Element@DirectUI@@QEAAJ_N@Z",
      "undecorated":  "public: long __cdecl DirectUI::Element::SetVisible(bool)",
      "rva":          "0x0002A1B0",
      "ordinal":      2914,
      "is_exported":  true,

      "kind":         "method",
      "scope":        "DirectUI::Element",
      "namespace":    "DirectUI",
      "class":        "Element",
      "member":       "SetVisible",

      "access":       "public",
      "is_virtual":   false,
      "is_static":    false,
      "is_const":     false,
      "callconv":     "__cdecl",
      "return_type":  "long",
      "params":       ["bool"],
      "is_template":  false,
      "is_operator":  false,

      "baseline_status": "identical"
    }
  ],
  "classes": [
    {
      "name": "Element",
      "namespace": "DirectUI",
      "methods": 202,
      "is_template": false,
      "in_baseline_headers": true,
      "in_msdef": true,
      "stable": true
    }
  ]
}
```

### 枚举取值（严格）
- `kind`: `method` | `static_method` | `ctor` | `dtor` | `operator` | `free_function` | `data` | `vftable` | `c_api` | `template` | `unknown`
- `access`: `public` | `protected` | `private`
- `baseline_status`: `identical`（修饰名与手写基线导入库一致） | `param_changed`（同 `class::member` 但签名不同） | `missing`（真实有、基线无） | `new`（同 missing，语义别名，统一用 `missing`） | `removed`（基线有、真实无）
- `callconv`: `__cdecl` | `__stdcall` | `__thiscall` | `__fastcall` | `__vectorcall`

### 解析规则
- `params` 存**未命名**的参数类型原文（如 `"class DirectUI::Element *"`），保留 `const`/指针/引用。
- 模板符号（`is_template: true`）**不进入**头文件生成，但必须保留在 symbols 里。
- 无法解析的符号：`kind: "unknown"` 且保留 `undecorated` 原文，**绝不丢弃**。
- 反修饰失败（36 个纯 C 导出）→ `kind: "c_api"`，`mangled == undecorated == 原名`。

## 产物 3：`.def`

标准 MSVC 模块定义文件，**全量 4321 条**，形如：
```
LIBRARY dui70
EXPORTS
    InitProcessPriv
    ?Host@NativeHWNDHost@DirectUI@@QEAAXPEAVElement@2@@Z
```
导入库生成命令（**spine 的关键，不依赖任何 C++ 源码**）：
```
lib.exe /def:dui70.def /machine:x64 /out:dui70.lib
```

## 产物 4：生成的 headers / stub 源码

```
.local/build/generated/include/DirectUI/Element.h ...
.local/build/generated/src/Element.cpp ...
```
**硬性验收标准（codegen 必须自证）**：把生成的 stub 源码编译成 `.obj`，用
`dumpbin /symbols` 导出其修饰名集合，与真实 DLL 的导出集合求交——
**对目标子集必须 100% 匹配**（修饰名逐字相同）。这证明声明与真实 ABI 一致。

**A4 语义修正（重要，防永真式）**：上述"求交"若按字面实现（target := obj∩real）
则 target ⊆ real 恒真，断言无价值。正确口径（verifier 实现，四夹具自证）：
- `target` 由**声明侧**决定：.obj 中所有 DirectUI 命名空间的已定义符号，与真实集合无关；
- `reference` = 真实导出 ∪ PDB publics（11983 条）；
- 显式排除编译器自动合成的 `??_R*`（RTTI）/`??_G*`/`??_E*`（真实 DLL 中计数为 0）；
- **精度与完整性分开陈述**：A4 PASS 只表示已生成部分无签名错误；
  覆盖率（如 867/4321 ≈ 20.1%）必须显式报告，不得以 A4 PASS 暗示全面保真。

## 产物 5：报告（verifier）

- `.local/audit/pipeline-verification.md`：端到端验证结论、命令、证据
- `.local/audit/baseline-diff.md`：生成声明 vs 手写基线的差异与保真度统计
- `.local/audit/baseline-diff.csv`：逐符号对照

## 基线正确性 oracle

手写基线与真实 DLL 有 **3198 个修饰名完全一致**——这是黄金参照：
生成器对这 3198 个符号产出的声明，若修饰名不匹配即为生成器 bug。
`baseline_diff.py` 必须以此为核心断言，而不是只看"能不能编译"。

**oracle 的权威载体是基线 stub DLL（`x64\Debug\Dui\dui70.dll`）的导出表**。
基线导入库（.lib）做 C-API 别名归一后与 DLL 等价（3198/1123/155+1 守卫），
不做归一会得 3149/1172/204 —— 两个数字都对，但口径不同，报告里必须写明用的是哪个。

**口径区分（重要）**：symbols.json 的 baseline_status 有两套统计，
`meta.baseline_status_scope = "exported_only"`（主口径，identical=3198）与 publics_only（导出外的 PDB 公共符号）。
任何"3198"断言必须基于 exported_only 口径。

**publics[].rva 的语义修正**：llvm-pdbutil publics 输出的左列是 PDB 记录偏移，不是 RVA。
真实 RVA = 节 VA + `addr = 0001:NNNNNN` 的十进制偏移。symbols.json 里的 rva 字段已是真实 RVA
（与 dumpbin /exports 零不匹配），原值保留在 pdb_record_offset。
