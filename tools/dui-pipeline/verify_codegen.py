#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_codegen.py -- stub-TU modname fidelity self-check.

Builds every generated stub TU with cl.exe (/std:c++20 /Zc:wchar_t- /c /EHsc),
extracts the decorated names via dumpbin /symbols, and diffs them against
the real dui70.dll export set.

Per contract the target set is: every EXPORTED symbol of the target classes
(from pinned/symbols.json is_exported, in DirectUI scope). Template
specialization classes ('PatternProvider<...>', 'FunctionDefinition<int>')
are matched via their exact mangled names from the symbol table, not by
string-patching the class name.

Routing:
  * FunctionDefinition<T> and ACCESSIBLEROLE are nested in a host class;
    their exports are verified against the HOST class's TU
    (DUIXmlParser.cpp / AccessibleButton.cpp).
  * 'default ctor closure' (??_F...) exports cannot be written in C++;
    classes carrying them have a companion <class>_ctor_closure.asm which
    is assembled with ml64 and merged into the symbol set.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from emit_headers import (  # noqa: E402
    in_directui_scope,
    is_duixml_nested,
    is_nested_pseudo_class,
    nested_host_of,
    safe_name,
)


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
    """Resolved compiler layout: cl/dumpbin/ml64 binaries + include roots."""

    def __init__(self, vcbin: Path, vcinc: Path, sdkinc: Path):
        self.cl = vcbin / "cl.exe"
        self.dumpbin = vcbin / "dumpbin.exe"
        self.ml64 = vcbin / "ml64.exe"
        self.vcinc = vcinc
        self.sdkinc = sdkinc
        for b in (self.cl, self.dumpbin):
            if not b.is_file():
                raise SystemExit(f"error: required tool missing: {b}")


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, **kw)


# Provider ABI compile flags. /Zc:wchar_t- is LOAD-BEARING: the SDK UIA
# interfaces' wchar_t params (IValueProvider::SetValue/get_Value) mangle
# PEBG/PEAPEAG -- identical to the pinned dui70.dll exports -- ONLY in
# this mode (default wchar_t diverges: PEB_W). compile_tu asserts the
# flag's presence so a refactor cannot silently drop it (fail-closed,
# per Option D PR requirements).
PROVIDER_ABI_FLAGS = ("/std:c++20", "/Zc:wchar_t-", "/EHsc", "/W0")


def compile_tu(tc: Toolchain, src: Path, obj_dir: Path, inc: Path) -> tuple[int, str]:
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj = obj_dir / (src.stem + ".obj")
    assert "/Zc:wchar_t-" in PROVIDER_ABI_FLAGS, \
        "provider ABI compile flags lost /Zc:wchar_t- (Option D invariant)"
    cmd = [
        tc.cl, "/nologo", "/c", *PROVIDER_ABI_FLAGS,
        f"/I{tc.vcinc}", f"/I{tc.sdkinc / 'ucrt'}", f"/I{tc.sdkinc / 'shared'}",
        f"/I{tc.sdkinc / 'um'}", f"/I{tc.sdkinc / 'winrt'}", f"/I{inc}",
        f"/Fo{obj}", str(src),
    ]
    proc = run(cmd)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def assemble_asm(tc: Toolchain, asm: Path, obj_dir: Path) -> tuple[int, str]:
    """ml64 companion assembly for ??_F ctor-closure symbols."""
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj = obj_dir / (asm.stem + ".obj")
    cmd = [tc.ml64, "/nologo", "/c", f"/Fo{obj}", str(asm)]
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


def class_target_set(symbols: list, cls: str) -> set[str]:
    """All real-export mangled names attributed to a class (DirectUI scope).
    Uses the symbol table directly so template specialization classes match
    exactly (their '@<class>@DirectUI@@" text form never appears in the
    mangled name)."""
    return {s["mangled"] for s in symbols
            if s.get("class") == cls
            and s.get("is_exported")
            and in_directui_scope(s)}


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

    symbols = json.loads((args.pinned / "symbols.json").read_text(encoding="utf-8"))["symbols"]

    report = []
    total_match = total = 0
    all_ok = True
    tu_done: dict[str, set[str]] = {}   # tu-stem -> merged symbol set

    def tu_symbols(stem: str) -> set[str]:
        """Compile (once) the TU for stem plus its companion .asm files,
        return the merged External symbol set."""
        if stem in tu_done:
            return tu_done[stem]
        src = args.src / f"{stem}.cpp"
        if not src.exists():
            tu_done[stem] = set()
            return tu_done[stem]
        rc, out = compile_tu(tc, src, args.objdir, args.inc)
        if rc != 0:
            report.append(f"## {stem}: COMPILE FAILED (rc={rc})")
            report.append("```")
            report.append(out[:4000])
            report.append("```")
            all_ok = False
            tu_done[stem] = set()
            return tu_done[stem]
        got = obj_symbols(tc, args.objdir / f"{stem}.obj")
        for suffix in ("_ctor_closure", "_own_vftable"):
            asm = args.src / f"{stem}{suffix}.asm"
            if asm.exists():
                arc, aout = assemble_asm(tc, asm, args.objdir)
                if arc != 0:
                    report.append(f"## {stem}: ASM FAILED (rc={arc})")
                    report.append("```")
                    report.append(aout[:2000])
                    report.append("```")
                    all_ok = False
                else:
                    got |= obj_symbols(tc, args.objdir / f"{stem}{suffix}.obj")
        tu_done[stem] = got
        return got

    for cls in classes:
        # which TU carries this class's exports?
        if is_duixml_nested(cls) or is_nested_pseudo_class(cls):
            stem = safe_name(nested_host_of(cls) if is_nested_pseudo_class(cls)
                             else "DUIXmlParser")
        else:
            stem = safe_name(cls)
        got = tu_symbols(stem)
        if not got and not (args.src / f"{stem}.cpp").exists():
            report.append(f"## {cls}: MISSING TU {args.src / (stem + '.cpp')}")
            all_ok = False
            continue

        cls_real = class_target_set(symbols, cls)
        cls_match = cls_real & got

        n, nm = len(cls_real), len(cls_match)
        total += n
        total_match += nm
        status = "OK" if nm == n else "FAIL"
        if nm != n:
            all_ok = False
        report.append(
            f"## {cls}: real-export match {nm}/{n} [{status}]"
            + (f" (TU {stem})" if stem != safe_name(cls) else "")
        )
        if nm != n:
            report.append("### missing real exports:")
            for m in sorted(cls_real - got):
                report.append(f"  - {m}")

    # the extern "C" API TU (plain-name exports) -- always compiled so the
    # purity/completeness check below sees its symbol set
    capi_syms = tu_symbols("CApi")

    pct = 100.0 * total_match / total if total else 0.0
    summary = (
        f"TOTAL real-export match: {total_match}/{total} "
        f"({pct:.2f}%)  {'**100% ACHIEVED**' if pct == 100 else '**NOT 100%**'}"
    )

    # extern "C" purity + completeness: the 86 plain-name C exports must be
    # (a) never emitted as C++-decorated namespace-level functions, and
    # (b) ALL present as plain definitions across the stub TUs (CApi.cpp).
    # Note: a plain C name (e.g. InitThread) can coexist with a same-named
    # CLASS MEMBER (FontCache::InitThread) in the real DLL — those are
    # distinct exports. Only decorated names resolving to namespace-level
    # functions (DirectUI::InitThread) violate the rule.
    export_names = {e["name"] for e in json.loads(
        (args.pinned / "exports.json").read_text(encoding="utf-8"))["exports"]
        if not e["name"].startswith("?")}
    capi_bad = []
    capi_plain = set()
    for stem, got in tu_done.items():
        for nm in got:
            if nm.startswith("?") and any(
                    re.match(r"\?" + re.escape(n) + r"@", nm) for n in export_names):
                # violation only in namespace-level form (?Name@DirectUI@@YA...);
                # same-named class members (?InitThread@FontCache@...) are
                # distinct legitimate exports.
                if re.match(r"\?(?:" + "|".join(map(re.escape, export_names)) + r")"
                            r"@DirectUI@@YA", nm):
                    capi_bad.append(f"{stem}: {nm}")
            elif nm in export_names:
                capi_plain.add(nm)
    capi_missing = export_names - capi_plain
    if capi_missing:
        all_ok = False
        report.append(f"## extern-C completeness: FAIL ({len(capi_missing)} plain-name "
                      f"exports not defined by any stub TU)")
        for m in sorted(capi_missing):
            report.append(f"  - {m}")
    if capi_bad:
        all_ok = False
        report.append(f"## extern-C purity: FAIL ({len(capi_bad)} decorated)")
        for b in capi_bad:
            report.append(f"  - {b}")
    if not capi_bad and not capi_missing:
        report.append(f"## extern-C purity: OK (no decorated C-API symbols; "
                      f"all {len(export_names)} plain-name exports defined)")
    text = "\n".join([summary, ""] + report) + "\n"
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8", newline="\n")
        print(f"report written to {args.report}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
