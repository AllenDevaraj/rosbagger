"""rosbagger-replay: live ROS 2 bag replay with transport controls (REP-01).

This is rosbagger's SECOND module that requires a sourced ROS 2 environment
(``rclpy``). The whole offline tier (``rosbagger_core``, ``bagq``) and this
package's PURE layers (the raw-CDR ``source`` seam + the transport ``scheduler``)
stay ROS-free — this package must not compromise that.

OFFLINE-IMPORT BOUNDARY (D-03/D-12) — the load-bearing discipline of this module:
``import rosbagger_replay`` MUST succeed in the ROS-free uv venv WITHOUT pulling
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` into ``sys.modules``. So this
file imports NO ROS at module top — only the stdlib-only teaching errors and the
pure ``source`` seam (rosbags-only). The lazy ROS-bound ``replay`` entry point and
the ``rosidl_runtime_py``/``rclpy`` publish sink land in Plan 03; the pure transport
scheduler lands in Plan 02.

``test_offline_guard.py`` (extended in Plan 03) regression-locks the boundary: it
asserts a fresh interpreter that does ``import rosbagger_replay`` leaks no ``rclpy``
/ ``rosbag2_py`` (and that ``import rosbagger_core`` / ``import bagq`` stay ROS-free).
"""

from __future__ import annotations

from .errors import NoMessagesToReplayError, RosNotAvailableError
from .source import ReplayItem, load_items

__version__ = "0.1.0"

# Public API (Plan 01 wave): the teaching capability errors and the pure raw-CDR
# source seam (ReplayItem + load_items). Re-exporting these binds NO ROS — errors.py
# is stdlib-only and source.py imports rosbags only (and lazily inside load_items).
# The lazy ROS-bound replay() front door lands in Plan 03.
__all__ = [
    "NoMessagesToReplayError",
    "ReplayItem",
    "RosNotAvailableError",
    "load_items",
]
