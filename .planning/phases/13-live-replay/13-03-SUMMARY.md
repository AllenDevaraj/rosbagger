---
phase: 13-live-replay
plan: 03
subsystem: rosbagger-replay
tags: [live-publish, rclpy, lazy-ros-boundary, cli, typer, offline-guard, sc1, two-tier-test]
requires:
  - "rosbagger_replay.source.load_items (Plan 13-01 — the time-ordered raw-CDR ReplayItem stream)"
  - "rosbagger_replay.scheduler.Replayer (Plan 13-02 — the pure transport state machine the sink injects into)"
  - "rosbagger_replay.errors.RosNotAvailableError / NoMessagesToReplayError (Plan 13-01 — teaching capability errors)"
provides:
  - "rosbagger_replay.replay / replay_bag — the lazy ROS-bound publish front door (the SINGLE production publish path)"
  - "rosbagger_replay.replay.replay — the rclpy publish SINK (init/shutdown + per-topic create_publisher + get_message + deserialize_message + publish)"
  - "the thin rosbagger-replay CLI (cli.py) over the package API"
  - "tests/test_replay_live.py — the LIVE SC1 integration test (production replay_bag() publishes, external subscriber subprocess receives)"
  - "tests/test_offline_guard.py extension proving import rosbagger_replay (+ submodules) leak no rclpy/rosbag2_py"
affects:
  - "Phase 14 (GUI Replay panel capability-gates over this same replay_bag() API)"
tech-stack:
  added: []
  patterns:
    - "Lazy _require_ros boundary mirroring rosbagger_record/__init__.py: replay() front door + submodule-shadow-proof replay_bag alias; replay.py is the ONLY rclpy module"
    - "VERIFIED publish path: get_message(type_str) -> create_publisher(cls, topic, 10) -> deserialize_message(cdr, cls) -> publish (D-04, Pattern 4)"
    - "Pure scheduler + injectable rclpy sink (D-06 payoff): the sink is a ~15-line closure injected into the pure Replayer; --start seconds maps to seek(int(start*1e9)) (W3, no scheduler start kwarg)"
    - "Two-tier test: offline CLI/parse tests (ROS mocked via attribute-patch) + LIVE SC1 (importorskip(rclpy) + live marker; production front door in-process publisher, external subscriber subprocess)"
    - "D-10 --end FOLDED into --duration with documented rationale (W5) — locked flag accounted for, not silently dropped"
key-files:
  created:
    - "packages/rosbagger-replay/src/rosbagger_replay/replay.py"
    - "packages/rosbagger-replay/src/rosbagger_replay/cli.py"
    - "tests/test_replay_live.py"
  modified:
    - "packages/rosbagger-replay/src/rosbagger_replay/__init__.py (lazy _require_ros + replay/replay_bag front door)"
    - "tests/test_replay_unit.py (added the CLI test section: parse/forward + Exit(1) + --end-fold help assertion)"
    - "tests/test_offline_guard.py (added test_import_replay_does_not_pull_ros + submodule guard)"
key-decisions:
  - "replay.py is the ONLY ROS-bound module (owns rclpy.init/shutdown, the per-topic publisher dict, the sink, seek, finally-cleanup) — the single production publish front door"
  - "D-10 --end folded into --duration (v1 scheduler bounds on monotonic duration / max_messages, not a bag-timestamp horizon); true --end deferred, documented in help + a module comment (W5)"
  - "CLI is a single typer command (typer flattens it): invoked as `rosbagger-replay <bag> [opts]`; `rosbagger-replay --help` and `rosbagger-replay replay --help` both work"
  - "rosbagger_replay stays OUT of the --cov gate (D-12) — the live publish path is live-only; the pure scheduler+source are unit-covered"
patterns-established:
  - "Pattern: lazy ROS front door + submodule-shadow-proof alias (replay_bag) mirroring rosbagger_record"
  - "Pattern: live SC1 via the PRODUCTION front door in-process + an EXTERNAL actor subprocess (Phase-12 pattern inverted — publisher in-process, subscriber external)"
requirements-completed: [REP-01]
duration: ~8min
completed: 2026-05-23
---

# Phase 13 Plan 03: Live replay front door + sink + CLI + SC1 test Summary

**The lazy `_require_ros` boundary + the rclpy publish front door (`replay.py`: init/shutdown, per-topic `create_publisher`, `get_message` + `deserialize_message` + `publish`) + a thin `rosbagger-replay` CLI + the LIVE SC1 test (production `replay_bag()` publishes, an external subscriber subprocess receives) — completing REP-01 end-to-end.**

## IMPORTANT — Live lane still needs the orchestrator to RUN it

This plan BUILT and offline-verified everything, but **SC1 is NOT yet signed off**. Per D-11/W4 (Phase-12 lesson), a collected-and-skipped live test is insufficient — **the orchestrator MUST actually run the ROS-sourced live lane** and confirm the SC1 test PASSES (not skipped):

```
source /opt/ros/humble/setup.bash && \
PYTHONPATH="packages/rosbagger-replay/src:packages/rosbagger-core/src:$PYTHONPATH" \
  python3 -m pytest tests/test_replay_live.py -m live -v
```

Expected: `test_sc1_replay_bag_publishes_external_subscriber_receives PASSED` — the external subscriber subprocess received the 3 `/imu` messages the production `replay_bag()` front door published. Until that passes, REP-01's live SC1 proof is pending (everything else — the offline tier — is green).

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-05-23T20:59:40Z
- **Tasks:** 3
- **Files modified:** 5 (2 created src + 1 created test; 1 src + 2 tests modified)

## Accomplishments

- **`__init__.py` lazy boundary** — `_require_ros()` imports `rclpy` inside its body and raises the teaching `RosNotAvailableError`; `replay()` is the lazy delegator to `.replay`; `replay_bag = replay` is the submodule-shadow-proof alias. NO top-level `rclpy`/`rosidl` import; `import rosbagger_replay` stays ROS-free.
- **`replay.py` — the ONLY rclpy module** (VERIFIED publish path, D-04/Pattern 4): loads the CDR stream via `load_items`, raises `NoMessagesToReplayError` BEFORE `rclpy.init()` on empty selection (WR-04), then in a try/finally owns `rclpy.init()`/`shutdown()`, builds a per-topic `(cls, publisher)` dict lazily, wires the sink (`get_message` → `create_publisher(cls, topic, 10)` → `deserialize_message(cdr, cls)` → `publish`), maps `--start` seconds to `replayer.seek(int(start*1e9))` (W3 — no scheduler `start` kwarg), drives the pure `Replayer`, and returns the published count.
- **Thin `rosbagger-replay` CLI** — a single `replay` typer verb over `replay_bag`, `@_capability_errors` presenting `RosNotAvailableError`/`NoMessagesToReplayError` as a clean `Exit(1)` (no traceback, no bare `except Exception`). Top imports are typer-only (no ROS). D-10's `--end` is folded into `--duration` with the rationale documented in both the `--duration` help text and a module-level comment (W5).
- **Offline-guard extension** — `test_import_replay_does_not_pull_ros` (fresh `PYTHONPATH=""` subprocess) + a submodule guard proving `import rosbagger_replay.scheduler`/`.source` leak no `rclpy`/`rosbag2_py`.
- **LIVE SC1 test** — `tests/test_replay_live.py`: the PRODUCTION `replay_bag()` runs in-process as the publisher; an EXTERNAL subscriber subprocess (its own `rclpy` context, no double-init clash) subscribes to `/imu`, counts, and reports back. Grep-verified BLOCKER-1 contract: shows `replay_bag(`, NO `Replayer(` / hand-built `create_publisher` in the test.

## Task Commits

1. **Task 1: Lazy ROS boundary (`__init__.py`) + rclpy publish sink (`replay.py`)** — `494dd09` (feat)
2. **Task 2: Thin CLI (`cli.py`) + CLI unit tests + offline-guard extension** — `7d05877` (feat)
3. **Task 3: LIVE SC1 integration test (`tests/test_replay_live.py`)** — `eb43821` (test)

**Plan metadata:** (this commit) — docs: complete plan

## Files Created/Modified

- `packages/rosbagger-replay/src/rosbagger_replay/__init__.py` — lazy `_require_ros` + `replay`/`replay_bag` front door; no top-level ROS import.
- `packages/rosbagger-replay/src/rosbagger_replay/replay.py` — the ONLY rclpy module: init/shutdown, per-topic publisher dict, the VERIFIED `get_message`+`deserialize_message`+`publish` sink, `--start`→`seek`, finally-cleanup.
- `packages/rosbagger-replay/src/rosbagger_replay/cli.py` — thin typer `replay` verb over `replay_bag`; `@_capability_errors` → clean `Exit(1)`; D-10 `--end` folded into `--duration` (W5).
- `tests/test_replay_unit.py` — added the CLI test section (parse/forward flags, `--end`-fold help assertion, `NoMessagesToReplayError`→`Exit(1)`).
- `tests/test_offline_guard.py` — `test_import_replay_does_not_pull_ros` + submodule guard.
- `tests/test_replay_live.py` — the LIVE SC1 test (importorskip + live marker; production front door + external subscriber subprocess).

## How to Verify

- **Offline front door:** `PYTHONPATH="" uv run python -c "import rosbagger_replay as r; assert callable(r.replay) and callable(r.replay_bag)"` → exits 0; calling `r.replay('/tmp/nope')` raises `RosNotAvailableError` offline (verified, prints `ok`).
- **CLI tests:** `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k cli -q` → 5 passed.
- **Offline guard:** `PYTHONPATH="" uv run pytest tests/test_offline_guard.py -q` → 17 passed (15 prior + 2 new replay guards).
- **Console script:** `PYTHONPATH="" uv run rosbagger-replay --help` and `... replay --help` both exit 0; `--help` documents `--end` folded into `--duration`.
- **Live test collected-and-skipped offline:** `PYTHONPATH="" uv run pytest tests/test_replay_live.py -q` → `1 skipped` (importorskip(rclpy)).
- **Full offline suite:** `PYTHONPATH="" uv run pytest -q` → **459 passed, 2 skipped @ 97.37%** (≥80% gate on core+bagq held; rosbagger_replay excluded per D-12).
- **ruff:** `PYTHONPATH="" uv run ruff check . && ruff format --check .` → clean (77 files).
- **BLOCKER-1 grep:** `grep -n "replay_bag(" tests/test_replay_live.py` shows the call; `grep "Replayer(\|create_publisher" tests/test_replay_live.py` → NONE.
- **LIVE SC1 (orchestrator MUST run — see the IMPORTANT note above):** the ROS-sourced lane confirms the SC1 test PASSES, not skipped.

## Decisions Made

- **replay.py is the single production publish path** — the CLI, the Phase-14 GUI, and the SC1 live test all call it through the `__init__` front door; there is no second publish path (so the live test exercises the shipped wiring, BLOCKER-1).
- **D-10 `--end` folded into `--duration` (W5)** — the v1 scheduler bounds on monotonic duration / `max_messages`, not a bag-timestamp horizon; a true absolute/relative `--end` would need a `t_ns`-relative stop predicate the scheduler does not expose. Folded (not dropped): documented in the `--duration` help + a module comment. A true `--end` is a noted deferred enhancement; the stop-early capability ships via `--duration`/`--max-messages`.
- **Single-command typer CLI flattens** — the app has one `replay` command, so typer invokes it as `rosbagger-replay <bag> [opts]` (the command name is optional). Both `rosbagger-replay --help` and `rosbagger-replay replay --help` work; the flat `--help` shows the BAG positional + all options including the `--end`-fold note.

## Deviations from Plan

**1. [Rule 1 — Bug] CLI invocation form: single-command typer flattening (test-only adjustment)**
- **Found during:** Task 2 (the CLI parse/forward tests first invoked `["replay", "/tmp/bag", ...]`, which failed with `exit 2: Got unexpected extra argument` because a single-command typer app FLATTENS the verb away — `replay` becomes the implicit command and the BAG positional is supplied directly).
- **Issue:** The plan's acceptance examples wrote `replay BAG --rate ...` as if `replay` were a subcommand token; with one command typer collapses it, so `replay` is not a passed token for the actual run (only `--help` accepts the optional command name).
- **Fix:** Updated the CLI tests to invoke the flat form (`["/tmp/bag", "--rate", "5", ...]`) — the real console-script invocation. `--help` assertions use the flat `["--help"]` (which still shows everything, including the `--end`-fold note). Production `cli.py` is unchanged; this is a test-invocation correction matching the shipped behavior. Both `rosbagger-replay --help` and `rosbagger-replay replay --help` still exit 0 (verified), so the plan's console-script acceptance grep holds.
- **Files modified:** `tests/test_replay_unit.py`
- **Commit:** `7d05877`

---

**Total deviations:** 1 (test-invocation correction; no production behavior change, no scope creep).
**Impact on plan:** None on delivered behavior — the CLI parses/forwards every D-10 flag and presents capability errors cleanly exactly as specified.

## Issues Encountered

- One ruff `E501` (long `--loop` help line) and one `I001` (import sort in the live test) — both fixed inline (line wrap / `ruff check --fix`) before their task commits. No functional impact.

## Next Phase Readiness

- **REP-01 is built end-to-end** — the offline tier is fully green and the live SC1 test is in place. **Pending: the orchestrator runs the ROS-sourced live lane to sign off SC1** (see the IMPORTANT note). Until then, mark REP-01 In Progress / pending-live-proof rather than fully Complete.
- Phase 14 (GUI Replay panel) capability-gates over the `replay_bag()` API delivered here — the front door + the six controls (via the pure `Replayer`) are ready.
- Standing blocker unchanged: HUMAN must `git push origin main && git push origin v0.1.0` + observe CI green to finalize the v0.1 release.

## Self-Check: PASSED

- `packages/rosbagger-replay/src/rosbagger_replay/__init__.py` — FOUND
- `packages/rosbagger-replay/src/rosbagger_replay/replay.py` — FOUND
- `packages/rosbagger-replay/src/rosbagger_replay/cli.py` — FOUND
- `tests/test_replay_live.py` — FOUND
- Commit `494dd09` (Task 1 feat) — FOUND
- Commit `7d05877` (Task 2 feat) — FOUND
- Commit `eb43821` (Task 3 test) — FOUND

---
*Phase: 13-live-replay*
*Completed: 2026-05-23*
