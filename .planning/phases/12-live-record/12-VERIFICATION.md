---
status: passed
phase: 12-live-record
verified: 2026-05-23
verifier: orchestrator-inline
reason: gsd-verifier agent not installed (agents_installed:false) and workflow.verifier_enabled=false; verified by independent offline-suite run + an independently-RE-RUN live lane + Success-Criteria trace + code review (0 critical; 4 warnings fixed)
score: 3/3 success criteria, 1/1 requirement (REC-01)
plans_complete: 3/3
---

# Phase 12: Live Record — Verification

**Goal:** A live recorder (`rosbagger-record`) — discover live ROS topics and record a selected subset to a bag (MCAP via rosbag2_py). Requires rclpy; the offline modules stay ROS-free.

## Verification method

`gsd-verifier` is not installed (`agents_installed: false`) and `verifier_enabled` is `false`. The orchestrator verified inline, in BOTH environments this phase requires:

1. **Offline suite** (`PYTHONPATH="" uv run pytest -q`, uv venv, ROS hidden): **433 passed, 1 skipped @ 97.37%** (gate ≥80%; the 1 skip is the live test, correctly `importorskip`-gated). `ruff check`+`format` clean (69 files); offline-import guard 15 passed; `uv sync --locked --dev` exit 0.
2. **Live lane** (independently RE-RUN by the orchestrator with ROS sourced — not trusting the executor's self-report): `source /opt/ros/humble/setup.bash && PYTHONPATH="<src trees>:$PYTHONPATH" python3 -m pytest tests/test_record_live.py -m live` → **2 passed, 1 skipped** (publisher → record → re-open). The skip is the MCAP variant (`skipif` on `get_registered_writers()` — the MCAP storage plugin is not installed on this box).
3. **Goal-backward trace** of SC1/SC2/SC3 + REC-01 against shipped code and the live run.
4. **Code review** (`12-REVIEW.md`, standard depth, 10 files): **0 CRITICAL**, 4 WARNING, 4 INFO. The headline offline-import invariant was verified against the regression test (not docstrings). **All 4 warnings FIXED** (`a4e9ae3`) with regression tests; Info items deferred.

## Success Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| SC1 | Discovers currently-published live topics | ✅ PASS | `discovery.py` `discover_topics` over `rclpy` `get_topic_names_and_types()`; `rosbagger-record list` prints them. Live test asserts `/telemetry` is discovered against a real publisher. |
| SC2 | Records a selected subset while a publisher runs | ✅ PASS | `record.py`: discover → select → `create_subscription(..., raw=True)` (CDR bytes) → `rosbag2_py.SequentialWriter` → bounded stop (`--duration`/`--max-messages`) + graceful SIGINT → `finally: writer.close()`. Live test records exactly 5 frames of `/telemetry` to a sqlite3 bag while an external rclpy publisher runs. |
| SC3 | Recorded bag re-opens + iterates via the v1 reader | ✅ PASS | Live test re-opens the recorded bag with `RosbagsReader(out, default_typestore=ROS2_HUMBLE)` and iterates — asserts 5 messages, all on `/telemetry`. (sqlite3 needs the typestore; MCAP self-describes — variant skipif-guarded.) The offline↔live loop closes through the EXISTING reader. |

## Requirement traceability

| Requirement | Verdict | Where |
|-------------|---------|-------|
| REC-01 — live topic discovery + select recording (needs rclpy) | ✅ Complete | Plans 12-01 (package + discovery/selection), 12-02 (rclpy/rosbag2_py record core), 12-03 (thin CLI + live SC1/SC2/SC3 proof) |

## must_haves (goal-backward)

- ✅ Live discovery + subset recording works against a real ROS graph (live lane proven).
- ✅ Recorded bag re-opens + iterates via the v1 reader (offline↔live contract).
- ✅ **Offline guarantee preserved** — `rosbagger_core`/`bagq` import NO rclpy/rosbag2_py; `rosbagger_record` lazy-imports them and imports clean in the ROS-free uv venv (independently confirmed: `import rosbagger_record` / `.record` leave `rclpy`/`rosbag2_py` out of `sys.modules`); offline-guard extended. `record()` raises a teaching capability error when ROS is absent.
- ✅ Thin CLI / API-first; `--storage` parse-time constrained to {mcap, sqlite3}.

## Decision coverage

All 11 locked CONTEXT decisions (D-01..D-11; D-08 refined to MCAP-default + sqlite3 capability escape) implemented and traceable. No deferred idea (replay, GUI, QoS, compression, split, general multi-format, rosbag2_py reader backend) leaked into scope.

## Code-review resolution

| Finding | Severity | Disposition |
|---------|----------|-------------|
| WR-01 — `--duration 0` silently unbounded (truthiness trap) | Warning | **FIXED** (`a4e9ae3`) — `if duration is not None` + regression test |
| WR-02 — wall-clock deadline (clock-step breaks the bound) | Warning | **FIXED** — `time.monotonic()` deadline |
| WR-03 — `_run` (duration path) untested | Warning | **FIXED** — offline mocked `_run` tests (incl. duration-0 lock) |
| WR-04 — empty selection → raw traceback | Warning | **FIXED** — `NoTopicsMatchedError` teaching error + clean Exit(1) + CliRunner test |
| IN-01..04 | Info | Deferred (minor — direct-call ImportError, fixed discovery settle, no output-path guard, writers container contract) |

## Environment notes / follow-ups (non-blocking)

- **MCAP storage plugin absent on this box** (`get_registered_writers()` → `{sqlite3, ...}`; `ros-humble-rosbag2-storage-mcap` needs `sudo`). SC2/SC3 were proven via the in-scope **sqlite3 capability escape** (D-08 refined); the MCAP-default path is `skipif`-guarded. Optional human follow-up: `sudo apt install ros-humble-rosbag2-storage-mcap` to exercise the MCAP variant.
- The live test runs only in a **ROS-sourced lane** (not `PYTHONPATH="" uv run`); the offline CI skips it cleanly. A ROS CI lane (or local run) is needed to exercise SC2/SC3 in CI.

## Verdict

**PASSED** — 3/3 success criteria (live lane independently re-run: 2 passed, 1 skipped), 1/1 requirement, 3/3 plans complete, 0 code-review blockers (4 warnings fixed). The offline guarantee held through rosbagger's first live phase. No regressions in the offline suite.
