---
phase: 21-replay-cli-parity-flags
status: passed
verified_by: inline (gsd-verifier agent not installed — verified by the orchestrator)
verified: 2026-05-29
requirements: [REP-05]
---

# Phase 21 Verification — Replay CLI Parity Flags

Verified against the four Success Criteria in `ROADMAP.md` (Phase 21 block), inline.

## Success Criteria

| SC | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| SC1 | `rosbagger-replay --help` exposes `--start-paused`, `--remap`, `--delay`, `--clock`, bounded-region options; each maps to the library with no new publish path | ✅ PASS | 21-02: `test_cli_replay_help_exposes_parity_flags` asserts `--clock/--delay/--remap/--start-paused/-p/--region-start/--region-end` in `--help` (exits 0, no ROS import). 21-01: each maps to a `replay()`/`build_publish_sink` param (no new publish path). |
| SC2 | `--remap` publishes on the remapped topic; `--start-paused` begins paused; `--delay` sleeps before play; the bounded region plays only `[in,out]` — proven by tests (live where publishing is required, unit where the mapping suffices) | ✅ PASS | 21-02: `test_cli_replay_forwards_parity_flags` + `test_cli_replay_remap_parses_pairs` (kwarg forwarding + `old:=new`→dict). 21-01: `test_scheduler_not_played_publishes_nothing` (start_paused→0 published, PAUSED); the `-m live` `test_remap_external_subscriber_receives_on_new_name` (subscriber on the new name receives). Region maps to `seek`+`set_loop_region` (repeat with `--loop`; single-pass stop deferred + documented). |
| SC3 | Deferred runtime-service controls documented as out-of-scope (not silently missing) | ✅ PASS | 21-02: the command docstring/help documents `~/seek`/`~/set_rate`/`~/play_next`/`~/burst`/`~/toggle_paused` + the single-pass region stop as deferred; `test_cli_replay_help_documents_deferred_services` asserts it. |
| SC4 | Offline/Qt-free guard green; CLI stays thin; full headless suite ≥80% | ✅ PASS | cli.py top level typer+stdlib only (ROS behind the lazy `replay_bag`); `tests/test_offline_guard.py` green; build_publish_sink stays the single publish path (remap = name lookup; 2-tuple back-compat). Full suite: **552 passed, 5 skipped, 87.79%** (junit: 557 tests, 0 failures/errors). |

## Gate evidence
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k cli` → 11 CLI tests green (5 new).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → green.
- Live remap/clock proofs collected-and-skipped offline; ROS-lane sign-off: `source /opt/ros/humble/setup.bash && uv run --with pyyaml pytest tests/test_replay_fidelity_live.py -m live`.
- Full blended (offline): 552 passed, 5 skipped, 87.79% (≥80%).
- ruff check + format → clean.

## Invariants held
- CLI thin (each flag maps to a library param; no publish logic in cli.py; top level typer+stdlib).
- `rosbagger_replay` ROS-free at module top; offline import graph ROS-free AND Qt-free.
- `build_publish_sink` single publish path (remap is a name lookup) with no-kwargs back-compat preserved; `scheduler.py` UNCHANGED.

## Commits
- `56e7124` feat(21-01): replay() CLI-parity params + build_publish_sink remap
- `fec544c` feat(21-02): rosbagger-replay CLI parity flags (+ the 21-0x docs commits)

## Result: PASSED — Phase 21 complete (REP-05). Milestone v0.5 (Replay Playback System) COMPLETE.
