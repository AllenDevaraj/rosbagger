# Phase 23 — Research

**Researched:** 2026-06-06 (5-agent codebase workflow + direct reads). Durable technical record for execution + post-compaction resume.

## 1. Rerun live-mirror bug — ROOT CAUSE (high confidence)

**Symptom (user):** Live mirror to Rerun "isn't working"; topics only load/play if Play was already
pressed before opening Rerun; opening Rerun **then** pressing Play → the **Image** topic doesn't show.

**Cause:** A viewer **spawn-readiness race** + swallowed-and-discarded diagnostics.
- `rosbagger_rerun/session.py:open_viewer()` → `rec.spawn(detach_process=False)` (L53) **returns
  immediately** — no wait for the viewer process/gRPC connection (viewer startup ~100–500 ms).
- `replay_panel.py:_open_rerun` (L511-523) then builds the sink and **discards** the diagnostics:
  `self._rerun_sink, _ = rosbagger_rerun.build_rerun_sink(rec)`.
- On **Rerun-before-Play**: the first items (often a large **Image**) hit `rec.log()` while the
  stream isn't connected yet → dropped. The sink swallows the exception (`sink.py:49-50`,
  `logged['errors'] += 1`) and that count is thrown away → zero feedback. Small msgs (TF/scalars)
  survive; big image frames don't — matches "image specifically doesn't play".
- On **Play-before-Rerun**: by the time you toggle, the viewer has settled → later items log fine.
- Secondary: `build_rerun_sink` t0 is captured from the **first logged item** (`sink.py:39-40`), so
  the `bag_time` timeline differs by toggle order (not the cause of dropped images, but a correctness/UX gap).

**Fix (plan 23-01):**
1. **Gate on viewer readiness** after `rec.spawn()` before returning from `open_viewer`. Confirm the
   mechanism against the installed rerun-sdk (memory says 0.32.2) + a live repro. Candidates, pick the
   simplest that empirically stops first-frame loss: (a) poll a TCP connect to the viewer's gRPC port
   until accept (bounded ~3 s); (b) bounded settle loop + `rec.flush()`. Run this OFF the UI thread
   (the spawn can block ~1 s) by moving spawn+readiness onto a `BlockingWorker` (mirror `_install_rerun`).
2. **Anchor t0 to bag start:** `_open_rerun` calls `_ensure_transport()` first (loads items → store
   `self._bag_start_ns = items[0].t_ns`), then `build_rerun_sink(rec, t0_ns=self._bag_start_ns)`.
   Order-independent `bag_time` timeline, aligned with the scrubber fraction basis.
3. **Surface errors:** keep the `logged` dict (`self._rerun_logged = logged`); when `logged['errors'] > 0`,
   show e.g. "Rerun: N message(s) could not be logged" on the status line (drive-done or position poll).

**rerun-sdk API (verified 0.32.2 in converters docstring):** `rr.RecordingStream(app_id)`, `.spawn()`,
`.save(path)`, `.set_time(timeline, *, duration=)`, `.log(path, archetype)`, `.flush()`. Archetypes:
`Image`/`DepthImage`/`EncodedImage(contents=, media_type=)`/`Points3D`/`Transform3D`/`Quaternion(xyzw=)`/`Scalars`/`TextLog`.

## 2. RViz launch — architecture

**Key enabler:** the `Replayer` already publishes **real ROS 2 topics** via `build_publish_sink`
(RELIABLE/VOLATILE, depth 10), and Phase 20 added `/clock` + `/tf_static` republish for RViz fidelity.
So the RViz button does NOT feed RViz — it launches `rviz2` and RViz subscribes to the live topics.

**QoS compatibility:** a RELIABLE publisher serves BOTH reliable and best-effort subscribers, so
RViz default displays receive Image/PointCloud2/LaserScan fine. The gap is **`/tf_static`** (normally
TRANSIENT_LOCAL/latched): a late-launched RViz misses it — fixed by auto-enabling static tracking +
one-shot `republish_static` after the viewer is up (the "auto-fidelity" decision).

**Topic enumeration:** `from rosbagger_core.inspect import collect_bag_info; collect_bag_info(reader).topics`
→ each `TopicInfo` has `.topic` and `.msgtype` (e.g. `sensor_msgs/msg/Image`). Run off the UI thread
(reuse `BlockingWorker`) — the inspect panel already does this.

**Pure config builder (offline-unit-tested, no ROS/Qt):** `build_rviz_config(topics, fixed_frame) -> str`
emitting `.rviz` YAML. Display map by msgtype:
| msgtype | RViz display class |
|---|---|
| sensor_msgs/msg/Image, sensor_msgs/msg/CompressedImage | rviz_default_plugins/Image |
| sensor_msgs/msg/PointCloud2 | rviz_default_plugins/PointCloud2 |
| sensor_msgs/msg/LaserScan | rviz_default_plugins/LaserScan |
| tf2_msgs/msg/TFMessage | rviz_default_plugins/TF |
| nav_msgs/msg/OccupancyGrid | rviz_default_plugins/Map |
| visualization_msgs/msg/Marker | rviz_default_plugins/Marker |
| visualization_msgs/msg/MarkerArray | rviz_default_plugins/MarkerArray |
| nav_msgs/msg/Odometry | rviz_default_plugins/Odometry |
| nav_msgs/msg/Path | rviz_default_plugins/Path |
Always add `rviz_default_plugins/Grid` + `rviz_default_plugins/TF`. The display dict needs at least
`Class`, `Name`, `Enabled: true`, and `Topic` (for topic-bound displays: a dict with `Value: <topic>`,
plus `Depth`, `Durability Policy: Volatile`, `Reliability Policy: Reliable` to match the publisher).
Top-level: `Visualization Manager: { Global Options: { Fixed Frame: <frame> }, Displays: [...] }`.
**Confirm the exact `.rviz` YAML schema against a real `rviz2`-saved config during execution** (write a
trivial config, launch rviz2 in the live lane, assert it loads). PyYAML is bundled in the live lanes
(quick-260605-i73) — use `yaml.safe_dump`.

**Fixed-Frame heuristic:** prefer `map`→`odom`→`base_link` if they appear as a parent frame in a
sampled `/tf`/`/tf_static`; else the first sensor `frame_id`; else `"map"`. Sampling TF requires
deserialize — acceptable to keep simple (default `"map"` and let the user change it in RViz); a richer
heuristic can read a few `/tf` items via `load_items`. Keep v1 simple.

**Launcher (mirror `rosbagger_rerun/session.py`):** `subprocess.Popen(["rviz2","-d",cfg_path])` with
`_prefer_gpu`-style env (reuse/duplicate the NVIDIA PRIME offload), `/proc` child-PID tracking,
`close_rviz()` SIGTERM + atexit, written to a temp `.rviz` (tempfile, cleaned on close). Gate:
`shutil.which("rviz2")` is None → teaching status "RViz 2 not found — source your ROS 2 environment."
No pip-install path.

**Auto-fidelity wiring (in replay_panel):** clicking Open-in-RViz (a) sets `_clock_checkbox` +
`_static_seek_checkbox` checked; (b) if `self._replayer` exists with a sink that has no `.tracker`
(built without static_topics), rebuild the transport: capture play state, `_teardown_transport()`,
`_ensure_transport()`, resume if it was playing — seamless; (c) after the viewer is up, one-shot
`republish_static(self._sink)` so RViz re-primes `/tf_static`. Note `build_publish_sink` bakes
`publish_clock`/`static_topics` at build time (`_ensure_transport` L424-430) — that's why a rebuild is
required when toggled mid-play.

## 3. Overlay / smart-minimize — wiring

**Scrubber reuse:** `Scrubber(QSlider)` is pure presentation: `seeked(float)` on user drag,
`set_position(float)` programmatic (suppresses emit), `set_markers`, `set_loop_region`. The overlay
hosts its OWN `Scrubber` instance, synced to the panel.

**Panel remote-control API (add to ReplayPanel):**
- `positionChanged = Signal(float)` — emit in `_update_position` (after `self._scrubber.set_position(fraction)`).
- `toggle_play()` — play if not genuinely playing else pause.
- `skip_back()` / `skip_forward()` — call `_skip(-5)/_skip(+5)` (plan 23-02).
- `seek_fraction(f)` — call `_on_seeked(f)`.
- `current_fraction()` — `self._replayer.position_fraction if self._replayer else 0.0`.

**OverlayWindow(QWidget):** flags `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`; layout =
`‹5s`/`⏯`/`5s›` + `Scrubber` + `⛶`/`✕`; wire scrubber.seeked → `panel.seek_fraction`, buttons →
panel methods; connect `panel.positionChanged` → overlay scrubber `set_position`. Frameless drag via
`mousePressEvent`/`mouseMoveEvent` storing the press offset and `self.move(...)`.

**Trigger (corner widget):** `self.menuBar().setCornerWidget(btn, Qt.TopRightCorner)`. On click:
if the active panel is the Replay panel (`self._stack.currentWidget() is self.replay_panel`) →
`enter_overlay()` (hide main window, create/show overlay, `_ensure_transport` so the scrubber is live);
else `self.showMinimized()`. `enter_overlay` stores `self.saveGeometry()`; `restore` (overlay `⛶`) →
hide overlay, `self.showNormal()`/`raise_()`/`restoreGeometry`. `✕` → `self.close()` on MainWindow
(closeEvent chain already stops replay + closes rerun viewer; add rviz close).

**±5s skip math (plan 23-02, in ReplayPanel):**
```
_skip(delta_s): _ensure_transport(); cur = position_fraction * _bag_span_ns
  new = min(max(cur + delta_s*1e9, 0), _bag_span_ns); _replayer.seek(int(new)); _update_position()
  if _static_seek_checkbox checked and _sink: republish_static(_sink)
```
Buttons `‹ 5s` / `5s ›` added to the control bar (near Step). Works playing or paused (seek is
thread-safe, Phase 18).

## 4. Invariants & test conventions (MUST hold)

- **Offline/Qt-free guard:** `import rosbagger_desktop.*` panel/widget modules pull NO `rclpy`/`rosbags`;
  `import rosbagger_rerun.*` pulls no `rclpy`/`rerun`. Keep ALL `rclpy`/`rosbags`/`rerun`/`subprocess`-of-ros
  imports inside method/worker bodies. New modules (`rviz_config.py` pure, `rviz_session.py` lazy)
  must be added to the offline-guard test if they could leak. `rviz_config.py` = stdlib+yaml only
  (yaml is fine — it's pure). The RViz **launcher** lazy-imports nothing heavy (subprocess/shutil/os
  are stdlib) but is ROS-gated at the call site.
- **Thin face:** panels add NO analysis/bag/SQL/ROS logic; RViz config building is presentation/launch glue.
- **Tests:** offline headless in `tests/test_desktop.py` (+ a new `tests/test_rviz_config.py` for the
  pure builder). Live paths in `*_live.py` with `importorskip(rclpy)` (+ `rviz2`/rerun viewer skipif).
  Local runs need `PYTHONPATH=""` (host ROS leak). Headless button clicks use `button.click()` (not
  `mouseClick`). Qt offscreen SIGBUS at teardown is a known artifact — re-run. Live GUI lane:
  `PYTHONPATH="" uv run --with lark ... --no-cov` (pyyaml now bundled).
- **Worker pattern (CR-02):** keep BOTH `self._*_thread` and `self._*_worker` refs; clear in
  `_on_*_finished` AFTER `stop_thread`. Parentless `BlockingWorker` → use-after-free if dropped early.

## 5. Plan breakdown

- **23-01** Rerun live-mirror fix (session readiness + t0 anchor + surfaced errors). Wave 1.
- **23-02** ±5s skip controls + ReplayPanel remote-control API. Wave 2 (depends 23-01; shares replay_panel.py).
- **23-03** Open in RViz (pure config builder + launcher + button + auto-fidelity). Wave 3 (depends 23-02).
- **23-04** Compact overlay + corner-widget trigger + smart minimize. Wave 4 (depends 23-02, 23-03).

Sequential because all four touch `replay_panel.py` and `parallelization:false` in config — depends_on
chain keeps edits ordered and conflict-free.
