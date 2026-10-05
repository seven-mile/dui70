"""Negative controls for the fail-closed closing batch (I-1..I-4).

Paired controls proving each new guard is LOAD-BEARING. All
mutations live in temp dirs (scratch copies); the repo tree is
never touched.

  C-I1 (A1 preflight): a scratch pinned dir with a missing input,
      and a sha-tampered DLL, must both exit rc 2 (tooling error),
      never rc 0/1 and never a raw traceback.

  C-I2 (R6 audited-subset floor): a scratch include dir with one
      audited class's header deleted must trip the floor (audited
      32 < 33 -> rc 2), while the clean tree stays rc 0 with the
      PARTIAL 33/324 marker printed.

  C-I4 (capi-evidence conflict-only): a scratch DirectUI.h whose
      DuiCreateObject decl drops a parameter (3 -> 2, STRONG
      evidence) must FAIL rc 1; a scratch DirectUI.h whose
      no-evidence void* decl changes shape must NOT fail (UNKNOWN
      stays UNKNOWN).
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
TOOLS = REPO / "tools" / "dui-pipeline"
PINNED = REPO / "pinned"
INCLUDE = REPO / "DirectUI" / "include"
DLL = (REPO / ".local" / "build" / "ci-probe" / "annot-trap" /
       "dll_alone" / "dui70.dll")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def control_i1():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        # a: missing pinned input (copy pinned minus vtable-slots.json)
        pin = root / "pinned"
        pin.mkdir()
        for f in PINNED.iterdir():
            if f.is_file() and f.name != "vtable-slots.json":
                shutil.copy(f, pin / f.name)
        r = run([PY, str(TOOLS / "slot_abi_audit.py"),
                 "--pinned", str(pin), "--include", str(INCLUDE),
                 "--workdir", str(root / "w")])
        if r.returncode == 2 and "missing" in (r.stdout + r.stderr):
            print("control C-I1a: PASS (missing pinned input -> rc 2, "
                  "clean message)")
        else:
            print(f"control C-I1a: FAIL (rc={r.returncode}) "
                  f"{(r.stderr or r.stdout)[-200:]}")
            ok = False
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        # b: sha-tampered DLL (flip one byte)
        bad = root / "dui70-bad.dll"
        blob = bytearray(DLL.read_bytes())
        blob[0x400] ^= 0xFF
        bad.write_bytes(bytes(blob))
        r = run([PY, str(TOOLS / "slot_abi_audit.py"),
                 "--pinned", str(PINNED), "--include", str(INCLUDE),
                 "--workdir", str(root / "w"), "--dll", str(bad)])
        if r.returncode == 2 and "sha mismatch" in (r.stdout + r.stderr):
            print("control C-I1b: PASS (sha-tampered DLL -> rc 2, "
                  "refused)")
        else:
            print(f"control C-I1b: FAIL (rc={r.returncode}) "
                  f"{(r.stderr or r.stdout)[-200:]}")
            ok = False
    return ok


def control_i2():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        # scratch include with one audited class header removed ->
        # audited drops below the floor 33
        inc = root / "include"
        shutil.copytree(INCLUDE, inc)
        # pick a class in the audited set but NOT in the mandatory 17
        # (removing a mandatory one trips mandatory_missing, not the
        # floor -- a different, already-enforced guard)
        mi = json.loads((PINNED / "mi-tables.json").read_text(
            encoding="utf-8"))["derived"]
        mandatory = {"ExpandCollapseProvider", "GridItemProvider",
                     "GridProvider", "InvokeProvider",
                     "RangeValueProvider", "ScrollItemProvider",
                     "ScrollProvider", "SelectionItemProvider",
                     "SelectionProvider", "TableItemProvider",
                     "TableProvider", "ToggleProvider",
                     "ValueProvider", "ElementProvider",
                     "HWNDElementProvider", "ScrollBar", "CCVScrollBar"}
        victim = None
        for cls in sorted(mi):
            e = mi[cls]
            n_tables = len(e.get("secondaries") or {}) + \
                (1 if e.get("primary") else 0)
            if n_tables >= 2 and cls not in mandatory and \
                    (inc / f"{cls}.h").is_file():
                victim = cls
                break
        if victim is None:
            print("control C-I2: INCONCLUSIVE (no non-mandatory "
                  "multi-table class found) -- non-rc0")
            return False
        (inc / f"{victim}.h").unlink()
        r = run([PY, str(TOOLS / "uia_order_verify.py"),
                 "--pinned", str(PINNED), "--include", str(inc),
                 "--workdir", str(root / "w")])
        if r.returncode == 2 and "shrank below floor" in (r.stdout + r.stderr):
            print(f"control C-I2a: PASS (removed {victim}.h -> "
                  "audited 32 < floor 33 -> rc 2, not silent)")
        else:
            print(f"control C-I2a: FAIL (rc={r.returncode}) "
                  f"{(r.stderr or r.stdout)[-200:]}")
            ok = False
    # b: clean tree must PASS and print the PARTIAL marker
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        r = run([PY, str(TOOLS / "uia_order_verify.py"),
                 "--pinned", str(PINNED), "--include", str(INCLUDE),
                 "--workdir", str(root / "w")])
        if r.returncode == 0 and "PARTIAL 33/" in r.stdout and \
                "audited subset: 33/" in r.stdout:
            print("control C-I2b: PASS (clean tree rc 0 with PARTIAL "
                  "33/324 marker printed)")
        else:
            print(f"control C-I2b: FAIL (rc={r.returncode})")
            ok = False
    return ok


def control_i4():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        inc = root / "include"
        shutil.copytree(INCLUDE, inc)
        # a: strong-evidence conflict -- drop a param from
        # DuiCreateObject (3 -> 2)
        hdr = inc / "DirectUI.h"
        txt = hdr.read_text(encoding="utf-8")
        mutated = txt.replace(
            "long WINAPI DuiCreateObject(struct _GUID const& clsid, "
            "struct _GUID const& riid, void** out);",
            "long WINAPI DuiCreateObject(struct _GUID const& clsid, "
            "void** out);")
        if mutated == txt:
            print("control C-I4a: INCONCLUSIVE (decl text not found)")
            return False
        hdr.write_text(mutated, encoding="utf-8")
        r = run([PY, str(TOOLS / "ci_checks.py"), "capi-evidence",
                 "--include", str(inc)])
        if r.returncode == 1 and "DuiCreateObject" in (r.stdout + r.stderr):
            print("control C-I4a: PASS (strong-evidence param-count "
                  "conflict -> rc 1)")
        else:
            print(f"control C-I4a: FAIL (rc={r.returncode})")
            ok = False
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        inc = root / "include"
        shutil.copytree(INCLUDE, inc)
        # b: no-evidence decl shape change must NOT fail (UNKNOWN)
        hdr = inc / "DirectUI.h"
        txt = hdr.read_text(encoding="utf-8")
        mutated = txt.replace(
            "void WINAPI DUIStopPVLAnimation(void* element);",
            "void WINAPI DUIStopPVLAnimation(int element, int extra);")
        if mutated == txt:
            print("control C-I4b: INCONCLUSIVE (decl text not found)")
            return False
        hdr.write_text(mutated, encoding="utf-8")
        r = run([PY, str(TOOLS / "ci_checks.py"), "capi-evidence",
                 "--include", str(inc)])
        if r.returncode == 0:
            print("control C-I4b: PASS (no-evidence decl shape change "
                  "stays UNKNOWN, never fails)")
        else:
            print(f"control C-I4b: FAIL (rc={r.returncode}) "
                  f"{(r.stderr or r.stdout)[-200:]}")
            ok = False
    return ok


def main() -> int:
    if not DLL.is_file():
        print("failclosed controls: NOT EXECUTED (pinned DLL not "
              "cached locally) -- rc 2, not a pass")
        return 2
    ok = True
    for name, fn in (("C-I1", control_i1), ("C-I2", control_i2),
                     ("C-I4", control_i4)):
        if not fn():
            ok = False
    print(f"failclosed controls: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
