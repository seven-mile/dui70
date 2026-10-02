#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emit_stub.py -- stub source emitter of the dui-pipeline.

Generates stub .cpp implementations for the target DirectUI classes, one
class per TU, from pinned/symbols.json + pinned/classes.json. Every
non-template method gets a trivial out-of-line definition so the resulting
.obj exports the exact MSVC decorated names of the real dui70.dll.
Output is deterministic (CI golden).

Hard acceptance metric (contract: tools/dui-pipeline/INTERFACE.md):
    cl.exe /std:c++20 /Zc:wchar_t- /c /EHsc  ->  .obj
    dumpbin /symbols  ->  decorated name set
    must match the real exports for the target classes.

Notes:
  * The 86 plain-name C functions are emitted as one extra TU (CApi.cpp)
    covering every extern "C" export of the real DLL; the declarations
    live in the aggregate header (DirectUI.h, C_API_DECLS table).
  * 'vector deleting dtor' (??_E...) entries are compiler-generated, are
    not exports, and are never emitted.
  * 'default ctor closure' (??_F...) entries cannot be expressed in C++
    source; for classes that export one, a companion MASM (.asm) file is
    emitted next to the .cpp defining the symbol verbatim (assemble with
    ml64). See ctor_closure_asm().
  * Static data members (s_pClassInfo, c_RefCount*, s_fd* tables) get
    definitions here because their decorated data symbols are real exports.

Usage:
    python emit_stub.py [--pinned <dir>] [--inchead <dir>] [--out <dir>] [--classes a,b,c]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# reuse the declaration logic from emit_headers
sys.path.insert(0, str(Path(__file__).resolve().parent))
from emit_headers import (  # noqa: E402
    CALLABLE_KINDS,
    TPL_CLASS_RE,
    TypeTranslator,
    base_list,
    classify_dtor,
    classify_scalar_dtor,
    in_directui_scope,
    is_data,
    is_duixml_nested,
    is_nested_pseudo_class,
    is_synth_member,
    is_template_class,
    load_symbols,
    load_classes,
    make_banner,
    safe_name,
    template_id,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PINNED = REPO / "pinned"
DEFAULT_INC = REPO / "DirectUI" / "include"
DEFAULT_OUT = REPO / "DirectUI" / "src"

# Trivial initializer expressions for known static data members.
DATA_INIT = {
    "s_pClassInfo": "nullptr",
    "c_RefCountBitOffset": "0",
    "c_RefCountMask": "0",
    "c_SingleRefCount": "0",
}

# 'windows.h real name' mapping for types the PDB reports under their
# struct tag: init expressions must name the windows.h type.
WINDOWS_STRUCT_TYPES = {"_RTL_CRITICAL_SECTION": "CRITICAL_SECTION"}


def render_return_expr(ret_decl: str) -> str:
    """Return a trivial return expression for a stub body."""
    r = ret_decl.strip()
    if r == "void":
        return ""
    if r.endswith("*") or r.endswith("&"):
        if r.endswith("*"):
            return "return nullptr;"
        return ""
    if ("ClickDevice" in r or "DynamicScale" in r or "_DUI_PARSE_STATE" in r
            or "CheckedStateFlags" in r):
        return "return {};"
    if r in ("UID", "DirectUI::UID", "class UID"):
        return "return UID();"
    if r.startswith("unsigned") or r in ("int", "long", "float", "double",
                                          "bool", "__int64", "short", "char"):
        return "return 0;"
    return f"return {r}{{}};"


def render_stub_body(ret_decl: str, cls: str, kind: str, member: str,
                     params: list, tr: TypeTranslator) -> str:
    """Render the function body of one stub definition."""
    if kind == "ctor":
        return "{}"
    if kind == "dtor" or member.startswith("~"):
        return "{}"
    if kind == "operator" and member == "operator=":
        return "{ return *this; }"
    r = ret_decl.strip()
    expr = render_return_expr(r)
    if expr:
        return f"{{ {expr} }}"
    return "{}"


# Classes whose ctor/operator= exports are defaulted (declare-only in the
# header; the TU defines them with '= default' which still emits symbols)
DEFAULTED_BODY_CLASSES = {"ISBLeak", "NavReference", "NavScoring"}


def render_definition(cls: str, sym: dict, tr: TypeTranslator,
                      base_init: str = "") -> str:
    """Render one out-of-line member definition (without leading indent).
    base_init: explicit mem-initializer text for ctors (base classes that
    lack default constructors)."""
    from emit_headers import MemberDecl

    md = MemberDecl(sym, cls)
    s = sym
    name = s["member"]
    if md.is_dtor:
        name = "~" + (TPL_CLASS_RE.match(cls).group(1) if is_template_class(cls) else cls)
    params = s.get("params") or []
    param_names = [f"a{i}" for i in range(len(params))]
    param_text = ", ".join(
        tr.translate_def(p, n) for p, n in zip(params, param_names)
    ) or "void"

    qual = template_id(cls) if is_template_class(cls) else cls
    if cls in DEFAULTED_BODY_CLASSES and s["kind"] in ("ctor", "operator"):
        # implicit-but-exported members: '= default' definitions emit the
        # exact decorated names with the correct tag letters
        if md.is_ctor or md.is_dtor:
            head = f"{qual}::{name}({param_text})"
        else:
            ret = tr.translate(s["return_type"]) if s.get("return_type") else "void"
            head = f"{ret} {qual}::{name}({param_text})"
        return f"{head} = default;"

    qual = template_id(cls) if is_template_class(cls) else cls
    fpr = md.fnptr_return()
    is_conv = (re.match(r"^operator\s+(struct\s+|class\s+|union\s+|enum\s+)?\w+(\s*\*)*\s*$", name)
               and re.sub(r"^(struct|class|union|enum)\s+", "", (s.get("return_type") or "").strip())
               == re.sub(r"^(struct|class|union|enum)\s+", "", name[len("operator"):].strip()))
    if md.is_ctor:
        head = f"{qual}::{name}({param_text})"
        body = f"{{ }}" if not base_init else f"{base_init} {{ }}"
        return f"{head}\n{body}"
    if md.is_dtor:
        head = f"{qual}::{name}({param_text})"
        return f"{head}\n{{}}"
    if is_conv:
        # conversion operator definition: no return type before the name;
        # the body cast-returns a null value of the target type
        conv = tr.translate(s["return_type"])
        head = f"{qual}::{name}({param_text})"
        body = f"{{ return ({conv})nullptr; }}"
        return f"{head}\n{body}"
    if fpr:
        head = f"auto {qual}::{name}({param_text}) -> {tr.translate(fpr)}"
        body = "{ return nullptr; }"
        return f"{head}\n{body}"
    ret = tr.translate(s["return_type"]) if s.get("return_type") else "void"
    if s.get("is_const"):
        head = f"{ret} {qual}::{name}({param_text}) const"
    else:
        head = f"{ret} {qual}::{name}({param_text})"
    body = render_stub_body(
        tr.translate(s["return_type"]) if s.get("return_type") else "void",
        cls, s["kind"], s["member"], params, tr,
    )
    return f"{head}\n{body}"


def data_init_expr(sym: dict, ty: str) -> str:
    """Initializer for an out-of-line static data member, classified by
    shape: pointer -> nullptr, integral -> 0, aggregate -> {}."""
    if ty.endswith("*"):
        return "nullptr"
    if re.match(r"^(const\s+)?(unsigned\s+)?(int|long|short|char|bool|__int64|unsigned\s+__int64|wchar_t|float|double)\b",
                ty):
        return "0"
    if ty.startswith("_RTL_") or "CRITICAL_SECTION" in ty or "GUID" in ty or "<" in ty:
        # windows.h struct types / template-ids: aggregate-init
        return "{}"
    # struct/class-ish type names (incl. nested like
    # CallstackTracker::IMGHLPFN_LOAD): aggregate-init
    if re.match(r"^[A-Za-z_][\w:]*$", ty):
        return "{}"
    return "nullptr"


def render_data_definition(cls: str, sym: dict, tr: TypeTranslator) -> str:
    """Out-of-line static data member definition.

    The type comes from return_type; pointer-ness for pointer members
    (e.g. s_pClassInfo) is recovered from the mangled name."""
    from emit_headers import FN_PTR_RE, data_type_from_mangled, fnptr_shape_from_mangled

    ty = tr.translate(sym.get("return_type") or "")
    name = sym["member"]
    mang = sym["mangled"]
    qual = template_id(cls) if is_template_class(cls) else cls
    if re.search(r"@@[012]Q[AB]U", mang):
        # const array of a (nested) struct: 0/1QBU...B (s_fd* tables,
        # Schema lookup tables, AccessibleButton c_rgar)
        ty = re.sub(r"\s*const\s*\*\s*const\s*$", "", ty).strip()
        return f"{ty} const {qual}::{name}[1] = {{ {{}} }};"
    if re.search(r"@@[012]QAY\d+\$\$CB", mang):
        # multi-dimensional const array of built-ins (HWNDHost g_rgMouseMap).
        # Encoding: Y<rank-2><bound-1 each dim except the first>; the first
        # bound is not encoded so [1][decoded...] reproduces the mangle.
        mm = re.search(r"@@[012]QAY(\d+)", mang)
        digits = mm.group(1)
        bounds = [int(d) + 1 for d in digits[1:]] or [1]
        brk = "[" + "][".join(str(b) for b in [1] + bounds) + "]"
        return f"{ty} {qual}::{name}{brk} = {{ {{}} }};"
    fn_shape = fnptr_shape_from_mangled(mang)
    if fn_shape:
        # function-pointer static member: bind the qualified name into the
        # declarator ('int (__cdecl* C::s_pfn)(...) = nullptr;')
        ret_t, rest = fn_shape.split(" (__cdecl*)", 1)
        args = rest.rstrip(")").lstrip("(")
        return f"{ret_t} (__cdecl* {qual}::{name})({args}) = nullptr;"
    # pointer members: the mangled name is authoritative for the pointee
    # tag and const-ness (PDB may lose the pointer or change PAU->PEAU)
    md = data_type_from_mangled(mang)
    if md and (md.endswith("*") or md.endswith("* __ptr32")):
        mty = re.sub(r"^(struct|class|union) ", "", md)
        if mty.startswith("DirectUI::"):
            mty = mty[len("DirectUI::"):]
        ty = mty
    elif re.search(r"@@[012]P[AEHQ]?[QAUVT]", mang) and not ty.endswith("*"):
        ty = ty + "*"
    if name in DATA_INIT:
        return f"{ty} {qual}::{name} = {DATA_INIT[name]};"
    init = data_init_expr(sym, ty)
    return f"{ty} {qual}::{name} = {init};"


def ctor_closure_asm(cls: str, closures: list, banner: str) -> str:
    """MASM source defining 'default ctor closure' (??_F) symbols that
    cannot be written in C++. Each entry: PUBLIC name + trivial proc."""
    lines = [banner.replace("// Generated", "; Generated").replace(" — ", " -- ")]
    lines.append(f"; 'default ctor closure' exports of DirectUI::{cls}.")
    lines.append("; Compiler-synthesized symbols (??_F...) are not expressible")
    lines.append("; in C++ source; MASM defines them verbatim.")
    lines.append("_TEXT SEGMENT")
    for mg in closures:
        lines.append(f"PUBLIC {mg}")
        lines.append(f"{mg} PROC")
        lines.append("    ret")
        lines.append(f"{mg} ENDP")
    lines.append("_TEXT ENDS")
    lines.append("END")
    return "\n".join(lines) + "\n"


def own_vftable_asm(cls: str, mangled: str, banner: str) -> str:
    """MASM source defining the class's own-vptr vftable symbol
    (??_7X@DirectUI@@6B@) that modern MSVC does not emit: the real DLL was
    built with a VC8-era compiler that gives MI classes with abstract
    interface bases their own vptr instead of merging into a primary base.
    Modern cl always picks a primary base, so the base-subobject vftables
    come from C++ and only the own-vptr symbol needs MASM (a vftable is
    data: one PUBLIC qword slot is enough to materialize the symbol)."""
    lines = [banner.replace("// Generated", "; Generated").replace(" — ", " -- ")]
    lines.append(f"; own-vptr vftable export of DirectUI::{cls}.")
    lines.append("; The real dui70.dll (VC8-era layout) emits ??_7X@@6B@ for this")
    lines.append("; MI class in addition to the base-subobject vftables that the C++")
    lines.append("; TU emits. Modern MSVC always merges into a primary base, so this")
    lines.append("; symbol is defined here as data (PUBLIC qword slot).")
    lines.append("_rdata SEGMENT READONLY")
    lines.append(f"PUBLIC {mangled}")
    lines.append(f"{mangled} DQ 0")
    lines.append("_rdata ENDS")
    lines.append("END")
    return "\n".join(lines) + "\n"


def trivial_arg_for(param_text: str) -> str:
    """A trivial argument expression for a base-ctor parameter."""
    p = param_text.strip()
    if p.endswith("*"):
        return "nullptr"
    if "const &" in p or p.endswith("&"):
        # base classes with reference params cannot be trivially invented;
        # this should not happen for default-constructibility repair.
        return "{}"
    return "0"


def ctor_base_init(cls: str, symbols: list, classes: list,
                   inheritance: dict) -> str:
    """Explicit mem-initializer list for ctors of cls: bases that HAVE
    exported ctors but NO default ctor must be initialized explicitly,
    else the derived default ctor is ill-formed. Zero/nullptr arguments
    reproduce no ABI effect (the mangled name encodes the signature only).
    """
    from emit_headers import base_list
    inits = []
    for b in base_list(inheritance, cls):
        if b not in classes:
            continue
        ctors = [s for s in symbols
                 if s.get("class") == b
                 and s.get("kind") == "ctor"
                 and s.get("is_exported")
                 and in_directui_scope(s)]
        if not ctors:
            continue  # implicit default ctor exists
        has_default = any(not (s.get("params") or []) for s in ctors)
        if has_default:
            continue
        # pick the first exported ctor whose params are all non-reference
        # (copy/move ctors cannot be invoked with trivial args); fall back
        # to the fewest-param ctor
        def invocable(s):
            return all("&" not in p for p in (s.get("params") or []))
        cands = [s for s in ctors if invocable(s)]
        pick = min(cands or ctors, key=lambda s: len(s.get("params") or []))
        args = ", ".join(trivial_arg_for(p) for p in (pick.get("params") or []))
        inits.append(f"{b}({args})")
    if not inits:
        return ""
    return ": " + ", ".join(inits)


def render_tu(cls: str, members: list, data_members: list,
              tr: TypeTranslator, banner: str,
              base_init: str = "") -> str:
    lines = [banner]
    tid = template_id(cls) if is_template_class(cls) else cls
    from emit_headers import GLOBAL_SCOPE_CLASSES
    global_cls = cls in GLOBAL_SCOPE_CLASSES
    if global_cls:
        tr = TypeTranslator(tr.target_classes, keep_scope=True)
    lines.append(f"// Stub implementations for DirectUI::{tid}.")
    lines.append(f'// Every definition exists solely to materialize the exact')
    lines.append(f'// decorated names of the real dui70.dll exports.')
    lines.append("")
    lines.append(f'#include "{safe_name(cls)}.h"')
    # s_pClassInfo has type IClassInfo* (incomplete in class headers);
    # the out-of-line definition needs the complete type from Interfaces.h.
    if any(d["member"] == "s_pClassInfo" for d in data_members):
        lines.append('#include "Interfaces.h"')
    lines.append("")
    if not global_cls:
        lines.append("namespace DirectUI")
        lines.append("{")
        lines.append("")
    for sym in members:
        lines.append(render_definition(cls, sym, tr, base_init))
        lines.append("")
    for dsym in data_members:
        lines.append(render_data_definition(cls, dsym, tr))
        lines.append("")
    if cls == "AccessibleButton":
        # ACCESSIBLEROLE nested struct: its implicit operator= pair are real
        # exports (??4ACCESSIBLEROLE@AccessibleButton@DirectUI@@...)
        lines.append("AccessibleButton::ACCESSIBLEROLE& AccessibleButton::ACCESSIBLEROLE::operator=(AccessibleButton::ACCESSIBLEROLE const& a0)")
        lines.append("{ return *this; }")
        lines.append("")
        lines.append("AccessibleButton::ACCESSIBLEROLE& AccessibleButton::ACCESSIBLEROLE::operator=(AccessibleButton::ACCESSIBLEROLE&& a0)")
        lines.append("{ return *this; }")
        lines.append("")
    if cls == "DUIXmlParser":
        # explicit operator= definitions + instantiations of the nested
        # FunctionDefinition<T> template: the real DLL exports operator=
        # for T in {int, unsigned long, Value*, ScaledRECT, ScaledSIZE}
        lines.append("template <typename T>")
        lines.append("auto DUIXmlParser::FunctionDefinition<T>::operator=(FunctionDefinition const& other) -> FunctionDefinition&")
        lines.append("{ _abi = other._abi; return *this; }")
        lines.append("")
        lines.append("template <typename T>")
        lines.append("auto DUIXmlParser::FunctionDefinition<T>::operator=(FunctionDefinition&& other) -> FunctionDefinition&")
        lines.append("{ _abi = other._abi; return *this; }")
        lines.append("")
        for inst in ("int", "unsigned long", "Value*", "ScaledRECT", "ScaledSIZE"):
            lines.append(f"template struct DUIXmlParser::FunctionDefinition<{inst}>;")
        lines.append("")
    if not global_cls:
        lines.append("} // namespace DirectUI")
    lines.append("")
    return "\n".join(lines)


def render_c_api_tu(banner: str) -> str:
    """Stub TU for the 86 plain-name extern "C" exports.

    Every definition is trivial (zero/nullptr return); the ONLY purpose is
    to materialize the exact undecorated symbol names the real dui70.dll
    exports. Signatures mirror C_API_DECLS in emit_headers.py verbatim."""
    from emit_headers import C_API_DECLS

    def body_of(decl: str) -> str:
        ret = decl.split("WINAPI")[0].strip()
        if ret == "void":
            return "{}"
        if ret.endswith("*") or "void**" in ret or ret.endswith("**"):
            return "{ return nullptr; }"
        return "{ return 0; }"

    lines = [banner]
    lines.append("// Stub implementations for the plain-name extern \"C\" API exports")
    lines.append("// of the real dui70.dll (86 entries).")
    lines.append("// Every definition exists solely to materialize the exact")
    lines.append("// undecorated symbol names of the real export table.")
    lines.append("")
    lines.append('#include "DirectUI.h"')
    lines.append("")
    for d in C_API_DECLS:
        # declaration -> definition: 'RET WINAPI name(args);' ->
        # 'RET WINAPI name(args) { body }' (args already carry names)
        head = d.rstrip(";").strip()
        lines.append(f"{head} {body_of(d)}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    ap.add_argument("--inchead", type=Path, default=DEFAULT_INC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--classes", default=None,
                    help="override the class list from classes.json (comma-separated)")
    args = ap.parse_args(argv)

    classes, inheritance = load_classes(args.pinned / "classes.json")
    if args.classes:
        classes = [c.strip() for c in args.classes.split(",") if c.strip()]

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.pinned / "manifest.json").read_text(encoding="utf-8"))
    banner = make_banner(manifest["dll"]["sha256"][:12])

    symbols = load_symbols(args.pinned / "symbols.json")
    tr = TypeTranslator(classes)

    n_asm = 0
    for cls in classes:
        if is_duixml_nested(cls):
            # operator= instantiations are emitted by the DUIXmlParser TU
            continue
        if is_nested_pseudo_class(cls):
            # nested in its host class: emitted inside the host's TU
            continue
        members = [s for s in symbols
                   if s.get("class") == cls
                   and s.get("is_exported")
                   and in_directui_scope(s)
                   and not is_synth_member(s)
                   and (s.get("kind") in CALLABLE_KINDS or s.get("kind") == "template")
                   and not s["mangled"].startswith("??$")
                   and not s["mangled"].startswith("??_F")
                   and not classify_scalar_dtor(s)]
        data_members = [s for s in symbols
                        if s.get("class") == cls
                        and s.get("is_exported")
                        and in_directui_scope(s)
                        and is_data(s)]
        base_init = ctor_base_init(cls, symbols, classes, inheritance)
        content = render_tu(cls, members, data_members, tr, banner, base_init)
        (out_dir / f"{safe_name(cls)}.cpp").write_text(content, encoding="utf-8", newline="\n")
        # ??_F 'default ctor closure' exports -> companion MASM file
        closures = [s["mangled"] for s in symbols
                    if s.get("class") == cls
                    and s.get("is_exported")
                    and s["mangled"].startswith("??_F")]
        if closures:
            asm_text = ctor_closure_asm(cls, closures, banner)
            (out_dir / f"{safe_name(cls)}_ctor_closure.asm").write_text(asm_text, encoding="ascii", newline="\r\n")
            n_asm += 1
        # own-vptr vftable (??_7X@@6B@) of MI classes whose real layout has
        # no primary base: modern MSVC merges into a primary base, so the
        # symbol is emitted as data via a companion MASM file
        n_bases = len(base_list(inheritance, cls)) if inheritance else 0
        own_vft = next((s["mangled"] for s in symbols
                        if s.get("class") == cls
                        and s.get("is_exported")
                        and s["mangled"].endswith("@DirectUI@@6B@")), None)
        if own_vft and n_bases >= 2:
            asm_text = own_vftable_asm(cls, own_vft, banner)
            (out_dir / f"{safe_name(cls)}_own_vftable.asm").write_text(asm_text, encoding="ascii", newline="\r\n")
            n_asm += 1
        n_dtor = sum(1 for s in members if classify_dtor(s))
        print(f"  {safe_name(cls):<44} stubs={len(members):4d} (dtor={n_dtor}) data-defs={len(data_members)}"
              + (f" +{len(closures)} ??_F asm" if closures else ""))

    # extern "C" API stub TU (86 plain-name exports)
    (out_dir / "CApi.cpp").write_text(render_c_api_tu(banner), encoding="utf-8", newline="\n")

    print(f"emit_stub: wrote {len(classes) + 1} TUs to {out_dir}"
          + (f" (+{n_asm} ctor-closure .asm)" if n_asm else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
