---
quick_id: 260530-2iv
slug: fix-replay-pause-play-already-playing-ra
date: 2026-05-30
status: complete
commit: b5020e7
---

# Quick Task 260530-2iv — Summary

## What changed

Fixed the desktop Replay **pause → play "Already playing"** race the user hit.

- `panels/replay_panel.py`:
  - New `_genuinely_playing()` — the guard's source of truth is now the **Replayer STATE**, not the
    zombie thread: returns True only when a worker runs AND `replayer.state is State.PLAYING`.
  - `_play` / `_step`: reject with "Already playing"/"Pause before stepping" only on a genuine
    double-play; when a **post-pause worker is still finishing** (state PAUSED, thread still
    `isRunning()`), set `self._pending_action = "play"|"step"` and return — no rejection.
  - `_on_drive_finished`: after clearing the thread/worker refs, replays a `_pending_action` (now
    `_drive_running()` is False, so it resumes cleanly from the held cursor).
  - `_pause`: clears `_pending_action` (a pause cancels a deferred play/step).
  - `__init__`: added `self._pending_action`.
- `tests/test_desktop.py`: `test_replay_pause_then_immediate_play_resumes` — fake replayer whose
  `run()` blocks until `pause()`; Play → Pause → IMMEDIATE Play asserts NO "already playing" and
  that the deferred resume restarts the drive.

## Root cause

`run()` returns on pause (proven by a threaded scheduler probe), and the worker's `finished`
signal clears `self._drive_thread` **asynchronously** on the UI thread. Between the pause and that
clear, `_drive_running()` is True while the Replayer is already PAUSED — a pause-then-play clicks
in that window, and the old guard (`if self._drive_running(): reject`) wrongly treated the RESUME
as a double-play. Reproduced deterministically before the fix.

## Verification

| Check | Result |
|-------|--------|
| New regression + replay/rerun desktop tests | **23 passed** |
| Full offline suite | **566 passed, 6 skipped** (was 565; +1 regression) |
| Coverage gate | **87%** (≥80%; replay_panel.py 74%→77%) |
| `ruff check` / `format --check` | clean |

## Out of scope (flagged to user)

- `closeEvent` calls `stop_thread` WITHOUT first pausing the Replayer, so closing the window while
  a long bag is mid-play can block `QThread.wait()` until the bag finishes — a latent close-hang,
  distinct from this race. Not fixed here; will offer it as a follow-up.
