---
phase: 19-replay-snippet-loop-and-advanced-controls-panel
status: passed
verified_by: inline (gsd-verifier agent not installed — verified by the orchestrator)
verified: 2026-05-29
requirements: [REP-03]
---

# Phase 19 Verification — Replay Snippet Loop & Advanced Controls Panel

Verified against the four Success Criteria in `ROADMAP.md` (Phase 19 block), inline (the
`gsd-verifier` subagent is not installed — `missing_agents` in init JSON).

## Success Criteria

| SC | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| SC1 | `Replayer` supports a loop region: playing wraps from `t_out` back to `t_in` (NOT index 0); clears cleanly to whole-bag/no-loop — unit tests | ✅ PASS | 19-01: 8 region tests in `tests/test_replay_unit.py` (`test_scheduler_region_*`) — wrap repeats, region+max_messages → bound-wins-DONE (W4), clear restores whole-bag loop AND no-loop DONE, region precedence over `_loop`, in-bound-past-end → DONE, thread-safe mid-run set. |
| SC2 | The `Scrubber` shows a shaded loop region with two draggable In/Out handles, AND Set-In/Set-Out set the region from the current playhead — headless test | ✅ PASS | 19-02: shaded band + two handle bars painted from theme tokens; `region_changed` on a user handle drag (`test_scrubber_handle_drag_emits_region_changed`). 19-03: `test_replay_set_in_out_read_position_fraction_and_set_both` drives Set-In/Out from `position_fraction` onto the scrubber + scheduler. |
| SC3 | Advanced controls live in a collapsible side sub-panel inside the Replay tab (region loop + Set-In/Out), themed via Phase-17 tokens, accessible status preserved | ✅ PASS | 19-03: `test_replay_advanced_subpanel_exists_and_toggles` (collapsible QToolButton header + QGroupBox body); region colours are NEW theme tokens (`region_fill`/`region_handle`, no inline hex); status via the shared `set_status` (accessible affordance preserved). |
| SC4 | Region survives pause/seek/play; offline/Qt-free guard green; full headless suite ≥80% | ✅ PASS | 19-03: `test_replay_region_survives_pause_seek_play_cycle` (re-applied in `_ensure_transport`). `tests/test_offline_guard.py` → 20 passed. Full suite: **533 passed, 4 skipped, 86.90% coverage**. |

## Gate evidence
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py` → 38 passed (30 prior + 8 region).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py` → all replay/scrubber/region tests green.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 20 passed.
- Full blended: 533 passed, 4 skipped, 86.90% (≥80%) — captured via junitxml past the intermittent Qt-offscreen SIGBUS-at-exit teardown artifact (a re-run produced exit 0).
- `ruff check` + `ruff format --check` on all changed files → clean.

## Invariants held
- Scheduler stdlib-only (region reuses the 18-01 lock + wake; W3/W4/WR-01/WR-02/Pitfall-6/D-08/step + thread-safety preserved — full prior suite unchanged).
- `rosbagger_replay` ROS-free at module top; offline import graph ROS-free AND Qt-free.
- Scrubber + panel offline/Qt-clean + thin face; `build_publish_sink` untouched.
- No inline color — region/handle colours are theme tokens; status via `set_status`.
- Phase-18 live scrubbing (playhead poll, drag-while-playing seek, live rate/loop) intact.

## Commits
- `702bcdd` feat(19-01): in/out region loop on the pure Replayer
- `34205da` feat(19-02): Scrubber dual In/Out region handles + shaded band
- `f3148d7` feat(19-03): collapsible advanced sub-panel + Set-In/Out region wiring
  (+ the 19-0x docs commits)

## Result: PASSED — Phase 19 complete (REP-03).
