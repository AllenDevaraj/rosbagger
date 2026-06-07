---
quick_id: 260607-5xf
status: complete
date: 2026-06-07
commit: dd78b72
---

# 260607-5xf SUMMARY — Close RViz/Rerun + tear down live panels on GUI close

**Shipped:** `MainWindow.closeEvent` now closes the live panels (`replay_panel`, `record_panel`) via
`panel.close()` before closing the shared reader. Qt doesn't deliver `closeEvent` to child widgets, so
this is what makes the panels' own teardown (`_close_rviz` + `_close_rerun` + worker-thread stop +
rclpy teardown) run on a GUI close — instead of relying on the `atexit` backstop that doesn't fire on
the known Qt-teardown SIGBUS (which orphaned rviz2/rerun, the user's report). Fixes both RViz and Rerun.

**Files:** `packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py` (`import contextlib` +
closeEvent panel-close loop), `tests/test_desktop.py` (`test_window_close_tears_down_live_panels` —
spies `_close_rviz`/`_close_rerun`, asserts `window.close()` fires both).

**Verification:** Diagnosis confirmed headlessly (`window.close()` fired no panel teardown before the
fix; `replay_panel.close()` fires both `_close_rerun` + `_close_rviz`). Desktop suite **83 passed, 0
failures** (junitxml); ruff + format clean; `main_window` stays ROS-free at module top. Commit `dd78b72`.

**User UAT (needs display + ROS):** Open RViz/Rerun, then close the GUI (or the overlay ✕) → both
viewers close with it.
