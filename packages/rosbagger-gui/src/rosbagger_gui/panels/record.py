"""Record panel STUB (LIVE). Plan 14-06 fills it with the rosbagger-record view.

LIVE PANEL (D-03): capability-gated. When ``rclpy`` is not importable the App
sets this widget ``disabled=True`` and it shows a teaching hint to source a ROS 2
environment. The real topic-discovery + record controls (and the LAZY
``rosbagger_record`` import — never at module top, Pitfall 2) land in a later
wave; this stub keeps the offline import graph clean.
"""

from __future__ import annotations

from textual.widgets import Static

RECORD_HINT = "Source your ROS 2 environment to enable live recording (rosbagger-record)."


class RecordPanel(Static):
    """Record view — discover live ROS topics + record a subset (live)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(RECORD_HINT, *args, **kwargs)
