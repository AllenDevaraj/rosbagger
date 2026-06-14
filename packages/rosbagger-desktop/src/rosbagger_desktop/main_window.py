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

import contextlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QWidget,
)

from . import capabilities
from .panels.inspect_panel import InspectPanel
from .panels.query_panel import QueryPanel
from .panels.record_panel import RecordPanel
from .panels.replay_panel import ReplayPanel
from .panels.tf_panel import TfPanel
from .workers import stop_thread

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
        the bag-only path) it is ``None`` and the window LAZILY constructs its OWN ThemeManager
        on first access (the ``theme_manager`` property / a View-toggle click) so a directly-
        built window stays themeable. Deferring construction keeps ``__init__`` from creating an
        extra ``QObject`` + doing ``QSettings`` disk I/O on EVERY window build — every unrelated
        headless test builds a window, and an orphaned manager QObject aggravates the known
        offscreen teardown Bus-error race (CONTEXT host note). A self-constructed manager is
        PARENTED to this window so it is destroyed with the window. A cli-supplied manager is
        already applied + owned by cli.main and stored as-is.
        """
        super().__init__()
        self.setWindowTitle("rosbagger-desktop")

        # Theme manager (D-06): a cli-supplied manager is stored eagerly; otherwise construction
        # is deferred until first access (see _ensure_theme_manager) to keep __init__ light.
        self._theme_manager = theme_manager

        # The ONE shared open reader (D-07); None until a bag is opened.
        self.reader: object | None = None
        self._bag_path: Path | None = None
        # The ROS-2-Humble typestore for legacy/def-less ROS 2 sqlite3 bags (Pitfall 5), built
        # once on first access (see the default_typestore property). Cached here so the offline
        # reader AND the live replay panel deserialize through the SAME typestore instance.
        self._default_typestore: object | None = None
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

        # Shell chrome objectNames (17-03 / D-03): the theme QSS targets these so the cockpit
        # frame (nav rail + central surface + panel stack) is styled centrally — the shell
        # writes NO inline color/QSS itself (styling lives only in theme/qss.py).
        self._nav = QListWidget()
        self._nav.setObjectName("nav_list")
        self._stack = QStackedWidget()
        self._stack.setObjectName("panel_stack")
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
        central.setObjectName("shell_central")
        layout = QHBoxLayout(central)
        # Deliberate spacing rhythm (17-03 / D-03): the nav rail is a fixed-width gutter and the
        # central margins/spacing give the cockpit breathing room — set on the layout, not via an
        # inline stylesheet color literal (styling stays in theme/qss.py).
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._nav.setMaximumWidth(180)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._build_menu()

        # Phase 23: a top-right corner control. On the Replay tab it collapses to the compact
        # overlay mini-player; on any other tab it does a normal OS minimize (textbook behavior).
        # The overlay (created lazily on first entry) + saved geometry let exit_overlay restore us.
        self._overlay: object | None = None
        self._saved_geometry: object | None = None
        self._overlay_button = QToolButton()
        self._overlay_button.setText("⤓")
        self._overlay_button.setObjectName("overlay_button")
        self._overlay_button.setToolTip("Compact overlay (Replay tab) / minimize")
        self.menuBar().setCornerWidget(self._overlay_button, Qt.TopRightCorner)
        self._overlay_button.clicked.connect(self._on_minimize_clicked)

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

    @property
    def default_typestore(self) -> object:
        """The ROS-2-Humble typestore used to read legacy/def-less ROS 2 sqlite3 bags.

        Built once and cached (the ``rosbags`` import stays lazy inside
        ``_ros2_humble_typestore`` — the offline/Qt-free top-level invariant, D-08). Exposed
        publicly so the live replay panel deserializes through the SAME typestore the offline
        reader uses (Pitfall 5): a real ``rosbag2`` sqlite3 recording embeds no message
        definitions, so ``load_items`` needs this or ``rosbags`` raises "no type definitions".
        """
        if self._default_typestore is None:
            self._default_typestore = _ros2_humble_typestore()
        return self._default_typestore

    def _ensure_theme_manager(self) -> object:
        """Return the shell's :class:`ThemeManager`, constructing one on first need (D-06).

        A cli-supplied manager is returned as-is. Otherwise one is constructed LAZILY and
        PARENTED to this window (destroyed with it — no orphaned QObject through teardown) the
        first time the toggle is used or the property is read. Deferring keeps ``__init__`` from
        building a QObject + touching ``QSettings`` on every (often theme-irrelevant) window.
        """
        if self._theme_manager is None:
            from .theme import ThemeManager

            manager = ThemeManager()
            manager.setParent(self)
            self._theme_manager = manager
        return self._theme_manager

    @property
    def theme_manager(self) -> object:
        """The shell's :class:`ThemeManager` (D-06), lazily constructed on first access."""
        return self._ensure_theme_manager()

    @property
    def theme_action(self) -> object:
        """The checkable View-menu "Dark theme" action (a test accessor, D-06)."""
        return self._theme_action

    def _build_menu(self) -> None:
        """Add File (open paths) + View (live Dark/Light toggle) menus (Pattern 5 / D-06)."""
        file_menu = self.menuBar().addMenu("&File")
        open_file = file_menu.addAction("Open Bag File…")
        open_file.triggered.connect(self._open_bag_file)
        open_dir = file_menu.addAction("Open Bag Directory…")
        open_dir.triggered.connect(self._open_bag_directory)

        # View ▸ Dark theme — a checkable action wired to ThemeManager.toggle (D-06). Lowest-
        # friction toggle home (17-RESEARCH Open Question 1) — no new toolbar chrome. The check
        # state reflects a cli-supplied manager's name when present; for a lazily-managed window
        # the manager is not yet built, so it defaults to the dark default (and is reconciled on
        # first toggle). The action build does NOT force a manager into existence.
        view_menu = self.menuBar().addMenu("&View")
        self._theme_action = view_menu.addAction("Dark theme")
        self._theme_action.setCheckable(True)
        initial_name = self._theme_manager.name if self._theme_manager is not None else "dark"
        self._theme_action.setChecked(initial_name == "dark")
        self._theme_action.triggered.connect(self._on_theme_action)

    def _on_theme_action(self) -> None:
        """View ▸ Dark theme triggered: flip the theme live, then sync the check state (D-06).

        Delegates the actual dark↔light flip + persistence + live restyle to
        ``ThemeManager.toggle`` (D-03/D-06 — the shell owns no styling logic), then reflects the
        manager's resulting name in the action's checked state so the menu stays in sync. Uses
        the lazy accessor so a directly-built window constructs its manager on first toggle.
        """
        manager = self._ensure_theme_manager()
        manager.toggle()
        self._theme_action.setChecked(manager.name == "dark")

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

        # C3: stop any in-flight offline-panel workers BEFORE closing the reader they iterate.
        # query/inspect/tf each run query()/collect_*/collect_tf_report on a BlockingWorker thread
        # that lazily iterates this shared reader; closing it mid-iteration is a use-after-free /
        # SIGBUS (sqlite3 cursor / mmap'd MCAP). stop_thread quit()+wait()s each (a no-op for a
        # None/finished thread), so the worker has stopped touching the reader before close(). This
        # briefly blocks the UI thread until a heavy in-flight call returns — the same accepted
        # trade-off the live panels' close-path stop_thread already makes.
        stop_thread(self.query_panel._query_thread)  # noqa: SLF001 - panel exposes these to tests too
        stop_thread(self.inspect_panel._refresh_thread)  # noqa: SLF001
        stop_thread(self.tf_panel._refresh_thread)  # noqa: SLF001

        if self.reader is not None:
            self.reader.close()
            self.reader = None

        reader = RosbagsReader(path, default_typestore=self.default_typestore)
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

    # ------------------------------------------------------- compact overlay (Phase 23)

    @property
    def overlay(self) -> object | None:
        """The compact overlay mini-player (``None`` until first entered) — a test accessor."""
        return self._overlay

    @property
    def overlay_button(self) -> QToolButton:
        """The top-right corner control (overlay on Replay / minimize elsewhere) — test accessor."""
        return self._overlay_button

    def _on_minimize_clicked(self) -> None:
        """Corner control: collapse to the overlay on the Replay tab, normal minimize elsewhere."""
        if self._stack.currentWidget() is self.replay_panel:
            self.enter_overlay()
        else:
            self.showMinimized()

    def enter_overlay(self) -> None:
        """Collapse to the compact overlay: save geometry, hide the window, show the floating bar.

        The overlay (created lazily here, then reused) remote-controls the EXISTING Replayer via the
        ReplayPanel 23-02 API (no second transport). Dragging its scrubber seeks live so RViz/Rerun
        update. ``exit_overlay`` (⛶) restores the window; the overlay's ✕ quits the app.
        """
        from .widgets.overlay import OverlayWindow

        self._saved_geometry = self.saveGeometry()
        if self._overlay is None:
            self._overlay = OverlayWindow(self.replay_panel, self)
        self._overlay.sync()
        self._position_overlay()
        self.hide()
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _position_overlay(self) -> None:
        """Place the overlay near the bottom-center of the available screen (best-effort)."""
        if self._overlay is None:
            return
        screen = self.screen()
        if screen is None:
            self._overlay.move(100, 100)  # headless / no screen — a sane fixed spot
            return
        geo = screen.availableGeometry()
        self._overlay.adjustSize()
        x = geo.x() + (geo.width() - self._overlay.width()) // 2
        y = geo.y() + geo.height() - self._overlay.height() - 60
        self._overlay.move(x, y)

    def exit_overlay(self) -> None:
        """Restore the full window from the overlay (⛶), at its prior geometry."""
        if self._overlay is not None:
            self._overlay.hide()
        self.showNormal()
        if self._saved_geometry is not None:
            self.restoreGeometry(self._saved_geometry)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Close the overlay, tear down the live panels, and close the shared reader on shutdown.

        Qt does NOT deliver ``closeEvent`` to CHILD widgets, so the live panels' own ``closeEvent``
        (which stops the drive/record worker threads, tears down the rclpy transport, and closes the
        spawned RViz + Rerun viewers) never runs on a window close — leaving those viewers to the
        ``atexit`` backstop, which does NOT fire if the known Qt-teardown SIGBUS hits (the viewers
        then orphan). So we explicitly ``close()`` each live panel here (delivering a QCloseEvent →
        the panel's ``closeEvent`` teardown) during the controlled close, BEFORE the reader closes.
        """
        if self._overlay is not None:
            # Suppress so an overlay-close raise can't skip the live-panel teardown below (the
            # whole point of this override) — matches the panel-close loop's guarding.
            with contextlib.suppress(Exception):
                self._overlay.close()
            self._overlay = None
        # Live panels own the spawned viewers + worker threads; close them so teardown runs now.
        for panel in (self.replay_panel, self.record_panel):
            with contextlib.suppress(Exception):
                panel.close()
        # C3: the OFFLINE panels also run worker threads that iterate the shared reader; Qt does
        # NOT auto-deliver closeEvent to child widgets, so close() each to run its stop_thread
        # teardown BEFORE the reader closes below — otherwise a query/inspect/tf worker can outlive
        # the reader and touch a freed handle during shutdown (the un-joined-QThread SIGBUS).
        for panel in (self.inspect_panel, self.query_panel, self.tf_panel):
            with contextlib.suppress(Exception):
                panel.close()
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        super().closeEvent(event)
