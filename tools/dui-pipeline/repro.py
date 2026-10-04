#!/usr/bin/env python3
"""repro.py -- CI stage-2: re-derive pinned/ from msdl and assert byte-equality.

WHAT THIS PROVES
    The committed `pinned/` is not hand-authored: from only the two URLs recorded
    in `pinned/manifest.json` (dll.source_url + pdb.source_url), this script
    re-downloads both artefacts, hard-asserts their sha256, re-runs the whole
    DLL+PDB -> pinned derivation in an isolated directory, and asserts the result
    is BYTE-IDENTICAL to what is committed:

        exports.json  4321 rows   (DLL export table)
        symbols.json 11983 rows   (4321 exports + 7662 PDB publics)

    No exemptions, no explanatory layer, no tolerated differences.

THE INPUTS ARE BOTH REPRODUCIBLE
    The PDB is served by msdl and is as reproducible as the DLL, but ONLY when
    addressed in canonical form: the symbol-server slot is `<GUID with the hyphens
    removed><age>`, concatenated with no separator --

        .../dui70.pdb/F1920C0ED3DE254FE969E8E8CC4435CE1/dui70.pdb

    A hyphenated or space-separated slot is not a legal path and the request fails,
    which is easy to misread as "the server does not have this file". So this gate
    does not trust the stored URL as a literal: it recomputes the DLL slot from the
    PE header and the PDB slot from the DLL's RSDS record, and requires both to
    agree with `manifest.*.source_url`. The URL is then a verified derivative of
    the downloaded bytes rather than a hand-typed string.

    With both inputs in hand, the whole pinned/ derivation is reproducible, so the
    assertions are full byte-equality. There is nothing to exempt and no
    "explanatory layer" of tolerated differences.

TWO ENVIRONMENT TRAPS THIS SCRIPT DEFENDS AGAINST
    1. `dumpbin /exports` CHANGES ITS OUTPUT when a matching same-named PDB sits
       next to the DLL: it appends " = <mangled>" annotations, and extract.py's
       parse_dumpbin_exports mis-attributes those lines (measured: 707 symbols get
       the wrong name for their ordinal). The committed exports.json was pinned
       from the un-annotated form, so a PDB beside the DLL makes the rebuild
       differ NECESSARILY. This script therefore keeps the DLL and the PDB in
       SEPARATE directories and asserts that no PDB sits beside the DLL.
    2. model.py's undname candidate list includes MSVC's `undname.exe`, which
       prints a different format and makes model.py fall back per symbol: rc=0
       with all 4321 symbols wrong (class=None everywhere). The `abi` job puts
       MSVC on PATH, so this is reachable. resolve_undname() proves the tool by
       its OUTPUT FORMAT and refuses anything that is not LLVM's.

EXIT CODES
    0  all assertions pass
    1  an assertion failed (stderr carries `GATE R*: FAIL expected=... actual=...`)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent

# msdl slot: for the DLL it is <TimeDateStamp:8 uppercase hex><SizeOfImage:lowercase
# hex> (winbindex's makeSymbolServerUrl literal -- mixed case is intentional); for
# the PDB it is <GUID without hyphens><age>, i.e. up to 33 chars. Accept both.
_MSDL_URL_RE = re.compile(
    r"^https://msdl\.microsoft\.com/download/symbols/"
    r"(?P<name>[^/]+)/(?P<slot>[0-9A-Fa-f]{8,40})/(?P=name)$")

# Fields of the rebuilt manifest that must equal the committed ones. These are all
# derived from the downloaded bytes, so they are legitimately reproducible.
# `file_version` is NOT here: for System32 paths Windows answers from servicing
# metadata instead of the file (see extract.py's file_version() and CI.md §7.6),
# so it is informational only.
DLL_HARD_FIELDS = ("sha256", "size", "arch")
PDB_HARD_FIELDS = ("sha256", "size", "guid", "age")

# Roots worth probing for LLVM tools. The official Windows LLVM distribution ships
# llvm-pdbutil but NOT llvm-undname, so mingw-style trees (including the one bundled
# inside a GHC install) are searched as well -- measured on the GitHub runner, where
# the only llvm-undname.exe on C: lives under C:\ghcup\ghc\<ver>\mingw\bin.
_LLVM_ROOTS = (
    r"C:\Program Files\LLVM\bin",
    r"C:\Program Files (x86)\LLVM\bin",
)


# ------------------------------------------------------------------- reporting
def fail(gate: str, expected: str, actual: str, extra: str = "") -> None:
    print(f"GATE {gate}: FAIL  expected={expected}  actual={actual}", file=sys.stderr)
    if extra:
        print(extra.rstrip(), file=sys.stderr)


def ok(gate: str, what: str) -> None:
    print(f"GATE {gate}: OK    {what}")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


# ------------------------------------------------------------- tool discovery
def _probe_undname(cand: str, probe: str) -> bool:
    """True if `cand` behaves like LLVM's undname (echoes the mangled name first).

    MSVC's undname.exe prints a banner and 'Undecoration of :- "..."' instead, and
    silently poisons model.py -- so this is a format test, not a name test.
    """
    try:
        r = subprocess.run([cand, probe], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
    return bool(lines) and lines[0].strip() == probe


def _vs_llvm_bins() -> list[str]:
    """VC\\Tools\\Llvm\\{x64,ARM64,}\\bin under any Visual Studio install we can locate."""
    out: list[str] = []
    bases: list[pathlib.Path] = []
    # env vars first: a VS developer prompt sets these, and they are authoritative
    for env in ("VSINSTALLDIR", "VCINSTALLDIR"):
        v = os.environ.get(env)
        if v:
            bases.append(pathlib.Path(v.rstrip("\\/")))
    vct = os.environ.get("VCToolsInstallDir")   # ...\VC\Tools\MSVC\<ver>\
    if vct:
        p = pathlib.Path(vct.rstrip("\\/"))
        for up in (p.parent.parent, p.parent, p):   # up to ...\VC
            bases.append(up)
    # then every install root on disk (Enterprise/Professional/Community/BuildTools,
    # any version -- the runner is VS 18, a dev box may be VS 2022)
    for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not pf:
            continue
        vs = pathlib.Path(pf) / "Microsoft Visual Studio"
        if not vs.is_dir():
            continue
        for ver in vs.iterdir():
            if not ver.is_dir():
                continue
            for ed in ver.iterdir():
                if ed.is_dir():
                    bases.append(ed)
    for b in bases:
        for rel in ("VC/Tools/Llvm/x64/bin", "VC/Tools/Llvm/ARM64/bin", "VC/Tools/Llvm/bin"):
            d = b / rel
            if d.is_dir():
                out.append(str(d))
    return list(dict.fromkeys(out))


def _mingw_style_bins() -> list[str]:
    """Incidental mingw/GHC trees that still carry llvm-undname.exe."""
    out: list[str] = []
    for base in (r"C:\ghcup", r"C:\tools", r"C:\mingw64", r"C:\msys64", r"C:\Strawberry",
                 r"C:\ProgramData\chocolatey", r"C:\Program Files\Git"):
        p = pathlib.Path(base)
        if not p.is_dir():
            continue
        try:
            for hit in list(p.glob("**/llvm-undname.exe"))[:4] + list(p.glob("**/llvm-pdbutil.exe"))[:4]:
                out.append(str(hit.parent))
        except OSError:
            continue
    return list(dict.fromkeys(out))


def resolve_undname(explicit: str | None) -> tuple[str | None, str]:
    """Find llvm-undname AND prove it is LLVM's, not MSVC's.

    Returns (path, note); path is None when no LLVM undname is available.
    """
    probe = "?Create@AcceleratorBehavior@@SAJPEAPEAUIDuiBehavior@@@Z"
    candidates: list[str] = []
    if explicit:
        candidates.append(str(pathlib.Path(explicit)))
    if os.environ.get("LLVM_UNDNAME"):
        candidates.append(os.environ["LLVM_UNDNAME"])
    for name in ("llvm-undname", "llvm-undname.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for root in _LLVM_ROOTS:
        candidates.append(str(pathlib.Path(root) / "llvm-undname.exe"))
    for d in _vs_llvm_bins() + _mingw_style_bins():
        candidates.append(str(pathlib.Path(d) / "llvm-undname.exe"))

    tried: list[str] = []
    for cand in candidates:
        if not cand or cand in tried:
            continue
        tried.append(cand)
        if not pathlib.Path(cand).is_file():
            continue
        if _probe_undname(cand, probe):
            return cand, f"verified LLVM-format (echoes the mangled name): {cand}"
    return None, (f"no LLVM-format llvm-undname found (probed: {', '.join(tried) or 'none'}). "
                  f"MSVC's undname.exe is NOT a substitute: it silently produces a wholly "
                  f"wrong symbols.json (rc=0, every symbol wrong).")


def resolve_pdbutil(explicit: str | None) -> tuple[str | None, str]:
    """Find llvm-pdbutil, which turns the PDB into the publics text."""
    candidates: list[str] = []
    if explicit:
        candidates.append(str(pathlib.Path(explicit)))
    if os.environ.get("LLVM_PDBUTIL"):
        candidates.append(os.environ["LLVM_PDBUTIL"])
    for name in ("llvm-pdbutil", "llvm-pdbutil.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for root in _LLVM_ROOTS:
        candidates.append(str(pathlib.Path(root) / "llvm-pdbutil.exe"))
    for d in _vs_llvm_bins() + _mingw_style_bins():
        candidates.append(str(pathlib.Path(d) / "llvm-pdbutil.exe"))

    tried: list[str] = []
    for cand in candidates:
        if not cand or cand in tried:
            continue
        tried.append(cand)
        if pathlib.Path(cand).is_file():
            return cand, f"llvm-pdbutil: {cand}"
    return None, (f"no llvm-pdbutil found (probed: {', '.join(tried) or 'none'}). "
                  f"It is required to read PDB publics.")


# ------------------------------------------------------------------ PE parsing
def pe_info(dll: pathlib.Path) -> dict:
    """Independently parse what repro needs: msdl slot inputs, and the RSDS record.

    Deliberately does NOT import extract.py: this is the verifier's own reading, so
    a bug in the pipeline's parser cannot silently satisfy the verifier.

    Returns dict(machine, timestamp, size_of_image, slot, pdb_guid, pdb_age, pdb_name).
    """
    data = dll.read_bytes()
    info: dict = {"slot": None, "pdb_guid": None, "pdb_age": None, "pdb_name": None}
    if len(data) < 0x40 or data[:2] != b"MZ":
        return info
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\0\0":
        return info
    coff = e + 4
    machine, nsec = struct.unpack_from("<HH", data, coff)
    ts = struct.unpack_from("<I", data, coff + 4)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    info["machine"] = machine
    info["timestamp"] = ts
    info["size_of_image"] = struct.unpack_from("<I", data, opt + 56)[0]
    info["slot"] = "%08X%x" % (ts, info["size_of_image"])
    if magic == 0x20B:
        dd_off = opt + 112
    elif magic == 0x10B:
        dd_off = opt + 96
    else:
        return info

    dbg_rva, dbg_size = struct.unpack_from("<II", data, dd_off + 6 * 8)
    if not dbg_rva:
        return info
    sec = opt + opt_size
    sections = []
    for i in range(nsec):
        off = sec + i * 40
        if off + 40 > len(data):
            break
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((vaddr, max(vsize, rawsize), rawptr))

    def rva2off(rva: int):
        for vaddr, vsz, rawptr in sections:
            if vaddr <= rva < vaddr + vsz:
                return rawptr + (rva - vaddr)
        return None

    dbg_off = rva2off(dbg_rva)
    if dbg_off is None:
        return info
    for i in range(dbg_size // 28):
        off = dbg_off + i * 28
        if off + 28 > len(data):
            break
        typ = struct.unpack_from("<I", data, off + 12)[0]
        size_of_data = struct.unpack_from("<I", data, off + 16)[0]
        ptr = struct.unpack_from("<I", data, off + 24)[0]
        if typ != 2 or size_of_data < 24:
            continue
        cv = ptr if ptr else rva2off(struct.unpack_from("<I", data, off + 20)[0])
        if cv is None or data[cv:cv + 4] != b"RSDS":
            continue
        g1, g2, g3 = struct.unpack_from("<IHH", data, cv + 4)
        g4 = data[cv + 12:cv + 20]
        guid = "%08X-%04X-%04X-%s-%s" % (
            g1, g2, g3, g4[:2].hex().upper(), g4[2:].hex().upper())
        age = struct.unpack_from("<I", data, cv + 20)[0]
        name = data[cv + 24:cv + 24 + size_of_data - 24].split(b"\0")[0]
        info["pdb_guid"] = guid
        info["pdb_age"] = age
        info["pdb_name"] = name.decode("ascii", "replace") or None
        break
    return info


def pdb_slot_from_rsds(guid: str, age: int) -> str:
    """Canonical msdl slot for a PDB: GUID without hyphens, then age, concatenated."""
    return "%s%d" % (guid.replace("-", "").upper(), int(age))


def download(url: str, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "dui-pipeline-ci"})
    with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


# --------------------------------------------------------------------- gate R1
def check_download(args) -> int:
    """R1: both manifest URLs are well-formed, download, and match pinned sha256."""
    mf = json.loads((args.pinned / "manifest.json").read_text(encoding="utf-8"))

    specs = []
    for key in ("dll", "pdb"):
        spec = mf.get(key) or {}
        url = spec.get("source_url")
        if not url:
            fail("R1", f"manifest.{key}.source_url present", "missing",
                 "manifest must carry the msdl URL for BOTH artefacts (see CI.md §7)")
            return 1
        m = _MSDL_URL_RE.match(url)
        if not m:
            fail("R1", f"manifest.{key}.source_url is an msdl symbol-server URL", url,
                 "note: the canonical PDB slot is '<GUID without hyphens><age>' "
                 "(no separator) -- a hyphenated or space-separated slot 404s")
            return 1
        specs.append((key, spec, url, m.group("name"), m.group("slot")))
        ok("R1", f"{key}.source_url well-formed: {url}")

    work = args.work
    # DLL and PDB go to SEPARATE directories -- dumpbin changes its output when a
    # same-named PDB sits beside the DLL (see the module docstring).
    dll = work / "dll-only" / specs[0][3]
    pdb = work / "pdb-only" / specs[1][3]
    paths: dict[str, pathlib.Path] = {}
    for (key, spec, url, _name, _slot), dest in zip(specs, (dll, pdb)):
        if args.skip_download and dest.is_file():
            ok("R1", f"{key}: reusing {dest} (--skip-download)")
        else:
            try:
                download(url, dest)
            except (urllib.error.URLError, OSError) as exc:
                fail("R1", f"{key} download succeeds ({url})",
                     f"{type(exc).__name__}: {exc}")
                return 1
        actual = sha256_file(dest)
        expected = (spec.get("sha256") or "").upper()
        if actual != expected:
            fail("R1", f"{key} downloaded sha256 == manifest {expected[:16]}...",
                 f"{actual[:16]}...",
                 "silently accepting a different revision is exactly the 19041 "
                 "lesson -- refusing")
            return 1
        size = dest.stat().st_size
        if size != spec.get("size"):
            fail("R1", f"{key} downloaded size == manifest {spec.get('size')}", str(size))
            return 1
        paths[key] = dest
        ok("R1", f"{key} byte-identical to pinned "
                 f"(sha256 {actual[:16]}..., {size} bytes)")

    # The DLL slot is derivable from the PE header; cross-check it against the
    # stored URL so a hand-edited URL cannot go unnoticed.
    pi = pe_info(paths["dll"])
    if pi.get("slot") != specs[0][4]:
        fail("R1", f"PE-derived dll slot == {specs[0][4]} (from source_url)",
             str(pi.get("slot")),
             "the stored URL is a credential derived from the PE header; they must agree")
        return 1
    ok("R1", f"PE-derived dll slot {pi['slot']} == source_url slot "
             f"(TimeDateStamp={pi['timestamp']:#x}, SizeOfImage={pi['size_of_image']:#x})")

    # The PDB slot is derivable from the DLL's RSDS record (the authoritative
    # dll->pdb link); cross-check it the same way.
    if not pi.get("pdb_guid") or pi.get("pdb_age") is None:
        fail("R1", "DLL carries an RSDS record linking it to a PDB", "no RSDS found")
        return 1
    rsds_slot = pdb_slot_from_rsds(pi["pdb_guid"], pi["pdb_age"])
    if rsds_slot != specs[1][4]:
        fail("R1", f"RSDS-derived pdb slot == {specs[1][4]} (from source_url)", rsds_slot,
             f"RSDS in the DLL says guid={pi['pdb_guid']} age={pi['pdb_age']} "
             f"name={pi['pdb_name']}")
        return 1
    ok("R1", f"RSDS-derived pdb slot {rsds_slot} == source_url slot "
             f"(guid={pi['pdb_guid']}, age={pi['pdb_age']}, name={pi['pdb_name']})")

    (work / "inputs.json").write_text(json.dumps(
        {"dll": str(paths["dll"]), "pdb": str(paths["pdb"]), "pe": pi}, indent=1),
        encoding="utf-8")
    return 0


# --------------------------------------------------------------------- gate R2
def check_rebuild(args) -> int:
    """R2: re-derive pinned/ in an isolated dir (DLL + PDB publics) and compare."""
    work = args.work
    iso = work / "iso"
    if iso.exists():
        shutil.rmtree(iso)
    (iso / "pinned").mkdir(parents=True)
    (iso / "build").mkdir(parents=True)

    inputs = json.loads((work / "inputs.json").read_text(encoding="utf-8"))
    dll = pathlib.Path(inputs["dll"])
    pdb = pathlib.Path(inputs["pdb"])

    # Guard our own layout: a same-named PDB beside the DLL silently changes
    # dumpbin's output and would make this gate fail for an environmental reason.
    beside = dll.parent / (dll.stem + ".pdb")
    if beside.exists():
        fail("R2", "no PDB sits beside the DLL (dumpbin annotation trap)",
             f"{beside} exists",
             "dumpbin /exports appends ' = name' annotations when a matching PDB is "
             "next to the DLL, and extract.py mis-attributes those lines. Keep the "
             "DLL and PDB in separate directories.")
        return 1

    # PDB publics -> text (in the PDB's own directory, never the DLL's)
    pdbutil, note = resolve_pdbutil(args.pdbutil)
    if pdbutil is None:
        fail("R2", "an llvm-pdbutil is available to read PDB publics", note)
        return 1
    ok("R2", note)
    publics_txt = pdb.parent / "publics.txt"
    try:
        with publics_txt.open("w", encoding="utf-8") as fh:
            r = subprocess.run([pdbutil, "dump", "-publics", str(pdb)],
                               stdout=fh, stderr=subprocess.PIPE, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        fail("R2", "llvm-pdbutil dump -publics succeeds", f"{type(exc).__name__}: {exc}")
        return 1
    if r.returncode != 0:
        fail("R2", "llvm-pdbutil dump -publics succeeds", f"rc={r.returncode}",
             (r.stderr or "")[-800:])
        return 1
    if publics_txt.stat().st_size < 1024:
        fail("R2", "publics text is non-trivial", f"{publics_txt.stat().st_size} bytes")
        return 1

    py = args.python or sys.executable
    env = dict(os.environ)
    if args.dumpbin:
        env["DUMPBIN"] = args.dumpbin
    cmd = [py, str(HERE / "extract.py"), "--dll", str(dll), "--pdb", str(pdb),
           "--pdb-publics", str(publics_txt),
           "--pinned", str(iso / "pinned"), "--build", str(iso / "build"), "--new-pin"]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), env=env)
    if p.returncode != 0:
        fail("R2", "extract.py re-derives pinned/exports.json", f"rc={p.returncode}",
             (p.stdout or "")[-1500:] + (p.stderr or "")[-800:])
        return 1

    # ---- exports.json must be byte-identical
    committed_exports = (args.pinned / "exports.json").read_bytes()
    rebuilt_exports_path = iso / "pinned" / "exports.json"
    if not rebuilt_exports_path.is_file():
        fail("R2", "rebuilt exports.json exists", "missing")
        return 1
    rebuilt_exports = rebuilt_exports_path.read_bytes()
    n_rows = len(json.loads(rebuilt_exports.decode("utf-8"))["exports"])
    if rebuilt_exports != committed_exports:
        a = json.loads(committed_exports.decode("utf-8"))["exports"]
        b = json.loads(rebuilt_exports.decode("utf-8"))["exports"]
        na, nb = [e["name"] for e in a], [e["name"] for e in b]
        n_annot = sum(1 for x, y in zip(a, b) if x != y)
        fail("R2", "rebuilt exports.json is byte-identical to committed", "differs",
             f"committed rows={len(a)} rebuilt rows={len(b)}\n"
             f"same order: {na == nb}\n"
             f"differing rows: {n_annot}\n"
             f"only committed: {len(set(na) - set(nb))}, only rebuilt: {len(set(nb) - set(na))}\n"
             f"HINT: if names look shifted between neighbouring ordinals, the dumpbin\n"
             f"' = ' annotation trap is probably armed (a PDB beside the DLL).")
        return 1
    ok("R2", f"exports.json rebuilt byte-identically "
             f"({n_rows} rows, sha256 {hashlib.sha256(rebuilt_exports).hexdigest()[:16]}...)")

    # ---- manifest fingerprints
    cm = json.loads((args.pinned / "manifest.json").read_text(encoding="utf-8"))
    rm = json.loads((iso / "pinned" / "manifest.json").read_text(encoding="utf-8"))
    for key, fields in (("dll", DLL_HARD_FIELDS), ("pdb", PDB_HARD_FIELDS)):
        for f in fields:
            if (cm.get(key) or {}).get(f) != (rm.get(key) or {}).get(f):
                fail("R2", f"rebuilt manifest {key}.{f} == committed "
                           f"{(cm.get(key) or {}).get(f)!r}",
                     repr((rm.get(key) or {}).get(f)))
                return 1
    ok("R2", "manifest dll sha256/size/arch and pdb sha256/size/guid/age all match "
             f"(dll file_version is informational: committed={cm['dll'].get('file_version')} "
             f"rebuilt={rm['dll'].get('file_version')})")

    # ---- model.py -> symbols.json
    iso_raw = iso / "build" / "extract-raw.json"
    if not iso_raw.is_file():
        fail("R2", "extract.py produced the extract-raw.json handoff", "missing")
        return 1
    n_publics = len(json.loads(iso_raw.read_text(encoding="utf-8")).get("publics") or [])
    if n_publics == 0:
        fail("R2", "publics were extracted from the PDB", "0 publics rows",
             "without publics the rebuild cannot reach the committed 11983 rows")
        return 1

    undname, note = resolve_undname(args.undname)
    if undname is None:
        fail("R2", "an LLVM-format undname is available for model.py", note)
        return 1
    ok("R2", note)
    env["LLVM_UNDNAME"] = undname
    cmd2 = [py, str(HERE / "model.py"), "--raw", str(iso_raw),
            "--pinned", str(iso / "pinned"),
            "--inventory", str(args.pinned / "class-inventory.csv"),
            "--undname", undname]
    p2 = subprocess.run(cmd2, capture_output=True, text=True, cwd=str(REPO), env=env)
    if p2.returncode != 0:
        fail("R2", "model.py re-derives symbols.json", f"rc={p2.returncode}",
             (p2.stdout or "")[-1200:] + (p2.stderr or "")[-800:])
        return 1

    # classes.json is deliberately NOT compared: it is a hand-curated input
    # (195 classes), not something model.py derives for us to re-derive.
    return compare_symbols(args.pinned, iso / "pinned", n_publics)


# --------------------------------------------------------------------- gate R3
def compare_symbols(pinned: pathlib.Path, reb: pathlib.Path, n_publics: int) -> int:
    """R3: rebuilt symbols.json must be BYTE-IDENTICAL to the committed one."""
    rebuilt_path = reb / "symbols.json"
    if not rebuilt_path.is_file():
        fail("R3", "rebuilt symbols.json exists", "missing")
        return 1
    rb = rebuilt_path.read_bytes()
    cb = (pinned / "symbols.json").read_bytes()
    n_rb = len(json.loads(rb.decode("utf-8"))["symbols"])
    n_cb = len(json.loads(cb.decode("utf-8"))["symbols"])

    if rb == cb:
        # The two inputs overlap (publics include exported symbols), so report the
        # split the same way model.py's contract does: export-table rows plus the
        # publics-only remainder that the export table alone cannot supply.
        n_exports = len(json.loads((pinned / "exports.json").read_text(
            encoding="utf-8"))["exports"])
        only_publics = n_rb - n_exports
        ok("R3", f"symbols.json rebuilt byte-identically ({n_rb} rows = "
                 f"{n_exports} export-table + {only_publics} PDB-publics-only, "
                 f"sha256 {hashlib.sha256(rb).hexdigest()[:16]}...)")
        return 0

    a = json.loads(rb.decode("utf-8"))["symbols"]
    b = json.loads(cb.decode("utf-8"))["symbols"]
    by_mangled = {s.get("mangled"): s for s in b}
    missing = [s.get("mangled") for s in a if s.get("mangled") not in by_mangled]
    n = min(len(a), len(b))
    fields = ("kind", "class", "member", "params", "return_type", "rva",
              "is_exported", "is_static", "is_virtual", "is_const")
    diffs = []
    for i in range(n):
        if a[i] != b[i]:
            differing = [f for f in fields if a[i].get(f) != b[i].get(f)]
            diffs.append((i, a[i], b[i], differing))
    detail = [f"rebuilt rows={len(a)} committed rows={len(b)}",
              f"symbols missing from committed: {len(missing)}",
              f"differing rows: {len(diffs)}"]
    for i, x, y, fl in diffs[:6]:
        detail.append(f"  #{i} differs in {fl}")
        detail.append(f"     rebuilt = {json.dumps(x, ensure_ascii=False)[:170]}")
        detail.append(f"     commit  = {json.dumps(y, ensure_ascii=False)[:170]}")
    if missing:
        detail.append("  first missing: " + ", ".join(str(m) for m in missing[:5]))
    fail("R3", "rebuilt symbols.json is byte-identical to committed", "differs",
         "\n".join(detail))
    return 1


# ------------------------------------------------------------------- gate R3'
def compare_vtable_slots(args, dll: pathlib.Path) -> int:
    """R3': re-derive pinned/vtable-slots.json and byte-compare it.

    vtable-slots.json is a pure function of the DLL bytes + symbols.json (see
    extract-vtable-slots.py). Unlike classes.json (hand-curated, deliberately
    exempt), it MUST be re-derivable: a hand edit to the table changes J1's
    verdict, and re-signing pinned.sha256 would let G1 pass anyway -- R3' is
    what closes that hole. Tamper proof measured on the prototype: editing
    three AddRef entries to Release diverges from re-derivation and fails here.
    """
    committed = args.pinned / "vtable-slots.json"
    if not committed.is_file():
        fail("R3'", "committed vtable-slots.json exists", "missing",
             "the table is a pipeline artifact; regenerate it with "
             "extract-vtable-slots.py --slots pinned/vtable-slots.json")
        return 1

    work = args.work / "r3prime"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    rebuilt = work / "vtable-slots.json"
    cmd = [sys.executable, str(HERE / "extract-vtable-slots.py"),
           "--dll", str(dll), "--symbols", str(args.pinned / "symbols.json"),
           "--slots", str(rebuilt)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           cwd=str(REPO))
    except (OSError, subprocess.SubprocessError) as exc:
        fail("R3'", "extract-vtable-slots.py re-derives the table",
             f"{type(exc).__name__}: {exc}")
        return 1
    if p.returncode != 0:
        fail("R3'", "extract-vtable-slots.py re-derives the table",
             f"rc={p.returncode}", (p.stdout or "")[-800:] + (p.stderr or "")[-800:])
        return 1

    # LF-canonical comparison (same rule as G1/pinned.sha256): a fresh
    # checkout on Windows CRLF-converts text files (.gitattributes `* text=auto`),
    # and R2/R3 pass only because extract.py writes with the platform newline
    # (CRLF on Windows) while extract-vtable-slots.py pins newline="n". A raw
    # byte compare is therefore newline-mode-inconsistent across runners.
    # Comparing after CRLF -> LF normalisation keeps the assertion
    # content-exact and checkout-independent. (First CI run of this gate,
    # PR #3, failed exactly here: 39224 CRLF pairs, 0 content diffs.)
    rb = rebuilt.read_bytes().replace(b"\r\n", b"\n")
    cb = committed.read_bytes().replace(b"\r\n", b"\n")
    if rb == cb:
        n = len(json.loads(cb.decode("utf-8"))["classes"])
        ok("R3'", f"vtable-slots.json re-derived byte-identically "
                  f"(LF-canonical; {n} classes, sha256 "
                  f"{hashlib.sha256(cb).hexdigest()[:16]}...)")
        return 0

    # Destructure the divergence for the log: which classes differ.
    a = json.loads(rb.decode("utf-8"))["classes"]
    b = json.loads(cb.decode("utf-8"))["classes"]
    only_rebuilt = sorted(set(a) - set(b))
    only_committed = sorted(set(b) - set(a))
    cls_diff = [c for c in sorted(set(a) & set(b)) if a[c] != b[c]]
    detail = [f"rebuilt classes={len(a)} committed classes={len(b)}",
              f"classes differing: {len(cls_diff)}",
              f"only in rebuilt: {only_rebuilt[:5]}",
              f"only in committed: {only_committed[:5]}"]
    for c in cls_diff[:6]:
        sa, sb = a[c]["slots"], b[c]["slots"]
        detail.append(f"  {c}: rebuilt {len(sa)} slots vs committed {len(sb)}")
        for k in range(min(len(sa), len(sb))):
            if sa[k] != sb[k]:
                detail.append(f"    slot {k}: rebuilt={json.dumps(sa[k])[:90]}")
                detail.append(f"             committed={json.dumps(sb[k])[:90]}")
                break
    fail("R3'", "vtable-slots.json re-derived byte-identical to committed",
         "differs", "\n".join(detail))
    return 1


# ------------------------------------------------------------------------ main
def compare_mi_tables(args, dll: pathlib.Path) -> int:
    """R3'': re-derive pinned/mi-tables.json DERIVED section and compare.

    mi-tables.json is a TWO-section document (schema 2):
      derived -- a pure function of DLL bytes + symbols.json + the
                 manual interface-lengths file (the lengths enter the
                 derivation as INPUTS; the derived section never
                 contains a length that lacks either in-binary evidence
                 or a manual input)
      manual  -- the human ABI inputs themselves

    R3'' re-derives `derived` under the COMMITTED manual inputs and
    compares (LF-canonical JSON semantics). The `manual` section is NOT
    compared against any re-derivation -- by construction it cannot be
    re-derived; its integrity is locked by G1 (pinned.sha256). This is
    exactly the split the schema exists to make: no "pure function"
    claim is ever made about the manual part.

    When pinned/mi-tables.json is ABSENT the gate is a no-op PASS
    (schema-2 adoption is incremental; schema 1 remains authoritative
    for primaries everywhere else).
    """
    committed = args.pinned / "mi-tables.json"
    if not committed.is_file():
        ok("R3''", "mi-tables.json absent -- schema-2 not adopted yet "
                   "(no-op pass)")
        return 0
    lengths = args.pinned / "mi-interface-lengths.json"
    if not lengths.is_file():
        fail("R3''", "pinned/mi-interface-lengths.json exists "
                     "(manual inputs for the derived section)", "missing")
        return 1

    work = args.work / "r3dblprime"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    rebuilt = work / "mi-tables.json"
    cmd = [sys.executable, str(HERE / "extract-mi-tables.py"),
           "--dll", str(dll), "--symbols", str(args.pinned / "symbols.json"),
           "--out", str(rebuilt), "--lengths", str(lengths)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           cwd=str(REPO))
    except (OSError, subprocess.SubprocessError) as exc:
        fail("R3''", "extract-mi-tables.py re-derives the derived section",
             f"{type(exc).__name__}: {exc}")
        return 1
    if p.returncode != 0:
        fail("R3''", "extract-mi-tables.py re-derives the derived section",
             f"rc={p.returncode}", (p.stdout or "")[-800:] + (p.stderr or "")[-800:])
        return 1

    def canon(path: pathlib.Path) -> dict:
        return json.loads(
            path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))

    try:
        rb = canon(rebuilt)
        cb = canon(committed)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail("R3''", "mi-tables.json parses", f"{type(exc).__name__}: {exc}")
        return 1
    if rb.get("schema") != 2 or cb.get("schema") != 2:
        fail("R3''", "both sides are schema 2", "schema mismatch")
        return 1
    if rb.get("manual") != cb.get("manual"):
        fail("R3''", "manual section identical (inputs copied verbatim)",
             "manual sections differ")
        return 1
    if rb.get("derived") == cb.get("derived"):
        n = len(cb.get("derived", {}))
        ok("R3''", f"mi-tables.json derived section re-derived identically "
                   f"({n} classes; manual section is a G1-locked input, "
                   f"deliberately outside the re-derivation claim)")
        return 0

    a, b = rb.get("derived", {}), cb.get("derived", {})
    only_r = sorted(set(a) - set(b))
    only_c = sorted(set(b) - set(a))
    detail = []
    if only_r:
        detail.append(f"only in rebuilt: {only_r[:8]}")
    if only_c:
        detail.append(f"only in committed: {only_c[:8]}")
    both = sorted(set(a) & set(b))
    shown = 0
    for cls in both:
        if a[cls] != b[cls]:
            detail.append(f"{cls}: differs")
            shown += 1
            if shown >= 8:
                detail.append("... (+more)")
                break
    fail("R3''", "mi-tables.json derived section re-derives identically",
         "differs", "\n".join(detail))
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CI stage 2: re-derive pinned/ from msdl (dll + pdb) and assert "
                    "byte-equality")
    ap.add_argument("--pinned", type=pathlib.Path, default=REPO / "pinned")
    ap.add_argument("--work", type=pathlib.Path, default=REPO / ".local" / "build" / "repro")
    ap.add_argument("--python", default=None, help="python interpreter for sub-tools")
    ap.add_argument("--dumpbin", default=None, help="dumpbin path (or set DUMPBIN)")
    ap.add_argument("--pdbutil", default=None,
                    help="llvm-pdbutil path (or set LLVM_PDBUTIL)")
    ap.add_argument("--undname", default=None,
                    help="llvm-undname path (model.py needs LLVM's undname, not MSVC's)")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the artefacts from a previous run (offline debugging)")
    args = ap.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)

    print("=" * 74)
    print("R1  re-download BOTH pinned artefacts from their manifest source_url")
    print("=" * 74)
    if check_download(args) != 0:
        return 1
    print()
    print("=" * 74)
    print("R2  re-derive pinned/ in an isolated dir (DLL + PDB publics)")
    print("=" * 74)
    if check_rebuild(args) != 0:
        return 1
    print()
    print("=" * 74)
    print("R3' re-derive pinned/vtable-slots.json (DLL bytes + symbols.json)")
    print("=" * 74)
    inputs = json.loads((args.work / "inputs.json").read_text(encoding="utf-8"))
    if compare_vtable_slots(args, pathlib.Path(inputs["dll"])) != 0:
        return 1
    print()
    print("=" * 74)
    print("R3'' re-derive pinned/mi-tables.json DERIVED section (schema 2)")
    print("=" * 74)
    if compare_mi_tables(args, pathlib.Path(inputs["dll"])) != 0:
        return 1
    print()
    print("ALL REPRO ASSERTIONS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
