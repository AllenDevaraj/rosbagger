---
phase: 14-gui
plan: 07
subsystem: ui
tags: [textual, tui, pytest-asyncio, run-test, pilot, offline-invariant, live-marker, phase-gate, proof]

# Dependency graph
requires:
  - phase: 14-gui (plan 14-02)
    provides: RosbaggerApp shell (nav-*/panel ids, _detect_ros capability gate, shared reader, asyncio_mode=auto scaffolding) — the App these tests drive
  - phase: 14-gui (plan 14-03)
    provides: InspectPanel (#bag-info DataTable) — the SC3 inspect assertion target
  - phase: 14-gui (plan 14-04)
    provides: QueryPanel (#sql-input Input + #results DataTable + the Enter-on-input run path) — the SC3 query assertion target
  - phase: 14-gui (plan 14-05)
    provides: RecordPanel (#topic-checklist discovery worker over real list_topics) — the live record integration target
  - phase: 14-gui (plan 14-06)
    provides: ReplayPanel (Play → build_publish_sink + Replayer.run() thread worker) — the live replay integration target
  - phase: 13-replay
    provides: rosbagger_replay.replay_bag / build_publish_sink / load_items / Replayer — the live publish path behind the replay panel
  - phase: 12-record
    provides: rosbagger_record.list_record_topics / record_topics — the live discovery/record path behind the record panel
provides:
  - tests/test_gui.py — the SC1/SC2/SC3 PROOF layer (headless App.run_test()/Pilot, ROS-FREE)
  - tests/test_offline_guard.py::test_import_gui_does_not_pull_ros — the GUI offline-import invariant (regression-locked)
  - tests/test_gui_live.py — the live-marked record/replay GUI integration (ROS-sourced lane; skipped offline)
  - a GREEN phase gate (full offline suite 465 passed @ 97.37% + ruff check + ruff format --check + offline guard)
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GUI proof-layer test: async def + asyncio_mode=auto (no per-test marker), App.run_test()/Pilot, await pilot.pause() after EVERY interaction before asserting (Pitfall 4)"
    - "Forced-no-ROS capability test: monkeypatch rosbagger_gui._detect_ros → False BEFORE App ctor so SC2 is meaningful on a ROS-equipped dev box (the ctor caches ros_available)"
    - "SC3 query trigger via the Enter-on-input path (focus sql-input, set value, pilot.press('enter')) — NOT a Run-button click, which can miss off-screen on the default 80-col harness viewport (14-04 caveat)"
    - "row_count is the stable textual 8.2.7 DataTable accessor (column-introspection accessor shifted across versions; verified row_count against the installed package)"
    - "Live GUI integration: importorskip('rclpy') + @pytest.mark.live + external publisher/subscriber subprocess (own rclpy context, no double-init clash); await app.workers.wait_for_complete() before asserting on a @work(thread=True) result"

key-files:
  created:
    - tests/test_gui.py
    - tests/test_gui_live.py
  modified:
    - tests/test_offline_guard.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py
    - .planning/phases/14-gui/deferred-items.md

key-decisions:
  - "SC2 forces no-ROS by monkeypatching rosbagger_gui._detect_ros → False before constructing the App (the 14-02 ctor caches ros_available = _detect_ros() once), so the capability gate is exercised deterministically even though this dev box HAS rclpy"
  - "SC3 query runs via the Enter-on-input path (focus + set value + press enter), not a Run-button click — the 14-04 SUMMARY documented that #run-query can miss on the default 80-col headless viewport; row_count is the stable accessor asserted"
  - "SC2 also drives the offline inspect panel under forced-no-ROS and asserts #bag-info row_count >= 1, proving 'offline panels work without ROS' (not merely 'live panels gated')"
  - "Live GUI integration awaits app.workers.wait_for_complete() after triggering the discovery/Play action so the @work(thread=True) worker (real list_topics / Replayer.run()) finishes before asserting on the widget it updated via call_from_thread"
  - "The blocking-prerequisite ruff format pass (inspect.py/tf.py) is its OWN atomic style() commit before the test commits, so the test history stays a clean RED→GREEN proof and the format fix is independently revertable"

requirements-completed: [GUI-01]

# Metrics
duration: ~4min
completed: 2026-05-24
---

# Phase 14 Plan 07: SC Proof + Offline Invariant + Phase Gate Summary

**GUI-01's three success criteria are now passing automated tests — SC1 (five panels exposed), SC2 (capability-gating with the offline panels still working), SC3 (inspect + query drive REAL `rosbagger_core` output to the widgets against a `make_fixtures` bag) — all headless via `App.run_test()`/`Pilot` and ROS-FREE in CI; the offline-import invariant now covers `rosbagger_gui` (a fresh-interpreter scan leaks no `rclpy`/`rosbag2_py`); a `live`-marked record/replay GUI integration test exercises the real discovery + publish paths on the ROS-sourced lane (skipped offline); and the full phase gate is green — 465 passed @ 97.37% + ruff check + ruff format --check + offline guard.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-24T06:48:23Z
- **Completed:** 2026-05-24T06:51:52Z
- **Tasks:** 2 (+ 1 blocking-prerequisite format pass)
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- **Blocking prerequisite — ruff format green (`f5fa849`):** ran `ruff format` on `panels/inspect.py` + `panels/tf.py` (the 14-03/14-04 whitespace divergence logged in `deferred-items.md`); `ruff format --check .` is now clean across all 90 files. Removed the resolved entry from `deferred-items.md`.
- **Task 1 — SC1/SC2/SC3 headless tests + the GUI offline guard (`de13a7c`):**
  - `tests/test_gui.py` is a self-contained async module (own repo-root/src `sys.path` insert; writes its OWN `write_ros2_sqlite_bag` fixture into `tmp_path`). Four `async def` tests under `asyncio_mode="auto"` (NOT skipped — Pitfall 3), each `await pilot.pause()` before asserting (Pitfall 4):
    - **SC1** `test_app_has_five_panels`: the five `nav-*` ListItems + the five ContentSwitcher panel ids are all queryable, and the switcher holds exactly those five children.
    - **SC2** `test_live_panels_disabled_without_ros`: monkeypatches `rosbagger_gui._detect_ros → False`, asserts `ros_available is False`, the record/replay nav items + panel widgets are `disabled`, the inspect/query/tf ones are NOT — and the inspect `#bag-info` DataTable still fills (`row_count >= 1`) without ROS (offline panels work).
    - **SC3 inspect** `test_inspect_panel_shows_real_topics`: after selecting inspect, `#bag-info` `row_count >= 1` (real `collect_bag_info` topics reached the widget).
    - **SC3 query** `test_query_panel_runs_real_core`: focuses `#sql-input`, sets `SELECT topic, t_ns FROM imu LIMIT 1`, presses Enter (the robust trigger), asserts `#results` `row_count == 1` (real `query()` output reached the widget).
  - `tests/test_offline_guard.py::test_import_gui_does_not_pull_ros`: a fresh-interpreter `env={"PYTHONPATH":""}` scan via the existing `_ros_modules_after_import` helper asserts `import rosbagger_gui` + `rosbagger_gui.app` leak no `rclpy`/`rosbag2_py` — mirrors `test_import_replay_does_not_pull_ros`.
- **Task 2 — live-marked record/replay GUI integration + phase gate (`4640e68`):**
  - `tests/test_gui_live.py` guarded by `pytest.importorskip("rclpy")` + `pytestmark = pytest.mark.live` (collected-and-SKIPPED offline, no import errors). Drives the real `RosbaggerApp` headlessly on the ROS-sourced lane: `test_record_panel_discovers_external_topic` (external `/telemetry` publisher subprocess → the record panel's `@work(thread=True)` discovery worker calls the real `list_topics` and populates `#topic-checklist`); `test_replay_panel_publishes_external_subscriber_receives` (external `/imu` subscriber subprocess → the replay panel's Play builds its own rclpy context + the SHARED `build_publish_sink` and drives `Replayer.run()` in a thread worker; the subscriber receives all 3 `/imu` messages). Both `await app.workers.wait_for_complete()` before asserting on the worker's `call_from_thread` widget update.
  - **Phase gate GREEN:** `PYTHONPATH="" uv run pytest` → **465 passed, 3 skipped, 97.37%** (coverage gate ≥80% on `rosbagger_core`+`bagq`, unchanged; `rosbagger_gui` stays OUT of it per D-12). `ruff check .` clean; `ruff format --check .` clean (90 files). The Phase-13 replay tests still green in the full run (no regression).

## Task Commits

Each task was committed atomically:

0. **Blocking prerequisite: ruff format inspect/tf panels** — `f5fa849` (style)
1. **Task 1: SC1/SC2/SC3 headless tests + GUI offline-import guard** — `de13a7c` (test)
2. **Task 2: live-marked record/replay GUI integration (ROS-sourced lane)** — `4640e68` (test)

## Files Created/Modified

- `tests/test_gui.py` — created: the SC1/SC2/SC3 proof layer (4 async App.run_test()/Pilot tests against a ROS-free fixture bag).
- `tests/test_offline_guard.py` — modified: added `test_import_gui_does_not_pull_ros` (fresh-interpreter scan, mirrors the replay/record guards).
- `tests/test_gui_live.py` — created: the live-marked record/replay GUI integration (importorskip rclpy + @mark.live; external publisher/subscriber subprocesses).
- `packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py` — modified: ruff format whitespace pass (no behavior change).
- `packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py` — modified: ruff format whitespace pass (no behavior change).
- `.planning/phases/14-gui/deferred-items.md` — modified: removed the resolved 14-06 format-divergence entry.

## Decisions Made

- SC2 forces no-ROS by monkeypatching `rosbagger_gui._detect_ros → False` BEFORE the App ctor (which caches `ros_available` once, 14-02) — the only way to exercise the capability gate deterministically on this ROS-equipped dev box.
- SC3 query runs via the Enter-on-input path (focus + set value + `press("enter")`), not a `#run-query` button click — the 14-04 SUMMARY documented the button can miss off-screen on the default 80-col headless viewport. `row_count` is the stable textual 8.2.7 accessor (verified against the installed package; the column-introspection accessor shifted across versions).
- SC2 additionally drives the offline inspect panel under forced-no-ROS and asserts `#bag-info row_count >= 1`, proving "offline panels work without ROS" rather than only "live panels are gated".
- The blocking-prerequisite ruff format pass is its OWN atomic `style()` commit before the test commits, keeping the test history a clean proof and the format fix independently revertable.

## Deviations from Plan

None — plan executed as written, including the documented blocking prerequisite (the ruff format pass on `inspect.py`/`tf.py`) which was in scope for this plan's phase-gate task.

One in-task housekeeping adjustment (not a deviation): a `ruff` I001 import-sort finding on `tests/test_gui.py`'s own new import block was auto-fixed (`ruff check --fix`) before the Task 1 commit — on this plan's own file, not pre-existing or out-of-scope.

## Threat Mitigations Applied

- **T-14-07-01 (Tampering / SC3 passing without executing):** `asyncio_mode="auto"` (14-02) means the async tests actually run (not skipped — verified `4 passed`, not `4 skipped`); `await pilot.pause()` before every assert flushes the message pump; SC3 asserts real `row_count` values (query `== 1`, inspect `>= 1`) that a no-op would not produce.
- **T-14-07-02 (Elevation / future ROS re-leak into the offline GUI graph):** `test_import_gui_does_not_pull_ros` regression-locks it via a fresh-interpreter `PYTHONPATH=""` subprocess scan over `rosbagger_gui` + `rosbagger_gui.app`.
- **T-14-07-SC (Tampering / package installs):** no NEW package installs in this plan (pytest-asyncio/textual/textual-dev were installed + slopchecked in 14-02); no blocking checkpoint needed.

## Known Stubs

None. The SC tests assert real core output (not placeholder/empty values) reaches the widgets; the live test drives the real discovery + publish paths.

## User Setup Required

None for the offline suite + the phase gate (ROS-free). To RUN `tests/test_gui_live.py` (the live lane) requires a sourced ROS 2 environment (`source /opt/ros/humble/setup.bash`) + the src-tree PYTHONPATH prepend in the file's docstring recipe; it is SKIPPED (not errored) without it.

## Next Phase Readiness

- GUI-01 is fully proven: SC1/SC2/SC3 are passing automated tests, the offline invariant covers the new package, the live lane is gated, and the full phase gate is green with the coverage gate unchanged. This is the FINAL plan of Phase 14 (7/7) and the final v0.2 phase.
- **Live-lane caveat (carried from Phases 12/13):** the `live`-marked GUI tests in `tests/test_gui_live.py` are collected-and-SKIPPED in this offline run. Actually RUNNING them on the ROS-sourced lane (the verified recipe in the file docstring) is a maintainer step — a collected-and-skipped result proves the gating + the import graph, not the live transport end-to-end.
- No blockers. Offline suite green (465 passed, 3 skipped, 97.37%); ruff check + format clean.

## Self-Check: PASSED

- FOUND: tests/test_gui.py
- FOUND: tests/test_gui_live.py
- FOUND: tests/test_offline_guard.py (test_import_gui_does_not_pull_ros present)
- FOUND: .planning/phases/14-gui/14-07-SUMMARY.md
- FOUND commit: f5fa849 (prerequisite — style)
- FOUND commit: de13a7c (Task 1 — test)
- FOUND commit: 4640e68 (Task 2 — test)
- Full offline suite green (465 passed, 3 skipped, 97.37%); ruff check + ruff format --check clean; the GUI offline guard + the 4 SC tests pass (NOT skipped); the live test is collected-and-skipped offline with no import errors.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
