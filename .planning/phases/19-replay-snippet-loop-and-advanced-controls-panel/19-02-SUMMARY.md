---
phase: 19-replay-snippet-loop-and-advanced-controls-panel
plan: 02
status: complete
subsystem: rosbagger-desktop (Scrubber widget + theme tokens)
requirements: [REP-03]
tags: [replay, desktop, pyside6, scrubber, region-handles, theme-tokens, offline-clean]
provides:
  - "Scrubber dual In/Out loop-region handles: set_loop_region/clear_loop_region (programmatic, silent) + a loop_region read prop + region_changed(in,out) emitted ONLY on a user handle drag"
  - "Shaded region band + two handle bars painted from NEW theme tokens (region_fill/region_handle) — no inline hex"
  - "A press far from a handle falls through to the base QSlider playhead seek (Phase-18 live scrubbing preserved)"
depends_on: []
affects:
  - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/theme/tokens.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/theme/qss.py
  - tests/test_desktop.py
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/tokens.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/qss.py
    - tests/test_desktop.py
decisions:
  - "Region/handle colours added as Tokens fields (region_fill/region_handle, DARK+LIGHT, OKLCH-authored) and surfaced via a theme.qss.region_colors(tokens=DARK) accessor — the Scrubber paints with QPainter (not QSS) so it resolves the token VALUES through the accessor (default DARK, the app's default theme) rather than inlining hex (D-03)."
  - "scrubber.py imports ..theme.qss (which imports ..theme.tokens) — both are PySide6-free pure Python, so the Scrubber stays offline/Qt-clean and the offline guard stays green (no import cycle: theme does not import widgets)."
  - "mousePressEvent only intercepts within _HANDLE_GRAB_PX of a handle; any other press calls super() so the existing playhead `seeked` path (Phase-18 live scrubbing) is untouched — proven by the far-press fall-through test."
  - "The mutate+emit lives in one helper (_update_drag_handle) so a headless test drives a handle drag directly (a real offscreen QSlider mouse drag is fiddly); programmatic set_loop_region never emits (no panel feedback loop)."
metrics:
  duration: ~25min (executed inline, worktrees disabled)
  completed: 2026-05-29
---

# Phase 19 Plan 02: Scrubber Dual Region Handles — Summary

Gave the `Scrubber` a draggable loop-region (REP-03) — the timeline half of the snippet-loop feature (handles AND, in 19-03, buttons). The widget stays a thin presentation+input face; region/handle colours are theme tokens, never inline hex.

## What changed
- **`theme/tokens.py`**: added `region_fill` + `region_handle` to `Tokens` with DARK + LIGHT baked-sRGB values (OKLCH-authored, accent family).
- **`theme/qss.py`**: added `region_colors(t=DARK) -> (fill, handle)` so the QPainter-based widget resolves region colours from the token module (the values stay in tokens.py — D-03).
- **`widgets/scrubber.py`**: `region_changed = Signal(float,float)` (user-drag only); `_loop_in`/`_loop_out`/`_drag_handle` state; `set_loop_region`/`clear_loop_region` (programmatic, silent) + `loop_region` prop; `_handle_at` hit-test + `_update_drag_handle` (clamp + in≤out + emit); `mousePress/Move/Release` overrides that grab a handle within `_HANDLE_GRAB_PX` else fall through to the base playhead seek; `paintEvent` extended to draw a translucent band + two handle bars from the token QColors.
- **`tests/test_desktop.py`**: 7 new headless tests (commit `34205da`).

## Verification
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py -k "region or tokens_have_region or handle_drag or click_far_from_handle or paint_with_region"` → 7 passed.
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 20 passed (scrubber.py stays offline/Qt-clean; the theme import adds no Qt to the offline graph).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → **528 passed, 4 skipped, 86.49% coverage** (≥80% gate).
- `ruff check` + `ruff format --check` on all four files → clean.

## Deviations from plan
None. The plan allowed a token accessor OR an objectName selector — chose the accessor (`region_colors`) because the Scrubber paints with QPainter and can't read region colours from a stylesheet.

## Self-Check: PASSED
- `widgets/scrubber.py` (region_changed + set/clear + handles + paint + mouse) — FOUND
- `theme/tokens.py` (region_fill/region_handle) + `theme/qss.py` (region_colors) — FOUND
- `tests/test_desktop.py` (7 region tests) — FOUND
- Commit `34205da` (feat 19-02) — FOUND
