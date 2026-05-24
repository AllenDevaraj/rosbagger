"""Inspect panel STUB (offline). Plan 14-03/04 fills it with the bagq-info view.

OFFLINE PANEL (D-03): always enabled — drives ``rosbagger_core.inspect`` over the
App's shared reader; no ROS. This stub only mounts a placeholder; the real
topics/types/counts/duration view lands in a later wave.
"""

from __future__ import annotations

from textual.widgets import Static


class InspectPanel(Static):
    """Inspect view — topics, message types, counts, duration (offline)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("Inspect panel (offline) — open a bag to view topics.", *args, **kwargs)
