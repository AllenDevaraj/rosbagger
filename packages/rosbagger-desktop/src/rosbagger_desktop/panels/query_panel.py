"""Query panel (offline, D-11) — a thin Qt face over ``rosbagger_core.backend.query``.

OFFLINE PANEL (D-08): always enabled. This is the richest offline panel and a pure
FACE: it collects a SQL *string* and forwards it VERBATIM to the ONE query API —
:func:`rosbagger_core.backend.query.query` — against the window's single shared open
reader, then maps the returned ``pyarrow.Table`` into the ``results`` ``QTableWidget``
(16-RESEARCH Pattern 4). It contains ZERO SQL/format/selection logic: it never builds
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

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): every ``rosbagger_core`` import lives
INSIDE a method body (the run handler / ``refresh_view`` / the export handler), never
at module top — so this module's top level stays PySide6-only and importing it pulls
no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

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


class QueryPanel(QWidget):
    """Query view — run SQL over the bag's topics via the real ``query()`` backend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status label, query bar, schema tree, results table, export bar, history."""
        super().__init__(parent)

        # The last result table kept for the export buttons. A pyarrow.Table or None;
        # the panel never inspects its contents beyond Pattern-4 rendering.
        self._last_result: pyarrow.Table | None = None

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

        # Results table (Pattern 4 rendering target).
        self._results_table = QTableWidget(0, 0)
        self._results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Export bar: two buttons, both disabled until a result exists.
        self._export_csv = QPushButton("Export CSV")
        self._export_parquet = QPushButton("Export Parquet")
        self._export_csv.setEnabled(False)
        self._export_parquet.setEnabled(False)
        export_bar = QHBoxLayout()
        export_bar.addWidget(self._export_csv)
        export_bar.addWidget(self._export_parquet)

        # History: successfully-run SQL strings (select to repopulate the input).
        self._history = QListWidget()

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addLayout(query_bar)
        layout.addWidget(self._schema_tree, 1)
        layout.addWidget(self._results_table, 2)
        layout.addLayout(export_bar)
        layout.addWidget(QLabel("History"))
        layout.addWidget(self._history)

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
    def results_table(self) -> QTableWidget:
        """The results table (tests assert ``rowCount()``/``columnCount()`` here)."""
        return self._results_table

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
        """Forward the SQL string + shared reader to ``query()`` and render the result.

        Reads the SQL from the input and the window's single shared open reader,
        lazily imports the ONE query API + the teaching errors INSIDE this handler
        (offline invariant), and calls ``query(sql, reader)`` VERBATIM. Fills the
        results table via the Pattern-4 mapping and appends the SQL to history. The
        Phase-7 teaching errors are caught and rendered into the status label — never a
        traceback. The result table is kept on ``_last_result`` for the export buttons.
        """
        sql = self._sql_input.text().strip()

        reader = self._reader()
        if reader is None:
            self._status.setText("Open a bag to query")
            return
        if not sql:
            self._status.setText("Enter a SQL query, then press Enter or Run.")
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

        try:
            result = query(sql, reader)
        except (UnknownTableError, UnknownColumnError, UnresolvedTypeError) as exc:
            # The message CONTENT is built in core (thin-face): present str(e), no crash.
            self._status.setText(str(exc))
            return

        self._last_result = result
        self._fill_results(result)
        self._append_history(sql)
        # A result now exists — enable export (D-06).
        self._export_csv.setEnabled(True)
        self._export_parquet.setEnabled(True)
        self._status.setText(f"{result.num_rows} row(s) · {len(result.column_names)} column(s)")

    def _fill_results(self, table: pyarrow.Table) -> None:
        """Map a ``pyarrow.Table`` into the results table (16-RESEARCH Pattern 4).

        ``query()`` already bounds the result (the user's SQL + the QURY-07 heavy-blob
        gating), so ``to_pylist()`` is safe — this never materializes an unbounded raw
        stream. Each cell value is ``str()``-rendered for display (the ns-timestamp →
        datetime crash class is sidestepped; the temporal-safe rule).
        """
        column_names = list(table.column_names)
        self._results_table.clear()
        self._results_table.setColumnCount(len(column_names))
        self._results_table.setHorizontalHeaderLabels(column_names)
        rows = table.to_pylist()
        self._results_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, name in enumerate(column_names):
                self._results_table.setItem(r, c, QTableWidgetItem(str(row[name])))

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
        except (ValueError, OSError) as exc:  # write_table teaches on a bad extension/path
            self._status.setText(str(exc))
            return
        self._status.setText(f"Exported {self._last_result.num_rows} row(s) → {path}")
