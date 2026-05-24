---
phase: 14-gui
plan: 03
subsystem: ui
tags: [textual, tui, datatable, thin-face, offline-invariant, inspect, tf]

# Dependency graph
requires:
  - phase: 14-gui (plan 14-02)
    provides: RosbaggerApp shell — shared single-open RosbagsReader (D-02), ContentSwitcher panel registry, the open_bag() bag-switch seam, and the inspect/tf STUB panels this plan fills
  - phase: 04-inspect
    provides: collect_bag_info + collect_table_schemas (the ONLY APIs InspectPanel calls)
  - phase: 09-tf
    provides: collect_tf_report + NoTransformsError (the ONLY API TfPanel calls + its teaching error)
provides:
  - InspectPanel (D-05) — thin renderer over collect_bag_info + collect_table_schemas into a header line + bag-info/table-schemas DataTables
  - TfPanel (D-07) — thin renderer over collect_tf_report into edge-summary + gap-timeline DataTables, with the NoTransformsError teaching path
  - refresh_view() panel convention + the app.open_bag bag-switch callback wired to it (repopulates the active panel from core on a bag switch)
affects: [14-gui plan 14-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Thin-face panel: a Widget that composes textual DataTables and reads ONLY the App's shared reader; ALL numbers come from one rosbagger_core API — zero analysis logic in the GUI"
    - "refresh_view() data-refresh convention: on_mount + on_show + the open_bag bag-switch callback all call refresh_view() (Textual's .refresh() only re-renders existing data, never re-reads)"
    - "Offline-import invariant in panels: the rosbagger_core import lives INSIDE refresh_view(); panel module top stays textual-only (verified: importing the panel modules leaks no rclpy/rosbag2_py/rosbags/pyarrow/duckdb)"

key-files:
  created: []
  modified:
    - packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py
    - packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py
    - packages/rosbagger-gui/src/rosbagger_gui/app.py

key-decisions:
  - "Panels switched from Static base (14-02 stub) to Widget + compose() so each can mount its own child DataTables (the plan's `InspectPanel(Widget)` shape); offline/live distinction stays data in the _PANELS registry, unaffected"
  - "Added a refresh_view() data-refresh hook + wired app.open_bag to call it: 14-02's open_bag called the active panel's Textual .refresh() (a render-only refresh that would NOT re-read a switched bag). Calling refresh_view() when present makes a bag switch actually repopulate from core (Rule 3 — wiring the bag-switch callback the plan references)"
  - "on_show() also calls refresh_view() so switching TO a panel (not just opening a bag) re-reads the current shared reader — covers the ContentSwitcher nav path, not only the open_bag path"
  - "TfPanel renders the empty-gaps case as a single 'no gaps detected' row inside the tf-gaps DataTable (rather than a separate Static), keeping one cleared-and-refilled table per refresh; the gap-timeline columns mirror bagq tf (parent/child/gap/at bag-t/at abs-ns)"

requirements-completed: [GUI-01]

# Metrics
duration: 6min
completed: 2026-05-24
---

# Phase 14 Plan 03: Inspect + TF Offline Panels Summary

**InspectPanel and TfPanel are now thin faces over `rosbagger_core` — InspectPanel renders `collect_bag_info` + `collect_table_schemas` (topics/types/counts/Hz + duration/size/message_count + per-topic table schemas) and TfPanel renders `collect_tf_report` (parent→child edge summary + per-edge gap timeline, with a `NoTransformsError` teaching path) — each driving the App's single shared reader with zero analysis logic, an empty-state, and a bag-switch refresh.**

## Performance

- **Duration:** ~6 min
- **Tasks:** 2
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments
- **InspectPanel (D-05):** a `Widget` composing a whole-bag header `Static` (`duration · message_count · human size`) plus a `bag-info` DataTable (topic/msgtype/count/hz, `<mixed>`/em-dash placeholders) and a `table-schemas` DataTable (table/column/type/lazy-blob). `refresh_view()` lazily imports and calls `collect_bag_info` + `collect_table_schemas` against the shared reader. Proven end-to-end against the TF fixture bag: 2 topic rows, 10 schema-column rows, header `duration: 2.30s · 25 messages · 37.0 KB`.
- **TfPanel (D-07):** a `Widget` composing a `tf-status` `Static` summary line plus a `tf-edges` DataTable (parent/child/kind/count/rate(Hz)/max gap/gaps — mirroring `bagq tf`) and a `tf-gaps` DataTable (parent/child/gap/at bag-t/at abs-ns). `refresh_view()` lazily imports and calls `collect_tf_report`; `NoTransformsError` is caught and rendered as a teaching status line, never a crash (T-14-03-02). Proven against the TF fixture: 3 edges, 1 gap (the 09-01-seeded 800ms dropout), `2 dynamic edges, 1 static edges over 2.30s`; and the no-`/tf` path renders `Bag has no /tf or /tf_static topics. Available topics: …`.
- **Bag-switch refresh wired (D-02):** `app.open_bag` now calls the active panel's `refresh_view()` (when present), so switching the shared reader repopulates the panel from core — previously the seam called only Textual's render-level `.refresh()`.
- **Offline invariant held:** importing `rosbagger_gui.panels.inspect` / `.tf` leaks none of `rclpy`/`rosbag2_py`/`rosbags`/`pyarrow`/`duckdb` (the core imports live inside `refresh_view()`).

## Task Commits

Each task was committed atomically:

1. **Task 1: InspectPanel — collect_bag_info + collect_table_schemas into DataTables (D-05)** - `2be90c8` (feat) — also wired `app.open_bag` to the `refresh_view()` callback.
2. **Task 2: TfPanel — collect_tf_report into edge + gap DataTables (D-07)** - `2b0d93a` (feat)

## Files Modified
- `packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py` - filled the stub: `InspectPanel(Widget)` over `collect_bag_info` + `collect_table_schemas`, header + two DataTables, lazy core import, empty-state, `refresh_view()` on `on_mount`/`on_show`.
- `packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py` - filled the stub: `TfPanel(Widget)` over `collect_tf_report`, edge + gap DataTables, `NoTransformsError` teaching path, lazy core import, empty-state, `refresh_view()`.
- `packages/rosbagger-gui/src/rosbagger_gui/app.py` - `open_bag` now calls the active panel's `refresh_view()` (data re-read) when present, falling back to `.refresh()`.

## Decisions Made
- Panels promoted from the 14-02 `Static` stub to `Widget` + `compose()` so each mounts its own child DataTables (the plan's `InspectPanel(Widget)`/`TfPanel(Widget)` shape). The offline/live gate is unaffected — it is data in the `_PANELS` registry, and inspect/tf are offline (always enabled).
- Introduced a `refresh_view()` data-refresh convention called from `on_mount`, `on_show`, and the `open_bag` bag-switch callback. Textual's `.refresh()` is render-only and would not re-read a switched bag; `refresh_view()` re-reads the shared reader and re-fills the tables.
- TfPanel renders the empty-gaps case as a single `no gaps detected` row inside the `tf-gaps` DataTable (one cleared-and-refilled table per refresh), rather than swapping in a separate `Static`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wired `app.open_bag` to a panel `refresh_view()` data-refresh callback**
- **Found during:** Task 1
- **Issue:** The plan's `<action>` says "the App calls back the active panel on `open_bag`", but 14-02's `open_bag` calls the active panel's Textual `.refresh()` — a render-only refresh that does NOT re-read a newly-switched shared reader. A bag switch would leave the panel showing the prior bag's data, so the panel could not actually satisfy "refresh whenever the bag is switched."
- **Fix:** Added a `refresh_view()` method to both panels (the data-read path) and updated `open_bag` to call `panel.refresh_view()` when present (falling back to `.refresh()` for any panel without it). This is the bag-switch callback the plan references — wiring, not new behavior. Also call `refresh_view()` from `on_show` so switching TO a panel re-reads too.
- **Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/app.py`, `inspect.py`, `tf.py`
- **Commit:** `2be90c8` (the app.py + inspect.py change), `2b0d93a` (tf.py)

(Promoting the panels from `Static` to `Widget` was required by the plan's own `InspectPanel(Widget)`/`TfPanel(Widget)` interface text — not a deviation.)

## Issues Encountered
- None affecting the panels. A first headless smoke-test harness passed the fixture's *parent* directory instead of the writer's returned bag path (`write_tf_bag` returns the actual bag dir); corrected the test invocation and the end-to-end run then rendered real rows for both panels. No code change to the panels was needed.

## User Setup Required
None — both panels are offline (no ROS) and need no configuration.

## Next Phase Readiness
- Two of the three always-on offline panels are now live faces over core. Plan 14-04 fills the query panel; 14-06 fills the live record/replay panels; 14-07 adds the headless App tests that formally prove SC3 (the inspect `bag-info` DataTable `row_count >= 1` against a fixture) and the tf rendering against the tf fixture — both already demonstrated here via an ad-hoc `run_test()` (inspect 2 rows / 10 schema rows; tf 3 edges / 1 gap; the no-`/tf` teaching path).
- No blockers. Offline-import invariant for the panel modules verified intact.

## Self-Check: PASSED

Both modified panel files exist on disk and import cleanly (`import rosbagger_gui.panels.inspect, rosbagger_gui.panels.tf` exits 0); both task commits (`2be90c8`, `2b0d93a`) are in the git log; the headless `run_test()` proved real core-driven rows for both panels and the NoTransformsError teaching path.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
