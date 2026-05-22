"""The load-bearing offline-import invariant.

These two tests protect the architectural "universal / no-ROS" promise for the
life of the repo: the offline packages (``rosbagger_core``, ``bagq``) must never
pull in a ROS module, directly or transitively. The ``no_ros`` fixture
(tests/conftest.py) installs a ``sys.meta_path`` blocker so the assertion is
meaningful on both a clean CI runner AND this ROS-equipped dev box.
"""

import importlib
import sys

import pytest


def test_core_imports_without_ros(no_ros):
    """Under the blocker, ROS modules raise ImportError but the offline packages still import."""
    for mod in ("rclpy", "rosbag2_py"):
        with pytest.raises(ImportError):
            importlib.import_module(mod)
    importlib.import_module("rosbagger_core")  # must still succeed
    importlib.import_module("bagq")


def test_no_ros_leaked_into_sys_modules():
    """Importing the offline packages must not populate sys.modules with any ROS module."""
    import bagq  # noqa: F401
    import rosbagger_core  # noqa: F401

    leaked = [m for m in sys.modules if m.split(".")[0] in {"rclpy", "rosbag2_py"}]
    assert leaked == [], f"offline import pulled in ROS modules: {leaked}"
