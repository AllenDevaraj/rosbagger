---
phase: 22-replay-live-mirror-to-rerun
plan: 01
status: complete
commits: [6bd8f5b, ce84808]
requirements: [RR-1]
---

# Plan 22-01 — Summary

## What changed

Scaffolded the new **`rosbagger-rerun`** package (7th workspace member) and wired it into the
workspace. Establishes the offline-import invariant the rest of the phase relies on.

- `packages/rosbagger-rerun/pyproject.toml` — hatchling src-layout; `dependencies=["numpy>=1.24"]`
  (image converter; import-safe), `rerun-sdk>=0.31,<0.33` under the **optional `[sdk]` extra**
  (never a base dep). No `[project.scripts]` (library only).
- `src/rosbagger_rerun/__init__.py` — lazy front door re-exporting `rerun_available` + `open_viewer`
  (no module-top rerun/rclpy import).
- `src/rosbagger_rerun/session.py` — `rerun_available()` (lazy `import rerun`, never raises) +
  `open_viewer(app_id, *, save_path=None)` (spawn the viewer, or `.save()` a `.rrd`).
- Root `pyproject.toml` — `[tool.uv.sources] rosbagger-rerun = {workspace=true}`, ruff `src` entry,
  and `rerun-sdk>=0.31,<0.33` in the **dev group** (so CI runs 22-02's offline converter tests).
- `tests/test_offline_guard.py` — `test_import_rerun_bridge_does_not_pull_ros_or_rerun` (fresh
  subprocess, `PYTHONPATH=""`): importing `rosbagger_rerun` pulls neither `rclpy`/`rosbag2_py` NOR
  `rerun`.
- `tests/test_rerun_unit.py` — package exposes the surface; `rerun_available()` returns a bool.

## Deviations from plan

- **`dependencies=["numpy>=1.24"]`** instead of the planned `dependencies=[]`. Justification: the
  22-02 image converter needs numpy; declaring it once here (import-safe, not ROS/rerun) is cleaner
  than a 22-02 pyproject edit. No impact on the offline invariant (numpy is not blocklisted).
- **rerun-sdk resolved to 0.32.2** (newer than the 0.31.4 seen at planning, still within `<0.33`).
  Verified the full API surface against 0.32.2: `Scalars` (not `Scalar`), `set_time(timeline, *,
  duration=)`, `RecordingStream.spawn/save/flush/log/set_time`, `Quaternion(xyzw=)`,
  `EncodedImage(contents=, media_type=)` — all present; 22-02 uses exactly these.

## Verification

| Check | Result |
|-------|--------|
| `uv sync` | clean (installed rerun-sdk 0.32.2 + rosbagger-rerun editable) |
| `import rosbagger_rerun` under `PYTHONPATH=""` | clean; `rerun_available()=True` in dev venv |
| Offline guard + unit (`--no-cov`) | **24 passed** |
| Full offline suite | **555 passed, 5 skipped** (was 552; +3 new tests) |
| Coverage gate | **88%** (≥80%; measured packages unchanged by this plan) |
| `ruff check` / `format --check` | clean |

## Notes for later waves

- Coverage-gate recipe under the offscreen-Qt SIGBUS: `pytest -o addopts="" --cov=... --cov-report=`
  then `coverage report` (suppressing the terminal cov report avoids the teardown crash; `.coverage`
  is written cleanly).
- API names for 22-02 are pinned + verified against the installed rerun 0.32.2.
