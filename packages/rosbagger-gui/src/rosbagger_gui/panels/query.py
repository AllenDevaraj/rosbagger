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

OFFLINE-IMPORT INVARIANT (D-03): the ``rosbagger_core`` import lives INSIDE the run
handler (a method body), never at module top — so this module's top level stays
textual-only and importing it pulls no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, ListItem, ListView, Static

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
        """The SQL input + Run button, a results DataTable, a status line, and history."""
        yield Static("Open a bag to query", id="query-status")
        with Horizontal(id="query-bar"):
            yield Input(placeholder="SELECT … FROM <table>", id="sql-input")
            yield Button("Run", id="run-query", variant="primary")
        yield DataTable(id="results")
        yield Label("History", id="history-label")
        yield ListView(id="history")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the SQL input runs the query (the SC3 path: press 'enter')."""
        if event.input.id == "sql-input":
            self._run_query()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """The Run button runs the query."""
        if event.button.id == "run-query":
            self._run_query()

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
        status.update(f"{result.num_rows} row(s) · {len(result.column_names)} column(s)")

    def _fill_results(self, table: pyarrow.Table) -> None:
        """Map a ``pyarrow.Table`` into the ``results`` DataTable (14-RESEARCH Pattern 4).

        ``query()`` already bounds the result (the user's SQL + the QURY-07 heavy-blob
        gating), so ``to_pylist()`` is safe — this never materializes an unbounded raw
        stream. Temporal/list cell values are ``str()``-rendered for display (the
        ns-timestamp → datetime crash class is sidestepped; 14-RESEARCH temporal note).
        """
        dt = self.query_one("#results", DataTable)
        dt.clear(columns=True)
        if not table.column_names:
            return
        dt.add_columns(*table.column_names)
        for row in table.to_pylist():
            dt.add_row(*(str(row[c]) for c in table.column_names))

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
