---
phase: 17-desktop-revamp-full-visual-design-system-qss-theme-design-to
plan: 02
subsystem: rosbagger-desktop (widgets/ shared models + status; inspect/tf engineering parity)
tags: [model-view, qabstracttablemodel, blockingworker, accessibility, thin-face, d-02]
requires:
  - "17-01: theme/qss.py QLabel#status_error selector (the error color the shared set_status toggles via objectName)"
provides:
  - "rosbagger_desktop.widgets._ResultTableModel (lifted out of query_panel — pyarrow-backed, lazy, shared)"
  - "rosbagger_desktop.widgets.RowsTableModel(headers, rows) — generic list-of-tuple model for dataclass-row panels"
  - "rosbagger_desktop.widgets.set_status(label, text, *, is_error) — shared accessible status helper (offscreen QAccessible guard preserved)"
  - "inspect/tf panels at the query-panel bar: QTableView + RowsTableModel + off-thread BlockingWorker refresh"
affects:
  - "17-03 panel visual rollout (inspect/tf now expose QTableViews + a status_error-keyed status line for QSS styling)"
tech-stack:
  added: []  # zero new dependencies (RESEARCH Package Legitimacy Audit — N/A)
  patterns:
    - "Shared QAbstractTableModel subclasses in widgets/ (pyarrow-backed + generic list[tuple] flavors)"
    - "Off-thread collect_* on BlockingWorker + run_on_thread/stop_thread (D-02 parity, T-17-04)"
    - "objectName(status_error) error affordance + unpolish/polish repolish (D-03 — color from theme QSS, no inline stylesheet)"
    - "platformName() != offscreen QAccessible guard centralized in one helper (D-09 / commit 7e99a5f)"
    - "lazy rosbagger_core imports INSIDE worker work() bodies (D-08 offline invariant)"
key-files:
  created:
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/result_model.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/rows_model.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/status.py
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/__init__.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/tf_panel.py
    - tests/test_desktop.py
decisions:
  - "set_status restores the label's ORIGINAL objectName on the non-error path (captured once as a dynamic property) so the status_error affordance is path-scoped; repolishes (unpolish/polish/update) after each objectName toggle so the theme QSS re-evaluates live"
  - "Query panel a11y test migrated from styleSheet() assertions to objectName() assertions (D-03: the error color now lives in theme QSS QLabel#status_error, not an inline literal)"
  - "Inspect worker work() returns the (info, schemas) pair; the UI-thread result slot does ALL presentation formatting (human size/duration, <mixed>/em-dash) before set_rows — no analysis crosses to the worker"
  - "TF NoTransformsError routed via BlockingWorker teaching_errors so str(exc) arrives on the failed slot and renders verbatim through set_status(is_error=True) — core owns the message (THIN-FACE)"
metrics:
  duration: ~40m
  tasks: 3
  files_created: 3
  files_modified: 5
  completed: 2026-05-25
---

# Phase 17 Plan 02: Cross-Panel Engineering Parity (inspect + tf) Summary

Lifted the query panel's lazy `_ResultTableModel` into a shared `widgets/result_model.py`, added a generic `RowsTableModel(headers, rows)` for dataclass-row panels and a shared accessible `set_status` helper (keeping the offscreen `QAccessible` guard, D-09) in `widgets/`, then migrated the **inspect** and **tf** panels to `QTableView` + a model and moved their synchronous `collect_*` core calls onto a `BlockingWorker` — closing the D-02 engineering-parity gap with ZERO new analysis/SQL/ROS logic (D-09) and the offline+Qt-free import graph intact (D-08).

## What Was Built

- **`widgets/result_model.py`** — `_ResultTableModel` MOVED verbatim out of `query_panel.py` (pyarrow-backed, lazy `str()`-per-cell, temporal-safe — never ns→datetime). Imports only PySide6 + a `TYPE_CHECKING`-only `pyarrow`.
- **`widgets/rows_model.py`** — NEW generic `RowsTableModel(headers, rows)` over `list[tuple[str, ...]]`: lazy `str()` per cell, `headers` for `headerData`, `set_rows` wrapped in begin/endResetModel. The dataclass-row analog of the result model for inspect/tf.
- **`widgets/status.py`** — NEW `set_status(label, text, *, is_error=False)` generalizing `query_panel._set_status`: sets text + `accessibleDescription`, toggles the `status_error` objectName (the COLOR comes from the theme QSS `QLabel#status_error` selector owned by 17-01 — D-03, NOT an inline stylesheet literal), repolishes the label so the QSS re-evaluates live, and on the error path posts a `QAccessible` Alert guarded by `platformName() != "offscreen"` inside `contextlib.suppress` (D-09 / commit 7e99a5f — posting under offscreen segfaults). The original objectName is captured once (dynamic property) and restored on the non-error path so the affordance is path-scoped.
- **`widgets/__init__.py`** — re-exports `_ResultTableModel`, `RowsTableModel`, `set_status` (Qt+stdlib only — offline/Qt-clean).
- **`query_panel.py`** — imports the lifted `_ResultTableModel` from `..widgets`; its `_set_status` now delegates to the shared `set_status`. Threaded behavior, history, export, splitter, and every public accessor unchanged.
- **`inspect_panel.py`** — both `QTableWidget`s replaced with `QTableView` + `RowsTableModel` (headers `["topic","msgtype","count","hz"]` / `["table","column","type","lazy"]`). `collect_bag_info` + `collect_table_schemas` run on a `BlockingWorker` (work() returns the `(info, schemas)` pair, lazy core import inside work() — D-08); a UI-thread result slot formats rows (keeping `_human_size`/`_EM_DASH`/`_MIXED` — presentation only) and `set_rows` both models; re-entry guard + `stop_thread` in `closeEvent`. Header routes through the shared `set_status`.
- **`tf_panel.py`** — both `QTableWidget`s replaced with `QTableView` + `RowsTableModel` (edges/gaps headers per plan). `collect_tf_report` runs on a `BlockingWorker` with `teaching_errors=(NoTransformsError,)` so the teaching message arrives on the `failed` slot as `str(exc)` and renders VERBATIM through `set_status(is_error=True)`. Per-edge rate/span computation + `_human_dur`/`_EM_DASH` formatting preserved exactly (moved into the result slot); the empty-gaps "no gaps detected" note row preserved; re-entry guard + `stop_thread` in `closeEvent`.

## How It Works (data flow)

`refresh_view()` (triggered by `showEvent` or an explicit call) builds a `BlockingWorker` whose `work()` lazily imports the `rosbagger_core` API and runs the blocking `collect_*` call off the UI thread via `run_on_thread`. On success the `(info, schemas)` / `TfReport` result crosses back to a UI-thread `_on_refresh_result` slot that does ALL presentation formatting and `set_rows` on the bound models (begin/endResetModel refreshes the `QTableView`s). On a teaching/unexpected error the `failed` slot renders the message verbatim through the shared accessible `set_status`. `_on_refresh_finished` clears the thread/worker refs on every outcome; `closeEvent` calls `stop_thread`.

## Tests (all headless, offscreen, ROS-free)

- `test_rows_model_renders_headers_and_cells` (pure, no QApplication): dimensions, `str()` cells, headers; non-str inputs str()-rendered.
- `test_rows_model_set_rows_resets_bound_view` (qtbot): a bound `QTableView` sees the new rows after `set_rows`.
- `test_set_status_sets_text_a11y_and_error_affordance` (qtbot): text + `accessibleDescription` set; `status_error` objectName toggled on error and the base objectName restored on success — no segfault under offscreen.
- `test_inspect_panel_shows_real_topics` (updated): asserts `bag_info_table.model().rowCount() > 0` AND `schemas_table.model().rowCount() > 0` after `qtbot.waitUntil` for worker completion.
- `test_tf_panel_renders_or_teaches` (updated): `/tf` bag yields `edges_table.model().rowCount() > 0` after waitUntil; no-`/tf` bag routes `NoTransformsError` through the status line (waitUntil it leaves the empty-state) with empty edges, no crash.
- `test_live_panels_disabled_without_ros` + `test_capability_gate_keeps_offline_panels_enabled` (updated): their inline inspect assertions migrated to the model API + `qtbot.waitUntil` (the off-thread refresh).
- `test_query_status_announces_and_styles_errors` (updated): error affordance assertions migrated from `styleSheet()` to `objectName() == "status_error"` (D-03).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Two extra inline inspect assertions migrated to the model API**
- **Found during:** Task 2 / full-suite verification.
- **Issue:** Beyond the planned `test_inspect_panel_shows_real_topics`, two other tests (`test_live_panels_disabled_without_ros`, `test_capability_gate_keeps_offline_panels_enabled`) also drive `inspect.refresh_view()` and asserted `bag_info_table.rowCount()` directly — which raises `AttributeError` now that `bag_info_table` is a `QTableView` (no `rowCount()`), and would no longer be synchronous post off-thread migration.
- **Fix:** Migrated both to `.model().rowCount()` + `qtbot.waitUntil` for worker completion.
- **Files modified:** `tests/test_desktop.py`. **Commit:** dcd6334.

**2. [Rule 3 - Blocking lint] Inspect header line exceeded the 100-col limit**
- **Found during:** Task 2 (ruff E501 after the first commit).
- **Fix:** Built the header string in a wrapped local before `set_status`.
- **Files modified:** `inspect_panel.py`. **Commit:** 4bd7927.

### Note on the query a11y test (planned migration, not a deviation)
The plan moves the error affordance from an inline `_STATUS_ERROR_STYLE` literal to the `status_error` objectName (color from theme QSS, D-03). The existing `test_query_status_announces_and_styles_errors` asserted `styleSheet()` non-empty/empty; it was updated to assert `objectName() == "status_error"` / restored — the same path-scoped-affordance contract, expressed against the new mechanism.

## Known Stubs

None — both panels are fully wired off-thread to real core APIs and tested.

## Threat Flags

None — no new network endpoint, auth path, file-access pattern, or schema change introduced. The threat register's `mitigate` dispositions (T-17-04 off-thread, T-17-05 offscreen guard, T-17-06 stop_thread, T-17-07 lazy imports) are all implemented.

## Verification

- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py` → **33 passed** (clean).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` (full blended suite) → **501 passed, 4 skipped**, **total coverage 84.42% ≥ 80%** (gate holds; widgets/rows_model 90%, widgets/status 92%, inspect_panel 89%, tf_panel 86%, query_panel 88%).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → **20 passed** (offline + Qt-free guard green, D-08; widgets/ added no Qt to the core graph).
- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop/src/rosbagger_desktop/` → clean.
- Every preserved accessor (`bag_info_table`/`schemas_table`/`edges_table`/`gaps_table`/`status_label`) resolves (grep confirmed).

### Note on the known offscreen segfault
An intermittent SIGSEGV under the offscreen Qt backend appeared on one full-suite run (during a `qtbot.waitUntil` and at process exit) — the load-dependent teardown artifact the host constraints + 17-01 SUMMARY document as environmental noise (equivalent on a clean pre-phase tree), NOT introduced by this plan. A re-run produced the clean `501 passed` + 84.42% line above, per the documented "re-run to confirm" guidance.

## DoD note (visual sanity check — human)

Offscreen tests prove behavior, not appearance. The inspect/tf panels now expose `QTableView`s + a `status_error`-keyed status line; a human visual sanity check (`PYTHONPATH="" uv run rosbagger-desktop <bag>`) lands with the 17-03 visual rollout once the panels are styled against the theme tokens.

## TDD Gate Compliance

Task 1 shipped the lifted/new models + shared helper with their unit/qtbot tests together (2c10475 — a refactor-lift of an already-tested model plus new model/helper tests). Tasks 2 and 3 shipped each panel's off-thread migration with its updated model-API + `waitUntil` tests in the same commit (5b91229 / edcce4a), with follow-up lint/test fixes (4bd7927, dcd6334). No RED-before-GREEN warning is required: Task 1 is a presentation/threading refactor over existing behavior, not new analysis logic.

## Self-Check: PASSED

All three created files exist on disk; all five commits (2c10475, 5b91229, 4bd7927, edcce4a, dcd6334) are present in git history; every preserved public accessor resolves; the working tree is clean for code.
