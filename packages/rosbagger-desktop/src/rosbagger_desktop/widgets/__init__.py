"""rosbagger-desktop widgets — reusable Qt presentation widgets for the panels.

OFFLINE-CLEAN (Pitfall 4): these widgets import ONLY PySide6 + stdlib and name no
live-module symbol — importing ``rosbagger_desktop.widgets`` pulls in no ROS / heavy stack.
"""

from __future__ import annotations

from .result_model import _ResultTableModel
from .rows_model import RowsTableModel
from .scrubber import EventMark, Scrubber
from .status import set_status

__all__ = ["EventMark", "RowsTableModel", "Scrubber", "_ResultTableModel", "set_status"]
