#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py -- dui-pipeline 端到端独立校验（verifier 实现）

契约：tools/dui-pipeline/INTERFACE.md
报告：.local/audit/pipeline-verification.md

断言清单
--------
A1  symbols.json 自洽：条数、字段完整性、枚举值合法、无重复 mangled
A2  生成的 .def 与真实导出表逐条一致（set 比较，报差集）
A3  生成的导入库（lib.exe /def 产物）符号集与 .def 一致
A4  **modname 保真（最重要）**：生成的 stub 源码编译出的 .obj，用 dumpbin /symbols
    取修饰名集合，与真实导出集合求交 —— 目标子集必须 100% 逐字匹配
A5  验收复跑：独立运行生成的 UITest.exe，Get-Process 查
    MainWindowTitle == "Microsoft DirectUI Test"

设计原则
--------
* 产物可能尚未就绪 —— 每个断言独立判定 PASS / FAIL / SKIP，绝不因为缺文件而中断。
* SKIP 表示"输入不存在"，与 FAIL（输入存在但不符预期）严格区分。
* 所有子进程原始输出落入报告，便于复核。

用法
----
  python verify.py                 # 全部断言
  python verify.py --only A1,A4    # 只跑指定断言
  python verify.py --json          # 额外打印机器可读汇总
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

# ---------------------------------------------------------------- 环境常量

REPO = r"Z:\repos\DirectUI"
PYTHON = r"C:\Users\7mile\AppData\Local\Programs\Python\Python311\python.exe"
VCBIN = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64"
)
DUMPBIN = os.path.join(VCBIN, "dumpbin.exe")
LIBEXE = os.path.join(VCBIN, "lib.exe")
CL = os.path.join(VCBIN, "cl.exe")
LLVM = r"C:\Local\Tools\mingw64\bin"

REAL_NORM = os.path.join(REPO, r".local\cache\real-x64-norm.txt")
PDB_CSV = os.path.join(REPO, r".local\cache\pdb-symbols-x64.csv")
REAL_DLL = r"C:\Windows\System32\dui70.dll"
BUILD = os.path.join(REPO, r".local\build")
GENERATED = os.path.join(BUILD, "generated")
SYMBOLS_JSON = os.path.join(BUILD, "symbols.json")
EXPORTS_JSON = os.path.join(BUILD, "exports.json")
GEN_DEF = os.path.join(BUILD, "dui70-full.def")
GEN_LIB = os.path.join(BUILD, "dui70-full.lib")
UITEST_EXE = os.path.join(BUILD, "acceptance-x64", "UITest.exe")
UITEST_OBJ = os.path.join(BUILD, "acceptance-x64", "UITest.obj")
STUB_OBJ_DIR = os.path.join(BUILD, "verify-obj")
REPORT = os.path.join(REPO, r".local\audit\pipeline-verification.md")

EXPECTED_TOTAL = 4321
EXPECTED_GOLDEN = 3198
EXPECTED_WINDOW_TITLE = "Microsoft DirectUI Test"

KINDS = {"method", "static_method", "ctor", "dtor", "operator", "free_function",
         "data", "vftable", "c_api", "template", "unknown"}
ACCESS = {"public", "protected", "private"}
STATUS = {"identical", "param_changed", "missing", "new", "removed"}
CALLCONV = {"__cdecl", "__stdcall", "__thiscall", "__fastcall", "__vectorcall"}

REQUIRED_SYMBOL_FIELDS = [
    "mangled", "undecorated", "rva", "ordinal", "is_exported",
    "kind", "scope", "namespace", "class", "member",
    "access", "is_virtual", "is_static", "is_const", "callconv",
    "return_type", "params", "is_template", "is_operator", "baseline_status",
]

# 已上报并转交修复的历史缺陷。即使当前复跑已 PASS，也必须在报告里保留痕迹 ——
# 审计痕迹比"干净报告"更有价值（Lead 明确要求）。
KNOWN_DEFECTS = [
    {
        "id": "D1",
        "title": "meta.file_version 把 x64 写成 x86 的版本号",
        "detail": ("symbols.json/exports.json 的 meta.dll 指向 System32（x64），"
                   "file_version 却写成 10.0.26100.9278（SysWOW64/x86 的版本）；"
                   "x64 实际为 10.0.26100.8875。已转交 symbols 模块修复。"),
        "reported_utc": "2026-09-30T09:5x",
        "probe": "verify.py A1 的 file_version 校验",
    },
    {
        "id": "D2",
        "title": "19 个数据符号（函数指针/数组）被误分类为 free_function",
        "detail": ("undecorated 形如 `... (*name)(...)` / `... name[N]`，是变量而非函数，"
                   "callconv 因此为 None；其中 ?g_rgMouseMap@HWNDHost@DirectUI@@0QAY02$$CBIA "
                   "是**真实导出**，契约第 131 行应归 kind='data'。"
                   "若按 free_function 生成声明，会产出 return_type=None 的荒谬签名，"
                   "并直接导致 A4 失败。已转交 symbols 模块修复。"),
        "reported_utc": "2026-09-30T09:5x",
        "probe": "verify.py A1 的 callconv/kind 校验",
    },
    {
        "id": "D3",
        "title": "2 个 vftable 的 baseline_status 判为 identical，实为 removed",
        "detail": ("??_7RichText@DirectUI@@6B@ 与 ??_7TouchButton@DirectUI@@6B@ "
                   "在真实导出集合中**不存在**（dumpbin /exports 实证），基线有；"
                   "按契约第 133 行应为 removed。这也使 symbols.json 全量口径的 "
                   "identical=3200 与黄金集 3198 相差恰好 2。已转交 symbols 模块修复。"),
        "reported_utc": "2026-09-30T09:5x",
        "probe": "baseline_diff.py 交叉验证（exported 口径）",
    },
    {
        "id": "D4",
        "title": "def 别名方向反转（`修饰名 = 未修饰名`）导致 UITest 无法启动",
        "detail": ("MSVC .def 语法为 `导出名 = 内部名`。曾写成 "
                   "`?InitProcessPriv@... = InitProcessPriv`，使导出名变成修饰名；"
                   "真实 DLL 导出的是**未修饰名**，UITest 也按未修饰名导入。"
                   "后果：生成的 UITest.exe 有 5 个导入无法满足，"
                   "直接运行退出码 0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND，"
                   "窗口句柄为 0。已由 lead 改为 alias-shim 方案修复，A5/A6 现均 PASS。"),
        "reported_utc": "2026-09-30T09:3x",
        "probe": "verify.py A5 的 unsatisfied-import + 退出码校验",
    },
    {
        "id": "D5",
        "title": "meta.removed_symbols 把 GetScreenDPI 计了两次（156 而非 155）",
        "detail": ("`meta.removed_symbols` 有 156 条，但真实“只在基线、已不在真实 DLL”"
                   "的**逻辑**符号只有 155 条。差的那 1 条是 `GetScreenDPI`：它同时以"
                   "**未修饰名** `GetScreenDPI` 和**修饰名别名** "
                   "`?GetScreenDPI@DirectUI@@YAHXZ` 出现在列表里，而二者是同一个 API。"
                   "另注：我的 baseline_diff.py 早期版本用 `LIB ∪ DLL` 直接求差，"
                   "把 50 组别名对双计，得出 removed=205（错）；已修为先做别名归一化，"
                   "现产出 155，与 DLL 载体口径一致。"),
        "reported_utc": "2026-09-30T10:0x",
        "probe": "baseline_diff.py 别名归一化 + meta.removed_symbols 组成分析",
    },
    {
        "id": "D6",
        "title": "2 个 stub 源文件无法编译（DUIXmlParser.cpp / Element.cpp）",
        "detail": ("codegen 产出 7 个 stub 源文件，其中 `DUIXmlParser.cpp` 报 "
                   "C2143/C2447/C2059（`_SetValue` 附近缺分号、`__cdecl` 位置非法）、"
                   "`Element.cpp` 报 C2146/C3646/C2761（`_SetValue` 参数解析错误）。"
                   "这属于**生成器缺陷**：声明无法通过编译就谈不上 ABI 保真。"
                   "A4 已把“源码存在但编译失败”从 SKIP 改为 FAIL，"
                   "避免被误当成“尚未就绪”而放过。"),
        "reported_utc": "2026-09-30T10:0x",
        "probe": "verify.py A4 的独立重新编译（cl.exe /c）",
    },
    {
        "id": "D7",
        "title": "13 个「函数指针参数」方法被误判 kind=data 且 params 破碎",
        "detail": ("Element::{Add,SortChildren,GetValue,SetValue,_SetValue,RemoveLocalValue,"
                   "_RemoveLocalValue,_PreSourceChange} 与 DUIXmlParser::{Create,CreateLayout,"
                   "SetGetSheetCallback,SetParseErrorCallback,SetUnknownAttrCallback} 共 13 个 "
                   "class::member 曾被判为 kind='data'，且 params 被反修饰文本切碎"
                   "（出现孤立的 ')'）。由 codegen 在联调中发现、symbols 修复。"
                   "A1 新增三条回归断言锁死：13 目标 kind∈{method,static_method} 且括号配平、"
                   "GetGetSheetCallback 的 return_type 保留函数指针形状、"
                   "哨兵 'kind==data 且 params 含 \")\"' 计数为 0。"),
        "reported_utc": "2026-09-30T10:3x",
        "probe": "verify.py A1 的三条回归断言",
    },
    {
        "id": "D8",
        "title": "DUIXmlParser::GetGetSheetCallback 的 return_type 丢失函数指针形状",
        "detail": ("该函数返回函数指针，但 return_type 一度只剩 `class DirectUI::Value *`，"
                   "丢掉 `(__cdecl *)(unsigned short const *, void *)` 部分，"
                   "会使生成的头文件产出错误签名。已修复；现 return_type 为 "
                   "`class DirectUI::Value * (__cdecl *)(unsigned short const *, void *)`。"
                   "A1 断言其必须含 `(__cdecl *)` / `unsigned short const *` / `void *`。"),
        "reported_utc": "2026-09-30T10:3x",
        "probe": "verify.py A1 的 return_type 形状断言",
    },
]


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


def msvc_env() -> tuple[dict | None, str]:
    """取得可编译 C++ 的环境（INCLUDE/LIB/PATH）。

    cl.exe 直接调用会报 `fatal error C1034: windows.h: no include path set`，
    因为缺少 INCLUDE。这里通过 vcvars64.bat 导出环境并缓存（进程内只做一次）。
    返回 (env 或 None, 说明)。
    """
    global _VCVARS_CACHE
    if _VCVARS_CACHE is not None:
        return _VCVARS_CACHE, "cached"
    vcvars = (r"C:\Program Files\Microsoft Visual Studio\2022\Community"
              r"\VC\Auxiliary\Build\vcvars64.bat")
    if not os.path.isfile(vcvars):
        return None, "vcvars64.bat 不存在: %s" % vcvars
    # 写一个临时 .bat 再执行：内联 `cmd /c "call ... && set"` 在 subprocess
    # 的 list 形式下会被 list2cmdline 重新加引号，导致 cmd 解析失败（实测 rc=1、无输出）。
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


def load_real(path: str = REAL_NORM) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def load_pdb_publics(path: str = PDB_CSV) -> set[str]:
    """读取 PDB publics 名单（契约第 82 行：含非导出内部符号，仅供分析）。

    A4 需要它来判断"某个声明是否为真实存在的 API"：`TouchButton` 的 11 个私有
    方法在真实 DLL 中**未导出**，但 PDB publics 里确实存在（我实证过）。若只用
    导出集合做参考，会把真实的内部符号误判为"生成器凭空捏造"。
    """
    if not os.path.isfile(path):
        return set()
    out: set[str] = set()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            n = (row.get("Name") or "").strip()
            if n:
                out.add(n)
    return out


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

    dumpbin 的行格式（实测，字段数可变，符号名在最后一个 `|` 之后）：
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
    aid, title = "A1", "symbols.json 自洽性（条数/字段/枚举/去重）"
    cmds = ["read %s" % SYMBOLS_JSON]
    if not os.path.isfile(SYMBOLS_JSON):
        ctx.add(aid, title, Verdict.SKIP, cmds,
                ["file not found: %s" % SYMBOLS_JSON],
                "symbols.json 尚未生成（symbols 模块未完成）——无法执行自洽性校验")
        return

    with open(SYMBOLS_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    syms = data.get("symbols", [])
    meta = data.get("meta", {})
    ev: list[str] = []
    problems: list[str] = []

    # 契约第 82 行：publics 含非导出内部符号，**仅供分析，不用于定义导出**。
    # 因此 symbols.json 条数 = 导出(4321) + 非导出 publics，不能简单要求 == 4321。
    exported = [s for s in syms if s.get("is_exported") is True]
    nonexported = [s for s in syms if s.get("is_exported") is not True]
    ev.append("symbols 总条数 = %d" % len(syms))
    ev.append("  is_exported=True  = %d" % len(exported))
    ev.append("  is_exported!=True = %d（契约允许：PDB publics 含非导出内部符号）"
              % len(nonexported))
    ev.append("  meta.source_exports_count = %s" % meta.get("source_exports_count"))
    ev.append("  meta.source_publics_count = %s" % meta.get("source_publics_count"))
    ev.append("  meta.symbols_count        = %s" % meta.get("symbols_count"))

    real = set(load_real())
    exp_names = {s.get("mangled") for s in exported if s.get("mangled")}
    ev.append("  导出符号唯一 mangled = %d" % len(exp_names))
    ev.append("  导出 ∩ 真实导出集合 = %d" % len(exp_names & real))
    if len(real) != EXPECTED_TOTAL:
        problems.append("真实导出集合 %d != %d" % (len(real), EXPECTED_TOTAL))
    if len(exp_names) != EXPECTED_TOTAL:
        problems.append("is_exported=True 的条数 %d != 契约 %d"
                        % (len(exp_names), EXPECTED_TOTAL))
    only_real = real - exp_names
    only_sym = exp_names - real
    if only_real:
        problems.append("导出符号缺 %d 个真实导出，例: %s"
                        % (len(only_real), sorted(only_real)[:5]))
    if only_sym:
        problems.append("导出符号多 %d 个非真实导出，例: %s"
                        % (len(only_sym), sorted(only_sym)[:5]))
    if meta.get("source_exports_count") not in (None, len(real)):
        problems.append("meta.source_exports_count=%s 与真实集合 %d 不一致"
                        % (meta.get("source_exports_count"), len(real)))

    # meta.file_version 必须与 meta.dll 指向文件的**字符串**版本一致。
    # 本机 x64 dui70.dll 的 FixedFileInfo=10.0.26100.9278 而
    # StringFileInfo FileVersion=10.0.26100.8875，二者确实是不同值（微软构建产物
    # 自身的不一致）。契约与产物采用字符串版本，故此处按字符串版本断言；
    # 同时把固化版本一并打印，避免读者误以为是提取 bug。
    dll_path = meta.get("dll") or ""
    actual = file_version_of(dll_path)
    fixed = fixed_file_version_of(dll_path)
    ev.append("meta.dll = %s" % dll_path)
    ev.append("meta.file_version = %s" % meta.get("file_version"))
    ev.append("该文件 StringFileInfo\\FileVersion = %s" % (actual or "<读取失败>"))
    ev.append("该文件 FixedFileInfo 版本        = %s" % (fixed or "<读取失败>"))
    if actual and fixed and actual.split(" ")[0] != fixed:
        ev.append("  注：该文件的字符串版本与固化版本本身不同 —— 微软构建产物自身的不一致，")
        ev.append("      不是提取 bug。按约定以**字符串版本**为准。")
    if actual and meta.get("file_version"):
        if actual.split(" ")[0] != str(meta["file_version"]).split(" ")[0]:
            problems.append("meta.file_version=%s 与 %s 的字符串版本 %s 不符"
                            % (meta.get("file_version"), dll_path, actual))

    # 重复 mangled
    mangled = [s.get("mangled") for s in syms]
    dup = [m for m, c in Counter(mangled).items() if c > 1 and m]
    ev.append("唯一 mangled = %d；重复 = %d" % (len(set(mangled)), len(dup)))
    if dup:
        problems.append("重复 mangled %d 个，例: %s" % (len(dup), dup[:5]))

    # 字段完整性
    missing_field: Counter = Counter()
    for s in syms:
        for f in REQUIRED_SYMBOL_FIELDS:
            if f not in s:
                missing_field[f] += 1
    if missing_field:
        problems.append("缺字段统计: %s" % dict(missing_field))
    ev.append("缺字段: %s" % (dict(missing_field) if missing_field else "无"))

    # 枚举合法性
    # callconv 例外：契约第 134 行只对**函数**规定调用约定；data/vftable/template
    # 等非函数符号没有调用约定，None 是合法值（单独在下文校验函数类符号）。
    bad = Counter()
    for s in syms:
        if s.get("kind") not in KINDS:
            bad["kind=%r" % s.get("kind")] += 1
        if s.get("access") not in ACCESS:
            bad["access=%r" % s.get("access")] += 1
        if s.get("baseline_status") not in STATUS:
            bad["baseline_status=%r" % s.get("baseline_status")] += 1
        if s.get("callconv") is not None and s.get("callconv") not in CALLCONV:
            bad["callconv=%r" % s.get("callconv")] += 1
        if not isinstance(s.get("params"), list):
            bad["params-not-list"] += 1
        if not isinstance(s.get("is_template"), bool):
            bad["is_template-not-bool"] += 1
        if not isinstance(s.get("is_operator"), bool):
            bad["is_operator-not-bool"] += 1
    if bad:
        problems.append("非法枚举值: %s" % dict(list(bad.items())[:10]))
    ev.append("非法枚举值（callconv=None 除外，见下）: %s" % (dict(bad) if bad else "无"))

    # 契约第 139-140 行：无法解析 -> kind unknown 且保留 undecorated；反修饰失败 -> c_api 且 mangled==undecorated
    unk_no_und = [s["mangled"] for s in syms
                  if s.get("kind") == "unknown" and not s.get("undecorated")]
    c_api_bad = [s["mangled"] for s in syms
                 if s.get("kind") == "c_api" and s.get("mangled") != s.get("undecorated")]
    ev.append("kind=unknown 且无 undecorated: %d" % len(unk_no_und))
    ev.append("kind=c_api 但 mangled!=undecorated: %d" % len(c_api_bad))
    if unk_no_und:
        problems.append("kind=unknown 却丢失 undecorated 原文（契约禁止丢弃）")
    if c_api_bad:
        problems.append("kind=c_api 但 mangled != undecorated（契约第 140 行）")

    # callconv 允许为 None：契约第 134 行只对**函数**规定调用约定；
    # data / vftable / template 等非函数符号没有调用约定，None 是合法值。
    cc_none_kinds = Counter(s.get("kind") for s in syms if s.get("callconv") is None)
    ev.append("callconv=None 的符号按 kind 分布 = %s" % dict(cc_none_kinds))
    fn_kinds = {"method", "static_method", "ctor", "dtor", "operator",
                "free_function", "c_api"}
    fn_no_cc = [s for s in syms
                if s.get("kind") in fn_kinds and s.get("callconv") is None]
    ev.append("函数类符号却缺 callconv 的条数 = %d" % len(fn_no_cc))
    if fn_no_cc:
        # 实测根因：这些其实是**数据**符号（函数指针 / 数组），被误分类为 free_function。
        # 判据：undecorated 含 `(*name)` 或 `name[`，说明是变量声明而非函数。
        looks_data = [s for s in fn_no_cc
                      if re.search(r"\(\s*\*", s.get("undecorated") or "")
                      or re.search(r"\)\s*\[", s.get("undecorated") or "")]
        ev.append("  其中形态明显是数据（含 `(*name)` / `)[N]`）的条数 = %d"
                  % len(looks_data))
        ev.append("  明细（前 8）:")
        for s in looks_data[:8]:
            ev.append("     kind=%s mangled=%s"
                      % (s.get("kind"), (s.get("mangled") or "")[:78]))
            ev.append("        undecorated=%s" % (s.get("undecorated") or "")[:110])
            ev.append("        is_exported=%s" % s.get("is_exported"))
        exported_data = [s for s in looks_data if s.get("is_exported") is True]
        ev.append("  其中 is_exported=True（即真实导出也被误分类）= %d" % len(exported_data))
        for s in exported_data:
            ev.append("     %s" % (s.get("mangled") or "")[:90])
        problems.append(
            "%d 个函数类符号缺 callconv；形态分析显示它们是**数据**符号"
            "（函数指针/数组）被误分类为 free_function，其中 %d 个是真实导出"
            "（契约第 131 行应归 kind='data'）"
            % (len(fn_no_cc), len(exported_data)))

    # ===== 新增断言（symbols 修复回归防护，Lead 指定）=====
    # 背景：曾有一批「函数指针参数」的符号被误判为 kind='data'，且 params 被
    # 反修饰文本切碎（出现孤立的 ')'）。以下三条锁死该回归。

    # (1) 13 个曾经出错的 class::member 必须 kind ∈ {method, static_method}，
    #     class/member 正确，且每个 param 括号配平。
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
    by_cm: dict[tuple, list] = {}
    for s in syms:
        by_cm.setdefault((s.get("class"), s.get("member")), []).append(s)

    ev.append("")
    ev.append("===== 回归防护 (1)：13 个曾经误判的 class::member =====")
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
            cls_ok = s.get("class") == cls and s.get("member") == mem
            if not (kind_ok and bal_ok and cls_ok):
                reg_bad.append("%s::%s kind=%s balanced=%s class/member=%s/%s"
                               % (cls, mem, s.get("kind"), bal_ok,
                                  s.get("class"), s.get("member")))
            ev.append("  [%s] %-14s::%-24s kind=%-14s 括号配平=%s nparams=%d"
                      % ("OK" if (kind_ok and bal_ok and cls_ok) else "XX",
                         cls, mem, s.get("kind"), bal_ok, len(pr)))
    if reg_bad:
        problems.append("13 个回归目标不达标: %s" % reg_bad[:6])
    ev.append("  不达标条数 = %d" % len(reg_bad))

    # (2) GetGetSheetCallback 的 return_type 必须保留函数指针形状
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

    # (3) 哨兵：kind=='data' 却带参数（params 含 ')'）的条数必须为 0
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
        problems.append("哨兵失败：%d 个 kind=data 的符号仍带参数（params 未清空或误判未修）"
                        % len(sentinel))

    ctx.add(aid, title, Verdict.FAIL if problems else Verdict.PASS, cmds, ev,
            "; ".join(problems) if problems else "全部自洽（含 13 回归目标 / GetGetSheetCallback / 哨兵）")


# ---------------------------------------------------------------- A2


def build_tree_fingerprint() -> tuple[float, int]:
    """返回 (最新 mtime, 文件数) —— 用于检测"验证期间有人在写产物"。

    实测踩坑：一次全量复跑恰逢 codegen 重写 generated/**（18:31:30），
    A4 因此抓到半写状态的 .cpp 而报"编译失败"，但单独复跑就 PASS。
    这是**竞态**而非真实缺陷；若不检测，会把假 FAIL 报给 Lead。
    """
    newest, count = -1.0, 0
    for root in (BUILD,):
        if not os.path.isdir(root):
            continue
        for dp, dirs, files in os.walk(root):
            # 跳过我们自己的编译产物目录，避免把本脚本的写入当成"他人写入"
            dirs[:] = [d for d in dirs if d not in ("verify-obj",)]
            for f in files:
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
    aid, title = "A2", "生成的 .def 与真实导出表逐条一致"
    cmds = ["read %s" % GEN_DEF, "set compare vs %s" % REAL_NORM]
    if not os.path.isfile(GEN_DEF):
        ctx.add(aid, title, Verdict.SKIP, cmds, ["file not found: %s" % GEN_DEF],
                ".def 尚未生成（lead 的 emit_def.py 未跑完）")
        return

    real = load_real()
    names = def_names(GEN_DEF)
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

    builtin = re.search(r"^\s*LIBRARY\s+(\S+)", open(GEN_DEF, encoding="utf-8",
                                                     errors="replace").read(), re.M)
    ev.append("LIBRARY 语句 = %s" % (builtin.group(1) if builtin else "<缺失>"))

    # ---- 别名方向诊断：真实 DLL 导出的是哪个名字？.def 导出的是哪个名字？----
    aliases = {}  # 导出名 -> 内部名
    for raw in open(GEN_DEF, encoding="utf-8", errors="replace"):
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
            ev.append("   真实 dui70.dll 的导出表用**未修饰 C 名**（实测 dumpbin /exports 见下），")
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
    aid, title = "A3", "生成的导入库符号集与真实导出表一致（含陈旧性检测）"
    cmds: list[str] = []
    ev: list[str] = []

    # 候选导入库：优先取最新且不早于 .def 的那个，避免验证陈旧产物
    candidates = [GEN_LIB, os.path.join(BUILD, "lib", "dui70.lib")]
    defs = [GEN_DEF, os.path.join(BUILD, "lib", "dui70-full.def")]
    existing = [c for c in candidates if os.path.isfile(c)]
    if not existing:
        ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % GEN_LIB],
                ["未找到任何生成的导入库（%s）" % ", ".join(candidates)],
                "导入库尚未生成")
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
            "; ".join(problems) if problems else "所选 lib 覆盖全部 4321 导出且非陈旧")


# ---------------------------------------------------------------- A4


def find_generated_sources(extra_dirs: list[str] | None = None) -> list[str]:
    """收集待验的生成 stub .cpp。

    只承认**真正的生成物目录**：`.local/build/generated/**` 或 `.local/build/<pkg>/`。
    **刻意排除** `.local/build/tmp-*/`、`.local/build/_*.py` 邻域与他人临时目录 ——
    那里是各模块的探针/试验 TU（会引入 std::/wil:: 等无关符号，导致假 FAIL）。
    """
    roots: list[str] = list(extra_dirs or [])
    if not roots:
        gen = GENERATED
        if os.path.isdir(gen):
            roots.append(gen)
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
    aid, title = "A4", "modname 保真：生成 stub 的 .obj 修饰名 vs 真实导出（必须 100%）"
    srcs = find_generated_sources(src_dirs)
    objs: list[str] = []
    compile_failures: list[str] = []   # 本次运行中 rc!=0（或未产出 .obj）的源文件

    cmds: list[str] = []
    ev: list[str] = []
    ev.append("已发现的生成 stub .cpp: %d 个" % len(srcs))
    for s in srcs[:10]:
        ev.append("   src: %s" % s)
    if not srcs:
        ev.append("")
        ev.append("说明：A4 只校验 **codegen 模块产出的 stub 源码**（.local/build/generated/**）。")
        ev.append("UITest.obj 是验收程序自身的编译单元（定义 IElementListener vtable、")
        ev.append("std::function 实例化等），**不是 stub 生成物**，纳入 A4 会产生假 FAIL。")
        ev.append("它的导入表正确性已由 A5 独立校验。")
        ctx.add(aid, title, Verdict.SKIP, cmds or ["<no generated .cpp>"],
                ev, "codegen 模块尚未产出 stub 源码 —— A4 无法执行（非通过）")
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
        gi = os.path.join(GENERATED, "include")
        if os.path.isdir(gi):
            incs += ["/I" + gi]
        incs += ["/I" + os.path.join(BUILD, "acceptance"), "/I" + REPO]
        for src in srcs:
            base = os.path.splitext(os.path.basename(src))[0]
            obj = os.path.join(STUB_OBJ_DIR, base + ".obj")
            # 先删除旧 .obj：否则上一次成功编译遗留的文件会让本次失败被误判为成功
            # （实测踩坑：DUIXmlParser.cpp 修好后，残留 .obj 使失败状态继续显示）。
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
                    "stub 源码尚未产出 —— codegen 模块尚未就绪（非通过）")
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
    # 契约第 162-164 行说「与真实 DLL 的导出集合**求交**，对目标子集必须 100% 匹配」。
    # 若把 target 定义为 `obj_defined ∩ real`，则 target ⊆ real 恒成立，
    # 该断言**永真**（vacuous）。因此这里改为：
    #
    #   target := .obj 中已定义、且属于被重建库（DirectUI）的全部名字
    #             —— 完全由**声明侧**决定，与真实集合无关；
    #   reference := 真实导出 ∪ PDB publics（11983 条）
    #             —— 既接受导出 API，也接受"真实存在但未导出"的内部符号
    #                （PDB 实证：TouchButton 的 11 个私有方法确实在 PDB 中）；
    #   unmatched := target - reference
    #
    # 并显式排除编译器**自动合成**的符号（RTTI `??_R*`、scalar/vector deleting
    # destructor `??_G*`/`??_E*`）：它们在真实 DLL 中计数为 0 且 PDB 也没有，
    # 是类布局的副产物、不属"声明保真"范畴；保留它们会让 A4 永远无法通过。
    def is_dui_ns(sym: str) -> bool:
        return bool(re.search(r"@DirectUI@@", sym) or sym.startswith("?DirectUI@"))

    def is_compiler_synth(sym: str) -> bool:
        return sym.startswith(("??_R", "??_G", "??_E"))

    target = {s for s in all_defined if s.startswith("?") and is_dui_ns(s)}
    target |= {s for s in all_defined
               if not s.startswith("?") and is_dui_ns(s) and not s.startswith("__")}
    synth = {s for s in target if is_compiler_synth(s)}
    target_check = target - synth                       # 实际参与判定的目标
    excluded_thirdparty = {s for s in all_defined
                           if s.startswith("?") and not is_dui_ns(s) and not is_junk(s)}

    matched = target_check & union
    unmatched = target_check - union
    matched_export = target_check & real
    unexported_but_real = (target_check & pdb) - real

    # ===== 覆盖率披露（防止把"A4 PASS"误读为"全部 4321 个导出都保真"）=====
    # A4 是**精度**（precision）断言：stub 里出现的 DirectUI 名字必须逐字正确。
    # 它**不是完整性**（recall）断言 —— 只有 codegen 已覆盖到的类才会出现在 .obj 里。
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
    ev.append("  实际判定目标 = %d" % len(target_check))
    ev.append("")
    ev.append("逐字命中参考集合     = %d" % len(matched))
    ev.append("  其中命中**真实导出**   = %d" % len(matched_export))
    ev.append("  其中仅存在于 PDB（真实但未导出，合规） = %d" % len(unexported_but_real))
    ev.append("未命中（真正的不保真） = %d" % len(unmatched))
    if unmatched:
        ev.append("未命中清单:")
        ev += ["   " + u for u in sorted(unmatched)]

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
                    "生成的 UITest.exe 尚未产生（lead 链接未完成）")
            return

    ev: list[str] = []
    cmds: list[str] = []
    ev.append(stat_line(exe))
    real = set(load_real())

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


def check_baseline_control(ctx: Ctx) -> None:
    """A6 对照实验：基线 UITest.exe 必须能建窗，用于证明 A5 失败非环境问题。"""
    aid, title = "A6", "对照实验：基线 UITest.exe 建窗（排除环境因素）"
    exe = os.path.join(REPO, r"x64\Debug\UITest.exe")
    if not os.path.isfile(exe):
        ctx.add(aid, title, Verdict.SKIP, ["Test-Path %s" % exe], ["<missing>"],
                "基线可执行不存在")
        return
    ps = (
        "$ErrorActionPreference='Continue';"
        "$p=Start-Process -FilePath '@EXE@' -PassThru;"
        "Start-Sleep -Seconds 3; $p.Refresh();"
        "Write-Output ('HasExited=' + $p.HasExited);"
        "if(-not $p.HasExited){"
        "  Write-Output ('MainWindowTitle=[' + $p.MainWindowTitle + ']');"
        "  Write-Output ('MainWindowHandle=' + $p.MainWindowHandle);"
        "  $null=$p.CloseMainWindow(); Start-Sleep -Seconds 1;"
        "  if(-not $p.HasExited){ $p.Kill() }"
        "} else { Write-Output ('ExitCode=' + $p.ExitCode) }"
    ).replace("@EXE@", exe.replace("'", "''"))
    rc, out, err = run(["pwsh", "-NoProfile", "-Command", ps], timeout=120)
    ev = [stat_line(exe)] + ["   " + l for l in out.splitlines() if l.strip()]
    m = re.search(r"MainWindowTitle=\[(.*)\]", out)
    got = m.group(1).strip() if m else ""
    ok = got == EXPECTED_WINDOW_TITLE
    ctx.add(aid, title, Verdict.PASS if ok else Verdict.FAIL,
            ["pwsh -NoProfile -Command \"Start-Process '%s'; $p.MainWindowTitle\"" % exe],
            ev,
            ("基线建窗 MainWindowTitle=%r —— 环境正常，A5 的失败归因于生成物"
             % got) if ok else
            "基线也未建窗（环境异常，A5 结论需重新评估）")


# ---------------------------------------------------------------- 报告


def _defect_status(did: str, ctx: Ctx) -> str:
    """把历史缺陷映射到当前复跑结论，用于报告里的占位说明。"""
    related = {
        "D1": "A1", "D2": "A1", "D3": "A1", "D4": "A5",
        "D5": "A1", "D6": "A4", "D7": "A1", "D8": "A1",
    }.get(did)
    if not related:
        return "—"
    r = ctx.by_id(related)
    if r is None:
        return "本次未执行断言 %s（无法判断）" % related
    if r["verdict"] == Verdict.PASS:
        return "断言 %s 已 PASS —— 修复生效" % related
    if r["verdict"] == Verdict.FAIL:
        return "断言 %s 仍 FAIL —— 修复未生效或仅部分生效，详见该断言原始输出" % related
    return "断言 %s 为 SKIP —— 输入缺失，无法确认" % related


def write_report(ctx: Ctx, extra: list[str]) -> None:
    counts = Counter(r["verdict"] for r in ctx.results)
    L: list[str] = []
    A = L.append
    A("# dui-pipeline 端到端验证报告（verify.py，verifier 独立执行）")
    A("")
    A("生成时间（UTC）：%s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    A("执行者：verifier（独立验证者，不采信任何其他模块的自述结论）")
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

    A("## 历史缺陷与修复状态（审计痕迹，按 Lead 要求保留）")
    A("")
    A("本节**不随当前复跑结果删除**。即使缺陷已修，也保留发现→上报→修复的完整链路，")
    A("以便审计追溯「谁在何时发现了什么」。当前复跑结论见上方汇总表。")
    A("")
    A("| ID | 缺陷 | 上报时间 | 发现手段 | 状态 |")
    A("|---|---|---|---|---|")
    for d in KNOWN_DEFECTS:
        A("| %s | %s | %s | %s | 已转修（见下方复跑结果） |"
          % (d["id"], d["title"], d["reported_utc"], d["probe"]))
    A("")
    for d in KNOWN_DEFECTS:
        A("### %s %s" % (d["id"], d["title"]))
        A("")
        A(d["detail"])
        A("")
        A("#### %s 修复后复跑占位" % d["id"])
        A("")
        A("- 复跑命令：`%s %s`" % (PYTHON, os.path.abspath(__file__)))
        A("- 复跑结果：见上表对应断言的当前结论")
        A("- 状态：%s" % _defect_status(d["id"], ctx))
        A("")

    A("## 复现方式")
    A("")
    A("```")
    A("%s %s" % (PYTHON, os.path.abspath(__file__)))
    A("%s %s --self-test" % (PYTHON, os.path.abspath(__file__)))
    A("```")
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
    "A6": check_baseline_control,
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
        import shutil
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
    ap = argparse.ArgumentParser(description="dui-pipeline end-to-end verifier")
    ap.add_argument("--only", default="", help="逗号分隔的断言 id，如 A1,A4")
    ap.add_argument("--json", action="store_true", help="打印机器可读汇总")
    ap.add_argument("--self-test", action="store_true",
                    help="用受控夹具验证 A4 判定逻辑本身是否正确")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    want = [x.strip().upper() for x in args.only.split(",") if x.strip()] or list(CHECKS)
    ctx = Ctx()
    extras: list[str] = []
    before_fp = build_tree_fingerprint()

    # 真实导出集合的前置校验（所有断言的基础）
    if not os.path.isfile(REAL_NORM):
        print("[FATAL] 真实导出集合不存在: %s" % REAL_NORM)
        return 2
    real = load_real()
    print("真实导出集合: %d 条 (%s)" % (len(real), REAL_NORM))
    if len(real) != EXPECTED_TOTAL:
        extras.append("真实导出集合为 %d 条，契约期望 4321 —— 后续断言基线可能失真"
                      % len(real))
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
    # 此时把结论降级说明，避免把假 FAIL 当成真实缺陷上报。
    race = check_build_quiescent(before_fp)
    if race:
        extras.append("**并发写入告警**：%s。若有 FAIL，可能是 codegen 正在重写产物"
                      "导致的假 FAIL —— 请等其停止后复跑确认。" % "；".join(race))
        print("[WARN] %s" % "；".join(race))

    # 把 baseline oracle 的结论并入报告（若 baseline-diff.md 已存在）
    bd = os.path.join(REPO, r".local\audit\baseline-diff.md")
    if os.path.isfile(bd):
        txt = open(bd, encoding="utf-8", errors="replace").read()
        m = re.search(r"\*\*基线 DLL ∩ 真实 = oracle\*\* \| \*\*(\d+)\*\*", txt)
        if m:
            extras.append("baseline oracle 独立复现：基线 DLL ∩ 真实 = %s"
                          "（契约 %d，%s）" % (m.group(1), EXPECTED_GOLDEN,
                                             "PASS" if int(m.group(1)) == EXPECTED_GOLDEN else "FAIL"))
        if "基线 LIB ∩ 真实 = 3149" in txt or "| 基线 LIB ∩ 真实 | 3149 |" in txt:
            extras.append("**矛盾**：契约第 33 行把 oracle 载体写作 BASELINE_LIB，"
                          "但该 .lib 只能给出 3149；3198 须由基线 DLL 复现。"
                          "详见 baseline-diff.md")

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
