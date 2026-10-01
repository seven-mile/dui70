#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dui-pipeline / symbols module -- 产物 1: pinned/exports.json (+ manifest 指纹校验)

从真实 dui70.dll 的导出表（dumpbin /exports）与公开 PDB 的 publics 提取符号，
规范化后写入 pinned/exports.json（schema v2, 见 INTERFACE.md 1.2）。

契约: tools/dui-pipeline/INTERFACE.md v2 — 字段名/枚举不得擅改。

v2 输出结构（严格按契约 1.2）:
{
  "schema_version": 2,
  "exports": [ { ordinal, name, rva } ]
}
- 删 forwarded（dui70 无转发导出）
- 删 publics 块（publics 职责属于 symbols.json）
- 删 meta 块（身份信息上移 manifest，单一事实源）
- mangled 更名 name

**指纹锚（契约 1.1 规则）**：写 pinned/ 前校验 DLL/PDB 的 sha256 与
pinned/manifest.json 一致；不符则拒绝写入并要求显式 `--new-pin`。

只用标准库（Python 3.11）。外部工具:
  dumpbin.exe  : C:\\Program Files\\...\\Hostx64\\x64\\dumpbin.exe
  llvm-pdbutil : (可选, 仅当 PDB 存在时用于交叉校验 GUID/age)

用法:
  python extract.py                        # 产 .local/build/exports.json（v1 全量, 自证用）
  python extract.py --pinned               # 产 pinned/exports.json（v2 瘦身, 校验指纹）
  python extract.py --pinned --new-pin     # 指纹不符时显式确认并重写 manifest
  python extract.py --pinned --verify-pin  # 只校验指纹，不写任何文件
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import json
import os
import re
import struct
import subprocess
import sys

# --------------------------------------------------------------------------
# 契约中的关键路径常量
# --------------------------------------------------------------------------
REPO = r"Z:\repos\DirectUI"
REAL_DLL_X64 = r"C:\Windows\System32\dui70.dll"
PDB_X64 = os.path.join(REPO, ".local", "symbols", "dui70-26200-x64.pdb")
PDB_PUBLICS = os.path.join(REPO, ".local", "cache", "pdb-publics-x64.txt")
REAL_NORM = os.path.join(REPO, ".local", "cache", "real-x64-norm.txt")
BUILD = os.path.join(REPO, ".local", "build")
PINNED = os.path.join(REPO, "pinned")

DUMPBIN = (r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC"
           r"\14.44.35207\bin\Hostx64\x64\dumpbin.exe")
LLVM_PDBUTIL = r"C:\Local\Tools\mingw64\bin\llvm-pdbutil.exe"


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
                             ("pdb", pdb or PDB_X64, mf.get("pdb") or {})):
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
    fv, _ = file_version(dll)
    pi = pe_info(dll)
    pub_guid = pdb_guid_age(pdb) if pdb and os.path.isfile(pdb) else None
    mf = {
        "schema_version": 2,
        "dll": {
            "name": os.path.basename(dll),
            "arch": pi["arch"],
            "file_version": fv,
            "size": os.path.getsize(dll),
            "sha256": sha256_file(dll),
            "obtain_hint": "local C:\\Windows\\System32\\dui70.dll on Win11 26100; "
                           "verify sha256 before refreshing",
        },
        "pdb": {
            "guid": pi["pdb_guid"] or (pub_guid or {}).get("pdb_guid"),
            "age": pi["pdb_age"] if pi["pdb_age"] is not None else (pub_guid or {}).get("pdb_age"),
            "size": os.path.getsize(pdb) if pdb and os.path.isfile(pdb) else None,
            "sha256": sha256_file(pdb) if pdb and os.path.isfile(pdb) else None,
            "source_url": "https://msdl.microsoft.com/download/symbols/dui70.pdb/"
                          "%s %s/dui70.pdb" % (pi["pdb_guid"], pi["pdb_age"]),
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
    rc, out, err = run([DUMPBIN])
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


def pe_info(path):
    """返回 dict(machine, arch, pdb_guid, pdb_age, pdb_name, sections)。

    sections: [ {index(1-based), name, virtual_address, virtual_size}, ... ]
    """
    info = {"machine": None, "arch": None, "pdb_guid": None, "pdb_age": None,
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
        ptr_raw = struct.unpack_from("<I", data, off + 24)[0]
        if typ != 2:  # IMAGE_DEBUG_TYPE_CODEVIEW
            continue
        p = rva2off(ptr_raw)
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
      file_version —— 契约 meta.file_version 采用的值 = StringFileInfo\\FileVersion
                      的版本串（去掉 " (WinBuild...)" 后缀），无则退回 FixedFileInfo。
      detail       —— {"fixed_fileinfo": ..., "string_fileversion": ...,
                       "mismatch": bool}，用于把二进制层面的差异显式记录下来。

    ！本机实测的坑（x64 dui70.dll）:
        FixedFileInfo(二进制) = 10.0.26100.9278
        StringFileInfo\\FileVersion = "10.0.26100.8875 (WinBuild.160101.0800)"
      INTERFACE.md 对本 DLL 记录的是 10.0.26100.8875（且 x86 两者都是 9278），
      即契约口径是"资源字符串版本"。故以字符串版本为准，并把 FixedFileInfo 差异
      一并输出，避免这个事实被静默吞掉。
    """
    fixed = None
    string = None
    try:
        ver = ctypes.windll.version
    except Exception:
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
    fv = None
    if string:
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)", string)
        if m:
            fv = m.group(1)
    if fv is None:
        fv = fixed
    detail = {"fixed_fileinfo": fixed, "string_fileversion": string,
              "mismatch": bool(fixed and fv and fixed != fv)}
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
      stats:   计数信息(用于自证/报告)
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
    """运行 dumpbin /exports, 可用 cache_file 缓存原始文本。返回 (text, source)。"""
    if cache_file and not refresh and os.path.isfile(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), "cache:" + cache_file
    rc, out, err = run([DUMPBIN, "/exports", dll])
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
#   ！！关键坑：左列 "307800" 不是 RVA，而是 PDB 里的记录偏移（本文档称 col1）。
#   真正的 RVA = 该符号所在节的 VirtualAddress + addr 冒号后的十进制偏移。
#   例: ?DuiNavigate 属 section 1(.text, VA=0x1000)，addr=0001:462544 ->
#       RVA = 0x1000 + 462544 = 0x71ED0，与 dumpbin /exports 的 0x00071ED0 完全一致。
#   （已用 4319 个同时是导出的符号全量验证: 0 个不匹配）
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
    """用 llvm-pdbutil 读 PDB 的 GUID/Age (仅用于与 DLL 的 RSDS 交叉校验)。"""
    if not os.path.isfile(LLVM_PDBUTIL) or not os.path.isfile(pdb):
        return None
    rc, out, err = run([LLVM_PDBUTIL, "dump", "-summary", pdb])
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

    doc = {"meta": meta, "exports": exports, "publics": publics}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")

    # ---------------- v2 pinned/exports.json（契约 1.2） ----------------
    pinned_report = None
    if getattr(args, "pinned", None):
        pin_dir = args.pinned
        ok, vrep = verify_pin(pin_dir, dll=dll, pdb=args.pdb)
        pinned_report = {"verify_pin": vrep}
        if not ok and not getattr(args, "new_pin", False):
            raise SystemExit(
                "pin 指纹不匹配，拒绝刷新 pinned/。\n"
                + json.dumps(vrep, ensure_ascii=False, indent=2)
                + "\n如确为有意换版，请加 --new-pin 显式确认。")
        # 写 manifest（首次 pin 或 --new-pin）
        prev = load_manifest(pin_dir)
        if prev is None or getattr(args, "new_pin", False) or not ok:
            mf = build_manifest(pin_dir, dll, args.pdb, prev=prev,
                                new_pin=getattr(args, "new_pin", False))
            ensure_dir(pin_dir)
            with open(os.path.join(pin_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(mf, f, ensure_ascii=False, indent=2)
                f.write("\n")
            pinned_report["manifest_written"] = os.path.join(pin_dir, "manifest.json")
            pinned_report["manifest"] = mf
        v2 = {"schema_version": 2,
              "exports": [{"ordinal": e["ordinal"], "name": e["mangled"], "rva": e["rva"]}
                          for e in exports]}
        ensure_dir(pin_dir)
        pin_out = os.path.join(pin_dir, "exports.json")
        with open(pin_out, "w", encoding="utf-8") as f:
            json.dump(v2, f, ensure_ascii=False, indent=1)
            f.write("\n")
        pinned_report["out"] = pin_out
        pinned_report["exports"] = len(v2["exports"])
        pinned_report["size_bytes"] = os.path.getsize(pin_out)

    # ---------------- 自证输出 ----------------
    exp_names = [e["mangled"] for e in exports]
    exp_set = set(exp_names)
    pub_names = [p["mangled"] for p in publics]
    pub_set = set(pub_names)
    derivable = sum(1 for e in exports if e["mangled"].startswith("?"))
    report = {
        "out": args.out,
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

    if os.path.isfile(REAL_NORM):
        with open(REAL_NORM, "r", encoding="utf-8", errors="replace") as f:
            norm = set(l.strip() for l in f if l.strip())
        report["cross_real_x64_norm"] = {
            "file": REAL_NORM,
            "count": len(norm),
            "equal": norm == exp_set,
            "only_in_norm": len(norm - exp_set),
            "only_in_dumpbin": len(exp_set - norm),
            "samples_only_in_norm": sorted(norm - exp_set)[:10],
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
        "契约 INTERFACE.md 对本 DLL 记录 file_version=10.0.26100.8875; 实测该值取自 "
        "VS_VERSIONINFO 的 StringFileInfo\\FileVersion（'10.0.26100.8875 "
        "(WinBuild.160101.0800)'），而同一文件的 FixedFileInfo/PE 头为 10.0.26100.9278"
        "（x86 dui70.dll 两者均为 9278）。meta.file_version 按契约口径取字符串版本。")
    if pinned_report is not None:
        report["pinned_v2"] = pinned_report

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return doc, report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="dui-pipeline symbols: dumpbin exports + PDB publics -> exports.json")
    ap.add_argument("--dll", default=REAL_DLL_X64)
    ap.add_argument("--pdb", default=PDB_X64)
    ap.add_argument("--pdb-publics", default=PDB_PUBLICS)
    ap.add_argument("--build", default=BUILD)
    ap.add_argument("--out", default=os.path.join(BUILD, "exports.json"),
                    help="v1 全量输出（自证用）")
    ap.add_argument("--pinned", nargs="?", const=PINNED, default=None,
                    help="同时产 pinned/exports.json（v2 瘦身）并校验/写 manifest；"
                         "不带值时用仓库根 pinned/")
    ap.add_argument("--new-pin", action="store_true",
                    help="指纹不符时显式确认换版并重写 manifest")
    ap.add_argument("--verify-pin", action="store_true",
                    help="只校验指纹，不写任何文件")
    ap.add_argument("--no-refresh", action="store_true",
                    help="复用 .local/build/raw/ 下已缓存的 dumpbin 输出")
    args = ap.parse_args(argv)

    if args.verify_pin:
        pin_dir = args.pinned or PINNED
        ok, rep = verify_pin(pin_dir, dll=args.dll, pdb=args.pdb)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    build(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
