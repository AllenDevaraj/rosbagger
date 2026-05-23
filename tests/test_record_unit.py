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
is absent from the uv venv, so a string-target patch of ``rclpy.spin_once``
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

from rosbagger_record import McapStorageUnavailableError, RosNotAvailableError, record
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


# --------------------------------------------------------------------------- #
# _should_stop — pure bounded-stop accounting (Plan 02 Task 1), NO mocks at all
# --------------------------------------------------------------------------- #
#
# These call the helper with plain values — _should_stop is deliberately ROS-free
# (12-RESEARCH coverage rec. b) so the loop's exit logic is unit-coverable in the
# uv venv while the irreducible rclpy spin wiring stays live-only.

from rosbagger_record.record import _check_storage, _should_stop  # noqa: E402


def test_should_stop_max_messages_bound():
    """``max_messages``: below the bound -> keep going; at/over the bound -> stop."""
    # now/deadline irrelevant here (deadline=None); only the count drives it
    assert _should_stop(0, 0.0, max_messages=4, deadline=None) is False
    assert _should_stop(3, 0.0, max_messages=4, deadline=None) is False
    assert _should_stop(4, 0.0, max_messages=4, deadline=None) is True  # hit the bound
    assert _should_stop(5, 0.0, max_messages=4, deadline=None) is True  # past the bound


def test_should_stop_duration_deadline():
    """``deadline``: now before the deadline -> keep going; at/after -> stop."""
    # captured_n irrelevant here (max_messages=None); only the clock drives it
    assert _should_stop(99, 9.0, max_messages=None, deadline=10.0) is False
    assert _should_stop(99, 10.0, max_messages=None, deadline=10.0) is True  # reached
    assert _should_stop(99, 10.5, max_messages=None, deadline=10.0) is True  # passed


def test_should_stop_unbounded_never_stops():
    """Unbounded (both None) -> always False; only SIGINT (rclpy.ok()) ends the loop."""
    assert _should_stop(0, 0.0, max_messages=None, deadline=None) is False
    assert _should_stop(10_000, 1e9, max_messages=None, deadline=None) is False


# --------------------------------------------------------------------------- #
# _check_storage — capability gate, with rosbag2_py MOCKED via sys.modules
# --------------------------------------------------------------------------- #
#
# Inject a fake rosbag2_py whose get_registered_writers() returns a controlled set
# (12-RESEARCH Pitfall 6 — NOT a string-target patch of rosbag2_py, which would fail
# at collection in the ROS-free venv).


def test_check_storage_registered_does_not_raise(monkeypatch):
    """A registered ``storage_id`` passes the gate silently (no raise)."""
    fake_rosbag2_py = MagicMock()
    fake_rosbag2_py.get_registered_writers.return_value = {"sqlite3", "mcap"}
    monkeypatch.setitem(sys.modules, "rosbag2_py", fake_rosbag2_py)

    assert _check_storage("sqlite3") is None  # registered -> no raise


def test_check_storage_unregistered_raises_teaching_error(monkeypatch):
    """An unregistered ``storage_id`` raises ``McapStorageUnavailableError``.

    The error carries the structured ``.requested`` / ``.available`` payload (sorted)
    and names the registered writers — the teaching remedy (D-08 refined / Pitfall 1).
    """
    fake_rosbag2_py = MagicMock()
    # mcap is the requested default but only sqlite3 is registered on this box
    fake_rosbag2_py.get_registered_writers.return_value = {"sqlite3"}
    monkeypatch.setitem(sys.modules, "rosbag2_py", fake_rosbag2_py)

    with pytest.raises(McapStorageUnavailableError) as excinfo:
        _check_storage("mcap")

    err = excinfo.value
    assert err.requested == "mcap"
    assert err.available == ["sqlite3"]  # sorted list of what IS registered
    assert "mcap" in str(err)
    assert "sqlite3" in str(err)  # the message names the available fallback


# --------------------------------------------------------------------------- #
# record() — finalize-on-error + empty-selection, full ROS stack MOCKED
# --------------------------------------------------------------------------- #
#
# Inject MagicMocks for BOTH rclpy and rosbag2_py via sys.modules, make
# SequentialWriter() return a controllable writer mock, and monkeypatch the
# discovery the record-impl module imported. We call the .record IMPL (not the
# package front door, which would hit _require_ros first — that path is already
# covered by test_record_raises_teaching_error_when_ros_absent).


@pytest.fixture
def mocked_ros(monkeypatch):
    """Inject MagicMock rclpy + rosbag2_py and a controllable SequentialWriter.

    Yields ``(record_impl, writer)`` where ``record_impl`` is the live
    ``rosbagger_record.record.record`` and ``writer`` is the MagicMock every
    ``SequentialWriter()`` call returns — so a test can assert ``writer.close`` /
    ``writer.open`` were (not) called. ``get_registered_writers`` includes the
    default ``mcap`` so the storage gate passes and the test exercises the pipeline.
    """
    import rosbagger_record.record as record_impl

    fake_rclpy = MagicMock()
    fake_rosbag2_py = MagicMock()
    fake_rosbag2_py.get_registered_writers.return_value = {"mcap", "sqlite3"}

    writer = MagicMock()
    fake_rosbag2_py.SequentialWriter.return_value = writer

    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setitem(sys.modules, "rosbag2_py", fake_rosbag2_py)
    # rosidl_runtime_py.utilities.get_message(type_str) -> a message class
    fake_rosidl = MagicMock()
    monkeypatch.setitem(sys.modules, "rosidl_runtime_py", fake_rosidl)
    monkeypatch.setitem(sys.modules, "rosidl_runtime_py.utilities", fake_rosidl.utilities)

    return record_impl, writer


def test_record_finalizes_writer_when_loop_raises(monkeypatch, mocked_ros):
    """If the spin loop raises, ``record()`` STILL calls ``writer.close()`` (SC3 / T-12-05).

    Proves the ``finally: writer.close()`` finalizes the bag on every exit path so a
    crash mid-record leaves a re-openable bag, not a corrupt one. We monkeypatch
    discovery to return the requested topic, then force ``_run`` to blow up and assert
    ``close`` was called exactly once and the exception still propagated.
    """
    record_impl, writer = mocked_ros
    monkeypatch.setattr(
        record_impl,
        "discover_topics",
        lambda node, **kw: {"/telemetry": "std_msgs/msg/String"},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("spin exploded")

    monkeypatch.setattr(record_impl, "_run", boom)

    with pytest.raises(RuntimeError, match="spin exploded"):
        record_impl.record(["/telemetry"], "/tmp/out", storage="mcap")

    writer.close.assert_called_once()  # finalized despite the loop raising
    writer.open.assert_called_once()  # we did open before the loop blew up


def test_record_empty_selection_raises_before_opening_writer(monkeypatch, mocked_ros):
    """No matched topics -> teaching error BEFORE ``writer.open()`` (no empty bag).

    Discovery returns a map containing NONE of the requested names, so selection is
    empty; ``record()`` must raise the teaching ``ValueError`` BEFORE opening the
    writer (assert ``SequentialWriter.open`` was never called — nothing was created).
    """
    record_impl, writer = mocked_ros
    monkeypatch.setattr(
        record_impl,
        "discover_topics",
        lambda node, **kw: {"/other": "std_msgs/msg/String"},  # not the requested topic
    )

    with pytest.raises(ValueError, match="No live topics matched"):
        record_impl.record(["/telemetry"], "/tmp/out", storage="mcap")

    writer.open.assert_not_called()  # bailed out before opening the writer
    writer.close.assert_not_called()  # nothing to finalize — writer never opened
