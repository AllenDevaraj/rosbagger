---
phase: 05-query-engine
plan: 02
subsystem: api
tags: [sqlglot, duckdb, pyarrow, rosbags, sql-resolution, query-orchestrator]

# Dependency graph
requires:
  - phase: 05-query-engine (plan 01)
    provides: "QueryBackend ABC (backend/base.py) + DuckDBBackend (backend/duckdb_backend.py); WR-01 fix in build_table_schema"
  - phase: 03-schema
    provides: "build_table_schema / build_arrow_table / TableNameResolver (topic->table sanitization, lazy heavy-blob include= seam)"
  - phase: 02-reader
    provides: "RosbagsReader / BagReader seam (open/close/read/topics/typestore over AnyReader)"
  - phase: 04-inspect
    provides: "inspect.collect_table_schemas — the shared-resolver topic->table map pattern this plan mirrors and inverts"
provides:
  - "backend/resolve.py — sqlglot SQL resolver: referenced_tables (CTE-alias-subtracted), referenced_columns, has_star, parse (parse-once)"
  - "RosbagsReader.read(*, topics=) — connection-level filter via AnyReader.messages(connections=...) so unreferenced topics are never deserialized (declared on the BagReader ABC too)"
  - "backend/query.py — query(sql, reader, *, backend=None) -> pyarrow.Table end-to-end orchestrator (resolve -> invert -> lazy-load -> register -> execute) + UnknownTableError"
affects: [06-output, 07-cli]

# Tech tracking
tech-stack:
  added: []  # no new deps — sqlglot/duckdb/pyarrow/rosbags all pre-existing locked deps
  patterns:
    - "Parse SQL once (resolve.parse) and pass the one tree to referenced_tables_in/referenced_columns/has_star — never re-parse"
    - "Connection-level lazy load: read(topics={t}) filters at AnyReader.messages(connections=...), NOT after deserialization"
    - "Orchestrator owns only the default backend's lifecycle; a caller-supplied backend= is left open for reuse"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/backend/resolve.py
    - packages/rosbagger-core/src/rosbagger_core/backend/query.py
    - tests/test_backend_resolve.py
    - tests/test_backend_query.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py
    - packages/rosbagger-core/src/rosbagger_core/reader/base.py
    - packages/rosbagger-core/src/rosbagger_core/backend/__init__.py

key-decisions:
  - "read(topics=set()) / an unknown topic yields an EMPTY stream, not all topics — rosbags treats messages(connections=()) as its all-connections default, so an empty conn list short-circuits to nothing (Rule 1 bug fix)"
  - "query() owns the lifecycle of ONLY the default backend (try/finally close); a caller-supplied backend= is left open so it can be reused across queries (refined from the plan's literal 'use with')"
  - "UnknownTableError subclasses ValueError so existing except-ValueError handlers still catch it while callers get a typed handle; the message lists available tables, did-you-mean deferred to Phase 7"

patterns-established:
  - "Parse-once SQL resolution: resolve.parse(sql) -> one tree -> referenced_tables_in/referenced_columns/has_star"
  - "Lazy connection-filtered topic load (QURY-05): unreferenced topics are never handed to deserialize"
  - "SELECT * (exp.Star) opts into heavy blobs; an explicit projection includes only the heavy-blob columns it names (QURY-07 include= seam)"

requirements-completed: [QURY-05, QURY-06]

# Metrics
duration: 10min
completed: 2026-05-22
---

# Phase 5 Plan 02: Query Engine (SQL resolution + orchestration) Summary

**`query(sql, reader)` ties sqlglot SQL resolution -> topic->table inversion -> connection-filtered lazy load -> DuckDB register/execute end-to-end, returning a pyarrow.Table; only the referenced topics are ever deserialized and `SELECT *` materializes heavy blobs.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-22T10:22:00Z (after 05-01)
- **Completed:** 2026-05-22T10:32:30Z
- **Tasks:** 2
- **Files modified:** 7 (4 created, 3 modified)

## Accomplishments

- **`backend/resolve.py`** — `sqlglot`-based SQL inspection: `referenced_tables` (every `exp.Table.name` MINUS `exp.CTE` alias names, so a CTE is never mistaken for a topic), `referenced_columns` (the `exp.Column.name`s, including a quoted dotted `"linear.x"`), `has_star` (any `exp.Star` ⇒ "include blobs"), and `parse` so the orchestrator parses once. `sqlglot` at module top (offline-safe, mirrors `schema/identifiers.py`); no `duckdb` import.
- **`RosbagsReader.read(*, topics=)`** — a connection-level filter that forwards the matching connections to `AnyReader.messages(connections=...)`, so unreferenced topics are **never deserialized** (QURY-05). Declared on the `BagReader` ABC too (A3 — keeps the seam honest for a future `rosbag2_py` backend). Proven by a monkeypatched `deserialize` that records only `geometry_msgs/msg/Twist` during a `/cmd_vel`-only read.
- **`backend/query.py`** — `query(sql, reader, *, backend=None) -> pyarrow.Table`: parse once, resolve CTE-subtracted tables/columns/star, build + invert the topic->table map via a shared `TableNameResolver` (skipping multi-msgtype topics, mirroring `inspect.collect_table_schemas`), raise a clear `UnknownTableError` listing available tables on an unmapped name (before loading anything), then per referenced topic build the schema, compute the heavy-blob `include` set (referenced blob cols, OR all blob cols when `SELECT *`), lazily `reader.read(topics={topic})`, `build_arrow_table`, register under the sanitized name, and `backend.execute(sql)`. Heavy stack imported lazily inside the function; the user's SQL is forwarded as-is (trusted interface).
- Verified end-to-end across all three formats (ros1, ros2_sqlite, ros2_mcap): `SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5` -> `t_ns=[1_100_000_000, 1_200_000_000]`, `linear.x=[1.0, 2.0]`.

## Task Commits

Each task was committed atomically:

1. **Task 1: sqlglot resolver + connection-filtered read(topics=)** - `57b6e81` (feat)
2. **Task 2: query(sql, reader) orchestrator** - `2ef0018` (feat)

_TDD tasks: test + implementation co-developed and committed atomically per this repo's established convention (matches 05-01 and prior phases)._

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/backend/resolve.py` (created) - sqlglot SQL resolver (parse, referenced_tables[_in], referenced_columns, has_star)
- `packages/rosbagger-core/src/rosbagger_core/backend/query.py` (created) - the `query(sql, reader)` orchestrator + `UnknownTableError`
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` (modified) - `read(*, topics=)` connection-level filter
- `packages/rosbagger-core/src/rosbagger_core/reader/base.py` (modified) - matching `read(*, topics=)` on the ABC, documented
- `packages/rosbagger-core/src/rosbagger_core/backend/__init__.py` (modified) - documents lazy entry points; no eager import (stays light)
- `tests/test_backend_resolve.py` (created) - resolver unit cases + the read(topics=) deserialize-only-requested proof (12 tests, parametrized to 24)
- `tests/test_backend_query.py` (created) - end-to-end query tests across 3 formats, blob include/omit, unknown-table, empty-result, swappable backend (17 tests)

## Decisions Made

- **`read(topics=set())` / unknown topic yields an empty stream, not all topics.** `rosbags`' `AnyReader.messages(connections=())` treats an empty connection list as its all-connections default, so naively passing `[]` would yield *everything*. The reader now short-circuits to an empty stream when the filter resolves to zero connections — correct for a caller that referenced no (or only unknown) topics. (Rule 1 — see Deviations.)
- **`query()` owns only the default backend's lifecycle.** The plan said "use `with` so it closes even on error," but a caller-supplied `backend=` may be reused across queries, so closing it would be wrong. Implemented as a `try/finally` that closes the backend only when `query` constructed the default — a caller-supplied backend is left open. (Refinement of the plan's literal guidance; see Deviations.)
- **`UnknownTableError(ValueError)`.** A typed error (the plan permitted "a small typed error defined here" or a plain `ValueError`); subclassing `ValueError` keeps existing `except ValueError` handlers working while giving callers a handle. Message lists available tables; did-you-mean is Phase 7.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `read(topics=)` empty/unknown-filter returned all topics instead of none**
- **Found during:** Task 1 (connection-filtered read)
- **Issue:** A test (`test_read_topics_empty_set_yields_nothing`) revealed that `read(topics=set())` and `read(topics={"/unknown"})` yielded all 9 messages. Root cause: `AnyReader.messages(connections=[])` interprets an empty connection list as its all-connections default sentinel, so an empty filter wrongly disabled filtering.
- **Fix:** When `topics` is given (not `None`) but resolves to zero matching connections, `read` short-circuits with an early `return` (empty stream) instead of calling `messages(connections=[])`.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py`
- **Verification:** `test_read_topics_empty_set_yields_nothing` passes; the `/cmd_vel`-only filter still yields exactly 3; `read()` (no filter) still yields all 9 time-ordered.
- **Committed in:** `57b6e81` (Task 1 commit)

**2. [Rule 1 - Correctness] Backend lifecycle: do not close a caller-supplied backend**
- **Found during:** Task 2 (orchestrator)
- **Issue:** The plan's literal "enter the backend via `with` so it closes on error" would close a caller-supplied `backend=`, breaking reuse across queries (the backend is swappable per call and the caller may keep it open).
- **Fix:** `query()` tracks `own_backend = backend is None` and uses `try/finally` to close the backend **only** when it constructed the default `DuckDBBackend`; a caller-supplied backend is left open. `execute()` fully materializes the Arrow result before any close, so the returned table outlives the connection regardless.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py`
- **Verification:** `test_query_accepts_a_supplied_backend` runs two queries on one supplied `DuckDBBackend` instance (the second would fail on a closed connection); the default-backend path is covered by every other end-to-end test.
- **Committed in:** `2ef0018` (Task 2 commit)

**3. [Rule 3 - Blocking] Reworded `resolve.py` docstring to satisfy the acceptance grep**
- **Found during:** Task 1 (acceptance-criteria check)
- **Issue:** The acceptance criterion `grep -c 'import duckdb' resolve.py == 0` matched the docstring phrase "There is NO `import duckdb` here" (a literal substring), returning 1.
- **Fix:** Reworded the docstring to "The duckdb dependency is never pulled in here" so the literal `import duckdb` substring is absent; there was never an actual import.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/backend/resolve.py`
- **Verification:** `grep -c 'import duckdb' resolve.py` is now `0`; ruff still clean.
- **Committed in:** `57b6e81` (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (2 bug/correctness, 1 blocking). **Impact on plan:** All three were necessary for correctness or to satisfy the stated acceptance criteria; no scope creep. The empty-filter fix and the backend-lifecycle refinement both make the public seams more correct than the plan's literal text.

## Issues Encountered

None beyond the deviations above. The `query.py` line 79 (`continue` in the multi-msgtype-skip branch) is uncovered because no fixture carries a multi-msgtype topic — a defensive guard mirroring the same uncovered line in `inspect.collect_table_schemas`; no pragma added (consistent with the Phase 2-3 precedent).

## Known Stubs

None. `resolve.py` and `query.py` are fully wired — no hardcoded empty values, placeholders, or unwired data sources.

## User Setup Required

None - no external service configuration required (offline, no-ROS, all deps pre-installed/locked).

## Verification

- `PYTHONPATH="" uv run pytest tests/test_backend_resolve.py tests/test_backend_query.py tests/test_reader.py tests/test_offline_guard.py -q` -> **57 passed**.
- Full suite: `PYTHONPATH="" uv run pytest -q` -> **186 passed at 97.91%** (coverage gate ≥80% met; `resolve.py` 100%, `query.py` 98%, `base.py`/`__init__` 100%).
- Offline guard intact: `import rosbagger_core` and `import rosbagger_core.backend` pull no `duckdb`/`sqlglot`/`pyarrow` (fresh-subprocess regression tests green).
- `PYTHONPATH="" uv run ruff format .` -> 36 files unchanged; `ruff check .` -> all checks passed.
- Acceptance greps: `messages(connections=` in rosbags_reader.py ≥1; `import duckdb` in resolve.py == 0; `TableNameResolver` in query.py ≥1; `read(topics=` in query.py ≥1.

## Next Phase Readiness

- **Phase 5 COMPLETE (2/2).** The query engine is whole: a swappable `QueryBackend` seam (05-01) + `query(sql, reader) -> pyarrow.Table` (05-02). QURY-05 (resolve referenced topics, load only those) and QURY-06 (execute through the backend) are both done and verified.
- **Phase 6 (output)** consumes the returned `pyarrow.Table` for CSV/Parquet/plot. Carry-forward flag (05-RESEARCH Pitfall 6): for **display**, use the `t_ns` (BIGINT) column, NOT `.to_pylist()` on a `t`/`stamp` `timestamp[ns]` column — that can raise in pure Python (no pandas). DuckDB/Arrow round-trip ns losslessly; this only bites the output layer.
- **Phase 7 (CLI)** owns the `with RosbagsReader(paths) as reader:` lifecycle and passes the reader to `query()`. It also owns teaching errors: `UnknownTableError` already lists available tables; the did-you-mean suggestion (CLI-02) layers on top. Column-not-found errors from DuckDB (`BinderException`) currently fall through — Phase 7 can wrap them.

---
*Phase: 05-query-engine*
*Completed: 2026-05-22*

## Self-Check: PASSED

- Created files verified on disk: `backend/resolve.py`, `backend/query.py`, `tests/test_backend_resolve.py`, `tests/test_backend_query.py`, `05-02-SUMMARY.md`.
- Task commits verified in git log: `57b6e81` (Task 1), `2ef0018` (Task 2).
