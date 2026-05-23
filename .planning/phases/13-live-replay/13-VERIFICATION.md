---
status: passed
phase: 13-live-replay
verified: 2026-05-23
verifier: orchestrator-inline
reason: gsd-verifier agent not installed (agents_installed:false) and workflow.verifier_enabled=false; verified by independent offline-suite run + an independently-RE-RUN live lane (re-run a second time after the code-fix pass) + Success-Criteria trace + code review (0 critical; 7 warnings + IN-01 fixed)
score: 3/3 success criteria, 1/1 requirement (REP-01)
plans_complete: 3/3
---

# Phase 13: Live Replay — Verification

**Goal:** A live replayer (`rosbagger-replay`) — publish a bag's messages to real ROS topics with transport controls (play/pause/step/seek/rate/loop). Requires `rclpy`; the offline modules stay ROS-free.

## Verification method

`gsd-verifier` is not installed (`agents_installed: false`) and `verifier_enabled` is `false`. The orchestrator verified inline, in BOTH environments this phase requires:

1. **Offline suite** (`PYTHONPATH="" uv run pytest -q`, uv venv, ROS hidden): **460 passed, 2 skipped @ 97.37%** (gate ≥80% on `--cov=rosbagger_core --cov=bagq`; `rosbagger_replay` is out of the cov gate per D-12, mirroring `rosbagger-record`; the 2 skips are ROS-gated live tests, correctly `importorskip`/`-m live` guarded). `ruff check` + `format --check` clean (77 files); offline-import guard 17 passed; `uv sync --locked --dev` exit 0 (no re-lock — typer already declared).
2. **Live lane** (independently RE-RUN by the orchestrator with ROS sourced — not trusting the executor's self-report; re-run a SECOND time after the code-fix pass to confirm WR-04/WR-05's init/shutdown changes did not regress SC1): `source /opt/ros/humble/setup.bash && PYTHONPATH="<src trees>:$PYTHONPATH" python3 -m pytest tests/test_replay_live.py -m live` → **1 passed in ~3.2s** (production `replay_bag()` publishes → external subscriber subprocess receives). NOT collected-and-skipped — an actually-passing live run (Phase-12 W4 lesson).
3. **Goal-backward trace** of SC1/SC2/SC3 + REP-01 against shipped code and the live run.
4. **Code review** (`13-REVIEW.md`, deep depth, 7 files): **0 CRITICAL**, 7 WARNING, 6 INFO. The headline offline-import invariant was verified against the regression test (not docstrings): no module-top `rclpy`/`rosbag2_py`/`rosidl` import in any pure module. **All 7 warnings + IN-01 FIXED** (commits `654e87c`, `ef6e11b`, `0d8f009`, `89426a6`, `218e690`, `be9082b`) with a regression test for the WR-01 step-pacing fix; remaining Info items (IN-02/03/04/05/06) deferred as typing polish / test-timing.

## Success Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| SC1 | Replays a bag, publishing real ROS topics a subscriber receives | ✅ PASS | `replay.py` `replay_bag()` (production front door): v1 `source.load_items` raw CDR → `Replayer` scheduler → sink `get_message(msgtype)` + `rclpy.serialization.deserialize_message(raw, type)` + `create_publisher().publish()`. Live test drives the PRODUCTION `replay_bag(...)` in-process + an EXTERNAL subscriber subprocess (grep-pinned: shows `replay_bag(`, NO `Replayer(`/hand-built `create_publisher`) — subscriber receives the published messages. Actually run with ROS sourced. |
| SC2 | Transport controls work: play/pause/step/seek/rate/loop | ✅ PASS | `scheduler.py` pure `Replayer` state machine (PLAYING/PAUSED/STEPPING/DONE) + the six controls. Proven offline with a fake clock + recording sink (13 unit tests). `step()` now publishes immediately without pre-pacing the inter-message gap (WR-01 fix, test-locked). |
| SC3 | Rate scaling and seek land at the expected message/timestamp | ✅ PASS | Monotonic inter-message pacing scaled by `rate` (rate=2.0 halves the slept Δt, no first-publish pre-sleep); `seek(t_offset_ns)` lands the first item with `t_ns >= items[0].t_ns + t_offset_ns` (sole position-setter, no `start` ctor param, W3). Unit tests assert skipped items absent and slept Δt scales by rate. |

## Requirement traceability

| Requirement | Verdict | Where |
|-------------|---------|-------|
| REP-01 — live bag replay to ROS topics with transport controls (needs rclpy) | ✅ Complete | Plans 13-01 (package + raw-CDR source seam), 13-02 (pure transport scheduler), 13-03 (lazy ROS boundary + rclpy publish front door + thin CLI + live SC1 proof) |

## must_haves (goal-backward)

- ✅ A real subscriber receives messages published from a bag via the PRODUCTION front door (live lane proven, re-run twice).
- ✅ All six transport controls work; rate/seek land at the expected message/timestamp (deterministic offline proof).
- ✅ **Offline guarantee preserved** — `rosbagger_core`/`bagq` import NO rclpy; `rosbagger_replay` and its pure submodules (`source.py`/`scheduler.py`/`errors.py`/`__init__.py`) lazy-isolate rclpy and import clean in the ROS-free uv venv (independently confirmed: `import rosbagger_replay` leaves `rclpy`/`rosbag2_py` out of `sys.modules`); offline-guard extended. `replay()` raises a teaching capability error when ROS is absent.
- ✅ Thin CLI / API-first; raw-CDR source is the v1 `rosbags` reader (D-05; `rosbag2_py` SequentialReader fails on rosbags-written fixtures).
- ✅ Re-entrant safety hardened (WR-04): `replay()` only `init()`/`shutdown()`s the rclpy context it created — protects the Phase-14 GUI as a long-lived-context caller.

## Decision coverage

All locked CONTEXT decisions (D-01..D-12) implemented and traceable: pure source/scheduler split, lazy rclpy boundary, raw-CDR via v1 reader (D-05), the verified `get_message`+`deserialize_message`+`publish` sink (D-04), `--end` folded into `--duration` (D-10/W5), `rosbagger_replay` out of the cov gate (D-12). No deferred idea (per-topic QoS, GUI, multi-bag) leaked into scope.

## Code-review resolution

`13-REVIEW.md`: 0 critical, 7 warning, 6 info. All 7 warnings fixed + IN-01 (fragile class-name detection → lazy `isinstance`) hardened. WR-05 used `contextlib.suppress(Exception)` instead of bare `try/except pass` (ruff SIM105). Offline suite + the live lane both re-verified green after the fixes. Info nits IN-02/03/04/05/06 (typing polish, test-timing) deferred — no correctness impact.

---
*Verified 2026-05-23 — orchestrator-inline. REP-01 Complete. Phase 13 (Live Replay) ships `rosbagger-replay`, rosbagger's second LIVE module: a bag → ROS-topic publisher with full transport controls, offline-clean except for the single lazy rclpy publish module.*
