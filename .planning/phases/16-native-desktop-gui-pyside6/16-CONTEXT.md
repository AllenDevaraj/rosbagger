# Phase 16: Native Desktop GUI (PySide6) - Context

**Gathered:** 2026-05-25
**Status:** Ready for planning
**Source:** Brainstormed design spec (treated as locked decisions + UI/design contract)

<domain>
## Phase Boundary

Deliver a **native desktop GUI** for rosbagger as a new isolated workspace package
`rosbagger-desktop`, built on **PySide6 (Qt)**. Running `rosbagger-desktop [BAG]`
spawns a real OS window (`QMainWindow`) with **full parity** to the existing Textual
TUI's five panels: inspect / query / tf / record / replay. The GUI is a **thin
frontend** — it calls the existing `rosbagger_core` / `rosbagger_record` /
`rosbagger_replay` module APIs verbatim and contains no analysis, bag-reading, SQL,
or ROS logic of its own.

In scope: the new package, its five panels, capability gating, headless GUI tests,
the offline+Qt-free guard, and packaging wiring (uv.lock re-lock).

Out of scope (v1): packaged/double-click installer (PyInstaller/AppImage); any new
analysis logic; 3D visualization; any change to the existing TUI (`rosbagger-gui`).
</domain>

<decisions>
## Implementation Decisions (locked)

### Toolkit & package
- **D-01:** GUI toolkit is **PySide6 (Qt)**. PySide6 is declared ONLY in
  `rosbagger-desktop`'s `[project] dependencies` — never in any other package, never
  in the base/offline install graph.
- **D-02:** New workspace package **`rosbagger-desktop`** at `packages/rosbagger-desktop`,
  version `0.2.0`, console script `rosbagger-desktop = "rosbagger_desktop.cli:main"`.
  Sibling deps pinned `rosbagger-core>=0.2,<0.3`, `rosbagger-record>=0.2,<0.3`,
  `rosbagger-replay>=0.2,<0.3` (version spec only — no git/path URL baked into deps).
- **D-03:** The existing TUI package `rosbagger-gui` is **untouched**. Both frontends
  coexist. No edits to the source of core/bagq/record/replay/gui beyond additive
  packaging wiring (root workspace already globs `packages/*`; `[tool.uv.sources]`
  entry only if resolution requires it; re-locked `uv.lock`).

### Isolation (hard constraint — "do not interfere with anything we already have")
- **D-04:** The offline import invariant is preserved AND extended: `import rosbagger_core`
  / `import bagq` stay ROS-free, and a NEW guard asserts the core/offline import graph
  stays **Qt-free** (no PySide6 leak). This is the structural enforcement of isolation.
- **D-05:** Single production publish path retained — live replay reuses the shared
  `build_publish_sink`; no second publish path is introduced.

### Architecture (thin frontend, mirrors the TUI)
- **D-06:** `QMainWindow` with a left nav (panel list) + `QStackedWidget` for the active
  panel (desktop analog of the TUI sidebar + `ContentSwitcher`).
- **D-07:** The main window owns ONE shared `RosbagsReader` (from the launch BAG arg or a
  `QFileDialog`) and hands it to each panel — same App-owned-reader model as the TUI.
- **D-08:** Each panel is a self-contained `QWidget` calling the named module APIs; zero
  analysis logic in the GUI. ROS imports are lazy, inside method bodies only.
- **D-09:** Capability gate — record/replay panels are disabled with a teaching hint when
  `rclpy` is not importable (identical behavior to the TUI's tier-1 gate).

### Panel → API map (verbatim reuse)
- **D-10:** Inspect → `collect_bag_info`, `collect_table_schemas`.
- **D-11:** Query → `collect_table_schemas`, `query(sql, reader)`, `write_table`, `errors.*`.
- **D-12:** TF → `collect_tf_report`, `NoTransformsError`.
- **D-13:** Record (live) → `list_record_topics`/`discover_topics`, `record_topics`.
- **D-14:** Replay (live) → `Replayer`, `build_publish_sink`, `list_events`.

### Live panels & threading
- **D-15:** Blocking/long-running calls (discovery, `record_topics`, replay loop) run on
  `QThread` workers emitting signals back to the UI thread (desktop analog of the TUI's
  `@work(thread=True)`). The replay scrubber becomes a Qt slider + transport buttons.

### Launch & testing
- **D-16:** `rosbagger-desktop` opens an empty window; `rosbagger-desktop <BAG>` opens it on
  that bag; File ▸ Open uses `QFileDialog` (dir picker for ROS2, file for ROS1/MCAP).
  `--help` exits 0 without constructing Qt objects (argparse front door, App imported
  inside `main` — mirrors the TUI cli.py discipline).
- **D-17:** GUI tests use **pytest-qt** with `QT_QPA_PLATFORM=offscreen` → headless,
  ROS-free in CI (analog of the TUI's `App.run_test()`/`Pilot`). PySide6 + pytest-qt added
  to the dev group. Live record/replay covered on the existing `@pytest.mark.live` lane.
  ≥80% coverage gate continues to apply.

### Build increments (end state = full parity)
- **D-18:** Increment A — offline parity (package skeleton + main window + capability gate
  + inspect/query/tf panels + Qt-free guard + headless tests + re-locked uv.lock).
- **D-19:** Increment B — live parity (record + replay panels with QThread workers +
  scrubber; live coverage on the `@pytest.mark.live` lane).

### Claude's Discretion
- Exact PySide6 version pin (pick a current stable `>=6.x,<6.y` at plan time).
- Whether a `[tool.uv.sources]` entry for `rosbagger-desktop` is needed (expected: no — it
  depends only on already-sourced siblings).
- Internal widget composition, layout details, and signal/slot wiring within each panel.
- Whether increments A and B are separate plans/waves or finer-grained (planner decides).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design contract (authoritative)
- `docs/superpowers/specs/2026-05-25-rosbagger-desktop-gui-design.md` — the full approved
  design (goals, isolation rules, package layout, architecture, panel→API map, threading,
  testing, build increments). This IS the UI/design contract for the phase.

### Existing thin-frontend precedent to mirror
- `packages/rosbagger-gui/src/rosbagger_gui/app.py` — TUI App shell (sidebar + ContentSwitcher,
  App-owned shared reader, capability gate) to mirror in Qt.
- `packages/rosbagger-gui/src/rosbagger_gui/cli.py` — argparse front door (optional bag,
  `--help` exits 0 without building the UI) to mirror.
- `packages/rosbagger-gui/src/rosbagger_gui/panels/*.py` — the five TUI panels showing the
  exact module-API calls each panel makes.
- `packages/rosbagger-gui/pyproject.toml` — packaging precedent (version, sibling pins, live
  extra) for the new package's manifest.

### Module APIs the panels call (no new logic)
- `rosbagger_core.inspect` (collect_bag_info, collect_table_schemas),
  `rosbagger_core.backend.query` (query), `rosbagger_core.output.export` (write_table),
  `rosbagger_core.tf` (collect_tf_report), `rosbagger_core.errors`,
  `rosbagger_record` (list_record_topics/discover_topics, record_topics),
  `rosbagger_replay` (Replayer, build_publish_sink, list_events).

### Isolation guard to extend
- `tests/test_offline_guard.py` — existing ROS-free / heavy-stack guards; add a Qt-free
  assertion for the core/offline import graph.

### Host constraint
- ROS is sourced globally on this box: prefix every `uv` / test / lint command with
  `PYTHONPATH=""`; invoke ruff as `uv run ruff`.
</canonical_refs>

<specifics>
## Specific Ideas
- Full parity = all five panels, with the two live panels (record/replay) being the
  highest-effort area (QThread integration with rclpy + the scrubber/transport controls).
- The package skeleton + manifest should mirror `packages/rosbagger-gui` exactly for the
  packaging shape (version 0.2.0, sibling pins by spec, console script).
</specifics>

<deferred>
## Deferred Ideas
- Packaged/double-click installer (PyInstaller / AppImage / `.app`) — future follow-up.
- 3D visualization — permanently out of scope (rviz/Foxglove/Rerun territory).
</deferred>

---

*Phase: 16-native-desktop-gui-pyside6*
*Context gathered: 2026-05-25 from the approved design spec*
