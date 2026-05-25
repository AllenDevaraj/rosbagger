---
phase: quick-260525-kj0
plan: 01
subsystem: rosbagger-desktop / query panel
tags: [pyside6, layout, accessibility, a11y, qsplitter, thin-face]
requires: [260525-is6 threaded query behavior]
provides:
  - "QSplitter-wrapped resizable query regions (schema tree / results view / history)"
  - "Accessible, error-styled query status live region (verbatim teaching text preserved)"
affects: [packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py, tests/test_desktop.py]
tech-stack:
  added: []
  patterns: ["QSplitter(Qt.Vertical) for user-resizable regions", "objectName + accessibleName + QAccessible Alert for a status live region", "path-scoped status stylesheet (error set, cleared on success)", "offscreen-platform guard around QAccessibleEvent"]
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
    - tests/test_desktop.py
decisions:
  - "Skip the QAccessible Alert announcement when QGuiApplication.platformName()=='offscreen' — posting a QAccessibleEvent into a running event loop under offscreen Qt segfaults at the C++ level (uncatchable by try/except); the bridge is absent headlessly anyway, so this is a true no-op that preserves the announcement on a real desktop."
  - "History QLabel + QListWidget wrapped in a margin-free QWidget container so the section title travels with its list inside the splitter as one region."
  - "Route ALL status sets through a single _set_status(text, *, is_error) helper so error styling is consistently applied on error paths and cleared on every neutral/success path — text content unchanged (THIN-FACE)."
metrics:
  duration: ~12min
  completed: 2026-05-25
---

# Phase quick-260525-kj0 Plan 01: Query Panel Layout + A11y Summary

Wrapped the rosbagger-desktop Query panel's three resizable regions in a user-draggable vertical `QSplitter` (P2-layout) and turned the status `QLabel` into an accessibly-named, error-styled live region that announces teaching errors via `QAccessible` (P2-a11y) — all presentation-only, with the verbatim core teaching text and the 260525-is6 threaded-query behavior unchanged.

## What changed

### Task 1 — QSplitter layout (P2-layout) — `da5a94f`
- Added `QSplitter` to the `QtWidgets` import.
- The schema tree, results view, and a new margin-free history container (the `QLabel("History")` + `QListWidget`) are now children of a `QSplitter(Qt.Vertical)` with initial `setSizes([1, 3, 1])` (results widest) and `setChildrenCollapsible(False)`.
- The outer `QVBoxLayout` keeps `_status`, the query bar, and the export bar as fixed-height siblings; the splitter is added with stretch `1` to take the free vertical space.
- All public accessors (`schema_tree`, `results_table`, `history_list`, etc.) return the same widgets.

### Task 2 — Accessible, error-styled status live region (P2-a11y) — `e6d0f73`
- Added `from PySide6.QtGui import QAccessible, QAccessibleEvent` (top-level Qt is this package's own dep — offline invariant unaffected).
- Set `objectName="query_status"`, `accessibleName="Query status"`, and an initial `accessibleDescription` on `self._status`.
- Added module-level `_STATUS_NEUTRAL_STYLE` / `_STATUS_ERROR_STYLE` constants.
- Introduced `_set_status(self, text, *, is_error=False)`: sets text, applies/clears the error stylesheet, mirrors text into `accessibleDescription`, and posts a `QAccessible` Alert on the error path.
- Routed every status set through `_set_status` (refresh empty-state, run guards, "Running…", success "row(s)", teaching failure, export). Text strings are byte-for-byte unchanged; success clears the error style; the export-error line passes `is_error=True`.

### Task 3 — Headless tests (TDD) — `9d272cc`
- `test_query_panel_regions_live_in_splitter`: finds the panel's `QSplitter` and asserts the schema tree, results view, and history list are descendants (robust to the history-container wrapper via `isAncestorOf`).
- `test_query_status_announces_and_styles_errors`: asserts a non-empty accessible name; drives the threaded teaching-error path and asserts the verbatim, no-"row(s)" status + a non-empty error stylesheet without crashing; then a successful query clears the stylesheet (path-scoped styling).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] QAccessible Alert segfaulted under offscreen Qt** — `7e99a5f`
- **Found during:** Task 3 (running the full `tests/test_desktop.py`).
- **Issue:** Posting `QAccessibleEvent(self._status, QAccessible.Alert)` from `_on_query_failed` while inside the threaded teaching-error `qtbot.waitUntil` event loop crashed at the C++ level (`Fatal Python error: Bus error` at the pre-existing `test_query_panel_runs_real_core` teaching leg, line 271). This is a segfault, so the surrounding `try/except` could not catch it. Confirmed introduced by this work: reverting `query_panel.py` to the pre-kj0 version made the test pass in isolation; restoring it reproduced the crash. The plan's `<action>` anticipated this fragility (T-kj0-03: "Guard the announcement so it is a no-op-safe call under the offscreen platform").
- **Fix:** Guard the announcement with `QGuiApplication.platformName() != "offscreen"` (added the `QGuiApplication` import). The offscreen backend has no accessibility bridge, so this is a true no-op headlessly while preserving the announcement on a real desktop. Also converted the `try/except/pass` to `contextlib.suppress(Exception)` and wrapped the `__init__` docstring (ruff `SIM105` + line-length).
- **Files modified:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py`
- **Commit:** `7e99a5f`

## Verification

- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **487 passed, 4 skipped, 97.37% coverage** (clean re-run; the intermittent offscreen-Qt teardown `Bus/Segmentation fault` artifact prints under coverage instrumentation at teardown — confirmed not a failure by the clean re-run and by an `addopts=""` run that always passed 487/4).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py tests/test_offline_guard.py` → 39 passed (offline-import invariant holds).
- `PYTHONPATH="" uv run ruff check <query_panel.py> <test_desktop.py>` → All checks passed.
- Manual grep: no top-level `from rosbagger_core` / `import rosbagger_core` in `query_panel.py` (invariant holds).

## Invariants preserved

- THIN-FACE: no new error/message text; teaching errors still render `str(exc)` verbatim; status text content unchanged.
- OFFLINE-IMPORT (D-08): no new top-level core import; `tests/test_offline_guard.py` passes.
- 260525-is6 threaded-query behavior (`BlockingWorker`, `waitUntil`, `_query_thread`/`_query_worker`/`_pending_sql`) and all public accessors unchanged.
- ISOLATION: changes confined to `packages/rosbagger-desktop` + `tests/`.

## Self-Check: PASSED

- FOUND: `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py`
- FOUND: `tests/test_desktop.py`
- FOUND commits: `da5a94f`, `e6d0f73`, `7e99a5f`, `9d272cc`
