"""TF panel STUB (offline). Plan 14-05 fills it with the TF dropout/timeline view.

OFFLINE PANEL (D-03): always enabled — drives ``rosbagger_core.tf`` over the
App's shared reader; no ROS. This stub only mounts a placeholder; the real
parent->child graph + per-edge gap report lands in a later wave.
"""

from __future__ import annotations

from textual.widgets import Static


class TfPanel(Static):
    """TF view — transform graph + per-edge dropout report (offline)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__("TF panel (offline) — open a bag to view transforms.", *args, **kwargs)
