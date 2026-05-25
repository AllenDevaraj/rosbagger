"""rosbagger-desktop widgets — reusable Qt presentation widgets for the panels.

OFFLINE-CLEAN (Pitfall 4): these widgets import ONLY PySide6 + stdlib and name no
live-module symbol — importing ``rosbagger_desktop.widgets`` pulls in no ROS / heavy stack.
"""

from __future__ import annotations

from .scrubber import EventMark, Scrubber

__all__ = ["EventMark", "Scrubber"]
