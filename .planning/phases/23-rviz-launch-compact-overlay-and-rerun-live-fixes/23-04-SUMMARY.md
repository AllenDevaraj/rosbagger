# 23-04 SUMMARY — Compact overlay + smart-minimize trigger

**Status:** Complete · **Requirement:** VIZ-OVERLAY · **Date:** 2026-06-06

## What shipped
- **`widgets/overlay.py` — `OverlayWindow`**: a frameless, always-on-top mini-player
  (`Qt.FramelessWindowHint | WindowStaysOnTopHint | Qt.Tool`) with `‹ 5s` · `⏯` · `5s ›` · a
  `Scrubber` · `⛶` restore · `✕` close. It **remote-controls the existing Replayer** via the
  ReplayPanel 23-02 API — no second transport: buttons → `skip_back`/`toggle_play`/`skip_forward`,
  scrubber `seeked` → `seek_fraction`, `panel.positionChanged` → overlay `scrubber.set_position`
  (live playhead), `⛶` → `main_window.exit_overlay`, `✕` → `main_window.close` (quit). Frameless
  dragging via mouse-offset handlers. Re-exported from `widgets/__init__.py`.
- **`main_window.py`**: a top-right **menu-bar corner control** (`menuBar().setCornerWidget(btn,
  Qt.TopRightCorner)`). `_on_minimize_clicked`: on the Replay tab → `enter_overlay()`; elsewhere →
  `showMinimized()` (textbook minimize). `enter_overlay` saves geometry, builds the overlay lazily,
  syncs the scrubber, hides the window, shows the overlay (positioned bottom-center, headless-safe).
  `exit_overlay` restores (`showNormal` + `restoreGeometry`). `closeEvent` closes the overlay so it
  never orphans the app. `overlay`/`overlay_button` test accessors.
- Dragging the overlay scrubber seeks the live Replayer → republished to ROS → RViz/Rerun update
  (inherited from 23-02's seek path); the overlay holds no ROS/transport code.

## Files
- NEW `packages/rosbagger-desktop/src/rosbagger_desktop/widgets/overlay.py`
- `.../widgets/__init__.py`, `.../main_window.py`
- `tests/test_desktop.py` (+5 tests: controls drive the panel + positionChanged sync; trigger enters
  overlay on Replay / minimizes elsewhere; exit restores; ✕ quits)

## Notes / deviations
- Overlay tests use **spy assertions** (monkeypatch `hide`/`showMinimized`/`showNormal`/`close`)
  rather than offscreen `isVisible()` checks (unreliable under the offscreen platform) and to avoid
  the full-window `show()` that aggravates the known Qt offscreen teardown SIGBUS.
- The `✕`-quits test patches `window.close` **before** `enter_overlay` so the overlay binds to the
  recorder (the connection captures the bound method at construction).

## Verification
- Full offline suite: **609 tests, 0 failures, 0 errors, 6 skipped, coverage 87.99%** (≥80%); ruff +
  format clean. (Captured via `--junitxml` — the intermittent Qt offscreen teardown SIGBUS is a
  process-exit artifact, not a test failure; per-test results are all green.)
- `import rosbagger_desktop`, `rosbagger_desktop.widgets.overlay`, `rosbagger_desktop.main_window`
  pull no rclpy/rerun/rosbags.
- **Needs user sign-off (live + display):** Open RViz → click the top-right ⤓ on the Replay tab → the
  GUI collapses to the overlay → drag the slider → RViz translates live; ⛶ restores; on a non-Replay
  tab ⤓ minimizes normally; ✕ quits (rviz2/rerun close too).
