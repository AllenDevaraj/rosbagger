"""``RowsTableModel`` — a generic lazy ``QAbstractTableModel`` over list-of-tuple rows.

The dataclass-row analog of ``_ResultTableModel`` (17-02 / D-02): where the query panel's
result model wraps a ``pyarrow.Table``, this wraps a plain ``list[tuple[str, ...]]`` so the
inspect / tf panels can render their already-formatted core rows through the same
``QTableView`` + model/view path (D-02 parity) instead of per-cell ``QTableWidgetItem``s.

PURE presentation wrapper (thin-face, D-09): it stores ``headers`` and ``rows`` and renders
each cell lazily via ``str()`` on paint — it builds nothing, analyses nothing. The caller
(panel) does ALL formatting up front (human-readable durations/sizes, em-dash placeholders)
and hands in ready strings; this only displays them.

OFFLINE-CLEAN (D-08, Pitfall 4): imports ONLY PySide6 + stdlib — importing this module
pulls in no ROS / heavy stack.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class RowsTableModel(QAbstractTableModel):
    """A lazy ``QAbstractTableModel`` over fixed ``headers`` + ``list[tuple[str, ...]]`` rows.

    Construct with the column ``headers`` (used for the horizontal header) and an optional
    initial ``rows`` list. :meth:`set_rows` swaps the rows inside a begin/endResetModel so a
    bound ``QTableView`` refreshes. Each cell is ``str()``-rendered on the DisplayRole — the
    same temporal-safe rule as the result model (never convert, only str()).
    """

    def __init__(
        self, headers: list[str], rows: list[tuple[str, ...]] | None = None
    ) -> None:
        """Hold the column ``headers`` + an optional initial ``rows`` list (default empty)."""
        super().__init__()
        self._headers: list[str] = list(headers)
        self._rows: list[tuple[str, ...]] = list(rows) if rows is not None else []

    def rowCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The number of rows currently held."""
        return len(self._rows)

    def columnCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The column count (``len(headers)``)."""
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = int(Qt.DisplayRole)) -> object | None:
        """Return ``str()`` of the cell at ``index`` for the DisplayRole, else ``None``.

        An out-of-range row/column or a non-DisplayRole returns ``None``. A row shorter than
        the header width yields ``None`` for the missing trailing cells (defensive).
        """
        if role != int(Qt.DisplayRole):
            return None
        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._rows) and 0 <= col < len(self._headers)):
            return None
        cells = self._rows[row]
        if col >= len(cells):
            return None
        return str(cells[col])

    def headerData(  # noqa: N802 - Qt override name
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.DisplayRole),
    ) -> object | None:
        """The header label for a horizontal DisplayRole header section, else ``None``."""
        if (
            role != int(Qt.DisplayRole)
            or orientation != Qt.Horizontal
            or not (0 <= section < len(self._headers))
        ):
            return None
        return self._headers[section]

    def set_rows(self, rows: list[tuple[str, ...]]) -> None:
        """Swap the backing rows inside a begin/endResetModel so the view refreshes."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()
