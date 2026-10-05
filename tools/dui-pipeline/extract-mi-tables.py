#!/usr/bin/env python3
"""extract-mi-tables.py -- schema-3 MI vftable tables + ctor vftable references.

WHAT THIS PRODUCES
    `pinned/mi-tables.json`: for every DirectUI class with a primary
    vftable (`??_7<C>@DirectUI@@6B@`) and/or secondary subobject tables
    (`??_7<C>@DirectUI@@6B<Base>@@`), the ordered slot lists resolved
    against pinned/symbols.json -- the multi-base (MI) extension of
    schema-1 vtable-slots.json, which keeps covering primaries only.

SCHEMA 3 ADDS (over schema 2)
    * `ctor_vftable_references`: for every class whose constructor is
      in the pinned symbols, the rip-relative LEA references to the
      class's OWN vftables, together with the ctor RVA -- REFERENCE-
      ONLY evidence (semantics: reference-only; order: ORDER-UNKNOWN).
      No base order, emission order, or declaration order is derived
      from it, and no `this+offset` store is traced or claimed.
    * `identity` per table: "primary" (unsuffixed `6B@`) or
      "secondary" with its base name from the mangled suffix.
    * fail-closed manual/derived conflict rule (see below).

TWO-SECTION SCHEMA (deliberate; see "length provenance")
    {
      "schema": 3,
      "derived": { ... },   # function(DLL bytes, symbols.json,
                            #          manual-length input)
      "manual": {           # HUMAN ABI INPUTS -- never claimed derived
        "interface_lengths": {"IProvider": 1, "RefcountBase": 2},
        "class_interface_lengths": {"ElementProvider": {"RefcountBase": 5}}
      }
    }

    The `derived` section is a function of the DLL bytes, symbols.json
    AND the manual-length input; repro.py gate R3'' proves CONDITIONAL
    re-derivability: given the same committed manual input, the derived
    section re-derives byte-identically. That is NOT an independent
    proof of the manual values themselves -- the manual section is
    locked by G1 (pinned.sha256) and is never claimed derived: a table
    whose length has no in-binary evidence is bounded by a HUMAN
    interface-length input, and claiming that input as derived would
    be self-certification. Derived vs manual is recorded
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

CTOR VFTABLE REFERENCES (schema 3)
    For each class with an in-symbols constructor `??0<C>@DirectUI@@QEAA...`,
    the extractor records the rip-relative LEA instructions, WITHIN the
    constructor's .pdata function extent only, whose targets are the
    class's OWN vftables (`??_7<C>@DirectUI@@6B...`). These are
    REFERENCES, not stores: proving a vptr STORE requires tracing the
    subsequent `this+offset` write (dataflow), which this extractor
    does not do. Every entry therefore carries
    semantics='reference-only' and order='ORDER-UNKNOWN'; NO base
    order, emission order, or declaration order is derived from this
    field. Honest limits, documented not hidden:
      * the scan is bounded by .pdata (BeginAddress/EndAddress of the
        function containing the ctor RVA); when .pdata or a covering
        entry is unavailable the field is 'unknown-scan-refused' --
        a fixed-window scan is refused rather than guessed;
      * one RVA can carry SEVERAL alias vftable symbols (ICF); ALL
        aliases are recorded as a candidate list, none dropped;
      * references inside the extent can still belong to
        compiler-generated helpers, not to C++ base initialisation;
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


def _pdata_functions(blob: bytes, secs) -> list[tuple[int, int]]:
    """Function extents from .pdata RUNTIME_FUNCTION entries.

    Returns [(BeginAddress, EndAddress), ...] sorted; empty when the
    image has no .pdata (scan consumers must REFUSE to scan then --
    a fixed window is never an acceptable substitute)."""
    e = struct.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    # locate .pdata by section name
    opt = coff + 20
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    optsz = struct.unpack_from("<H", blob, coff + 16)[0]
    for i in range(nsec):
        o = opt + optsz + i * 40
        name = blob[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
        if name != ".pdata":
            continue
        _, vaddr, _, raddr = struct.unpack_from("<IIII", blob, o + 8)
        vsize = struct.unpack_from("<I", blob, o + 8)[0]
        out = []
        n = vsize // 12
        for j in range(n):
            b, en, _u = struct.unpack_from("<III", blob, raddr + j * 12)
            if b or en:
                out.append((b, en))
        out.sort()
        return out
    return []


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
    ap.add_argument("--lengths", required=True,
                    help="manual interface-lengths JSON (human ABI input; "
                         "copied verbatim into output.manual). REQUIRED "
                         "and fail-closed: emission REQUIRES the manual "
                         "input -- an absent input is an error, never a "
                         "silent pass with unbounded tables.")
    args = ap.parse_args(argv)

    dll = pathlib.Path(args.dll)
    sym_path = pathlib.Path(args.symbols)
    for p, what in ((dll, "dll"), (sym_path, "symbols.json")):
        if not p.is_file():
            print(f"extract-mi-tables: ERROR {what} missing: {p}",
                  file=sys.stderr)
            return 2

    lp = pathlib.Path(args.lengths)
    if not lp.is_file():
        print(f"extract-mi-tables: ERROR --lengths file missing: {lp}",
             file=sys.stderr)
        return 2
    manual = json.loads(lp.read_text(encoding="utf-8"))
    for req_key in ("interface_lengths", "class_interface_lengths"):
        if not isinstance(manual.get(req_key), dict):
            print(f"extract-mi-tables: ERROR --lengths input lacks "
                  f"'{req_key}' dict -- fail-closed (N5)",
                  file=sys.stderr)
            return 2

    try:
        blob = dll.read_bytes()
        image_base, secs = parse_pe(blob)
        exec_rng = exec_ranges(blob)
        pdata_bounds = _pdata_functions(blob, secs)
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

    # every vftable symbol: (rva, class_key, base|None) -- the
    # CLASSIFIED subset (DirectUI primary/secondary classes) drives
    # which tables are EMITTED.
    vft = []
    # N6 (boundary integrity): the physical next-vftable boundary is
    # computed from ALL vftable symbol RVAs in the binary -- including
    # outer-namespace and template instantiation vftables that
    # classify_vftable() declines to classify. A foreign vftable laid
    # out directly after a DirectUI table is a REAL physical boundary:
    # reading past it pulls the foreign table's slots into the
    # DirectUI table (16 classes overread such tails, e.g.
    # CCCommandLink 74 vs true 63 -- the 11 extra slots were
    # ?$SmObjectT@VPVLLauncherAnimationTriggers... entries).
    # Classification limits the OUTPUT table set, never the boundary.
    all_vt_rvas: set = set()
    for s in sym:
        if s.get("kind") != "vftable":
            continue
        rv = s.get("rva")
        if not isinstance(rv, str) or not rv:
            continue
        all_vt_rvas.add(int(rv, 16))
        parsed = classify_vftable(s.get("mangled") or "")
        if parsed is None:
            continue
        vft.append((int(rv, 16), parsed[0], parsed[1]))
    vt_sorted = sorted(all_vt_rvas)

    # vftable rva -> ALL alias mangled names (dict[int, list[str]]).
    # One RVA can carry SEVERAL vftable symbols (ICF-folded tables
    # share an address); last-wins would silently drop aliases, so
    # every consumer gets the full sorted list.
    vt_by_rva: dict[int, list[str]] = collections.defaultdict(list)
    for s in sym:
        if s.get("kind") != "vftable":
            continue
        rv = s.get("rva")
        if isinstance(rv, str) and rv:
            vt_by_rva[int(rv, 16)].append(s.get("mangled") or "")
    for rva in vt_by_rva:
        vt_by_rva[rva] = sorted(set(vt_by_rva[rva]))

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
        # N-c: move constructors ($$QEAV by-value&& parameter) are
        # constructors too -- record them alongside copy/default ctors
        # so a class whose ONLY ctor is a move ctor still gets
        # reference evidence. $$QEAV marks the rvalue-ref parameter;
        # the check is on the mangled param encoding, not the symbol
        # kind field.
        elif m.startswith("??0") and "@DirectUI@@QEAA" in m and \
                "$$QEAV" in m:
            cls = m[3:m.index("@DirectUI@@")]
            ctor_rva.setdefault(cls, int(rv, 16))

    # ctor symbol extents from the pinned symbols table: the next
    # symbol's RVA bounds the ctor symbol's own extent (symbols are
    # RVA-sorted in practice; we compute per-class [rva, next_rva)
    # conservatively from the sorted symbol list, same-kind only).
    # Used ONLY as the safe-scan fallback when .pdata does not cover
    # the ctor (R4: symbol-bounded safe scan; never a fixed window).
    all_rvas = sorted({int(s["rva"], 16) for s in sym
                       if isinstance(s.get("rva"), str) and s.get("rva")})
    import bisect as _bi
    ctor_symbol_extents: dict[str, tuple[int, int]] = {}
    for cls, r in ctor_rva.items():
        i = _bi.bisect_right(all_rvas, r)
        if i < len(all_rvas):
            nxt = all_rvas[i]
            # conservative cap: the next symbol at most 0x200 away --
            # beyond that the symbol table gives no trustworthy bound
            if nxt - r <= 0x200:
                ctor_symbol_extents[cls] = (r, nxt)

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
                if max_len is not None and k < max_len:
                    # manual value LARGER than the in-binary bound:
                    # the input is redundant for this table (the
                    # bound already cuts earlier). Record that the
                    # manual input was ignored -- provenance must not
                    # silently swallow a redundant human input.
                    stat["manual_redundant"] += 1
                    provenance = "ignored-redundant"
                else:
                    provenance = "next-vftable"
                break
            if k >= 400:
                provenance = "unknown"
                break
            p = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            if p == 0:
                if max_len is not None and k < max_len:
                    stat["manual_redundant"] += 1
                    provenance = "ignored-redundant"
                else:
                    provenance = "hard-stop"
                break
            if not is_code_target(p - image_base):
                if k > 0:
                    if max_len is not None and k < max_len:
                        stat["manual_redundant"] += 1
                        provenance = "ignored-redundant"
                    else:
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

    # ---- ctor vftable REFERENCES (schema 3): reference-only ----
    # vt_by_rva itself now preserves ALL aliases per RVA
    # (dict[int, list[str]]); the reference scan consumes it directly.

    def ctor_vftable_references(cls: str):
        """Rip-relative LEA references to the class's OWN vftables,
        bounded by the ctor's function extent.

        REFERENCE-ONLY: a vptr store would additionally require a
        traced `this+offset` write (dataflow) -- out of scope, so
        order='ORDER-UNKNOWN' and NO base/emission order is derived.
        Bounding, in order of preference:
          1. .pdata function extent (scan=pdata-bounded);
          2. symbol-bounded safe scan: the ctor symbol's own extent
             as reported by the pinned symbols table
             (scan=symbol-bounded-safe) -- the walk never leaves the
             symbol's reported extent;
          3. refused (scan=unknown-scan-refused) -- fixed windows are
             never an acceptable substitute."""
        crva = ctor_rva.get(cls)
        if crva is None:
            return None
        extent = None
        scan_mode = None
        if pdata_bounds:
            for b, en in pdata_bounds:
                if b <= crva < en:
                    extent = (b, en)
                    scan_mode = "pdata-bounded"
                    break
        if extent is None:
            sym_ext = ctor_symbol_extents.get(cls)
            if sym_ext is not None:
                extent = sym_ext
                scan_mode = "symbol-bounded-safe"
            else:
                return {
                    "scan": "unknown-scan-refused",
                    "reason": "ctor rva not covered by .pdata and no "
                              "symbol-bounded extent available",
                }
        off = rva_to_off(crva)
        if off is None:
            return None
        end_off = rva_to_off(extent[1])
        if end_off is None:
            end_off = off + (extent[1] - extent[0])
        code = blob[off:end_off]
        events = []

        def decode_lea(idx: int):
            """(target_rva, reg) for a rip-relative LEA at idx, else None."""
            if code[idx] in (0x48, 0x4C) and code[idx + 1] == 0x8D \
                    and (code[idx + 2] & 0xC7) == 0x05:
                disp = struct.unpack_from("<i", code, idx + 3)[0]
                reg = ((code[idx + 2] >> 3) & 7) + \
                    (8 if code[idx] == 0x4C else 0)
                return (crva + idx + 7 + disp, reg)
            return None

        i = 0
        while i < len(code) - 7:
            lea = decode_lea(i)
            if lea is None:
                i += 1
                continue
            target, lea_reg = lea
            i += 7
            if target not in vt_by_rva:
                continue
            aliases = [m for m in vt_by_rva[target]
                       if m.startswith(f"??_7{cls}@DirectUI@@6B")]
            if not aliases:
                continue
            cands = []
            for m in aliases:
                parsed = classify_vftable(m)
                base = (parsed[1] or "PRIMARY") \
                    if parsed is not None else "?"
                cands.append({"base": base, "symbol": m})
            # vptr STORE decode: walk forward for a MOV [reg+disp], reg2
            # (89 /r with SIB or no-SIB disp8/disp32, REX.W) whose source
            # register is the LEA destination. The disp IS the subobject
            # this-offset; without a traced store the reference keeps
            # store_offset=None (position never substitutes for offset).
            store_offset = None
            store_at = None
            j = i
            while j < min(i + 24, len(code) - 4):
                # a new vptr computation (LEA) ends this store window
                if decode_lea(j) is not None:
                    break
                b0, b1, b2 = code[j], code[j + 1], code[j + 2]
                if b0 in (0x48, 0x49, 0x4C, 0x4D) and b1 == 0x89:
                    mod = (b2 >> 6) & 3
                    rm = b2 & 7
                    src = ((b2 >> 3) & 7) + (8 if b0 & 1 else 0)
                    if rm == 4:
                        sib = code[j + 3]
                        if (sib & 7) == 5:
                            j += 1
                            continue  # RIP-relative: not a vptr store
                        base_reg = (sib & 7) + (8 if b0 & 2 else 0)
                        disp_off = j + 4
                    else:
                        base_reg = rm + (8 if b0 & 2 else 0)
                        disp_off = j + 3
                    if src == lea_reg:
                        if mod == 0:
                            disp = 0
                        elif mod == 1:
                            disp = struct.unpack_from("<b", code,
                                                      disp_off)[0]
                        elif mod == 2:
                            disp = struct.unpack_from("<i", code,
                                                      disp_off)[0]
                        else:
                            j += 1
                            continue
                        store_offset = disp
                        store_at = j
                        break
                    if mod in (0, 1, 2):
                        break  # store of a DIFFERENT reg: stop
                j += 1
            events.append({
                "lea_offset": i - 7,
                "kind": "reference",
                "table_rva": "0x%08X" % target,
                "candidates": cands,
                "store_offset": store_offset,
                "store_kind": "mov-m64" if store_offset is not None
                              else "untraced",
                **({"store_at": store_at} if store_at is not None else {}),
                # legacy field retained for schema stability; equals the
                # LEA position and is NOT a this-offset. Consumers must
                # use store_offset (None = untraced).
                "offset": i - 7,
            })
        return {
            "scan": scan_mode,
            "function_extent": ["0x%08X" % extent[0],
                                "0x%08X" % extent[1]],
            "semantics": "reference+store-offset",
            "order": "ORDER-UNKNOWN",
            "references": events,
        }

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
        # ctor vftable REFERENCES (reference-only, ORDER-UNKNOWN):
        # no base order / emission order is derived from this field
        cvr = ctor_vftable_references(cls)
        if cvr is not None:
            cvr = {"ctor_rva": "0x%08X" % ctor_rva[cls], **cvr}
            entry["ctor_vftable_references"] = cvr
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
    scan_states = collections.Counter()
    for e in derived.values():
        cvr = e.get("ctor_vftable_references") or {}
        if cvr:
            scan_states[cvr.get("scan", "?")] += 1
    n_cso = sum(scan_states.values())
    n_refused = scan_states.get("unknown-scan-refused", 0)
    provs = collections.Counter()
    for e in derived.values():
        if "primary" in e:
            provs[e["primary"]["length_provenance"]] += 1
        for s in e.get("secondaries", {}).values():
            provs[s["length_provenance"]] += 1
    print(f"extract-mi-tables: classes={len(derived)} "
          f"primary={n_prim} secondary={n_sec} total={n_tables} "
          f"ctor_vftable_references={n_cso} "
          f"(scan states: {dict(scan_states)})")
    print(f"  slot stats: {dict(stat)}")
    print(f"  length provenance: {dict(provs)}")
    print(f"  manual interface_lengths: {len(iface_lengths)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
