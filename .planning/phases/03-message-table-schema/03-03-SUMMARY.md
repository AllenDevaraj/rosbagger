---
phase: 03-message-table-schema
plan: 03
subsystem: schema
tags: [pyarrow, arrow, sqlglot, rosbags, duckdb, schema, flatten]

# Dependency graph
requires:
  - phase: 03-message-table-schema (03-01)
    provides: ColumnDef/TableSchema model, sanitize_table_name, TableNameResolver, arrow_schema stub
  - phase: 03-message-table-schema (03-02)
    provides: ROS->Arrow type map (arrow_type_of/is_heavy_blob), build_table_schema flatten walk, STANDARD_COLUMNS
  - phase: 02-bag-reader-layer
    provides: RosbagsReader + Message record (the row-extract input; typestore via reader._reader.typestore)
provides:
  - "flatten_message(msg, schema, *, include=...) — row-value extractor by ros_path (reduce(getattr, path, msg))"
  - "build_arrow_table(messages, schema, *, include=...) — Message stream -> typed pyarrow.Table (backend-neutral)"
  - "TableSchema.arrow_schema(include=...) — real pyarrow.Schema honoring the lazy heavy-blob include seam (no longer NotImplementedError)"
  - "schema/identifiers.py quote_ident — SQL-injection-safe quoted identifier via sqlglot (T-03-06 defense)"
  - "public schema/__init__.py re-exporting the schema API (mirrors reader/__init__ convention)"
affects: [04-inspect, 05-query-engine, 06-output-export]

# Tech tracking
tech-stack:
  added: []  # no new deps — pyarrow/sqlglot/rosbags/duckdb already locked Phase 1
  patterns:
    - "Build per-column Arrow arrays with explicit ColumnDef.arrow_type (never inferred) — stable schema across messages (Pitfall 1)"
    - "Lazy heavy-blob include seam keyed on the dotted column name (QURY-07); arrow_schema drives the kept-column set so build stays in lockstep"
    - "All SQL identifiers via sqlglot.exp.to_identifier(quoted=True) — never f-string hand-quoting (T-03-06)"
    - "pyarrow imported INSIDE TableSchema.arrow_schema so model.py stays stdlib-light at module top"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/schema/identifiers.py
    - packages/rosbagger-core/src/rosbagger_core/schema/__init__.py
    - tests/test_schema_arrow.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
    - packages/rosbagger-core/src/rosbagger_core/schema/model.py
    - tests/test_schema_names.py

key-decisions:
  - "build_arrow_table drives its kept-column set off schema.arrow_schema(include=...).names so the Table schema and the value arrays are guaranteed in lockstep (single source of truth)"
  - "Standard columns identified by empty ros_path; their values pulled off the Message record by the SAME attribute name (t/t_ns/stamp/topic) — data columns by ros_path"
  - "pyarrow imported inside arrow_schema (not at model.py top) to preserve the stdlib-light top-level import (Phase 1 decision); arrow_type values are already real pyarrow types from the flatten/types builders"
  - "Updated 03-01's stale arrow_schema 'deferred/NotImplementedError' test to assert the now-implemented include-honoring behavior (Rule 1 — my change made the old assertion obsolete)"

patterns-established:
  - "Pattern: ndarray array-values passed straight to pa.array(values, type=col.arrow_type) — never .tolist()'d (Pitfall 2)"
  - "Pattern: empty Message stream still yields a typed empty Table via the explicit arrow_schema (RESEARCH §7)"
  - "Pattern: offline guard re-asserted in a FRESH subprocess so an already-imported pyarrow/rosbags in the test process can't mask a top-level leak"

requirements-completed: [QURY-03, QURY-07]

# Metrics
duration: 7min
completed: 2026-05-22
---

# Phase 3 Plan 03: Row Extraction + Arrow Table Build Summary

**Turns a stream of `Message`s into a backend-neutral `pyarrow.Table` per topic — dotted columns extracted by `ros_path`, arrays as LIST / sub-message arrays as LIST<STRUCT> with short inner names, heavy byte blobs lazy via an `include` seam (QURY-03/07) — plus the real `arrow_schema`, the `sqlglot` `quote_ident` injection defense, and the public `schema/` API.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-22T08:54:44Z
- **Completed:** 2026-05-22T09:01:44Z
- **Tasks:** 3 (all TDD: RED -> GREEN, one REFACTOR)
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments

- `flatten_message(msg, schema, *, include=...)` — extracts each non-standard leaf's value via `reduce(getattr, col.ros_path, msg)`; ndarrays passed straight through (Pitfall 2); heavy blobs omitted unless named.
- `build_arrow_table(messages, schema, *, include=...)` — consumes a `Message` stream once, builds each column with its explicit `ColumnDef.arrow_type`, and assembles a `pyarrow.Table` whose schema is exactly `schema.arrow_schema(include=...)`. Standard columns sourced off the `Message` record (`t`/`stamp` as `timestamp("ns")`, `t_ns` as `int64`, `topic` as `string`). A zero-message stream still yields a typed empty Table (RESEARCH §7).
- `TableSchema.arrow_schema(include=...)` — replaced the `NotImplementedError` stub with a real `pa.schema(...)` honoring the heavy-blob filter; `stamp` field explicitly nullable.
- `schema/identifiers.py` `quote_ident` — `sqlglot.exp.to_identifier(name, quoted=True)`; escapes embedded quotes (`weird"name` -> `"weird""name"`) and neutralizes `x"; DROP TABLE y;--` (T-03-06).
- Public `schema/__init__.py` re-exporting the API (mirrors `reader/__init__`); `import rosbagger_core` stays light (offline guard 2/2, verified in a fresh subprocess).
- Verified end-to-end on fixtures: `/cmd_vel` and `/imu` `Message` streams -> `pa.Table` with correct dotted columns/values; DuckDB round-trip yields the spec types (`TIMESTAMP_NS`/`BIGINT`/`DOUBLE`/`VARCHAR`) and a quoted-identifier query returns correct rows.

## Task Commits

Each task was committed atomically (TDD: test -> feat, plus one refactor folded into Task 2's GREEN):

1. **Task 1: arrow_schema(include=...) + sqlglot quote_ident**
   - `9e4a4d7` (test — RED) / `b9e0536` (feat — GREEN)
2. **Task 2: flatten_message + build_arrow_table**
   - `5717606` (test — RED) / `d860fb5` (feat — GREEN; build_arrow_table simplified to drive off arrow_schema.names before commit)
3. **Task 3: public schema/__init__ + end-to-end / LIST<STRUCT> / offline-guard tests**
   - `8d7d017` (test — RED) / `9bc1a28` (feat — GREEN; also updated 03-01's stale arrow_schema test)

**Plan metadata:** _(this commit)_ — `docs(03-03): complete row-extract + Arrow build plan`

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py` — added `flatten_message` (row extractor) and `build_arrow_table` (Message stream -> `pa.Table`); module docstring extended to cover the row-extract/Arrow-build half.
- `packages/rosbagger-core/src/rosbagger_core/schema/model.py` — implemented `TableSchema.arrow_schema(include=...)` (was a `NotImplementedError` stub); `pyarrow` imported inside the method.
- `packages/rosbagger-core/src/rosbagger_core/schema/identifiers.py` — NEW: `quote_ident` (sqlglot identifier-safety boundary).
- `packages/rosbagger-core/src/rosbagger_core/schema/__init__.py` — NEW (replaced the docstring-only seam): public re-exports + `__all__`.
- `tests/test_schema_arrow.py` — NEW: 26 fixture-backed tests (arrow_schema, quote_ident, flatten_message, build_arrow_table, end-to-end /imu across 3 formats, LIST<STRUCT>, lazy blob, offline guard).
- `tests/test_schema_names.py` — updated one 03-01 test (the now-obsolete "arrow_schema deferred / NotImplementedError" assertion) to assert the implemented include-honoring behavior.

## Decisions Made

- **`build_arrow_table` is driven by `arrow_schema(include=...).names`** as the single source of truth for the kept-column set, so the Table's schema and its value arrays cannot drift apart.
- **Standard vs data columns distinguished by `ros_path`** — empty `ros_path` -> standard column sourced off the `Message` record by the same attribute name; non-empty -> body column via `flatten_message`.
- **`pyarrow` imported inside `arrow_schema`** (not at `model.py` top level) to keep the backend-neutral model importable without the heavy stack and preserve the light top-level import graph (Phase 1 decision).
- **`duckdb` stays entirely out of shipped `schema/` code** — verified zero real `import duckdb` statements (only docstring "do NOT import" mentions). The DuckDB type round-trip was exercised only as a dev-time sanity check, not in committed code (research-sanctioned: a *test* may register Arrow to assert types; here it was an ad-hoc check, so no duckdb test dependency was added to the suite).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated 03-01's stale `arrow_schema` deferral test**
- **Found during:** Task 3 (running the full suite with coverage)
- **Issue:** `tests/test_schema_names.py::test_arrow_schema_is_deferred_to_03_03` asserted `arrow_schema()` raises `NotImplementedError`. Task 1 implemented the method, so the assertion was obsolete; worse, the test's `_sample_table_schema` used string placeholders (`"ts"`, `"str"`) for `arrow_type` (intentional — that file is pyarrow-free), so calling the now-real method raised `ValueError: No type alias for ts` and failed the full-suite run.
- **Fix:** Replaced the deferral test with `test_arrow_schema_implemented_and_honors_include`, which builds a small pyarrow-typed `TableSchema` locally and asserts `arrow_schema()` omits the heavy `data` blob by default and re-adds it (as `list<uint8>`) under `include={"data"}`.
- **Files modified:** `tests/test_schema_names.py`
- **Verification:** `PYTHONPATH="" uv run pytest -q` -> 88 passed at 96.43% coverage.
- **Committed in:** `9bc1a28` (Task 3 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug — stale test obsoleted by the implementation).
**Impact on plan:** Necessary to keep the suite green; no scope creep. The plan explicitly anticipated arrow_schema moving from stub to implemented, so updating its 03-01 assertion is in-scope cleanup.

## Issues Encountered

- The full-suite run initially failed on the stale 03-01 test (above). Resolved by updating that single assertion. The targeted per-task runs (`-k`/single-file) all passed throughout; the failure only surfaced under the whole-suite collection, which is exactly why the full coverage run is the gate.

## Threat Model Compliance

- **T-03-06 (Tampering — SQL identifier injection):** `quote_ident` renders all identifiers via `sqlglot.exp.to_identifier(quoted=True)`; tests assert the dotted-quote, embedded-quote-escape, and injection-neutralization cases by exact string. No f-string hand-quoting anywhere.
- **T-03-07 (DoS — heavy-blob materialization):** the QURY-07 lazy `include` seam is enforced in BOTH `arrow_schema` (column dropped) and `build_arrow_table`/`flatten_message` (value never read) — a query that never references `data` never materializes the multi-MB blob. Verified: default `/image` Table has no `data` column; `include={"data"}` adds a `list<uint8>` column.
- **T-03-08 (accept):** field values carried as inert Arrow data; arrays built with explicit `type=` (prevents schema-confusion from a hostile empty/heterogeneous stream).
- **T-03-SC (accept):** no installs — all deps locked Phase 1.

## User Setup Required

None — no external service configuration required. (Offline, local-file library.)

## Next Phase Readiness

- **Phase 3 is COMPLETE (3/3 plans).** The schema layer now emits a backend-neutral `pyarrow.Table` per topic with dotted columns, LIST/LIST<STRUCT>, the four standard columns, and the lazy heavy-blob `include` seam; the public `schema/` API is exported cleanly.
- **Phase 4 (Inspect):** `bagq tables` can render a `TableSchema` (table name + columns) — the model and `TableNameResolver.mapping` are ready.
- **Phase 5 (Query Engine):** can register `build_arrow_table(...)` zero-copy into DuckDB and drive the `include` set from sqlglot column references; `quote_ident` is the identifier-safety boundary to wire into SQL-build. The Arrow->DuckDB type round-trip was verified (`TIMESTAMP_NS`/`BIGINT`/`DOUBLE[]`/`STRUCT(...)[]`).
- **Offline invariant intact:** top-level `import rosbagger_core` pulls in no `pyarrow`/`rosbags` (offline guard 2/2); importing `rosbagger_core.schema` is heavy-by-design (like `reader`).
- **No blockers.** No `duckdb` import in shipped schema code (Phase 5 concern).

## Self-Check: PASSED

- All created files verified on disk (`identifiers.py`, `schema/__init__.py`, `tests/test_schema_arrow.py`, `03-03-SUMMARY.md`).
- All 6 task commits verified in git log (`9e4a4d7`, `b9e0536`, `5717606`, `d860fb5`, `8d7d017`, `9bc1a28`).
- Full suite: 88 passed at 96.43% coverage (gate `--cov-fail-under=80` held); ruff check + format clean.

---
*Phase: 03-message-table-schema*
*Completed: 2026-05-22*
