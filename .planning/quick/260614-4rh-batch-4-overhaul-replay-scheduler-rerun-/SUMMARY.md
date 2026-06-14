# SUMMARY — Quick 260614-4rh — Batch 4: replay scheduler + rerun converter bugs

**Date:** 2026-06-14 · **Status:** complete · **Commits:** dccdb9c, 3b8fde0, 5db47cf

Batch 4 of the whole-codebase overhaul. Five confirmed findings in the replay scheduler,
the two replay panels, and the Rerun converter — each fixed with a regression test and an
atomic commit. Full offline suite **677 passed / ~5 skipped** (671 baseline + 6 new tests).

## Fixes

### newD9 — region-loop bounds: relative offsets vs absolute t_ns (CORRECTNESS) · dccdb9c
`Replayer.set_loop_region` stored its bounds as **absolute** t_ns, but BOTH callers pass
**bag-relative** offsets (CLI `region_start*1e9`; desktop `frac*bag_span_ns`) — the same
basis `seek()` already uses. On a real bag (t0 = a large ROS stamp) `items[cursor].t_ns >
out_ns` was always true → the cursor wrapped after every publish and the region collapsed
to "republish item 0". Fixture streams used t0==0, masking it. **Fix:** `set_loop_region`
now adds `items[0].t_ns` internally (consistent with `seek`), so both callers — and the CLI
`--region-start/--region-end` — are correct with one change. Desktop `_region_abs_ns` →
`_region_offset_ns` with an honest docstring. New non-zero-t0 regression test.

### newD13 — single-item / zero-span loop busy-spins at 100% CPU (QoL/perf) · dccdb9c
`do_pace = cursor > 0` is False at index 0, and a loop wrap rewinds to 0, so a one-message
(or all-equal-timestamp) looping bag never paced → republished as fast as the CPU allowed.
**Fix:** `_is_zero_span_loop()` + floor the wrap cadence to `_DEGENERATE_LOOP_PERIOD_S /
rate` when there is no Δt. Normal positive-span pacing (incl. a multi-item loop's instant
wrap) is untouched. Two new tests (single-item; multi-item zero-span floors only the wrap).

### newD16 — TUI replay silently coerces a bad rate to 1.0 on Play (QoL) · 3b8fde0
`gui/panels/replay.py` `_read_rate()` coerced a non-numeric / `<=0` entry to 1.0 at
transport-build time (Play reported `"rate 1"`); the Enter handler taught but Play did not.
(The desktop panel already validates via `_validated_rate`.) **Fix:** `_parse_rate()` raises
on bad/`<=0`; `_ensure_transport` validates BEFORE `import rclpy` and teaches + refuses;
`_play` reports the Replayer's actual rate. New offline GUI test (rejection runs before the
ROS import, so it needs no ROS).

### F4 — `seek` linear-scans the item list under the lock (perf) · dccdb9c
`seek` + the region in-bound scan did O(n) `next(i for ...)` under `_lock`, stalling
concurrent transport controls on a large bag. **Fix:** `_first_index_at_or_after()` via
`bisect.bisect_left(key=)` (Python ≥3.10) — O(log n), identical semantics. Used by both.

### F5 — Rerun `_pointcloud2_xyz` does 3 `struct.unpack_from` per point (perf) · 5db47cf
Per-point Python unpack = minutes on a 100k+ point cloud (live-mirror stall). **Fix:** a
NumPy structured-dtype view reads all points in one C pass, honoring `is_bigendian`,
`point_step`, offsets, and the truncated-buffer guard. `struct` drops from the module;
NumPy stays lazy (rerun/offline invariant intact). Two new tests (big-endian+truncated;
point_step padding).

## Verification
- `tests/test_replay_unit.py` 48 passed · `tests/test_gui.py` 7 passed · `tests/test_rerun_unit.py` 20 passed
- Full offline suite: 590 passed (non-Qt) + 87 passed (`test_desktop.py`, Qt offscreen) = **677 passed**, ~5 skipped.
- Offline-import guard unaffected (scheduler stdlib-only + `bisect`; converter NumPy lazy).

## Remaining overhaul
Batch 5 (GUI/TUI threading races C1/C2/C3/C5/C6/C7/C8 + newE21 + F1/F7 + TUI query worker),
Batch 6 (replay_panel refactor S2/S4/S5/R5/R8 + T6), Batch 2e (error/capability dedup
R4/R6/R7/T7), T4 version-sync.
