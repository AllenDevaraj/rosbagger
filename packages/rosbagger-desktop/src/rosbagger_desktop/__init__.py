"""rosbagger-desktop: the native PySide6 (Qt) cockpit — a thin face over the module APIs.

ISOLATION INVARIANT (D-04): ``import rosbagger_desktop`` MUST succeed in the
ROS-free uv venv WITHOUT pulling ``PySide6`` / ``shiboken6`` (the Qt-free
invariant) NOR ``rclpy`` / ``rosbag2_py`` (the ROS-free invariant) into
``sys.modules``. The capability probe lives in :mod:`rosbagger_desktop.capabilities`
(``ros_available`` imports ``rclpy`` INSIDE its body); the cli imports ``QApplication``
inside :func:`~rosbagger_desktop.cli.main`; and the panels lazy-import the
``rosbagger_core`` / ``rosbagger_record`` / ``rosbagger_replay`` APIs only inside
their method bodies. So this package top level stays Qt-free AND ROS-free.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rosbagger-desktop")
except PackageNotFoundError:  # raw source tree (not pip-installed)
    __version__ = "0.0.0+unknown"
