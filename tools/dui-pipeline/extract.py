#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dui-pipeline / symbols module -- 产物 1: pinned/exports.json (+ manifest 指纹校验)

从真实 dui70.dll 的导出表（dumpbin /exports）与公开 PDB 的 publics 提取符号，
规范化后写入 pinned/exports.json（见 INTERFACE.md 1.2）。

契约: tools/dui-pipeline/INTERFACE.md — 字段名/枚举不得擅改。

输出结构（严格按契约 1.2）:
{
  "exports": [ { ordinal, name, rva } ]
}
- 无 forwarded 字段（dui70 无转发导出；转发器在解析阶段已剔除）
- 无 publics 块（publics 是 symbols.json 的输入职责）
- 无 meta 块（身份信息在 manifest.json，单一事实源）
- 导出名记为 name（86 个纯 C 导出没有修饰名，name 比 mangled 更诚实）

**指纹锚（契约 1.1 规则）**：写 pinned/ 前校验 DLL/PDB 的 sha256 与
pinned/manifest.json 一致；不符则拒绝写入并要求显式 `--new-pin`。

只用标准库（Python 3.11）。外部工具:
  dumpbin.exe  : C:\\Program Files\\...\\Hostx64\\x64\\dumpbin.exe
  llvm-pdbutil : (可选, 仅当 PDB 存在时用于交叉校验 GUID/age)

用法:
  python extract.py                        # 校验指纹后产 pinned/exports.json
  python extract.py --new-pin               # 指纹不符时显式确认换版并重写 manifest
  python extract.py --verify-pin            # 只校验指纹，不写任何文件
  python extract.py --pinned <dir>          # 指定 pinned 目录（默认 <repo>/pinned）
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import os
import re
import shutil
import struct
import subprocess
import sys

# --------------------------------------------------------------------------
# 路径与外部工具
# --------------------------------------------------------------------------
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL_DLL_X64 = r"C:\Windows\System32\dui70.dll"
# pinned/ 是可提交的契约输入；BUILD 是放缓存与交接文件的工作目录（可丢弃重建）
BUILD = os.path.join(REPO, ".local", "build")
PINNED = os.path.join(REPO, "pinned")
# 缓存目录：存放 dumpbin 原始输出与 PDB publics 文本的副本，便于离线复跑
CACHE = os.path.join(REPO, ".local", "cache")

# 外部工具逻辑名 -> (可执行文件名候选, 覆盖用环境变量)
_TOOLS = {
    "dumpbin": (("dumpbin", "dumpbin.exe"), "DUMPBIN"),
    "pdbutil": (("llvm-pdbutil", "llvm-pdbutil.exe"), "LLVM_PDBUTIL"),
}


def tool_path(name):
    """Resolve an external tool to an absolute path.

    Order:
      1. the tool-specific environment variable (see _TOOLS);
      2. PATH;
      3. for dumpbin only, the newest MSVC installation found via vswhere
         (Visual Studio does not put its tools on PATH by default).

    Raises with an actionable message when the tool is absent, so a missing
    dependency is reported as such rather than as a confusing parse failure.
    """
    candidates, env = _TOOLS[name]
    if env and os.environ.get(env):
        return os.environ[env]
    for cand in candidates:
        found = shutil.which(cand)
        if found:
            return found
    if name == "dumpbin":
        found = _dumpbin_from_vs()
        if found:
            return found
    raise SystemExit(
        "required external tool %r not found; install it and/or set %s to its "
        "full path (dumpbin ships with the MSVC toolset: run from a Developer "
        "Command Prompt, or install Visual Studio's C++ workload)"
        % (candidates[0], env))


def _dumpbin_from_vs():
    """Locate dumpbin.exe in the newest MSVC toolset via vswhere, if present."""
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return None
    try:
        p = subprocess.run([vswhere, "-latest", "-products", "*",
                            "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-property", "installationPath"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    root = (p.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    if not root:
        return None
    msvc = os.path.join(root[0], "VC", "Tools", "MSVC")
    if not os.path.isdir(msvc):
        return None
    arch = "x64" if struct.calcsize("P") * 8 == 64 else "x86"
    for ver in sorted(os.listdir(msvc), reverse=True):
        cand = os.path.join(msvc, ver, "bin", "Host%s" % arch, arch, "dumpbin.exe")
        if os.path.isfile(cand):
            return cand
    return None


# --------------------------------------------------------------------------
# 指纹锚（契约 1.1）
# --------------------------------------------------------------------------

def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def load_manifest(pinned_dir):
    p = os.path.join(pinned_dir, "manifest.json")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_pin(pinned_dir, dll=None, pdb=None):
    """校验 DLL/PDB 指纹与 manifest 一致。

    返回 (ok, report)。report 逐项列出 expected/actual。
    """
    mf = load_manifest(pinned_dir)
    rep = {"manifest": os.path.join(pinned_dir, "manifest.json"), "checks": [], "ok": True}
    if mf is None:
        # 无 manifest: 首次 pin，允许（由调用方决定是否补写）
        rep["ok"] = True
        rep["manifest_missing"] = True
        rep["checks"].append({"what": "manifest", "expected": "present",
                              "actual": "absent", "ok": True,
                              "note": "首次 pin, manifest 将由 --pinned 写入"})
        return True, rep

    for what, path, spec in (("dll", dll or REAL_DLL_X64, mf.get("dll") or {}),
                             ("pdb", pdb, mf.get("pdb") or {})):
        # pdb 不在 manifest 里则不校验（PDB 是可选的交叉校验来源）
        if path is None:
            rep["checks"].append({"what": what, "expected": "n/a",
                                  "actual": "not supplied", "ok": True,
                                  "note": "未提供 %s 路径，跳过指纹校验" % what})
            continue
        if not os.path.isfile(path):
            rep["checks"].append({"what": what, "path": path, "expected": "file exists",
                                  "actual": "missing", "ok": False})
            rep["ok"] = False
            continue
        actual_size = os.path.getsize(path)
        actual_sha = sha256_file(path)
        exp_sha = (spec.get("sha256") or "").upper()
        exp_size = spec.get("size")
        item = {"what": what, "path": path,
                "expected": {"sha256": exp_sha, "size": exp_size},
                "actual": {"sha256": actual_sha, "size": actual_size},
                "sha256_match": actual_sha == exp_sha,
                "size_match": actual_size == exp_size}
        item["ok"] = item["sha256_match"] and item["size_match"]
        if not item["ok"]:
            rep["ok"] = False
        rep["checks"].append(item)
    return rep["ok"], rep


def build_manifest(pinned_dir, dll, pdb, prev=None, new_pin=False):
    """按契约 1.1 组装 manifest.json。prev 用于保留 toolchain/pinned_utc。"""
    fv, fv_detail = file_version(dll)
    pi = pe_info(dll)
    pub_guid = pdb_guid_age(pdb) if pdb and os.path.isfile(pdb) else None
    dll_name = os.path.basename(dll)
    mf = {
        "dll": {
            "name": dll_name,
            "arch": pi["arch"],
            # 口径 = FixedFileInfo（文件字节），不是 System32 路径的 WRP 元数据。
            # 详见 file_version() 的 docstring 与 CI.md 的 repro 一节。
            "file_version": fv,
            "size": os.path.getsize(dll),
            "sha256": sha256_file(dll),
            # 这份 binary 从哪来（静态凭证）。槽位是可派生的，repro 会现算并交叉核对。
            "source_url": msdl_source_url(dll_name, pi),
            "msdl_slot": msdl_slot(pi),
            "obtain_hint": "msdl (see source_url); verify sha256 before refreshing. "
                           "Locally it also exists as C:\\Windows\\System32\\dui70.dll "
                           "on Win11 26100, but that path reports a WRP servicing "
                           "version (10.0.26100.8875) instead of the file's own "
                           "FixedFileInfo (%s)." % (fv,),
        },
        "pdb": {
            "guid": pi["pdb_guid"] or (pub_guid or {}).get("pdb_guid"),
            "age": pi["pdb_age"] if pi["pdb_age"] is not None else (pub_guid or {}).get("pdb_age"),
            "size": os.path.getsize(pdb) if pdb and os.path.isfile(pdb) else None,
            "sha256": sha256_file(pdb) if pdb and os.path.isfile(pdb) else None,
            # 规范符号服务器路径：GUID 去连字符 + age 直拼（无分隔符）。
            # 与 dll 侧的 source_url/msdl_slot 对称，repro 会现算槽位并交叉核对。
            "source_url": pdb_source_url(pi["pdb_guid"],
                                         pi["pdb_age"],
                                         pi.get("pdb_name") or "dui70.pdb"),
            "msdl_slot": pdb_msdl_slot(pi["pdb_guid"], pi["pdb_age"]),
            "obtain_hint": "msdl (see source_url); verify sha256 before refreshing. "
                           "The slot is '<GUID without hyphens><age>' -- hyphenated or "
                           "space-separated forms are not valid symbol-server paths "
                           "and 404. Publics from this PDB are what make the rebuilt "
                           "symbols.json complete (11983 rows).",
        },
        "toolchain": (prev or {}).get("toolchain") or {
            "dumpbin": dumpbin_version(),
            "note": "undname output is read-only consumption; version differences "
                    "should not affect pinned content",
        },
        "pinned_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return mf


def dumpbin_version():
    rc, out, err = run([tool_path("dumpbin")])
    txt = (out or "") + (err or "")
    m = re.search(r"(\d+\.\d+\.\d+[\.\d]*)", txt)
    return m.group(1) if m else "unknown"

# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

def run(cmd, timeout=600):
    """运行外部程序, 返回 (returncode, stdout, stderr)。文本模式, 宽松解码。"""
    p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    dec = lambda b: (b or b"").decode("utf-8", errors="replace")
    return p.returncode, dec(p.stdout), dec(p.stderr)


def fmt_rva(v):
    """契约示例: "0x00026D5A" -> 0x + 8 位大写十六进制。"""
    if v is None:
        return None
    return "0x%08X" % (int(v) & 0xFFFFFFFF)


def ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


# --------------------------------------------------------------------------
# PE 解析: 架构 + 调试目录里的 RSDS (PDB GUID/Age)
# --------------------------------------------------------------------------
IMAGE_FILE_MACHINE = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64", 0x01C4: "arm"}

# msdl 符号服务器槽位：<TimeDateStamp:8位大写HEX><SizeOfImage:小写HEX>
# 大小写混合是 winbindex 的 makeSymbolServerUrl 的原样语义，不要"统一"成同一大小写。
MSDL_BASE = "https://msdl.microsoft.com/download/symbols"


def msdl_slot(pi):
    """由 PE 头字段算出 msdl 槽位串。

    槽位是**派生物**：能算就不要存。存下来的 URL 是"这份 binary 从哪来"的
    静态凭证，repro 时应现算并与凭证交叉核对（见 CI.md 的 repro 一节）。
    """
    if pi.get("timestamp") is None or pi.get("size_of_image") is None:
        return None
    return "%08X%x" % (pi["timestamp"], pi["size_of_image"])


def msdl_source_url(dll_name, pi):
    """组装 dui70.dll 在 msdl 上的下载 URL（槽位现算）。"""
    slot = msdl_slot(pi)
    if slot is None:
        return None
    return "%s/%s/%s/%s" % (MSDL_BASE, dll_name, slot, dll_name)


def pdb_msdl_slot(guid, age):
    """PDB 在 msdl 上的槽位串 = GUID 去连字符(大写) + age 十进制直拼。

    规范路径是 ``<GUID 去掉连字符><age>``（两者之间没有分隔符、没有空格）。
    带连字符或带空格的 ``"<GUID> <age>"`` 形态不是合法的符号服务器路径，
    服务器对它只会返回 404。详见 CI.md 的 repro 一节。
    """
    if not guid or age is None:
        return None
    return "%s%d" % (guid.replace("-", "").upper(), int(age))


def pdb_source_url(guid, age, pdb_name="dui70.pdb"):
    """组装 dui70.pdb 在 msdl 上的下载 URL（槽位现算，与 dll 侧对称）。

    msdl 对文件名大小写不敏感（实测 dui70.pdb 与 DUI70.pdb 同 200），
    这里统一用 RSDS 里的名字，回退到 dui70.pdb。
    """
    slot = pdb_msdl_slot(guid, age)
    if slot is None:
        return None
    return "%s/%s/%s/%s" % (MSDL_BASE, pdb_name, slot, pdb_name)


def pe_info(path):
    """返回 dict(machine, arch, timestamp, size_of_image, pdb_guid, pdb_age,
    pdb_name, sections)。

    timestamp / size_of_image 是 msdl 符号槽位地址的两个组成部分
    （见 msdl_source_url()），必须按文件字节读取，不得硬编码。

    sections: [ {index(1-based), name, virtual_address, virtual_size}, ... ]
    """
    info = {"machine": None, "arch": None, "timestamp": None, "size_of_image": None,
            "pdb_guid": None, "pdb_age": None,
            "pdb_name": None, "sections": []}
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 0x40 or data[:2] != b"MZ":
        return info
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return info
    coff = e_lfanew + 4
    machine = struct.unpack_from("<H", data, coff)[0]
    info["machine"] = machine
    info["arch"] = IMAGE_FILE_MACHINE.get(machine, "unknown(0x%04X)" % machine)
    info["timestamp"] = struct.unpack_from("<I", data, coff + 4)[0]
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x20B:      # PE32+
        dd_off = opt + 112
    elif magic == 0x10B:    # PE32
        dd_off = opt + 96
    else:
        return info
    info["size_of_image"] = struct.unpack_from("<I", data, opt + 56)[0]
    # data directory 6 = debug
    dbg_rva, dbg_size = struct.unpack_from("<II", data, dd_off + 6 * 8)
    if not dbg_rva:
        return info
    # RVA -> file offset 需要 section 表
    sec = opt + opt_size
    sections = []
    for i in range(nsec):
        off = sec + i * 40
        if off + 40 > len(data):
            break
        sname = data[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((vaddr, max(vsize, rawsize), rawptr))
        info["sections"].append({"index": i + 1, "name": sname,
                                 "virtual_address": fmt_rva(vaddr),
                                 "virtual_size": fmt_rva(vsize)})

    def rva2off(rva):
        for vaddr, vsz, rawptr in sections:
            if vaddr <= rva < vaddr + vsz:
                return rawptr + (rva - vaddr)
        return None

    dbg_off = rva2off(dbg_rva)
    if dbg_off is None:
        return info
    # IMAGE_DEBUG_DIRECTORY: Characteristics(0) TimeDateStamp(4) Major/Minor(8)
    #                        Type(12) SizeOfData(16) AddressOfRawData(20) PointerToRawData(24)
    for i in range(dbg_size // 28):
        off = dbg_off + i * 28
        if off + 28 > len(data):
            break
        typ = struct.unpack_from("<I", data, off + 12)[0]
        if typ != 2:  # IMAGE_DEBUG_TYPE_CODEVIEW
            continue
        # AddressOfRawData(+20) is an RVA; PointerToRawData(+24) is a file offset.
        # Go through the section table (rva2off) for the canonical mapping. The two
        # coincide when the image happens to map RSDS into a file-offset-equal slot
        # (dui70 26100/28000), but differ on Win10-era builds (1507/1607/2004), where
        # treating ptr_raw as an RVA lands in the wrong section and the RSDS header
        # is never found (parsing ptr_raw as a file offset worked there only by luck
        # of coincidental section alignment).
        a_rva = struct.unpack_from("<I", data, off + 20)[0]
        p = rva2off(a_rva)
        if p is None or data[p:p + 4] != b"RSDS":
            continue
        guid = data[p + 4:p + 20]
        age = struct.unpack_from("<I", data, p + 20)[0]
        d1, d2, d3 = struct.unpack_from("<IHH", guid, 0)
        d4 = guid[8:10].hex().upper()
        rest = guid[10:16].hex().upper()
        info["pdb_guid"] = "%08X-%04X-%04X-%s-%s" % (d1, d2, d3, d4, rest)
        info["pdb_age"] = age
        info["pdb_name"] = data[p + 24:data.find(b"\0", p + 24)].decode("ascii", "replace")
        break
    return info


# --------------------------------------------------------------------------
# 文件版本: 用 Win32 version API (ctypes, 标准库)
# --------------------------------------------------------------------------

def file_version(path):
    """读 VS_VERSIONINFO。

    返回 (file_version, detail)：
      file_version —— 契约 manifest.dll.file_version 采用的值 = **FixedFileInfo**
                      （文件字节里的真实版本，可复现），无则退回字符串版本。
      detail       —— {"fixed_fileinfo": ..., "string_fileversion": ...,
                       "mismatch": bool}，用于把差异显式记录下来。

    关于 x64 dui70.dll 的版本号（实测结论）：

      * 对 System32 的 pinned 件（sha256 2080E43F…）逐字节搜索，
        "10.0.26100.8875" 出现 **0** 次，"10.0.26100.9278" 出现 2 次；
        文件里的 FixedFileInfo 与 StringFileInfo 都是 9278。
      * GetFileVersionInfo 对 **System32 这条路径** 报 8875，对 sha256
        完全相同的副本（Z:\\、C:\\Windows\\ 下、WinSxS 原件）一律报 9278。
      * 机制：System32\\dui70.dll 是硬链接到
        WinSxS\\amd64_..._dui70_..._10.0.26100.9278_...\\dui70.dll；
        该路径的版本查询由服务栈/WRP 元数据回答（该 slot 记录的原始安装
        修订是 8875），**不读文件字节**。WinSxS 现存版本系列里没有 8875。

    结论：8875 是"System32 路径 + 本机服务栈状态"的元数据，换台机器换条路径
    就变；9278 才是文件字节的事实。因此 manifest 记 9278（可复现口径），
    8875 仅作为历史注记保留（见 CI.md repro 一节）。
    """
    fixed = None
    string = None
    try:
        ver = ctypes.windll.version
    except Exception:
        # 非 Windows 平台（ctypes.windll 不存在）—— 返回 None，调用方按"未知"处理
        return None, {"fixed_fileinfo": None, "string_fileversion": None, "mismatch": False}
    size = ver.GetFileVersionInfoSizeW(ctypes.c_wchar_p(path), None)
    if not size:
        return None, {"fixed_fileinfo": None, "string_fileversion": None, "mismatch": False}
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(ctypes.c_wchar_p(path), 0, size, buf):
        return None, {"fixed_fileinfo": None, "string_fileversion": None, "mismatch": False}
    ptr = ctypes.c_void_p()
    length = ctypes.c_uint()
    if ver.VerQueryValueW(buf, ctypes.c_wchar_p("\\"), ctypes.byref(ptr), ctypes.byref(length)):
        ms, ls = struct.unpack_from("<II", ctypes.string_at(ptr.value, 16), 8)
        fixed = "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    if ver.VerQueryValueW(buf, ctypes.c_wchar_p("\\VarFileInfo\\Translation"),
                          ctypes.byref(ptr), ctypes.byref(length)):
        raw = ctypes.string_at(ptr.value, length.value)
        for i in range(0, len(raw) - 3, 4):
            lang, cp = struct.unpack_from("<HH", raw, i)
            sub = "\\StringFileInfo\\%04x%04x\\FileVersion" % (lang, cp)
            if ver.VerQueryValueW(buf, ctypes.c_wchar_p(sub), ctypes.byref(ptr),
                                  ctypes.byref(length)):
                string = ctypes.wstring_at(ptr.value, length.value).rstrip("\0")
                break
    # 只取形如 a.b.c.d 的版本号
    strver = None
    if string:
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)", string)
        if m:
            strver = m.group(1)
    # 契约口径 = FixedFileInfo（文件字节里的真实版本，可复现）。
    # 字符串版本只在 FixedFileInfo 不可得时兜底；两者的差异照旧记录不吞。
    fv = fixed if fixed is not None else strver
    detail = {"fixed_fileinfo": fixed, "string_fileversion": string,
              "string_version_only": strver,
              "mismatch": bool(fixed and strver and fixed != strver)}
    return fv, detail


# --------------------------------------------------------------------------
# dumpbin /exports 解析
# --------------------------------------------------------------------------
# 正常导出行:  "    1905  76F 00026D5A ?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z"
# 转发导出行:  "    1905  76F 00026D5A Name = OtherDll.OtherFunc"   (@ILT 转发器)
# 静态数据行:  "    1905  76F 00026D5A name = ?name@@3HA (int DirectUI::name)"
_EXPORT_LINE = re.compile(
    r"^\s*(?P<ordinal>\d+)\s+(?P<hint>[0-9A-Fa-f]+)\s+(?P<rva>[0-9A-Fa-f]{8})\s+(?P<rest>\S.*?)\s*$"
)
_FORWARDER = re.compile(r"^(?P<name>\S+)\s*=\s*(?P<target>.*?)\s*$")
_STATIC_DATA_NOTE = re.compile(r"^(?P<name>\S+)\s*=\s*(?P<mangled>\S+)\s*\((?P<note>.*)\)\s*$")


def parse_dumpbin_exports(text):
    """解析 dumpbin /exports 输出。

    返回 (exports, stats):
      exports: [ {ordinal:int, rva:"0x...", mangled:str, forwarded:None|str}, ... ]
      stats:   计数信息(用于运行报告)
    """
    exports = []
    stats = {"lines": 0, "forwarded": 0, "static_data": 0, "skipped": []}
    for line in text.splitlines():
        m = _EXPORT_LINE.match(line)
        if not m:
            continue
        stats["lines"] += 1
        rest = m.group("rest")
        ordinal = int(m.group("ordinal"))
        rva = int(m.group("rva"), 16)
        mangled = rest
        forwarded = None

        if "=" in rest:
            sd = _STATIC_DATA_NOTE.match(rest)
            if sd and " " not in sd.group("name"):
                # 静态数据形式: "name = mangled (注释)" -> 以 mangled 为准, 注释丢弃
                mangled = sd.group("mangled")
                stats["static_data"] += 1
            else:
                fw = _FORWARDER.match(rest)
                if fw:
                    # 转发器: 导出名 = 目标; 剔除 "= @ILT+NNN(...)" 后缀
                    mangled = fw.group("name")
                    forwarded = fw.group("target")
                    stats["forwarded"] += 1
        exports.append({"ordinal": ordinal, "rva": fmt_rva(rva),
                        "mangled": mangled, "forwarded": forwarded})
    return exports, stats


def dumpbin_exports(dll, cache_file=None, refresh=True):
    """运行 dumpbin /exports, 可用 cache_file 缓存原始文本。返回 (text, source)。

    cache_file 是**缓存**而非输入依赖：命中且未要求 refresh 时直接复用，
    以便在没有 MSVC 的机器上离线复跑；缺缓存时会现场调用 dumpbin 重建。
    """
    if cache_file and not refresh and os.path.isfile(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), "cache:" + cache_file
    rc, out, err = run([tool_path("dumpbin"), "/exports", dll])
    if rc != 0 and "number of functions" not in out:
        raise RuntimeError("dumpbin failed rc=%s\n%s\n%s" % (rc, out[-2000:], err[-2000:]))
    text = out + ("\n" + err if err.strip() else "")
    if cache_file:
        ensure_dir(os.path.dirname(cache_file))
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(text)
    return text, "dumpbin"


# --------------------------------------------------------------------------
# PDB publics 解析 (llvm-pdbutil dump -publics 原始文本)
#
#   格式(两行一组):
#     "  307800 | S_PUB32 [size = 60] `??4DuiNavigate@DirectUI@@QEAAAEAV01@AEBV01@@Z`"
#     "           flags = function, addr = 0001:462544"
#
#   左列 "307800" 是 PDB 记录偏移（col1），**不是 RVA**。真实 RVA 需按
#   该符号所在节的 VirtualAddress 加上 addr 冒号后的十进制偏移算出。
#   例: ?DuiNavigate 属 section 1(.text, VA=0x1000)，addr=0001:462544 ->
#       RVA = 0x1000 + 462544 = 0x71ED0，与 dumpbin /exports 的 0x00071ED0 一致。
#   4319 个同时出现在导出表中的符号全部吻合（0 个不匹配）。
# --------------------------------------------------------------------------
_PUB_LINE = re.compile(r"^\s*(?P<col1>\d+)\s*\|\s*S_PUB32\b[^`]*`(?P<name>[^`]*)`\s*$")
_PUB_ADDR = re.compile(r"^\s*flags\s*=\s*(?P<flags>\w+)\s*,\s*addr\s*=\s*(?P<sec>\d+):(?P<off>\d+)\s*$")
_CSV_LINE = re.compile(r'^"?(\d+)"?,"?(.+?)"?\s*$')


def parse_pdb_publics_text(text, sections=None):
    """解析 llvm-pdbutil -publics 文本。

    sections: {index(1-based int): virtual_address(int)}；给出时计算真实 rva，
              否则 rva=None（并把 col1 记到 record_offset）。
    """
    sections = sections or {}
    publics = []
    detail = []
    pending = None
    for line in text.splitlines():
        m = _PUB_LINE.match(line)
        if m:
            pending = {"record_offset": int(m.group("col1")), "mangled": m.group("name"),
                       "rva": None, "section": None, "section_offset": None, "flags": None}
            # 契约要求 publics 元素恰好是 {rva, mangled}; 其余诊断信息单独收集
            publics.append({"rva": None, "mangled": m.group("name")})
            detail.append(pending)
            continue
        a = _PUB_ADDR.match(line)
        if a and pending is not None:
            sec = int(a.group("sec"))
            off = int(a.group("off"))          # 十进制
            pending["flags"] = a.group("flags")
            pending["section"] = sec
            pending["section_offset"] = fmt_rva(off)
            if sec in sections:
                pending["rva"] = fmt_rva(sections[sec] + off)
                publics[-1]["rva"] = pending["rva"]
            pending = None
    return publics, detail


def read_pdb_publics(path, sections=None):
    """支持三种来源: llvm-pdbutil 文本 dump / pdb-symbols CSV / 纯名字列表。

    返回 (publics, detail, source)。publics 严格为契约形状 [{rva, mangled}]。
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if "S_PUB32" in text:
        pubs, detail = parse_pdb_publics_text(text, sections)
        return pubs, detail, "pdbutil-text"
    publics, detail = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('"RVA"'):
            continue
        m = _CSV_LINE.match(line)
        if m:
            # 注意: 该 CSV 第 1 列名为 "RVA", 实为 PDB 记录偏移, 不是 RVA。
            publics.append({"rva": None, "mangled": m.group(2)})
            detail.append({"rva": None, "mangled": m.group(2), "record_offset": int(m.group(1)),
                           "section": None, "section_offset": None, "flags": None})
        else:
            publics.append({"rva": None, "mangled": line})
            detail.append({"rva": None, "mangled": line, "record_offset": None,
                           "section": None, "section_offset": None, "flags": None})
    return publics, detail, "csv/name-list"


def pdb_guid_age(pdb):
    """用 llvm-pdbutil 读 PDB 的 GUID/Age (仅用于与 DLL 的 RSDS 交叉校验)。

    llvm-pdbutil 与 PDB 都是可选的：任一缺失即返回 None，交叉校验跳过，
    不影响 DLL 自身 RSDS 提供的 GUID/Age（那才是权威来源）。
    """
    if not pdb or not os.path.isfile(pdb):
        return None
    try:
        pdbutil = tool_path("pdbutil")
    except SystemExit:
        return None
    rc, out, err = run([pdbutil, "dump", "-summary", pdb])
    txt = out + err
    guid = re.search(r"GUID:\s*\{?([0-9A-Fa-f\-]{36})\}?", txt)
    age = re.search(r"Age:\s*(\d+)", txt)
    if guid:
        return {"pdb_guid": guid.group(1).upper(), "pdb_age": int(age.group(1)) if age else None}
    return None


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def build(args):
    dll = args.dll
    if not os.path.isfile(dll):
        raise SystemExit("DLL not found: %s" % dll)
    ensure_dir(args.build)
    raw_dir = os.path.join(args.build, "raw")

    text, src = dumpbin_exports(
        dll,
        cache_file=os.path.join(raw_dir, "dumpbin-exports-%s.txt"
                               % os.path.splitext(os.path.basename(dll))[0]),
        refresh=not args.no_refresh)
    exports, estats = parse_dumpbin_exports(text)

    pdb_path = args.pdb_publics
    pi = pe_info(dll)
    sections = {}
    for s in pi["sections"]:
        try:
            sections[s["index"]] = int(s["virtual_address"], 16)
        except (TypeError, ValueError):
            pass
    publics, pub_detail, psrc = ([], [], "none")
    if pdb_path and os.path.isfile(pdb_path):
        publics, pub_detail, psrc = read_pdb_publics(pdb_path, sections)

    fv, fv_detail = file_version(dll)

    pub_guid = pdb_guid_age(args.pdb) if args.pdb else None
    # 优先用 DLL 自己的 RSDS (那是"这个 dll 对应哪个 pdb"的权威证据)
    meta = {
        "dll": dll,
        "file_version": fv,
        "arch": pi["arch"],
        "pdb_guid": pi["pdb_guid"] or (pub_guid or {}).get("pdb_guid"),
        "pdb_age": pi["pdb_age"] if pi["pdb_age"] is not None else (pub_guid or {}).get("pdb_age"),
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # ---------------- pinned/exports.json（契约 1.2） ----------------
    pin_dir = args.pinned
    ok, vrep = verify_pin(pin_dir, dll=dll, pdb=args.pdb)
    pinned_report = {"verify_pin": vrep}
    if not ok and not args.new_pin:
        raise SystemExit(
            "pin 指纹不匹配，拒绝刷新 pinned/。\n"
            + json.dumps(vrep, ensure_ascii=False, indent=2)
            + "\n如确为有意换版，请加 --new-pin 显式确认。")
    # 写 manifest（首次 pin 或 --new-pin）
    prev = load_manifest(pin_dir)
    if prev is None or args.new_pin or not ok:
        mf = build_manifest(pin_dir, dll, args.pdb, prev=prev, new_pin=args.new_pin)
        ensure_dir(pin_dir)
        with open(os.path.join(pin_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(mf, f, ensure_ascii=False, indent=2)
            f.write("\n")
        pinned_report["manifest_written"] = os.path.join(pin_dir, "manifest.json")
        pinned_report["manifest"] = mf
    export_table = {"exports": [{"ordinal": e["ordinal"], "name": e["mangled"], "rva": e["rva"]}
                                for e in exports]}
    ensure_dir(pin_dir)
    pin_out = os.path.join(pin_dir, "exports.json")
    with open(pin_out, "w", encoding="utf-8") as f:
        json.dump(export_table, f, ensure_ascii=False, indent=1)
        f.write("\n")
    pinned_report["out"] = pin_out
    pinned_report["exports"] = len(export_table["exports"])
    pinned_report["size_bytes"] = os.path.getsize(pin_out)

    # ---------------- 内部交接文件（model.py 的输入） ----------------
    # pinned/exports.json 按契约只有 {ordinal,name,rva}，不含 PDB publics；
    # 而 publics（含 RVA）是 model.py 必需的。这里把原始解析结果落到
    # --build 指定的工作目录（默认 .local/build/，git 忽略、可丢弃重建），
    # 不是 tracked 产物。
    # pub_flags 一并带上，使 model.py 不必回头去读 PDB publics 的原始文本。
    raw_path = os.path.join(args.build, "extract-raw.json")
    ensure_dir(args.build)
    pub_flags = {d["mangled"]: d.get("flags") for d in pub_detail if d.get("flags")}
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "exports": exports, "publics": publics,
                   "pub_flags": pub_flags},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")
    pinned_report["raw_handoff"] = raw_path

    # ---------------- 运行报告 ----------------
    exp_names = [e["mangled"] for e in exports]
    exp_set = set(exp_names)
    pub_names = [p["mangled"] for p in publics]
    pub_set = set(pub_names)
    derivable = sum(1 for e in exports if e["mangled"].startswith("?"))
    report = {
        "out": pin_out,
        "dumpbin_source": src,
        "publics_source": psrc,
        "export_rows": len(exports),
        "export_unique_mangled": len(exp_set),
        "export_duplicates": len(exp_names) - len(exp_set),
        "export_forwarded": estats["forwarded"],
        "export_static_data_form": estats["static_data"],
        "export_non_decorated": len(exports) - derivable,
        "publics_rows": len(publics),
        "publics_unique_mangled": len(pub_set),
        "publics_duplicates": len(pub_names) - len(pub_set),
        "publics_also_exported": len(pub_set & exp_set),
        "pe_machine": pi["machine"],
        "pe_sections": pi["sections"],
        "pe_rsds": {"guid": pi["pdb_guid"], "age": pi["pdb_age"], "name": pi["pdb_name"]},
        "file_version_details": fv_detail,
        "pdb_file": ({"path": args.pdb, **(pub_guid or {})} if args.pdb else None),
        "meta": meta,
    }

    # 可选的交叉校验：若调用方另外提供了一份"已知正确的导出名清单"
    # （每行一个名字），则与其逐名比对。这不是运行依赖 —— 不提供就跳过。
    if args.cross_check and os.path.isfile(args.cross_check):
        with open(args.cross_check, "r", encoding="utf-8", errors="replace") as f:
            norm = set(l.strip() for l in f if l.strip())
        report["cross_check"] = {
            "file": args.cross_check,
            "count": len(norm),
            "equal": norm == exp_set,
            "only_in_file": len(norm - exp_set),
            "only_in_dumpbin": len(exp_set - norm),
            "samples_only_in_file": sorted(norm - exp_set)[:10],
            "samples_only_in_dumpbin": sorted(exp_set - norm)[:10],
        }

    # PDB public RVA vs 导出 RVA（两者都提供时逐符号核对）
    exp_rva = {e["mangled"]: e["rva"] for e in exports}
    checked = mismatch = 0
    samples = []
    for p in pub_detail:
        if p.get("rva") and p["mangled"] in exp_rva:
            checked += 1
            if p["rva"] != exp_rva[p["mangled"]]:
                mismatch += 1
                if len(samples) < 5:
                    samples.append({"mangled": p["mangled"], "export": exp_rva[p["mangled"]],
                                    "public": p["rva"]})
    report["rva_cross_check"] = {"checked": checked, "mismatch": mismatch, "samples": samples}
    report["publics_without_rva"] = sum(1 for p in publics if not p.get("rva"))
    report["publics_rva_note"] = (
        "PDB publics 左列(col1)是记录偏移, 不是 RVA; rva = 节 VA + addr 的十进制偏移")
    report["version_note"] = (
        "manifest.dll.file_version 取 VS_VERSIONINFO 的 FixedFileInfo（文件字节口径）"
        "= %s。注意 System32 这条路径会被 Windows 服务栈/WRP 元数据回答成 8875，"
        "那是路径元数据不是文件内容（'10.0.26100.8875' 在文件字节里出现 0 次）；"
        "详见 file_version() docstring 与 CI.md 的 repro 一节。" % (fv,))
    if pinned_report is not None:
        report["pinned"] = pinned_report

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="dui-pipeline: 真实 DLL + PDB -> pinned/exports.json（含 manifest 指纹校验）")
    ap.add_argument("--dll", default=REAL_DLL_X64,
                    help="待提取的 dui70.dll（默认系统 x64 副本 %s）" % REAL_DLL_X64)
    ap.add_argument("--pdb", default=None,
                    help="对应的 dui70.pdb。提供后用于交叉校验 GUID/Age 并解析 "
                         "publics；缺失则只依赖 DLL 的导出表与 RSDS。")
    ap.add_argument("--pdb-publics", default=None,
                    help="llvm-pdbutil -publics 文本或符号清单的路径；"
                         "提供后其符号并入 pinned/symbols.json")
    ap.add_argument("--cross-check", default=None,
                    help="可选的导出名清单（每行一个），用于交叉校验导出集合")
    ap.add_argument("--build", default=BUILD,
                    help="缓存/交接目录（dumpbin 原始输出、model.py 的输入）")
    ap.add_argument("--pinned", default=PINNED,
                    help="pinned 目录（默认 <repo>/pinned）")
    ap.add_argument("--new-pin", action="store_true",
                    help="指纹不符时显式确认换版并重写 manifest")
    ap.add_argument("--verify-pin", action="store_true",
                    help="只校验指纹，不写任何文件")
    ap.add_argument("--no-refresh", action="store_true",
                    help="复用 .local/build/raw/ 下已缓存的 dumpbin 输出")
    args = ap.parse_args(argv)

    if args.verify_pin:
        ok, rep = verify_pin(args.pinned, dll=args.dll, pdb=args.pdb)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
