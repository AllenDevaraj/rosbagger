# Phase 22: Replay live mirror to Rerun — Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Source:** Brainstorming (approved design spec `.planning/specs/2026-05-29-rerun-live-mirror-design.md`)

<domain>
## Phase Boundary

Add an **Open in Rerun** toggle to the desktop Replay control bar that **live-mirrors Play**
into the Rerun viewer with zero manual setup — replacing the manual RViz add-display /
Fixed-Frame dance. Additive: RViz / `ros2 topic` keep working. New ROS-isolated
`rosbagger-rerun` package holds the converters; the offline import graph stays ROS-free AND
Rerun-free. v1 = sensor essentials + generic fallback.
</domain>

<decisions>
## Implementation Decisions (LOCKED via AskUserQuestion)

### Source
- **Live mirror of Play**, not an independent bag-read into Rerun. Rerun advances with the
  playhead; only shows data while Play runs.

### Tap point
- **Fork Play's publish sink** (in-process dynamic tee), NOT a separate ROS subscriber node.
  Each played message is published to ROS (unchanged) and, while the toggle is on, also
  logged to Rerun — same instant, perfectly in sync.
- **`build_publish_sink` is byte-for-byte untouched.** The tee reads `self._rerun_sink`
  dynamically, so toggling needs no transport rebuild. The rerun sink re-deserializes the
  item independently (accepted cost; protects the `260529-k6m` publish path).
- Consequence ACCEPTED: mirrors only THIS app's Play, not a separate terminal `ros2 bag play`.

### Visual scope
- **Sensor essentials** get rich native visuals: Image/CompressedImage, LaserScan,
  PointCloud2, TF. **Generic fallback** (numeric→`rr.Scalars`, all→`rr.TextLog`) catches every
  other topic so nothing is invisible.
- v1 TF = direct parent→child `Transform3D` (Rerun entity hierarchy composes the tree); no
  standalone tf2 buffer / time-interpolated lookups.

### Gating & dependency
- Button is **ROS-gated** (live mirror) + **`rerun_available()`**-gated. `rerun-sdk` is an
  **optional** dep, **install-on-click** (`Open in Rerun (install)` → `pip install
  rerun-sdk` with status feedback → re-probe). No silent pip on launch.

### Threading
- Conversion + `rec.log` run inside the existing drive `BlockingWorker` thread (off the GUI
  thread). Viewer spawn on the GUI thread at toggle-on.

### Claude's Discretion
- Exact entity-path scheme, converter internals, the generic-walk depth bound, and the
  precise `rerun-sdk` archetype/`set_time` call signatures (verified against the installed
  version at execution — see RESEARCH §1).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `.planning/specs/2026-05-29-rerun-live-mirror-design.md` — approved design (the why + scope fence)
- `.planning/phases/22-replay-live-mirror-to-rerun/22-RESEARCH.md` — API surface + integration anchors

### Code this phase forks/wires (do NOT modify the sink)
- `packages/rosbagger-replay/src/rosbagger_replay/replay.py` — `build_publish_sink` (`:40`/inner `:111`); the tap
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py` — control bar `:121`, sink build `:388`, Replayer `:392`, teardown `:416`
- `packages/rosbagger-desktop/src/rosbagger_desktop/capabilities.py` — `ros_available()` pattern → add `rerun_available()`
- `packages/rosbagger-replay/src/rosbagger_replay/__init__.py` — front-door / lazy-import pattern to MIRROR
- `tests/test_offline_guard.py` — the offline-import invariant to EXTEND
- `pyproject.toml:53-58` — editable src path list (add the new member)
</canonical_refs>

<specifics>
## Specific Ideas
- New package modules: `converters.py`, `sink.py` (`build_rerun_sink`), `session.py`
  (`open_viewer`/`rerun_available`), `__init__.py` (lazy front door). Structural twin of
  `rosbagger-replay`.
- Live `.rrd` regression via `RecordingStream.save()` (no viewer process) — verifiable in CI's
  ROS lane.
</specifics>

<deferred>
## Deferred Ideas (NOT in v1)
- Mirroring external `ros2 bag play` (separate-subscriber design).
- OccupancyGrid (map) / IMU / Pose / Odometry / Path / Markers rich converters (fallback covers them).
- Time-interpolated / multi-root TF lookups.
- Per-topic Rerun blueprint/layout customization; persistent `.rrd` recording from the GUI.
- An `observers=` hook on `build_publish_sink` to avoid double-deserialize (optimization).
</deferred>

---

*Phase: 22-replay-live-mirror-to-rerun*
*Context gathered: 2026-05-29 via brainstorming → approved spec*
