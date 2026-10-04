#!/usr/bin/env python3
"""uia_order_verify.py -- R6: multi-vtable shape/slot checker.

WHAT THIS GATES (stage2 order-contract track, Lead rulings e18ca202
and 131ca2bb)
    For every class with a header in --include AND tables in pinned
    mi-tables.json (schema 3), compile an isolated probe TU that
    forces the class's vftable SET, split the object's relocation
    rows into per-base tables (??_R4 block anchoring), and verify
    EVERY table slot-by-slot against the pinned DLL bytes at the
    table's RVA.

    THIS STAGE IS A SHAPE/SLOT CHECKER. It does NOT compare or
    validate any base ORDER: the schema-3 ctor_vftable_references
    field is reference-only (ORDER-UNKNOWN) and is reported as
    evidence context, never used for a verdict. No order-compare
    verdict exists or is promised at this stage.

PER-CLASS REPORT (stdout + --json-out artifact)
    * table list with identity (primary / secondary:<base>), RVA,
      slot count, length provenance;
    * per-slot verdict with the FULL mangled symbol set at the DLL's
      slot address and the probe's symbol (sets stored untruncated
      in the artifact; stdout may elide for readability);
    * this-offsets: probe-observed W-adjustor encodings per table,
      marked "unknown" when none are decodable (an absent encoding
      is never reported as a measured offset);
    * ctor_vftable_references evidence context (reference-only,
      ORDER-UNKNOWN) when present.

REJECT ATTRIBUTION
    A REJECTED verdict names the ACTUAL probe mismatches (slot
    counts, mangled identity divergences, missing probe tables,
    manual-conflict). It does NOT attribute the rejection to any
    inheritance-order claim -- order diagnosis is out of scope for
    this gate at this stage.

MANDATORY COVERAGE (Lead ruling: all 17)
    The 13 pattern providers, ElementProvider, HWNDElementProvider,
    ScrollBar, CCVScrollBar. A mandatory class missing from the audit
    (no header, no mi entry, probe not buildable) is a FAIL of the
    gate itself, not a warning.

EVIDENCE GRADES (schema 3, stated not implied)
    Solid: table shapes/slots (DLL bytes), slot identity hits.
    The ctor_vftable_references field is reference-only evidence:
    no order (base/emission/declaration) is derived from it here.

USAGE
    python tools/dui-pipeline/uia_order_verify.py \
        --pinned pinned --include DirectUI/include \
        --workdir <dir> [--json-out r6.json] [--dll <dui70.dll>] \
        [--selftest]

    Exit codes: 0 PASS (all classes verified or UNKNOWN-reported,
    mandatory set covered); 1 FAIL; 2 structural error / selftest
    not executed where required.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys

MANDATORY = [
    "ExpandCollapseProvider", "GridItemProvider", "GridProvider",
    "InvokeProvider", "RangeValueProvider", "ScrollItemProvider",
    "ScrollProvider", "SelectionItemProvider", "SelectionProvider",
    "TableItemProvider", "TableProvider", "ToggleProvider",
    "ValueProvider", "ElementProvider", "HWNDElementProvider",
    "ScrollBar", "CCVScrollBar",
]


def _find_tool(name: str, hardcoded: str) -> str:
    if pathlib.Path(hardcoded).is_file():
        return hardcoded
    p = shutil.which(name)
    if p:
        return p
    raise SystemExit(f"uia_order_verify: {name} not found (neither "
                     f"{hardcoded} nor PATH); run under msvc-dev-cmd")


CL = _find_tool("cl.exe",
                r"C:\Program Files\Microsoft Visual Studio\2022"
                r"\Community\VC\Tools\MSVC\14.44.35207"
                r"\bin\Hostx64\x64\cl.exe")
DUMPBIN = _find_tool("dumpbin.exe",
                     r"C:\Program Files\Microsoft Visual Studio\2022"
                     r"\Community\VC\Tools\MSVC\14.44.35207"
                     r"\bin\Hostx64\x64\dumpbin.exe")


def _sdk_inc_dirs() -> list:
    incs = []
    msvc_local = (r"C:\Program Files\Microsoft Visual Studio\2022"
                  r"\Community\VC\Tools\MSVC\14.44.35207\include")
    if pathlib.Path(msvc_local).is_dir():
        incs.append(msvc_local)
    roots = (r"C:\Program Files (x86)\Windows Kits\10\Include",
             r"C:\Program Files\Windows Kits\10\Include")
    for root_s in roots:
        root = pathlib.Path(root_s)
        if not root.is_dir():
            continue
        for ver in sorted((x.name for x in root.iterdir() if x.is_dir()),
                          reverse=True):
            for sub in ("ucrt", "um", "shared"):
                d = root / ver / sub
                if d.is_dir():
                    incs.append(str(d))
    return incs


INC = _sdk_inc_dirs()


def _resolve_dll(pinned_dir: pathlib.Path) -> pathlib.Path:
    import hashlib
    man = json.loads((pinned_dir / "manifest.json").read_text(
        encoding="utf-8"))
    want = man["dll"]["sha256"].lower()
    c = (pinned_dir / ".." / ".local" / "build" / "ci-probe" /
         "annot-trap" / "dll_alone" / "dui70.dll").resolve()
    if not c.is_file():
        raise SystemExit(
            f"uia_order_verify: pinned DLL missing ({c}); pass --dll")
    got = hashlib.sha256(c.read_bytes()).hexdigest()
    if got.lower() != want:
        raise SystemExit(f"uia_order_verify: DLL sha mismatch for {c}")
    return c


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


def _thunk_equiv(s_obj: str, s_dll: str) -> bool:
    """Same class+member with probe/DLL thunk-skin differences.

    Covers: (a) pinned-name truncation at the adjustor zone;
    (b) U<->M this-adjustor thunk skins (subobject offset differs
    between real and modeled layout); (c) differing '@W' adjustor
    encodings for the same member. NEVER used to pass a slot -- only
    to mark it THUNK-UNKNOWN (identity not provable at mangled
    level, but same member provable)."""
    m_obj = re.match(r"\?(\w+)@(\w+)@DirectUI@@", s_obj)
    m_dll = re.match(r"\?(\w+)@(\w+)@DirectUI@@", s_dll)
    if not (m_obj and m_dll):
        return False
    if m_obj.group(1) != m_dll.group(1) or m_obj.group(2) != m_dll.group(2):
        return False
    m2t = re.match(r"\?\w+@\w+@DirectUI@@W", s_obj)
    m3t = re.match(r"\?\w+@\w+@DirectUI@@W", s_dll)
    if m2t and m3t:
        return True
    shorter = s_obj if len(s_obj) <= len(s_dll) else s_dll
    longer = s_dll if shorter is s_obj else s_obj
    if longer.startswith(shorter):
        return bool(re.match(r"^(\?(\w+)@(\w+)@DirectUI@@)?"
                             r"[A-Z]*@?[A-Z]*$", shorter))
    m2 = re.match(r"\?(\w+)@(\w+)@DirectUI@@([A-Z])(.*)$", s_obj)
    m3 = re.match(r"\?(\w+)@(\w+)@DirectUI@@([A-Z])(.*)$", s_dll)
    if m2 and m3 and m2.group(4) == m3.group(4) and \
            len(m2.group(3)) == len(m3.group(3)) == 1:
        if {m2.group(3), m3.group(3)} <= {"E", "M", "U", "V", "W",
                                           "A", "B", "C", "D", "F", "G"}:
            if {m2.group(3), m3.group(3)} == {"U", "M"}:
                return True
    return False


def _selftest(pinned: pathlib.Path, inc: pathlib.Path,
              workdir: pathlib.Path, dll: pathlib.Path) -> int:
    """Paired negative controls -- one per review BLOCK item
    (Lead review message). Each control mutates an ISOLATED COPY of
    the pinned inputs (never the tree under test) and asserts the
    gate/tool FAILS or REFUSES as required; the unmutated pair must
    behave normally. A control that cannot fail is reported as an
    error (never vacuous).

    T1 (F1 scan bounds): every ctor_vftable_references entry that
    claims scan=pdata-bounded must keep ALL reference offsets inside
    the .pdata function extent it reports, and that extent must be
    the actual .pdata entry containing the ctor RVA. A fixed-window
    scan (the BLOCKed behavior) would produce references past the
    extent -- the shipped scan must not.

    T2 (F1 alias lists): an RVA carrying TWO alias vftable symbols
    (ICF) must record BOTH candidates -- drop-last-wins must not
    occur. Verified structurally on the pinned artifact.

    T3 (F3/F4 no order claims): the pinned artifact carries
    ORDER-UNKNOWN semantics and no order-compare verdict field
    exists in the gate.

    T4 (offsets honesty): every table row this_offsets is either a
    non-empty list of decodings or the string unknown -- never an
    empty list masquerading as measured.

    T5 (full sets): every fail-slot entry carries the FULL
    dll_symbols list (len == the RVA symbol-set size), untruncated.

    T6 (manual-conflict refusal): tampering the manual RefcountBase
    length to deny a visible bound (2 to 1) must make the extractor
    emit manual-conflict (not truncation), and R6 must REJECT the
    affected class.
    """
    import copy
    import shutil
    import subprocess
    repo = pathlib.Path(__file__).resolve().parents[2]
    here = repo / "tools" / "dui-pipeline"
    root = workdir / "selftest"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ok = True
    mi = json.loads((pinned / "mi-tables.json").read_text(
        encoding="utf-8"))

    # ---- T1: .pdata-bounding of the reference scan ----
    import struct as _s
    blob = dll.read_bytes()
    e = _s.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    nsec = _s.unpack_from("<H", blob, coff + 2)[0]
    optsz = _s.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    pdata_extents = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        name = blob[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
        if name == ".pdata":
            _, vaddr, _, raddr = _s.unpack_from("<IIII", blob, o + 8)
            vsize = _s.unpack_from("<I", blob, o + 8)[0]
            for j in range(vsize // 12):
                b, en, _u = _s.unpack_from("<III", blob, raddr + j * 12)
                if b or en:
                    pdata_extents.append((b, en))
    bad = 0
    checked = {"pdata-bounded": 0, "symbol-bounded-safe": 0}
    for cls, e_ in mi["derived"].items():
        cvr = e_.get("ctor_vftable_references")
        if not cvr:
            continue
        mode = cvr.get("scan")
        if mode not in checked:
            continue
        b, en = (int(cvr["function_extent"][0], 16),
                 int(cvr["function_extent"][1], 16))
        ctor = int(cvr["ctor_rva"], 16)
        refs = cvr.get("references", [])
        checked[mode] += 1
        # every reference offset must land inside the extent
        if any(not (b <= ctor + r["offset"] < en) for r in refs):
            bad += 1
        if not (b <= ctor < en):
            bad += 1
        # pdata-bounded extents must BE the .pdata entry containing
        # the ctor; symbol-bounded extents must NOT exceed the next
        # symbol (conservatively inside [ctor, ctor+0x200])
        if mode == "pdata-bounded":
            if not any(bb <= ctor < ee and (bb, ee) == (b, en)
                       for bb, ee in pdata_extents):
                bad += 1
        else:
            if en - b > 0x200:
                bad += 1
    print(f"selftest T1: {checked['pdata-bounded']} pdata-bounded + "
          f"{checked['symbol-bounded-safe']} symbol-bounded-safe, "
          f"{bad} violations")
    if bad or not (checked["pdata-bounded"] or
                   checked["symbol-bounded-safe"]):
        print("selftest T1: FAIL")
        ok = False
    else:
        print("selftest T1: PASS (all references inside reported "
              "extents; pdata extents = actual .pdata entries; "
              "symbol-bounded extents conservative <= 0x200)")

    # ---- T2: REAL paired control (deletion + alias) ----
    # Pair 1 (deletion): re-derive the references with the extractor
    # on the same committed inputs and compare the FULL reference set
    # against the committed artifact -- a deleted/extra reference in
    # the artifact must diverge. This is a true-value cross-check,
    # not a len>1 structural observation.
    # Pair 2 (alias): mutate a copy of the artifact by replacing one
    # reference's candidate list with a SINGLE alias (dropping the
    # others); the re-derivation comparison must CATCH the dropped
    # alias.
    mutroot = root / "t2"
    mutroot.mkdir(parents=True, exist_ok=True)
    rebuilt = mutroot / "mi-tables.json"
    rx = subprocess.run(
        [sys.executable, str(here / "extract-mi-tables.py"),
         "--dll", str(dll), "--symbols", str(pinned / "symbols.json"),
         "--lengths", str(pinned / "mi-interface-lengths.json"),
         "--out", str(rebuilt)],
        capture_output=True, text=True)
    if rx.returncode != 0:
        print("selftest T2: FAIL (re-derivation failed)")
        ok = False
    else:
        re_der = json.loads(rebuilt.read_text(encoding="utf-8"))["derived"]
        com = mi["derived"]
        ref_diff = []
        for c in sorted(set(re_der) | set(com)):
            a = (re_der.get(c, {}).get("ctor_vftable_references")
                 or {}).get("references")
            b = (com.get(c, {}).get("ctor_vftable_references")
                 or {}).get("references")
            if a != b:
                ref_diff.append(c)
        if ref_diff:
            print(f"selftest T2: FAIL (committed references diverge "
                  f"from re-derivation: {ref_diff[:4]})")
            ok = False
        else:
            print(f"selftest T2: PASS pair 1 (committed reference set "
                  f"= re-derivation, {sum(1 for e in com.values() if e.get('ctor_vftable_references'))} classes)")
        # negative control: DELETE one reference in a copy; the
        # comparison must flag the class
        if not ref_diff:
            import copy as _cp
            mutmi = _cp.deepcopy(com)
            tgt = None
            for c, e in mutmi.items():
                cvr = e.get("ctor_vftable_references") or {}
                if len(cvr.get("references", [])) >= 2:
                    tgt = c
                    break
            if tgt is None:
                # R2: an undecidable control is NOT a pass -- the
                # selftest exits non-zero so a vacuous run cannot go
                # green
                print("selftest T2: INCONCLUSIVE (no class with >=2 "
                      "references to delete from) -- non-rc0")
                ok = False
            else:
                mutmi[tgt]["ctor_vftable_references"]["references"].pop(0)
                # compare again
                diff2 = [c for c in sorted(set(mutmi) | set(re_der))
                         if ((mutmi.get(c, {}).get("ctor_vftable_references")
                              or {}).get("references")
                             != (re_der.get(c, {})
                                 .get("ctor_vftable_references")
                                 or {}).get("references"))]
                if diff2 == [tgt]:
                    print(f"selftest T2: PASS pair 2 (deleted "
                          f"reference caught: {tgt})")
                else:
                    print(f"selftest T2: FAIL pair 2 (deletion NOT "
                          f"caught: diff={diff2[:4]})")
                    ok = False

    # ---- T3: verdict-independence from cvr order fields ----
    # REAL mutation control (source-grep is not evidence): mutate a
    # copy of the pinned artifact so one class's
    # ctor_vftable_references claims a fake order (order=RB-FIRST,
    # semantics=declaration-order) and assert:
    #   (a) the gate's VERDICT for that class is UNCHANGED (verdicts
    #       are computed from probe/table evidence, never from cvr);
    #   (b) the gate's own report rows contain NO order verdict field
    #       (the context echo carries ORDER-UNKNOWN as given by the
    #       extractor; a mutated order claim never becomes a verdict).
    # pick a class that (a) has pdata-bounded cvr evidence and
    # (b) the gate actually audits (header + >=2 tables): probe once
    # on the pdata-bounded set and keep those with a report row
    pb = [c for c, e_ in mi["derived"].items()
          if (e_.get("ctor_vftable_references") or {})
          .get("scan") == "pdata-bounded"]
    probe = root / "t3-pick"
    probe.mkdir(parents=True, exist_ok=True)
    pr = subprocess.run(
        [sys.executable, str(here / "uia_order_verify.py"),
         "--pinned", str(pinned), "--include", str(inc),
         "--workdir", str(probe), "--dll", str(dll),
         "--classes", ",".join(pb), "--json-out", str(probe / "p.json")],
        capture_output=True, text=True)
    t3cands = []
    if (probe / "p.json").is_file():
        pdoc = json.loads((probe / "p.json").read_text(
            encoding="utf-8"))
        t3cands = [c for c in pdoc.get("audited", {})
                   if pdoc["audited"][c].get("verdict")]
    if not t3cands:
        print("selftest T3: INCONCLUSIVE (no audited pdata-bounded "
              "class) -- non-rc0")
        ok = False
    else:
        t3cls = t3cands[0]
        t3root = root / "t3"
        (t3root / "pinned").mkdir(parents=True, exist_ok=True)
        import shutil as _sh
        for f_ in pinned.iterdir():
            if f_.is_file():
                _sh.copy(f_, t3root / "pinned" / f_.name)
        mutmi = json.loads((t3root / "pinned" / "mi-tables.json")
                           .read_text(encoding="utf-8"))
        cvr = mutmi["derived"][t3cls]["ctor_vftable_references"]
        cvr["order"] = "RB-FIRST"
        cvr["semantics"] = "declaration-order"
        (t3root / "pinned" / "mi-tables.json").write_text(
            json.dumps(mutmi), encoding="utf-8")

        def _gate(pinned_dir, workname, outname):
            art = t3root / outname
            r_ = subprocess.run(
                [sys.executable, str(here / "uia_order_verify.py"),
                 "--pinned", str(pinned_dir), "--include", str(inc),
                 "--workdir", str(t3root / workname),
                 "--dll", str(dll), "--classes", t3cls,
                 "--json-out", str(art)],
                capture_output=True, text=True)
            doc_ = (json.loads(art.read_text(encoding="utf-8"))
                    if art.is_file() else None)
            return r_.returncode, (doc_ or {}).get("audited", {}) \
                .get(t3cls)

        rc0, rep0 = _gate(pinned, "w-orig", "orig.json")
        rc1, rep1 = _gate(t3root / "pinned", "w-mut", "mut.json")
        if rep0 is None or rep1 is None:
            print("selftest T3: FAIL (gate did not audit the class)")
            ok = False
        elif rep0.get("verdict") != rep1.get("verdict"):
            print(f"selftest T3: FAIL (fake order claim changed the "
                  f"verdict: {rep0.get('verdict')} -> "
                  f"{rep1.get('verdict')})")
            ok = False
        else:
            # verdict rows must carry no order field of their own
            order_fields = []
            for tbl, tr in (rep1.get("tables") or {}).items():
                if "order" in tr:
                    order_fields.append(tbl)
            if order_fields:
                print(f"selftest T3: FAIL (verdict rows carry order "
                      f"fields: {order_fields})")
                ok = False
            else:
                print(f"selftest T3: PASS (fake order claim in cvr "
                      f"did not change {t3cls}'s verdict "
                      f"[{rep0.get('verdict')}] and no order verdict "
                      f"field exists in report rows)")

    # ---- T4/T5: run the gate on ONE class and inspect the artifact --
    cls = "InvokeProvider"
    art = root / "r6-one.json"
    r = subprocess.run(
        [sys.executable, str(here / "uia_order_verify.py"),
         "--pinned", str(pinned), "--include", str(inc),
         "--workdir", str(root / "w-one"), "--dll", str(dll),
         "--classes", cls, "--json-out", str(art)],
        capture_output=True, text=True)
    if r.returncode not in (0, 1) or not art.is_file():
        print(f"selftest T4/T5: FAIL (gate rc={r.returncode})")
        ok = False
    else:
        doc = json.loads(art.read_text(encoding="utf-8"))
        rep = doc["audited"].get(cls)
        if rep is None:
            print("selftest T4/T5: FAIL (class not audited)")
            ok = False
        else:
            bad4 = [t for t, tr in rep["tables"].items()
                    if tr.get("this_offsets") == []]
            if bad4:
                print(f"selftest T4: FAIL (empty this_offsets on "
                      f"{bad4})")
                ok = False
            else:
                print("selftest T4: PASS (this_offsets never an empty "
                      "list; unknown when undecodable)")
            symd = json.loads((pinned / "symbols.json").read_text(
                encoding="utf-8"))["symbols"]
            full = {}
            for s in symd:
                rv = s.get("rva")
                if rv:
                    full.setdefault(int(rv, 16), []).append(
                        s["mangled"])
            bad5 = 0
            for t, tr in rep["tables"].items():
                for fs in tr.get("fail_slots", []):
                    if "dll_symbols" not in fs:
                        continue
                    # recompute the true set size at the slot
                    rva = int(tr["rva"], 16)
                    slot = fs["slot"]
                    off = None
                    for va, vs, ra, rs in [(x[0], x[1], x[2], x[3])
                                           for x in _pe_secs(blob)]:
                        if va <= rva < va + vs:
                            off = ra + (rva - va)
                            break
                    if off is None or slot is None:
                        continue
                    va = _s.unpack_from("<Q", blob, off + 8 * slot)[0]
                    true_set = full.get(va - _pe_base(blob), [])
                    if len(fs["dll_symbols"]) != len(true_set):
                        bad5 += 1
            if bad5:
                print(f"selftest T5: FAIL ({bad5} truncated symbol "
                      f"sets in fail slots)")
                ok = False
            else:
                print("selftest T5: PASS (fail slots carry full DLL "
                      "symbol sets)")

    # ---- T6: manual-conflict refusal (deny direction) ----
    mut = root / "deny"
    (mut / "pinned").mkdir(parents=True)
    for f in pinned.iterdir():
        if f.is_file():
            shutil.copy(f, mut / "pinned" / f.name)
    ld = json.loads((mut / "pinned" / "mi-interface-lengths.json")
                    .read_text(encoding="utf-8"))
    ld["interface_lengths"]["RefcountBase"] = 1
    (mut / "pinned" / "mi-interface-lengths.json").write_text(
        json.dumps(ld), encoding="utf-8")
    rx = subprocess.run(
        [sys.executable, str(here / "extract-mi-tables.py"),
         "--dll", str(dll),
         "--symbols", str(mut / "pinned" / "symbols.json"),
         "--lengths", str(mut / "pinned" / "mi-interface-lengths.json"),
         "--out", str(mut / "pinned" / "mi-tables.json")],
        capture_output=True, text=True)
    if rx.returncode != 0:
        print("selftest T6: FAIL (extractor rejected the tamper input "
              "outright)")
        ok = False
    else:
        mdoc = json.loads((mut / "pinned" / "mi-tables.json")
                          .read_text(encoding="utf-8"))["derived"]
        conf = [c for c, e_ in mdoc.items()
                for k, t_ in (e_.get("secondaries") or {}).items()
                if t_.get("length_provenance") == "manual-conflict"]
        trunc = [c for c, e_ in mdoc.items()
                 for k, t_ in (e_.get("secondaries") or {}).items()
                 if t_.get("length_provenance") == "manual-conflict"
                 and len(t_["slots"]) < len(
                     (mi["derived"].get(c, {})
                      .get("secondaries") or {}).get(k, {})
                     .get("slots", []))]
        if not conf:
            print("selftest T6: FAIL (deny not refused)")
            ok = False
        elif trunc:
            print("selftest T6: FAIL (silent truncation)")
            ok = False
        else:
            r6 = subprocess.run(
                [sys.executable,
                 str(here / "uia_order_verify.py"),
                 "--pinned", str(mut / "pinned"),
                 "--include", str(inc),
                 "--workdir", str(mut / "w"),
                 "--dll", str(dll), "--classes",
                 "InvokeProvider,ElementProvider"],
                capture_output=True, text=True)
            inv_ok = "manual-conflict" in (r6.stdout + r6.stderr)
            if r6.returncode == 1 and inv_ok:
                print("selftest T6: PASS (deny -> manual-conflict, "
                      "visible slots kept, R6 REJECTs)")
            else:
                print("selftest T6: FAIL (R6 did not reject with "
                      "manual-conflict attribution)")
                ok = False

    print(f"uia_order_verify selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _pe_secs(blob):
    import struct as _s
    e = _s.unpack_from("<I", blob, 0x3C)[0]
    coff = e + 4
    nsec = _s.unpack_from("<H", blob, coff + 2)[0]
    optsz = _s.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    out = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vsize, vaddr, rsize, raddr = _s.unpack_from("<IIII", blob, o + 8)
        out.append((vaddr, vsize, raddr, rsize))
    return out


def _pe_base(blob):
    import struct as _s
    e = _s.unpack_from("<I", blob, 0x3C)[0]
    return _s.unpack_from("<Q", blob, e + 4 + 20 + 24)[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinned", required=True)
    ap.add_argument("--include", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="paired negative controls per the review "
                         "BLOCK items (scan bounds, alias lists, no "
                         "order claims, offsets honesty, full symbol "
                         "sets, manual-conflict refusal)")
    ap.add_argument("--classes", default=None,
                    help="comma list; default: all classes with both "
                         "header and mi-tables entry")
    args = ap.parse_args(argv)

    pinned = pathlib.Path(args.pinned)
    inc = pathlib.Path(args.include)
    work = pathlib.Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)

    if args.selftest:
        dll = pathlib.Path(args.dll) if args.dll else _resolve_dll(pinned)
        return _selftest(pinned, inc, work, dll)

    mi_path = pinned / "mi-tables.json"
    if not mi_path.is_file():
        print("uia_order_verify: ERROR pinned/mi-tables.json missing "
              "(run extract-mi-tables.py first)", file=sys.stderr)
        return 2
    mi_doc = json.loads(mi_path.read_text(encoding="utf-8"))
    if mi_doc.get("schema") != 3:
        print(f"uia_order_verify: ERROR mi-tables schema "
              f"{mi_doc.get('schema')} != 3 (the shape/slot checker "
              "consumes schema 3: ctor_vftable_references + identity "
              "fields + fail-closed manual conflicts)", file=sys.stderr)
        return 2
    derived = mi_doc["derived"]

    dll_path = pathlib.Path(args.dll) if args.dll else _resolve_dll(pinned)
    blob = dll_path.read_bytes()
    image_base, secs = parse_pe(blob)

    def rva2off(rva):
        for va, vs, ra, rs in secs:
            if va <= rva < va + vs:
                return ra + (rva - va)
        return None

    symd = json.loads((pinned / "symbols.json").read_text(
        encoding="utf-8"))["symbols"]
    rva_map: dict[int, list[str]] = {}
    for s in symd:
        r = s.get("rva")
        if r:
            rva_map.setdefault(int(r, 16), []).append(s["mangled"])

    def dll_slot_set(rva: int, k: int):
        off = rva2off(rva)
        if off is None:
            return None
        va = struct.unpack_from("<Q", blob, off + 8 * k)[0]
        return rva_map.get(va - image_base)

    only = {c.strip() for c in args.classes.split(",")} if args.classes \
        else None

    audited = {}          # cls -> report dict
    failed_classes = []
    mandatory_missing = []

    for cls in sorted(derived):
        if only and cls not in only:
            continue
        entry = derived[cls]
        tables_expected = dict(entry.get("secondaries") or {})
        if entry.get("primary"):
            tables_expected = {"PRIMARY": entry["primary"],
                               **tables_expected}
        if len(tables_expected) < 2 and cls not in MANDATORY:
            continue  # single-table classes: schema-1 track covers them
        hp = inc / f"{cls}.h"
        if not hp.is_file():
            if cls in MANDATORY:
                mandatory_missing.append(cls)
            continue
        txt = hp.read_text(encoding="utf-8")

        report = {"class": cls, "tables": {},
                  "verdict": None, "notes": []}

        # fail-closed: manual-conflict tables reject the class outright
        conflict_tables = [
            k for k, t in tables_expected.items()
            if t.get("length_provenance") == "manual-conflict"]
        if conflict_tables:
            report["verdict"] = "REJECTED"
            report["notes"].append(
                "manual-conflict tables: " + ",".join(conflict_tables) +
                " -- manual length denies in-binary visible slots")
            failed_classes.append(cls)
            audited[cls] = report
            continue

        # ---- build probe TU ----
        # Attempt order MATTERS for table identity:
        #   1. dtor-only TU -- emits the CLASS's own vftable set
        #      (no subclass): the tables carry the class name and
        #      are directly comparable to the DLL tables.
        #   2. sub-force TU -- concrete __Probe subclass overriding
        #      every placeholder + a global instance: guarantees
        #      every table is emitted, but the tables carry the
        #      __Probe name; the subclass adds NO slots (its dtor
        #      overrides the base vdtor slot), so slot-for-slot
        #      comparison against the class's DLL tables remains
        #      valid (A1 semantics).
        cpp_d = work / f"r6d_{cls}.cpp"
        cpp_d.write_text(
            f'#include "{cls}.h"\nnamespace DirectUI {{\n'
            f"    {cls}::~{cls}(void) {{}}\n}}\n", encoding="utf-8")
        obj = work / f"r6_{cls}.obj"
        r = subprocess.run(
            [CL, "/nologo", "/std:c++20", "/EHsc", "/Od",
             "/Zc:wchar_t-", "/c",
             *sum([["/I", p] for p in INC], []),
             "/I", str(inc), f"/Fo{obj}", str(cpp_d)],
            capture_output=True, text=True)
        used_tu = "dtor"
        if r.returncode != 0:
            phs = [(int(m.group(3)), m.group(1)) for m in re.finditer(
                r"virtual void (__DuiAbiSlot_(\w+)_(\d+))\(void\) = 0;",
                txt)]
            cpp = work / f"r6_{cls}.cpp"
            lines = [f'#include "{cls}.h"', "namespace DirectUI {"]
            lines.append(f"    struct __Probe{cls} : {cls} {{")
            for _, pn in phs:
                lines.append(f"        void {pn}(void);")
            lines.append(f"        ~__Probe{cls}(void);")
            lines.append("    };")
            for _, pn in phs:
                lines.append(f"    void __Probe{cls}::{pn}(void) {{}}")
            lines.append(f"    __Probe{cls}::~__Probe{cls}(void) {{}}")
            lines.append(f"    __Probe{cls} __g_probe_{cls};")
            lines.append("}")
            cpp.write_text("\n".join(lines), encoding="utf-8")
            r = subprocess.run(
                [CL, "/nologo", "/std:c++20", "/EHsc", "/Od",
                 "/Zc:wchar_t-", "/c",
                 *sum([["/I", p] for p in INC], []),
                 "/I", str(inc), f"/Fo{obj}", str(cpp)],
                capture_output=True, text=True)
            used_tu = "sub"
            if r.returncode != 0:
                err = [x for x in (r.stderr or r.stdout).splitlines()
                       if "error" in x]
                if cls in MANDATORY:
                    report["verdict"] = "REJECTED"
                    report["notes"].append(
                        "probe compile failed: " +
                        (err[0][:100] if err else "?"))
                    failed_classes.append(cls)
                    audited[cls] = report
                    continue
                continue
        report["probe_tu"] = used_tu

        # ---- split vftables by ??_R4 block ----
        def split_tables(obj_path):
            r2 = subprocess.run(
                [DUMPBIN, "/nologo", "/relocations", str(obj_path)],
                capture_output=True, text=True)
            entries = []
            block = -1
            for L in r2.stdout.splitlines():
                m_sec = re.match(r"RELOCATIONS #([0-9A-Fa-f]+)", L)
                if m_sec:
                    block += 1
                    continue
                if "ADDR64" not in L:
                    continue
                m = re.match(
                    r"\s*([0-9A-F]+)\s+ADDR64\s+\S+\s+\S+\s+"
                    r"(?:(\w+)\s+)?(.*)$", L)
                if not m:
                    continue
                off = int(m.group(1), 16)
                sym = (m.group(3) or "").strip()
                cut = sym.find(" (")
                if cut > 0:
                    sym = sym[:cut].strip()
                if sym.startswith("?") or "_purecall" in sym:
                    entries.append((block, off, sym))
            tables: dict[str, list] = {}
            offs_map: dict[str, list] = {}
            by_sec: dict[int, list] = {}
            for s, off, sym in entries:
                by_sec.setdefault(s, []).append((off, sym))
            for s, rows in by_sec.items():
                rows.sort()
                runs: list = []
                cur = [rows[0]]
                for prev, nxt in zip(rows, rows[1:]):
                    if nxt[0] - prev[0] == 8:
                        cur.append(nxt)
                    else:
                        runs.append(cur)
                        cur = [nxt]
                runs.append(cur)
                for rn in runs:
                    if not rn or not rn[0][1].startswith("??_R4"):
                        continue
                    m = re.match(
                        r"\?\?_R4(?:__Probe)?\w+@DirectUI@@6B(.*)@",
                        rn[0][1])
                    if m is None:
                        continue
                    key = re.sub(r"@\d+@$", "@", m.group(1)).rstrip("@")
                    tables[key] = [sym for _, sym in rn[1:]]
                    dec = sorted({int(mm.group(1)) for sym in
                                  tables[key]
                                  for mm in [re.match(
                                      r"\?\S+@\w+@DirectUI@@W(\d+)",
                                      sym)] if mm})
                    # absent W-encodings are UNKNOWN, never an empty
                    # list presented as a measured result
                    offs_map[key] = dec if dec else "unknown"

            return tables, offs_map

        probe_tables, this_offsets = split_tables(obj)

        # retry with sub-force TU when an expected table is absent:
        # the dtor-only TU emits only tables the header's shape
        # produces; a missing table is a finding ONLY after the
        # guaranteed-emission sub-force TU also fails to produce it.
        expected_keys = {("" if k == "PRIMARY" else k).rstrip("@")
                         for k in tables_expected}
        if used_tu == "dtor" and not expected_keys <= set(probe_tables):
            phs = [(int(m.group(3)), m.group(1)) for m in re.finditer(
                r"virtual void (__DuiAbiSlot_(\w+)_(\d+))\(void\) = 0;",
                txt)]
            cpp = work / f"r6_{cls}.cpp"
            lines = [f'#include "{cls}.h"', "namespace DirectUI {"]
            lines.append(f"    struct __Probe{cls} : {cls} {{")
            for _, pn in phs:
                lines.append(f"        void {pn}(void);")
            lines.append(f"        ~__Probe{cls}(void);")
            lines.append("    };")
            for _, pn in phs:
                lines.append(f"    void __Probe{cls}::{pn}(void) {{}}")
            lines.append(f"    __Probe{cls}::~__Probe{cls}(void) {{}}")
            lines.append(f"    __Probe{cls} __g_probe_{cls};")
            lines.append("}")
            cpp.write_text("\n".join(lines), encoding="utf-8")
            obj2 = work / f"r6s_{cls}.obj"
            rs = subprocess.run(
                [CL, "/nologo", "/std:c++20", "/EHsc", "/Od",
                 "/Zc:wchar_t-", "/c",
                 *sum([["/I", p] for p in INC], []),
                 "/I", str(inc), f"/Fo{obj2}", str(cpp)],
                capture_output=True, text=True)
            if rs.returncode == 0:
                sub_tables, sub_offs = split_tables(obj2)
                # __Probe tables are keyed by probe name but carry
                # the same base suffixes; merge missing ones in
                for k, v in sub_tables.items():
                    if k not in probe_tables:
                        probe_tables[k] = v
                        this_offsets.setdefault(k, sub_offs.get(k, []))
                report["probe_tu"] = "dtor+sub"

        # ---- per-table slot verification vs DLL bytes ----
        any_fail = False
        for tname, tinfo in tables_expected.items():
            base_key = "" if tname == "PRIMARY" else tname
            got = probe_tables.get(base_key) or \
                probe_tables.get(base_key.rstrip("@")) or \
                probe_tables.get(base_key + "@")
            trow = {"identity": tinfo.get("identity", tname),
                    "rva": tinfo["rva"],
                    "length_provenance": tinfo.get("length_provenance"),
                    "dll_slots": len(tinfo["slots"]),
                    "probe_slots": len(got) if got is not None else None,
                    "verified": 0, "fold_unknown": 0,
                    "thunk_unknown": 0, "unresolved": 0,
                    "fail_slots": [], "slot_detail": [],
                    "this_offsets": this_offsets.get(
                        base_key if base_key else "", "unknown")}
            rva = int(tinfo["rva"], 16)
            if got is None:
                trow["fail_slots"].append(
                    {"slot": None, "err": "probe table missing"})
            elif len(got) != len(tinfo["slots"]):
                trow["fail_slots"].append(
                    {"slot": None,
                     "err": f"slot count {len(got)} vs DLL "
                            f"{len(tinfo['slots'])}"})
            if got is not None:
                for i, want in enumerate(tinfo["slots"]):
                    exp_set = dll_slot_set(rva, i)
                    sym = got[i] if i < len(got) else ""
                    if exp_set is None:
                        trow["unresolved"] += 1
                        continue
                    if isinstance(want, str) and want.startswith("_E"):
                        if "??_E" in sym:
                            trow["verified"] += 1
                        else:
                            trow["fail_slots"].append(
                                {"slot": i, "err": f"expected vdtor, "
                                                   f"got {sym[:60]}"})
                        continue
                    trow["slot_detail"].append({
                        "slot": i, "probe_symbol": sym,
                        "dll_symbols": sorted(exp_set)})
                    if sym in exp_set:
                        if len(exp_set) > 1:
                            trow["fold_unknown"] += 1
                        else:
                            trow["verified"] += 1
                        continue
                    if any(_thunk_equiv(sym, x) for x in exp_set):
                        trow["thunk_unknown"] += 1
                        continue
                    names = want if isinstance(want, list) else [want]
                    if any(f"?{n}@{cls}@DirectUI@@" in sym or
                           f"??_E{n}@" in sym for n in names):
                        if len(exp_set) > 1:
                            trow["fold_unknown"] += 1
                        else:
                            trow["verified"] += 1
                        continue
                    trow["fail_slots"].append({
                        "slot": i,
                        "err": "mangled identity divergence",
                        "dll_symbols": sorted(exp_set),
                        # None when the probe table ran out of slots
                        # (never an empty string that looks like a
                        # symbol)
                        "probe_symbol": sym or None})
            if trow["fail_slots"]:
                any_fail = True
            report["tables"][tname] = trow

        # ---- ctor vftable references: evidence CONTEXT only ----
        # Reference-only (ORDER-UNKNOWN); NOT used for any verdict.
        # This gate does not compare base orders at this stage.
        cvr = entry.get("ctor_vftable_references")
        if cvr:
            report["ctor_vftable_references"] = {
                "scan": cvr.get("scan"),
                "order": cvr.get("order", "ORDER-UNKNOWN"),
                "semantics": "reference-only evidence context; no "
                             "order verdict is derived from it",
                "function_extent": cvr.get("function_extent"),
                "references": [
                    {"offset": r.get("offset"),
                     "bases": [c.get("base")
                               for c in r.get("candidates", [])]}
                    for r in cvr.get("references", [])],
            }
        else:
            report["ctor_vftable_references"] = None

        if any_fail:
            report["verdict"] = "REJECTED"
            kinds = sorted({fs.get("err", "?").split(":")[0].strip()
                            for tr in report["tables"].values()
                            for fs in tr["fail_slots"]})
            report["notes"].append(
                "rejected by probe mismatch: " + ", ".join(kinds))
            failed_classes.append(cls)
        else:
            total_unk = sum(t["fold_unknown"] + t["thunk_unknown"] +
                            t["unresolved"] for t in
                            report["tables"].values())
            report["verdict"] = "VERIFIED" if total_unk == 0 else \
                "VERIFIED-UNKNOWN-SLOTS"
        audited[cls] = report

    # mandatory coverage (full runs only; --classes restricts the
    # audited set deliberately for targeted re-checks and controls)
    if not only:
        for m in MANDATORY:
            if m not in audited:
                if m not in mandatory_missing:
                    mandatory_missing.append(m)

    n_ver = sum(1 for r in audited.values()
                if r["verdict"] and r["verdict"].startswith("VERIFIED"))
    n_unk = sum(1 for r in audited.values()
                if r["verdict"] == "VERIFIED-UNKNOWN-SLOTS")
    n_rej = sum(1 for r in audited.values() if r["verdict"] == "REJECTED")
    print(f"R6 uia-order-verify: audited {len(audited)} classes -- "
          f"{n_ver} VERIFIED, {n_unk} VERIFIED-UNKNOWN-SLOTS, "
          f"{n_rej} REJECTED")
    if mandatory_missing:
        print(f"  MANDATORY MISSING (fail-closed): {mandatory_missing}")
    for cls, r in sorted(audited.items()):
        tables_desc = " ".join(
            f"{t}[v={t_['verified']},u={t_['fold_unknown'] + t_['thunk_unknown'] + t_['unresolved']},"
            f"f={len(t_['fail_slots'])}]"
            for t, t_ in sorted(r["tables"].items()))
        print(f"  {r['verdict']:24} {cls}: {tables_desc}")
        for n in r["notes"]:
            print(f"     - {n}")
        for t, t_ in sorted(r["tables"].items()):
            for fs in t_["fail_slots"][:3]:
                if "dll_symbols" in fs:
                    dll_syms = ", ".join(fs["dll_symbols"][:2])
                    more = (f" (+{len(fs['dll_symbols'])-2} more)"
                            if len(fs["dll_symbols"]) > 2 else "")
                    psym = fs.get("probe_symbol")
                    psym = psym[:56] if psym else "(no probe symbol)"
                    print(f"     * {t} slot {fs['slot']}: "
                          f"{fs['err']} -- DLL [{dll_syms}{more}], "
                          f"object {psym}")
                else:
                    print(f"     * {t} slot {fs['slot']}: {fs['err']}")
    if args.json_out:
        # R4 coverage disclosure: REAL counts of what the ctor
        # reference evidence covers -- never a full-coverage claim.
        scan_states: dict[str, int] = {}
        n_ref = 0
        for e in derived.values():
            cvr = e.get("ctor_vftable_references") or {}
            if cvr:
                st_ = cvr.get("scan", "?")
                scan_states[st_] = scan_states.get(st_, 0) + 1
                n_ref += len(cvr.get("references", []))
        cov_claim = ("ctor reference evidence is PARTIAL: scan "
                     "states above; leaf classes without "
                     "multi-table inheritance are outside this "
                     "gate audit set; NOT a full-coverage claim")
        cov = {
            "classes_total": len(derived),
            "classes_with_ctor_reference_evidence":
                sum(scan_states.values()),
            "scan_states": scan_states,
            "references_total": n_ref,
            "coverage_claim": cov_claim,
        }
        pathlib.Path(args.json_out).write_text(
            json.dumps({"gate": "R6 multi-vtable shape/slot checker",
                        "mandatory": MANDATORY,
                        "mandatory_missing": mandatory_missing,
                        "coverage": cov,
                        "audited": audited,
                        "counts": {"verified": n_ver,
                                   "verified_unknown": n_unk,
                                   "rejected": n_rej},
                        "verdict": ("FAIL" if (failed_classes or
                                    mandatory_missing) else "PASS")},
                       indent=1, ensure_ascii=False),
            encoding="utf-8")
    if failed_classes or mandatory_missing:
        print("uia_order_verify: FAIL")
        return 1
    print("uia_order_verify: PASS "
          "(UNKNOWN slots reported, never passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
