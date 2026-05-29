---
phase: 20-replay-rviz-fidelity-clock-and-static-republish
plan: 01
status: complete
subsystem: rosbagger-replay (pure fidelity tier)
requirements: [REP-04]
tags: [replay, rviz-fidelity, static-republish, clock, pure-python, offline-clean]
provides:
  - "StaticTracker: record latest ReplayItem per configured static topic (default /tf_static); republish_items() returns the re-publish set; clear() resets"
  - "clock_stamp_ns(t_ns) -> (sec, nanosec) via divmod (pure time math for the live /clock build)"
  - "Both re-exported from rosbagger_replay without binding ROS (the SC2 unit-test/CI route)"
depends_on: []
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/fidelity.py
  - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
  - tests/test_replay_fidelity.py
  - tests/test_offline_guard.py
key-files:
  created:
    - packages/rosbagger-replay/src/rosbagger_replay/fidelity.py
    - tests/test_replay_fidelity.py
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
    - tests/test_offline_guard.py
decisions:
  - "ReplayItem imported under TYPE_CHECKING only — fidelity.py imports NOTHING heavy at runtime (duck-types item.topic), keeping the offline graph trivially clean."
  - "StaticTracker keeps latest-per-topic in a dict keyed by topic (bounded by the static set, NOT message history) so a long replay doesn't grow memory."
  - "clock_stamp_ns uses divmod(t_ns, 1e9) which guarantees 0 <= nanosec < 1e9 for non-negative t_ns — a well-formed ROS stamp."
metrics:
  duration: ~15min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 20 Plan 01: Pure RViz-Fidelity Tier — Summary

Created the ROS-free decision tier for making a replay seek "look right" in RViz (REP-04) — the offline half of the Phase-12/13 two-tier split, so SC2 (static re-publish) has a deterministic CI proof and `import rosbagger_replay` stays ROS-free.

## What changed
- **NEW `fidelity.py`** (stdlib-only): `StaticTracker` (latest-per-static-topic record, default `/tf_static`, `republish_items`, `clear`) + `clock_stamp_ns(t_ns) -> (sec, nanosec)`.
- **`__init__.py`**: re-export `StaticTracker` + `clock_stamp_ns` (added to `__all__`, sorted) via a module-top stdlib-only `.fidelity` import — binds no ROS.
- **NEW `tests/test_replay_fidelity.py`**: 6 pure unit tests.
- **`tests/test_offline_guard.py`**: `test_import_replay_fidelity_does_not_pull_ros`.

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_fidelity.py` → 6 passed.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 21 passed (incl. the new fidelity ROS-free assertion).
- Full blended: **540 passed, 4 skipped, 86.90% coverage** (≥80%; clean on attempt 1 — the intermittent Qt SIGBUS-at-exit can pre-empt the summary, re-run clears it).
- ruff check + format → clean on all four files.

## Deviations from plan
None. Used the `TYPE_CHECKING` import for `ReplayItem` (the plan's preferred option) to keep `fidelity.py` importing nothing heavy.

## Self-Check: PASSED
- `fidelity.py` (StaticTracker + clock_stamp_ns) — FOUND
- `__init__.py` re-export + `tests/test_offline_guard.py` fidelity test — FOUND
- `tests/test_replay_fidelity.py` (6 tests) — FOUND
- Commit `90380b1` (feat 20-01) — FOUND
