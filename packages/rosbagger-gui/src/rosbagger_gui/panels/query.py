"""Query panel STUB (offline). Plan 14-04/05 fills it with the SQL query view.

OFFLINE PANEL (D-03): always enabled — drives ``rosbagger_core`` query over the
App's shared reader; no ROS. This stub only mounts a placeholder; the real
SQL editor + results table lands in a later wave.
"""

from __future__ import annotations

from textual.widgets import Static


class QueryPanel(Static):
    """Query view — run SQL over the bag's topics (offline)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("Query panel (offline) — open a bag to run SQL.", *args, **kwargs)
