"""``_ResultTableModel`` — a lazy ``QAbstractTableModel`` over a ``pyarrow.Table`` (P2).

LIFTED VERBATIM out of ``panels/query_panel.py`` (17-02 / D-02) so every panel can share
the query panel's allocation-light model/view rendering. The class body is unchanged from
its query-panel origin: it reads the result ``pyarrow.Table`` only via ``num_rows`` /
``column_names`` / ``column(...)`` — it builds no SQL, picks no format, and analyses
nothing (thin-face). The rows are core's; this only renders them. Unlike a ``QTableWidget``
(a ``QTableWidgetItem`` allocated per cell up front), the view pulls each cell lazily
through :meth:`data` only when it paints — so a wide/long result is not materialized into
N×M widget items.

Each cell is ``str()``-rendered for display (the temporal-safe rule: an ns-timestamp →
datetime conversion crash class is sidestepped by never converting; we only str() it).

OFFLINE-CLEAN (D-08, Pitfall 4): imports ONLY PySide6 + stdlib (``pyarrow`` is a
TYPE_CHECKING-only import) — importing this module pulls in no ROS / heavy stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow


class _ResultTableModel(QAbstractTableModel):
    """A lazy, allocation-light ``QAbstractTableModel`` over a ``pyarrow.Table`` (P2).

    PURE presentation wrapper (thin-face): it reads the result ``pyarrow.Table`` only via
    ``num_rows`` / ``column_names`` / ``column(...)`` — it builds no SQL, picks no format,
    and analyses nothing. The rows are core's; this only renders them. Unlike the old
    ``QTableWidget`` (a ``QTableWidgetItem`` allocated per cell up front), the view pulls
    each cell lazily through :meth:`data` only when it paints — so a wide/long result is not
    materialized into N×M widget items.

    Each cell is ``str()``-rendered for display (the temporal-safe rule: an ns-timestamp →
    datetime conversion crash class is sidestepped by never converting; we only str() it).
    """

    def __init__(self, table: pyarrow.Table | None = None) -> None:
        """Hold an optional ``pyarrow.Table`` (``None`` → an empty 0×0 model)."""
        super().__init__()
        self._table: pyarrow.Table | None = table

    def rowCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The result's row count (``num_rows``), or 0 when there is no table."""
        return self._table.num_rows if self._table is not None else 0

    def columnCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The result's column count (``len(column_names)``), or 0 when there is no table."""
        return len(self._table.column_names) if self._table is not None else 0

    def data(self, index: QModelIndex, role: int = int(Qt.DisplayRole)) -> object | None:
        """Return ``str()`` of the cell at ``index`` for the DisplayRole, else ``None``.

        Lazy per-cell access (P2): read ``column(col)[row].as_py()`` only for the cell being
        painted rather than materializing ``to_pylist()`` up front. An out-of-range index or a
        non-DisplayRole returns ``None``.
        """
        if role != int(Qt.DisplayRole) or self._table is None:
            return None
        row = index.row()
        col = index.column()
        if not (0 <= row < self._table.num_rows and 0 <= col < len(self._table.column_names)):
            return None
        value = self._table.column(col)[row].as_py()
        return str(value)

    def headerData(  # noqa: N802 - Qt override name
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.DisplayRole),
    ) -> object | None:
        """The column name for a horizontal DisplayRole header section, else ``None``."""
        if (
            role != int(Qt.DisplayRole)
            or orientation != Qt.Horizontal
            or self._table is None
            or not (0 <= section < len(self._table.column_names))
        ):
            return None
        return self._table.column_names[section]

    def set_table(self, table: pyarrow.Table | None) -> None:
        """Swap the backing table inside a begin/endResetModel so the view refreshes (P2)."""
        self.beginResetModel()
        self._table = table
        self.endResetModel()
