---
phase: 14-gui
fixed_at: 2026-05-24T00:00:00Z
review_path: .planning/phases/14-gui/14-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 14: Code Review Fix Report

**Fixed at:** 2026-05-24
**Source review:** .planning/phases/14-gui/14-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (WR-01..WR-06; 0 Critical)
- Fixed: 6
- Skipped: 0
- Info findings (IN-01..IN-06): out of scope this pass, not touched.

**Verification:** offline suite + ruff re-run on the fully-committed state —
`465 passed, 3 skipped, 97.37%`, ruff clean (90 files), matching the pre-fix
baseline exactly. Live record/replay paths (rclpy absent offline) were verified
by import + lint only, per the environment note. Each fix was staged and
committed atomically; the four findings that share `replay.py` were split into
separate commits via per-hunk index staging.

## Fixed Issues

### WR-01: Scrubber playhead uses index-fraction but seek/markers use time-fraction

**Files modified:** `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py`, `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py`
**Commit:** 601923f
**Applied fix:** Added a public `Replayer.position_fraction` property that derives
the cursor position as a TIME fraction of the bag span (cursor item `t_ns` relative
to `items[-1].t_ns - items[0].t_ns`), returning a clean `0.0`/`1.0` for empty,
zero-span, and at/past-end cursors. The panel's `_update_position` now reads this
accessor instead of `cursor / item_count`, so the playhead shares the same
time-fraction basis as the seek mapping and the event markers — they no longer
drift apart on non-uniform bags. Followed the review's preference to add a public
accessor on `Replayer` rather than reach into `_items` from the panel (keeps the
thin-face boundary clean).

### WR-02: Rate-validation branch unreachable; invalid rate silently coerced to 1.0

**Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py`
**Commit:** 5cc23c4
**Applied fix:** Rewrote `on_input_submitted` to read the raw rate string, parse it
ONCE with `float(raw)`, and let the scheduler's `set_rate` be the single `> 0`
validator. A non-numeric or `<= 0` entry now hits the `except ValueError` branch and
shows `Invalid rate {raw!r}: enter a number > 0.` instead of being silently coerced
to 1.0 and reported as a successful "Rate set to 1.". Left `_read_rate`'s coercion in
place for its other callers (the ctor default and the Play/Step status echo).

### WR-03: "Stop" does not stop — record() keeps recording for the bounded window

**Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/panels/record.py`
**Commit:** fb38270
**Applied fix:** Chose review option (b) — relabel to reflect reality — because
option (a) (a cooperative `should_stop`/`threading.Event` hook) would require
changing the `record()` front-door signature, the `_run` spin loop, and the
package wrapper across `rosbagger-record`, all outside the reviewed GUI files and
beyond a safe auto-fix (it is a cross-package API design change). Relabeled the
button "Stop" -> "Dismiss", changed `_stop_record`'s status from the false
"Stopped." to "Dismissed — the bounded record finalizes on its own (up to Ns)."
and updated the docstrings so the affordance no longer claims an immediate stop the
panel cannot deliver. The bounded `duration` still terminates the recorder.

### WR-04: `_load_markers` eagerly builds the rclpy transport on `on_show`

**Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py`
**Commit:** 910a612
**Applied fix:** Removed the `self._ensure_transport()` call from the marker path.
`bag_start_ns`/`span` are now computed from `load_items(bag)` alone (which the path
already called), so merely navigating to the Replay tab no longer runs `rclpy.init()`
+ `create_node(...)`. Transport construction stays lazy on the Play/Step/seek paths,
restoring the "built lazily on first Play" contract; marker fractions still line up
with the seek mapping because both use the same item timestamps.

### WR-05: `open_bag` / launch open path raises out without a teaching catch

**Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/app.py`
**Commit:** 01aa4eb
**Applied fix:** Wrapped `reader.open()` in `_open_reader` with a `try/except
Exception` that calls `self.notify(f"Could not open {path}: {exc}",
severity="error")` and returns without setting `self.reader`. Both entry points
funnel through `_open_reader` (the `on_mount` launch path and the `open_bag` picker
seam), so a bad/corrupt/missing bag now surfaces a teaching notification instead of a
traceback that crashes startup or escapes the message handler. On failure
`self.reader` stays `None`, which the panels already handle.

### WR-06: Step + Play share one exclusive worker group — Step during Play is racy

**Files modified:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py`
**Commit:** 81bd228
**Applied fix:** Added a `_drive_running()` helper that checks `self.workers` for a
running worker in the `replay-run` group, and guarded both `_play` and `_step` to
no-op with a teaching status ("Already playing — pause before issuing a new control."
/ "Pause before stepping (a play worker is running).") when a drive worker is in
flight. This prevents a second `exclusive=True` worker from cancelling the in-flight
playback and stops the UI thread from mutating the non-thread-safe `Replayer` state
while `run()` reads it on the worker thread. Pause remains allowed (it asks the loop
to stop at the next boundary). This is a concurrency/logic change — the offline suite
exercises the pure scheduler but not the live worker interleaving, so a developer
should confirm the live Play/Step/Pause behavior on a ROS box (requires human
verification).

---

_Fixed: 2026-05-24_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
