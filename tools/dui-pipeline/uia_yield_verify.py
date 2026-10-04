#!/usr/bin/env python
"""Option D yield verification matrix (R1/R2/R5 + N1-N4).

Runs against the CURRENT working tree's generated headers (DirectUI/include)
and stub TUs (DirectUI/src). All checks are compile-time only; no dynamic
probes. Exit 0 = all green; nonzero = a check failed.

R1  per-member mangled exactness: every ?member@Provider@DirectUI@@UEAA*
    body symbol in the 13 provider stub objs must equal a pinned exported
    mangled symbol.
R2  13/13 primary vftable slot order vs pinned mi-tables.json
    (fold-tolerant: fold slots accept any fold member; fold identity
    stays fold-UNKNOWN and is reported, never masked).
R5  full matrix: CApi shape (DirectUI.h), 13 provider stubs,
    ElementProvider stub, Schema.h / ElementProxy.h self-compile -- all
    under /Zc:wchar_t-.
N*  negative controls (tamper variants in a temp tree):
    N1 yield guard removed -> C2011
    N2 default wchar mode -> ValueProvider C3668
    N3 REQUIRED state -> C1189
    N4 wrong (uppercase) guard -> C2011
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]


def find_toolchain() -> tuple[str, str, str]:
    """Locate (cl.exe path, MSVC include dir, SDK include root).

    Mirrors verify_codegen._find_toolchain: VCToolsInstallDir /
    WindowsSdkDir env vars (set by vcvars64 / the CI runner), then cl.exe
    on PATH, then INCLUDE-derived fallbacks. Hardcoded absolute paths are
    deliberately avoided -- the CI runner's MSVC version differs.
    """
    sdk = os.environ.get("WindowsSdkDir", "").strip('"')
    ver = os.environ.get("WindowsSDKVersion", "").strip('"\\/')
    sdk_root = None
    if sdk and ver and (pathlib.Path(sdk) / "Include" / ver / "ucrt").is_dir():
        sdk_root = str(pathlib.Path(sdk) / "Include" / ver)
    if sdk_root is None:
        for p in os.environ.get("INCLUDE", "").split(";"):
            m = re.search(r"(.+Windows Kits.+Include[\\/][\d.]+)"
                          r"[\\/](ucrt|shared|um|winrt)$", p.strip(), re.I)
            if m and (pathlib.Path(m.group(1)) / "ucrt").is_dir():
                sdk_root = m.group(1)
                break
    if sdk_root is None:
        # local fallback: newest installed SDK with um/UIAutomationCore.h
        root = pathlib.Path(r"C:\Program Files (x86)\Windows Kits\10\Include")
        cands = [d.name for d in root.iterdir()
                 if (d / "um" / "UIAutomationCore.h").is_file()]
        if not cands:
            raise SystemExit("error: Windows SDK include tree not found")
        sdk_root = str(root / sorted(cands)[-1])

    vc_root = os.environ.get("VCToolsInstallDir", "").strip('"')
    if vc_root:
        bin_dir = pathlib.Path(vc_root) / "bin" / "Hostx64" / "x64"
        vcinc = pathlib.Path(vc_root) / "include"
        if (bin_dir / "cl.exe").is_file() and (vcinc / "vcruntime.h").is_file():
            return str(bin_dir / "cl.exe"), str(vcinc), sdk_root
    cl = shutil.which("cl.exe")
    if cl:
        vcbin = pathlib.Path(cl).parent
        for parent in vcbin.parents:
            if parent.name.lower() == "bin":
                guess = parent.parent / "include"
                if (guess / "vcruntime.h").is_file():
                    return cl, str(guess), sdk_root
        for p in os.environ.get("INCLUDE", "").split(";"):
            if p and (pathlib.Path(p) / "vcruntime.h").is_file():
                return cl, p.strip(), sdk_root
    # local fallback: standard VS Community layout (newest MSVC found)
    vs_root = pathlib.Path(
        r"C:\Program Files\Microsoft Visual Studio\2022")
    for edition in ("Community", "Professional", "Enterprise", "BuildTools"):
        tools = vs_root / edition / "VC" / "Tools" / "MSVC"
        if not tools.is_dir():
            continue
        for ver in sorted(tools.iterdir(), reverse=True):
            bin_dir = tools / ver.name / "bin" / "Hostx64" / "x64"
            vcinc = tools / ver.name / "include"
            if (bin_dir / "cl.exe").is_file() and (vcinc / "vcruntime.h").is_file():
                return str(bin_dir / "cl.exe"), str(vcinc), sdk_root
    raise SystemExit(
        "error: MSVC toolchain not found; run from a VS developer prompt "
        "(or after vcvars64.bat), or add cl.exe to PATH."
    )


CL, VCINC, SDK = find_toolchain()
DB = str(pathlib.Path(CL).parent / "dumpbin.exe")

PROVIDERS = ["ExpandCollapseProvider", "GridItemProvider", "GridProvider",
             "InvokeProvider", "RangeValueProvider", "ScrollItemProvider",
             "ScrollProvider", "SelectionItemProvider", "SelectionProvider",
             "TableItemProvider", "TableProvider", "ToggleProvider",
             "ValueProvider"]

fails = []


def find_sdk() -> str:
    """Resolved SDK include root (find_toolchain already located it)."""
    return SDK


def compile_cl(tu: pathlib.Path, obj: pathlib.Path, inc_dirs, flags=(),
               defines=()) -> subprocess.CompletedProcess:
    return subprocess.run(
        [CL, "/nologo", "/std:c++20", "/c", "/Zc:wchar_t-", *flags, *defines,
         *[x for d in inc_dirs for x in ("/I", str(d))],
         "/I", VCINC,
         "/I", SDK + r"\um", "/I", SDK + r"\shared", "/I", SDK + r"\ucrt",
         f"/Fo{obj}", str(tu)],
        capture_output=True, text=True)


def errors_of(r: subprocess.CompletedProcess) -> list:
    return [l for l in (r.stdout + r.stderr).splitlines()
            if "error" in l.lower()]


def defined_class_symbols(obj: pathlib.Path, cls: str) -> set:
    d = subprocess.run([DB, "/nologo", "/all", str(obj)], capture_output=True)
    out = d.stdout.decode("utf-8", errors="replace")
    sec, syms = False, set()
    for line in out.splitlines():
        if "COFF SYMBOL TABLE" in line:
            sec = True
            continue
        if sec and "External" in line and "SECT" in line:
            m = re.search(r"\|\s+(\S+)", line)
            if m:
                s = m.group(1).split("(")[0]
                if (s.startswith("?") and f"@{cls}@DirectUI@@" in s
                        and "$" not in s and not s.startswith("??_R")):
                    syms.add(s)
    return syms


def primary_vftable(obj: pathlib.Path, cls: str) -> list | None:
    d = subprocess.run([DB, "/nologo", "/all", str(obj)], capture_output=True)
    out = d.stdout.decode("utf-8", errors="replace")
    measured = None
    for b in out.split("RELOCATIONS #")[1:]:
        rows = []
        for line in b.splitlines():
            lm = re.match(r"\s*([0-9A-Fa-f]+)\s+ADDR64", line)
            if not lm:
                continue
            sym = None
            for tok in line.split():
                if tok.startswith("??") or (tok.startswith("?") and "@" in tok):
                    sym = tok
                    break
            if sym and f"@{cls}@DirectUI@@" in sym:
                rows.append((int(lm.group(1), 16), sym))
        if len(rows) < 3:
            continue
        rows.sort()
        if all(rows[i + 1][0] - rows[i][0] == 8 for i in range(len(rows) - 1)):
            names = []
            for a, s in rows:
                m = re.match(r"\?(\w+)@", s) or re.match(r"\?\?_E(\w+)@", s)
                names.append(m.group(1) if m else s[:12])
            iface = [n for n in names if n not in ("Init", "GetProxyCreator")
                     and not n.startswith("_E")]
            if len(iface) >= 3 and not measured:
                measured = names
    return measured


def norm(slots):
    return [tuple(sorted(s)) if isinstance(s, list) else s for s in slots]


def fold_tolerant(truth: list, measured: list) -> bool:
    t, m = norm(truth), norm(measured)
    if len(t) != len(m):
        return False
    for a, b in zip(t, m):
        if isinstance(a, tuple):
            if b not in a:
                return False
        elif a != b:
            return False
    return True


INC = REPO / "DirectUI" / "include"
SRC = REPO / "DirectUI" / "src"
WORK = pathlib.Path(tempfile.mkdtemp(prefix="uia-verify-"))
print(f"workdir: {WORK}")
print(f"sdk: {SDK}")
print(f"cl: {CL}")

# ---- load pinned truth ----------------------------------------------------
pinned = {s["mangled"] for s in
          json.loads((REPO / "pinned" / "symbols.json").read_text(encoding="utf-8"))["symbols"]
          if s.get("mangled")}
mi = json.loads((REPO / "pinned" / "mi-tables.json").read_text(encoding="utf-8"))["derived"]

# ---- R5: full compile matrix ---------------------------------------------
print("\n== R5: full compile matrix (wchar-) ==")
r5_ok = True

def r5_compile(name: str, tu_text: str, tree: pathlib.Path) -> bool:
    tu = WORK / f"{name}.cpp"
    tu.write_text(tu_text, encoding="utf-8")
    obj = WORK / f"{name}.obj"
    r = compile_cl(tu, obj, [tree])
    errs = errors_of(r)
    ok = r.returncode == 0
    if not ok:
        r5_ok and print(f"  {name}: FAIL rc={r.returncode} errors={len(errs)}")
        for l in errs[:3]:
            print("     ", l[:130])
    return ok

if r5_compile("r5-capi", '#include "DirectUI.h"\nint main(){return 0;}\n', INC):
    print("  CApi shape (DirectUI.h): OK")
else:
    fails.append("R5 CApi shape")
    r5_ok = False

stub_ok = 0
for p in PROVIDERS:
    src = SRC / f"{p}.cpp"
    if not src.is_file():
        print(f"  stub {p}: MISSING"); fails.append(f"R5 stub {p} missing"); continue
    obj = WORK / f"r5-stub-{p}.obj"
    r = compile_cl(src, obj, [INC])
    if r.returncode == 0:
        stub_ok += 1
    else:
        errs = errors_of(r)
        print(f"  stub {p}: FAIL -- {errs[0][:120] if errs else '?'}")
        fails.append(f"R5 stub {p}")
print(f"  provider stubs: {stub_ok}/13")
if stub_ok != 13:
    fails.append(f"R5 stubs {stub_ok}/13")

for extra in ["ElementProvider.cpp"]:
    src = SRC / extra
    if src.is_file():
        obj = WORK / f"r5-{extra}.obj"
        r = compile_cl(src, obj, [INC])
        print(f"  {extra}: {'OK' if r.returncode == 0 else 'FAIL'}")
        if r.returncode:
            fails.append(f"R5 {extra}")
            for l in errors_of(r)[:3]:
                print("     ", l[:130])

# every generated header whose class references SDK UIA types must
# self-compile (the quarantine moved the SDK includes to the direct
# consumers; a miss is a C2061 compile error). Detected from the
# generated tree: all headers whose text references SDK UIA tokens.
SDK_TOKENS = ("IRawElementProviderSimple", "IRawElementProviderFragment",
              "IRawElementProviderAdviseEvents", "UiaRect",
              "AutomationIdentifierType", "UiaRaiseAutomationEvent",
              "ScrollAmount", "ExpandCollapseState", "ToggleState",
              "RowOrColumnMajor")
sdk_users = []
for h in sorted(INC.glob("*.h")):
    if h.name in ("dui_abi_types.h",):
        continue  # quarantine: no SDK include by design
    text = h.read_text(encoding="utf-8")
    if any(tok in text for tok in SDK_TOKENS):
        sdk_users.append(h.name)
for h in sdk_users:
    if r5_compile(f"r5-self-{h}", f'#include "{h}"\nint main(){{return 0;}}\n', INC):
        pass
    else:
        fails.append(f"R5 SDK-user {h}")
print(f"  SDK UIA consumers self-compile: {len(sdk_users)} headers"
      f" ({', '.join(sdk_users[:6])}{' ...' if len(sdk_users) > 6 else ''})")

for h in ["Schema.h", "ElementProxy.h"]:
    if r5_compile(f"r5-self-{h}", f'#include "{h}"\nint main(){{return 0;}}\n', INC):
        print(f"  {h} self-compile: OK")
    else:
        fails.append(f"R5 self {h}")

# ---- R1: per-member mangled exactness ------------------------------------
print("\n== R1: stub symbols vs pinned exports ==")
r1_ok = True
for p in PROVIDERS:
    obj = WORK / f"r5-stub-{p}.obj"
    if not obj.is_file():
        continue
    stubs = defined_class_symbols(obj, p)
    missing = sorted(s for s in stubs if s not in pinned)
    if missing:
        r1_ok = False
        fails.append(f"R1 {p}: {len(missing)} symbol(s) not pinned")
        for m in missing[:3]:
            print(f"  {p}: NOT PINNED: {m[:100]}")
print("  all 13 stubs' class symbols exact-match pinned" if r1_ok
      else "  R1 FAILED")

# ---- R2: slot order --------------------------------------------------------
print("\n== R2: primary vftable slot order vs mi-tables.json ==")
r2_ok = True
fold_slots = 0
for p in PROVIDERS:
    obj = WORK / f"r5-stub-{p}.obj"
    if not obj.is_file():
        continue
    measured = primary_vftable(obj, p)
    truth = mi[p]["primary"]["slots"]
    if measured is None:
        r2_ok = False
        fails.append(f"R2 {p}: vftable not isolated")
        continue
    fold_slots += sum(1 for s in truth if isinstance(s, list))
    if not fold_tolerant(truth, measured):
        r2_ok = False
        fails.append(f"R2 {p}: order mismatch")
        print(f"  {p}: truth={truth}")
        print(f"        meas ={measured}")
print(f"  13/13 fold-tolerant OK ({fold_slots} fold slots reported as "
      f"fold-UNKNOWN)" if r2_ok else "  R2 FAILED")

# ---- N1-N4: negative controls ---------------------------------------------
print("\n== N1-N4: negative controls ==")

def tamper_tree(mutate) -> pathlib.Path:
    dst = WORK / f"nc{tamper_tree.n}"
    tamper_tree.n += 1
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(INC, dst)
    mutate(dst)
    return dst

tamper_tree.n = 1

# N1: yield guard removed from IInvokeProvider.h
def n1_mut(d: pathlib.Path):
    f = d / "IInvokeProvider.h"
    c = f.read_text(encoding="utf-8")
    c = c.replace("#ifndef __uiautomationcore_h__\n", "").replace(
        "#endif // __uiautomationcore_h__\n", "")
    f.write_text(c, encoding="utf-8")

tree = tamper_tree(n1_mut)
tu = WORK / "nc1.cpp"
tu.write_text('#include "IInvokeProvider.h"\nint main(){return 0;}\n', encoding="utf-8")
r = compile_cl(tu, WORK / "nc1.obj", [tree])
n1 = any("C2011" in l for l in errors_of(r))
print(f"  N1 guard removed -> C2011: {'FAIL(expected)' if n1 else 'PASS(UNEXPECTED!)'}")
if not n1:
    fails.append("N1 did not fail")

# N2: default wchar (no /Zc:wchar_t-) on ValueProvider stub
tu = SRC / "ValueProvider.cpp"
obj = WORK / "nc2.obj"
r = subprocess.run([CL, "/nologo", "/std:c++20", "/c", "/Zc:wchar_t",
                    "/I", str(INC), "/I", VCINC,
                    "/I", SDK + r"\um", "/I", SDK + r"\shared", "/I", SDK + r"\ucrt",
                    f"/Fo{obj}", str(tu)], capture_output=True, text=True)
n2 = any("C3668" in l for l in errors_of(r))
print(f"  N2 default-wchar ValueProvider -> C3668: {'FAIL(expected)' if n2 else 'PASS(UNEXPECTED!)'}")
if not n2:
    fails.append("N2 did not fail")

# N3: REQUIRED state fires C1189
tu = WORK / "nc3.cpp"
tu.write_text('#include "IInvokeProvider.h"\nint main(){return 0;}\n', encoding="utf-8")
r = compile_cl(tu, WORK / "nc3.obj", [INC], defines=("/DDUI_ABI_PROVIDER_ABI_REQUIRED=1",))
n3 = any("C1189" in l for l in errors_of(r))
print(f"  N3 REQUIRED -> C1189: {'FAIL(expected)' if n3 else 'PASS(UNEXPECTED!)'}")
if not n3:
    fails.append("N3 did not fail")

# N4: wrong (uppercase) guard -> guard misses -> C2011
def n4_mut(d: pathlib.Path):
    f = d / "IInvokeProvider.h"
    c = f.read_text(encoding="utf-8")
    c = c.replace("#ifndef __uiautomationcore_h__", "#ifndef __UIAUTOMATIONCORE_H__")
    f.write_text(c, encoding="utf-8")

tree = tamper_tree(n4_mut)
tu = WORK / "nc4.cpp"
tu.write_text('#include "IInvokeProvider.h"\nint main(){return 0;}\n', encoding="utf-8")
r = compile_cl(tu, WORK / "nc4.obj", [tree])
n4 = any("C2011" in l for l in errors_of(r))
print(f"  N4 wrong guard -> C2011 (fail-visible): {'FAIL(expected)' if n4 else 'PASS(UNEXPECTED!)'}")
if not n4:
    fails.append("N4 did not fail")

# ---- verdict ----------------------------------------------------------------
print("\n" + "=" * 60)
if fails:
    print(f"VERIFY: FAIL ({len(fails)} problem(s))")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("VERIFY: ALL GREEN (R1, R2, R5, N1-N4)")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0)
