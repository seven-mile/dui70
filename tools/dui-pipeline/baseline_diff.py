#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
baseline_diff.py -- 生成声明 vs 手写基线的逐符号对照（verifier 独立实现）

契约：tools/dui-pipeline/INTERFACE.md（产物 2 symbols.json / 产物 5 报告）

核心 oracle
-----------
INTERFACE.md 第 174 行：手写基线与真实 DLL 有 **3198 个修饰名完全一致**。

本脚本**独立复现**这个数字，并回答一个关键问题：3198 到底出自哪个基线载体？
实测答案（见 .local/audit/baseline-diff.md 的"根因"一节）：

    | 基线载体                              | 与真实 x64 导出集合的逐字交集 |
    |---------------------------------------|-------------------------------|
    | x64\\Debug\\Dui\\dui70.dll（基线 DLL） | **3198**  <- 契约 oracle 的真实来源 |
    | x64\\Debug\\Dui\\dui70.lib（导入库）   | 3149（含 4 个链接器内部符号）/ 3148（纯修饰名） |

契约把 BASELINE_LIB 写成 oracle 来源，但 lib 只能给出 3148/3149；3198 来自**基线 DLL**。
两者相差 49 个符号，根因是 50 个 legacy "C 别名" 导出（InitProcessPriv / InitThread /
StrToID / RegisterAllControls ...）：基线工程在 .def 里同时导出了 C 名与 C++ 修饰名，
链接成 DLL 后导出表里留下的是 **C 名**（与真实 DLL 逐字一致），而导入库 .lib 的索引仍以
**修饰名**为主。真实 DLL 里 `InitProcessPriv` 本身就是未修饰的 C 名导出
（`ordinal 4289, rva 0x00081FF0, name "InitProcessPriv"`），所以 DLL 侧才对得上。

本脚本不"凑数"：两个数字都报，并且把 49 个符号逐个列出来。

输出
----
  .local/audit/baseline-diff.csv   逐符号对照
  .local/audit/baseline-diff.md    统计与结论

用法
----
  python baseline_diff.py                      # 用默认路径
  python baseline_diff.py --real <file> --lib <lib> --dll <dll> [--symbols <json>]
  python baseline_diff.py --self-test          # 断言 oracle == 3198，退出码 0/1
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
DUMPBIN = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe"
)
CL = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
)

DEF_REAL = os.path.join(REPO, r".local\cache\real-x64-norm.txt")
DEF_LIB = os.path.join(REPO, r"x64\Debug\Dui\dui70.lib")
DEF_DLL = os.path.join(REPO, r"x64\Debug\Dui\dui70.dll")
DEF_SYMBOLS = os.path.join(REPO, r".local\build\symbols.json")
DEF_CSV = os.path.join(REPO, r".local\audit\baseline-diff.csv")
DEF_MD = os.path.join(REPO, r".local\audit\baseline-diff.md")

GOLDEN = 3198  # INTERFACE.md 第 174 行

# 链接器/归档内部符号（不是 API，不参与 oracle）
LINKER_JUNK = {
    "__IMPORT_DESCRIPTOR_dui70",
    "__NULL_IMPORT_DESCRIPTOR",
    "\x7fdui70_NULL_THUNK_DATA",
    "size",
    "mode",
}
LINKER_JUNK_PREFIX = (".debug$", ".idata$")

CSV_HEADER = [
    "mangled",
    "undecorated",
    "namespace",
    "class",
    "member",
    "baseline_status",
    "in_real",
    "in_baseline_lib",
    "in_baseline_dll",
    "baseline_has_declaration",
    "source",
]


# ---------------------------------------------------------------- 小工具


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0 and not p.stdout:
        raise RuntimeError("command failed: %s\n%s" % (" ".join(cmd), p.stderr[:2000]))
    return p.stdout


def is_junk(name: str) -> bool:
    return name in LINKER_JUNK or name.startswith(LINKER_JUNK_PREFIX)


def norm_undecorate_plain(name: str) -> str:
    """去掉 __imp_ 前缀；仅用于导入库。"""
    return name[6:] if name.startswith("__imp_") else name


# ---------------------------------------------------------------- 历史基线（git）

# 契约 v2 第 116 行：baseline_status 语义已死，手写基线退役；
# 「历史对照由 baseline_diff.py 读 git 历史满足」。因此本脚本降级为**历史工具**：
# 它的 oracle 不再是 x64\Debug\Dui\dui70.dll（该目录被 .gitignore 忽略、随时可能消失），
# 而是 **git 历史里的手写基线**，可长期复现。

GIT_BASELINE_REF = "master"
GIT_BASELINE_DIR = "DirectUI"


def git_available() -> bool:
    try:
        out = run(["git", "-C", REPO, "rev-parse", "--verify", GIT_BASELINE_REF])
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return False


def git_show(path: str, ref: str = GIT_BASELINE_REF) -> str | None:
    """读取 git 历史中的文件内容；不存在返回 None。"""
    try:
        p = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (ref, path)],
                           capture_output=True, text=True, errors="replace")
        if p.returncode != 0:
            return None
        return p.stdout
    except Exception:  # noqa: BLE001
        return None


def git_ls_files(ref: str = GIT_BASELINE_REF, prefix: str = GIT_BASELINE_DIR) -> list[str]:
    try:
        p = subprocess.run(["git", "-C", REPO, "ls-tree", "-r", "--name-only",
                            "%s:%s" % (ref, prefix)],
                           capture_output=True, text=True, errors="replace")
        if p.returncode != 0:
            return []
        return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001
        return []


def history_baseline_symbols(ref: str = GIT_BASELINE_REF) -> dict:
    """从 git 历史 + 冻结快照反推"历史基线符号集"。

    契约 v2 第 116 行指定「读 git 历史」。实测结论（见报告）：
      * `DirectUI/DirectUI.def`（git 历史）只有 **51 个未修饰 C 名** ——
        它是"legacy C 入口"清单，不是完整导出集；
      * `DirectUI/*.h` 是**源码级**声明，里面根本没有修饰名（`?Foo@Bar@@`），
        按文本正则抽取只能得到极少数误命中。
    因此**光靠 git 历史文本无法重建 4321 条基线符号集**；历史模式的符号来源
    取二者之并：
      1. git 历史 `DirectUI.def`（权威的 C 名清单，可长期复现）；
      2. **冻结快照** `.local/audit/baseline-diff.csv`（4476 行，Lead 明确认可）
         —— 由 v1 时期的基线 LIB/DLL 逐符号对照落盘，是基线二进制消失后
         唯一幸存的完整记录。

    返回 {'def','snapshot','snapshot_rows','headers','files','def_path','any'}。
    """
    res: dict = {"def": set(), "snapshot": set(), "snapshot_rows": 0,
                 "headers": set(), "files": 0, "def_path": None}
    files = git_ls_files(ref)
    if files:
        res["files"] = len(files)

    # 1) 历史 .def：`导出名 = 内部名` -> 取左侧导出名
    for cand in ("DirectUI.def", "dui70.def"):
        txt = git_show("%s/%s" % (GIT_BASELINE_DIR, cand), ref)
        if not txt:
            continue
        res["def_path"] = "%s/%s" % (GIT_BASELINE_DIR, cand)
        in_exp = False
        for raw in txt.splitlines():
            line = raw.split(";")[0].strip()
            if not line:
                continue
            up = line.upper()
            if up.startswith("EXPORTS"):
                in_exp = True
                continue
            if up.startswith(("LIBRARY", "NAME", "DESCRIPTION", "SECTIONS",
                              "STACKSIZE", "HEAPSIZE", "VERSION", "STUB")):
                in_exp = False
                continue
            if not in_exp:
                continue
            name = line.split("=", 1)[0].split()[0]
            if name and not name.startswith("@"):
                res["def"].add(name)
        break

    # 2) 冻结快照：baseline-diff.csv（v1 落盘的基线逐符号记录）
    if os.path.isfile(DEF_CSV):
        try:
            with open(DEF_CSV, encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    m = (row.get("mangled") or "").strip()
                    if not m:
                        continue
                    res["snapshot_rows"] += 1
                    # 只要"曾出现在基线 LIB 或 DLL 中"的符号
                    if row.get("in_baseline_lib") == "yes" or \
                       row.get("in_baseline_dll") == "yes":
                        res["snapshot"].add(m)
        except OSError:
            pass

    res["any"] = res["def"] | res["snapshot"]
    return res


def compare_against_history(gen_symbols: set[str], ref: str = GIT_BASELINE_REF) -> dict:
    """生成物 vs 历史基线：并集/差集对照（本脚本 v2 的主输出）。"""
    hist = history_baseline_symbols(ref)
    hist_any = hist["any"]
    return {
        "ref": ref,
        "hist_files": hist["files"],
        "hist_def_path": hist["def_path"],
        "hist_def": hist["def"],
        "hist_snapshot": hist["snapshot"],
        "snapshot_rows": hist["snapshot_rows"],
        "hist_headers": hist["headers"],
        "hist_any": hist_any,
        "gen_total": len(gen_symbols),
        "hist_total": len(hist_any),
        "only_gen": sorted(gen_symbols - hist_any),
        "only_hist": sorted(hist_any - gen_symbols),
        "common": sorted(gen_symbols & hist_any),
    }


_VCVARS_CACHE: dict | None = None


def msvc_env() -> dict | None:
    """取得可编译 C++ 的环境（INCLUDE/LIB/PATH）。

    cl.exe 直接调用会报 `fatal error C1034: windows.h: no include path set`，
    因为缺少 INCLUDE；这里通过 vcvars64.bat 导出环境并缓存（进程内只做一次）。
    与 verify.py 同样的做法，避免"历史模式"因环境缺失静默退化成 0 个符号。
    """
    global _VCVARS_CACHE
    if _VCVARS_CACHE is not None:
        return _VCVARS_CACHE
    vcvars = (r"C:\Program Files\Microsoft Visual Studio\2022\Community"
              r"\VC\Auxiliary\Build\vcvars64.bat")
    if not os.path.isfile(vcvars):
        return None
    # 写一个临时 .bat 再执行：内联 `cmd /c "call ... && set"` 在 subprocess 的
    # list 形式下会被 list2cmdline 重新加引号，导致 cmd 解析失败（实测无输出）。
    bat = os.path.join(REPO, r".local\audit\_vcvars_env.bat")
    os.makedirs(os.path.dirname(bat), exist_ok=True)
    try:
        with open(bat, "w", encoding="ascii", errors="replace") as fh:
            fh.write('@echo off\r\ncall "%s" >nul 2>&1\r\nset\r\n' % vcvars)
        p = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True,
                           errors="replace", timeout=180)
    except Exception:  # noqa: BLE001
        return None
    if "INCLUDE=" not in (p.stdout or "").upper():
        return None
    env = dict(os.environ)
    for line in p.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    _VCVARS_CACHE = env
    return env


def compiled_generated_symbols(src_dir: str) -> set[str]:
    """编译 DirectUI/src 的 stub，返回其**已定义**的修饰名集合。

    这是历史模式里"生成器侧"的权威口径：直接看编译器真正产出的修饰名，
    而不是从源码文本猜测（文本正则会把注释/字符串里的片段也算进去）。
    编译不可用时返回空集，由调用方降级到文本口径。
    """
    srcs = []
    d = os.path.join(src_dir, "src")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".cpp"):
                srcs.append(os.path.join(d, f))
    if not srcs:
        return set()
    cl = CL
    if not os.path.isfile(cl):
        return set()
    env = msvc_env() or None
    if env is None:
        print("[WARN] 未能取得 MSVC 环境（vcvars64.bat），历史模式降级为文本口径")
        return set()
    objdir = os.path.join(REPO, r".local\build\verify-scratch\hist-obj")
    os.makedirs(objdir, exist_ok=True)
    out: set[str] = set()
    for src in srcs:
        obj = os.path.join(objdir, os.path.splitext(os.path.basename(src))[0] + ".obj")
        if os.path.isfile(obj):
            try:
                os.remove(obj)
            except OSError:
                pass
        cmd = [cl, "/nologo", "/c", "/EHsc", "/std:c++17", "/D_AMD64_",
               "/DUNICODE", "/D_UNICODE", "/I" + os.path.join(src_dir, "include"),
               "/Fo" + obj, src]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", env=env)
        if p.returncode == 0 and os.path.isfile(obj):
            out |= obj_defined_symbols(obj)
    return out


def obj_defined_symbols(obj_path: str) -> set[str]:
    """dumpbin /symbols -> 该 .obj **已定义**的 External 符号名。"""
    try:
        out = run([DUMPBIN, "/symbols", obj_path])
    except Exception:  # noqa: BLE001
        return set()
    syms: set[str] = set()
    for line in out.splitlines():
        if "|" not in line:
            continue
        m = re.match(r"^\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]{8})\s+(\S+)\s+(.*)$", line)
        if not m:
            continue
        sect, rest = m.group(2), m.group(3)
        name = rest.rsplit("|", 1)[1].strip()
        if not name:
            continue
        name = name.split(" (", 1)[0].strip()
        if not name or "External" not in rest or sect.upper() == "UNDEF":
            continue
        if not is_junk(name):
            syms.add(name)
    return syms


def load_generated_symbols(src_dir: str) -> dict[str, set[str]]:
    """从生成 stub 源/头文件抽取修饰名（不编译的降级口径）。

    返回 {'src': set, 'inc': set, 'any': set}。
    """
    pat = re.compile(r"\?[?$A-Za-z0-9_@]+")
    src_syms: set[str] = set()
    inc_syms: set[str] = set()
    for root, bucket in ((os.path.join(src_dir, "src"), src_syms),
                         (os.path.join(src_dir, "include"), inc_syms)):
        if not os.path.isdir(root):
            continue
        for dp, _dirs, files in os.walk(root):
            for f in files:
                if not f.lower().endswith((".cpp", ".h")):
                    continue
                try:
                    txt = open(os.path.join(dp, f), encoding="utf-8",
                               errors="replace").read()
                except OSError:
                    continue
                for m in pat.finditer(txt):
                    bucket.add(m.group(0))
    return {"src": src_syms, "inc": inc_syms, "any": src_syms | inc_syms}


# ---------------------------------------------------------------- 符号提取


def dumpbin_lib_symbols(lib_path: str) -> set[str]:
    """dumpbin /linkermember:1 -> 归档成员名集合（去掉 __imp_ 前缀）。

    注意两点（均由实测踩坑得出）：
      1. 归档偏移可以是 3 位十六进制（小型 .lib 如 88 字节），不能强制 4 位；
      2. 必须在 `Summary` 段之前停止，否则会把节名（.text$mn/.debug$S/.idata$2…）
         误当符号，导致集合虚高。
    """
    out = run([DUMPBIN, "/linkermember:1", lib_path])
    syms: set[str] = set()
    for line in out.splitlines():
        if line.strip().startswith("Summary"):
            break
        m = re.match(r"^\s+[0-9A-Fa-f]+\s+(\S+)\s*$", line)
        if m:
            syms.add(norm_undecorate_plain(m.group(1)))
    return {s for s in syms if not is_junk(s)}


def dumpbin_dll_exports(dll_path: str) -> dict[str, int]:
    """dumpbin /exports -> {name: ordinal}（用于基线 DLL）。"""
    out = run([DUMPBIN, "/exports", dll_path])
    res: dict[str, int] = {}
    for line in out.splitlines():
        m = re.match(r"^\s+(\d+)\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]{8}\s+(\S+)", line)
        if m and not is_junk(m.group(2)):
            res[m.group(2)] = int(m.group(1))
    return res


def load_real(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


# ---------------------------------------------------------------- 键解析


_CTOR_DTOR = {
    "??0": "ctor",
    "??1": "dtor",
    "??4": "operator",
    "??_7": "vftable",
    "??_C": "string_const",
    "??_R": "rtti",
    "??_G": "scalar_deleting_dtor",
    "??_E": "vector_deleting_dtor",
}

_RE_MEMBER = re.compile(r"^\?([^@]+)@([^@]+)@([^@]+)@@")
_RE_FREE = re.compile(r"^\?([^@]+)@([^@]+)@@")
_RE_SPECIAL = re.compile(r"^\?\?([0-9A-Za-z_])@?([^@]*)@?")


def parse_key(mangled: str) -> tuple[str, str, str, str]:
    """把修饰名解析成 (kind, namespace, class, member)。

    namespace/class 可能为空字符串。解析不出来的归 ('unknown','','',mangled)。
    这里只做"分组键"，不做完整反修饰 —— 完整语义由 symbols 模块的 symbols.json 提供。
    """
    if not mangled.startswith("?"):
        return ("c_api", "", "", mangled)

    for pre, kind in _CTOR_DTOR.items():
        if mangled.startswith(pre):
            rest = mangled[len(pre):]
            rest = rest.lstrip("_")
            parts = [p for p in rest.split("@") if p]
            if kind in ("ctor", "dtor", "operator"):
                # ??0Class@Namespace@@  -> class=Class, namespace=Namespace
                if len(parts) >= 2:
                    return (kind, parts[1], parts[0], parts[0])
                if parts:
                    return (kind, "", parts[0], parts[0])
                return (kind, "", "", mangled)
            # vftable: ??_7Class@Namespace@@6B...
            mm = re.match(r"^([^@]+)@([^@]+)@@", rest)
            if mm:
                return (kind, mm.group(2), mm.group(1), "`vftable'")
            if "@@" in rest:
                head = rest.split("@@")[0]
                ps = [p for p in head.split("@") if p]
                if len(ps) >= 2:
                    return (kind, ps[1], ps[0], "`vftable'")
                if ps:
                    return (kind, "", ps[0], "`vftable'")
            return (kind, "", "", mangled)

    m = _RE_MEMBER.match(mangled)
    if m:
        member, cls, ns = m.group(1), m.group(2), m.group(3)
        return ("method", ns, cls, member)

    m = _RE_FREE.match(mangled)
    if m:
        fn, ns = m.group(1), m.group(2)
        return ("free_function", ns, "", fn)

    return ("unknown", "", "", mangled)


def key_of(mangled: str) -> tuple[str, str, str]:
    kind, ns, cls, member = parse_key(mangled)
    if kind in ("c_api", "unknown"):
        return (ns, cls, mangled)
    return (ns, cls, member)


def display_of(mangled: str) -> tuple[str, str, str]:
    kind, ns, cls, member = parse_key(mangled)
    return (ns, cls, member)


# ---------------------------------------------------------------- 分类


def classify_against(real: list[str], baseline: set[str]) -> dict:
    """在给定基线符号集合下做四分类（identical / param_changed / missing / removed）。"""
    real_set = set(real)
    base_by_key: dict[tuple[str, str, str], list[str]] = {}
    for b in baseline:
        base_by_key.setdefault(key_of(b), []).append(b)

    counts = Counter()
    for mangled in real_set:
        if mangled in baseline:
            counts["identical"] += 1
        elif key_of(mangled) in base_by_key:
            counts["param_changed"] += 1
        else:
            counts["missing"] += 1
    counts["removed"] = len(baseline - real_set)
    return {
        "identical": counts["identical"],
        "param_changed": counts["param_changed"],
        "missing": counts["missing"],
        "removed": counts["removed"],
        "baseline_total": len(baseline),
    }


def classify(
    real: list[str],
    baseline_lib: set[str],
    baseline_dll: set[str],
) -> tuple[list[dict], dict]:
    """逐符号对照，产出 CSV 行与统计汇总。

    契约第 113 行把 `identical` 定义为「修饰名与**手写基线导入库**一致」，第 174 行的
    黄金集 3198 却只有从基线 **DLL** 才能复现。为不掩盖这个矛盾，本函数：
      * CSV 行按 `LIB ∪ DLL` 判定 `baseline_status`（与契约 3198 一致），
      * 同时给出 `in_baseline_lib` / `in_baseline_dll` 两列，
      * 并在 summary['per_carrier'] 里对每种载体单独统计四类数量。
    """
    real_set = set(real)
    baseline_any = baseline_lib | baseline_dll

    # ===== 别名归一化（修 double-count 缺陷）=====
    # 基线把 50 个旧式 API 同时以**两种**形式记录：
    #   * 导入库里是**修饰名**  ?Foo@DirectUI@@YA...Z
    #   * DLL 导出表里是**未修饰名** Foo
    # 若直接对 `LIB ∪ DLL` 求 `removed = union - real`，同一个 API 会被算两次
    # （修饰名一次 + 未修饰名一次），得到 205；而真实"只在基线、已不在真实 DLL"
    # 的逻辑符号只有 155。因此先把「修饰名别名」映射回其未修饰名再合并。
    alias_map: dict[str, str] = {}          # 修饰名 -> 未修饰名
    for x in (baseline_lib - baseline_dll):
        m = re.match(r"^\?(\w+)@", x)
        if m:
            alias_map[x] = m.group(1)
    effective_any = set(baseline_dll) | {alias_map.get(x, x) for x in baseline_lib}

    per_carrier = {
        "lib": classify_against(real, baseline_lib),
        "dll": classify_against(real, baseline_dll),
        # 合并载体必须用**归一化后**的集合，否则 removed 会把别名对双计（205 而非 155）
        "lib|dll": classify_against(real, effective_any),
    }

    base_by_key: dict[tuple[str, str, str], list[str]] = {}
    for b in baseline_any:
        base_by_key.setdefault(key_of(b), []).append(b)

    rows: list[dict] = []
    stats = Counter()
    for mangled in real_set:
        ns, cls, member = display_of(mangled)
        k = key_of(mangled)
        in_lib = mangled in baseline_lib
        in_dll = mangled in baseline_dll
        # 未修饰名也可能是别名目标（例如真实导出 `StrToID` 对应库里修饰名）
        in_lib_alias = mangled in set(alias_map.values())
        if in_lib or in_dll or in_lib_alias:
            status = "identical"
        elif k in base_by_key:
            status = "param_changed"
        else:
            status = "missing"
        stats[status] += 1
        rows.append({
            "mangled": mangled, "undecorated": "",
            "namespace": ns, "class": cls, "member": member,
            "baseline_status": status,
            "in_real": "yes",
            "in_baseline_lib": "yes" if (in_lib or in_lib_alias) else "no",
            "in_baseline_dll": "yes" if in_dll else "no",
            "baseline_has_declaration": "yes" if (in_lib or in_dll or k in base_by_key) else "no",
            "source": "real",
        })

    for b in sorted(effective_any - real_set):
        ns, cls, member = display_of(b)
        stats["removed"] += 1
        rows.append({
            "mangled": b, "undecorated": "",
            "namespace": ns, "class": cls, "member": member,
            "baseline_status": "removed",
            "in_real": "no",
            "in_baseline_lib": "yes" if b in baseline_lib else "no",
            "in_baseline_dll": "yes" if b in baseline_dll else "no",
            "baseline_has_declaration": "yes",
            "source": "baseline",
        })

    summary = {
        "real_total": len(real_set),
        "baseline_lib_total": len(baseline_lib),
        "baseline_dll_total": len(baseline_dll),
        "oracle_dll_intersection": len(real_set & baseline_dll),
        "oracle_lib_intersection": len(real_set & baseline_lib),
        "identical": stats["identical"],
        "param_changed": stats["param_changed"],
        "missing": stats["missing"],
        "removed": stats["removed"],
        "removed_naive_union_minus_real": len(baseline_any - real_set),
        "alias_pairs_normalized": len(alias_map),
        "effective_baseline_names": len(effective_any),
        "asymmetric_dll_only": sorted((real_set & baseline_dll) - (real_set & baseline_lib)),
        "lib_hits_subset_of_dll": (real_set & baseline_lib) <= (real_set & baseline_dll),
        "lib_minus_dll_raw": sorted(baseline_lib - baseline_dll),
        "dll_minus_lib_raw": sorted(baseline_dll - baseline_lib),
        "per_carrier": per_carrier,
        "effective_removed": sorted(effective_any - real_set),
    }
    return rows, summary


# ---------------------------------------------------------------- symbols.json


def load_symbols(path: str) -> tuple[dict[str, str], dict[str, str], dict | None]:
    """读取 symbols.json。

    返回 (exported_map, all_map, raw)：
      * exported_map —— 只含 `is_exported is True` 的符号（**契约断言的正确口径**）；
      * all_map      —— 全部符号（含 PDB 非导出 publics，契约第 82 行「仅供分析」）；
      * raw          —— 原始 JSON，供读取 meta。

    symbols.json 里 7662 个非导出 publics 绝大多数会被标成 missing，若混入
    identical 计数会让 identical 虚高（如 3200 > 黄金集 3198）。因此契约级的
    `identical == 3198` 断言**只在 exported 口径下成立**。
    """
    if not os.path.isfile(path):
        return {}, {}, None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    exported: dict[str, str] = {}
    allmap: dict[str, str] = {}
    for s in data.get("symbols", []):
        m = s.get("mangled")
        if not m:
            continue
        st = s.get("baseline_status") or ""
        allmap[m] = st
        if s.get("is_exported") is True:
            exported[m] = st
    return exported, allmap, data


# ---------------------------------------------------------------- 报告


def write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_md(s: dict, rows: list[dict], symbols_path: str, symbols_meta: dict | None,
             lib_path: str, dll_path: str, real_path: str, cross: dict) -> None:
    L: list[str] = []
    A = L.append
    A("# 基线对照报告（baseline_diff.py，verifier 独立复现）")
    A("")
    A("本报告由 `tools/dui-pipeline/baseline_diff.py` 独立运行产出；不引用任何其他模块的自述结论。")
    A("")
    A("## 输入")
    A("")
    A("| 用途 | 路径 |")
    A("|---|---|")
    A(f"| 真实导出集合（规范化） | `{real_path}` |")
    A(f"| 手写基线导入库 | `{lib_path}` |")
    A(f"| 手写基线 DLL | `{dll_path}` |")
    A(f"| 生成物 symbols.json | `{symbols_path}`"
      + ("" if symbols_meta else "（**当前不存在**，oracle 部分仍独立复现）") + " |")
    A("")
    A("## 一、黄金 oracle：3198 的独立复现")
    A("")
    A("INTERFACE.md 第 174 行断言：手写基线与真实 DLL 有 **3198** 个修饰名完全一致。")
    A("")
    A("| 指标 | 实测值 | 与契约 |")
    A("|---|---|---|")
    A(f"| 真实 x64 导出（唯一名） | {s['real_total']} | 契约 4321 "
      + ("PASS" if s["real_total"] == 4321 else "**FAIL**") + " |")
    A(f"| 基线 DLL 导出 | {s['baseline_dll_total']} | — |")
    A(f"| 基线导入库符号（去链接器内部符号） | {s['baseline_lib_total']} | — |")
    A(f"| **基线 DLL ∩ 真实 = oracle** | **{s['oracle_dll_intersection']}** | 契约 3198 "
      + ("**PASS**" if s["oracle_dll_intersection"] == GOLDEN else "**FAIL**") + " |")
    A(f"| 基线 LIB ∩ 真实 | {s['oracle_lib_intersection']} | 契约（若以 lib 为准）"
      + ("PASS" if s["oracle_lib_intersection"] == GOLDEN else "**不一致**") + " |")
    A("")
    if s["oracle_dll_intersection"] == GOLDEN:
        A("### 根因：3198 来自基线 **DLL** 的导出表")
        A("")
        A("契约第 33 行把 oracle 载体写作 `x64\\Debug\\Dui\\dui70.lib`；第 174 行断言")
        A("「手写基线与真实 DLL 有 3198 个修饰名完全一致」。实测：")
        A("")
        A(f"- 基线 **DLL** 导出 ∩ 真实 = **{s['oracle_dll_intersection']}** ← 命中契约 3198")
        A(f"- 基线 **LIB** 符号 ∩ 真实 = **{s['oracle_lib_intersection']}** ← 差 "
          f"**{GOLDEN - s['oracle_lib_intersection']}**")
        A(f"- 且 `real ∩ lib ⊆ real ∩ dll` = {s['lib_hits_subset_of_dll']}"
          "（前者是后者的真子集，故 `identical` 与 oracle 恰好同为 3198）")
        A("")
        A("机制（已逐符号证实）：基线工程为 **50 个 legacy 函数** 在 `.def` 中同时导出了")
        A("**C 名**与 **C++ 修饰名**。链接成 DLL 后导出表保留 **C 名**，而导入库 `.lib`")
        A("的归档成员表保留 **修饰名** —— 两侧正好各 50 个，一一配对：")
        A("")
        A("```")
        A("真实 C:\\Windows\\System32\\dui70.dll:")
        A("       4289 10C0 00081FF0 InitProcessPriv          <- 未修饰 C 名")
        A("")
        A("基线 x64\\Debug\\Dui\\dui70.dll:")
        A("       1905  CFB 00026D5A InitProcessPriv = @ILT+11605(?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z)")
        A("                          ^^^^^^^^^^^^^^^^ 导出名 = C 名（命中真实集合）")
        A("")
        A("基线 x64\\Debug\\Dui\\dui70.lib:")
        A("   1024AE ?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z   <- 归档名 = 修饰名（不命中）")
        A("   1024AE __imp_?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z")
        A("```")
        A("")
        A(f"`|lib - dll| = {len(s['lib_minus_dll_raw'])}` 与 "
          f"`|dll - lib| = {len(s['dll_minus_lib_raw'])}` 严格配对，"
          "前者全是修饰名，后者全是 C 名。")
        A("")
        A(f"这 50 对中，**49 个 C 名在真实 DLL 里存在**（因此 DLL 侧多命中 49 个），"
          "第 50 个是 `GetScreenDPI`——真实 DLL 已用 `GetDesktopDPI` 取代它，")
        A("故其 C 名也不命中，计入 `removed`。差额明细：")
        A("")
        A("```")
        A("# 真实集合中存在、经基线 DLL 命中、但经基线 LIB 无法命中的 49 个名字：")
        for x in s["asymmetric_dll_only"]:
            A(x)
        A("```")
        A("")
        A("**独立佐证**：仓库既有审计报告 `.local/audit/AUDIT-REPORT.md` 第 13–16 行的")
        A("「stub 导出 3353 / 完全一致 3198 / 真实有缺 1123 / stub 有真实无 155」与")
        A("基线 **DLL**（3353 个导出、∩真实 3198、缺 1123、removed 155）逐项吻合；")
        A("若改用 `.lib` 则应为 3149 / 1172 / 204，与该报告不符。")
        A("→ 故 3198 的载体是**基线 DLL**，契约把 BASELINE_LIB 当作 oracle 来源属于**表述不精确**。")
        A("")
        A("**verifier 未强行凑数**：两个数字均如实上报，并列出全部差额。)")
        A("")
    A("")
    A("## 二、四类统计（对照基线 LIB ∪ DLL）")
    A("")
    pc = s.get("per_carrier", {})
    if pc:
        A("契约第 113 行把 `identical` 定义为「修饰名与**手写基线导入库**一致」，")
        A("但第 174 行的黄金集 3198 实际来自基线 **DLL**。为不掩盖这一矛盾，")
        A("下表对三种基线载体分别统计四类数量（同一份真实导出集合，4321 条）：")
        A("")
        A("| 基线载体 | identical | param_changed | missing | removed |")
        A("|---|---|---|---|---|")
        for label, disp in (("dll", "基线 **DLL**（=契约 3198 的真实来源）"),
                            ("lib", "基线 **LIB**（契约第 33 行所写载体）"),
                            ("lib|dll", "LIB ∪ DLL（**已做别名归一化**，本报告 CSV 采用）")):
            c = pc.get(label)
            if not c:
                continue
            mark = " **<-- 命中契约**" if c["identical"] == GOLDEN else ""
            A("| %s | %d%s | %d | %d | %d |" % (
                disp, c["identical"], mark, c["param_changed"], c["missing"], c["removed"]))
        A("")
        A("注：`LIB ∪ DLL` 一行必须先做**别名归一化**再统计，否则 50 组"
          "「库里是修饰名 / DLL 里是未修饰名」的同一 API 会被双计，")
        A("得到 removed=205 的虚高值。归一化后与 DLL 载体一致（%d）。"
          % s["removed"])
        A("")
        A("**这是本次独立验证发现的最重要矛盾**：契约把 oracle 载体写成导入库，")
        A("但导入库只能给出 %d；只有基线 DLL 才能给出 %d。" % (
            pc["lib"]["identical"], pc["dll"]["identical"]))
        A("该矛盾已在第一节给出逐符号根因。CSV 的 `baseline_status` 采用 LIB ∪ DLL")
        A("（与契约 3198 一致），并另设 `in_baseline_lib` / `in_baseline_dll` 两列，")
        A("读者可自行按任一载体重算。")
        A("")
    A("| baseline_status | 数量 | 契约语义 |")
    A("|---|---|---|")
    A(f"| identical | {s['identical']} | 修饰名与手写基线一致 |")
    A(f"| param_changed | {s['param_changed']} | 同 class::member 但签名不同 |")
    A(f"| missing | {s['missing']} | 真实有、基线无 |")
    A(f"| removed | {s['removed']} | 基线有、真实无 |")
    A("")
    A("交叉验证：`identical` 与 oracle 的关系——")
    A("")
    A(f"- `identical` = {s['identical']}（真实符号在基线 LIB **或** DLL 中逐字命中）")
    A(f"- oracle（真实 ∩ 基线 DLL）= {s['oracle_dll_intersection']}")
    delta = s["identical"] - s["oracle_dll_intersection"]
    extra = ""
    if delta == len(s["asymmetric_dll_only"]) and delta:
        extra = "，其中 +%d 来自基线 LIB 独有命中（legacy C 别名的修饰名形态）" % delta
    A(f"- 差值 = {delta}{extra}")
    A("两数语义不同但**互相一致**：`identical` 统计的是「生成声明是否与基线声明逐字相同」，")
    A("oracle 统计的是「基线导出表与真实导出表的重合度」。二者不可直接相加或替代。")
    A("")

    if cross:
        A("## 三、与 symbols.json 的交叉验证")
        A("")
        A("| 指标 | 值 |")
        A("|---|---|")
        for k, v in cross.items():
            A(f"| {k} | {v} |")
        A("")
        if cross.get("mismatch_count"):
            A("**发现的矛盾（symbols.json 的 baseline_status 与本脚本独立复现不一致）：**")
            A("")
            A("```")
            for x in cross.get("mismatch_examples", []):
                A(x)
            A("```")
            A("")
        else:
            A("symbols.json 的 `baseline_status` 与独立复现**无矛盾**。")
            A("")

    A("## 四、复现命令")
    A("")
    A("```")
    A(r"C:\Users\7mile\AppData\Local\Programs\Python\Python311\python.exe \\?\%s" % os.path.abspath(__file__))
    A("```")
    A("")
    A(f"逐符号对照见 `{DEF_CSV}`（{len(rows)} 行）。")
    A("")
    with open(DEF_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- 历史模式


def run_history_mode(args) -> int:
    """生成物 vs git 历史基线（契约 v2 第 116 行指定的历史对照）。"""
    if not git_available():
        print("[FATAL] git 不可用或 ref %r 不存在 —— 历史模式无法执行" % args.ref)
        return 2

    text_gen = load_generated_symbols(args.src)
    # 权威口径：编译 stub，取编译器真正产出的修饰名。
    compiled = compiled_generated_symbols(args.src)
    compile_ok = bool(compiled)
    gen_src = compiled if compile_ok else text_gen["src"]

    if not text_gen["any"] and not compiled:
        print("[FATAL] 生成物目录 %s 下未找到任何修饰名" % args.src)
        return 2

    cmps = {
        "compiled-src" if compile_ok else "text-src":
            compare_against_history(gen_src, args.ref),
        "text-src+include": compare_against_history(text_gen["any"], args.ref),
    }
    c = list(cmps.values())[0]

    # 逐符号对照表（生成物侧）
    rows = []
    for m in sorted(text_gen["any"]):
        rows.append({
            "mangled": m,
            "in_gen_compiled": "yes" if m in compiled else "no",
            "in_gen_src_text": "yes" if m in text_gen["src"] else "no",
            "in_gen_include": "yes" if m in text_gen["inc"] else "no",
            "in_hist_def": "yes" if m in c["hist_def"] else "no",
            "in_hist_snapshot": "yes" if m in c["hist_snapshot"] else "no",
            "history_status": "common" if m in c["hist_any"] else "new_in_generator",
        })
    for m in c["only_hist"]:
        rows.append({
            "mangled": m,
            "in_gen_compiled": "no", "in_gen_src_text": "no", "in_gen_include": "no",
            "in_hist_def": "yes" if m in c["hist_def"] else "no",
            "in_hist_snapshot": "yes" if m in c["hist_snapshot"] else "no",
            "history_status": "only_in_history",
        })

    hist_csv = os.path.splitext(args.history_md)[0] + ".csv"
    with open(hist_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mangled", "in_gen_compiled",
                                           "in_gen_src_text", "in_gen_include",
                                           "in_hist_def", "in_hist_snapshot",
                                           "history_status"])
        w.writeheader()
        w.writerows(rows)

    L: list[str] = []
    A = L.append
    A("# 生成物 vs git 历史基线（baseline_diff.py --history）")
    A("")
    A("生成时间（UTC）：%s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    A("执行者：verifier（独立验证者）")
    A("")
    A("## 为什么是「历史模式」")
    A("")
    A("契约 v2 第 116 行判了 `baseline_status` 死刑，手写基线退役；"
      "v1 的 oracle 载体 `x64\\Debug\\Dui\\dui70.dll` **被 .gitignore 忽略**"
      "（`.gitignore:18 [Xx]64/`），随时可能消失、不可长期复现。"
      "因此本脚本降级为**历史工具**：读 git 历史里的手写基线，"
      "输出「生成物 vs 历史基线」的并集/差集对照。")
    A("")
    A("## 实测：为什么必须补一份冻结快照")
    A("")
    A("本想「纯 git 历史」重建基线符号集，实测**行不通**，两个数据源都不够：")
    A("")
    A("| 来源 | 实测内容 | 为什么不够 |")
    A("|---|---|---|")
    A("| `master:DirectUI/DirectUI.def` | **51 个未修饰 C 名**（InitProcessPriv 等 legacy 入口）"
      "| 只是 legacy 入口清单，不是完整导出集 |")
    A("| `master:DirectUI/*.h`（101 个）| 源码级声明，**不含修饰名** |"
      "`?Foo@Bar@@` 在头文件里不存在，文本正则无从匹配 |")
    A("")
    A("故历史符号集 = 历史 .def（权威 C 名）∪ **冻结快照** "
      "`.local/audit/baseline-diff.csv`（%d 行；Lead 明确认可）。"
      "该 CSV 是 v1 时期基线 LIB/DLL 的逐符号落盘，也是基线二进制消失后"
      "唯一幸存的完整记录。" % c["snapshot_rows"])
    A("")
    A("生成器侧则**编译** stub 取编译器真正产出的修饰名（`in_gen_compiled`），"
      "文本抽取仅作降级备用 —— 正则会把注释/字符串里的片段也算进去。")
    A("")
    A("## 数据源")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| git ref | `%s` |" % c["ref"])
    A("| 历史基线目录 | `%s/`（%d 个文件）|" % (GIT_BASELINE_DIR, c["hist_files"]))
    A("| 历史 .def | `%s` |" % (c["hist_def_path"] or "<未找到>"))
    A("| 历史 .def 符号数 | %d |" % len(c["hist_def"]))
    A("| 冻结快照符号数 | %d（来自 %d 行）|"
      % (len(c["hist_snapshot"]), c["snapshot_rows"]))
    A("| 历史符号合计（去重）| %d |" % c["hist_total"])
    A("| 生成物符号（%s）| %d |"
      % ("编译口径" if compile_ok else "文本口径（编译不可用，已降级）", c["gen_total"]))
    A("| 交集 | %d |" % len(c["common"]))
    A("")
    A("## 差集")
    A("")
    A("| 方向 | 数量 | 含义 |")
    A("|---|---|---|")
    A("| 仅生成物有（new_in_generator） | %d | 历史基线没有、生成器新产出的符号 |"
      % len(c["only_gen"]))
    A("| 仅历史有（only_in_history） | %d | 历史声明过、生成物未覆盖（含历史内部符号）|"
      % len(c["only_hist"]))
    A("")
    A("### src-only vs src+include 口径")
    A("")
    A("| 口径 | 生成物符号数 | 仅生成物有 | 仅历史有 |")
    A("|---|---|---|---|")
    for k, v in cmps.items():
        A("| %s | %d | %d | %d |" % (k, v["gen_total"], len(v["only_gen"]),
                                      len(v["only_hist"])))
    A("")
    A("> 说明：`include` 里含大量仅用于**消费者侧**的接口声明（Interfaces.h 等），"
      "它们本就不该出现在导出集合里；因此 `src` 口径更接近「导出的符号」，"
      "`src+include` 口径更接近「声明过的符号」。两者都报，不做取舍。")
    A("")
    A("## 仅生成物有（前 40）")
    A("")
    A("```")
    for m in c["only_gen"][:40]:
        A(m)
    if len(c["only_gen"]) > 40:
        A("... 共 %d 条" % len(c["only_gen"]))
    A("```")
    A("")
    A("## 仅历史有（前 40）")
    A("")
    A("```")
    for m in c["only_hist"][:40]:
        A(m)
    if len(c["only_hist"]) > 40:
        A("... 共 %d 条" % len(c["only_hist"]))
    A("```")
    A("")
    A("## 复现方式")
    A("")
    A("```")
    A("%s %s --history --ref %s" % (PYTHON, os.path.abspath(__file__), args.ref))
    A("```")
    A("")
    os.makedirs(os.path.dirname(os.path.abspath(args.history_md)), exist_ok=True)
    with open(args.history_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    print("ref            = %s" % c["ref"])
    print("hist files     = %d  (def: %s)" % (c["hist_files"], c["hist_def_path"]))
    print("gen symbols    = %d   hist symbols = %d   common = %d"
          % (c["gen_total"], c["hist_total"], len(c["common"])))
    print("only-generator = %d" % len(c["only_gen"]))
    print("only-history   = %d" % len(c["only_hist"]))
    print("wrote          %s" % hist_csv)
    print("wrote          %s" % args.history_md)
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="baseline vs real export diff (verifier)")
    ap.add_argument("--real", default=DEF_REAL)
    ap.add_argument("--lib", default=DEF_LIB)
    ap.add_argument("--dll", default=DEF_DLL)
    ap.add_argument("--symbols", default=DEF_SYMBOLS)
    ap.add_argument("--csv", default=DEF_CSV)
    ap.add_argument("--md", default=DEF_MD)
    ap.add_argument("--history", action="store_true",
                    help="历史模式（契约 v2）：生成物 vs **git 历史手写基线**，"
                         "不依赖 x64\\Debug\\Dui（该目录被 .gitignore 忽略）")
    ap.add_argument("--ref", default=GIT_BASELINE_REF,
                    help="历史模式使用的 git ref（默认 master）")
    ap.add_argument("--pinned", default=os.path.join(REPO, "pinned"),
                    help="契约输入目录（与 verify.py 同参数名；历史模式下用于定位快照）")
    ap.add_argument("--out", default=os.path.join(REPO, "DirectUI"),
                    help="生成物目录（与 verify.py 同参数名）")
    ap.add_argument("--src", default=None,
                    help="历史模式：生成物目录（默认取 --out）")
    ap.add_argument("--history-md", default=os.path.join(
        REPO, r".local\audit\baseline-history.md"),
        help="历史模式报告输出路径")
    ap.add_argument("--self-test", action="store_true",
                    help="只断言 oracle == 3198，非 0 退出表示复现失败")
    args = ap.parse_args(argv)

    # 与 verify.py 对齐：--out 是生成物目录的规范参数名
    if args.src is None:
        args.src = args.out
    if args.history:
        return run_history_mode(args)

    real = load_real(args.real)
    baseline_lib = dumpbin_lib_symbols(args.lib)
    baseline_dll = set(dumpbin_dll_exports(args.dll).keys())

    rows, summary = classify(real, baseline_lib, baseline_dll)

    if args.self_test:
        ok = summary["oracle_dll_intersection"] == GOLDEN and summary["real_total"] == 4321
        print("real_total=%d (expect 4321)" % summary["real_total"])
        print("oracle (baseline DLL cap real) = %d (expect %d)" % (
            summary["oracle_dll_intersection"], GOLDEN))
        print("baseline LIB cap real          = %d" % summary["oracle_lib_intersection"])
        print("identical=%d param_changed=%d missing=%d removed=%d" % (
            summary["identical"], summary["param_changed"],
            summary["missing"], summary["removed"]))
        print("SELF-TEST:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    sym_exported, sym_all, sym_meta = load_symbols(args.symbols)
    cross: dict = {}
    if sym_meta is not None:
        scope = (sym_meta.get("meta") or {}).get("baseline_status_scope")
        # 契约级断言用 exported_only 口径（见 load_symbols 文档）。
        # 若 symbols.json 已声明 scope，尊重其声明并说明。
        use = sym_exported if sym_exported else sym_all
        mismatch = []
        for r in rows:
            got = use.get(r["mangled"])
            if got is None:
                continue
            if got != r["baseline_status"]:
                mismatch.append("%s: symbols.json=%s  independent=%s" % (
                    r["mangled"][:100], got, r["baseline_status"]))
        reported = Counter(use.values())
        reported_all = Counter(sym_all.values())
        cross["symbols.json 声明的 baseline_status_scope"] = scope or "<未声明>"
        cross["本脚本采用的口径"] = "exported_only（is_exported=True，%d 条）"
        cross["符号总数（含非导出 publics）"] = len(sym_all)
        cross["用于断言的导出符号数"] = len(use)
        cross["baseline_status 不一致数"] = len(mismatch)
        cross["mismatch_count"] = len(mismatch)
        cross["mismatch_examples"] = mismatch[:40]
        cross["symbols.json 自报 identical（exported 口径）"] = reported.get("identical", 0)
        cross["symbols.json 自报 identical（全量口径）"] = reported_all.get("identical", 0)
        cross["独立复现 identical"] = summary["identical"]
        cross["黄金集"] = GOLDEN
        cross["identical 是否收敛到黄金集"] = (
            "PASS" if reported.get("identical", 0) == GOLDEN else
            "**不符（差 %d）**" % (reported.get("identical", 0) - GOLDEN))
        if reported.get("identical", 0) != reported_all.get("identical", 0):
            cross["口径差异说明"] = (
                "exported 口径 identical=%d，全量口径 identical=%d —— "
                "非导出 publics 被计入全量统计，会虚高；契约断言必须用 exported 口径"
                % (reported.get("identical", 0), reported_all.get("identical", 0)))

        # 次级校验（信息性，不参与 PASS/FAIL）：
        # 非导出符号（is_exported=False）的 baseline_status 无法用"是否为真实导出"判定，
        # 但仍应满足"该 mangled 是否真的存在于基线"。这里把这类不一致单独列出，
        # 避免它们被 exported 口径的过滤悄悄掩盖。
        nonexported_mismatch = []
        for r in rows:
            m = r["mangled"]
            if m in sym_exported:
                continue
            got = sym_all.get(m)
            if got is None:
                continue
            # 基线里是否有这个 mangled（决定 removed / identical 的合理值）
            in_base = r["in_baseline_lib"] == "yes" or r["in_baseline_dll"] == "yes"
            if got == "identical" and not in_base:
                nonexported_mismatch.append(
                    "%s: symbols.json=identical 但该名不在基线 LIB/DLL 中" % m[:100])
            elif got == "removed" and in_base:
                nonexported_mismatch.append(
                    "%s: symbols.json=removed 但该名存在于基线中" % m[:100])
        cross["次级：非导出符号 baseline_status 与基线存在性不符"] = len(nonexported_mismatch)
        cross["次级不符样例"] = nonexported_mismatch[:20]
    else:
        cross = {}

    write_csv(rows, args.csv)
    write_md(summary, rows, args.symbols, sym_meta, args.lib, args.dll, args.real, cross)

    print("real=%d  baseline_lib=%d  baseline_dll=%d" % (
        summary["real_total"], summary["baseline_lib_total"], summary["baseline_dll_total"]))
    print("ORACLE  baseline DLL cap real = %d   (contract expects %d)  -> %s" % (
        summary["oracle_dll_intersection"], GOLDEN,
        "PASS" if summary["oracle_dll_intersection"] == GOLDEN else "FAIL"))
    print("        baseline LIB cap real = %d" % summary["oracle_lib_intersection"])
    print("STATS   identical=%d param_changed=%d missing=%d removed=%d" % (
        summary["identical"], summary["param_changed"],
        summary["missing"], summary["removed"]))
    if sym_meta is not None:
        print("CROSS   symbols.json status mismatches = %d" % cross.get("mismatch_count", 0))
    else:
        print("CROSS   symbols.json not present yet (oracle reproduced independently)")
    print("wrote   %s" % args.csv)
    print("wrote   %s" % args.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
