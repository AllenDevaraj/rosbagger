# Phase 23: RViz launch, compact overlay & Rerun live fixes - Context

**Gathered:** 2026-06-06
**Status:** Ready for planning
**Source:** Brainstorming (superpowers) + AskUserQuestion (4 decisions locked) + 5-agent codebase research workflow

<domain>
## Phase Boundary

Four additive workstreams on the desktop **Replay** experience, all behind the established
invariants (offline import graph ROS-free AND Qt-free, `rosbagger_replay` ROS-free at module top,
desktop panels thin faces over the library, every existing test green):

1. **Open in RViz** — launch `rviz2` auto-subscribed to the bag's viz topics.
2. **Auto-fidelity for RViz** — opening RViz turns on `/clock` + static re-prime so a late-joining
   RViz "just works".
3. **Compact overlay mini-player** + **±5s skip controls** — collapse the GUI to a thin always-on-top
   scrubber that remote-controls the live Replayer; add `‹ 5s` / `5s ›` skip to the normal bar too.
4. **Rerun live-mirror fix** — fix the viewer spawn-readiness race so image topics show regardless of
   toggle order.

IN SCOPE: desktop `rosbagger-desktop` package + the `rosbagger-rerun` viewer-readiness fix. RViz
subscribes to the topics the existing `Replayer`/`build_publish_sink` already publishes — NO second
publish path, NO new `rosbagger_core` analysis logic.

OUT OF SCOPE (deferred): per-topic RViz QoS overrides; RViz auto-layout beyond the generated config;
mirroring an external `ros2 bag play`; persistent overlay geometry across launches (best-effort only);
new rich Rerun converters (OccupancyGrid/IMU/etc. stay on the generic fallback).
</domain>

<decisions>
## Implementation Decisions (LOCKED)

### Overlay (compact mini-player)
- **Contents:** `‹ 5s` · `⏯` play/pause · `5s ›` · the **Scrubber** · `⛶` restore · `✕` close.
  (User confirmed slider + skip; play/pause kept as a small, useful addition.)
- **`✕` close = QUIT the whole app** (real window-close semantics; existing teardown stops replay +
  closes RViz/Rerun viewers). `⛶` restore = back to the full window at prior geometry.
- **Trigger = a menu-bar top-right corner control** (`menuBar().setCornerWidget`), near the OS close
  button. Behavior is context-dependent: **on the Replay tab → collapse to overlay**; **on any other
  tab → normal `showMinimized()`** (textbook minimize like any other window).
- The overlay is a **thin remote control over the EXISTING Replayer** — no second transport. Dragging
  its scrubber seeks live → republished to ROS → RViz/Rerun update live.

### ±5s skip
- `‹ 5s` / `5s ›` buttons added to the **normal Replay control bar too** (user: "id prefer that step
  button in gui as well normally"). Distinct from the existing single-message **Step** (which stays).
- Skip = seek to `clamp(current_time ± 5s)` via the thread-safe `Replayer.seek` (works playing/paused).

### RViz
- **Auto-generate a `.rviz` config** from the bag's viz topics and launch `rviz2 -d cfg`. RViz
  subscribes to the live topics Replay already publishes.
- **Auto-enable fidelity ("just works"):** opening RViz checks `Publish /clock` + `Re-publish static
  on seek`, rebuilds the transport seamlessly if one already exists without them, and fires a one-shot
  `republish_static` after the viewer is up so the late-joining RViz immediately gets `/tf_static`.
- Viewer lifecycle mirrors `rosbagger-rerun/session.py` (non-detached spawn, `/proc` PID tracking,
  NVIDIA-dGPU env, SIGTERM on close + atexit). **No pip-install path** (rviz2 isn't pip-installable) —
  missing `rviz2` teaches.

### Rerun fix
- **Spawn-readiness gate off the UI thread** before streaming (reuse the install-worker pattern).
- **Anchor `build_rerun_sink(t0_ns=items[0].t_ns)`** to bag start (order-independent timeline).
- **Surface `logged['errors']`** on the status line (no more silent drops).

### Claude's Discretion
- Exact rerun-sdk 0.32 readiness mechanism (socket-probe vs bounded settle) — confirm against the
  installed wheel during execution + a live repro.
- RViz Fixed-Frame heuristic specifics (prefer map/odom/base_link; else first sensor frame_id; else map).
- Overlay default size/position and drag implementation details.
</decisions>

<canonical_refs>
## Canonical References

**Downstream execution MUST read these before implementing.**

### Replay panel & transport (the integration surface)
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py` — Rerun tee (`_drive_sink` L437-441), `_open_rerun`/`_close_rerun` (L511-544), `_ensure_transport` (L370-467), `_on_seeked` (L733-768), `_start_drive`/`_update_position`/`_position_timer` (L920-950, L770-780), fidelity checkboxes (L177-185).
- `packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py` — `Scrubber(QSlider)`: `seeked(float)` signal, `set_position(float)`, `set_markers`, `set_loop_region`.
- `packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py` — `MainWindow(QMainWindow)`: `_nav`/`_stack`, `_build_menu` (L220-238), `menuBar()`, `closeEvent` (L302-307); panels reach it via `self.window()`.
- `packages/rosbagger-desktop/src/rosbagger_desktop/workers.py` — `BlockingWorker` + `run_on_thread`/`stop_thread` (the off-UI-thread pattern; CR-02 keep-both-refs).
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py` — `collect_bag_info(reader)` usage → `info.topics` = `(topic, msgtype)` (topic enumeration for the RViz config).

### Replay engine (already publishes RViz-ready topics)
- `packages/rosbagger-replay/src/rosbagger_replay/replay.py` — `build_publish_sink(node, *, publish_clock, static_topics, remap)` (RELIABLE/VOLATILE depth-10 publishers), `republish_static(sink)`.
- `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py` — `Replayer.seek/play/pause/position_fraction` (thread-safe, Phase 18).

### Rerun viewer (the lifecycle pattern to mirror + the bug)
- `packages/rosbagger-rerun/src/rosbagger_rerun/session.py` — `open_viewer`/`close_viewer`/`_child_pids`/`_prefer_gpu` (spawn non-detached, /proc PID tracking, atexit, GPU env). **Bug:** `rec.spawn()` L53 returns before viewer ready.
- `packages/rosbagger-rerun/src/rosbagger_rerun/sink.py` — `build_rerun_sink(rec, *, t0_ns)`; `logged['errors']` swallowed-then-discarded.

### Tests / invariants
- `tests/test_desktop.py` (offline), `tests/test_desktop_live.py` (`importorskip(rclpy)`), `tests/test_rerun_unit.py`/`test_rerun_live.py`, `tests/test_replay_unit.py`.
- Offline-import guard (extend for any new module): keep `import rosbagger_desktop.*` panel/widget modules + `import rosbagger_rerun.*` ROS-free AND Rerun-free at top level.

### Prior design specs
- `.planning/specs/2026-05-29-rerun-live-mirror-design.md` — Phase 22 Rerun mirror design.
- ROADMAP.md Phase 20 — `/clock` + static-republish fidelity (the RViz groundwork).
</canonical_refs>

<specifics>
## Specific Ideas

- The RViz config builder is a **pure, offline-unit-tested** function (no ROS, no Qt): `(topics, fixed_frame) -> rviz YAML`. msgtype→display map: Image/CompressedImage→Image, PointCloud2→PointCloud2, LaserScan→LaserScan, TFMessage→TF, OccupancyGrid→Map, Marker→Marker, MarkerArray→MarkerArray, Odometry→Odometry, Path→Path; always add Grid + TF.
- Skip math: `cur = position_fraction * bag_span_ns; new = clamp(cur ± 5e9, 0, bag_span_ns); seek(int(new))`.
- Overlay window flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`; custom mouse handlers for dragging; a new `positionChanged(float)` signal on ReplayPanel (emitted in `_update_position`) syncs the overlay scrubber.
- Panel public remote-control API for the overlay: `toggle_play()`, `skip_back()`, `skip_forward()`, `seek_fraction(f)`, `positionChanged` signal, `current_fraction()`.
</specifics>

<deferred>
## Deferred Ideas

- Per-topic RViz/Rerun QoS overrides.
- Persistent overlay geometry across launches.
- New rich Rerun converters (OccupancyGrid/IMU/Pose/Odometry/Path/Markers stay generic-fallback).
- Mirroring an external `ros2 bag play` session.
</deferred>

---

*Phase: 23-rviz-launch-compact-overlay-and-rerun-live-fixes*
*Context gathered: 2026-06-06 via brainstorming + AskUserQuestion + research workflow*
