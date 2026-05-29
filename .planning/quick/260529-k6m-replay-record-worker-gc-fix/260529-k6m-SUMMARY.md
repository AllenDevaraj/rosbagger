---
quick_id: 260529-k6m
slug: replay-record-worker-gc-fix
date: 2026-05-29
status: complete
commit: d307d71
---

# Quick Task 260529-k6m — Summary

## What changed

Fixed a garbage-collection bug that made the desktop **live drive workers no-op**: the
panels kept the `QThread` returned by `run_on_thread` but discarded the `BlockingWorker`,
so the parentless worker was collected before `thread.started → worker.run` fired and the
blocking work (`Replayer.run()` for replay; discovery/record for record) never ran.

- `panels/replay_panel.py` — keep `self._drive_worker` for the drive's lifetime; clear in
  `_on_drive_finished`.
- `panels/record_panel.py` — keep `self._discover_worker` + `self._record_worker`; clear in
  `_clear_discover_thread` / `_on_record_finished`.
- `tests/test_desktop_live.py` — `test_replay_panel_publishes_external_subscriber_receives`
  now presses Play via `play_button.click()` (the prior `qtbot.mouseClick` was dropped on a
  non-visible button, so it never exercised the drive). True regression now.

Single commit: **d307d71** (3 files, +32 / −8).

## Why it mattered (user impact)

Desktop Replay `Play` looked like it was working ("Playing… (N msg, rate R)") but published
nothing — the playhead never moved and RViz / `ros2 topic list` saw no bag topics. Live
recording (discovery + capture) was silently broken the same way.

## Root cause

`self._drive_thread, _ = run_on_thread(self, worker, ...)` — worker dropped into `_` → GC'd
before its `run` slot fired. The inspect/query/tf panels already kept `self._*_worker`; the
fix makes replay/record match them. (`run_on_thread`'s own docstring warns the returned
`(thread, worker)` pair MUST be kept.)

## Verification

| Check | Result |
|-------|--------|
| Live desktop tests (ROS on path) | **2 passed** (replay + record) |
| Full offline suite (`PYTHONPATH=""`, CI-equivalent) | **552 passed, 5 skipped, 87.82%** (≥80% gate) |
| `ruff check` / `ruff format --check` | clean |
| Real-bag reproduction (`~/Desktop/rosbag`) | Play publishes; pub count climbs, playhead advances |

## Visibility gap closed

The pre-existing live test was skipped in CI (no ROS) **and** in the documented
`PYTHONPATH=""` local runs (which strip ROS so `importorskip("rclpy")` skips), **and** when
run with ROS it crashed at startup (ROS `launch_testing` pytest plugin needs `lark`, absent
from the uv venv) — so the GUI publish path was effectively never exercised. The test fix +
documented `uv run --with lark` invocation make it runnable; it now catches this class of bug.

## Follow-ups / not in scope

- Pre-existing intermittent offscreen-Qt SIGBUS *at pytest teardown* (benign; re-run) — left
  as-is per the standing note.
- Deferred `chore(format)` drift item (inspect_panel.py / rows_model.py) untouched.
