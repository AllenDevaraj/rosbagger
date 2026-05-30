---
phase: 22-replay-live-mirror-to-rerun
status: passed
date: 2026-05-30
verifier: inline (gsd-verifier not installed)
plans: [22-01, 22-02, 22-03]
requirements: [RR-1, RR-2, RR-3]
---

# Phase 22 — Verification: Replay live mirror to Rerun

**Result: PASSED** — offline gate fully green AND all three ROS-lane live tests pass.

## Goal

Add an **Open in Rerun** toggle to the desktop Replay tab that live-mirrors Play into the Rerun
viewer by forking the publish sink into a new ROS-isolated `rosbagger-rerun` package
(Image/CompressedImage, LaserScan, PointCloud2, TF rich converters + generic fallback), gated on
`rerun-sdk`. Additive (RViz / `ros2 topic` unaffected); offline import graph stays ROS-free AND
Rerun-free.

## Success criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Open in Rerun → Play mirrors the bag (image/scan/…) into the viewer, no manual setup | **PASS** | `test_replay_panel_rerun_mirror_writes_rrd` PASSED in the ROS lane (toggle on → Play → tee → non-empty `.rrd`); the GUI path runs end-to-end |
| 2 | RViz / `ros2 topic` still receive the same topics (additive) | **PASS** | `test_replay_panel_publishes_external_subscriber_receives` (existing) still PASSES with the tee in place — the external subscriber receives; `build_publish_sink` untouched |
| 3 | A topic with no rich converter still appears (generic fallback) | **PASS** | `test_convert_unknown_falls_back_to_textlog` (offline) — unknown msgtype → Scalars + trailing TextLog |
| 4 | `import rosbagger_rerun` pulls no rclpy/rerun; offline gate ≥80% | **PASS** | `test_import_rerun_bridge_does_not_pull_ros_or_rerun`; full offline suite **565 passed, 6 skipped, 87% coverage** |
| 5 | Live `.rrd` regression asserts non-empty output | **PASS** | `test_build_rerun_sink_writes_rrd` PASSED in the ROS lane (real items → non-empty `.rrd`) |

## Requirement coverage

- **RR-1** (package scaffold + wiring + `rerun_available()` + offline guard) — 22-01, 2 commits.
- **RR-2** (converters + `build_rerun_sink` + session; offline + live `.rrd`) — 22-02, 2 commits.
- **RR-3** (desktop toggle + dynamic tee + gating + install-on-click + live mirror) — 22-03, 2 commits.

## Test evidence

| Lane | Command | Result |
|------|---------|--------|
| Offline (CI-equivalent) | `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` | **565 passed, 6 skipped** |
| Offline coverage | `… --cov=rosbagger_core --cov=bagq --cov=rosbagger_desktop` | **87%** (≥80%) |
| ROS lane — library | `uv run --with pyyaml --with lark pytest tests/test_rerun_live.py -m live` | **1 passed** |
| ROS lane — desktop mirror | `… test_desktop_live.py::test_replay_panel_rerun_mirror_writes_rrd -m live` | **1 passed** |
| ROS lane — publish additive | `… test_desktop_live.py::test_replay_panel_publishes_external_subscriber_receives -m live` | **1 passed** |
| Lint | `ruff check` / `ruff format --check` | clean |

## Invariants held

- `build_publish_sink` is byte-for-byte unchanged — the rerun sink re-deserializes independently;
  the `260529-k6m` publish path is protected (the additive publish test still passes).
- Offline-import invariant: `import rosbagger_rerun` pulls neither `rclpy` nor `rerun`; the desktop
  `replay_panel` module top stays ROS-free AND rerun-free.
- The install-on-click worker keeps both thread+worker refs (the `260529-k6m` GC discipline).
- The Rerun mirror is transport-independent (cleaned up in `closeEvent`/`_close_rerun`, never
  `_teardown_transport`).

## Notes

- The offscreen-Qt teardown SIGBUS (a known benign artifact, documented) intermittently truncates
  pytest's summary; results captured via line-buffered re-runs + the `--cov-report=` recipe. It is
  a teardown artifact at process exit, never a test failure.
- v1 deferrals (per spec): external `ros2 bag play` mirroring, OccupancyGrid/IMU/Pose/Path/Markers
  rich converters, time-interpolated/multi-root TF, blueprint customization, GUI `.rrd` recording.
- Final user confirmation = manual smoke on `~/Desktop/rosbag` (camera + `/scan` in the viewer).
