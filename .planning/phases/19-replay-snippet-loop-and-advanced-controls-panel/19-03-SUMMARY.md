---
phase: 19-replay-snippet-loop-and-advanced-controls-panel
plan: 03
status: complete
subsystem: rosbagger-desktop (Replay panel)
requirements: [REP-03]
tags: [replay, desktop, pyside6, region-loop, advanced-panel, thin-face]
provides:
  - "Collapsible Advanced sub-panel in the Replay tab (QToolButton header + QGroupBox body) with a Loop-region checkbox + Set-In/Set-Out buttons"
  - "Set-In/Out snap the region to the live playhead on BOTH the scrubber band and the scheduler; the checkbox toggles the scheduler region; scrubber.region_changed keeps them in sync"
  - "The region survives pause/seek/play — fractions stored on the panel + re-applied in _ensure_transport on the rebuilt Replayer + scrubber"
depends_on: [19-01, 19-02]
affects:
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
  - tests/test_desktop.py
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
    - tests/test_desktop.py
decisions:
  - "The durable unit is the FRACTION (_loop_in_frac/_loop_out_frac), converted to absolute t_ns at apply time via one _region_abs_ns helper (int(frac*bag_span_ns), the same basis seek uses) — so the region survives a transport rebuild where bag_span_ns is recomputed."
  - "Enabling region-loop (checkbox on, Set-In/Out, region_changed-while-active) calls _apply_region_to_scheduler which set_loop_region + seek(in_ns) so the cursor enters the region (the scheduler only wraps after passing t_out — 19-01 semantics)."
  - "Collapsible = a checkable QToolButton header toggling a QGroupBox body (arrow flips Right<->Down); starts collapsed so the main strip stays clean."
  - "region_changed (user drag) does NOT call scrubber.set_loop_region back (the scrubber already shows the band it emitted) — no feedback loop; programmatic paths (Set-In/Out, re-apply) DO set the scrubber."
metrics:
  duration: ~30min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 19 Plan 03: Advanced Sub-Panel + Region Wiring — Summary

Joined the two wave-1 deliverables (19-01 scheduler region + 19-02 Scrubber handles) into a usable control: a collapsible "Advanced" sub-panel in the Replay tab with a Loop-region toggle + Set-In/Set-Out buttons that snap to the live playhead, kept in sync with the scrubber handles and the scheduler, surviving pause/seek/play. Thin face preserved.

## What changed
- **`panels/replay_panel.py`**: added `QToolButton`/`QGroupBox` imports + `Qt`; a collapsible Advanced sub-panel (header + body) after `control_bar`; `_loop_in_frac`/`_loop_out_frac` durable state; handlers `_on_advanced_toggled`, `_on_set_in`/`_on_set_out` (via `_set_region_bound`), `_on_region_toggled`, `_on_region_changed`; helpers `_region_abs_ns` (fraction→absolute t_ns) + `_apply_region_to_scheduler` (set_loop_region + seek into region); a re-apply tail in `_ensure_transport`; accessor properties for tests. Status via the shared `set_status` (no inline color).
- **`tests/test_desktop.py`**: 5 new headless tests (commit `f3148d7`).

## Verification
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py -k "advanced_subpanel or set_in_out_read_position or loop_region_checkbox or region_changed_updates_scheduler or region_survives_pause_seek_play"` → 5 passed.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 20 passed (panel module top stays ROS-free AND Qt-free; rosbagger_replay imports stay lazy in methods).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **533 passed, 4 skipped, 86.90% coverage** (≥80% gate; captured via junitxml past the intermittent SIGBUS-at-exit teardown artifact).
- `ruff check` + `ruff format --check` on both files → clean.

## Deviations from plan
None. Followed RESEARCH §2c. Confirmed the fraction-as-durable-unit choice the plan's interface note recommended (avoids an absolute-vs-offset mismatch across rebuilds).

## Self-Check: PASSED
- `panels/replay_panel.py` (advanced sub-panel + Set-In/Out + region wiring + re-apply) — FOUND
- `tests/test_desktop.py` (5 sub-panel/region tests) — FOUND
- Commit `f3148d7` (feat 19-03) — FOUND
