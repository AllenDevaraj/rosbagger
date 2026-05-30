---
phase: 22-replay-live-mirror-to-rerun
plan: 02
status: complete
commits: [418fa6e, fd2b64a]
requirements: [RR-2]
---

# Plan 22-02 — Summary

## What changed

Built the conversion + fork-sink core of `rosbagger-rerun`.

- `converters.py` — PURE helpers (no rerun/ROS): `_laserscan_xyz` (polar→cartesian, finite +
  range filter), `_pointcloud2_xyz` (struct-unpack float32 x/y/z, endian + bounds safe),
  `_image_array` (rgb8/bgr8→rgb, mono8, 16UC1→depth), `_numeric_leaves` (bounded-depth numeric
  walk; arrays → length only), `_entity_path` (frame_id else topic). Lazy-rerun wrappers behind
  `convert(msg, msgtype, topic)`: Image/CompressedImage/LaserScan/PointCloud2/TF rich archetypes
  + a generic `Scalars`/`TextLog` fallback so EVERY msgtype yields ≥1 `(path, archetype)`.
- `sink.py` — `build_rerun_sink(rec, *, t0_ns=None)`: the deserialize→set_time→convert→log twin
  of `build_publish_sink`. Independent re-deserialize (publish path untouched); `bag_time`
  timeline at `(t_ns - t0)/1e9`; a bad item bumps `logged['errors']` instead of aborting.
- `__init__.py` — front door now re-exports `convert` + `build_rerun_sink` (still no module-top
  rerun import).
- `tests/test_rerun_unit.py` — 7 converter tests (exact math + dispatch + generic fallback).
- `tests/test_rerun_live.py` — `-m live` `.rrd` proof (save-mode RecordingStream, real items).

## Deviations from plan

- **`rec.flush()` not `rec.flush(blocking=True)`** — verified against the installed rerun 0.32.2
  that `RecordingStream.flush` is `flush(*, timeout_sec=...)` with NO `blocking` kwarg; the plan
  text's `flush(blocking=True)` would have raised `TypeError`. Live test uses plain `rec.flush()`.
- **`session.py` not modified** — `open_viewer` (incl. the `save_path` mode the live test uses)
  was already complete in 22-01; no change needed (the plan listed it speculatively).
- **`logged = {"n": 0, "errors": 0}`** — both keys initialized up front (cleaner than
  `setdefault`); same contract.
- Validated the full archetype path against real rerun 0.32.2 out-of-band: `open_viewer(save_path)`
  + `Points3D`/`TextLog` + `set_time(duration=)` + `flush()` writes a non-empty `.rrd` (3930 B).

## Verification

| Check | Result |
|-------|--------|
| Converter unit + offline guard (`--no-cov`) | **31 passed** |
| Offline-import invariant (no rerun/rclpy on import) | clean (after front-door extension) |
| Live `.rrd` test offline | **1 skipped** (importorskip rclpy) |
| Full offline suite | **562 passed, 6 skipped** (was 555/5: +7 converter, +1 skipped live) |
| Coverage gate | **88%** (≥80%; rosbagger_rerun excluded by design) |
| `ruff check` / `format --check` | clean |

## Notes for 22-03

- `convert()` / `build_rerun_sink` / `open_viewer` are the desktop's seam. The tee in
  `_ensure_transport` calls `build_rerun_sink(rec)` once on toggle-on and reads the resulting
  sink live; the converters need no further changes.
