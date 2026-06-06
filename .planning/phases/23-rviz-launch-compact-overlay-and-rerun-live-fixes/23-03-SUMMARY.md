# 23-03 SUMMARY — Open in RViz

**Status:** Complete · **Requirement:** VIZ-RVIZ · **Date:** 2026-06-06

## What shipped
A one-click **Open in RViz** toggle on the Replay control bar that launches `rviz2` auto-subscribed to
the bag's viz topics — which the Replayer already publishes (no second publish path).

- **`rviz_config.py`** (pure, offline-tested, stdlib + yaml, NO ROS/Qt): `build_rviz_config(topics,
  fixed_frame) -> str` maps each `(topic, msgtype)` to an `rviz_default_plugins` display
  (Image/CompressedImage→Image, PointCloud2, LaserScan, TFMessage→TF, OccupancyGrid→Map,
  Marker/MarkerArray, Odometry, Path) with QoS matching the publisher (RELIABLE/VOLATILE depth-10);
  always adds Grid + TF; unknown msgtypes skipped; de-duped. `pick_fixed_frame` prefers
  map>odom>base_link else first frame else `map`.
- **`rviz_session.py`** (stdlib, ROS-free): `rviz_available()` = `shutil.which("rviz2")`;
  `open_rviz(cfg)` → `subprocess.Popen(["rviz2","-d",cfg])` non-detached, NVIDIA-dGPU PRIME-offload env,
  PID tracked; `close_rviz()` SIGTERM + atexit. Mirrors `rosbagger_rerun/session.py`. **No pip path**
  (rviz2 isn't pip-installable) — missing `rviz2` teaches.
- **`replay_panel.py`**: `_rviz_button` + `rviz_button` accessor; `_toggle_rviz` (ROS-gate →
  rviz-availability-gate → auto-fidelity → topic read → launch); `_read_rviz_topics` (O(1)
  `collect_bag_info`); `_enable_rviz_fidelity`; `_launch_rviz` (temp `.rviz` + `open_rviz` + delayed
  one-shot `republish_static`); `_reprime_rviz_static`; `_close_rviz`; closeEvent closes rviz.
- `pyyaml>=6` added to `rosbagger-desktop` deps (pure; ROS/Qt-free).

## Files
- NEW `packages/rosbagger-desktop/src/rosbagger_desktop/rviz_config.py`, `.../rviz_session.py`
- `.../panels/replay_panel.py`, `packages/rosbagger-desktop/pyproject.toml`
- NEW `tests/test_rviz_config.py`; `tests/test_desktop.py` (+7 rviz tests); `tests/test_desktop_live.py` (rviz smoke + rerun-async fix)

## Deviations (vs plan)
1. **Topic read on the UI thread, not a worker.** `collect_bag_info` reads only O(1) AnyReader
   metadata (never `reader.read()`), so a worker added complexity + shared-reader concurrency risk for
   no benefit. UI-thread is simpler and safe (the `_rviz_topics_thread/_worker` refs were dropped).
2. **Auto-fidelity rebuild only when SAFE (paused), not mid-play.** A live rebuild-and-restart while
   playing would race the finishing drive worker's queued `_on_drive_finished`, which would clobber
   the just-restarted drive thread/timer (a real use-after-restart bug). So: no transport yet (the
   common "open RViz before Play" flow) → boxes checked, first build gets full fidelity; paused
   transport without a tracker → synchronous rebuild preserving the playhead; mid-play → teach
   "pause & play to re-prime" (one extra step). This honors the user's "just works" for the normal
   flow while staying thread-safe.
3. **Fixed the existing live rerun-mirror test** (`test_desktop_live.py`) to `waitUntil` the
   asynchronously-built `_rerun_sink` — a consequence of 23-01 moving the viewer spawn off the UI
   thread (the old synchronous assertion would have failed in the live lane).

## Verification
- Full offline suite: **598 passed, 6 skipped, coverage 87.73%** (≥80%); ruff + format clean.
- `import rosbagger_desktop.rviz_config` is ROS-free AND Qt-free; `rviz_session` + `replay_panel` ROS-free at module top.
- Live lane (collected-and-skipped offline): `test_replay_panel_rviz_launch_smoke` (skipif no `rviz2`) starts a real rviz2 + checks the fidelity boxes.
- **Needs user sign-off (live + display):** Open in RViz → an rviz2 window opens with Image/PointCloud/LaserScan/TF displays bound to the bag topics; Play/scrub updates them live; closing the GUI kills rviz2.
