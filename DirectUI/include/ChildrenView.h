// ChildrenView.h -- a read-only, ownership-safe view over an Element's children.
//
// WHY THIS FILE EXISTS
//   Element::GetChildren(Value** out) does NOT return an array the caller owns.
//   It returns *(Value + 0x08) and writes the backing Value* into *out; the
//   caller MUST call Value::Release on that Value once it is done reading.
//   Every in-DLL caller does exactly this (5 call sites verified: DUI_GetFirstChild
//   @0x57C04, DUI_GetChildCount @0xB2B2C, Pages::GetCount @0xDD350, Pages::GetPage
//   @0xDD390, Element::Add @0x73810 -- each ends in a Value::Release call).
//
//   Getting that wrong is easy and its symptom is a leak or a use-after-free, not
//   a compile error. So this view makes the BORROW mistake UNEXPRESSIBLE:
//     * no public constructor -- a view can only come from GetChildrenView()
//     * the borrowed Value* is private and has no getter
//     * the DynamicArray pointer is private and has no getter
//     * copy is deleted (two views would each Release the same borrow)
//     * the destructor is the ONLY place Release is called
//     * elements come out as bare Element* that the view never owns or frees
//   The raw DynamicArray/Value pointers therefore never appear in the public
//   surface, so "forgot to Release" and "the array owns the elements" are both
//   unwritable rather than merely discouraged.
//
//   Scope of that guarantee: it covers the borrow, NOT the elements. A bare
//   `Element*` from at() is still deletable by a caller. See "WHAT THIS CLASS DOES
//   NOT PREVENT" below -- the limit is stated there rather than papered over.
//
// SCOPE / PROVENANCE  (read this before using it)
//   This is deliberately narrow: it covers ONLY DynamicArray<Element*, 0>, the
//   single instantiation whose layout is measured on the pinned DLL.
//
//   Measured on dui70.dll sha256 2080E43F5D997A3BD9827F38D8F3029D88F77A7F301966FBA10EC0ACAD9AA556
//   (machine-tracked in pinned/dynarray-contracts.json -- re-derived and
//   byte-compared by repro.py gate R3''' and cross-checked against this
//   header's constants by the CI G-lite gate; original read-only audit:
//   .local/audit/w1-dynamicarray-contract.md and .local/build/w1/):
//     +0x00  uint32 header : bits 0..27 = count, bit 28 = on-heap, bit 29 = owns
//                          (bit 30/31 UNPROVEN -- not read here)
//     +0x08  T* data, or the inline element storage
//     +0x10  uint32 capacity
//     sizeof = 8 + max(16, sizeof(T)); for Element* (8 bytes) that is 24 bytes and
//     the inline capacity is 2.  These numbers are NOT general across T: the same
//     template measures 24/32/40 bytes and inline capacities 4/2/1 for other T.
//     That is exactly why this view is restricted to Element*.
//
//   The base selection below mirrors the DLL's own code at Pages::GetPage
//   @0xDD3B2..0xDD3C1:
//       testl $0x10000000,(%rax)   ; bit 28 = on-heap?
//       lea   0x8(%rax),%rcx       ; inline base
//       je     -> use rcx
//       mov    (%rcx),%rcx         ; on-heap: deref the data pointer
//       mov    (%rcx,%rdi,8),%rbx  ; element i
//
//   NOT PROVIDED, ON PURPOSE:
//     * no element ownership: at(i) returns a borrowed Element* whose lifetime is
//       NOT extended by this view. Do not delete it or store it past the view.
//     * no mutation: this view is read-only and never writes raw memory.
//     * no reliance on Element+0x95 bit 1: that flag is what GetChildren itself
//       branches on, but its semantics are UNPROVEN, so no code here reads it.
//       (The DLL owns that decision; we just call the function.)
//     * children added/removed while a view is alive are not tracked.
//
// WHAT THIS CLASS DOES *NOT* PREVENT  (read before trusting "unexpressible" above)
//   `private` protects the BORROW, not the ELEMENT. at(i) necessarily hands back a
//   bare `Element*`, and a bare pointer is deletable by anyone: `delete
//   view.at(i);` compiles, and the view cannot stop it. What the design does
//   guarantee is narrower and worth stating precisely:
//     * you cannot obtain, copy away, or store the borrowed Value* -- so you
//       cannot double-Release it or leak it by losing track of it
//     * you cannot hold the raw array pointer -- so you cannot walk past count()
//     * you cannot copy a view -- so two views cannot Release one borrow
//   Element lifetime remains the caller's contract, documented not enforced. That
//   is a deliberate limit: enforcing it would require returning an owning wrapper
//   or a reference type, which would misrepresent the DLL's actual ownership model
//   (the tree owns its elements; the view owns nothing).
//
// Hand-written: registered in tools/dui-pipeline/ci_checks.py HANDWRITTEN, so G3
// requires it to exist and G5 compiles it. It is NOT derived from pinned/ and must
// never be regenerated over.
#pragma once

#include <windows.h>

#include "dui_abi_types.h"
#include "Element.h"
#include "Value.h"

// x64-ONLY, enforced at compile time.
//
// The layout this header encodes was measured on the x64 pinned DLL, and the
// numbers are sizeof(void*)-dependent: sizeof(T)=8 gives sizeof(DynamicArray)=24
// and inline capacity 2. On a 32-bit target sizeof(T)=4, so the same template
// would give a different size and a different inline capacity, and every offset
// below (kDataOffset / kCapacityOffset / the pointer stride in ElementAt) would
// silently read the wrong bytes.
//
// This is not a theoretical concern: the header would still COMPILE for x86,
// because the offsets are plain integer constants and the accesses are memcpy on
// an opaque blob -- there is no type error to catch. Refusing to build is
// therefore the only honest option; a wrong-but-compiling layout reader is worse
// than a missing feature.
static_assert(sizeof(void *) == 8,
              "ChildrenView encodes offsets measured on the x64 pinned dui70.dll "
              "(sizeof(DynamicArray<Element*,0>) == 24, inline capacity 2). That "
              "layout does not hold when sizeof(void*) != 8, so this header is "
              "deliberately unusable on 32-bit targets.");

namespace DirectUI {

// ---------------------------------------------------------------------------
// ChildrenView
//
// Usage:
//     auto kids = GetChildrenView(elem);        // borrows, Releases on scope exit
//     for (unsigned i = 0; i < kids.count(); ++i) {
//         Element* child = kids.at(i);          // borrowed; do not delete
//         ...
//     }
// ---------------------------------------------------------------------------
class ChildrenView {
public:
  // The only way to obtain a view. Returns a view with count()==0 and no borrow
  // when the element has no children (GetChildren then yields the shared "empty
  // list" sentinel, whose Release is a measured no-op -- see below).
  friend ChildrenView GetChildrenView(Element *element);

  ChildrenView(ChildrenView const &) = delete;
  ChildrenView &operator=(ChildrenView const &) = delete;

  // Move is allowed: it transfers the single borrow, so exactly one live view
  // ever owns it. The moved-from view is left empty and Releases nothing.
  ChildrenView(ChildrenView &&other) noexcept
      : borrowed_(other.borrowed_), array_(other.array_) {
    other.borrowed_ = nullptr;
    other.array_ = nullptr;
  }
  ChildrenView &operator=(ChildrenView &&other) noexcept {
    if (this != &other) {
      Reset();  // release whatever this view already held
      borrowed_ = other.borrowed_;
      array_ = other.array_;
      other.borrowed_ = nullptr;
      other.array_ = nullptr;
    }
    return *this;
  }

  // The ONLY Release site. Value::Release on the shared "empty children" sentinel
  // is a measured no-op (its header is 0xFFFFFF84, and Release is gated on
  // (header & ~0x7F) == 0xFFFFFF80), so calling it unconditionally is correct for
  // both the real-list and the sentinel case.
  ~ChildrenView() { Reset(); }

  // Number of children currently in the list. Read from the header's low 28 bits.
  unsigned count() const { return array_ ? CountOf(array_) : 0u; }

  bool empty() const { return count() == 0u; }

  // Borrowed element at `index`; nullptr when out of range.
  //
  // The returned pointer is NOT owned by this view: its lifetime is bounded by
  // whatever owns the element tree, not by the view, and it must not be deleted.
  Element *at(unsigned index) const {
    if (!array_ || index >= count())
      return nullptr;
    return ElementAt(array_, index);
  }

private:
  ChildrenView(Value *borrowed, void *array) : borrowed_(borrowed), array_(array) {}

  void Reset() {
    if (borrowed_) {
      borrowed_->Release();  // borrow returned: exactly one Release per acquire
      borrowed_ = nullptr;
    }
    array_ = nullptr;
  }

  // -------------------------------------------------------------------------
  // Opaque layout access for DynamicArray<Element*, 0> ONLY.
  //
  // The generated tree intentionally leaves `DynamicArray` an incomplete type
  // (dui_abi_types.h: `template <typename T, int N> class DynamicArray;`). That
  // is correct for a pointer-only ABI and it is what keeps the generated headers
  // decoupled from an implementation detail of this DLL build. So rather than
  // completing the template, the three measured offsets are named here, once,
  // next to the evidence. The typing is intentionally "array is an opaque blob".
  // -------------------------------------------------------------------------
  static constexpr unsigned kHeaderOffset = 0x00;  // uint32
  static constexpr unsigned kDataOffset = 0x08;    // T* or inline storage
  static constexpr unsigned kCapacityOffset = 0x10;
  static constexpr unsigned kCountMask = 0x0FFFFFFFu;   // bits 0..27
  static constexpr unsigned kOnHeapBit = 0x10000000u;   // bit 28
  // bit 29 (owns) is measured but NOT needed by a read-only view; bits 30/31 are
  // unproven, so nothing here touches them.

  static unsigned HeaderOf(void const *array) {
    unsigned header;
    // The array is a live dui70-owned object; read it with memcpy so this stays
    // well-defined and does not trip strict-aliasing assumptions.
    memcpy(&header, static_cast<unsigned char const *>(array) + kHeaderOffset,
           sizeof(header));
    return header;
  }

  static unsigned CountOf(void const *array) {
    return HeaderOf(array) & kCountMask;
  }

  // Reproduces the DLL's own base selection (Pages::GetPage @0xDD3B2..0xDD3C1):
  //   inline  -> element i lives at array + 8 + i*sizeof(Element*)
  //   on-heap -> array + 0x08 holds a pointer to the heap element block
  // A view is read-only, so this only ever computes an address.
  static unsigned char const *ElementBase(void const *array) {
    unsigned char const *const inlineBase =
        static_cast<unsigned char const *>(array) + kDataOffset;
    if ((HeaderOf(array) & kOnHeapBit) == 0)
      return inlineBase;  // inline storage starts at +0x08

    void *heapBlock = nullptr;
    memcpy(&heapBlock, inlineBase, sizeof(heapBlock));
    return static_cast<unsigned char const *>(heapBlock);
  }

  static Element *ElementAt(void const *array, unsigned index) {
    unsigned char const *base = ElementBase(array);
    if (!base)
      return nullptr;
    void *slot = nullptr;
    memcpy(&slot, base + static_cast<size_t>(index) * sizeof(Element *),
           sizeof(slot));
    return static_cast<Element *>(slot);
  }

  Value *borrowed_;  // private: the borrow that must be Released. No getter.
  void *array_;      // private: opaque DynamicArray<Element*,0>*. No getter.
};

// ---------------------------------------------------------------------------
// The acquiring entry point. This is the ONE place Element::GetChildren is
// called, so the borrow/Release pairing is visible in a single function.
//
// Deliberately NOT a member/constructor: making it a free function keeps the
// "acquire" and "release" responsibilities in one file and leaves the class with
// no way to be constructed holding a borrow it did not acquire.
// ---------------------------------------------------------------------------
inline ChildrenView GetChildrenView(Element *element) {
  if (!element)
    return ChildrenView(nullptr, nullptr);

  // Initialize the out-parameter to nullptr first, exactly as the DLL's own
  // callers do (e.g. DUI_GetFirstChild @0x57C0A zeroes its out slot before the
  // call): if GetChildren were ever to fail without writing *out, we must not
  // Release an uninitialized garbage pointer.
  Value *borrowed = nullptr;
  DynamicArray<Element *, 0> *array = element->GetChildren(&borrowed);

  // If there is no borrow there is nothing to release, so do not keep a view
  // that would later call Release on nullptr (Reset() tolerates it, but keeping
  // the invariant "borrowed_ == nullptr iff nothing to release" is cleaner).
  return ChildrenView(borrowed, array);
}

}  // namespace DirectUI
