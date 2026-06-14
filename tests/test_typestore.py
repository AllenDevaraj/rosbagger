"""Unit tests for rosbagger_core.typestore.resolve_default_typestore (T1).

Proves the def-less-bag default-typestore resolver maps $ROS_DISTRO to the right rosbags
Stores member and always falls back to ROS2_HUMBLE — the decision the reader applies so no
frontend hard-codes a typestore.

LOCAL-RUN: this dev host sources ROS onto PYTHONPATH; run with `PYTHONPATH=""` to keep the
host leak from crashing collection (02-RESEARCH Pitfall 5). CI is ROS-free, needs no prefix.
"""

from __future__ import annotations

import pytest

from rosbagger_core.typestore import _store_for_distro, resolve_default_typestore


@pytest.mark.parametrize(
    ("distro", "expected"),
    [
        ("humble", "ROS2_HUMBLE"),
        ("jazzy", "ROS2_JAZZY"),
        ("iron", "ROS2_IRON"),
        ("JAZZY", "ROS2_JAZZY"),  # case-insensitive
        (" humble ", "ROS2_HUMBLE"),  # stripped
        ("", "ROS2_HUMBLE"),  # unset -> fallback
        ("noetic", "ROS2_HUMBLE"),  # ROS 1 distro -> fallback
        ("nonsense", "ROS2_HUMBLE"),  # unknown -> fallback
    ],
)
def test_store_for_distro_maps_or_falls_back(distro: str, expected: str) -> None:
    assert _store_for_distro(distro).name == expected


def test_resolve_default_typestore_unset_is_humble(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no $ROS_DISTRO the resolver returns a usable ROS2_HUMBLE typestore."""
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    ts = resolve_default_typestore()
    # A standard type resolves -> it is a real ROS 2 typestore (not an empty stub).
    assert ts.get_msgdef("sensor_msgs/msg/Imu") is not None


def test_resolve_default_typestore_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """$ROS_DISTRO drives the selection; jazzy still yields a usable store."""
    monkeypatch.setenv("ROS_DISTRO", "jazzy")
    ts = resolve_default_typestore()
    assert ts.get_msgdef("geometry_msgs/msg/Twist") is not None
