# Phase 16: Native Desktop GUI (PySide6) - Research

**Researched:** 2026-05-25
**Domain:** Native desktop GUI (PySide6/Qt) as a thin frontend over existing Python module APIs; headless GUI testing; workspace dependency isolation
**Confidence:** HIGH

## Summary

Phase 16 adds `rosbagger-desktop`, a new isolated uv workspace package that spawns a
native Qt window (`QMainWindow` + left nav `QListWidget` + `QStackedWidget`) with full
parity to the existing Textual TUI's five panels (inspect/query/tf/record/replay). The
work is almost entirely a **mechanical port of the already-shipped TUI** (`rosbagger-gui`):
the panel→API map is identical and locked (D-10..D-14), the module APIs are unchanged and
verbatim-reused, and the hard architectural invariants (App-owned single reader, lazy ROS
imports, capability gate, single publish path) are all already proven in the TUI source.
The GUI contains zero analysis/bag/SQL/ROS logic — it is a pure presentation layer.

The two genuinely new technical concerns are (1) the **Qt concurrency model** — the
`QThread` + `QObject`-worker + signals/slots pattern that replaces the TUI's
`@work(thread=True)` workers for the three blocking calls (topic discovery, `record_topics`,
`Replayer.run()`), and (2) **headless testing** via pytest-qt with `QT_QPA_PLATFORM=offscreen`,
the desktop analog of the TUI's `App.run_test()`/`Pilot`. Both are well-trodden, current Qt
patterns. The isolation requirement (PySide6 confined to one package; offline import graph
stays Qt-free) maps exactly onto the repo's existing offline-guard discipline — the new
Qt-free assertion is a one-line extension of the established `_ros_modules_after_import` /
`_heavy_modules_after_import` subprocess technique in `tests/test_offline_guard.py`.

**Primary recommendation:** Pin `PySide6>=6.10,<6.12` and `pytest-qt>=4.5,<5` (dev group);
mirror `packages/rosbagger-gui`'s package shape exactly; port each panel one-to-one keeping
every `rosbagger_core`/`rosbagger_record`/`rosbagger_replay` import lazy inside method/worker
bodies; use the `QObject`-worker-moved-to-`QThread` pattern (NOT `QThread` subclassing) for
the three blocking calls; run GUI tests with `QT_QPA_PLATFORM=offscreen` set in pytest config;
extend the offline guard with a Qt-free subprocess assertion.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Window/shell, nav, panel switching | Desktop GUI (`rosbagger-desktop`) | — | Pure Qt presentation; the desktop analog of the TUI App shell |
| Bag reading / open | `rosbagger_core.reader` (via App-owned `RosbagsReader`) | Desktop GUI (owns the single instance) | Reader logic lives in core; the window only owns the one instance and hands it to panels (D-07) |
| Inspect / schema computation | `rosbagger_core.inspect` | Desktop GUI (renders) | `collect_bag_info`/`collect_table_schemas` own all analysis (D-10) |
| SQL query + export | `rosbagger_core.backend.query` / `rosbagger_core.output.export` | Desktop GUI (collects SQL string, renders rows) | `query()`/`write_table` own SQL/format; GUI builds neither (D-11) |
| TF report | `rosbagger_core.tf` | Desktop GUI (renders edges/gaps) | `collect_tf_report` owns all tf math (D-12) |
| Live topic discovery + record | `rosbagger_record` | Desktop GUI (QThread worker drives it) | `list_record_topics`/`record_topics` own the rclpy node + recorder (D-13) |
| Live replay transport + publish | `rosbagger_replay` (`Replayer`, `build_publish_sink`) | Desktop GUI (transport buttons + scrubber drive it) | Pure `Replayer` state machine + the single `build_publish_sink` own scheduling/publishing (D-14/D-05) |
| Capability gate (rclpy probe) | Desktop GUI (`capabilities.py`) | — | Cheap tier-1 `import rclpy` probe inside a function body, mirrors the TUI's `_detect_ros` |
| Concurrency (off-UI-thread blocking calls) | Desktop GUI (`workers.py` — QThread + QObject worker) | — | Qt event loop must never block; this is the desktop analog of the TUI's `@work(thread=True)` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PySide6 | `>=6.10,<6.12` | The Qt6 GUI toolkit (QMainWindow, widgets, QThread, signals/slots, QFileDialog) | The official Qt-for-Python binding (LGPL, maintained by the Qt Company); the locked toolkit (D-01). 6.10/6.11 are the current stable lines. `[CITED: pypi.org/project/PySide6]` |

### Supporting (dev group only)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-qt | `>=4.5,<5` | The `qtbot` fixture: instantiate widgets, send events/clicks, wait on signals — headless GUI tests | All GUI tests, exactly as the TUI uses pytest-asyncio + `App.run_test()`. `[CITED: pypi.org/project/pytest-qt]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PySide6 | PyQt6 | Decision is locked to PySide6 (D-01). PySide6 is LGPL (Qt-Company-maintained) vs PyQt6 (Riverbank, GPL/commercial); API near-identical. No reason to deviate. |
| QThread + QObject worker | Python `threading` + `QApplication.postEvent` / signals | `threading` works but you still need a Qt-safe way to marshal results back to the UI thread; the QThread+worker+signals pattern is Qt's blessed, documented form and is the cleanest analog of the TUI's worker model. Prefer it. |
| QThread + QObject worker | `concurrent.futures` + a `QTimer` poll | More moving parts, no signal-based teardown story. Avoid. |

**Installation:**
```bash
# In packages/rosbagger-desktop/pyproject.toml [project] dependencies: PySide6 ONLY here.
# In the ROOT [dependency-groups] dev list: add PySide6 + pytest-qt so CI exercises the GUI.
PYTHONPATH="" uv sync   # re-locks uv.lock; the members glob already discovers the new package
```

**Version verification (this session, against PyPI):**
- `PySide6` latest = **6.11.1** (released 2026-05-13); available lines include 6.11.x, 6.10.x, 6.9.x. Pin `>=6.10,<6.12` to track the two current stable minors while leaving a guard for an unvetted 6.12. `[VERIFIED: PyPI — pip index versions PySide6]`
- `pytest-qt` latest = **4.5.0**. Pin `>=4.5,<5`. `[VERIFIED: PyPI — pip index versions pytest-qt]`
- `PySide6` requires Python `>=3.9` for recent lines; the repo floor is 3.10 (`.python-version` = 3.10) — compatible. Confirm the chosen line still publishes a 3.10 wheel at plan time (6.10/6.11 do as of this research). `[ASSUMED]` (3.10-wheel availability per chosen line — verify at install)

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| PySide6 | PyPI | ~5 yrs (6.0 in 2020) | tens of millions/mo | code.qt.io / github mirror | not-runnable (network) | Approved — first-party Qt Company binding, verified on PyPI |
| pytest-qt | PyPI | ~10 yrs | millions/mo | github.com/pytest-dev/pytest-qt | not-runnable (network) | Approved — pytest-dev org, verified on PyPI |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> slopcheck 0.6.1 is installed but its `install` verdict requires network access that was
> unavailable in this session. Both packages are nonetheless high-confidence: PySide6 is the
> official Qt-for-Python binding (Qt Company) and pytest-qt is a pytest-dev project, both with
> a decade of history and very high download counts, and both **verified present on PyPI** via
> `pip index versions` (correct ecosystem). These are not hallucination-risk names. No
> `checkpoint:human-verify` gate is required beyond the normal `uv sync` review of the re-locked
> `uv.lock`. There are **no transitive ROS/network postinstall** concerns — Python wheels run no
> postinstall scripts.

## Architecture Patterns

### System Architecture Diagram

```
                         rosbagger-desktop  (the only new package; PySide6-only dep)
  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                    │
  │  cli.main(argv)  ──argparse──►  --help? ──► print + exit 0   (NO QApplication)     │
  │       │  (optional BAG arg)                                                        │
  │       ▼  import MainWindow INSIDE main()  (mirror TUI cli.py)                      │
  │  QApplication(sys.argv) ──► MainWindow(bag_path) ──► app.exec()                    │
  │       │                                                                            │
  │       │  owns ONE shared RosbagsReader (D-07)   capabilities.ros_available (D-09)  │
  │       ▼                                                                            │
  │  ┌─────────────┐   selection   ┌──────────────────────────────────────────────┐   │
  │  │ QListWidget │ ─────────────► │ QStackedWidget.setCurrentIndex(panel)        │   │
  │  │  (left nav) │                │  ┌────────┬───────┬────┬────────┬─────────┐  │   │
  │  └─────────────┘                │  │Inspect │ Query │ TF │ Record │ Replay  │  │   │
  │  record/replay nav items        │  └───┬────┴───┬───┴─┬──┴───┬────┴────┬────┘  │   │
  │  disabled when !ros_available   └──────┼────────┼─────┼──────┼─────────┼───────┘   │
  │                                        │ lazy import of module APIs (method bodies)│
  └────────────────────────────────────────┼────────┼─────┼──────┼─────────┼──────────┘
   (offline panels, UI thread)              │        │     │      │ QThread │ QThread
                                            ▼        ▼     ▼      ▼ worker  ▼ worker
                              rosbagger_core.inspect  .backend.query  rosbagger_record   rosbagger_replay
                              collect_bag_info        query(sql,rdr)  list_record_topics  Replayer / run()
                              collect_table_schemas   write_table     record_topics       build_publish_sink
                              rosbagger_core.tf        errors.*                            load_items / list_events
                              collect_tf_report
                                  │                                          │
                                  ▼                                          ▼
                          rosbags AnyReader (ROS-free)              rclpy / rosbag2_py (lazy, live only)
```

Data flow for the primary use case (`rosbagger-desktop /path/to/bag` → inspect): argparse
parses the bag arg → `main()` constructs `QApplication` then `MainWindow(bag_path)` → the
window opens ONE `RosbagsReader`, builds the nav + stack, applies the capability gate → the
Inspect panel (default) calls `collect_bag_info`/`collect_table_schemas` against the shared
reader and renders rows into a `QTableView`/`QTableWidget`.

### Recommended Project Structure

Mirror `packages/rosbagger-gui` exactly (swap textual→PySide6). This is the spec's layout
(design §Package Layout) and is the lowest-risk shape:

```
packages/rosbagger-desktop/
├── pyproject.toml                  # version 0.2.0; deps: PySide6 + sibling pins; console script
└── src/rosbagger_desktop/
    ├── __init__.py                 # __version__; Qt-free + ROS-free at top level
    ├── cli.py                      # argparse front door; --help exits 0 WITHOUT QApplication
    ├── capabilities.py             # rclpy probe inside a function body (mirror _detect_ros)
    ├── main_window.py              # QMainWindow: QListWidget nav + QStackedWidget; owns reader; gate
    ├── workers.py                  # QObject worker scaffolding (moveToThread); for live panels
    ├── panels/
    │   ├── __init__.py
    │   ├── inspect_panel.py        # QWidget: collect_bag_info + collect_table_schemas
    │   ├── query_panel.py          # QWidget: collect_table_schemas + query() + write_table + errors
    │   ├── tf_panel.py             # QWidget: collect_tf_report (+ NoTransformsError)
    │   ├── record_panel.py         # QWidget (live): list_record_topics + record_topics on a worker
    │   └── replay_panel.py         # QWidget (live): Replayer + build_publish_sink on a worker
    └── widgets/
        └── scrubber.py             # Qt QSlider + transport buttons (analog of TUI Scrubber)
```

> The desktop GUI tests should follow the **same convention the TUI tests use**: they live in
> the repo-root `tests/` directory (e.g. `tests/test_desktop.py`, `tests/test_desktop_live.py`),
> NOT inside the package. `[VERIFIED: codebase — tests/test_gui.py, tests/test_gui_live.py exist;
> packages/rosbagger-gui has no tests/ dir]`. The spec's "`tests/` under the package" line
> describes intent; match the repo's actual convention (root `tests/`) so the coverage config,
> `live` marker, and `no_ros` fixture in `tests/conftest.py` apply unchanged.

### Pattern 1: argparse front door — `--help` exits 0 without constructing Qt (D-16)
**What:** A thin stdlib-argparse `main()` that parses the optional BAG arg, then imports the
window and constructs `QApplication` ONLY after parsing. `--help` (and arg errors) exit via
argparse before any Qt object exists.
**When to use:** The package's only console entry point.
**Example (port of the verified TUI `cli.py`):**
```python
# Source: packages/rosbagger-gui/src/rosbagger_gui/cli.py (verified verbatim pattern)
from __future__ import annotations
import argparse, sys
from collections.abc import Sequence

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosbagger-desktop",
        description="Launch the rosbagger desktop GUI (inspect / query / tf / record / replay).",
    )
    parser.add_argument("bag_path", nargs="?", default=None, metavar="BAG",
                        help="optional ROS 1 / ROS 2 sqlite3 / MCAP bag to open on launch")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)   # --help / bad args exit here, no Qt built
    from PySide6.QtWidgets import QApplication      # imported INSIDE main (Qt-free top level)
    from .main_window import MainWindow
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    window = MainWindow(bag_path=args.bag_path)
    window.show()
    return app.exec()
```
> `--help` reaches `parse_args`, which calls `sys.exit(0)` after printing — `QApplication` is
> never imported on that path. This is exactly the TUI discipline (App imported inside `main`).

### Pattern 2: QMainWindow shell — nav + QStackedWidget + App-owned reader (D-06/D-07)
**What:** `QListWidget` (left) wired to `QStackedWidget.setCurrentIndex`; the window opens and
owns ONE `RosbagsReader`; each panel is a `QWidget` constructed once and added to the stack.
**Example:**
```python
# Source: port of packages/rosbagger-gui/src/rosbagger_gui/app.py (verified shell pattern)
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QListWidget,
                               QStackedWidget, QFileDialog)

class MainWindow(QMainWindow):
    def __init__(self, bag_path=None):
        super().__init__()
        from rosbagger_core.reader import RosbagsReader      # lazy: keep top level light
        from .capabilities import ros_available
        self.reader = None
        self._ros_available = ros_available()                 # computed ONCE (D-09)
        nav = QListWidget(); stack = QStackedWidget()
        self._panels = [InspectPanel(self), QueryPanel(self), TfPanel(self),
                        RecordPanel(self), ReplayPanel(self)]
        for i, (label, panel, is_live) in enumerate(self._registry()):
            nav.addItem(label); stack.addWidget(panel)
            if is_live and not self._ros_available:
                item = nav.item(i); item.setFlags(item.flags() & ~Qt.ItemIsEnabled)  # gate
                item.setToolTip("Source a ROS 2 environment to enable live record/replay.")
        nav.currentRowChanged.connect(stack.setCurrentIndex)
        central = QWidget(); lay = QHBoxLayout(central)
        lay.addWidget(nav); lay.addWidget(stack, 1); self.setCentralWidget(central)
        if bag_path is not None:
            self._open_reader(Path(bag_path))     # surface open errors as a QMessageBox, not a crash
```
> `_ros2_humble_typestore()` from the TUI (`rosbags.typesys.get_typestore(Stores.ROS2_HUMBLE)`,
> ROS-free) must be carried over so the legacy ROS 2 sqlite3 fixture opens — `RosbagsReader` is
> constructed with `default_typestore=...` exactly as in the TUI `_open_reader`.
> `[VERIFIED: codebase — app.py _open_reader / _ros2_humble_typestore]`

### Pattern 3: QThread + QObject worker + signals/slots for blocking calls (D-15)
**What:** The ONE correct Qt concurrency pattern: a plain `QObject` worker holding the blocking
call, `moveToThread`'d onto a `QThread`, started via a signal, emitting result/error/finished
signals back to the UI thread. **Do NOT subclass `QThread`** and put work in `run()` — the
worker-object pattern is the documented, leak-free form and the clean analog of the TUI's
`@work(thread=True)` + `call_from_thread`.
**When to use:** All three blocking calls — `list_record_topics()` (discovery),
`record_topics(...)` (bounded record), and `Replayer.run()` (the replay drive loop).
**Example:**
```python
# Source: Qt for Python threading docs pattern (QObject worker moved to QThread)
from PySide6.QtCore import QObject, QThread, Signal, Slot

class DiscoverWorker(QObject):
    discovered = Signal(dict)        # {topic: type}
    failed = Signal(str)             # teaching message (str(exc))
    finished = Signal()
    @Slot()
    def run(self) -> None:
        try:
            from rosbagger_record import (list_record_topics, RosNotAvailableError,
                                          NoTopicsMatchedError, McapStorageUnavailableError)
            self.discovered.emit(dict(list_record_topics()))   # blocking rclpy scan, off UI thread
        except (RosNotAvailableError, NoTopicsMatchedError, McapStorageUnavailableError) as e:
            self.failed.emit(str(e))           # present the core teaching message, never a traceback
        except Exception as e:                 # noqa: BLE001 - surface as teaching text, not a crash
            self.failed.emit(f"Topic discovery failed: {e}")
        finally:
            self.finished.emit()

# In the panel:
def _scan(self):
    if not self.window().ros_available: return
    self._thread = QThread(self)
    self._worker = DiscoverWorker()
    self._worker.moveToThread(self._thread)
    self._thread.started.connect(self._worker.run)
    self._worker.discovered.connect(self._populate)       # slot runs on the UI thread
    self._worker.failed.connect(self._show_status)
    self._worker.finished.connect(self._thread.quit)      # clean teardown
    self._worker.finished.connect(self._worker.deleteLater)
    self._thread.finished.connect(self._thread.deleteLater)
    self._thread.start()
```
> **Teardown discipline (Pitfall 2):** always connect `finished → thread.quit`,
> `finished → worker.deleteLater`, `thread.finished → thread.deleteLater`, and keep references
> (`self._thread`, `self._worker`) so the GC doesn't collect a live thread. On window close,
> `quit()` + `wait()` any running thread before the worker is destroyed.

### Pattern 4: rendering a `pyarrow.Table` into a Qt table (Query/Inspect/TF panels)
**What:** Map `result.column_names` to columns and `result.to_pylist()` rows to cells. For the
v1 thin face, `QTableWidget` (simple, sufficient for bounded query results) is fine; the TUI
proved `to_pylist()` is safe here because `query()` already bounds the result and gates heavy
blobs. Cells are rendered with `str(value)` to sidestep the ns-timestamp→datetime crash class.
**Example:**
```python
# Source: port of packages/rosbagger-gui/.../panels/query.py _fill_results (verified)
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
def _fill_results(self, table):                  # table: pyarrow.Table
    cols = table.column_names
    self.results.clear(); self.results.setColumnCount(len(cols))
    self.results.setHorizontalHeaderLabels(cols)
    rows = table.to_pylist()
    self.results.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, name in enumerate(cols):
            self.results.setItem(r, c, QTableWidgetItem(str(row[name])))  # str() — temporal-safe
```
> For larger result sets a `QTableView` + a `QAbstractTableModel` is the scalable upgrade, but
> it is NOT required for parity — the TUI uses the eager `to_pylist()` form and `query()` bounds
> the result. Keep v1 simple (`QTableWidget`); note the model/view path as a future option only.

### Pattern 5: QFileDialog — ROS 2 dir vs ROS 1/MCAP file (D-16)
**What:** File ▸ Open offers BOTH a directory picker (ROS 2 bags are directories containing
`metadata.yaml` + a storage file) and a file picker (ROS 1 `.bag` / standalone `.mcap`).
**Example:**
```python
# Source: PySide6 QFileDialog docs
from PySide6.QtWidgets import QFileDialog
# Directory (ROS 2 bag dir):
path = QFileDialog.getExistingDirectory(self, "Open ROS 2 bag directory")
# File (ROS 1 .bag / .mcap):
path, _ = QFileDialog.getOpenFileName(self, "Open bag file", "",
                                      "Bags (*.bag *.mcap);;All files (*)")
```
> Offer two menu entries ("Open Bag File…" / "Open Bag Directory…") rather than guessing —
> `RosbagsReader`/`AnyReader` accepts both a dir and a file path, so the only job is picking the
> right dialog. An empty return (user cancelled) is a no-op.

### Anti-Patterns to Avoid
- **Subclassing `QThread` and overriding `run()` with the work.** Use the QObject-worker +
  `moveToThread` pattern instead — it has a clean signal-based teardown and matches the TUI model.
- **Touching widgets from the worker thread.** All widget mutation must happen on the UI thread
  — emit a signal and let a slot (auto-queued connection) do the update. This is the Qt analog of
  the TUI's `call_from_thread`.
- **Top-level `from PySide6...` import in `__init__.py` or any module the offline graph could
  reach.** PySide6 lives only inside `rosbagger_desktop`, and even there the cli keeps the
  `QApplication` import inside `main()` so `--help` is Qt-free. It must NEVER be importable from
  `rosbagger_core`/`bagq`.
- **Eager `import rclpy` / `import rosbagger_record` / `import rosbagger_replay` at module top.**
  Every ROS-bound import stays inside a worker/method body (D-08), exactly as the TUI panels do.
- **A second publish path in replay.** Reuse `build_publish_sink` verbatim (D-05) — do not inline
  publisher-build / message-deserialize mechanics.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bag reading / format detection / merge | Any IO in the GUI | App-owned `RosbagsReader` (core) | All reading is core's; GUI owns one instance only (D-07) |
| SQL parsing / table resolution / blob gating | Query building in the panel | `rosbagger_core.backend.query.query(sql, reader)` | The panel forwards the user's SQL string verbatim (D-11) |
| Export serialization (CSV/Parquet, LIST-safe) | Format picking / writers | `rosbagger_core.output.export.write_table(table, path)` | Format chosen by extension; the one LIST/STRUCT-safe writer (D-11) |
| TF math (edges/rates/gaps) | Any tf computation | `rosbagger_core.tf.collect_tf_report` | All tf analysis is core's (D-12) |
| Live topic discovery + rclpy node mechanics | A second rclpy node/spin loop | `rosbagger_record.list_record_topics()` | It owns its own short-lived node + spin-to-settle (D-13) |
| Recording loop / writer / bounded stop | Subscriber/writer plumbing | `rosbagger_record.record_topics(topics, out, storage=..., duration=...)` | The single discover→select→record orchestrator (D-13) |
| Replay scheduling / pacing / loop/seek state | A timer-based publish loop | `rosbagger_replay.Replayer` (pure state machine) | The verified transport scheduler; six controls already implemented (D-14) |
| ROS publisher build + msg deserialize | Inlined publish mechanics | `rosbagger_replay.build_publish_sink(node)` | The SINGLE production publish path (D-05) |
| Thread-result marshalling | Manual `QMetaObject.invokeMethod` plumbing | Qt signals/slots (auto-queued cross-thread) | Built-in, type-safe, the documented pattern |
| Headless GUI driving | Hand-rolled event injection | pytest-qt `qtbot` (`addWidget`, `mouseClick`, `keyClicks`, `waitSignal`) | The standard GUI test harness; analog of `Pilot` |

**Key insight:** Phase 16 is a **presentation port**, not a feature build. Every panel maps to
named, already-shipped, already-tested module APIs (the panel→API map is locked D-10..D-14 and
verified against the live TUI source). The only net-new code is Qt widget composition, the
QThread worker scaffolding, and the headless tests. Re-deriving any analysis/IO/ROS logic in the
GUI violates the thin-frontend rule and the isolation constraint.

## Runtime State Inventory

> This is a greenfield additive package (no rename/refactor/migration), so most categories are
> empty. The one item worth calling out is the shared-file boundary the spec flags for review.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys/collections/IDs are renamed. | none |
| Live service config | None — no external service config embeds a renamed string. | none |
| OS-registered state | None — no OS-level registrations. | none |
| Secrets/env vars | None. The new package introduces no secrets. `QT_QPA_PLATFORM=offscreen` is a test-time env var set in pytest config, not a secret. | none |
| Build artifacts | **`uv.lock` must be re-locked** when the new member + PySide6/pytest-qt dev deps are added. The members glob (`packages/*`) auto-discovers the package — no `[tool.uv.sources]` entry is expected (the new package depends only on already-sourced siblings). | `PYTHONPATH="" uv sync` to re-lock; review the `uv.lock` diff |

**Nothing found in the first four categories** — verified by inspecting the spec's isolation
rules and the locked decisions; the only intended shared-file change is the re-locked `uv.lock`.

## Common Pitfalls

### Pitfall 1: Blocking the Qt event loop with a long-running call
**What goes wrong:** Calling `list_record_topics()`, `record_topics(...)`, or `Replayer.run()`
directly from a button handler freezes the window (no repaints, "not responding").
**Why it happens:** Qt's UI runs on a single event-loop thread; a blocking call starves it.
**How to avoid:** Run every blocking call on a `QThread` via a `QObject` worker (Pattern 3);
marshal results back with signals. This is the explicit intent of D-15 and the desktop analog
of the TUI's `@work(thread=True)`.
**Warning signs:** UI unresponsive during discovery/record/replay; spinner never animates.

### Pitfall 2: QThread lifetime / "QThread: Destroyed while thread is still running"
**What goes wrong:** A worker thread is garbage-collected or the window closes while a thread is
running, crashing with `QThread: Destroyed while thread is still running` or a segfault.
**Why it happens:** No persistent reference to the `QThread`/worker, or no `quit()`+`wait()` on
close.
**How to avoid:** Keep `self._thread`/`self._worker` references; wire `finished→quit`,
`finished→worker.deleteLater`, `thread.finished→thread.deleteLater`; on window/panel close call
`thread.quit(); thread.wait()` for any running thread. For record, the bounded `duration` makes
the worker self-terminate (mirror the TUI's bounded-record discipline); a Stop/Dismiss cancels
the result handling but the bounded window finalizes on its own — `record_topics` exposes no
in-process early-stop hook (verified in the TUI `record.py` `_stop_record` comment).

### Pitfall 3: pytest-qt offscreen platform not actually applied
**What goes wrong:** GUI tests pop real windows in local dev, or fail/hang in CI with no display
("could not connect to display").
**Why it happens:** `QT_QPA_PLATFORM=offscreen` not set before `QApplication` is created, or set
only in some run paths.
**How to avoid:** Set it in pytest config so every run is identical (mirrors how the coverage
gate lives in `addopts`). In root `pyproject.toml`:
```toml
[tool.pytest.ini_options]
# (existing addopts / asyncio_mode unchanged)
qt_api = "pyside6"
env = []   # if using pytest-env; otherwise set QT_QPA_PLATFORM in a conftest before QApplication
```
pytest-qt reads `qt_api`; the offscreen platform is set via the `QT_QPA_PLATFORM` env var. The
simplest robust approach: set `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at the top
of the desktop test module (or a desktop-scoped conftest) BEFORE any PySide6 import.
**Warning signs:** A window flashes on screen during `pytest`; CI fails with xcb/display errors.
**Note (offscreen limitation):** some event categories (e.g. tooltips, certain mouse-tracking
events) behave differently or not at all under `offscreen` `[CITED: pytest-qt docs / Qt forum]`.
Test observable behavior (signal emitted, model/table populated, widget enabled/disabled) rather
than pixel-level rendering or hover tooltips.

### Pitfall 4: PySide6 leaking into the offline import graph (the load-bearing invariant)
**What goes wrong:** A stray top-level `from PySide6...` somewhere reachable from `rosbagger_core`
/ `bagq` breaks the Qt-free invariant the phase is built to guarantee (D-04).
**Why it happens:** Convenience top-level imports; or importing a desktop module from a core test.
**How to avoid:** PySide6 imported only inside `rosbagger_desktop`, and the cli keeps even the
`QApplication` import inside `main()`. Extend `tests/test_offline_guard.py` with a Qt-free
subprocess assertion (see Code Example 2). The new package is NOT in the coverage `--cov` set (the
GUI is a thin face — mirror the TUI's exemption: the root `addopts` covers only
`rosbagger_core`+`bagq`). `[VERIFIED: codebase — pyproject [tool.pytest.ini_options] addopts]`
**Warning signs:** `import rosbagger_core` pulls `PySide6` into `sys.modules`.

### Pitfall 5: Forgetting the ROS-2-Humble typestore for the legacy sqlite3 fixture
**What goes wrong:** Opening the ROS 2 sqlite3 fixture bag fails because it lacks embedded type
definitions.
**Why it happens:** `RosbagsReader` is constructed without `default_typestore`.
**How to avoid:** Carry over the TUI's `_ros2_humble_typestore()` helper
(`rosbags.typesys.get_typestore(Stores.ROS2_HUMBLE)`, ROS-free) and pass it to `RosbagsReader`
exactly as `app.py`'s `_open_reader` does. `[VERIFIED: codebase — app.py]`

### Pitfall 6: Constructing QApplication on `--help` / breaking the clean exit
**What goes wrong:** `rosbagger-desktop --help` spins up Qt (or fails on a headless box) instead
of printing help and exiting 0.
**Why it happens:** Importing `QApplication`/the window at module top, or before `parse_args`.
**How to avoid:** argparse front door (Pattern 1); import the window + `QApplication` inside
`main()` AFTER `parse_args`. Add a test that `main(["--help"])` raises `SystemExit(0)` and that
`sys.modules` has no `PySide6` after a fresh-subprocess `import rosbagger_desktop.cli`.

### Pitfall 7: Replay state machine driven from two threads at once
**What goes wrong:** Issuing Play/Step while the drive worker runs mutates `Replayer` state from
the UI thread while `run()` reads it on the worker thread — undefined interleaving.
**Why it happens:** `Replayer` is a pure, non-thread-safe state machine.
**How to avoid:** Mirror the TUI's WR-06 guard — only issue Play/Step BETWEEN run segments; if a
drive worker is running, ignore the control with a teaching status (Pause is allowed: it asks the
loop to stop at the next boundary). Use one `exclusive` drive thread at a time.
`[VERIFIED: codebase — replay.py _drive_running / _play / _step]`

## Code Examples

### Example 1: capabilities.py — the rclpy probe (port of `_detect_ros`)
```python
# Source: port of packages/rosbagger-gui/src/rosbagger_gui/__init__.py _detect_ros (verified)
from __future__ import annotations

def ros_available() -> bool:
    """Cheap tier-1 ROS probe (D-09): is rclpy importable? Import lives INSIDE the body."""
    try:
        import rclpy  # noqa: F401
    except ImportError:
        return False
    return True
```

### Example 2: the Qt-free offline guard (extend `tests/test_offline_guard.py`)
```python
# Source: extends the verified _ros_modules_after_import / fresh-subprocess pattern in
# tests/test_offline_guard.py (PYTHONPATH="" neutralizes the host ROS-on-PYTHONPATH leak;
# the editable workspace member still resolves via its site-packages .pth)
def test_import_core_does_not_pull_pyside6():
    """`import rosbagger_core` / `import bagq` must NOT pull PySide6 (the Qt-free invariant, D-04)."""
    code = (
        "import sys; import rosbagger_core; import bagq; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'PySide6','shiboken6'}]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            check=True, env={"PYTHONPATH": ""})
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"offline import pulled in Qt: {leaked}"

def test_import_desktop_cli_does_not_pull_pyside6_or_ros():
    """`import rosbagger_desktop.cli` stays Qt-free AND ROS-free (QApplication is inside main())."""
    code = (
        "import sys; import rosbagger_desktop.cli; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in "
        "{'PySide6','shiboken6','rclpy','rosbag2_py'}]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            check=True, env={"PYTHONPATH": ""})
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"import rosbagger_desktop.cli pulled Qt/ROS: {leaked}"
```
> Note: `shiboken6` is PySide6's binding runtime; including it in the blocklist catches an indirect
> leak. `[ASSUMED]` (shiboken6 is the PySide6 binding module name — verify after first install).

### Example 3: a headless pytest-qt offline-panel test (analog of `test_gui.py`)
```python
# Source: pytest-qt qtbot pattern + port of the verified tests/test_gui.py harness
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE any PySide6 import
import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "packages" / "rosbagger-desktop" / "src",
           _REPO_ROOT / "packages" / "rosbagger-core" / "src"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from tools.make_fixtures import write_ros2_sqlite_bag

def test_inspect_panel_shows_real_topics(qtbot, tmp_path):
    from rosbagger_desktop.main_window import MainWindow
    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)                 # qtbot owns teardown
    window.show()
    table = window.findChild(type(window).bag_info_table_type, "bag-info")  # or panel accessor
    assert table.rowCount() > 0             # real collect_bag_info rows landed in the widget
```
> Drive widgets with `qtbot.mouseClick(button, Qt.LeftButton)` / `qtbot.keyClicks(line_edit, sql)`;
> wait on worker results with `with qtbot.waitSignal(worker.discovered, timeout=...):`. For
> capability-gating tests, monkeypatch `rosbagger_desktop.capabilities.ros_available` → `False`
> (the analog of the TUI's `_detect_ros` monkeypatch) so the assertion is meaningful on this
> ROS-equipped dev box.

### Example 4: live record/replay tests on the `@pytest.mark.live` lane
```python
# Source: port of tests/test_gui_live.py convention; the live marker is registered in pyproject
import pytest
pytest.importorskip("rclpy")     # skip on offline CI (mirrors test_record_live.py / test_gui_live.py)

@pytest.mark.live
def test_record_panel_records(qtbot):
    ...   # drive the QThread worker; assert on the captured-count signal/status
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `QThread` subclass with work in `run()` | `QObject` worker + `moveToThread` + signals | Qt 4.6+ guidance (long-standing) | Cleaner teardown; the documented pattern; matches the TUI worker model |
| PyQt5 / Qt5 | PySide6 / Qt6 (6.10/6.11 current) | Qt6 GA 2020; 6.11.1 = 2026-05-13 | Use PySide6 6.10/6.11; Python 3.10 wheels available |
| Real X display for GUI CI | `QT_QPA_PLATFORM=offscreen` | Qt 5.x+ offscreen plugin | Headless, display-free GUI tests in CI (the no-display promise holds) |

**Deprecated/outdated:**
- Subclassing `QThread` for worker logic — superseded by the worker-object pattern.
- Qt5/PyQt5 — not the locked toolkit; PySide6 (Qt6) is the decision (D-01).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The chosen PySide6 line (6.10/6.11) publishes a Python 3.10 wheel | Standard Stack | LOW — verify at `uv sync`; if a line drops 3.10 wheels, pick the latest line that keeps it (6.10/6.11 do today) |
| A2 | `shiboken6` is the correct PySide6 binding-runtime module name to add to the Qt-free guard blocklist | Code Examples (Ex 2) | LOW — confirm after first install via `python -c "import PySide6; import sys; print([m for m in sys.modules if 'shibok' in m])"`; the `PySide6` entry alone already catches a leak |
| A3 | No `[tool.uv.sources]` entry is needed for `rosbagger-desktop` (it depends only on already-sourced siblings + a PyPI dep) | Runtime State Inventory | LOW — spec's expectation; if uv resolution complains, add the workspace source (this is explicitly D-discretion) |
| A4 | `QTableWidget` + eager `to_pylist()` is sufficient for v1 result rendering (no model/view needed for parity) | Pattern 4 | LOW — the TUI uses the same eager form and `query()` bounds results; model/view is a noted future upgrade |

## Open Questions

1. **Increment granularity (A vs B as plans/waves).**
   - What we know: D-18/D-19 define Increment A (offline parity + skeleton + guard + tests +
     re-lock) and Increment B (live parity). Planner has discretion on plan/wave split (D-19).
   - What's unclear: whether to make A and B separate plans or finer-grained waves.
   - Recommendation: at least one plan boundary at the A→B seam (offline parity is a shippable,
     test-green milestone before the higher-effort live work begins).

2. **Where desktop tests live.**
   - What we know: the TUI tests live in repo-root `tests/` and the GUI is excluded from the
     `--cov` set; the spec text says "`tests/` under the package."
   - What's unclear: strictly which directory.
   - Recommendation: put them in repo-root `tests/` (e.g. `test_desktop.py`,
     `test_desktop_live.py`) to inherit the existing `conftest.py` `no_ros` fixture, the `live`
     marker, and the coverage exemption — matching the established TUI convention.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.10 (`.python-version`) | — |
| uv | workspace install / re-lock | ✓ (project uses it) | — | — |
| PySide6 | the desktop GUI runtime | ✗ (not yet a dep) | 6.11.1 on PyPI | add to package deps + dev group; `uv sync` installs |
| pytest-qt | headless GUI tests | ✗ (not yet a dep) | 4.5.0 on PyPI | add to dev group; `uv sync` installs |
| A display server (X/Wayland) | NOT required | n/a | — | `QT_QPA_PLATFORM=offscreen` removes the need (headless CI) |
| rclpy / rosbag2_py | live record/replay panels ONLY (and live tests) | host-dependent (sourced ROS on this dev box) | — | live tests gated by `pytest.importorskip("rclpy")` + `@pytest.mark.live`; offline panels need none |

**Missing dependencies with no fallback:** none (PySide6/pytest-qt install from PyPI via `uv sync`).
**Missing dependencies with fallback:** live ROS (rclpy/rosbag2_py) — live panels are
capability-gated and live tests are skipped on offline CI, exactly as the existing record/replay
and TUI-live suites already are.

> **Host constraint (load-bearing):** every `uv` / test / lint command MUST be prefixed
> `PYTHONPATH=""` on this dev box (ROS is sourced onto `PYTHONPATH` globally, which would
> otherwise leak rclpy into the offline guard and make it meaningless). Invoke the linter as
> `uv run ruff`. The Qt-free / ROS-free offline-guard subprocesses already pass `env={"PYTHONPATH":""}`.

## Security Domain

> `security_enforcement` is not set in `.planning/config.json`. This phase is a local desktop GUI
> with no authentication, no network surface, no session/cookie/crypto handling, and no
> user-supplied data beyond local file paths and SQL the user types against their own bag. The
> standard ASVS web categories largely do not apply.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth in a local GUI) |
| V3 Session Management | no | — |
| V4 Access Control | no | — (OS file permissions govern bag access) |
| V5 Input Validation | partial | SQL strings are forwarded verbatim to `query()`, which already uses sqlglot-resolved, quoted identifiers (the established injection boundary, Phase 3/5). File paths come from `QFileDialog` and `RosbagsReader` opens them; the GUI adds no new parsing. |
| V6 Cryptography | no | — (never hand-rolled; none used) |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious / huge / corrupt bag fed to a panel | Denial of Service | Core APIs already bound work (O(1) metadata reads in inspect; bounded query results + heavy-blob gating). GUI must not re-derive — it inherits the bounds. Open errors surface as a `QMessageBox`, never a crash. |
| SQL injection via the query box | Tampering | `query()` quotes identifiers via sqlglot (the single established boundary); the GUI builds no SQL itself. |
| Unbounded record / replay blocking the UI | Denial of Service (local) | Bounded `duration` on record; the drive loop and discovery run on QThread workers; the UI thread never blocks. |

## Sources

### Primary (HIGH confidence)
- Codebase: `packages/rosbagger-gui/src/rosbagger_gui/{app.py,cli.py,__init__.py,panels/*.py,widgets/scrubber.py}` — the verified thin-frontend precedent ported one-to-one.
- Codebase: `tests/test_offline_guard.py`, `tests/conftest.py`, `tests/test_gui.py` — the offline-guard subprocess technique, the `no_ros` blocker, and the headless GUI test harness to mirror.
- Codebase: `packages/rosbagger-{record,replay}/src/.../__init__.py`, `scheduler.py`, `record.py`, `source.py`, `rosbagger_core/events.py` — verified module-API signatures (`record_topics`, `list_record_topics`, `Replayer`, `build_publish_sink`, `load_items`, `list_events`).
- Codebase: root `pyproject.toml` — workspace members glob, `[tool.uv.sources]`, dev group, pytest coverage/`live`-marker config.
- PyPI (`pip index versions`): PySide6 6.11.1, pytest-qt 4.5.0 — verified current versions on the correct ecosystem.
- `docs/superpowers/specs/2026-05-25-rosbagger-desktop-gui-design.md` + `16-CONTEXT.md` — the authoritative design contract and locked decisions D-01..D-19.

### Secondary (MEDIUM confidence)
- pytest-qt docs / Qt forum (offscreen platform, qtbot, headless CI) — `QT_QPA_PLATFORM=offscreen`, `qtbot` usage, offscreen event limitations.
- Qt for Python threading guidance — the QObject-worker + `moveToThread` + signals pattern (vs subclassing QThread).

### Tertiary (LOW confidence)
- `shiboken6` as the exact PySide6 binding-runtime module name for the guard blocklist (A2) — confirm after first install.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — both packages verified on PyPI with current versions; toolkit locked (D-01).
- Architecture: HIGH — a one-to-one port of the verified, shipped TUI; panel→API map locked and cross-checked against live source.
- Threading: HIGH — the QObject-worker pattern is the documented Qt standard; maps cleanly onto the TUI's `@work(thread=True)` model and the re-entrant-safe record/replay APIs.
- Testing/isolation: HIGH — offscreen + pytest-qt is the established headless approach; the Qt-free guard is a one-line extension of the repo's proven subprocess technique.
- Pitfalls: HIGH — drawn from verified TUI source (WR-06 replay guard, bounded record, typestore) + standard Qt concurrency/teardown gotchas.

**Research date:** 2026-05-25
**Valid until:** 2026-06-24 (stable stack; re-confirm the PySide6 line if a 6.12 GA appears)
