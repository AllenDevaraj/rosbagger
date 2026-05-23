"""ROS-free unit tests for the live replay module (REP-01, D-11 tier 1).

These are the OFFLINE tier of the two-tier test strategy (D-11): they run in the
ROS-free uv venv / the offline CI, exercising the PURE raw-CDR source seam
(``rosbagger_replay.source.load_items``) over real fixture bags written by
``tools.make_fixtures`` — no live ROS graph required. ``load_items`` reads a bag
through the v1 ``rosbags`` ``AnyReader`` and yields an ordered stream of
``ReplayItem(t_ns, topic, msgtype, cdr)`` records whose ``cdr`` is always CDR
bytes (ROS 2 raw bytes pass through; ROS 1 wire bytes are bridged via
``reader.deserialize -> typestore.serialize_cdr`` — D-05). The genuinely ROS-bound
publish path (``rclpy`` publishers) is proven separately by the LIVE tier
(``tests/test_replay_live.py``, Plan 03), gated behind ``importorskip("rclpy")``.

The source layer imports ``rosbags`` only — never ``rclpy`` / ``rosbag2_py`` —
which is what lets these tests (and the whole offline suite) run ROS-free; a test
below asserts no ``rclpy`` leaked into ``sys.modules`` after the source import.

``tools.make_fixtures`` is a dev-only repo-root package, so (mirroring the other
fixture-consuming suites, e.g. ``tests/test_tf.py``) we put the repo root on
``sys.path`` here, scoped to this file. ``rosbagger_replay`` itself is an installed
uv workspace member, so it needs no path hack.

LOCAL-RUN REQUIREMENT (MEMORY.md): this dev host sources ROS 2 Humble onto
``PYTHONPATH``, which crashes a bare ``uv run pytest`` on collection. Run locally
with the host leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k source -q

CI is ROS-free, so it needs no prefix; this file bakes in NO ``PYTHONPATH``
override (a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Repo root on sys.path so `from tools.make_fixtures import ...` resolves under
# pytest's default import mode (mirrors tests/test_tf.py); scoped to this file.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import (  # noqa: E402  (after sys.path)
    write_ros1_bag,
    write_ros2_mcap_bag,
    write_ros2_sqlite_bag,
)

from rosbagger_replay.source import ReplayItem, load_items  # noqa: E402

_TOPICS = {"/cmd_vel", "/imu", "/image"}
_MSGTYPE_BY_TOPIC = {
    "/cmd_vel": "geometry_msgs/msg/Twist",
    "/imu": "sensor_msgs/msg/Imu",
    "/image": "sensor_msgs/msg/Image",
}


def _ros2_humble_typestore():
    """The default typestore the ROS 2 sqlite3 fixture needs (no embedded defs path)."""
    from rosbags.typesys import Stores, get_typestore

    return get_typestore(Stores.ROS2_HUMBLE)


# --------------------------------------------------------------------------- #
# source — raw-CDR load over the three fixture formats (D-05)
# --------------------------------------------------------------------------- #


def test_source_ros2_sqlite_yields_time_ordered_cdr(tmp_path):
    """ROS 2 sqlite3 fixture -> 9 ReplayItems, t_ns non-decreasing, cdr is non-empty bytes."""
    bag = write_ros2_sqlite_bag(tmp_path)
    items = load_items(bag, default_typestore=_ros2_humble_typestore())

    assert len(items) == 9
    assert all(isinstance(it, ReplayItem) for it in items)
    # time-ordered across the stream (non-decreasing t_ns)
    ts = [it.t_ns for it in items]
    assert ts == sorted(ts)
    for it in items:
        assert isinstance(it.cdr, bytes) and len(it.cdr) > 0
        assert it.topic in _TOPICS
        assert it.msgtype == _MSGTYPE_BY_TOPIC[it.topic]


def test_source_ros2_mcap_yields_cdr_without_default_typestore(tmp_path):
    """ROS 2 MCAP fixture is self-describing -> 9 items, cdr is bytes, NO default_typestore."""
    bag = write_ros2_mcap_bag(tmp_path)
    items = load_items(bag)  # self-describing: no default_typestore needed

    assert len(items) == 9
    for it in items:
        assert isinstance(it.cdr, bytes) and len(it.cdr) > 0
        assert it.topic in _TOPICS


def test_source_ros1_bridge_produces_cdr(tmp_path):
    """ROS 1 fixture -> 9 items; ROS 1 wire bytes bridged via deserialize->serialize_cdr."""
    bag = write_ros1_bag(tmp_path)
    items = load_items(bag)  # bridge must run without raising

    assert len(items) == 9
    for it in items:
        # The bridge produced CDR (not raw ROS 1 wire): non-empty bytes, no raise above.
        assert isinstance(it.cdr, bytes) and len(it.cdr) > 0
        assert it.topic in _TOPICS
        assert it.msgtype == _MSGTYPE_BY_TOPIC[it.topic]


# --------------------------------------------------------------------------- #
# source — topics subset filter + empty-selection short-circuit (QURY-05)
# --------------------------------------------------------------------------- #


def test_source_topics_filter_subset(tmp_path):
    """topics={'/imu'} returns exactly the 3 /imu items, nothing else."""
    bag = write_ros2_sqlite_bag(tmp_path)
    items = load_items(bag, topics={"/imu"}, default_typestore=_ros2_humble_typestore())

    assert len(items) == 3
    assert all(it.topic == "/imu" for it in items)


def test_source_empty_selection_returns_empty(tmp_path):
    """An unmatched topics filter short-circuits to [] (NOT all topics — QURY-05)."""
    bag = write_ros2_sqlite_bag(tmp_path)
    items = load_items(bag, topics={"/nope"}, default_typestore=_ros2_humble_typestore())

    assert items == []


# --------------------------------------------------------------------------- #
# source — offline import invariant (the dedicated guard lands in Plan 03)
# --------------------------------------------------------------------------- #


def test_source_imports_no_rclpy(tmp_path):
    """Importing + running the source seam leaks no rclpy/rosbag2_py into sys.modules."""
    bag = write_ros2_sqlite_bag(tmp_path)
    load_items(bag, default_typestore=_ros2_humble_typestore())

    assert "rclpy" not in sys.modules
    assert "rosbag2_py" not in sys.modules
