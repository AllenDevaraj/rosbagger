---
phase: 20-replay-rviz-fidelity-clock-and-static-republish
status: passed
verified_by: inline (gsd-verifier agent not installed — verified by the orchestrator)
verified: 2026-05-29
requirements: [REP-04]
---

# Phase 20 Verification — Replay RViz Fidelity (/clock + static republish)

Verified against the four Success Criteria in `ROADMAP.md` (Phase 20 block), inline (gsd-verifier not installed).

## Success Criteria

| SC | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| SC1 | With clock publishing enabled, `/clock` is published carrying bag-relative time during replay — live test | ✅ PASS (offline-built + live-proof authored) | 20-02: `build_publish_sink(publish_clock=True)` emits `Clock(.clock=clock_stamp_ns(item.t_ns))` per publish; `tests/test_replay_fidelity_live.py::test_sc1_clock_published_external_subscriber_receives` (`-m live`, external `/clock` subscriber) is the ROS-lane proof. `clock_stamp_ns` proven pure-unit (20-01). |
| SC2 | After a seek, latched/`transient_local` topics (and `/tf_static`) seen before the seek are re-published so a fresh subscriber re-primes — live OR unit (SC explicitly allows unit) | ✅ PASS | 20-01: `StaticTracker` unit tests (latest-per-static-topic, republish set) — the deterministic CI route. 20-02: `republish_static(sink)` + the `-m live` `test_sc2_static_republished_after_seek_external_subscriber_receives`. 20-03: the desktop `_on_seeked` re-prime path (ordering test). |
| SC3 | Both behaviors opt-in via the side sub-panel + matching CLI flags; defaults unchanged (clock off) | ✅ PASS (UI + library halves; CLI flags are Phase 21) | 20-02: opt-in keyword args on `build_publish_sink`, default off (back-compatible 2-tuple). 20-03: "Publish /clock" + "Re-publish static on seek" toggles in the Advanced sub-panel, default OFF, threaded into the sink (spy tests); defaults-off preserves today's call. The matching CLI flag (`--clock`) is Phase 21's scope (the library mechanism + GUI toggles ship here). |
| SC4 | Offline/Qt-free guard green; `import rosbagger_replay` stays ROS-free; full headless suite ≥80% | ✅ PASS | `fidelity.py` stdlib-only; the `/clock`/tracker live code + the panel's `republish_static` import stay lazy. `tests/test_offline_guard.py` → 21 passed (incl. the new fidelity ROS-free assertion). Full suite: **546 passed, 5 skipped, 87.79% coverage** (junit: 551 tests, 0 failures/errors). |

## Gate evidence
- `PYTHONPATH="" uv run pytest tests/test_replay_fidelity.py` → 6 passed (pure StaticTracker + clock_stamp_ns).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 21 passed.
- `tests/test_replay_fidelity_live.py` collected-and-skipped offline (importorskip rclpy); the `-m live` SC1/SC2-live proof runs in the ROS-sourced lane (`source /opt/ros/humble/setup.bash && uv run --with pyyaml pytest tests/test_replay_fidelity_live.py -m live`).
- Full blended (offline): 546 passed, 5 skipped, 87.79% (≥80%).
- ruff check + format → clean on all changed files.

## Invariants held
- `rosbagger_replay` ROS-free at module top; offline import graph ROS-free AND Qt-free.
- `build_publish_sink` stays the SINGLE publish path (extended, opt-in, back-compatible 2-tuple); `scheduler.py` UNCHANGED (static re-publish is a publish-path concern around seek).
- Desktop panel thin face; no inline color; Phase-18 live scrubbing + Phase-19 region loop intact.
- Defaults OFF — today's behavior unchanged unless explicitly enabled.

## Commits
- `90380b1` feat(20-01): pure RViz-fidelity decision tier (StaticTracker + clock_stamp_ns)
- `bf2394c` feat(20-02): opt-in /clock + static re-publish on the single publish sink
- `1109768` feat(20-03): desktop RViz-fidelity toggles (+ the 20-0x docs commits)

## Result: PASSED — Phase 20 complete (REP-04).
