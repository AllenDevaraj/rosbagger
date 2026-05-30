---
quick_id: 260530-5cg
slug: fix-replay-close-while-playing-hang
date: 2026-05-30
status: complete
commit: d6c0d6c
---

# Quick Task 260530-5cg — Summary

## What changed

Fixed the latent **close-while-playing hang** (flagged in 260530-2iv).

- `panels/replay_panel.py` — `closeEvent` now, BEFORE `stop_thread(self._drive_thread)`:
  - clears `self._pending_action` (so the 260530-2iv deferred-resume can't rebuild a transport
    during teardown), and
  - pauses the Replayer (`self._replayer.pause()` under `contextlib.suppress`) so the blocking
    `Replayer.run()` returns promptly and `QThread.wait()` no longer blocks until the bag ends.
- `tests/test_desktop.py` — `test_replay_close_while_playing_pauses_and_stops`: a fake replayer
  whose `run()` blocks until `pause()`; start the drive, `panel.close()`, assert the replayer was
  paused and the drive stopped (passes in ~0.4s — proves no wait-for-run() hang).

## Root cause

`stop_thread` does `QThread.quit()` + `wait()`. `quit()` asks the thread's EVENT LOOP to exit, but
the worker is inside the blocking `Replayer.run()` loop (which never reads that event loop), so
`wait()` blocks until `run()` returns on its own — and it only returns when state != PLAYING. With
no pause in `closeEvent`, closing mid-play of a long bag froze the app until playback finished.

## Verification

| Check | Result |
|-------|--------|
| Close-hang regression + replay/pause/rerun tests | **25 passed** |
| Full offline suite | **567 passed, 6 skipped** (was 566; +1 regression) |
| Coverage gate | **88%** (≥80%; replay_panel.py 77%→78%) |
| `ruff check` / `format --check` | clean |

## Notes

- Composes with 260530-2iv (the pause→play race fix): both touch the transport lifecycle in
  `replay_panel.py`; clearing `_pending_action` on close is the seam between them.
