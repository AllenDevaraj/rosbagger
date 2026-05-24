"""Replay panel STUB (LIVE). Plan 14-06 fills it with the rosbagger-replay view.

LIVE PANEL (D-03): capability-gated. When ``rclpy`` is not importable the App
sets this widget ``disabled=True`` and it shows a teaching hint to source a ROS 2
environment. The real transport controls drive ``rosbagger_replay.replay`` /
``build_publish_sink`` (the single production publish front door, D-09a) via a
LAZY import inside method bodies (never at module top, Pitfall 2) in a later
wave; this stub keeps the offline import graph clean.
"""

from __future__ import annotations

from textual.widgets import Static

REPLAY_HINT = "Source your ROS 2 environment to enable live replay (rosbagger-replay)."


class ReplayPanel(Static):
    """Replay view — publish a bag to live ROS topics with transport controls (live)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(REPLAY_HINT, *args, **kwargs)
