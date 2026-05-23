"""ROS-mocked unit tests for the live record module (REC-01, D-10 tier 1).

These are the OFFLINE tier of the two-tier test strategy (D-10): they run in the
ROS-free uv venv / the offline CI, exercising every piece of ``rosbagger_record``
that does NOT require a live ROS graph — the pure-Python subset selection
(``select_topics``), the topic-discovery orchestration (``discover_topics``, with
``rclpy`` MOCKED), and the no-ROS capability error (``record`` raising
``RosNotAvailableError``). The genuinely ROS-bound recording path (``rclpy``
subscriptions + the ``rosbag2_py`` writer) is proven separately by the LIVE tier
(``tests/test_record_live.py``, Plan 03), gated behind ``importorskip("rclpy")``.

WHY ``sys.modules`` INJECTION, NOT ``mock.patch`` (12-RESEARCH Pitfall 6): ``rclpy``
is absent from the uv venv, so a string-target ``mock.patch("rclpy.spin_once")``
would fail at COLLECTION (it imports the target). Because ``rosbagger_record``
lazy-imports ``rclpy`` INSIDE function bodies, we inject a ``MagicMock`` via
``monkeypatch.setitem(sys.modules, "rclpy", ...)`` BEFORE calling — the function's
``import rclpy`` then binds the mock. For the no-ROS case we reuse the ``no_ros``
conftest blocker (it raises ``ImportError`` for ``rclpy``), so ``_require_ros()``
converts that into the teaching ``RosNotAvailableError``.

NO sys.path hack is needed: ``rosbagger-record`` is an installed uv workspace
member, so pytest in the venv resolves ``import rosbagger_record`` directly
(verified) — unlike ``tools`` (a dev-only repo-root package other suites add to
``sys.path``).

LOCAL-RUN REQUIREMENT (MEMORY.md): this dev host sources ROS 2 Humble onto
``PYTHONPATH``, which crashes a bare ``uv run pytest`` on collection. Run locally
with the host leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_record_unit.py -q

CI is ROS-free, so it needs no prefix; this file bakes in NO ``PYTHONPATH``
override (a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from rosbagger_record import RosNotAvailableError, record
from rosbagger_record.discovery import discover_topics, select_topics

# --------------------------------------------------------------------------- #
# select_topics — pure-Python subset selection (D-07), no ROS at all
# --------------------------------------------------------------------------- #


def test_select_positional_keeps_present_drops_missing():
    """Positional names select exactly the named PRESENT topics; missing ones drop."""
    discovered = {"/a": "T", "/b": "U", "/c": "V"}
    assert select_topics(discovered, topics=["/a", "/c", "/zzz"]) == {"/a": "T", "/c": "V"}


def test_select_all_returns_full_map():
    """``all_topics=True`` returns every discovered topic with its type."""
    discovered = {"/a": "T", "/b": "U", "/c": "V"}
    assert select_topics(discovered, all_topics=True) == discovered


def test_select_regex_keeps_only_matches():
    """``regex`` keeps only base-set names matching ``re.search``."""
    discovered = {"/cmd_vel": "geometry_msgs/msg/Twist", "/imu": "sensor_msgs/msg/Imu"}
    assert select_topics(discovered, all_topics=True, regex="^/cmd") == {
        "/cmd_vel": "geometry_msgs/msg/Twist"
    }


def test_select_exclude_drops_matches():
    """``exclude`` drops base-set names matching ``re.search``."""
    discovered = {"/cmd_vel": "geometry_msgs/msg/Twist", "/image": "sensor_msgs/msg/Image"}
    assert select_topics(discovered, all_topics=True, exclude="image") == {
        "/cmd_vel": "geometry_msgs/msg/Twist"
    }


def test_select_all_plus_exclude_yields_everything_minus_excluded():
    """``all_topics`` + ``exclude`` = the full map minus the excluded names."""
    discovered = {"/cmd_vel": "X", "/image_raw": "Y", "/image_rect": "Z", "/imu": "W"}
    assert select_topics(discovered, all_topics=True, exclude="image") == {
        "/cmd_vel": "X",
        "/imu": "W",
    }


def test_select_regex_then_exclude_compose():
    """Precedence: base -> regex include -> exclude (the regex set is then narrowed)."""
    discovered = {"/cam/image_raw": "A", "/cam/info": "B", "/lidar/points": "C"}
    # regex keeps the two /cam topics, exclude then drops the image one
    assert select_topics(discovered, all_topics=True, regex="^/cam", exclude="image") == {
        "/cam/info": "B"
    }


def test_select_empty_base_when_no_topics_and_not_all():
    """No positional names and ``all_topics=False`` -> empty selection (not all)."""
    discovered = {"/a": "T", "/b": "U"}
    assert select_topics(discovered) == {}


def test_select_is_deterministic_and_preserves_discovered_order():
    """Output iterates ``discovered`` insertion order (stable) and keeps the type strings."""
    discovered = {"/z": "Z", "/a": "A", "/m": "M"}
    assert list(select_topics(discovered, all_topics=True).items()) == [
        ("/z", "Z"),
        ("/a", "A"),
        ("/m", "M"),
    ]


# --------------------------------------------------------------------------- #
# discover_topics — ROS-bound, with rclpy MOCKED via sys.modules (Pitfall 6)
# --------------------------------------------------------------------------- #


def test_discover_topics_mocked_drops_typeless_and_settles(monkeypatch):
    """A MagicMock node drives ``discover_topics`` with ``rclpy`` injected.

    Asserts: the ``{topic: type_str}`` map takes the first type per topic and drops
    a typeless topic, and ``rclpy.spin_once`` is called ``settle_iters`` times (the
    DDS settle, Pattern 3).
    """
    fake_rclpy = MagicMock()
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)

    node = MagicMock()
    node.get_topic_names_and_types.return_value = [
        ("/telemetry", ["std_msgs/msg/String"]),
        ("/empty", []),
    ]

    out = discover_topics(node, settle_iters=30, settle_dt=0.02)

    assert out == {"/telemetry": "std_msgs/msg/String"}  # typeless /empty dropped
    assert fake_rclpy.spin_once.call_count == 30  # settled settle_iters times


def test_discover_topics_takes_first_type_for_multitype(monkeypatch):
    """Multi-type topics resolve to their FIRST advertised type (Pattern 3)."""
    monkeypatch.setitem(sys.modules, "rclpy", MagicMock())
    node = MagicMock()
    node.get_topic_names_and_types.return_value = [("/multi", ["pkg/msg/A", "pkg/msg/B"])]
    assert discover_topics(node, settle_iters=1) == {"/multi": "pkg/msg/A"}


# --------------------------------------------------------------------------- #
# no_ros — record() raises the teaching capability error (D-11)
# --------------------------------------------------------------------------- #


def test_record_raises_teaching_error_when_ros_absent(no_ros):
    """With ROS blocked, ``record()`` raises ``RosNotAvailableError`` (not bare ImportError).

    The ``no_ros`` conftest fixture blocks ``rclpy`` import (raising ``ImportError``);
    ``_require_ros()`` converts that into the teaching error whose message points the
    user at sourcing ROS 2.
    """
    with pytest.raises(RosNotAvailableError) as excinfo:
        record(["/telemetry"], "/tmp/out")
    assert "ROS 2" in str(excinfo.value)
