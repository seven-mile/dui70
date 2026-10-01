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
  * The 5 plain-name C functions (InitProcessPriv, UnInitProcessPriv,
    RegisterAllControls, StartMessagePump, StrToID) are NOT emitted here;
    they are plain-name exports declared extern "C" in the aggregate header.
  * 'vector deleting dtor' (??_E...) entries are compiler-generated, are
    not exports, and are never emitted.
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
    TypeTranslator,
    classify_dtor,
    classify_scalar_dtor,
    is_data,
    load_symbols,
    load_classes,
    make_banner,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PINNED = REPO / "pinned"
DEFAULT_INC = REPO / "DirectUI" / "include"
DEFAULT_OUT = REPO / "DirectUI" / "src"

# Trivial initializer expressions for static data definitions.
DATA_INIT = {
    "s_pClassInfo": "nullptr",
    "c_RefCountBitOffset": "0",
    "c_RefCountMask": "0",
    "c_SingleRefCount": "0",
}


def render_return_expr(ret_decl: str) -> str:
    """Return a trivial return expression for a stub body."""
    r = ret_decl.strip()
    if r == "void":
        return ""
    if r.endswith("*") or r.endswith("&"):
        # pointer / reference -> null / dangling-free default
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
    # by-value structs (tagSIZE, LINEINFO, ...)
    return f"return {r}{{}};"


def render_stub_body(ret_decl: str, cls: str, kind: str, member: str,
                     params: list, tr: TypeTranslator) -> str:
    """Render the function body of one stub definition."""
    if kind == "ctor":
        return "{}"
    if kind == "dtor" or classify_dtor_sym(kind, member, cls):
        return "{}"
    if kind == "operator" and member == "operator=":
        # returns Class& -- return *this
        return "{ return *this; }"
    r = ret_decl.strip()
    expr = render_return_expr(r)
    if expr:
        return f"{{ {expr} }}"
    return "{}"


def classify_dtor_sym(kind: str, member: str, cls: str) -> bool:
    return member.startswith("~")


def render_definition(cls: str, sym: dict, tr: TypeTranslator) -> str:
    """Render one out-of-line member definition (without leading indent)."""
    from emit_headers import MemberDecl

    md = MemberDecl(sym, cls)
    s = sym
    name = s["member"]
    if md.is_dtor:
        name = "~" + cls
    params = s.get("params") or []
    param_names = [f"a{i}" for i in range(len(params))]
    param_text = ", ".join(
        tr.translate_def(p, n) for p, n in zip(params, param_names)
    ) or "void"

    fpr = md.fnptr_return()
    if md.is_ctor or md.is_dtor:
        head = f"{cls}::{name}({param_text})"
    elif fpr:
        # function returning a function pointer -- trailing return type
        head = f"auto {cls}::{name}({param_text}) -> {tr.translate(fpr)}"
    else:
        ret = tr.translate(s["return_type"]) if s.get("return_type") else "void"
        if s.get("is_const"):
            head = f"{ret} {cls}::{name}({param_text}) const"
        else:
            head = f"{ret} {cls}::{name}({param_text})"
    if fpr:
        body = "{ return nullptr; }"
    else:
        body = render_stub_body(
            tr.translate(s["return_type"]) if s.get("return_type") else "void",
            cls, s["kind"], s["member"], params, tr,
        )
    return f"{head}\n{body}"


def render_data_definition(cls: str, sym: dict, tr: TypeTranslator) -> str:
    """Out-of-line static data member definition.

    The type comes from return_type; pointer-ness for pointer members
    (e.g. s_pClassInfo) is recovered from the mangled name."""
    ty = tr.translate(sym.get("return_type") or "")
    name = sym["member"]
    mang = sym["mangled"]
    if mang.startswith("?s_fd"):
        # const array of FunctionDefinition<T> (1QBU...B)
        ty = re.sub(r"\s*const\s*\*\s*const\s*$", "", ty).strip()
        return f"{ty} const {cls}::{name}[1] = {{ {{}} }};"
    if re.search(r"@@[012]PE[QAUVT]", mang) and not ty.endswith("*"):
        ty = ty + "*"
    init = DATA_INIT.get(name, "nullptr")
    return f"{ty} {cls}::{name} = {init};"


def render_tu(cls: str, members: list, data_members: list,
              tr: TypeTranslator, banner: str) -> str:
    lines = [banner]
    lines.append(f"// Stub implementations for DirectUI::{cls}.")
    lines.append(f'// Every definition exists solely to materialize the exact')
    lines.append(f'// decorated names of the real dui70.dll exports.')
    lines.append("")
    lines.append(f'#include "{cls}.h"')
    # s_pClassInfo has type IClassInfo* (incomplete in class headers);
    # the out-of-line definition needs the complete type from Interfaces.h.
    if any(d["member"] == "s_pClassInfo" for d in data_members):
        lines.append('#include "Interfaces.h"')
    lines.append("")
    lines.append("namespace DirectUI")
    lines.append("{")
    lines.append("")
    for sym in members:
        lines.append(render_definition(cls, sym, tr))
        lines.append("")
    for dsym in data_members:
        lines.append(render_data_definition(cls, dsym, tr))
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
    lines.append("} // namespace DirectUI")
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

    classes, _inheritance = load_classes(args.pinned / "classes.json")
    if args.classes:
        classes = [c.strip() for c in args.classes.split(",") if c.strip()]

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.pinned / "manifest.json").read_text(encoding="utf-8"))
    banner = make_banner(manifest["dll"]["sha256"][:12])

    symbols = load_symbols(args.pinned / "symbols.json")
    tr = TypeTranslator(classes)

    for cls in classes:
        members = [s for s in symbols
                   if s.get("class") == cls
                   and (s.get("kind") in CALLABLE_KINDS or s.get("kind") == "template")
                   and not s["mangled"].startswith("??$")
                   and not classify_scalar_dtor(s)]
        data_members = [s for s in symbols
                        if s.get("class") == cls
                        and is_data(s)]
        content = render_tu(cls, members, data_members, tr, banner)
        (out_dir / f"{cls}.cpp").write_text(content, encoding="utf-8", newline="\n")
        n_dtor = sum(1 for s in members if classify_dtor(s))
        print(f"  {cls:<16} stubs={len(members):4d} (dtor={n_dtor}) data-defs={len(data_members)}")

    print(f"emit_stub: wrote {len(classes)} TUs to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
