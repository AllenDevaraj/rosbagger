"""``OverlayWindow`` — the compact, frameless mini-player (Phase 23).

A small always-on-top window that REMOTE-CONTROLS the existing Replay transport via the ReplayPanel
23-02 API (no second Replayer): ``‹ 5s`` / ``⏯`` / ``5s ›`` / a ``Scrubber`` / ``⛶`` restore /
``✕`` close. The user opens RViz/Rerun, collapses the GUI to this thin slider, and scrubs — the seek
republishes to ROS so RViz/Rerun update live. Entry + restore are owned by the ``MainWindow`` (which
saves/restores geometry); ``✕`` quits the app, ``⛶`` restores the full window.

OFFLINE-CLEAN (Pitfall 4): imports ONLY PySide6 + the local ``Scrubber`` — no ROS, no rerun.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .scrubber import Scrubber


class OverlayWindow(QWidget):
    """A frameless, always-on-top mini-player bound to a ReplayPanel's remote-control API."""

    def __init__(self, panel, main_window, parent: QWidget | None = None) -> None:
        """Build the strip + wire every control to ``panel`` (23-02 API) and ``main_window``."""
        super().__init__(parent)
        self._panel = panel
        self._main = main_window
        self._drag_offset = None
        self.setObjectName("overlay_window")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedHeight(56)
        self.setMinimumWidth(520)

        self._back = QToolButton()
        self._back.setText("‹ 5s")
        self._play = QToolButton()
        self._play.setText("⏯")
        self._fwd = QToolButton()
        self._fwd.setText("5s ›")
        self._scrubber = Scrubber()
        self._restore = QToolButton()
        self._restore.setText("⛶")
        self._restore.setToolTip("Restore the full window")
        self._close = QToolButton()
        self._close.setText("✕")
        self._close.setToolTip("Close rosbagger")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addWidget(self._back)
        layout.addWidget(self._play)
        layout.addWidget(self._fwd)
        layout.addWidget(self._scrubber, 1)
        layout.addWidget(self._restore)
        layout.addWidget(self._close)

        # Controls → the panel's 23-02 remote API + the window (no transport logic here).
        self._back.clicked.connect(panel.skip_back)
        self._play.clicked.connect(panel.toggle_play)
        self._fwd.clicked.connect(panel.skip_forward)
        self._scrubber.seeked.connect(panel.seek_fraction)
        self._restore.clicked.connect(main_window.exit_overlay)
        self._close.clicked.connect(main_window.close)
        # Live playhead: the panel emits positionChanged from _update_position.
        panel.positionChanged.connect(self._scrubber.set_position)

    # ------------------------------------------------------------------ accessors

    @property
    def scrubber(self) -> Scrubber:
        """The overlay's timeline scrubber (synced to the panel; drag → seek)."""
        return self._scrubber

    @property
    def play_button(self) -> QToolButton:
        """The ⏯ play/pause button."""
        return self._play

    @property
    def skip_back_button(self) -> QToolButton:
        """The ‹ 5s skip-back button."""
        return self._back

    @property
    def skip_forward_button(self) -> QToolButton:
        """The 5s › skip-forward button."""
        return self._fwd

    @property
    def restore_button(self) -> QToolButton:
        """The ⛶ restore button (back to the full window)."""
        return self._restore

    @property
    def close_button(self) -> QToolButton:
        """The ✕ close button (quits the app)."""
        return self._close

    def sync(self) -> None:
        """Snap the scrubber to the panel's current playhead (called by the window on enter)."""
        self._scrubber.set_position(self._panel.current_fraction())

    # ------------------------------------------------- frameless window dragging

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """Start a drag on a left-press over the overlay background (children handle their own)."""
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """Move the frameless window while the left button is held."""
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """End the drag."""
        self._drag_offset = None
        event.accept()
