#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_codegen.py -- self-verification harness for the codegen module.

Builds every generated stub TU with cl.exe (/std:c++20 /Zc:wchar_t- /c /EHsc),
extracts the decorated names via dumpbin /symbols, and diffs them against the
real dui70.dll export set (.local/cache/real-x64-norm.txt).

Reports, per target class:
  * how many of the class's REAL exports the stub .obj reproduces exactly
  * the subset that must match: baseline_status == 'identical' (target: 100%)
  * failures with the closest real symbol for diagnosis

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

DEFAULT_SYMBOLS = REPO / ".local" / "build" / "symbols.json"
DEFAULT_REAL = REPO / ".local" / "cache" / "real-x64-norm.txt"
DEFAULT_SRC = REPO / ".local" / "build" / "generated" / "src"
DEFAULT_INC = REPO / ".local" / "build" / "generated" / "include"
DEFAULT_OBJ = REPO / ".local" / "build" / "generated" / "obj"

TARGET_CLASSES = ["Value", "DUIXmlParser", "Element", "HWNDElement",
                  "NativeHWNDHost", "TouchButton", "Edit"]
MIGRATION_CLASSES = TARGET_CLASSES + ["Button", "Progress", "PushButton",
                                      "TouchCheckBox", "XProvider"]

CALLABLE_KINDS = {"method", "static_method", "ctor", "dtor", "operator"}


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
    ap.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    ap.add_argument("--real", type=Path, default=DEFAULT_REAL)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--inc", type=Path, default=DEFAULT_INC)
    ap.add_argument("--objdir", type=Path, default=DEFAULT_OBJ)
    ap.add_argument("--classes", default=",".join(MIGRATION_CLASSES))
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args(argv)

    classes = [c for c in args.classes.split(",") if c]
    real = set(x.strip() for x in args.real.read_text(encoding="utf-8").splitlines() if x.strip())
    syms = json.loads(args.symbols.read_text(encoding="utf-8"))["symbols"]

    report = []
    total_id_match = total_id = 0
    all_ok = True

    for cls in classes:
        # compile
        src = args.src / f"{cls}.cpp"
        rc, out = compile_tu(src, args.objdir, args.inc)
        if rc != 0:
            report.append(f"## {cls}: COMPILE FAILED (rc={rc})")
            report.append("```")
            report.append(out[:4000])
            report.append("```")
            all_ok = False
            continue
        got = obj_symbols(args.objdir / f"{cls}.obj")

        # expected symbol groups for this class
        cls_syms = [s for s in syms
                    if s.get("class") == cls and s.get("namespace") == "DirectUI"]
        identical = [s for s in cls_syms
                     if s.get("baseline_status") == "identical"
                     and s.get("is_exported")]
        # identical symbols of any kind except true function templates (??$)
        id_targets = [s["mangled"] for s in identical
                      if not s["mangled"].startswith("??$")]
        id_match = [m for m in id_targets if m in got]

        # all real exports of this class
        cls_real = {m for m in real if f"@{cls}@DirectUI@@" in m}
        cls_real_match = cls_real & got

        n_id, n_idm = len(id_targets), len(id_match)
        total_id += n_id
        total_id_match += n_idm
        status = "OK" if n_idm == n_id else "FAIL"
        if n_idm != n_id:
            all_ok = False
        report.append(
            f"## {cls}: identical-export match {n_idm}/{n_id} [{status}]"
            f" | real-class-exports reproduced {len(cls_real_match)}/{len(cls_real)}"
        )
        if n_idm != n_id:
            report.append("### missing identical symbols:")
            for m in sorted(set(id_targets) - got):
                report.append(f"  - {m}")

    pct = 100.0 * total_id_match / total_id if total_id else 0.0
    summary = (
        f"TOTAL identical-export match: {total_id_match}/{total_id} "
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
