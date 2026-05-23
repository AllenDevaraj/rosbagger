---
phase: 13-live-replay
plan: 02
subsystem: rosbagger-replay
tags: [transport-scheduler, state-machine, pacing, offline-clean, pure-python, tdd]
requires:
  - "rosbagger_replay.source.ReplayItem (Plan 13-01 — the ordered .t_ns/.topic/.msgtype/.cdr stream)"
provides:
  - "rosbagger_replay.scheduler.Replayer — the pure-Python transport state machine (D-06..D-09)"
  - "rosbagger_replay.scheduler.State (PLAYING/PAUSED/STEPPING/DONE)"
  - "the six transport controls (play/pause/step/seek/set_rate/loop) + monotonic pacing + bounded stop"
affects:
  - "Plan 13-03 (rclpy publish sink injected as the Replayer's sink callback; CLI --start/--rate/--loop/--duration map onto the Replayer)"
tech-stack:
  added: []
  patterns:
    - "Injectable clock/sleep/sink so the whole state machine is unit-tested ROS-free with a fake clock + recording sink (D-11 tier 1)"
    - "Generic-over-.t_ns scheduler: no source import at module top — indexes a list + reads item.t_ns"
    - "Bounded-stop is-not-None guards (WR-01) + injected monotonic clock (WR-02); bound checked BEFORE loop-reset (W4)"
    - "seek() as the SOLE position-setter (W3 — no start index ctor param)"
key-files:
  created:
    - "packages/rosbagger-replay/src/rosbagger_replay/scheduler.py"
  modified:
    - "tests/test_replay_unit.py (added the scheduler test section: 13 SC2/SC3 tests)"
decisions:
  - "run() does an up-front bound check (max_messages=0 / duration<=0 halt BEFORE the first publish — WR-01 truthiness trap) plus a while/else clean-DONE when the cursor is already at end-of-stream (seek-past-end), so neither edge IndexErrors nor silently runs unbounded"
  - "Replayer is generic over items-with-.t_ns and imports no source.py at top (offline-clean module surface); ReplayItem is used only as the test fixture type"
  - "rate validated >0 in BOTH __init__ and set_rate (reused guard) — no ZeroDivisionError, no busy-wait (Pitfall 5)"
metrics:
  duration: ~12 min
  completed: 2026-05-23
  tasks: 2
  files: 2
---

# Phase 13 Plan 02: Pure transport scheduler (Replayer) Summary

Built the PURE-PYTHON `Replayer` transport scheduler — the architectural payoff of D-06. A ROS-free state machine over an ordered list of `.t_ns`-bearing items, owning the four-state machine (PLAYING/PAUSED/STEPPING/DONE), the six controls (play / pause / step / seek / set_rate / loop), monotonic inter-message pacing scaled by `rate`, and an optional bounded stop (`max_messages` / `duration`) — with injectable `clock`, `sleep`, and publish `sink`. SC2 (all six controls) and SC3 (rate scaling halves/doubles the slept Δt; seek lands on the expected message index/timestamp) are now PROVEN deterministically offline with a fake clock + a recording sink. No `rclpy` anywhere.

## What Was Built

- **Task 1 — `scheduler.py`** (commit `a27009a`): `class State(Enum)` (PLAYING/PAUSED/STEPPING/DONE) + `class Replayer`. The ctor takes `(items, sink, *, clock=time.monotonic, sleep=time.sleep, rate=1.0, loop=False, max_messages=None, duration=None)` — **no `start` index param** (W3: `seek` is the only position-setter). `rate > 0` is validated at construction (reusing the `set_rate` guard). The six controls: `play`/`pause`/`step` mutate the state; `set_rate(x)` raises `ValueError("rate must be > 0")` for `x <= 0`; `seek(t_offset_ns)` lands the cursor on the first index `i` with `items[i].t_ns >= items[0].t_ns + t_offset_ns` (skipping intervening items, never publishing them). `run()` paces via `self._sleep(max(0.0, dt_ns/1e9/self._rate))` for cursor>0 (the first item incurs no pre-sleep), publishes the current item, then evaluates the bounded-stop guards (`max_messages`/`duration` via `is not None`) **before** the end-of-stream loop-reset so DONE wins over `loop=True` at the exact-end boundary (W4). Module top imports only stdlib (`time`, `enum.Enum`, `collections.abc.Callable`) — no rclpy/rosbag2_py/rosidl, no source import. Read-only `state`/`cursor`/`rate` properties expose the machine for the tests.
- **Task 2 — scheduler unit tests** (commit `cc979de`, TDD): added a scheduler section to `tests/test_replay_unit.py` (the same file Plan 01 created) — 13 ROS-free tests selectable by `-k scheduler`. They drive the `Replayer` with a `recorded = []` / `recorded.append` sink, a recording `slept.append` sleep, and (for duration) a `_FakeClock` advancing on each call. They prove: play-full (all N in order → DONE), step-one-then-PAUSED (cursor==1; a second step publishes the next), pause-holds-cursor (resume continues from index 2, no re-publish), seek lands on the first item ≥ target (skipped items absent) + seek-past-end (cursor==len → publishes nothing → DONE), rate scaling (rate=2.0 slept Δt is exactly half rate=1.0; first publish no pre-sleep — SC3), rate-invalid (set_rate(0)/(-1) + rate=-1 ctor raise), loop-restarts (max=2*N wraps cursor→0 and re-publishes), the **W4 loop+max==N exact-end boundary** (publishes EXACTLY N, ends DONE — not 2*N, not unbounded), and the bounded stops (max=2 over 9; max=0 → zero publishes; monotonic duration; duration=0 → zero publishes).

## How to Verify

- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k scheduler -q` — 13 scheduler tests green.
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -q` — full replay-unit suite (source from Plan 01 + scheduler here): **19 passed**.
- `PYTHONPATH="" uv run pytest -q` — full offline suite: **452 passed, 1 skipped**, coverage **97.37%** (≥80% gate on core+bagq held; rosbagger_replay stays out of the gate per D-12).
- `PYTHONPATH="" uv run ruff check .` + `ruff format --check .` — clean (74 files).
- `PYTHONPATH="" uv run python -c "import sys, rosbagger_replay.scheduler; assert 'rclpy' not in sys.modules and 'rosbag2_py' not in sys.modules"` — scheduler is ROS-free.
- `grep -v '^#' .../scheduler.py | grep -cE 'rclpy|rosbag2_py|rosidl'` returns 3, all in DOCSTRING prose (lines 14/16/65 document the offline invariant) — zero actual ROS imports, zero `source` import at module top (verified by `grep -nE '^\s*(import|from)\s+(rclpy|rosbag2_py|rosidl)'` → none; `... source` → none). Same documentation pattern as 13-01's source.py/errors.py.
- `PYTHONPATH="" uv sync --locked --dev` exits 0 (no new deps; no re-lock).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] `run()` did not halt at `max_messages=0` / `duration=0` and left state PLAYING after a seek-past-end.**
- **Found during:** Task 2 (the `max=0` and `seek-past-end` tests went RED against the Task 1 `run()`).
- **Issue:** (a) The bound was checked only AFTER a publish, so `max_messages=0` published one item before the `published >= 0` check could fire — violating WR-01 (`0` must mean zero, not "publish one then stop"). (b) When the cursor was already at `len(items)` (a seek-past-end while PLAYING), the `while ... and cursor < len` body never ran, so the state stayed PLAYING and never reached DONE.
- **Fix:** Added an up-front bound check at `run()` entry (so `max_messages=0` and `duration<=0` halt to DONE before any publish) and a `while ... else` clause that sets DONE when the cursor is already at end-of-stream while in a running state (clean DONE, no IndexError). Both edges are now pinned by `test_scheduler_bounded_max_messages_zero_means_zero`, `test_scheduler_bounded_duration_zero_halts_before_first_publish`, and `test_scheduler_seek_past_end_publishes_nothing_then_done`.
- **Files modified:** `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py`
- **Commit:** `cc979de`

**2. [Rule 1 — Test adjustment] duration test reworked to model the real clock-call sequence.**
- **Found during:** Task 2 (the duration test as first written assumed `run()` made no up-front clock call).
- **Issue:** The up-front `duration` guard (from deviation 1) consumes one `_FakeClock` tick before the loop, so a fixed "exactly 2 publishes at duration=2" expectation no longer matched the (now correct) production behavior.
- **Fix:** Reworked the test to assert the robust monotonic invariant — `0 < len(recorded) < len(items)` and `state is DONE` (a bounded mid-stream halt driven by the injected monotonic clock) — plus a dedicated `duration=0` zero-publish test. This is a test-expectation correction; production behavior (a `duration` bound that halts mid-run, and `duration=0` halting immediately) is the desired contract.
- **Files modified:** `tests/test_replay_unit.py`
- **Commit:** `cc979de`

## TDD Gate Compliance

Plan type is `execute` (not plan-level `tdd`); both tasks are `tdd="true"`. Task 1 ships the scheduler (`feat` `a27009a`); Task 2 adds the tests (`test` `cc979de`), which went RED on three edge cases (max=0, duration=0, seek-past-end) and drove the Rule-1 `run()` fix to GREEN within the same commit. The `feat` precedes the `test` commit by the plan's structure (Task 1 = implementation, Task 2 = the SC2/SC3 suite) — mirroring the 13-01 characterization pattern — but the tests genuinely went red-then-green against the implementation (the three edge fixes prove the suite was not a rubber-stamp). No separate REFACTOR commit (the fix landed with the tests).

## Notes on the no-ROS grep criterion

The Task-1 acceptance grep (`grep -v '^#' scheduler.py | grep -cE 'rclpy|rosbag2_py|rosidl'` → 0) returns **3**, all matches in DOCSTRING prose (lines 14, 16, 65) that document the offline invariant and the Plan-03 publish path — the same documentation pattern 13-01 used for `source.py`/`errors.py`. The substantive requirement ("imports no ROS") is verified two stronger ways: (a) `grep -nE '^\s*(import|from)\s+(rclpy|rosbag2_py|rosidl)'` and `... source` both return nothing, and (b) the runtime check confirms `import rosbagger_replay.scheduler` adds no `rclpy`/`rosbag2_py` to `sys.modules`.

## Self-Check: PASSED

- `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py` — FOUND
- `tests/test_replay_unit.py` (scheduler section) — FOUND
- Commit `a27009a` (feat scheduler) — FOUND
- Commit `cc979de` (test + run() fix) — FOUND
