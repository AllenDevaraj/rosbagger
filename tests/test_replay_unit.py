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

from rosbagger_replay.scheduler import Replayer, State  # noqa: E402
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


# --------------------------------------------------------------------------- #
# scheduler — the pure Replayer state machine (SC2 + SC3, D-06..D-09, W3/W4)
#
# These drive the ROS-free Replayer with a recording sink + recording sleep +
# (where needed) a fake monotonic clock — no real sleeping, no rclpy. SC2 (all
# six controls work) and SC3 (rate scaling halves/doubles the slept Δt; seek
# lands on the expected message index/timestamp) are proven deterministically.
# Select with `-k scheduler` (SC3 ones also match `-k 'rate or seek or loop or step'`).
# --------------------------------------------------------------------------- #


def _items(t_ns_list):
    """Build a list of ReplayItem with crafted t_ns (topic carries the index for assertions)."""
    return [
        ReplayItem(t_ns=t, topic=f"/t{i}", msgtype="std_msgs/msg/String", cdr=b"x")
        for i, t in enumerate(t_ns_list)
    ]


class _FakeClock:
    """A monotonic clock that advances by `step` seconds on each call (for the duration bound)."""

    def __init__(self, step=1.0):
        self._t = 0.0
        self._step = step

    def __call__(self):
        t = self._t
        self._t += self._step
        return t


def test_scheduler_play_full_publishes_all_in_order_then_done():
    """SC2 play: play()+run() publishes all N in order; end state DONE (loop=False)."""
    items = _items([0, 100, 200, 300])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None)
    r.play()
    r.run()

    assert recorded == items  # all N, in order
    assert [it.topic for it in recorded] == ["/t0", "/t1", "/t2", "/t3"]
    assert r.state is State.DONE


def test_scheduler_step_one_then_paused():
    """SC2 step: step()+run() publishes ONE -> PAUSED, cursor==1; a 2nd step publishes the next."""
    items = _items([0, 100, 200])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None)

    r.step()
    r.run()
    assert recorded == [items[0]]
    assert r.cursor == 1
    assert r.state is State.PAUSED

    r.step()
    r.run()
    assert recorded == [items[0], items[1]]
    assert r.cursor == 2
    assert r.state is State.PAUSED


def test_scheduler_pause_holds_cursor():
    """SC2 pause: play to max=2, pause() holds cursor 2; resume continues from 2 (no re-publish)."""
    items = _items([0, 100, 200, 300])
    recorded = []
    # First leg: a bounded run publishes exactly items[0:2] and stops.
    r = Replayer(items, recorded.append, sleep=lambda s: None, max_messages=2)
    r.play()
    r.run()
    assert recorded == [items[0], items[1]]
    assert r.cursor == 2

    # pause() holds the cursor; a fresh play()+run() (no bound) continues from index 2.
    r.pause()
    assert r.cursor == 2
    r._max_messages = None  # lift the bound for the resume leg
    r.play()
    r.run()
    assert recorded == items  # items[2:] appended, NOT re-publishing 0/1
    assert [it.topic for it in recorded] == ["/t0", "/t1", "/t2", "/t3"]


def test_scheduler_seek_lands_on_first_item_at_or_after_target():
    """SC3 seek: t_ns [0,100,200,300]; seek(150) lands index 2 (t_ns 200); skipped absent."""
    items = _items([0, 100, 200, 300])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None)

    r.seek(150)  # first t_ns >= 0+150 is 200 at index 2
    assert r.cursor == 2

    r.play()
    r.run()
    assert recorded == items[2:]  # only items[2], items[3]
    assert items[0] not in recorded and items[1] not in recorded  # skipped, never published
    assert r.state is State.DONE


def test_scheduler_seek_past_end_publishes_nothing_then_done():
    """SC3 seek-past-end: seek beyond last t_ns -> cursor==len; run() publishes nothing; DONE."""
    items = _items([0, 100, 200, 300])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None)

    r.seek(10_000)  # past the last t_ns (300)
    assert r.cursor == len(items)

    r.play()
    r.run()
    assert recorded == []
    assert r.state is State.DONE


def test_scheduler_rate_scales_sleep():
    """SC3 rate: items 100ms apart; rate=1.0 sleeps ~0.1; rate=2.0 halves it; first no pre-sleep."""
    spacing_ns = 100_000_000  # 100 ms
    items = _items([0, spacing_ns, 2 * spacing_ns, 3 * spacing_ns])

    slept_1x = []
    r1 = Replayer(items, lambda i: None, sleep=slept_1x.append, rate=1.0)
    r1.play()
    r1.run()
    # 4 items -> 3 inter-message sleeps; the FIRST publish incurs no pre-sleep.
    assert len(slept_1x) == 3
    assert all(s == pytest.approx(0.1) for s in slept_1x)

    slept_2x = []
    r2 = Replayer(items, lambda i: None, sleep=slept_2x.append, rate=2.0)
    r2.play()
    r2.run()
    assert len(slept_2x) == 3
    assert all(s == pytest.approx(0.05) for s in slept_2x)
    # The set_rate(2.0) schedule is exactly HALF the rate=1.0 schedule (SC3).
    assert all(s2 == pytest.approx(s1 / 2) for s1, s2 in zip(slept_1x, slept_2x, strict=True))


def test_scheduler_rate_invalid_raises():
    """SC3 rate guard: set_rate(0)/set_rate(-1)/rate=-1 ctor raise ValueError (no div-by-zero)."""
    r = Replayer(_items([0, 100]), lambda i: None, sleep=lambda s: None)
    with pytest.raises(ValueError, match="rate must be > 0"):
        r.set_rate(0)
    with pytest.raises(ValueError, match="rate must be > 0"):
        r.set_rate(-1)
    # construction-time validation too
    with pytest.raises(ValueError, match="rate must be > 0"):
        Replayer(_items([0, 100]), lambda i: None, rate=-1)


def test_scheduler_loop_restarts_at_end_of_stream():
    """SC2 loop: loop=True + max=2*N proves the cursor wraps to 0 and re-publishes from the top."""
    items = _items([0, 100, 200])
    n = len(items)
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=True, max_messages=2 * n)
    r.play()
    r.run()

    assert len(recorded) == 2 * n
    first_half = [it.topic for it in recorded[:n]]
    second_half = [it.topic for it in recorded[n:]]
    assert first_half == ["/t0", "/t1", "/t2"]
    assert second_half == first_half  # wrapped to 0 and re-published the same stream


def test_scheduler_loop_bound_exact_end_done_wins_over_loop_reset():
    """W4: loop=True + max==N over N items publishes EXACTLY N then DONE (bound wins at end)."""
    items = _items([0, 100, 200])
    n = len(items)
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=True, max_messages=n)
    r.play()
    r.run()

    # The bound trips on the final item where cursor==len; DONE wins over the loop-reset.
    assert len(recorded) == n  # NOT 2*N, NOT unbounded
    assert r.state is State.DONE  # NOT PLAYING


def test_scheduler_bounded_max_messages():
    """Bounded stop: max=2 over 9 items publishes exactly 2 then DONE (is-not-None, WR-01)."""
    items = _items([i * 100 for i in range(9)])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, max_messages=2)
    r.play()
    r.run()

    assert len(recorded) == 2
    assert r.cursor == 2
    assert r.state is State.DONE


def test_scheduler_bounded_max_messages_zero_means_zero():
    """WR-01: max=0 means ZERO publishes (is-not-None, not truthiness) -> immediate DONE."""
    items = _items([0, 100, 200])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, max_messages=0)
    r.play()
    r.run()

    assert recorded == []
    assert r.state is State.DONE


def test_scheduler_bounded_duration_halts_on_monotonic_clock():
    """WR-02: a fake monotonic clock + duration=D halts run() once the clock crosses D."""
    items = _items([i * 100 for i in range(9)])
    recorded = []
    # _FakeClock returns 0,1,2,3,... on successive calls (monotonic, NOT wall-clock).
    # run() samples the clock at entry (0), then once per duration check. With duration=4
    # the elapsed (clock()-start) crosses 4 only after several publishes -> a bounded,
    # deterministic halt driven entirely by the INJECTED monotonic clock.
    clock = _FakeClock(step=1.0)
    r = Replayer(items, recorded.append, sleep=lambda s: None, clock=clock, duration=4.0)
    r.play()
    r.run()

    # The run halts mid-stream (fewer than all 9 published) once the monotonic clock
    # crosses the deadline; it does NOT run to natural end, and ends DONE.
    assert 0 < len(recorded) < len(items)
    assert r.state is State.DONE


def test_scheduler_bounded_duration_zero_halts_before_first_publish():
    """WR-01/WR-02: duration=0 halts immediately (is-not-None, monotonic) -> zero pubs, DONE."""
    items = _items([0, 100, 200])
    recorded = []
    clock = _FakeClock(step=1.0)
    r = Replayer(items, recorded.append, sleep=lambda s: None, clock=clock, duration=0.0)
    r.play()
    r.run()

    assert recorded == []  # duration=0 is a real bound (NOT unbounded via truthiness)
    assert r.state is State.DONE
