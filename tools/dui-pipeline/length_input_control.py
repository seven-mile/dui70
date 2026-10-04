"""Negative controls for the manual interface-length ABI input.

pinned/mi-interface-lengths.json is an EXPLICIT human ABI input (G1-
locked), not a derived fact: interface method counts are not derivable
from a single binary when a table's tail is unobservable. These
controls prove the input is LOAD-BEARING in BOTH directions:

  A (loosening): re-running extract-mi-tables with a loosened manual
     length must NOT fabricate slot content (the in-binary next-
     vftable bounds hold on their own) while the affected tables'
     length_provenance must flip manual -> next-vftable (the input is
     live in the record, not dead).

  B (deny, 2 -> 1): a manual length SHORTER than an in-binary visible
     bound must be REFUSED, not silently truncate: the affected
     tables must come out length_provenance == "manual-conflict"
     (schema 3 fail-closed rule; a manual input may tighten an
     unobservable tail, never deny visible slots).
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
DLL = (REPO / ".local" / "build" / "ci-probe" / "annot-trap" /
       "dll_alone" / "dui70.dll")


def _run_extract(lengths_json: dict, out_dir: pathlib.Path):
    for f in (REPO / "pinned").iterdir():
        if f.suffix == ".json":
            shutil.copy(f, out_dir / f.name)
    (out_dir / "mi-interface-lengths.json").write_text(
        json.dumps(lengths_json), encoding="utf-8")
    r = subprocess.run(
        [PY, str(REPO / "tools/dui-pipeline/extract-mi-tables.py"),
         "--dll", str(DLL), "--symbols", str(out_dir / "symbols.json"),
         "--lengths", str(out_dir / "mi-interface-lengths.json"),
         "--out", str(out_dir / "mi-tables.json")],
        capture_output=True, text=True)
    return r


def main() -> int:
    if not DLL.is_file():
        print("length-input control: SKIP (pinned DLL not cached locally)")
        return 0
    ok = True

    # ---- Control A: loosening must not fabricate slots ----
    # On THIS binary every manual interface length sits at its
    # next-vftable bound (the counts are confirmatory), so loosening a
    # manual value must (a) NOT change any table's slot CONTENT (the
    # derived bounds hold on their own -- this is the anti-fabrication
    # direction) and (b) flip the affected tables' length_provenance
    # from manual to next-vftable (the input is LIVE in the record,
    # not dead). Content change under loosening = fabrication (FAIL);
    # no provenance flip = the input is dead (FAIL).
    mut = pathlib.Path(tempfile.mkdtemp(prefix="len-ctl-a-"))
    doc = json.loads((REPO / "pinned" / "mi-interface-lengths.json")
                     .read_text(encoding="utf-8"))
    doc["class_interface_lengths"]["ElementProvider"]["RefcountBase"] = 6
    r = _run_extract(doc, mut)
    if r.returncode != 0:
        print("length-input control A: FAIL (extractor rejected tampered input)")
        ok = False
    else:
        new = json.loads((mut / "mi-tables.json").read_text(
            encoding="utf-8"))["derived"]
        old = json.loads((REPO / "pinned" / "mi-tables.json").read_text(
            encoding="utf-8"))["derived"]
        ep_old = old["ElementProvider"]["secondaries"]["RefcountBase"]
        ep_new = new["ElementProvider"]["secondaries"]["RefcountBase"]
        content_stable = ep_old["slots"] == ep_new["slots"]
        prov_flipped = (ep_old.get("length_provenance") == "manual"
                        and ep_new.get("length_provenance") == "next-vftable")
        print(f"length-input control A: ElementProvider RB slots "
              f"{'stable' if content_stable else 'CHANGED'} under 5->6, "
              f"provenance {ep_old.get('length_provenance')} -> "
              f"{ep_new.get('length_provenance')}")
        if not content_stable:
            print("length-input control A: FAIL (loosening fabricated "
                  "slot content -- derived bounds are not holding)")
            ok = False
        elif not prov_flipped:
            print("length-input control A: FAIL (input is dead -- not "
                  "recorded in provenance)")
            ok = False
        else:
            print("length-input control A: PASS (bounds hold; input is "
                  "live in the provenance record)")

    # ---- Control B: denying 2 -> 1 must be REFUSED (conflict) ------
    mutb = pathlib.Path(tempfile.mkdtemp(prefix="len-ctl-b-"))
    doc = json.loads((REPO / "pinned" / "mi-interface-lengths.json")
                     .read_text(encoding="utf-8"))
    doc["interface_lengths"]["RefcountBase"] = 1
    r = _run_extract(doc, mutb)
    if r.returncode != 0:
        print("length-input control B: FAIL (extractor crashed on "
              "conflicting input: rc=%d)" % r.returncode)
        ok = False
    else:
        docb = json.loads((mutb / "mi-tables.json").read_text(
            encoding="utf-8"))["derived"]
        conflicts = [
            c for c, e in docb.items()
            for k, t in (e.get("secondaries") or {}).items()
            if t.get("length_provenance") == "manual-conflict"]
        print(f"length-input control B: {len(conflicts)} class/table "
              f"entries refused as manual-conflict under RefcountBase "
              f"2->1 (e.g. {conflicts[:4]})")
        # every conflict entry must keep its VISIBLE slots (no truncation)
        truncated = []
        for c in set(conflicts):
            e_new = docb[c]
            e_old = json.loads((REPO / "pinned" / "mi-tables.json")
                               .read_text(encoding="utf-8"))["derived"].get(c, {})
            for k, t in (e_new.get("secondaries") or {}).items():
                if t.get("length_provenance") == "manual-conflict":
                    old_t = (e_old.get("secondaries") or {}).get(k, {})
                    if len(t["slots"]) < len(old_t.get("slots", [])):
                        truncated.append(f"{c}.{k}")
        if truncated:
            print(f"length-input control B: FAIL (silent truncation: "
                  f"{truncated[:4]})")
            ok = False
        elif not conflicts:
            print("length-input control B: FAIL (deny direction is not "
                  "refused -- fail-closed rule broken)")
            ok = False
        else:
            print("length-input control B: PASS (deny refused, visible "
                  "slots kept, never truncated)")

    print("length-input control: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
