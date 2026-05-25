# rosbagger-desktop — Native Desktop GUI (PySide6) Design

*Date: 2026-05-25*
*Status: approved design — pre-implementation spec*
*Author: brainstormed with the maintainer*

## Summary

Add a **native desktop GUI** for rosbagger as a new, fully isolated workspace
package `rosbagger-desktop`, built on **PySide6 (Qt)**. Running `rosbagger-desktop`
spawns a real OS window (a `QMainWindow`) with full parity to the existing Textual
TUI's five panels: inspect / query / tf / record / replay.

The GUI is a **thin frontend**: it calls the existing `rosbagger_core` /
`rosbagger_record` / `rosbagger_replay` module APIs verbatim and contains no
analysis, bag-reading, SQL, or ROS logic of its own. The existing TUI package
`rosbagger-gui` is left **completely untouched** — both frontends coexist.

## Goals

- One command → a native desktop window opens (console script `rosbagger-desktop [BAG]`).
- Full feature parity with the TUI's five panels, reusing the same module APIs.
- Genuinely native look + behavior (native widgets, file dialogs, threading).

## Non-Goals (v1)

- No packaged/double-click installer (PyInstaller / AppImage / `.app`) — launch is
  via the console script. (Possible future follow-up.)
- No new analysis logic — zero reimplementation of bag IO, SQL, tf, record, replay.
- No 3D visualization (pointclouds, robot model) — remains rviz / Foxglove / Rerun
  territory, per the standing project Out-of-Scope.

## Hard Constraint: Isolation ("do not interfere with anything we already have")

This is a first-class design requirement, not a nice-to-have:

1. **New package only.** All new code lives under `packages/rosbagger-desktop/`.
   No edits to the source of `rosbagger-core`, `bagq`, `rosbagger-record`,
   `rosbagger-replay`, or `rosbagger-gui` (the TUI).
2. **Dependency isolation.** `PySide6` is declared *only* in
   `rosbagger-desktop`'s `[project] dependencies`. It must never appear in any
   other package's deps and must never enter the base/offline install graph.
3. **Offline invariant preserved AND extended.** The existing guarantee —
   `import rosbagger_core` / `import bagq` pull no ROS — still holds. We add a new
   guard asserting the core/offline import graph also stays **Qt-free** (no
   `PySide6` leak). This is the structural enforcement of the isolation rule.
4. **Single publish path retained.** Live replay reuses the shared
   `build_publish_sink` (the one production publish path); no second publish path
   is introduced.
5. **Minimal shared-file surface.** The root workspace already globs
   `members = ["packages/*"]`, so the new package is auto-discovered. The only
   shared-file changes are a re-locked `uv.lock` (and a `[tool.uv.sources]` entry
   only if resolution requires one — `rosbagger-desktop` depends on already-sourced
   siblings, so likely none). These boundaries are called out so review can confirm
   nothing else changed.

## Package Layout

```
packages/rosbagger-desktop/
  pyproject.toml                     # version 0.2.0; deps: PySide6, rosbagger-core>=0.2,<0.3,
                                     #   rosbagger-record>=0.2,<0.3, rosbagger-replay>=0.2,<0.3
                                     # [project.scripts] rosbagger-desktop = "rosbagger_desktop.cli:main"
  src/rosbagger_desktop/
    __init__.py                      # __version__ = "0.2.0"; import-light, Qt-free at top level
    cli.py                           # argparse front door: optional BAG arg → MainWindow(bag_path).run
    main_window.py                   # QMainWindow: nav list + QStackedWidget; owns the shared reader; capability gate
    capabilities.py                  # tier-1 rclpy-availability probe (mirrors the TUI gate); lazy, no eager ROS import
    panels/
      __init__.py
      inspect_panel.py               # collect_bag_info + collect_table_schemas
      query_panel.py                 # collect_table_schemas + query() + write_table (+ errors)
      tf_panel.py                    # collect_tf_report (+ NoTransformsError)
      record_panel.py                # (live) discover/list_record_topics + record_topics on a QThread worker
      replay_panel.py                # (live) Replayer + build_publish_sink on a QThread worker
    widgets/
      scrubber.py                    # Qt transport slider + play/pause/step/seek/rate/loop controls
    workers.py                       # QThread/QObject worker scaffolding for live panels
  tests/                             # pytest-qt, QT_QPA_PLATFORM=offscreen (headless, ROS-free)
```

## Architecture

A `QMainWindow` is the desktop analog of the TUI's App shell:

- **Left nav** (a `QListWidget`) selects a panel; a **`QStackedWidget`** shows the
  active panel — analogous to the TUI sidebar + `ContentSwitcher`.
- **Shared reader ownership.** The main window opens a single `RosbagsReader`
  (from the launch `BAG` arg or via a `QFileDialog`) and passes it to each panel —
  the same App-owned-reader model the TUI uses. Panels never open their own readers.
- **Capability gate.** `capabilities.py` performs a cheap tier-1 check for whether
  `rclpy` is importable. When absent, the record and replay nav entries are
  disabled with a teaching tooltip — identical behavior to the TUI's gate. Every
  ROS import is lazy, inside method bodies, never at module top.
- Each panel is a self-contained `QWidget`. It can be understood, built, and tested
  independently; it depends only on the shared reader + the named module APIs.

## Panel → API Map (verbatim reuse — no new logic)

| Panel | Reuses |
|-------|--------|
| Inspect | `rosbagger_core.inspect.collect_bag_info`, `collect_table_schemas` |
| Query | `collect_table_schemas`, `rosbagger_core.backend.query.query`, `rosbagger_core.output.export.write_table`, `rosbagger_core.errors.*` |
| TF | `rosbagger_core.tf.collect_tf_report`, `NoTransformsError` |
| Record (live) | `rosbagger_record.list_record_topics` / `discover_topics`, `record_topics` |
| Replay (live) | `rosbagger_replay.Replayer`, `build_publish_sink`, `list_events` |

## Live Panels & Threading (the highest-effort area)

- Blocking/long-running calls — topic discovery, `record_topics`, and the replay
  loop — run on **`QThread` workers** (a `QObject` moved to a `QThread`, emitting
  signals back to the UI thread). This is Qt's standard concurrency pattern and the
  desktop analog of the TUI's `@work(thread=True)` workers. The UI thread is never
  blocked.
- Replay drives the **pure `Replayer`** state machine through the shared
  `build_publish_sink` — the single production publish path. The TUI's custom
  scrubber widget becomes a Qt slider + transport buttons (`widgets/scrubber.py`),
  emitting play/pause/step/seek/rate/loop intents to the worker.
- ROS context lifecycle (init/shutdown) stays inside the live panels, lazy, and
  re-entrant-safe (the existing record/replay APIs already guarantee this).

## Launch & UX

- `rosbagger-desktop` → opens an empty window (no bag); a **File ▸ Open** menu uses
  `QFileDialog` (directory picker for ROS 2 / file picker for ROS 1 `.bag` / MCAP).
- `rosbagger-desktop /path/to/bag` → opens the window with that bag loaded.
- `--help` exits 0 without constructing any Qt objects (argparse front door, App
  imported inside `main` — mirrors the TUI's `cli.py` discipline).

## Error Handling

- Bag-open / read / query / tf errors surface as Qt message dialogs or inline panel
  banners carrying the message from the already-teaching core errors
  (`UnknownTableError`, `UnknownColumnError`, `UnresolvedTypeError`,
  `NoTransformsError`, `FileNotFoundError`). The GUI presents; it never re-derives
  error text.
- Live-panel failures (no ROS graph, publish errors) are reported in-panel without
  crashing the window; the worker thread is torn down cleanly.

## Testing (keeps "runs anywhere, no display")

- **`pytest-qt`** with `QT_QPA_PLATFORM=offscreen` runs GUI tests headless and
  ROS-free in CI — the desktop analog of the TUI's `App.run_test()` / `Pilot`
  approach. PySide6 + pytest-qt are added to the dev group so CI exercises the GUI.
- Offline panels (inspect/query/tf) are covered against a `make_fixtures` bag,
  ROS-free. Live record/replay are covered on the existing `@pytest.mark.live`
  ROS-sourced lane.
- A new **Qt-free offline guard** asserts the core/offline import graph pulls no
  `PySide6` (added alongside the existing ROS-free guards in
  `tests/test_offline_guard.py`).
- Project ≥80% coverage gate continues to apply.

## Build Increments (end state = full parity)

The phased split de-risks the largest scope while ending at full parity:

- **Increment A — offline parity:** package skeleton + `pyproject.toml` + `cli.py`
  + `main_window.py` + `capabilities.py` + inspect/query/tf panels + the Qt-free
  offline guard + headless pytest-qt tests + re-locked `uv.lock`.
- **Increment B — live parity:** `workers.py` + record + replay panels + the Qt
  scrubber, with live coverage on the `@pytest.mark.live` lane.

## Open Questions (resolve at planning)

- Exact PySide6 version pin (`PySide6>=6.x,<6.y`) — pick a current stable line at
  plan time.
- Whether any `[tool.uv.sources]` entry is needed for `rosbagger-desktop` (expected:
  no — it depends only on already-sourced siblings).
