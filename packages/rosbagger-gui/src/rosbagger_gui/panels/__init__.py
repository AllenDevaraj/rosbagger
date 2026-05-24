"""rosbagger-gui panels: the five views mounted in the App's ContentSwitcher.

Three OFFLINE panels (inspect/query/tf, always enabled) + two LIVE panels
(record/replay, capability-gated when ROS is absent, D-03). Re-exporting these
binds NO ROS — every module here imports only ``textual`` at top level; the LIVE
packages (rosbagger_record / rosbagger_replay) are lazy-imported inside method
bodies in a later wave (Pitfall 2 offline-import boundary).
"""

from __future__ import annotations

from .inspect import InspectPanel
from .query import QueryPanel
from .record import RecordPanel
from .replay import ReplayPanel
from .tf import TfPanel

__all__ = [
    "InspectPanel",
    "QueryPanel",
    "RecordPanel",
    "ReplayPanel",
    "TfPanel",
]
