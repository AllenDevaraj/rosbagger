"""Pure offline unit tests for the Phase-20 RViz-fidelity decision tier (REP-04).

`rosbagger_replay.fidelity` is stdlib-only and operates on the rosbags-free ReplayItem, so
these run in the ROS-free uv venv with no ROS / no Qt — the deterministic CI proof for SC2
(static re-publish) + the clock-stamp math the live /clock build (20-02) relies on.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve the workspace packages when run from the repo root (mirrors the other suites).
_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _ROOT / "packages" / "rosbagger-replay" / "src",
    _ROOT / "packages" / "rosbagger-core" / "src",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rosbagger_replay import ReplayItem, StaticTracker, clock_stamp_ns  # noqa: E402


def _item(topic: str, t_ns: int = 0, cdr: bytes = b"x") -> ReplayItem:
    """Build a ReplayItem with a given topic/t_ns (msgtype is irrelevant to the tracker)."""
    return ReplayItem(t_ns=t_ns, topic=topic, msgtype="std_msgs/msg/String", cdr=cdr)


def test_static_tracker_records_latest_per_static_topic() -> None:
    """record keeps only the LATEST item per static topic (no history)."""
    tracker = StaticTracker(frozenset({"/tf_static"}))
    first = _item("/tf_static", t_ns=100, cdr=b"a")
    second = _item("/tf_static", t_ns=200, cdr=b"b")
    tracker.record(first)
    tracker.record(second)

    items = tracker.republish_items()
    assert items == [second]  # exactly one — the latest, not a history


def test_static_tracker_ignores_non_static_topics() -> None:
    """A non-static topic is never tracked; only the configured static topic is retained."""
    tracker = StaticTracker(frozenset({"/tf_static"}))
    tracker.record(_item("/imu"))  # not static -> ignored
    assert tracker.republish_items() == []

    tf = _item("/tf_static")
    tracker.record(tf)
    tracker.record(_item("/imu", t_ns=999))  # still ignored
    assert tracker.republish_items() == [tf]


def test_static_tracker_default_is_tf_static() -> None:
    """A bare StaticTracker() tracks /tf_static and nothing else (the default set)."""
    tracker = StaticTracker()
    tf = _item("/tf_static")
    tracker.record(tf)
    tracker.record(_item("/map"))  # /map not in the default set -> ignored
    assert tracker.republish_items() == [tf]


def test_static_tracker_user_extended_set() -> None:
    """A user-extended set tracks the extra topics too (one latest per tracked topic)."""
    tracker = StaticTracker(frozenset({"/tf_static", "/map"}))
    tf = _item("/tf_static", t_ns=1)
    mp = _item("/map", t_ns=2)
    tracker.record(tf)
    tracker.record(mp)
    tracker.record(_item("/scan"))  # not tracked

    items = tracker.republish_items()
    assert len(items) == 2
    assert set(items) == {tf, mp}


def test_static_tracker_clear_resets() -> None:
    """clear() forgets all tracked items."""
    tracker = StaticTracker()
    tracker.record(_item("/tf_static"))
    tracker.clear()
    assert tracker.republish_items() == []


def test_clock_stamp_ns_splits_correctly() -> None:
    """clock_stamp_ns splits an absolute t_ns into (sec, nanosec) with 0 <= nanosec < 1e9."""
    assert clock_stamp_ns(0) == (0, 0)
    assert clock_stamp_ns(1_500_000_000) == (1, 500_000_000)  # sub-second remainder
    assert clock_stamp_ns(2_000_000_000) == (2, 0)  # exact second
    big = 1_716_950_000_123_456
    sec, nanosec = clock_stamp_ns(big)
    assert (sec, nanosec) == divmod(big, 1_000_000_000)
    assert 0 <= nanosec < 1_000_000_000
