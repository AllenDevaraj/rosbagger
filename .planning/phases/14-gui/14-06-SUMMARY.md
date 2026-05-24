---
phase: 14-gui
plan: 06
subsystem: ui
tags: [textual, tui, replay, transport, scrubber, threads, workers, live, offline-invariant]

# Dependency graph
requires:
  - phase: 14-gui (plan 14-01)
    provides: rosbagger_replay.build_publish_sink(node) -> (sink, published) — the SINGLE shared rclpy publish path the panel drives (D-09a), re-exported lazily behind _require_ros
  - phase: 14-gui (plan 14-02)
    provides: RosbaggerApp shell — the tier-1 ros_available capability gate (D-03/D-04) that disables this live panel when rclpy is absent, the shared single-open RosbagsReader (D-02, .paths is the bag source), the ContentSwitcher panel registry, and the replay STUB panel this plan fills
  - phase: 13-replay
    provides: the pure Replayer transport state machine (play/pause/step/set_rate/seek/loop + run() + State/cursor introspection) and the ROS-free load_items raw-CDR source seam
  - phase: 11-events
    provides: rosbagger_core.events.list_events(bag) — the event sidecar reader feeding jump-to-event markers (offline-safe, pyarrow imported lazily)
provides:
  - Scrubber(Widget) — a reusable custom timeline widget (no built-in slider): a reactive position playhead + a (fraction,label) event-marker overlay; on_click posts Scrubber.Seeked(fraction) with nearest-marker snap, holding ZERO transport/module logic
  - ReplayPanel(Widget) — the live thin face over rosbagger_replay: builds its OWN rclpy context+node + the SHARED build_publish_sink, drives the pure Replayer.run() in a @work(thread=True) worker with the six transport controls, a position-reflecting scrubber that seeks, and event-sidecar jump markers — no duplicated publish path, offline-clean import graph
affects: [14-gui plan 14-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Custom scrubber widget (no textual-slider dep): a Widget rendering a bar + reactive position playhead + event-marker overlay that emits ONLY a click fraction (Scrubber.Seeked Message) — the panel owns the fraction -> seek(int(fraction * bag_span_ns)) mapping, so the widget stays pure presentation/input (zero Replayer/seek/module code; grep-gated)"
    - "Live replay panel: drives the PURE Replayer over the SHARED build_publish_sink (D-09a) in the panel's OWN rclpy context (WR-04 re-entrant-safe — init only the context we created, shut down only that one); Replayer.run() (the blocking drive loop) runs in @work(exclusive=True, thread=True), transport methods (play/pause/step/set_rate/seek/loop) fire from UI handlers between run segments, cursor reflected on the scrubber via call_from_thread (Pitfall 1 / T-14-06-01)"
    - "Single production publish path held in the GUI: the panel imports build_publish_sink (Plan 14-01) and inlines NONE of the publisher-build / message-deserialise mechanics — acceptance grep-gates create_publisher/deserialize_message == 0 (T-14-06-02 / D-09a)"
    - "Offline-import invariant held in a LIVE panel: rosbagger_replay/rclpy/rosbagger_core.events imported INSIDE worker/method bodies only; importing rosbagger_gui.panels.replay (and .widgets.scrubber) leaks no rclpy/rosbag2_py (fresh-interpreter scan)"

key-files:
  created:
    - packages/rosbagger-gui/src/rosbagger_gui/widgets/__init__.py
    - packages/rosbagger-gui/src/rosbagger_gui/widgets/scrubber.py
  modified:
    - packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py
    - packages/rosbagger-gui/src/rosbagger_gui/app.tcss

key-decisions:
  - "Custom Scrubber(Widget) over a third-party slider (14-RESEARCH Alternatives Considered): keeps deps to textual only. It renders a one-row bar (─) with a playhead glyph (▮) at round(position*(width-1)) and event markers (▼) at each marker fraction; the playhead overwrites a colliding marker cell. The widget emits ONLY a click fraction via a Scrubber.Seeked Message (with a nearest-marker snap within 0.02 so jump-to-event lands exact) — it holds NO Replayer/seek/module logic; the panel maps fraction -> seek."
  - "Panel owns its OWN rclpy context (D-09a / WR-04): _ensure_transport() builds it lazily on first Play/Step/Seek, mirroring replay.py's created_ctx = not rclpy.ok() discipline — init only if we created it, and _teardown_transport (on_unmount) destroys the node + shuts down only that same context (best-effort, WR-05). The Replayer/replay design is re-entrant-context-safe (Phase 13 WR-04), so a panel-owned long-lived context coexists with the CLI's run-to-completion context."
  - "Bag source is the App's shared reader (D-02): _bag_path() reads self.app.reader.paths[0] (callable before open, returns a copy) rather than re-deriving a path — the panel sits on the single shared reader the shell owns, never opening a second one."
  - "Markers source = list_events(bag) (the events sidecar, D-09) mapped via the 14-RESEARCH Code Example 4 formula (t_start_ns - bag_start_ns)/max(1, span); bag_start_ns/span come from the SAME load_items the transport uses so the marker fractions line up exactly with the scrubber's seek mapping. A missing/empty sidecar yields zero markers (an empty fixed-schema table), and ANY sidecar read failure leaves markers empty — markers are an aid, not a gate, so they never crash the panel."
  - "Scheduler edge behavior is consumed, not re-implemented (Pitfall 6 / WR-02 / T-14-06-04): State.DONE / cursor==len(items) is treated as end-of-track (a seek-past-end lands a clean DONE, no IndexError), and a loop wrap rewinds to index 0 (NOT the last seek) — both per the pure Replayer contract. The drive worker reports the published count from the shared build_publish_sink published[\"n\"] dict on DONE."

requirements-completed: [GUI-01]

# Metrics
duration: ~5min
completed: 2026-05-24
---

# Phase 14 Plan 06: Live Replay Panel + Custom Scrubber Summary

**ReplayPanel is now the live thin face over `rosbagger_replay`: a custom `Scrubber` timeline widget (reactive playhead + event-marker overlay, click→fraction with marker snap) plus a panel that builds its OWN rclpy context + the SHARED `build_publish_sink` (D-09a — single publish path), drives the PURE `Replayer.run()` in a `@work(thread=True)` worker with all six transport controls (play/pause/step/set_rate/seek/loop), reflects the cursor onto the scrubber via `call_from_thread`, and overlays jump-to-event markers from `list_events(bag)` — with an offline-import graph that leaks no `rclpy`/`rosbag2_py`.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-24T06:40:15Z
- **Completed:** 2026-05-24T06:44:47Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **Task 1 — Custom `Scrubber` Widget (D-09):** new `rosbagger_gui/widgets` package. `Scrubber(Widget)` renders a one-row timeline bar with a reactive `position` (0..1) playhead glyph and an overlaid set of event markers set via `set_markers([(fraction, label), ...])`. `on_click` computes the click's fraction along the bar width and posts a `Scrubber.Seeked(fraction)` message — with a nearest-marker snap (within `0.02`) so a jump-to-event click lands exactly on the event time. The widget holds ZERO transport/module logic: grep-gated `Replayer|.seek( == 0`, `rosbagger == 0` — it only reports a fraction and reflects the playhead; the panel owns the `fraction -> seek` mapping. Scrubber CSS (a one-line `$primary` bar) added to `app.tcss`. Imports cleanly offline (`import rosbagger_gui.widgets.scrubber` exits 0).
- **Task 2 — `ReplayPanel` over the pure Replayer + shared sink (D-09/D-09a):** filled the 14-02 `Static` stub with a `ReplayPanel(Widget)` composing a `replay-status` `Static`, the `Scrubber`, Play/Pause/Step `Button`s, a rate `Input` (`set_rate`), and a loop `Switch` (`replayer.loop`). `_ensure_transport()` lazily builds the panel's OWN rclpy context + node (the WR-04 `created_ctx = not rclpy.ok()` discipline), the SHARED `sink, published = build_publish_sink(node)` (no inlined publish mechanics — grep-gated `create_publisher|deserialize_message == 0`), `load_items(bag)`, and the pure `Replayer`. `Replayer.run()` runs in a `@work(exclusive=True, thread=True)` worker (Pitfall 1); Play (re)starts the worker, Pause/Step set the scheduler state (Step runs the worker once, one-then-pause), `set_rate`/`loop` forward to the scheduler, and a `Scrubber.Seeked` fraction maps to `replayer.seek(int(fraction * bag_span_ns))`. The worker pushes the cursor fraction onto the scrubber playhead via `call_from_thread` and reports the published count on `State.DONE`. Jump-to-event markers come from a lazy `list_events(bag)` mapped via the Code Example 4 formula. Every `rosbagger_replay`/`rclpy`/`rosbagger_core.events` import is inside a worker/method body — the fresh-interpreter scan leaks no `rclpy`/`rosbag2_py`.
- **Thread-worker discipline (T-14-06-01 / Pitfall 1):** the only blocking ROS path (`Replayer.run()`) runs in the `@work(thread=True)` worker; every widget update from the worker (playhead position, terminal status) goes through `self.app.call_from_thread` — the event loop never blocks.
- **Single publish path held in the GUI (T-14-06-02 / D-09a):** the panel drives the SHARED `build_publish_sink` (Plan 14-01) and inlines NO `create_publisher`/`deserialize_message` mechanics — there is exactly one production publish path.
- **Offline invariant held in a live panel (T-14-06-03):** module-top ROS-import scan is 0; `import rosbagger_gui.panels.replay` (and `.widgets.scrubber`) leaks none of `rclpy`/`rosbag2_py`. Verified headlessly: the panel mounts with all seven widgets composing, the scrubber accepts markers + position and renders, and on this `PYTHONPATH=""` lane `ros_available` is `False` so the panel is correctly gated (`disabled=True`, the teaching-hint state).
- **No regression:** the full offline suite stays green — 460 passed, 2 skipped, 97.37% (unchanged baseline; the GUI is intentionally outside the coverage gate per Phase 13 D-12). `ruff check` clean on the whole gui src; `ruff format --check` clean on both files this plan created/modified.

## Task Commits

Each task was committed atomically:

1. **Task 1: Custom Scrubber widget — reactive playhead + event-marker overlay + click→fraction** — `90930b4` (feat)
2. **Task 2: ReplayPanel — six transport controls over the pure Replayer + shared sink in a thread worker** — `604051b` (feat)

## Files Created/Modified

- `packages/rosbagger-gui/src/rosbagger_gui/widgets/__init__.py` — new widgets package; re-exports `Scrubber` (pure textual/stdlib — no ROS).
- `packages/rosbagger-gui/src/rosbagger_gui/widgets/scrubber.py` — `Scrubber(Widget)`: reactive `position` playhead + `(fraction,label)` event-marker overlay; `on_click` → `Scrubber.Seeked(fraction)` with nearest-marker snap; zero transport/module logic.
- `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py` — filled the 14-02 stub: `ReplayPanel(Widget)` over `rosbagger_replay` — own rclpy context + SHARED `build_publish_sink`, `Replayer.run()` in a `@work(thread=True)` worker, six controls, scrubber seek, `list_events` jump markers, lazy ROS imports inside worker/method bodies.
- `packages/rosbagger-gui/src/rosbagger_gui/app.tcss` — `Scrubber` (one-row `$primary` bar) + `.replay-controls` styling.

## Decisions Made

- Custom `Scrubber(Widget)` over a third-party slider (14-RESEARCH Alternatives Considered) — keeps deps to textual only; the widget emits only a click fraction (`Scrubber.Seeked`), the panel owns the `fraction -> seek` mapping.
- The panel owns its OWN rclpy context (D-09a / WR-04): built lazily on first Play/Step/Seek (`created_ctx = not rclpy.ok()`), torn down on `on_unmount` (best-effort, only our own context).
- Bag source is the App's shared reader (`self.app.reader.paths[0]`, D-02) — the panel never opens a second reader.
- Markers from `list_events(bag)` mapped via the Code Example 4 formula `(t_start_ns - bag_start_ns)/max(1, span)`; a missing/empty sidecar or any read failure leaves markers empty (an aid, not a gate).
- Scheduler edge behavior is consumed, not re-implemented (Pitfall 6 / WR-02 / T-14-06-04): `State.DONE`/`cursor==len(items)` is end-of-track, a loop wrap rewinds to 0 — per the pure `Replayer` contract.

## Deviations from Plan

None — plan executed as written. Two adjustments worth noting (neither a scope deviation):

- **[Housekeeping — docstring prose reworded for the literal grep gates]** Two acceptance criteria use literal `grep -c` gates that count `Replayer|.seek(`/`rosbagger` (Task 1) and `create_publisher|deserialize_message` (Task 2) as 0 to assert "no transport/module/publish CODE inlined." The first drafts mentioned those tokens in DOCSTRING PROSE (e.g. "the panel inlines NO `create_publisher`/`deserialize_message` mechanics"), tripping the literal grep though there was zero such code. Reworded the prose (e.g. "the publisher-build / message-deserialise mechanics", "the scheduler", "the position jump") so the literal gates pass clean — the criteria's INTENT (single publish path, pure widget) was met from the first draft. This mirrors the same `grep -c` false-positive housekeeping documented in 14-01's SUMMARY.
- **In-task ruff fixes (not deviations):** an I001 import-block sort (merged two `from rosbagger_replay` lines) and an E501 long-line wrap in this plan's own new code, fixed by `ruff check`/`ruff format` before the Task 2 commit.

## Deferred Issues (out of scope)

- `ruff format --check` flags the PRE-EXISTING `panels/inspect.py` and `panels/tf.py` (committed by Plans 14-03/14-04, NOT touched here — no working-tree diff) as "would reformat" on the current ruff version. `ruff check` (lint) is clean across the whole gui src; only the formatter's whitespace pass diverges on those two files. Logged to `.planning/phases/14-gui/deferred-items.md` — out of scope for 14-06 (scope boundary). Fix in a dedicated format pass or when those panels are next edited.

## Threat Mitigations Applied

- **T-14-06-01 (DoS / event-loop block):** `Replayer.run()` runs in `@work(exclusive=True, thread=True)`; transport methods fire from UI handlers between run segments; scrubber updates via `call_from_thread`.
- **T-14-06-02 (Tampering / second publish path):** the panel imports the SHARED `build_publish_sink` (Plan 14-01); acceptance grep-gate confirms no `create_publisher`/`deserialize_message` mechanics are inlined (single production publish path — D-09a).
- **T-14-06-03 (Elevation / ROS import leak):** lazy imports inside worker/method bodies; fresh-interpreter scan confirms `import rosbagger_gui.panels.replay` leaks no `rclpy`/`rosbag2_py`.
- **T-14-06-04 (DoS / seek-past-end / loop-wrap):** `State.DONE`/`cursor==len(items)` treated as end-of-track; a loop wrap rewinds to 0 (WR-02 / Pitfall 6) — handled per the scheduler contract, not re-implemented.

## Known Stubs

None. The replay stub is now fully filled. Live transport behavior (the actual publish loop, seek, loop-wrap, DONE) is exercised by the `live`-marked GUI integration test in Plan 14-07 (ROS-sourced lane, `importorskip("rclpy")`, skipped in offline CI); offline this is proven structurally (mount + compose + the scrubber widget logic + the offline-clean import graph).

## User Setup Required

None for the offline import graph + the panel mount. To ACTUALLY replay, the live panel needs a sourced ROS 2 environment (it surfaces the teaching hint otherwise) and a bag loaded into the App's shared reader. Event markers additionally require a `<bag>.events.parquet` sidecar (none ⇒ no markers, never an error).

## Next Phase Readiness

- Both live panels are now filled (record in 14-05, replay here). Plan 14-07 adds the headless App tests + the formal offline-import-guard test for the GUI graph and the `live`-marked record/replay integration tests (ROS-sourced lane) that exercise the actual transport loop + seek + Stop.
- No blockers. Offline-import invariant for the replay panel + scrubber verified intact; the full offline suite stays green (460 passed, 2 skipped, 97.37%).

## Self-Check: PASSED

- FOUND: packages/rosbagger-gui/src/rosbagger_gui/widgets/__init__.py
- FOUND: packages/rosbagger-gui/src/rosbagger_gui/widgets/scrubber.py
- FOUND: packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py
- FOUND: packages/rosbagger-gui/src/rosbagger_gui/app.tcss
- FOUND: .planning/phases/14-gui/14-06-SUMMARY.md
- FOUND commit: 90930b4 (Task 1)
- FOUND commit: 604051b (Task 2)
- Imports clean + offline-leak scan green; headless mount composes all seven widgets; full offline suite + ruff (lint) green.

---
*Phase: 14-gui*
*Completed: 2026-05-24*
