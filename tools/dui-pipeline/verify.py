#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py -- dui-pipeline 端到端校验（独立复算）

契约：tools/dui-pipeline/INTERFACE.md
报告：.local/audit/pipeline-verification.md

断言清单
--------
A1  symbols.json 自洽：条数、字段完整性、枚举值合法、无重复 mangled、
    与 exports.json 的交叉一致、回归防护三条
A2  生成的 dui70.def 与 pinned/exports.json 逐条一致（set 比较，报差集）
A3  自建导入库（lib.exe /def 产物）覆盖全部导出，且非陈旧
A4  **modname 保真（最重要）**：生成的 stub 源码编译出的 .obj，用 dumpbin /symbols
    取修饰名集合，与 `exports.json ∪ symbols(is_exported=false)` 比对 ——
    目标集合必须无一遗漏、且全部可编译。只断言精度，覆盖率单独披露
A5  验收复跑：独立运行生成的 UITest.exe，查
    MainWindowTitle == "Microsoft DirectUI Test"，且产物非陈旧
A6  确定性：regen 两次，产物树 byte-diff == 0

设计原则
--------
* 产物可能尚未就绪 —— 每个断言独立判定 PASS / FAIL / SKIP，绝不因为缺文件而中断。
* SKIP 表示"输入不存在"，与 FAIL（输入存在但不符预期）严格区分。
* 所有子进程原始输出落入报告，便于复核。

用法
----
  python verify.py                       # 全部断言
  python verify.py --assertion A1,A4     # 只跑指定断言
  python verify.py --json                # 额外打印机器可读汇总
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter

# ---------------------------------------------------------------- 环境常量

# 仓库根由本文件位置推导（tools/dui-pipeline/verify.py -> 仓库根），
# 不写死机器路径；同理解释器用当前进程的 sys.executable。
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON = sys.executable

# MSVC 工具目录（含 dumpbin.exe / cl.exe）：--vcbin > VCToolsInstallDir > PATH。
VCBIN = ""
DUMPBIN = "dumpbin"
CL = "cl"

REAL_DLL = r"C:\Windows\System32\dui70.dll"
BUILD = os.path.join(REPO, r".local\build")
SCRATCH = os.path.join(BUILD, "verify-scratch")   # 验证自己的临时产物（不污染受检产物）

# ---- 契约路径（可被 --pinned/--out 覆盖，见 configure()）----
PINNED = os.path.join(REPO, "pinned")
OUT = os.path.join(REPO, "DirectUI")
REPORT = os.path.join(REPO, r".local\audit\pipeline-verification.md")

# 受检产物（由 configure() 依 PINNED/OUT 推导）
SYMBOLS_JSON = ""
EXPORTS_JSON = ""
MANIFEST_JSON = ""
CLASSES_JSON = ""
OUT_DEF = ""
OUT_INCLUDE = ""
OUT_SRC = ""
GEN_LIB = ""
UITEST_EXE = ""
STUB_OBJ_DIR = ""

EXPECTED_TOTAL = 4321          # 真实导出条数（pinned/exports.json）
EXPECTED_SYMBOLS = 11983       # pinned/symbols.json 条数（4321 导出 + 7662 publics）
EXPECTED_NONEXPORTED = 7662    # is_exported=false 条数
EXPECTED_WINDOW_TITLE = "Microsoft DirectUI Test"

# 契约 §1.3 的 kind 枚举（11 种）。
CONTRACT_KINDS = {"method", "static_method", "ctor", "dtor", "operator",
                  "c_api", "free_function", "data", "vftable", "template",
                  "unknown"}

# 恒定必备字段（class/member/return_type/rva 为条件字段）
REQUIRED_SYMBOL_FIELDS = [
    "mangled", "kind", "is_exported", "is_virtual", "is_static", "is_const",
    "params",
]

# 必须保持"方法语义"的 13 个 class::member（回归防护，见 A1）
REGRESSION_TARGETS = [
    ("Element", "Add"), ("Element", "SortChildren"), ("Element", "GetValue"),
    ("Element", "SetValue"), ("Element", "_SetValue"),
    ("Element", "RemoveLocalValue"), ("Element", "_RemoveLocalValue"),
    ("Element", "_PreSourceChange"),
    ("DUIXmlParser", "Create"), ("DUIXmlParser", "CreateLayout"),
    ("DUIXmlParser", "SetGetSheetCallback"),
    ("DUIXmlParser", "SetParseErrorCallback"),
    ("DUIXmlParser", "SetUnknownAttrCallback"),
]

# 生成器**刻意注入**的合成符号白名单（A4 的 precision 判定需要豁免它们）。
#
# 这些名字在真实 dui70.dll 里**不存在**，但它们是"让真实存在的 ??_7 vftable
# 导出得以落地"的必要手段：C++ 里一个类只有含虚函数才会实例化 vftable，而
# 部分真实类的虚函数全部内联（不出现在符号表），所以生成器必须注入一个锚点
# 虚函数，才能让编译器吐出那个**确实是真实导出**的 ??_7 符号。
#
# 因此它们不是"生成错误"，而是"为达成 ABI 目标而付出的合成代价"。A4 是
# precision 断言，天然无法区分"刻意合成"与"生成漏改名"，故在此显式豁免。
#
# 分两组：
#   (1) vftable 锚点：emit_headers.py 对"有自有 vftable、但没有任何导出虚方法"
#       的类注入 `virtual long On<Class>Virt(void) { return 0; }`
#       （ISBLeak / FontCache / StyleSheet / IXElementCP / IXProviderCP 形态）。
#   (2) 多态基类合成 ctor：emit_headers.py 的 POLYMORPHIC_BASE_CLASSES 对抽象
#       基类注入纯虚 `AddRef`，使其子类能导出基类子对象 vftable；纯虚类的
#       ctor 由编译器合成，故这两个 ??0 名字是副产物。
#
# 维护要求：新增豁免必须逐条列出**完整修饰名**（不要用类名通配），
# 否则白名单会掩盖真实的保真缺陷。
SYNTHETIC_ANCHORS = {
    # (1) vftable 锚点 —— 对应 ??_7 是真实导出
    "?OnFontCacheVirt@FontCache@DirectUI@@UEAAJXZ",
    "?OnISBLeakVirt@ISBLeak@DirectUI@@UEAAJXZ",
    "?OnIXElementCPVirt@IXElementCP@DirectUI@@UEAAJXZ",
    "?OnIXProviderCPVirt@IXProviderCP@DirectUI@@UEAAJXZ",
    "?OnStyleSheetVirt@StyleSheet@DirectUI@@UEAAJXZ",
    # (2) 多态基类（抽象接口）的编译器合成 ctor
    "??0IDialogElement@DirectUI@@QEAA@XZ",
    "??0IElementListener@DirectUI@@QEAA@XZ",
}


def configure(pinned: str | None = None, out: str | None = None,
              report: str | None = None) -> None:
    """解析 --pinned/--out 并派生所有受检路径。

    契约 §3 要求所有脚本支持 `--pinned <dir>` / `--out <dir>`，
    默认仓库根的 `pinned/` 与 `DirectUI/`。
    """
    global PINNED, OUT, REPORT, SYMBOLS_JSON, EXPORTS_JSON, MANIFEST_JSON
    global CLASSES_JSON, OUT_DEF, OUT_INCLUDE, OUT_SRC, GEN_LIB, UITEST_EXE
    global STUB_OBJ_DIR
    if pinned:
        PINNED = os.path.abspath(pinned)
    if out:
        OUT = os.path.abspath(out)
    if report:
        REPORT = os.path.abspath(report)
    SYMBOLS_JSON = os.path.join(PINNED, "symbols.json")
    EXPORTS_JSON = os.path.join(PINNED, "exports.json")
    MANIFEST_JSON = os.path.join(PINNED, "manifest.json")
    CLASSES_JSON = os.path.join(PINNED, "classes.json")
    OUT_DEF = os.path.join(OUT, "dui70.def")
    OUT_INCLUDE = os.path.join(OUT, "include")
    OUT_SRC = os.path.join(OUT, "src")
    GEN_LIB = os.path.join(BUILD, "lib", "dui70.lib")     # run.ps1 自建
    UITEST_EXE = os.path.join(BUILD, "acceptance-x64", "UITest.exe")
    STUB_OBJ_DIR = os.path.join(SCRATCH, "stub-obj")

# ---------------------------------------------------------------- 基础设施


class Verdict:
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class Ctx:
    """收集每条断言的命令 / 原始输出 / 结论。"""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, aid: str, title: str, verdict: str, cmds: list[str],
            evidence: list[str], detail: str = "") -> None:
        self.results.append({
            "id": aid, "title": title, "verdict": verdict,
            "cmds": cmds, "evidence": evidence, "detail": detail,
        })
        tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[verdict]
        print("%s %s  %s" % (tag, aid, title))
        if detail:
            for ln in detail.splitlines():
                print("        " + ln)

    def by_id(self, aid: str) -> dict | None:
        for r in self.results:
            if r["id"] == aid:
                return r
        return None


def run(cmd: list[str], timeout: int = 600, env: dict | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as exc:
        return 127, "", "FileNotFoundError: %s" % exc
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ds" % timeout


_VCVARS_CACHE: dict | None = None


def _tool_subdirs() -> list[str]:
    """MSVC 二进制子目录候选（按架构优先 x64）。"""
    return [os.path.join("bin", "Hostx64", "x64"),
            os.path.join("bin", "Hostx86", "x86")]


def discover_vcbin() -> str | None:
    """定位 MSVC 二进制目录（含 dumpbin.exe），找不到返回 None。

    顺序：环境变量 VCToolsInstallDir -> PATH 上的 dumpbin -> vswhere 查询。
    """
    vct = os.environ.get("VCToolsInstallDir")
    if vct:
        for sub in _tool_subdirs():
            cand = os.path.join(vct, sub)
            if os.path.isfile(os.path.join(cand, "dumpbin.exe")):
                return cand
    which = shutil.which("dumpbin")
    if which:
        return os.path.dirname(os.path.abspath(which))
    vswhere = os.path.join(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        rc, out, _err = run([vswhere, "-latest", "-products", "*",
                             "-requires",
                             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                             "-property", "installationPath"], timeout=60)
        if rc == 0 and out.strip():
            root = out.strip().splitlines()[0].strip()
            base = os.path.join(root, "VC", "Tools", "MSVC")
            if os.path.isdir(base):
                for ver in sorted(os.listdir(base), reverse=True):
                    for sub in _tool_subdirs():
                        cand = os.path.join(base, ver, sub)
                        if os.path.isfile(os.path.join(cand, "dumpbin.exe")):
                            return cand
    return None


def configure_vcbin(path: str | None = None) -> str:
    """设置 MSVC 工具目录（`--vcbin` 覆盖自动发现），返回说明文字。"""
    global VCBIN, DUMPBIN, CL
    chosen = None
    if path:
        chosen = os.path.abspath(path)
        if not os.path.isfile(os.path.join(chosen, "dumpbin.exe")):
            return "指定的 --vcbin 下没有 dumpbin.exe: %s" % chosen
    else:
        chosen = discover_vcbin()
    if not chosen:
        return ("未找到 MSVC 工具目录（可设 VCToolsInstallDir 或用 --vcbin 指定）；"
                "将按 PATH 调用 dumpbin/cl")
    VCBIN = chosen
    DUMPBIN = os.path.join(chosen, "dumpbin.exe")
    CL = os.path.join(chosen, "cl.exe")
    return "MSVC 工具目录 = %s" % chosen


def _vcvars_path() -> str | None:
    """定位 vcvars64.bat（用于导出 INCLUDE/LIB/PATH）。"""
    cands = []
    vs = os.environ.get("VSINSTALLDIR")
    if vs:
        cands.append(os.path.join(vs, "VC", "Auxiliary", "Build", "vcvars64.bat"))
    vct = os.environ.get("VCToolsInstallDir")
    if vct:
        cands.append(os.path.join(vct, "..", "..", "..", "Auxiliary", "Build",
                                  "vcvars64.bat"))
    if VCBIN:
        cands.append(os.path.join(VCBIN, "..", "..", "..", "..", "..", "..",
                                  "Auxiliary", "Build", "vcvars64.bat"))
    for c in cands:
        c = os.path.abspath(c)
        if os.path.isfile(c):
            return c
    return None


def msvc_env() -> tuple[dict | None, str]:
    """取得可编译 C++ 的环境（INCLUDE/LIB/PATH）。

    cl.exe 直接调用会报 `fatal error C1034: windows.h: no include path set`，
    因为缺少 INCLUDE。这里通过 vcvars64.bat 导出环境并缓存（进程内只做一次）。
    返回 (env 或 None, 说明)。
    """
    global _VCVARS_CACHE
    if _VCVARS_CACHE is not None:
        return _VCVARS_CACHE, "cached"
    vcvars = _vcvars_path()
    if not vcvars:
        return None, "未找到 vcvars64.bat（可用 --vcbin 或 VCToolsInstallDir 指定）"
    # 写一个临时 .bat 再执行：内联 `cmd /c "call ... && set"` 在 subprocess
    # 的 list 形式下会被 list2cmdline 重新加引号，导致 cmd 解析失败（rc=1、无输出）。
    bat = os.path.join(REPO, r".local\audit\_vcvars_env.bat")
    os.makedirs(os.path.dirname(bat), exist_ok=True)
    with open(bat, "w", encoding="ascii", errors="replace") as fh:
        fh.write('@echo off\r\ncall "%s" >nul 2>&1\r\nset\r\n' % vcvars)
    rc, out, err = run(["cmd", "/c", bat], timeout=180)
    if "INCLUDE=" not in out.upper():
        return None, "vcvars64.bat 执行失败 rc=%d（INCLUDE 未导出）" % rc
    env = dict(os.environ)
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    _VCVARS_CACHE = env
    return env, "from vcvars64.bat"


def tail(text: str, n: int = 25) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-n:]


def q(path: str) -> str:
    return '"%s"' % path if " " in path else path


# ---------------------------------------------------------------- 数据提取


def load_real(path: str | None = None) -> list[str]:
    """真实导出名集合。

    唯一事实源是 `pinned/exports.json`（字段 `name`）。
    """
    if path:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    with open(EXPORTS_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [x.get("name") for x in data.get("exports", []) if x.get("name")]


def load_pdb_publics(path: str | None = None) -> set[str]:
    """PDB publics 名单（A4 的参考集合之一）。

    口径：直接从 `pinned/symbols.json` 取 `is_exported == false` 的
    mangled 集合 —— schema 仍保留这些符号。
    """
    if path:
        out: set[str] = set()
        if not os.path.isfile(path):
            return out
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                n = (row.get("Name") or "").strip()
                if n:
                    out.add(n)
        return out
    if os.path.isfile(SYMBOLS_JSON):
        with open(SYMBOLS_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {s["mangled"] for s in data.get("symbols", [])
                if s.get("is_exported") is False and s.get("mangled")}
    return set()


def def_names(path: str) -> list[str]:
    """解析 .def 的 EXPORTS 段，返回**导出名**列表。

    MSVC .def 的别名语法是 `导出名 = 内部名`。真实 DLL 的导出表里是**导出名**，
    因此这里取 `=` 左边的名字。例如：

        ?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z = InitProcessPriv

    导出名是 `?InitProcessPriv@...`（修饰名），内部名是 `InitProcessPriv`。
    这与真实 dui70.dll 导出 `InitProcessPriv`（未修饰）**方向相反**，
    是本次验证发现的 pipeline bug —— 见 A2 的说明。
    """
    names: list[str] = []
    in_exports = False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.split(";")[0].strip()
            if not line:
                continue
            up = line.upper()
            if up.startswith("EXPORTS"):
                in_exports = True
                continue
            if up.startswith(("LIBRARY", "NAME", "DESCRIPTION", "STACKSIZE",
                              "HEAPSIZE", "SECTIONS", "VERSION", "STUB")):
                in_exports = False
                continue
            if not in_exports:
                continue
            tok = line.split()
            name = tok[0]
            if "=" in name:
                name = name.split("=", 1)[0]          # 取导出名（= 左侧）
            elif "=" in line:
                # 形如 `name @ordinal = internal`（少见）
                name = line.split("=", 1)[0].split()[0]
            # 去掉 @ordinal 形式
            if name.startswith("@"):
                continue
            names.append(name.strip())
    return names


def lib_symbols(path: str) -> set[str]:
    rc, out, err = run([DUMPBIN, "/linkermember:1", path])
    if rc not in (0, 1) and not out:
        return set()
    syms: set[str] = set()
    for line in out.splitlines():
        if line.strip().startswith("Summary"):
            break
        m = re.match(r"^\s+[0-9A-Fa-f]+\s+(\S+)\s*$", line)
        if m:
            n = m.group(1)
            if n.startswith("__imp_"):
                n = n[6:]
            syms.add(n)
    return syms


def obj_symbols(path: str) -> dict[str, set[str]]:
    """dumpbin /symbols 提取符号，返回 {'defined': {...}, 'undefined': {...}}。

    dumpbin 的行格式（字段数可变，符号名在最后一个 `|` 之后）：
        009 00000000 SECT3  notype ()    External     | InitProcessPriv
        00A 00000000 UNDEF  notype ()    External     | ?Foo@Bar@@QAEXXZ

    `UNDEF` 表示未定义（引用了外部符号）；`SECTn`/`ABS` 等表示已定义。
    只有**已定义的 External** 才代表本编译单元真正产出的修饰名 —— 这正是
    "modname 保真"要断言的：生成的声明能否编译出与真实 DLL 逐字相同的修饰名。
    """
    rc, out, err = run([DUMPBIN, "/symbols", path])
    defined: set[str] = set()
    undefined: set[str] = set()
    for line in out.splitlines():
        if "|" not in line:
            continue
        m = re.match(r"^\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        sect = m.group(2)
        rest = m.group(3)
        name = rest.rsplit("|", 1)[1].strip()
        if not name:
            continue
        # dumpbin 会把反修饰结果附在修饰名之后：`?Foo@@YAXXZ (void __cdecl Foo(void))`
        # 取第一段（真正的符号名），否则无法与导出集合逐字比对。
        name = name.split(" (", 1)[0].strip()
        if not name:
            continue
        if "External" not in rest:
            continue
        if sect.upper() == "UNDEF":
            undefined.add(name)
        else:
            defined.add(name)
    return {"defined": defined, "undefined": undefined}


def obj_defined_symbols(path: str) -> set[str]:
    return obj_symbols(path)["defined"]


JUNK = {"__IMPORT_DESCRIPTOR_dui70", "__NULL_IMPORT_DESCRIPTOR",
        "\x7fdui70_NULL_THUNK_DATA", "size", "mode"}


def is_junk(n: str) -> bool:
    return n in JUNK or n.startswith((".debug$", ".idata$")) or n.startswith("__")


# ---------------------------------------------------------------- A1


def check_symbols_json(ctx: Ctx) -> None:
    """A1：pinned/symbols.json 自洽性。

    schema 顶层只有 symbols。断言：
      1) 顶层形状（只允许 symbols 键）
      2) 条数：总 11983 = 导出 4321 + 非导出 7662
      3) 字段完整性（恒定字段必备 + 全量键集合）
      4) 枚举合法（kind ∈ 契约 §1.3 的 11 种枚举）
      5) 无重复 mangled
      6) 交叉一致：is_exported=true 的 mangled 集合 == exports.json 的 name 集合
      7) 三件套齐全（manifest/exports/symbols/classes）
      8) 回归防护三条（13 class::member / GetGetSheetCallback / 哨兵）
    """
    aid, title = "A1", "pinned/symbols.json 自洽性（条数/字段/枚举/去重）"
    cmds = ["read %s" % SYMBOLS_JSON, "read %s" % EXPORTS_JSON,
            "read %s" % MANIFEST_JSON, "read %s" % CLASSES_JSON]
    if not os.path.isfile(SYMBOLS_JSON):
        ctx.add(aid, title, Verdict.SKIP, cmds,
                ["file not found: %s" % SYMBOLS_JSON],
                "pinned/symbols.json 尚未产出 —— 无法执行自洽性校验（非通过）")
        return

    with open(SYMBOLS_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    syms = data.get("symbols", [])
    ev: list[str] = []
    problems: list[str] = []

    # ---- (1) 顶层形状 ----
    top_extra = sorted(set(data) - {"symbols"})
    ev.append("顶层键 = %s（契约 §1.3 只允许 symbols）" % sorted(data))
    ev.append("顶层多余键 = %s（应为无）" % (top_extra or "无"))
    if top_extra:
        problems.append("顶层出现非契约键: %s" % top_extra)

    # ---- (2) 条数 ----
    exported = [s for s in syms if s.get("is_exported") is True]
    nonexported = [s for s in syms if s.get("is_exported") is False]
    neither = [s for s in syms if not isinstance(s.get("is_exported"), bool)]
    ev.append("symbols 总条数 = %d（契约期望 %d）" % (len(syms), EXPECTED_SYMBOLS))
    ev.append("  is_exported=True  = %d（契约期望 %d）" % (len(exported), EXPECTED_TOTAL))
    ev.append("  is_exported=False = %d（契约期望 %d）" % (len(nonexported), EXPECTED_NONEXPORTED))
    if len(syms) != EXPECTED_SYMBOLS:
        problems.append("总条数 %d != %d" % (len(syms), EXPECTED_SYMBOLS))
    if len(exported) != EXPECTED_TOTAL:
        problems.append("is_exported=True 条数 %d != %d" % (len(exported), EXPECTED_TOTAL))
    if len(nonexported) != EXPECTED_NONEXPORTED:
        problems.append("is_exported=False 条数 %d != %d"
                        % (len(nonexported), EXPECTED_NONEXPORTED))
    if neither:
        problems.append("is_exported 非布尔值的条数 = %d" % len(neither))

    # ---- (3) 字段完整性 ----
    missing_field: Counter = Counter()
    for s in syms:
        for f in REQUIRED_SYMBOL_FIELDS:
            if f not in s:
                missing_field[f] += 1
    ev.append("恒定字段缺失统计 = %s" % (dict(missing_field) if missing_field else "无"))
    if missing_field:
        problems.append("缺必需字段: %s" % dict(missing_field))

    # 全部 11983 条都带齐 11 个键，连条件字段 class/member/return_type/rva
    # 也是键恒在、值可为 null。这里把它固化成断言：既能防"字段悄悄消失"，
    # 也能防"悄悄多加字段"。
    key_union: Counter = Counter()
    for s in syms:
        for k in s:
            key_union[k] += 1
    full_keys = {k for k, c in key_union.items() if c == len(syms)}
    ev.append("出现在**全部** %d 条里的键 = %s" % (len(syms), sorted(full_keys)))
    ev.append("非全量的键 = %s"
              % {k: c for k, c in key_union.items() if c != len(syms)})
    expect_keys = set(REQUIRED_SYMBOL_FIELDS) | {
        "class", "member", "return_type", "rva"}
    if full_keys != expect_keys:
        problems.append("字段键集合不符：缺 %s / 多 %s"
                        % (sorted(expect_keys - full_keys),
                           sorted(full_keys - expect_keys)))

    # 条件字段：member 对"有类成员语义"的 kind 必备（data 里含全局变量，无 member）
    no_member = [s for s in syms
                 if s.get("kind") in {"method", "static_method", "ctor", "dtor",
                                      "operator", "vftable"}
                 and not s.get("member")]
    ev.append("类成员类 kind 却缺 member 的条数 = %d（data/unknown 允许无 member）"
              % len(no_member))
    if no_member:
        problems.append("%d 个类成员类符号缺 member" % len(no_member))

    # ---- (4) 枚举合法 ----
    kinds = Counter(s.get("kind") for s in syms)
    illegal = {k: c for k, c in kinds.items() if k not in CONTRACT_KINDS}
    ev.append("kind 分布 = %s" % dict(sorted(kinds.items(), key=lambda x: -x[1])))
    ev.append("契约 §1.3 枚举 = %s" % sorted(CONTRACT_KINDS))
    if illegal:
        problems.append("非法 kind 值: %s" % illegal)

    # ---- (5) 重复 mangled ----
    mangled = [s.get("mangled") for s in syms]
    dup = [m for m, c in Counter(mangled).items() if c > 1]
    ev.append("唯一 mangled = %d；重复 = %d" % (len(set(mangled)), len(dup)))
    if dup:
        problems.append("重复 mangled %d 个，例: %s" % (len(dup), dup[:5]))
    empty = sum(1 for m in mangled if not m)
    if empty:
        problems.append("空 mangled %d 个" % empty)

    # ---- (6) 与 exports.json 交叉一致 ----
    if os.path.isfile(EXPORTS_JSON):
        with open(EXPORTS_JSON, "r", encoding="utf-8") as fh:
            ex = json.load(fh)
        ex_list = ex.get("exports", [])
        ex_names = [x.get("name") for x in ex_list]
        ev.append("")
        ev.append("--- 与 pinned/exports.json 交叉核对 ---")
        ev.append("exports.json 顶层键 = %s（契约 §1.2 只允许 exports）" % sorted(ex))
        ex_top_extra = sorted(set(ex) - {"exports"})
        if ex_top_extra:
            problems.append("exports.json 顶层出现非契约键: %s" % ex_top_extra)
        ev.append("exports.json 条数 = %d" % len(ex_list))
        if len(ex_list) != EXPECTED_TOTAL:
            problems.append("exports.json 条数 %d != %d" % (len(ex_list), EXPECTED_TOTAL))
        ex_set = set(ex_names)
        exp_set = {s.get("mangled") for s in exported}
        ev.append("  exports.json name 唯一 = %d" % len(ex_set))
        ev.append("  symbols(is_exported) == exports.name ? %s" % (ex_set == exp_set))
        if ex_set != exp_set:
            problems.append("is_exported 集合与 exports.json 不一致："
                            "仅 exports 有 %d，仅 symbols 有 %d"
                            % (len(ex_set - exp_set), len(exp_set - ex_set)))
        # exports 条目字段应为 ordinal/name/rva，多出的即为非契约字段
        field_freq: Counter = Counter()
        for x in ex_list:
            field_freq.update(x.keys())
        ev.append("  exports 条目字段频次 = %s" % dict(field_freq))
        unexpected = sorted(set(field_freq) - {"ordinal", "name", "rva"})
        if unexpected:
            problems.append("exports.json 含非契约字段: %s" % unexpected)
        ords = sorted(x.get("ordinal") for x in ex_list if isinstance(x.get("ordinal"), int))
        if ords and ords != list(range(1, len(ords) + 1)):
            problems.append("ordinal 不是 1..%d 连续（min=%s max=%s）"
                            % (len(ords), ords[0], ords[-1]))
        ev.append("  ordinal 1..%d 连续 = %s" % (len(ords), bool(ords) and ords == list(range(1, len(ords) + 1))))
    else:
        problems.append("pinned/exports.json 缺失 —— 无法交叉核对")

    # ---- (7) rva 形状 ----
    rvas = [s.get("rva") for s in syms if s.get("rva")]
    bad_rva = [r for r in rvas if not re.match(r"^0x[0-9A-Fa-f]{8}$", str(r))]
    ev.append("")
    ev.append("rva 条数 = %d，格式不合规 = %d" % (len(rvas), len(bad_rva)))
    no_rva = [s for s in syms if not s.get("rva")]
    ev.append("无 rva 的条数 = %d" % len(no_rva))
    for s in no_rva[:8]:
        ev.append("   %-12s exp=%-5s %s" % (s.get("kind"), s.get("is_exported"),
                                            (s.get("mangled") or "")[:70]))
    if bad_rva:
        problems.append("rva 格式不合规 %d 个，例: %s" % (len(bad_rva), bad_rva[:5]))

    # ---- (8) 回归防护 ----
    by_cm: dict[tuple, list] = {}
    for s in syms:
        by_cm.setdefault((s.get("class"), s.get("member")), []).append(s)

    ev.append("")
    ev.append("===== 回归防护 (1)：13 个必须保持方法语义的 class::member =====")
    reg_bad = []
    for cls, mem in REGRESSION_TARGETS:
        hits = by_cm.get((cls, mem), [])
        if not hits:
            reg_bad.append("%s::%s 缺失" % (cls, mem))
            ev.append("  [X] %s::%s -> <未找到>" % (cls, mem))
            continue
        for s in hits:
            pr = s.get("params") or []
            kind_ok = s.get("kind") in ("method", "static_method")
            bal_ok = all(str(p).count("(") == str(p).count(")") for p in pr)
            ok = kind_ok and bal_ok
            if not ok:
                reg_bad.append("%s::%s kind=%s balanced=%s"
                               % (cls, mem, s.get("kind"), bal_ok))
            ev.append("  [%s] %-14s::%-24s kind=%-14s 括号配平=%s nparams=%d"
                      % ("OK" if ok else "XX", cls, mem, s.get("kind"), bal_ok, len(pr)))
    if reg_bad:
        problems.append("13 个回归目标不达标: %s" % reg_bad[:6])
    ev.append("  不达标条数 = %d" % len(reg_bad))

    ev.append("")
    ev.append("===== 回归防护 (2)：DUIXmlParser::GetGetSheetCallback 返回类型形状 =====")
    ggs = [s for s in syms if "GetGetSheetCallback" in (s.get("mangled") or "")]
    if not ggs:
        problems.append("GetGetSheetCallback 缺失")
        ev.append("  <未找到>")
    for s in ggs:
        rt = s.get("return_type") or ""
        need = ["(__cdecl *)", "unsigned short const *", "void *"]
        miss = [n for n in need if n not in rt]
        ev.append("  return_type = %s" % rt)
        ev.append("  必需片段缺失 = %s" % (miss if miss else "无"))
        ev.append("  kind = %s" % s.get("kind"))
        if miss:
            problems.append("GetGetSheetCallback 的 return_type 缺函数指针形状: %s" % miss)
        if s.get("kind") != "method":
            problems.append("GetGetSheetCallback 的 kind=%s，期望 method" % s.get("kind"))

    ev.append("")
    ev.append("===== 回归防护 (3)：哨兵 —— kind=data 却含参数 =====")
    sentinel = [s for s in syms
                if s.get("kind") == "data"
                and any(")" in str(p) for p in (s.get("params") or []))]
    ev.append("  kind=='data' 且 params 含 ')' 的条数 = %d（期望 0）" % len(sentinel))
    for s in sentinel[:10]:
        ev.append("     %s params=%s" % ((s.get("mangled") or "")[:70],
                                         json.dumps(s.get("params"), ensure_ascii=False)[:90]))
    if sentinel:
        problems.append("哨兵失败：%d 个 kind=data 的符号仍带参数" % len(sentinel))

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems
            else "schema 自洽（11983 = 4321 导出 + 7662 publics；含 13 回归目标 / "
                 "GetGetSheetCallback / 哨兵）")


# ---------------------------------------------------------------- A2


def build_tree_fingerprint() -> tuple[float, int]:
    """返回 (最新 mtime, 文件数) —— 用于检测"验证期间有人在写产物"。

    注意：一次全量复跑恰逢产物被并发重写，A4 因此抓到半写状态的 .cpp
    而报"编译失败"，但单独复跑就 PASS。这是**竞态**而非真实缺陷；
    若不检测，会产生假 FAIL。

    监视 pinned/ 与 OUT（生成物），排除本脚本自己的临时目录，以及
    **A5 运行 UITest.exe 时它自己写出的探针日志** —— 后者是本脚本自身的
    行为（不是"他人写入"），若计入会让守卫每次全量跑都误报。
    """
    # A5 验收运行 UITest 时由被测程序写出的探针产物（见 UITest/UITest.cpp）。
    # 它们是本脚本自身运行的副作用，不属于"并发写入"。
    self_outputs = {"anim-experiment.log", "duser-call-counts.txt"}
    newest, count = -1.0, 0
    for root in (PINNED, OUT, os.path.join(BUILD, "lib"),
                 os.path.join(BUILD, "acceptance-x64")):
        if not os.path.isdir(root):
            continue
        for dp, dirs, files in os.walk(root):
            # 跳过本脚本自己的临时/编译产物目录，避免误判为并发写入
            dirs[:] = [d for d in dirs
                       if d not in ("verify-obj", "stub-obj")
                       and not d.startswith(("tmp-", "tmp_", "_"))]
            if os.path.abspath(dp).startswith(os.path.abspath(SCRATCH)):
                continue
            for f in files:
                if f in self_outputs or f.endswith(".g.txt"):
                    continue
                p = os.path.join(dp, f)
                try:
                    t = os.path.getmtime(p)
                except OSError:
                    continue
                count += 1
                if t > newest:
                    newest = t
    return newest, count


def check_build_quiescent(before: tuple[float, int]) -> list[str]:
    after = build_tree_fingerprint()
    msgs = []
    if after[1] != before[1]:
        msgs.append("产物文件数在验证期间变化（%d -> %d）" % (before[1], after[1]))
    elif after[0] > before[0] + 0.5:
        msgs.append("产物在验证期间被写入（最新 mtime %s -> %s）"
                    % (time.strftime("%H:%M:%S", time.localtime(before[0])),
                       time.strftime("%H:%M:%S", time.localtime(after[0]))))
    return msgs


def newest(paths: list[str]) -> tuple[str, float]:
    best, bt = "<none>", -1.0
    for p in paths:
        if os.path.isfile(p):
            t = os.path.getmtime(p)
            if t > bt:
                best, bt = p, t
    return best, bt


def file_version_of(path: str) -> str | None:
    """用 Win32 VerQueryValueW 读取文件的**字符串**版本（StringFileInfo\\FileVersion）。

    注意：本机 x64 `dui70.dll` 的 FixedFileInfo 与 StringFileInfo **不一致**
    （固化版本 10.0.26100.9278，而字符串版本 10.0.26100.8875）—— 这是微软构建
    产物自身的问题，不是提取 bug。契约/产物采用字符串版本，故这里也读字符串版本，
    并另行提供 fixed_file_version_of() 供对照。
    """
    return _string_version_of(path, "FileVersion")


def fixed_file_version_of(path: str) -> str | None:
    """读取 FixedFileInfo 的四段版本号（可能与字符串版本不同）。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None
        res = ctypes.c_void_p()
        ln = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\",
                                                    ctypes.byref(res),
                                                    ctypes.byref(ln)):
            return None

        class FI(ctypes.Structure):
            _fields_ = [("dwSignature", wt.DWORD), ("dwStrucVersion", wt.DWORD),
                        ("dwFileVersionMS", wt.DWORD), ("dwFileVersionLS", wt.DWORD)]

        f = ctypes.cast(res, ctypes.POINTER(FI)).contents
        ms, ls = f.dwFileVersionMS, f.dwFileVersionLS
        return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:  # noqa: BLE001
        return None


def _string_version_of(path: str, key: str) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None
        res = ctypes.c_void_p()
        ln = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                                                    ctypes.byref(res),
                                                    ctypes.byref(ln)):
            return None
        langs = ctypes.cast(res, ctypes.POINTER(wt.WORD))
        for i in range(ln.value // 4):
            lang, cp = langs[i * 2], langs[i * 2 + 1]
            sub = "\\StringFileInfo\\%04x%04x\\%s" % (lang, cp, key)
            r2 = ctypes.c_void_p()
            l2 = ctypes.c_uint()
            if ctypes.windll.version.VerQueryValueW(buf, sub, ctypes.byref(r2),
                                                    ctypes.byref(l2)):
                return ctypes.wstring_at(r2.value, l2.value).rstrip("\x00")
        return None
    except Exception:  # noqa: BLE001
        return None


def stat_line(path: str) -> str:
    if not os.path.isfile(path):
        return "%-64s <missing>" % path
    return "%-64s %s  %8d bytes" % (
        path, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
        os.path.getsize(path))


def check_def(ctx: Ctx) -> None:
    aid, title = "A2", "生成的 DirectUI/dui70.def 与 pinned/exports.json 逐条一致"
    cmds = ["read %s" % OUT_DEF, "set compare vs %s" % EXPORTS_JSON]
    if not os.path.isfile(OUT_DEF):
        ctx.add(aid, title, Verdict.SKIP, cmds, ["file not found: %s" % OUT_DEF],
                "DirectUI/dui70.def 尚未生成（regen.py 未跑）—— 非通过")
        return
    if not os.path.isfile(EXPORTS_JSON):
        ctx.add(aid, title, Verdict.SKIP, cmds,
                ["file not found: %s" % EXPORTS_JSON],
                "pinned/exports.json 缺失 —— 无参照集合")
        return

    real = load_real()
    names = def_names(OUT_DEF)
    real_s, def_s = set(real), set(names)
    ev = [
        ".def EXPORTS 条数 = %d（含重复前的原始行数）" % len(names),
        ".def 唯一导出名 = %d" % len(def_s),
        "真实唯一导出   = %d" % len(real_s),
        "真实有、def 无 = %d" % len(real_s - def_s),
        "def 有、真实无 = %d" % len(def_s - real_s),
    ]
    problems = []
    if len(real_s) != EXPECTED_TOTAL:
        problems.append("真实集合 %d != 4321" % len(real_s))
    if real_s - def_s:
        problems.append("def 缺少 %d 个真实导出，例: %s"
                        % (len(real_s - def_s), sorted(real_s - def_s)[:5]))
    if def_s - real_s:
        problems.append("def 多出 %d 个非真实导出，例: %s"
                        % (len(def_s - real_s), sorted(def_s - real_s)[:5]))
    dup = [n for n, c in Counter(names).items() if c > 1]
    ev.append("def 内重复名 = %d %s" % (len(dup), dup[:5]))
    if dup:
        problems.append("def 内重复 %d 个" % len(dup))

    builtin = re.search(r"^\s*LIBRARY\s+(\S+)", open(OUT_DEF, encoding="utf-8",
                                                     errors="replace").read(), re.M)
    ev.append("LIBRARY 语句 = %s" % (builtin.group(1) if builtin else "<缺失>"))

    # ---- 别名方向诊断：真实 DLL 导出的是哪个名字？.def 导出的是哪个名字？----
    aliases = {}  # 导出名 -> 内部名
    for raw in open(OUT_DEF, encoding="utf-8", errors="replace"):
        line = raw.split(";")[0].strip()
        if "=" in line and not line.upper().startswith(("LIBRARY", "EXPORTS")):
            lhs, rhs = line.split("=", 1)
            lhs = lhs.split()[0].strip()
            rhs = rhs.strip()
            if lhs and rhs:
                aliases[lhs] = rhs
    if aliases:
        # 真实 DLL 里存在、但被 .def 用作"内部名"的名字 => 方向反了
        reversed_hits = sorted(set(aliases.values()) & real_s)
        ev.append("")
        ev.append("别名条目总数 = %d" % len(aliases))
        ev.append("被 .def 当作 **内部名**、却正是真实 DLL 导出名的条目 = %d"
                  % len(reversed_hits))
        for n in reversed_hits:
            lhs = [k for k, v in aliases.items() if v == n][0]
            ev.append("   真实导出名 %-28s 被 .def 写成:  %s = %s" % (n, lhs, n))
        if reversed_hits:
            ev.append("")
            ev.append("=> .def 的别名方向反了。MSVC .def 语法是 `导出名 = 内部名`。")
            ev.append("   真实 dui70.dll 的导出表用**未修饰 C 名**（dumpbin /exports 见下），")
            ev.append("   而 UITest.exe 也是按**未修饰 C 名**导入这些函数，故 .def 必须以")
            ev.append("   未修饰名作为**导出名**，即应写成 `InitProcessPriv = ?Init…@Z`（或无别名）。")
            ev.append("   当前写成 `?Init…@Z = InitProcessPriv`，导出名变成了修饰名，")
            ev.append("   既与真实 DLL 不符（A2 FAIL），也无法满足 UITest 的 plain 名导入。")
            problems.append(
                ".def 别名方向反转：%d 条被写成 `修饰名 = 真实导出名`；"
                "应为 `真实导出名 = 修饰名`" % len(reversed_hits))

    # 真实 DLL 的实际导出名（独立取证）
    rc, out, err = run([DUMPBIN, "/exports", REAL_DLL])
    cmds.append("dumpbin /exports %s" % REAL_DLL)
    real_plain_sample = []
    for line in out.splitlines():
        m = re.match(r"^\s+\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]{8}\s+(\S+)\s*$", line)
        if m and not m.group(1).startswith("?"):
            real_plain_sample.append(m.group(1))
    ev.append("")
    ev.append("真实 DLL 未修饰导出共 %d 个，样例: %s"
              % (len(real_plain_sample), real_plain_sample[:6]))
    if "InitProcessPriv" in real_plain_sample:
        ev.append("确证：真实 DLL 导出的是未修饰名 'InitProcessPriv'，不是 '?InitProcessPriv@…'")

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems else "逐条一致（%d/%d）"
            % (len(real_s & def_s), len(real_s)))


# ---------------------------------------------------------------- A3


def check_gen_lib(ctx: Ctx) -> None:
    aid, title = "A3", "自建导入库覆盖 4321 导出（lib.exe /def:DirectUI/dui70.def）"
    cmds: list[str] = []
    ev: list[str] = []

    # 契约第 135 行：dui70.lib 不进 git，由 run.ps1 自建
    #   lib.exe /def:DirectUI\dui70.def /machine:x64 /out:dui70.lib
    candidates = [GEN_LIB]
    defs = [OUT_DEF]
    existing = [c for c in candidates if os.path.isfile(c)]
    if not existing:
        ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % GEN_LIB],
                ["未找到自建导入库: %s" % GEN_LIB],
                "导入库尚未由 run.ps1 自建 —— 非通过")
        return

    ev.append("候选导入库与 .def 的时间戳：")
    for p in candidates + defs:
        ev.append("   " + stat_line(p))
    ev.append("")

    real = set(load_real())

    # 逐个候选评估，并显式报告陈旧性
    scored = []
    for lib in existing:
        dfn, dft = newest(defs)
        lt = os.path.getmtime(lib)
        stale = (dft > lt + 1.0)
        syms = {s for s in lib_symbols(lib) if not is_junk(s)}
        hit = len(syms & real)
        scored.append((lib, syms, hit, stale, lt, dft))
        ev.append("%s" % lib)
        ev.append("   lib 符号 = %d ; ∩真实 = %d" % (len(syms), hit))
        ev.append("   最新 .def = %s (%s)" % (dfn, time.strftime("%H:%M:%S", time.localtime(dft))
                                              if dft > 0 else "-"))
        ev.append("   STALE（lib 早于 .def，属于陈旧产物）= %s" % stale)
        if stale and dft > 0:
            ev.append("   -> lib 比 .def 旧 %.0f 秒；该 lib 不反映当前 .def，"
                      "用它会得到假 PASS/FAIL" % (dft - lt))
        ev.append("")

    # 选最新的非陈旧库；若全陈旧则选最新的并在结论里标 FAIL
    fresh = [s for s in scored if not s[3]]
    chosen = max(fresh or scored, key=lambda s: s[4])
    lib, syms, hit, stale, _lt, _dft = chosen

    cmds.append("dumpbin /linkermember:1 %s" % lib)
    if stale:
        cmds.append("Get-Item %s | Select LastWriteTime  # staleness check" % lib)

    ev.append("=> 采用 %s" % lib)
    ev.append("   lib 归档符号（去链接器内部/__imp_） = %d" % len(syms))
    ev.append("   lib ∩ 真实 = %d" % hit)
    ev.append("   真实 - lib = %d" % len(real - syms))
    ev.append("   lib - 真实 = %d" % len(syms - real))
    if real - syms:
        ev.append("   lib 无法满足的真实导出（前 15）:")
        ev += ["      " + x for x in sorted(real - syms)[:15]]

    problems = []
    if stale:
        problems.append("导入库陈旧：比最新 .def 旧（用陈旧产物验证会产生假结论）")
    if hit != EXPECTED_TOTAL:
        problems.append("lib ∩ real = %d，期望 %d" % (hit, EXPECTED_TOTAL))
    miss = real - syms
    if miss:
        problems.append("lib 无法满足 %d 个真实导出，例: %s"
                        % (len(miss), sorted(miss)[:5]))

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems
            else "自建 lib 覆盖全部 %d 导出且非陈旧" % EXPECTED_TOTAL)


# ---------------------------------------------------------------- A4


def find_generated_sources(extra_dirs: list[str] | None = None) -> list[str]:
    """收集待验的生成 stub .cpp —— 即 DirectUI/src/*.cpp。

    产物不路过 .local/（契约第 157 行），因此默认根是 OUT/src。
    仍然排除 `tmp-*`/`_*` 邻域，避免把他人探针 TU 当成生成物。
    """
    roots: list[str] = list(extra_dirs or [])
    if not roots:
        if os.path.isdir(OUT_SRC):
            roots.append(OUT_SRC)
    srcs: list[str] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            # 排除明显的临时/探针目录
            dirs[:] = [d for d in dirs if not d.startswith(("tmp-", "tmp_", "_"))]
            for f in files:
                if f.lower().endswith(".cpp"):
                    srcs.append(os.path.join(dirpath, f))
    return sorted(set(srcs))


def check_modname_fidelity(ctx: Ctx, src_dirs: list[str] | None = None) -> None:
    aid, title = ("A4", "modname 保真：DirectUI/src 编译出的装饰符号 vs "
                         "pinned/exports.json ∪ symbols(is_exported=false)")
    srcs = find_generated_sources(src_dirs)
    objs: list[str] = []
    compile_failures: list[str] = []   # 本次运行中 rc!=0（或未产出 .obj）的源文件

    cmds: list[str] = []
    ev: list[str] = []
    ev.append("已发现的生成 stub .cpp: %d 个（%s）" % (len(srcs), OUT_SRC))
    for s in srcs[:10]:
        ev.append("   src: %s" % s)
    if not srcs:
        ev.append("")
        ev.append("说明：A4 只校验 **生成器产出的 stub 源码**（DirectUI/src/*.cpp）。")
        ev.append("UITest.obj 是验收程序自身的编译单元，**不是 stub 生成物**，")
        ev.append("纳入 A4 会产生假 FAIL。它的导入表正确性已由 A5 独立校验。")
        ctx.add(aid, title, Verdict.SKIP, cmds or ["<no generated .cpp>"],
                ev, "生成器尚未产出 stub 源码（DirectUI/src 为空）—— A4 无法执行（非通过）")
        return

    # 若存在生成源码，独立编译成 .obj
    if srcs and os.path.isfile(CL):
        env, env_note = msvc_env()
        ev.append("编译环境：%s" % env_note)
        if env is None:
            ctx.add(aid, title, Verdict.SKIP, cmds,
                    ev + ["无法取得 MSVC 编译环境（INCLUDE 缺失）"],
                    "cl.exe 缺少标准头搜索路径，无法独立编译 stub")
            return
        os.makedirs(STUB_OBJ_DIR, exist_ok=True)
        incs = []
        gi = OUT_INCLUDE
        if os.path.isdir(gi):
            incs += ["/I" + gi]
        incs += ["/I" + REPO]
        for src in srcs:
            base = os.path.splitext(os.path.basename(src))[0]
            obj = os.path.join(STUB_OBJ_DIR, base + ".obj")
            # 先删除旧 .obj：否则上一次成功编译遗留的文件会让本次失败被误判为成功
            # （残留 .obj 会使上一次的成功状态继续显示）。
            if os.path.isfile(obj):
                try:
                    os.remove(obj)
                except OSError:
                    pass
            cmd = [CL, "/nologo", "/c", "/EHsc", "/std:c++17", "/D_AMD64_",
                   "/DUNICODE", "/D_UNICODE"] + incs + ["/Fo" + obj, src]
            cmds.append(" ".join(q(c) for c in cmd))
            rc, out, err = run(cmd, timeout=900, env=env)
            ev.append("cl.exe %s -> rc=%d" % (os.path.basename(src), rc))
            if rc != 0:
                ev += ["   " + l for l in tail(out + err, 12)]
                compile_failures.append(base)
            elif os.path.isfile(obj):
                objs.append(obj)
            else:
                compile_failures.append(base)
                ev.append("   rc=0 但未产出 .obj")

    if not objs:
        # 关键区分：**源码存在但全部编译失败** = 生成器缺陷（必须 FAIL）；
        # 只有**源码本身不存在**才算"尚未就绪"（SKIP）。
        if srcs:
            ctx.add(aid, title, Verdict.FAIL, cmds or ["<no .cpp found>"],
                    ev + ["找到了 %d 个 stub 源文件，但无一能编译成功" % len(srcs)],
                    "全部 %d 个 stub 源文件编译失败 —— 生成器产出了无法编译的 C++，"
                    "这是生成器缺陷而非“尚未就绪”" % len(srcs))
        else:
            ctx.add(aid, title, Verdict.SKIP, cmds or ["<no .cpp found>"],
                    ev + ["未找到任何生成 stub 源码"],
                    "DirectUI/src 尚未生成 —— stub 源码不存在（非通过）")
        return

    real = set(load_real())
    pdb = load_pdb_publics()
    union = real | pdb
    all_defined: set[str] = set()
    all_undef: set[str] = set()
    per_obj: list[str] = []
    for obj in objs:
        cmds.append("dumpbin /symbols %s" % obj)
        syms = obj_symbols(obj)
        all_defined |= syms["defined"]
        all_undef |= syms["undefined"]
        hit = syms["defined"] & real
        per_obj.append("%s: 已定义 %d, 未定义 %d, 已定义∩真实导出 %d"
                       % (os.path.basename(obj), len(syms["defined"]),
                          len(syms["undefined"]), len(hit)))
    ev += per_obj

    # ============ A4 的判定语义（重要，避免"求交"式同义反复）============
    # 若把 target 定义为 `obj_defined ∩ real`，则 target ⊆ real 恒成立，
    # 该断言**永真**（vacuous）。因此这里改为：
    #
    #   target := .obj 中已定义、且属于被重建库（DirectUI）的全部名字
    #             —— 完全由**声明侧**决定，与参考集合无关；
    #   reference := pinned/exports.json 的真实导出
    #                ∪ symbols.json 中 is_exported=false 的 mangled（PDB publics）
    #             —— 既接受导出 API，也接受"真实存在但未导出"的内部符号；
    #   unmatched := target - reference
    #
    # 并显式排除编译器**自动合成**的符号（RTTI `??_R*`、scalar/vector deleting
    # destructor `??_G*`/`??_E*`）：它们在真实 DLL 中计数为 0 且 PDB 也没有，
    # 是类布局的副产物、不属"声明保真"范畴；保留它们会让 A4 永远无法通过。
    def is_dui_ns(sym: str) -> bool:
        return bool(re.search(r"@DirectUI@@", sym) or sym.startswith("?DirectUI@"))

    def is_compiler_synth(sym: str) -> bool:
        return sym.startswith(("??_R", "??_G", "??_E"))

    def is_synth_bare_vftable(sym: str) -> bool:
        """编译器在"无 MI 基类 + 有虚方法 + out-of-line 拷贝构造/析构"组合下
        强制落盘的 primary vftable（裸 `6B@` 形态），而真实 DLL 里没有该形态。

        机制链（已用最小探针复现验证）：这些类在 classes.json 无继承条目
        （MI 基类只存在于 PDB publics、不在导出表，导出驱动的继承提取未收录）
        → 虚方法必须 virtual 才能产出 UEAA/MEAA 装饰 → out-of-line 拷贝构造/
        析构定义（真实导出）触发 vptr 初始化 → primary vftable 落盘。
        与 ??_R/??_G/??_E 同性质：编译器强制合成、真实对应物是非导出内部形态。

        判定：`??_7` 前缀 + `6B@` 结尾 + 不在参考并集（导出表 ∪ PDB publics）
        中。真实 DLL 若存在该类的 vftable，形态是**基类限定**的
        （如 ??_7TouchScrollBar@DirectUI@@6BBaseScrollBar@1@@），故裸形态
        必然不在并集里。
        """
        return (sym.startswith("??_7") and sym.endswith("@@6B@")
                and sym not in union)

    target = {s for s in all_defined if s.startswith("?") and is_dui_ns(s)}
    target |= {s for s in all_defined
               if not s.startswith("?") and is_dui_ns(s) and not s.startswith("__")}
    synth = {s for s in target if is_compiler_synth(s)}
    # 合成裸 vftable：与 is_compiler_synth 同级豁免（见函数注释的机制链）。
    synth_vft = {s for s in target if is_synth_bare_vftable(s)}
    # 生成器刻意注入的合成锚点（见 SYNTHETIC_ANCHORS 说明）：从判定目标中豁免，
    # 但**单独统计并披露**，避免"豁免"变成"眼不见为净"。
    anchors = target & SYNTHETIC_ANCHORS
    target_check = target - synth - synth_vft - anchors   # 实际参与判定的目标
    excluded_thirdparty = {s for s in all_defined
                           if s.startswith("?") and not is_dui_ns(s) and not is_junk(s)}

    matched = target_check & union
    unmatched = target_check - union
    matched_export = target_check & real
    unexported_but_real = (target_check & pdb) - real

    # ===== 覆盖率披露（防止把"A4 PASS"误读为"全部 4321 个导出都保真"）=====
    # A4 是**精度**（precision）断言：stub 里出现的 DirectUI 名字必须逐字正确。
    # 它**不是完整性**（recall）断言 —— 只有生成器已覆盖到的类才会出现在 .obj 里。
    # 因此必须显式报告覆盖率，否则 PASS 会被过度解读。
    covered_exports = matched_export
    not_covered = real - covered_exports
    coverage = (100.0 * len(covered_exports) / len(real)) if real else 0.0

    ev.append("")
    ev.append("===== 覆盖率披露（A4 只保证精度，不保证完整性）=====")
    ev.append("真实导出总数           = %d" % len(real))
    ev.append("被本批 stub 逐字覆盖   = %d  (%.1f%%)" % (len(covered_exports), coverage))
    ev.append("尚未被任何 stub 覆盖   = %d" % len(not_covered))
    ev.append("未被覆盖示例（前 10）:")
    ev += ["   " + x for x in sorted(not_covered)[:10]]
    ev.append("说明：A4 通过 = “已生成的部分没有签名错误”，"
              "**不**等于“4321 个导出全部已保真”。")
    ev.append("      完整性需由“导出符号集一致性”类断言（A2/A3）与整体重建进度共同保证。")

    ev.append("")
    ev.append("参考集合：真实导出 = %d，PDB publics = %d，并集 = %d"
              % (len(real), len(pdb), len(union)))
    ev.append("已定义符号总数 = %d" % len(all_defined))
    ev.append("  第三方（std::/wil::/CRT，刻意排除） = %d" % len(excluded_thirdparty))
    ev.append("  DirectUI 命名空间（判定目标，未去合成符号） = %d" % len(target))
    ev.append("    其中编译器自动合成（??_R/??_G/??_E，排除） = %d" % len(synth))
    ev.append("    其中编译器强制落盘的裸 vftable（??_7…@@6B@，排除） = %d" % len(synth_vft))
    if synth_vft:
        ev += ["       " + a for a in sorted(synth_vft)]
    ev.append("    其中生成器刻意注入的合成锚点（见代码注释，排除） = %d" % len(anchors))
    if anchors:
        ev += ["       " + a for a in sorted(anchors)]
    ev.append("  实际判定目标 = %d" % len(target_check))
    ev.append("")
    ev.append("逐字命中参考集合     = %d" % len(matched))
    ev.append("  其中命中**真实导出**   = %d" % len(matched_export))
    ev.append("  其中仅存在于 PDB（真实但未导出，合规） = %d" % len(unexported_but_real))
    ev.append("未命中（真正的不保真） = %d" % len(unmatched))
    if unmatched:
        ev.append("未命中清单:")
        ev += ["   " + u for u in sorted(unmatched)]

    # ===== 裸 vftable 披露（已豁免，但必须全程可见）=====
    # 真实 DLL 里一个类可能有多个**基类限定**的 vftable（??_7C@@6BBase@@），
    # 也可能一个都没有；而生成器在这些类上总是产出裸形态 ??_7C@@6B@。该裸形态
    # 已按"编译器强制合成"豁免（见 is_synth_bare_vftable 的机制链），但豁免
    # 不等于隐藏 —— 这里逐条披露，并把真实 DLL 的对应形态一并列出，便于读者
    # 判断这是"合成代价"而非"保真缺陷"。
    if synth_vft:
        ev.append("")
        ev.append("【已豁免·披露】编译器强制落盘、真实 DLL 无对应形态的裸 vftable"
                  "（%d 个）:" % len(synth_vft))
        for s in sorted(synth_vft):
            cls = s[len("??_7"):-len("@DirectUI@@6B@")]
            # 真实 DLL 中该类的任何 vftable 形态（裸的或基类限定的）
            real_forms = sorted(x for x in union
                                if x.startswith("??_7" + cls + "@DirectUI@@6B"))
            ev.append("   %s" % s)
            if real_forms:
                ev.append("      真实 DLL 形态（基类限定）: %s" % real_forms)
            else:
                ev.append("      真实 DLL 中该类的 vftable 个数 = 0"
                          "（基类只在 PDB、不在导出表，导出驱动的继承提取未收录）")
        ev.append("  说明：机制见 is_synth_bare_vftable() 的注释链；"
                  "豁免仅针对此形态，A4 的 precision 判定不变。")

    # 编译失败必须计入结论 —— 编不出来的声明无法证明 ABI 保真。
    # 这里用**本次运行的返回码**（compile_failures），而不是检查 .obj 是否存在：
    # 磁盘上可能残留上一次成功编译的 .obj，会让失败被误判为成功。
    failed_srcs = compile_failures
    if failed_srcs:
        ev.append("")
        ev.append("编译失败的 stub 源文件（%d 个）:" % len(failed_srcs))
        ev += ["   " + s for s in failed_srcs]

    problems = []
    if not target_check:
        problems.append("未能从 .obj 提取任何 DirectUI 目标修饰名"
                        "（检查 dumpbin /symbols 解析或 stub 是否真的产出符号）")
    if unmatched:
        problems.append("modname 保真失败：%d 个目标修饰名不在参考集合中，例 %s"
                        % (len(unmatched), sorted(unmatched)[:5]))
    if failed_srcs:
        problems.append("%d 个 stub 源文件编译失败（%s）—— 声明无法通过编译，"
                        "ABI 保真无从谈起"
                        % (len(failed_srcs), ", ".join(failed_srcs)))

    detail_bits = ["判定目标 %d 个：命中真实导出 %d、命中 PDB 内部符号 %d、未命中 %d、编译失败 %d"
                   % (len(target_check), len(matched_export),
                      len(unexported_but_real), len(unmatched), len(failed_srcs)),
                   "覆盖率：%d/%d 真实导出（%.1f%%）—— A4 仅断言精度，完整性另计"
                   % (len(covered_exports), len(real), coverage)]
    if problems:
        detail_bits = ["; ".join(problems)] + detail_bits
    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(detail_bits))


# ---------------------------------------------------------------- A5


def check_acceptance_run(ctx: Ctx) -> None:
    aid, title = "A5", "验收复跑：生成的 UITest.exe 成功建窗（MainWindowTitle）"
    exe = UITEST_EXE
    if not os.path.isfile(exe):
        alt = os.path.join(BUILD, "UITest.exe")
        if os.path.isfile(alt):
            exe = alt
        else:
            ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % UITEST_EXE],
                    ["file not found: %s" % UITEST_EXE],
                    "生成的 UITest.exe 尚未产生（尚未构建）")
            return

    ev: list[str] = []
    cmds: list[str] = []
    ev.append(stat_line(exe))
    real = set(load_real())

    # ---- 0) 陈旧性预检 ----
    # 与 A3 同样的教训：用一个比 .def / src 还旧的 exe 做验收，会得到**假 PASS**
    # （旧 exe 连的是旧的 lib，可能刚好能跑起来）。A5 必须确认 exe 不比生成物旧。
    stale_refs: list[tuple[str, float]] = []
    for ref in (OUT_DEF, os.path.join(OUT_SRC, "XProvider.cpp"), GEN_LIB):
        if os.path.isfile(ref):
            stale_refs.append((ref, os.path.getmtime(ref)))
    exe_mt = os.path.getmtime(exe)
    newer = [(p, t) for p, t in stale_refs if t > exe_mt]
    ev.append("")
    ev.append("陈旧性检查（exe 必须不早于生成物与导入库）：")
    ev.append("   %s  %s" % (os.path.relpath(exe, REPO),
                             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exe_mt))))
    for p, t in stale_refs:
        ev.append("   %s  %s" % (os.path.relpath(p, REPO),
                                 time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))))
    stale_exe = bool(newer)
    ev.append("   STALE（exe 早于下列输入，验收结果不可信）= %s%s"
              % (stale_exe, ("：" + ", ".join(os.path.relpath(p, REPO)
                                              for p, _ in newer)) if newer else ""))

    # ---- 1) 静态预检：导入是否都能被真实 dui70.dll 满足 ----
    rc, out, err = run([DUMPBIN, "/imports", exe])
    cmds.append("dumpbin /imports %s" % exe)
    imports: list[str] = []
    inblk = False
    for line in out.splitlines():
        if re.match(r"^\s+\S+\.dll\s*$", line):
            inblk = "dui70" in line.lower()
            continue
        if inblk:
            m = re.match(r"^\s+[0-9A-Fa-f]+\s+(\S+)\s*$", line)
            if m:
                imports.append(m.group(1))
    unsatisfied = [i for i in imports if i not in real]
    ev.append("")
    ev.append("对 dui70.dll 的导入数 = %d" % len(imports))
    ev.append("无法被真实 dui70.dll 满足的导入 = %d" % len(unsatisfied))
    for u in unsatisfied:
        ev.append("   UNSATISFIED: %s" % u)
    if unsatisfied:
        ev.append("=> 加载期必然失败（真实 System32\\dui70.dll 无这些导出名）。")
        ev.append("   常见根因：.def 别名方向写反（`修饰名 = 未修饰名`），")
        ev.append("   使导入表引用修饰名，而真实 DLL 导出、UITest 导入的都是未修饰名。")

    # ---- 2) 直接运行取退出码 ----
    codes = []
    for _ in range(2):
        rcx, _o, _e = run([exe], timeout=30)
        codes.append(rcx & 0xFFFFFFFF)
    STATUS = {
        0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND",
        0xC0000135: "STATUS_DLL_NOT_FOUND",
        0xC0000142: "STATUS_DLL_INIT_FAILED",
        0xC0000005: "STATUS_ACCESS_VIOLATION",
    }
    ev.append("")
    ev.append("直接运行退出码（2 次）: %s" % ", ".join(
        "0x%08X (%s)" % (c, STATUS.get(c, "n/a")) for c in codes))

    # ---- 3) 亲眼观测窗口 ----
    ps = (
        "$ErrorActionPreference='Continue';"
        "try{ $p=Start-Process -FilePath '@EXE@' -PassThru -ErrorAction Stop }"
        "catch{ Write-Output ('START_FAILED=' + $_.Exception.Message); exit 0 };"
        "Start-Sleep -Seconds 3;"
        "try{ $p.Refresh() }catch{ Write-Output 'REFRESH_FAILED' };"
        "Write-Output ('HasExited=' + $p.HasExited);"
        "if(-not $p.HasExited){"
        "  Write-Output ('MainWindowTitle=[' + $p.MainWindowTitle + ']');"
        "  Write-Output ('MainWindowHandle=' + $p.MainWindowHandle);"
        "  $null=$p.CloseMainWindow(); Start-Sleep -Seconds 1;"
        "  if(-not $p.HasExited){ $p.Kill() }"
        "} else {"
        "  $c=$p.ExitCode; Write-Output ('ExitCode=' + $c);"
        "  Write-Output ('ExitCodeHex=0x' + ('{0:X8}' -f ($c -band 0xFFFFFFFF)))"
        "}"
    ).replace("@EXE@", exe.replace("'", "''"))

    cmd = ["pwsh", "-NoProfile", "-Command", ps]
    rc, out, err = run(cmd, timeout=120)
    cmds.append("pwsh -NoProfile -Command \"$p=Start-Process '%s' -PassThru; "
                "$p.Refresh(); $p.MainWindowTitle; $p.MainWindowHandle\"" % exe)
    ev.append("")
    ev.append("窗口观测（Start-Process + Refresh）：")
    ev += ["   " + l for l in out.splitlines() if l.strip()]
    if err.strip():
        ev += ["   stderr: " + l for l in tail(err, 6)]

    title_m = re.search(r"MainWindowTitle=\[(.*)\]", out)
    has_exited_m = re.search(r"HasExited=(\w+)", out)
    hwnd_m = re.search(r"MainWindowHandle=(\d+)", out)
    got_title = title_m.group(1).strip() if title_m else ""

    ev.append("")
    ev.append("判定依据：HasExited=%s  MainWindowTitle=%r  MainWindowHandle=%s"
              % (has_exited_m.group(1) if has_exited_m else "?",
                 got_title, hwnd_m.group(1) if hwnd_m else "?"))

    problems = []
    if stale_exe:
        problems.append("UITest.exe 陈旧：比生成物/导入库旧（用陈旧产物验收会产生假 PASS）；"
                        "先重跑 run.ps1 或 gen_uitest_proj.ps1")
    if unsatisfied:
        problems.append("导入表有 %d 个符号真实 DLL 不提供 -> 加载期失败" % len(unsatisfied))
    if codes and all(c in STATUS for c in codes):
        problems.append("进程以 NTSTATUS 0x%08X (%s) 启动失败"
                        % (codes[0], STATUS.get(codes[0], "")))
    if has_exited_m and has_exited_m.group(1) == "True":
        problems.append("进程已退出，未保持窗口")
    if got_title != EXPECTED_WINDOW_TITLE:
        problems.append("MainWindowTitle=%r，期望 %r" % (got_title, EXPECTED_WINDOW_TITLE))

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems
            else "亲眼观测到 MainWindowTitle == %r（HWND=%s）"
                 % (got_title, hwnd_m.group(1)))


def _git_tracked(path: str) -> bool:
    """该文件是否已被 git 跟踪（用于把「已入库手写文件」与漂移区分开）。"""
    try:
        rc, _o, _e = run(["git", "-C", REPO, "ls-files", "--error-unmatch",
                          os.path.relpath(path, REPO)], timeout=60)
        return rc == 0
    except Exception:  # noqa: BLE001
        return False


def _tree_hashes(root: str) -> dict[str, str]:
    """递归散列目录下所有文件的相对路径 -> sha256（用于 byte-diff 比较）。"""
    import hashlib
    out: dict[str, str] = {}
    if not os.path.isdir(root):
        return out
    for dp, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(("tmp-", "tmp_", "_")))
        for f in sorted(files):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            h = hashlib.sha256()
            try:
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
            except OSError as exc:
                out[rel] = "<unreadable: %s>" % exc
                continue
            out[rel] = h.hexdigest()
    return out


def check_determinism(ctx: Ctx) -> None:
    """A6 确定性断言：regen 两次产物 byte-diff == 0（契约第 20 行不变量）。

    契约第 20 行：`pinned → DirectUI/` 段必须是**纯 Python、确定性**的；
    第 175 行 CI golden job 即 `regen.py` 后 `git diff --exit-code DirectUI/`。
    本断言独立复现该不变量：跑两次 regen 到两个隔离目录，逐文件 sha256 比对，
    并额外与**当前 DirectUI/** 比对（若存在），从而把"生成器确定性"与
    "仓库产物是否为最新生成结果"分开报告。
    """
    aid, title = "A6", "确定性：regen 两次产物 byte-diff == 0（golden 不变量）"
    regen = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regen.py")
    cmds: list[str] = []
    ev: list[str] = []
    problems: list[str] = []

    if not os.path.isfile(regen):
        ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % regen], ["<missing>"],
                "regen.py 不存在 —— 无法验证确定性")
        return
    if not os.path.isdir(PINNED):
        ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % PINNED], ["<missing>"],
                "pinned/ 不存在 —— 无法验证确定性")
        return

    a = os.path.join(SCRATCH, "regen-a")
    b = os.path.join(SCRATCH, "regen-b")
    for d in (a, b):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    for out_dir, tag in ((a, "第 1 次"), (b, "第 2 次")):
        cmd = [PYTHON, regen, "--pinned", PINNED, "--out", out_dir]
        cmds.append(" ".join(q(c) for c in cmd))
        rc, out, err = run(cmd, timeout=600)
        ev.append("%s regen.py -> rc=%d" % (tag, rc))
        if rc != 0:
            ev += ["   " + l for l in tail(out + err, 15)]
            problems.append("regen.py %s 失败 rc=%d" % (tag, rc))

    ha = _tree_hashes(a)
    hb = _tree_hashes(b)
    ev.append("")
    ev.append("第 1 次产物文件数 = %d" % len(ha))
    ev.append("第 2 次产物文件数 = %d" % len(hb))
    only_a = sorted(set(ha) - set(hb))
    only_b = sorted(set(hb) - set(ha))
    diff = sorted(k for k in set(ha) & set(hb) if ha[k] != hb[k])
    ev.append("仅第 1 次有 = %d %s" % (len(only_a), only_a[:5]))
    ev.append("仅第 2 次有 = %d %s" % (len(only_b), only_b[:5]))
    ev.append("内容不同的文件 = %d %s" % (len(diff), diff[:10]))
    if only_a or only_b or diff:
        problems.append("regen 非确定性：文件数差 %d/%d，内容差 %d 个 %s"
                        % (len(only_a), len(only_b), len(diff), diff[:5]))
    else:
        ev.append("=> 两次 regen 产物逐字节一致（%d 个文件）" % len(ha))

    # 与仓库中当前 DirectUI/ 比对：确认产物是否为最新生成结果。
    # 注意：这是**漂移**（drift）而非**确定性**。契约第 137 行的 golden test
    # 才是"仓库产物必须等于 regen 结果"的断言；A6 只断言
    # "regen 两次 byte-diff == 0"。二者混在一起会让"尚未提交 golden"被误报成
    # "生成器不确定"。因此漂移只作**独立披露**，不参与 A6 的 PASS/FAIL。
    drift_note = None
    ev.append("")
    if os.path.isdir(OUT):
        hc = _tree_hashes(OUT)
        ev.append("--- 附加披露：当前 %s 与 regen 结果的漂移 ---" % OUT)
        ev.append("当前 %s 文件数 = %d" % (OUT, len(hc)))
        drift = sorted(k for k in set(ha) & set(hc) if ha[k] != hc[k])
        miss = sorted(set(ha) - set(hc))
        extra = sorted(set(hc) - set(ha))
        ev.append("与 regen 结果内容不一致 = %d %s" % (len(drift), drift[:10]))
        ev.append("regen 有而仓库缺 = %d %s" % (len(miss), miss[:10]))
        ev.append("仓库有而 regen 无 = %d %s" % (len(extra), extra[:10]))
        # 「仓库有而 regen 无」不一定是漂移：DirectUI/README.md 是**手写且已入库**
        # 的文件，regen.py 不产出它。把它算成漂移会误导。这里按「是否被 git 跟踪」
        # 与「是否由 regen 产出」区分：只有 regen 该产出却内容不同/缺失才算漂移。
        hand_written = [p for p in extra if _git_tracked(os.path.join(OUT, p))]
        ev.append("   其中**已入库的手写文件**（regen 本就不产出，不算漂移）= %d %s"
                  % (len(hand_written), hand_written[:10]))
        real_extra = [p for p in extra if p not in hand_written]
        ev.append("   真正多出的未跟踪文件 = %d %s" % (len(real_extra), real_extra[:10]))
        if drift or miss or real_extra:
            drift_note = ("DirectUI/ 与最新 regen 结果存在漂移：内容差 %d、缺 %d、多 %d"
                          "（golden test 会打回；这是**待提交产物**，非生成器缺陷）"
                          % (len(drift), len(miss), len(real_extra)))
            ev.append("=> %s" % drift_note)
        else:
            extra_note = ("（另有 %d 个已入库手写文件 regen 不产出，已排除：%s）"
                          % (len(hand_written), hand_written[:5])) if hand_written else ""
            ev.append("=> DirectUI/ 的 regen 产物与最新 regen 结果完全一致（golden 可入库）%s"
                      % extra_note)
    else:
        ev.append("%s 不存在 —— 跳过漂移披露" % OUT)

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems
            else "两次 regen 逐字节一致（%d 个文件）—— 生成器确定性成立" % len(ha))
    if drift_note:
        ctx.results[-1]["drift"] = drift_note


# ---------------------------------------------------------------- 报告


def write_report(ctx: Ctx, extra: list[str]) -> None:
    counts = Counter(r["verdict"] for r in ctx.results)
    L: list[str] = []
    A = L.append
    A("# dui-pipeline 端到端验证报告（verify.py，独立复算）")
    A("")
    A("生成时间（UTC）：%s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    A("")
    A("## 结论汇总")
    A("")
    A("| 断言 | 说明 | 结论 |")
    A("|---|---|---|")
    for r in ctx.results:
        A("| %s | %s | **%s** |" % (r["id"], r["title"], r["verdict"]))
    A("")
    A("统计：PASS=%d  FAIL=%d  SKIP=%d" % (
        counts[Verdict.PASS], counts[Verdict.FAIL], counts[Verdict.SKIP]))
    A("")
    A("> `SKIP` 表示所需输入文件不存在（上游模块未产出），**不是**通过。")
    A("> `FAIL` 表示输入存在但与契约不符，已给出最小复现。")
    A("")
    if extra:
        A("## 关键发现")
        A("")
        for e in extra:
            A("- " + e)
        A("")

    for r in ctx.results:
        A("## %s %s" % (r["id"], r["title"]))
        A("")
        A("**结论：%s**" % r["verdict"])
        A("")
        if r["detail"]:
            A("```")
            A(r["detail"])
            A("```")
            A("")
        A("命令：")
        A("")
        A("```")
        for c in (r["cmds"] or ["<无>"]):
            A(c)
        A("```")
        A("")
        A("原始输出：")
        A("")
        A("```")
        for e in (r["evidence"] or ["<无>"]):
            A(e)
        A("```")
        A("")

    A("## 断言矩阵")
    A("")
    A("| 断言 | 输入 | 参照（oracle）| 断言什么 | 覆盖边界（**不**断言什么）|")
    A("|---|---|---|---|---|")
    A("| **A1** | pinned/symbols.json | 契约 §1.3 + §103 枚举 | 顶层键恰为 {symbols}；"
      "11983 = 4321 导出 + 7662 非导出；"
      "11 个键在全部条目上恒在；kind 枚举合法；mangled 无重复/空；"
      "`is_exported` 集合 == `exports.json` 的 name 集合；13 个回归目标 |"
      "**不判**语义正确性（名字对不对由 A4 判，条数对不对由 A2/A3 判）|")
    A("| **A2** | `DirectUI/dui70.def`（regen 产物）| `pinned/exports.json` | "
      "4321 条导出名逐条一致（集合相等 + 无多余/缺失）| "
      "**不判**修饰名能否被 MSVC 复现（那是 A4）|")
    A("| **A3** | `.local/build/lib/dui70.lib`（`lib.exe /def:` 产物）| `pinned/exports.json` | "
      "自建导入库覆盖全部 4321 导出，且**非陈旧**（时间戳晚于 .def）| "
      "**不判**符号在真实 DLL 里能否解析（那是 A5）|")
    A("| **A4** | `DirectUI/src/*.cpp` 编译出的 .obj | "
      "`pinned/exports.json` ∪ `symbols.json(is_exported=false)` | "
      "生成声明的**修饰名精度**：编译成功、每个目标修饰名都能在参照集合中找到 | "
      "**只断言精度，不断言完整性**；覆盖率（985/4321 = 22.8%）单独披露。"
      "A4 PASS ≠ “4321 全部保真”|")
    A("| **A5** | `UITest.exe`（链接自建 lib）| 运行期观察 + 系统 `dui70.dll` | "
      "进程存活、窗口标题 == `Microsoft DirectUI Test`、加载的是 SYSTEM32 的真实 DLL | "
      "**不判**每个 API 的行为正确性（只证明 ABI 可用）|")
    A("| **A6** | `regen.py` 两次运行的输出树 | 自身（byte-diff）| "
      "两次 regen 逐字节一致（确定性/golden 不变量）| "
      "**不断言**仓库 `DirectUI/` 是否已是最新（那是 CI golden job 的 "
      "`git diff --exit-code`；漂移仅在本报告“附加披露”中给出）|")
    A("")
    A("## schema 缺什么字段（A1 自洽检查的产出）")
    A("")
    A("A1 只做自洽性检查，但顺带暴露了**契约文本与数据现实不一致**的地方，属于契约层面的待办：")
    A("")
    A("| # | 发现 | 数据 | 影响 / 建议 |")
    A("|---|---|---|---|")
    A("| 1 | `rva` 对 6 个 `__guard_*` 符号为 `null` | 6 条数据符号（`__guard_eh_cont_count`、"
      "`__guard_fids_count`、`__guard_flags`、`__guard_iat_count`、`__guard_longjmp_count`、"
      "`__guard_longjmp_table`）无 RVA | 它们是 CFG 计数/标志，**本就不占 RVA**。"
      "契约需写明“rva 可为 null 及其判定规则”，否则会被当成缺字段 |")
    A("| 2 | 哪些 kind 允许哪些字段为 `null` 未逐项规定 | "
      "`member` 为 null 1454 条（`data` 1097 + `unknown` 357）；"
      "`return_type` 为 null 4613 条；`class` 为 null 4296 条 | 契约已声明“值可为 null”，"
      "但未逐 kind 列出规则；下游按 kind 解引用时仍需自行判断 |")
    A("| 3 | `data` 却带非空 `params` | **8** 条（函数指针型全局变量，如 "
      "`?g_pfnLoggingCallback@details@wil@@...`）| 契约若把 `params` 定义为"
      "“仅函数类 kind 可用”，需为这 8 条开例外或改述 |")
    A("| 4 | `manifest.json` 的 `pinned_utc` 是占位值 | `2026-10-01T00:00:00Z` | "
      "非真实提取时间；若下游用它做“陈旧判定”会失真。本报告 A3 用**文件 mtime** 判陈旧 |")
    A("")
    A("> 以上均为**契约文本**与**数据现实**的差异，不是数据缺陷。")
    A("")

    A("## 复现方式")
    A("")
    A("```")
    A("%s %s" % (PYTHON, os.path.abspath(__file__)))
    A("%s %s --self-test" % (PYTHON, os.path.abspath(__file__)))
    A("# CI 单断言模式：")
    A("%s %s --assertion A3 --lib .local/build/lib/dui70.lib" % (PYTHON, os.path.abspath(__file__)))
    A("%s %s --assertion A4" % (PYTHON, os.path.abspath(__file__)))
    A("```")
    A("")
    A("## CI 三层 × 断言覆盖矩阵")
    A("")
    A("| CI job | runner | 覆盖断言 | 命令 |")
    A("|---|---|---|---|")
    A("| golden | ubuntu | 无（regen.py + `git diff --exit-code DirectUI/`）| 纯 Python，不依赖 MSVC |")
    A("| abi | windows | **A3 + A4** | `--assertion A3 --lib <自建 lib>`、`--assertion A4` |")
    A("| smoke | windows | **A5**（+ A2 前置）| `run.ps1`，窗口标题 + SYSTEM32 断言 |")
    A("")
    A("全量 A1–A6 在本地/验收时跑；CI 按 job 拆分以省时间。")
    A("")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


CHECKS = {
    "A1": check_symbols_json,
    "A2": check_def,
    "A3": check_gen_lib,
    "A4": check_modname_fidelity,
    "A5": check_acceptance_run,
    "A6": check_determinism,
}


# ---------------------------------------------------------------- self-test


def self_test() -> int:
    """用受控夹具证明 A4 的判定逻辑正确（能 PASS 也能 FAIL），并复算 A2/A3 口径。

    夹具构造（写入 .local/audit/_selftest/）：
      good.cpp —— 声明 2 个与真实 DLL 逐字一致的 DirectUI 符号 + 1 个 std:: 噪声；
                   期望 A4 = PASS，且 std:: 噪声被排除。
      bad.cpp  —— 同一个函数但参数类型故意不同（int 而非 long）；
                   期望 A4 = FAIL 并能指出该符号。
    """
    root = os.path.join(REPO, r".local\audit\_selftest")
    os.makedirs(root, exist_ok=True)
    real = load_real()

    ok = True
    print("=" * 68)
    print("verify.py self-test：A4 modname 保真判定逻辑")
    print("=" * 68)

    # 选取真实导出中的两个可稳定重建的符号作为夹具
    c_api = next(n for n in real if n == "InitProcessPriv")
    mangled = "?SetVisible@Element@DirectUI@@QEAAJ_N@Z"
    if mangled not in real:
        mangled = next(n for n in sorted(real)
                       if n.startswith("?") and "@DirectUI@@" in n and "QEAAJ" in n
                       and "PEB" not in n and "PEAV" not in n)
    print("夹具目标符号：%s" % c_api)
    print("              %s" % mangled)

    # --- good 夹具：完全一致的声明
    good_src = os.path.join(root, "good.cpp")
    with open(good_src, "w", encoding="utf-8") as fh:
        fh.write(
            '#include <windows.h>\n'
            'typedef const wchar_t* UCString;\n'
            'extern "C" long __cdecl InitProcessPriv(int, UCString, char, bool);\n'
            'extern "C" long __cdecl InitProcessPriv(int, UCString, char, bool) { return 0; }\n'
            'namespace DirectUI {\n'
            'struct Element {\n'
            '    long __cdecl SetVisible(bool);\n'
            '};\n'
            'long __cdecl Element::SetVisible(bool) { return 0; }\n'
            '}\n'
            'namespace std { template<class T> struct Noise { void f() {} }; '
            'template struct Noise<int>; }\n'
        )

    # --- bad 夹具：参数类型故意错误（int 而非 bool -> 修饰名不同）
    bad_src = os.path.join(root, "bad.cpp")
    with open(bad_src, "w", encoding="utf-8") as fh:
        fh.write(
            '#include <windows.h>\n'
            'namespace DirectUI {\n'
            'struct Element {\n'
            '    long __cdecl SetVisible(int);\n'
            '};\n'
            'long __cdecl Element::SetVisible(int) { return 0; }\n'
            '}\n'
        )

    # --- pdb 夹具：声明一个**真实存在但未导出**的 PDB 内部符号。
    # 若 A4 只用导出集合做参考，这个夹具会假 FAIL —— 用来证明新语义正确。
    pdb = load_pdb_publics()
    real_set = set(real)
    pdb_only = None
    for cand in sorted(pdb - real_set):
        if re.match(r"^\?_[A-Za-z]\w*@TouchButton@DirectUI@@", cand):
            pdb_only = cand
            break
    pdb_src = None
    if pdb_only:
        pdb_src = os.path.join(root, "pdbonly.cpp")
        with open(pdb_src, "w", encoding="utf-8") as fh:
            # PDB 里该符号是 **private**（`AE`），所以用 class 让成员默认私有，
            # 否则会得到 `QE`(public) 而修饰名不同 —— 那正是 A4 要抓的差异。
            fh.write(
                '#include <windows.h>\n'
                'namespace DirectUI {\n'
                'class TouchButton {\n'
                '    void __cdecl _UpdateAccState(bool, bool);\n'
                '};\n'
                'void __cdecl TouchButton::_UpdateAccState(bool, bool) {}\n'
                '}\n'
            )

    # --- broken 夹具：无法编译的源码，期望 A4 至少不 PASS
    broken_src = os.path.join(root, "broken.cpp")
    with open(broken_src, "w", encoding="utf-8") as fh:
        fh.write("namespace DirectUI { struct X { void f() } }\n")  # 故意缺分号

    cases = [("GOOD", good_src, "PASS"), ("BAD", bad_src, "FAIL")]
    if pdb_src:
        cases.append(("PDBONLY", pdb_src, "PASS"))
    cases.append(("BROKEN", broken_src, "FAIL"))

    for label, src, expect in cases:
        d = os.path.join(root, label.lower())
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        shutil.copy(src, os.path.join(d, os.path.basename(src)))
        ctx = Ctx()
        check_modname_fidelity(ctx, [d])
        r = ctx.by_id("A4")
        verdict = r["verdict"]
        status = "OK " if verdict == expect else "!! "
        if verdict != expect:
            ok = False
        print("%s%-8s 夹具 -> A4=%-4s（期望 %s）" % (status, label, verdict, expect))
        print("       detail: %s" % r["detail"][:170])

    print()
    if ok:
        print("SELF-TEST: PASS —— A4 接受正确声明、拒绝错误签名、"
              "接受 PDB 内部符号、拒绝无法编译的源码")
    else:
        print("SELF-TEST: FAIL —— A4 判定逻辑不可信")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dui-pipeline end-to-end checks (A1-A6)")
    ap.add_argument("--assertion", default="",
                    help="只跑指定断言，逗号分隔（如 A1,A4 或单个 A3）；"
                         "缺省则跑全部")
    ap.add_argument("--lib", default=None,
                    help="覆盖导入库路径（CI 的 abi job 用它指定自建 dui70.lib）")
    ap.add_argument("--vcbin", default=None,
                    help="MSVC 工具目录（含 dumpbin.exe / cl.exe）；默认自动发现")
    ap.add_argument("--json", action="store_true", help="打印机器可读汇总")
    ap.add_argument("--self-test", action="store_true",
                    help="用受控夹具验证 A4 判定逻辑本身是否正确")
    ap.add_argument("--pinned", default=None,
                    help="契约输入目录（默认 <repo>/pinned）")
    ap.add_argument("--out", default=None,
                    help="生成物目录（默认 <repo>/DirectUI）")
    ap.add_argument("--report", default=None,
                    help="报告输出路径（默认 .local/audit/pipeline-verification.md）")
    args = ap.parse_args(argv)

    configure(args.pinned, args.out, args.report)
    vc_note = configure_vcbin(args.vcbin)

    # CI：--lib 覆盖导入库路径（run.ps1 的产物位置可能与默认不同）
    if args.lib:
        global GEN_LIB
        GEN_LIB = os.path.abspath(args.lib)

    if args.self_test:
        return self_test()

    sel = args.assertion
    want = [x.strip().upper() for x in sel.split(",") if x.strip()] or list(CHECKS)
    unknown = [a for a in want if a not in CHECKS]
    if unknown:
        print("[FATAL] 未知断言 id: %s（可用: %s）"
              % (", ".join(unknown), ", ".join(sorted(CHECKS))))
        return 2
    ctx = Ctx()
    extras: list[str] = []
    before_fp = build_tree_fingerprint()

    # 前置校验：真实导出集合（所有断言的参照）
    if not os.path.isfile(EXPORTS_JSON):
        print("[FATAL] pinned/exports.json 不存在: %s" % EXPORTS_JSON)
        print("        （可先用 --pinned 指定契约输入目录）")
        return 2
    real = load_real()
    print("pinned  : %s" % PINNED)
    print("out     : %s" % OUT)
    print("MSVC    : %s" % vc_note)
    print("真实导出集合: %d 条 (%s)" % (len(real), EXPORTS_JSON))
    if len(real) != EXPECTED_TOTAL:
        extras.append("真实导出集合为 %d 条，契约期望 %d —— 后续断言基线可能失真"
                      % (len(real), EXPECTED_TOTAL))
    print()

    for aid in want:
        fn = CHECKS.get(aid)
        if fn is None:
            print("[WARN] 未知断言 id: %s" % aid)
            continue
        try:
            fn(ctx)
        except Exception as exc:  # noqa: BLE001 - 报告里必须记录异常而不是崩掉
            import traceback
            ctx.add(aid, "断言执行异常", Verdict.FAIL, ["<内部异常>"],
                    traceback.format_exc().splitlines(),
                    "%s: %s" % (type(exc).__name__, exc))
        print()

    # 竞态守卫：若产物在验证期间被改写，任何 FAIL 都可能是"半写状态"造成的假 FAIL。
    # 此时在报告里降级说明，避免把假 FAIL 当成真实缺陷。
    race = check_build_quiescent(before_fp)
    if race:
        extras.append("**并发写入告警**：%s。若有 FAIL，可能是产物正被并发重写"
                      "导致的假 FAIL —— 请等其停止后复跑确认。" % "；".join(race))
        print("[WARN] %s" % "；".join(race))

    write_report(ctx, extras)

    counts = Counter(r["verdict"] for r in ctx.results)
    print("=" * 68)
    print("PASS=%d  FAIL=%d  SKIP=%d" % (
        counts[Verdict.PASS], counts[Verdict.FAIL], counts[Verdict.SKIP]))
    print("报告: %s" % REPORT)
    if args.json:
        print(json.dumps([{k: r[k] for k in ("id", "verdict", "detail")}
                          for r in ctx.results], ensure_ascii=False, indent=2))
    return 1 if counts[Verdict.FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
