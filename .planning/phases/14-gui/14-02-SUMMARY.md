---
phase: 14-gui
plan: 02
subsystem: ui
tags: [textual, tui, content-switcher, capability-gating, uv-workspace, pytest-asyncio]

# Dependency graph
requires:
  - phase: 02-reader
    provides: RosbagsReader (open/close/context-manager + O(1) metadata) — the App's shared reader
  - phase: 14-gui (plan 14-01)
    provides: build_publish_sink re-exported from rosbagger_replay (the replay panel will import it in Wave 3)
provides:
  - rosbagger-gui uv workspace member (deps = rosbagger-core + textual; NOTHING ROS)
  - RosbaggerApp shell — sidebar ListView + ContentSwitcher over five panels (D-01)
  - shared single-open-reader lifecycle owned by the App (D-02) + open_bag() picker seam
  - cheap tier-1 _detect_ros capability gate disabling the live record/replay panels (D-03/D-04)
  - five STUB panels (inspect/query/tf offline always-enabled; record/replay live capability-gated)
  - rosbagger-gui console script (launch-arg <bag-path>)
  - pytest-asyncio + asyncio_mode="auto" + textual-dev dev tooling for the Plan 14-07 headless tests
affects: [14-gui plan 14-03, 14-04, 14-05, 14-06, 14-07]

# Tech tracking
tech-stack:
  added: [textual>=8 (TUI), pytest-asyncio (headless App tests), textual-dev (devtools)]
  patterns:
    - "Thin-face GUI: panels are Static/Widget stubs over module APIs; GUI stays OUT of the coverage gate (D-12)"
    - "Offline-import invariant in the GUI: _detect_ros + all live/ROS imports live INSIDE function/method bodies"
    - "Panel registry tuple drives compose(): nav ids = 'nav-'+panel id, ContentSwitcher keys = panel id"

key-files:
  created:
    - packages/rosbagger-gui/pyproject.toml
    - packages/rosbagger-gui/src/rosbagger_gui/__init__.py
    - packages/rosbagger-gui/src/rosbagger_gui/app.py
    - packages/rosbagger-gui/src/rosbagger_gui/app.tcss
    - packages/rosbagger-gui/src/rosbagger_gui/cli.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/__init__.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/query.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/record.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "argparse (not typer) for cli.py: stdlib, dependency-free, gives `--help` exit 0 WITHOUT constructing the App (no TUI launch); RosbaggerApp imported lazily inside main()"
  - "Panels subclass textual.widgets.Static (not bare Widget) so the placeholder/teaching-hint text mounts with zero extra compose() boilerplate; the offline/live distinction is data in the _PANELS registry, not separate base classes"
  - "ROS-2-Humble typestore (from the ROS-FREE rosbags.typesys) passed as default_typestore so the legacy ROS 2 sqlite3 fixture opens; modern bags / MCAP / ROS 1 ignore the unused default — keeps the offline invariant intact"
  - "_PANELS registry tuple is the single source of truth for nav ids, ContentSwitcher keys, labels, and the is_live gate — compose() + on_mount iterate it so the five ids can't drift"

patterns-established:
  - "Capability gate (D-03): a single _detect_ros() at App.__init__ sets self.ros_available; on_mount disables both the live nav ListItems and the live panel widgets so the teaching hint is the only inert thing shown"
  - "Shared reader (D-02): App owns ONE RosbagsReader (opened on_mount / closed on_unmount); open_bag() is the close-then-open picker seam that refreshes the active panel"

requirements-completed: [GUI-01]

# Metrics
duration: 4min
completed: 2026-05-24
---

# Phase 14 Plan 02: GUI App Shell + Packaging Summary

**Launchable `rosbagger-gui` Textual cockpit — a sidebar ListView + ContentSwitcher over five (stubbed) panels, an App-owned single shared reader, the cheap rclpy capability gate that disables the live record/replay panels, and the pytest-asyncio test scaffolding — all on an offline-clean import graph.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-24T06:18:07Z
- **Completed:** 2026-05-24T06:22:16Z
- **Tasks:** 2
- **Files modified:** 13 (11 created, 2 modified)

## Accomplishments
- New `rosbagger-gui` uv workspace member: deps `rosbagger-core` + `textual>=8,<9`, NOTHING ROS declared (D-03); `import rosbagger_gui` resolves offline.
- `RosbaggerApp` shell: `Horizontal(ListView sidebar, ContentSwitcher)` with five nav items driving the switcher (D-01); proven via a headless `run_test()` that mounts `nav-inspect..nav-replay` + panels `inspect..replay`.
- Shared single-open reader (D-02): the App opens ONE `RosbagsReader` from the launch `<bag-path>` (verified end-to-end against a real ROS 2 sqlite3 fixture — topics + message_count read off the shared reader); `open_bag()` is the in-TUI picker seam.
- Capability gate (D-03/D-04): `_detect_ros()` computed once; with ROS absent the live record/replay nav items AND panel widgets are disabled (verified `disabled=True`), offline panels stay enabled.
- Dev/test scaffolding for Plan 14-07: `pytest-asyncio` + `asyncio_mode="auto"` + `textual-dev` added to the dev group; GUI kept OUT of the coverage gate (Phase 13 D-12 thin-face rule).

## Task Commits

Each task was committed atomically:

1. **Task 1: Workspace-member packaging + root pyproject wiring + dev async plugin** - `69f8ab4` (chore)
2. **Task 2: App shell — sidebar + ContentSwitcher, shared reader, ROS gate, panel stubs** - `ea0cf64` (feat)

**Plan metadata:** (final docs commit — see below)

## Files Created/Modified
- `packages/rosbagger-gui/pyproject.toml` - workspace-member manifest (rosbagger-core + textual; console script; hatchling)
- `packages/rosbagger-gui/src/rosbagger_gui/__init__.py` - ROS-free package top + cheap tier-1 `_detect_ros` (rclpy import INSIDE the body)
- `packages/rosbagger-gui/src/rosbagger_gui/app.py` - `RosbaggerApp`: sidebar+ContentSwitcher shell, shared reader lifecycle, ROS gate
- `packages/rosbagger-gui/src/rosbagger_gui/app.tcss` - Horizontal layout + disabled-live dim styling
- `packages/rosbagger-gui/src/rosbagger_gui/cli.py` - argparse `main()` parsing optional `<bag-path>` -> `RosbaggerApp(...).run()`
- `packages/rosbagger-gui/src/rosbagger_gui/panels/*` - five panel stubs (inspect/query/tf offline; record/replay live-gated) + `__init__` re-export
- `pyproject.toml` - gui src added to `[tool.ruff] src`; pytest-asyncio + textual-dev in dev group; `asyncio_mode="auto"`; coverage gate unchanged
- `uv.lock` - re-resolved: rosbagger-gui + textual + dev plugins, no ROS wheel

## Decisions Made
- argparse (not typer) for `cli.py`: stdlib, dependency-free, `--help` exits 0 without launching the App; `RosbaggerApp` imported lazily inside `main()`.
- Panels subclass `textual.widgets.Static` so the placeholder/teaching-hint mounts with zero compose() boilerplate; offline-vs-live is data in the `_PANELS` registry, not separate base classes.
- Passed the ROS-2-Humble typestore (from the ROS-free `rosbags.typesys`) as `default_typestore` so the legacy ROS 2 sqlite3 fixture opens; modern bags / MCAP / ROS 1 ignore the unused default.
- `_PANELS` registry tuple is the single source of truth for nav ids, ContentSwitcher keys, labels, and the `is_live` gate — `compose()` + `on_mount` iterate it so the five ids can't drift.

## Deviations from Plan

None - plan executed exactly as written. Three minor in-task adjustments were housekeeping, not deviations:
- Two ruff findings in newly-written code were cleaned during Task 2's verify step (an E501 over-long `Static(...)` string in `tf.py` shortened; an I001 import-block sort auto-fixed by `ruff check --fix` + `ruff format`). These were on this plan's own new files, fixed before the Task 2 commit — not pre-existing or out-of-scope.

## Issues Encountered
- The plan's Task 1 acceptance grep `grep -c 'rclpy|rosbag2_py|rosidl' packages/rosbagger-gui/pyproject.toml == 0` initially failed because the manifest's explanatory comment mentioned those tokens. Reworded the comment to "the ROS runtime" so the grep is clean — the manifest still declares zero ROS deps (the actual intent). No functional change.
- The plan's Task 2 acceptance grep for literal `nav-inspect` etc. finds nothing because the nav ids are built via `f"nav-{panel_id}"` from the `_PANELS` registry (not literal). Verified the stronger runtime guarantee instead: a headless `App.run_test()` confirms all five `nav-*` ListItem ids and all five panel ids are actually mounted, plus the live-gate disabled state and a real shared-reader open.

## User Setup Required
None - no external service configuration required. (The live record/replay panels require a sourced ROS 2 environment to be ENABLED, but the shell, packaging, and offline panels need no setup; the live panels surface a teaching hint when ROS is absent.)

## Next Phase Readiness
- The shell, packaging, capability gate, and shared-reader seam every panel sits on are in place. Waves 2-3 fill the five stubs: 14-03/04/05 wire the offline inspect/query/tf panels over the shared reader; 14-06 wires the live record/replay panels (lazy-importing rosbagger_record / rosbagger_replay — incl. 14-01's `build_publish_sink`); 14-07 adds the headless App tests (asyncio scaffolding is ready) + the formal offline-import-guard test for the GUI graph.
- No blockers. Offline invariant locked from the start (fresh-interpreter scan leaks no rclpy/rosbag2_py); full offline suite stays green (460 passed, 2 skipped, 97.37%).

## Self-Check: PASSED

All 11 created source/manifest files + the SUMMARY exist on disk; both task commits (`69f8ab4`, `ea0cf64`) are in the git log.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
