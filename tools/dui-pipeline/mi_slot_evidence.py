"""Per-slot mangled evidence table for the 13 MI pattern providers.

For each provider: every primary-vftable slot of the PROBE object with
its FULL mangled symbol, the DLL's symbol set at the pinned slot RVA,
and the verdict (EXACT singleton hit / FOLD-UNKNOWN / placeholder).
Run after slot_abi_audit passes: python tools/dui-pipeline/mi_slot_evidence.py
"""
import json
import pathlib
import re
import struct
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "dui-pipeline"))
CL = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
DUMPBIN = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe"
VCINC = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include"
SDKROOT = r"C:\Program Files (x86)\Windows Kits\10\Include"

PROVIDERS = ["ExpandCollapseProvider", "GridItemProvider", "GridProvider",
             "InvokeProvider", "RangeValueProvider", "ScrollItemProvider",
             "ScrollProvider", "SelectionItemProvider", "SelectionProvider",
             "TableItemProvider", "TableProvider", "ToggleProvider",
             "ValueProvider"]


def main() -> int:
    sdk = sorted((p for p in pathlib.Path(SDKROOT).iterdir()
                  if (p / "um" / "UIAutomationCore.h").is_file()))[-1]
    inc = REPO / "DirectUI" / "include"
    mi = json.loads((REPO / "pinned" / "mi-tables.json").read_text(encoding="utf-8"))["derived"]
    symd = json.loads((REPO / "pinned" / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    rva_map = {}
    for s in symd:
        r = s.get("rva")
        if r:
            rva_map.setdefault(int(r, 16), []).append(s["mangled"])
    dll = REPO / ".local" / "build" / "ci-probe" / "annot-trap" / "dll_alone" / "dui70.dll"
    blob = dll.read_bytes()
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    coff = e_lfanew + 4
    nsec = struct.unpack_from("<H", blob, coff + 2)[0]
    optsz = struct.unpack_from("<H", blob, coff + 16)[0]
    opt = coff + 20
    image_base = struct.unpack_from("<Q", blob, opt + 24)[0]
    secs = []
    for _i in range(nsec):
        _o = opt + optsz + _i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", blob, _o + 8)
        secs.append((vaddr, vsize, raddr, rsize))

    def rva2off(rva):
        for va, vs, ra, rs in secs:
            if va <= rva < va + vs:
                return ra + (rva - va)
        return None

    import tempfile
    W = pathlib.Path(tempfile.mkdtemp(prefix="mi-slot-ev-"))
    n_exact = n_fold = n_ph = 0
    total = 0
    fails = 0
    for cls in PROVIDERS:
        txt = (inc / f"{cls}.h").read_text(encoding="utf-8")
        PHRE = re.compile(r"virtual void (__DuiAbiSlot_(\w+)_(\d+))\(void\) = 0;")
        phs = [(int(m.group(3)), m.group(1)) for m in PHRE.finditer(txt)]
        lines = [f'#include "{cls}.h"', "namespace DirectUI {"]
        lines.append(f"    struct __Probe{cls} : {cls} {{")
        for _, pn in phs:
            lines.append(f"        void {pn}(void);")
        lines.append(f"        ~__Probe{cls}(void);")
        lines.append("    };")
        for _, pn in phs:
            lines.append(f"    void __Probe{cls}::{pn}(void) {{}}")
        lines.append(f"    __Probe{cls}::~__Probe{cls}(void) {{}}")
        lines.append(f"    __Probe{cls} __g_probe_{cls};")
        lines.append("}")
        cpp = W / f"probe_{cls}.cpp"
        cpp.write_text("\n".join(lines), encoding="utf-8")
        r = subprocess.run([CL, "/nologo", "/std:c++20", "/EHsc", "/Od",
                            "/Zc:wchar_t-", "/c",
                            "/I", str(inc), "/I", VCINC,
                            "/I", str(sdk / "um"), "/I", str(sdk / "shared"),
                            "/I", str(sdk / "ucrt"),
                            "/Fo" + str(W / f"probe_{cls}.obj"), str(cpp)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"## {cls}: PROBE COMPILE FAIL")
            fails += 1
            continue
        r2 = subprocess.run([DUMPBIN, "/nologo", "/relocations",
                             str(W / f"probe_{cls}.obj")],
                            capture_output=True, text=True)
        sec = None
        entries = []
        for L in r2.stdout.splitlines():
            m_sec = re.match(r"RELOCATIONS #(\d+)", L)
            if m_sec:
                sec = int(m_sec.group(1))
                continue
            if "ADDR64" not in L:
                continue
            m = re.match(r"\s*([0-9A-F]+)\s+ADDR64\s+\S+\s+\S+\s+(?:(\w+)\s+)?(.*)$", L)
            if not m:
                continue
            sym = (m.group(3) or "").strip()
            cut = sym.find(" (")
            if cut > 0:
                sym = sym[:cut].strip()
            if sym.startswith("?") or "_purecall" in sym:
                entries.append((sec, int(m.group(1), 16), sym))
        by_sec = {}
        for s, off, sym in entries:
            by_sec.setdefault(s, []).append((off, sym))
        primary = None
        for s, rows in sorted(by_sec.items()):
            rows.sort()
            if rows and rows[0][1].startswith("??_R4") and \
                    rows[0][1].endswith("@DirectUI@@6B@"):
                primary = [sym for _, sym in rows[1:]]
                break
        if primary is None:
            print(f"## {cls}: PRIMARY TABLE NOT FOUND")
            fails += 1
            continue
        truth = mi[cls]["primary"]["slots"]
        rva = int(mi[cls]["primary"]["rva"], 16)
        off = rva2off(rva)
        print(f"## {cls}: {len(primary)} primary slots "
              f"(DLL rva {mi[cls]['primary']['rva']})")
        if len(primary) != len(truth):
            print(f"   SLOT COUNT MISMATCH: probe {len(primary)} vs DLL {len(truth)}")
            fails += 1
            continue
        for i, sym in enumerate(primary):
            total += 1
            va = struct.unpack_from("<Q", blob, off + 8 * i)[0]
            exp = rva_map.get(va - image_base)
            want = truth[i]
            if isinstance(want, list):
                verdict = "FOLD-UNKNOWN" if sym in (exp or []) else "FAIL"
                n_fold += 1
            elif exp and len(exp) > 1:
                # singleton truth slot whose DLL RVA is inside an ICF
                # fold: membership proves a fold member sits there;
                # WHICH member is not provable
                verdict = "FOLD-UNKNOWN" if sym in (exp or []) else "FAIL"
                n_fold += 1
            else:
                verdict = "EXACT" if exp == [sym] else "FAIL"
                if verdict == "EXACT":
                    n_exact += 1
            if verdict == "FAIL":
                fails += 1
            name = re.match(r"\?(\w+)@", sym)
            nm = name.group(1) if name else sym[:20]
            print(f"   [{i}] {nm:32} {verdict:12} {sym}")
            if exp and len(exp) > 1:
                print(f"        DLL fold set: {len(exp)} symbols")
    print()
    print(f"TOTAL: {total} slots checked: {n_exact} EXACT, "
          f"{n_fold} FOLD-UNKNOWN, {total - n_exact - n_fold} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

