"""TF panel (offline, D-07) — a thin face over ``rosbagger_core.tf``.

OFFLINE PANEL (D-03): always enabled. This panel is a pure RENDERER: it reads the
App's single shared open reader and calls EXACTLY one ``rosbagger_core.tf`` API —
:func:`collect_tf_report` — then renders the parent→child edge summary and the
per-edge gap timeline into two DataTables. It contains ZERO analysis logic; every
edge, rate, and gap comes from core. Display formatting (human-readable gap/interval
durations, em-dash placeholders) mirrors the ``bagq tf`` renderer and adds no
computation.

NoTransformsError (a ``ValueError`` subclass raised by the core API when the bag has
neither ``/tf`` nor ``/tf_static``) is caught and rendered as a teaching ``Static`` —
the panel never crashes on a bag with no transforms (threat T-14-03-02).

OFFLINE-IMPORT INVARIANT (D-03): the ``rosbagger_core.tf`` / ``rosbagger_core.errors``
imports live INSIDE :meth:`refresh_view` (a method body), never at module top — so
this module's top level stays textual-only and importing it pulls no ``rosbags``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

_EM_DASH = "—"


def _human_dur(ns: int) -> str:
    """Format a nanosecond duration human-readably — presentation only.

    Mirrors the ``bagq tf`` renderer's ``_human_dur``; the core API keeps every
    duration as raw integer nanoseconds. Sub-second values print as milliseconds
    (a whole number of ms drops the decimal, e.g. ``800ms``); a second or more
    prints seconds with two decimals (e.g. ``12.40s``).
    """
    ms = ns / 1e6
    if ms < 1000.0:
        return f"{int(ms)}ms" if ms == int(ms) else f"{ms:.1f}ms"
    return f"{ns / 1e9:.2f}s"


class TfPanel(Widget):
    """TF view — parent→child edge summary + per-edge gap timeline (offline)."""

    def compose(self) -> ComposeResult:
        """A status line + the per-edge summary and gap-timeline DataTables."""
        yield Static("Open a bag with /tf to analyze", id="tf-status")
        yield DataTable(id="tf-edges")
        yield DataTable(id="tf-gaps")

    def on_mount(self) -> None:
        """Populate from the shared reader once the widget tree exists."""
        self.refresh_view()

    def on_show(self) -> None:
        """Re-read whenever the panel becomes the active ContentSwitcher view."""
        self.refresh_view()

    def refresh_view(self) -> None:
        """Read the App's shared reader and fill both DataTables from core output.

        Lazily imports :func:`collect_tf_report` and ``NoTransformsError`` INSIDE the
        method (offline invariant), calls the API against the shared reader, and
        renders the edge summary + gap timeline. A bag with no ``/tf``/``/tf_static``
        raises ``NoTransformsError`` — caught and shown as a teaching status line, not
        a crash (T-14-03-02). With no bag open it shows the empty-state line.
        """
        status = self.query_one("#tf-status", Static)
        edges_table = self.query_one("#tf-edges", DataTable)
        gaps_table = self.query_one("#tf-gaps", DataTable)

        reader = getattr(self.app, "reader", None)
        if reader is None:
            status.update("Open a bag with /tf to analyze")
            edges_table.clear(columns=True)
            gaps_table.clear(columns=True)
            return

        # Lazy import (D-03): keep this module's top level textual-only.
        from rosbagger_core.errors import NoTransformsError
        from rosbagger_core.tf import collect_tf_report

        try:
            report = collect_tf_report(reader)
        except NoTransformsError as exc:
            # Teaching path (T-14-03-02): render the core message, do not crash.
            status.update(str(exc))
            edges_table.clear(columns=True)
            gaps_table.clear(columns=True)
            return

        # Whole-bag span for the header + per-edge rate (presentation only).
        n_static = sum(1 for e in report.edges if e.static)
        n_dynamic = len(report.edges) - n_static
        span_s: float | None = None
        if report.start_ns is not None and report.end_ns is not None:
            raw = (report.end_ns - report.start_ns) / 1e9
            span_s = raw if raw > 0 else None
        span_clause = f" over {span_s:.2f}s" if span_s else ""
        status.update(f"{n_dynamic} dynamic edges, {n_static} static edges{span_clause}")

        # Per-edge summary: one row per TfReport.edges entry (mirror bagq tf columns).
        edges_table.clear(columns=True)
        edges_table.add_columns("parent", "child", "kind", "count", "rate(Hz)", "max gap", "gaps")
        for e in report.edges:
            kind = "static" if e.static else "dynamic"
            # Rate is meaningful only for a multi-sample dynamic edge over a span.
            if e.static or e.samples < 2 or not span_s or span_s <= 0:
                rate = _EM_DASH
            else:
                rate = f"{e.samples / span_s:.1f}"
            max_gap = _human_dur(e.max_gap_ns) if e.max_gap_ns is not None else _EM_DASH
            edges_table.add_row(
                e.parent, e.child, kind, str(e.samples), rate, max_gap, str(e.gap_count)
            )

        # Gap timeline: one row per TfReport.gaps entry; empty -> a status note.
        gaps_table.clear(columns=True)
        gaps_table.add_columns("parent", "child", "gap", "at (bag t)", "at (abs ns)")
        if not report.gaps:
            gaps_table.add_row("no gaps detected", "", "", "", "")
        else:
            for g in report.gaps:
                gaps_table.add_row(
                    g.parent,
                    g.child,
                    _human_dur(g.gap_ns),
                    f"t={g.at_rel_ns / 1e9:.2f}s",
                    str(g.at_ns),
                )
