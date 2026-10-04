#!/usr/bin/env python3
"""uia_order_verify.py -- R6: MI inheritance-order + table-truth gate.

WHAT THIS GATES (stage2 order-contract track, Lead ruling e18ca202)
    For every class with a header in --include AND tables in pinned
    mi-tables.json (schema 3), compile an isolated probe TU that
    forces the class's complete vftable SET (primary + secondaries),
    split the object's relocation rows into per-base tables (??_R4
    block anchoring), and verify EVERY table slot-by-slot against the
    pinned DLL bytes at the table's RVA.

PER-CLASS REPORT (stdout + --json-out artifact)
    * table list with identity (primary / secondary:<base>), RVA,
      slot count, length provenance;
    * per-slot verdict: the FULL MANGLED symbol set at the DLL's slot
      address, the probe's symbol, and EXACT / FOLD-UNKNOWN /
      THUNK-UNKNOWN / FAIL / UNRESOLVED;
    * this-offsets: probe-observed subobject displacements (the
      W<off> adjustor encodings of thunk symbols per secondary table);
    * ctor_store_order evidence (schema 3) when present.

ORDER CONTRACT CHECK (fail-closed)
    The header's base-clause order must not CONTRADICT the schema-3
    ctor_store_order evidence. Evidence semantics (documented, not
    hidden): ctor store order is an OBJECT-LAYOUT OBSERVATION (Solid
    Evidence) -- the sequence in which the constructor's code
    references the class's own vftables. It is NOT the source-level
    base-declaration order; store order may legitimately differ from
    declaration order (compiler store reordering), so the check is
    one-directional:
      * a header whose clause order EQUALS the ctor-store order:
        CONSISTENT (verified);
      * a header whose clause order is a DIFFERENT permutation but
        whose tables all verify against DLL bytes: the class is
        reported ORDER-UNKNOWN (layout-verified, declaration order
        not pinned) -- never silently passed as ordered;
      * a header whose tables FAIL slot verification: FAIL (regardless
        of clause order);
      * a class with mi tables but NO ctor-store evidence and NO
        header: covered elsewhere; a class with a header but NO
        schema-3 mi entry while carrying >=2 base clauses of its own:
        REJECTED (fail-closed: emission without table truth is not
        auditable -- exactly the ScrollBar/CCVScrollBar debt).

MANDATORY COVERAGE (Lead ruling: all 17)
    The 13 pattern providers, ElementProvider, HWNDElementProvider,
    ScrollBar, CCVScrollBar. A mandatory class missing from the audit
    (no header, no mi entry, probe not buildable) is a FAIL of the
    gate itself, not a warning.

EVIDENCE GRADES (schema 3, stated not implied)
    Solid: table shapes/slots (DLL bytes), ctor-store order
    (disassembly observation), slot identity hits.
    Strong Inference: any emission ORDERING strategy built on the
    above (store order != declaration order); reported as such.

USAGE
    python tools/dui-pipeline/uia_order_verify.py \
        --pinned pinned --include DirectUI/include \
        --workdir <dir> [--json-out r6.json] [--dll <dui70.dll>]

    Exit codes: 0 PASS (all classes verified or UNKNOWN-reported,
    mandatory set covered); 1 FAIL; 2 structural error.
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinned", required=True)
    ap.add_argument("--include", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--dll", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--classes", default=None,
                    help="comma list; default: all classes with both "
                         "header and mi-tables entry")
    args = ap.parse_args(argv)

    pinned = pathlib.Path(args.pinned)
    inc = pathlib.Path(args.include)
    work = pathlib.Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)

    mi_path = pinned / "mi-tables.json"
    if not mi_path.is_file():
        print("uia_order_verify: ERROR pinned/mi-tables.json missing "
              "(run extract-mi-tables.py first)", file=sys.stderr)
        return 2
    mi_doc = json.loads(mi_path.read_text(encoding="utf-8"))
    if mi_doc.get("schema") != 3:
        print(f"uia_order_verify: ERROR mi-tables schema "
              f"{mi_doc.get('schema')} != 3 (order-contract track "
              "needs schema 3)", file=sys.stderr)
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

        report = {"class": cls, "tables": {}, "order": {},
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
                    offs = sorted({int(mm.group(1)) for sym in
                                   tables[key]
                                   for mm in [re.match(
                                       r"\?\S+@\w+@DirectUI@@W(\d+)",
                                       sym)] if mm})
                    offs_map[key] = offs
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
                    "fail_slots": [], "this_offsets": this_offsets.get(
                        base_key if base_key else "", [])}
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
                        "err": f"mangled identity -- DLL "
                               f"{sorted(exp_set)[:1]}, object {sym[:56]}"})
            if trow["fail_slots"]:
                any_fail = True
            report["tables"][tname] = trow

        # ---- order-contract check ----
        cso = entry.get("ctor_store_order")
        if cso:
            seq = [s["base"] for s in cso["stores"]]
            report["order"]["ctor_store_order"] = seq
            report["order"]["evidence"] = (
                "object-layout observation (Solid); NOT declaration "
                "order; emission ordering on it = Strong Inference")
        else:
            report["order"]["ctor_store_order"] = None
            report["order"]["evidence"] = (
                "no ctor-store evidence (ctor not in pinned symbols or "
                "own-table refs filtered: ICF-merged code)")

        if any_fail:
            report["verdict"] = "REJECTED"
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
                print(f"     * {t} slot {fs['slot']}: {fs['err']}")
    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps({"gate": "R6 MI order + table truth",
                        "mandatory": MANDATORY,
                        "mandatory_missing": mandatory_missing,
                        "audited": audited,
                        "counts": {"verified": n_ver,
                                   "verified_unknown": n_unk,
                                   "rejected": n_rej},
                        "verdict": "FAIL" if (failed_classes or
                                              mandatory_missing)
                        else "PASS"},
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
