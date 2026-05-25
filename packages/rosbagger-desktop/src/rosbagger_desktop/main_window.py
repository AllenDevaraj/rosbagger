"""``MainWindow`` — the native Qt shell: left ``QListWidget`` nav + ``QStackedWidget``.

The desktop analog of the TUI ``RosbaggerApp`` (D-06/D-07/D-08/D-09):

* **Shell (D-06):** a ``QHBoxLayout`` central widget holding a left ``QListWidget``
  nav (one row per panel) and a ``QStackedWidget`` (the panel widgets). Selecting a
  nav row drives ``stack.setCurrentIndex`` via ``currentRowChanged``.
* **Shared reader (D-07):** the window owns exactly ONE open ``RosbagsReader``. It is
  opened from the launch ``bag_path`` (or a ``QFileDialog`` via the File menu) and
  handed to each panel — there is never a second open reader.
* **Capability gate (D-09):** a cheap tier-1 :func:`~rosbagger_desktop.capabilities.ros_available`
  probe runs ONCE in ``__init__``; the live panel nav items are disabled with a
  teaching tooltip when ROS is absent. (No live rows exist yet this plan — Plan 03
  populates record/replay — but the gate logic is in place for them to use.)

OFFLINE-IMPORT INVARIANT (D-08): this module imports NO ``rosbagger_core`` / ``rosbags``
/ ``rclpy`` at top level. ``RosbagsReader`` and the ROS-2-Humble typestore are imported
INSIDE method bodies; only PySide6 + stdlib live at module top.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from . import capabilities
from .panels.inspect_panel import InspectPanel
from .panels.query_panel import QueryPanel
from .panels.record_panel import RecordPanel
from .panels.replay_panel import ReplayPanel
from .panels.tf_panel import TfPanel

# The default panel shown on launch (the first nav row).
_INITIAL_PANEL = "inspect"

# Teaching tooltip shown on a gated (live) nav row when ROS is absent (D-09).
_GATE_TOOLTIP = "Source a ROS 2 environment to enable live record/replay."


def _ros2_humble_typestore() -> object:
    """Build the ROS-2-Humble typestore for legacy ROS 2 sqlite3 bags (Pitfall 5).

    Modern ROS 2 bags (and MCAP / ROS 1) embed their own message definitions and
    need no default; the legacy ROS 2 sqlite3 fixture does. ``rosbags.typesys`` is
    ROS-FREE — importing it pulls no ``rclpy`` — so passing this default keeps the
    shared reader able to open every fixture while preserving the offline invariant.
    Imported INSIDE the body to keep this module's top level rosbags-free (D-08).
    """
    from rosbags.typesys import Stores, get_typestore

    return get_typestore(Stores.ROS2_HUMBLE)


class MainWindow(QMainWindow):
    """The desktop cockpit: a left nav + a stacked set of panels over a shared reader."""

    def __init__(
        self,
        bag_path: str | Path | None = None,
        theme_manager: object | None = None,
    ) -> None:
        """Build the shell, apply the capability gate (D-09), and open the launch bag.

        The single shared ``reader`` is ``None`` until a bag opens. ``ros_available``
        is computed ONCE here (cheap, D-09). A bad/missing launch bag surfaces a
        ``QMessageBox`` rather than crashing construction (WR-05).

        ``theme_manager`` (Phase 17) is the shell's live Dark/Light toggle owner (D-06).
        ``cli.main`` constructs+applies one and hands it in; when called directly (tests,
        the bag-only path) it is ``None`` and the window constructs its OWN ThemeManager so a
        directly-built window stays themeable. The manager is NOT re-applied here — cli.main
        already applied it before show(); a self-constructed one is left unapplied (no running
        app stylesheet is forced from a unit-test-built window).
        """
        super().__init__()
        self.setWindowTitle("rosbagger-desktop")

        # Theme manager (D-06): supplied by cli.main (already applied) or self-constructed for a
        # directly-built window so the View-menu toggle always has a manager to drive (Task 3).
        if theme_manager is None:
            from .theme import ThemeManager

            theme_manager = ThemeManager()
        self._theme_manager = theme_manager

        # The ONE shared open reader (D-07); None until a bag is opened.
        self.reader: object | None = None
        self._bag_path: Path | None = None
        # Called via the module (not a bound name) so a test can monkeypatch
        # ``rosbagger_desktop.capabilities.ros_available`` to force the gate path
        # deterministically — the documented analog of the TUI's _detect_ros patch.
        self._ros_available: bool = capabilities.ros_available()

        # Panel registry — an editable list of (panel_id, label, widget, is_live)
        # rows in the full TUI _PANELS order inspect/query/tf/record/replay (SC1
        # completeness, D-08/D-09). The three offline rows (is_live=False) are always
        # enabled; the two live rows (is_live=True) are capability-gated below — their
        # nav items are disabled with a teaching tooltip when ROS is absent.
        self.inspect_panel = InspectPanel(self)
        self.query_panel = QueryPanel(self)
        self.tf_panel = TfPanel(self)
        self.record_panel = RecordPanel(self)
        self.replay_panel = ReplayPanel(self)
        self._registry: list[tuple[str, str, QWidget, bool]] = [
            ("inspect", "Inspect", self.inspect_panel, False),
            ("query", "Query", self.query_panel, False),
            ("tf", "TF", self.tf_panel, False),
            ("record", "Record", self.record_panel, True),
            ("replay", "Replay", self.replay_panel, True),
        ]
        # Public accessor so headless tests reach the live widgets by id.
        self.panels: dict[str, QWidget] = {
            panel_id: widget for panel_id, _label, widget, _live in self._registry
        }

        self._nav = QListWidget()
        self._stack = QStackedWidget()
        for index, (_panel_id, label, widget, is_live) in enumerate(self._registry):
            self._nav.addItem(label)
            self._stack.addWidget(widget)
            # Capability gate (D-09): disable a LIVE row's nav item + teaching tooltip
            # when ROS is absent. No live rows exist yet this plan, but the gate runs
            # for Plans 02/03 to inherit unchanged.
            if is_live and not self._ros_available:
                item = self._nav.item(index)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setToolTip(_GATE_TOOLTIP)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._build_menu()

        # Select the initial (offline) panel so it renders on launch.
        initial_index = next(
            (i for i, (pid, *_rest) in enumerate(self._registry) if pid == _INITIAL_PANEL),
            0,
        )
        self._nav.setCurrentRow(initial_index)

        if bag_path is not None:
            self._open_reader(Path(bag_path))

    @property
    def ros_available(self) -> bool:
        """Whether a ROS 2 environment is sourced (computed once at startup, D-09)."""
        return self._ros_available

    def _build_menu(self) -> None:
        """Add a File menu with the two ``QFileDialog`` open paths (Pattern 5, D-16)."""
        file_menu = self.menuBar().addMenu("&File")
        open_file = file_menu.addAction("Open Bag File…")
        open_file.triggered.connect(self._open_bag_file)
        open_dir = file_menu.addAction("Open Bag Directory…")
        open_dir.triggered.connect(self._open_bag_directory)

    def _open_bag_file(self) -> None:
        """File ▸ Open Bag File… — a file picker for a ROS 1 ``.bag`` / standalone ``.mcap``."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open bag file", "", "Bags (*.bag *.mcap);;All files (*)"
        )
        if path:  # empty -> user cancelled (no-op)
            self._open_reader(Path(path))
            self._refresh_active_panel()

    def _open_bag_directory(self) -> None:
        """File ▸ Open Bag Directory… — a directory picker for a ROS 2 bag dir."""
        path = QFileDialog.getExistingDirectory(self, "Open ROS 2 bag directory")
        if path:  # empty -> user cancelled (no-op)
            self._open_reader(Path(path))
            self._refresh_active_panel()

    def _open_reader(self, path: Path) -> None:
        """Open ONE shared ``RosbagsReader`` over ``path`` (D-07), replacing any prior.

        Closes any currently-open reader first so there is never a second open reader.
        Passes the ROS-2-Humble typestore so the legacy sqlite3 fixture loads (Pitfall 5);
        modern bags ignore the unused default. A bad/corrupt/missing path surfaces a
        ``QMessageBox.warning`` rather than crashing construction (WR-05).
        """
        from rosbagger_core.reader import RosbagsReader  # lazy (D-08): keep top level light

        if self.reader is not None:
            self.reader.close()
            self.reader = None

        reader = RosbagsReader(path, default_typestore=_ros2_humble_typestore())
        try:
            reader.open()
        except Exception as exc:  # noqa: BLE001 - teaching dialog, not a startup crash (WR-05)
            QMessageBox.warning(self, "Could not open bag", f"Could not open {path}: {exc}")
            # WR-04: keep _bag_path consistent with reader. The prior reader was already
            # closed/nulled above, so a failed re-open must also drop the stale path rather
            # than leaving _bag_path pointing at a bag the window no longer has open.
            self._bag_path = None
            return
        self.reader = reader
        self._bag_path = path

    def _refresh_active_panel(self) -> None:
        """Re-READ the new shared reader into the currently-visible panel after a bag opens."""
        widget = self._stack.currentWidget()
        refresh_view = getattr(widget, "refresh_view", None)
        if callable(refresh_view):
            refresh_view()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Close the shared reader on shutdown (no leaked file handle, D-07)."""
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        super().closeEvent(event)
