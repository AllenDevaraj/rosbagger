"""Inspect panel (offline, D-05) — a thin face over ``rosbagger_core.inspect``.

OFFLINE PANEL (D-03): always enabled. This panel is a pure RENDERER: it reads the
App's single shared open reader and calls EXACTLY two ``rosbagger_core.inspect``
APIs — :func:`collect_bag_info` (per-topic msgtype/count/Hz + whole-bag
duration/size/message_count) and :func:`collect_table_schemas` (per-topic table
name + column schema). It contains ZERO analysis logic; every number comes from
core. Display formatting (human-readable duration/size, ``<mixed>``/em-dash
placeholders) is presentation only — mirroring the ``bagq info``/``bagq tables``
renderers — and adds no new computation.

OFFLINE-IMPORT INVARIANT (D-03): the ``rosbagger_core.inspect`` import lives INSIDE
:meth:`refresh_view` (a method body), never at module top — so this module's top
level stays textual-only and importing it pulls no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

# Placeholder rendering (mirrors the bagq CLI's shape) — presentation only.
_MIXED = "<mixed>"
_EM_DASH = "—"


def _human_size(size_bytes: int) -> str:
    """Format a byte count human-readably (B/KB/MB/GB/TB) — presentation only.

    Mirrors the ``bagq info`` footer's ``_human_size``; the core API keeps
    ``size_bytes`` as a raw int (display formatting is the face's job, not the API's).
    """
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


class InspectPanel(Widget):
    """Inspect view — topics/types/counts/duration/size + per-topic table schemas."""

    def compose(self) -> ComposeResult:
        """A whole-bag header line + the per-topic overview and table-schema DataTables."""
        yield Static("Open a bag to inspect", id="inspect-header")
        yield DataTable(id="bag-info")
        yield DataTable(id="table-schemas")

    def on_mount(self) -> None:
        """Populate from the shared reader once the widget tree exists."""
        self.refresh_view()

    def on_show(self) -> None:
        """Re-read whenever the panel becomes the active ContentSwitcher view."""
        self.refresh_view()

    def refresh_view(self) -> None:
        """Read the App's shared reader and fill both DataTables from core output.

        Lazily imports the two ``rosbagger_core.inspect`` APIs INSIDE the method
        (offline invariant), calls them against the shared reader, and renders the
        results. With no bag open it shows the empty-state header and leaves the
        tables cleared — never an analysis pass without a reader.
        """
        header = self.query_one("#inspect-header", Static)
        bag_info_table = self.query_one("#bag-info", DataTable)
        schemas_table = self.query_one("#table-schemas", DataTable)

        reader = getattr(self.app, "reader", None)
        if reader is None:
            header.update("Open a bag to inspect")
            bag_info_table.clear(columns=True)
            schemas_table.clear(columns=True)
            return

        # Lazy import (D-03): keep this module's top level textual-only.
        from rosbagger_core.inspect import collect_bag_info, collect_table_schemas

        info = collect_bag_info(reader)
        schemas = collect_table_schemas(reader)

        # Whole-bag header line (presentation formatting only — no new analysis).
        duration = f"{info.duration_ns / 1e9:.2f}s" if info.duration_ns is not None else _EM_DASH
        header.update(
            f"duration: {duration} · {info.message_count} messages · {_human_size(info.size_bytes)}"
        )

        # Per-topic overview: one row per BagInfo.topics entry.
        bag_info_table.clear(columns=True)
        bag_info_table.add_columns("topic", "msgtype", "count", "hz")
        for ti in info.topics:
            hz = f"{ti.hz:.1f}" if ti.hz is not None else _EM_DASH
            bag_info_table.add_row(ti.topic, ti.msgtype or _MIXED, str(ti.count), hz)

        # Per-topic table schemas: one row per (table, column) with a heavy-blob marker.
        schemas_table.clear(columns=True)
        schemas_table.add_columns("table", "column", "type", "lazy")
        for schema in schemas:
            for col in schema.columns:
                marker = "lazy (blob)" if col.is_heavy_blob else ""
                schemas_table.add_row(schema.table_name, col.name, str(col.arrow_type), marker)
