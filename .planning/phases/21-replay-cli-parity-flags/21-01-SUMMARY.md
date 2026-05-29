---
phase: 21-replay-cli-parity-flags
plan: 01
status: complete
subsystem: rosbagger-replay (library)
requirements: [REP-05]
tags: [replay, cli-parity, remap, delay, start-paused, region, single-publish-path]
provides:
  - "replay() keyword-only delay/start_paused/publish_clock/remap/region_start/region_end (all default off), each mapping to an existing mechanism"
  - "build_publish_sink(node, *, publish_clock, static_topics, remap=None) — remap is a name lookup inside the single sink (back-compatible)"
depends_on: []
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/replay.py
  - tests/test_replay_unit.py
  - tests/test_replay_fidelity_live.py
key-files:
  created: []
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/replay.py
    - tests/test_replay_unit.py
    - tests/test_replay_fidelity_live.py
decisions:
  - "remap appended LAST as keyword-only to build_publish_sink; pub_topic = remap.get(item.topic, item.topic) keys the publisher dict + create_publisher — the 2-tuple return + sink.tracker + Phase-20 static/clock paths unchanged."
  - "start_paused maps to 'skip replayer.play()' — a run-to-completion call then publishes 0 and returns PAUSED (interactive resume is the GUI; runtime ROS services deferred per SC3). Proven by a pure scheduler test (never-played Replayer publishes 0)."
  - "region_start/region_end (seconds) reuse Phase-19 seek + set_loop_region; single-pass [in,out] stop documented deferred (mirrors the --end-folded-into-duration precedent)."
  - "delay = time.sleep after sink build, before play (subscribers discover); import time at module top (stdlib, ROS-free)."
metrics:
  duration: ~20min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 21 Plan 01: Library CLI-Parity Plumbing — Summary

Plumbed the `ros2 bag play`-parity behaviors through the library (REP-05), each mapping to an existing mechanism — no new publish path, `scheduler.py` untouched. 21-02 adds the thin CLI surface that forwards these params.

## What changed
- **`replay.py`**: `build_publish_sink` gains `remap=None` (name lookup inside the single sink). `replay()` gains keyword-only `delay`/`start_paused`/`publish_clock`/`remap`/`region_start`/`region_end` (all default off), mapping to sleep-before-play / skip-play() / `build_publish_sink` / `seek`+`set_loop_region`. `import time` added at module top.
- **`tests/test_replay_unit.py`**: `test_scheduler_not_played_publishes_nothing` (the start_paused mapping).
- **`tests/test_replay_fidelity_live.py`**: `-m live` `test_remap_external_subscriber_receives_on_new_name`.

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py tests/test_offline_guard.py` → 60 passed (the no-kwargs back-compat path + offline guard unchanged).
- Live module collected-and-skipped offline.
- Full blended: **547 passed, 5 skipped, 87.79% coverage** (junit: 552 tests, 0 failures/errors).
- ruff check + format → clean.
- ROS-lane sign-off (SC2 remap): `source /opt/ros/humble/setup.bash && uv run --with pyyaml pytest tests/test_replay_fidelity_live.py -m live`.

## Deviations from plan
None. Kept the remap offline assertion at the scheduler/back-compat level (the real republish-on-new-name is the live proof, per the plan's allowance).

## Self-Check: PASSED
- `replay.py` (replay() params + build_publish_sink remap) — FOUND
- `tests/test_replay_unit.py` (start_paused test) — FOUND
- `tests/test_replay_fidelity_live.py` (remap live test) — FOUND
- Commit `56e7124` (feat 21-01) — FOUND
