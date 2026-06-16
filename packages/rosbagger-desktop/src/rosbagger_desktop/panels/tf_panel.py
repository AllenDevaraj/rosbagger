"""TF panel (offline, D-12) — a thin Qt face over ``rosbagger_core.tf``.

OFFLINE PANEL (D-08): always enabled. A pure RENDERER — it reads the window's single
shared open reader and calls EXACTLY one ``rosbagger_core.tf`` API,
:func:`collect_tf_report`, then renders the parent→child edge summary and the per-edge
gap timeline into two ``QTableView``s. It contains ZERO analysis logic; every edge,
rate, and gap comes from core. Display formatting (human-readable durations, em-dash
placeholders) mirrors the TUI tf panel and adds no computation.

``NoTransformsError`` (a ``ValueError`` subclass raised by the core API when the bag has
neither ``/tf`` nor ``/tf_static``) is routed through the worker's ``failed`` slot as
``str(exc)`` and rendered VERBATIM on the accessible status line — the panel never crashes
on a bag with no transforms (T-16-TF / THIN-FACE: core owns the message, D-09).

ENGINEERING PARITY (17-02 / D-02): brought up to the query-panel bar. The two tabular
surfaces render via :class:`~rosbagger_desktop.widgets.RowsTableModel` + ``QTableView``
(not per-cell ``QTableWidgetItem``), the blocking ``collect_tf_report`` call runs OFF the UI
thread on a :class:`~rosbagger_desktop.workers.BlockingWorker` (T-17-04), and the status
routes through the shared accessible :func:`~rosbagger_desktop.widgets.set_status` helper.

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): the ``rosbagger_core.tf`` /
``rosbagger_core.errors`` imports live INSIDE the worker ``work()`` body (a method body),
never at module top — so this module's top level stays PySide6-only.
"""

from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..widgets import RowsTableModel, set_status
from ..workers import BlockingWorker, run_on_thread, stop_thread

_EM_DASH = "—"

_EDGES_HEADERS = ["parent", "child", "kind", "count", "rate(Hz)", "max gap", "gaps"]
_GAPS_HEADERS = ["parent", "child", "gap", "at (bag t)", "at (abs ns)"]


def _human_dur(ns: int) -> str:
    """Format a nanosecond duration human-readably — delegates to the shared core formatter (R2).

    Was byte-identical in three faces; now the single ``rosbagger_core.format.human_dur``.
    Imported INSIDE the function so the module top stays PySide6-only (offline invariant).
    """
    from rosbagger_core.format import human_dur

    return human_dur(ns)


class TfPanel(QWidget):
    """TF view — parent→child edge summary + per-edge gap timeline (offline)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status label + the edges and gaps ``QTableView``s (D-02)."""
        super().__init__(parent)

        # The in-flight refresh worker thread (Pitfall 2) + worker. Both None between runs.
        self._refresh_thread: QThread | None = None
        self._refresh_worker: BlockingWorker | None = None
        # Bumped per refresh; a superseded worker's late signal (older gen) is ignored so it
        # can neither clobber the current worker's refs nor render a stale report (refresh_view).
        self._refresh_gen = 0
        # F7-style reader-identity cache: the reader the last report was computed from.
        self._analyzed_reader: object | None = None

        # Status line as an accessibly-named region (D-02); a stable objectName lets the
        # shared status helper restore it after an error toggle.
        self._status = QLabel("Open a bag with /tf to analyze")
        self._status.setObjectName("tf_status")
        self._status.setAccessibleName("TF status")
        self._status.setAccessibleDescription("Open a bag with /tf to analyze")
        # Section-heading affordance (17-03 / D-03): keyed to the theme QSS heading style — no
        # inline font/color literal in the panel.
        self._status.setProperty("heading", True)

        # Model/view rendering target (D-02): RowsTableModel behind a QTableView.
        self._edges_model = RowsTableModel(_EDGES_HEADERS)
        self._edges_view = QTableView()
        self._edges_view.setModel(self._edges_model)
        self._edges_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._edges_view.setEditTriggers(QTableView.NoEditTriggers)

        self._gaps_model = RowsTableModel(_GAPS_HEADERS)
        self._gaps_view = QTableView()
        self._gaps_view.setModel(self._gaps_model)
        self._gaps_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._gaps_view.setEditTriggers(QTableView.NoEditTriggers)

        layout = QVBoxLayout(self)
        # Deliberate spacing rhythm (17-03 / D-03): margins/spacing on the layout, not an inline
        # color/QSS literal — styling stays in theme/qss.py.
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._edges_view, 1)
        layout.addWidget(self._gaps_view, 1)

    @property
    def status_label(self) -> QLabel:
        """The teaching/status line (tests assert the NoTransformsError text here)."""
        return self._status

    @property
    def edges_table(self) -> QTableView:
        """The per-edge summary view (tests assert ``.model().rowCount() > 0``)."""
        return self._edges_view

    @property
    def gaps_table(self) -> QTableView:
        """The per-edge gap-timeline view."""
        return self._gaps_view

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Re-read whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self.refresh_view()

    def _reader(self) -> object | None:
        """The window's single shared open reader (``None`` until a bag opens)."""
        return getattr(self.window(), "reader", None)

    def refresh_view(self) -> None:
        """Dispatch ``collect_tf_report`` OFF the UI thread on a worker (D-02 / P1 / T-17-04).

        With no bag open it shows the empty-state line and clears both models. Otherwise it
        runs ``collect_tf_report`` on a :class:`~rosbagger_desktop.workers.BlockingWorker`
        with ``teaching_errors=(NoTransformsError,)`` so a bag with no ``/tf``/``/tf_static``
        arrives on the ``failed`` slot as ``str(exc)`` and is rendered VERBATIM through the
        accessible status helper (T-16-TF), never a crash. A refresh while a worker runs is
        refused (re-entry guard).
        """
        reader = self._reader()
        if reader is None:
            set_status(self._status, "Open a bag with /tf to analyze")
            self._edges_model.set_rows([])
            self._gaps_model.set_rows([])
            self._analyzed_reader = None
            return

        # Reader-identity cache: showEvent fires on EVERY TF-tab visit, and collect_tf_report is
        # a FULL O(n) stream of /tf+/tf_static (the most expensive offline op). Skip the recompute
        # when the bag is unchanged — the views already reflect this reader's report. Held ref +
        # `is` (NOT id(), which a freed reader could reuse). Mirrors the query panel's F7 cache.
        if reader is self._analyzed_reader:
            return
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            return

        def work() -> object:
            # Lazy import (D-08): keep this module's top level PySide6-only.
            from rosbagger_core.tf import collect_tf_report

            return collect_tf_report(reader)

        # NoTransformsError (a teaching error) emits as str(exc) on the failed slot. Import it
        # lazily INSIDE refresh_view (D-08) only to name the teaching-error type for the worker.
        from rosbagger_core.errors import NoTransformsError

        worker = BlockingWorker(
            work, teaching_errors=(NoTransformsError,), label="TF analysis failed"
        )
        # Generation guard: bump per refresh; a SUPERSEDED worker's late signal (older gen) is
        # ignored, so its finished slot can't null the CURRENT worker's refs (the
        # File-Open-mid-refresh race) and a stale report can't render. (self.sender() is
        # unreliable for cross-thread bound-method slots in PySide6 — use an explicit gen.)
        self._refresh_gen += 1
        gen = self._refresh_gen
        analyzed = reader

        def _live(fn):
            return lambda *a, g=gen: fn(*a) if g == self._refresh_gen else None

        def _result(result: object) -> None:
            self._analyzed_reader = analyzed  # cache the reader this report was computed from
            self._on_refresh_result(result)

        def _failed(message: str) -> None:
            self._analyzed_reader = analyzed  # cache the no-/tf outcome too (don't re-stream it)
            self._on_refresh_failed(message)

        self._refresh_thread, self._refresh_worker = run_on_thread(
            self,
            worker,
            on_result=_live(_result),
            on_failed=_live(_failed),
            on_finished=_live(self._on_refresh_finished),
        )

    def _on_refresh_result(self, result: object) -> None:
        """Format the worker's ``TfReport`` into edge/gap rows on the UI thread (D-09).

        Presentation only (THIN-FACE): the per-edge rate/span computation + human-readable
        durations + em-dash placeholders are display formatting, no new analysis — identical
        to the old synchronous render, just moved into the result slot feeding ``set_rows``.
        """
        report = result  # type: ignore[assignment]  # always a TfReport here

        # Whole-bag span for the header + per-edge rate (presentation only).
        n_static = sum(1 for e in report.edges if e.static)
        n_dynamic = len(report.edges) - n_static
        span_s: float | None = None
        if report.start_ns is not None and report.end_ns is not None:
            raw = (report.end_ns - report.start_ns) / 1e9
            span_s = raw if raw > 0 else None
        span_clause = f" over {span_s:.2f}s" if span_s else ""
        set_status(self._status, f"{n_dynamic} dynamic edges, {n_static} static edges{span_clause}")

        # Per-edge summary: one row per TfReport.edges entry (mirror TUI tf columns).
        edge_rows: list[tuple[str, ...]] = []
        for e in report.edges:
            kind = "static" if e.static else "dynamic"
            # Rate is meaningful only for a multi-sample dynamic edge over a span.
            if e.static or e.samples < 2 or not span_s or span_s <= 0:
                rate = _EM_DASH
            else:
                rate = f"{e.samples / span_s:.1f}"
            max_gap = _human_dur(e.max_gap_ns) if e.max_gap_ns is not None else _EM_DASH
            edge_rows.append(
                (
                    str(e.parent),
                    str(e.child),
                    str(kind),
                    str(e.samples),
                    str(rate),
                    str(max_gap),
                    str(e.gap_count),
                )
            )
        self._edges_model.set_rows(edge_rows)

        # Gap timeline: one row per TfReport.gaps entry; empty -> a status note row.
        if not report.gaps:
            self._gaps_model.set_rows([("no gaps detected", "", "", "", "")])
        else:
            gap_rows: list[tuple[str, ...]] = [
                (
                    str(g.parent),
                    str(g.child),
                    str(_human_dur(g.gap_ns)),
                    f"t={g.at_rel_ns / 1e9:.2f}s",
                    str(g.at_ns),
                )
                for g in report.gaps
            ]
            self._gaps_model.set_rows(gap_rows)

    def _on_refresh_failed(self, message: str) -> None:
        """Render the teaching message (e.g. ``NoTransformsError``) VERBATIM (T-16-TF / D-09).

        The worker emits ``str(exc)`` for ``NoTransformsError`` (or ``"TF analysis failed:
        <exc>"`` otherwise) — never a traceback. Both models are cleared so a stale view never
        lingers; the message is rendered through the shared accessible status helper.
        """
        set_status(self._status, message, is_error=True)
        self._edges_model.set_rows([])
        self._gaps_model.set_rows([])

    def _on_refresh_finished(self) -> None:
        """Clear the thread/worker refs (CR-01, UI thread) — only for the CURRENT generation.

        A SUPERSEDED worker's late ``finished`` (an older generation — see ``refresh_view``'s
        ``_live`` guard) never reaches here, so it cannot null the CURRENT worker's refs in a
        File-Open-mid-refresh race (which would leave the new worker unparented + un-joined,
        re-opening the C3 reader use-after-free on close).
        """
        self._refresh_thread = None
        self._refresh_worker = None

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Stop the in-flight refresh thread before teardown (Pitfall 2)."""
        stop_thread(self._refresh_thread)
        super().closeEvent(event)
