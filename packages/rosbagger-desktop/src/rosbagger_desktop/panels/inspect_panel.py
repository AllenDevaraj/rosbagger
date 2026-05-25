"""Inspect panel (offline, D-10) — a thin Qt face over ``rosbagger_core.inspect``.

OFFLINE PANEL (D-08): always enabled. A pure RENDERER — it reads the window's single
shared open reader and calls EXACTLY two ``rosbagger_core.inspect`` APIs:
:func:`collect_bag_info` (per-topic msgtype/count/Hz + whole-bag duration/size/count)
and :func:`collect_table_schemas` (per-topic table name + column schema). It contains
ZERO analysis logic; every number comes from core. Display formatting (human-readable
duration/size, ``<mixed>``/em-dash placeholders) is presentation only — mirroring the
TUI inspect panel — and adds no computation.

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): the ``rosbagger_core.inspect`` import lives
INSIDE :meth:`refresh_view` (a method body), never at module top — so this module's top
level stays PySide6-only and importing it pulls no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Placeholder rendering (mirrors the TUI / bagq CLI shape) — presentation only.
_MIXED = "<mixed>"
_EM_DASH = "—"


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
        """Build the header label + the bag-info and table-schema ``QTableWidget``s."""
        super().__init__(parent)

        self._header = QLabel("Open a bag to inspect")

        self._bag_info_table = QTableWidget(0, 4)
        self._bag_info_table.setHorizontalHeaderLabels(["topic", "msgtype", "count", "hz"])
        self._bag_info_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._bag_info_table.setEditTriggers(QTableWidget.NoEditTriggers)

        self._schemas_table = QTableWidget(0, 4)
        self._schemas_table.setHorizontalHeaderLabels(["table", "column", "type", "lazy"])
        self._schemas_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._schemas_table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addWidget(self._bag_info_table, 1)
        layout.addWidget(self._schemas_table, 1)

    @property
    def bag_info_table(self) -> QTableWidget:
        """The per-topic overview table (tests assert ``rowCount() > 0`` here)."""
        return self._bag_info_table

    @property
    def schemas_table(self) -> QTableWidget:
        """The per-topic (table, column) schema table."""
        return self._schemas_table

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Re-read whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self.refresh_view()

    def _reader(self) -> object | None:
        """The window's single shared open reader (``None`` until a bag opens)."""
        return getattr(self.window(), "reader", None)

    def refresh_view(self) -> None:
        """Read the window's shared reader and fill both tables from core output.

        Lazily imports the two ``rosbagger_core.inspect`` APIs INSIDE the method
        (offline invariant), calls them against the shared reader, and renders the
        results. With no bag open it shows the empty-state header and clears the
        tables — never an analysis pass without a reader.
        """
        reader = self._reader()
        if reader is None:
            self._header.setText("Open a bag to inspect")
            self._bag_info_table.setRowCount(0)
            self._schemas_table.setRowCount(0)
            return

        # Lazy import (D-08): keep this module's top level PySide6-only.
        from rosbagger_core.inspect import collect_bag_info, collect_table_schemas

        info = collect_bag_info(reader)
        schemas = collect_table_schemas(reader)

        # Whole-bag header line (presentation formatting only — no new analysis).
        duration = f"{info.duration_ns / 1e9:.2f}s" if info.duration_ns is not None else _EM_DASH
        self._header.setText(
            f"duration: {duration} · {info.message_count} messages · {_human_size(info.size_bytes)}"
        )

        # Per-topic overview: one row per BagInfo.topics entry.
        self._bag_info_table.setRowCount(len(info.topics))
        for row, ti in enumerate(info.topics):
            hz = f"{ti.hz:.1f}" if ti.hz is not None else _EM_DASH
            self._bag_info_table.setItem(row, 0, QTableWidgetItem(str(ti.topic)))
            self._bag_info_table.setItem(row, 1, QTableWidgetItem(str(ti.msgtype or _MIXED)))
            self._bag_info_table.setItem(row, 2, QTableWidgetItem(str(ti.count)))
            self._bag_info_table.setItem(row, 3, QTableWidgetItem(str(hz)))

        # Per-topic table schemas: one row per (table, column) with a heavy-blob marker.
        rows = [(schema.table_name, col) for schema in schemas for col in schema.columns]
        self._schemas_table.setRowCount(len(rows))
        for row, (table_name, col) in enumerate(rows):
            marker = "lazy (blob)" if col.is_heavy_blob else ""
            self._schemas_table.setItem(row, 0, QTableWidgetItem(str(table_name)))
            self._schemas_table.setItem(row, 1, QTableWidgetItem(str(col.name)))
            self._schemas_table.setItem(row, 2, QTableWidgetItem(str(col.arrow_type)))
            self._schemas_table.setItem(row, 3, QTableWidgetItem(str(marker)))
