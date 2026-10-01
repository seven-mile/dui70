#!/usr/bin/env python3
"""Regenerate DirectUI/ from pinned/ — the golden pipeline entry point.

Runs the three deterministic emit steps in order:

    pinned/exports.json  -> emit_def.py     -> DirectUI/dui70.def
    pinned/symbols.json  -> emit_headers.py -> DirectUI/include/*.h
    pinned/symbols.json  -> emit_stub.py    -> DirectUI/src/*.cpp

Pure Python, no toolchain dependency, deterministic: the same pinned input
always produces byte-identical output. CI golden test:

    python tools/dui-pipeline/regen.py
    git diff --exit-code DirectUI/

Usage:
    python regen.py [--pinned <dir>] [--out <dir>] [--classes A,B,..]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_PINNED = REPO / "pinned"
DEFAULT_OUT = REPO / "DirectUI"


def pin_short_hash(pinned_dir: Path) -> str:
    """First 12 hex chars of the pinned DLL sha256 — embedded in generated banners."""
    manifest = pinned_dir / "manifest.json"
    if not manifest.exists():
        return "unknown-pin"
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
        return m["dll"]["sha256"][:12]
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"warning: manifest unreadable ({exc}); banner pin hash = unknown", file=sys.stderr)
        return "unknown-pin"


def run_step(script: str, extra_args: list[str]) -> None:
    cmd = [sys.executable, str(HERE / script)] + extra_args
    print(f"--- {script} {' '.join(extra_args)}", flush=True)
    proc = subprocess.run(cmd, capture_output=False)
    if proc.returncode != 0:
        raise SystemExit(f"regen: {script} failed with exit {proc.returncode}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--classes", default=None,
                    help="override pinned/classes.json class list (comma-separated; experimental)")
    ap.add_argument("--skip-def", action="store_true")
    ap.add_argument("--skip-headers", action="store_true")
    ap.add_argument("--skip-stub", action="store_true")
    args = ap.parse_args(argv)

    if not args.pinned.exists():
        print(f"error: pinned dir not found: {args.pinned}", file=sys.stderr)
        return 2

    pin = pin_short_hash(args.pinned)
    print(f"pin  : {pin}")
    print(f"out  : {args.out}")

    if not args.skip_def:
        run_step("emit_def.py", ["--pinned", str(args.pinned),
                                 "--out", str(args.out / "dui70.def")])
    if not args.skip_headers:
        hdr_args = ["--pinned", str(args.pinned),
                    "--out", str(args.out / "include")]
        if args.classes:
            hdr_args += ["--classes", args.classes]
        run_step("emit_headers.py", hdr_args)
    if not args.skip_stub:
        stub_args = ["--pinned", str(args.pinned),
                     "--out", str(args.out / "src")]
        if args.classes:
            stub_args += ["--classes", args.classes]
        run_step("emit_stub.py", stub_args)

    print("regen: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
