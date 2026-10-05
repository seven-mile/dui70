"""Shared mi-tables.json schema capability sets.

Schema 3 is a strict superset of 2 for the EMISSION-side consumers
(same derived structure, same provenance semantics): the emitter
(emit_headers.load_mi_tables) and the G3 registry
(ci_checks._mi_pattern_interfaces) accept both and must share ONE
set so they can never disagree.

Schema 4 adds "mangles" (per-slot full mangled candidate lists, the
owner-contract evidence) as a parallel array to "slots". For schema
3 consumers the derived structure is unchanged (mangles is additive;
readers that ignore it see exactly schema 3), so 4 joins the
emission-side set. The R6 gate reads slots only and its derived-
section semantics are identical under 4 (no new gate input is
consumed), so 4 joins R6's set as evidence-neutral.

The R6 gate (uia_order_verify) is NOT a superset consumer: it
requires schema-3+ fields -- per-table identity, ctor_
vftable_references (reference-only evidence), length_provenance
honesty values (ignored-redundant), and the R3'' manual-consistency
contract. Accepting schema 2 there would be a widening of the
gate's input contract, not an evidence-neutral change, so R6 keeps
its own stricter set. The schema2->R6 path stays fail-closed (rc 2
structural error) and a negative control asserts it.
"""

# emission-side capability: derived structure + provenance values
# readable identically from schema 2, 3 and 4
MI_EMIT_SCHEMA_OK = (2, 3, 4)

# R6 audit capability: identity + ctor_vftable_references +
# provenance honesty + R3'' manual consistency -- schema 3/4
MI_R6_SCHEMA_OK = (3, 4)

# back-compat alias for callers that genuinely accept any known
# mi-tables schema (introspection only, never a gate input)
MI_TABLES_SCHEMA_OK = MI_EMIT_SCHEMA_OK
