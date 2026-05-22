---
phase: 05-query-engine
plan: 01
subsystem: api
tags: [duckdb, pyarrow, sqlglot, abc, query-backend, arrow, sql, offline-guard]

# Dependency graph
requires:
  - phase: 03-schema
    provides: build_table_schema / build_arrow_table / TableSchema / ColumnDef / quote_ident (Arrow tables + the WR-01 fix site)
  - phase: 02-reader
    provides: BagReader ABC + RosbagsReader (the ABC + idempotent-close pattern this seam mirrors)
provides:
  - "QueryBackend ABC (backend/base.py): swappable SQL-over-Arrow seam — register_table / execute -> pyarrow.Table / close + context-manager lifecycle"
  - "DuckDBBackend (backend/duckdb_backend.py): default impl over one in-memory duckdb.connect(); Arrow via to_arrow_table()"
  - "WR-01 fix in build_table_schema: body columns colliding with t/t_ns/stamp/topic are renamed (ros_path preserved); build_arrow_table no longer crashes on hostile field names"
  - "Strengthened offline guard: import rosbagger_core / rosbagger_core.backend leave duckdb/sqlglot/pyarrow out of sys.modules (permanent regression test)"
affects: [05-02-query-orchestrator, 06-output, 07-cli]

# Tech tracking
tech-stack:
  added: []  # duckdb/sqlglot/pyarrow were already declared+installed (Phases 1-3); duckdb newly USED here
  patterns:
    - "QueryBackend ABC mirrors reader/base.py: stdlib-only abstractmethods + inherited __enter__/__exit__ (returns False), execute typed -> object so the seam names no pyarrow"
    - "duckdb imported ONLY at the top of backend/duckdb_backend.py (the offline-import boundary); backend/__init__ stays empty/light"
    - "Unique-name invariant at schema-build time: build_table_schema renames colliding body columns so the downstream name-keyed values dict is safe (single fix resolves all three crash layers)"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/backend/base.py
    - packages/rosbagger-core/src/rosbagger_core/backend/duckdb_backend.py
    - tests/test_schema_collision.py
    - tests/test_backend_duckdb.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
    - tests/test_offline_guard.py

key-decisions:
  - "WR-01 fix renames the BODY column (suffix _ until unique), preserving ros_path/arrow_type/is_heavy_blob; the four standard columns t/t_ns/stamp/topic are NEVER renamed (QURY-04 contract) — RESEARCH Pitfall 1 'namespace the standard column' alternative rejected"
  - "Uniqueness is enforced against prior body names too (taken-set seeded with _STANDARD_COLUMN_NAMES), so two body fields colliding to one name chain to _, __, ..."
  - "QueryBackend.execute returns `object` (not pyarrow.Table) so base.py imports no pyarrow — the seam stays as light as reader/base.py; the real return is a pyarrow.Table"
  - "DuckDBBackend owns ONE in-memory connection per instance (Pitfall 5), uses to_arrow_table() (NOT deprecated fetch_arrow_table), idempotent close mirroring RosbagsReader.close"
  - "backend/__init__.py left empty/light — DuckDBBackend is NOT re-exported at package top level; the documented entry is `import rosbagger_core.backend.duckdb_backend` (W2 invariant)"

patterns-established:
  - "Backend seam pattern: ABC in base.py (stdlib-only), heavy impl in its own module that owns the duckdb import"
  - "Schema-build unique-name invariant downstream code can rely on (documented at build_arrow_table's values dict)"
  - "Fresh-subprocess offline-leak assertion extended from pyarrow/rosbags to the full duckdb/sqlglot/pyarrow heavy stack"

requirements-completed: [QURY-06]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 5 Plan 01: QueryBackend Seam + DuckDB + WR-01 Fix Summary

**Swappable `QueryBackend` ABC with an in-memory `DuckDBBackend` (Arrow register -> `to_arrow_table()` execute -> Arrow), plus the WR-01 fix that renames body columns colliding with `t`/`t_ns`/`stamp`/`topic` so `build_arrow_table` no longer crashes on hostile bags.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-22T10:17:05Z
- **Completed:** 2026-05-22T10:21:59Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments
- **QueryBackend seam (decision 6):** `backend/base.py` — a stdlib-only `abc.ABC` with abstract `register_table`/`execute`/`close` and inherited `__enter__`/`__exit__`, mirroring `reader/base.py`. A future `PolarsBackend`/`SQLiteBackend` slots in behind the same interface.
- **DuckDBBackend (QURY-06):** `backend/duckdb_backend.py` — one in-memory `duckdb.connect()` per instance; `register_table` via `con.register` (zero-copy), `execute` via `con.execute(sql).to_arrow_table()` (the non-deprecated API), idempotent `close`. A `SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5` over a registered Arrow table returns the correct rows; two tables share one connection; empty results keep the full schema.
- **WR-01 fixed at the source:** `build_table_schema` now enforces a unique-name invariant on body columns — a body field named `t`/`t_ns`/`stamp`/`topic` (or a repeated body name) is renamed (suffix `_` until unique) with its `ros_path` preserved. This stops `build_arrow_table`'s name-keyed `values` dict from collapsing duplicate columns and raising `ArrowTypeError` (RESEARCH Pitfall 1, was VERIFIED reproducible).
- **Offline guard hardened (W2):** `test_offline_guard.py` now asserts (in a fresh subprocess) that `import rosbagger_core` and `import rosbagger_core.backend` leave `duckdb`/`sqlglot`/`pyarrow` out of `sys.modules` — converting the previously ad-hoc "light __init__" check into a permanent regression test, with the ROS-blocking assertions intact.

## Task Commits

Each task was committed atomically:

1. **Task 1: WR-01 reserved-name collision fix + regression test** - `9106708` (fix) — TDD: failing collision test + the `build_table_schema` unique-name fix in one logical commit.
2. **Task 2: QueryBackend ABC + DuckDBBackend (+ W2 offline-guard strengthening)** - `58885e0` (feat) — TDD: the seam, the DuckDB impl, the round-trip tests, and the W2 heavy-stack offline assertions.

**Plan metadata:** (this commit) `docs(05-01): complete query-backend seam + WR-01 plan`

_Note: both tasks are TDD; each commit bundles its RED test with its GREEN implementation since the test files are new and the unit is atomic._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/backend/base.py` (created) - `QueryBackend(abc.ABC)`: the swappable seam — abstract `register_table`/`execute`/`close` + inherited context-manager lifecycle; stdlib-only (names no `duckdb`/`pyarrow`).
- `packages/rosbagger-core/src/rosbagger_core/backend/duckdb_backend.py` (created) - `DuckDBBackend(QueryBackend)` over one in-memory connection; `import duckdb` lives ONLY here (the offline boundary); `to_arrow_table()` (not the deprecated `fetch_arrow_table`); idempotent `close`.
- `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py` (modified) - `build_table_schema` enforces the unique-name invariant on body columns (WR-01); added a comment at `build_arrow_table`'s `values` dict documenting the invariant it now relies on.
- `tests/test_schema_collision.py` (created) - WR-01 regression on a crafted `evil_msgs/msg/Collide`: distinct names, preserved standard values, repeated/per-reserved-name collisions, and a Twist no-op.
- `tests/test_backend_duckdb.py` (created) - DuckDBBackend round-trip: subclass/abstract assertions, quoted-dotted-column SELECT, no `DeprecationWarning`, two-table single connection, context-manager + idempotent close + empty-result schema.
- `tests/test_offline_guard.py` (modified) - W2: fresh-subprocess assertions that `import rosbagger_core` / `rosbagger_core.backend` leave the heavy stack out of `sys.modules`; existing ROS-blocking tests untouched.

## Decisions Made
- **Body-column rename (not standard-column rename) for WR-01** — preserves the documented QURY-04 `t`/`t_ns`/`stamp`/`topic` contract; the body field's `ros_path` is kept so its value still extracts. (RESEARCH Assumption A2 / Pitfall 1.)
- **Uniqueness enforced against prior body names too** — the taken-set is seeded with `_STANDARD_COLUMN_NAMES`, so a body field literally named `topic_` alongside a body `topic` chains to `topic`->`topic_`, `topic_`->`topic__`. Proven by `test_repeated_body_collision_gets_further_suffix`.
- **`QueryBackend.execute -> object`** (not `-> pyarrow.Table`) so `base.py` imports no `pyarrow` — keeps the seam as light as `reader/base.py`. The real return is a `pyarrow.Table`, asserted in the impl's tests.
- **`backend/__init__.py` stays empty/light** — `DuckDBBackend` is reachable via `import rosbagger_core.backend.duckdb_backend`, not re-exported at the package top level. This is what makes the W2 `import rosbagger_core.backend` invariant hold.

## Deviations from Plan

None - plan executed exactly as written.

(The plan's grep acceptance criterion `grep -c 'fetch_arrow_table' ... == 0` reads literally as `2` because the impl's docstrings explicitly name the deprecated API to say "NEVER use it"; the criterion's INTENT — no *call* to `fetch_arrow_table` — is satisfied: `grep -c '\.fetch_arrow_table(' == 0`, `grep -c '\.to_arrow_table(' == 2`, and `test_execute_emits_no_deprecation_warning` pins it at runtime. This mirrors the Phase 3 precedent where "only docstring 'do NOT import' mentions" of `duckdb` were allowed. Not a behavior deviation — documented for the verifier.)

## Issues Encountered
- **Ruff SIM117 on the exception-propagation test** — the nested `with pytest.raises(...)` / `with DuckDBBackend()` tripped SIM117 (combine `with` statements). Resolved by combining them onto one line (`with pytest.raises(...), DuckDBBackend() as backend:`), which preserves the test's intent (assert `__exit__` runs AND the exception propagates) and passes ruff. Caught by the host-hazard "run FORMAT then CHECK" discipline before committing.

## User Setup Required

None - no external service configuration required. `duckdb`/`sqlglot`/`pyarrow` are pre-existing, pre-installed, locked dependencies (no install occurred in this plan).

## Next Phase Readiness
- The `QueryBackend` seam + `DuckDBBackend` are ready for the **05-02 orchestrator** (`query(sql, reader)` — sqlglot resolution, topic-table inversion, lazy connection-filtered load, register -> execute).
- WR-01 is fixed, so 05-02 can safely call `build_arrow_table` on arbitrary user bags where the collision is reachable.
- Still pending for 05-02 (per RESEARCH): the `RosbagsReader.read(topics=...)` connection-filter parameter (Pattern 5 / Pitfall 2) for lazy loading — NOT part of this plan.
- Coverage 97.81% (gate >= 80% met); offline guard 2/2 + the new heavy-stack assertions; full suite 150 passed.

## Self-Check: PASSED

- All 4 created files present (`backend/base.py`, `backend/duckdb_backend.py`, `tests/test_schema_collision.py`, `tests/test_backend_duckdb.py`) + the SUMMARY.
- Both modified files present (`schema/flatten.py`, `tests/test_offline_guard.py`).
- Both task commits exist in git: `9106708` (Task 1, fix), `58885e0` (Task 2 + W2, feat).
- Full suite: 150 passed, 97.81% coverage (gate >= 80% met); ruff format + check clean.

---
*Phase: 05-query-engine*
*Completed: 2026-05-22*
