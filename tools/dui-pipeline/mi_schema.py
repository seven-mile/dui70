"""Shared mi-tables.json schema whitelist.

Schema 3 is a strict superset of 2 for every consumer in this
tree (same derived structure, same provenance semantics). One
constant for emit_headers.load_mi_tables,
ci_checks._mi_pattern_interfaces, and uia_order_verify so the
emitter, the G3 registry, and the R6 gate can never disagree.
"""
MI_TABLES_SCHEMA_OK = (2, 3)
