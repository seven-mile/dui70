#!/usr/bin/env python3
"""Emit the MSVC module-definition (.def) file for dui70 from the pinned export table.

Input is pinned/exports.json (see tools/dui-pipeline/INTERFACE.md).
Output is DirectUI/dui70.def — the golden, git-tracked export manifest. Consumers
build the import library themselves:

    lib.exe /def:DirectUI\\dui70.def /machine:x64 /out:dui70.lib

The .def lists every export with its real name (mangled C++ or plain C), which
makes lib.exe synthesise a complete import library with NO C++ source at all.

Determinism: same pinned input -> byte-identical .def (stable order = ordinal
order from the export table; no timestamps; ASCII only).

Usage:
    python emit_def.py [--pinned <dir>] [--out <file.def>] [--lib <name>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PINNED = REPO / "pinned"
DEFAULT_OUT = REPO / "DirectUI" / "dui70.def"


def load_exports(pinned_dir: Path) -> list[dict]:
    """Load pinned/exports.json. Returns entries in file order."""
    path = pinned_dir / "exports.json"
    if not path.exists():
        raise FileNotFoundError(f"pinned exports not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("exports")
    if not entries:
        raise ValueError("exports.json has no entries")
    return entries


def write_def(entries: list[dict], out: Path, library: str = "dui70") -> None:
    """Emit the .def in ordinal order (stable, deterministic)."""
    lines = [f"LIBRARY {library}", "EXPORTS"]
    for e in sorted(entries, key=lambda x: x["ordinal"]):
        name = e["name"]
        if not name or any(c.isspace() for c in name):
            raise ValueError(f"invalid export name: {name!r}")
        lines.append(f"    {name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    # .def must be ANSI/ASCII for lib.exe; decorated names are pure ASCII.
    out.write_text("\n".join(lines) + "\n", encoding="ascii", errors="strict")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pinned", type=Path, default=DEFAULT_PINNED,
                    help="pinned input dir (default: <repo>/pinned)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output .def (default: <repo>/DirectUI/dui70.def)")
    ap.add_argument("--lib", default="dui70", help="LIBRARY name inside the .def")
    args = ap.parse_args(argv)

    try:
        entries = load_exports(args.pinned)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_def(entries, args.out, args.lib)

    names = [e["name"] for e in entries]
    c_api = sum(1 for n in names if not n.startswith("?"))
    print(f"pinned      : {args.pinned / 'exports.json'}")
    print(f"exports     : {len(names)}  (mangled={len(names) - c_api}, plain={c_api})")
    print(f"wrote       : {args.out}  ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
