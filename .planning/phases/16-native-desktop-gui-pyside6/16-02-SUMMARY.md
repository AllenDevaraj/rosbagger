---
phase: 16-native-desktop-gui-pyside6
plan: 02
subsystem: rosbagger-desktop (native PySide6 desktop GUI — Query panel)
tags: [gui, pyside6, qt, query, offline, thin-frontend, pyarrow]
dependency_graph:
  requires:
    - rosbagger-core (backend.query.query, inspect.collect_table_schemas, output.export.write_table, errors.{UnknownTable,UnknownColumn,UnresolvedType}Error)
    - rosbagger-desktop MainWindow shell + editable panel registry (Plan 16-01)
    - tools.make_fixtures (write_ros2_sqlite_bag)
  provides:
    - QueryPanel offline QWidget — a thin face over query() + collect_table_schemas + write_table
    - Query nav row registered in MainWindow (offline, always-enabled) in inspect/query/tf order
    - headless SC2/SC3 query test driving a real query() over a fixture bag + the teaching-error path
  affects:
    - Plan 03 (record/replay live panels + five-panel completeness; the registry now holds three offline rows)
tech_stack:
  added: []
  patterns:
    - SQL string forwarded VERBATIM to query(sql, reader); zero SQL/format logic in the GUI
    - schema QTreeWidget leaf carries the verbatim column name as item data (click-to-insert, no SQL build)
    - Phase-7 teaching errors caught and rendered as str(e) to a status label (never a traceback)
    - pyarrow.Table -> QTableWidget via to_pylist() + QTableWidgetItem(str(value)) (Pattern 4, temporal-safe)
    - write_table(last_result, path) export; format chosen by extension; export disabled until a result
    - all rosbagger_core imports lazy inside method bodies (offline+Qt-free import invariant)
key_files:
  created:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py (register the Query offline row)
    - tests/test_desktop.py (add the SC2/SC3 query test; update Plan-01 panel-count assertions)
decisions:
  - Test derives the target table name from the panel's own schema tree (collect_table_schemas) rather than hardcoding a fixture topic — robust to fixture changes and self-validating
  - Tree leaf / history item carry their payload on Qt.UserRole (the Qt analog of the TUI node.data / item._sql); top-level table items carry no column data so a table click is a no-op
  - Plan-01 nav-count assertions (== 2) updated to == 3 for the new offline Query row (the registration changes the observable count)
metrics:
  duration: ~8min
  completed: 2026-05-25
  tasks: 2
  files: 3
---

# Phase 16 Plan 02: rosbagger-desktop Query panel Summary

Added the richest offline panel — Query — to the native PySide6 desktop cockpit: a thin Qt face that forwards a user SQL string VERBATIM to `rosbagger_core.backend.query.query`, renders the returned `pyarrow.Table` into a `QTableWidget`, offers a click-to-insert schema tree from `collect_table_schemas`, catches the Phase-7 teaching errors as status text, and exports the last result via `write_table` — registered as an always-enabled offline nav row, proven by a headless pytest-qt test running a real `query()` end-to-end. Zero SQL/format/analysis logic lives in the GUI; the offline import graph stays both ROS-free and Qt-free.

## What Shipped

- **panels/query_panel.py** — `QueryPanel(QWidget)` (D-11), a one-to-one Qt port of the TUI query panel:
  - **Query bar** — a `QLineEdit` (placeholder `"SELECT … FROM <table>"`) + a Run `QPushButton`; both the Run `clicked` and the line-edit `returnPressed` call `_run_query()`.
  - **`_run_query()`** reads the SQL + the window's shared reader, lazily imports `from rosbagger_core.backend.query import query` and the three teaching errors INSIDE the handler, calls `query(sql, reader)` VERBATIM, catches `UnknownTableError`/`UnknownColumnError`/`UnresolvedTypeError` to render `str(e)` on the status label (no traceback), and on success keeps `self._last_result`, fills the results table, appends history, enables export, and sets `"{num_rows} row(s) · {n} column(s)"`.
  - **Schema tree** — a `QTreeWidget` with one top-level item per `TableSchema.table_name` and a child leaf per `columns[*].name`; each leaf carries the verbatim column name on `Qt.UserRole`. Clicking a leaf inserts the bare column identifier into the SQL input at the cursor (the panel builds NO SQL); a top-level table click is a no-op.
  - **Results table** — a `QTableWidget` filled by the Pattern-4 mapping (`setColumnCount`/`setHorizontalHeaderLabels(column_names)`, a row per `to_pylist()` entry, `QTableWidgetItem(str(value))` per cell — temporal-safe).
  - **Export bar** — Export CSV / Export Parquet `QPushButton`s, both `setEnabled(False)` until a result; `_export(path)` lazily imports `write_table` and calls `write_table(last_result, path)` (format chosen by the `.csv`/`.parquet` extension), catching `(ValueError, OSError)` to render `str(e)`. Defaults `query_result.csv` / `query_result.parquet`.
  - **History** — a `QListWidget`; each successfully-run SQL is stored verbatim on `Qt.UserRole`, and selecting an entry repopulates the SQL input (re-run on Run).
  - **`refresh_view()`** (called from `showEvent` and after a bag opens) rebuilds the schema tree from `collect_table_schemas(reader)` (lazy import); with no reader it clears the tree and shows the empty-state status.
  - **Offline-import invariant** — every `rosbagger_core` import lives inside a method body; module top is PySide6 + stdlib + a `TYPE_CHECKING` pyarrow import only.
  - **Test accessors** — `sql_input`, `run_button`, `results_table`, `status_label`, `schema_tree`, `export_csv_button`, `export_parquet_button`, `history_list` properties.
- **main_window.py** — constructs `self.query_panel = QueryPanel(self)` and registers `("query", "Query", self.query_panel, False)` in the registry between Inspect and TF (mirroring the TUI `_PANELS` order); exposed via the `query_panel` attribute and `panels["query"]`. All three offline rows stay always-enabled.
- **tests/test_desktop.py** — `test_query_panel_runs_real_core` (SC2/SC3): opens a ROS 2 sqlite fixture, shows the Query panel, derives a real table name from the panel's own schema tree, runs `SELECT * FROM <table> LIMIT 1` via the Run button, and asserts `rowCount() > 0` + `columnCount() > 0` (real `query()` rows) and both export buttons enabled; a second leg drives an unknown table and asserts a non-empty teaching status with no exception. Updated the Plan-01 `test_app_has_offline_panels` / capability-gate nav-count assertions from 2 to 3 and added the `query` panel-accessor checks.

## Verification

- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py` — All checks passed. PASS
- `grep -rn "^from rosbagger_core\|^import rosbagger_core" .../query_panel.py` — no top-level core import. PASS
- `query_panel.py` contains `from rosbagger_core.backend.query import query`, `from rosbagger_core.output.export import write_table`, and references `UnknownTableError`. PASS
- `main_window.py` registers `QueryPanel` as an offline (`is_live=False`) row and exposes `query_panel` / `panels["query"]`. PASS
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py -x -q --no-cov` — 5 passed. PASS
- `PYTHONPATH="" uv run ruff check tests/test_desktop.py packages/rosbagger-desktop/src` + format check — clean. PASS
- Full suite: **473 passed, 3 skipped, 97.37% coverage** (≥80% gate held; +1 test over Plan 01). The Qt-free + ROS-free offline guards stayed green — no top-level Qt/core leak introduced. PASS

## Success Criteria

- **SC2 (query slice)** — the Query panel reaches parity with the TUI query panel: run/render/schema-tree/history/export, all over the real core APIs. MET.
- **SC3** — the Query panel drives real `query()` against a fixture bag with rows landing in the results table (proven by `test_query_panel_runs_real_core`). MET (the inspect/query/tf trio now all drive real `rosbagger_core` output).
- **SC5** — the headless query test passes under `QT_QPA_PLATFORM=offscreen` (no real window appears). MET.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan-01 nav-count assertions hardcoded `== 2` and would fail once Query registers**
- **Found during:** Task 2
- **Issue:** `test_app_has_offline_panels` and `test_capability_gate_keeps_offline_panels_enabled` asserted `window._nav.count() == 2`. Registering the Query panel (the explicit purpose of this plan) makes the observable count 3, so those two Plan-01 tests would break — a regression in the same file the plan instructs Task 2 to extend.
- **Fix:** Updated both assertions to `== 3`, added the `panels["query"]` / `window.query_panel` accessor checks to `test_app_has_offline_panels`, and refreshed the two docstrings to read "inspect/query/tf". These were the only edits to existing tests; no Plan-01 behavior was changed.
- **Files modified:** tests/test_desktop.py
- **Commit:** 1a1598f

### Note on the acceptance command + coverage gate

The Task-2 acceptance command `pytest tests/test_desktop.py -x -q` runs under the repo `addopts` coverage gate (`--cov=rosbagger_core --cov=bagq --cov-fail-under=80`). Run against a SINGLE test file that exercises only a slice of core, total coverage is ~57% and the gate alone forces a non-zero exit — independent of test correctness (the same Plan-01 situation; the desktop GUI is intentionally outside the cov gate). The tests themselves pass cleanly (`--no-cov` → 5 passed), and the ≥80% gate holds on the FULL suite (97.37%, 473 passed). Both evidences are recorded above.

## TDD Gate Compliance

Task 1 was marked `tdd="true"` but its `<files>` set is source-only (`query_panel.py`, `main_window.py`) — the behavioral proof test lives in Task 2's `tests/test_desktop.py`, exactly as in Plan 16-01. The RED/GREEN gate therefore manifests as: source committed in `e8d8c5d` (feat, gated by the ruff + no-top-level-core-import grep + required-reference acceptance criteria), behavioral proof committed in `1a1598f` (test). No standalone failing-then-passing RED commit was produced because the plan assigns no test file to the TDD-marked task; the Task-1 behavior contract is fully covered by the green Task-2 test (`rowCount > 0` after a real `query()`, plus the UnknownTableError teaching path).

## Known Stubs

None. The Query panel renders real `query()` output, builds its schema tree from real `collect_table_schemas`, and exports via the real `write_table`. The record/replay rows remain intentionally deferred to Plan 03 (the registry is editable and the capability gate is in place for them).

## Self-Check: PASSED

The created file `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py` is present on disk; both task commits (`e8d8c5d`, `1a1598f`) are present in git history.
