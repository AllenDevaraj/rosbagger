"""Inspect panel (offline, D-10) — a thin Qt face over ``rosbagger_core.inspect``.

OFFLINE PANEL (D-08): always enabled. A pure RENDERER — it reads the window's single
shared open reader and calls EXACTLY two ``rosbagger_core.inspect`` APIs:
:func:`collect_bag_info` (per-topic msgtype/count/Hz + whole-bag duration/size/count)
and :func:`collect_table_schemas` (per-topic table name + column schema). It contains
ZERO analysis logic; every number comes from core. Display formatting (human-readable
duration/size, ``<mixed>``/em-dash placeholders) is presentation only — mirroring the
TUI inspect panel — and adds no computation.

ENGINEERING PARITY (17-02 / D-02): brought up to the query-panel bar. The two tabular
surfaces render via :class:`~rosbagger_desktop.widgets.RowsTableModel` + ``QTableView``
(not per-cell ``QTableWidgetItem``), the blocking ``collect_*`` calls run OFF the UI thread
on a :class:`~rosbagger_desktop.workers.BlockingWorker` (so a heavy bag never freezes the
window — T-17-04), and the header status routes through the shared accessible
:func:`~rosbagger_desktop.widgets.set_status` helper.

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): the ``rosbagger_core.inspect`` import lives
INSIDE the worker ``work()`` body (a method body), never at module top — so this module's
top level stays PySide6-only and importing it pulls no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..widgets import RowsTableModel, set_status
from ..workers import BlockingWorker, run_on_thread, stop_thread

# Placeholder rendering (mirrors the TUI / bagq CLI shape) — presentation only.
_MIXED = "<mixed>"
_EM_DASH = "—"

_BAG_INFO_HEADERS = ["topic", "msgtype", "count", "hz"]
_SCHEMAS_HEADERS = ["table", "column", "type", "lazy"]


def _human_size(size_bytes: int) -> str:
    """Format a byte count human-readably (B/KB/MB/GB/TB) — presentation only.

    Mirrors the TUI inspect panel's ``_human_size``; the core API keeps ``size_bytes``
    as a raw int (display formatting is the face's job, not the API's).
    """
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


class InspectPanel(QWidget):
    """Inspect view — topics/types/counts/duration/size + per-topic table schemas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the header label + the bag-info and table-schema ``QTableView``s (D-02)."""
        super().__init__(parent)

        # The in-flight refresh worker thread (Pitfall 2 — kept so the GC can't collect a
        # live thread mid-run) and its worker. Both None between refreshes.
        self._refresh_thread: QThread | None = None
        self._refresh_worker: BlockingWorker | None = None

        # Status/header line as an accessibly-named region (D-02); a stable objectName lets
        # the shared status helper restore it after an error toggle.
        self._header = QLabel("Open a bag to inspect")
        self._header.setObjectName("inspect_status")
        self._header.setAccessibleName("Inspect status")
        self._header.setAccessibleDescription("Open a bag to inspect")
        # Section-heading affordance (17-03 / D-03): keyed to the theme QSS heading style — no
        # inline font/color literal in the panel.
        self._header.setProperty("heading", True)

        # Model/view rendering target (D-02): a generic RowsTableModel behind a QTableView,
        # no per-cell item allocation. The panel formats every cell to a string up front.
        self._bag_info_model = RowsTableModel(_BAG_INFO_HEADERS)
        self._bag_info_view = QTableView()
        self._bag_info_view.setModel(self._bag_info_model)
        self._bag_info_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._bag_info_view.setEditTriggers(QTableView.NoEditTriggers)

        self._schemas_model = RowsTableModel(_SCHEMAS_HEADERS)
        self._schemas_view = QTableView()
        self._schemas_view.setModel(self._schemas_model)
        self._schemas_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._schemas_view.setEditTriggers(QTableView.NoEditTriggers)

        layout = QVBoxLayout(self)
        # Deliberate spacing rhythm (17-03 / D-03): margins/spacing on the layout, not an inline
        # color/QSS literal — styling stays in theme/qss.py.
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._header)
        layout.addWidget(self._bag_info_view, 1)
        layout.addWidget(self._schemas_view, 1)

    @property
    def bag_info_table(self) -> QTableView:
        """The per-topic overview view (tests assert ``.model().rowCount() > 0``)."""
        return self._bag_info_view

    @property
    def schemas_table(self) -> QTableView:
        """The per-topic (table, column) schema view."""
        return self._schemas_view

    @property
    def status_label(self) -> QLabel:
        """The header/status line (accessible region; D-02)."""
        return self._header

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Re-read whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self.refresh_view()

    def _reader(self) -> object | None:
        """The window's single shared open reader (``None`` until a bag opens)."""
        return getattr(self.window(), "reader", None)

    def refresh_view(self) -> None:
        """Dispatch the two ``collect_*`` calls OFF the UI thread on a worker (D-02 / P1).

        With no bag open it shows the empty-state header and clears both models — never an
        analysis pass without a reader. Otherwise it runs ``collect_bag_info`` +
        ``collect_table_schemas`` on a :class:`~rosbagger_desktop.workers.BlockingWorker`
        (the heavy path never blocks the UI event loop — T-17-04); the result is formatted
        into rows and fed to both models on the UI thread (:meth:`_on_refresh_result`). A
        refresh while a worker runs is refused (re-entry guard, mirroring query).
        """
        reader = self._reader()
        if reader is None:
            set_status(self._header, "Open a bag to inspect")
            self._bag_info_model.set_rows([])
            self._schemas_model.set_rows([])
            return

        # Re-entry guard: a refresh while a worker runs is refused (mirrors the query panel).
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            return

        def work() -> object:
            # Lazy import (D-08): keep this module's top level PySide6-only. The two APIs run
            # off the UI thread; the panel performs no analysis (thin-face).
            from rosbagger_core.inspect import collect_bag_info, collect_table_schemas

            return (collect_bag_info(reader), collect_table_schemas(reader))

        worker = BlockingWorker(work, label="Inspect failed")
        self._refresh_thread, self._refresh_worker = run_on_thread(
            self,
            worker,
            on_result=self._on_refresh_result,
            on_failed=self._on_refresh_failed,
            on_finished=self._on_refresh_finished,
        )

    def _on_refresh_result(self, result: object) -> None:
        """Format the worker's ``(info, schemas)`` pair into rows on the UI thread (D-09).

        Presentation only (THIN-FACE): the human-readable duration/size + ``<mixed>``/em-dash
        placeholders are display formatting, no new analysis. Rows are fed to both models via
        ``set_rows`` (begin/endResetModel refreshes the bound views).
        """
        info, schemas = result  # type: ignore[misc]  # always the (info, schemas) pair here

        # Whole-bag header line (presentation formatting only — no new analysis).
        duration = f"{info.duration_ns / 1e9:.2f}s" if info.duration_ns is not None else _EM_DASH
        header_line = (
            f"duration: {duration} · {info.message_count} messages "
            f"· {_human_size(info.size_bytes)}"
        )
        set_status(self._header, header_line)

        # Per-topic overview: one row per BagInfo.topics entry (each cell str()-formatted).
        info_rows: list[tuple[str, ...]] = []
        for ti in info.topics:
            hz = f"{ti.hz:.1f}" if ti.hz is not None else _EM_DASH
            info_rows.append(
                (str(ti.topic), str(ti.msgtype or _MIXED), str(ti.count), str(hz))
            )
        self._bag_info_model.set_rows(info_rows)

        # Per-topic table schemas: one row per (table, column) with a heavy-blob marker.
        schema_rows: list[tuple[str, ...]] = []
        for schema in schemas:
            for col in schema.columns:
                marker = "lazy (blob)" if col.is_heavy_blob else ""
                schema_rows.append(
                    (str(schema.table_name), str(col.name), str(col.arrow_type), str(marker))
                )
        self._schemas_model.set_rows(schema_rows)

    def _on_refresh_failed(self, message: str) -> None:
        """Render an unexpected refresh error VERBATIM on the accessible status line (D-09).

        The worker emits ``"Inspect failed: <exc>"`` (never a traceback). Both models are
        cleared so a stale view never lingers behind a failure.
        """
        set_status(self._header, message, is_error=True)
        self._bag_info_model.set_rows([])
        self._schemas_model.set_rows([])

    def _on_refresh_finished(self) -> None:
        """Clear the thread/worker refs on every outcome (CR-01, UI thread)."""
        self._refresh_thread = None
        self._refresh_worker = None

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Stop the in-flight refresh thread before teardown (Pitfall 2)."""
        stop_thread(self._refresh_thread)
        super().closeEvent(event)
