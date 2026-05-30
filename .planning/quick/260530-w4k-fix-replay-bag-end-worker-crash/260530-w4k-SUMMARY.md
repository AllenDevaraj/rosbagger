---
quick_id: 260530-w4k
slug: fix-replay-bag-end-worker-crash
date: 2026-05-30
status: complete
commit: b6ab97b
---

# Quick Task 260530-w4k — Summary

## What changed

Fixed the **bag-end GUI crash** (user: "it auto crashed once the bag ended"). The whole
desktop process died with `QObject: shared QObject was deleted directly. The program is
malformed and may crash.` when a bag reached the end of the track.

- `panels/replay_panel.py` — `_on_drive_finished`: capture the drive thread, clear the thread
  ref, then **`stop_thread(thread)` (quit+wait) to JOIN the worker thread before dropping
  `self._drive_worker`**. `_on_install_finished`: same join (same parentless-worker pattern).
- `tests/test_desktop.py` —
  - new `test_replay_drive_to_done_joins_thread_before_clearing_worker`: a fake replayer whose
    `run()` reaches `State.DONE`; drives the REAL worker/thread; spies on `stop_thread` to assert
    the join happens during `_on_drive_finished`; asserts refs cleared + "Done" status.
  - `test_replay_panel_close_after_finished_run_is_safe`: the `object()` stand-in `_drive_thread`
    became a real unstarted `QThread` (the join no-ops on a not-running thread; a bare object has
    no `isRunning()`).

## Root cause

`self._drive_worker` is a `BlockingWorker` — a **parentless** `QObject` (it must be parentless to
be `moveToThread`'d), so shiboken hands its lifetime to **Python**. At end-of-track,
`_on_drive_finished` (UI thread) set `self._drive_worker = None`, which deletes the C++ object
**from the UI thread**. But the worker thread's event loop is still alive at that instant
(`worker.finished` fired, but `thread.quit` is a *queued* teardown), so the UI-thread deletion
**races `worker.deleteLater()` on the worker thread** — a cross-thread use-after-free /
double-free. Independent of the Rerun mirror (the `h2 protocol error` from Rerun was downstream:
its viewer lost the gRPC link as the GUI process died).

Joining the thread (`quit()`+`wait()`, already finished so immediate) makes it provably dead
before the worker ref is dropped, so nothing can race the deletion.

## Verification

| Check | Result |
|-------|--------|
| New + related teardown tests | **4 passed** |
| Full offline suite | **571 passed, 6 skipped** (was 570; +1 regression) |
| Coverage gate | **88%** (≥80%; replay_panel.py 78%) |
| `ruff check` / `format --check` | clean |
| Manual faithful repro (`/tmp/repro3.py`, real `QApplication.exec()`) | **0 crashes / 120 runs** with the join vs **~43%** (single bag-end) / **100%** (replay-again ×8) before |

## Notes

- Reproduced offline with NO ROS: the `Replayer` is generic over any `.t_ns` object, so the real
  production drive/teardown runs against fake items + a no-op sink.
- Composes with 260530-2iv (pending-action replay) and 260530-5cg (close-while-playing pause):
  all three touch the drive-thread lifecycle; the join slots in before the deferred-resume.
- **Known follow-up (not in scope):** the inspect/query/tf/record panels use the same
  `run_on_thread` + clear-worker-ref-in-`on_finished` pattern, so they share the latent race
  (far less likely to trigger — short-lived workers). Worth a centralized fix later.
