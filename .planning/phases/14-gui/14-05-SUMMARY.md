---
phase: 14-gui
plan: 05
subsystem: ui
tags: [textual, tui, threads, workers, live, record, capability-gating, offline-invariant]

# Dependency graph
requires:
  - phase: 14-gui (plan 14-02)
    provides: RosbaggerApp shell — the App-owned ros_available tier-1 capability gate (D-03/D-04) that disables this live panel when rclpy is absent, the ContentSwitcher panel registry, and the record STUB panel this plan fills
  - phase: 12-record
    provides: rosbagger_record front door — list_topics/record (+ submodule-shadow-proof aliases list_record_topics/record_topics), discover_topics/select_topics, and the teaching errors (RosNotAvailableError/NoTopicsMatchedError/McapStorageUnavailableError)
provides:
  - RecordPanel (D-04/D-08) — the live thin face over rosbagger_record: a @work(thread=True) discovery worker filling a topic SelectionList via call_from_thread, and a @work(thread=True) record worker driving the real record() API (bounded duration + worker-cancel Stop), with teaching-error handling and an offline-clean import graph
affects: [14-gui plan 14-06, 14-gui plan 14-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live panel thread-worker pattern: every blocking ROS call (discovery scan, record loop) runs in @work(exclusive=True, thread=True); widget updates marshalled back to the event-loop thread via self.app.call_from_thread — the TUI never freezes (RESEARCH Pitfall 1 / T-14-05-01)"
    - "Submodule-shadow-proof lazy import: the panel imports list_record_topics/record_topics (the alias front doors) inside worker bodies — importing the rosbagger_record.record SUBMODULE anywhere would rebind the bare record name to the module, so the aliases are the guaranteed-callable handles"
    - "Bounded-record + worker-cancel Stop: record() owns its own rclpy.ok()+_should_stop spin loop with no in-process interrupt hook from the event loop, so the GUI drives a BOUNDED duration (self-terminating) and Stop cancels the worker group (suppressing the late result callback) — the panel never opens an unbounded record it could not stop"
    - "Offline-import invariant held in a LIVE panel: rosbagger_record/rclpy imported INSIDE worker/method bodies only; importing rosbagger_gui.panels.record leaks no rclpy/rosbag2_py (fresh-interpreter scan)"

key-files:
  created: []
  modified:
    - packages/rosbagger-gui/src/rosbagger_gui/panels/record.py

key-decisions:
  - "Discovery via list_record_topics() (the lazy list_topics front-door alias) rather than re-creating an rclpy node in the panel: list_topics owns its own short-lived node + spin-to-settle, so the panel duplicates NO node mechanics — the plan's explicit 'simplest correct path that needs no duplicated node mechanics' preference"
  - "Promoted RecordPanel from the 14-02 Static stub to a Widget that composes its own children (status Static, topic SelectionList, out Input, storage RadioSet, Start/Stop Buttons) — the plan's RecordPanel(Widget) shape; offline/live gating is unchanged (data in the _PANELS registry, record stays live-gated by ros_available)"
  - "SelectionList (not a ListView of Checkbox) for the topic checklist — each option carries the topic NAME as its value, so the Start handler reads checklist.selected verbatim and constructs no selection (record() owns discover->select->record, D-08)"
  - "Stop cancels the record-run worker group (self.workers.cancel_group) AND the bounded duration ends record()'s loop — the bound is the actual terminator; the cancel suppresses the late call_from_thread status write so a Stop reads as a clean end. on_worker_state_changed re-enables Start as a safety net on every worker exit path"
  - "Caught the FULL teaching-error family RosNotAvailableError/NoTopicsMatchedError/McapStorageUnavailableError (the plan AC required the first two; McapStorageUnavailableError added as a Rule 2 correctness path — the default storage is mcap and on this box the mcap plugin is unregistered, so record() would raise it). A bare `except Exception` (noqa BLE001) below the typed catch surfaces any other live failure as teaching status text, never a TUI-crashing traceback"

requirements-completed: [GUI-01]

# Metrics
duration: ~10min
completed: 2026-05-24
---

# Phase 14 Plan 05: Live Record Panel Summary

**RecordPanel is now a live thin face over `rosbagger_record`: on show (when `ros_available`) a `@work(thread=True)` discovery worker lazily calls `list_record_topics()` and fills a topic `SelectionList` checklist via `call_from_thread`; Start gathers the checked topics + out path + storage and runs a SECOND `@work(thread=True)` worker driving the real `record_topics()` API with a bounded `duration`, posting the captured count back; Stop cancels the worker group (the bound ends `record()`'s loop) — with the full teaching-error family presented on the status line and an offline-import graph that leaks no `rclpy`/`rosbag2_py`.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 1
- **Files modified:** 1 (0 created, 1 modified)

## Accomplishments

- **Task 1 — RecordPanel discovery scan + start/stop record (D-04/D-08):** `RecordPanel(Widget)` composes a `record-status` `Static`, a `topic-checklist` `SelectionList`, a `record-out` `Input` (default `rosbagger_record_out`), a `record-storage` `RadioSet` (mcap default + sqlite3 escape, D-08), and `record-start`/`record-stop` `Button`s. On `on_mount`/`on_show`, `_scan_topics()` checks the App's tier-1 `ros_available` gate (the teaching-hint state when ROS is absent) and otherwise fires a `@work(exclusive=True, thread=True)` discovery worker that lazily `from rosbagger_record import list_record_topics` and posts the `{topic: type}` map back via `self.app.call_from_thread(self._populate_checklist, ...)`. Start reads `checklist.selected` verbatim (empty-selection guarded with a teaching status), disables Start / enables Stop, and runs a `@work(exclusive=True, thread=True)` record worker that lazily `from rosbagger_record import record_topics` and calls `record_topics(topics, out, storage=storage, duration=_DEFAULT_RECORD_SECONDS)`, posting the captured count to the status line via `call_from_thread`. Stop calls `self.workers.cancel_group(self, "record-run")` (the bounded duration ends the loop; the cancel suppresses the late callback) and resets the controls; `on_worker_state_changed` re-enables Start on every record-worker exit as a safety net.
- **Thread-worker discipline (T-14-05-01 / Pitfall 1):** both blocking ROS paths (the discovery scan and the record loop) run in `@work(thread=True)` workers; every widget update from a worker goes through `self.app.call_from_thread` — the event loop is never blocked. Six `@work`/`thread=True` decorators present; twelve `call_from_thread` sites.
- **Offline invariant held in a live panel (T-14-05-02):** every `rosbagger_record`/`rclpy` import lives inside a worker/method body (module-top ROS-import scan is 0); a fresh-interpreter `import rosbagger_gui.panels.record` leaks none of `rclpy`/`rosbag2_py`. Verified headlessly: the panel mounts and all six widgets compose; on this `PYTHONPATH=""` lane `ros_available` is `False`, so the panel correctly shows the teaching-hint state and skips the scan.
- **No regression:** the full offline suite stays green — 460 passed, 2 skipped, 97.37% (unchanged baseline; the GUI is intentionally outside the coverage gate per Phase 13 D-12). `ruff check`/`ruff format --check` clean on the GUI src.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fill live RecordPanel — tier-2 discovery scan + record() in thread workers** — `90fb5d1` (feat)

## Files Modified

- `packages/rosbagger-gui/src/rosbagger_gui/panels/record.py` — filled the 14-02 stub: `RecordPanel(Widget)` over `rosbagger_record` — a `@work(thread=True)` discovery worker (`list_record_topics` → `SelectionList` via `call_from_thread`), a `@work(thread=True)` record worker (real `record_topics()` with bounded `duration`), Start/Stop with worker-cancel, full teaching-error handling, and lazy ROS imports inside worker/method bodies.

## Decisions Made

- Discovery via `list_record_topics()` (the lazy `list_topics` front-door alias) — it owns its own short-lived `rclpy` node + spin-to-settle, so the panel duplicates no node mechanics (the plan's preferred simplest-correct path).
- Promoted `RecordPanel` from the 14-02 `Static` stub to a `Widget` composing its own children; offline/live gating is unchanged (record stays `ros_available`-gated via the App).
- `SelectionList` for the checklist; each option carries the topic name as its value so Start reads `checklist.selected` verbatim — the panel builds no selection (`record()` owns discover→select→record).
- Stop cancels the `record-run` worker group AND the bounded `duration` ends `record()`'s loop (the bound is the actual terminator); `on_worker_state_changed` re-enables Start on every worker exit as a safety net.
- Caught the full teaching-error family including `McapStorageUnavailableError` (a Rule 2 correctness add — the default storage is `mcap`, unregistered on this box, so `record()` would raise it); a typed catch presents the teaching message and a trailing `except Exception` surfaces any other live failure as status text, never a traceback.

## Deviations from Plan

None — plan executed as written.

Two adjustments worth noting (neither a scope deviation):
- **[Rule 2 — Missing critical functionality]** Added `McapStorageUnavailableError` to the caught teaching-error family. The plan's AC required `RosNotAvailableError`/`NoTopicsMatchedError` (both present); but `record()`'s default `storage="mcap"` hits `_check_storage` first, and on a box without the mcap plugin that raises `McapStorageUnavailableError` — leaving it uncaught would surface a traceback in the TUI instead of the teaching remedy ("install the plugin or pass --storage sqlite3"). Caught + presented on the status line. Commit `90fb5d1`.
- In-task housekeeping (not a deviation): `ruff format` reformatted this plan's own new file before the commit (long status-string lines). On this plan's own file, fixed before the Task 1 commit.

## Issues Encountered

- `record()` exposes no in-process interrupt hook callable from the event loop (its spin loop checks `rclpy.ok()` + the bounded `_should_stop` deadline, and SIGINT is the unbounded-stop path). The GUI therefore drives a BOUNDED `duration` (self-terminating) and implements Stop as a worker-group cancel that suppresses the late result callback — exactly the worker-cancel / bounded path the plan sanctioned. Live behavior (the actual record loop ending on Stop) is exercised by the `live`-marked GUI integration test in Plan 14-07 (ROS-sourced lane); offline this is proven structurally (mount + compose + the offline-clean import graph).

## User Setup Required

None for the offline import graph + the panel mount. To ACTUALLY record, the live panel needs a sourced ROS 2 environment (it surfaces the teaching hint otherwise) and a registered storage plugin (MCAP default; pass/select `sqlite3` if the mcap plugin is absent, e.g. on this box).

## Next Phase Readiness

- The first of the two live panels is filled. Plan 14-06 fills the live ReplayPanel (the same `@work(thread=True)` + `call_from_thread` shape over `rosbagger_replay`'s `replay_bag()` / `build_publish_sink`). Plan 14-07 adds the headless App tests + the formal offline-import-guard test for the GUI graph and the `live`-marked record/replay integration tests (ROS-sourced lane, `importorskip("rclpy")`, skipped in offline CI) that exercise the actual discovery scan + record loop / Stop.
- No blockers. Offline-import invariant for the record panel module verified intact; the full offline suite stays green (460 passed, 2 skipped, 97.37%).

## Self-Check: PASSED

The modified panel file exists on disk and imports cleanly (`import rosbagger_gui.panels.record` exits 0, fresh-interpreter scan leaks no `rclpy`/`rosbag2_py`); the Task 1 commit (`90fb5d1`) is in the git log; the panel mounts headlessly with all six widgets composing; the full offline suite + `ruff` are green.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
