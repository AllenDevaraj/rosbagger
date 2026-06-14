"""Query panel (offline, D-06) — a thin face over ``rosbagger_core.backend.query``.

OFFLINE PANEL (D-03): always enabled. This is the richest offline panel and a pure
FACE: it collects a SQL *string* and forwards it VERBATIM to the ONE query API —
:func:`rosbagger_core.backend.query.query` — against the App's single shared open
reader, then maps the returned ``pyarrow.Table`` into the ``results`` DataTable
(14-RESEARCH Pattern 4). It contains ZERO SQL/format/selection logic: it never builds
SQL, never picks a serialization format, and never analyses anything — the string is
the user's, the rows are core's (the thin-face rule).

It also keeps a query HISTORY (D-06): every successfully-run SQL is appended to a
``history`` list; selecting an entry repopulates ``sql-input`` so the user re-runs by
pressing Run again. Bad queries raise the Phase-7 teaching errors
(``UnknownTableError`` / ``UnknownColumnError`` / ``UnresolvedTypeError``, all
``ValueError`` subclasses carrying messages built in core); the panel CATCHES them and
renders ``str(e)`` into the ``query-status`` line — the GUI PRESENTS the teaching
message, it does not BUILD it (API-first).

A schema/topic ``Tree`` browser (``schema-tree``) sourced from
:func:`rosbagger_core.inspect.collect_table_schemas` (D-06) gives one branch per
table with a leaf per column; clicking a column leaf inserts that column name —
VERBATIM from ``col.name``, the panel constructs NO SQL — into ``sql-input`` at the
cursor. Two export ``Button``s (``export-csv`` / ``export-parquet``) write the LAST
result ``pyarrow.Table`` via :func:`rosbagger_core.output.export.write_table` (the one
LIST/STRUCT-safe writer; the serialization is chosen by the file EXTENSION, never by
the panel — the panel only supplies a path with the matching suffix). Export is
disabled until a result exists.

OFFLINE-IMPORT INVARIANT (D-03): every ``rosbagger_core`` import lives INSIDE a method
body (the run handler / ``refresh_view`` / the export handler), never at module top —
so this module's top level stays textual-only and importing it pulls no ``rosbags`` /
heavy stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Tree,
)

# Default export destinations (CWD). The panel collects a PATH only; the FORMAT is
# chosen by write_table from the extension — the panel never picks a format itself.
_CSV_PATH = "query_result.csv"
_PARQUET_PATH = "query_result.parquet"

# Max rows rendered into the DataTable (F6). The full result is kept on `_last_result` for
# export; the on-screen table is bounded so a `SELECT *` over a 500k-row topic does not
# materialize every cell and freeze the event loop. Export still writes ALL rows.
_MAX_DISPLAY_ROWS = 1000

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow


class QueryPanel(Vertical):
    """Query view — run SQL over the bag's topics via the real query() backend."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # The last result table kept for the export buttons (Task 2). A pyarrow.Table
        # or None; the panel never inspects its contents beyond Pattern-4 rendering.
        self._last_result: pyarrow.Table | None = None

    def compose(self) -> ComposeResult:
        """Schema Tree + SQL input/Run, results DataTable, status, history, export."""
        yield Static("Open a bag to query", id="query-status")
        with Horizontal(id="query-bar"):
            yield Input(placeholder="SELECT … FROM <table>", id="sql-input")
            yield Button("Run", id="run-query", variant="primary")
        yield Tree("schema", id="schema-tree")
        yield DataTable(id="results")
        with Horizontal(id="export-bar"):
            yield Button("Export CSV", id="export-csv", disabled=True)
            yield Button("Export Parquet", id="export-parquet", disabled=True)
        yield Label("History", id="history-label")
        yield ListView(id="history")

    def on_mount(self) -> None:
        """Build the schema Tree from the shared reader once the widget tree exists."""
        self.refresh_view()

    def on_show(self) -> None:
        """Rebuild the schema Tree whenever the panel becomes the active view."""
        self.refresh_view()

    def refresh_view(self) -> None:
        """Populate the schema/topic Tree from ``collect_table_schemas`` (D-06).

        Lazily imports the inspect API INSIDE this method (offline invariant) and
        builds one Tree branch per ``TableSchema.table_name`` with a leaf per
        ``columns[*].name``. Each leaf carries the VERBATIM column name as node data
        for the click-to-insert handler — the panel constructs no SQL. With no bag
        open the Tree is reset to its empty root and the status shows the empty-state.
        """
        tree = self.query_one("#schema-tree", Tree)
        tree.clear()
        reader = getattr(self.app, "reader", None)
        if reader is None:
            self.query_one("#query-status", Static).update("Open a bag to query")
            return

        # Lazy import (D-03): keep this module's top level textual-only.
        from rosbagger_core.inspect import collect_table_schemas

        for schema in collect_table_schemas(reader):
            branch = tree.root.add(schema.table_name, expand=False)
            for col in schema.columns:
                # data = the verbatim column name; clicking inserts it as-is (no SQL).
                branch.add_leaf(col.name, data=col.name)
        tree.root.expand()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Click a schema column leaf → insert its name into ``sql-input`` (D-06).

        Inserts the column name VERBATIM (the leaf's ``node.data`` is exactly
        ``col.name`` from the schema) at the SQL input's cursor. The panel performs
        NO SQL construction — it inserts a bare identifier string the user then
        composes into their own query.
        """
        col_name = event.node.data
        if col_name is None:  # a branch (table) node carries no column data
            return
        self.query_one("#sql-input", Input).insert_text_at_cursor(str(col_name))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the SQL input runs the query (the SC3 path: press 'enter')."""
        if event.input.id == "sql-input":
            self._run_query()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Run the query or export the last result, by button id."""
        if event.button.id == "run-query":
            self._run_query()
        elif event.button.id == "export-csv":
            self._export(_CSV_PATH)
        elif event.button.id == "export-parquet":
            self._export(_PARQUET_PATH)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Selecting a history entry repopulates the SQL input (D-06 re-run)."""
        if event.list_view.id != "history":
            return
        sql = getattr(event.item, "_sql", None)
        if sql is not None:
            self.query_one("#sql-input", Input).value = sql

    def _run_query(self) -> None:
        """Forward the SQL string + shared reader to query() and render the result.

        Reads the SQL from ``sql-input`` and the App's single shared open reader,
        lazily imports the ONE query API INSIDE this handler (offline invariant), and
        calls ``query(sql, reader)`` VERBATIM. Fills the ``results`` DataTable via the
        Pattern-4 mapping and appends the SQL to ``history``. The Phase-7 teaching
        errors are caught and rendered into ``query-status`` — never a traceback. The
        result table is kept on ``_last_result`` for the export buttons.
        """
        status = self.query_one("#query-status", Static)
        sql = self.query_one("#sql-input", Input).value.strip()

        reader = getattr(self.app, "reader", None)
        if reader is None:
            status.update("Open a bag to query")
            return
        if not sql:
            status.update("Enter a SQL query, then press Enter or Run.")
            return

        # Lazy import (D-03): keep this module's top level textual-only. The teaching
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
        except (UnknownTableError, UnknownColumnError, UnresolvedTypeError) as e:
            # The message CONTENT is built in core (thin-face): present str(e), no crash.
            status.update(str(e))
            return

        self._last_result = result
        self._fill_results(result)
        self._append_history(sql)
        # A result now exists — enable export (D-06).
        self.query_one("#export-csv", Button).disabled = False
        self.query_one("#export-parquet", Button).disabled = False
        # Note truncation when the on-screen table is capped (F6); export still writes all rows.
        shown = min(result.num_rows, _MAX_DISPLAY_ROWS)
        capped = f" · showing first {shown}" if result.num_rows > _MAX_DISPLAY_ROWS else ""
        status.update(
            f"{result.num_rows} row(s) · {len(result.column_names)} column(s){capped}"
        )

    def _fill_results(self, table: pyarrow.Table) -> None:
        """Map a ``pyarrow.Table`` into the ``results`` DataTable (14-RESEARCH Pattern 4).

        Renders via the core temporal-safe coercer ``rows_for_display`` (SW2): the previous
        ``table.to_pylist()`` RAISED ``ValueError`` on the always-present ``timestamp[ns]``
        ``t``/``stamp`` columns when pandas is absent (it is not a GUI dependency) — and that
        crash was OUTSIDE the run handler's try/except, so it bubbled out and broke the query
        action. ``rows_for_display`` converts temporal columns the safe way and CAPS the row
        count at ``_MAX_DISPLAY_ROWS`` (F6) so a ``SELECT *`` over a huge topic does not
        materialize every cell into the DataTable. Export still writes ALL rows (``_last_result``).
        """
        from rosbagger_core.output.render import rows_for_display

        dt = self.query_one("#results", DataTable)
        dt.clear(columns=True)
        if not table.column_names:
            return
        names, rows = rows_for_display(table, max_rows=_MAX_DISPLAY_ROWS)
        dt.add_columns(*names)
        for row in rows:
            dt.add_row(*row)

    def _append_history(self, sql: str) -> None:
        """Append a successfully-run SQL to the ``history`` ListView (D-06).

        Each entry carries the raw SQL on a ``_sql`` attribute so selecting it
        repopulates ``sql-input`` (re-run by pressing Run again). The panel stores the
        string verbatim — it builds no SQL.
        """
        history = self.query_one("#history", ListView)
        item = ListItem(Label(sql))
        item._sql = sql  # noqa: SLF001 - carry the raw SQL for the re-run select
        history.append(item)

    def _export(self, path: str) -> None:
        """Write the last result ``pyarrow.Table`` to ``path`` via ``write_table`` (D-06).

        Lazily imports the ONE export API INSIDE this handler (offline invariant) and
        calls ``write_table(last_result, path)`` VERBATIM. The FORMAT is chosen by
        ``write_table`` from the path EXTENSION (the one LIST/STRUCT-safe writer + the
        T-06-01 quote-escape live there) — the panel only supplies a path with the
        matching suffix; it builds no serialization/format string. Any error is
        surfaced to ``query-status`` rather than crashing the TUI.
        """
        status = self.query_one("#query-status", Static)
        if self._last_result is None:  # export disabled until a result exists
            status.update("Run a query first, then export.")
            return

        # Lazy import (D-03): keep this module's top level textual-only.
        from rosbagger_core.output.export import write_table

        try:
            write_table(self._last_result, path)
        except (ValueError, OSError) as e:  # write_table teaches on a bad extension/path
            status.update(str(e))
            return
        status.update(f"Exported {self._last_result.num_rows} row(s) → {path}")
