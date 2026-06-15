"""Tests for ``rosbagger_core.capabilities`` — the shared runtime-capability probes (R6/T7)."""

from __future__ import annotations

import pytest

from rosbagger_core.capabilities import module_importable, ros_distro


def test_module_importable_true_for_a_real_module() -> None:
    """A real, importable module probes True (R6)."""
    assert module_importable("json") is True


def test_module_importable_false_for_an_absent_module() -> None:
    """A module that does not exist probes False (ImportError → False, never a raise) — R6."""
    assert module_importable("rosbagger_definitely_not_a_real_module_xyz") is False


def test_ros_distro_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ros_distro() returns $ROS_DISTRO when set, so remedies name the user's actual distro (T7)."""
    monkeypatch.setenv("ROS_DISTRO", "jazzy")
    assert ros_distro() == "jazzy"


def test_ros_distro_falls_back_to_humble(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset OR empty $ROS_DISTRO falls back to the documented 'humble' baseline (T7)."""
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    assert ros_distro() == "humble"
    monkeypatch.setenv("ROS_DISTRO", "")
    assert ros_distro() == "humble"


def test_teaching_remedies_use_the_active_distro(monkeypatch: pytest.MonkeyPatch) -> None:
    """The record/replay capability remedies interpolate ros_distro(), not a hard-coded one (T7)."""
    from rosbagger_record.errors import McapStorageUnavailableError
    from rosbagger_record.errors import RosNotAvailableError as RecordRosNotAvailable
    from rosbagger_replay.errors import RosNotAvailableError as ReplayRosNotAvailable

    monkeypatch.setenv("ROS_DISTRO", "iron")
    assert "/opt/ros/iron/setup.bash" in str(RecordRosNotAvailable())
    assert "/opt/ros/iron/setup.bash" in str(ReplayRosNotAvailable())
    mcap_msg = str(McapStorageUnavailableError("mcap", ["sqlite3"]))
    assert "ros-iron-rosbag2-storage-mcap" in mcap_msg
