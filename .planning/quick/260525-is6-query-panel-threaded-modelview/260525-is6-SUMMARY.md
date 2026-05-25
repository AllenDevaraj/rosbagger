---
phase: quick-260525-is6
plan: 01
subsystem: rosbagger-desktop (Query panel)
tags: [pyside6, threading, model-view, query, offline-invariant]
requires:
  - rosbagger_desktop.workers (BlockingWorker / run_on_thread / stop_thread)
  - rosbagger_core.backend.query.query (forwarded verbatim, lazy-imported)
provides:
  - "_ResultTableModel(QAbstractTableModel): lazy pyarrow.Table → QTableView rendering"
  - "Threaded query() execution off the UI thread via BlockingWorker"
affects:
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
  - tests/test_desktop.py
tech-stack:
  added: []
  patterns:
    - "QAbstractTableModel + QTableView (allocation-light, lazy per-cell str())"
    - "BlockingWorker drive pattern mirrored from replay_panel (Pattern 3)"
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
    - tests/test_desktop.py
decisions:
  - "Keep BOTH thread AND worker refs on the panel — discarding the worker let the GC collect it before its queued run slot fired (a fast query never started); replay masked this with a long-blocking run()."
metrics:
  duration: ~20min
  completed: 2026-05-25
---

# Phase quick-260525-is6 Plan 01: Query Panel Threaded Model/View Summary

Routed the Query panel's `query(sql, reader)` call off the UI thread onto the existing
`BlockingWorker` and replaced the per-cell `QTableWidget` with a lazy
`QAbstractTableModel` + `QTableView` — keeping the window responsive and result rendering
allocation-light while preserving the thin-face, offline-import, and isolation invariants.

## What changed

### Task 1 — Model/View rendering (P2) · commit `9b4e142`
- Added `_ResultTableModel(QAbstractTableModel)`: `rowCount`/`columnCount` off the
  `pyarrow.Table` (`num_rows` / `len(column_names)`, 0 when None), `data` returns `str()`
  of the cell for `DisplayRole` only via lazy `column(col)[row].as_py()` (no up-front
  `to_pylist()`), `headerData` returns the column name, and `set_table` swaps inside
  `beginResetModel`/`endResetModel`. Out-of-range indices return `None`.
- Swapped the `QTableWidget`/`QTableWidgetItem` imports for `QTableView`; `__init__` builds
  `self._result_model` + `self._results_view` wired via `setModel`, with the read-only +
  stretch behaviour preserved. `_fill_results` now just calls `set_table`.
- `results_table` property returns the `QTableView`; module top stays PySide6-only.

### Task 2 — Threaded query() (P1) · commit `f92ad95`
- `_run_query` builds a `work` closure (`return query(sql, reader)`) and runs it on a
  `BlockingWorker(teaching_errors=(UnknownTableError, UnknownColumnError, UnresolvedTypeError),
  label="Query failed")` via `run_on_thread`. Run is disabled + "Running…" shown before
  start; a re-entry guard refuses a second Run while one is in flight (T-is6-02).
- UI-thread slots: `_on_query_result` (set `_last_result`, populate model, append history,
  enable export, "N row(s) · M column(s)"), `_on_query_failed` (status = message verbatim,
  T-is6-01), `_on_query_finished` (null thread+worker refs, re-enable Run).
- `closeEvent` calls `stop_thread(self._query_thread)` (T-is6-03).
- Module top still imports only PySide6 + `..workers` (offline invariant held).

### Task 3 — Headless tests + GC fix · commit `da65d96`
- `test_query_panel_runs_real_core` now `waitUntil`s the model populates (threaded result),
  asserts the view is `QAbstractTableModel`-backed with rows/cols, the teaching error lands
  as status text with no "row(s)", and the worker clears `_query_thread` (non-blocking).
- The two export tests `waitUntil` the model populates before exercising export.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Worker garbage-collected before its `run` slot fired**
- **Found during:** Task 3 (the new threaded test timed out; the panel status stuck at
  "Running…" and no result/failed/finished slot ever ran).
- **Issue:** `_run_query` discarded the `BlockingWorker` returned by `run_on_thread`
  (`self._query_thread, _ = ...`). The worker is `moveToThread`'d but NOT Qt-reparented, so
  with no Python reference the GC collected it before its queued `started → run` slot
  executed. A *fast* query never started; the replay panel masked this because its
  `Replayer.run()` blocks long enough that GC timing never bit.
- **Fix:** Keep `self._query_worker = run_on_thread(...)[1]` (added the ref in `__init__`,
  cleared in `_on_query_finished` alongside the thread ref). Verified in isolation: status
  goes from "Running…" → "1 row(s) · 10 column(s)" and the thread ref clears.
- **Files modified:** packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
- **Commit:** da65d96

## Threat model

All three mitigations from the plan's register are implemented: T-is6-01 (teaching text via
the worker's `failed` signal, never a traceback), T-is6-02 (re-entry guard), T-is6-03
(`closeEvent` → `stop_thread`; finished slot nulls the ref before deleteLater). No new
dependencies (T-is6-SC accept holds).

## Verification

- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **485 passed, 4 skipped** (full
  headless suite; coverage gate met).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_offline_guard.py -q` →
  20 passed (core import graph stays ROS-free AND Qt-free; no `rosbagger_core` import at the
  `query_panel.py` module top — confirmed via grep).
- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop tests/test_desktop.py` → clean.
- Changes confined to `packages/rosbagger-desktop` + `tests/test_desktop.py`; no
  core/bagq/record/replay/gui source touched.

### Note on the at-exit dump
The full-suite run emits an intermittent PySide6/shiboken interpreter-shutdown traceback
AFTER the `485 passed, 4 skipped` summary line. Confirmed pre-existing: the baseline commit
(986745c, before these changes) shows the identical `485 passed, 4 skipped` summary and the
same intermittent at-exit dump. It is a Qt teardown artifact at process exit, not a test
failure, and is out of scope for this task.

## Self-Check: PASSED
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py` — FOUND
- `tests/test_desktop.py` — FOUND
- Commit 9b4e142 — FOUND
- Commit f92ad95 — FOUND
- Commit da65d96 — FOUND
