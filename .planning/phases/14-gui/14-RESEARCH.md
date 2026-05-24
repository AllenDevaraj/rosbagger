# Phase 14: GUI - Research

**Researched:** 2026-05-23
**Domain:** Textual TUI (terminal UI) as a thin face over existing `rosbagger` module APIs
**Confidence:** HIGH (module APIs read from source; Textual core verified against current docs + installed 8.2.7)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Sidebar + content pane.** A left nav list of the five panels; the selected panel renders in the main content pane (IDE-style). Not tabbed-only, not a tiled dashboard.
- **D-02 — Launch-arg AND an in-TUI file/path picker.** `rosbagger-gui <bag-path>` loads a bag at startup; an in-TUI picker lets the user open/switch bags without relaunching. All offline panels (inspect/query/tf) share the one currently-loaded bag. The launch-arg path is what SC3 exercises; the picker is part of v1, not deferred.
- **D-03 — Live panels visible but disabled + teaching hint.** Record/replay panels always appear in the sidebar but render greyed/disabled with a teaching hint ("source your ROS 2 environment to enable") when no ROS graph is present. Not hidden. Mirrors the CLI's `RosNotAvailableError` ethos.
- **D-04 — Tiered ROS detection.** `import rclpy` succeeding (ROS 2 sourced) *enables* the live tabs; *opening* the record panel then runs a live topic-discovery scan (`rosbagger_record.discovery.discover_topics`) to populate its checklist. Cheap gate up front, accurate scan on demand. A panel-level live capability error still fires if the graph turns out empty.
- **D-05 — Inspect panel:** rich read view over `collect_bag_info` / `collect_table_schemas` (topics, types, counts, duration, approx Hz, size).
- **D-06 — Query panel:** SQL input + results table over the existing `query()` backend, **plus all of:** query history + re-run, a schema/topic browser tree (click a column to insert into SQL), and CSV/Parquet export buttons over the existing output/export path.
- **D-07 — TF panel:** report view over `collect_tf_report` (parent→child graph + per-edge gap detection), reusing the existing rich-table rendering shape.
- **D-08 — Record panel (live):** topic checklist populated by the on-open discovery scan (D-04) + start/stop, over the `rosbagger_record.record` / `list_topics` API.
- **D-09 — Replay panel (live):** **full transport controls** — play / pause / step / seek / rate / loop — wired live to the existing `Replayer` state machine, **plus a scrubber timeline** (wired to `Replayer.seek()`) **and jump-to-event markers** sourced from the `<bag>.events.parquet` sidecar. Drives the production `replay_bag()` front door, never re-implements the publish path.

**The thin-face rule is NON-NEGOTIABLE:** every panel calls an existing module API. "Rich" means richer UI affordances over those APIs, never new logic in the GUI. If a desired affordance needs logic that doesn't exist in a module API, it belongs in the module (or a future phase), not the GUI.

### Claude's Discretion
- TUI testing strategy — use Textual's `Pilot` / `App.run_test()` to drive panels headless against a fixture bag (the SC3 proof mechanism).
- Keeping `rosbagger-gui` offline-importable: live panels lazy-import `rosbagger_record` / `rosbagger_replay` behind the gating; `tests/test_offline_guard.py` is extended to assert `import rosbagger_gui` pulls no `rclpy` / `rosbag2_py`.
- Exact module layout, widget composition, keyboard bindings/shortcuts, theme, and the empty-state when launched with no bag.
- Whether the GUI's own coverage stays out of the `--cov=rosbagger_core --cov=bagq` gate, mirroring the live-package precedent (D-12 of Phase 13).

### Deferred Ideas (OUT OF SCOPE)
- **3D / pointcloud / robot-model visualization** — rviz / Foxglove / Rerun own it.
- **Rich timeseries plotting in the TUI** — `--plot` stays intentionally minimal; PlotJuggler/Foxglove own this.
- **Multi-bag catalog / search across many bags** — offline panels share one loaded bag in v1.
- **Topic remapping / per-topic QoS in the replay panel** — inherited deferral from Phase 13; v1 replay uses module defaults.
- **Interactive `/clock` + `use_sim_time` simulated-clock replay** — Phase 13 deferral; v1 paces on wall-clock.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GUI-01 | Five capability-gated panels (record/inspect/query/tf/replay) over module APIs | Textual `App` + sidebar `ListView`/`OptionList` + `ContentSwitcher` (Pattern 1); each panel is a `Widget` calling exactly one module API (Architectural Responsibility Map). SC1 = launch + 5 panels; SC2 = `disabled` reactive gates live panels (Pattern 3); SC3 = `App.run_test()`/`Pilot` drives inspect+query against a fixture bag asserting real `rosbagger_core` output (Pattern 2 / Code Example 2). |
</phase_requirements>

## Summary

Phase 14 is a **UI-integration phase, not a logic phase**. Every capability already exists as a read-only or driveable module API, verified by reading the source:

- `collect_bag_info(reader)` / `collect_table_schemas(reader)` → frozen dataclasses (inspect, D-05).
- `query(sql, reader)` → `pyarrow.Table`; `output.export.write_table(table, path)` writes CSV/Parquet by extension (query + export, D-06).
- `collect_tf_report(reader)` → `TfReport` (frames / per-edge `EdgeReport` / `GapReport` timeline) (tf, D-07).
- `events.list_events(bag)` → `pyarrow.Table` with columns `t_start_ns, t_end_ns, label, note` (replay jump markers, D-09).
- `rosbagger_record.discover_topics(node)` / `select_topics(...)` / `record(...)` / `list_topics()` (record, D-04/D-08).
- `rosbagger_replay.load_items(...)` → `list[ReplayItem(t_ns, topic, msgtype, cdr)]`, the **pure** `Replayer` transport state machine (play/pause/step/seek/set_rate/loop + `run()`), and the production `replay_bag()` front door (replay, D-09). The `Replayer` takes injectable `sink`/`clock`/`sleep` — a perfect seam for a TUI driver.

The genuinely unknown surface is **Textual**. The installed version is **8.2.7** (latest on PyPI as of 2026-05-23). Textual provides everything the panels need: `ListView`/`OptionList` (sidebar), `ContentSwitcher` (swap panels over a shared layout), `DataTable` (query results / inspect / tf tables), `Tree` (schema browser), `Input`/`TextArea` (SQL box), `Button` (export/start/stop/transport), `ProgressBar`, and a `disabled` + `loading` reactive on every `Widget` (the D-03 gating affordance). There is **no built-in slider/scrubber** — the replay timeline (D-09) is a small custom `Widget` (recommended) wired to `Replayer.seek()`. Headless testing is first-class via `App.run_test()` → `Pilot` (async), which is the SC3 proof mechanism.

Two hard constraints carry over from Phases 12/13 and must shape the plan: (1) **`import rosbagger_gui` must stay ROS-free** — live panels lazy-import `rosbagger_record`/`rosbagger_replay` inside method bodies, and `test_offline_guard.py` gets a new `import rosbagger_gui` assertion; (2) **never block the Textual event loop** — the `Replayer.run()` loop and the record/discovery spin loops are blocking and MUST run in a `@work(thread=True)` worker, updating widgets via `call_from_thread` / posted messages.

**Primary recommendation:** Build `rosbagger-gui` as a uv workspace member depending on `rosbagger-core` + `textual` (mirror `rosbagger-replay/pyproject.toml`); one `App` with a `Horizontal(ListView, ContentSwitcher)` shell and one `Widget` subclass per panel that holds a reference to the shared open reader and calls exactly one module API. Gate live panels with the `disabled` reactive driven by a cheap top-level `import rclpy` check (no module-top ROS import). Run all long-running ROS work in thread workers. Prove SC3 with `App.run_test()` against a `tools/make_fixtures.py` bag.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Panel navigation / layout | GUI (Textual `App`) | — | Pure UI shell; no business logic. |
| Bag open / shared reader lifecycle | GUI (owns `with RosbagsReader(...)`) | `rosbagger_core.reader` | `query()`/`collect_*` all take an *already-open* reader; the App owns the context-manager lifecycle (Open Q2 of Phase 5). |
| Inspect / table-schema read | `rosbagger_core.inspect` | GUI renders dataclasses | API-first; GUI is a thin renderer over `BagInfo`/`TableSchema`. |
| SQL execution + export | `rosbagger_core.backend.query` + `output.export` | GUI collects SQL string + path | All SQL/format logic is in core; GUI passes a string and a path. |
| TF report | `rosbagger_core.tf` | GUI renders `TfReport` | Identical shape to the `bagq tf` CLI renderer. |
| Event jump markers | `rosbagger_core.events` | GUI maps rows to scrubber marks | `list_events(bag)` returns the sidecar table; GUI only positions markers. |
| Live topic discovery + record | `rosbagger_record` (rclpy) | GUI thread worker | ROS-bound; lazy-imported, run off-loop. |
| Live replay transport | `rosbagger_replay.Replayer` + `replay_bag()` | GUI thread worker + injectable sink | Transport state machine is pure + already built; GUI drives it, never re-implements pacing/seek. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `textual` | `>=8,<9` (installed 8.2.7) | The TUI framework: App, widgets, CSS, reactivity, workers, headless test harness | The de-facto Python TUI framework; ships `App.run_test()`/`Pilot` for deterministic headless tests (the SC3 mechanism). `[VERIFIED: npm/PyPI registry via pip index + slopcheck OK]` for existence; framework choice is roadmap-locked. |
| `rosbagger-core` | workspace (`0.1.0`) | Every offline panel's API (inspect/query/tf/events/reader) | Already built; the thin-face target. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `textual-dev` | `>=1,<2` (latest 1.8.0) | `textual run --dev`, `textual console` live-debug, devtools | Dev dependency only — add to the root `[dependency-groups] dev`, NOT to `rosbagger-gui` runtime deps. `[VERIFIED: PyPI via slopcheck OK]` |
| `pytest-asyncio` | `>=0.23` | Run `async def` tests that use `App.run_test()` | Required for the SC3 headless tests (they must be async). See Validation Architecture — likely a Wave 0 gap. `[ASSUMED]` — verify it (or `anyio`) is the project's async-test plugin before pinning. |
| `rosbagger-record` | workspace | Live record panel API (lazy) | Reachable for the live panel; `rclpy` env-provided + lazy (D-04). NOT a hard runtime dep of the offline import graph. |
| `rosbagger-replay` | workspace | Live replay panel API (lazy) | Same as record. The `Replayer` + `replay_bag()` front door. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom scrubber `Widget` (D-09) | `textual-slider` (3rd-party, `github.com/TomJGooding/textual-slider`) | A third-party slider adds a dependency + supply-chain surface for a ~40-line custom widget. **Recommend custom widget** (a `Static`/`Widget` rendering a bar + a reactive `position`, click→`seek`); keeps the dependency graph to `textual` only and lets you overlay event markers. `[CITED: github.com/TomJGooding/textual-slider]` |
| `ContentSwitcher` for panel swapping | `TabbedContent` / `Tabs` | `TabbedContent` is tab-bar-on-top, not sidebar+content (D-01 is explicitly "not tabbed-only"). `ContentSwitcher` (driven by a sidebar `ListView`) matches the IDE-style layout. `[CITED: textual.textualize.io/widgets]` |
| `ListView` sidebar | `OptionList` | Both work. `ListView` holds arbitrary widgets per row (easier to grey a disabled live item + show a hint); `OptionList` is lighter for plain text. Planner's call. |

**Installation:**
```bash
# rosbagger-gui/pyproject.toml runtime deps (mirror rosbagger-replay):
#   dependencies = ["rosbagger-core", "textual>=8,<9"]
# root pyproject [dependency-groups] dev: add "textual-dev>=1,<2" (+ async test plugin)
uv sync
```

**Version verification (run 2026-05-23):**
- `pip index versions textual` → latest **8.2.7** (installed). `[VERIFIED: PyPI]`
- `pip index versions textual-dev` → latest **1.8.0**. `[VERIFIED: PyPI]`
- Note: Textual moved to a major-version cadence (8.x); the assistant's January-2026 training predates parts of the 8.x line, so the `>=8,<9` pin and any 8.x-specific API should be confirmed against the installed package, not from memory.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `textual` | PyPI | ~4 yrs | very high (millions/mo) | github.com/Textualize/textual | [OK] | Approved |
| `textual-dev` | PyPI | ~2 yrs | high | github.com/Textualize/textual-dev | [OK] | Approved (dev-group only) |

`slopcheck scan` on a `requirements.txt` containing `textual` + `textual-dev` returned **2 OK** (verified 2026-05-23, slopcheck 0.6.1). Both resolve on PyPI with established source repos.

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.
**Note on `pytest-asyncio` / `textual-slider`:** not yet slopcheck-verified in this session (tagged `[ASSUMED]` above). If the planner adopts `pytest-asyncio`, gate it behind a `slopcheck scan` of the updated dep file before install. The custom-scrubber recommendation avoids `textual-slider` entirely.

## Architecture Patterns

### System Architecture Diagram

```
            rosbagger-gui  <bag-path>?
                   │
                   ▼
            ┌──────────────────┐
            │  RosbaggerApp    │  (textual.App)  ── owns the shared OPEN reader
            │                  │     (with RosbagsReader(bag) as reader)
            │  cheap gate:     │
            │  try import rclpy│──► ros_available: bool (reactive)
            └───────┬──────────┘
                    │ compose()
       ┌────────────┴───────────────────────────────┐
       ▼                                             ▼
 ┌───────────────┐                       ┌──────────────────────────────┐
 │ Sidebar       │   on select →         │ ContentSwitcher (main pane)  │
 │ ListView:     │   switcher.current =  │  ┌────────────────────────┐  │
 │  • inspect    │      panel_id         │  │ InspectPanel           │──┼─► collect_bag_info(reader)
 │  • query      │ ───────────────────►  │  │ QueryPanel             │──┼─► query(sql, reader) + write_table
 │  • tf         │                       │  │ TfPanel                │──┼─► collect_tf_report(reader)
 │  • record ░░  │ (disabled if          │  │ RecordPanel  [live]    │──┼─► @work(thread) discover/record
 │  • replay ░░  │  not ros_available)   │  │ ReplayPanel  [live]    │──┼─► @work(thread) Replayer.run()
 └───────────────┘                       │  └────────────────────────┘  │
                                         └──────────────────────────────┘
   live panels lazy-import rosbagger_record / rosbagger_replay INSIDE
   method bodies (offline-import boundary) and run blocking ROS work in
   @work(thread=True) workers, posting results back via call_from_thread.
```

Data-flow trace (SC3 primary case): `rosbagger-gui ros2_sqlite/` → App opens `RosbagsReader(bag, default_typestore=get_typestore(Stores.ROS2_HUMBLE))` → user selects "query" in sidebar → `ContentSwitcher` shows `QueryPanel` → user types SQL in `Input`, presses Run → panel calls `query(sql, reader)` → result `pyarrow.Table` populates a `DataTable` → Export button calls `write_table(table, "out.csv")`.

### Recommended Project Structure
```
packages/rosbagger-gui/
├── pyproject.toml                 # workspace member; deps = rosbagger-core + textual
└── src/rosbagger_gui/
    ├── __init__.py                # ROS-free top level; lazy ros-detection helper
    ├── app.py                     # RosbaggerApp(App): shell, sidebar, ContentSwitcher, reader lifecycle
    ├── cli.py                     # console-script entry point (parse <bag-path> arg → app.run())
    ├── panels/
    │   ├── inspect.py             # InspectPanel(Widget) → collect_bag_info / collect_table_schemas
    │   ├── query.py               # QueryPanel(Widget) → query() + Tree schema browser + history + export
    │   ├── tf.py                  # TfPanel(Widget) → collect_tf_report
    │   ├── record.py              # RecordPanel(Widget) → lazy rosbagger_record (live)
    │   └── replay.py              # ReplayPanel(Widget) → lazy rosbagger_replay (live) + scrubber
    ├── widgets/
    │   └── scrubber.py            # custom timeline Widget (position reactive + event markers)
    └── app.tcss                   # Textual CSS (layout, disabled styling)
```

### Pattern 1: Sidebar + ContentSwitcher shell (D-01)
**What:** A `Horizontal` layout with a `ListView` sidebar and a `ContentSwitcher` content pane. Selecting a sidebar item sets `switcher.current = <panel_id>`.
**When to use:** The whole App shell.
**Example:**
```python
# Source: textual.textualize.io/widgets/content_switcher + /widgets/list_view (current docs)
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import ListView, ListItem, Label, ContentSwitcher

class RosbaggerApp(App):
    CSS_PATH = "app.tcss"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(
                ListItem(Label("inspect"), id="nav-inspect"),
                ListItem(Label("query"), id="nav-query"),
                ListItem(Label("tf"), id="nav-tf"),
                ListItem(Label("record"), id="nav-record"),   # disabled if no ROS
                ListItem(Label("replay"), id="nav-replay"),
                id="sidebar",
            )
            with ContentSwitcher(initial="inspect", id="content"):
                yield InspectPanel(id="inspect")
                yield QueryPanel(id="query")
                yield TfPanel(id="tf")
                yield RecordPanel(id="record")
                yield ReplayPanel(id="replay")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        panel_id = event.item.id.removeprefix("nav-")
        self.query_one("#content", ContentSwitcher).current = panel_id
```

### Pattern 2: Headless SC3 test with `App.run_test()` / `Pilot`
**What:** Drive the app in headless mode, interact via `Pilot`, assert real `rosbagger_core` output.
**When to use:** The SC3 proof. Offline, ROS-free, CI-safe.
**Example:** see Code Example 2 (full runnable shape).

### Pattern 3: Capability-gating via the `disabled` reactive (D-03)
**What:** Every Textual `Widget` has a `disabled` reactive bool ("Disabled widgets can not be interacted with, and are typically styled to look dimmer") and a `loading` reactive. Set the live sidebar items + panels `disabled = not ros_available`; show the teaching hint as a `Label`/`Static` inside the disabled panel.
**Example:**
```python
# Source: textual.textualize.io/api/widget (Widget.disabled, Widget.loading)
def _detect_ros() -> bool:
    """Cheap tier-1 gate (D-04): rclpy importable == ROS 2 sourced.
    Imported INSIDE a function so rosbagger_gui's module top stays ROS-free."""
    try:
        import rclpy  # noqa: F401
        return True
    except ImportError:
        return False

class RecordPanel(Widget):
    def on_mount(self) -> None:
        if not _detect_ros():
            self.disabled = True
            self.mount(Static("Source your ROS 2 environment to enable live recording."))
```
**Note:** `disabled` is the *enable* gate (tier 1). The tier-2 live discovery scan (`discover_topics`) runs only when the enabled record panel is opened, in a thread worker (Pattern 5), and a still-empty graph surfaces the panel-level live error.

### Pattern 4: Render `pyarrow.Table` into a `DataTable`
**What:** `query()` returns a `pyarrow.Table`; map it into Textual's `DataTable`.
**Example:**
```python
# Source: textual.textualize.io/widgets/data_table (add_columns / add_rows)
from textual.widgets import DataTable

def fill_table(dt: DataTable, table) -> None:  # table: pyarrow.Table
    dt.clear(columns=True)
    dt.add_columns(*table.column_names)
    # to_pylist() materializes rows; fine for query results (already bounded by SQL)
    for row in table.to_pylist():
        dt.add_row(*(row[c] for c in table.column_names))
```

### Pattern 5: Long-running ROS work in a thread worker (D-08/D-09)
**What:** `Replayer.run()`, `record()`, and `discover_topics()` all block. Run them in `@work(thread=True)` and update the UI via `call_from_thread`.
**Example:** see Code Example 3.

### Anti-Patterns to Avoid
- **Calling `Replayer.run()` / `record()` / `discover_topics()` directly in an event handler** — blocks the event loop; the whole TUI freezes (no repaint, no input). Always wrap in `@work(thread=True)`.
- **Importing `rclpy` / `rosbagger_record` / `rosbagger_replay` at module top in any `rosbagger_gui` module** — breaks the offline-import invariant. Import inside method bodies only (the Phase 12/13 `_require_ros` discipline). `test_offline_guard.py` will fail otherwise.
- **Putting any SQL/format/selection logic in a panel** — violates the thin-face rule. Panels collect a string/path/topic-set and call the module API verbatim.
- **Re-implementing pacing/seek in the replay panel** — the `Replayer` already owns play/pause/step/seek/rate/loop. The panel calls `replayer.seek(int(t_s*1e9))`, `replayer.set_rate(x)`, etc. Drive the production `replay_bag()` for the actual publish; use the `Replayer` directly only if the panel needs in-process transport state (see Open Q2).
- **Updating a widget from inside a thread worker without `call_from_thread`** — Textual is not thread-safe for direct widget mutation; use `call_from_thread(widget.update, ...)` or `post_message`.
- **`DataTable` materializing a multi-GB heavy-blob column** — `query()` already gates heavy blobs (QURY-07); don't `to_pylist()` an unbounded raw stream. Query results are bounded by the user's SQL; inspect/tf use O(1) metadata.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Headless TUI testing | A custom terminal-driver / pexpect harness | `App.run_test()` + `Pilot` | First-class, deterministic, async; the documented SC3 mechanism. |
| Background work without freezing UI | Manual `threading.Thread` + queue plumbing | `@work(thread=True)` + `call_from_thread` | Textual manages worker lifecycle, cancellation, and DOM-node binding. |
| Panel swapping | A manual mount/unmount of widgets on nav change | `ContentSwitcher` | Built-in, keeps all panels mounted and toggles visibility by `current`. |
| Disabled/greyed UI | Custom dim styling + input-swallowing | `Widget.disabled` reactive | Built-in: blocks interaction + applies the dim style; `loading` for the scan. |
| Replay transport (play/pause/step/seek/rate/loop + pacing) | Any timing/seek logic in the panel | `rosbagger_replay.scheduler.Replayer` | Already a pure, unit-tested state machine with injectable `sink`/`clock`/`sleep`. |
| Topic selection filter (record checklist) | A regex/include/exclude filter in the panel | `rosbagger_record.select_topics(...)` | Pure function; same filter the CLI uses (API-first parity). |
| CSV/Parquet export | A pyarrow/csv writer in the panel | `rosbagger_core.output.export.write_table(table, path)` | Format chosen by extension; LIST/STRUCT-safe DuckDB COPY; the one SQL-literal escape lives there. |
| Scrubber slider | (only if you must) | Small custom `Widget` (recommended) or `textual-slider` | No built-in slider; custom keeps deps to `textual` only and supports event-marker overlay. |

**Key insight:** Phase 14's correctness comes almost entirely from *not* writing logic. The only genuinely new code is Textual glue (layout, widget composition, worker wiring) + one small custom scrubber widget. If a panel needs a value the module API doesn't expose, that is a signal the logic belongs in the module, not the GUI.

## Runtime State Inventory

> Phase 14 is **greenfield** (a new package) plus a one-line extension to an existing test. It is not a rename/refactor/migration. The categories below are answered for completeness because the phase touches the workspace config.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys, collection names, or user_ids introduced. The GUI reads bags + the events sidecar; it writes nothing persistent of its own. | None |
| Live service config | None — no external service config embeds a `rosbagger-gui` string. (ROS discovery is transient; nothing registered.) | None |
| OS-registered state | One NEW console-script entry point `rosbagger-gui = rosbagger_gui.cli:app` (declared in the new pyproject; created by `uv sync`/install, not pre-existing). | Declare entry point; reinstall workspace. |
| Secrets/env vars | None. ROS availability is detected via `import rclpy`, not an env var the GUI defines. | None |
| Build artifacts | New package needs `uv sync` so its editable `.pth` lands in site-packages (so `import rosbagger_gui` resolves under `PYTHONPATH=""` in the offline-guard subprocess, mirroring the record/replay members). | Run `uv sync` after adding the member; add `packages/rosbagger-gui/src` to `[tool.ruff] src`. |

## Common Pitfalls

### Pitfall 1: Blocking the Textual event loop
**What goes wrong:** Calling `Replayer.run()`, `record()`, or `discover_topics()` (a 30-iteration `spin_once` loop, ~0.6 s) inside an event handler freezes the entire TUI until it returns.
**Why it happens:** Textual runs the UI on a single async event loop; synchronous blocking work starves it.
**How to avoid:** `@work(thread=True)` for all three. Use `worker.is_cancelled` checks for a stop button; update widgets via `call_from_thread`.
**Warning signs:** UI doesn't repaint, key presses queue up and fire late, `Pilot.pause()` hangs in tests.

### Pitfall 2: `rclpy` leaking into the offline import graph
**What goes wrong:** A top-level `import rclpy` (or `import rosbagger_record`) anywhere in `rosbagger_gui` makes `import rosbagger_gui` pull ROS, breaking the universal/no-ROS promise and failing `test_offline_guard.py`.
**Why it happens:** Convenience imports at module scope.
**How to avoid:** Every ROS-touching import lives inside a method body (the `_detect_ros()` / `_require_ros()` pattern). Re-exporting pure things at the package top is fine; importing the live packages is not. Note `rosbagger_record`/`rosbagger_replay` *themselves* are import-safe (their top levels are ROS-free), but to keep the guard's intent crisp, still import them lazily where you call them.
**Warning signs:** The new `test_import_gui_does_not_pull_ros` assertion fails; `rclpy` appears in a fresh-interpreter `sys.modules` scan.

### Pitfall 3: Async test wiring for `App.run_test()`
**What goes wrong:** SC3 tests silently don't run (or error "coroutine never awaited") because the async-test plugin isn't configured.
**Why it happens:** `run_test()` is an async context manager; tests must be `async def` and pytest needs `pytest-asyncio` (with `asyncio_mode = "auto"`) or `anyio`.
**How to avoid:** Add the async test plugin in Wave 0; set `asyncio_mode = auto` (or decorate). Always `await pilot.pause()` after an interaction before asserting, so messages flush.
**Warning signs:** Tests pass without executing; assertions never reached.

### Pitfall 4: Forgetting `pilot.pause()` before asserting
**What goes wrong:** A click/keypress posts a message that hasn't been processed when the assertion runs → flaky test.
**How to avoid:** `await pilot.pause()` (or `pilot.pause(delay=...)`) after each interaction. For thread workers, await until the worker completes (`await app.workers.wait_for_complete()` or poll a reactive the worker sets via `call_from_thread`).

### Pitfall 5: Reader lifecycle across panels (D-02 shared bag)
**What goes wrong:** Each panel opens its own reader, or the reader is closed while a panel still holds it; `query()`/`collect_*` all require an *already-open* reader (Phase 5 Open Q2 — the caller owns `with RosbagsReader(...)`).
**How to avoid:** The App opens one reader on bag-load and exposes it (a reactive or attribute); panels read from it. On bag-switch (the in-TUI picker), close the old reader and open the new one, then refresh the active panel. The ROS 2 sqlite3 fixture needs `default_typestore=get_typestore(Stores.ROS2_HUMBLE)` (MCAP/ROS 1 do not).
**Warning signs:** "reader is closed" / empty results after switching bags; double-open file handles.

### Pitfall 6: `Replayer` loop wraparound and seek-past-end in a live driver
**What goes wrong:** Driving the `Replayer` in-process for the scrubber, a seek past the last timestamp lands `cursor == len(items)` (clean DONE, no IndexError — already handled), but the scrubber must reflect DONE; a `loop=True` wrap rewinds to index 0, NOT the last seek target (documented WR-02 behavior).
**How to avoid:** Read `replayer.state` / `replayer.cursor` to drive the scrubber position; treat DONE as end-of-track. Don't assume seek persists across a loop wrap.

## Code Examples

### Code Example 1: `rosbagger-gui/pyproject.toml` (mirror `rosbagger-replay`)
```toml
# Source: packages/rosbagger-replay/pyproject.toml (read 2026-05-23) — same shape
[project]
name = "rosbagger-gui"
version = "0.1.0"
requires-python = ">=3.10"
# rosbagger-core (workspace) + textual ONLY. The live packages are reachable as
# workspace siblings and lazy-imported behind the gating; NOTHING ROS here (D-03).
dependencies = ["rosbagger-core", "textual>=8,<9"]

[project.scripts]
rosbagger-gui = "rosbagger_gui.cli:app"   # or a thin main() that parses <bag-path>

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
Also add to the **root** `pyproject.toml`: `packages/rosbagger-gui/src` under `[tool.ruff] src`, and `textual-dev` (+ the async test plugin) under `[dependency-groups] dev`. `rosbagger-core` is already a `[tool.uv.sources]` workspace source. The live packages are resolved as workspace members; if the GUI declares them as deps for the live panels, add `rosbagger-record`/`rosbagger-replay` to `[tool.uv.sources]` as `{ workspace = true }` too (or import them lazily as already-installed siblings — preferred, matching how nothing depends on them today).

### Code Example 2: SC3 headless proof — inspect + query against a fixture bag
```python
# Source: textual.textualize.io/guide/testing (App.run_test / Pilot), verified API shape
import pytest
from rosbags.typesys import Stores, get_typestore
from rosbagger_gui.app import RosbaggerApp

@pytest.mark.asyncio  # or asyncio_mode = "auto" in pyproject
async def test_query_panel_runs_real_core(tmp_path):
    from tools.make_fixtures import write_ros2_sqlite_bag
    bag = write_ros2_sqlite_bag(tmp_path)

    app = RosbaggerApp(bag_path=bag)  # launch-arg path (D-02); App opens the reader
    async with app.run_test() as pilot:
        await pilot.pause()                       # let on_mount open the reader
        await pilot.click("#nav-query")           # select the query panel (sidebar)
        await pilot.pause()
        sql = app.query_one("#sql-input")         # the Input widget
        sql.value = "SELECT topic, t_ns FROM imu LIMIT 1"
        await pilot.press("enter")                # Run
        await pilot.pause()
        table = app.query_one("#results", DataTable)
        # Real rosbagger_core.query() output reached the DataTable (SC3):
        assert table.row_count == 1
        assert "topic" in [c.label.plain for c in table.columns.values()]

@pytest.mark.asyncio
async def test_inspect_panel_shows_real_topics(tmp_path):
    from tools.make_fixtures import write_ros2_sqlite_bag
    bag = write_ros2_sqlite_bag(tmp_path)
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-inspect")
        await pilot.pause()
        # InspectPanel called collect_bag_info(reader) and rendered TopicInfo rows
        info_table = app.query_one("#bag-info", DataTable)
        assert info_table.row_count >= 1
```
Note: confirm the exact `DataTable` column-introspection accessor against the installed 8.2.7 API (`table.columns` shape changed across versions); the assertion above may need `table.ordered_columns` or similar — verify when writing the test, do not trust memory.

### Code Example 3: Replay panel driving the production front door in a thread worker
```python
# Source: textual.textualize.io/guide/workers + packages/rosbagger-replay (read 2026-05-23)
from textual import work
from textual.widgets import Widget
from textual.worker import get_current_worker

class ReplayPanel(Widget):
    @work(exclusive=True, thread=True)
    def start_replay(self, bag, topics, rate, loop) -> None:
        # Lazy import INSIDE the worker body (offline-import boundary, D-03).
        from rosbagger_replay import replay_bag, RosNotAvailableError, NoMessagesToReplayError
        worker = get_current_worker()
        try:
            # The single production publish front door (re-entrant-safe rclpy context,
            # so the GUI may own its own context — see Phase 13 WR-04). Pass the
            # ROS 2 sqlite3 fixture typestore when needed.
            n = replay_bag(bag, topics=topics, rate=rate, loop=loop)
            if not worker.is_cancelled:
                self.app.call_from_thread(self._on_done, n)
        except (RosNotAvailableError, NoMessagesToReplayError) as exc:
            self.app.call_from_thread(self._show_capability_error, str(exc))

    def _on_done(self, n: int) -> None:
        self.query_one("#status").update(f"published {n} messages")
```
**Transport-control note (D-09):** `replay_bag()` runs to completion (or to a bound) and is not pausable mid-flight from outside. To expose **live** play/pause/step/seek/rate/loop + a scrubber, the panel must drive the **pure `Replayer` directly** with its own rclpy publish sink (the same ~15-line sink `replay.py` builds), running `Replayer.run()` in the worker and calling `replayer.pause()`/`seek()`/`set_rate()` from UI handlers between `run()` segments. This is still "over the module API" (the `Replayer` is the API and is injectable by design), but it is more than a single `replay_bag()` call — see Open Q2 for the planner decision.

### Code Example 4: Event jump markers for the scrubber (D-09)
```python
# Source: packages/rosbagger-core/src/rosbagger_core/events.py (read 2026-05-23)
from rosbagger_core.events import list_events  # ROS-free, lazy pyarrow inside

def event_marks(bag, bag_start_ns: int, bag_end_ns: int) -> list[tuple[float, str]]:
    tbl = list_events(bag)  # columns: t_start_ns, t_end_ns, label, note
    rows = tbl.to_pylist()
    span = max(1, bag_end_ns - bag_start_ns)
    # fractional position 0..1 along the scrubber + the label for the marker
    return [((r["t_start_ns"] - bag_start_ns) / span, r["label"]) for r in rows]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Textual 0.x (training-era memory) | Textual 8.x (8.2.7 latest) | through 2025–2026 | Some widget APIs (e.g. `DataTable` column accessors) shifted; verify against installed package, not memory. |
| Manual threading for blocking work | `@work(thread=True)` worker API | stable since 0.18+ | Standard pattern; use it for all ROS work. |
| `App.process_messages` test hacks | `App.run_test()` + `Pilot` | stable | The supported headless test harness; the SC3 mechanism. |

**Deprecated/outdated:**
- Driving long work on the event loop directly — always use workers.
- Hiding/unmounting panels on nav-change — `ContentSwitcher` is the idiom.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pytest-asyncio` (with `asyncio_mode=auto`) is the right async-test plugin for `App.run_test()` | Standard Stack / Pitfall 3 | Low — `anyio` is the only alternative; SC3 tests just need *an* async runner. Verify the project's existing test config first; it currently uses plain pytest with no async tests. |
| A2 | A custom ~40-line scrubber `Widget` is preferable to `textual-slider` | Alternatives / Don't Hand-Roll | Low — both work; custom avoids a dependency and supports marker overlay. Planner may choose `textual-slider` (slopcheck-verify it first). |
| A3 | `DataTable.add_columns/add_rows` + `to_pylist()` mapping is the result-render path | Pattern 4 / Code Example 2 | Low — these are stable DataTable APIs; only the column-introspection accessor in assertions needs version-checking against 8.2.7. |
| A4 | Live transport controls (D-09) require driving the pure `Replayer` directly (not just `replay_bag()`) for mid-flight pause/seek | Code Example 3 / Open Q2 | Medium — affects how much the replay panel wires. The `Replayer` is purpose-built for this (injectable sink), so it stays within the thin-face rule, but the planner must decide the exact driver shape. |
| A5 | `textual>=8,<9` is the appropriate pin | Standard Stack | Low — 8.2.7 is installed and latest; major-cadence means `<9` guards against an 9.x break. |

## Open Questions

1. **Async test plugin choice (A1).**
   - What we know: `App.run_test()` is async; the project currently has no async tests.
   - What's unclear: `pytest-asyncio` vs `anyio` and the exact config key.
   - Recommendation: add `pytest-asyncio>=0.23` to the dev group with `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`; this is the most common choice. Slopcheck-verify before install.

2. **Replay panel driver shape (D-09 / A4).**
   - What we know: `replay_bag()` is the production front door but runs to completion; the pure `Replayer` exposes live play/pause/step/seek/set_rate/loop with an injectable sink and is re-entrant-context-safe (Phase 13 WR-04 was explicitly designed so "the Phase-14 GUI can own its own context").
   - What's unclear: whether v1 ships *full* live transport (drive `Replayer` + own rclpy sink in a worker) or a *simpler* "start/stop + rate/loop/seek-then-replay" over `replay_bag()`.
   - Recommendation: D-09 says **full transport controls** + scrubber + jump-to-event, so plan to drive the pure `Replayer` directly with the verified ~15-line rclpy sink (mirroring `replay.py`'s sink), run `Replayer.run()` in a thread worker, and call the transport methods from UI handlers. The publish *mechanics* (get_message/deserialize_message/create_publisher) are copied verbatim from the verified `replay.py` — no new publish logic. Confirm this reading with the user; it is the one place the panel is more than a one-liner.

3. **GUI coverage gate (Claude's discretion in CONTEXT).**
   - What we know: live packages are excluded from `--cov=rosbagger_core --cov=bagq` (Phase 13 D-12).
   - Recommendation: keep `rosbagger_gui` OUT of the coverage gate (it is near-zero pure logic by the thin-face rule, and its tests are async UI-integration tests). Mirror the live-package precedent.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `textual` | All panels (the framework) | ✓ | 8.2.7 | — (pinned dep) |
| `textual-dev` | Dev debugging (`textual console`) | ✓ | (latest 1.8.0) | optional; dev-only |
| `rosbagger-core` | Offline panels | ✓ | 0.1.0 (workspace) | — |
| `rclpy` (env-provided) | Live panels (record/replay) ONLY | ✓ on this box (ROS 2 Humble) | — | Live panels render disabled with teaching hint (D-03); offline panels unaffected |
| ROS 2 graph (running publishers) | Record panel discovery scan | conditional | — | `NoTopicsMatchedError` teaching error if empty (D-04) |
| MCAP storage plugin | (not used by GUI — replay reads via rosbags) | ✗ (known box gap) | — | N/A for GUI |

**Missing dependencies with no fallback:** none — the offline panels (inspect/query/tf) require only `textual` + `rosbagger-core`, both present.
**Missing dependencies with fallback:** live ROS graph — the disabled-panel teaching hint (D-03) IS the fallback; offline CI stays green.

## Validation Architecture

> nyquist_validation: config not inspected for an explicit `false`; treating as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=8,<10` (+ pytest-cov `>=6`); needs an async plugin for `run_test()` — see Wave 0 |
| Config file | root `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, coverage gate in `addopts`) |
| Quick run command | `PYTHONPATH="" uv run pytest tests/test_gui.py -x` (local box needs the `PYTHONPATH=""` prefix — MEMORY) |
| Full suite command | `PYTHONPATH="" uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GUI-01 (SC1) | App launches exposing 5 panels over module APIs | integration (headless) | `pytest tests/test_gui.py::test_app_has_five_panels -x` | ❌ Wave 0 |
| GUI-01 (SC2) | Live panels disabled without ROS; offline always work | integration (headless) | `pytest tests/test_gui.py::test_live_panels_disabled_without_ros -x` | ❌ Wave 0 |
| GUI-01 (SC3) | inspect+query drive real `rosbagger_core` against a fixture bag | integration (headless) | `pytest tests/test_gui.py::test_query_panel_runs_real_core -x` | ❌ Wave 0 (Code Example 2) |
| (invariant) | `import rosbagger_gui` pulls no `rclpy`/`rosbag2_py` | unit (subprocess) | `pytest tests/test_offline_guard.py::test_import_gui_does_not_pull_ros -x` | ❌ Wave 0 (extend existing file) |
| (live, gated) | record/replay panels drive the live API on a ROS-sourced lane | integration (live) | `pytest tests/test_gui_live.py -m live` | ❌ Wave 0; `@pytest.mark.importorskip("rclpy")` + `live` marker |

### Sampling Rate
- **Per task commit:** `PYTHONPATH="" uv run pytest tests/test_gui.py tests/test_offline_guard.py -x`
- **Per wave merge:** `PYTHONPATH="" uv run pytest`
- **Phase gate:** Full offline suite green before `/gsd:verify-work`; the `live`-marked GUI test runs on the ROS-sourced lane (mirrors Phase 12/13).

### Wave 0 Gaps
- [ ] `tests/test_gui.py` — SC1/SC2/SC3 headless `App.run_test()` tests
- [ ] `tests/test_gui_live.py` — `live`-marked record/replay integration (ROS-sourced lane), `importorskip("rclpy")`
- [ ] Extend `tests/test_offline_guard.py` — add `test_import_gui_does_not_pull_ros` (mirror `test_import_replay_does_not_pull_ros`, fresh interpreter + `PYTHONPATH=""`)
- [ ] Async test plugin: add `pytest-asyncio>=0.23` to `[dependency-groups] dev` + `asyncio_mode = "auto"` in `[tool.pytest.ini_options]` (Open Q1)
- [ ] Decide GUI coverage exclusion (keep `--cov=rosbagger_core --cov=bagq` only — Open Q3)

## Security Domain

> `security_enforcement` config not inspected for an explicit `false`; included for completeness. This is a **local single-user TUI** with the same trust model as the existing CLIs.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local TUI; no auth surface. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | User runs against their own bags. |
| V5 Input Validation | partial | The SQL box forwards the user's own SQL to `query()` — the existing trusted-SQL boundary (Phase 5 T-05-04); the user is the trusted local operator. Export paths go through `write_table`'s existing single-quote escape (T-06-01). The GUI introduces no new SQL interpolation. |
| V6 Cryptography | no | None. |

### Known Threat Patterns for {Textual TUI over local file/ROS APIs}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious bag triggers heavy-blob materialization | Denial of Service | `query()` already gates heavy blobs (QURY-07); inspect/tf use O(1) metadata. Don't `to_pylist()` an unbounded raw stream in a panel. |
| User SQL injection | (N/A — trusted local user) | The SQL *is* the intended interface (Phase 5 disposition: accept). No new surface. |
| Export path with quote/traversal | Tampering | Reuse `write_table` (T-06-01 escape); path is the local user's own input (accept, as in Phase 6). |
| ROS topic/regex strings in record panel | Injection | `select_topics` uses stdlib `re` only, never shell/eval (T-12-02). The GUI passes strings through verbatim. |

## Sources

### Primary (HIGH confidence)
- Project source (read 2026-05-23): `inspect.py`, `tf.py`, `events.py`, `backend/query.py`, `output/export.py`, `reader/base.py`, `reader/rosbags_reader.py`, `tests/test_offline_guard.py`, `tools/make_fixtures.py`; `rosbagger-replay`/`rosbagger-record` `pyproject.toml` + `__init__.py` + `scheduler.py`/`source.py`/`replay.py`/`record.py`/`discovery.py`; root + `bagq` `pyproject.toml`.
- Textual docs (current): testing (`textual.textualize.io/guide/testing`), workers (`/guide/workers`), reactivity (`/guide/reactivity`), widget reference (`/widgets`), Widget API (`/api/widget` — confirmed `disabled`/`loading` reactives).
- `pip index versions textual` → 8.2.7 latest (installed); `textual-dev` → 1.8.0. `slopcheck scan` → textual + textual-dev both `[OK]`.

### Secondary (MEDIUM confidence)
- WebSearch: Textual ProgressBar exists, no built-in slider; `textual-slider` is the 3rd-party option — `github.com/TomJGooding/textual-slider`.

### Tertiary (LOW confidence)
- Exact 8.2.7 `DataTable` column-introspection accessor in test assertions — verify against the installed package when writing tests (training memory is 0.x-era).

## Metadata

**Confidence breakdown:**
- Module APIs (inspect/query/tf/events/record/replay): HIGH — read from source, signatures confirmed.
- Textual core (App/ContentSwitcher/ListView/DataTable/Tree/Input/Button, workers, run_test/Pilot, disabled/loading): HIGH — current docs + installed 8.2.7.
- Offline-import + packaging discipline: HIGH — directly mirrors the verified Phase 12/13 pattern.
- Replay live-transport driver shape (D-09): MEDIUM — design is sound (pure `Replayer` is injectable), but the exact panel wiring is a planner decision (Open Q2).
- Async test plugin + DataTable assertion accessor: MEDIUM — verify at implementation time.

**Research date:** 2026-05-23
**Valid until:** ~2026-06-22 (30 days; Textual evolves on a major cadence — re-check the version pin and any 8.x-specific API if planning slips).

Sources:
- [Textual testing guide](https://textual.textualize.io/guide/testing/)
- [Textual workers guide](https://textual.textualize.io/guide/workers/)
- [Textual widget reference](https://textual.textualize.io/widgets/)
- [Textual Widget API (disabled/loading)](https://textual.textualize.io/api/widget/)
- [Textual ProgressBar](https://textual.textualize.io/widgets/progress_bar/)
- [textual-slider (3rd-party)](https://github.com/TomJGooding/textual-slider)
