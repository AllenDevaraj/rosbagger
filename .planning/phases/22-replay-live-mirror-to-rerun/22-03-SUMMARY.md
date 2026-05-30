---
phase: 22-replay-live-mirror-to-rerun
plan: 03
status: complete
commits: [f8f7c4f, ea43495]
requirements: [RR-3]
---

# Plan 22-03 — Summary

## What changed

Wired the live mirror into the desktop Replay tab.

- `panels/replay_panel.py`:
  - A checkable **Open in Rerun** button at the end of the control bar (behind a stretch) +
    `rerun_button` accessor + `toggled→_toggle_rerun` wiring + `self._rerun_sink/_rerun_rec/
    _install_thread/_install_worker` refs.
  - `_ensure_transport` now drives a **dynamic tee** `_drive_sink` — publishes to ROS (unchanged)
    then, when `self._rerun_sink is not None`, logs to Rerun. Reads the sink LIVE → toggling needs
    no transport rebuild; `build_publish_sink` + `self._sink` are byte-for-byte untouched.
  - `_toggle_rerun` (ROS-gate → `rerun_available()` → open / install), `_open_rerun` (spawn viewer
    + build the mirror sink), `_close_rerun` (drop sink + flush), `_install_rerun` (pip in a
    KEPT-REF worker), `_on_install_result/_failed/_finished`.
  - `closeEvent` stops a running install worker + `_close_rerun()` (mirror cleanup is here, NOT in
    `_teardown_transport`, so a rate-change rebuild can't kill the mirror).
- `packages/rosbagger-desktop/pyproject.toml` — deps += `rosbagger-rerun>=0.2,<0.3` (import-safe).
- `tests/test_desktop.py` — 3 offline tests: button present + checkable; toggle-unavailable enters
  the install state with NO pip/viewer (patches `_ros_available`→True, `rerun_available`→False,
  `run_on_thread`→no-op); `_close_rerun` drops the sink + flushes + resets the label.
- `tests/test_desktop_live.py` — `-m live` mirror proof: monkeypatch `open_viewer`→save-mode, toggle
  on, Play, assert a non-empty `.rrd`.

## Deviations from plan

- **`_install_rerun` written as the full installer directly** (the plan staged a Task-1 stub then a
  Task-2 fill; the call site never changes, so a single implementation is cleaner).
- **`_on_install_result` calls `importlib.invalidate_caches()`** before re-probing — robustness so a
  just-`pip install`ed rerun is importable in the running process (not in the plan text).
- **`closeEvent` also `stop_thread(self._install_thread)`** — defensive: a window closing mid-install
  stops the pip worker.
- **`capabilities.py` NOT modified** — `rerun_available()` is canonicalized in `rosbagger_rerun`
  (single source of truth); the panel calls `rosbagger_rerun.rerun_available()` lazily. The spec
  mentioned a desktop-side probe; centralizing avoids duplication and keeps the offline invariant.
- The offline "unavailable is safe" test patches `run_on_thread`→no-op (deterministic, no real pip
  or viewer) — the side-effect-free design from the inline plan-check.

## Verification

| Check | Result |
|-------|--------|
| Panel module top stays ROS-free AND rerun-free on import | clean |
| 3 offline rerun desktop tests (`-k rerun`) | **3 passed** |
| Live mirror test offline | **1 skipped** (importorskip rclpy) |
| Full offline suite | **565 passed, 6 skipped** (was 562/6: +3 offline desktop) |
| Coverage gate | **87%** (≥80%; replay_panel.py 74% — live-only branches are ROS-lane) |
| `ruff check` / `format --check` | clean |

## User-facing result

`uv run --with pyyaml rosbagger-desktop <bag>` → Replay → **Open in Rerun** → **Play** → the Rerun
viewer fills with the bag's camera/scan/cloud/TF live (generic fallback for the rest), additive to
RViz/`ros2 topic`. If rerun-sdk is missing, the button reads "Open in Rerun (install)" and installs
it on click without freezing the UI.
