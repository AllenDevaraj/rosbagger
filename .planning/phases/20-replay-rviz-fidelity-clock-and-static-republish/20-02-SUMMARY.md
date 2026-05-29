---
phase: 20-replay-rviz-fidelity-clock-and-static-republish
plan: 02
status: complete
subsystem: rosbagger-replay (live publish sink)
requirements: [REP-04]
tags: [replay, rviz-fidelity, clock, static-republish, live, single-publish-path]
provides:
  - "build_publish_sink(node, *, publish_clock=False, static_topics=frozenset()) — opt-in /clock + static-tracking on the SINGLE publish path, default off, 2-tuple return back-compatible"
  - "republish_static(sink) — re-push sink.tracker.republish_items() through the sink after a seek (front-door exposed)"
depends_on: [20-01]
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/replay.py
  - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
  - tests/test_replay_fidelity_live.py
key-files:
  created:
    - tests/test_replay_fidelity_live.py
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/replay.py
    - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
decisions:
  - "Back-compat: kept the (sink, published) 2-tuple return and attached the tracker as sink.tracker (a function attribute) — both existing 2-tuple unpackings (replay.py, replay_panel.py) keep working when no kwargs are passed. New args are keyword-only + default off."
  - "/clock publisher + Clock class resolved ONCE before the sink closure (never per-item — no publisher churn); the get_message import stays lazy in the body (offline invariant)."
  - "republish_static is a module function driving the sink AFTER seek — scheduler.py is untouched (static re-publish is a publish-path concern, not scheduler logic)."
  - "republish_static exposed via the lazy front door + _require_ros guard (consistent with replay/build_publish_sink) even though it imports no ROS itself, since it lives in the ROS-touching .replay module."
metrics:
  duration: ~25min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 20 Plan 02: Live /clock + Static Re-publish — Summary

Wired the live rclpy boundary for RViz fidelity (REP-04) onto the single existing publish path, opt-in and default-off, so today's behavior (and both existing 2-tuple call sites) is unchanged.

## What changed
- **`replay.py`**: `build_publish_sink` gains keyword-only `publish_clock`/`static_topics` (default off). When enabled it records each item to a `StaticTracker` (20-01) and/or emits a `/clock` `Clock(.clock=clock_stamp_ns(item.t_ns))` per publish (publisher resolved once). The tracker is exposed as `sink.tracker` (the 2-tuple return is unchanged). Added `republish_static(sink)` — re-pushes the tracked static set through the same sink after a seek.
- **`__init__.py`**: `republish_static` re-exported via a lazy front door (+ `__all__`).
- **NEW `tests/test_replay_fidelity_live.py`**: `-m live` (importorskip rclpy) — external subscriber receives `/clock` (SC1) and the re-published `/tf_static` after a seek (SC2-live, via `write_tf_bag`).

## Verification
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py tests/test_replay_unit.py` → 59 passed (the no-kwargs back-compat path + offline guard unchanged).
- Live module collected-and-skipped in the offline lane (importorskip rclpy → no tests collected).
- Full blended: **540 passed, 5 skipped, 86.90% coverage** (≥80%; the +1 skip is the new live module; clean on a re-run past the intermittent Qt SIGBUS-at-exit).
- ruff check + format → clean.
- ROS-lane sign-off (SC1 + SC2-live, NOT part of the offline gate): `source /opt/ros/humble/setup.bash && uv run --with pyyaml pytest tests/test_replay_fidelity_live.py -m live -v`.

## Deviations from plan
None. Chose the `sink.tracker` attribute return (the plan's least-disruptive option) to preserve both 2-tuple unpackings.

## Self-Check: PASSED
- `replay.py` (build_publish_sink opt-ins + republish_static) — FOUND
- `__init__.py` (republish_static front door) — FOUND
- `tests/test_replay_fidelity_live.py` (SC1 + SC2-live) — FOUND
- Commit `bf2394c` (feat 20-02) — FOUND
