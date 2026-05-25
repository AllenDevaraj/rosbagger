---
phase: 16-native-desktop-gui-pyside6
plan: 03
subsystem: rosbagger-desktop (native PySide6 desktop GUI — Record + Replay live panels)
tags: [gui, pyside6, qt, qthread, live, record, replay, scrubber, capability-gate, thin-frontend]
dependency_graph:
  requires:
    - rosbagger-record (list_record_topics / record_topics + the three teaching errors — lazy live use)
    - rosbagger-replay (load_items, build_publish_sink, Replayer, scheduler.State, NoMessagesToReplayError, RosNotAvailableError — lazy live use)
    - rosbagger-core (events.list_events for jump-to-event markers)
    - rosbagger-desktop MainWindow shell + editable panel registry + capability gate (Plans 16-01/16-02)
    - tools.make_fixtures (write_ros2_sqlite_bag)
  provides:
    - workers.py — BlockingWorker (QObject moveToThread) + run_on_thread / stop_thread scaffolding (D-15, Pattern 3)
    - widgets/scrubber.py — Qt QSlider Scrubber emitting seek fractions + an event-marker overlay
    - panels/record_panel.py — Record QWidget over list_record_topics + record_topics on QThread workers (D-13)
    - panels/replay_panel.py — Replay QWidget over the pure Replayer + the single build_publish_sink on a QThread worker (D-14/D-05)
    - Record + Replay nav rows registered in MainWindow (is_live=True, capability-gated) — full five-panel parity (SC1/SC2)
    - tests/test_desktop_live.py — live-marked record/replay lane gated by importorskip(rclpy)
  affects:
    - PHASE 16 COMPLETE (3/3) — the native desktop cockpit reaches full TUI parity
tech_stack:
  added: []
  patterns:
    - QObject worker moved to a QThread, started via thread.started, emitting result/failed/finished signals (NEVER subclass QThread) — D-15 Pattern 3
    - Pitfall-2 teardown wiring (finished->quit, finished->worker.deleteLater, thread.finished->thread.deleteLater) + kept self._thread refs + quit()+wait() on close
    - every rosbagger_record / rosbagger_replay / rclpy / list_events import lazy INSIDE a worker callable / method body (offline + Qt-free import invariant)
    - bounded record duration self-terminates (WR-03) — Dismiss does not stop the capture early (no in-process hook)
    - re-entrant-safe own-context guard for replay (init rclpy only when not rclpy.ok(); teardown only our own context — WR-04/WR-05)
    - the single build_publish_sink is the ONLY publish path (D-05) — the panel inlines no publisher-build/deserialize mechanics
    - _drive_running guard ignores Play/Step/seek while a drive worker runs (WR-06 / Pitfall 7); Pause stays allowed; seek the only position-setter
    - Qt Scrubber programmatic set_position suppresses the seeked emit so reflecting the cursor never triggers a fresh jump
key_files:
  created:
    - packages/rosbagger-desktop/src/rosbagger_desktop/workers.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/__init__.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
    - tests/test_desktop_live.py
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py (register the Record + Replay live rows in inspect/query/tf/record/replay order)
    - tests/test_desktop.py (add test_app_has_five_panels + test_live_panels_disabled_without_ros; update stale nav-count assertions 3 -> 5)
decisions:
  - The blocking callable is PASSED IN to BlockingWorker (the panel lazily imports the live module inside the callable body), so workers.py names no live symbol and stays offline-clean — the single concurrency scaffold serves all three blocking calls
  - Scrubber is a QSlider subclass (not a from-scratch paint widget): the base slider gives the groove + draggable playhead for free; markers are painted as ticks in paintEvent and a programmatic set_position suppresses the seeked emit (only a user drag/click reports a fraction)
  - A teaching-error tuple is resolved lazily via importlib.import_module inside a helper (never at module top) so importing record_panel pulls no rosbagger_record; a resolution failure falls back to the generic teaching path
  - The capability-gate loop + panels dict accessor from Plan 16-01 handle the two new live rows generically (is_live=True) — no gate-logic change needed, only two registry rows + two panel constructions
metrics:
  duration: ~12min
  completed: 2026-05-25
  tasks: 3
  files: 8
---

# Phase 16 Plan 03: rosbagger-desktop Record + Replay live panels Summary

Completed the native PySide6 desktop cockpit to full five-panel parity with the Textual TUI by adding the two LIVE panels — Record and Replay — plus the reusable `QThread` worker scaffolding and the Qt `Scrubber` they ride on. Record discovers live topics and records a selected subset via `rosbagger_record` on a `QThread` worker; Replay drives the pure `Replayer` through the SINGLE `build_publish_sink` (D-05) on a `QThread` worker with six transport controls and a Qt scrubber. Both live panels keep every `rclpy` / `rosbagger_record` / `rosbagger_replay` / `list_events` import lazy inside worker / method bodies, are capability-gated in the QMainWindow nav, and are proven by an `importorskip(rclpy)` + `pytest.mark.live` lane. The offline import graph stays ROS-free AND Qt-free; the full phase gate is green at 97.37%.

## What Shipped

- **workers.py** — `BlockingWorker(QObject)` holding a blocking callable, `moveToThread`'d onto a `QThread`, started via `thread.started`, emitting `result` / `failed` / `finished` (D-15 Pattern 3 — never subclasses `QThread`). `run_on_thread(owner, worker, on_result, on_failed, on_finished=None)` wires the Pitfall-2 teardown chain (`finished->quit`, `finished->worker.deleteLater`, `thread.finished->thread.deleteLater`), keeps the thread ref on the panel, and starts it. `stop_thread(thread)` quits+waits a running thread on close. A *known* teaching error emits `str(exc)` verbatim; any other `Exception` emits a one-line `"<label>: <exc>"` (never a traceback); `finished` always fires in a `finally`. Imports ONLY PySide6 + stdlib — names no live symbol (the callable is passed in).
- **widgets/scrubber.py** — `Scrubber(QSlider)`: a 0..1000 horizontal slider (a 0..1 fraction playhead) emitting `seeked(float)` on a USER drag/click, with a `_MARKER_SNAP_FRACTION` snap-to-marker port and an event-marker tick overlay (`set_markers`, `paintEvent`). `set_position(fraction)` (panel-driven, UI-thread slot) suppresses the `seeked` emit so reflecting the scheduler cursor never triggers a fresh jump (the Qt analog of the TUI `Scrubber.Seeked` message). Imports ONLY PySide6 + stdlib.
- **widgets/__init__.py** — re-exports `Scrubber`, `EventMark` (offline-clean).
- **panels/record_panel.py** — `RecordPanel(QWidget)` (D-13): status label, checkable-item topic `QListWidget`, output `QLineEdit` (default `rosbagger_record_out`), mcap/sqlite3 `QRadioButton`s (mcap default, D-08), Start + Dismiss buttons. On show, a discovery `QThread` worker lazily calls `list_record_topics()` and fills the checklist via a UI-thread slot; Start runs `record_topics(topics, out, storage=, duration=10s)` on a SECOND worker (bounded → self-terminates, WR-03); Dismiss tears down the worker and writes the WR-03 "the bounded record finalizes on its own" status (no early-stop hook). Empty selection guarded with a teaching status. Every `rosbagger_record` / `rclpy` import lazy inside a worker callable.
- **panels/replay_panel.py** — `ReplayPanel(QWidget)` (D-14/D-05): status label, the Qt `Scrubber`, Play/Pause/Step buttons, a rate `QLineEdit` (default `1.0`), a loop `QCheckBox`. `_ensure_transport()` is idempotent: lazily imports `rclpy` + the `rosbagger_replay` front door, loads `items = load_items(reader.paths[0])`, creates the panel's OWN rclpy context only when `not rclpy.ok()` (WR-04 re-entrant-safe guard), builds `sink, self._published = build_publish_sink(node)` (the SINGLE publish path, D-05 — inlines nothing), and constructs `Replayer(items, sink, rate=, loop=)`. The six controls forward straight to the pure scheduler; the rate edit's `returnPressed` parses once and calls `set_rate` (`ValueError` → teaching status); a `Scrubber.seeked(fraction)` maps to `replayer.seek(int(fraction * bag_span_ns))` (seek the only position-setter). `Replayer.run()` (BLOCKING) runs on a `QThread` worker; Play/Step/seek guarded by `_drive_running()` (WR-06 / Pitfall 7, Pause allowed). After `run()` returns, a UI-thread slot pushes `position_fraction` onto the scrubber and reports the published count at `State.DONE`. `_load_markers()` lazily reads `list_events(bag)` + `load_items(bag)` and overlays jump-to-event markers (any read failure leaves markers empty). `closeEvent` stops the drive thread + tears down only our own context (WR-05).
- **main_window.py** — constructs `self.record_panel` / `self.replay_panel` and appends `("record", "Record", …, True)` + `("replay", "Replay", …, True)` to the registry in the full TUI order inspect/query/tf/record/replay. The existing Plan-16-01 capability-gate loop disables a live row's nav item + sets the teaching tooltip when `not self._ros_available` — no gate-logic change needed; the `panels` accessor exposes the live widgets for the five-panel SC1 test.
- **tests/test_desktop.py** — `test_app_has_five_panels` (SC1: all five panels + five nav rows present) and `test_live_panels_disabled_without_ros` (SC2/SC4: record/replay nav disabled under monkeypatched `ros_available=False` while inspect/query/tf stay enabled, and offline inspect still renders real rows without ROS).
- **tests/test_desktop_live.py** — mirrors `tests/test_gui_live.py`: `rclpy = pytest.importorskip("rclpy")` + `pytestmark = pytest.mark.live` + the offscreen/sys.path harness. `test_record_panel_discovers_external_topic` drives the real discovery worker against an external `/telemetry` publisher subprocess and asserts the checklist fills; `test_replay_panel_publishes_external_subscriber_receives` presses Play (real `build_publish_sink` + `Replayer.run()` on the worker) with an external `/imu` subscriber up first and asserts the panel reaches a published/Done terminal status. `qtbot.waitUntil` is the pytest-qt analog of awaiting the Textual worker.

## Verification

- `PYTHONPATH="" uv run ruff check .` — All checks passed. PASS
- `PYTHONPATH="" uv run python -c "import rosbagger_desktop.panels.record_panel; import rosbagger_desktop.widgets.scrubber; assert no rclpy/rosbag2_py in sys.modules"` — record/scrubber import ROS-free OK. PASS
- `PYTHONPATH="" uv run python -c "import rosbagger_desktop.panels.replay_panel; assert no rclpy/rosbag2_py in sys.modules"` — replay import ROS-free OK. PASS
- `grep`: `replay_panel.py` has no top-level `from rosbagger_replay` / `from rosbagger_core.events` / `import rclpy`; contains `build_publish_sink`, `Replayer`, `load_items`, `list_events`. `record_panel.py` has no top-level `from rosbagger_record`. `workers.py` has no `class X(QThread)` worker. PASS
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop_live.py tests/test_gui_live.py -rs --no-cov` — 2 skipped (both live files COLLECTED-AND-SKIPPED by `importorskip(rclpy)`, no unknown-marker warning). PASS
- Qt-free + desktop-cli guards (`-k "pyside6 or desktop"`) — 2 passed. PASS
- **Full phase gate:** `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` — **475 passed, 4 skipped, 97.37% coverage** (≥80% gate held; +2 desktop tests over Plan 02, the 2 new live tests skipped under the ROS-free venv). PASS

## Success Criteria

- **SC1** — all five panels registered in the QMainWindow nav (proven by `test_app_has_five_panels`: five panels reachable via the accessor + five nav rows). MET.
- **SC2** — full five-panel parity with the TUI: Record (discover + bounded record) and Replay (six controls + scrubber + markers) reach feature parity reusing the live module APIs verbatim. MET.
- **SC4** — `record_panel` / `replay_panel` / `scrubber` modules pull no `rclpy` / `rosbag2_py` at import; the Qt-free + ROS-free guards stay green. MET.
- **SC5** — headless tests pass at ≥80% coverage (97.37%, the rosbagger_core+bagq gate held); live record/replay covered on the `@pytest.mark.live` lane (collected-and-skipped offline). MET.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan-01/02 nav-count assertions hardcoded `== 3` and would fail once record/replay register**
- **Found during:** Task 3
- **Issue:** `test_app_has_offline_panels` and `test_capability_gate_keeps_offline_panels_enabled` asserted `window._nav.count() == 3`. Registering the Record + Replay panels (the explicit purpose of this plan) makes the observable count 5, so those two prior-plan tests would break — a regression in the same file the plan instructs Task 3 to extend (the identical pattern Plan 16-02 fixed when Query registered).
- **Fix:** Updated both assertions to `== 5`, and narrowed each enabled-row loop to the OFFLINE trio (inspect/query/tf) via a registry-derived index map — because with ROS forced absent the live record/replay rows are now correctly disabled by the gate, so a blanket "all rows enabled" assertion no longer holds. The detailed live-row gating is asserted by the new `test_live_panels_disabled_without_ros`. No prior-plan behavior was changed.
- **Files modified:** tests/test_desktop.py
- **Commit:** df7c184

## TDD Gate Compliance

Plan type is `execute` (not `tdd`); no task carried `tdd="true"`. The RED/GREEN gate sequence does not apply. Source (Tasks 1/2) was gated before commit by ruff + the per-module ROS-free import assertions + the grep acceptance criteria; the behavioral proof (Task 3) is the headless pytest-qt five-panel + capability-gate tests (offline) plus the live-marked record/replay lane (ROS-sourced).

## Known Stubs

None. Both live panels drive the real `rosbagger_record` / `rosbagger_replay` / `build_publish_sink` / `list_events` APIs; the only intentionally-deferred work is the live-lane execution itself, which requires a sourced ROS 2 environment (the documented `@pytest.mark.live` recipe) and is COLLECTED-AND-SKIPPED in the offline CI by design.

## Notes

- **PHASE 16 COMPLETE (3/3):** the native PySide6 desktop cockpit reaches full five-panel parity with the Textual TUI (inspect/query/tf offline + record/replay live), reusing the shipped module APIs verbatim, with the offline import graph kept both ROS-free and Qt-free.
- **Live-lane recipe (the sole human follow-up to exercise record/replay on real ROS):** `source /opt/ros/humble/setup.bash && PYTHONPATH="packages/rosbagger-desktop/src:packages/rosbagger-replay/src:packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_desktop_live.py -m live -v`.

## Self-Check: PASSED

All 6 created files present on disk (workers.py, widgets/__init__.py, widgets/scrubber.py, panels/record_panel.py, panels/replay_panel.py, tests/test_desktop_live.py); all 3 task commits (41a5109, c3a04d9, df7c184) present in git history.
