---
phase: 13-live-replay
plan: 01
subsystem: rosbagger-replay
tags: [scaffolding, source-seam, raw-cdr, offline-clean, teaching-errors]
requires:
  - "rosbagger-core v1 rosbags reader (AnyReader; Phase 2)"
  - "tools/make_fixtures.py (ROS-free fixture bags)"
provides:
  - "packages/rosbagger-replay/ uv workspace member (console script rosbagger-replay)"
  - "rosbagger_replay.source.ReplayItem + load_items (time-ordered raw-CDR stream)"
  - "rosbagger_replay.errors.RosNotAvailableError + NoMessagesToReplayError (teaching capability errors)"
affects:
  - "Plan 13-02 (pure transport scheduler consumes the ReplayItem stream)"
  - "Plan 13-03 (rclpy publish sink + lazy replay() front door + offline-guard extension)"
tech-stack:
  added:
    - "rosbagger-replay (local uv member; deps rosbagger-core + typer only)"
  patterns:
    - "Lazy AnyReader import inside load_items (offline-clean module top)"
    - "ROS1 wire -> CDR bridge via reader.deserialize -> typestore.serialize_cdr"
    - "Connection-level topics filter with empty-selection short-circuit (QURY-05)"
    - "Teaching RuntimeError subclasses building their message in __init__ (API-first)"
key-files:
  created:
    - "packages/rosbagger-replay/pyproject.toml"
    - "packages/rosbagger-replay/src/rosbagger_replay/__init__.py"
    - "packages/rosbagger-replay/src/rosbagger_replay/errors.py"
    - "packages/rosbagger-replay/src/rosbagger_replay/source.py"
    - "tests/test_replay_unit.py"
  modified:
    - "pyproject.toml (ruff src list += rosbagger-replay/src)"
    - "uv.lock (re-locked to pick up the new member)"
decisions:
  - "load_items uses AnyReader DIRECTLY (not RosbagsReader) to access raw (conn,t_ns,rawdata) tuples + the ROS1 bridge"
  - "Materialize a list (A2) for v1 — fixtures are tiny and a list makes seek/index-landing (Plan 02) trivial; streaming deferred"
  - "__init__.py re-exports errors + source now (ROS-free); lazy replay() front door deferred to Plan 03"
metrics:
  duration: ~15 min
  completed: 2026-05-23
  tasks: 3
  files: 7
---

# Phase 13 Plan 01: rosbagger-replay scaffold + raw-CDR source seam Summary

Scaffolded the `rosbagger-replay` uv workspace member (mirroring `rosbagger-record`), added the stdlib-only teaching capability errors, and built the PURE, offline-clean raw-CDR `source.py` seam: `load_items` reads a bag through the v1 `rosbags` `AnyReader` and yields a time-ordered list of `ReplayItem(t_ns, topic, msgtype, cdr)` records whose `cdr` is always CDR bytes (ROS 2 passthrough; ROS 1 wire bridged via `deserialize -> serialize_cdr`). No `rclpy` anywhere.

## What Was Built

- **Task 1 — package scaffold** (commit `9232215`): `packages/rosbagger-replay/pyproject.toml` declaring only `rosbagger-core` + `typer>=0.15,<1` (rclpy/rosidl env-provided per D-03, never a pyproject dep), console script `rosbagger-replay = "rosbagger_replay.cli:app"` (cli lands in Plan 03), an `__init__.py` whose re-exports stay ROS-free, the ruff `src` entry, and a re-locked `uv.lock`. The `--cov=rosbagger_core --cov=bagq` gate was left untouched (D-12 — the new package stays out of the coverage gate).
- **Task 2 — teaching errors** (commit `369eb28`): `errors.py` with `RosNotAvailableError` (rclpy not sourced — teaching "source your ROS 2 environment" remedy) and `NoMessagesToReplayError` (empty replay selection — carries structured `.bag_paths` / `.topics`, teaching remedy). Both `RuntimeError` subclasses, stdlib-only (`from __future__` is the only import), message built in `__init__` (API-first).
- **Task 3 — raw-CDR source seam (TDD)** (commits `cd31a7d` RED, `ddc30a6` GREEN): `source.py` with the frozen+slotted `ReplayItem` dataclass and `load_items(bag_paths, *, topics=None, default_typestore=None)`. Opens an `AnyReader` (lazy-imported inside the body), filters connections by `topics` with an empty-selection short-circuit to `[]` (QURY-05), and for each `(conn, t_ns, rawdata)` emits CDR: ROS 2 `rawdata` passes through; ROS 1 (detected via `type(conn.ext).__name__ == "ConnectionExtRosbag1"`) is bridged through `reader.deserialize -> typestore.serialize_cdr`. `tests/test_replay_unit.py` proves all three fixture formats, the subset filter, the empty result, and the no-rclpy invariant.

## How to Verify

- `PYTHONPATH="" uv sync --locked --dev` exits 0 (new member resolves; lockfile consistent).
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k source -q --no-cov` — 6 source tests green.
- `PYTHONPATH="" uv run pytest -q` — full offline suite: **439 passed, 1 skipped**, coverage **97.37%** (≥80% on core+bagq).
- `PYTHONPATH="" uv run ruff check .` — all checks pass.
- `PYTHONPATH="" uv run python -c "import sys, rosbagger_replay; assert 'rclpy' not in sys.modules and 'rosbag2_py' not in sys.modules"` — `import rosbagger_replay` leaks no ROS.

## Deviations from Plan

**1. [Rule 2 — missing critical functionality] Added a minimal `__init__.py` in Task 1.**
- **Found during:** Task 1 (package must be importable for the member to install and for `tests/test_replay_unit.py` to `from rosbagger_replay.source import ...`).
- **Issue:** The plan's artifact list names pyproject/errors/source but not `__init__.py`; an empty/absent package init would leave `import rosbagger_replay` undefined and the source/errors unreachable as package attributes.
- **Fix:** Created `__init__.py` re-exporting the two errors + `ReplayItem`/`load_items` (all ROS-free). It deliberately does NOT add the lazy `replay()` front door (that lands in Plan 03 per the plan's instruction not to reference the lazy `replay` function here).
- **Files modified:** `packages/rosbagger-replay/src/rosbagger_replay/__init__.py`
- **Commit:** `9232215`

## Notes on the no-ROS grep criterion

The plan's Task-2/Task-3 acceptance greps (`grep -v '^#' <file> | grep -c -E 'rclpy|rosbag2_py|rosidl'` → 0) are a proxy for "this module imports no ROS." `errors.py` and `source.py` contain ZERO ROS imports or code references — but their docstrings name `rclpy`/`rosbag2_py`/`rosidl_runtime_py` in prose to document the offline invariant and the publish path (the same documentation pattern as `rosbagger_record/errors.py`). The substantive requirement is verified two ways: (a) `grep -nE 'rclpy|rosbag2_py|rosidl' source.py` shows all matches are inside docstrings, and (b) the runtime check confirms `import rosbagger_replay` adds no `rclpy`/`rosbag2_py` to `sys.modules`. The `import`-statement grep for `errors.py` shows only `from __future__`.

## TDD Gate Compliance

Task 3 followed RED -> GREEN:
- RED: `cd31a7d` — `test(13-01)` failing source tests (collection error: source missing).
- GREEN: `ddc30a6` — `feat(13-01)` source.py; all 6 source tests pass.
- No REFACTOR commit (implementation was clean as written).

## Self-Check: PASSED

All created files exist on disk; all four commits are in `git log`.
