---
phase: 18-replay-live-scrubbing-and-thread-safe-transport
plan: 02
status: complete
subsystem: rosbagger-desktop (Replay panel)
requirements: [REP-02]
tags: [replay, desktop, pyside6, live-scrub, qtimer, thin-face]
provides:
  - "Replay panel scrubber playhead tracks playback in real time (QTimer poll of position_fraction)"
  - "Drag-while-playing seek + live rate/loop changes (no 'Pause before …' rejection); controls stay enabled during a drive"
  - "Honest backward-drag status ('Seeking to N% — resuming forward.') — jump + forward republish, never a rewind claim"
depends_on: [18-01]
affects:
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
  - tests/test_desktop.py
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
    - tests/test_desktop.py
decisions:
  - "Live playhead via a UI-thread QTimer polling position_fraction (RESEARCH §3b) — no cross-thread signal plumbing; the cursor read is atomic and the Scrubber already suppresses emit on a programmatic set_position, so no Scrubber change was needed."
  - "Removed the three _drive_running() rejection branches (_on_seeked/_apply_rate/_apply_loop) and the rate/loop setEnabled(False) in _start_drive — all are safe now that 18-01 made the Replayer setters lock-guarded. The controls stay enabled for the whole drive."
  - "Backward-seek detection compares the requested fraction to the live position_fraction BEFORE the jump; backward => 'resuming forward' copy (SC3 honesty). Forward keeps the plain 'Seeked to N%' message."
  - "Rewrote the two existing tests that encoded the old behavior (close_after_finished_run: drop the re-enable assertions, assert the timer stops; the CR-02 guard test: inverted to assert live application + no 'Pause before' status). Added backward-seek-status + controls-stay-enabled tests."
metrics:
  duration: ~25min (executed inline after the Wave-1 executor's session limit; same low-token approach)
  completed: 2026-05-29
---

# Phase 18 Plan 02: Desktop Live Scrubbing — Summary

Turned the Replay tab into a real playback surface on top of 18-01's thread-safe `Replayer` (REP-02): the scrubber **playhead tracks playback in real time**, and the user can **drag the scrubber / change rate / toggle loop WHILE it plays** — the "drag back and forth like a playback system" the user asked for. A backward drag is honestly reported as a forward resume (jump + forward republish, not a visual rewind — the RViz-fidelity work is Phase 20). The panel stays a thin face: module top is still PySide6 + stdlib + local only.

## What changed

### `panels/replay_panel.py`
- **Live playhead (SC2).** Added a UI-thread `QTimer` (`_position_timer`, 60ms) in `__init__`, wired to `_update_position`. Started in `_start_drive`; stopped in `_on_drive_finished` (every drive outcome) AND `closeEvent`. While the drive worker runs `Replayer.run()` on its thread, the timer polls the now-thread-safe `position_fraction` → `scrubber.set_position`, so the playhead advances during playback (previously it only updated at seek and at DONE).
- **Mid-play control (SC2).** Removed the `_drive_running()` rejection branches from `_on_seeked`, `_apply_rate`, `_apply_loop`, and removed the `setEnabled(False)` of the rate input + loop checkbox in `_start_drive` (and the matching re-enable in `_on_drive_finished`). 18-01's lock-guarded setters make these safe; the controls stay enabled throughout.
- **Backward-seek honesty (SC3).** `_on_seeked` reads `position_fraction` before the jump; when the requested fraction is lower (a backward drag) it sets `"Seeking to N% — resuming forward."`, otherwise the plain `"Seeked to N% of the bag."`. Never claims reverse playback.

### `tests/test_desktop.py`
- Rewrote `test_replay_panel_close_after_finished_run_is_safe`: dropped the re-enable assertions (Phase 18 never disables the controls), assert the playhead timer stops on finish, and that rate/loop remain enabled.
- Replaced `test_replay_rate_loop_guarded_while_drive_running` with `test_replay_rate_loop_seek_live_while_drive_running`: with `_drive_running()` forced True, `_apply_rate`/`_apply_loop`/`_on_seeked` now DO reach the replayer and show no "Pause before …" status (the inverse of the old guard).
- Added `test_replay_backward_seek_status_says_resuming_forward` (SC3) and `test_replay_controls_stay_enabled_during_drive` (SC2; stubs `run_on_thread` so no real thread/ROS is needed, asserts controls enabled + timer active after `_start_drive`).

## Deviations from plan
None to the design. The Scrubber needed no change — RESEARCH §3b's "add a suppression guard if needed" was a no-op because `_suppress_emit` already existed. Execution-wise, this plan was done inline (like 18-01) rather than via a spawned executor, after Wave 1's executor hit a session limit; same TDD + atomic-commit discipline.

## Verification
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py -k "replay_rate_loop_seek_live or backward_seek_status or controls_stay_enabled or close_after_finished"` → **5 passed**.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → **20 passed** (panel module top stays ROS-free AND Qt-free; offline graph intact).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **514 passed, 4 skipped; 86.87% coverage** (≥80% gate).
- `ruff check` + `ruff format --check` on both files → clean.

## Human end-to-end (post-merge, not a CI gate)
`uv run --with pyyaml rosbagger-desktop ~/Desktop/rosbag`, press Play, drag the scrubber while it plays — the playhead should track, and dragging should seek live (no "Pause before seeking"). Confirm in another terminal with `ros2 topic echo /cmd_vel`, and open RViz2 (Image on `/camera/color/image_raw`) to watch the forward resume after a backward drag.

## Self-Check: PASSED
- `panels/replay_panel.py` (QTimer live playhead; guards removed; controls stay enabled; backward-seek status) — FOUND
- `tests/test_desktop.py` (2 rewritten + 2 new replay tests) — FOUND
- Commit `bf9f8c7` (feat 18-02) — FOUND
