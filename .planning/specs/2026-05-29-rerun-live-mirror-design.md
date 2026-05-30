---
title: Replay live-mirror to Rerun ("Open in Rerun")
date: 2026-05-29
status: approved-design
proposed_phase: "Phase 22 (new Milestone v0.6 — Live visualization)"
supersedes: null
author: brainstorming (allendevaraj33333@gmail.com + Claude)
---

# Replay live-mirror to Rerun — design spec

## Problem / goal

The desktop **Replay** tab can publish a bag to live ROS topics, but the only way to
*see* that data is an external viewer (RViz2), which forces manual per-display setup:
add each display, pick the right topic, and set a Fixed Frame (painful when the bag has
no `/tf`, as the user's `~/Desktop/rosbag` does — frame must be set to a sensor's
`frame_id`). Goal: a **one-click "Open in Rerun"** button that launches the Rerun viewer
and **auto-visualizes every topic** as Play runs — zero manual configuration — sitting
*alongside* (not replacing) the existing RViz2/ROS publish path.

## Decisions locked during brainstorming

1. **Source = live mirror of Play** (not an independent bag-read into Rerun). Rerun
   advances with the playhead; only shows data while Play runs.
2. **Tap point = fork Play's publish sink** (in-process), not a separate ROS subscriber
   node. Each message Play plays is, in the same instant, published to ROS *and* logged
   to Rerun. Consequence (accepted): Rerun mirrors **only this app's Play**, not a
   separate `ros2 bag play` run in a terminal.
3. **Visual scope = sensor essentials**: rich native visuals for Image/CompressedImage,
   LaserScan, PointCloud2, and TF; **generic fallback** for everything else so no topic
   is ever invisible.

## User-facing behavior (UX)

- New button at the **end of the Replay control bar** (after the loop checkbox, visually
  separated so it reads as "view", not a transport control): **`Open in Rerun`**.
- **Toggle semantics:**
  - **On** → launch the Rerun viewer (own window) + start mirroring. Press Play and the
    camera image, scan, cloud, and transforms stream into Rerun live, advancing with the
    playhead. RViz2 / `ros2 topic` keep working unchanged — this is *additive*.
  - **Off** (or the Rerun window is closed) → stop logging; Play keeps publishing to ROS
    normally.
- Toggle is valid **before or during** playback; no Play restart required.
- Rerun receives the bag timestamp per message, so its own timeline is scrubbable too.

## Architecture

### New package: `rosbagger-rerun` (the seam)

Mirrors how `rosbagger-replay` isolates ROS. **Top-level import stays both ROS-free and
Rerun-free** (offline-import invariant): every `rclpy` / `rerun` / `rosidl_runtime_py`
import lives **inside** a function body. Added as a 7th workspace member under
`packages/*` (root `pyproject.toml` `members = ["packages/*"]` already globs it; also add
its `src` to the explicit editable path list, currently `pyproject.toml:53-58`).

Modules:

- `converters.py` — pure `ros_msg → Rerun archetype(s)` functions (image, laserscan,
  pointcloud2, tf, generic fallback). Offline-unit-testable.
- `sink.py` — `build_rerun_sink(recording, ...)` returns `rerun_sink(item)`:
  `get_message(item.msgtype) → deserialize_message(item.cdr, cls) → dispatch converter →
  rr.log(entity_path, archetype)` stamped with `item.t_ns` on a `bag_time` timeline. The
  **structural twin of `build_publish_sink`** (`packages/rosbagger-replay/.../replay.py:40`).
- `session.py` — `open_viewer()` (spawn the bundled Rerun viewer), `rerun_available()`
  capability probe, teardown.
- `__init__.py` — lazy front door (no ROS/Rerun import at module top).

### The fork (how it taps Play)

In `ReplayPanel._ensure_transport`
(`packages/rosbagger-desktop/.../panels/replay_panel.py`, sink built ~line 388), instead
of handing the bare publish sink to the `Replayer`, hand it a **tee**:

```python
def composed(item):
    sink(item)                          # → ROS graph (today, unchanged)
    if self._rerun_sink is not None:    # → Rerun, only while toggled on
        self._rerun_sink(item)
self._replayer = Replayer(items, composed, ...)
```

`self._rerun_sink` is `None` until the Rerun toggle is on, so toggling is just flipping
that reference — **no transport rebuild, and `build_publish_sink` is untouched** (zero
risk to the production publish path fixed in quick task 260529-k6m). The Rerun sink
re-deserializes the item independently (cheap; keeps the shared publish path pristine).
The kept `self._rerun_sink` / viewer handle follow the same worker/teardown discipline as
`self._sink` and fold into `_teardown_transport`.

### Converters, entity paths & TF (the meat)

- **Image / CompressedImage** → `rr.Image` (handle rgb8/bgr8/mono8/16UC1; reorder bgr→rgb)
  / encoded passthrough for compressed.
- **LaserScan** → polar→cartesian (`angle_min + i·angle_increment`) → `rr.Points3D`.
- **PointCloud2** → unpack x/y/z(+rgb) fields → `rr.Points3D`.
- **TF (`/tf`, `/tf_static`)** → `rr.Transform3D` per child frame.
- **Entity paths** keyed off each message's `header.frame_id`, so when TF exists, sensor
  data sits under the frame TF positions (real spatial coherence); when it does **not**
  (the user's bag — no `/tf`), everything still logs flat under its `frame_id` and is
  fully viewable.
- **v1 TF simplification (the trickiest part):** log each transform as a direct
  parent→child `Transform3D` and let Rerun's entity hierarchy compose them, rather than
  building a standalone tf2 buffer with time-interpolated lookups. Correct for normal
  single-root trees; multi-root and time-interpolated lookups are **deferred**.

### Generic fallback (guarantees nothing is invisible)

Any msgtype without a rich converter: walk the deserialized message, log numeric fields as
`rr.Scalar` time-series (plottable), and the whole message as a text entry. Every topic
therefore appears in Rerun, always.

### Dependency & gating

- `rerun-sdk` is **not** currently a dependency anywhere and pulls in **no ROS** (clean
  pip wheel — installs in CI). It becomes `rosbagger-rerun`'s own dependency.
- The button is **ROS-gated like the rest of the Replay panel** (it mirrors live Play),
  plus a `rerun_available()` check (the Qt analog of `capabilities.ros_available()` in
  `packages/rosbagger-desktop/.../capabilities.py`).
- **Install UX:** if `rerun-sdk` is missing, the button reads **`Open in Rerun (install)`**
  and clicking it runs the install with status feedback, then proceeds — realizing the
  "auto-install" intent behind a single consent click (no silent pip on launch).

### Threading & lifecycle

- Conversion + `rr.log` happen **inside the drive worker** (the `BlockingWorker` thread)
  — off the GUI thread, so no UI stalls. Rerun's `RecordingStream` is logged from that
  worker thread.
- The viewer spawn happens on toggle-on (GUI thread; it's a quick subprocess launch).
- Teardown drops `self._rerun_sink` + viewer handle, folded into the existing
  `_teardown_transport`.

## Testing strategy

- **Offline (CI):** converter unit tests — synthesize messages via the rosbags typestore,
  assert the emitted Rerun archetypes. `rerun-sdk` installs with no ROS, so these run in
  CI. Plus the offline-import invariant test (importing `rosbagger_rerun` pulls no
  `rclpy`/`rerun`).
- **Live (ROS-gated):** drive a few bag items through `build_rerun_sink` in **`rr.save()`
  (write-to-`.rrd`, no viewer)** mode and assert the `.rrd` is non-empty — a real
  regression with no GUI/viewer process needed. (Live tests are skipped in CI and under
  `PYTHONPATH=""`; run with ROS on path + `uv run --with lark` per the live-test note.)

## Out of scope (YAGNI, v1)

- Mirroring an external `ros2 bag play` (would need the separate-subscriber design).
- OccupancyGrid (map) / IMU / Pose / Odometry / Path / Markers rich converters — the
  generic fallback covers them as plots/text; promote later as bags demand.
- Time-interpolated / multi-root TF lookups.
- Per-topic Rerun blueprint/layout customization.
- Recording the live mirror to a persistent `.rrd` from the GUI.

## Success criteria

1. With ROS sourced + `rerun-sdk` installed, clicking **Open in Rerun** then **Play** on
   `~/Desktop/rosbag` shows the camera image and the `/scan` points updating live in the
   Rerun viewer, with no manual display/frame setup.
2. RViz2 and `ros2 topic echo` still receive the same topics unchanged (additive).
3. A topic with no rich converter still appears in Rerun (fallback).
4. `import rosbagger_rerun` triggers no `rclpy`/`rerun` import (offline invariant test
   passes); full offline suite stays green at ≥80% coverage.
5. Live `.rrd` regression test asserts non-empty output for a driven bag.

## Process notes

- Build routes through **GSD** per `CLAUDE.md`: proposed as **Phase 22** under a new
  **Milestone v0.6 — Live visualization (Rerun)**; `/gsd-plan-phase` produces the
  executable `PLAN.md` (reviewed before `/gsd-execute-phase`).
- This spec is the design input that planning consumes.
