"""Shared pytest fixtures for the rosbagger test suite.

The load-bearing fixture here is ``no_ros``: a ``sys.meta_path`` import blocker
that makes the offline-import guard meaningful even on a host that HAS ROS
installed (this dev machine sources ROS 2 Humble onto ``PYTHONPATH``, so a bare
``import rclpy`` succeeds). See 01-RESEARCH.md Pitfall 4 for why the naive
``with pytest.raises(ImportError): import rclpy`` form proves nothing — it
passes for the wrong reason on clean CI and gives false confidence on the dev
box. The blocker neutralizes the host's ROS install for the duration of the
guard test, so the test exercises the import GRAPH of the offline packages
rather than the ambient environment.
"""

import sys

import pytest


class _ROSBlocker:
    """Meta-path finder that blocks ROS imports even when ROS is installed on the host."""

    BLOCKED = {"rclpy", "rosbag2_py", "rosidl_runtime_py", "ament_index_python"}

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"{name} is blocked: offline package must not import ROS")
        return None


@pytest.fixture
def no_ros(monkeypatch):
    """Block ROS modules via sys.meta_path and purge any already-imported ones.

    monkeypatch restores ``sys.meta_path`` and ``sys.modules`` after the test,
    so the blocker does not leak into other tests.
    """
    monkeypatch.setattr(sys, "meta_path", [_ROSBlocker(), *sys.meta_path])
    for m in list(sys.modules):
        if m.split(".")[0] in _ROSBlocker.BLOCKED:
            monkeypatch.delitem(sys.modules, m, raising=False)
    yield
