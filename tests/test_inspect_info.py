"""Fixture-backed tests for the Phase 4 inspect API and reader metadata surface.

Covers BOTH plan-04-01 tasks:

* **Task 1** — the additive public metadata properties on ``RosbagsReader``
  (``message_count``/``duration``/``start_time``/``end_time``/``typestore``/
  ``paths``) and their before-open guards (test names ``*reader_propert*`` /
  ``*before_open*``).
* **Task 2** — ``rosbagger_core.inspect.collect_bag_info`` over the three fixture
  formats: topic/msgtype/count rows, whole-bag duration, approximate per-topic
  Hz, format-aware size, plus the empty-bag and multi-msgtype edge cases.

The inspect API reads ONLY O(1) ``AnyReader`` metadata — it never iterates
message bodies (``reader.read()``), which is both the performance contract
(T-04-01) and what keeps a hostile/huge bag cheap to inspect.

VERIFIED fixture facts (rosbags 0.11.2, confirmed against the runtime this
plan): a single fixture bag carries 9 messages — 3 each of /cmd_vel
(geometry_msgs/msg/Twist), /imu (sensor_msgs/msg/Imu), /image
(sensor_msgs/msg/Image). Log timestamps are 1.0s / 1.1s / 1.2s, so
``start_time == 1_000_000_000``, ``end_time == 1_200_000_001`` and
``duration == 200_000_001`` ns (NOT a round 200_000_000 — the end stamp carries
a +1ns tail; see DURATION_NS below). Per-topic Hz ~= 3 / 0.200000001 s ~= 15.0.

LOCAL-RUN REQUIREMENT (02/04-RESEARCH.md): this dev host sources ROS 2 Humble
onto ``PYTHONPATH``; run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_inspect_info.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only repo-root package (not an installed distribution), so it
# is not on sys.path under pytest's default import mode. Put the repo root on
# sys.path here — scoped to this file (mirrors tests/test_reader.py), touching
# neither tests/conftest.py nor the root pyproject.toml.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures  # noqa: E402  (after sys.path setup)

from rosbagger_core.inspect import (  # noqa: E402  (3rd-party, after sys.path)
    BagInfo,
    TopicInfo,
    collect_bag_info,
)
from rosbagger_core.reader import RosbagsReader  # noqa: E402

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")

# Verified fixture facts (see module docstring). Each topic publishes 3 messages.
EXPECTED_MESSAGE_COUNT = 9
DURATION_NS = 200_000_001  # end_time(1_200_000_001) - start_time(1_000_000_000)
START_NS = 1_000_000_000
END_NS = 1_200_000_001
# msgcount / (duration_ns / 1e9) == 3 / 0.200000001 ~= 15.0 (approx; not exact).
EXPECTED_HZ = 15.0

# topic -> expected msgtype, sorted by topic name (cmd_vel, image, imu).
EXPECTED_TOPIC_TYPES = {
    "/cmd_vel": "geometry_msgs/msg/Twist",
    "/image": "sensor_msgs/msg/Image",
    "/imu": "sensor_msgs/msg/Imu",
}
EXPECTED_SORTED_TOPICS = ["/cmd_vel", "/image", "/imu"]


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("inspect_bags")
    return make_all_fixtures(dest)


@pytest.fixture(scope="session")
def empty_ros2_bag(tmp_path_factory) -> Path:
    """A zero-message ROS 2 sqlite bag (a Writer opened and closed with no writes).

    A bag with no messages is the empty-bag edge (Pitfall 1): ``AnyReader``
    reports ``start_time == sys.maxsize`` and a large-negative ``duration``,
    which ``collect_bag_info`` must collapse to ``None``.
    """
    from rosbags.rosbag2 import StoragePlugin
    from rosbags.rosbag2 import Writer as Ros2Writer

    dest = tmp_path_factory.mktemp("empty_bag")
    path = dest / "ros2_empty"
    with Ros2Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3):
        pass  # no add_connection / write -> zero messages
    return path


# ---------------------------------------------------------------------------
# Task 1 — additive RosbagsReader metadata properties (+ before-open guards)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_reader_property_metadata_on_open(fixture_bags: dict[str, Path], fmt: str) -> None:
    """The new O(1) metadata properties report the verified fixture values."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        assert reader.message_count == EXPECTED_MESSAGE_COUNT
        assert reader.duration == DURATION_NS
        assert reader.start_time == START_NS
        assert reader.end_time == END_NS
        assert reader.typestore is not None


def test_reader_property_paths_is_a_copy_callable_before_open(
    fixture_bags: dict[str, Path],
) -> None:
    """``paths`` reads no ``_reader`` (works before open) and returns a fresh copy."""
    bag = fixture_bags["ros1"]
    reader = RosbagsReader(bag)
    assert reader.paths == [Path(bag)]  # callable WITHOUT open()
    first = reader.paths
    first.append(Path("/mutation/should/not/persist"))
    assert reader.paths == [Path(bag)]  # internal list not mutated by caller


def test_reader_property_before_open_raises(fixture_bags: dict[str, Path]) -> None:
    """Every ``_reader``-backed metadata property raises RuntimeError before open()."""
    reader = RosbagsReader(fixture_bags["ros1"])
    for accessor in ("message_count", "duration", "start_time", "end_time", "typestore"):
        with pytest.raises(RuntimeError):
            getattr(reader, accessor)


# ---------------------------------------------------------------------------
# Task 2 — collect_bag_info over the fixtures (INSP-01 / INSP-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_collect_bag_info_message_count_and_duration(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Whole-bag totals: 9 messages, the verified duration, and a positive size."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        info = collect_bag_info(reader)
    assert isinstance(info, BagInfo)
    assert info.message_count == EXPECTED_MESSAGE_COUNT
    assert info.duration_ns == DURATION_NS
    assert info.start_time_ns == START_NS
    assert info.end_time_ns == END_NS
    assert info.size_bytes > 0


@pytest.mark.parametrize("fmt", FORMATS)
def test_collect_bag_info_topics_sorted_with_types_counts_hz(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Per-topic rows: sorted names, correct msgtype+count, approximate Hz ~= 15.0."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        info = collect_bag_info(reader)

    assert [t.topic for t in info.topics] == EXPECTED_SORTED_TOPICS
    for ti in info.topics:
        assert isinstance(ti, TopicInfo)
        assert ti.msgtype == EXPECTED_TOPIC_TYPES[ti.topic]
        assert ti.count == 3
        assert ti.hz == pytest.approx(EXPECTED_HZ, rel=1e-6)


def test_collect_bag_info_empty_bag_has_none_bounds_and_hz(empty_ros2_bag: Path) -> None:
    """Empty bag: None duration/start/end, no topics, no negative-duration garbage."""
    with RosbagsReader(empty_ros2_bag) as reader:
        info = collect_bag_info(reader)
    assert info.message_count == 0
    assert info.duration_ns is None
    assert info.start_time_ns is None
    assert info.end_time_ns is None
    assert all(ti.hz is None for ti in info.topics)
    assert info.topics == []


def test_collect_bag_info_ros2_size_is_summed_not_inode(fixture_bags: dict[str, Path]) -> None:
    """A ROS 2 directory bag's size is the summed file content, not the dir inode."""
    ros2_dir = fixture_bags["ros2_sqlite"]
    assert Path(ros2_dir).is_dir()
    with RosbagsReader(ros2_dir) as reader:
        info = collect_bag_info(reader)
    inode_size = Path(ros2_dir).stat().st_size
    assert info.size_bytes > inode_size  # summed contents, not the ~4 KB inode


def test_collect_bag_info_ros1_size_is_file_size(fixture_bags: dict[str, Path]) -> None:
    """A ROS 1 single-file bag's size equals ``stat().st_size``."""
    ros1_bag = fixture_bags["ros1"]
    assert not Path(ros1_bag).is_dir()
    with RosbagsReader(ros1_bag) as reader:
        info = collect_bag_info(reader)
    assert info.size_bytes == Path(ros1_bag).stat().st_size


def test_collect_bag_info_does_not_iterate_messages(fixture_bags: dict[str, Path]) -> None:
    """collect_bag_info must NOT call reader.read() (T-04-01: O(1) metadata only)."""
    with RosbagsReader(fixture_bags["ros1"]) as reader:

        def _boom():
            raise AssertionError("collect_bag_info called reader.read() — must use O(1) metadata")

        reader.read = _boom  # type: ignore[method-assign]
        info = collect_bag_info(reader)
    assert info.message_count == EXPECTED_MESSAGE_COUNT


def test_collect_bag_info_multi_msgtype_topic_yields_none_msgtype() -> None:
    """A topic whose msgtype is None (multi-msgtype) yields TopicInfo.msgtype=None.

    The fixtures never carry a heterogeneous-msgtype topic, so this exercises the
    Pitfall 4 guard path with a minimal duck-typed reader stub (no real bag): the
    inspect API must surface ``msgtype=None`` with the count intact, never crash.
    """
    from collections import namedtuple

    _Info = namedtuple("_Info", ["msgtype", "msgdef", "msgcount", "connections"])

    class _StubReader:
        # Attributes mirror the RosbagsReader public surface collect_bag_info reads.
        message_count = 5
        start_time = 1_000_000_000
        end_time = 1_500_000_000
        duration = 500_000_000
        paths: list = []  # empty -> size 0; size is not under test here

        @property
        def topics(self):
            return {"/mixed": _Info(msgtype=None, msgdef="", msgcount=5, connections=())}

    info = collect_bag_info(_StubReader())
    assert len(info.topics) == 1
    assert info.topics[0].topic == "/mixed"
    assert info.topics[0].msgtype is None
    assert info.topics[0].count == 5
    assert info.topics[0].hz == pytest.approx(10.0)  # 5 / 0.5 s
