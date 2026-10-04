# W1 ChildrenView fixture

A tracked, CI-managed test for `DirectUI/include/ChildrenView.h` — the read-only
view over `DynamicArray<Element*, 0>` — that **also proves which `dui70.dll` it
actually exercised**.

```
tests/w1-childrenview/
    w1-childrenview-probe.cpp        # the fixture
    README.md                        # this file
tools/dui-pipeline/
    gen_childrenview_probe.ps1       # build + stage pinned DLL + run (+ negatives)
    pe-digest.py                     # derives the A2 pin anchor from the DLL
```

Run it:

```powershell
# requires the repro stage to have downloaded the pinned DLL first:
pwsh -File tools/dui-pipeline/repro.ps1
pwsh -File tools/dui-pipeline/gen_childrenview_probe.ps1 -RunNegative
```

---

## 1. What it asserts

| # | assertion | oracle |
|---|---|---|
| 1 | `ChildrenView::count()` == number of children created | `root->HasChildren()`, raw header read |
| 2 | `view.at(i)` == the i-th child | **`Element::FindDescendent`** (dui70's own walk) |
| 3 | count agrees with a second door | **exported `DUI70_ElementGetChildren`** |
| 4 | `at(count())` == `nullptr` | bounds check, no wild read |
| 5 | both storage modes exercised | n=1,2 inline; n=3 heap — FAILS if either never occurs |
| 6 | the borrow is released | refcount returns to its pre-view value |
| 7 | the refcount instrument would *notice* a leak | deliberate unreleased borrow stays elevated |
| 8 | **the loaded DLL is the pinned one** | A1/A2/A3 below |

It initialises dui70 exactly the way `UITest.cpp` does
(`InitProcessPriv(14)` → `InitThread(2)` → `RegisterAllControls`) and builds real
trees through `DUIXmlParser::SetXML` / `CreateElement`.

**It does not** write raw memory, synthesise layout, read `Element+0x95` bit 1,
or call `DynamicArray::Create` directly. Every dui70 entry point is reached
through its **exported name** — there are no RVA-based calls. (The RVAs that
appear in comments are documentation of measured addresses, not call targets.)

---

## 2. The pin check, and why A2 is not the obvious hash

Without a pin check, a PASS says only "some `dui70.dll` agreed", and the
System32 copy also passes. So the fixture proves which binary is loaded:

| | check |
|---|---|
| **A1** | `GetModuleFileNameW` directory == the staging directory |
| **A2** | sha256 of the **loaded `.text`** == the derived anchor |
| **A3** | the module was **not** loaded from `System32`/`SysWOW64` |

### Why not `sha256(image[0..SizeOfImage)) == manifest.dll.sha256`

That check is **unsatisfiable by any implementation**. Measured on the pinned DLL:

1. `SizeOfImage` is `0x1AA000` but the file is `0x1A7000` — the image range covers
   `0x3000` bytes with no on-disk counterpart. The ranges can never be equal.
2. The loader **writes** to the mapped image: it patches the import address table
   and the delay-load table (both in `.rdata` here). Those sections never match
   the file.
3. The values it writes are addresses of **other modules**, which are themselves
   relocated per run. Measured across 5 runs at an *identical* base
   (`0x...6D270000`): **5 different hashes**.

### What A2 uses instead: the loaded `.text`

`.text` is a sound anchor for measured reasons:

* **rebase-invariant** — of the 11619 relocation entries, **none** target `.text`
  (`pe-digest.py` re-checks this and *refuses to emit an anchor* if any do);
* the loader never writes to it;
* it **differs** between the pinned DLL and System32, so it *discriminates*:

  ```
  pinned   .text = BC9E51C687293A567CA5F8101CB32786A501B822412D8B4B299B6913466A9696
  System32 .text = EA767A4CF8619C9FA018D66CD876D7998EF7E7D5EF497B6D9BF6F54CBD31AC50
  ```

The expected value is **derived, never hardcoded**:
`pe-digest.py derive` first asserts the source DLL's whole-file sha256 equals
`pinned/manifest.json`, then emits the anchor. So the anchor cannot be hand-edited
into blessing the wrong file without also failing the manifest assertion.

**The probe never re-reads the DLL from disk.** Hashing the file named by
`GetModuleFileNameW` would be a TOCTOU check: it validates bytes that are not
necessarily the ones mapped. The digest is taken over the **in-memory** image,
bounded by that image's own section header.

---

## 3. Why app-local staging pins the DLL

`gen_childrenview_probe.ps1` copies the pinned DLL **next to the exe**. The loader
searches the application directory before `System32`, and `dui70.dll` is **not** a
`KnownDLL` (verified: 37 `KnownDLLs` entries, none of them `dui70`), so the local
copy wins.

This is **checked, not assumed**: if the local copy is missing the loader falls
back to System32, and A1/A3 fail loudly. A deliberately corrupted local copy
hard-fails with `0xC000007B` rather than silently falling back.

> If `dui70.dll` ever became a `KnownDLL`, app-local staging would stop working.
> A2 would then fail (the System32 `.text` differs), turning a silent
> substitution into a red gate instead of a false PASS.

---

## 4. Negative controls

| control | how | required result |
|---|---|---|
| `NEGCTL` | assert wrong expectations (counts off by 7, element equality inverted) | exit **1** |
| `NOPIN` | hide the staged DLL so System32 is loaded | exit **1** (A1 + A3 + A2 all fire) |

`NOPIN` is what makes A2 *evidence* rather than decoration: it demonstrates the
check actually distinguishes the two binaries. Run both with `-RunNegative`.

The lifecycle sensitivity control runs in **every** mode: it deliberately withholds
a `Release` and requires the refcount to stay elevated, proving the "no leak"
assertion could have failed.

---

## 5. Notes / boundaries

* The fixture links an import library built from `DirectUI/dui70.def`; it does not
  depend on `run.ps1` having run first.
* It is intentionally **not** wired into `pipeline.yml` yet — CI gating is a
  separate, reviewable change.
* `A2` proves the `.text` bytes are the pinned ones. It does not (and cannot)
  prove the *data* sections are unpatched — they are patched by the loader by
  design, which is exactly why `.text` is the anchor.
* The probe runs the real engine, so it needs a desktop-less agent-friendly
  environment: it does not create a window.
