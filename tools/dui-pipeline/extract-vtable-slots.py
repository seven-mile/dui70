#!/usr/bin/env python3
"""extract-vtable-slots.py -- derive the vtable ground-truth table from dui70.dll.

WHAT THIS PRODUCES
    `pinned/vtable-slots.json`: for every class with a primary vftable
    (mangled `??_7<C>@DirectUI@@6B@`), the ordered slot list resolved against
    pinned/symbols.json.

    The table is a PURE FUNCTION of exactly two inputs:

        dui70.dll bytes          (sha256-locked by pinned/manifest.json)
        pinned/symbols.json      (byte-locked by repro.py gate R3)

    It reads NEITHER DirectUI/include/** (that would inherit the very
    header-ordering bug it exists to detect) NOR pinned/classes.json
    (hand-curated, not re-derivable). Because the table is a pure function
    of two locked inputs, it can be -- and is -- re-derived and byte-compared
    by repro.py gate R3' ("R3-prime"). It is NOT a hand-maintained truth
    table: any hand edit diverges from re-derivation and fails R3'.

SCHEMA (schema: 1)
    {
      "schema": 1,
      "classes": {
        "<Class>": {
          "rva": "0x00107F18",              # primary vftable RVA (ICF grouping)
          "slots": [ ... ]                   # position == slot index
        }
      },
      "icf_groups": {                        # DERIVED from equal rva, not declared
        "0x00104ED0": ["HWNDElementProvider", "TouchSelectPopupProvider"]
      }
    }

    Each slot is EXACTLY ONE list element (so len(slots) == real slot count and
    a slot can never shift the sequence):
        "Name"          the slot's RVA resolves to exactly one symbol member
        ["N1","N2",..]  ICF: several symbols share this RVA (candidates, sorted;
                        take the UNION when matching, never names[0])
        []              no symbol resolves at this RVA (thunk / int3 / unknown)

    ICF groups are DERIVED by grouping classes on equal vftable RVA -- there is
    deliberately no icf-groups.json exemption table (a hand-written list the
    gate reads would be an unconstrained hole: adding all 103 classes to it
    would make the J1 gate pass vacuously). Editing an rva to fake a shared
    vtable is caught by R3' byte-comparison against re-derivation.

USAGE
    python tools/dui-pipeline/extract-vtable-slots.py \
        --dll C:/Windows/System32/dui70.dll \
        --symbols pinned/symbols.json \
        --slots pinned/vtable-slots.json

    Exit codes: 0 ok; 2 input/structural error (e.g. a truncated or wrong DLL
    parsing to fewer than 100 primary vftables -- refuse rather than emit an
    empty table that downstream might mistake for "zero divergences").
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import pathlib
import re
import struct
import sys

# A truncated/garbage DLL previously produced rc=0 with an EMPTY table, which
# downstream looked like "0 divergences = green". Refuse instead. The floor is
# deliberately below the known 175 so it detects structural failure (bad PE /
# wrong file) rather than merely a revision change.
MIN_CLASSES = 100

# Primary vftable of a DirectUI class: the FIRST (leftmost) base subobject.
# Multi-base subobject tables (`??_7<C>@DirectUI@@6B<Base>@@`) and templates
# are intentionally NOT part of this table.
PRIM_RE = re.compile(r"^\?\?_7([A-Za-z_]\w*)@DirectUI@@6B@$")


def parse_pe(blob: bytes):
    """Return (image_base, sections); section = (VA, VSize, RawPtr, RawSize).

    Field order note: the section header stores (VirtualSize, VirtualAddress,
    SizeOfRawData, PointerToRawData) at offset +8; an earlier prototype unpacked
    base/size swapped so every slot was read from the wrong file offset (Button
    decoded as IsGlobal/AddChild/... instead of _EButton/OnPropertyChanged/...).
    The ICF grouping looked right through that bug because it only used rva
    strings from symbols.json -- which is exactly why this function carries the
    comment: a gate bug that still groups correctly is the dangerous kind.
    """
    e = struct.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    optsz = struct.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    if struct.unpack_from("<H", blob, opt)[0] != 0x20B:
        raise SystemExit("not PE32+ (x64)")
    image_base = struct.unpack_from("<Q", blob, opt + 24)[0]
    secs = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", blob, o + 8)
        secs.append((vaddr, vsize, raddr, rsize))
    return image_base, secs


def exec_ranges(blob: bytes) -> list[tuple[int, int]]:
    """Virtual-address ranges of every executable section (ENTRY targets).

    A vftable entry is a code pointer: it must land inside a section
    marked IMAGE_SCN_MEM_EXECUTE. On dui70.dll that is .text + fothk
    (the import forwarder thunks). Anything else -- .rdata string
    literals, .data pointers, misaligned garbage -- marks the END of
    the table: the extractor was reading PAST the table into adjacent
    .rdata (string tables, other constants) whenever the next vftable
    symbol happened to sit far away. 42 classes had such phantom tails
    (DUIXmlParser: 36 phantom slots read out of a layout-factory string
    table; Layout: 3 phantom slots past ??_ELayout).
    """
    e = struct.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    optsz = struct.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    ranges = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", blob, o + 8)
        ch = struct.unpack_from("<I", blob, o + 36)[0]
        if ch & 0x20000000:  # IMAGE_SCN_MEM_EXECUTE
            ranges.append((vaddr, vaddr + vsize))
    return ranges


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dll", required=True, help="path to the pinned dui70.dll")
    ap.add_argument("--symbols", required=True, help="pinned/symbols.json")
    ap.add_argument("--slots", required=True, help="output vtable-slots.json path")
    ap.add_argument("--max-slots", type=int, default=400,
                    help="per-class slot cap (ModernProgressBar exceeds this; "
                         "truncation is printed, never silent)")
    args = ap.parse_args(argv)

    dll = pathlib.Path(args.dll)
    sym_path = pathlib.Path(args.symbols)
    for p, what in ((dll, "dll"), (sym_path, "symbols.json")):
        if not p.is_file():
            print(f"extract-vtable-slots: ERROR  {what} missing: {p}", file=sys.stderr)
            return 2

    try:
        blob = dll.read_bytes()
        image_base, secs = parse_pe(blob)
        exec_rng = exec_ranges(blob)
        if not exec_rng:
            print("extract-vtable-slots: ERROR  no executable sections -- "
                  "not a sane image", file=sys.stderr)
            return 2
    except (OSError, struct.error, SystemExit) as exc:
        print(f"extract-vtable-slots: ERROR  cannot parse PE: {exc}", file=sys.stderr)
        return 2

    def is_code_target(rva: int) -> bool:
        return any(lo <= rva < hi for lo, hi in exec_rng)

    def rva_to_off(rva: int):
        for va, vsize, raddr, rsize in secs:
            if va <= rva < va + max(vsize, rsize):
                off = raddr + (rva - va)
                if 0 <= off < len(blob):
                    return off
        return None

    try:
        sym = json.loads(sym_path.read_text(encoding="utf-8"))["symbols"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"extract-vtable-slots: ERROR  symbols.json unusable: {exc}",
              file=sys.stderr)
        return 2

    # names_at[rva] = every symbol member name whose rva equals it. Use ALL
    # symbols: exports-only misses _purecall and unexported publics, which
    # misresolves 192 pure-virtual slots in the wrong variant.
    names_at: dict[int, set[str]] = collections.defaultdict(set)
    vftable_rvas: set[int] = set()
    for s in sym:
        rv = s.get("rva")
        if not isinstance(rv, str) or not rv:
            continue
        r = int(rv, 16)
        if s.get("kind") == "vftable":
            vftable_rvas.add(r)
        m = s.get("mangled") or ""
        if m.startswith("?"):
            mm = re.match(r"\?+([^@]+)@", m)
            if mm:
                names_at[r].add(mm.group(1))
        else:
            names_at[r].add(m)
    vt_sorted = sorted(vftable_rvas)

    prim: dict[str, int] = {}
    for s in sym:
        if s.get("kind") == "vftable":
            m = PRIM_RE.match(s.get("mangled") or "")
            if m:
                prim[m.group(1)] = int(s["rva"], 16)

    classes: dict[str, dict] = {}
    stat: collections.Counter = collections.Counter()
    truncated: list[str] = []
    for cls in sorted(prim):
        rva = prim[cls]
        off = rva_to_off(rva)
        if off is None:
            stat["unmapped"] += 1
            continue
        # Table runs until the NEXT vftable symbol RVA (vftables are packed
        # back-to-back in .rdata), a zero pointer, or an entry that does
        # NOT point into an executable section (the hard end-of-table
        # signal: vftable entries are code pointers; anything else means
        # the read has left the table and entered adjacent .rdata).
        i = bisect.bisect_right(vt_sorted, rva)
        end = vt_sorted[i] if i < len(vt_sorted) else None
        n = (end - rva) // 8 if end else 64
        if n > args.max_slots:
            n = args.max_slots
            truncated.append(cls)
        slots = []
        for k in range(max(1, n)):
            p = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            if p == 0:
                break
            if not is_code_target(p - image_base):
                if k > 0:
                    # entry outside every executable section: the table
                    # ended before this slot (never counted as a slot)
                    stat["stopped_non_code"] += 1
                    break
                # slot 0 itself is not a code pointer: keep it as an
                # empty slot (fail-open toward [], the audit will flag)
                stat["bad_slot0"] += 1
                slots.append([])
                continue
            cands = names_at.get(p - image_base)
            if not cands:
                stat["unresolved"] += 1
                slots.append([])
                continue
            ordered = sorted(cands)
            if len(ordered) == 1:
                slots.append(ordered[0])
                stat["unique"] += 1
            else:
                slots.append(ordered)
                stat["ambiguous"] += 1
        classes[cls] = {"rva": "0x%08X" % rva, "slots": slots}

    # ---- DERIVED ICF grouping: equal rva => same vtable. No declaration table.
    by_rva: dict[str, list[str]] = collections.defaultdict(list)
    for c, v in classes.items():
        by_rva[v["rva"]].append(c)
    icf = {r: sorted(v) for r, v in by_rva.items() if len(v) > 1}

    doc = {"schema": 1, "classes": classes, "icf_groups": icf}

    if len(classes) < MIN_CLASSES:
        print(f"extract-vtable-slots: ERROR  only {len(classes)} primary vftables "
              f"parsed (floor {MIN_CLASSES}) -- refusing to emit. Input is probably "
              f"not the expected dui70.dll.", file=sys.stderr)
        return 2

    dst = pathlib.Path(args.slots)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")

    print(f"extract-vtable-slots: classes={len(classes)} bytes={dst.stat().st_size}")
    print(f"  slots: {dict(stat)}")
    print(f"  ICF groups derived: {len(icf)}")
    for r in sorted(icf):
        print(f"    {r}: {', '.join(icf[r])}")
    if truncated:
        print(f"  truncated (slot cap {args.max_slots}): {truncated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
