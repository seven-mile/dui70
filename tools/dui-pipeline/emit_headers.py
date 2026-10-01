#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emit_headers.py -- codegen module of the dui-pipeline.

Generates C++ header files for the 7 UITest-required DirectUI classes
(Value, DUIXmlParser, Element, HWNDElement, NativeHWNDHost, TouchButton, Edit)
from the structured symbol table (.local/build/symbols-kindfix.json).

Design goals (contract: tools/dui-pipeline/INTERFACE.md, Product 4):
  * Output headers must be self-contained: only <windows.h>, forward
    declarations and mutually-generated headers. They must NOT include
    anything from the handwritten baseline (DirectUI/*.h).
  * The declarations must reproduce the exact MSVC decorated names of the
    real dui70.dll exports. This is the hard acceptance metric and drives
    every type-mapping decision below (class vs struct tag, namespace
    placement, /Zc:wchar_t- typedefs, by-value struct completeness...).

Key ABI facts encoded here (verified against real-x64-norm.txt):
  * MSVC mangles `class X` as V...@ and `struct X` as U...@. The tag keyword
    in the undecorated text from llvm-undname is authoritative.
  * Under /Zc:wchar_t- (used by the baseline project), `const wchar_t*`
    mangles exactly like `const unsigned short*` (PEBG), matching UCString.
  * DynamicScaleValue is a GLOBAL-scope enum (W4DynamicScaleValue@@),
    while DynamicScaleParsing / _DUI_PARSE_STATE live in namespace DirectUI
    and ClickDevice is nested inside TouchButton.
  * IXmlReader / IDuiBehavior / ISharedBitmap / IAccessible / IStream /
    IUnknown / EventMsg / UID / _GUID / _RTL_CRITICAL_SECTION / tagXXX /
    HXXX__ handle types are global-scope (mangled without the @2@ backref).
  * Element::s_pClassInfo etc. are PRIVATE static data members (prefix 0 in
    the decorated name); they are only declared in the header, defined in
    the stub TU (emit_stub.py).
  * The by-value LINEINFO / ScaledSIZE / ScaledRECT parameters need a
    complete type, so a small placeholder definition header is emitted
    (dui_abi_types.h). LINEINFO actually has real fields; the placeholder
    only guarantees size >= real one is NOT required for symbol matching --
    only the decorated name must match, so a 1-field dummy is fine for ABI
    verification. (Header consumers get the real layout from the baseline.)

Usage:
    python emit_headers.py [--symbols <path>] [--out <dir>] [--classes A,B,..]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SYMBOLS = REPO / ".local" / "build" / "symbols.json"
DEFAULT_OUT = REPO / ".local" / "build" / "generated" / "include"

TARGET_CLASSES = [
    "Value",
    "DUIXmlParser",
    "Element",
    "HWNDElement",
    "NativeHWNDHost",
    "TouchButton",
    "Edit",
]

MIGRATION_CLASSES = TARGET_CLASSES + [
    "Button",
    "Progress",
    "PushButton",
    "TouchCheckBox",
    "XProvider",
]

# Inheritance (derived from the real DLL's class hierarchy; the class
# keyword of a base does not affect the derived class's own mangling, but
# the base must be a complete-enough type here: our generated classes work
# as bases directly).
# The real chains pass through intermediate classes not in the generated
# set (ElementWithHWND/HWNDHost/RichText/AutoButton/AccessibleButton);
# attaching the derived class directly to the nearest generated base is
# ABI-equivalent for symbol fidelity (decorated names encode no base) and
# for consumer-side upcasts (single inheritance, offset 0).
INHERITANCE = {
    "HWNDElement": "Element",     # real: HWNDElement : ElementWithHWND : Element
    "Edit": "Element",            # real: Edit : HWNDHost : ElementWithHWND : Element
    "TouchButton": "Element",     # real: TouchButton : RichText : Element
    "Button": "Element",
    "Progress": "Element",
    "PushButton": "Button",       # real chain: PushButton : AutoButton : AccessibleButton : Button
    "TouchCheckBox": "TouchButton",
    "XProvider": "IXProvider",    # abstract consumer interface (Interfaces.h)
}

CALLABLE_KINDS = {"method", "static_method", "ctor", "dtor", "operator"}

# ---------------------------------------------------------------------------
# Type universe
# ---------------------------------------------------------------------------
# Types declared at GLOBAL scope. Everything in this table that is a struct
# or handle is either provided by <windows.h> (handles, tagXXX) or is a
# DirectUI-external type that the real DLL mangles at global scope.
# (kind: how it appears in the undecorated signature text)
GLOBAL_TYPES = {
    # windows.h handles & structs (do NOT redeclare)
    "HDC__": "windows",
    "HBITMAP__": "windows",
    "HENHMETAFILE__": "windows",
    "HGADGET__": "declare",  # DECLARE_HANDLE - we emit a minimal decl
    "HICON__": "windows",
    "HINSTANCE__": "windows",
    "HMENU__": "windows",
    "HWND__": "windows",
    "tagGMSG": "declare",  # not in windows.h
    "tagMSG": "windows",
    "tagPOINT": "windows",
    "tagRECT": "windows",
    "tagSIZE": "windows",
    "_GUID": "windows-alias",  # GUID via windows.h; mangled as _GUID
    "_RTL_CRITICAL_SECTION": "windows-alias",  # CRITICAL_SECTION
    "IAccessible": "declare",
    "IDuiBehavior": "declare",
    "ISharedBitmap": "declare",
    "IStream": "declare",
    "IUnknown": "declare",
    "IXmlReader": "declare",
    "EventMsg": "declare",
    # UID mangles as VUID@@ (GLOBAL scope) in the real DLL even though it is
    # documented inside DirectUI in the baseline headers -- the decorated
    # name is authoritative, so we declare it at global scope.
    "UID": "define",  # needs a complete definition (returned by value)
    "DynamicScaleValue": "enum",
}

# Types inside namespace DirectUI. kind -> declaration strategy.
DIRECTUI_CLASS_TYPES = {
    # the 7 targets themselves are emitted as full headers
    "DeferCycle": "fwd",
    "ElementProvider": "fwd",
    "Expression": "fwd",
    "InvokeHelper": "fwd",
    "Layout": "fwd",
    "StyleSheet": "fwd",
    "Surface": "fwd",
    "TouchHWNDElement": "fwd",
}
DIRECTUI_STRUCT_TYPES = {
    "Cursor": "fwd",
    "DepRecs": "fwd",
    "EnumMap": "fwd",
    "Event": "fwd",
    "Fill": "fwd",
    "Graphic": "fwd",
    "IClassInfo": "fwd",
    "IElementListener": "fwd",
    "InputEvent": "fwd",
    "KeyboardEvent": "fwd",
    "LINEINFO": "define",  # by-value in several DUIXmlParser signatures
    "MouseEvent": "fwd",
    "NavReference": "fwd",
    "PointerEvent": "fwd",
    "PropertyInfo": "fwd",
    "ScaledInt": "fwd",
    "ScaledRECT": "define",  # by-value? no - pointer only, but keep symmetrical
    "ScaledSIZE": "define",  # by-value in Value::CreateGraphic
    "ThemeChangedEvent": "fwd",
    "UpdateCache": "fwd",
}
DIRECTUI_ENUM_TYPES = {
    "_DUI_PARSE_STATE": "enum",
    "DynamicScaleParsing": "enum",
}
PARSERTOOLS_TYPES = {
    "ExprNode": ("struct", "fwd"),
    "ValueParser": ("class", "fwd"),
}
# nested inside TouchButton
TOUCHBUTTON_ENUMS = {"ClickDevice"}

BANNER = "// Generated by tools/dui-pipeline/emit_headers.py -- DO NOT EDIT.\n"

# ---------------------------------------------------------------------------
# undecorated-type-text -> C++ declaration text translation
# ---------------------------------------------------------------------------

FN_PTR_RE = re.compile(
    r"^(?P<ret>.+?)\s*\(__cdecl\s*\*\)\s*\((?P<args>.*)\)$"
)

# Template-id like 'class DirectUI::DynamicArray<class DirectUI::Element *, 0>'
# or 'struct DirectUI::DUIXmlParser::FunctionDefinition<int>'
TEMPLATE_ID_RE = re.compile(
    r"^(?P<kw>class|struct)\s+"
    r"(?P<ns>(?:DirectUI::)?(?:DUIXmlParser::)?(?:ParserTools::)?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"<(?P<args>.+)>$"
)


class TypeTranslator:
    """Translates undecorated parameter/return type strings into C++ decl text
    usable inside `namespace DirectUI`."""

    def __init__(self, target_classes):
        self.target_classes = set(target_classes)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _strip_ns_prefix(text: str) -> str:
        """Remove 'DirectUI::' qualifications (we are inside that namespace).
        Keep 'ParserTools::' and nested class qualifications."""
        return text.replace("DirectUI::", "")

    def translate(self, text: str) -> str:
        """Translate one type string (return type or param type)."""
        text = text.strip()

        # Function pointer?
        m = FN_PTR_RE.match(text)
        if m:
            ret = self.translate(m.group("ret"))
            args = m.group("args").strip()
            if args in ("", "void"):
                arg_list = "void"
            else:
                arg_list = ", ".join(
                    self.translate(a.strip()) for a in self._split_args(args)
                )
            return f"{ret} (__cdecl*)({arg_list})"

        # Pointer/ref decorations trailing the base type
        base = text
        suffix = ""
        while True:
            m2 = re.search(r"\s*(\*+|&&|&)\s*$", base)
            if not m2:
                break
            suffix = m2.group(1).replace(" ", "") + suffix
            base = base[: m2.start()].rstrip()

        # const prefix / const after base (e.g. 'unsigned short const *'
        # already consumed by suffix loop; 'const X' or 'X const')
        const_prefix = False
        if base.startswith("const "):
            const_prefix = True
            base = base[len("const "):].strip()
        const_suffix = False
        if base.endswith(" const"):
            const_suffix = True
            base = base[: -len(" const")].rstrip()
        is_const = const_prefix or const_suffix

        # strip class/struct/enum/union elaborated keyword
        m3 = re.match(r"^(class|struct|enum|union)\s+(.*)$", base)
        if m3:
            base = m3.group(2).strip()

        base = self._strip_ns_prefix(base)

        # Template-id? (e.g. 'DynamicArray<Element*, 0>') -- translate args
        if "<" in base and ">" in base:
            base = self._translate_template_id(base)

        out = base + (" const" if is_const else "") + ((" " + suffix) if suffix else "")
        if suffix:
            # normalize spacing: 'X *' -> 'X*'
            out = out.replace(" *", "*").replace(" &", "&")
        return out

    def _translate_template_id(self, text: str) -> str:
        """Translate 'DynamicArray<Element*, 0>' style template-ids by
        recursively translating the arguments and dropping the elaborated
        keyword. Non-type args (plain integers) are kept verbatim."""
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*<(.*)>$", text)
        if not m:
            # nested template-ids may have trailing decoration; fall back
            return text
        name = m.group(1)
        args_raw = m.group(2)
        args = []
        for a in self._split_args(args_raw):
            a = a.strip()
            if re.fullmatch(r"\d+", a):
                args.append(a)  # non-type parameter
            else:
                args.append(self.translate(a))
        return f"{name}<{', '.join(args)}>"

    def translate_def(self, text: str, name: str) -> str:
        """Translate one type string for a definition context, binding the
        parameter name. Function pointers get the name inside the (*name)
        declarator."""
        text = text.strip()
        m = FN_PTR_RE.match(text)
        if m:
            ret = self.translate(m.group("ret"))
            args = m.group("args").strip()
            if args in ("", "void"):
                arg_list = "void"
            else:
                arg_list = ", ".join(
                    self.translate(a.strip()) for a in self._split_args(args)
                )
            return f"{ret} (__cdecl* {name})({arg_list})"
        plain = self.translate(text)
        if plain.endswith("*") or plain.endswith("&"):
            return f"{plain}{name}"
        return f"{plain} {name}"

    @staticmethod
    def _split_args(text: str) -> list:
        """Split a comma-separated argument list, respecting parentheses."""
        parts, depth, cur = [], 0, []
        for ch in text:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        if cur:
            parts.append("".join(cur))
        return [p for p in (s.strip() for s in parts) if p]


# ---------------------------------------------------------------------------
# Symbol model helpers
# ---------------------------------------------------------------------------


def load_symbols(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["symbols"]


def classify_dtor(sym: dict) -> bool:
    """True for the real destructor (??1Class...). The 'vector deleting
    dtor' (??_E...) is a compiler-generated entry, not an export."""
    return sym["mangled"].startswith("??1")


def classify_scalar_dtor(sym: dict) -> bool:
    """'vector deleting dtor' ??_E... entries - these are NOT exports (they
    come from the PDB publics) and are compiler-generated; we never emit
    them. They appear as kind='method' with member '`vector deleting dtor'`."""
    return sym["mangled"].startswith("??_E")


def is_callable(sym: dict) -> bool:
    if sym.get("namespace") != "DirectUI":
        return False
    if sym.get("kind") not in CALLABLE_KINDS:
        # plain methods that merely USE template parameter types (e.g.
        # ?CreateElementList@Value@...DynamicArray@...) carry kind='template'
        # in the symbol table but are NOT function templates (no ??$ prefix)
        if sym.get("kind") != "template":
            return False
    if classify_scalar_dtor(sym):
        return False
    # True function templates (??$...) are skipped -- their instantiations
    # are compile-time and cannot be re-emitted from a declaration.
    if sym["mangled"].startswith("??$"):
        return False
    return True


def is_data(sym: dict) -> bool:
    if sym.get("namespace") != "DirectUI":
        return False
    if sym["mangled"].startswith("??$"):
        return False
    return sym.get("kind") == "data"


def mangled_class(mangled: str) -> str | None:
    """Extract the class name from ?Member@Class@DirectUI@@..."""
    m = re.match(r"^\?\w+@(\w+)@DirectUI@@", mangled)
    return m.group(1) if m else None


def split_top_level(text: str) -> list:
    """Split a comma-separated list at top level (paren-aware)."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def recover_fnptr_methods(symbols: list, target_classes) -> list:
    """Safety net for a symbols-module bug (fixed upstream 18:27): methods
    with fn-pointer parameters were mis-parsed as kind='data', class=None,
    with a broken params list.

    The upstream fix stores correct records (kind='method', complete
    params/return_type), so this recovery now only fires on records that
    STILL look broken (kind='data' + function-shaped undecorated text +
    mangled name of a plain member function). With a healthy symbols.json
    it returns an empty list and is effectively a no-op."""
    recovered = []
    for s in symbols:
        if s.get("kind") != "data":
            continue
        und = s.get("undecorated") or ""
        if "__cdecl" not in und or "::" not in und:
            continue
        # genuine static data: 'static <type> Class::name' with NO call
        # operator and no trailing parameter list
        if re.match(r"^[^()]*\bstatic\b[^()]*::\w+$", und):
            continue
        mangled = s["mangled"]
        cls = mangled_class(mangled)
        if not cls or cls not in target_classes:
            continue
        # only recover if the record is still broken: class must be absent
        # (a healthy record for the same mangled name would carry it)
        if s.get("class"):
            continue
        # <access>: [static] <ret> __cdecl DirectUI::<Class>::<member>(<params>)
        m = re.match(
            r"^(public|protected|private):\s+(?:static\s+)?(.*?)\s+__cdecl\s+DirectUI::(\w+)::(\w+)\((.*)\)$",
            und,
        )
        if not m:
            continue
        access, ret_text, cls2, member, params_text = m.groups()
        if cls2 != cls:
            continue
        rec = dict(s)
        rec["kind"] = "static_method" if "static " in und.split("__cdecl")[0] else "method"
        rec["class"] = cls
        rec["namespace"] = "DirectUI"
        rec["member"] = member
        rec["scope"] = f"DirectUI::{cls}"
        rec["access"] = access
        rec["params"] = split_top_level(params_text)
        rec["is_static"] = rec["kind"] == "static_method"
        # fn-ptr-returning methods embed the member name in ret_text; the
        # true return type is the text before ' (__cdecl *' there
        m2 = re.match(
            r"^(.*?)\s*\(__cdecl\s\*\s*__cdecl\s*DirectUI::\w+::\w+\(.*\)\)\(.*\)$",
            und,
        )
        if m2:
            rec["return_type"] = m2.group(1)
        else:
            rec["return_type"] = ret_text
        recovered.append(rec)
    return recovered


# ---------------------------------------------------------------------------
# Declaration rendering
# ---------------------------------------------------------------------------


class MemberDecl:
    def __init__(self, sym: dict, cls: str):
        self.sym = sym
        self.cls = cls
        self.is_dtor = classify_dtor(sym)
        self.is_ctor = sym["kind"] == "ctor" and not self.is_dtor

    def fnptr_return(self) -> str | None:
        """Return the raw fn-pointer return-type text if the method returns
        a function pointer, else None.

        The upstream symbols.json (fixed 18:27) now stores the complete
        shape in return_type, e.g.:
            'class DirectUI::Value * (__cdecl *)(unsigned short const *, void *)'
        We detect that via the '(__cdecl *)' marker."""
        ret = self.sym.get("return_type") or ""
        m = re.match(r"^(.*?)\s*\(__cdecl\s*\*\)\s*\((.*)\)$", ret.strip())
        if not m:
            return None
        return ret.strip()

    def signature(self, tr: TypeTranslator) -> str:
        s = self.sym
        name = s["member"]
        if self.is_ctor or self.is_dtor:
            if self.is_dtor:
                name = "~" + self.cls
            params = s.get("params") or []
            param_text = ", ".join(tr.translate(p) for p in params) or "void"
            sig = f"{name}({param_text})"
        else:
            params = s.get("params") or []
            param_text = ", ".join(tr.translate(p) for p in params) or "void"
            fpr = self.fnptr_return()
            if fpr:
                # function returning a function pointer -- use trailing
                # return type: the shape is emitted verbatim after '->'.
                # The decorated name is unaffected (it encodes the
                # signature, not the syntax).
                sig = f"auto {name}({param_text}) -> {tr.translate(fpr)}"
            else:
                ret = tr.translate(s["return_type"]) if s.get("return_type") else "void"
                sig = f"{ret} {name}({param_text})"
        if s.get("is_const"):
            sig += " const"
        return sig

    def qualifiers(self) -> str:
        s = self.sym
        q = []
        if s.get("is_virtual"):
            q.append("virtual")
        if s.get("is_static"):
            q.append("static")
        return " ".join(q)

    def is_virtual(self) -> bool:
        return bool(self.sym.get("is_virtual"))

    def full_decl(self, tr: TypeTranslator) -> str:
        q = self.qualifiers()
        sig = self.signature(tr)
        if q:
            return f"{q} {sig};"
        return f"{sig};"


def order_key(sym: dict):
    # keep original order from the symbol table (roughly vtable order for
    # virtuals, which helps readability but is not semantically required)
    return 0


# ---------------------------------------------------------------------------
# Header emission
# ---------------------------------------------------------------------------

INCLUDE_GUARD_PREFIX = "DUI_GENERATED"


def render_class_header(cls: str, members: list, data_members: list,
                        tr: TypeTranslator, classes: list | None = None) -> str:
    """Render one class header file content."""
    classes = classes or TARGET_CLASSES
    lines = []
    lines.append(BANNER)
    lines.append(f"// DirectUI::{cls} -- declarations derived from the real")
    lines.append("// dui70.dll export table + PDB publics.")
    lines.append("#pragma once")
    lines.append("")
    lines.append("#include <windows.h>")
    lines.append('#include "dui_abi_types.h"')
    lines.append("")
    # include the base-class header (must be a complete type)
    base = INHERITANCE.get(cls)
    if base and base in classes:
        lines.append(f'#include "{base}.h"')
        lines.append("")
    if cls == "XProvider":
        # XProvider : IXProvider (abstract consumer interface)
        lines.append('#include "Interfaces.h"')
        lines.append("")

    lines.append("namespace DirectUI")
    lines.append("{")
    # forward declarations for sibling generated classes
    siblings = [c for c in classes if c != cls and c != base]
    for sib in siblings:
        lines.append(f"    class {sib};")
    lines.append("")

    # Split by access. The real access is recorded per symbol.
    sections = {"public": [], "protected": [], "private": []}
    for sym in members:
        acc = sym.get("access") or "public"
        sections.setdefault(acc, []).append(sym)

    # Nested enums (only TouchButton has one: ClickDevice)
    if cls == "TouchButton":
        # emitted in the public section
        pass

    kw = "class"
    # All classes in the real ABI mangle as 'class DirectUI::X' (V...@).
    base = INHERITANCE.get(cls)
    base_clause = f" : public {base}" if base else ""
    lines.append(f"    {kw} {cls}{base_clause}")
    lines.append("    {")
    lines.append("    public:")

    if cls == "TouchButton":
        lines.append("        enum ClickDevice")
        lines.append("        {")
        lines.append("            ClickDevice_None = 0,")
        lines.append("        };")
        lines.append("")

    if cls == "DUIXmlParser":
        # nested union referenced by ParseArgs/ParseFunction (mangles
        # PEATParsedArg@12@ -- must be nested inside DUIXmlParser)
        lines.append("        union ParsedArg")
        lines.append("        {")
        lines.append("            unsigned __int64 _raw;")
        lines.append("        };")
        lines.append("")
        # nested template struct used by the s_fd* static tables (mangles
        # U?$FunctionDefinition@...@12@ -- nested inside DUIXmlParser).
        # The real DLL exports its operator= for 5 instantiations, so we
        # declare them out-of-line (definitions in the stub TU).
        lines.append("        template <typename T>")
        lines.append("        struct FunctionDefinition")
        lines.append("        {")
        lines.append("            int _abi;")
        lines.append("            FunctionDefinition& operator=(FunctionDefinition const&);")
        lines.append("            FunctionDefinition& operator=(FunctionDefinition&&);")
        lines.append("        };")
        lines.append("")

    first = True
    for acc in ("public", "protected", "private"):
        syms = sections.get(acc) or []
        data_syms = [d for d in data_members if (d.get("access") or "private") == acc]
        if not syms and not data_syms:
            continue
        if not first:
            lines.append("")
            lines.append(f"        {acc}:")
        lines_is_first_section = first
        first = False

        for sym in syms:
            md = MemberDecl(sym, cls)
            decl = md.full_decl(tr)
            lines.append(f"        {decl}")
        for dsym in data_syms:
            lines.append(f"        {render_data_decl(dsym, tr)}")

    lines.append("    };")
    lines.append("")
    # static data member declarations live inside the class (private), but
    # their *definitions* are emitted by emit_stub.py.
    lines.append("} // namespace DirectUI")
    lines.append("")
    return "\n".join(lines)


def render_data_decl(sym: dict, tr: TypeTranslator) -> str:
    """static data member in-class declaration, e.g.
    'static IClassInfo* s_pClassInfo;'"""
    und = sym["undecorated"]  # 'private: static struct DirectUI::IClassInfo *DirectUI::Element::s_pClassInfo'
    m = re.match(r"^.*?static\s+(.*?)\s*\b\w+::(\w+)$", und)
    if not m:
        # fallback: parse from mangled+undecorated manually
        return f"// UNPARSED DATA: {sym['mangled']}"
    ty = tr.translate(m.group(1))
    name = m.group(2)
    # s_fd* tables: the real symbol 1QBU...B encodes a const ARRAY
    # (llvm-undname prints 'const *const' for it). Declare as array [1].
    if sym["mangled"].startswith("?s_fd"):
        ty = ty.replace(" const* const", "").replace(" const *const", "").strip()
        return f"static {ty} const {name}[1];"
    return f"static {ty} {name};"


def render_abi_types_header() -> str:
    """The shared prelude: global-scope declarations + DirectUI forward
    declarations + small complete definitions needed for by-value ABI."""
    lines = [BANNER]
    lines.append("// Shared ABI prelude for the generated DirectUI headers.")
    lines.append("// Contains only what is required to reproduce the exact")
    lines.append("// decorated names of the real dui70.dll exports:")
    lines.append("//  * global-scope forward declarations (mangled without @2@)")
    lines.append("//  * namespace DirectUI forward declarations")
    lines.append("//  * minimal complete definitions for by-value types")
    lines.append("// NOTE: compiled with /Zc:wchar_t- like the baseline, so")
    lines.append("//       'const wchar_t*' == 'const unsigned short*' (UCString).")
    lines.append("#pragma once")
    lines.append("")
    lines.append("#ifndef DUI_ABI_TYPES_INCLUDED")
    lines.append("#define DUI_ABI_TYPES_INCLUDED")
    lines.append("")
    lines.append("#include <windows.h>")
    lines.append("")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// DirectUI string typedefs (ABI: unsigned short const*)")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("typedef unsigned short UChar;")
    lines.append("typedef UChar* UString;")
    lines.append("typedef const unsigned short* UCString;")
    lines.append("")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// Global-scope declarations (mangle WITHOUT the DirectUI back-reference)")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("struct tagGMSG;")
    lines.append("struct EventMsg;")
    lines.append("struct IAccessible;")
    lines.append("struct IDuiBehavior;")
    lines.append("struct ISharedBitmap;")
    lines.append("struct IStream;")
    lines.append("struct IUnknown;")
    lines.append("struct IXmlReader;")
    lines.append("struct HGADGET__;   // DECLARE_HANDLE(HGADGET) in the real headers")
    lines.append("typedef struct HGADGET__* HGADGET;")
    lines.append("")
    lines.append("// UID: returned by value by several static event-id accessors.")
    lines.append("// Decorated name in the real DLL is VUID@@ (GLOBAL scope), so it is")
    lines.append("// declared here at global scope -- NOT inside namespace DirectUI.")
    lines.append("class UID")
    lines.append("{")
    lines.append("public:")
    lines.append("    UID() {}")
    lines.append("    void* value;")
    lines.append("};")
    lines.append("")
    lines.append("// Compare a UID against an event-id ACCESSOR FUNCTION (called on the")
    lines.append("// spot). Lets consumer code write `ev->type == TouchButton::Click`")
    lines.append("// without call parentheses (baseline types.h compatibility).")
    lines.append("inline bool operator==(UID id, UID (*ev)(void))")
    lines.append("{")
    lines.append("    UID p = ev();")
    lines.append("    return id.value == p.value;")
    lines.append("}")
    lines.append("")
    lines.append("// DynamicScaleValue: GLOBAL-scope enum (W4DynamicScaleValue@@)")
    lines.append("enum DynamicScaleValue { DynamicScaleValue_None = 0 };")
    lines.append("")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// namespace DirectUI")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("namespace DirectUI")
    lines.append("{")
    lines.append("    // ---- complete definitions required for by-value parameters ----")
    lines.append("    struct LINEINFO { unsigned int line; };")
    lines.append("    struct ScaledSIZE { int w; int h; };")
    lines.append("    struct ScaledRECT { int l; int t; int r; int b; };")
    lines.append("")
    lines.append("    // ---- enums inside DirectUI ----")
    lines.append("    enum _DUI_PARSE_STATE { DUI_PARSE_STATE_None = 0 };")
    lines.append("    enum DynamicScaleParsing { DynamicScaleParsing_None = 0 };")
    lines.append("")
    lines.append("    // ---- class forward declarations ----")
    for name in sorted(DIRECTUI_CLASS_TYPES):
        lines.append(f"    class {name};")
    lines.append("")
    # ---- types referenced by the migration (5 extra) classes ----
    MIGRATION_EXTRA_TYPES = {
        "struct": ["IDialogElement", "IXBaby", "IXElementCP", "IXProviderCP"],
    }
    lines.append("    // ---- struct forward declarations ----")
    lines.append("    struct XMLParserCond;")
    for name in sorted(DIRECTUI_STRUCT_TYPES):
        if name in ("LINEINFO", "ScaledSIZE", "ScaledRECT"):
            continue
        lines.append(f"    struct {name};")
    for name in sorted(MIGRATION_EXTRA_TYPES["struct"]):
        lines.append(f"    struct {name};")
    lines.append("")
    lines.append("    // ---- enum for TouchCheckBox (W4CheckedStateFlags@2@) ----")
    lines.append("    enum CheckedStateFlags { CheckedStateFlags_None = 0 };")
    lines.append("")
    lines.append("    // ---- ValueType: consumer-side knowledge (enum members are never")
    lines.append("    // exported; shape transcribed from the baseline Value.h). Used by")
    lines.append("    // UITest in switch statements over Value::GetType(). ----")
    lines.append("    enum class ValueType : int")
    lines.append("    {")
    lines.append("        Unavailable = -2,")
    lines.append("        Unset = -1,")
    lines.append("        Null = 0,")
    lines.append("        Int = 1,")
    lines.append("        Bool = 2,")
    lines.append("        Element = 3,")
    lines.append("        Ellist = 4,")
    lines.append("        String = 5,")
    lines.append("        Point = 6,")
    lines.append("        Size = 7,")
    lines.append("        Rect = 8,")
    lines.append("        Color = 9,")
    lines.append("        Layout = 10,")
    lines.append("        Graphic = 11,")
    lines.append("        Sheet = 12,")
    lines.append("        Expr = 13,")
    lines.append("        Atom = 14,")
    lines.append("        Cursor = 15,")
    lines.append("        Float = 18,")
    lines.append("        DblList = 19,")
    lines.append("    };")
    lines.append("")
    lines.append("    // ---- ParserTools nested namespace ----")
    lines.append("    namespace ParserTools")
    lines.append("    {")
    lines.append("        struct ExprNode;")
    lines.append("        class ValueParser;")
    lines.append("    }")
    lines.append("")
    lines.append("    // ---- generic containers referenced by exported methods ----")
    lines.append("    // DynamicArray<T, N> is used as a plain (non-template) parameter")
    lines.append("    // type by several exported methods (CreateElementList etc.)")
    lines.append("    template <typename T, int N>")
    lines.append("    class DynamicArray;")
    lines.append("")
    lines.append("} // namespace DirectUI")
    lines.append("")
    lines.append("#endif // DUI_ABI_TYPES_INCLUDED")
    lines.append("")
    return "\n".join(lines)


def render_interfaces_header() -> str:
    """Consumer-side pure-abstract interfaces. These produce NO export
    symbols in the real DLL (they are consumed via vtable slots only), so
    they are transcribed from the baseline shape knowledge with slot order
    preserved -- the //N comments in the baseline are the vtable indices."""
    lines = [BANNER]
    lines.append("// Consumer-side interfaces: no exported symbols; vtable slot order")
    lines.append("// mirrors the real dui70.dll consumers (baseline Interfaces.h).")
    lines.append("#pragma once")
    lines.append("")
    lines.append("#include <windows.h>")
    lines.append('#include "dui_abi_types.h"')
    lines.append("")
    lines.append("namespace DirectUI")
    lines.append("{")
    lines.append("")
    lines.append("    // ---- forward declarations (interfaces reference these) ----")
    lines.append("    class Value;")
    lines.append("    class Element;")
    lines.append("    class HWNDElement;")
    lines.append("    class DUIXmlParser;")
    lines.append("")
    lines.append("    // PropertyInfo: property metadata record (pointer-only in ABI).")
    lines.append("    // cap->type is a ValueType bitfield (baseline Primitives.h).")
    lines.append("    struct PropertyInfo")
    lines.append("    {")
    lines.append("        UCString name;             // property name")
    lines.append("        unsigned __int64 unk1;")
    lines.append("        struct PropCapability")
    lines.append("        {")
    lines.append("            ValueType type : 6;")
    lines.append("            unsigned other : 26;")
    lines.append("            unsigned unk;")
    lines.append("        } *cap;")
    lines.append("        struct { UCString str_value; int int_value; } *enum_value_map;")
    lines.append("        Value* (*get_default_value)();")
    lines.append("        unsigned __int64 *unk2;")
    lines.append("    };")
    lines.append("")
    lines.append("    // ---- DUSER enums + Event/InputEvent (consumer-side; from baseline")
    lines.append("    // misc.h -- Event is dereferenced by UITest listeners) ----")
    lines.append("    enum DUSER_MSG_FLAG : unsigned int")
    lines.append("    {")
    lines.append("        GMF_DIRECT = 0x00000000,      // OnMessage")
    lines.append("        GMF_ROUTED = 0x00000001,      // PreviewMessage")
    lines.append("        GMF_BUBBLED = 0x00000002,     // PostMessage")
    lines.append("        GMF_EVENT = 0x00000003,       // Message -> Event")
    lines.append("        GMF_DESTINATION = 0x00000003, // Message reach dest")
    lines.append("    };")
    lines.append("")
    lines.append("    enum DUSER_INPUT_DEVICE : unsigned int")
    lines.append("    {")
    lines.append("        GINPUT_MOUSE = 0,")
    lines.append("        GINPUT_KEYBOARD = 1,")
    lines.append("        GINPUT_JOYSTICK = 2,")
    lines.append("    };")
    lines.append("")
    lines.append("    enum DUSER_INPUT_CODE : unsigned int")
    lines.append("    {")
    lines.append("        GMOUSE_MOVE = 0,")
    lines.append("        GMOUSE_DOWN = 1,")
    lines.append("        GMOUSE_UP = 2,")
    lines.append("        GMOUSE_DRAG = 3,")
    lines.append("        GMOUSE_HOVER = 4,")
    lines.append("        GMOUSE_WHEEL = 5,")
    lines.append("        GBUTTON_NONE = 0,")
    lines.append("        GBUTTON_LEFT = 1,")
    lines.append("        GBUTTON_RIGHT = 2,")
    lines.append("    };")
    lines.append("")
    lines.append("    enum DUSER_INPUT_MODIFIERS : unsigned int")
    lines.append("    {")
    lines.append("        GMODIFIER_NONE = 0,")
    lines.append("        GMODIFIER_LBUTTON = 0x0001,")
    lines.append("        GMODIFIER_RBUTTON = 0x0002,")
    lines.append("        GMODIFIER_SHIFT = 0x0004,")
    lines.append("        GMODIFIER_CONTROL = 0x0008,")
    lines.append("        GMODIFIER_MIDDLE = 0x0010,")
    lines.append("        GMODIFIER_LALT = 0x0020,")
    lines.append("        GMODIFIER_RALT = 0x0040,")
    lines.append("    };")
    lines.append("")
    lines.append("    struct Event")
    lines.append("    {")
    lines.append("        Element* target;")
    lines.append("        UID type;")
    lines.append("        bool handled;")
    lines.append("        DUSER_MSG_FLAG flag;")
    lines.append("    };")
    lines.append("")
    lines.append("    struct InputEvent")
    lines.append("    {")
    lines.append("        Element* target;")
    lines.append("        bool handled;")
    lines.append("        DUSER_MSG_FLAG flag;")
    lines.append("        DUSER_INPUT_DEVICE device;")
    lines.append("        DUSER_INPUT_CODE code;")
    lines.append("        DUSER_INPUT_MODIFIERS modifiers;")
    lines.append("    };")
    lines.append("")
    lines.append("    // CClassFactory: opaque handle type used by UITest's Register hook")
    lines.append("    // (the real implementation is internal to dui70.dll).")
    lines.append("    struct CClassFactory;")
    lines.append("")
    lines.append("    struct IElementListener")
    lines.append("    {")
    lines.append("    public:")
    lines.append("        // slot 0")
    lines.append("        virtual void OnListenerAttach(Element* elem) = 0;")
    lines.append("        // slot 1")
    lines.append("        virtual void OnListenerDetach(Element* elem) = 0;")
    lines.append("        // slot 2 -- returns false to cancel")
    lines.append("        virtual bool OnPropertyChanging(Element* elem, PropertyInfo const* prop, int unk, Value* before, Value* after) = 0;")
    lines.append("        // slot 3")
    lines.append("        virtual void OnListenedPropertyChanged(Element* elem, PropertyInfo const* prop, int type, Value* before, Value* after) = 0;")
    lines.append("        // slot 4")
    lines.append("        virtual void OnListenedInput(Element* elem, InputEvent* event) = 0;")
    lines.append("        // slot 5")
    lines.append("        virtual void OnListenedEvent(Element* elem, Event* event) = 0;")
    lines.append("    };")
    lines.append("")
    lines.append("    struct IClassInfo")
    lines.append("    {")
    lines.append("        IClassInfo() {}")
    lines.append("        IClassInfo(const IClassInfo&) = delete;")
    lines.append("        IClassInfo& operator=(const IClassInfo&) = delete;")
    lines.append("        virtual ~IClassInfo() {}")
    lines.append("")
    lines.append("    public:")
    lines.append("        // slots follow the baseline order (AddRef..AssertPIZeroRef,")
    lines.append("        // then the deleting dtor)")
    lines.append("        virtual long AddRef(void) = 0;                                   // 0")
    lines.append("        virtual long Release(void) = 0;                                 // 1")
    lines.append("        virtual long CreateInstance(Element*, unsigned long*, Element**) = 0;  // 2")
    lines.append("        virtual PropertyInfo* EnumPropertyInfo(unsigned int) = 0;       // 3")
    lines.append("        virtual PropertyInfo* GetByClassIndex(unsigned int) = 0;        // 4")
    lines.append("        virtual unsigned int GetPICount(void) = 0;                     // 5")
    lines.append("        virtual unsigned int GetGlobalIndex(void) = 0;                 // 6")
    lines.append("        virtual IClassInfo* GetBaseClass(void) = 0;                    // 7")
    lines.append("        virtual UCString GetName(void) = 0;                            // 8")
    lines.append("        virtual bool IsValidProperty(PropertyInfo const*) = 0;        // 9")
    lines.append("        virtual bool IsSubclassOf(IClassInfo*) = 0;                   // 10")
    lines.append("        virtual void Destroy(void) = 0;                               // 11")
    lines.append("        virtual HINSTANCE GetModule(void) = 0;                        // 12")
    lines.append("        virtual bool IsGlobal(void) = 0;                              // 13")
    lines.append("        virtual void AddChild(void) = 0;                              // 14")
    lines.append("        virtual void RemoveChild(void) = 0;                           // 15")
    lines.append("        virtual unsigned int GetChildren(void) = 0;                   // 16")
    lines.append("        virtual void AssertPIZeroRef(void) = 0;                       // 17")
    lines.append("    };")
    lines.append("")
    lines.append("    // IXProviderCP / IXElementCP: connection-point interfaces used by")
    lines.append("    // XProvider (vtable slot order from the baseline).")
    lines.append("    class IXProviderCP")
    lines.append("    {")
    lines.append("    public:")
    lines.append("        virtual long CreateDUICP(HWNDElement*, HWND, HWND, Element**, DUIXmlParser**) = 0;")
    lines.append("        virtual long CreateParserCP(DUIXmlParser**) = 0;")
    lines.append("        virtual void DestroyCP(void) = 0;")
    lines.append("    };")
    lines.append("")
    lines.append("    class IXElementCP")
    lines.append("    {")
    lines.append("    public:")
    lines.append("        virtual HWND GetNotificationSinkHWND(void) = 0;")
    lines.append("    };")
    lines.append("")
    lines.append("    // IXProvider: the abstract interface XProvider implements.")
    lines.append("    // Slot order: IUnknown first (QI/AddRef/Release), then the")
    lines.append("    // provider methods in baseline order. On x64 the real methods")
    lines.append("    // are all __cdecl; the __stdcall markers in the baseline are")
    lines.append("    // ignored by the x64 compiler, so we use the default here too.")
    lines.append("    class IXProvider : public IUnknown")
    lines.append("    {")
    lines.append("    public:")
    lines.append("        virtual long CreateDUI(IXElementCP*, HWND*) = 0;")
    lines.append("        virtual long SetParameter(GUID const&, void*) = 0;")
    lines.append("        virtual long GetDesiredSize(int, int, SIZE*) = 0;")
    lines.append("        virtual long IsDescendent(Element*, bool*) = 0;")
    lines.append("        virtual long SetFocus(Element*) = 0;")
    lines.append("        virtual long Navigate(int, bool*) = 0;")
    lines.append("        virtual long CanSetFocus(bool*) = 0;")
    lines.append("        virtual int FindElementWithShortcutAndDoDefaultAction(unsigned short, int) = 0;")
    lines.append("        virtual long GetHostedElementID(unsigned short*) = 0;")
    lines.append("        virtual long ForceThemeChange(UINT_PTR, LONG_PTR) = 0;")
    lines.append("        virtual long SetDefaultButtonTracking(bool) = 0;")
    lines.append("        virtual int ClickDefaultButton(void) = 0;")
    lines.append("        virtual long SetRegisteredDefaultButton(Element*) = 0;")
    lines.append("        virtual long SetButtonClassAcceptsEnterKey(bool) = 0;")
    lines.append("    };")
    lines.append("")
    lines.append("} // namespace DirectUI")
    lines.append("")
    return "\n".join(lines)


def render_extern_c_block(classes: list) -> str:
    """extern "C" declarations for the plain-named C API exports.
    The real DLL exports these as undecorated C symbols; declaring them
    extern \"C\" produces exactly the same symbol shape for the linker.
    Signatures come from UITest usage + baseline knowledge (the export
    table only carries the plain name)."""
    lines = []
    lines.append("")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// extern \"C\" API -- plain-name exports of the real dui70.dll.")
    lines.append("// Signatures from UITest usage + baseline declarations; the export table")
    lines.append("// itself only carries the undecorated name.")
    lines.append("// TODO: remaining ~80 plain-name exports (incl. DUI70_XXX-prefixed")
    lines.append("// whose signatures are not yet recovered) are not declared here.")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append('extern "C" {')
    lines.append("")
    lines.append("HRESULT WINAPI InitProcessPriv(int duiVersion, unsigned short* unk1, char unk2, bool bEnableUIAutomationProvider);")
    lines.append("HRESULT WINAPI UnInitProcessPriv(unsigned short* unk1);")
    lines.append("HRESULT WINAPI InitThread(int iDontKnow);")
    lines.append("int WINAPI RegisterAllControls();")
    lines.append("int WINAPI StartMessagePump();")
    lines.append("ATOM WINAPI StrToID(UCString resId);")
    lines.append("")
    lines.append("} // extern \"C\"")

    # Decorated free functions (real exports, global scope, C++ mangling).
    # DumpDuiTree is consumed by UITest.
    lines.append("")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("// Free functions -- decorated exports of the real dui70.dll")
    lines.append("// (mangled ?Name@@YA...; NOT extern \"C\").")
    lines.append("// ---------------------------------------------------------------------------")
    lines.append("void __cdecl DumpDuiTree(DirectUI::Element* element, int depth);")
    return "\n".join(lines)


def render_aggregate_header(classes: list | None = None) -> str:
    classes = classes or TARGET_CLASSES
    lines = [BANNER]
    n = len(classes)
    lines.append(f"// Aggregate header for the {n} UITest-required classes.")
    lines.append("#pragma once")
    lines.append("")
    lines.append('#include "dui_abi_types.h"')
    lines.append('#include "Interfaces.h"')
    for cls in classes:
        lines.append(f'#include "{cls}.h"')
    # extern "C" API block at the end (needs UCString from dui_abi_types.h)
    lines.append(render_extern_c_block(classes))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--classes", default=",".join(TARGET_CLASSES))
    args = ap.parse_args(argv)

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = load_symbols(args.symbols)
    # merge in fn-pointer methods the symbols module mis-parsed as data
    symbols += recover_fnptr_methods(symbols, set(classes))
    tr = TypeTranslator(classes)

    stats = {}
    for cls in classes:
        members = [s for s in symbols
                   if s.get("class") == cls
                   and s.get("namespace") == "DirectUI"
                   and is_callable(s)]
        data_members = [s for s in symbols
                        if s.get("class") == cls
                        and is_data(s)]
        content = render_class_header(cls, members, data_members, tr, classes)
        (out_dir / f"{cls}.h").write_text(content, encoding="utf-8", newline="\n")
        stats[cls] = {"methods": len(members), "data": len(data_members)}

    # shared prelude + interfaces + aggregate
    (out_dir / "dui_abi_types.h").write_text(render_abi_types_header(), encoding="utf-8", newline="\n")
    (out_dir / "Interfaces.h").write_text(render_interfaces_header(), encoding="utf-8", newline="\n")
    (out_dir / "DirectUI.h").write_text(render_aggregate_header(classes), encoding="utf-8", newline="\n")

    print(f"emit_headers: wrote {len(classes) + 3} files to {out_dir}")
    for cls in classes:
        s = stats[cls]
        print(f"  {cls:<16} callables={s['methods']:4d} data={s['data']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
