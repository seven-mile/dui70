#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dui-pipeline / symbols module -- 产物 2: pinned/symbols.json + pinned/classes.json

输入是 extract.py 从 DLL/PDB 解析出的符号（导出表 + PDB publics），做:
  1. llvm-undname 批量反修饰
  2. 结构化解出契约要求的字段
  3. 写出 pinned/symbols.json + pinned/classes.json

契约: tools/dui-pipeline/INTERFACE.md — 字段名/枚举不得擅改。
只用标准库（Python 3.11）。

依赖的外部工具:
  llvm-undname  反修饰。从 PATH 查找（LLVM 发行版自带）；也可用
                环境变量 LLVM_UNDNAME 或 --undname <path> 指定。

输入:
  --raw          extract.py 的交接文件（导出表 + PDB publics + pub_flags）
  --inventory    pinned/class-inventory.csv —— 来自旧 build 的类名普查，
                 作类名白名单用。少数类只导出普通成员函数，没有
                 ctor/dtor/vftable 可供自举，只能靠它。该文件已随
                 pinned/ 提交，缺失时报错（不静默降级）。

用法:
  python model.py                     # 读 .local/build/extract-raw.json -> pinned/
  python model.py --pinned <dir>      # 指定 pinned 目录（默认 <repo>/pinned）
  python model.py --undname <path>    # 指定 llvm-undname 可执行文件
  python model.py --inventory <csv>   # 指定类清单 CSV
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(REPO, ".local", "build")
HEADERS_DIR = os.path.join(REPO, "DirectUI")
PINNED_DIR = os.path.join(REPO, "pinned")
# pinned/ 是冻结输入：类名普查 CSV 与 exports/symbols/classes 同住于此
CLASS_INVENTORY = os.path.join(PINNED_DIR, "class-inventory.csv")

# 契约 1.4: 引导种子（仅在 pinned/classes.json 缺失时使用；已存在 = 冻结输入，不覆盖）。
# 改此表 = 改生成范围 —— 现在的正确途径是直接编辑 pinned/classes.json（195 类）。
SEED_CLASSES = {
    "classes": ["Value", "DUIXmlParser", "Element", "HWNDElement", "NativeHWNDHost",
                "TouchButton", "Edit", "Button", "Progress", "PushButton",
                "TouchCheckBox", "XProvider"],
    "inheritance": {
        "HWNDElement": "Element",
        "Edit": "Element",
        "TouchButton": "Element",
        "Button": "Element",
        "Progress": "Element",
        "PushButton": "Button",
        "TouchCheckBox": "TouchButton",
        "XProvider": "IXProvider",
    },
}

CALL_CONVS = ("__cdecl", "__stdcall", "__thiscall", "__fastcall", "__vectorcall", "__clrcall")
_CC_RE = re.compile(r"(__cdecl|__stdcall|__thiscall|__fastcall|__vectorcall|__clrcall)")
_ACCESS_RE = re.compile(r"^(public|protected|private):\s*")

# 契约枚举（严格）
KINDS = ("method", "static_method", "ctor", "dtor", "operator", "free_function",
         "data", "vftable", "c_api", "template", "unknown")

# 已知数据类符号的名字形态（仅用于给"反修饰失败的 public"分 c_api / data）
_DATA_NAME_HINTS = ("_GUID", "CLSID_", "IID_", "LIBID_", "CATID_", "__imp_", "_PchSym_",
                    "_Property_", "_Event_", "_ControlType", "_Pattern", "_Pattern_GUID")


# ==========================================================================
# 基础工具
# ==========================================================================

def ensure_dir(p):
    if p and not os.path.isdir(p):
        os.makedirs(p, exist_ok=True)


def run(cmd, timeout=900):
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    dec = lambda b: (b or b"").decode("utf-8", errors="replace")
    return p.returncode, dec(p.stdout), dec(p.stderr)


# 外部工具逻辑名 -> (可执行文件名候选, 覆盖用环境变量)
_TOOLS = {
    "undname": (("llvm-undname", "llvm-undname.exe", "undname", "undname.exe"),
                "LLVM_UNDNAME"),
}


def tool_path(name):
    """Resolve an external tool to an absolute path.

    Order: the tool-specific environment variable (e.g. LLVM_UNDNAME), then
    PATH. A clear error is raised when the tool cannot be found, so that a
    missing dependency is reported as such instead of surfacing later as an
    empty undecoration result.
    """
    candidates, env = _TOOLS[name]
    if env and os.environ.get(env):
        return os.environ[env]
    for cand in candidates:
        found = shutil.which(cand)
        if found:
            return found
    raise SystemExit(
        "required external tool %r not found on PATH; install LLVM (which provides "
        "%s) and/or set %s to its full path"
        % (candidates[0], candidates[0], env))


def split_top_level(s, sep="::"):
    """按 sep 切分, 跳过 <> () [] 内的分隔符。"""
    parts, depth, last, i = [], 0, 0, 0
    while i < len(s):
        c = s[i]
        if c in "<([":
            depth += 1
        elif c in ">)]":
            depth -= 1
        elif depth <= 0 and s.startswith(sep, i):
            parts.append(s[last:i])
            i += len(sep)
            last = i
            continue
        i += 1
    parts.append(s[last:])
    return parts


def split_params(s):
    """按顶层逗号切分参数列表。"""
    if not s.strip():
        return []
    out, depth, last = [], 0, 0
    for i, c in enumerate(s):
        if c in "<([":
            depth += 1
        elif c in ">)]":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(s[last:i].strip())
            last = i + 1
    out.append(s[last:].strip())
    return [p for p in out if p]


def first_top_level_paren(s):
    """返回第一个 angle-depth==0 的 '(' 下标, 无则 -1。"""
    ang, i = 0, 0
    while i < len(s):
        c = s[i]
        if c == "<":
            ang += 1
        elif c == ">":
            ang -= 1
        elif c == "(" and ang == 0:
            return i
        i += 1
    return -1


def match_paren(s, i):
    """s[i]=='(' 时返回配对 ')' 的下标, 无则 -1。"""
    depth = 0
    while i < len(s):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def is_template_mangled(mangled):
    """MSVC 模板实例化标记: 修饰名里出现 "?$"。

    注意: 字符串常量 `??_C@_...` 的内容会被编码进修饰名, 内容里的 '#' 编码为 "?$CD",
    于是出现 "?$" 但它根本不是模板（1024 个假阳性）。故排除 `??_C@`。
    """
    if mangled.startswith("??_C@"):
        return False
    return "?$" in mangled


def template_base(name):
    return name.split("<", 1)[0] if name else name


_TRAILING_SPEC = re.compile(r"\s*(?:noexcept(?:\s*\([^()]*\))?|throw\s*\([^()]*\))\s*$")


def strip_trailing_spec(s):
    """去掉尾部的 noexcept / noexcept(...) / throw(...) 异常规格。

    注意: "void (__cdecl *wil::g_pfnX)(void) noexcept" 因尾部 noexcept 导致
    "RET (__cc * DECL)(P)$" 匹配失败, 被误判成普通函数（member 取成返回类型）。
    共 17 个 wil:: 函数指针全局变量受此影响。
    """
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_SPEC.sub("", s)
    return s


def parse_fnptr_data(s):
    """解析"类型为函数指针的数据成员": "RET (__cc * DECL)(P)"。

    成功返回 (ret, callconv, decl, params), 否则 None。
    用显式扫描而非纯正则, 以便处理 DECL 里被反引号引住的名字
    （如 wil 的 `void * __cdecl Foo(int)'::`2'::pfnX, 内含括号）。

    两个必须的守卫（否则会把"函数的一个参数"误当成被声明的实体）:
      1) ret 里不能有顶层 '(' —— 有则说明这个 '(' 属于参数列表，
         例如 Add(Element *, int (__cdecl *)(void const *, void const *))
      2) DECL 必须非空 —— 空 DECL 意味着"(*)"这种无名字段，不是数据声明
    """
    if not s.endswith(")"):
        return None
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "`":                       # `name' 整体跳过
            j = s.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "(":
            # 该 ( 之后应紧跟 __cc 与 *
            m = re.match(r"\(\s*__(?P<cc>\w+)\s*\*", s[i:])
            if not m:
                i += 1
                continue
            ret = s[:i].strip()
            # 守卫 1: ret 里已有顶层 '(' -> 这个 '(' 属于参数列表, 不是声明器
            if first_top_level_paren(ret) >= 0:
                i += 1
                continue
            cc = "__" + m.group("cc")
            decl_start = i + m.end()
            # 从 ( 开始配平括号, 找 *_DECL_* 的右括号
            depth = 0
            k = i
            while k < n:
                if s[k] == "`":
                    j = s.find("'", k + 1)
                    k = n if j < 0 else j + 1
                    continue
                if s[k] == "(":
                    depth += 1
                elif s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= n:
                return None
            decl = s[decl_start:k].strip()
            rest = s[k + 1:].strip()
            if not rest.startswith("(") or not rest.endswith(")"):
                return None
            params = rest[1:-1].strip()
            # 守卫 2: ret / decl 都必须非空
            if not ret or not decl:
                i += 1
                continue
            return ret, cc, decl, params
        i += 1
    return None


# MSVC 函数内静态变量: "?VAR@?1??EnclosingFunc@Scope@@...@Z@4<TYPE>"
#   反修饰结果形如: "<TYPE> `<enclosing signature>'::`2'::VAR"
#   注意: 里面的反引号签名含 :: 和括号, 天真的"取最后一段 :: 之后"会取到**外层函数名**
#   （27 个里有 23 个被这样误判）。变量名以修饰名为准最可靠。
_LOCAL_STATIC_RE = re.compile(r"^\?(?P<var>[^@]+)@\?1\?\?")


def parse_local_static(mangled, u, resolve_scope=None):
    """处理 MSVC 函数内静态变量。返回 dict 或 None。"""
    m = _LOCAL_STATIC_RE.match(mangled)
    if not m:
        return None
    var = m.group("var")
    out = {
        "kind": "data", "scope": None, "namespace": None, "class": None, "member": var,
        "access": "public", "is_virtual": False, "is_static": True, "is_const": False,
        "callconv": None, "return_type": None, "params": [], "is_operator": False,
    }
    if not u:
        return out
    s = _ACCESS_RE.sub("", u.strip())
    # 拆掉外层反引号签名, 只留类型 + 变量名
    if "'::" in s:
        head, _sep, _tail = s.partition("'::")
        out["return_type"] = head.rsplit("`", 1)[0].strip() or None
        # 从外层签名里取类/命名空间: "`long __cdecl wil::details::RecordLog(long)'"
        inner = head.rsplit("`", 1)[-1]
        scope_m = re.search(r"([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)::\s*"
                            r"(?:~?\w+|operator\S*)\s*\(", inner)
        if scope_m:
            out["scope"] = scope_m.group(1)
    else:
        # 无外层签名: "<TYPE> VAR"
        if " " in s:
            out["return_type"] = s.rsplit(" ", 1)[0].strip() or None
    if out["scope"] and resolve_scope:
        out["namespace"], out["class"] = resolve_scope(out["scope"])
    return out


def strip_ptr(decl):
    """去掉声明器前的 *, &, __ptr64 以及指针自身的 const/volatile 限定。"""
    d = decl.strip()
    changed = True
    while changed and d:
        changed = False
        while d and (d[0] in "*&"):
            d = d[1:].lstrip()
            changed = True
        if d.startswith("__ptr64"):
            d = d[len("__ptr64"):].lstrip()
            changed = True
        for q in ("const ", "volatile "):
            if d.startswith(q):
                d = d[len(q):].lstrip()
                changed = True
                break
    return d


# ==========================================================================
# 反修饰
# ==========================================================================

def _undecorate_chunk(chunk, tool):
    rc, out, err = run([tool] + chunk)
    groups, cur = [], []
    for ln in out.splitlines():
        if ln == "":
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(ln)
    if cur:
        groups.append(cur)
    return groups, err


def undecorate_batch(names, chunk_chars=16000, verbose=True, tool=None):
    """批量反修饰。返回 {mangled: undecorated|None}。

    llvm-undname 单参数输出 [mangled, undecorated, ""]（失败时只有 [mangled, ""]）;
    批量时每个符号一组, 以空行分隔。以"回显行 == 输入名"对齐, 数量不符时逐个回退。
    """
    tool = tool or tool_path("undname")
    res = {}
    names = list(names)
    i, n_fallback, n_invoked = 0, 0, 0
    while i < len(names):
        chunk, size = [], 0
        while i < len(names) and size + len(names[i]) + 1 < chunk_chars:
            chunk.append(names[i])
            size += len(names[i]) + 1
            i += 1
        groups, _ = _undecorate_chunk(chunk, tool)
        n_invoked += 1
        aligned = (len(groups) == len(chunk) and
                   all(g and g[0] == c for g, c in zip(groups, chunk)))
        if aligned:
            for c, g in zip(chunk, groups):
                res[c] = g[1] if len(g) >= 2 and g[1] else None
        else:
            # 回退: 逐个调用, 保证不错位
            n_fallback += len(chunk)
            for c in chunk:
                g, _ = _undecorate_chunk([c], tool)
                g = g[0] if g else [c]
                res[c] = g[1] if len(g) >= 2 and g[1] else None
    if verbose:
        print("[undname] %d symbols in %d batch calls, %d per-symbol fallbacks"
              % (len(names), n_invoked, n_fallback), file=sys.stderr)
    return res


# ==========================================================================
# 反修饰文本 -> 结构化字段
# ==========================================================================

def parse_undecorated(u, mangled, resolve_scope):
    """把一条 undecorated 文本解析成契约字段。永不抛异常, 失败给 kind=unknown。"""
    out = {
        "kind": "unknown", "scope": None, "namespace": None, "class": None, "member": None,
        "access": "public", "is_virtual": False, "is_static": False, "is_const": False,
        "callconv": None, "return_type": None, "params": [], "is_operator": False,
    }
    if u is None:
        return out
    try:
        s = u.strip()

        # ---- 编译器产物: vftable ----
        if "`vftable'" in s:
            pre = s.split("::`vftable'", 1)[0]
            pre = _ACCESS_RE.sub("", pre).strip()
            pre = re.sub(r"^(class|struct|const)\s+", "", pre)
            out["kind"] = "vftable"
            out["scope"] = pre or None
            out["namespace"], out["class"] = resolve_scope(pre) if pre else (None, None)
            out["member"] = "`vftable'"
            return out

        # ---- 其它编译器产物: thunk / RTTI / vcall / 字符串常量 ----
        if s.startswith("[thunk]:") or "`RTTI" in s or "`vcall'" in s:
            out["kind"] = "unknown"
            return out
        if s[:1] == '"' or s[:2] == 'L"':
            out["kind"] = "data"
            out["return_type"] = None
            return out

        # ---- 访问限定 / virtual / static ----
        m = _ACCESS_RE.match(s)
        if m:
            out["access"] = m.group(1)
            s = s[m.end():]
        if s.startswith("virtual "):
            out["is_virtual"] = True
            s = s[len("virtual "):]
        if s.startswith("static "):
            out["is_static"] = True
            s = s[len("static "):]

        # ---- MSVC 函数内静态变量: "?VAR@?1??Enclosing..." ----
        #      必须在所有其它分支之前处理, 否则外层函数签名会污染解析。
        ls = parse_local_static(mangled, u, resolve_scope)
        if ls is not None:
            return ls

        # ---- 尾部 const ----
        if s.endswith(" const") and "(" in s:
            out["is_const"] = True
            s = s[:-len(" const")].rstrip()

        # ---- 函数指针"返回类型": "RET (__cc1 * __cc2 DECL(p1))(p2)" ----
        #      即"返回函数指针的函数"。return_type 必须保留函数指针形状
        #      （否则 GetGetSheetCallback 会丢掉 "(*)(unsigned short const *, void *)"）。
        mfp = re.match(
            r"^(?P<ret>.*?)\s*\(\s*__(?P<cc1>\w+)\s*\*\s*__(?P<cc2>\w+)\s+"
            r"(?P<decl>.+?)\s*\((?P<p1>[^()]*)\)\s*\)\s*\((?P<p2>[^()]*)\)$", s)
        if mfp:
            ret = mfp.group("ret").strip()
            p2 = mfp.group("p2").strip()
            out["callconv"] = "__" + mfp.group("cc2")
            out["return_type"] = "%s (%s *)(%s)" % (ret or "", "__" + mfp.group("cc1"),
                                                    p2 if p2 else "void")
            _fill_declarator(out, mfp.group("decl"), mangled, resolve_scope)
            p1 = mfp.group("p1").strip()
            out["params"] = [] if p1 in ("", "void") else split_params(p1)
            _finish_kind(out, mangled)
            return out

        # ---- 数据成员, 其类型是函数指针: "RET (__cc * DECL)(p)" ----
        #      必须要求 DECL 非空, 且"函数指针组之前不含顶层括号"——否则函数
        #      `Add(Element *, int (__cdecl *)(void const *, void const *))` 会把
        #      **参数列表里**的函数指针误当成被声明的实体（曾致 53 个方法被误判 data）。
        mdfp = re.match(
            r"^(?P<ret>.*?)\s*\(\s*__(?P<cc>\w+)\s*\*\s*(?P<decl>[^()]*?)\s*\)\s*"
            r"\((?P<p>.*)\)$", s)
        if (mdfp and mdfp.group("decl").strip()
                and first_top_level_paren(mdfp.group("ret")) < 0):
            out["kind"] = "data"
            out["return_type"] = mdfp.group("ret").strip() or None
            out["callconv"] = "__" + mdfp.group("cc")
            _fill_declarator(out, strip_ptr(mdfp.group("decl")), mangled, resolve_scope)
            _finish_kind(out, mangled)
            return out

        # ---- 数据成员, 类型是"指向数组的指针": "RET (*DECL)[N]" ----
        #      例: private: static unsigned int const (*const DirectUI::HWNDHost::g_rgMouseMap)[3]
        #      无调用约定 -> 是数据, 不是函数（否则会被下面的"常规函数"分支吞掉）
        marr = re.match(
            r"^(?P<ret>.*?)\s*\(\s*(?P<decl>[*&][^()]*?)\s*\)\s*\[[^\]]*\]$", s)
        if marr:
            out["kind"] = "data"
            out["return_type"] = marr.group("ret").strip() or None
            _fill_declarator(out, strip_ptr(marr.group("decl")), mangled, resolve_scope)
            _finish_kind(out, mangled)
            return out

        # ---- 无参数列表: 数据符号 ----
        if "(" not in s:
            if " " in s:
                ret, decl = s.rsplit(" ", 1)
                out["return_type"] = ret.strip() or None
            else:
                decl = s
            out["kind"] = "data"
            _fill_declarator(out, strip_ptr(decl), mangled, resolve_scope)
            _finish_kind(out, mangled)
            return out

        # ---- 类型为函数指针的数据成员: "RET (__cc * DECL)(P) [noexcept]" ----
        #      必须在"常规函数"之前判定, 否则会被当成返回函数指针的函数。
        #      parse_fnptr_data 内部已保证这里的 '(' 是顶层声明器（不是某个参数）。
        stripped = strip_trailing_spec(s)
        fpd = parse_fnptr_data(stripped)
        if fpd is not None:
            ret, cc, decl, params = fpd
            out["kind"] = "data"
            out["return_type"] = ret
            out["callconv"] = cc
            _fill_declarator(out, strip_ptr(decl), mangled, resolve_scope)
            out["params"] = [] if params in ("", "void") else split_params(params)
            _finish_kind(out, mangled)
            return out

        # ---- 常规函数: "RET __cc DECL(params)" ----
        i = first_top_level_paren(s)
        if i < 0:
            out["kind"] = "unknown"
            return out
        j = match_paren(s, i)
        if j < 0:
            out["kind"] = "unknown"
            return out
        head, pstr = s[:i], s[i + 1:j]
        ccs = list(_CC_RE.finditer(head))
        if ccs:
            cc = ccs[-1]
            out["callconv"] = cc.group(0)
            out["return_type"] = head[:cc.start()].strip() or None
            decl = strip_ptr(head[cc.end():])
        else:
            decl = strip_ptr(head)
        _fill_declarator(out, decl, mangled, resolve_scope)
        out["params"] = [] if pstr.strip() in ("", "void") else split_params(pstr)
        _finish_kind(out, mangled)
        return out
    except Exception:
        out["kind"] = "unknown"
        out["params"] = []
        return out


def _fill_declarator(out, decl, mangled, resolve_scope):
    """拆分 "Scope::Member" -> scope/namespace/class/member。"""
    decl = decl.strip()
    if not decl:
        return
    parts = split_top_level(decl, "::")
    if len(parts) >= 2:
        scope = "::".join(parts[:-1])
        member = parts[-1]
    else:
        scope, member = None, decl
    out["scope"] = scope
    out["member"] = member
    if scope:
        out["namespace"], out["class"] = resolve_scope(scope)
    # ctor / dtor 的 member 形态修正
    if member.startswith("~"):
        out["member"] = member[1:]
    out["is_operator"] = member.startswith("operator")


def _finish_kind(out, mangled):
    """按优先级定 kind。

    注意: 进入本函数时 kind=="unknown" 只表示"尚未分类的正常函数/数据"
    （vftable / thunk / RTTI / 字符串在 parse_undecorated 里已提前 return）。
    优先级: 编译器产物 > dtor/ctor > operator > 数据 > template > static_method > method > free。
    """
    k = out["kind"]
    if k not in ("unknown", "data"):
        return
    member = out["member"] or ""
    if -1 != member.find("deleting destructor"):
        out["kind"] = "dtor"
        return
    # ---- 构造函数 / 析构函数 —— 以修饰名前缀为准（最权威） ----
    if mangled.startswith("??0"):
        out["kind"] = "ctor"
        return
    if mangled.startswith(("??1", "??_G", "??_E", "??_D")):
        out["kind"] = "dtor"
        return
    # ---- 数据（无参数列表者）优先于函数判定 ----
    if k == "data":
        return
    if out["is_operator"]:
        out["kind"] = "operator"
        return
    # MSVC 模板实例化: 修饰名里出现 "?$"（"$$Q" 是右值引用, 不是模板）
    if is_template_mangled(mangled):
        out["kind"] = "template"
        return
    if out["is_static"] and out["class"]:
        out["kind"] = "static_method"
        return
    if out["class"]:
        out["kind"] = "method"
        return
    out["kind"] = "free_function"


# ==========================================================================
# 类名发现
# ==========================================================================

def load_class_inventory(path):
    """读取类清单 CSV（列: Class, MethodCount）。

    这是 pinned/ 冻结输入之一：来自旧 build 的类名普查，作为类名白名单使用。
    它覆盖仅凭修饰名无法反推的类（例如 BehaviorStore：只有普通成员函数，
    没有任何 ctor/dtor/vftable 可供自举）；MethodCount 列是那份普查的产物，
    精度不可靠，本模块不读。

    该文件随 pinned/ 一起提交，缺失即无法复现 pinned/symbols.json 的
    class 字段，因此按错误处理而不是静默降级。
    """
    if not path or not os.path.isfile(path):
        raise SystemExit(
            "class inventory CSV not found: %s\n"
            "它是 pinned/ 的冻结输入之一（来自旧 build 的类名普查）；"
            "用 --inventory <path> 指定其它位置。" % path)
    classes = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            n = (row.get("Class") or "").strip()
            if n:
                classes.add(n)
    return classes


def load_namespaces():
    """已知命名空间白名单（dui70 实际只用到这几个）。"""
    return {"DirectUI", "SWF", "std", "wistd", "wil", "Gdiplus", "Library",
            "Windows", "Microsoft", "Details", "wil_details"}


def load_header_text():
    buf = []
    if os.path.isdir(HEADERS_DIR):
        for fn in sorted(os.listdir(HEADERS_DIR)):
            if fn.lower().endswith((".h", ".hpp")):
                try:
                    with open(os.path.join(HEADERS_DIR, fn), encoding="utf-8", errors="replace") as f:
                        buf.append(f.read())
                except OSError:
                    pass
    return "\n".join(buf)


def discover_classes(und, header_text, inventory_path):
    """Collect class names from the undecorated dump (`und`), the headers and
    the pinned class inventory.

    Sources, in decreasing authority:
      1. the class inventory CSV from pinned/ (see load_class_inventory) — the
         only source able to name classes that leave no ctor/dtor/vftable
         residue;
      2. `class X` / `struct X` declarations in the generated headers;
      3. the scope of every ctor / dtor / operator= / vftable symbol in the
         undecorated dump.

    Source 3 needs only the DLL/PDB-derived undname output, so it is available
    with no extra inputs. The `und` key is the *mangled* name, because
    undecoration of a large batch is done in one llvm-undname pass keyed by
    mangled name.

    Only modifiers whose scope is necessarily a class are used (ctor, dtor,
    operator=, and the vftable / deleting-dtor helpers). Bootstrapping from
    free functions would be wrong: those may live in a namespace, which would
    then be promoted to a class.

    Scope extraction: the declarator is the text before the first "(", which
    for a member definition is `... Scope::Member`; the last "::" segment is
    the class name, so nested scopes resolve correctly. Three rendering quirks
    have to be handled before taking that last segment:

      * non-namespaced classes render as `public: __cdecl UID::UID(...)`,
        gluing the calling convention onto the scope ("__cdecl UID") — strip
        everything up to and including the last calling-convention token;
      * `Scope::operator=` and `Scope::~Dtor` end with the member name, which
        must be removed (otherwise a class such as NavReference would be
        recorded as "operator=", and its members would lose their class and
        fall back to `free_function`);
      * the vftable helper renders as `Scope::`vftable'`, i.e. a backquoted
        pseudo-member name that must be stripped with the member segment.
    """
    known = set(load_class_inventory(inventory_path))
    for m in re.finditer(r"\b(?:class|struct)\s+([A-Za-z_]\w*)(?!\s*::)", header_text):
        known.add(m.group(1))
    for mangled, u in und.items():
        if not u:
            continue
        if not mangled.startswith(("??0", "??1", "??4", "??_7", "??_G", "??_E", "??_D")):
            continue
        s = _ACCESS_RE.sub("", u.strip())
        s = re.sub(r"^(?:class|struct|const)\s+", "", s)
        if "::" not in s:
            continue
        scope = s.split("(", 1)[0]
        scope = re.sub(r"^.*?\b__(?:cdecl|stdcall|thiscall|fastcall|vectorcall)\s+",
                       "", scope)
        # 末尾成员：普通名 / ~dtor / operatorXXX / `vftable'
        scope = re.sub(r"\s*::\s*(`vftable'|~?\w+|operator\S*)$", "", scope)
        scope = scope.strip()
        if not scope:
            continue
        parts = split_top_level(scope, "::")
        known.add(parts[-1])
        known.add(template_base(parts[-1]))
    return known


# ==========================================================================
# 主流程
# ==========================================================================

def build(args):
    raw_path = args.raw
    if not os.path.isfile(raw_path):
        raise SystemExit("missing %s -- run extract.py first" % raw_path)
    # 先校验 pinned 输入，避免在跑完上万符号的反修饰之后才发现缺文件
    if not args.inventory or not os.path.isfile(args.inventory):
        raise SystemExit(
            "class inventory CSV not found: %s\n"
            "它是 pinned/ 的冻结输入之一（来自旧 build 的类名普查）；"
            "用 --inventory <path> 指定其它位置。" % args.inventory)
    with open(raw_path, encoding="utf-8") as f:
        src = json.load(f)

    exports = src["exports"]
    publics = src["publics"]
    exp_by_name = {}
    for e in exports:
        exp_by_name.setdefault(e["mangled"], e)
    pub_names = set(p["mangled"] for p in publics)

    # ---------------- 反修饰 ----------------
    all_names = sorted(set(exp_by_name) | pub_names)
    und = undecorate_batch(all_names, tool=args.undname or tool_path("undname"))

    # ---------------- 类发现 ----------------
    header_text = load_header_text()
    known_classes = discover_classes(und, header_text, args.inventory)
    namespaces = load_namespaces()
    # 命名空间白名单里的名字不算类（否则 "DirectUI::FreeFunc" 会被当成 DirectUI 的成员）
    known_classes = set(n for n in known_classes if n not in namespaces)

    def resolve_scope(scope):
        if not scope:
            return None, None
        parts = split_top_level(scope, "::")
        last = parts[-1]
        base = template_base(last)
        if last in namespaces and last not in known_classes:
            return scope, None
        if last in known_classes or base in known_classes or "<" in last:
            return ("::".join(parts[:-1]) or None), last
        return scope, None

    # ---------------- 逐符号构造 ----------------
    # pub_flags 由 extract.py 从 PDB publics 文本解析后放进交接文件，
    # 只用于区分"反修饰失败的 public"是 c_api 还是 data。
    flags = dict(src.get("pub_flags") or {})
    # publics 的真实 RVA 由 extract.py 算好放在交接文件的 publics[].rva
    pub_rva = {}
    for p in publics:
        if p.get("rva"):
            pub_rva.setdefault(p["mangled"], p["rva"])

    symbols = []
    for mangled in all_names:
        is_export = mangled in exp_by_name
        e = exp_by_name.get(mangled)
        u = und.get(mangled)

        if u is None:
            # 反修饰失败 -> 纯 C 名
            u = mangled
            if is_export:
                kind = "c_api"
            else:
                f = flags.get(mangled)
                if f == "function":
                    kind = "c_api"
                elif f == "none":
                    kind = "data"
                else:
                    kind = "data" if any(h in mangled for h in _DATA_NAME_HINTS) else "c_api"
            parsed = {
                "kind": kind, "scope": None, "namespace": None, "class": None, "member": mangled,
                "access": "public", "is_virtual": False, "is_static": False, "is_const": False,
                "callconv": "__cdecl" if kind == "c_api" else None,
                "return_type": None, "params": [], "is_operator": False,
            }
        else:
            parsed = parse_undecorated(u, mangled, resolve_scope)

        rva = e["rva"] if e else pub_rva.get(mangled)

        # 契约 1.3 的字段集合。键**显式存在**（值可为 null），不做 sparse 省略
        # —— 契约 §1.3 的字段完整性要求。
        symbols.append({
            "mangled": mangled,
            "kind": parsed["kind"],
            "class": parsed["class"],
            "member": parsed["member"],
            "is_exported": bool(is_export),
            "is_virtual": bool(parsed["is_virtual"]),
            "is_static": bool(parsed["is_static"]),
            "is_const": bool(parsed["is_const"]),
            "return_type": parsed["return_type"],
            "params": parsed["params"],
            "rva": rva,
        })

    # ---------------- meta ----------------
    meta = dict(src["meta"])
    meta["source_exports_count"] = len(exports)
    meta["source_publics_count"] = len(publics)
    meta["symbols_count"] = len(symbols)
    meta["kind_counts"] = dict(collections.Counter(s["kind"] for s in symbols).most_common())
    meta["notes"] = {
        "params_void": "无参函数（undname 输出 '(void)'）的 params 记为 [] 而非 ['void']",
        "kind_precedence": "c_api/data(反修饰失败) > vftable > unknown(thunk/RTTI) > dtor > ctor > "
                           "operator > template > static_method > data > method > free_function",
        "class_resolution": "scope 最后一段若为已知类名/模板实例（<...>）则为 class",
        "rva": "PDB publics 的左列是记录偏移而非 RVA; 真实 RVA=节VA+addr 十进制偏移",
    }

    doc = {"meta": meta, "symbols": symbols}

    # ---------------- pinned/symbols.json + pinned/classes.json ----------------
    pin_dir = args.pinned
    ensure_dir(pin_dir)
    out_sym = os.path.join(pin_dir, "symbols.json")
    with open(out_sym, "w", encoding="utf-8") as f:
        json.dump({"symbols": symbols}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    # classes.json（契约 1.4）—— 生成范围的真实来源。
    # 历史教训（2026-10-02 事故）：这里曾经无条件写死 12 类旧列表，把已提交的
    # 195 类 classes.json 打回 12 类（run.ps1 任何一次执行都会触发）。
    # 现在的语义：classes.json 是 pinned/ 冻结输入，model.py 只在文件缺失时
    # 才用 SEED_CLASSES 引导初始版本；已存在时绝不覆盖。
    cpath = os.path.join(pin_dir, "classes.json")
    if os.path.exists(cpath):
        try:
            with open(cpath, encoding="utf-8") as f:
                existing = json.load(f)
            if not (isinstance(existing, dict)
                    and isinstance(existing.get("classes"), list)
                    and isinstance(existing.get("inheritance"), dict)):
                raise ValueError("classes.json 形状不对（缺 classes/inheritance）")
        except (ValueError, OSError) as exc:
            sys.exit("refusing to overwrite pinned/classes.json: %s\n"
                     "（pinned/ 是冻结输入；如确要重建，请先手动移走该文件）" % exc)
        with open(cpath, encoding="utf-8") as f:
            final_classes = json.load(f)
        report_classes_note = "kept existing pinned/classes.json (frozen input)"
    else:
        final_classes = SEED_CLASSES
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(SEED_CLASSES, f, ensure_ascii=False, indent=2)
            f.write("\n")
        report_classes_note = "bootstrapped classes.json from SEED_CLASSES (12-class seed)"
    pinned_report = {
        "out": out_sym,
        "classes_out": cpath,
        "classes_note": report_classes_note,
        "symbols": len(symbols),
        "size_bytes": os.path.getsize(out_sym),
        "classes_size_bytes": os.path.getsize(cpath),
    }

    # ---------------- 运行报告 ----------------
    report = self_check(doc, src)
    report["pinned"] = pinned_report
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return doc, report


def self_check(doc, src):
    symbols = doc["symbols"]
    exports = src["exports"]
    publics = src["publics"]
    exp_names = set(e["mangled"] for e in exports)
    pub_names = set(p["mangled"] for p in publics)
    expected_union = len(exp_names | pub_names)

    kinds = collections.Counter(s["kind"] for s in symbols)
    exp_syms = [s for s in symbols if s["is_exported"]]

    # rva 一致性: 导出 rva 与 PDB public rva 是否吻合
    pub_rva = {}
    for p in publics:
        if p.get("rva"):
            pub_rva.setdefault(p["mangled"], p["rva"])
    checked = [s for s in exp_syms if s["mangled"] in pub_rva]
    mismatch = [s["mangled"] for s in checked if pub_rva[s["mangled"]] != s["rva"]]

    target7 = ["Value", "DUIXmlParser", "Element", "HWNDElement", "NativeHWNDHost",
               "TouchButton", "Edit"]
    per_class = {}
    for c in target7:
        cs = [s for s in symbols if s["class"] == c]
        per_class[c] = {
            "symbols": len(cs),
            "parsed_methods": sum(1 for s in cs if s["kind"] in
                                  ("method", "static_method", "ctor", "dtor", "operator")),
            "exported": sum(1 for s in cs if s["is_exported"]),
            "kinds": dict(collections.Counter(s["kind"] for s in cs).most_common()),
        }
    return {
        "assertions": {
            "symbols_eq_exports_union_publics":
                len(symbols) == expected_union,
            "expected_union": expected_union,
            "actual_symbols": len(symbols),
            "kind_distribution_nonzero_methodlike":
                sum(kinds[k] for k in ("method", "static_method", "ctor", "dtor", "operator")) > 0,
            "seven_target_classes_all_parsed":
                all(v["parsed_methods"] > 0 or v["symbols"] == 0 for v in per_class.values()),
            "rva_export_vs_public_zero_mismatch": len(mismatch) == 0,
        },
        "per_target_class": per_class,
        "counts": {
            "exports": len(exports),
            "publics": len(publics),
            "exports_unique": len(exp_names),
            "publics_unique": len(pub_names),
            "publics_also_exported": len(pub_names & exp_names),
            "publics_not_exported": len(pub_names - exp_names),
            "expected_union": expected_union,
            "symbols_written": len(symbols),
            "matches_union": len(symbols) == expected_union,
        },
        "kind_distribution": dict(kinds.most_common()),
        "kind_sum_check": sum(kinds.values()) == len(symbols),
        "rva_cross_check": {
            "export_rva_vs_pdb_public_rva": {"checked": len(checked),
                                             "mismatch": len(mismatch),
                                             "samples": mismatch[:5]},
            "publics_without_rva": sum(1 for p in publics if not p.get("rva")),
            "note": "PDB 左列是记录偏移; 真实 RVA=节VA+addr 十进制偏移, 由 extract.py 计算",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="dui-pipeline: DLL/PDB 符号解析结果 -> pinned/symbols.json + pinned/classes.json")
    ap.add_argument("--raw", default=os.path.join(BUILD, "extract-raw.json"),
                    help="extract.py 的交接文件（导出表 + PDB publics）")
    ap.add_argument("--pinned", default=PINNED_DIR,
                    help="pinned 目录（默认 <repo>/pinned）")
    ap.add_argument("--undname", default=None,
                    help="llvm-undname 可执行文件路径（默认从 PATH 查找，"
                         "也可用环境变量 LLVM_UNDNAME）")
    ap.add_argument("--inventory", default=CLASS_INVENTORY,
                    help="类名普查 CSV（列 Class,MethodCount）；默认 "
                         "<repo>/pinned/class-inventory.csv。"
                         "它是 pinned/ 的冻结输入之一，缺失时报错。")
    ap.add_argument("--self-check", action="store_true", default=True)
    args = ap.parse_args(argv)
    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
