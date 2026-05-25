"""TF panel (offline, D-12) — a thin Qt face over ``rosbagger_core.tf``.

OFFLINE PANEL (D-08): always enabled. A pure RENDERER — it reads the window's single
shared open reader and calls EXACTLY one ``rosbagger_core.tf`` API,
:func:`collect_tf_report`, then renders the parent→child edge summary and the per-edge
gap timeline into two ``QTableWidget``s. It contains ZERO analysis logic; every edge,
rate, and gap comes from core. Display formatting (human-readable durations, em-dash
placeholders) mirrors the TUI tf panel and adds no computation.

``NoTransformsError`` (a ``ValueError`` subclass raised by the core API when the bag has
neither ``/tf`` nor ``/tf_static``) is caught and rendered as a teaching status line —
the panel never crashes on a bag with no transforms (T-16-TF).

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): the ``rosbagger_core.tf`` /
``rosbagger_core.errors`` imports live INSIDE :meth:`refresh_view` (a method body),
never at module top — so this module's top level stays PySide6-only.
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

_EM_DASH = "—"


def _human_dur(ns: int) -> str:
    """Format a nanosecond duration human-readably — presentation only.

    Mirrors the TUI tf panel's ``_human_dur``; the core API keeps every duration as
    raw integer nanoseconds. Sub-second values print as milliseconds (a whole number
    of ms drops the decimal, e.g. ``800ms``); a second or more prints seconds with two
    decimals (e.g. ``12.40s``).
    """
    ms = ns / 1e6
    if ms < 1000.0:
        return f"{int(ms)}ms" if ms == int(ms) else f"{ms:.1f}ms"
    return f"{ns / 1e9:.2f}s"


class TfPanel(QWidget):
    """TF view — parent→child edge summary + per-edge gap timeline (offline)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status label + the edges and gaps ``QTableWidget``s."""
        super().__init__(parent)

        self._status = QLabel("Open a bag with /tf to analyze")

        self._edges_table = QTableWidget(0, 7)
        self._edges_table.setHorizontalHeaderLabels(
            ["parent", "child", "kind", "count", "rate(Hz)", "max gap", "gaps"]
        )
        self._edges_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._edges_table.setEditTriggers(QTableWidget.NoEditTriggers)

        self._gaps_table = QTableWidget(0, 5)
        self._gaps_table.setHorizontalHeaderLabels(
            ["parent", "child", "gap", "at (bag t)", "at (abs ns)"]
        )
        self._gaps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._gaps_table.setEditTriggers(QTableWidget.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._edges_table, 1)
        layout.addWidget(self._gaps_table, 1)

    @property
    def status_label(self) -> QLabel:
        """The teaching/status line (tests assert the NoTransformsError text here)."""
        return self._status

    @property
    def edges_table(self) -> QTableWidget:
        """The per-edge summary table (tests assert ``rowCount() > 0`` here)."""
        return self._edges_table

    @property
    def gaps_table(self) -> QTableWidget:
        """The per-edge gap-timeline table."""
        return self._gaps_table

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Re-read whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self.refresh_view()

    def _reader(self) -> object | None:
        """The window's single shared open reader (``None`` until a bag opens)."""
        return getattr(self.window(), "reader", None)

    def refresh_view(self) -> None:
        """Read the window's shared reader and fill both tables from core output.

        Lazily imports :func:`collect_tf_report` and ``NoTransformsError`` INSIDE the
        method (offline invariant), calls the API against the shared reader, and renders
        the edge summary + gap timeline. A bag with no ``/tf``/``/tf_static`` raises
        ``NoTransformsError`` — caught and shown as a teaching status line, not a crash
        (T-16-TF). With no bag open it shows the empty-state line.
        """
        reader = self._reader()
        if reader is None:
            self._status.setText("Open a bag with /tf to analyze")
            self._edges_table.setRowCount(0)
            self._gaps_table.setRowCount(0)
            return

        # Lazy import (D-08): keep this module's top level PySide6-only.
        from rosbagger_core.errors import NoTransformsError
        from rosbagger_core.tf import collect_tf_report

        try:
            report = collect_tf_report(reader)
        except NoTransformsError as exc:
            # Teaching path (T-16-TF): render the core message, do not crash.
            self._status.setText(str(exc))
            self._edges_table.setRowCount(0)
            self._gaps_table.setRowCount(0)
            return

        # Whole-bag span for the header + per-edge rate (presentation only).
        n_static = sum(1 for e in report.edges if e.static)
        n_dynamic = len(report.edges) - n_static
        span_s: float | None = None
        if report.start_ns is not None and report.end_ns is not None:
            raw = (report.end_ns - report.start_ns) / 1e9
            span_s = raw if raw > 0 else None
        span_clause = f" over {span_s:.2f}s" if span_s else ""
        self._status.setText(f"{n_dynamic} dynamic edges, {n_static} static edges{span_clause}")

        # Per-edge summary: one row per TfReport.edges entry (mirror TUI tf columns).
        self._edges_table.setRowCount(len(report.edges))
        for row, e in enumerate(report.edges):
            kind = "static" if e.static else "dynamic"
            # Rate is meaningful only for a multi-sample dynamic edge over a span.
            if e.static or e.samples < 2 or not span_s or span_s <= 0:
                rate = _EM_DASH
            else:
                rate = f"{e.samples / span_s:.1f}"
            max_gap = _human_dur(e.max_gap_ns) if e.max_gap_ns is not None else _EM_DASH
            self._edges_table.setItem(row, 0, QTableWidgetItem(str(e.parent)))
            self._edges_table.setItem(row, 1, QTableWidgetItem(str(e.child)))
            self._edges_table.setItem(row, 2, QTableWidgetItem(str(kind)))
            self._edges_table.setItem(row, 3, QTableWidgetItem(str(e.samples)))
            self._edges_table.setItem(row, 4, QTableWidgetItem(str(rate)))
            self._edges_table.setItem(row, 5, QTableWidgetItem(str(max_gap)))
            self._edges_table.setItem(row, 6, QTableWidgetItem(str(e.gap_count)))

        # Gap timeline: one row per TfReport.gaps entry; empty -> a status note row.
        if not report.gaps:
            self._gaps_table.setRowCount(1)
            self._gaps_table.setItem(0, 0, QTableWidgetItem("no gaps detected"))
            for col in range(1, 5):
                self._gaps_table.setItem(0, col, QTableWidgetItem(""))
        else:
            self._gaps_table.setRowCount(len(report.gaps))
            for row, g in enumerate(report.gaps):
                self._gaps_table.setItem(row, 0, QTableWidgetItem(str(g.parent)))
                self._gaps_table.setItem(row, 1, QTableWidgetItem(str(g.child)))
                self._gaps_table.setItem(row, 2, QTableWidgetItem(str(_human_dur(g.gap_ns))))
                self._gaps_table.setItem(row, 3, QTableWidgetItem(f"t={g.at_rel_ns / 1e9:.2f}s"))
                self._gaps_table.setItem(row, 4, QTableWidgetItem(str(g.at_ns)))
