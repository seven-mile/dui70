"""Negative controls for the tracked DynamicArray contract (P1).

pinned/dynarray-contracts.json is machine-derived end to end (DLL
bytes + symbols.json); repro.py gate R3''' re-derives and
byte-compares it, and the CI G-lite gate compares ChildrenView.h's
constants against it. These controls prove the chain is
LOAD-BEARING in both directions:

  P1a (hand-edit drift): a hand-edited sizeof (24 -> 25) in a copy
     of the committed contract must FAIL the R3''' comparison --
     there is no manual escape hatch; only re-derivation passes.

  P1b (byte tamper): a tampered DLL copy (one Create body's
     allocation-request immediate rewritten) must CHANGE the
     extracted value (the extractor reads real bytes, it does not
     echo the committed file) and therefore also FAIL R3'''
     against the untampered committed contract.

  P1c (law-inconsistency refusal): a tampered DLL copy whose
     inline-gate immediate contradicts the allocation request (so
     8 + max(16, stride*gate) != sizeof) must have that instance
     DROPPED by the extractor (fail-closed), not emitted with a
     guessed or clamped value.

All mutations live in temp dirs; the repo tree is never touched.
"""
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable
DLL = (REPO / ".local" / "build" / "ci-probe" / "annot-trap" /
       "dll_alone" / "dui70.dll")
EXTRACT = REPO / "tools" / "dui-pipeline" / "extract-dynarray-contracts.py"
PINNED = REPO / "pinned"

# DynamicArray<Element*,0>::Create @ 0x32BC4 (pinned symbols.json).
# Body: `lea 0x18(%rdi),%ecx` = 41 8d 4f 18 ~0x26 bytes in. The
# control locates the pattern dynamically (never a hardcoded offset).
CREATE_RVA = 0x32BC4
LEA_PATTERN = bytes([0x41, 0x8D, 0x4F])  # lea disp8(%rdi),%ecx


def _extract(dll: pathlib.Path, symbols: pathlib.Path,
             out: pathlib.Path):
    return subprocess.run(
        [PY, str(EXTRACT), "--dll", str(dll),
         "--symbols", str(symbols), "--out", str(out)],
        capture_output=True, text=True)


def main() -> int:
    if not DLL.is_file():
        print("dynarray-contract control: NOT EXECUTED (pinned DLL "
              "not cached locally) -- rc 2, not a pass")
        return 2
    ok = True

    # ---- Control P1a: hand-edit drift must fail R3''' comparison ----
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        # committed copy with one hand-edited value
        doc = json.loads((PINNED / "dynarray-contracts.json")
                         .read_text(encoding="utf-8"))
        el = doc["derived"]["PEAVElement@DirectUI@@"]
        el["sizeof"] = el["sizeof"] + 1  # 24 -> 25
        edited = root / "edited-contracts.json"
        edited.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        rebuilt = root / "rebuilt.json"
        r = _extract(DLL, PINNED / "symbols.json", rebuilt)
        if r.returncode != 0:
            print("dynarray-contract control P1a: FAIL (extractor "
                  f"rc={r.returncode})")
            ok = False
        else:
            a = rebuilt.read_bytes().replace(b"\r\n", b"\n")
            b = edited.read_bytes().replace(b"\r\n", b"\n")
            if a == b:
                print("dynarray-contract control P1a: FAIL (hand edit "
                      "did NOT diverge from re-derivation)")
                ok = False
            else:
                print("dynarray-contract control P1a: PASS (hand-edited "
                      "sizeof diverges from re-derivation -> R3''' "
                      "must FAIL)")

    # ---- Control P1b: byte tamper must change the extraction ----
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        blob = bytearray(DLL.read_bytes())
        # file offset = RVA-based (sections are file-aligned here the
        # same way the extractor's rva2off computes; reuse that by
        # patching via the extractor's own PE walk):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "exdyn", str(EXTRACT))
        ex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ex)
        secs = ex.parse_pe(bytes(blob))
        off = None
        for va, vs, ra, rs in secs:
            if va <= CREATE_RVA < va + max(vs, rs):
                off = ra + (CREATE_RVA - va)
                break
        if off is None:
            print("dynarray-contract control P1b: INCONCLUSIVE "
                  "(Create RVA not in a section) -- non-rc0")
            ok = False
        else:
            # find the lea disp8(rdi),ecx pattern dynamically
            body = bytes(blob[off:off + 96])
            pat = body.find(LEA_PATTERN)
            if pat < 0:
                print("dynarray-contract control P1b: INCONCLUSIVE "
                      "(lea pattern not found in Create body) -- non-rc0")
                ok = False
            else:
                imm_at = off + pat + 3
                imm = blob[imm_at]
                blob[imm_at] = imm + 1  # 0x18 -> 0x19 (25)
                tampered = root / "dui70-tampered.dll"
                tampered.write_bytes(bytes(blob))
                out = root / "tampered.json"
                r = _extract(tampered, PINNED / "symbols.json", out)
                if r.returncode != 0:
                    print("dynarray-contract control P1b: FAIL (extractor "
                          f"refused the tampered DLL rc={r.returncode})")
                    ok = False
                else:
                    tdoc = json.loads(out.read_text(encoding="utf-8"))
                    tel = tdoc["derived"].get("PEAVElement@DirectUI@@")
                    cdoc = json.loads((PINNED / "dynarray-contracts.json")
                                      .read_text(encoding="utf-8"))
                    cel = cdoc["derived"]["PEAVElement@DirectUI@@"]
                    # 25 != 8 + max(16, 8*2) = 24: the law check drops
                    # it; if somehow kept, sizeof must differ
                    if tel is None:
                        print("dynarray-contract control P1b: PASS "
                              "(tampered imm breaks the law -> instance "
                              "dropped fail-closed; value did not echo)")
                    elif tel["sizeof"] != cel["sizeof"]:
                        print("dynarray-contract control P1b: PASS "
                              "(tampered byte changed the extracted sizeof "
                              f"{cel['sizeof']} -> {tel['sizeof']}; extractor "
                              "reads real bytes)")
                    else:
                        print("dynarray-contract control P1b: FAIL "
                              "(tampered byte changed NOTHING -- extractor "
                              "echoes the committed file?)")
                        ok = False

    # ---- Control P1c: law-inconsistent instance must be dropped ----
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        blob = bytearray(DLL.read_bytes())
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "exdyn2", str(EXTRACT))
        ex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ex)
        secs = ex.parse_pe(bytes(blob))
        off = None
        for va, vs, ra, rs in secs:
            if va <= CREATE_RVA < va + max(vs, rs):
                off = ra + (CREATE_RVA - va)
                break
        # find the inline-gate cmp imm8 (83 /7) with imm in [1,8]
        # inside the Create body and rewrite it to contradict the law
        gate_at = None
        for i in range(off, off + 320):
            if blob[i] == 0x83 and (blob[i + 1] >> 3) & 7 == 7:
                imm = blob[i + 2]
                if 1 <= imm <= 8:
                    gate_at = i
                    break
        if off is None or gate_at is None:
            print("dynarray-contract control P1c: INCONCLUSIVE "
                  "(inline gate not found in Create body) -- non-rc0")
            ok = False
        else:
            # cap 2 -> 4 would give 8+max(16,32)=40 != 24: law break
            blob[gate_at + 2] = 4
            tampered = root / "dui70-lawbreak.dll"
            tampered.write_bytes(bytes(blob))
            out = root / "lawbreak.json"
            r = _extract(tampered, PINNED / "symbols.json", out)
            if r.returncode != 0:
                print("dynarray-contract control P1c: FAIL (extractor "
                      f"rc={r.returncode})")
                ok = False
            else:
                tdoc = json.loads(out.read_text(encoding="utf-8"))
                tel = tdoc["derived"].get("PEAVElement@DirectUI@@")
                if tel is None:
                    print("dynarray-contract control P1c: PASS "
                          "(law-inconsistent instance DROPPED "
                          "fail-closed, never emitted with a guess)")
                else:
                    print("dynarray-contract control P1c: FAIL "
                          f"(law-inconsistent instance emitted: {tel})")
                    ok = False

    print(f"dynarray-contract controls: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
