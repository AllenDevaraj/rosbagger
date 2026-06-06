# 23-01 SUMMARY — Rerun live-mirror fix

**Status:** Complete · **Requirement:** RR-FIX · **Date:** 2026-06-06

## What shipped

The Rerun live mirror now works **regardless of toggle order** (Open-in-Rerun before OR after Play),
fixing the "image topic doesn't play if you open Rerun then press Play" bug.

### Root cause (confirmed)
`open_viewer()` returned the instant `rec.spawn()` was called; the viewer's gRPC server takes
~100–500 ms to bind. The first logged items (a large **Image** first) streamed into a not-yet-connected
sink and were dropped. The sink swallowed the error (`logged['errors'] += 1`) and `_open_rerun`
discarded the count (`self._rerun_sink, _ = …`) — zero feedback. Play-first only "worked" because the
stream had settled by the time you toggled.

### Fix
1. **Viewer-readiness gate** (`session.py`): confirmed against the installed **rerun-sdk 0.32.2**
   (`spawn(port=9876, connect=True, …)`). `open_viewer(…, ready_timeout=5.0)` now passes the port to
   `spawn` explicitly and calls a new `_wait_viewer_ready(rec, port, timeout)` that polls a TCP connect
   to `127.0.0.1:9876` until it accepts (or the bounded timeout elapses), then `rec.flush()`. It
   **never raises** and is strictly bounded (a viewer that never comes up degrades to the old behavior,
   never hangs). Save mode skips it entirely (tests don't block).
2. **Off the UI thread** (`replay_panel.py`): because the readiness gate can block ~1 s, `_open_rerun`
   now spawns the viewer on a kept-ref `BlockingWorker` (mirroring `_install_rerun`; CR-02/260530-w4k
   join-before-drop). New handlers `_on_rerun_opened`/`_on_rerun_open_failed`/`_on_rerun_open_finished`;
   `closeEvent` stops the open thread.
3. **t0 anchored to bag start**: `_ensure_transport` records `self._bag_start_ns = items[0].t_ns`;
   `_open_rerun` runs `_ensure_transport()` first, then `build_rerun_sink(rec, t0_ns=self._bag_start_ns)`
   so the `bag_time` timeline is identical whichever order you open Rerun.
4. **Errors surfaced**: `self._rerun_logged` is kept (not discarded); `_on_drive_done` appends
   "Rerun: N message(s) could not be logged." when `logged['errors'] > 0`.

## Files
- `packages/rosbagger-rerun/src/rosbagger_rerun/session.py` — `_VIEWER_GRPC_PORT`, `ready_timeout`, `_wait_viewer_ready`.
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py` — `_bag_start_ns`, off-thread `_open_rerun` + handlers, surfaced errors, closeEvent.
- `tests/test_rerun_unit.py` — readiness bounded/never-raises + save-mode-skips-readiness + spawn-port assertions.
- `tests/test_desktop.py` — off-thread open anchors `t0_ns=bag_start` (kept `logged`), Done status surfaces drop count.

## Deviation
The plan suggested an offline `test_build_rerun_sink_t0_anchor` in `test_rerun_unit.py`, but
`build_rerun_sink` imports `rclpy` (deserialize) at call time → not offline-runnable. Instead the
**t0 anchoring is proven at the desktop wiring layer** (`test_replay_rerun_open_anchors_t0_off_thread`,
offline, asserts `_open_rerun` passes `t0_ns=self._bag_start_ns` to a monkeypatched `build_rerun_sink`).
The real deserialize/timeline behavior remains covered by the existing live mirror `.rrd` lane (22-03).

## Verification
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py tests/test_rerun_unit.py -q --no-cov` → 84 passed.
- Full offline suite: **579 passed, 6 skipped, coverage 88.19%** (≥80%).
- ruff check + format clean; `import rosbagger_rerun.session` and `import rosbagger_desktop.panels.replay_panel` stay rerun-free AND rclpy-free.
- **Needs user sign-off (live + display):** Open in Rerun → Play (Rerun-first order) shows the Image topic; status shows no drop errors.
