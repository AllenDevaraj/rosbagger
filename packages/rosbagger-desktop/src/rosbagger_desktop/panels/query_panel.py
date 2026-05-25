"""Query panel (offline, D-11) — a thin Qt face over ``rosbagger_core.backend.query``.

OFFLINE PANEL (D-08): always enabled. This is the richest offline panel and a pure
FACE: it collects a SQL *string* and forwards it VERBATIM to the ONE query API —
:func:`rosbagger_core.backend.query.query` — against the window's single shared open
reader, then maps the returned ``pyarrow.Table`` into the ``results`` view via a lazy
``QAbstractTableModel`` + ``QTableView`` (16-RESEARCH Pattern 4, P2 — allocation-light).
It contains ZERO SQL/format/selection logic: it never builds
SQL, never picks a serialization format, and never analyses anything — the string is
the user's, the rows are core's (the thin-face rule). The Qt analog of the TUI query
panel (``rosbagger_gui.panels.query``), ported one-to-one into PySide6 widgets.

It keeps a query HISTORY (D-06): every successfully-run SQL is appended to a
``QListWidget``; selecting an entry repopulates the SQL input so the user re-runs by
pressing Run again. Bad queries raise the Phase-7 teaching errors
(``UnknownTableError`` / ``UnknownColumnError`` / ``UnresolvedTypeError``, all
``ValueError`` subclasses carrying messages built in core); the panel CATCHES them and
renders ``str(e)`` into the status ``QLabel`` — the GUI PRESENTS the teaching message,
it does not BUILD it (API-first).

A schema/topic ``QTreeWidget`` browser sourced from
:func:`rosbagger_core.inspect.collect_table_schemas` (D-11) gives one top-level item
per table with a child leaf per column; clicking a column leaf inserts that column
name — VERBATIM from ``col.name``, the panel constructs NO SQL — into the SQL input at
the cursor. Two export ``QPushButton``s write the LAST result ``pyarrow.Table`` via
:func:`rosbagger_core.output.export.write_table` (the one LIST/STRUCT-safe writer; the
serialization is chosen by the file EXTENSION, never by the panel — the panel only
supplies a path with the matching suffix). Export is disabled until a result exists.

The blocking ``query(sql, reader)`` call runs OFF the UI thread on a
:class:`~rosbagger_desktop.workers.BlockingWorker` (P1, mirroring the replay panel's drive
worker): Run disables + a running status shows for the flight, the result/teaching message
arrives on a UI-thread slot, and Run re-enables on finish — so a heavy-but-bounded query
never freezes the window. A second Run while one is in flight is refused.

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): every ``rosbagger_core`` import lives
INSIDE a method body (the run handler / ``refresh_view`` / the export handler), never
at module top — the top level stays PySide6 + local (``..workers``) only, so importing
this module pulls no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..workers import BlockingWorker, run_on_thread, stop_thread

# Default export file NAMES (the dialog's pre-filled name; the user picks the directory via
# the save dialog, WR-03). The panel collects a PATH only; the FORMAT is chosen by write_table
# from the extension — the panel never picks a format itself.
_CSV_DEFAULT_NAME = "query_result.csv"
_PARQUET_DEFAULT_NAME = "query_result.parquet"
_CSV_FILTER = "CSV (*.csv)"
_PARQUET_FILTER = "Parquet (*.parquet)"

# Qt item-data role carrying the verbatim SQL on a history row / column on a tree leaf.
_SQL_ROLE = int(Qt.UserRole)

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


class QueryPanel(QWidget):
    """Query view — run SQL over the bag's topics via the real ``query()`` backend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status label, query bar, and a vertical QSplitter holding the schema tree, results view, and history; export bar stays fixed-height outside it."""
        super().__init__(parent)

        # The last result table kept for the export buttons. A pyarrow.Table or None;
        # the panel never inspects its contents beyond Pattern-4 rendering.
        self._last_result: pyarrow.Table | None = None

        # The in-flight query worker thread (Pitfall 2 — kept so the GC can't collect a live
        # thread mid-run) and the SQL captured for the in-flight run (appended to history on
        # the result slot). Both None between runs.
        self._query_thread: QThread | None = None
        self._query_worker: BlockingWorker | None = None
        self._pending_sql: str | None = None

        self._status = QLabel("Open a bag to query")

        # Query bar: a SQL line-edit + a Run button (both trigger _run_query).
        self._sql_input = QLineEdit()
        self._sql_input.setPlaceholderText("SELECT … FROM <table>")
        self._run_button = QPushButton("Run")
        query_bar = QHBoxLayout()
        query_bar.addWidget(self._sql_input, 1)
        query_bar.addWidget(self._run_button)

        # Schema/topic tree: one top-level item per table, one child leaf per column.
        self._schema_tree = QTreeWidget()
        self._schema_tree.setHeaderLabels(["schema"])

        # Results model/view (Pattern 4 rendering target, P2): a lazy QAbstractTableModel
        # wrapping the result pyarrow.Table behind a QTableView (no per-cell item allocation).
        self._result_model = _ResultTableModel()
        self._results_view = QTableView()
        self._results_view.setModel(self._result_model)
        self._results_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_view.setEditTriggers(QTableView.NoEditTriggers)

        # Export bar: two buttons, both disabled until a result exists.
        self._export_csv = QPushButton("Export CSV")
        self._export_parquet = QPushButton("Export Parquet")
        self._export_csv.setEnabled(False)
        self._export_parquet.setEnabled(False)
        export_bar = QHBoxLayout()
        export_bar.addWidget(self._export_csv)
        export_bar.addWidget(self._export_parquet)

        # History: successfully-run SQL strings (select to repopulate the input). The
        # section title travels INSIDE the splitter with its list, so wrap both in a small
        # container that becomes one resizable splitter region.
        self._history = QListWidget()
        history_container = QWidget()
        history_layout = QVBoxLayout(history_container)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(QLabel("History"))
        history_layout.addWidget(self._history)

        # P2-layout: the three resizable regions (schema tree, results view, history) live
        # in a vertical QSplitter the user drags to rebalance — instead of fixed stretch
        # factors that crush each other on a short window. Initial proportions mirror the
        # old 1:2 stretch with history smallest (results widest); a region can't be dragged
        # to zero (setChildrenCollapsible(False)).
        regions = QSplitter(Qt.Vertical)
        regions.addWidget(self._schema_tree)
        regions.addWidget(self._results_view)
        regions.addWidget(history_container)
        regions.setChildrenCollapsible(False)
        regions.setSizes([1, 3, 1])

        # Fixed-height controls (status, query bar, export bar) stay OUTSIDE the splitter;
        # the splitter takes the free vertical space (stretch factor 1).
        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addLayout(query_bar)
        layout.addWidget(regions, 1)
        layout.addLayout(export_bar)

        # Signal wiring: Run click + Enter in the input both run the query.
        self._run_button.clicked.connect(self._run_query)
        self._sql_input.returnPressed.connect(self._run_query)
        self._schema_tree.itemClicked.connect(self._on_schema_item_clicked)
        self._history.itemClicked.connect(self._on_history_item_clicked)
        self._export_csv.clicked.connect(lambda: self._export(_CSV_DEFAULT_NAME, _CSV_FILTER))
        self._export_parquet.clicked.connect(
            lambda: self._export(_PARQUET_DEFAULT_NAME, _PARQUET_FILTER)
        )

    @property
    def sql_input(self) -> QLineEdit:
        """The SQL line-edit (tests set/read the query string here)."""
        return self._sql_input

    @property
    def run_button(self) -> QPushButton:
        """The Run button (tests click it to drive a real ``query()``)."""
        return self._run_button

    @property
    def results_table(self) -> QTableView:
        """The results view (tests assert dimensions via ``.model().rowCount()/columnCount()``)."""
        return self._results_view

    @property
    def status_label(self) -> QLabel:
        """The status/teaching line (tests assert the UnknownTableError text here)."""
        return self._status

    @property
    def schema_tree(self) -> QTreeWidget:
        """The schema/topic tree (one top-level item per table, leaves per column)."""
        return self._schema_tree

    @property
    def export_csv_button(self) -> QPushButton:
        """The Export CSV button (disabled until a result exists)."""
        return self._export_csv

    @property
    def export_parquet_button(self) -> QPushButton:
        """The Export Parquet button (disabled until a result exists)."""
        return self._export_parquet

    @property
    def history_list(self) -> QListWidget:
        """The query-history list (select an entry to repopulate the SQL input)."""
        return self._history

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Rebuild the schema tree whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self.refresh_view()

    def _reader(self) -> object | None:
        """The window's single shared open reader (``None`` until a bag opens)."""
        return getattr(self.window(), "reader", None)

    def refresh_view(self) -> None:
        """Populate the schema/topic tree from ``collect_table_schemas`` (D-11).

        Lazily imports the inspect API INSIDE this method (offline invariant) and
        builds one top-level item per ``TableSchema.table_name`` with a leaf per
        ``columns[*].name``. Each leaf carries the VERBATIM column name as item data
        for the click-to-insert handler — the panel constructs no SQL. With no bag
        open the tree is cleared and the status shows the empty-state line.
        """
        self._schema_tree.clear()
        reader = self._reader()
        if reader is None:
            self._status.setText("Open a bag to query")
            return

        # Lazy import (D-08): keep this module's top level PySide6-only.
        from rosbagger_core.inspect import collect_table_schemas

        for schema in collect_table_schemas(reader):
            table_item = QTreeWidgetItem([schema.table_name])
            for col in schema.columns:
                # The leaf carries the verbatim column name; clicking inserts it as-is.
                leaf = QTreeWidgetItem([col.name])
                leaf.setData(0, _SQL_ROLE, col.name)
                table_item.addChild(leaf)
            self._schema_tree.addTopLevelItem(table_item)
        self._schema_tree.expandAll()

    def _on_schema_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Click a schema column leaf → insert its name into the SQL input (D-11).

        Inserts the column name VERBATIM (the leaf's stored data is exactly
        ``col.name`` from the schema) at the SQL input's cursor. The panel performs NO
        SQL construction — it inserts a bare identifier the user composes into a query.
        A top-level (table) item carries no column data and is a no-op.
        """
        col_name = item.data(0, _SQL_ROLE)
        if col_name is None:  # a table (top-level) item — not an insertable column
            return
        self._sql_input.insert(str(col_name))

    def _on_history_item_clicked(self, item: QListWidgetItem) -> None:
        """Selecting a history entry repopulates the SQL input (D-06 re-run)."""
        sql = item.data(_SQL_ROLE)
        if sql is not None:
            self._sql_input.setText(str(sql))

    def _run_query(self) -> None:
        """Forward the SQL string + shared reader to ``query()`` OFF the UI thread (P1).

        Reads the SQL from the input and the window's single shared open reader, then
        lazily imports the ONE query API + the teaching errors INSIDE this handler
        (offline invariant) and runs ``query(sql, reader)`` VERBATIM on a
        :class:`~rosbagger_desktop.workers.BlockingWorker` so a heavy-but-bounded query
        never freezes the window (P1, mirroring the replay panel's drive worker). Run is
        disabled + a running status shown for the flight; both restored on the finished
        slot. The Phase-7 teaching errors are routed through the worker's ``failed`` signal
        as ``str(exc)`` — never a traceback. A second Run while one is in flight is refused.
        """
        sql = self._sql_input.text().strip()

        reader = self._reader()
        if reader is None:
            self._status.setText("Open a bag to query")
            return
        if not sql:
            self._status.setText("Enter a SQL query, then press Enter or Run.")
            return
        # Re-entry guard (T-is6-02): the reader/query is not driven twice — a Run while a
        # worker runs is refused with a teaching status (mirrors the replay drive guard).
        if self._query_thread is not None and self._query_thread.isRunning():
            self._status.setText("A query is already running — wait for it to finish.")
            return

        # Lazy import (D-08): keep this module's top level PySide6-only. The teaching
        # errors are ValueError subclasses whose messages are built in core; the panel
        # only presents them (API-first / thin-face).
        from rosbagger_core.backend.query import query
        from rosbagger_core.errors import (
            UnknownColumnError,
            UnknownTableError,
            UnresolvedTypeError,
        )

        # Capture sql + reader by value; the closure forwards the SQL VERBATIM to query()
        # (the panel still builds no SQL — thin-face intact).
        def work() -> object:
            return query(sql, reader)

        # The teaching errors emit as str(exc) via the worker's failed signal (the teaching
        # contract: str(e), never a traceback); any other Exception emits "Query failed: <exc>".
        worker = BlockingWorker(
            work,
            teaching_errors=(UnknownTableError, UnknownColumnError, UnresolvedTypeError),
            label="Query failed",
        )
        # Remember the in-flight SQL so the result slot can append it to history.
        self._pending_sql = sql
        # Disable Run + show the running status BEFORE starting (P1 responsiveness contract).
        self._run_button.setEnabled(False)
        self._status.setText("Running…")
        # Keep BOTH the thread and worker refs on the panel (Pitfall 2): the worker is
        # moved onto the thread but not Qt-reparented, so a discarded Python ref lets the GC
        # collect it before its queued `run` slot fires (a fast query never starts) — the
        # replay panel's blocking run() masked this by keeping the worker busy. Hold the
        # worker until _on_query_finished clears it.
        self._query_thread, self._query_worker = run_on_thread(
            self,
            worker,
            on_result=self._on_query_result,
            on_failed=self._on_query_failed,
            on_finished=self._on_query_finished,
        )

    def _on_query_result(self, result: object) -> None:
        """Render the worker's result on the UI thread: model, history, export, status.

        Runs on the UI thread (worker ``result`` slot). Keeps ``_last_result`` for export,
        populates the lazy model, appends the in-flight SQL to history, enables both export
        buttons, and reports the row/column count.
        """
        self._last_result = result  # type: ignore[assignment]  # always a pyarrow.Table here
        self._fill_results(result)  # type: ignore[arg-type]
        if self._pending_sql is not None:
            self._append_history(self._pending_sql)
        self._pending_sql = None
        # A result now exists — enable export (D-06).
        self._export_csv.setEnabled(True)
        self._export_parquet.setEnabled(True)
        self._status.setText(
            f"{result.num_rows} row(s) · {len(result.column_names)} column(s)"  # type: ignore[attr-defined]
        )

    def _on_query_failed(self, message: str) -> None:
        """Render the worker's teaching message VERBATIM into the status label (T-is6-01).

        The worker already emitted ``str(exc)`` for the known teaching errors (or
        ``"Query failed: <exc>"`` otherwise) — never a traceback. Export state is untouched.
        """
        self._pending_sql = None
        self._status.setText(message)

    def _on_query_finished(self) -> None:
        """Clear the thread ref (CR-01) + re-enable Run on every outcome (UI thread).

        ``run_on_thread`` wires ``thread.finished → thread.deleteLater``, so once the worker
        finishes the underlying C++ ``QThread`` is destroyed; keeping the stale wrapper would
        make a later ``stop_thread``/re-entry probe touch a deleted object. Runs on result OR
        failure (mirrors the replay panel's ``_on_drive_finished``).
        """
        self._query_thread = None
        self._query_worker = None
        self._run_button.setEnabled(True)

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Stop the in-flight query thread before teardown (Pitfall 2)."""
        stop_thread(self._query_thread)
        super().closeEvent(event)

    def _fill_results(self, table: pyarrow.Table) -> None:
        """Hand the result ``pyarrow.Table`` to the lazy model (16-RESEARCH Pattern 4, P2).

        ``set_table`` wraps the swap in begin/endResetModel so the ``QTableView`` refreshes;
        the model renders each cell lazily via ``str()`` on demand (the temporal-safe rule —
        no up-front ``to_pylist()`` materialization, no per-cell ``QTableWidgetItem``).
        """
        self._result_model.set_table(table)

    def _append_history(self, sql: str) -> None:
        """Append a successfully-run SQL to the history list (D-06).

        Each entry stores the raw SQL on the user role so selecting it repopulates the
        SQL input (re-run by pressing Run again). The panel stores the string verbatim
        — it builds no SQL.
        """
        item = QListWidgetItem(sql)
        item.setData(_SQL_ROLE, sql)
        self._history.addItem(item)

    def _export(self, default_name: str, filter_: str) -> None:
        """Write the last result ``pyarrow.Table`` to a USER-CHOSEN path via ``write_table`` (D-11).

        WR-03: open a ``QFileDialog.getSaveFileName`` so the user controls the destination (and
        gets the native overwrite confirmation) rather than silently overwriting a fixed
        CWD-relative file whose location depends on where the GUI was launched. ``default_name``
        pre-fills the file name and ``filter_`` constrains the suffix; the FORMAT is still chosen
        by ``write_table`` from the path EXTENSION (the one LIST/STRUCT-safe writer) — the panel
        builds no serialization/format string. A cancelled dialog is a clean no-op. Any error is
        surfaced to the status label rather than crashing the GUI.
        """
        if self._last_result is None:  # export disabled until a result exists
            self._status.setText("Run a query first, then export.")
            return

        path, _selected = QFileDialog.getSaveFileName(
            self, "Export query result", default_name, filter_
        )
        if not path:  # the user cancelled the save dialog
            return

        # Lazy import (D-08): keep this module's top level PySide6-only.
        from rosbagger_core.output.export import write_table

        try:
            write_table(self._last_result, path)
        except Exception as exc:  # noqa: BLE001 - present as teaching text, never crash the GUI
            # WR-05: write_table teaches on a bad extension/path (ValueError/OSError), but
            # serializing a pyarrow.Table can also raise Arrow's own exceptions
            # (ArrowInvalid / ArrowNotImplementedError for an unwritable column type) which are
            # NOT ValueError/OSError. Broaden to match the docstring's "any error is surfaced to
            # the status label rather than crashing the GUI" promise (the worker-style policy).
            self._status.setText(f"Export failed: {exc}")
            return
        self._status.setText(f"Exported {self._last_result.num_rows} row(s) → {path}")
