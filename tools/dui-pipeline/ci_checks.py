#!/usr/bin/env python3
"""CI gate helpers for the dui-pipeline (consumer only — never mutates the pipeline).

This module implements the *checkable* parts of the CI gates so that `ci.ps1`
stays a thin orchestrator. It never writes to `pinned/` or `DirectUI/`; the only
file it can create is the sha256 manifest (explicit `--write`).

Subcommands
    hash      verify (or --write) the sha256 manifest of pinned/
    struct    structural consistency: classes.json vs the generated tree
    totals    derive the expected modname / extern-C totals FROM pinned data
    headers   sample N generated headers and syntax-check them with cl.exe
    selftest  self-verification of this script's own verdict logic

Exit codes: 0 = green, 1 = gate failed, 2 = usage / environment error.
All failure detail goes to stderr in the form
    GATE <id>: FAIL  expected=<..>  actual=<..>
so `ci.ps1` can surface "which gate, what was expected, what was seen".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_PINNED = REPO / "pinned"
DEFAULT_OUT = REPO / "DirectUI"
DEFAULT_MANIFEST = HERE / "pinned.sha256"

MANIFEST_HEADER = (
    "# sha256 manifest for pinned/ -- the frozen pipeline contract input.\n"
    "#\n"
    "# Hash covers LF-canonical content (CRLF normalised to LF) so the manifest is\n"
    "# checkout-independent: .gitattributes sets `* text=auto`, which rewrites line\n"
    "# endings on checkout under core.autocrlf=true. Hashing raw bytes would make\n"
    "# this gate pass in one working tree and fail in a fresh clone or on Linux.\n"
    "#\n"
    "# Regenerate ONLY when intentionally re-pinning:\n"
    "#   python tools/dui-pipeline/ci_checks.py hash --write\n"
    "# Format: <sha256>  <path relative to pinned/>  (sorted, LF, lowercase hex)\n"
)


def fail(gate: str, expected: str, actual: str, extra: str = "") -> None:
    print(f"GATE {gate}: FAIL  expected={expected}  actual={actual}", file=sys.stderr)
    if extra:
        print(extra.rstrip(), file=sys.stderr)


def sha256_file(path: Path) -> str:
    """sha256 of the file's **LF-canonical** content.

    Why not raw bytes: `.gitattributes` declares `* text=auto`, so a checkout
    rewrites LF to CRLF under `core.autocrlf=true` (Windows default). Hashing raw
    bytes would make the manifest checkout-dependent -- it would pass in this
    working tree and FAIL in a fresh clone or on the Linux CI runner. The gate is
    about *content identity*, so we hash exactly what git considers the content:
    CRLF normalised to LF, which is what git stores and what a Linux checkout has.

    (Verified: this repo's worktree `pinned/manifest.json` is LF/836B while a
    fresh `git clone` on the same machine is CRLF/858B, yet `git diff` reports no
    change for a CRLF->LF rewrite. Normalising here reproduces git's own view.)
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk.replace(b"\r\n", b"\n"))
    return h.hexdigest()


# --------------------------------------------------------------------------- hash
def pinned_files(pinned: Path) -> list[Path]:
    """Every regular file under pinned/, recursively, sorted by relative posix path."""
    return sorted((p for p in pinned.rglob("*") if p.is_file()),
                  key=lambda p: p.relative_to(pinned).as_posix())


def cmd_hash(args: argparse.Namespace) -> int:
    pinned: Path = args.pinned
    if not pinned.is_dir():
        fail("G1", "pinned/ exists", f"missing: {pinned}")
        return 2
    files = pinned_files(pinned)

    if args.write:
        lines = [MANIFEST_HEADER]
        for p in files:
            lines.append(f"{sha256_file(p)}  {p.relative_to(pinned).as_posix()}\n")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
        print(f"wrote {args.manifest} ({len(files)} entries)")
        return 0

    if not args.manifest.is_file():
        fail("G1", f"manifest exists: {args.manifest}", "missing", 
             "        fix: python tools/dui-pipeline/ci_checks.py hash --write")
        return 2

    recorded: dict[str, str] = {}
    for raw in args.manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            fail("G1", "parseable manifest line", f"bad line: {raw!r}")
            return 2
        recorded[parts[1].strip().lstrip("*")] = parts[0].lower()

    actual_names = {p.relative_to(pinned).as_posix() for p in files}
    mismatched: list[str] = []
    for rel in sorted(recorded):
        p = pinned / rel
        if not p.is_file():
            mismatched.append(f"  MISSING  {rel}  (recorded {recorded[rel][:12]}...)")
            continue
        got = sha256_file(p)
        if got != recorded[rel]:
            mismatched.append(f"  CHANGED  {rel}\n"
                              f"           expected sha256 {recorded[rel]} (LF-canonical)\n"
                              f"           actual   sha256 {got}")
    for rel in sorted(actual_names - set(recorded)):
        mismatched.append(f"  UNTRACKED  {rel}  (present but not in manifest)")

    if mismatched:
        fail("G1", f"{len(files)} pinned files match the sha256 manifest",
             f"{len(mismatched)} discrepanc{'y' if len(mismatched) == 1 else 'ies'}",
             "\n".join(mismatched))
        return 1

    print(f"G1 OK  {len(files)} pinned files match {args.manifest.name} "
          f"(sha256, LF-canonical)")
    for p in files:
        print(f"        {recorded[p.relative_to(pinned).as_posix()][:16]}  "
              f"{p.relative_to(pinned).as_posix()}")
    return 0


# ------------------------------------------------------------------------- totals
def load_pinned(pinned: Path) -> tuple[list, list, dict]:
    try:
        exports = json.loads((pinned / "exports.json").read_text(encoding="utf-8"))["exports"]
        symbols = json.loads((pinned / "symbols.json").read_text(encoding="utf-8"))["symbols"]
        classes = json.loads((pinned / "classes.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise SystemExit(f"G3/G4: cannot read pinned contract data ({exc})")
    return exports, symbols, classes


def in_directui_scope(sym: dict) -> bool:
    """Byte-for-byte the same predicate `emit_headers.in_directui_scope` uses.

    Imported rather than re-implemented when available, so CI cannot drift from
    the generator's own definition of "this symbol belongs to DirectUI".
    """
    try:
        sys.path.insert(0, str(HERE))
        from emit_headers import in_directui_scope as impl  # noqa: PLC0415
        return bool(impl(sym))
    except Exception:  # pragma: no cover - fallback for a bare checkout
        m = sym.get("mangled") or ""
        cls = sym.get("class") or ""
        if not m.startswith("?"):
            return True
        import re
        m2 = re.match(r"^\?\??\w+@" + re.escape(cls) + r"@([^@]+)@", m)
        if not m2:
            return True
        return m2.group(1) == "DirectUI"


def expected_totals(pinned: Path) -> dict:
    """Derive the two headline fidelity numbers FROM pinned data (never hardcoded).

    modname_total = sum over classes.json classes of |exported & DirectUI-scope
    symbols attributed to that class|  -- exactly verify_codegen.py's `total`.
    capi_total    = count of plain-name (non '?') exports in exports.json.
    """
    exports, symbols, classes = load_pinned(pinned)
    cls_list = classes["classes"]
    by_class: dict[str, set[str]] = {}
    for s in symbols:
        if s.get("is_exported") and in_directui_scope(s):
            by_class.setdefault(s.get("class"), set()).add(s["mangled"])
    modname_total = sum(len(by_class.get(c, set())) for c in cls_list)
    capi_total = sum(1 for e in exports if not e["name"].startswith("?"))
    return {
        "modname_total": modname_total,
        "capi_total": capi_total,
        "class_count": len(cls_list),
        "inheritance_count": len(classes.get("inheritance", {})),
        "exports_total": len(exports),
        "symbols_total": len(symbols),
        "classes": cls_list,
    }


def cmd_totals(args: argparse.Namespace) -> int:
    t = expected_totals(args.pinned)
    if args.json:
        t.pop("classes", None)
        print(json.dumps(t, indent=2))
    else:
        print(f"modname_total      = {t['modname_total']}  (from classes.json x symbols.json)")
        print(f"capi_total         = {t['capi_total']}  (plain-name exports in exports.json)")
        print(f"class_count        = {t['class_count']}")
        print(f"inheritance_count  = {t['inheritance_count']}")
        print(f"exports_total      = {t['exports_total']}")
        print(f"symbols_total      = {t['symbols_total']}")
    return 0


# ------------------------------------------------------------------------- struct
# Headers in DirectUI/include/ that classes.json does not imply, split by origin.
#
#   GENERATED_EXTRA -- written by emit_headers.py next to the per-class headers.
#       Reproducible from pinned/, so regen must produce them.
#   HANDWRITTEN     -- maintained by hand and NOT derivable from pinned/: dui70's
#       runtime reflection is the only source. Being in this set means G3 demands
#       the file EXISTS and G5 compiles it -- an entry added here is a deliberate
#       widening of what "the generated tree" contains and must be reviewed as one.
#
# Kept at module scope so G3 (existence) and G5 (compile) read one registry.
GENERATED_EXTRA = {"DirectUI", "Interfaces", "dui_abi_types"}
HANDWRITTEN = {"DuiEnums"}


def cmd_struct(args: argparse.Namespace) -> int:
    """G3: the generated tree must agree with the pinned contract on class count.

    The expected count is READ from classes.json, never hardcoded -- this is the
    regression guard for the `model.py` overwrote-classes.json incident.

    "Materialised" means: a class gets its own header + TU **unless** the
    pipeline declares it a nested type (nested pseudo-class such as
    ACCESSIBLEROLE, or a `FunctionDefinition<T>` specialization nested in
    DUIXmlParser). Those are emitted inside their host's TU. We reuse the
    generator's own predicates so CI cannot invent a second definition of
    "nested".
    """
    pinned: Path = args.pinned
    out: Path = args.out
    t = expected_totals(pinned)
    cls_list = t["classes"]
    expected = len(cls_list)

    inc = out / "include"
    src = out / "src"
    if not inc.is_dir():
        fail("G3", f"generated include dir {inc}", "missing")
        return 2
    if not src.is_dir():
        fail("G3", f"generated src dir {src}", "missing")
        return 2

    try:
        sys.path.insert(0, str(HERE))
        from emit_headers import (is_duixml_nested, is_nested_pseudo_class,  # noqa: PLC0415
                                  nested_host_of, safe_name)
    except Exception as exc:  # pragma: no cover
        fail("G3", "import emit_headers helpers", f"{exc}")
        return 2

    headers = {p.stem for p in inc.glob("*.h")}
    tus = {p.stem for p in src.glob("*.cpp")}
    class_tus = tus - {"CApi"}          # CApi.cpp is the extern-C TU, not a class

    nested = {c for c in cls_list if is_duixml_nested(c) or is_nested_pseudo_class(c)}
    standalone = [c for c in cls_list if c not in nested]
    want = {safe_name(c) for c in standalone}


    problems: list[str] = []

    # EXACT equality, not a subset test. A subset test would accept a *shrunk*
    # classes.json (195 -> 12) against a full tree -- precisely the "model.py
    # overwrote classes.json" incident this gate exists to catch. Requiring
    # equality means both directions fail: a missing artefact AND a stale extra.
    missing_hdr = sorted(want - headers)
    extra_hdr = sorted(headers - want - GENERATED_EXTRA - HANDWRITTEN)
    if missing_hdr:
        problems.append(f"{len(missing_hdr)} class header(s) missing from include/: "
                        f"{missing_hdr[:6]}")
    if extra_hdr:
        problems.append(f"{len(extra_hdr)} header(s) present but not implied by "
                        f"classes.json: {extra_hdr[:6]}")

    # A registered hand-written header must exist. Exact equality cannot see its
    # absence: it is subtracted from the "extra" set, so deleting it would leave
    # nothing behind to complain about.
    missing_hand = sorted(HANDWRITTEN - headers)
    if missing_hand:
        problems.append(f"{len(missing_hand)} registered hand-written header(s) "
                        f"missing from include/: {missing_hand[:6]}")

    missing_tu = sorted(want - class_tus)
    extra_tu = sorted(class_tus - want)
    if missing_tu:
        problems.append(f"{len(missing_tu)} class TU(s) missing from src/: "
                        f"{missing_tu[:6]}")
    if extra_tu:
        problems.append(f"{len(extra_tu)} class TU(s) present but not implied by "
                        f"classes.json: {extra_tu[:6]}")

    # nested types must still be accounted for by their host
    orphan_nested: list[str] = []
    for c in sorted(nested):
        host = nested_host_of(c)
        if is_duixml_nested(c):
            host = "DUIXmlParser"
        if host and safe_name(host) not in headers:
            orphan_nested.append(f"{c} (host {host} has no header)")
    if orphan_nested:
        problems.append(f"nested types without a host: {orphan_nested}")

    # the class count must actually come from classes.json, not a constant
    if expected != t["class_count"]:
        problems.append("internal: class_count drift")

    print(f"G3      classes.json declares {expected} classes "
          f"({t['inheritance_count']} inheritance edges)")
    print(f"        standalone classes      : {len(standalone)} "
          f"-> expect {len(standalone)} headers + {len(standalone)} TUs")
    print(f"        nested types (no own TU) : {len(nested)} "
          f"{sorted(nested)[:3]}{' ...' if len(nested) > 3 else ''}")
    print(f"        generated               : {len(headers)} .h "
          f"(={len(want)} class + {sorted(headers - want)}), "
          f"{len(class_tus)} class .cpp (+CApi)")

    if problems:
        fail("G3", f"generated tree == classes.json exactly "
                   f"({len(standalone)} standalone + {len(nested)} nested)",
             "; ".join(problems))
        return 1
    print(f"G3 OK   {expected} classes = {len(standalone)} standalone "
          f"(header+TU each) + {len(nested)} nested (host-embedded); "
          f"no stale/extra artefacts")
    return 0


# ------------------------------------------------------------------------ headers
def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p.returncode, p.stdout


def cmd_headers(args: argparse.Namespace) -> int:
    """G5: syntax-check a *reproducible random sample* of generated headers.

    A fixed seed keeps CI deterministic while still sampling rather than
    compiling all ~192 headers. The aggregate DirectUI.h is always included
    because it is the public entry point.
    """
    inc: Path = args.include
    if not inc.is_dir():
        fail("G5", f"include dir {inc}", "missing")
        return 2
    cl = Path(args.cl)
    if not cl.is_file():
        fail("G5", f"cl.exe at {cl}", "missing")
        return 2

    all_h = sorted(p.name for p in inc.glob("*.h"))
    if not all_h:
        fail("G5", "at least one generated header", "0 headers found")
        return 1

    rng = random.Random(args.seed)
    sample = set(rng.sample(all_h, min(args.sample, len(all_h))))
    sample.add("DirectUI.h")            # public aggregate: always checked
    # Force-add the hand-written registry too: they are 1-of-N in a 12-header
    # sample, so leaving them to the draw means they would usually NOT be
    # compiled -- and these are the files most likely to drift.
    #
    # HANDWRITTEN holds header STEMS (G3 compares `p.stem`); `all_h` holds file
    # NAMES, so the suffix must be added here. Without it the membership test is
    # silently always false and this loop adds nothing.
    for must in ("dui_abi_types.h", *(f"{h}.h" for h in sorted(HANDWRITTEN))):
        if must in all_h:
            sample.add(must)
    sample = sorted(sample)

    # SDK-style include set; explicit so this works outside a dev prompt.
    inc_flags: list[str] = []
    for d in (inc, Path(args.vc_include), Path(args.sdk_root) / "ucrt",
              Path(args.sdk_root) / "shared", Path(args.sdk_root) / "um",
              Path(args.sdk_root) / "winrt"):
        inc_flags += ["/I", str(d)]

    tmp = Path(args.workdir)
    tmp.mkdir(parents=True, exist_ok=True)
    bad: list[str] = []
    warn_total = 0
    for name in sample:
        tu = tmp / f"hdrcheck_{name.replace('.', '_')}.cpp"
        tu.write_text(f"#include <{name}>\n", encoding="ascii", newline="\n")
        rc, out = _run([str(cl), "/nologo", "/Zs", "/std:c++17", "/EHsc", "/W3",
                        *inc_flags, str(tu)])
        warn_total += out.count("warning C")
        if rc != 0:
            first = "\n".join(out.strip().splitlines()[:12])
            bad.append(f"  {name}  (cl rc={rc})\n{first}")

    print(f"G5      sample {len(sample)}/{len(all_h)} headers "
          f"(seed={args.seed}, +DirectUI.h always), cl /Zs syntax-only")
    print(f"        warnings seen: {warn_total} (non-fatal)")
    for name in sample:
        print(f"        ok   {name}")
    if bad:
        fail("G5", f"all {len(sample)} sampled headers parse (cl /Zs rc=0)",
             f"{len(bad)} failed", "\n".join(bad))
        return 1
    print(f"G5 OK   {len(sample)} sampled headers parse cleanly")
    return 0


# ----------------------------------------------------------------------- selftest
def cmd_selftest(args: argparse.Namespace) -> int:
    """Prove the gate verdict logic actually fails when it should."""
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pin = root / "pinned"
        pin.mkdir()
        (pin / "a.json").write_text('{"x":1}\n', encoding="utf-8")
        (pin / "b.bin").write_bytes(b"\x00\x01\x02")
        man = root / "pinned.sha256"

        ns = argparse.Namespace(pinned=pin, manifest=man, write=True)
        if cmd_hash(ns) != 0:
            print("selftest: hash --write failed", file=sys.stderr)
            ok = False

        ns.write = False
        # 1) untouched inputs must PASS
        if cmd_hash(ns) != 0:
            print("selftest: clean inputs reported FAIL (false positive)", file=sys.stderr)
            ok = False

        # 2) a single flipped byte must FAIL
        (pin / "b.bin").write_bytes(b"\x00\x01\x03")
        if cmd_hash(ns) == 0:
            print("selftest: corrupted input reported PASS (false negative!)", file=sys.stderr)
            ok = False
        (pin / "b.bin").write_bytes(b"\x00\x01\x02")

        # 3) an added untracked file must FAIL
        (pin / "c.extra").write_text("x\n", encoding="utf-8")
        if cmd_hash(ns) == 0:
            print("selftest: untracked pinned file reported PASS", file=sys.stderr)
            ok = False
        (pin / "c.extra").unlink()

        # 4) a removed file must FAIL
        (pin / "a.json").unlink()
        if cmd_hash(ns) == 0:
            print("selftest: missing pinned file reported PASS", file=sys.stderr)
            ok = False
        (pin / "a.json").write_text('{"x":1}\n', encoding="utf-8")

        # 5) totals must be derived, and identical across two runs (deterministic)
        if not args.pinned.is_dir():
            print(f"selftest: real pinned/ not found at {args.pinned}", file=sys.stderr)
            return 2
        t1 = expected_totals(args.pinned)
        t2 = expected_totals(args.pinned)
        if t1 != t2:
            print("selftest: expected_totals is non-deterministic", file=sys.stderr)
            ok = False
        if t1["modname_total"] <= 0 or t1["capi_total"] <= 0:
            print(f"selftest: implausible totals {t1}", file=sys.stderr)
            ok = False
        # the metric must move if a class is dropped from the contract
        if t1["class_count"] > 1:
            cls = t1["classes"][:-1]
            shrunk = pin / "classes.json"
            shrunk.write_text(json.dumps({"classes": cls, "inheritance": {}}),
                              encoding="utf-8")
            (pin / "exports.json").write_text(
                (args.pinned / "exports.json").read_text(encoding="utf-8"),
                encoding="utf-8")
            (pin / "symbols.json").write_text(
                (args.pinned / "symbols.json").read_text(encoding="utf-8"),
                encoding="utf-8")
            t3 = expected_totals(pin)
            if t3["class_count"] != t1["class_count"] - 1:
                print("selftest: class_count does not track classes.json", file=sys.stderr)
                ok = False
            if t3["modname_total"] >= t1["modname_total"] and t1["class_count"] > 1:
                print("selftest: modname_total did not shrink when a class was removed "
                      f"({t3['modname_total']} vs {t1['modname_total']})", file=sys.stderr)
                ok = False
            print(f"        metric sensitivity: dropping 1 class moved modname_total "
                  f"{t1['modname_total']} -> {t3['modname_total']}")

    if ok:
        print("SELFTEST PASS  gate logic detects corruption, addition, deletion, and "
              "tracks the contract file")
        return 0
    print("SELFTEST FAIL", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("hash", help="verify/sha256 manifest of pinned/")
    h.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    h.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    h.add_argument("--write", action="store_true", help="(re)generate the manifest")
    h.set_defaults(func=cmd_hash)

    t = sub.add_parser("totals", help="derive expected fidelity totals from pinned/")
    t.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_totals)

    s = sub.add_parser("struct", help="classes.json vs generated tree")
    s.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    s.add_argument("--out", type=Path, default=DEFAULT_OUT)
    s.set_defaults(func=cmd_struct)

    hd = sub.add_parser("headers", help="sample + cl /Zs syntax-check headers")
    hd.add_argument("--include", type=Path, default=DEFAULT_OUT / "include")
    hd.add_argument("--cl", required=True)
    hd.add_argument("--vc-include", required=True)
    hd.add_argument("--sdk-root", required=True)
    hd.add_argument("--sample", type=int, default=12)
    hd.add_argument("--seed", type=int, default=20261002)
    hd.add_argument("--workdir", default=str(REPO / ".local" / "build" / "ci-hdrcheck"))
    hd.set_defaults(func=cmd_headers)

    st = sub.add_parser("selftest", help="verify this script's own verdict logic")
    st.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    st.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
