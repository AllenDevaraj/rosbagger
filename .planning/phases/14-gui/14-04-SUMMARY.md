---
phase: 14-gui
plan: 04
subsystem: ui
tags: [textual, tui, datatable, tree, thin-face, offline-invariant, query, export]

# Dependency graph
requires:
  - phase: 14-gui (plan 14-02)
    provides: RosbaggerApp shell — shared single-open RosbagsReader (D-02), ContentSwitcher panel registry, the open_bag() bag-switch seam, and the query STUB panel this plan fills
  - phase: 14-gui (plan 14-03)
    provides: the refresh_view() panel data-refresh convention + the app.open_bag bag-switch callback wired to it (this plan's schema Tree reuses it)
  - phase: 05-query
    provides: query(sql, reader) -> pyarrow.Table (the ONLY query API the panel calls)
  - phase: 06-output
    provides: write_table(table, path) — extension-dispatched LIST/STRUCT-safe writer (the ONLY export API)
  - phase: 07-errors
    provides: UnknownTableError / UnknownColumnError / UnresolvedTypeError teaching errors (caught + presented, never built, in the panel)
  - phase: 04-inspect
    provides: collect_table_schemas (the schema/topic Tree source)
provides:
  - QueryPanel (D-06) — thin face over query() + collect_table_schemas + write_table delivering a SQL Input + results DataTable + schema Tree click-to-insert + history/re-run + CSV/Parquet export, with ZERO SQL/format/selection logic
affects: [14-gui plan 14-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Thin-face query panel: collects a SQL STRING + an export PATH and forwards them VERBATIM to query()/write_table — builds no SQL, picks no serialization format, runs no analysis (the SC3 second half)"
    - "Schema Tree click-to-insert: collect_table_schemas → one Tree branch per table_name, a leaf per col.name carrying the name as node data; on NodeSelected the leaf's data is inserted at the SQL input cursor VERBATIM (no SQL construction)"
    - "Teaching-error presentation: the Phase-7 ValueError subclasses are caught and str(e) is rendered to a status Static — the GUI presents the message, core builds it (API-first)"
    - "Offline-import invariant held: query() / collect_table_schemas / write_table all imported INSIDE method bodies; importing the panel module leaks no rclpy/rosbags/pyarrow/duckdb/sqlglot"

key-files:
  created: []
  modified:
    - packages/rosbagger-gui/src/rosbagger_gui/panels/query.py

key-decisions:
  - "QueryPanel switched from the 14-02 Static stub to a Vertical container so it can compose its own children (SQL bar, schema Tree, results DataTable, export bar, history) — the plan's QueryPanel(Widget) shape; offline/live gating is unaffected (data in the _PANELS registry; query is offline, always enabled)"
  - "Run is bound to BOTH Enter-on-input (on_input_submitted — the SC3 'press enter' path) AND a Run Button (on_button_pressed) so the panel runs the same _run_query() regardless of input device"
  - "History entries are ListItem widgets carrying the raw SQL on a private _sql attribute; selecting one repopulates sql-input (re-run by pressing Run again) — the panel stores the string verbatim, builds no SQL"
  - "Export defaults to query_result.csv / query_result.parquet in CWD; the panel supplies ONLY the path (matching suffix) and lets write_table choose the serialization from the extension — no format/COPY string in the GUI. Buttons start disabled and enable once a result exists"
  - "Result cells are str()-rendered into the DataTable (14-RESEARCH temporal note) so a timestamp[ns] / LIST column displays without the ns->datetime crash class; query() already bounds the result (QURY-07) so to_pylist() is safe (never an unbounded raw stream)"

requirements-completed: [GUI-01]

# Metrics
duration: 8min
completed: 2026-05-24
---

# Phase 14 Plan 04: Query Offline Panel Summary

**QueryPanel is now a thin face over `query()` / `collect_table_schemas` / `write_table` — a SQL `Input` (+ Run button) whose result `pyarrow.Table` is mapped into the `results` `DataTable`, a `schema-tree` `Tree` whose column leaves insert their name verbatim into the SQL box, a re-runnable query history, and CSV/Parquet export buttons that write the last result through the real `write_table` path — with ZERO SQL/format/selection logic in the GUI, the Phase-7 teaching errors presented (not built) on a bad query, and the offline-import invariant intact.**

## Performance

- **Duration:** ~8 min
- **Tasks:** 2
- **Files modified:** 1 (0 created, 1 modified)

## Accomplishments

- **Task 1 — SQL input + results + history (D-06):** `QueryPanel(Vertical)` composes an `Input` (`sql-input`), a Run `Button` (`run-query`), a `results` `DataTable`, a `query-status` `Static`, and a `history` `ListView`. `_run_query()` reads the SQL string + the App's single shared reader, lazily imports `from rosbagger_core.backend.query import query`, and calls `query(sql, reader)` VERBATIM; the `pyarrow.Table` is mapped into `results` via 14-RESEARCH Pattern 4 (`add_columns(*column_names)` + a `str()`-rendered row per `to_pylist()` entry — temporal/LIST-safe). The teaching errors (`UnknownTableError`/`UnknownColumnError`/`UnresolvedTypeError`) are caught and `str(e)` rendered to `query-status` — no traceback. Each successful SQL is appended to `history`; selecting an entry repopulates `sql-input`. Proven headless against the ROS 2 sqlite fixture: `SELECT topic, t_ns FROM cmd_vel LIMIT 2` filled `results` with 2 rows (cols `topic`/`t_ns`); a `SELECT * FROM nope_table` surfaced `Unknown table 'nope_table'. ...` to the status line without crashing.
- **Task 2 — schema Tree + export (D-06):** `refresh_view()` lazily imports `collect_table_schemas` and builds the `schema-tree` `Tree` — one branch per `TableSchema.table_name`, a leaf per `columns[*].name` (the column name carried as node `data`). On `Tree.NodeSelected` for a leaf, the column name is inserted VERBATIM (`Input.insert_text_at_cursor`) at the SQL cursor — the panel constructs no SQL. Two export `Button`s (`export-csv`, `export-parquet`, disabled until a result exists) call `write_table(last_result, path)` with a default `query_result.csv` / `.parquet` path; the serialization is chosen by `write_table` from the extension — the panel supplies only a path. Export errors are surfaced to `query-status`. Proven headless: the tree built 3 table branches (`cmd_vel`/`image`/`imu`) with column leaves, click-to-insert put `t` into the empty SQL box, and after a 3-row query both `query_result.csv` (71 B) and `query_result.parquet` (366 B) were written through the real `write_table` path.
- **Offline invariant held:** importing `rosbagger_gui.panels.query` leaks none of `rclpy`/`rosbag2_py`/`rosbags`/`pyarrow`/`duckdb`/`sqlglot`/`matplotlib` (the three core imports — `query`, `collect_table_schemas`, `write_table` — all live inside method bodies). Module-top `rosbagger_core` import count is 0.
- **No regression:** the full offline suite stays green — 460 passed, 2 skipped, 97.37% (unchanged baseline; the GUI is intentionally outside the coverage gate per Phase 13 D-12).

## Task Commits

Each task was committed atomically:

1. **Task 1: QueryPanel — SQL input + query() results DataTable + history/re-run** — `caaf5d2` (feat)
2. **Task 2: Schema/topic Tree click-to-insert + CSV/Parquet export buttons** — `7c2e26f` (feat)

## Files Modified

- `packages/rosbagger-gui/src/rosbagger_gui/panels/query.py` — filled the 14-02 stub: `QueryPanel(Vertical)` over `query()` + `collect_table_schemas` + `write_table`; SQL `Input`/Run, `results` `DataTable`, `schema-tree` `Tree` (click-to-insert), `history` `ListView` (re-run), and CSV/Parquet export `Button`s; lazy core imports, empty-state, `refresh_view()` on `on_mount`/`on_show`.

## Decisions Made

- Promoted the panel from the 14-02 `Static` stub to a `Vertical` container so it composes its own children (the plan's `QueryPanel(Widget)` shape). Offline/live gating is unaffected — it is data in the `_PANELS` registry, and query is offline (always enabled).
- Run is bound to BOTH Enter-on-`sql-input` (the SC3 `press("enter")` path) and a Run `Button`; both call the same `_run_query()`.
- History entries carry the raw SQL on a private `_sql` attribute; selecting one repopulates `sql-input` (re-run by pressing Run again) — the panel stores the string verbatim and builds no SQL.
- Export supplies only a path (`query_result.csv` / `.parquet` in CWD) with the matching suffix and lets `write_table` choose the serialization from the extension — no format/`COPY` string in the GUI. The buttons start disabled and enable once a result exists.
- Result cells are `str()`-rendered into the `DataTable` so a `timestamp[ns]` / LIST column displays without the ns→datetime crash class; `query()` already bounds the result (QURY-07), so `to_pylist()` is safe.

## Deviations from Plan

None — plan executed exactly as written.

Two in-task housekeeping adjustments (not deviations):
- A `ruff` I001 import-sort finding on this plan's own new import block was auto-fixed (`ruff check --fix` + `ruff format`) before the Task 1 commit — on this plan's own file, not pre-existing.
- Task 2's acceptance grep `grep -c "COPY\|FORMAT CSV\|FORMAT PARQUET" == 0` initially matched 3 lines of DOCSTRING PROSE ("DuckDB-COPY writer", "builds no COPY/format string") — no code built any such string. Reworded the prose ("LIST/STRUCT-safe writer", "serialization/format string") so the literal grep is clean; the panel still builds no SQL/format string (the actual intent). No functional change.

## Issues Encountered

- In the headless `run_test()` smoke harness, `pilot.click("#run-query")` did not fire on the default 80-column viewport because the Run button's region (x≈78–94) sits partly off-screen — a TEST-harness viewport concern, not a panel bug. The handler is correct: an explicit `Button.press()` and the Enter-on-input path both fill `results` (verified 2/3 rows). Plan 14-07 owns the formal SC3 test and can size the viewport or use the documented `press("enter")` path (Code Example 2). No code change to the panel.

## User Setup Required

None — the query panel is offline (no ROS) and needs no configuration.

## Next Phase Readiness

- All three always-on offline panels (inspect/query/tf) are now live faces over core. Plan 14-06 fills the live record/replay panels; Plan 14-07 adds the headless App tests that formally prove SC3 — including the query test (`SELECT … FROM <table>` against a fixture fills the `results` `DataTable` with `row_count >= 1` carrying real `query()` output), already demonstrated here via an ad-hoc `run_test()` (2/3 rows, schema tree 3 branches, click-to-insert, CSV+Parquet export written).
- No blockers. Offline-import invariant for the query panel module verified intact; full offline suite green (460 passed, 2 skipped, 97.37%).

## Self-Check: PASSED

The modified panel file exists on disk and imports cleanly (`import rosbagger_gui.panels.query` exits 0); both task commits (`caaf5d2`, `7c2e26f`) are in the git log; the headless `run_test()` proved real `query()` rows reaching the `results` `DataTable`, the schema Tree + click-to-insert, the teaching-error path, history/re-run, and CSV+Parquet export through the real `write_table` path; the offline-import invariant and the full offline suite are intact.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
