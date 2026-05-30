"""rosbagger-rerun — convert ROS 2 messages to Rerun archetypes and log them live.

OFFLINE-IMPORT INVARIANT: importing this package pulls NEITHER ``rclpy`` NOR
``rerun``. Every ``rerun`` / ``rclpy`` / ``rosidl_runtime_py`` import lives lazily
INSIDE a function body (see ``session`` / ``converters`` / ``sink``), so the offline
import graph (bagq / inspect / query, and the desktop's module top) stays ROS-free
AND Rerun-free. ``tests/test_offline_guard.py`` enforces this.

Public surface (added across Phase 22):
- ``rerun_available()`` / ``open_viewer()`` / ``close_viewer()``  — session (22-01, 260530-c3p)
- ``convert()`` / ``build_rerun_sink()``      — converters + sink (22-02)
"""

from __future__ import annotations

from .converters import convert
from .session import close_viewer, open_viewer, rerun_available
from .sink import build_rerun_sink

__all__ = ["build_rerun_sink", "close_viewer", "convert", "open_viewer", "rerun_available"]
