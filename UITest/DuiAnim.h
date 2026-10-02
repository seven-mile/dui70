// DuiAnim.h -- the animation bit-field accepted by Element::SetAnimation().
//
// ============================================================================
// WHERE THESE VALUES COME FROM  【实锤】
// ============================================================================
// Not from guessing and not from a symbol dump: dui70 reports this table about
// itself. Every control's `[Animation]` property carries an `enum_value_map`,
// and the classinfo dump prints it as a `name : value` list. All 86 dumps that
// contain the property agree on one identical set, so the names below are
// dui70's own names, copied verbatim rather than invented here.
//
// Regenerate with: uncomment `HookClassFactoryRegister()` in UITest.cpp, run it,
// and the dumps appear in `class-dump/<Name>Class.g.txt`; the archived copies
// live in `docs/duixml-classinfo/`.
//
// One caveat from that source: the dump lists `MediumSlow` TWICE (both
// 0x50000000), with `Medium` (0x40000000) printed between the two copies -- 26
// entries, 25 distinct values. This header keeps the 25 distinct values. It is
// a duplication in the emitter's table, not two different speeds.
//
// ============================================================================
// FIELD LAYOUT -- one 32-bit word, sub-fields OR'd together
// ============================================================================
//   bits  0-3   0x0000000F   easing          None/Linear/Log/Exp/S
//   bits  4-5   0x00000030   delay           Short/Medium/Long
//   bit   8     0x00000100   alpha
//   bits 12-15  0x0000F000   target property Position/Size/SizeH/SizeV/
//                                            Rectangle/RectangleH/RectangleV
//   bit  16     0x00010000   scale
//   bit  24     0x01000000   reverse
//   bits 28-31  0xF0000000   speed           VeryFast .. VerySlow
//
// Which masks the binary actually uses 【实锤】 for the mask being an immediate,
// 【强推】 for it being this field:
//   0xF, 0x100, 0x1000000, 0x10000 and 0xF000 all appear as and/test immediates;
//   0xF0000000 is the strongest case -- `InvokeAnimation` does
//   `andl $0xf0000000, %eax` and then compares 0x10000000..0x70000000, so that
//   field is proven, not inferred.
//   0x30 for the delay field is the weakest: the VALUES 0x10/0x20/0x30 are in the
//   table above, but 0x30 itself was not observed as an immediate.
//   0x7000 is NOT used as a mask (0xF000 is), even though no value above 0x7000
//   is defined -- bits 12-15 are the field, bits 12-14 are the used range.
//
// ============================================================================
// UNDERLYING TYPE IS int32_t  【实锤】
// ============================================================================
// The accessor's mangled name is `?SetAnimation@Element@DirectUI@@QEAAJH@Z` and
// `?GetAnimation@Element@DirectUI@@QEAAHXZ`: the trailing `H` is MSVC for `int`
// (`I` would be `unsigned int`). So the word is signed 32-bit, matching
// `long SetAnimation(int)` / `int GetAnimation()` in Element.h.
//
// ============================================================================
// BIT 31 IS RESERVED / UNUSED
// ============================================================================
// The speed mask 0xF0000000 covers bits 28-31, but dui70 only ever compares
// 0x10000000..0x70000000 -- bit 31 has no enumerator, so 0x80000000 and above are
// not valid speeds today.
//
// UPGRADE CONDITION: if a future classinfo dump or an observed call shows a speed
// value >= 0x80000000 (i.e. the top nibble reaches 8..F), change the underlying
// type to uint32_t. `0x80000000` is outside int32_t's enumerator range, so it
// cannot be represented honestly as an int32_t enumerator.
//
// Nothing else in the layout is signed-sensitive: every other field is small and
// positive.

#pragma once

#include <cstdint>

namespace DirectUI {

enum class DuiAnim : int32_t {
  // -- easing (bits 0-3) ----------------------------------------------------
  None = 0x0,
  Linear = 0x1,
  Log = 0x2,
  Exp = 0x3,
  S = 0x4,

  // -- delay (bits 4-5) ----------------------------------------------------
  DelayShort = 0x10,
  DelayMedium = 0x20,
  DelayLong = 0x30,

  // -- alpha (bit 8) -------------------------------------------------------
  Alpha = 0x100,

  // -- target property (bits 12-15) ---------------------------------------
  Position = 0x1000,
  Size = 0x2000,
  SizeH = 0x3000,
  SizeV = 0x4000,
  Rectangle = 0x5000,
  RectangleH = 0x6000,
  RectangleV = 0x7000,

  // -- scale (bit 16) ------------------------------------------------------
  Scale = 0x10000,

  // -- reverse (bit 24) ----------------------------------------------------
  Reverse = 0x1000000,

  // -- speed (bits 28-31; bit 31 reserved, see above) ----------------------
  VeryFast = 0x10000000,
  Fast = 0x20000000,
  MediumFast = 0x30000000,
  Medium = 0x40000000,
  MediumSlow = 0x50000000,
  Slow = 0x60000000,
  VerySlow = 0x70000000,
};

// Combine sub-fields, e.g. DuiAnim::S | DuiAnim::Fast | DuiAnim::Alpha.
constexpr DuiAnim operator|(DuiAnim a, DuiAnim b) {
  return static_cast<DuiAnim>(static_cast<int32_t>(a) | static_cast<int32_t>(b));
}

constexpr DuiAnim operator&(DuiAnim a, DuiAnim b) {
  return static_cast<DuiAnim>(static_cast<int32_t>(a) & static_cast<int32_t>(b));
}

constexpr bool HasAnimFlag(DuiAnim value, DuiAnim flag) {
  return (static_cast<int32_t>(value) & static_cast<int32_t>(flag)) != 0;
}

// SetAnimation()/GetAnimation() speak plain int.
constexpr int ToInt(DuiAnim v) { return static_cast<int>(v); }

}  // namespace DirectUI
