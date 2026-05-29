---
phase: 21-replay-cli-parity-flags
plan: 02
status: complete
subsystem: rosbagger-replay (CLI)
requirements: [REP-05]
tags: [replay, cli, typer, parity-flags, remap, thin-face]
provides:
  - "rosbagger-replay CLI flags: --clock, --delay, --remap (old:=new, repeatable), --start-paused/-p, --region-start, --region-end — forwarded to replay_bag"
  - "Deferred runtime ROS services + single-pass region stop documented out-of-scope in --help (SC3)"
depends_on: [21-01]
affects:
  - packages/rosbagger-replay/src/rosbagger_replay/cli.py
  - tests/test_replay_unit.py
key-files:
  created: []
  modified:
    - packages/rosbagger-replay/src/rosbagger_replay/cli.py
    - tests/test_replay_unit.py
decisions:
  - "--remap parsed with str.partition(':=') — a missing separator or empty side raises typer.BadParameter (clean usage error, non-zero exit, no traceback)."
  - "CLI stays a pure parser/forwarder: each flag maps 1:1 to a replay_bag kwarg (publish_clock/delay/remap/start_paused/region_start/region_end); no publish logic; top level typer+stdlib only."
  - "Deferred controls documented in the command docstring/help (SC3) rather than silently omitted — mirrors the existing --end-folded-into-duration discipline."
metrics:
  duration: ~20min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 21 Plan 02: CLI Parity Flags — Summary

Added the `ros2 bag play`-parity flags to the thin `rosbagger-replay` CLI (REP-05), each forwarded to the 21-01 library params. The CLI stays a pure parser/forwarder over `replay_bag`.

## What changed
- **`cli.py`**: `--clock`/`--delay`/`--remap`/`--start-paused`(`-p`)/`--region-start`/`--region-end` typer options; `--remap old:=new` parsed into a dict (malformed → `typer.BadParameter`); all forwarded to `replay_bag(...)`. Docstring/help documents the deferred runtime services + single-pass region stop (SC3).
- **`tests/test_replay_unit.py`**: 5 CliRunner tests (commit `fec544c`).

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k cli` → green (11 CLI tests incl. the 5 new).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → green (cli.py top level stays typer+stdlib).
- Full blended: **552 passed, 5 skipped, 87.79% coverage** (junit: 557 tests, 0 failures/errors).
- ruff check + format → clean.

## Deviations from plan
None.

## Self-Check: PASSED
- `cli.py` (6 parity flags + remap parse + deferred-services docstring) — FOUND
- `tests/test_replay_unit.py` (5 CliRunner tests) — FOUND
- Commit `fec544c` (feat 21-02) — FOUND
