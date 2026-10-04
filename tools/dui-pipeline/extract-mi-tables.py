#!/usr/bin/env python3
"""extract-mi-tables.py -- schema-3 MI vftable tables + ctor-store order.

WHAT THIS PRODUCES
    `pinned/mi-tables.json`: for every DirectUI class with a primary
    vftable (`??_7<C>@DirectUI@@6B@`) and/or secondary subobject tables
    (`??_7<C>@DirectUI@@6B<Base>@@`), the ordered slot lists resolved
    against pinned/symbols.json -- the multi-base (MI) extension of
    schema-1 vtable-slots.json, which keeps covering primaries only.

SCHEMA 3 ADDS (over schema 2)
    * `ctor_store_order`: for every class whose constructor is in the
      pinned symbols, the order in which the ctor's code references
      the class's own vftables (rip-relative LEA targets), together
      with the ctor RVA -- direct OBJECT-LAYOUT observation. It is
      evidence about subobject INITIALISATION order in the compiled
      binary; it is NOT the source-level base-declaration order
      (declaration order is not recoverable from a binary).
    * `identity` per table: "primary" (unsuffixed `6B@`) or
      "secondary" with its base name from the mangled suffix.
    * fail-closed manual/derived conflict rule (see below).

TWO-SECTION SCHEMA (deliberate; see "length provenance")
    {
      "schema": 3,
      "derived": { ... },   # pure function of DLL bytes + symbols.json
      "manual": {           # HUMAN ABI INPUTS -- never claimed derived
        "interface_lengths": {"IProvider": 1, "RefcountBase": 2},
        "class_interface_lengths": {"ElementProvider": {"RefcountBase": 5}}
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
        "manual"        the manual input cut at exactly the derived
                        bound, or the bound is looser and the manual
                        value tightens an UNOBSERVABLE tail (no
                        in-binary evidence between the two)
        "manual-conflict"  FAIL-CLOSED: the manual value is SHORTER
                        than an in-binary bound (next-vftable or
                        hard-stop). A human input may tighten an
                        unobservable tail; it may NOT deny slots the
                        binary visibly contains. Conflicted tables are
                        emitted with the CONFLICT marker and the
                        emitter/audit must refuse the class (never
                        silently truncate).
        "hard-stop"     a zero pointer / non-code entry ended the walk
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

CTOR-STORE ORDER (schema 3)
    For each class with an in-symbols constructor `??0<C>@DirectUI@@QEAA...`,
    the extractor disassembles a window of the ctor and records the
    sequence of rip-relative LEA instructions whose targets are the
    class's OWN vftables (`??_7<C>@DirectUI@@6B...`). The sequence is
    the store order of subobject vptrs = object-layout observation
    (Solid Evidence). Caveats, documented not hidden:
      * store order is not necessarily declaration order (the compiler
        may reorder stores), so the EMISSION ORDERING STRATEGY derived
        from it stays Strong Inference;
      * ICF can merge ctor tails of sibling classes; only references to
        the class's OWN tables are kept;
      * classes without an in-symbols ctor get no entry (no guessing).

USAGE
    python tools/dui-pipeline/extract-mi-tables.py \
        --dll <pinned dui70.dll> \
        --symbols pinned/symbols.json \
        --out pinned/mi-tables.json \
        [--lengths pinned/mi-interface-lengths.json]

    --lengths (optional) points at the MANUAL interface-length JSON.
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
# Secondary in the DirectUI namespace: ??_7<C>@DirectUI@@6B<Base>@1@@
# Secondary to an external interface: ??_7<C>@DirectUI@@6B<IFace>@@
CTOR_RE = re.compile(r"^\?\?0([A-Za-z_]\w*)@DirectUI@@QEAA[^A]*$")


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

    # vftable rva -> mangled (for ctor-store-order resolution)
    vt_by_rva: dict[int, str] = {}
    for s in sym:
        if s.get("kind") != "vftable":
            continue
        rv = s.get("rva")
        if isinstance(rv, str) and rv:
            vt_by_rva[int(rv, 16)] = s.get("mangled") or ""

    # constructors: class -> first non-copy ctor rva
    ctor_rva: dict[str, int] = {}
    for s in sym:
        m = s.get("mangled") or ""
        rv = s.get("rva")
        if not isinstance(rv, str) or not rv:
            continue
        if m.startswith("??0") and "@DirectUI@@QEAA" in m and "AEBV" not in m:
            cls = m[3:m.index("@DirectUI@@")]
            ctor_rva.setdefault(cls, int(rv, 16))

    stat: collections.Counter = collections.Counter()

    def read_table(rva: int, max_len: int | None):
        """Read slots until a hard stop. Returns (slots, provenance).

        Hard stops (in order of the walk):
          * zero pointer            -> table ended cleanly
          * non-code entry          -> left the table (k>0: stop; k==0:
                                       keep as empty slot, fail-open)
          * next vftable RVA        -> derived length bound
          * max_len (manual)        -> manual length bound

        FAIL-CLOSED conflict rule (schema 3): when the manual bound cuts
        the table STRICTLY SHORTER than an in-binary bound (next-vftable
        or hard-stop), the human input is denying slots the binary
        visibly contains -> provenance "manual-conflict"; the table is
        emitted with the VISIBLE slots (never truncated) plus the
        marker; consumers must refuse the class.
        """
        off = rva_to_off(rva)
        if off is None:
            return None, "unmapped"
        i = bisect.bisect_right(vt_sorted, rva)
        nxt = vt_sorted[i] if i < len(vt_sorted) else None
        slots = []
        provenance = "unknown"
        visible_len: int | None = None  # in-binary bound (slots visible)
        k = 0
        while True:
            hit_manual = max_len is not None and k >= max_len
            hit_next = nxt is not None and rva + 8 * k >= nxt
            if hit_manual or hit_next:
                # continue walking to find the IN-BINARY bound first
                visible_len = k if hit_next else None
                if hit_manual and hit_next:
                    provenance = "manual"  # agrees with derived bound
                    break
                if hit_manual:
                    # manual cut first: keep walking (fail-open here,
                    # conflict detected below) to find the binary bound
                    j = k
                    vlen = None
                    while True:
                        if nxt is not None and rva + 8 * j >= nxt:
                            vlen = j
                            break
                        if j >= 400:
                            break
                        p = struct.unpack_from("<Q", blob, off + 8 * j)[0]
                        if p == 0:
                            vlen = j
                            break
                        if not is_code_target(p - image_base):
                            vlen = j
                            break
                        j += 1
                    if vlen is not None and vlen > max_len:
                        stat["manual_conflict"] += 1
                        # emit the VISIBLE slots, conflict-marked
                        slots2, _prov = _read_exact(rva, off, vlen)
                        return slots2, "manual-conflict"
                    provenance = "manual"
                    break
                provenance = "next-vftable"
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

    def _read_exact(rva: int, off: int, n: int):
        """Read exactly n visible slots (conflict path)."""
        slots = []
        for k in range(n):
            p = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            cands = names_at.get(p - image_base)
            if not cands:
                slots.append([])
            else:
                ordered = sorted(cands)
                slots.append(ordered[0] if len(ordered) == 1 else ordered)
        return slots, "manual-conflict"

    iface_lengths: dict[str, int] = manual.get("interface_lengths", {})
    # class-scoped overrides: the manual input may pin the length of a
    # SPECIFIC class's subobject table. Family-wide defaults apply only
    # when no class-scoped entry exists; a class-scoped entry is itself
    # subject to the fail-closed conflict rule.
    class_lengths: dict[str, dict[str, int]] = manual.get(
        "class_interface_lengths", {})

    def table_len(cls: str, base: str | None) -> int | None:
        ov = class_lengths.get(cls)
        if isinstance(ov, dict) and base is not None and base in ov:
            return ov[base]
        if base is None:
            return None
        return iface_lengths.get(base)

    # group tables by class
    by_class: dict[str, dict] = collections.defaultdict(dict)
    for rva, cls, base in vft:
        if base is None:
            by_class[cls]["_primary_rva"] = rva
        else:
            by_class[cls].setdefault("_secondaries", {})[base] = rva

    # ---- ctor-store-order (schema 3): object-layout observation ----
    def ctor_store_order(cls: str, limit: int = 0x300):
        crva = ctor_rva.get(cls)
        if crva is None:
            return None
        off = rva_to_off(crva)
        if off is None:
            return None
        code = blob[off:off + limit]
        events = []
        i = 0
        while i < len(code) - 7:
            # rip-relative LEA: 48 8D /r with mod=00 rm=101
            if code[i] == 0x48 and code[i + 1] == 0x8D and \
                    (code[i + 2] & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", code, i + 3)[0]
                target = crva + i + 7 + disp
                m = vt_by_rva.get(target)
                if m and m.startswith(f"??_7{cls}@DirectUI@@6B"):
                    parsed = classify_vftable(m)
                    if parsed is not None:
                        base = parsed[1] or "PRIMARY"
                        events.append({"offset": i, "table_rva": "0x%08X" % target,
                                       "base": base, "symbol": m})
                i += 7
                continue
            i += 1
        return events or None

    derived: dict[str, dict] = {}
    n_tables = 0
    for cls in sorted(by_class):
        info = by_class[cls]
        entry: dict = {}
        prva = info.get("_primary_rva")
        if prva is not None:
            slots, prov = read_table(prva, table_len(cls, None))
            if slots is not None:
                entry["primary"] = {
                    "identity": "primary",
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
                slots, prov = read_table(rva, table_len(cls, base))
                if slots is None:
                    continue
                sec_out[base] = {
                    "identity": "secondary:" + base,
                    "rva": "0x%08X" % rva,
                    "slots": slots,
                    "length_provenance": prov,
                }
                n_tables += 1
            if sec_out:
                entry["secondaries"] = sec_out
        # ctor-store-order: object-layout observation (Solid); the
        # EMISSION ordering strategy built on it is Strong Inference
        # (store order != declaration order) -- documented in schema
        cso = ctor_store_order(cls)
        if cso is not None:
            entry["ctor_store_order"] = {
                "ctor_rva": "0x%08X" % ctor_rva[cls],
                "evidence": "rip-relative LEA sequence in ctor code",
                "semantics": "object-layout observation (Solid); "
                             "NOT source-level declaration order",
                "stores": cso,
            }
        if entry:
            derived[cls] = entry

    doc = {
        "schema": 3,
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
    n_cso = sum(1 for e in derived.values() if "ctor_store_order" in e)
    provs = collections.Counter()
    for e in derived.values():
        if "primary" in e:
            provs[e["primary"]["length_provenance"]] += 1
        for s in e.get("secondaries", {}).values():
            provs[s["length_provenance"]] += 1
    print(f"extract-mi-tables: classes={len(derived)} "
          f"primary={n_prim} secondary={n_sec} total={n_tables} "
          f"ctor_store_order={n_cso}")
    print(f"  slot stats: {dict(stat)}")
    print(f"  length provenance: {dict(provs)}")
    print(f"  manual interface_lengths: {len(iface_lengths)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
