"""Negative control for the manual interface-length ABI input.

pinned/mi-interface-lengths.json is an EXPLICIT human ABI input (G1-
locked), not a derived fact: interface method counts are not derivable
from a single binary when a table's tail is unobservable. This control
proves the input is LOAD-BEARING: re-running extract-mi-tables with a
tampered RefcountBase length (2 -> 3) must change the derived slot
tables of the classes whose RefcountBase tail is manual-only (the
ElementProvider/HWNDElementProvider family gains a phantom 'GetElement'
slot). No change = the input is dead and the "explicit ABI input" claim
is false.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
mut = pathlib.Path(tempfile.mkdtemp(prefix="len-ctl-"))
for f in (REPO / "pinned").iterdir():
    if f.suffix == ".json":
        shutil.copy(f, mut / f.name)
doc = json.loads((mut / "mi-interface-lengths.json").read_text(encoding="utf-8"))
doc["interface_lengths"]["RefcountBase"] = 3
(mut / "mi-interface-lengths.json").write_text(json.dumps(doc), encoding="utf-8")
dll = REPO / ".local" / "build" / "ci-probe" / "annot-trap" / "dll_alone" / "dui70.dll"
if not dll.is_file():
    print("length-input control: SKIP (pinned DLL not cached locally)")
    sys.exit(0)
r = subprocess.run([PY, str(REPO / "tools/dui-pipeline/extract-mi-tables.py"),
                    "--dll", str(dll), "--symbols", str(mut / "symbols.json"),
                    "--lengths", str(mut / "mi-interface-lengths.json"),
                    "--out", str(mut / "mi-tables.json")],
                   capture_output=True, text=True)
if r.returncode != 0:
    print("length-input control: FAIL (extractor rejected tampered input)")
    sys.exit(1)
new = json.loads((mut / "mi-tables.json").read_text(encoding="utf-8"))["derived"]
old = json.loads((REPO / "pinned" / "mi-tables.json").read_text(encoding="utf-8"))["derived"]
changed = [c for c in old
           if ((old[c].get("secondaries") or {}).get("RefcountBase", {}).get("slots")
               != (new.get(c, {}).get("secondaries") or {}).get("RefcountBase", {}).get("slots"))]
print(f"length-input control: {len(changed)} class table(s) changed under "
      f"tampered RefcountBase length: {changed}")
if not changed:
    print("length-input control: FAIL (input is dead -- not load-bearing)")
    sys.exit(1)
print("length-input control: PASS (manual length input is load-bearing)")
sys.exit(0)
