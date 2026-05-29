---
phase: 18-replay-live-scrubbing-and-thread-safe-transport
plan: 01
status: complete
subsystem: rosbagger-replay (pure Replayer scheduler)
requirements: [REP-02]
tags: [replay, scheduler, threading, thread-safety, live-scrub, pure-python]
provides:
  - "Replayer is thread-safe: seek/set_rate/pause/play/step/loop apply WHILE run() executes on another thread, with no data race (cursor-unchanged advance guard)"
  - "DEFAULT pacing wait is interruptible (threading.Event) so a live control takes effect mid-gap; sleep stays injectable (Phase-13 seam intact)"
  - "Synchronous control API unchanged — seek() then read cursor reflects the jump immediately"
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/scheduler.py
  - tests/test_replay_unit.py
key-files:
  created: []
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/scheduler.py
    - tests/test_replay_unit.py
decisions:
  - "Lock + interruptible Event (RESEARCH §3a) chosen over a command-queue: preserves the synchronous control semantics every Phase-13 test relies on, while making run() race-free + responsive."
  - "_wake is CLEARED under the lock at the top of each run() iteration (NOT at the end of _interruptible_sleep). Clearing after the wait let play()'s set persist and short-circuited the first paced gap — caught by test_scheduler_default_sleep_is_interruptible. Clearing under the lock serializes against setters: a setter either is seen in the same-iteration state read, or fires set() after the clear and interrupts the wait."
  - "loop converted from a public attribute to a lock-guarded property keeping the name `loop` — existing `replayer.loop = x` usages and tests are unchanged."
  - "Cursor advance uses `if self._cursor == cursor: self._cursor = cursor + 1` so a concurrent seek that moved the cursor during the publish/wait is NOT clobbered back (the lost-update fix at the old :214-215)."
metrics:
  duration: ~30min (incl. a partial first executor run that hit a session limit after writing the RED tests; completed inline)
  completed: 2026-05-29
---

# Phase 18 Plan 01: Scheduler Thread-Safety — Summary

Made the pure `rosbagger_replay.Replayer` safe to control from another thread **while `run()` is executing**, so Plan 18-02's desktop scrubber can seek / change rate / toggle loop / pause **during playback** with no data race — the foundation of the v0.5 live-scrubbing milestone. The control API stays fully synchronous (a `seek()` issued when not running still updates `cursor` immediately), so every Phase-13 single-threaded test passes unchanged.

## What changed

### `scheduler.py` — thread-safety (RESEARCH §3a)
- `__init__`: added `self._lock = threading.Lock()` and `self._wake = threading.Event()`. `sleep` is now `Callable | None`; when not overridden it binds to the new `_interruptible_sleep` (production gets interruptibility; an injected recording sleep is honored verbatim — T-18-01-C). `loop` is stored as `self._loop`.
- `loop` is now a property; its setter mutates under the lock + sets `_wake` (a live `replayer.loop = x` toggle is race-free against `run()`'s end-of-stream read).
- `_interruptible_sleep(seconds)`: `self._wake.wait(timeout=seconds)` — no clear here (see below).
- `play` / `pause` / `step` / `set_rate` / `seek`: each wraps its mutation in `with self._lock:` and calls `self._wake.set()` so an in-progress pacing wait ends and the command lands promptly.
- `run()` restructured: the lock is held ONLY for the fast state/cursor/rate reads, the pacing-Δt computation, the cursor advance, and the bound/step/loop/DONE transitions — NEVER across `self._sink(...)` (publish) or `self._sleep(...)` (wait). The cursor advance uses the **cursor-unchanged guard** (`if self._cursor == cursor: self._cursor = cursor + 1`) so a concurrent `seek` landing mid-publish is honored, not clobbered. State is re-read after the wait so a mid-gap pause/seek/stop is honored before the next publish. `_wake.clear()` happens under the lock at the top of each iteration.
- Introspection reads (`state`/`cursor`/`position_fraction`/`rate`) stay lock-free (single-attribute, atomic in CPython — fine for a UI poll).

### `tests/test_replay_unit.py` — 5 new deterministic thread-safety tests
A `_BarrierSleep` (two `threading.Event`s) injected as `sleep` wedges the worker mid-run so the interleave is deterministic (no real `time.sleep`, no flakiness — T-18-01-E):
- `test_scheduler_threadsafe_seek_midrun_no_lost_update` — **SC1**: mid-run `seek(600)` → next published item is `items[6]` (1..5 skipped), cursor advances 6→9, no clobber.
- `test_scheduler_threadsafe_set_rate_midrun_takes_effect` — mid-run `set_rate(4.0)` observable immediately.
- `test_scheduler_threadsafe_pause_midrun_returns_paused` — mid-run `pause()` → `run()` returns PAUSED, cursor held.
- `test_scheduler_default_sleep_is_interruptible` (T-18-01-B) — with the default sleep, a `pause()` cuts a 10s gap short (returns well under the bound, PAUSED, 2nd item unpublished).
- `test_scheduler_injected_sleep_still_honored` (T-18-01-C) — an injected recording sleep receives the exact paced Δt values.

## Deviations from plan
None to the design. One execution deviation: the first spawned `gsd-executor` hit a session/quota limit after writing the RED tests (Task 1's test half) but before touching `scheduler.py` and before any commit — clean partial state (modified test file, no production code, no commits). Plan 18-01 was completed **inline** from RESEARCH §3a rather than re-spawning, to avoid another mid-task interruption.

One real bug was found+fixed during green: clearing `_wake` at the end of `_interruptible_sleep` let `play()`'s `set()` persist and short-circuit the first paced gap (the interruptible-sleep test caught it). Moved the clear under the lock at the top of each `run()` iteration.

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k "threadsafe or interruptible or injected_sleep"` → **5 passed**.
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py` → **30 passed** (25 prior Phase-13 unchanged + 5 new).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → **20 passed** (`import rosbagger_replay` stays ROS-free; scheduler stdlib-only).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **512 passed, 4 skipped; 85.76% coverage** (≥80% gate).
- `ruff check` + `ruff format --check` on both files → clean.

## Self-Check: PASSED
- `scheduler.py` (lock + wake + interruptible default sleep + locked setters + restructured run + loop property) — FOUND
- `tests/test_replay_unit.py` (5 thread-safety tests + `_BarrierSleep`) — FOUND
- Commit `2b470c2` (feat 18-01) — FOUND
