#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_codegen.py -- stub-TU modname fidelity self-check.

Builds every generated stub TU with cl.exe (/std:c++20 /Zc:wchar_t- /c /EHsc),
extracts the decorated names via dumpbin /symbols, and diffs them against
the real dui70.dll export set (pinned/exports.json).

Per contract the target set is: every EXPORTED symbol of the target classes.

Also asserts extern "C" purity: no obj may contain a C++-decorated name
for the plain C API exports.

Toolchain discovery (first hit wins):
  * --vcbin / --sdk command-line overrides
  * VCToolsInstallDir / WindowsSdkDir environment variables (as set by
    vcvars64.bat or a VS Developer prompt)
  * cl.exe / dumpbin.exe on PATH

Requires Visual Studio 2022 (or newer) with MSVC v143 and the Windows 10
SDK (ucrt/shared/um/winrt include trees).

Module-level self-check; the pipeline-level end-to-end check (verify.py)
re-validates independently.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _find_toolchain(vcbin_arg: str | None, sdk_arg: str | None) -> tuple[Path, Path, Path]:
    """Locate (cl-dir, MSVC-include-dir, SDK-include-root)."""
    sdkinc = Path(sdk_arg) if sdk_arg else _find_sdk_root()

    if vcbin_arg:
        vcbin = Path(vcbin_arg)
        if not (vcbin / "cl.exe").is_file():
            raise SystemExit(f"error: cl.exe not found in --vcbin {vcbin}")
        return vcbin, _msvc_include_for_bin(vcbin), sdkinc

    # VCToolsInstallDir (set by vcvars64.bat / VS developer prompt) points at
    # .../VC/Tools/MSVC/<ver>/ and carries a trailing backslash.
    vc_root = os.environ.get("VCToolsInstallDir", "").strip('"')
    if vc_root:
        bin_dir = Path(vc_root) / "bin" / "Hostx64" / "x64"
        vcinc = Path(vc_root) / "include"
        if (bin_dir / "cl.exe").is_file() and (vcinc / "vcruntime.h").is_file():
            return bin_dir, vcinc, sdkinc

    # cl.exe on PATH; include dirs from the INCLUDE env var (a developer
    # prompt sets both).
    cl = shutil.which("cl.exe")
    if cl:
        vcbin = Path(cl).parent
        return vcbin, _msvc_include_for_bin(vcbin), sdkinc

    raise SystemExit(
        "error: MSVC toolchain not found. Pass --vcbin <dir with cl.exe>, "
        "run from a VS developer prompt (or after vcvars64.bat), or add "
        "cl.exe to PATH."
    )


def _msvc_include_for_bin(vcbin: Path) -> Path:
    """MSVC include dir for a cl.exe at .../VC/Tools/MSVC/<ver>/bin/Hostx64/x64
    (or .../bin/x64); falls back to the INCLUDE env var entry holding
    vcruntime.h when the layout differs."""
    guess = None
    for parent in vcbin.parents:
        if parent.name.lower() == "bin":
            guess = parent.parent / "include"
            break
    if guess and (guess / "vcruntime.h").is_file():
        return guess
    for p in os.environ.get("INCLUDE", "").split(";"):
        if p and (Path(p) / "vcruntime.h").is_file():
            return Path(p)
    raise SystemExit(
        f"error: MSVC include dir not derivable from {vcbin}; pass --vcbin "
        "pointing at a standard VS layout or run from a developer prompt."
    )


def _find_sdk_root() -> Path:
    """Windows SDK include root: WindowsSdkDir + WindowsSDKVersion (developer
    prompt), or the common ancestor of the Windows Kits entries on INCLUDE."""
    sdk = os.environ.get("WindowsSdkDir", "").strip('"')
    ver = os.environ.get("WindowsSDKVersion", "").strip('"\\/')
    if sdk and ver:
        root = Path(sdk) / "Include" / ver
        if (root / "ucrt").is_dir():
            return root
    for p in os.environ.get("INCLUDE", "").split(";"):
        # a Windows Kits include entry looks like .../Include/<ver>/um
        m = re.search(r"(.+Windows Kits.+Include[\\/][\d.]+)[\\/](ucrt|shared|um|winrt)$", p.strip(), re.I)
        if m:
            root = Path(m.group(1))
            if (root / "ucrt").is_dir():
                return root
    raise SystemExit(
        "error: Windows SDK include tree not found. Pass --sdk <SDK Include "
        "root> (the directory containing ucrt/ shared/ um/ winrt/), or run "
        "from a VS developer prompt."
    )


DEFAULT_PINNED = REPO / "pinned"
DEFAULT_SRC = REPO / "DirectUI" / "src"
DEFAULT_INC = REPO / "DirectUI" / "include"
DEFAULT_OBJ = REPO / ".local" / "build" / "verify-obj"


class Toolchain:
    """Resolved compiler layout: cl/dumpbin binaries + include roots."""

    def __init__(self, vcbin: Path, vcinc: Path, sdkinc: Path):
        self.cl = vcbin / "cl.exe"
        self.dumpbin = vcbin / "dumpbin.exe"
        self.vcinc = vcinc
        self.sdkinc = sdkinc
        for b in (self.cl, self.dumpbin):
            if not b.is_file():
                raise SystemExit(f"error: required tool missing: {b}")


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, **kw)


def compile_tu(tc: Toolchain, src: Path, obj_dir: Path, inc: Path) -> tuple[int, str]:
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj = obj_dir / (src.stem + ".obj")
    cmd = [
        tc.cl, "/nologo", "/c", "/std:c++20", "/Zc:wchar_t-", "/EHsc", "/W0",
        f"/I{tc.vcinc}", f"/I{tc.sdkinc / 'ucrt'}", f"/I{tc.sdkinc / 'shared'}",
        f"/I{tc.sdkinc / 'um'}", f"/I{tc.sdkinc / 'winrt'}", f"/I{inc}",
        f"/Fo{obj}", str(src),
    ]
    proc = run(cmd)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def obj_symbols(tc: Toolchain, obj: Path) -> set[str]:
    proc = run([tc.dumpbin, "/nologo", "/symbols", str(obj)])
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
    ap.add_argument("--vcbin", default=None,
                    help="directory containing cl.exe + dumpbin.exe (default: "
                         "VCToolsInstallDir env, then PATH)")
    ap.add_argument("--sdk", default=None,
                    help="Windows SDK Include root containing ucrt/ shared/ um/ "
                         "winrt/ (default: WindowsSdkDir env)")
    args = ap.parse_args(argv)

    tc = Toolchain(*_find_toolchain(args.vcbin, args.sdk))

    # class list from pinned/classes.json
    classes = json.loads((args.pinned / "classes.json").read_text(encoding="utf-8"))["classes"]
    if args.classes:
        classes = [c.strip() for c in args.classes.split(",") if c.strip()]

    # real export set from pinned/exports.json (name field)
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
        rc, out = compile_tu(tc, src, args.objdir, args.inc)
        if rc != 0:
            report.append(f"## {cls}: COMPILE FAILED (rc={rc})")
            report.append("```")
            report.append(out[:4000])
            report.append("```")
            all_ok = False
            continue
        got = obj_symbols(tc, args.objdir / f"{cls}.obj")

        # target set: ALL real exports of this class (contract semantics)
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
        for nm in obj_symbols(tc, obj):
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
