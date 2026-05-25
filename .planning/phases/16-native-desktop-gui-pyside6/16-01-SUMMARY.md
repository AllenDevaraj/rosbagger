---
phase: 16-native-desktop-gui-pyside6
plan: 01
subsystem: rosbagger-desktop (native PySide6 desktop GUI)
tags: [gui, pyside6, qt, packaging, offline-guard, thin-frontend]
dependency_graph:
  requires:
    - rosbagger-core (inspect.collect_bag_info / collect_table_schemas, tf.collect_tf_report, errors.NoTransformsError, reader.RosbagsReader)
    - rosbagger-record (sibling pin only — lazy live use deferred to Plan 03)
    - rosbagger-replay (sibling pin only — lazy live use deferred to Plan 03)
    - tools.make_fixtures (write_ros2_sqlite_bag, write_tf_bag)
  provides:
    - rosbagger-desktop workspace package (v0.2.0) + `rosbagger-desktop` console script
    - MainWindow QMainWindow shell (nav + QStackedWidget, App-owned reader, capability gate, editable panel registry)
    - InspectPanel / TfPanel offline QWidget panels
    - Qt-free offline-import guards (two fresh-subprocess assertions)
  affects:
    - Plan 02 (query panel appends to the panel registry)
    - Plan 03 (record/replay live panels + five-panel completeness; uses the in-place capability gate)
tech_stack:
  added:
    - PySide6 6.11.1 (Qt6 GUI toolkit — declared ONLY in rosbagger-desktop deps)
    - shiboken6 6.11.1 (PySide6 binding runtime — pulled transitively)
    - pytest-qt 4.5.0 (dev group — headless qtbot GUI tests)
  patterns:
    - argparse front door; QApplication imported inside main() (Qt-free --help)
    - lazy ROS/core imports inside method bodies (offline-import invariant)
    - App-owned single shared RosbagsReader handed to panels
    - QTableWidgetItem(str(value)) temporal-safe rendering
    - headless pytest-qt under QT_QPA_PLATFORM=offscreen
key_files:
  created:
    - packages/rosbagger-desktop/pyproject.toml
    - packages/rosbagger-desktop/src/rosbagger_desktop/__init__.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/cli.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/capabilities.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/__init__.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/tf_panel.py
    - tests/test_desktop.py
  modified:
    - pyproject.toml (dev group += PySide6/pytest-qt; ruff src; pytest qt_api)
    - uv.lock (re-locked additively)
    - tests/test_offline_guard.py (two Qt-free guards)
decisions:
  - PySide6 pinned >=6.10,<6.12 (resolved to 6.11.1); declared ONLY in rosbagger-desktop deps + the dev group for CI test execution
  - shiboken6 confirmed as the PySide6 binding-runtime module name (A2 resolved) — added to the Qt-free guard blocklist alongside PySide6
  - main_window calls capabilities.ros_available() via the module (not a bound name) so the capability gate input is monkeypatchable in tests
  - panel registry is an editable list[(id,label,widget,is_live)] + a panels dict accessor; Plans 02/03 append query/record/replay rows
  - no [tool.uv.sources] entry needed for rosbagger-desktop (A3 confirmed — members glob auto-discovers it; deps are already-sourced siblings + PyPI PySide6)
metrics:
  duration: ~12min
  completed: 2026-05-25
  tasks: 3
  files: 12
---

# Phase 16 Plan 01: rosbagger-desktop foundation (offline shell + Inspect/TF) Summary

Stood up the isolated `rosbagger-desktop` PySide6 workspace package and shipped a launchable native `QMainWindow` cockpit with working offline Inspect and TF panels, the rclpy capability gate, two Qt-free offline-import guards, headless pytest-qt SC1/SC3 proof tests, and a re-locked `uv.lock` — a thin presentation port of the Textual TUI that calls `rosbagger_core` APIs verbatim and contains zero analysis/bag/SQL/ROS logic.

## What Shipped

- **New isolated package** `packages/rosbagger-desktop` (v0.2.0): PySide6-only Qt dep, sibling pins by spec, `rosbagger-desktop = "rosbagger_desktop.cli:main"` console script, hatchling backend. PySide6 declared ONLY here (D-01). Top level Qt-free + ROS-free.
- **cli.py** — argparse front door; `QApplication` + `MainWindow` imported inside `main()` so `rosbagger-desktop --help` exits 0 building no Qt (D-16, Pitfall 6).
- **capabilities.py** — `ros_available()` rclpy probe inside the function body (D-09).
- **main_window.py** — `QMainWindow` shell: `QListWidget` nav + `QStackedWidget`, App-owned single `RosbagsReader` (lazy `_open_reader`, `QMessageBox` on failure — WR-05), File menu (Open File / Open Directory via `QFileDialog`), editable panel registry + `panels` dict accessor, capability-gate logic in place for Plans 02/03. The ROS-2-Humble typestore helper is carried over (Pitfall 5).
- **panels/inspect_panel.py** — `InspectPanel(QWidget)` rendering `collect_bag_info` (topic/msgtype/count/hz) + `collect_table_schemas` (table/column/type/lazy), lazy-imported in `refresh_view` (D-10).
- **panels/tf_panel.py** — `TfPanel(QWidget)` rendering `collect_tf_report` edges + gaps with the `NoTransformsError` teaching path, lazy-imported in `refresh_view` (D-12).
- **tests/test_offline_guard.py** — two new fresh-subprocess Qt-free guards (D-04): `import rosbagger_core`/`bagq` pulls no PySide6/shiboken6, and `import rosbagger_desktop.cli` pulls no Qt nor ROS.
- **tests/test_desktop.py** — headless pytest-qt proof under `QT_QPA_PLATFORM=offscreen`: offline panels present+enabled (SC1), inspect renders real `collect_bag_info` rows (SC3), tf populates edges on a `/tf` bag and shows the teaching text on a no-`/tf` bag, capability gate exercised via monkeypatch (proven both True and False).
- **root pyproject.toml** — dev group `+= PySide6`, `pytest-qt`; ruff `src += packages/rosbagger-desktop/src`; pytest `qt_api = "pyside6"`. Coverage gate unchanged (rosbagger_desktop exempt — thin face).
- **uv.lock** — re-locked additively (PySide6 6.11.1, pyside6-essentials/addons, shiboken6 6.11.1, pytest-qt 4.5.0, rosbagger-desktop member).

## Verification

- `PYTHONPATH="" uv sync` re-locks; `uv.lock` lists the new member + PySide6 + pytest-qt. PASS
- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop/src` (+ test files) exits 0; `ruff format --check` clean. PASS
- `rosbagger-desktop --help` raises `SystemExit(0)` with no PySide6 in `sys.modules` (help-clean OK). PASS
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py tests/test_offline_guard.py` — 24 passed. PASS
- Full suite: **472 passed, 3 skipped, 97.37% coverage** (>=80% gate held). PASS
- PySide6 appears in NO `packages/*/pyproject.toml` except rosbagger-desktop's. PASS

## Success Criteria

- **SC1** — `rosbagger-desktop [BAG]` launches a native `QMainWindow` via the console script; `--help` exits 0 Qt-free. MET.
- **SC3 (partial)** — Inspect drives real `collect_bag_info`/`collect_table_schemas`; TF drives real `collect_tf_report` (+ NoTransformsError teaching). Query panel = Plan 02. MET.
- **SC4** — `import rosbagger_core`/`bagq` stays Qt-free AND ROS-free; the two new Qt-free guards pass. MET.
- **SC5** — headless pytest-qt tests pass under `QT_QPA_PLATFORM=offscreen`. MET.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] capability-gate test was inert with a bound-name import**
- **Found during:** Task 3 (writing the capability-gate test)
- **Issue:** `main_window.py` imported `from .capabilities import ros_available` and called the bound name, so monkeypatching `rosbagger_desktop.capabilities.ros_available` did not affect the window. The test passed only incidentally because `rclpy` is absent in the `PYTHONPATH=""` uv venv — the gate's input was the ambient venv, not the patch, making the test non-deterministic and not actually exercising the gate.
- **Fix:** Changed `main_window.py` to `from . import capabilities` and call `capabilities.ros_available()` via the module (the documented analog of the TUI's `_detect_ros` monkeypatch). Strengthened the test to prove the patch wiring both ways (force True -> `ros_available is True`, then force False -> gate path).
- **Files modified:** packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py, tests/test_desktop.py
- **Commit:** ef360b3

### Resolved Assumptions

- **A2 (shiboken6 module name):** Confirmed `shiboken6` IS the PySide6 binding-runtime module (also `shibokensupport`); both `PySide6` and `shiboken6` are in the Qt-free guard blocklist.
- **A3 (no uv.sources entry):** Confirmed — `uv sync` resolved the new member with no `[tool.uv.sources]` entry (members glob + already-sourced siblings).
- **A1 (3.10 wheel for the PySide6 line):** PySide6 6.11.1 installed cleanly on the repo's Python 3.10 floor.

## TDD Gate Compliance

Task 2 was marked `tdd="true"`, but its `<files>` set contains only source modules — the behavioral proof tests live in Task 3's `tests/test_desktop.py` (the plan's own structure splits implementation and test files across tasks). The RED/GREEN commit gate therefore manifests as: source committed in `2ee0f21` (feat), test proof committed in `ef360b3` (test). The Task 2 inline verify (ruff + help-clean) gated the source before commit; the Task 3 headless pytest-qt suite is the behavioral proof. No standalone failing-then-passing RED commit was produced because the plan did not assign a test file to the TDD-marked task. The behavior contract in Task 2 is fully covered by the green Task 3 tests.

## Known Stubs

None. The two offline panels render real core output; record/replay registry rows are intentionally deferred to Plan 03 (the registry is editable and the capability gate is in place for them), and the query panel to Plan 02 — both documented in the plan as out of scope for Plan 01.

## Notes for Next Plans

- **Plan 02 (query):** append a `("query", "Query", QueryPanel, False)` row to `MainWindow._registry`; the `panels` dict accessor and initial-panel selection already handle additional rows.
- **Plan 03 (record/replay + five-panel completeness):** append the two live rows with `is_live=True`; the capability gate in `MainWindow.__init__` already disables a live row's nav item + sets the teaching tooltip when `not self._ros_available`. The `panels` accessor exposes them for the five-panel SC1 completeness test.

## Self-Check: PASSED

All 9 created files present on disk; all 3 task commits (190455b, 2ee0f21, ef360b3) present in git history.
