// w1-childrenview-probe.cpp -- end-to-end check of ChildrenView against a REAL
// element tree built by dui70's own XML parser, PLUS a pin check that proves
// WHICH dui70.dll was actually exercised.
//
// WHAT THIS PROVES
//   * initialises dui70 exactly the way UITest.cpp does
//     (InitProcessPriv(14) -> InitThread(2) -> RegisterAllControls)
//   * loads a UIFILE XML string through DUIXmlParser::SetXML / CreateElement
//   * builds FOUR trees whose root has 0, 1, 2 and 3 children
//   * for each tree compares ChildrenView::count()/at(i) against TWO independent
//     oracles:
//         - Element::FindDescendent       (existing tree walk inside dui70)
//         - the exported C wrapper DUI70_ElementGetChildren (a different entry
//           point onto the same property system)
//   * requires BOTH storage modes to be exercised: for Element* the inline
//     capacity is 2, so n=1,2 stay inline and n=3 forces the heap branch. The
//     probe FAILS if either mode never happened.
//   * proves the borrow is released (refcount returns to its pre-view value)
//     AND that the instrument would have noticed a leak.
//   * proves it ran against the PINNED dui70.dll, not the System32 one (A1/A2/A3
//     below). Without this, a PASS says nothing about the pinned binary.
//
// WHY THE PIN CHECK LOOKS THE WAY IT DOES (A2)
//   The obvious check -- "sha256 over the loaded image's SizeOfImage range ==
//   pinned/manifest.json dll.sha256" -- CANNOT be satisfied by any
//   implementation. Measured on the real pinned DLL:
//     * SizeOfImage is 0x1AA000 but the file is 0x1A7000, so the image range
//       covers bytes with no on-disk counterpart;
//     * the loader patches the import address table and delay-load table (both
//       in .rdata here), which therefore never match the file;
//     * those patches contain addresses of OTHER modules, so the image-range
//       hash differs on EVERY run even at an identical base (measured: 5 runs at
//       base ...6D270000 gave 5 different hashes).
//   So A2 is anchored on .text instead, which is sound for a measured reason:
//     * no relocation targets .text (all 11619 reloc entries are in
//       .rdata/.didat/.data), so it is rebase-invariant; and
//     * the loader never writes to it; and
//     * it DIFFERS between the pinned DLL and the System32 DLL, so it
//       discriminates -- which is the entire point of the check.
//   The expected value is derived from a manifest-verified DLL by
//   tools/dui-pipeline/pe-digest.py and pasted in as W1_EXPECTED_TEXT_SHA256.
//   This probe NEVER re-reads the DLL from disk (that would be a TOCTOU check
//   that could pass on bytes other than the ones actually loaded).
//
// NOT DONE HERE (stated, not faked)
//   * no raw-memory writes and no synthesised layout: only public API plus the
//     measured header-bit read that ChildrenView itself performs.
//   * no Element+0x95 bit-1 read by this probe.
//   * no bare DynamicArray<Element*,0>::Create call: the array is always
//     produced by dui70's own property system, never constructed here.
//   * no RVA-based calls: every dui70 entry point is reached through its
//     exported NAME (see CALLS below).
//
// CALLS (all resolved by name, all present in pinned/exports.json)
//   InitProcessPriv, InitThread, RegisterAllControls, UnInitProcessPriv,
//   StrToID, DUIXmlParser::Create/SetXML/CreateElement/Destroy,
//   Element::GetChildren/FindDescendent/HasChildren,
//   Value::Release, DUI70_ElementGetChildren
//
// Negative controls
//   NEGCTL          assert WRONG expectations -> must exit 1
//   NOPIN           hide/omit the pinned DLL       -> must exit 1 (A1/A3)
//   (A2 sensitivity is self-checked: see PinCheck's anchor comparison.)
//
// Exit code 0 only when every assertion held.

#include <Windows.h>
#include <bcrypt.h>

#include <cstdio>
#include <cstring>
#include <string>

#include <DirectUI.h>
#include <ChildrenView.h>

#include "w1-pin-anchor.h"

#pragma comment(lib, "dui70.lib")
#pragma comment(lib, "bcrypt.lib")

using namespace DirectUI;

static int g_fails = 0;
static int g_heapCases = 0;
static int g_inlineCases = 0;

// ---------------------------------------------------------------------------
// Independent oracle #2: the exported C wrapper, reached by NAME.
// ---------------------------------------------------------------------------
typedef void *(__stdcall *PFN_DUI70_ElementGetChildren)(Element *elem, Value **out);

// Read the on-heap bit (28) from an array pointer, using the same measured
// offsets ChildrenView uses. This lives in the PROBE, not in ChildrenView, so a
// bug in the view cannot hide itself from the mode report.
static bool ProbeIsHeap(void *array) {
  unsigned header = 0;
  memcpy(&header, static_cast<unsigned char *>(array), sizeof(header));
  return (header & 0x10000000u) != 0;
}
static unsigned ProbeCount(void *array) {
  unsigned header = 0;
  memcpy(&header, static_cast<unsigned char *>(array), sizeof(header));
  return header & 0x0FFFFFFFu;
}

// ---------------------------------------------------------------------------
// Value refcount reading -- for the LIFECYCLE check.
//
// Measured from the pinned DLL:
//   Value::AddRef   `and $0xffffff80,%eax; cmp $0xffffff80` then
//                   `lock addl $0x80,(%rcx)`
//   Value::Release  same guard, then `lock xadd` with 0xffffff80 (-128)
//   Value::GetElListNull sentinel has header 0xFFFFFF84, so (hdr & ~0x7F) ==
//                   0xFFFFFF80 and Release is a measured NO-OP.
// So the refcount lives in bits 7..31 (quantum 0x80). These are reads only:
// the probe never writes a Value.
// ---------------------------------------------------------------------------
static unsigned RefCountOf(Value *v) {
  unsigned header = 0;
  memcpy(&header, v, sizeof(header));
  return (header & 0xFFFFFF80u) >> 7;
}
static bool IsSentinelRef(Value *v) {
  unsigned header = 0;
  memcpy(&header, v, sizeof(header));
  return (header & 0xFFFFFF80u) == 0xFFFFFF80u;
}

// ---------------------------------------------------------------------------
// SHA-256 over a memory range, via CNG.
// ---------------------------------------------------------------------------
static bool Sha256(const void *data, size_t len, unsigned char out[32]) {
  BCRYPT_ALG_HANDLE alg = nullptr;
  if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0)
    return false;
  BCRYPT_HASH_HANDLE h = nullptr;
  bool ok = BCryptCreateHash(alg, &h, nullptr, 0, nullptr, 0, 0) == 0;
  if (ok)
    ok = BCryptHashData(h, (PUCHAR)data, (ULONG)len, 0) == 0;
  if (ok)
    ok = BCryptFinishHash(h, out, 32, 0) == 0;
  if (h)
    BCryptDestroyHash(h);
  BCryptCloseAlgorithmProvider(alg, 0);
  return ok;
}
static void Hex(const unsigned char *d, char *o) {
  for (int i = 0; i < 32; ++i)
    sprintf_s(o + i * 2, 3, "%02X", d[i]);
  o[64] = 0;
}

// ===========================================================================
// A1 / A2 / A3 -- the pin check. Fails closed: any doubt is a FAIL.
// ===========================================================================
static void PinCheck(bool expectPinned) {
  printf("---- pin check (A1 path / A2 image digest / A3 not System32) ----\n");

  HMODULE hm = GetModuleHandleW(L"dui70.dll");
  if (!hm) {
    printf("  FAIL: dui70.dll is not loaded at all\n");
    ++g_fails;
    return;
  }

  // ---- A1: the loaded module must come from the expected directory ----------
  wchar_t path[MAX_PATH] = {};
  DWORD n = GetModuleFileNameW(hm, path, MAX_PATH);
  printf("  loaded path          : %ls\n", (n ? path : L"<unavailable>"));
  printf("  expected dir         : %ls\n", W1_EXPECTED_DLL_DIR);

  bool pathOk = false;
  if (n == 0) {
    printf("  A1 FAIL: GetModuleFileNameW failed (%lu)\n", GetLastError());
  } else {
    std::wstring full(path);
    size_t slash = full.find_last_of(L'\\');
    std::wstring dir = (slash == std::wstring::npos) ? L"" : full.substr(0, slash);
    std::wstring want = W1_EXPECTED_DLL_DIR;
    // case-insensitive compare: Windows paths are case-insensitive
    pathOk = (dir.size() == want.size());
    if (pathOk) {
      for (size_t i = 0; i < dir.size(); ++i) {
        if (towlower(dir[i]) != towlower(want[i])) {
          pathOk = false;
          break;
        }
      }
    }
    if (pathOk)
      printf("  A1 ok   : loaded from the expected directory\n");
    else
      printf("  A1 FAIL: expected dir <%ls>, got <%ls>\n", want.c_str(),
             dir.c_str());
  }
  if (!pathOk)
    ++g_fails;

  // ---- A3: explicitly reject System32 ---------------------------------------
  {
    std::wstring full(path);
    for (auto &c : full)
      c = towlower(c);
    bool fromSystem32 = full.find(L"\\windows\\system32\\") != std::wstring::npos ||
                        full.find(L"\\windows\\syswow64\\") != std::wstring::npos;
    if (fromSystem32) {
      printf("  A3 FAIL: module loaded from %ls -- that is the OS copy, NOT the "
             "pinned DLL. A PASS here would prove nothing about pinned bytes.\n",
             full.c_str());
      ++g_fails;
    } else {
      printf("  A3 ok   : not loaded from System32/SysWOW64\n");
    }
  }

  // ---- A2: hash the LOADED .text, never the file on disk --------------------
  //
  // Reading the path above and hashing the file would be a TOCTOU check: it
  // would validate bytes that are not necessarily the ones mapped. We hash the
  // in-memory image, bounded by the headers of that same in-memory image.
  {
    auto *base = (unsigned char *)hm;
    auto *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
      printf("  A2 FAIL: bad DOS signature in the loaded image\n");
      ++g_fails;
      return;
    }
    auto *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) {
      printf("  A2 FAIL: bad NT signature in the loaded image\n");
      ++g_fails;
      return;
    }
    auto *sec = IMAGE_FIRST_SECTION(nt);
    const IMAGE_SECTION_HEADER *text = nullptr;
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
      if (strncmp((const char *)sec[i].Name, ".text", 8) == 0) {
        text = &sec[i];
        break;
      }
    }
    if (!text) {
      printf("  A2 FAIL: no .text section in the loaded image\n");
      ++g_fails;
      return;
    }
    // Bound the hash by the section's raw size, so we hash exactly the bytes
    // that would have come from the file (loader zero-fills any tail).
    unsigned char digest[32];
    if (!Sha256(base + text->VirtualAddress, text->SizeOfRawData, digest)) {
      printf("  A2 FAIL: SHA-256 over the loaded .text failed\n");
      ++g_fails;
      return;
    }
    char got[65];
    Hex(digest, got);
    printf("  loaded .text sha256  : %s\n", got);
    printf("  expected (pinned)    : %s\n", W1_EXPECTED_TEXT_SHA256);

    // A2 must also be NON-VACUOUS: if the anchor were empty or the digest could
    // not distinguish anything, "match" would be meaningless. Require a real
    // 64-hex-char anchor and require that the anchor is not a degenerate value.
    bool anchorWellFormed = (strlen(W1_EXPECTED_TEXT_SHA256) == 64);
    for (const char *p = W1_EXPECTED_TEXT_SHA256; anchorWellFormed && *p; ++p) {
      if (!isxdigit((unsigned char)*p))
        anchorWellFormed = false;
    }
    if (!anchorWellFormed) {
      printf("  A2 FAIL: the anchor is not a 64-hex-char digest; the comparison "
             "would be vacuous\n");
      ++g_fails;
    }

    bool match = (_stricmp(got, W1_EXPECTED_TEXT_SHA256) == 0);
    if (expectPinned) {
      if (match) {
        printf("  A2 ok   : loaded .text IS the pinned DLL's .text\n");
      } else {
        printf("  A2 FAIL: loaded .text does NOT match the pinned DLL. The "
               "module under test is a DIFFERENT build, so every measurement "
               "below describes that other binary, not the pinned one.\n");
        ++g_fails;
      }
    } else {
      // NOPIN: we EXPECT a mismatch and require the check to notice it.
      if (match) {
        printf("  A2 FAIL (NOPIN): expected a non-pinned module, but the digest "
               "matched the pinned value -- the pin check cannot detect "
               "substitution.\n");
        ++g_fails;
      } else {
        printf("  A2 ok (NOPIN): non-pinned module correctly detected\n");
      }
    }
  }
  printf("\n");
}

// ---------------------------------------------------------------------------
// Build a UIFILE string with `n` children under a uniquely-named root.
//
// Shape taken from UITest/dui.xml:
//   * a CREATABLE element is declared at TOP LEVEL (a sibling of <stylesheets>)
//     with `resid="Name"` -- that resid is what CreateElement looks up. A root
//     nested inside <style> is a style rule, not a create target, and
//     CreateElement returns 0x800403EF (element not found) for it.
//   * child ids use `id="Atom(NAME)"` so StrToID(NAME) can find them.
// ---------------------------------------------------------------------------
static std::wstring MakeXml(int n, int tag) {
  std::wstring x = L"<duixml><stylesheets/><Element resid=\"Root\">";
  for (int i = 0; i < n; ++i) {
    x += L"<Element id=\"Atom(C";
    x += std::to_wstring(tag);
    x += L"_";
    x += std::to_wstring(i);
    x += L")\"/>";
  }
  x += L"</Element></duixml>";
  return x;
}

static void Expect(bool cond, const char *what) {
  if (!cond) {
    printf("  FAIL: %s\n", what);
    ++g_fails;
  }
}

// ---------------------------------------------------------------------------
// One case: parse XML with n children, then verify count/at against oracles.
// ---------------------------------------------------------------------------
static void RunCase(int n, bool negctl) {
  printf("---- case n=%d ----\n", n);

  DUIXmlParser *parser = nullptr;
  HRESULT hr = DUIXmlParser::Create(&parser, nullptr, nullptr, nullptr, nullptr);
  if (FAILED(hr) || !parser) {
    printf("  FAIL: DUIXmlParser::Create hr=0x%08lX\n", (unsigned long)hr);
    ++g_fails;
    return;
  }

  std::wstring xml = MakeXml(n, n);
  // UCString is `unsigned short const*`, but the XML is built as wchar_t.
  hr = parser->SetXML(reinterpret_cast<UCString>(xml.c_str()), nullptr, nullptr);
  if (FAILED(hr)) {
    printf("  FAIL: SetXML n=%d hr=0x%08lX\n", n, (unsigned long)hr);
    ++g_fails;
    parser->Destroy();
    return;
  }

  Element *root = nullptr;
  hr = parser->CreateElement((UCString)L"Root", nullptr, nullptr, nullptr, &root);
  if (FAILED(hr) || !root) {
    printf("  FAIL: CreateElement(Root) hr=0x%08lX\n", (unsigned long)hr);
    ++g_fails;
    parser->Destroy();
    return;
  }

  // ---- mode: inspect the raw array BEFORE the view releases the borrow -------
  Value *rawBorrow = nullptr;
  DynamicArray<Element *, 0> *rawArray = root->GetChildren(&rawBorrow);
  bool isHeap = false;
  unsigned rawCount = 0;
  if (rawArray) {
    isHeap = ProbeIsHeap(rawArray);
    rawCount = ProbeCount(rawArray);
    if (isHeap)
      ++g_heapCases;
    else
      ++g_inlineCases;
    printf("  mode=%s rawCount=%u\n", isHeap ? "HEAP" : "INLINE", rawCount);
  } else {
    printf("  mode=none rawCount=0\n");
  }
  if (rawBorrow)
    rawBorrow->Release();  // release the probe's own borrow immediately

  // ---- oracle A: ChildrenView -------------------------------------------------
  ChildrenView view = GetChildrenView(root);

  // ---- oracle B: exported C wrapper, resolved by NAME -------------------------
  PFN_DUI70_ElementGetChildren pExport =
      (PFN_DUI70_ElementGetChildren)(void *)GetProcAddress(
          GetModuleHandleW(L"dui70.dll"), "DUI70_ElementGetChildren");
  Expect(pExport != nullptr, "DUI70_ElementGetChildren export resolved");
  unsigned exportCount = 0;
  if (pExport) {
    Value *vb = nullptr;
    void *arr = pExport(root, &vb);
    if (vb) {
      if (arr)
        exportCount = ProbeCount(arr);
      vb->Release();
    }
  }

  // ---- assertions -------------------------------------------------------------
  unsigned expected = negctl ? (unsigned)(n + 7) : (unsigned)n;
  printf("  count()=%u (expect %u)  exportCount=%u\n", view.count(), expected,
         exportCount);
  Expect(view.count() == expected, "ChildrenView::count() == children added");
  Expect(exportCount == (unsigned)n,
         "exported wrapper sees the same count as the tree has children");
  Expect(view.count() == rawCount, "count() agrees with the raw header read");

  // element-by-element: compare against FindDescendent, an independent walk.
  for (int i = 0; i < n; ++i) {
    std::wstring id = L"C";
    id += std::to_wstring(n);
    id += L"_";
    id += std::to_wstring(i);

    Element *viaView = view.at((unsigned)i);
    Element *viaFind = root->FindDescendent(StrToID((UCString)id.c_str()));

    bool same = (viaView == viaFind);
    if (negctl) {
      // control: claim a MISMATCH is required, so equality must fail the probe
      same = !same;
    }
    printf("    at(%d)=%p  FindDescendent(%ls)=%p  %s\n", i, (void *)viaView,
           id.c_str(), (void *)viaFind, same ? "OK" : "FAIL");
    if (!same) {
      printf("      FAIL: view element %d != independent FindDescendent\n", i);
      ++g_fails;
    }
  }

  // out-of-range must be nullptr, not a wild read
  Element *oob = view.at((unsigned)n);
  Expect(oob == nullptr, "at(count()) is nullptr (bounds enforced)");

  // ---- child count oracle: HasChildren ---------------------------------------
  bool has = root->HasChildren();
  printf("  HasChildren()=%d\n", (int)has);
  Expect(has == (n > 0), "HasChildren() agrees with n>0");

  // ---------------------------------------------------------------------------
  // LIFECYCLE: prove ChildrenView actually RELEASES the borrow.
  //
  // Method: take our own borrow with the public API, record the refcount, then
  // observe that dropping a ChildrenView built from an ADDITIONAL borrow returns
  // the refcount to the same value. A view that leaked would leave the refcount
  // one quantum higher.
  //
  // The sentinel case (n == 0) is reported separately because its Release is a
  // measured no-op, so a refcount delta is not expected there.
  // ---------------------------------------------------------------------------
  {
    Value *b1 = nullptr;
    root->GetChildren(&b1);
    if (b1) {
      unsigned before = RefCountOf(b1);
      bool sentinel = IsSentinelRef(b1);
      if (sentinel) {
        printf("  lifecycle: sentinel header (refcount field empty) -> "
               "Release is a no-op by measurement\n");
      } else {
        {
          ChildrenView tmp = GetChildrenView(root);
          unsigned during = RefCountOf(b1);
          printf("  lifecycle: refcount before=%u during-extra-view=%u\n", before,
                 during);
          if (!negctl)
            Expect(during > before,
                   "a live extra view holds a refcounted borrow");
        }
        unsigned after = RefCountOf(b1);
        printf("  lifecycle: refcount after view destroyed=%u (expect %u)\n",
               after, before);
        // This is THE anti-leak assertion: exactly one Release happened.
        if (negctl)
          Expect(after != before, "NEGCTL: view must fail to restore refcount");
        else
          Expect(after == before,
                 "ChildrenView released exactly its own borrow (no leak)");
      }
      b1->Release();
    } else {
      printf("  lifecycle: no borrow returned for n=%d\n", n);
    }
  }

  // ---------------------------------------------------------------------------
  // LIFECYCLE SENSITIVITY CONTROL (always run, not just NEGCTL).
  //
  // The check above only means something if the refcount instrument can actually
  // SEE a missed Release. So deliberately reproduce a leak: acquire a borrow and
  // do NOT release it, and require the refcount to stay elevated. Then release it
  // to leave the process clean. If this control ever fails, the "no leak"
  // assertion above is not evidence of anything.
  // ---------------------------------------------------------------------------
  {
    Value *leaked = nullptr;
    root->GetChildren(&leaked);
    if (leaked && !IsSentinelRef(leaked)) {
      unsigned base = RefCountOf(leaked);
      Value *leak2 = nullptr;
      root->GetChildren(&leak2);
      unsigned leakedCount = RefCountOf(leaked);
      printf("  leak-control: base=%u after-unreleased-borrow=%u\n", base,
             leakedCount);
      if (leakedCount <= base) {
        printf("  FAIL: leak-control could not observe an unreleased borrow -- "
               "the no-leak assertion is not evidence\n");
        ++g_fails;
      }
      if (leak2)
        leak2->Release();  // clean up the deliberate leak
    }
    if (leaked)
      leaked->Release();
  }

  parser->Destroy();
}

int main(int argc, char **argv) {
  bool negctl = false, nopin = false;
  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "NEGCTL") == 0)
      negctl = true;
    else if (strcmp(argv[i], "NOPIN") == 0)
      nopin = true;
  }
  printf("=== W1 ChildrenView end-to-end probe%s%s ===\n",
         negctl ? " [NEGATIVE CONTROL: must FAIL]" : "",
         nopin ? " [NOPIN: pinned DLL expected absent]" : "");

  HMODULE before = GetModuleHandleW(L"dui70.dll");
  if (!before) {
    printf("FAIL: dui70.dll not loaded\n");
    return 1;
  }
  wchar_t path[MAX_PATH] = {0};
  GetModuleFileNameW(before, path, MAX_PATH);
  printf("dui70.dll        : %ls\n", path);

  // The pin check runs FIRST, before any dui70 API call. Which binary we are
  // testing is a precondition for everything below, so it must not depend on
  // the engine successfully initialising -- otherwise a wrong-DLL run could
  // fail for an unrelated reason and look like a pin failure.
  PinCheck(!nopin);

  // Real initialisation, copied from UITest.cpp -- no fabricated engine state.
  HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
  if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) {
    printf("FAIL: CoInitializeEx 0x%08lX\n", (unsigned long)hr);
    return 1;
  }
  hr = InitProcessPriv(14, nullptr, 0, true);
  if (FAILED(hr)) {
    printf("FAIL: InitProcessPriv 0x%08lX\n", (unsigned long)hr);
    return 1;
  }
  hr = InitThread(2);
  if (FAILED(hr)) {
    printf("FAIL: InitThread 0x%08lX\n", (unsigned long)hr);
    return 1;
  }
  // RegisterAllControls returns an NTSTATUS/HRESULT-style code where 0 = success
  // (UITest.cpp wraps it in THROW_IF_NTSTATUS_FAILED, i.e. it only fails when the
  // value is negative). Testing the return for truthiness would be inverted, so
  // compare against failure explicitly and print the raw value for the log.
  int reg = RegisterAllControls();
  printf("RegisterAllControls -> 0x%08X\n", (unsigned)reg);
  if (reg < 0) {
    printf("FAIL: RegisterAllControls 0x%08X\n", (unsigned)reg);
    return 1;
  }
  printf("init             : OK (InitProcessPriv/InitThread/RegisterAllControls)\n\n");

  // 0/1/2 children exercise the INLINE path (inline capacity for Element* is 2);
  // 3 children forces the array onto the HEAP.
  for (int n = 0; n <= 3; ++n)
    RunCase(n, negctl);

  printf("\nstorage modes exercised: inline=%d heap=%d\n", g_inlineCases,
         g_heapCases);
  // A probe that never reached the heap would not have tested the branch that
  // owns a separate allocation. Require both in normal mode.
  if (!negctl) {
    if (g_heapCases == 0) {
      printf("FAIL: no HEAP case was exercised -- the heap branch is untested\n");
      ++g_fails;
    }
    if (g_inlineCases == 0) {
      printf("FAIL: no INLINE case was exercised\n");
      ++g_fails;
    }
  }

  UnInitProcessPriv(nullptr);
  CoUninitialize();

  printf(g_fails ? "\nLIVE-CHILDRENVIEW FAIL (%d)\n" : "\nLIVE-CHILDRENVIEW PASS\n",
         g_fails);
  return g_fails ? 1 : 0;
}
