"""pe-digest.py -- derive the A2 anchor for the ChildrenView fixture.

WHY THIS EXISTS (and why the naive A2 could not work)
=====================================================
The original A2 spec was: "sha256 over the loaded image's SizeOfImage range ==
pinned/manifest.json dll.sha256". That is impossible, and not because of a bug
in our code. Measured on the real pinned DLL:

  1. SizeOfImage = 0x1AA000 but the file is only 0x1A7000 bytes. The mapped
     image range therefore includes 0x3000 bytes that have no on-disk
     counterpart, so the two ranges can never be equal.

  2. The loader WRITES to the mapped image: it patches the import address
     table and delay-load import table (both of which live in .rdata for this
     DLL). Those sections can never equal their file bytes.

  3. The values written in (2) are addresses of OTHER modules, which are
     themselves relocated per run. So sha256(image[0..SizeOfImage)) differs on
     every single run even when dui70 lands at the same base. Measured across 5
     runs at identical base 0x...6D270000: five different hashes.

So A2 as literally written cannot be satisfied by any implementation. What it
was REACHING FOR -- "prove the loaded module is the pinned file, not the
System32 one" -- is achievable with a sound anchor:

  .text is the anchor.
    * no relocation targets .text (verified: 11619 reloc entries, all in
      .rdata/.didat/.data), so it is REBASE-INVARIANT; and
    * the loader never writes to it, so the loaded bytes equal the file bytes.
    * it DIFFERS between the pinned DLL and the System32 DLL, so it
      discriminates -- which is the whole point.

This script derives that anchor from a manifest-verified DLL so the runtime
probe never has to re-read the DLL: the probe hashes the LOADED .text and
compares it against the value emitted here. The disk read happens once, here,
as derivation -- not as the runtime assertion.
"""

import argparse
import hashlib
import json
import pathlib
import struct
import sys

RELOC_DIR_INDEX = 5
TEXT_NAME = ".text"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def parse_pe(path):
    d = pathlib.Path(path).read_bytes()
    if len(d) < 0x40:
        raise ValueError("file too small to be a PE: %s" % path)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        raise ValueError("missing PE signature: %s" % path)
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", d, opt)[0]
    if magic != 0x20B:
        raise ValueError("expected PE32+ (x64); magic=%04X" % magic)
    ndir = struct.unpack_from("<I", d, opt + 0x6C)[0]
    dirs = [struct.unpack_from("<II", d, opt + 0x70 + 8 * i) for i in range(ndir)]
    sizeofimage = struct.unpack_from("<I", d, opt + 0x38)[0]

    secoff = opt + optsz
    secs = []
    for i in range(nsec):
        o = secoff + 40 * i
        name = d[o:o + 8].rstrip(b"\0").decode("latin1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, o + 8)
        secs.append(dict(name=name, va=vaddr, vsize=vsize,
                         rawsize=rawsize, rawptr=rawptr))
    return dict(data=d, secs=secs, dirs=dirs, sizeofimage=sizeofimage)


def section_bytes(pe, name):
    for s in pe["secs"]:
        if s["name"] == name:
            return pe["data"][s["rawptr"]:s["rawptr"] + s["rawsize"]], s
    raise ValueError("section %s not found" % name)


def reloc_target_census(pe):
    """Count base-relocation targets per section.

    The reloc directory's DataDirectory RVA is a VIRTUAL address and must be
    translated to a file offset before reading -- reading it as an offset walks
    into unrelated bytes and silently reports zero entries.
    """
    if len(pe["dirs"]) <= RELOC_DIR_INDEX:
        return {}, 0
    rva, size = pe["dirs"][RELOC_DIR_INDEX]
    if rva == 0 or size == 0:
        return {}, 0

    def rva_to_off(r):
        for s in pe["secs"]:
            if s["va"] <= r < s["va"] + max(s["vsize"], s["rawsize"]):
                return s["rawptr"] + (r - s["va"])
        return r

    d = pe["data"]
    start = rva_to_off(rva)
    counts, total, off = {}, 0, 0
    while off + 8 <= size:
        page, bsize = struct.unpack_from("<II", d, start + off)
        if bsize < 8 or off + bsize > size:
            break
        for k in range((bsize - 8) // 2):
            ent = struct.unpack_from("<H", d, start + off + 8 + 2 * k)[0]
            if (ent >> 12) == 0:  # IMAGE_REL_BASED_ABSOLUTE is padding
                continue
            target = page + (ent & 0xFFF)
            nm = "?"
            for s in pe["secs"]:
                if s["va"] <= target < s["va"] + max(s["vsize"], s["rawsize"]):
                    nm = s["name"]
                    break
            counts[nm] = counts.get(nm, 0) + 1
            total += 1
        off += bsize
    return counts, total


def dir_section(pe, index):
    """Which section does a data directory live in? Returns (name, rva, size)."""
    if len(pe["dirs"]) <= index:
        return None, 0, 0
    rva, size = pe["dirs"][index]
    if rva == 0 or size == 0:
        return None, 0, 0
    for s in pe["secs"]:
        if s["va"] <= rva < s["va"] + max(s["vsize"], s["rawsize"]):
            return s["name"], rva, size
    return "?", rva, size


def text_digest(path):
    pe = parse_pe(path)
    raw, sec = section_bytes(pe, TEXT_NAME)
    return hashlib.sha256(raw).hexdigest().upper(), sec


def cmd_text_sha(args):
    digest, sec = text_digest(args.dll)
    print(digest)
    return 0


def cmd_discriminate(args):
    a, sa = text_digest(args.pinned)
    b, sb = text_digest(args.system32)
    print("pinned   .text sha256 = %s  (rawsize %X)" % (a, sa["rawsize"]))
    print("system32 .text sha256 = %s  (rawsize %X)" % (b, sb["rawsize"]))
    if a == b:
        print("FAIL: .text is identical in both DLLs -- an A2 anchored on .text "
              "could NOT tell them apart, so A2 would be vacuous.")
        return 1
    print("OK: .text discriminates pinned from System32 (A2 has teeth)")
    return 0


def cmd_derive(args):
    dll = pathlib.Path(args.dll)
    if not dll.is_file():
        print("FAIL: pinned DLL not found: %s" % dll)
        return 1

    # 1. anchor to the manifest: the file we derive from must BE the pinned file
    manifest = json.loads(pathlib.Path(args.manifest).read_text(encoding="utf-8"))
    want = manifest["dll"]["sha256"].upper()
    got = sha256_file(dll)
    print("manifest dll.sha256 = %s" % want)
    print("derived  file sha256= %s" % got)
    if got != want:
        print("FAIL: the DLL being derived from is NOT the pinned one. "
              "Refusing to emit an anchor that would bless the wrong file.")
        return 1

    # 2. the anchor is only sound if .text is rebase-invariant
    pe = parse_pe(dll)
    counts, total = reloc_target_census(pe)
    print("relocation entries  = %d" % total)
    for k in sorted(counts):
        print("    targets in %-8s : %d" % (k, counts[k]))
    if TEXT_NAME in counts:
        print("FAIL: %d relocation target(s) fall inside %s. %s is therefore NOT "
              "rebase-invariant and hashing the loaded %s against the file would "
              "be UNSOUND. Refusing to emit this anchor."
              % (counts[TEXT_NAME], TEXT_NAME, TEXT_NAME, TEXT_NAME))
        return 1
    if total == 0:
        print("NOTE: no relocation entries at all; rebase-invariance still holds")

    # 2b. state WHY a whole-image hash is not used, so nobody "simplifies" this
    #     back into the unsatisfiable form. Both conditions are re-measured here
    #     rather than asserted from memory.
    file_size = len(pe["data"])
    print("\nwhy not a whole-image SizeOfImage hash:")
    print("  SizeOfImage    = %X" % pe["sizeofimage"])
    print("  file size      = %X" % file_size)
    if pe["sizeofimage"] > file_size:
        print("  -> image range exceeds the file by %X bytes that have no file "
              "counterpart, so image==file is structurally impossible"
              % (pe["sizeofimage"] - file_size))
    for idx, label in ((1, "import (IAT)"), (13, "delay import")):
        nm, rva, size = dir_section(pe, idx)
        if nm:
            print("  %-14s lives in %-8s -> the loader patches it in memory, so "
                  "it can never match the file" % (label, nm))

    # 3. emit the anchor the probe compares against
    tsha, tsec = text_digest(dll)
    print("\nANCHOR (A2): loaded %s sha256 must equal" % TEXT_NAME)
    print("  %s" % tsha)
    print("  (%s rawsize %X, virtualsize %X)"
          % (TEXT_NAME, tsec["rawsize"], tsec["vsize"]))

    out = pathlib.Path(args.out_header)
    out.parent.mkdir(parents=True, exist_ok=True)
    esc_dir = str(pathlib.Path(args.expect_dir)).replace("\\", "\\\\")
    out.write_text(
        "// GENERATED by tools/dui-pipeline/pe-digest.py -- DO NOT EDIT.\n"
        "//\n"
        "// A2 anchor for the ChildrenView pin check. Derived from a DLL whose\n"
        "// whole-file sha256 was asserted equal to pinned/manifest.json, so the\n"
        "// runtime probe never re-reads the DLL: it hashes the LOADED .text and\n"
        "// compares it to W1_EXPECTED_TEXT_SHA256 below. See pe-digest.py for why\n"
        "// a whole-image SizeOfImage hash cannot be used instead.\n"
        "#pragma once\n"
        "\n"
        "#define W1_EXPECTED_DLL_SHA256 \"%s\"\n"
        "#define W1_EXPECTED_TEXT_SHA256 \"%s\"\n"
        "#define W1_EXPECTED_DLL_DIR L\"%s\"\n"
        % (got, tsha, esc_dir),
        encoding="ascii", newline="\n")
    print("\nwrote %s" % out)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("derive", help="assert manifest + emit the A2 anchor header")
    d.add_argument("--dll", required=True)
    d.add_argument("--manifest", required=True)
    d.add_argument("--out-header", required=True)
    d.add_argument("--expect-dir", required=True)
    d.set_defaults(func=cmd_derive)

    t = sub.add_parser("text-sha", help="print a DLL's .text sha256")
    t.add_argument("--dll", required=True)
    t.set_defaults(func=cmd_text_sha)

    c = sub.add_parser("discriminate",
                       help="assert .text differs between pinned and System32")
    c.add_argument("--pinned", required=True)
    c.add_argument("--system32", required=True)
    c.set_defaults(func=cmd_discriminate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
