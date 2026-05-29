# Phase 19 Context: Replay Snippet Loop & Advanced Controls Panel

**Phase:** 19 (REP-03) · **Milestone:** v0.5 — Replay Playback System
**Source:** user ask while testing the desktop replay — "once I have paused somewhere I should be able to replay a small snippet of the entire bag on loop" + "there should be a tab on the side for the replay tab." Decisions locked via AskUserQuestion. Builds on Phase 18 (thread-safe live transport). Full Goal + 4 Success Criteria live in `ROADMAP.md` (Phase 19 block).

## Locked decisions (from AskUserQuestion)

- **Snippet loop region** markable BOTH ways: **draggable In/Out handles on the timeline AND Set-In / Set-Out buttons** that snap to the current playhead. (User chose "Both handles + buttons".)
- **Side sub-panel:** a **collapsible side/sub-panel inside the Replay tab** holds the advanced controls (region-loop toggle + Set-In/Set-Out). The "tab on the side" the user asked for.

## Scope

**In:** (1) an in/out **region loop** `[t_in, t_out]` in the pure `Replayer` — distinct from the existing whole-bag `loop` (which rewinds to index 0): when region-loop is on, playback wraps from `t_out` back to `t_in`; thread-safe (consistent with 18-01's lock pattern). (2) `Scrubber` gains **two draggable In/Out handles** + a shaded region paint + a `region_changed(in, out)` signal + programmatic `set_loop_region`/`clear_loop_region`. (3) a **collapsible advanced-controls sub-panel** in the Replay tab with a region-loop toggle + **Set-In / Set-Out buttons** (snap to the live playhead), wired to the scheduler region.

**Out (deferred):** `/clock` + latched/static re-publish on seek → **Phase 20**; CLI parity flags → **Phase 21**; in-app 3D/image viz → permanently out.

## Hard invariants (must not regress)

- Scheduler stays **stdlib-only** (`scheduler.py` imports only `threading`/`time`/`enum`/`collections.abc`); region-loop reuses the 18-01 lock + wake; preserve W3/W4/WR-01/WR-02/Pitfall-6/D-08/step + the Phase-18 thread-safety contract; ALL existing scheduler tests stay green unchanged.
- `rosbagger_replay` no module-top ROS import; offline import graph ROS-free AND Qt-free (`tests/test_offline_guard.py`).
- `Scrubber` + the panel stay **offline/Qt-clean** (PySide6 + stdlib only at module top) and a **thin face** — no analysis/ROS logic.
- **No inline color** — the region shade + handles + sub-panel use the Phase-17 theme tokens / objectName-keyed QSS (extend `theme/qss.py`), never literal hex in the widget/panel.
- Don't break the Phase-18 live scrubbing: the playhead poll, drag-while-playing seek, and rate/loop still work; region controls compose with them.

## Success criteria (from ROADMAP Phase 19)

1. `Replayer` supports a loop region: playing wraps from `t_out` back to `t_in` (NOT index 0) when region-loop is on, and clears cleanly back to whole-bag / no-loop — proven by unit tests (fake clock + recording sink).
2. The `Scrubber` shows a shaded loop region with two draggable In/Out handles, AND Set-In / Set-Out buttons set the region from the current playhead — a headless pytest-qt test drives both paths and asserts the resulting region.
3. Advanced replay controls live in a collapsible side sub-panel inside the Replay tab (region loop + the Set-In/Out controls), themed via Phase-17 tokens with accessible status preserved.
4. Region values survive pause/seek/play cycles; offline/Qt-free guard green; full headless suite passes at ≥80%.

## Testing strategy / host notes

- Scheduler: fast deterministic unit tests (fake clock + recording sink) incl. region wrap, region+bound precedence (DONE wins), region cleared → whole-bag/no-loop unchanged, and a thread-safe set-region-mid-run case.
- Desktop: headless `pytest-qt` under `QT_QPA_PLATFORM=offscreen`. Dual-handle DRAG is awkward to drive via real mouse events offscreen — prefer testing the programmatic `set_loop_region` + the Set-In/Set-Out button paths + the `region_changed` signal, and the handle-hit logic via the widget's internal helpers (or `QTest.mouse*` where feasible).
- Run all tests with `PYTHONPATH=""` on this ROS box. Gate: blended `--cov=rosbagger_core --cov=bagq --cov=rosbagger_desktop --cov-fail-under=80`. Intermittent SIGBUS at exit = Qt-offscreen teardown artifact (re-run), not a failure.
- **Worktrees are disabled** for this uv+ROS workspace (`config.json workflow.use_worktrees=false`) — executors run sequentially on the main tree.

## Suggested plan split (for the planner)

- **19-01** — scheduler region loop (pure, Wave 1): `set_loop_region(in_ns, out_ns)` + `clear_loop_region()` (lock-guarded + wake), `run()` wraps cursor from the item past `t_out` back to the first item at/after `t_in` when region-loop active; precedence — bound guards still win (W4), region wrap replaces the whole-bag end-of-stream branch when active. Unit tests + full Phase-13/18 regression.
- **19-02** — `Scrubber` dual handles (Wave 1, independent): region state + `set_loop_region`/`clear_loop_region`/`region_changed`, paint the shaded region + two handles, mouse handling to drag a handle (near-handle hit test; fall through to playhead seek otherwise; keep in≤out). New QSS tokens for the region/handles. Headless tests.
- **19-03** — panel side sub-panel (Wave 2, depends 19-01+19-02): collapsible advanced sub-panel with a region-loop toggle + Set-In/Set-Out buttons (snap to the live `position_fraction`), wired to the scheduler region + the scrubber; region survives pause/seek/play. Headless tests + phase gate.
