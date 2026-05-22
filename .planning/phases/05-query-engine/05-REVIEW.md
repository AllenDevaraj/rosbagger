---
phase: 05-query-engine
reviewed: 2026-05-22
depth: standard (orchestrator-inline)
files_reviewed: 13
status: issues_found
critical: 0
warning: 0
info: 2
total: 2
note: "The gsd-code-reviewer subagent hit a session/quota limit before writing this file; the orchestrator performed an inline review of the highest-risk modules (query.py, resolve.py, duckdb_backend.py) plus the passing 186-test suite and functional query()/DuckDB spot-checks. Code review is advisory/non-blocking."
---

# Phase 05: Query Engine — Code Review (orchestrator-inline)

The gsd-code-reviewer subagent was interrupted by a session/quota limit. Per the GSD workflow, the code-review gate is advisory and never blocks; the orchestrator reviewed the security-critical modules directly.

## What was verified

- **`backend/query.py`** — sound orchestration: resolve (tables/columns/star) → invert topic→table map via the SAME shared `TableNameResolver` pass as `inspect.collect_table_schemas` (honors the Phase 4 CR-01 collision fix; skips multi-msgtype topics) → raise `UnknownTableError` listing available tables BEFORE loading → lazy-load only referenced topics (`reader.read(topics={topic})`) → register under the sanitized name → execute. Heavy-blob `include` is `heavy if star else heavy & columns` (QURY-07). Lifecycle correct: `own_backend` closes only the default backend in `finally`; a caller-supplied `backend=` is left open for reuse. Offline invariant via lazy imports.
- **`backend/resolve.py`** — `referenced_tables_in` = `find_all(exp.Table).name` minus `exp.CTE` aliases (CTEs not mistaken for topics); `referenced_columns` preserves dotted names (lines up with the QURY-07 include key); `has_star` via `exp.Star`. `import sqlglot` at module top is safe (pure-Python, not ROS).
- **`backend/duckdb_backend.py`** — one in-memory connection, zero-copy `register`, `con.execute(sql).to_arrow_table()` (not the deprecated `fetch_arrow_table`), idempotent `close`, `_require_open` guard; `import duckdb` confined to this module.
- **Security/threat dispositions:** the user's SQL is the intended local-CLI interface (forwarded as-is, no orchestrator-built SQL → no injection surface); bag-derived identifiers are quoted via Phase 3's allow-list; the offline guard (strengthened in 05-01) confirms `import rosbagger_core`/`.backend` pull no duckdb/sqlglot/pyarrow.
- **Tests + functional:** 186 passed at 97.91% coverage; `query()` verified end-to-end across all 3 formats (a `SELECT ... WHERE "linear.x" >= 1.0` over an MCAP bag returns correct filtered rows; unknown table raises listing available tables); `read(topics=)` only-referenced-loaded proven by the executor's monkeypatched-deserialize test; WR-01 regression test (`test_schema_collision.py`) present.

## Findings

- **IN-01 (info):** v1 loads each referenced topic's FULL Arrow table into memory before executing (no column-projection pushdown). Documented as a deliberate v1 boundary; pushdown is QURY-09/v2. Large bags could strain memory — acceptable for v1, revisit if it bites.
- **IN-02 (info):** a SQL table that maps to a *multi-msgtype* topic (skipped from the map, `msgtype is None`) yields `UnknownTableError` rather than a specific "mixed message types" message. Minor UX; Phase 7 (CLI-02 teaching errors) owns better messaging.

No critical or warning findings in the reviewed modules.

## Follow-up

A full gsd-code-reviewer pass can be re-run after quota reset with `/gsd:code-review 05` if a deeper independent review is wanted; not required for phase completion.
