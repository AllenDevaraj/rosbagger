---
phase: 10-query-ergonomics
plan: 03
subsystem: backend
tags: [query-orchestrator, alias-expansion, projection-pushdown, sqlglot, pyarrow, duckdb, integration]

# Dependency graph
requires:
  - phase: 10-01-alias-pack
    provides: "rosbagger_core.backend.alias.expand_aliases(tree, msgtype, schema_names) — the single-msgtype/single-schema sqlglot AST rewrite this orchestrator gates and calls"
  - phase: 10-02-projection-pushdown
    provides: "build_arrow_table(..., restrict=) / arrow_schema / column_names / flatten_message restrict= filter — the materialization seam this orchestrator computes a per-topic restrict set for and threads in"
  - phase: 05-query
    provides: "backend/query.py query() pipeline (parse->resolve->load->execute), _topic_table_maps (topic_to_msgtype), the UnknownTableError pre-load raise, the BinderException->UnknownColumnError catch, the swappable backend= seam"
  - phase: 03-schema
    provides: "build_table_schema (O(1) metadata, no reader.read()) — hoisted ahead of resolution so the alias existence-gate sees dotted names"
provides:
  - "query(sql, reader, *, alias=True, backend=None) — alias keyword (D-11) wired end-to-end; SELECT vx FROM cmd_vel returns the linear.x series (SC1)"
  - "Reordered pipeline (D-02 / Pattern 4): parse -> hoist typestore + per-topic TableSchema -> single-base-topic gated expand_aliases -> referenced_*/has_star on the REWRITTEN tree -> load (reusing hoisted schemas) -> execute the rewritten SQL"
  - "Single-base-topic alias gate (Open Q1): expansion runs ONLY when exactly one distinct base topic resolves; JOIN/CTE/multi-topic and alias=False are safe no-ops"
  - "Per-topic projection restrict set (D-06/D-07/D-08/D-09): restrict=(columns & schema_names)|STANDARD when not star, restrict=None under SELECT */qualified-star; applied per-topic (over-include on JOIN, never under-include)"
  - "Rewritten-SQL forwarding (D-02): backend.execute(tree.sql('duckdb')) so expanded dotted columns reach DuckDB while preserving the trusted-SQL boundary (no hand-built strings)"
  - "SC3 proven by a recording QueryBackend observing query()'s actual registered table across ROS1 + ROS2-sqlite + MCAP"
affects: [bagq-cli-no-alias-surface, query-ergonomics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hoist O(1) per-topic TableSchema construction ahead of SQL resolution so BOTH the alias existence-gate and the projection see dotted names; reuse the same schemas in the load loop (no double-build) — D-02 / 10-RESEARCH Pattern 4"
    - "Single-base-topic alias gate: count CTE-subtracted base topics; expand only when ==1, keyed on that topic's msgtype, existence-gated on its schema column names (Open Q1 / A3) — safe no-op on JOIN/CTE/multi-topic"
    - "Star short-circuit for projection: has_star(tree) -> restrict=None BEFORE an empty referenced-column set can collapse to STANDARD-only (Pitfall 4/5); compose restrict with the existing heavy-blob include set, never replace it"
    - "Observe-don't-rederive verification: a recording QueryBackend (the existing backend= seam) wraps a real DuckDBBackend and captures the table at register_table; assert on its column_names (a column absent from the Table cannot have had its reduce(getattr) run — research A4)"

key-files:
  created: []
  modified:
    - "packages/rosbagger-core/src/rosbagger_core/backend/query.py — query() reordered + alias keyword + _STANDARD_COLUMNS constant + per-topic restrict computation + rewritten-SQL forwarding"
    - "tests/test_backend_query.py — 8 alias-integration tests + 8 projection/star tests (incl. the _RecordingBackend spy)"

key-decisions:
  - "Single-base-topic gate (Open Q1 LOCKED): the orchestrator counts CTE-subtracted base topics via referenced_tables_in mapped through table_to_topic, ignoring names that map to no topic; expansion runs ONLY when exactly one resolves. >1 or 0 base topics (and alias=False) skip expansion — DuckDB then rejects an unresolved short token. This is what protects the existing JOIN test from mis-expansion."
  - "Schema hoist + typestore move: build_table_schema (O(1) metadata, no reader.read()) is built up front for every mapped topic keyed by sanitized table name, with `typestore = reader.typestore` moved up alongside it (W3 fix — the previous binding in Step 4 was after this point and would NameError). The hoisted schemas are reused in the load loop (build_table_schema appears exactly once)."
  - "Standard columns are unioned into restrict HERE (D-07), not in the schema layer: _STANDARD_COLUMNS = frozenset({t,t_ns,stamp,topic}) is a stdlib-only module constant (offline-safe), unioned into the non-star restrict; the star branch sets restrict=None so a SELECT * never collapses to standard-only (Pitfall 4)."
  - "restrict is computed PER topic against that topic's own schema_names (D-09): over-include on a JOIN (a name in two topics is kept in both), never under-include; table-qualified projection stays deferred."
  - "SC3 proven by observation (W2 fix): a _RecordingBackend implementing the QueryBackend ABC wraps a real DuckDBBackend (forwarding register_table/execute/close) and captures each registered pyarrow.Table; the assertion reads the captured table's column_names — the exact set query() computed and passed to build_arrow_table — NOT a restrict expression re-derived in the test."
  - "Rewritten SQL is forwarded (D-02): backend.execute(tree.sql('duckdb')); when expansion ran, tree carries the expanded dotted columns, else it round-trips the parsed original unchanged. The BinderException catch inspects the exception, not the SQL string, so it still works."

requirements-completed: [QURY-08, QURY-09]

# Metrics
duration: 5min
completed: 2026-05-23
---

# Phase 10 Plan 03: Query-Orchestrator Wiring (alias expansion + projection pushdown) Summary

**Wired both Phase-10 features into `query()` — the integration crux where the alias pack (10-01) and the projection filter (10-02) become observable end-to-end: `query()` gained an `alias=True` keyword, hoists per-topic `TableSchema` construction ahead of SQL resolution (D-02), runs `expand_aliases` gated to the single-base-topic case (Open Q1), recomputes referenced-tables/columns/star on the rewritten tree, computes a per-topic `restrict` set (D-06/D-07/D-08/D-09), and forwards the REWRITTEN SQL (`tree.sql("duckdb")`) — so `SELECT vx FROM cmd_vel` returns the right rows (SC1) while materializing exactly the referenced column plus the four standard columns (SC2/SC3), proven across ROS1 + ROS2-sqlite + MCAP by a recording backend observing the table `query()` actually registers.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-23T05:17:24Z
- **Completed:** 2026-05-23T05:21:59Z
- **Tasks:** 2 (both TDD: RED -> GREEN)
- **Files modified:** 2

## Accomplishments

- **`query()` reordered per D-02 / Pattern 4**, preserving every existing behavior. New order: `parse` -> build topic↔table maps -> **hoist** `typestore` + per-topic `TableSchema` (`schemas_by_table`, O(1) metadata, no `reader.read()`) -> (if `alias`) single-base-topic-gated `expand_aliases` -> `referenced_tables_in`/`referenced_columns`/`has_star` on the **rewritten** tree -> `UnknownTableError` pre-load raise -> load loop (reusing the hoisted schemas) -> `backend.execute(tree.sql("duckdb"))` inside the try/finally with the `BinderException -> UnknownColumnError` catch intact.
- **`alias: bool = True` keyword-only parameter** added and documented (D-11; `alias=False` is the `--no-alias` escape hatch). `expand_aliases` is lazy-imported inside `query()` (offline discipline).
- **Single-base-topic alias gate (Open Q1 LOCKED):** expansion runs only when exactly one distinct CTE-subtracted base topic resolves, keyed on that topic's `msgtype`, existence-gated on its schema column names. JOIN/CTE/multi-topic and `alias=False` leave short tokens untouched (safe no-op) — DuckDB then rejects an unresolved token, which is exactly what keeps the existing JOIN test green.
- **Per-topic projection `restrict` set (D-06/D-07/D-08/D-09)** computed in the load loop (Code Example 4): under a star `include=heavy, restrict=None` (full materialization, D-08); else `include=heavy & columns` (unchanged QURY-07) and `restrict = (columns & schema_names) | _STANDARD_COLUMNS` (D-06 + D-07). Computed and applied **per topic** against that topic's own `schema_names` (over-include on JOIN, never under-include — D-09). Threaded into `build_arrow_table(include=, restrict=)`.
- **`_STANDARD_COLUMNS` frozenset** added as a stdlib-only module constant so the standard-column union (D-07) is offline-safe at module top.
- **SC1 (alias):** `SELECT vx FROM cmd_vel` returns the Twist `linear.x` series `[0.0, 1.0, 2.0]` across all three formats; `alias=False` makes the same query raise `UnknownColumnError`; `SELECT vx AS speed FROM cmd_vel` returns a column named `speed` (rewritten SQL forwarded, output alias preserved).
- **SC2/SC3 (projection):** `SELECT vx FROM cmd_vel` registers a `pyarrow.Table` whose `column_names == {linear.x, t, t_ns, stamp, topic}` and excludes `angular.z`/`linear.y` — proven across ROS1 + ROS2-sqlite + MCAP by a recording `QueryBackend` observing `query()`'s actual registered table. `SELECT *` and `o.*` disable projection (full non-heavy set kept).
- **No regressions:** the existing JOIN, heavy-blob `SELECT *`, projection-omits-blob, filtered-rows, unknown-table, empty-result, swappable-backend, and offline-import tests all stay green.

## Task Commits

Each task was committed atomically following TDD (test RED -> feat GREEN):

1. **Task 1: Hoist schema build + wire alias expansion (single-base-topic gated)**
   - `bebaeff` (test — RED: failing alias-integration tests)
   - `3e3c80b` (feat — GREEN: reorder query(), alias keyword, hoisted schemas, rewritten-SQL forwarding)
2. **Task 2: Compute + thread the projection restrict set (SC2/SC3 + SELECT * opt-out)**
   - `79eb0ca` (test — RED: failing SC3 projection proof via recording backend + star opt-out)
   - `87e9523` (feat — GREEN: per-topic restrict computation threaded into build_arrow_table)

**Plan metadata:** committed separately (`docs(10-03): ...` — SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/backend/query.py` — added `alias: bool = True` keyword-only param; added `_STANDARD_COLUMNS` frozenset; reordered the pipeline (Steps 1-8 in comments): hoisted `typestore = reader.typestore` and the per-topic `schemas_by_table` build ahead of resolution, inserted the single-base-topic-gated `expand_aliases` call, moved `referenced_tables_in`/`referenced_columns`/`has_star` to AFTER expansion, reused the hoisted schemas in the load loop (no double-build), added the per-topic `include`/`restrict` computation, and changed `backend.execute(sql)` -> `backend.execute(tree.sql("duckdb"))`. Lazy-imports `expand_aliases`. Docstring updated to document the new pipeline + the `alias` arg.
- `tests/test_backend_query.py` — added the `QueryBackend` import; 8 alias-integration tests (`-k alias`: SC1 `vx` end-to-end x3 formats, `alias=False` raises `UnknownColumnError` x3, JOIN single-base-topic gate no-op, `AS speed` output-alias preservation) and 8 projection/star tests (`-k projection`/`-k star`: the `_RecordingBackend` spy + SC3 column-set proof x3 formats, filtered-rows regression x3, `SELECT *` opt-out, `o.*` opt-out).

## Decisions Made

- **The single-base-topic gate is the orchestrator's job, not `alias.py`'s.** `expand_aliases` is per-msgtype/per-schema and tree-wide; the orchestrator counts CTE-subtracted base topics (via `referenced_tables_in` mapped through `table_to_topic`, dropping unmapped names) and only calls `expand_aliases` when exactly one resolves (Open Q1 / A3). This is the second safety net over the existence-gate and is what the JOIN no-op test pins.
- **Standard-column union lives here (D-07), not in the schema layer.** Plan 10-02 deliberately did NOT special-case the standard columns in `arrow_schema`/`flatten_message`; this plan unions `_STANDARD_COLUMNS` into the non-star `restrict` so a `SELECT vx` is still plottable (`t_ns`/`stamp` present), and sets `restrict=None` under a star so a `SELECT *` never collapses to standard-only (Pitfall 4).
- **SC3 is proven by observation, not re-derivation (W2 fix).** A `_RecordingBackend` test double implementing the `QueryBackend` ABC wraps a real `DuckDBBackend` (forwarding `register_table`/`execute`/`close` so `execute` runs for real) and captures every registered `pyarrow.Table`; the assertion reads the captured table's `column_names` — the exact set `query()` computed and passed to `build_arrow_table` — rather than re-computing the restrict expression in the test (research A4 / Code Example 5).
- **Rewritten SQL is always forwarded (D-02).** `backend.execute(tree.sql("duckdb"))` round-trips the parsed original unchanged when expansion did not run, and carries the expanded dotted columns when it did — keeping the trusted-SQL boundary (sqlglot-rendered, never hand-concatenated; T-05-04 / T-10-07). The `BinderException` catch inspects the exception object, not the SQL string, so it is unaffected.

## Deviations from Plan

None — plan executed exactly as written. The W2 (recording-backend) and W3 (`typestore` hoist) fixes called out in the plan revision and `<critical_local_constraints>` were implemented as specified, not discovered as deviations. All acceptance-criteria greps passed (alias keyword present, rewritten-SQL forwarded, `build_table_schema` count == 1, `typestore` precedes the build, `expand_aliases` imported + called, the exact `restrict` expression, the star `restrict=None` branch, and `build_arrow_table` with both `include=` and `restrict=`).

## Threat Model Compliance

All `mitigate`-disposition threats in the plan's register are satisfied by the implementation:

- **T-10-07 (Tampering — forwarding rewritten SQL):** the forwarded string is `tree.sql("duckdb")` regenerated by sqlglot from an AST whose only injected nodes are `expand_aliases`' quoted identifiers; the orchestrator builds no SQL by concatenation.
- **T-10-08 (Info disclosure — alias mis-expansion in JOIN/CTE):** the single-base-topic gate (Open Q1) means expansion runs only on an unambiguous single topic; the JOIN no-op test (`test_query_alias_join_no_op_leaves_short_token_untouched`) pins it.
- **T-10-09 (Info disclosure — projection dropping a standard column):** the non-star branch unconditionally unions `_STANDARD_COLUMNS`; the star branch passes `restrict=None`. SC3 + the star tests pin both.
- **T-10-10 (DoS — `SELECT *` collapsing to standard-only):** `has_star(tree)` short-circuits to `restrict=None` before an empty `columns` set can produce `columns | STANDARD`; the qualified-star `o.*` case routes through the same short-circuit; both integration-tested via the recording backend.
- **T-10-SC (Tampering — installs):** zero new packages added; `query.py`'s only new dependency is the in-repo `backend.alias`.

## Issues Encountered

None. The full suite is green (313 passed, 97.73% coverage), the offline-guard suite is green (10 passed — `import rosbagger_core.backend` pulls no heavy stack because `expand_aliases` is lazy-imported inside `query()`), and ruff check + format are clean on both changed files.

## Verification Evidence

- Task 1 verify: `PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_query.py -k "alias or join" -x` -> **9 passed**.
- Task 2 verify: `PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_query.py -k "projection or star or blob" -x` -> **11 passed**.
- Full `test_backend_query.py`: **33 passed** (17 pre-existing + 16 new).
- Full suite: `PYTHONPATH="" .venv/bin/python -m pytest -q` -> **313 passed, 97.73% coverage** (≥80% gate met). Baseline before this plan: 297 passed (per 10-02 SUMMARY).
- Offline-import guard: `tests/test_offline_guard.py` -> **10 passed**.
- `ruff check` + `ruff format --check` on `backend/query.py` + `tests/test_backend_query.py` -> clean.
- SC3 parametrized green across `ros1` + `ros2_sqlite` + `ros2_mcap`, asserting on the table `query()` registers via `_RecordingBackend`.

## Known Stubs

None — this plan is pure integration wiring of two already-shipped seams (10-01 alias pack, 10-02 restrict filter) into the existing orchestrator. No placeholder values, no unwired data sources, no TODO/FIXME introduced.

## Next Phase Readiness

- **QURY-08 and QURY-09 are now fully traceable and observable end-to-end** in `query()`. SC1 (alias `vx` resolves), SC2 (projection loads only referenced columns), and SC3 (single-column query does not materialize unreferenced/heavy columns) are all proven by tests across all three formats.
- **Plan 10-04 (the `bagq query` CLI surface) is unblocked:** it adds a `--no-alias` boolean to the `query` command and forwards `alias=not no_alias` through to `query()`. Projection pushdown needs no flag (it changes only what is loaded, never the result — D-11). The orchestrator keyword (`alias=True`) the CLI threads onto is in place and tested.
- Standing project blocker unchanged (not introduced by this plan): per MEMORY/prior phases, a HUMAN must `git push origin main && git push origin v0.1.0` and observe GitHub Actions green to finalize the v0.1 release.

## Self-Check: PASSED

- Files exist: `packages/rosbagger-core/src/rosbagger_core/backend/query.py`, `tests/test_backend_query.py` — both FOUND.
- Commits exist: `bebaeff` (Task1 RED), `3e3c80b` (Task1 GREEN), `79eb0ca` (Task2 RED), `87e9523` (Task2 GREEN) — all FOUND in git log.
- `query.py` `contains: "expand_aliases"` (artifact check) — present (import line 153, call line 195).
- `tests/test_backend_query.py` `contains: "def test_query_alias"` — present (`test_query_alias_vx_resolves_end_to_end` and 3 more).
- TDD gate sequence verified for both behavior-adding tasks: each `test(...)` RED commit precedes its `feat(...)` GREEN commit.

---
*Phase: 10-query-ergonomics*
*Completed: 2026-05-23*
