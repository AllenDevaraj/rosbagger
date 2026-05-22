"""Round-trip tests for the fixture-bag generator (``tools/make_fixtures.py``).

These tests prove the load-bearing test-harness guarantee: bags written by
``rosbags`` (with NO ROS installed) re-open via ``rosbags.highlevel.AnyReader``
in all three target formats — ROS 1 ``.bag``, ROS 2 sqlite3, ROS 2 MCAP — and
carry the forward-looking content (``/cmd_vel`` Twist, ``/imu`` Imu with
``header.stamp`` + a length-9 covariance, ``/image`` Image blob) that Phases 2-3
will query without changing the fixtures.

The bags are generated once per session into a throwaway ``tmp_path_factory``
directory (O-2: no committed binaries — they are version-coupled to ``rosbags``
and ``.gitignore`` excludes them). The session-scoped fixture lives HERE, not in
``tests/conftest.py`` (which is owned by plan 01-02).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rosbags.highlevel import AnyReader

# `tools` is a dev-only package at the repo root (NOT an installed distribution
# like rosbagger_core / bagq), so it is not on sys.path under pytest's default
# import mode. Put the repo root on sys.path here — scoped to this test file, so
# we touch neither tests/conftest.py nor the root pyproject.toml (plan 01-02).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures  # noqa: E402  (after sys.path setup)

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")
EXPECTED_TOPICS = {"/cmd_vel", "/imu", "/image"}


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("bags")
    return make_all_fixtures(dest)


@pytest.mark.parametrize("fmt", FORMATS)
def test_bag_reopens_via_anyreader(fixture_bags: dict[str, Path], fmt: str) -> None:
    """Each generated bag exists and re-opens via AnyReader yielding >= 1 message."""
    path = fixture_bags[fmt]
    assert path.exists(), f"{fmt} bag was not written to {path}"
    with AnyReader([path]) as reader:
        messages = list(reader.messages())
    assert len(messages) >= 1, f"{fmt} bag yielded no messages"
    # AnyReader yields the documented (connection, t_ns, raw) tuple shape.
    connection, t_ns, raw = messages[0]
    assert isinstance(t_ns, int)
    assert isinstance(raw, (bytes, bytearray, memoryview))
    assert connection.topic in EXPECTED_TOPICS


@pytest.mark.parametrize("fmt", FORMATS)
def test_bag_carries_all_forward_looking_topics(fixture_bags: dict[str, Path], fmt: str) -> None:
    """Every format carries /cmd_vel, /imu, and /image (the forward-looking set)."""
    with AnyReader([fixture_bags[fmt]]) as reader:
        topics = {connection.topic for connection, _, _ in reader.messages()}
    assert topics >= EXPECTED_TOPICS, f"{fmt} missing topics: {EXPECTED_TOPICS - topics}"


def test_ros2_sqlite_imu_has_stamp_and_length9_covariance(
    fixture_bags: dict[str, Path],
) -> None:
    """A deserialized /imu message carries header.stamp and a length-9 covariance.

    This proves the Phase 2-3 substrate: ``header.stamp`` extraction (QURY-04)
    and the ``float64[9]`` LIST column (QURY-03). Asserted on the ROS 2 sqlite
    bag; the round-trip test above already covers all three formats opening.
    """
    with AnyReader([fixture_bags["ros2_sqlite"]]) as reader:
        imu_msg = None
        for connection, _t_ns, raw in reader.messages():
            if connection.topic == "/imu":
                imu_msg = reader.deserialize(raw, connection.msgtype)
                break
    assert imu_msg is not None, "no /imu message found in the ROS 2 sqlite bag"
    # header.stamp is present (Twist, by contrast, has no header -> stamp NULL later).
    assert hasattr(imu_msg, "header")
    assert hasattr(imu_msg.header, "stamp")
    assert imu_msg.header.stamp.sec >= 1
    # orientation_covariance is the float64[9] array Phase 3 will expose as a LIST.
    assert len(imu_msg.orientation_covariance) == 9


def test_image_blob_round_trips(fixture_bags: dict[str, Path]) -> None:
    """The /image message carries its uint8[] data blob through serialization.

    This is the heavy-blob placeholder for QURY-07 lazy materialization.
    """
    with AnyReader([fixture_bags["ros2_sqlite"]]) as reader:
        image_msg = None
        for connection, _t_ns, raw in reader.messages():
            if connection.topic == "/image":
                image_msg = reader.deserialize(raw, connection.msgtype)
                break
    assert image_msg is not None, "no /image message found in the ROS 2 sqlite bag"
    assert image_msg.encoding == "rgb8"
    # 2x2 RGB -> height(2) * step(2*3) == 12 bytes of data.
    assert len(image_msg.data) == 12
