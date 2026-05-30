---
phase: 22-replay-live-mirror-to-rerun
type: research
date: 2026-05-29
sources:
  - .planning/specs/2026-05-29-rerun-live-mirror-design.md (approved design)
  - rerun.io / ref.rerun.io / pypi rerun-sdk (API surface, verified 2026-05-30)
---

# Phase 22 — Research: live-mirror Play into Rerun

Grounds the three plans. The approved design spec
(`.planning/specs/2026-05-29-rerun-live-mirror-design.md`) holds the *why* and the locked
decisions; this doc pins the *how* against the real code + the current `rerun-sdk` API.

## §1. rerun-sdk Python API surface (verified 2026-05-30, stable 0.31.4)

Pin: **`rerun-sdk>=0.31,<0.33`**. The archetype/timeline API has churned across 0.x
(`Scalar`→`Scalars`; `set_time_nanos/_seconds/_sequence`→unified `set_time`), so every plan
that calls the SDK lists "verify the exact archetype/`set_time` signature against the
installed `rerun-sdk`" as a `read_first` — minor drift is absorbed at execution, not guessed.

- **Recording / viewer (session.py):** `rec = rr.RecordingStream("rosbagger")` then
  `rec.spawn()` (launch + stream to the bundled viewer) for the GUI, or `rec.save(path)`
  (write a `.rrd`, no viewer) for tests. Log via `rec.log(entity_path, archetype)` and set
  time via `rec.set_time(...)`. An explicit `RecordingStream` (not the global `rr.init`)
  keeps the sink testable (save-stream) and the GUI (spawn-stream) on one seam.
- **Timeline:** `rec.set_time("bag_time", duration=(item.t_ns - t0_ns) / 1e9)` — a 0-based
  seconds timeline (`t0_ns` = first item's `t_ns`, captured once) so Rerun's own scrubber
  matches the bag. (`duration=` takes seconds; `timestamp=` would be absolute epoch — relative
  is cleaner for replay.)
- **Archetypes used:**
  - `rr.Image(<HxWx3 uint8 rgb>)` (raw); `rr.DepthImage(<HxW>)` for `16UC1`;
    `rr.EncodedImage(contents=<bytes>, media_type="image/jpeg"|"image/png")` (CompressedImage).
  - `rr.Points3D(positions, colors=None, radii=None)` (LaserScan, PointCloud2).
  - `rr.Transform3D(translation=[x,y,z], rotation=rr.Quaternion(xyzw=[...]))` (TF).
  - `rr.Scalars(<float>)` (generic numeric fields → time series); `rr.TextLog(<str>)` (generic
    catch-all). NOTE: `Scalars` (plural) on 0.31; the verify step confirms.
- **Thread-safety:** `rec.log` is logged from the drive worker thread (off the GUI thread).
  Rerun's `RecordingStream` buffers + flushes internally; logging from one worker thread is
  supported. `rec.spawn()` runs on the GUI thread at toggle-on (quick subprocess launch).

## §2. Integration points in OUR code (exact anchors)

- **The tap — `build_publish_sink`** (`packages/rosbagger-replay/.../replay.py:40`, inner
  `sink(item)` at `:111`). Each `item` (a `ReplayItem`) exposes `item.topic` (str),
  `item.msgtype` (type string, e.g. `sensor_msgs/msg/Image`), `item.cdr` (raw CDR bytes),
  `item.t_ns` (int). The publish sink already does `get_message(item.msgtype)` +
  `deserialize_message(item.cdr, cls)`. **We do NOT modify `build_publish_sink`** — the
  rerun sink re-deserializes independently (cheap; keeps the production publish path the
  byte-for-byte sink protected by quick-task `260529-k6m`).
- **The panel wiring — `ReplayPanel`** (`packages/rosbagger-desktop/.../panels/replay_panel.py`):
  - Control bar built at `:121-127` (Play/Pause/Step/`rate:`/loop); added to layout at `:169`.
    The **Open in Rerun** button slots here (after the loop checkbox).
  - `__init__` keeps thread/worker refs at `:76-93` (the `260529-k6m` pattern). Add
    `self._rerun_sink` + `self._rerun_rec` (viewer handle) + `self._rerun_active` next to them.
  - `_ensure_transport` builds the sink at `:388-391` and constructs
    `Replayer(items, sink, ...)` at `:392`. The **dynamic tee** wraps `sink` here:
    `Replayer(items, composed, ...)` where `composed(item)` calls `sink(item)` then, if
    `self._rerun_sink is not None`, `self._rerun_sink(item)`. Toggling Rerun flips
    `self._rerun_sink` → no transport rebuild; `build_publish_sink` untouched.
  - `_teardown_transport` (`:416-429`, clears `self._sink` at `:423`) — also drop
    `self._rerun_sink`/`self._rerun_rec` here.
- **Capability gate — `capabilities.py`** (`ros_available()` does a lazy `import rclpy`).
  Add a sibling **`rerun_available()`** (lazy `import rerun`). The button is ROS-gated like the
  rest of the panel (live mirror) PLUS `rerun_available()`.

## §3. Message conversion specifics

- **Image** (`sensor_msgs/msg/Image`): build `np.frombuffer(msg.data, uint8).reshape(h, w, ch)`;
  `rgb8`→as-is; `bgr8`→`[..., ::-1]`; `mono8`/`8UC1`→2D; `16UC1`→`rr.DepthImage`
  (`np.frombuffer(uint16)`); unknown encoding → generic fallback (don't guess).
- **CompressedImage** (`sensor_msgs/msg/CompressedImage`): `msg.format` (e.g. `"jpeg"`,
  `"rgb8; jpeg compressed bgr8"`) → `media_type` via substring match (`jpeg`/`png`) →
  `rr.EncodedImage(contents=bytes(msg.data), media_type=...)`; unknown → fallback.
- **LaserScan** (`sensor_msgs/msg/LaserScan`): `angle = angle_min + i*angle_increment`;
  drop `inf`/`nan`/out-of-`[range_min,range_max]`; `xyz = [r*cos, r*sin, 0]` → `rr.Points3D`.
- **PointCloud2** (`sensor_msgs/msg/PointCloud2`): read `fields` for x/y/z offsets +
  `point_step`; `struct.unpack_from` per point (honor `is_bigendian`); optional rgb →
  `colors`. Bounded helper, no `sensor_msgs_py` dependency (offline-importable).
- **TF** (`tf2_msgs/msg/TFMessage` on `/tf`,`/tf_static`): per `TransformStamped`, log
  `rr.Transform3D(translation=[t.x,t.y,t.z], rotation=rr.Quaternion(xyzw=[r.x,r.y,r.z,r.w]))`
  at the child-frame entity path. v1: direct parent→child, Rerun's entity hierarchy composes
  the tree (no standalone tf2 buffer / time-interpolation — deferred).
- **Entity path:** strip-leading-slash of `header.frame_id` when present, else the topic name
  (`/camera/color/image_raw`→`camera/color/image_raw`). Frame-keyed paths give spatial
  coherence when TF exists and stay flat-but-viewable when it doesn't (the user's no-`/tf` bag).
- **Generic fallback:** walk the deserialized message's numeric leaf fields →
  `rr.Scalars` at `entity/field`; always also `rr.TextLog(repr-ish)` so the topic is never
  invisible. Recurse a bounded depth; arrays-of-numbers logged as length only (no explosion).

## §4. Test strategy (offline-first; live behind the ROS gate)

- **Offline converter unit tests** (CI-runnable): `rerun-sdk` is a pure wheel with NO ROS dep
  → add it to the **dev dependency group** so CI has it. Synthesize ROS messages with the
  rosbags typestore (`get_typestore(Stores.ROS2_HUMBLE).types[...]` — the same path the
  reader/replay tests already use) OR plain duck-typed objects, call each converter, assert the
  returned `rr.*` archetype type + key fields. No viewer, no ROS.
- **Offline-import invariant** (extend `tests/test_offline_guard.py`): `import rosbagger_rerun`
  pulls neither `rclpy` nor `rerun` (both lazy inside function bodies).
- **Live `.rrd` regression** (`tests/test_rerun_live.py`, `importorskip("rclpy")`, `-m live`):
  build `build_rerun_sink(rec)` with `rec = rr.RecordingStream(...); rec.save(tmp.rrd)`, drive a
  few real bag items through it, flush, assert the `.rrd` is non-empty (and parseable). Proves
  the deserialize→convert→log path with no GUI/viewer process. Skipped in CI + under
  `PYTHONPATH=""` (strips ROS); run with ROS on path + `uv run --with lark` (see
  `live-gui-tests-need-ros-and-lark`).
- **Live desktop** (`tests/test_desktop_live.py`): toggle Rerun on (save-mode injected),
  press Play via `play_button.click()` (programmatic — `mouseClick` drops on a non-visible
  widget), assert the `.rrd` got data. Mirrors the `260529-k6m` regression recipe.

## §5. Packaging

- **7th workspace member** `packages/rosbagger-rerun/` (`members=["packages/*"]` already globs
  it; add `packages/rosbagger-rerun/src` to the editable src list in root `pyproject.toml:53-58`).
- `rosbagger-rerun/pyproject.toml`: ROS-free, `rerun-sdk` under an **optional extra**
  (`[project.optional-dependencies] sdk = ["rerun-sdk>=0.31,<0.33"]`) so importing the package
  needs neither ROS nor rerun. Console-scriptless (library only).
- **Desktop** gains a regular dep on `rosbagger-rerun` (import-safe: no ROS/rerun pulled at
  import) so the button can `import rosbagger_rerun`. `rerun-sdk` itself stays **install-on-click**
  (`rerun_available()` false → button reads `Open in Rerun (install)` → runs
  `python -m pip install "rerun-sdk>=0.31,<0.33"` with status feedback, then re-probes).
- Dev group gains `rerun-sdk` (CI runs the offline converter tests).

## §6. Risks / decisions

- **rerun API churn** → version pin + per-plan "verify against installed version" read_first.
  ACCEPTED: minor signature fixes happen at execution, not in the plan text.
- **Double deserialize** (publish sink + rerun sink each `deserialize_message`) → ACCEPTED;
  mirroring is opt-in and visualization-rate; keeps `build_publish_sink` untouched (the whole
  point). A future `observers=` hook on `build_publish_sink` is the optimization, deferred.
- **RecordingStream thread-safety** → log only from the single drive worker; spawn on the GUI
  thread. No cross-thread RecordingStream sharing.
- **Offline invariant** is the load-bearing constraint: `rerun`/`rclpy`/`rosidl` imports stay
  inside function bodies; `tests/test_offline_guard.py` is the enforcement.
