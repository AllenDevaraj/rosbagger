---
phase: 20-replay-rviz-fidelity-clock-and-static-republish
plan: 03
status: complete
subsystem: rosbagger-desktop (Replay panel)
requirements: [REP-04]
tags: [replay, desktop, pyside6, rviz-fidelity, clock, static-republish, thin-face]
provides:
  - "Advanced sub-panel toggles: 'Publish /clock' + 'Re-publish static on seek' (default OFF), threaded into build_publish_sink at transport build"
  - "_on_seeked re-primes static topics via republish_static(self._sink) AFTER the seek when the toggle is on"
depends_on: [20-01, 20-02]
affects:
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
  - tests/test_desktop.py
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
    - tests/test_desktop.py
decisions:
  - "Kept self._sink on the panel (set in _ensure_transport, cleared in _teardown_transport) so _on_seeked can reach sink.tracker for republish_static — the sink wasn't retained before."
  - "Both toggles default OFF and _ensure_transport passes publish_clock=False + static_topics=frozenset() when off, preserving today's exact call shape (proven by a defaults-off spy test)."
  - "republish is a purely additive tail in _on_seeked guarded by the toggle + a non-None sink; the Phase-18 seek/position/status and Phase-19 region-loop seek are untouched."
metrics:
  duration: ~25min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 20 Plan 03: Desktop Fidelity Toggles — Summary

Surfaced the Phase-20 opt-ins in the desktop Replay panel's Phase-19 Advanced sub-panel (REP-04) — the thin Qt face over the 20-02 library mechanism.

## What changed
- **`replay_panel.py`**: two `QCheckBox`es ("Publish /clock", "Re-publish static on seek") in `_advanced_body`, default OFF + accessor properties; `_ensure_transport` threads `publish_clock`/`static_topics` into `build_publish_sink` and stores `self._sink` (cleared in `_teardown_transport`); `_on_seeked` calls `republish_static(self._sink)` after the seek when the static toggle is on (lazy import; no-op otherwise).
- **`tests/test_desktop.py`**: 6 headless tests (commit `1109768`).

## Verification
- Targeted: 6 passed.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 21 passed (panel module top stays ROS-free AND Qt-free; the new republish_static import stays lazy in `_on_seeked`).
- Full blended: **546 passed, 5 skipped, 87.79% coverage** (junitxml: 551 tests, 0 failures/0 errors; clean on a re-run past the intermittent Qt SIGBUS-at-exit).
- ruff check + format → clean.

## Deviations from plan
None.

## Self-Check: PASSED
- `replay_panel.py` (clock/static toggles + kwargs threading + post-seek republish) — FOUND
- `tests/test_desktop.py` (6 fidelity-toggle tests) — FOUND
- Commit `1109768` (feat 20-03) — FOUND
