#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dui-pipeline / symbols module -- 产物 2: symbols.json

吃 .local/build/exports.json（由 extract.py 产出），做:
  1. llvm-undname 批量反修饰
  2. 结构化解出契约要求的全部字段
  3. 与手写基线（导入库 + 基线 DLL 导出表）对照得 baseline_status
  4. 汇总 classes 数组
输出 .local/build/symbols.json。

契约: tools/dui-pipeline/INTERFACE.md （冻结版 v1）— 字段名/枚举不得擅改。
只用标准库（Python 3.11）。

用法:
  python model.py                     # exports.json -> symbols.json
  python model.py --self-check        # 额外打印逐项自证（默认也打印摘要）
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as _dt
import json
import os
import re
import struct
import subprocess
import sys

REPO = r"Z:\repos\DirectUI"
BUILD = os.path.join(REPO, ".local", "build")
AUDIT = os.path.join(REPO, ".local", "audit")
HEADERS_DIR = os.path.join(REPO, "DirectUI")
MSDEF = os.path.join(REPO, "DirectUI", "msdef.txt")
# msdef.txt 在 dd1fd41 被删除（"retire hand-written DirectUI project"），
# 但它是 4 个类的唯一来源（NavReference / LinkedListNode / ACCESSIBLEROLE / UID）。
# 缓存副本 + git 历史兜底，使 class 发现不再依赖已退役的手写树。
MSDEF_CACHE = os.path.join(AUDIT.replace("audit", "cache"), "msdef-x64.txt")
CLASS_INVENTORY = os.path.join(AUDIT, "class-inventory-26200.csv")
LEAD_MISSING_CSV = os.path.join(AUDIT, "missing-exports-26200.csv")
PINNED_DIR = os.path.join(REPO, "pinned")

# 契约 1.4: 目标类清单 + 继承表（轴 B 成本显式化）。改此表 = 改生成范围。
CLASSES_V2 = {
    "schema_version": 2,
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

BASELINE_DLL = os.path.join(REPO, "x64", "Debug", "Dui", "dui70.dll")
BASELINE_LIB = os.path.join(REPO, "x64", "Debug", "Dui", "dui70.lib")

UNDNAME = r"C:\Local\Tools\mingw64\bin\llvm-undname.exe"
DUMPBIN = (r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC"
           r"\14.44.35207\bin\Hostx64\x64\dumpbin.exe")

CALL_CONVS = ("__cdecl", "__stdcall", "__thiscall", "__fastcall", "__vectorcall", "__clrcall")
_CC_RE = re.compile(r"(__cdecl|__stdcall|__thiscall|__fastcall|__vectorcall|__clrcall)")
_ACCESS_RE = re.compile(r"^(public|protected|private):\s*")

# 契约枚举（严格）
KINDS = ("method", "static_method", "ctor", "dtor", "operator", "free_function",
         "data", "vftable", "c_api", "template", "unknown")
BASELINE_STATUS = ("identical", "param_changed", "missing", "removed")

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

    坑: 字符串常量 `??_C@_...` 的内容会被编码进修饰名, 内容里的 '#' 编码为 "?$CD",
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

    坑: "void (__cdecl *wil::g_pfnX)(void) noexcept" 因尾部 noexcept 导致
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

    ！两个必须的守卫（否则会把"函数的一个参数"误当成被声明的实体）:
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
#   坑: 里面的反引号签名含 :: 和括号, 天真的"取最后一段 :: 之后"会取到**外层函数名**
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

def _undecorate_chunk(chunk):
    rc, out, err = run([UNDNAME] + chunk)
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


def undecorate_batch(names, chunk_chars=16000, verbose=True):
    """批量反修饰。返回 {mangled: undecorated|None}。

    llvm-undname 单参数输出 [mangled, undecorated, ""]（失败时只有 [mangled, ""]）;
    批量时每个符号一组, 以空行分隔。以"回显行 == 输入名"对齐, 数量不符时逐个回退。
    """
    res = {}
    names = list(names)
    i, n_fallback, n_invoked = 0, 0, 0
    while i < len(names):
        chunk, size = [], 0
        while i < len(names) and size + len(names[i]) + 1 < chunk_chars:
            chunk.append(names[i])
            size += len(names[i]) + 1
            i += 1
        groups, _ = _undecorate_chunk(chunk)
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
                g, _ = _undecorate_chunk([c])
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
# 基线（手写 stub）符号集合
# ==========================================================================

def _baseline_dll_names(path=BASELINE_DLL):
    """基线 DLL 的导出名集合（导入库的最终形态; 与 Lead 的 3198/1123/155 完全吻合）。"""
    if not os.path.isfile(path):
        return set(), "missing"
    rc, out, err = run([DUMPBIN, "/exports", path])
    names = set()
    for ln in (out + "\n" + err).splitlines():
        m = re.match(r"^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]{8}\s+(\S.*?)\s*$", ln)
        if m:
            rest = m.group(1)
            names.add(rest.split(" = ")[0] if " = " in rest else rest)
    return names, "baseline-dll"


def _baseline_lib_names(path=BASELINE_LIB):
    """手写基线导入库的符号集合。

    优先用 dumpbin /linkermember:1（任务指定的方法）; 同时用 COFF archive 的
    first linker member 二进制解析做交叉校验 —— dumpbin 文本对超长符号会截断/丢行。
    """
    names = set()
    src = "missing"
    if os.path.isfile(path):
        rc, out, err = run([DUMPBIN, "/linkermember:1", path])
        for ln in (out + "\n" + err).splitlines():
            m = re.match(r"^\s*[0-9A-Fa-f]{4,}\s+(\S+)\s*$", ln)
            if not m:
                continue
            t = m.group(1)
            if t.startswith("__imp_"):
                t = t[6:]
            if (t.startswith("__IMPORT_DESCRIPTOR") or t.startswith("__NULL_IMPORT_DESCRIPTOR")
                    or "NULL_THUNK_DATA" in t or t.startswith(".")):
                continue
            if t in ("mode", "size", "uid", "gid", "time/date", "symbols", "public"):
                continue
            names.add(t)
        src = "baseline-lib/dumpbin"
        # 二进制交叉校验
        binnames = _lib_linker_member_names(path)
        if binnames:
            if binnames != names:
                print("[baseline] NOTE dumpbin /linkermember:1 (%d) != COFF archive (%d); "
                      "using archive union" % (len(names), len(binnames)), file=sys.stderr)
            names |= binnames
            src = "baseline-lib/dumpbin+archive"
    return names, src


def _lib_linker_member_names(path):
    """直接解析 COFF archive 的 first linker member（big-endian 偏移表）。"""
    try:
        raw = open(path, "rb").read()
        if raw[:8] != b"!<arch>\n":
            return set()
        hdr = raw[8:68]
        size = int(hdr[48:58].decode("ascii").strip())
        d = raw[68:68 + size]
        n = struct.unpack(">I", d[0:4])[0]
        region = d[4 + 4 * n:]
        out = set()
        for tok in region.split(b"\0"):
            if not tok:
                continue
            t = tok.decode("ascii", "replace")
            if t.startswith("__imp_"):
                t = t[6:]
            if (t.startswith("__IMPORT_DESCRIPTOR") or t.startswith("__NULL_IMPORT_DESCRIPTOR")
                    or "NULL_THUNK_DATA" in t):
                continue
            out.add(t)
        return out
    except Exception:
        return set()


def build_baseline_set():
    """返回 (baseline_set, info)。baseline_set 是"手写基线能提供的导入符号"集合。

    两路来源最终归一为同一集合（均得 identical=3198 / missing=1123 / removed=155）:
      * 基线 DLL 导出表  —— 权威（导出名即链接期符号）
      * 基线导入库       —— 需做别名归一: 基线 .lib 里 C API 存的是修饰名
        （?BlurBitmap@DirectUI@@...），而真实 DLL 导出的是纯名（BlurBitmap），
        二者是同一 API。规则: 若 .lib 符号的 member 名等于某个真实纯名导出，视为同一。
    """
    dll_names, dll_src = _baseline_dll_names()
    lib_names, lib_src = _baseline_lib_names()
    info = {
        "sources": {"dll": dll_src, "lib": lib_src},
        "baseline_dll_names": len(dll_names),
        "baseline_lib_names": len(lib_names),
        "baseline_dll_path": BASELINE_DLL,
        "baseline_lib_path": BASELINE_LIB,
    }
    return dll_names | lib_names, dll_names, lib_names, info


def alias_normalize(baseline, real_exports):
    """把基线 .lib 中"C API 的修饰名"折叠回真实 DLL 使用的纯名。

    基线 .lib 对 C API 存的是修饰名（如 ?BlurBitmap@DirectUI@@YAHPEAX0000@Z），
    而真实 DLL 导出的是纯名（BlurBitmap），二者是同一 API。

    注意: 只有当"该纯名本身是一个真实导出、且没有同名的修饰导出"时才折叠。
    反例: InitThread —— 真实 DLL 同时导出纯名 `InitThread`（C API）和
    `?InitThread@FontCache@DirectUI@@SAJXZ`（类静态方法），两者是不同符号，
    若折叠会让后者被误判为 identical（正是 3197 vs 3198 差的 1 个）。
    """
    decorated_exports = set(n for n in real_exports if n.startswith("?"))
    plain_exports = set(n for n in real_exports if not n.startswith("?"))
    aliased = {}
    eff = set()
    for b in baseline:
        if not b.startswith("?") or b.startswith("??"):
            eff.add(b)
            continue
        member = b[1:].split("@", 1)[0]
        if member in plain_exports and b not in decorated_exports:
            aliased[b] = member
            eff.add(member)
            continue
        eff.add(b)
    return eff, aliased


def key_of(parsed):
    """class::member 键, 用于 param_changed 判定。"""
    scope = parsed.get("scope")
    member = parsed.get("member")
    if member is None:
        return None
    return (scope, member)


# ==========================================================================
# 类名发现
# ==========================================================================

def load_class_inventory():
    classes = set()
    if os.path.isfile(CLASS_INVENTORY):
        with open(CLASS_INVENTORY, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                n = (row.get("Class") or "").strip()
                if n:
                    classes.add(n)
    return classes


def server_scope_ok(name, known):
    """判断 scope 的最后一段是否真的是"类"而不是"命名空间"。

    规则: 已登记为类的名字 -> 是; 模板实例化（含 '<'）-> 是;
    否则只有当它不是已知命名空间时才可能是类。
    已知命名空间来自 PDB 里大量 "DirectUI::FreeFunc" / "DirectUI::g_var" 这类条目
    —— 单看一行无法区分命名空间与类, 需靠白名单。
    """
    if "<" in name:
        return True
    return name in known


def load_namespaces():
    """已知命名空间白名单（dui70 实际只用到这几个）。"""
    return {"DirectUI", "SWF", "std", "wistd", "wil", "Gdiplus", "Library",
            "Windows", "Microsoft", "Details", "wil_details"}


def load_msdef_classes():
    """从 msdef 抓类名。

    坑 1: 天真的 `(\\w+)::` 会把命名空间 DirectUI 也当成类
    （"DirectUI::Element::Foo()" 的第一个匹配是 "DirectUI"），
    从而把 `DirectUI::FreeFunc()` 这类自由函数误判成 class="DirectUI" 的成员。
    这里只认"紧邻 '(' 或 '`vftable' 的那一段"，即真正的 Scope::Member 结构。

    坑 2: 直接 isfile(MSDEF) 判断会因 dd1fd41 删掉 DirectUI/msdef.txt 而静默返回空集，
    导致 4 个类（NavReference/LinkedListNode/ACCESSIBLEROLE/UID）+ 一批类名丢失。
    统一走 load_msdef_text() 的多级回退。
    """
    classes = set()
    text = load_msdef_text()
    if not text:
        return classes
    for ln in text.splitlines():
            # Scope::Member(  ->  Scope 的最后一段是类
            for m in re.finditer(r"([A-Za-z_]\w*)\s*::\s*(?:~\w+|operator\S*|[A-Za-z_]\w*)\s*\(", ln):
                classes.add(m.group(1))
            # Scope::`vftable'
            for m in re.finditer(r"([A-Za-z_]\w*)\s*::\s*`vftable'", ln):
                classes.add(m.group(1))
            # 数据成员: "Type Scope::Member"（行尾无括号）
            s = ln.strip()
            if s and "(" not in s:
                for m in re.finditer(r"([A-Za-z_]\w*)\s*::\s*[A-Za-z_]\w*\s*$", s):
                    classes.add(m.group(1))
    return classes


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


def load_msdef_text():
    """读 msdef（MS 的修饰名定义清单）。

    优先 DirectUI/msdef.txt；已被删除时退回 .local/cache/msdef-x64.txt；
    再不行从 git 历史取（只读操作，不改工作区）。
    """
    if os.path.isfile(MSDEF):
        with open(MSDEF, encoding="utf-8", errors="replace") as f:
            return f.read()
    if os.path.isfile(MSDEF_CACHE):
        with open(MSDEF_CACHE, encoding="utf-8", errors="replace") as f:
            return f.read()
    try:
        p = subprocess.run(["git", "show", "dd1fd41~1:DirectUI/msdef.txt"],
                           cwd=REPO, capture_output=True, timeout=60)
        if p.returncode == 0:
            return (p.stdout or b"").decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def discover_classes(und, header_text, msdef_text):
    """从 ctor/dtor/vftable 的 scope 里自举类名（scope 的最后一段）。

    注: 这里的自举只是兜底（msdef 才是主来源）。它对无命名空间的类
    （如 UID::UID）取不到正确的末段，但那种情况下 msdef 已经能提供，
    因此保持保守实现，避免把命名空间误升为类。
    """
    known = set(load_class_inventory())
    known |= load_msdef_classes()
    for m in re.finditer(r"\b(?:class|struct)\s+([A-Za-z_]\w*)(?!\s*::)", header_text):
        known.add(m.group(1))
    for mangled, u in und.items():
        if not u:
            continue
        if not mangled.startswith(("??0", "??1", "??_7", "??_G", "??_E", "??_D")):
            continue
        s = _ACCESS_RE.sub("", u.strip())
        s = re.sub(r"^(class|struct|const)\s+", "", s)
        if "::" in s:
            scope = s.split("(", 1)[0]
            # 无命名空间的类（如 "public: __cdecl UID::UID(...)"）会把调用约定
            # 粘进 scope（"__cdecl UID"），导致 UID 从未被登记。剥掉最后一个
            # 调用约定记号之前的所有内容。
            scope = re.sub(r"^.*?\b__(?:cdecl|stdcall|thiscall|fastcall|vectorcall)\s+",
                           "", scope)
            scope = re.sub(r"\s*::\s*(`vftable'|~?\w+)$", "", scope)
            scope = scope.strip()
            if scope:
                parts = split_top_level(scope, "::")
                known.add(parts[-1])
                known.add(template_base(parts[-1]))
    return known


# ==========================================================================
# baseline_status
# ==========================================================================

def classify_status(mangled, is_export, eff_baseline, baseline_keys, key, exported_names):
    """baseline_status —— 双侧校验。

    契约: identical = "修饰名与手写基线导入库一致"。
    但若一个符号只是 PDB public（真实 DLL 里存在、导出表里没有），它就不属于
    "真实导出 ∩ 基线"：基线（stub DLL）曾把它导出、真实 DLL 现在不再导出，
    因此它是 removed，而不是 identical。
    （例: ??_7RichText@DirectUI@@6B@、??_7TouchButton@DirectUI@@6B@）
    """
    in_baseline = mangled in eff_baseline
    if in_baseline:
        return "identical" if is_export else "removed"
    if key and key in baseline_keys:
        return "param_changed"
    return "missing"


# ==========================================================================
# 主流程
# ==========================================================================

def load_pdb_info(path):
    """返回 (flags, rvas, record_offsets)。

    flags:         name -> 'function' | 'none'
    rvas:          name -> "0x........"（由 extract.py 算好的真实 RVA）
    record_offsets: name -> PDB 记录偏移（注意: 不是 RVA）
    """
    flags, rvas, offs = {}, {}, {}
    if not os.path.isfile(path):
        return flags, rvas, offs
    pending = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            m = re.match(r"^\s*(\d+)\s*\|\s*S_PUB32\b[^`]*`([^`]*)`\s*$", ln)
            if m:
                pending = m.group(2)
                offs[pending] = int(m.group(1))
                continue
            a = re.match(r"^\s*flags = (\w+), addr = (\d+):(\d+)", ln)
            if a and pending:
                flags[pending] = a.group(1)
                pending = None
    return flags, rvas, offs


def build(args):
    exports_path = args.exports
    if not os.path.isfile(exports_path):
        raise SystemExit("missing %s -- run extract.py first" % exports_path)
    with open(exports_path, encoding="utf-8") as f:
        src = json.load(f)

    exports = src["exports"]
    publics = src["publics"]
    exp_by_name = {}
    for e in exports:
        exp_by_name.setdefault(e["mangled"], e)
    pub_names = set(p["mangled"] for p in publics)

    # ---------------- 基线 ----------------
    raw_baseline, dll_b, lib_b, binfo = build_baseline_set()
    eff_baseline, aliased = alias_normalize(raw_baseline, exp_by_name)

    # ---------------- 反修饰 ----------------
    all_names = sorted(set(exp_by_name) | pub_names)
    und = undecorate_batch(all_names)

    # ---------------- 类发现 ----------------
    header_text = load_header_text()
    msdef_text = load_msdef_text()
    known_classes = discover_classes(und, header_text, msdef_text)
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

    # ---------------- 基线 key 集合 ----------------
    base_parsed = {}
    base_und = undecorate_batch(sorted(eff_baseline)) if eff_baseline else {}
    for b in eff_baseline:
        bu = base_und.get(b) or (b if not b.startswith("?") else None)
        if bu is None:
            continue
        bp = parse_undecorated(bu, b, resolve_scope)
        if bp["member"] is not None:
            base_parsed[b] = bp
    baseline_keys = set()
    for b, bp in base_parsed.items():
        k = key_of(bp)
        if k:
            baseline_keys.add(k)

    # ---------------- 逐符号构造 ----------------
    flags, _unused, rec_offsets = load_pdb_info(
        os.path.join(REPO, ".local", "cache", "pdb-publics-x64.txt"))
    # publics 的真实 RVA 由 extract.py 算好放在 exports.json 的 publics[].rva
    pub_rva = {}
    for p in publics:
        if p.get("rva"):
            pub_rva.setdefault(p["mangled"], p["rva"])
    n_pub_rva = len(pub_rva)

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

        key = key_of(parsed)
        status = classify_status(mangled, is_export, eff_baseline, baseline_keys, key,
                                 exp_by_name)

        rva = e["rva"] if e else pub_rva.get(mangled)
        record_offset = rec_offsets.get(mangled)

        sym = {
            "mangled": mangled,
            "undecorated": u,
            "rva": rva,
            "ordinal": e["ordinal"] if e else None,
            "pdb_record_offset": record_offset,
            "is_exported": bool(is_export),
            "kind": parsed["kind"],
            "scope": parsed["scope"],
            "namespace": parsed["namespace"],
            "class": parsed["class"],
            "member": parsed["member"],
            "access": parsed["access"],
            "is_virtual": bool(parsed["is_virtual"]),
            "is_static": bool(parsed["is_static"]),
            "is_const": bool(parsed["is_const"]),
            "callconv": parsed["callconv"],
            "return_type": parsed["return_type"],
            "params": parsed["params"],
            "is_template": is_template_mangled(mangled),
            "is_operator": bool(parsed["is_operator"]),
            "baseline_status": status,
        }
        symbols.append(sym)

    # ---------------- v2 瘦身投影（契约 1.3） ----------------
    # 只留 11 个字段。与 v1 的差别:
    #   - 键**显式存在**（值可为 null），不做 sparse 省略 —— 契约示例与
    #     verifier A1 的"字段完整性"断言都要求字段齐全
    #   - kind 保留原值（含 "template"）；见 meta 里对 1.3 枚举遗漏的说明
    V2_FIELDS = ("mangled", "kind", "class", "member", "is_exported", "is_virtual",
                 "is_static", "is_const", "return_type", "params", "rva")
    v2_symbols = []
    for s in symbols:
        v2 = {}
        for f in V2_FIELDS:
            v2[f] = s.get(f)
        v2_symbols.append(v2)

    # ---------------- classes 汇总（v1 审计用, 不写进 v2） ----------------
    by_class = collections.OrderedDict()
    for s in symbols:
        if not s["class"]:
            continue
        by_class.setdefault(s["class"], []).append(s)
    classes = []
    for name in sorted(by_class):
        members = by_class[name]
        base = template_base(name)
        exp_members = [m for m in members if m["is_exported"]]
        classes.append({
            "name": name,
            "namespace": members[0]["namespace"],
            "methods": len(members),
            "methods_exported": len(exp_members),
            "methods_publics_only": len(members) - len(exp_members),
            "is_template": "<" in name,
            "in_baseline_headers": bool(re.search(r"\b%s\b" % re.escape(base), header_text)),
            "in_msdef": ("::%s::" % base) in msdef_text or ("::%s>" % base) in msdef_text,
            "stable": all(m["baseline_status"] == "identical" for m in exp_members),
        })

    # ---------------- meta ----------------
    meta = dict(src["meta"])
    meta["source_exports_count"] = len(exports)
    meta["source_publics_count"] = len(publics)
    meta["symbols_count"] = len(symbols)
    meta["classes_count"] = len(classes)

    # 两套口径分开统计，避免把 7662 个非导出 public 的 missing 混进导出口径
    st_exp = collections.Counter(s["baseline_status"] for s in symbols if s["is_exported"])
    st_pub = collections.Counter(s["baseline_status"] for s in symbols if not s["is_exported"])
    meta["baseline_status_scope"] = "exported_only"
    meta["baseline_status"] = {
        "exported_only": {
            "total": sum(st_exp.values()),
            "identical": st_exp.get("identical", 0),
            "missing": st_exp.get("missing", 0),
            "param_changed": st_exp.get("param_changed", 0),
            "removed": st_exp.get("removed", 0),
            "note": "identical 必须 == 3198; missing + param_changed == 1123",
        },
        "publics_only": {
            "total": sum(st_pub.values()),
            "identical": st_pub.get("identical", 0),
            "missing": st_pub.get("missing", 0),
            "param_changed": st_pub.get("param_changed", 0),
            "removed": st_pub.get("removed", 0),
            "note": "真实 PDB 有、但不在导出表里的内部符号; 与导出口径不能相加",
        },
    }
    meta["baseline_stats"] = {
        **binfo,
        "baseline_effective_names": len(eff_baseline),
        "aliased_lib_names": len(aliased),
        "alias_examples": dict(list(aliased.items())[:5]),
    }
    meta["notes"] = {
        "params_void": "无参函数（undname 输出 '(void)'）的 params 记为 [] 而非 ['void']",
        "is_template": "按 MSVC 修饰特征 '?$' 判定（排除 '??_C@' 字符串常量; 模板实例化）",
        "kind_precedence": "c_api/data(反修饰失败) > vftable > unknown(thunk/RTTI) > dtor > ctor > "
                           "operator > template > static_method > data > method > free_function",
        "class_resolution": "scope 最后一段若为已知类名/模板实例（<...>）则为 class, 其余为 namespace",
        "stable": "该类所有符号的 baseline_status 均为 identical",
        "baseline_status_scope": "meta.baseline_status 分 exported_only / publics_only 两套口径统计; "
                                 "baseline_status 字段本身仍是双侧校验的结果",
        "removed": "基线有、真实导出表无 的 155 个符号（含 2 个仍以 PDB public 存在的 vftable）"
                   "清单见 meta.removed_symbols",
        "rva": "PDB publics 的左列是记录偏移而非 RVA; 真实 RVA=节VA+addr 十进制偏移",
    }
    removed_syms = sorted(b for b in eff_baseline if b not in exp_by_name)
    meta["removed_symbols"] = removed_syms

    doc = {"meta": meta, "symbols": symbols, "classes": classes}

    # ---------------- 写出 ----------------
    ensure_dir(os.path.dirname(args.out))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")

    # ---------------- v2 pinned/symbols.json（契约 1.3） ----------------
    pinned_report = None
    if getattr(args, "pinned", None):
        pin_dir = args.pinned
        ensure_dir(pin_dir)
        out_v2 = os.path.join(pin_dir, "symbols.json")
        with open(out_v2, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "symbols": v2_symbols},
                      f, ensure_ascii=False, indent=1)
            f.write("\n")
        # classes.json（契约 1.4）—— 12 类 + 8 条继承边
        cpath = os.path.join(pin_dir, "classes.json")
        with open(cpath, "w", encoding="utf-8") as f:
            json.dump(CLASSES_V2, f, ensure_ascii=False, indent=2)
            f.write("\n")
        pinned_report = {
            "out": out_v2,
            "classes_out": cpath,
            "symbols": len(v2_symbols),
            "size_bytes": os.path.getsize(out_v2),
            "classes_size_bytes": os.path.getsize(cpath),
            "v2_fields": list(V2_FIELDS),
        }

    # ---------------- 自证 ----------------
    report = self_check(doc, src, eff_baseline, dll_b, lib_b,
                        alias_normalize(raw_baseline, exp_by_name)[1])
    if pinned_report is not None:
        report["pinned_v2"] = pinned_report
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return doc, report


def self_check(doc, src, eff_baseline, dll_b, lib_b, aliased):
    symbols = doc["symbols"]
    exports = src["exports"]
    publics = src["publics"]
    exp_names = set(e["mangled"] for e in exports)
    pub_names = set(p["mangled"] for p in publics)
    expected_union = len(exp_names | pub_names)

    kinds = collections.Counter(s["kind"] for s in symbols)
    status_all = collections.Counter(s["baseline_status"] for s in symbols)
    status_exp = collections.Counter(s["baseline_status"] for s in symbols if s["is_exported"])
    exp_syms = [s for s in symbols if s["is_exported"]]
    non_identical_exports = [s for s in exp_syms if s["baseline_status"] != "identical"]

    # Lead 的 1123 交叉验证
    lead_missing = None
    if os.path.isfile(LEAD_MISSING_CSV):
        with open(LEAD_MISSING_CSV, encoding="utf-8", errors="replace") as f:
            lead_missing = set(r["Mangled"] for r in csv.DictReader(f) if r.get("Mangled"))
    my_missing_mangled = set(s["mangled"] for s in non_identical_exports)
    cmp_lead = None
    if lead_missing is not None:
        only_mine = my_missing_mangled - lead_missing
        only_lead = lead_missing - my_missing_mangled
        cmp_lead = {
            "lead_csv": LEAD_MISSING_CSV,
            "lead_count": len(lead_missing),
            "mine_count_mangled_based": len(my_missing_mangled),
            "equal": my_missing_mangled == lead_missing,
            "diff_pct": round(100.0 * len(only_mine) / max(1, len(lead_missing)), 3),
            "only_mine": len(only_mine),
            "only_lead": len(only_lead),
            "samples_only_mine": sorted(only_mine)[:5],
            "samples_only_lead": sorted(only_lead)[:5],
        }

    # 基线三来源一致性
    #   注意: removed 的判据是"基线有、真实导出表无"（契约原文）。
    #   若某个基线符号虽然不再导出、但仍以 PDB public 形式存在于真实 DLL，
    #   它仍然在 symbols 里（作为 is_exported=false 的 public），其 baseline_status=identical。
    exp_list = [e["mangled"] for e in exports]

    def stat(B):
        rem = [b for b in B if b not in exp_names]
        return {"identical": len([m for m in exp_list if m in B]),
                "missing": len([m for m in exp_list if m not in B]),
                "removed": len(rem),
                "removed_but_still_pdb_public": len([b for b in rem if b in pub_names]),
                "removed_gone_entirely": len([b for b in rem if b not in pub_names])}

    baseline_check = {
        "baseline_dll_raw": stat(dll_b),
        "baseline_lib_raw": stat(lib_b),
        "effective_after_alias": stat(eff_baseline),
        "aliased_count": len(aliased),
    }

    # rva 一致性: 导出 rva 与 PDB public rva 是否吻合
    pub_rva = {}
    for p in publics:
        if p.get("rva"):
            pub_rva.setdefault(p["mangled"], p["rva"])
    checked = [s for s in exp_syms if s["mangled"] in pub_rva]
    mismatch = [s["mangled"] for s in checked if pub_rva[s["mangled"]] != s["rva"]]

    # 显式断言（契约自证要求）
    #   真实有、基线无 的导出 = missing + param_changed（param_changed 也是"基线没有该签名"）
    strict_missing = [s for s in exp_syms if s["baseline_status"] == "missing"]
    param_changed = [s for s in exp_syms if s["baseline_status"] == "param_changed"]
    identical = [s for s in exp_syms if s["baseline_status"] == "identical"]
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
    rva_mismatch_pub_only = None
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
            "missing_plus_param_changed_equals_lead":
                (len(strict_missing) + len(param_changed)) == (len(lead_missing) if lead_missing else -1),
            "rva_export_vs_public_zero_mismatch": len(mismatch) == 0,
        },
        "per_target_class": per_class,
        "export_status": {
            "identical": len(identical),
            "missing": len(strict_missing),
            "param_changed": len(param_changed),
            "missing_plus_param_changed": len(strict_missing) + len(param_changed),
        },
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
        "class_count": len(doc["classes"]),
        "class_count_check": len(doc["classes"]) == len(set(s["class"] for s in symbols if s["class"])),
        "baseline_status_all": dict(status_all.most_common()),
        "baseline_status_exports_only": dict(status_exp.most_common()),
        "baseline_check": baseline_check,
        "lead_cross_check": cmp_lead,
        "rva_cross_check": {
            "export_rva_vs_pdb_public_rva": {"checked": len(checked),
                                             "mismatch": len(mismatch),
                                             "samples": mismatch[:5]},
            "publics_without_rva": sum(1 for p in publics if not p.get("rva")),
            "note": "PDB 左列是记录偏移; 真实 RVA=节VA+addr 十进制偏移, 由 extract.py 计算",
        },
        "undecorate_failures": {
            "total": sum(1 for s in symbols if s["undecorated"] == s["mangled"] and not s["mangled"].startswith("?")),
            "exports": sum(1 for s in symbols if s["is_exported"] and s["undecorated"] == s["mangled"]),
            "publics_only": sum(1 for s in symbols if not s["is_exported"] and s["undecorated"] == s["mangled"]),
        },
        "notes": {
            "missing_semantics": "mangled 与基线不一致的导出 = missing + param_changed; "
                                 "strict missing 数 + param_changed 数才等于 Lead 的 1123",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="dui-pipeline symbols: exports.json -> symbols.json (v1 全量 / v2 瘦身)")
    ap.add_argument("--exports", default=os.path.join(BUILD, "exports.json"))
    ap.add_argument("--out", default=os.path.join(BUILD, "symbols.json"),
                    help="v1 全量输出（自证用）")
    ap.add_argument("--pinned", nargs="?", const=PINNED_DIR, default=None,
                    help="同时产 pinned/symbols.json + pinned/classes.json（schema v2）；"
                         "不带值时用仓库根 pinned/")
    ap.add_argument("--self-check", action="store_true", default=True)
    args = ap.parse_args(argv)
    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
