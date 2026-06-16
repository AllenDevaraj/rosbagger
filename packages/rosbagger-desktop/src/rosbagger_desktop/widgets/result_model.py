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


def _temporal_column_indices(table: pyarrow.Table | None) -> frozenset[int]:
    """Indices of ``table``'s NANOSECOND-timestamp (``timestamp[ns]``) columns — once per table.

    Only ``timestamp[ns]`` needs the raw-ns ``numpy.datetime64`` render path in :meth:`data`:
    its sub-µs precision overflows ``datetime``'s µs floor, so ``.as_py()`` RAISES without pandas
    (not a desktop dep). Every OTHER temporal type renders correctly via ``.as_py()`` — and the
    old broad ``is_temporal`` gate sent them down the hard-coded ``"ns"`` path, MIS-SCALING a
    ``timestamp[us]`` / ``date32`` (from CAST / now() / date_trunc) by orders of magnitude and
    CRASHING on an ``interval`` (which has no ``.value``). So gate strictly on timestamp + ns.

    ``pyarrow`` is imported lazily here (the module top stays PySide6 + stdlib only); this is
    metadata-only (column TYPES, no row materialization), so it is cheap to do on set_table.
    """
    if table is None:
        return frozenset()
    import pyarrow as pa

    return frozenset(
        i
        for i, field in enumerate(table.schema)
        if pa.types.is_timestamp(field.type) and field.type.unit == "ns"
    )


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
        # Which columns are timestamp[ns] (QURY-04 t/stamp) — those cells need temporal-safe
        # rendering (SW1); computed once here (metadata-only) so data() stays O(1) per cell.
        self._temporal_cols: frozenset[int] = _temporal_column_indices(table)

    def rowCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The result's row count (``num_rows``), or 0 when there is no table."""
        return self._table.num_rows if self._table is not None else 0

    def columnCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802 - Qt override
        """The result's column count (``len(column_names)``), or 0 when there is no table."""
        return len(self._table.column_names) if self._table is not None else 0

    def data(self, index: QModelIndex, role: int = int(Qt.DisplayRole)) -> object | None:
        """Return ``str()`` of the cell at ``index`` for the DisplayRole, else ``None``.

        Lazy per-cell access (P2): read the single painted cell rather than materializing
        ``to_pylist()`` up front. A ``timestamp[ns]`` cell (the always-present ``t``/``stamp``
        columns) is rendered temporal-safe via ``numpy.datetime64`` from the scalar's raw ns
        value (SW1): ``.as_py()`` on a sub-microsecond ns timestamp RAISES ``ValueError`` when
        pandas is absent (it is not a desktop dependency), which previously made the time
        columns paint blank with per-cell traceback spam. An out-of-range index or a
        non-DisplayRole returns ``None``.
        """
        if role != int(Qt.DisplayRole) or self._table is None:
            return None
        row = index.row()
        col = index.column()
        if not (0 <= row < self._table.num_rows and 0 <= col < len(self._table.column_names)):
            return None
        scalar = self._table.column(col)[row]
        if col in self._temporal_cols:
            value = scalar.value  # raw int64 ns — .as_py() would raise on sub-µs ns
            if value is None:
                return ""
            import numpy as np

            return str(np.datetime64(int(value), "ns"))
        return str(scalar.as_py())

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
        self._temporal_cols = _temporal_column_indices(table)
        self.endResetModel()
