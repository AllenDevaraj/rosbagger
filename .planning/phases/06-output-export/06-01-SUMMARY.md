---
phase: 06-output-export
plan: 01
subsystem: api
tags: [pyarrow, duckdb, rich, typer, csv, parquet, json, output, cli]

# Dependency graph
requires:
  - phase: 05-query-engine
    provides: "query(sql, reader) -> pyarrow.Table (fully-materialized result; backend closed before return)"
  - phase: 04-inspect
    provides: "bagq thin-CLI + rich-render pattern (info/tables); lazy-import-in-body discipline"
  - phase: 03-schema
    provides: "result column types: timestamp[ns] t/stamp, int64 t_ns, string topic, LIST/STRUCT body cols"
  - phase: 02-reader
    provides: "RosbagsReader context manager (caller-owned with-lifecycle)"
provides:
  - "rosbagger_core.output: backend-neutral presentation over a pyarrow.Table"
  - "rows_for_display(table, max_rows) — temporal-safe row coercion (timestamp[ns] never crashes)"
  - "to_json(table) — temporal-safe JSON records (t/stamp as int64 raw-ns)"
  - "write_table(table, path) — CSV/Parquet export by extension via DuckDB COPY"
  - "write_csv_stream(table, path) — CSV to /dev/stdout (no ext detection) for --format csv"
  - "bagq query \"<SQL>\" BAG... [-o OUT] [--format table|csv|parquet|json] command + _render_result"
affects: [07-cli-teaching-errors, 06-02-plot]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backend-neutral output module: stdlib-only top level; pyarrow/duckdb imported INSIDE function bodies (mirrors backend/query.py); re-exporting __init__ binds names without firing heavy imports"
    - "Single shared COPY core (_copy_to) drives both write_table (ext-routed) and write_csv_stream (forced FORMAT CSV); the ONE place this phase builds SQL, path literal '-escaped (T-06-01)"
    - "Temporal-safe coercion: timestamp[ns] cols via combine_chunks().to_numpy(zero_copy_only=False)->datetime64 (NaT->\"\"); to_json casts temporal to int64 raw-ns"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/output/__init__.py
    - packages/rosbagger-core/src/rosbagger_core/output/render.py
    - packages/rosbagger-core/src/rosbagger_core/output/export.py
    - tests/test_output_render.py
    - tests/test_output_export.py
    - tests/test_cli_query.py
  modified:
    - packages/bagq/src/bagq/cli.py
    - tests/test_offline_guard.py

key-decisions:
  - "CSV+Parquet BOTH via DuckDB COPY (not pyarrow.csv.write_csv, which raises ArrowInvalid on LIST cols); CSV LIST renders as bracketed string"
  - "Added write_csv_stream() to back --format csv stdout streaming — write_table is extension-routed so write_table('/dev/stdout') was impossible (Rule 1 fix)"
  - "JSON temporal columns emitted as int64 raw-ns (A5) — machine-parseable, lossless, no ns->datetime crash"
  - "v1 error handling stays simple: UnknownTableError/AnyReaderError/FileNotFoundError propagate (Phase 7 owns teaching errors)"

patterns-established:
  - "Backend-neutral lazy-import output module (offline invariant: import rosbagger_core.output pulls no duckdb/sqlglot/pyarrow)"
  - "Shared _copy_to() export core with single-quote path escaping (T-06-01) — both file export and stdout streaming"
  - "Temporal-safe pyarrow.Table coercion for rich render + JSON"

requirements-completed: [OUT-01, OUT-02, OUT-03]

# Metrics
duration: 7min
completed: 2026-05-22
---

# Phase 6 Plan 01: Output & Export Summary

**Backend-neutral `rosbagger_core.output` (temporal-safe rich render + CSV/Parquet via DuckDB `COPY`) wired to a thin `bagq query "<SQL>" BAG [-o OUT] [--format ...]` command — delivering OUT-01/02/03.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-22T16:44Z
- **Completed:** 2026-05-22T16:52Z
- **Tasks:** 3
- **Files modified:** 8 (6 created, 2 modified)

## Accomplishments
- `rosbagger_core.output` subpackage: `rows_for_display` (temporal-safe — `timestamp[ns]` `t`/`stamp` render via `to_numpy(datetime64)`, never `ValueError`), `to_json` (temporal cols → int64 raw-ns), `write_table` (CSV/Parquet by extension via DuckDB `COPY`), `write_csv_stream` (CSV to `/dev/stdout`). Stdlib-only top level; heavy imports inside function bodies.
- `bagq query "<SQL>" BAG... [-o OUT] [--format table|csv|parquet|json]` command + `_render_result` rich renderer wired into `bagq/cli.py`: opens `RosbagsReader`, calls Phase 5 `query()`, routes the result Arrow table. Verified end-to-end on fixtures (rich table with temporal `t`; `-o out.csv` with a bracketed LIST cell; `-o out.parquet`; `--format json`; `--format csv` streaming; `--format parquet`/unknown errors; `(0 rows)`).
- Offline guard extended: `import rosbagger_core.output` leaks no duckdb/sqlglot/pyarrow (fresh-subprocess regression). Full suite **208 passed at 97.89%** (`--cov-fail-under=80` satisfied); ruff format-check + lint clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: output subpackage — temporal-safe render + DuckDB-COPY export** - `8eec387` (feat)
2. **Task 2: bagq query command + result routing** - `ef16fae` (feat, includes the Rule 1 `write_csv_stream` fix)
3. **Task 3: offline-guard regression + full-suite green** - `8914113` (test)

**Plan metadata:** (this commit) (docs: complete plan)

_Note: Task 1 carried `tdd="true"`; implementation + tests were authored together and verified RED→GREEN against the fixture-backed result tables in one commit (the new files have no prior history to regress against)._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/output/__init__.py` - Output subpackage; stdlib-only top level; re-exports `rows_for_display`/`to_json`/`write_table`/`write_csv_stream`
- `packages/rosbagger-core/src/rosbagger_core/output/render.py` - `rows_for_display` (temporal-safe coercion) + `to_json` (int64 raw-ns temporal)
- `packages/rosbagger-core/src/rosbagger_core/output/export.py` - `_copy_to` (shared COPY core + path escape), `write_table` (ext-routed), `write_csv_stream` (forced CSV)
- `packages/bagq/src/bagq/cli.py` - `query` command + `_render_result` rich renderer (lazy-imports core; top level stays typer/rich)
- `tests/test_output_render.py` - render coercion (timestamp[ns] no-crash, max_rows cap, 0-row, JSON int64-ns)
- `tests/test_output_export.py` - CSV/Parquet write+read-back over /imu (LIST) + /cmd_vel (scalar/empty), unknown-ext, quote-escape, write_csv_stream
- `tests/test_cli_query.py` - CliRunner smoke (default table, -o csv/parquet, --format json, (0 rows), --format parquet guard, --help)
- `tests/test_offline_guard.py` - `test_import_output_subpackage_does_not_pull_heavy_query_stack`

## Decisions Made
- **CSV + Parquet both via DuckDB `COPY`** (not `pyarrow.csv.write_csv`, which raises `ArrowInvalid` on LIST columns — 06-RESEARCH Pitfall 2). One uniform writer; LIST renders as a bracketed string in CSV, round-trips in Parquet.
- **JSON temporal columns → int64 raw-ns** (decision A5): machine-parseable, lossless, sidesteps the `timestamp[ns]`→`datetime` crash class.
- **`--format csv` with no `-o` streams to stdout, `--format parquet` errors** (decision A2): Parquet is binary.
- **v1 error handling propagates** `UnknownTableError`/`AnyReaderError`/`FileNotFoundError` unchanged — Phase 7 (CLI & Teaching Errors) owns did-you-mean enrichment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `--format csv` stdout streaming crashed via `write_table('/dev/stdout')`**
- **Found during:** Task 2 (bagq query routing)
- **Issue:** The plan said to "reuse `write_table` against `/dev/stdout`" for the `--format csv` stdout path. But `write_table` derives its format from the file extension; `/dev/stdout` has none, so it raised `ValueError: Unknown output extension ''` — caught in a real subprocess (`bagq query ... --format csv`), not by the CliRunner tests (CliRunner does not capture OS-fd-level COPY writes). A direct plan-vs-implementation contract conflict.
- **Fix:** Refactored `export.py` to a shared `_copy_to(table, path, opts)` core (the single `COPY` + `'`-escape) and added `write_csv_stream(table, path="/dev/stdout")` that forces `FORMAT CSV` with NO extension detection. The CLI's `--format csv` path now calls `write_csv_stream`. This keeps `COPY` construction + the T-06-01 quote-escape in the core module (so `bagq/cli.py` still imports no duckdb — offline invariant preserved) instead of duplicating SQL in the CLI.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/output/export.py`, `packages/rosbagger-core/src/rosbagger_core/output/__init__.py`, `tests/test_output_export.py` (added `test_write_csv_stream_writes_csv_to_extensionless_target`)
- **Verification:** `bagq query "SELECT t_ns, topic FROM cmd_vel" <bag> --format csv` now streams real CSV to stdout (subprocess-verified); the new export test passes; `write_table`'s extension-routing behavior is unchanged.
- **Committed in:** `ef16fae` (Task 2 commit)

**2. [Rule 3 - Blocking] `zip()` without explicit `strict=` failed `ruff check` (B905)**
- **Found during:** Task 1 (render.py)
- **Issue:** The three `zip` calls in `rows_for_display`/`to_json` tripped lint rule B905 (Python ≥3.10 requires explicit `strict=`), blocking the per-task ruff gate.
- **Fix:** Added `strict=True` to all three (the operands are guaranteed equal-length — same-table columns/names).
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/output/render.py`
- **Verification:** `ruff check .` clean; Task 1 tests still pass.
- **Committed in:** `8eec387` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking lint)
**Impact on plan:** Deviation 1 was a genuine plan/contract conflict (the prescribed `write_table('/dev/stdout')` reuse is impossible given `write_table`'s extension-routing); the fix preserves every stated invariant (offline-safe, one `COPY` core, T-06-01 escape) and adds the missing stdout-CSV capability. Deviation 2 was a trivial lint conformance. No scope creep; all OUT-01/02/03 success criteria met.

## Issues Encountered
- `cli.py` shows 2 uncovered lines (the `>max_rows` "... N more rows" footer and the parquet `BadParameter` raise line). The parquet guard's *behavior* is tested (`test_query_format_parquet_without_output_errors` asserts a non-zero exit) — typer unwinds `BadParameter` before the line registers under CliRunner. Coverage is 97.89% (far above the 80% gate), so neither was force-covered.

## User Setup Required
None - no external service configuration required (duckdb/pyarrow/rich/typer are pre-existing locked deps; this plan added no package — matplotlib for `--plot` lands in 06-02).

## Next Phase Readiness
- **06-02 (`--plot`)** ready: it layers `plot_table` onto the same `output/` subpackage and a `--plot [FILE]` option onto the now-wired `bagq query` command; adds matplotlib to the dev group.
- **Phase 7 (CLI & Teaching Errors)** ready: the `bagq query` skeleton + error-propagation seam is in place for did-you-mean / unknown-column enrichment.
- No blockers.

---
*Phase: 06-output-export*
*Completed: 2026-05-22*

## Self-Check: PASSED

All created files exist on disk (output `__init__`/`render`/`export`, three test files, this SUMMARY) and all three task commits (`8eec387`, `ef16fae`, `8914113`) are present in git history.
