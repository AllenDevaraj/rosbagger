"""Capability probe for the desktop GUI — the Qt analog of the TUI ``_detect_ros``.

The cheap tier-1 ROS-availability check the main window runs ONCE at startup to
gate the live record/replay panels (D-09). The ``rclpy`` import lives INSIDE the
function body so this module's top level (and thus ``import rosbagger_desktop.cli``)
stays ROS-free — the offline-import invariant.
"""

from __future__ import annotations


def ros_available() -> bool:
    """Cheap tier-1 ROS-availability probe (D-09): is ``rclpy`` importable?

    The import lives INSIDE this function body so the package top level stays
    ROS-free. Returns ``True`` when a ROS 2 environment is sourced (``rclpy``
    resolves), ``False`` otherwise. The main window computes this ONCE at startup
    to gate the live record/replay panels.
    """
    try:
        import rclpy  # noqa: F401
    except ImportError:
        return False
    return True
