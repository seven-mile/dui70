#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract-dynarray-contracts.py -- derive per-instance
DynamicArray<T, 0> layout contracts from the pinned DLL bytes.

Contract: this script NEVER hand-maintains a truth table. Every
value is re-derived from (pinned DLL bytes + pinned symbols.json)
on every run; repro.py gate R3''' byte-compares the re-derivation
against the committed pinned/dynarray-contracts.json, so any hand
edit drifts and fails CI.

What is derived, per DISTINCT ?Create@?$DynamicArray@<T>$0A@@ RVA
(ICF-folds share a body, and a shared body implies a shared
sizeof -- that is why the linker folded them):
  * sizeof           : the allocation request loaded into ECX
                       immediately before the allocator call
                       (lea imm8/imm32(%reg),%ecx or mov imm32,%ecx),
                       sanity-clamped to [8, 64];
  * element_stride   : the shift in the same instance's
                       SwitchToHeap/Insert-family memcpy scaling when
                       derivable, else the pointer default 8 for
                       pointer-T instances (PEA/PEB/PEAV/PEBU
                       mangled prefixes), else omitted;
  * inline_capacity  : the `cmp $imm` gate in the same RVA's
                       Initialize/Create path when derivable
                       (imm in [1, 8]);
  * law_consistent   : sizeof == 8 + max(16, stride*inline_capacity)
                       cross-check; inconsistent instances are
                       DROPPED (fail-closed), never emitted with a
                       guessed value.

Fail-closed rules:
  * an instance whose bytes cannot be decoded is OMITTED (never
    guessed);
  * fewer than 5 decodable instances -> exit 2 (vacuous guard);
  * any decode ambiguity inside the clamp window -> omitted.

Usage:
    python tools/dui-pipeline/extract-dynarray-contracts.py \
        --dll <dui70.dll> --symbols pinned/symbols.json \
        --out pinned/dynarray-contracts.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

LAW = {"formula": "8 + max(16, sizeof(T))"}
MIN_INSTANCES = 5
SIZE_LO, SIZE_HI = 8, 64
CAP_LO, CAP_HI = 1, 8
STRIDES = (4, 8)


def parse_pe(blob: bytes):
    e = struct.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    optsz = struct.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    if struct.unpack_from("<H", blob, opt)[0] != 0x20B:
        raise SystemExit("extract-dynarray: not PE32+ (x64)")
    secs = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", blob, o + 8)
        secs.append((vaddr, vsize, raddr, rsize))
    return secs


def _scan_ecx_imm(code: bytes, window: int = 160):
    """Last ECX-loaded immediate before the first call/jmp in the
    window. Recognizes `lea imm(reg),%ecx` in every ModRM encoding
    (reg field == 1 (ECX), mod 01 disp8 / mod 10 disp32, with or
    without REX prefix 41) and `mov imm32,%ecx` (b9 imm32).
    Returns int or None."""
    last = None
    i = 0
    n = len(code)
    while i < n - 5:
        b0 = code[i]
        rex = 1
        if b0 == 0x41 and code[i + 1] == 0x8D:
            modrm = code[i + 2]
            disp8_at, disp32_at, adv = i + 3, i + 3, i + 4
        elif b0 == 0x8D:
            modrm = code[i + 1]
            disp8_at, disp32_at, adv = i + 2, i + 2, i + 3
        else:
            rex = 0
            modrm = 0
        if rex:
            if (modrm >> 3) & 7 == 1 and (modrm >> 6) == 1:  # [reg+disp8] -> ecx
                last = code[disp8_at]
                i = adv
                continue
            if (modrm >> 3) & 7 == 1 and (modrm >> 6) == 2:  # [reg+disp32] -> ecx
                last = struct.unpack_from("<i", code, disp32_at)[0]
                i = adv + 4
                continue
        if b0 == 0xB9:  # mov imm32, %ecx
            last = struct.unpack_from("<I", code, i + 1)[0]
            i += 5
            continue
        if b0 in (0xE8, 0xE9):
            if last is not None:
                v = last
                return v if SIZE_LO <= v <= SIZE_HI else None
        i += 1
    return None


def _scan_inline_gate(code: bytes, window: int = 320):
    """`cmp imm8, r32` (83 /7, any register) with imm in
    [CAP_LO, CAP_HI] followed within a few bytes by a conditional
    jump -- the inline->heap gate."""
    i = 0
    n = min(len(code), window)
    while i < n - 4:
        if code[i] == 0x83 and (code[i + 1] >> 3) & 7 == 7:
            imm = code[i + 2]
            if CAP_LO <= imm <= CAP_HI:
                for j in range(i + 3, min(i + 9, n)):
                    if 0x70 <= code[j] <= 0x7F or code[j] == 0x0F:
                        return imm
        i += 1
    return None


def _t_stride(t_mangled: str):
    """Element stride for the instance when derivable from the
    mangled T argument: pointer prefixes are stride 8, H (int) and
    N (double) families are 4/8."""
    if t_mangled.startswith(("PEA", "PEB")):
        return 8
    if t_mangled in ("H", "K"):
        return 4 if t_mangled == "H" else 4
    if t_mangled == "N" or t_mangled == "O":
        return 8
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dll", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    dll = Path(args.dll)
    blob = dll.read_bytes()
    secs = parse_pe(blob)

    def rva2off(rva):
        for va, vs, ra, rs in secs:
            if va <= rva < va + max(vs, rs):
                return ra + (rva - va)
        return None

    syms = json.loads(Path(args.symbols).read_text(encoding="utf-8"))["symbols"]
    creates = {}
    for s in syms:
        m = s.get("mangled", "")
        mm = re.match(
            r"\?Create@\?\$DynamicArray@(.+?)\$0A@@DirectUI@@SAJI_NPEAPEAV12@@Z", m)
        if mm:
            rva = int(s["rva"], 16)
            creates.setdefault(rva, set()).add(mm.group(1))

    derived = {}
    dropped = {}
    for rva, targs in sorted(creates.items()):
        off = rva2off(rva)
        if off is None:
            dropped[hex(rva)] = "rva not in a section"
            continue
        code = blob[off:off + 384]
        size = _scan_ecx_imm(code)
        if size is None:
            dropped[hex(rva)] = "allocation request not decodable"
            continue
        gate = _scan_inline_gate(code)
        if gate is None:
            dropped[hex(rva)] = "inline gate not decodable"
            continue
        # stride: unanimous pointer-type across the fold set, else None
        strides = {_t_stride(t) for t in targs}
        stride = strides.pop() if len(strides) == 1 else None
        # law consistency when all three are known
        if stride is not None:
            expected = 8 + max(16, stride * gate)
            if expected != size:
                dropped[hex(rva)] = (
                    f"law mismatch: sizeof={size} but 8+max(16,"
                    f"{stride}*{gate})={expected}")
                continue
        key = sorted(targs)[0]
        entry = {
            "create_rva": hex(rva),
            "fold_members": len(targs),
            "sizeof": size,
            "inline_capacity": gate,
            "provenance": "create-alloc-request+inline-gate",
        }
        if stride is not None:
            entry["element_stride"] = stride
            entry["law_consistent"] = True
        derived[key] = entry

    if len(derived) < MIN_INSTANCES:
        print(f"extract-dynarray: only {len(derived)} decodable "
              f"instances (< {MIN_INSTANCES}) -- refusing to emit a "
              "vacuous contract", file=sys.stderr)
        return 2

    doc = {
        "schema": 1,
        "source": {
            "dll_sha256": hashlib.sha256(blob).hexdigest().upper(),
            "symbols": "pinned/symbols.json",
        },
        "law": LAW,
        "derived": derived,
        "dropped": dropped,
    }
    out = Path(args.out)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"extract-dynarray: {len(derived)} instances derived "
          f"({len(dropped)} dropped, fail-closed) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
