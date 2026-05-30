---
quick_id: 260530-c3p
slug: close-rerun-viewer-with-gui
date: 2026-05-30
status: complete
commit: 35937bc
---

# Quick Task 260530-c3p — Summary

## What changed

The spawned Rerun viewer no longer **outlives the desktop GUI** (user: "i want rerun to close as
well in any case our main terminal which runs the gui crashes or if i close it with ctrl c").

- `rosbagger-rerun/session.py`:
  - `open_viewer()` now spawns the viewer **`rec.spawn(detach_process=False)`** (was the default
    `True`) and records the new child PID via a `/proc` child-diff. Returns `rec` (unchanged).
  - new `close_viewer()` — `SIGTERM`s every tracked viewer PID (best-effort reap), idempotent;
    plus `_child_pids`, `_track_viewers` (installs an `atexit` backstop once), `_terminate_pid`.
- `rosbagger-rerun/__init__.py`: export `close_viewer`.
- `desktop/panels/replay_panel.py`: `_close_rerun()` (toggle-off AND `closeEvent`) now calls
  `rosbagger_rerun.close_viewer()` after the flush.

## Root cause

`rec.spawn()`'s default `detach_process=True` `setsid()`s the viewer into its **own session /
process group**, so it survived the GUI closing and escaped terminal-directed signals.

## How each close path is covered

| Path | Mechanism |
|------|-----------|
| Window close (X) / normal app exit | `_close_rerun`/`closeEvent` + `atexit` → `close_viewer()` SIGTERMs it |
| `Ctrl-C` (`SIGINT`) in the terminal | the non-detached viewer shares our process group → receives the group signal directly |
| Terminal closes/crashes (`SIGHUP`) | same — process-group signal reaches the viewer |
| GUI hard-segfaults, terminal still open | **NOT covered** (no `PR_SET_PDEATHSIG` without owning the fork) — but the bag-end segfault is fixed in [[260530-w4k]]; documented gap |

## Verification

| Check | Result |
|-------|--------|
| New lifecycle tests (`test_rerun_unit.py`) | **4 passed** (`_child_pids`, `close_viewer`, `open_viewer` non-detached+track, save-mode untouched) |
| Panel close test (`test_desktop.py`) | **passed** (`_close_rerun` calls `close_viewer`) |
| Full offline suite (per-file, retried past the intermittent teardown SIGBUS) | **575 passed, 0 failed, 6 skipped** (was 571; +4) |
| Offline-import invariant | **22 passed** (`import rosbagger_rerun` still pulls no rerun/rclpy) |
| Coverage gate | **88%** (≥80%) |
| `ruff check` / `format --check` | clean |
| Manual process-group proof | non-detached child shares our pgrp (Ctrl-C/SIGHUP reach it); detached child escapes it |

## Notes

- Couldn't spawn a real viewer to test end-to-end — it pops a window on the user's box (they'd
  complained about that). Verified the lifecycle mechanics with dummy subprocesses + the OS
  process-group semantics, and the rerun wiring with mocks.
- `open_viewer` keeps returning `rec`, so `test_desktop_live.py`'s save-mode monkeypatch and
  `test_rerun_live.py` are unaffected.
- Pairs with [[260530-w4k]] (bag-end crash) and [[260530-ja4]] (GPU offload) to close out the
  user's Rerun runtime reports.
