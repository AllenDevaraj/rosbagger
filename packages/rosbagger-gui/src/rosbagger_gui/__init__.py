"""rosbagger-gui: the Textual TUI cockpit — a thin face over the module APIs.

OFFLINE-IMPORT INVARIANT (D-03): ``import rosbagger_gui`` MUST succeed in the
ROS-free uv venv WITHOUT pulling ``rclpy`` / ``rosbag2_py`` into ``sys.modules``.
The :func:`_detect_ros` capability probe imports ``rclpy`` INSIDE its body (never
at module top), and the live panels lazy-import the ROS-bound siblings only inside
their method bodies (a later wave). The shell + offline panels need no ROS at all.
"""

from __future__ import annotations

__version__ = "0.2.0"


def _detect_ros() -> bool:
    """Cheap tier-1 ROS-availability probe (D-04): is ``rclpy`` importable?

    Delegates to :func:`rosbagger_core.capabilities.module_importable` (shared with the desktop
    ``ros_available`` gate, R6); the import lives INSIDE this body so the package top level stays
    ROS-free (the offline-import invariant). Returns ``True`` when a ROS 2 environment is sourced.
    The App computes this ONCE at startup to gate the live record/replay panels (D-03).
    """
    from rosbagger_core.capabilities import module_importable

    return module_importable("rclpy")
