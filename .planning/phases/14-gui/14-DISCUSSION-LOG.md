# Phase 14: GUI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 14-gui
**Areas discussed:** Layout & navigation, Bag selection / session, Capability-gating UX, Panel depth & interactivity

---

## Layout & navigation

| Option | Description | Selected |
|--------|-------------|----------|
| Tabbed (one at a time) | TabbedContent — one panel fills the screen, switch via tab bar/keys | |
| Sidebar + content pane | Left nav list of the five panels, selected panel renders in the main pane (IDE-style) | ✓ |
| Dashboard grid | Multiple panels tiled at once | |

**User's choice:** Sidebar + content pane
**Notes:** —

---

## Bag selection / session

| Option | Description | Selected |
|--------|-------------|----------|
| Launch-arg, both later | `rosbagger-gui <bag>`; picker deferred | |
| Launch-arg + in-TUI picker | Accept a path arg AND an in-TUI open/switch picker | ✓ |
| In-TUI picker only | No launch arg; always browse inside the TUI | |

**User's choice:** Launch-arg + in-TUI picker
**Notes:** Offline panels share the one currently-loaded bag; launch-arg path is what SC3 exercises; picker is in v1, not deferred.

---

## Capability-gating UX (presentation)

| Option | Description | Selected |
|--------|-------------|----------|
| Visible but disabled + hint | Live tabs always show, greyed/disabled with a teaching hint | ✓ |
| Hidden entirely | Live panels don't appear without ROS | |
| Visible + live status banner | Panels visible, global status bar shows ROS state | |

**User's choice:** Visible but disabled + teaching hint

## Capability-gating — ROS detection mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| rclpy importable | Enable when `import rclpy` succeeds | |
| Live topics present | Spin up a discovery scan; enable only when topics published | |
| Tiered (import to enable, scan on open) | rclpy-importable enables the tab; opening record runs a live scan | ✓ |

**User's choice:** Tiered
**Notes:** Cheap gate up front, accurate discovery scan on demand for the record panel checklist.

---

## Panel depth & interactivity

| Option | Description | Selected |
|--------|-------------|----------|
| Functional but minimal | Real face over each API, nothing more | |
| Read/display only | Mostly display; no export, no interactive replay | |
| Rich/interactive | Schema browser, query history, scrubber/jump-to-event, etc. | ✓ |

**User's choice:** Rich/interactive (bounded by the thin-face rule — rich UI, zero new business logic)

### Rich features selected for v1 (multiSelect — all chosen)

| Feature | Selected |
|---------|----------|
| Query history + re-run | ✓ |
| Schema/topic browser | ✓ |
| Replay scrubber + jump-to-event (events sidecar) | ✓ |
| Query result export buttons (CSV/Parquet) | ✓ |

### Replay transport interactivity

| Option | Description | Selected |
|--------|-------------|----------|
| Full controls | play/pause/step/seek/rate/loop wired live to the Replayer | ✓ |
| Core subset | play/pause/stop + rate only | |
| Fire-and-configure | Set args up front, no live mid-playback control | |

**User's choice:** Full controls
**Notes:** Flagged the thin-vs-rich tension; confirmed rich = UI affordances over existing APIs, no new logic. The events-sidecar jump-points Phase 13 deferred to Phase 14 are in scope here.

---

## Claude's Discretion

- TUI testing strategy (Textual `Pilot` / `App.run_test()` against a fixture bag for SC3) — research item.
- Keeping `rosbagger-gui` offline-importable (lazy live-package imports + extend `test_offline_guard.py`) — follows Phase 12/13 pattern.
- Module layout, widget composition, keyboard bindings, theme, empty-state when launched with no bag.
- Whether GUI coverage stays out of the `--cov=rosbagger_core --cov=bagq` gate (mirroring Phase 13 D-12).

## Deferred Ideas

- 3D / pointcloud / robot-model visualization (rviz / Foxglove / Rerun own it).
- Rich timeseries plotting in the TUI (PlotJuggler / Foxglove own it).
- Multi-bag catalog / search across many bags.
- Topic remapping / per-topic QoS in the replay panel (inherited from Phase 13).
- Interactive `/clock` + `use_sim_time` simulated-clock replay (Phase 13 deferral).
