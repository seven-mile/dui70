#!/usr/bin/env python3
"""Emit a full MSVC module-definition (.def) file from the real dui70.dll export table.

This is the "spine" of the pipeline: a .def with every real export lets lib.exe
synthesise a complete import library with NO C++ source at all, which guarantees
UITest can link. Headers/stub sources (phase two) then only need to be *correct*,
not *complete*, for the link to succeed.

Key subtlety — decorated-name aliases (Form B):
    The real DLL exports some entry points as PLAIN C names (e.g. InitProcessPriv),
    while C++ callers reference the DECORATED name (e.g. ?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z).
    A .def line of the form
        ?InitProcessPriv@DirectUI@@YAJHPEAGD_N@Z = InitProcessPriv
    makes lib.exe emit an import member that satisfies the decorated reference at
    link time AND resolves to the plain name at load time. The baseline stub DLL
    achieves the same via its own .def aliases; we go straight to the real DLL.

Usage:
    python emit_def.py [--exports <exports.json|real-x64-norm.txt>] [--out <file.def>] [--lib <name>]
                       [--alias <mangled=plain>]...

Default input is .local/cache/real-x64-norm.txt (one decorated name per line).
Also accepts .local/build/exports.json (schema in INTERFACE.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TXT = REPO / ".local" / "cache" / "real-x64-norm.txt"
DEFAULT_JSON = REPO / ".local" / "build" / "exports.json"
DEFAULT_OUT = REPO / ".local" / "build" / "dui70-full.def"


def load_export_names(path: Path) -> list[str]:
    """Return unique decorated export names, preserving dumpbin order."""
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("exports", data if isinstance(data, list) else [])
        names = []
        for e in entries:
            if isinstance(e, str):
                names.append(e)
            elif isinstance(e, dict):
                m = e.get("mangled") or e.get("name")
                if m:
                    names.append(m)
    else:
        names = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # tolerate "name = @ILT+123(...)" forwarders and "name = mangled (comment)"
            line = line.split(" = ", 1)[0].strip()
            if line:
                names.append(line)

    # de-duplicate, preserve first-seen order
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def write_def(names: list[str], out: Path, library: str = "dui70",
              aliases: list[tuple[str, str]] | None = None) -> None:
    """names: plain export lines; aliases: (decorated, plain) Form-B pairs."""
    lines = [f"LIBRARY {library}", "EXPORTS"]
    plain_set = set(names)
    for d, p in (aliases or []):
        if p not in plain_set:
            print(f"warning: alias target '{p}' is not a real export; skipped", file=sys.stderr)
            continue
        # Form B: the entry name IS the decorated reference callers use;
        # the value is the plain name actually exported by the real DLL.
        lines.append(f"    {d} = {p}")
        # do not ALSO emit the plain name — the alias line already covers the
        # runtime import; emitting both would duplicate ordinals.
        plain_set.discard(p)
    lines.extend(f"    {n}" for n in names if n in plain_set)
    out.parent.mkdir(parents=True, exist_ok=True)
    # .def must be ANSI/ASCII for lib.exe; decorated names are pure ASCII.
    out.write_text("\n".join(lines) + "\n", encoding="ascii", errors="strict")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = DEFAULT_JSON if DEFAULT_JSON.exists() else DEFAULT_TXT
    ap.add_argument("--exports", type=Path, default=src)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--lib", default="dui70", help="LIBRARY name inside the .def")
    ap.add_argument("--alias", action="append", default=[],
                    metavar="DECORATED=PLAIN",
                    help="Form-B alias: emit 'DECORATED = PLAIN' so C++ callers resolve")
    args = ap.parse_args(argv)

    if not args.exports.exists():
        print(f"error: export source not found: {args.exports}", file=sys.stderr)
        return 2

    names = load_export_names(args.exports)
    if not names:
        print(f"error: no exports parsed from {args.exports}", file=sys.stderr)
        return 2

    aliases = []
    for a in args.alias:
        if "=" not in a:
            print(f"error: bad --alias '{a}' (expected DECORATED=PLAIN)", file=sys.stderr)
            return 2
        d, p = a.split("=", 1)
        aliases.append((d.strip(), p.strip()))

    write_def(names, args.out, args.lib, aliases)

    c_api = sum(1 for n in names if not n.startswith("?"))
    print(f"source      : {args.exports}")
    print(f"exports     : {len(names)}  (mangled={len(names) - c_api}, c_api={c_api})")
    print(f"aliases     : {len(aliases)}  (Form B decorated->plain)")
    print(f"wrote       : {args.out}  ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
