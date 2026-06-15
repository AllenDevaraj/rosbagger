"""Capability probes shared across the rosbagger faces (offline-safe).

A small home for the runtime-capability checks the GUI / desktop / live faces each used to
inline. Everything here imports ONLY the standard library at module top (the offline-import
invariant — ``import rosbagger_core.capabilities`` pulls no ROS / heavy query stack); a probe
that needs a heavy module imports it LAZILY inside its own body, at call time.
"""

from __future__ import annotations


def module_importable(name: str) -> bool:
    """Whether ``import <name>`` succeeds — a cheap capability probe (R6).

    Performs the REAL import (matching the prior ``_detect_ros`` / ``ros_available`` gates) and
    returns ``False`` only on :class:`ImportError`; any other failure propagates (a present but
    broken module is a real error, not "absent"). The import happens at CALL time, so importing
    this module never pulls ``name`` — keeping the offline-import invariant intact for callers
    that probe ``"rclpy"`` to gate live ROS features.
    """
    import importlib

    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


def ros_distro() -> str:
    """The active ROS 2 distro name for teaching remedies (T7).

    Reads ``$ROS_DISTRO`` (exported by ``source /opt/ros/<distro>/setup.bash``) so a remedy
    points at the user's ACTUAL distro (jazzy, iron, rolling, …) instead of a hard-coded one.
    Falls back to ``"humble"`` (the project's documented baseline) when the variable is unset or
    empty, so an offline / unsourced environment still shows a concrete, copy-pasteable command.
    """
    import os

    return os.environ.get("ROS_DISTRO") or "humble"
