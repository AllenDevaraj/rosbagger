# 23-02 SUMMARY — ±5s skip + ReplayPanel remote-control API

**Status:** Complete · **Requirement:** VIZ-SKIP · **Date:** 2026-06-06

## What shipped
- **`‹ 5s` / `5s ›` skip buttons** on the Replay control bar (after Step). `_skip(delta_s)` reads the
  live time cursor (`position_fraction * _bag_span_ns`), seeks to `clamp(cur ± 5s, 0, span)` over the
  thread-safe `Replayer.seek`, updates the playhead, re-primes static topics when the fidelity toggle
  is on (same as `_on_seeked`), and shows "Skipped to N%." Works while playing or paused; distinct from
  the single-message **Step**.
- **Remote-control API** on `ReplayPanel` for the compact overlay (23-04), all thin wrappers over
  existing handlers — no new transport logic:
  - `positionChanged = Signal(float)` emitted in `_update_position` after `scrubber.set_position`.
  - `skip_back()` / `skip_forward()` → `_skip(∓5)`.
  - `toggle_play()` → pause if `_genuinely_playing()` else play.
  - `seek_fraction(f)` → `_on_seeked(f)`.
  - `current_fraction()` → `position_fraction` (0.0 with no transport).
- Accessors `skip_back_button` / `skip_forward_button`.

## Files
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py` — `Signal` import, class `positionChanged`, skip buttons + wiring + accessors, `_skip`, the 5 public API methods, `_update_position` emit.
- `tests/test_desktop.py` — skip buttons present; ±5s relative seek + end clamp; `toggle_play` flips; `positionChanged` emitted + `current_fraction`.

## Verification
- Full offline suite: **583 passed, 6 skipped, coverage 88.18%** (≥80%); ruff + format clean.
- `import rosbagger_desktop.panels.replay_panel` stays ROS-free (no new module-top ROS import; `republish_static` lazy inside `_skip`).
- **Live sign-off (user):** `5s ›`/`‹ 5s` jump the playhead ±5s with RViz/Rerun reflecting it.
