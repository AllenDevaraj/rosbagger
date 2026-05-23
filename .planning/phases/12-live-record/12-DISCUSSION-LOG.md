# Phase 12: Live Record - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 12-live-record
**Mode:** `--auto` (autonomous — all gray areas auto-selected; recommended option chosen per question, no prompts)
**Areas discussed:** Package/deps/CLI surface, Recording mechanism, Topic discovery & selection, Output format & stop control, Test strategy & offline guarantee

**Defining constraint discovered:** `rclpy` imports from the system ROS install but is ABSENT from the project `uv` venv (`PYTHONPATH="" uv run python -c "import rclpy"` → ModuleNotFoundError) — the live module runs in a sourced-ROS environment, not the offline uv venv.

---

## Package, dependencies & CLI surface

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `rosbagger-record` package + `rosbagger-record` console script; ROS deps env-provided + lazy | New workspace member; bagq stays offline; rclpy/rosbag2_py from sourced ROS, lazy-imported | ✓ |
| `bagq record` capability-gated subcommand | Add record to the bagq CLI | |
| rclpy/rosbag2_py as uv pyproject deps | Let uv resolve the ROS deps | |

**Auto-selected:** separate `packages/rosbagger-record/` + `rosbagger-record` console script; rclpy/rosbag2_py environment-provided (NOT uv-resolved) and lazy-imported.
**Notes:** Design-locked ("live modules isolate rclpy behind their package boundary"; offline core/bagq stay ROS-free). `bagq record` rejected — it would pull rclpy into bagq's offline import graph. uv-resolved ROS deps rejected — rclpy/rosbag2_py aren't usable PyPI wheels (verified absent from the uv venv); they're distro-provided.

---

## Recording mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| rosbag2_py SequentialWriter (MCAP) + rclpy discovery/spin | Design's explicit choice; ROS-native recorder; MCAP re-opens via v1 reader | ✓ |
| rclpy generic subscriptions → rosbags Writer | Reuse the offline-edit writer for the live write | |
| Shell out to `ros2 bag record` | Subprocess the ROS CLI recorder | |

**Auto-selected:** record to MCAP via `rosbag2_py` (with `rclpy` for discovery + node spin); generic serialized capture.
**Notes:** The design spec literally says "record to MCAP via rosbag2_py" — the robust ROS-native path; its MCAP output is re-openable by the v1 reader (SC3). The rosbags Writer is the OFFLINE edit path, not the live-record path — not substituted here. Shelling out rejected (the project owns its pipeline / API-first).

---

## Topic discovery & selection

| Option | Description | Selected |
|--------|-------------|----------|
| rclpy get_topic_names_and_types; `list`; subset via positional topics + --all/--regex/--exclude | Discover then select | ✓ |
| Record everything always | No selection | |
| Config-file topic lists only | Selection only via a file | |

**Auto-selected:** rclpy `get_topic_names_and_types()` discovery; `rosbagger-record list` to print topics+types (SC1); record subset via positional topics + `--all`/`--regex`/`--exclude`.
**Notes:** Matches the design's "discover active topics + their types, checkbox-select." Positional topics + `--all` is the ergonomic CLI mirror of the GUI checkbox-select (same API).

---

## Output format & stop control

| Option | Description | Selected |
|--------|-------------|----------|
| Default MCAP; stop on SIGINT (graceful finalize) + optional --duration/--max-messages | MCAP lock; Ctrl-C + bounded mode | ✓ |
| Default ROS2 sqlite3 | Record to sqlite3 | |
| Stop only on Ctrl-C (no bounded mode) | No deterministic stop | |

**Auto-selected:** default MCAP; stop on SIGINT with graceful bag finalize; optional `--duration SECONDS` / `--max-messages N`.
**Notes:** MCAP is the ROS 2 default and the design's record target. A bounded mode is REQUIRED for a deterministic live integration test (record exactly N → exit → assert). Graceful SIGINT shutdown ensures the bag finalizes so it re-opens cleanly.

---

## Test strategy & offline guarantee (CRITICAL)

| Option | Description | Selected |
|--------|-------------|----------|
| Two-tier: ROS-free mocked unit tests (uv venv/CI) + live rclpy-gated integration tests (ROS sourced) | Mock for CI; real graph for the live path; offline-guard extended | ✓ |
| Live tests only (ROS-equipped CI required) | No ROS-free coverage | |
| Mock everything (no real live test) | Never exercise the real rclpy/rosbag2_py path | |

**Auto-selected:** two-tier — (1) ROS-free unit tests with rclpy/rosbag2_py mocked, run in the uv venv/offline CI; (2) `live`-marked, `importorskip("rclpy")`-gated integration tests (real publisher → record → re-open via v1 reader, SC2+SC3) run with ROS sourced, skipped in offline CI. Extend `test_offline_guard.py` so core/bagq still pull no rclpy/rosbag2_py.
**Notes:** Forced by the verified rclpy-not-in-uv-venv reality. "Mock everything" rejected — would never prove the real SC2/SC3 path. "Live only" rejected — would break the ROS-free CI guarantee. The two suites run in DIFFERENT environments (offline = `PYTHONPATH=""`; live = ROS sourced) — a key planning consideration.

---

## Claude's Discretion

- Exact module layout; CLI flag names; the precise rclpy generic-subscription + rosbag2_py SequentialWriter wiring (research-confirmed).
- The `live` pytest-marker name and how the ROS-sourced lane is invoked.
- Whether any non-MCAP `--format` is exposed.
- Hard constraints: offline core/bagq must NEVER import rclpy; recorded bag MUST re-open via the v1 reader; live tests gated/skippable so offline CI stays green.

## Deferred Ideas

- Replay (Phase 13); GUI Record panel (Phase 14).
- QoS capture/override, compression, split-by-size/duration, service/action recording.
- Non-MCAP record formats (ROS1 .bag, ROS2 sqlite3).
- rosbag2_py reader backend (still out per PROJECT).
