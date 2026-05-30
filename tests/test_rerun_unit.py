"""Offline unit tests for ``rosbagger-rerun``.

No ROS required. ``rerun`` is present via the dev dependency group, so these run in the
standard offline lane (they are NOT ``importorskip("rclpy")``). The package import itself
stays rerun-free (see ``tests/test_offline_guard.py``); these tests exercise the public
surface + (in 22-02) the pure converter helpers + the ``convert()`` dispatch.
"""

from __future__ import annotations

import rosbagger_rerun


def test_import_rosbagger_rerun_is_clean():
    """The package exposes its public surface (22-01 scaffold)."""
    assert hasattr(rosbagger_rerun, "rerun_available")
    assert hasattr(rosbagger_rerun, "open_viewer")


def test_rerun_available_returns_bool():
    """``rerun_available()`` returns a bool and never raises (environment-independent).

    Asserts the PROBE CONTRACT, not the value: it is ``True`` in the dev venv (rerun-sdk in
    the dev group) and ``False`` where rerun is absent — either way it must be a plain bool.
    """
    result = rosbagger_rerun.rerun_available()
    assert isinstance(result, bool)
