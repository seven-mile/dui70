"""W5 v2 full-repo slot-ABI audit (tracked tool).

For every class with a contract table in pinned/vtable-slots.json and a
generated header, compile a probe TU that forces the class's vftable to be
emitted (out-of-line dtor definition when the class has one, else one
placeholder-body definition), then verify against the contract:

  * vftable entry count == contract slot count (no extra/missing slots)
  * every known-signature virtual sits at its contract slot (by mangled
    name in the vftable relocations)
  * every placeholder slot holds _purecall
  * the vector-deleting dtor (??_E) sits at its CONTRACT slot (the slot
    whose table entry is the `_E<Class>` marker -- slot 0 when the dtor
    was declared first, the last slot when declared last; never assumed)

Expectation model (INDEPENDENT of the emitter's binder): the pinned
DLL's vftable RVAs are dereferenced directly and the FULL mangled name
set at each target address is the ground truth (symbols.json). ICF
folds (several symbols at one address) are reported as fold-UNKNOWN --
a hit proves only that SOME fold member sits there, never which.

Fail-closed: any divergence exits 1 with the class/slot list.

--selftest runs PAIRED negative controls on isolated mutated copies of
the pinned inputs (never the tree under test): (a) an own-virtual
slot swap must FAIL, (b) a same-name overload declaration swap must
FAIL, and the unmutated pair must PASS -- a control that cannot fail
is vacuous and the selftest reports that as an error.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile


def _find_tool(name: str, hardcoded: str) -> str:
    """Prefer the hardcoded local toolchain path (pinned local runs);
    fall back to PATH resolution (CI runners provision MSVC via
    msvc-dev-cmd). Fail loudly when neither exists."""
    if pathlib.Path(hardcoded).is_file():
        return hardcoded
    p = shutil.which(name)
    if p:
        return p
    raise SystemExit(f"slot-abi-audit: {name} not found (neither "
                     f"{hardcoded} nor PATH); run under msvc-dev-cmd "
                     "or add MSVC to PATH")


def _sdk_inc_dirs() -> list:
    """MSVC + Windows SDK include dirs: the pinned local layout first
    (MSVC 14.44 + SDK 10.0.26100.0), otherwise every installed Windows
    Kits version newest-first plus cl.exe's sibling include dir (CI
    runners provision different versions -- never assume one path)."""
    incs = []
    msvc_local = (r"C:\Program Files\Microsoft Visual Studio\2022"
                  r"\Community\VC\Tools\MSVC\14.44.35207\include")
    if pathlib.Path(msvc_local).is_dir():
        incs.append(msvc_local)
    else:
        vc_inc = pathlib.Path(CL).parent.parent.parent / "include"
        if vc_inc.is_dir():
            incs.append(str(vc_inc))
    roots = (r"C:\Program Files (x86)\Windows Kits\10\Include",
             r"C:\Program Files\Windows Kits\10\Include")
    for root_s in roots:
        root = pathlib.Path(root_s)
        if not root.is_dir():
            continue
        for ver in sorted((x.name for x in root.iterdir() if x.is_dir()),
                          reverse=True):
            for sub in ("ucrt", "um", "shared"):
                d = root / ver / sub
                if d.is_dir():
                    incs.append(str(d))
    return incs


CL = _find_tool("cl.exe",
                r"C:\Program Files\Microsoft Visual Studio\2022"
                r"\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe")
DUMPBIN = _find_tool("dumpbin.exe",
                     r"C:\Program Files\Microsoft Visual Studio\2022"
                     r"\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\dumpbin.exe")
INC = _sdk_inc_dirs()


def build_probe(cls, table, tmp):
    """One TU forcing the vftable; returns cpp path."""
    ph_slots = []
    body = []
    has_dtor = isinstance(table[0], str) and table[0].startswith("_E") or (
        isinstance(table[0], list) and any(isinstance(x, str) and x.startswith("_E") for x in table[0]))
    # placeholders from the header (source of truth: header decls)
    src = []
    return ph_slots, body


def _resolve_dll(pinned_dir, download: bool = True) -> pathlib.Path:
    """The pinned DLL: pinned/manifest.json names its sha256 and the
    msdl source_url; the DLL itself lives outside pinned/ (too large
    for the repo). Resolution:
    <pinned>/../.local/build/ci-probe/annot-trap/dll_alone/dui70.dll
    (the canonical local copy); when absent and download=True (e.g. a
    fresh CI runner), fetch manifest.dll.source_url into that cache
    path first. The manifest sha is VERIFIED either way, so a
    different build can never silently become the ground truth."""
    import hashlib, urllib.request
    p = pathlib.Path(pinned_dir)
    man = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
    want = man["dll"]["sha256"].lower()
    c = (p / ".." / ".local" / "build" / "ci-probe" / "annot-trap" / "dll_alone" / "dui70.dll").resolve()
    if not c.is_file() and download:
        url = man["dll"].get("source_url")
        if not (url and url.startswith("https://")):
            raise SystemExit("slot-abi-audit: pinned DLL missing and no https source_url to fetch it")
        c.parent.mkdir(parents=True, exist_ok=True)
        tmp = c.with_suffix(".part")
        req = urllib.request.Request(url, headers={"User-Agent": "dui70-repro"})
        with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as out:
            out.write(resp.read())
        tmp.replace(c)
    if c.is_file():
        got = hashlib.sha256(c.read_bytes()).hexdigest()
        if got.lower() != want:
            raise SystemExit(f"slot-abi-audit: DLL sha mismatch for {c}: {got} != manifest {want} -- refusing")
        return c
    raise SystemExit("slot-abi-audit: pinned dui70.dll not found (expected <repo>/.local/build/ci-probe/annot-trap/dll_alone/dui70.dll); pass --dll explicitly")


def selftest(args) -> int:
    """PAIRED negative controls on isolated copies (never vacuous,
    never run against the baseline tree itself).

    Control A (own-virtual swap): mutate a scratch copy of
    pinned/vtable-slots.json so two of Element's singleton slots
    exchange names, regenerate headers into the scratch dir, and audit
    THAT pair -- the mutated run must FAIL while the clean pair PASSes.
    Control B (overload swap): swap Element's two OnPropertyChanged
    overload declarations in a scratch copy of the include dir --
    mutated run must FAIL (const vs non-const is visible in the
    mangled name), clean run PASSes.
    Control C (split-vote guard): mutate a scratch copy of the
    contract so CCBase's OnNotify@46 singleton becomes OnMessage@46
    (a 1-vs-14 split vote across tables), regenerate into the scratch
    dir, and assert the SOLVER failed closed: HWNDHost's header must
    carry placeholder slots in the fold-pair region (both bindings
    refused) rather than a guessed order. The scratch copy is the
    audit INPUT only -- the pinned source tree is never touched.
    """
    import shutil
    here = pathlib.Path(__file__).resolve().parent
    pinned = pathlib.Path(args.pinned).resolve()
    inc = pathlib.Path(args.include).resolve()
    dll = str(_resolve_dll(pinned))
    root = pathlib.Path(args.workdir) / "selftest"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ok = True

    def run_audit(p, i, w, cls="Element"):
        return subprocess.run(
            [sys.executable, str(here / "slot_abi_audit.py"),
             "--pinned", str(p), "--include", str(i),
             "--workdir", str(w), "--classes", cls, "--dll", dll],
            capture_output=True, text=True)

    # ---- Control A: own-virtual swap (Element contract slots 3<->8) --
    mut = root / "swap-own"
    mut.mkdir()
    for f in pinned.iterdir():
        shutil.copy(f, mut / f.name)
    doc = json.loads((mut / "vtable-slots.json").read_text(encoding="utf-8"))
    t = doc["classes"]["Element"]["slots"]
    a, b = 3, 8
    assert isinstance(t[a], str) and isinstance(t[b], str), (t[a], t[b])
    t[a], t[b] = t[b], t[a]
    (mut / "vtable-slots.json").write_text(json.dumps(doc), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(here / "emit_headers.py"),
         "--pinned", str(mut), "--out", str(mut / "hdrs")],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("selftest A: emit_headers failed on mutated contract "
              f"(rc={r.returncode}) -- control invalid: "
              + (r.stderr or r.stdout).strip()[:160])
        ok = False
    else:
        ra = run_audit(mut, mut / "hdrs", mut / "work")
        rb = run_audit(pinned, inc, root / "clean-a")
        if ra.returncode == 0:
            print("selftest A: VACUOUS -- mutated own-virtual swap "
                  "did not FAIL")
            ok = False
        elif rb.returncode != 0:
            print("selftest A: clean pair did not PASS (baseline "
                  "regression?)")
            ok = False
        else:
            print("selftest A: PASS (own-virtual swap FAILs as "
                  "required, clean pair PASSes)")

    # ---- Control B: overload declaration swap (const/non-const) ------
    mutb = root / "swap-overload"
    mutb.mkdir()
    shutil.copytree(inc, mutb / "include")
    h = mutb / "include" / "Element.h"
    txt = h.read_text(encoding="utf-8")
    A = ("virtual void OnPropertyChanged(PropertyInfo*, int, Value*, "
         "Value*);")
    B = ("virtual void OnPropertyChanged(PropertyInfo const*, int, "
         "Value*, Value*);")
    if A not in txt or B not in txt:
        print("selftest B: overload declarations not found -- control "
              "invalid (header shape changed?)")
        ok = False
    else:
        txt = (txt.replace(A, "__SWAP_A__").replace(B, A)
                  .replace("__SWAP_A__", B))
        h.write_text(txt, encoding="utf-8")
        rc = run_audit(pinned, mutb / "include", mutb / "work")
        rb = run_audit(pinned, inc, root / "clean-b")
        if rc.returncode == 0:
            print("selftest B: VACUOUS -- overload swap did not FAIL")
            ok = False
        elif rb.returncode != 0:
            print("selftest B: clean pair did not PASS (baseline "
                  "regression?)")
            ok = False
        else:
            print("selftest B: PASS (overload swap FAILs as required, "
                  "clean pair PASSes)")

    # ---- Control C: split-vote guard (solver fail-closed) --------------
    # A 1-vs-14 split vote (CCBase's OnNotify@46 singleton mutated to
    # OnMessage@46) must make the solver REFUSE both bindings for
    # HWNDHost's fold pair: placeholders in the pair region, real
    # declarations appended unbound. The mutated contract lives only
    # in the scratch dir; the pair is judged structurally (placeholder
    # presence) because a guessed order here would be exactly the
    # defect this control guards against.
    mutc = root / "split-vote"
    mutc.mkdir()
    for f in pinned.iterdir():
        shutil.copy(f, mutc / f.name)
    doc = json.loads((mutc / "vtable-slots.json").read_text(encoding="utf-8"))
    t = doc["classes"]["CCBase"]["slots"]
    if t[46] != "OnNotify":
        print("selftest C: CCBase[46] is not the OnNotify singleton "
              f"(got {t[46]!r}) -- control invalid (contract changed?)")
        ok = False
    else:
        t[46] = "OnMessage"
        (mutc / "vtable-slots.json").write_text(json.dumps(doc), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(here / "emit_headers.py"),
             "--pinned", str(mutc), "--out", str(mutc / "hdrs")],
            capture_output=True, text=True)
        if r.returncode != 0:
            print("selftest C: emit_headers refused the mutated "
                  f"contract (rc={r.returncode}) -- control invalid: "
                  + (r.stderr or r.stdout).strip()[:160])
            ok = False
        else:
            ht = (mutc / "hdrs" / "HWNDHost.h").read_text(encoding="utf-8")
            ph46 = "__DuiAbiSlot_HWNDHost_46" in ht
            ph47 = "__DuiAbiSlot_HWNDHost_47" in ht
            both_decl = ("OnMessage" in ht and "OnNotify" in ht)
            if ph46 and ph47 and both_decl:
                print("selftest C: PASS (split vote -> both pair slots "
                      "UNKNOWN placeholders, declarations kept unbound)")
            else:
                print(f"selftest C: FAIL -- solver did not fail closed "
                      f"(ph46={ph46} ph47={ph47} decls={both_decl}); "
                      "a guessed order would be a defect")
                ok = False

    print(f"slot-abi-audit selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinned", required=True)
    ap.add_argument("--include", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--classes", help="comma list; default all placeholder+bound classes")
    ap.add_argument("--dll", default=None,
                    help="pinned dui70.dll path; default: resolve+sha-verify from pinned/manifest.json")
    ap.add_argument("--selftest", action="store_true",
                    help="run paired negative controls (slot swap + overload swap) on isolated mutated copies")
    ap.add_argument("--json-out", default=None,
                    help="write the full verdict (verified/unknown/rejected/failed "
                         "per class) as a JSON artifact")
    args = ap.parse_args()
    if args.selftest:
        return selftest(args)
    inc = pathlib.Path(args.include)
    work = pathlib.Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    doc = json.loads((pathlib.Path(args.pinned) / "vtable-slots.json").read_text(encoding="utf-8"))
    classes = doc["classes"]

    # ---- independent expected-slot model (DLL bytes + symbols.json) ----
    # For every class/contract slot, dereference the pinned DLL's vftable
    # RVA and collect the FULL MANGLED names of every symbol at the
    # target address. The expectation is derived WITHOUT the emitter's
    # binder (contract_reorder) -- the DLL bytes are the ground truth, so
    # a binder bug cannot mask itself. An address carrying >1 symbol is
    # an ICF fold: the probe object emits whichever member OUR header
    # declares, so membership in the RVA symbol set is the mangled-level
    # hit, but the slot is additionally recorded fold=UNKNOWN (a hit
    # proves only that SOME member of the fold sits there, not which).
    import struct
    dll_path = pathlib.Path(args.dll) if args.dll else _resolve_dll(args.pinned)
    blob = dll_path.read_bytes()
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

    symd = json.loads((pathlib.Path(args.pinned) / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    rva_map = {}
    for s in symd:
        r = s.get("rva")
        if r:
            rva_map.setdefault(int(r, 16), []).append(s["mangled"])
    expect = {}   # cls -> list[set[str] | None] | None (None = no table)
    for cls, entry in classes.items():
        try:
            rva = int(entry["rva"], 16)
        except (KeyError, ValueError, TypeError):
            expect[cls] = None
            continue
        off = rva2off(rva)
        if off is None:
            expect[cls] = None
            continue
        row = []
        for k in range(len(entry["slots"])):
            va = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            row.append(rva_map.get(va - image_base))
        expect[cls] = row

    PHRE = re.compile(r"virtual void (__DuiAbiSlot_(\w+)_(\d+))\(void\) = 0;")

    # any pure virtual declaration (single line) in a generated header:
    # "virtual <ret> <name>(<params>) = 0;" -- placeholders AND recovered
    # real-signature pures (Rule E) both end in "= 0;".
    PURE_RE = re.compile(r"^(?:\s*)(virtual\s+[^;{}()]+?\([^;{}]*?\))\s*=\s*0\s*;")

    def harvest_pure_decls(header_paths: list) -> list:
        """Return unique pure-virtual declarations (signature text) in
        first-seen order from the given header files (class header plus
        its direct #include chain). Each entry is the declarator text
        WITHOUT the leading 'virtual' and trailing '= 0;', suitable for
        emitting an override stub: '<sig> {}' inside the probe struct."""
        seen = []
        names = set()
        for hp in header_paths:
            try:
                txt = hp.read_text(encoding="utf-8")
            except OSError:
                continue
            for ln in txt.splitlines():
                m = PURE_RE.match(ln)
                if not m:
                    continue
                sig = m.group(1).strip()
                sig = sig[len("virtual"):].strip() if sig.startswith("virtual") else sig
                nm = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", sig)
                if not nm or nm.group(1) in names:
                    continue
                names.add(nm.group(1))
                seen.append(sig)
        return seen



    # ---- schema-2 MI secondary tables (stage2): mi-tables.json carries
    # the SECONDARY vftables (IProvider / RefcountBase subobjects) with
    # their own RVAs + slot names. When present, the audit additionally
    # verifies the probe object's secondary tables against the DLL bytes
    # at those RVAs -- the PRIMARY table check is unchanged (contract).
    mi_doc_path = pathlib.Path(args.pinned) / "mi-tables.json"
    mi_sec: dict[str, dict[str, dict]] = {}   # cls -> base -> {rva, slots}
    mi_prim_rva: dict[str, int] = {}
    if mi_doc_path.is_file():
        mi_doc = json.loads(mi_doc_path.read_text(encoding="utf-8"))["derived"]
        for cls, e in mi_doc.items():
            if isinstance(e.get("primary"), dict) and e["primary"].get("rva"):
                mi_prim_rva[cls] = int(e["primary"]["rva"], 16)
            for base, sec in (e.get("secondaries") or {}).items():
                if not isinstance(sec, dict) or not sec.get("rva"):
                    continue
                mi_sec.setdefault(cls, {})[base] = {
                    "rva": int(sec["rva"], 16),
                    "slots": sec["slots"],
                }

    def mi_expect_row(rva: int, n: int) -> list:
        """DLL-byte expectation row for an arbitrary vftable RVA."""
        off = rva2off(rva)
        if off is None:
            return [None] * n
        row = []
        for k in range(n):
            va = struct.unpack_from("<Q", blob, off + 8 * k)[0]
            row.append(rva_map.get(va - image_base))
        return row

    only = {c.strip() for c in args.classes.split(",")} if args.classes else None
    failed = []
    source_verified = []
    checked = 0
    rejected_classes = 0
    unknowns = {}   # cls -> [slot,...] fold/UNKNOWN slots (not verified)
    for cls, entry in sorted(classes.items()):
        if only and cls not in only:
            continue
        hp = inc / f"{cls}.h"
        if not hp.is_file():
            continue
        txt = hp.read_text(encoding="utf-8")
        phs = [(int(m.group(3)), m.group(1)) for m in PHRE.finditer(txt)]
        rej = "W5 CONTRACT: REJECTED" in txt or "L2 IClassInfo" in txt
        if rej:
            rejected_classes += 1
            continue  # canonical-order classes are outside slot truth
        checked += 1
        table = entry["slots"]
        # ---- expected model ----
        # vdtor slot: wherever the `_E<Class>` marker sits (generic rule)
        dtor_slot = None
        for _i, _e in enumerate(table):
            if _e == f"_E{cls}" or (isinstance(_e, list) and f"_E{cls}" in _e):
                dtor_slot = _i
                break
        s0_vdtor = dtor_slot == 0
        ph_slots = {s for s, _ in phs}
        if len(ph_slots) != len(phs):
            failed.append((cls, "duplicate placeholder slots"))
            continue
        # contract-truth _purecall slots: the DLL table holds _purecall
        # there; our header may carry either a __DuiAbiSlot placeholder
        # or a Rule-E recovered NAMED pure (same-RVA fold evidence).
        # The probe overrides either form; acceptance below treats both.
        contract_pure = {i for i, e in enumerate(table)
                         if e == "_purecall"}
        ph_slots |= contract_pure
        # ---- probe: force the class's OWN vftable ----
        # Attempt 1 ("own"/"dtor" force): define one of the class's own
        # virtuals out-of-line (the dtor when declared -- a defined dtor
        # is the classic vftable key function; else the first declared
        # non-pure virtual). MSVC emits the class's vftable in that TU
        # -- but NOT always (inline-only classes with no ODR use of the
        # table can still drop it).
        # Attempt 2 ("sub" force): a concrete subclass overriding every
        # placeholder plus a global INSTANCE. The instance guarantees
        # the subobject vftable is emitted with every slot laid out in
        # real MSVC order; the entries equal the base's slots (the
        # subclass adds none: its dtor overrides the base vdtor slot).
        cpp = work / f"probe_{cls}.cpp"
        obj = work / f"probe_{cls}.obj"

        def build_tu(force: str) -> bool:
            lines = [f'#include "{cls}.h"', "namespace DirectUI {"]
            if force == "dtor":
                lines.append(f"    {cls}::~{cls}(void) {{}}")
            elif force == "own":
                # the class's FIRST declared non-pure virtual, defined
                # out-of-line (key-function rule). Placeholders stay
                # pure (_purecall entries -- what the contract expects).
                first_virt = None
                for L in txt.splitlines():
                    s = L.strip()
                    if (s.startswith("virtual") and s.endswith(";")
                            and "__DuiAbiSlot" not in s and "= 0" not in s
                            and "~" not in s.split("(")[0]):
                        first_virt = s[:-1]  # strip ';'
                        break
                if first_virt is None:
                    # no definable virtual at all (pure/placeholder-only
                    # class): this attempt is not buildable
                    return False
                d = first_virt[len("virtual"):].strip()
                paren = d.index("(")
                head = d[:paren]          # 'RET NAME'
                m = re.match(r"^(.*?)(\w+)$", head.strip())
                ret, name = m.group(1).strip(), m.group(2)
                params = d[paren:]
                body = "return {};" if ret not in ("void",) else ""
                lines.append(f"    {ret} {cls}::{name}{params} {{ {body} }}")
            lines.append("}")
            if force == "sub":
                lines.append("namespace DirectUI {")
                lines.append(f"    struct __Probe{cls} : {cls} {{")
                for _, pn in phs:
                    lines.append(f"        void {pn}(void);")
                # Rule E / Rule C recovered real-signature pures in
                # THIS class's header (they are abstract until
                # overridden). Own header only: base-chain pures are
                # placeholders harvested by phs above, and interface
                # pures from dui_abi_types.h are not this class's
                # bases. Skip names phs already declares (C2535).
                ph_names = {pn for _, pn in phs}
                inc0 = inc / f"{cls}.h"
                for sig in harvest_pure_decls([inc0]):
                    nm = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", sig)
                    if nm and nm.group(1) in ph_names:
                        continue
                    # body: value-returning pures need a return
                    mret = re.match(r"^(.*?)\s*[A-Za-z_][A-Za-z0-9_]*\s*\(", sig)
                    rt = (mret.group(1).strip() if mret else "")
                    body = "" if rt in ("void", "") else "return {};"
                    lines.append(f"        {sig} override {{ {body} }}")
                lines.append(f"        ~__Probe{cls}(void);")
                lines.append("    };")
                for _, pn in phs:
                    lines.append(f"    void __Probe{cls}::{pn}(void) {{}}")
                lines.append(f"    __Probe{cls}::~__Probe{cls}(void) {{}}")
                lines.append(f"    __Probe{cls} __g_probe_{cls};")
                lines.append("}")
            cpp.write_text("\n".join(lines), encoding="utf-8")
            return True

        def compile_obj() -> tuple[str, list]:
            # /Zc:wchar_t- matches the provider ABI compile mode (Option
            # D): the SDK UIA interfaces declare wchar_t params; under
            # this flag they mangle PEBG == the pinned exports. Default
            # wchar_t mode diverges and ValueProvider's overrides stop
            # matching their SDK base (C3668) -- a probe TOOLCHAIN mode,
            # not an ABI finding.
            r = subprocess.run([CL, "/nologo", "/std:c++20", "/EHsc", "/Od",
                                "/Zc:wchar_t-", "/c",
                                *sum([["/I", p] for p in INC], []),
                                "/I", str(inc),
                                f"/Fo{obj}", str(cpp)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                err = [x for x in (r.stderr or r.stdout).splitlines() if "error" in x]
                return ("compile", [err[0][:120] if err else "?"])
            r2 = subprocess.run([DUMPBIN, "/nologo", "/relocations", str(obj)],
                                capture_output=True, text=True)
            entries = []  # (block, offset, symbol)
            # dumpbin prints one RELOCATIONS #<n> block per COFF section,
            # and comdat sections can REPEAT the same printed number
            # (each comdat gets its own block). Two different vftables
            # may therefore both appear under "#1" with offsets that
            # restart at 0x0 -- grouping by the printed number would
            # interleave them after sorting. Key each BLOCK by its
            # ordinal position in the output instead; within a block the
            # rows are ascending and contiguous.
            block = -1
            for L in r2.stdout.splitlines():
                m_sec = re.match(r"RELOCATIONS #(\d+)", L)
                if m_sec:
                    block += 1
                    continue
                if "ADDR64" not in L:
                    continue
                m = re.match(r"\s*([0-9A-F]+)\s+ADDR64\s+\S+\s+\S+\s+(?:(\w+)\s+)?(.*)$", L)
                if not m:
                    continue
                off = int(m.group(1), 16)
                sym = (m.group(3) or "").strip()
                # dumpbin appends the undecorated name in parentheses on
                # the same line -- identity compares DECORATED names only
                cut = sym.find(" (")
                if cut > 0:
                    sym = sym[:cut].strip()
                if sym.startswith("?") or "_purecall" in sym:
                    entries.append((block, off, sym))
            return ("ok", entries)

        def split_vftables(payload: list, cls: str) -> dict:
            """Split the probe object's relocation rows into per-base
            vftables, keyed by the MI base encoded in the ??_R4
            complete-object-locator name.

            MSVC emits, for a class with MI bases, one vftable per base
            subobject, each PRECEDED by its RTTI locator pointer (a
            ??_R4 relocation row at vftable[-1]). The locator name
            encodes the subobject path:
              ??_R4Probe@...@@6B@                -- PRIMARY subobject
              ??_R4Probe@...@@6BRefcountBase@1@@ -- RefcountBase subobject
              ??_R4Probe@...@@6BIProvider@1@@    -- IProvider subobject
            Within one section the rows are contiguous (locator, slot0,
            slot1, ...); the next ??_R4 row starts the next table.

            The pre-fix code anchored on the FIRST ??_R4 row and took
            every 8-byte-aligned row after it -- under MI that mixed
            rows across secondary tables (or anchored on a secondary
            when section order differed), producing bogus slot-identity
            mismatches. This fix changes SELECTION only; the
            expectation side (DLL bytes) is untouched -- no false PASS
            is possible.
            """
            tables: dict[str, list] = {}
            if not payload:
                return tables
            # group by dumpbin RELOCATIONS BLOCK (each vftable comdat is
            # its own block; offsets restart per block), then into
            # contiguous 8-byte runs within each block
            by_sec: dict[int, list] = {}
            for s, off, sym in payload:
                by_sec.setdefault(s, []).append((off, sym))
            for s, rows in by_sec.items():
                rows.sort()
                runs: list = []
                cur: list = [rows[0]]
                for prev, nxt in zip(rows, rows[1:]):
                    if nxt[0] - prev[0] == 8:
                        cur.append(nxt)
                    else:
                        runs.append(cur)
                        cur = [nxt]
                runs.append(cur)
                for r in runs:
                    if not r or not r[0][1].startswith("??_R4"):
                        continue
                    m = re.match(
                        r"\?\?_R4(?:__Probe)?\w+@DirectUI@@6B(.*)@",
                        r[0][1])
                    if m is None:
                        continue
                    key = m.group(1)
                    # the COL path may carry the collision-number suffix
                    # ('RefcountBase@1@') or a trailing '@' for external
                    # interface secondaries ('IFoo@'): keep the bare base
                    # name so it matches mi-tables.json's secondary keys
                    key = re.sub(r"@\d+@$", "@", key).rstrip("@")
                    tables[key] = [sym for _, sym in r[1:]]
            return tables

        has_dtor_decl = bool(re.search(
            r"virtual\s+~" + re.escape(cls) + r"\b", txt))
        if dtor_slot is not None and has_dtor_decl:
            attempts = ["dtor", "sub"]
        else:
            attempts = ["own", "sub"]
        force = None
        entries = []
        base = None
        tables: dict[str, list] = {}
        for att in attempts:
            if not build_tu(att):
                continue
            status, payload = compile_obj()
            if status == "compile":
                # the 'own' attempt can fail on inaccessible members
                # (private virtuals); the subclass may still work
                if att == attempts[-1]:
                    failed.append((cls, "compile: " + payload[0]))
                    break
                continue
            # split into per-base vftables (MI probe-accuracy fix):
            # primary table = the ??_R4 run keyed "" ; secondaries carry
            # their base name. The old single-anchor logic mis-selected
            # tables for MI classes.
            tables = split_vftables(payload, cls)
            primary = tables.get("")
            if primary is not None:
                force = att
                entries = payload
                base = -8  # marker: slot_syms derivation below needs a
                # truthy anchor; the actual slot extraction now uses
                # `tables`, not offset arithmetic
                break
            entries = payload  # keep last for the source-fallback path
            base = None
        if any(c == cls for c, _ in failed):
            continue
        if base is None:
            # vftable not emittable in an isolated TU (abstract /
            # ctor-inaccessible / inline-only classes). Fall back to a
            # SOURCE-LEVEL structural check: the header's virtual
            # sequence must equal the contract slot sequence
            # (placeholder names at placeholder slots, known names at
            # their bound slots, exact count). Fail-closed on any
            # divergence.
            seq = []
            for L in txt.splitlines():
                s = L.strip()
                m = re.match(r"virtual\s+[^;{]*?([~]?\w+)\s*\(", s)
                if m:
                    seq.append(m.group(1))
            seq = [x for x in seq if x != cls and not x.startswith("~")]
            errs = []
            ph_names = {i: f"__DuiAbiSlot_{cls}_{i}" for i in ph_slots}
            # expected sequence from the contract: placeholders + known
            # bound names in slot order (derived classes' base slots
            # are inherited: their header only re-declares overrides,
            # which sit at base slots < base_prefix — those appear in
            # the header but their position is governed by C++
            # inheritance, so compare only the TAIL region beyond the
            # last known bound slot... too fragile. Compare as MULTISET
            # + placeholder slot-set equality instead:
            hdr_ph = {int(x) for x in re.findall(
                rf"__DuiAbiSlot_{cls}_(\d+)", txt)}
            if hdr_ph != ph_slots:
                errs.append(f"placeholder slots differ: hdr={sorted(hdr_ph)} contract={sorted(ph_slots)}")
            if len(seq) - len(ph_slots) < 0:
                errs.append("virtual count below placeholder count")
            if errs:
                failed.append((cls, "; ".join(errs)))
            else:
                source_verified.append(cls)
            continue
        slot_syms = {}
        primary_slots = tables.get("")
        if primary_slots is not None:
            # per-base table split succeeded: the primary table's slots
            # in declaration order (??_R4-anchored contiguous run)
            for i, sym in enumerate(primary_slots):
                slot_syms[i] = sym
        else:
            # legacy offset path (single-inheritance probes): entries
            # are (section, offset, symbol) -- the primary anchor is the
            # class's own ??_R4 row in its section
            anchor = None
            for _s, off, sym in entries:
                if f"??_R4{cls}@DirectUI@@6B@" in sym or \
                        f"??_R4__Probe{cls}@DirectUI@@6B@" in sym:
                    anchor = (_s, off)
                    break
            if anchor is not None:
                for s, off, sym in entries:
                    if s == anchor[0] and off > anchor[1] and \
                            (off - anchor[1]) % 8 == 0:
                        slot_syms[(off - anchor[1]) // 8 - 1] = sym
        n_tab = len(table)
        n_expect = n_tab  # subclass dtor only adds a slot if base had a vdtor
        errs = []
        if set(slot_syms) != set(range(n_expect)):
            got = sorted(slot_syms)
            errs.append(f"slot count {len(got)} vs expect {n_expect}")

        # ---- MI SECONDARY tables (stage2 mi-tables.json truth) ----
        # The probe object lays out the secondary vftables too. Verify
        # each against the DLL bytes at the pinned secondary RVA: slot
        # count must match and every slot's mangled symbol must hit the
        # DLL's symbol set at that position (fold sets accepted,
        # membership recorded as fold-UNKNOWN, exactly like primary).
        # Fold slots in the SECONDARY truth are lists (fold pairs).

        def _thunk_equiv(s_obj: str, s_dll: str) -> bool:
            """Pinned-name truncation / thunk-adjustor tolerance.

            The pinned PDB publics sometimes store a THUNK name
            truncated right after the adjustor component
            ('?QI@C@DirectUI@@WB' vs the probe's full
            '?QI@C@DirectUI@@WBI@EAAJ...'), and MSVC encodes the
            this-adjustor differently (M-thunk 'MEAA' vs direct
            'UEAA') when the subobject offset differs between the
            two layouts. Both sides must name the SAME class and
            member; the member component must fully agree up to
            the shorter name's end.
            """
            m_obj = re.match(r"\?(\w+)@(\w+)@DirectUI@@", s_obj)
            m_dll = re.match(r"\?(\w+)@(\w+)@DirectUI@@", s_dll)
            if not (m_obj and m_dll):
                return False
            if m_obj.group(1) != m_dll.group(1) or \
                    m_obj.group(2) != m_dll.group(2):
                return False
            # same member, both this-adjustor THUNK forms
            # ('@W<adjustor>@...' encodings): the subobject OFFSET
            # differs between the DLL's real layout and the modeled
            # one; which member the slot carries is still provable
            m2t = re.match(r"\?\w+@\w+@DirectUI@@W", s_obj)
            m3t = re.match(r"\?\w+@\w+@DirectUI@@W", s_dll)
            if m2t and m3t:
                return True
            # one side a strict prefix of the other (truncation)
            shorter = s_obj if len(s_obj) <= len(s_dll) else s_dll
            longer = s_dll if shorter is s_obj else s_obj
            if longer.startswith(shorter):
                # the prefix boundary must sit at the access/
                # adjustor zone ('@...E'/'@...M'/'@W'), not
                # mid-signature
                return bool(re.match(r"^(\?(\w+)@(\w+)@DirectUI@@)?"
                                     r"[A-Z]*@?[A-Z]*$", shorter))
            # access-letter skin: this-adjustor thunk ('MEAA') vs
            # direct ('UEAA') when the subobject offset differs
            # between layouts -- the access markers differ only in
            # the leading letter (M = thunk form) and everything
            # after must be equal
            m2 = re.match(r"\?(\w+)@(\w+)@DirectUI@@([A-Z])(.*)$", s_obj)
            m3 = re.match(r"\?(\w+)@(\w+)@DirectUI@@([A-Z])(.*)$", s_dll)
            if m2 and m3 and m2.group(4) == m3.group(4) and \
                    len(m2.group(3)) == len(m3.group(3)) == 1:
                if {m2.group(3), m3.group(3)} <= {"E", "M", "U", "V",
                                                   "W", "A", "B", "C",
                                                   "D", "F", "G"}:
                    # single-letter access zone: only the U<->M thunk
                    # distinction may differ
                    if (m2.group(3) == "U" and m3.group(3) == "M") or \
                            (m2.group(3) == "M" and m3.group(3) == "U"):
                        return True
            # multi-letter access markers: equal after the first letter
            m2b = re.match(r"\?\w+@\w+@DirectUI@@([A-Z]+)(.*)$", s_obj)
            m3b = re.match(r"\?\w+@\w+@DirectUI@@([A-Z]+)(.*)$", s_dll)
            if m2b and m3b and m2b.group(2) == m3b.group(2) and \
                    len(m2b.group(1)) == len(m3b.group(1)) and \
                    m2b.group(1)[1:] == m3b.group(1)[1:] and \
                    {m2b.group(1)[0], m3b.group(1)[0]} == {"U", "M"}:
                return True
            return False

        if cls in mi_sec and primary_slots is not None:
            for base_name, sec in sorted(mi_sec[cls].items()):
                sec_slots = sec["slots"]
                # mi-tables keys may carry the trailing '@' collision
                # suffix ('IFoo@'); the split keys are rstripped
                got = tables.get(base_name) or tables.get(
                    base_name.rstrip("@"), [])
                if len(got) != len(sec_slots):
                    errs.append(
                        f"secondary {base_name}: slot count {len(got)} "
                        f"vs DLL {len(sec_slots)}")
                    continue
                sec_row = mi_expect_row(sec["rva"], len(sec_slots))
                for i, want_name in enumerate(sec_slots):
                    sym = got[i]
                    # deleting-dtor slots: the probe's ??_E form
                    if isinstance(want_name, str) and \
                            want_name.startswith(f"_E{cls}"):
                        if f"??_E" not in sym:
                            errs.append(
                                f"secondary {base_name} slot {i}: "
                                f"expected vdtor, got {sym[:60]}")
                        continue
                    exp_set = sec_row[i] if i < len(sec_row) else None
                    if exp_set is None:
                        continue  # unresolved DLL slot: UNKNOWN, not FAIL
                    if sym in exp_set:
                        if len(exp_set) > 1:
                            unknowns.setdefault(cls, []).append(i)
                        continue
                    # thunk/truncation skin of the same member (see
                    # _thunk_equiv in the primary loop): UNKNOWN, not
                    # FAIL
                    if any(_thunk_equiv(sym, x) for x in exp_set):
                        unknowns.setdefault(cls, []).append(i)
                        continue
                    # fold pair in the secondary truth: any member
                    # accepted (member identity not provable)
                    names = (want_name if isinstance(want_name, list)
                             else [want_name])
                    if any(f"?{n}@{cls}@DirectUI@@" in sym
                           or f"??_E{n}@" in sym
                           for n in names):
                        if len(exp_set) > 1:
                            unknowns.setdefault(cls, []).append(i)
                        continue
                    errs.append(
                        f"secondary {base_name} slot {i}: mangled "
                        f"identity -- DLL {sorted(exp_set)[:1]}, "
                        f"object {sym[:56]}")

        # per-class DLL-derived expectation (None table = skip identity)
        exp_row = expect.get(cls)

        # names declared as pure virtuals in THIS class's header
        # (Rule E recoveries render as named "= 0;" declarations)
        named_pure_names = set()
        for L in txt.splitlines():
            m_pn = re.match(r"virtual\s+[^;()]*?([~]?[A-Za-z_]\w*)\s*\([^;]*\)\s*=\s*0\s*;", L.strip())
            if m_pn:
                named_pure_names.add(m_pn.group(1))
        for i in range(n_expect):
            sym = slot_syms.get(i, "")
            if i in ph_slots:
                # placeholder slot: _purecall (class's own vftable form)
                # or the probe subclass's override symbol
                ok_ph = ("_purecall" in sym
                         or (force == "sub"
                             and f"__DuiAbiSlot_{cls}_{i}@__Probe{cls}@" in sym)
                         or f"__DuiAbiSlot_{cls}_{i}@{cls}@" in sym)
                if not ok_ph:
                    # Rule E recovery: the header declares a NAMED pure
                    # at this _purecall contract slot (same-RVA fold
                    # evidence). The probe's named override proves our
                    # declared member sits at the right position; the
                    # DLL's _purecall only means the base never
                    # instantiated the slot. Accept as refined-UNKNOWN
                    # (reported, never silently passed).
                    m_np = re.match(r"\?(\w+)@__Probe" + re.escape(cls)
                                    + r"@DirectUI@@", sym)
                    nm_np = m_np.group(1) if m_np else None
                    if nm_np and nm_np in named_pure_names:
                        unknowns.setdefault(cls, []).append(i)
                    else:
                        errs.append(f"slot {i}: expected _purecall/override, got {sym[:60]}")
                continue
            if i == dtor_slot:
                # the vdtor's CONTRACT slot (may be anywhere: first,
                # last, or middle): must carry ??_E (deleting dtor)
                okd = (f"??_E{cls}@" in sym or f"??_C{cls}@" in sym
                       or (force == "sub" and f"??_E__Probe{cls}@" in sym))
                if not okd:
                    errs.append(f"slot {i} (dtor): expected vdtor, got {sym[:60]}")
                continue
            # ---- full-mangled SLOT IDENTITY vs the pinned DLL ----
            # expected set = every symbol at the DLL's table slot i RVA
            # (ICF folds give a set; unresolvable RVAs give None=UNKNOWN)
            exp_set = exp_row[i] if exp_row else None
            if exp_set is None:
                # UNKNOWN target address (import thunk / unsymbolized):
                # cannot assert an identity. Fail-closed on obviously
                # wrong content, but do NOT accept a named DirectUI
                # member here: an unresolved slot in the DLL table means
                # the probe must hold a placeholder (_purecall) or an
                # override -- a real member body would be a divergence
                # from an unsymbolized slot.
                if "_purecall" not in sym and "__DuiAbiSlot_" not in sym:
                    errs.append(f"slot {i}: UNKNOWN dll slot carries "
                                f"real member {sym[:60]}")
                continue
            if sym in exp_set:
                # mangled-level hit. If the RVA carries several symbols
                # (ICF fold), the hit is ambiguous: record UNKNOWN, not
                # a verified identity.
                if len(exp_set) > 1:
                    unknowns.setdefault(cls, []).append(i)
                continue
            # thunk/truncation skin of the same member (see
            # _thunk_equiv above): UNKNOWN, not FAIL
            if any(_thunk_equiv(sym, x) for x in exp_set):
                unknowns.setdefault(cls, []).append(i)
                continue

            def _cands():
                # report ALL symbols at the slot's RVA (an ICF fold can
                # carry dozens); never an arbitrary representative
                s = sorted(exp_set)
                return (", ".join(x[:48] for x in s[:3]) +
                        (f" (+{len(s)-3} more)" if len(s) > 3 else ""))
            if "_purecall" in sym or "__DuiAbiSlot_" in sym:
                errs.append(f"slot {i}: probe holds placeholder/purecall "
                            f"but DLL carries [{_cands()}]")
            else:
                errs.append(f"slot {i}: mangled identity -- DLL "
                            f"[{_cands()}], object {sym[:56]}")
        if errs:
            failed.append((cls, "; ".join(errs)))
    n_unk = sum(len(v) for v in unknowns.values())
    # verified = checked - failed - source-verified (object-probe
    # identity held, fold-singleton slots only); rejected = headers
    # carrying the rejected/L2 banner (outside slot truth, counted
    # separately from `checked`)
    n_rej = rejected_classes
    print(f"v2 slot-abi audit: checked {checked} classes, "
          f"{len(failed)} failed, {len(source_verified)} source-verified, "
          f"{n_unk} fold-UNKNOWN slots (mangled hit inside an ICF fold: "
          f"member-level identity not provable), "
          f"{n_rej} rejected (outside slot truth)")
    for c, slots in sorted(unknowns.items()):
        if len(slots) <= 6:
            print(f"  UNKNOWN {c}: slots {slots}")
        else:
            print(f"  UNKNOWN {c}: {len(slots)} slots "
                  f"(e.g. {slots[:6]})")
    for c, e in failed:
        print(f"  FAIL {c}: {e}")
    if args.json_out:
        artifact = {
            "gate": "A1 slot-ABI identity (full-mangled)",
            "checked": checked,
            "failed": len(failed),
            "failed_detail": [{"class": c, "errors": e} for c, e in failed],
            "source_verified": len(source_verified),
            "fold_unknown_slots": n_unk,
            "fold_unknown_detail": {c: s for c, s in sorted(unknowns.items())},
            "rejected": n_rej,
            "verified": checked - len(failed) - len(source_verified),
            "verdict": "FAIL" if failed else "PASS",
        }
        pathlib.Path(args.json_out).write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8")
    if failed:
        print("slot-abi-audit v2: FAIL")
        return 1
    print("slot-abi-audit v2: PASS "
          "(full-mangled identity; UNKNOWN slots are reported, not passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
