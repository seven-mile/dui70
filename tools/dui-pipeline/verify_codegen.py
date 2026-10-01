#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_codegen.py -- self-verification harness for the codegen module (schema v2).

Builds every generated stub TU with cl.exe (/std:c++20 /Zc:wchar_t- /c /EHsc),
extracts the decorated names via dumpbin /symbols, and diffs them against
the real dui70.dll export set (pinned/exports.json).

Per contract v2 the target set is: every EXPORTED symbol of the target
classes (the old baseline_status=identical distinction is retired with the
hand-written baseline).

Also asserts extern "C" purity: no obj may contain a C++-decorated name
for the plain C API exports.

This is an internal self-check tool of the codegen module; the pipeline-level
verifier (verifier/verify.py) re-checks independently.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VCBIN = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community"
             r"\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64")
VCINC = Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community"
             r"\VC\Tools\MSVC\14.44.35207\include")
SDKINC = Path(r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0")
CL = VCBIN / "cl.exe"
DUMPBIN = VCBIN / "dumpbin.exe"

DEFAULT_PINNED = REPO / "pinned"
DEFAULT_SRC = REPO / "DirectUI" / "src"
DEFAULT_INC = REPO / "DirectUI" / "include"
DEFAULT_OBJ = REPO / ".local" / "build" / "verify-obj"


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, **kw)


def compile_tu(src: Path, obj_dir: Path, inc: Path) -> tuple[int, str]:
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj = obj_dir / (src.stem + ".obj")
    cmd = [
        CL, "/nologo", "/c", "/std:c++20", "/Zc:wchar_t-", "/EHsc", "/W0",
        f"/I{VCINC}", f"/I{SDKINC / 'ucrt'}", f"/I{SDKINC / 'shared'}",
        f"/I{SDKINC / 'um'}", f"/I{SDKINC / 'winrt'}", f"/I{inc}",
        f"/Fo{obj}", str(src),
    ]
    proc = run(cmd)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def obj_symbols(obj: Path) -> set[str]:
    proc = run([DUMPBIN, "/nologo", "/symbols", str(obj)])
    names = set()
    for line in proc.stdout.splitlines():
        m = re.search(r"External\s+\|\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--inc", type=Path, default=DEFAULT_INC)
    ap.add_argument("--objdir", type=Path, default=DEFAULT_OBJ)
    ap.add_argument("--classes", default=None,
                    help="override the class list from classes.json (comma-separated)")
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args(argv)

    # class list from pinned/classes.json
    classes = json.loads((args.pinned / "classes.json").read_text(encoding="utf-8"))["classes"]
    if args.classes:
        classes = [c.strip() for c in args.classes.split(",") if c.strip()]

    # real export set from pinned/exports.json (schema v2: name field)
    exports = json.loads((args.pinned / "exports.json").read_text(encoding="utf-8"))
    real = {e["name"] for e in exports["exports"]}

    report = []
    total_match = total = 0
    all_ok = True

    for cls in classes:
        # compile
        src = args.src / f"{cls}.cpp"
        if not src.exists():
            report.append(f"## {cls}: MISSING TU {src}")
            all_ok = False
            continue
        rc, out = compile_tu(src, args.objdir, args.inc)
        if rc != 0:
            report.append(f"## {cls}: COMPILE FAILED (rc={rc})")
            report.append("```")
            report.append(out[:4000])
            report.append("```")
            all_ok = False
            continue
        got = obj_symbols(args.objdir / f"{cls}.obj")

        # target set: ALL real exports of this class (contract v2 semantics)
        cls_real = {n for n in real if f"@{cls}@DirectUI@@" in n}
        cls_match = cls_real & got

        n, nm = len(cls_real), len(cls_match)
        total += n
        total_match += nm
        status = "OK" if nm == n else "FAIL"
        if nm != n:
            all_ok = False
        report.append(
            f"## {cls}: real-export match {nm}/{n} [{status}]"
        )
        if nm != n:
            report.append("### missing real exports:")
            for m in sorted(cls_real - got):
                report.append(f"  - {m}")

    pct = 100.0 * total_match / total if total else 0.0
    summary = (
        f"TOTAL real-export match: {total_match}/{total} "
        f"({pct:.2f}%)  {'**100% ACHIEVED**' if pct == 100 else '**NOT 100%**'}"
    )

    # extern "C" purity check: no obj may contain a C++-decorated name for
    # the plain C API exports (e.g. ?InitProcessPriv@DirectUI@@...)
    capi_names = ("InitProcessPriv", "UnInitProcessPriv", "InitThread",
                  "RegisterAllControls", "StartMessagePump", "StrToID")
    capi_bad = []
    capi_plain = 0
    for cls in classes:
        obj = args.objdir / f"{cls}.obj"
        if not obj.exists():
            continue
        for nm in obj_symbols(obj):
            if nm.startswith("?") and any(n in nm for n in capi_names):
                capi_bad.append(f"{cls}: {nm}")
            elif nm in capi_names:
                capi_plain += 1
    if capi_bad:
        all_ok = False
        report.append(f"## extern-C purity: FAIL ({len(capi_bad)} decorated)")
        for b in capi_bad:
            report.append(f"  - {b}")
    else:
        report.append(f"## extern-C purity: OK (no decorated C-API symbols; "
                      f"{capi_plain} plain-name refs)")
    text = "\n".join([summary, ""] + report) + "\n"
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8", newline="\n")
        print(f"report written to {args.report}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
