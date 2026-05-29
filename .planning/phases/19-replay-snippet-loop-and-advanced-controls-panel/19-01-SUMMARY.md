---
phase: 19-replay-snippet-loop-and-advanced-controls-panel
plan: 01
status: complete
subsystem: rosbagger-replay (pure Replayer scheduler)
requirements: [REP-03]
tags: [replay, scheduler, region-loop, snippet, threading, pure-python]
provides:
  - "Replayer in/out region loop: set_loop_region(in_ns,out_ns) / clear_loop_region() (lock-guarded + wake) + a loop_region read property"
  - "run() wraps a snippet on repeat from past t_out back to the first item at/after t_in (distinct from whole-bag loop); region wins over _loop; bound guards still win (W4); in-bound past end -> DONE"
depends_on: []
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/scheduler.py
  - tests/test_replay_unit.py
key-files:
  created: []
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/scheduler.py
    - tests/test_replay_unit.py
decisions:
  - "Region stored as ABSOLUTE t_ns bounds (not offsets) so it shares position_fraction's basis — the 19-03 panel maps fractions through the same basis."
  - "The region branch wraps only AFTER the cursor passes t_out — it does NOT auto-seek into the region on the first pass. The panel (19-03) seeks to t_in when enabling region-loop; the wrap tests seek(t_in) first to mirror that real flow."
  - "Placed AFTER the bound guards (W4 preserved: DONE/bound beats the wrap) and given precedence over the whole-bag _loop when a region is set (a snippet is the more specific intent)."
  - "Reused the Phase-18 lock + wake contract verbatim for the setters (no new concurrency primitive); reused the existing _BarrierSleep for the deterministic mid-run thread-safe test."
metrics:
  duration: ~20min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 19 Plan 01: Scheduler Region Loop — Summary

Added an in/out **region loop** `[t_in, t_out]` to the pure `Replayer` (REP-03) — the snippet-on-repeat the user asked for — distinct from the existing whole-bag `loop`. Pure-scheduler tier; 19-02 (Scrubber handles) and 19-03 (panel sub-panel) wire on top.

## What changed
- **`scheduler.py`**: `__init__` gains `_loop_in_ns`/`_loop_out_ns` (absolute t_ns, None=off). `set_loop_region(in,out)` (normalize in≤out, lock-guarded + wake), `clear_loop_region()` (lock-guarded + wake), and a `loop_region` read property (both-or-neither). `run()`'s advance block gains a region-wrap branch **after** the bound + step guards: when a region is active, if the cursor ran off the end OR the next item's `t_ns > t_out`, jump to the first item at/after `t_in` (the same `next(...)` scan `seek` uses); an in-bound past end → DONE. The region wins over the whole-bag `_loop` when both are set; with no region, the existing `_loop`/DONE branch is unchanged.
- **`tests/test_replay_unit.py`**: 8 region tests (see commit `702bcdd`).

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k region` → 8 passed.
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py` → **38 passed** (30 prior Phase-13/18 unchanged + 8 new).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 20 passed (scheduler stdlib-only; `import rosbagger_replay` ROS-free AND Qt-free).
- `ruff check` + `ruff format --check` on both files → clean.

## Deviations from plan
None to the design. Clarified (and documented in tests) that the region branch wraps only after passing `t_out` — it doesn't auto-seek into the region on pass 1; the wrap tests `seek(t_in)` first to mirror the panel's real flow.

## Self-Check: PASSED
- `scheduler.py` (set_loop_region / clear_loop_region / loop_region + run() region wrap) — FOUND
- `tests/test_replay_unit.py` (8 region tests) — FOUND
- Commit `702bcdd` (feat 19-01) — FOUND
