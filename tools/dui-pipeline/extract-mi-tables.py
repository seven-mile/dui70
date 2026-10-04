#!/usr/bin/env python3
"""extract-mi-tables.py -- derive schema-2 primary+secondary vftable tables.

WHAT THIS PRODUCES
    `pinned/mi-tables.json`: for every DirectUI class with a primary
    vftable (`??_7<C>@DirectUI@@6B@`) and/or secondary subobject tables
    (`??_7<C>@DirectUI@@6B<Base>@@`), the ordered slot lists resolved
    against pinned/symbols.json -- the multi-base (MI) extension of
    schema-1 vtable-slots.json, which keeps covering primaries only.

TWO-SECTION SCHEMA (deliberate; see "length provenance"):
    {
      "schema": 2,
      "derived": { ... },   # pure function of DLL bytes + symbols.json
      "manual": {           # HUMAN ABI INPUTS -- never claimed derived
        "interface_lengths": {"IProvider": 1, "RefcountBase": 2}
      }
    }

    The `derived` section is re-derivable and byte-compared by repro.py
    gate R3'' (R3-double-prime). The `manual` section is locked by G1
    (pinned.sha256) but is NOT covered by any re-derivation claim: a
    table whose length has no in-binary evidence is bounded by a HUMAN
    interface-length input, and mixing that into a "pure function"
    claim would be self-certification. Derived vs manual is recorded
    per table as "length_provenance":
        "next-vftable"  bounded by the next vftable symbol RVA
                        (vftables are packed in .rdata; hard evidence)
        "manual:<name>" bounded by manual.interface_lengths[name]
                        (human ABI input; the derived section still
                        records the slots it can see, but the LENGTH is
                        an input, so the table may be a prefix)
        "unknown"       no length evidence of either kind -> slots are
                        emitted but the length is NOT asserted; the
                        emitter must treat the tail as UNKNOWN and must
                        not guess (接口无表长证据不猜).

DERIVATION RULES (identical philosophy to schema 1)
    * slot entries: "Name" (unique symbol at target RVA), ["N1","N2"]
      (ICF fold candidates, sorted, union semantics), or [] (no symbol
      at the target RVA -- thunk/int3/unknown).
    * a table ENDS at: a zero pointer, an entry that does not point
      into an executable section, or the next vftable RVA -- whichever
      comes first. The next-vftable bound is the only DERIVED length
      evidence; the exec-section stop is a conservative cut (the table
      may in truth continue past a non-code entry only if the entry is
      data, which cannot happen for a real vftable, so this cut is
      sound).
    * secondary tables are keyed by their BASE name exactly as it
      appears in the mangled symbol (DirectUI-namespace bases use
      `6B<Base>@1@@`, external COM interfaces use `6B<IFace>@@`).
    * template classes (`??_7?$...`) are included with their full
      mangled class key; nothing about them is special-cased.

USAGE
    python tools/dui-pipeline/extract-mi-tables.py \
        --dll <pinned dui70.dll> \
        --symbols pinned/symbols.json \
        --out pinned/mi-tables.json \
        [--lengths pinned/mi-interface-lengths.json]

    --lengths (optional) points at the MANUAL interface-length JSON:
        {"IProvider": 1, "RefcountBase": 2, ...}
    The manual file is the human-ABI-input source of truth; it is
    copied verbatim into the output's "manual" section so G1 (which
    locks pinned/) covers it, while R3'' re-derives and compares ONLY
    the "derived" section.

    Exit codes: 0 ok; 2 input/structural error.
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

MIN_TABLES = 100  # structural floor: refuse an implausibly empty result

# Primary: ??_7<C>@DirectUI@@6B@  (C is a plain identifier)
PRIM_RE = re.compile(r"^\?\?_7([A-Za-z_]\w*)@DirectUI@@6B@$")
# Secondary in the DirectUI namespace: ??_7<C>@DirectUI@@6B<Base>@1@@
SEC_DUI_RE = re.compile(r"^\?\?_7([A-Za-z_]\w*)@DirectUI@@6B([A-Za-z_]\w*)@1@@$")
# Secondary to an external interface: ??_7<C>@DirectUI@@6B<IFace>@@
# (anything after 6B that is not <X>@1@@ -- e.g. IAccessible@@,
# IRawElementProviderSimple@@)
SEC_EXT_RE = re.compile(r"^\?\?_7([A-Za-z_]\w*)@DirectUI@@6B(.+?)@@$")
# Template class primary/secondary (class key starts with ?$)
TPL_RE = re.compile(
    r"^\?\?_7(\?\$[A-Za-z_]\w*@[^@]*(?:@[^@]*)*?)@DirectUI@@6B([A-Za-z_]\w*)?@?1?@?$")


def parse_pe(blob: bytes):
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


def classify_vftable(mangled: str):
    """Return (class_key, base_or_None) for a ??_7 symbol, else None.

    base is:
      None                 primary table (bare 6B@)
      "<DirectUI base>"    a DirectUI-namespace base (6B<B>@1@@)
      "<external iface>"   an external COM interface base (6B<I>@@)
    """
    if not mangled.startswith("??_7"):
        return None
    body = mangled[len("??_7"):]
    if not body.endswith("@DirectUI@@6B") and "@DirectUI@@6B" not in body:
        return None
    # split class key from the table suffix
    i = body.find("@DirectUI@@6B")
    if i < 0:
        return None
    cls = body[:i]
    rest = body[i + len("@DirectUI@@6B"):]
    # rest forms: "@" (primary), "<B>@1@@" (dui base), "<I>@@" (ext)
    if rest == "@":
        return cls, None
    m = re.match(r"^([A-Za-z_]\w*)@1@@$", rest)
    if m:
        return cls, m.group(1)
    m = re.match(r"^(.+?)@@$", rest)
    if m:
        return cls, m.group(1)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dll", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lengths", default=None,
                    help="manual interface-lengths JSON (human ABI input; "
                         "copied verbatim into output.manual)")
    args = ap.parse_args(argv)

    dll = pathlib.Path(args.dll)
    sym_path = pathlib.Path(args.symbols)
    for p, what in ((dll, "dll"), (sym_path, "symbols.json")):
        if not p.is_file():
            print(f"extract-mi-tables: ERROR {what} missing: {p}",
                  file=sys.stderr)
            return 2

    manual: dict = {}
    if args.lengths:
        lp = pathlib.Path(args.lengths)
        if not lp.is_file():
            print(f"extract-mi-tables: ERROR --lengths file missing: {lp}",
                 file=sys.stderr)
            return 2
        manual = json.loads(lp.read_text(encoding="utf-8"))

    try:
        blob = dll.read_bytes()
        image_base, secs = parse_pe(blob)
        exec_rng = exec_ranges(blob)
        if not exec_rng:
            print("extract-mi-tables: ERROR no executable sections",
                 file=sys.stderr)
            return 2
    except (OSError, struct.error, SystemExit) as exc:
        print(f"extract-mi-tables: ERROR cannot parse PE: {exc}",
              file=sys.stderr)
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
        print(f"extract-mi-tables: ERROR symbols.json unusable: {exc}",
             file=sys.stderr)
        return 2

    # name sets at every RVA (union over all public symbols)
    names_at: dict[int, set[str]] = collections.defaultdict(set)
    for s in sym:
        rv = s.get("rva")
        if not isinstance(rv, str) or not rv:
            continue
        m = s.get("mangled") or ""
        mm = re.match(r"\?+([^@]+)@", m)
        names_at[int(rv, 16)].add(mm.group(1) if mm else m)

    # every vftable symbol: (rva, class_key, base|None)
    vft = []
    for s in sym:
        if s.get("kind") != "vftable":
            continue
        rv = s.get("rva")
        m = s.get("mangled") or ""
        if not isinstance(rv, str) or not rv:
            continue
        parsed = classify_vftable(m)
        if parsed is None:
            continue
        vft.append((int(rv, 16), parsed[0], parsed[1]))
    vt_sorted = sorted({r for r, _, _ in vft})

    stat: collections.Counter = collections.Counter()

    def read_table(rva: int, max_len: int | None):
        """Read slots until a hard stop. Returns (slots, provenance).

        Hard stops (in order of the walk):
          * zero pointer            -> table ended cleanly
          * non-code entry          -> left the table (k>0: stop; k==0:
                                       keep as empty slot, fail-open)
          * next vftable RVA        -> derived length bound
          * max_len (manual)        -> manual length bound (prefix!)
        provenance is the TIGHTER bound that cut the table:
          "next-vftable"  the in-binary bound won (derived evidence)
          "manual"        the manual input cut at or before the derived
                          bound (the human input is the length evidence;
                          when both agree the manual side is still
                          recorded -- an input that matches evidence is
                          confirmation, not derivation)
          "hard-stop"     a zero pointer / non-code entry ended the walk
          "unknown"       no bound applied (length NOT asserted)
        """
        off = rva_to_off(rva)
        if off is None:
            return None, "unmapped"
        i = bisect.bisect_right(vt_sorted, rva)
        nxt = vt_sorted[i] if i < len(vt_sorted) else None
        slots = []
        provenance = "unknown"
        k = 0
        while True:
            hit_manual = max_len is not None and k >= max_len
            hit_next = nxt is not None and rva + 8 * k >= nxt
            if hit_manual or hit_next:
                # when both fire at the same k the manual input AGREES
                # with the derived bound: record "manual" (the length is
                # an input; the derived bound corroborates it)
                provenance = "manual" if hit_manual else "next-vftable"
                break
            if k >= 400:
                provenance = "unknown"
                break
            p = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            if p == 0:
                provenance = "hard-stop"
                break
            if not is_code_target(p - image_base):
                if k > 0:
                    provenance = "hard-stop"
                    break
                stat["bad_slot0"] += 1
                slots.append([])
                k += 1
                continue
            cands = names_at.get(p - image_base)
            if not cands:
                stat["unresolved"] += 1
                slots.append([])
            else:
                ordered = sorted(cands)
                slots.append(ordered[0] if len(ordered) == 1 else ordered)
            k += 1
        return slots, provenance

    iface_lengths: dict[str, int] = manual.get("interface_lengths", {})

    # group tables by class
    by_class: dict[str, dict] = collections.defaultdict(dict)
    for rva, cls, base in vft:
        if base is None:
            by_class[cls]["_primary_rva"] = rva
        else:
            by_class[cls].setdefault("_secondaries", {})[base] = rva

    derived: dict[str, dict] = {}
    n_tables = 0
    for cls in sorted(by_class):
        info = by_class[cls]
        entry: dict = {}
        prva = info.get("_primary_rva")
        if prva is not None:
            slots, prov = read_table(prva, iface_lengths.get(cls))
            if slots is not None:
                entry["primary"] = {
                    "rva": "0x%08X" % prva,
                    "slots": slots,
                    "length_provenance": prov,
                }
                n_tables += 1
        secs_ = info.get("_secondaries", {})
        if secs_:
            sec_out = {}
            for base in sorted(secs_):
                rva = secs_[base]
                slots, prov = read_table(rva, iface_lengths.get(base))
                if slots is None:
                    continue
                sec_out[base] = {
                    "rva": "0x%08X" % rva,
                    "slots": slots,
                    "length_provenance": prov,
                }
                n_tables += 1
            if sec_out:
                entry["secondaries"] = sec_out
        if entry:
            derived[cls] = entry

    doc = {
        "schema": 2,
        "derived": derived,
        "manual": manual,
    }

    if n_tables < MIN_TABLES:
        print(f"extract-mi-tables: ERROR only {n_tables} tables parsed "
              f"(floor {MIN_TABLES}) -- refusing to emit.", file=sys.stderr)
        return 2

    dst = pathlib.Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")

    n_prim = sum(1 for e in derived.values() if "primary" in e)
    n_sec = sum(len(e.get("secondaries", {})) for e in derived.values())
    provs = collections.Counter()
    for e in derived.values():
        if "primary" in e:
            provs[e["primary"]["length_provenance"]] += 1
        for s in e.get("secondaries", {}).values():
            provs[s["length_provenance"]] += 1
    print(f"extract-mi-tables: classes={len(derived)} "
          f"primary={n_prim} secondary={n_sec} total={n_tables}")
    print(f"  slot stats: {dict(stat)}")
    print(f"  length provenance: {dict(provs)}")
    print(f"  manual interface_lengths: {len(iface_lengths)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
