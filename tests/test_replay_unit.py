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
    write_ros2_sqlite_bag_defless,
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


def test_scheduler_step_does_not_pace_inter_message_gap():
    """WR-01: a STEPPING advance publishes IMMEDIATELY — it must NOT pre-sleep the Δt gap.

    A step is an interactive single-advance (D-09): stepping across a long inter-message
    gap must not block the caller for that gap. Pacing is a PLAYING-only concern. We craft
    a 5-second gap between items, then step from index 0 to index 1: the step at cursor>0
    must record NO sleep of the inter-message Δt (5s/rate). (PLAYING the same stream WOULD
    sleep ~5s — proven below — so this is a genuine control-correctness lock, not a no-op.)
    """
    five_s_ns = 5_000_000_000  # 5 s between item[0] and item[1]
    items = _items([0, five_s_ns])

    # Step from index 0 -> 1 across the 5s gap; record every sleep call.
    slept_step = []
    r = Replayer(items, lambda i: None, sleep=slept_step.append)
    r.step()
    r.run()  # publishes items[0]; cursor 0 -> 1, no pre-sleep (cursor was 0)
    r.step()
    r.run()  # publishes items[1] from cursor 1 — a STEP must NOT pace the 5s gap
    # No sleep ever paced the 5s inter-message Δt during stepping (the pre-step at cursor>0).
    assert all(s < 1.0 for s in slept_step), f"step paced an inter-message gap: {slept_step}"
    assert five_s_ns / 1e9 not in slept_step

    # Contrast: PLAYING the SAME two-item stream DOES pace the 5s gap (one inter-message sleep).
    slept_play = []
    r2 = Replayer(items, lambda i: None, sleep=slept_play.append)
    r2.play()
    r2.run()
    assert slept_play == [pytest.approx(5.0)]  # play paces; step (above) did not


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


# --------------------------------------------------------------------------- #
# scheduler — thread-safety (Phase 18, SC1): run() on a worker thread while the
# main thread issues seek/set_rate/pause/loop with NO data race. The injected
# sleep is a CONTROLLABLE barrier (two threading.Events) so the interleave is
# deterministic — no real time.sleep, no flaky races (T-18-01-E). The default
# sleep's interruptibility (the _wake.wait/clear path) is exercised separately.
# Select with `-k 'threadsafe or interruptible or injected_sleep'`.
# --------------------------------------------------------------------------- #

import threading  # noqa: E402  (stdlib; the scheduler's only new dep is threading too)


class _BarrierSleep:
    """An INJECTED sleep that blocks on the FIRST call until the main thread releases it.

    The worker thread, on its first paced ``self._sleep(...)``, sets ``entered`` (so the
    main thread knows the worker is parked INSIDE a pre-publish wait, mid-run) and then
    blocks on ``release`` until the main thread issues its control + calls :meth:`go`.
    Subsequent sleeps are recorded and return immediately (the deterministic interleave
    is only needed once, to wedge the worker mid-run). Records every slept value so a
    test can assert the injected sleep was honored verbatim (T-18-01-C).
    """

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.slept = []
        self._first = True

    def __call__(self, seconds):
        self.slept.append(seconds)
        if self._first:
            self._first = False
            self.entered.set()
            self.release.wait(timeout=5.0)

    def go(self):
        self.release.set()


def test_scheduler_threadsafe_seek_midrun_no_lost_update():
    """SC1/T-18-01-A: a seek() issued WHILE run() executes on another thread is honored.

    The worker plays from index 0; after item[0] publishes it parks in the FIRST paced
    pre-publish sleep (the barrier). The main thread then seeks several items ahead and
    releases the barrier. The NEXT published item must be at/after the seek target and
    the cursor must advance FROM the seek index — no lost update (the cursor-unchanged
    advance guard must not clobber the concurrent seek).
    """
    items = _items([i * 100 for i in range(10)])  # t_ns 0,100,...,900
    recorded = []
    sleep = _BarrierSleep()
    r = Replayer(items, recorded.append, sleep=sleep)
    r.play()
    worker = threading.Thread(target=r.run)
    worker.start()

    # The worker published item[0], then parked in the first inter-message wait.
    assert sleep.entered.wait(timeout=5.0)
    assert recorded[0] is items[0]

    target_ns = 600  # first t_ns >= 0+600 is 600 at index 6
    r.seek(target_ns)
    sleep.go()
    worker.join(timeout=5.0)
    assert not worker.is_alive()

    # The next published item (after item[0]) is at/after the seek target — items 1..5
    # were SKIPPED by the mid-run seek (no lost update clobbering it back to index 1).
    after_seek = recorded[1:]
    assert after_seek, "the worker published nothing after the mid-run seek"
    assert after_seek[0].t_ns >= items[0].t_ns + target_ns
    assert after_seek[0] is items[6]
    # And the cursor advanced FROM the seek index (consecutive forward items 6..9).
    assert [it.topic for it in after_seek] == ["/t6", "/t7", "/t8", "/t9"]
    assert r.state is State.DONE


def test_scheduler_threadsafe_set_rate_midrun_takes_effect():
    """SC1: a set_rate(x) issued mid-run is observable via replayer.rate after the wake."""
    items = _items([i * 100 for i in range(10)])
    recorded = []
    sleep = _BarrierSleep()
    r = Replayer(items, recorded.append, sleep=sleep, rate=1.0)
    r.play()
    worker = threading.Thread(target=r.run)
    worker.start()

    assert sleep.entered.wait(timeout=5.0)
    r.set_rate(4.0)
    assert r.rate == 4.0  # observable immediately (lock-guarded mutation, lock-free read)
    sleep.go()
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert r.rate == 4.0


def test_scheduler_threadsafe_pause_midrun_returns_paused():
    """SC1: a pause() issued mid-run makes run() return with state == PAUSED (cursor held)."""
    items = _items([i * 100 for i in range(10)])
    recorded = []
    sleep = _BarrierSleep()
    r = Replayer(items, recorded.append, sleep=sleep)
    r.play()
    worker = threading.Thread(target=r.run)
    worker.start()

    assert sleep.entered.wait(timeout=5.0)
    assert recorded == [items[0]]  # only item[0] published before the park
    r.pause()
    sleep.go()
    worker.join(timeout=5.0)
    assert not worker.is_alive()

    # The pause arrived during the wait; run() re-read state and broke out -> PAUSED,
    # publishing no further items (the cursor is held for a later resume).
    assert r.state is State.PAUSED
    assert recorded == [items[0]]
    assert r.cursor == 1


def test_scheduler_default_sleep_is_interruptible():
    """T-18-01-B: with the DEFAULT sleep, a setter's wake cuts a long pacing wait short.

    Two items spaced 10s apart: without interruptibility the worker would block ~10s in
    the inter-message wait. A pause() from the main thread sets self._wake, so the default
    _interruptible_sleep returns PROMPTLY and run() honors the pause — proven by a generous
    wall-clock upper bound far below the 10s gap (and run() ending PAUSED, not DONE).
    """
    import time as _time

    ten_s_ns = 10_000_000_000
    items = _items([0, ten_s_ns])
    recorded = []
    r = Replayer(items, recorded.append)  # DEFAULT sleep == the interruptible bound method
    r.play()
    worker = threading.Thread(target=r.run)
    worker.start()

    # Give the worker a moment to publish item[0] and enter the 10s default wait, then
    # interrupt it. A tiny poll loop avoids racing the worker into the wait.
    deadline = _time.monotonic() + 2.0
    while recorded == [] and _time.monotonic() < deadline:
        _time.sleep(0.005)
    assert recorded == [items[0]]  # parked in the inter-message wait now

    t0 = _time.monotonic()
    r.pause()  # sets self._wake -> the default wait returns immediately
    worker.join(timeout=5.0)
    elapsed = _time.monotonic() - t0
    assert not worker.is_alive()
    assert elapsed < 5.0, f"the default wait was not interrupted (blocked {elapsed:.2f}s)"
    assert r.state is State.PAUSED
    assert recorded == [items[0]]  # the 2nd item was NOT published (paused mid-wait)


def test_scheduler_injected_sleep_still_honored():
    """T-18-01-C: an INJECTED sleep is used verbatim — the interruptible default does NOT apply.

    The recording ``sleep=lambda``/list seam the whole Phase-13 suite relies on must keep
    working: when the caller overrides ``sleep``, run() calls THAT callable (no _wake.wait
    substitution). We prove the injected sleep receives the exact paced Δt values.
    """
    spacing_ns = 100_000_000  # 100 ms
    items = _items([0, spacing_ns, 2 * spacing_ns])
    slept = []
    r = Replayer(items, lambda i: None, sleep=slept.append, rate=1.0)
    r.play()
    r.run()  # synchronous, no thread — the injected recording sleep must be honored

    assert slept == [pytest.approx(0.1), pytest.approx(0.1)]  # exactly the paced gaps


# --------------------------------------------------------------------------- #
# scheduler — in/out region loop (Phase 19, REP-03 / SC1): set_loop_region wraps
# a SNIPPET on repeat (cursor jumps from past t_out back to the first item at/after
# t_in), DISTINCT from the whole-bag loop (index-0 rewind). The region branch sits
# AFTER the bound guards (W4 — DONE/bound still wins) and takes precedence over the
# whole-bag _loop when both are on. Select with `-k region`.
# --------------------------------------------------------------------------- #


def test_scheduler_region_setters_normalize_and_read_back():
    """The region setters normalize in<=out and loop_region reads them back (both/neither)."""
    r = Replayer(_items([0, 100, 200]), lambda i: None, sleep=lambda s: None)
    assert r.loop_region is None  # no region by default

    r.set_loop_region(200, 500)
    assert r.loop_region == (200, 500)

    r.set_loop_region(500, 200)  # reversed -> normalized to (200, 500)
    assert r.loop_region == (200, 500)

    r.clear_loop_region()
    assert r.loop_region is None


def test_scheduler_region_setters_are_threadsafe_midrun():
    """SC4/T-19-01-A: a set_loop_region issued WHILE run() executes is honored race-free.

    Reuses the Phase-18 _BarrierSleep so the interleave is deterministic. The worker parks in
    the first paced wait after item[0]; the main thread sets a region [300, 600] + caps the run
    with max_messages so it terminates, releases the barrier, and joins. The region read is
    observable immediately (lock-guarded mutation, lock-free read) and the worker ends cleanly.
    """
    items = _items([i * 100 for i in range(10)])  # t_ns 0..900
    recorded = []
    sleep = _BarrierSleep()
    # max_messages caps the run so a region that would otherwise loop forever terminates.
    r = Replayer(items, recorded.append, sleep=sleep, max_messages=6)
    r.play()
    worker = threading.Thread(target=r.run)
    worker.start()

    assert sleep.entered.wait(timeout=5.0)  # parked mid-run after item[0]
    r.set_loop_region(300, 600)
    assert r.loop_region == (300, 600)  # observable immediately
    sleep.go()
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert r.state is State.DONE  # the max_messages bound terminated it (no infinite loop)


def test_scheduler_region_wrap_repeats():
    """SC1: with a region [200,500], playback wraps the snippet on repeat (NOT a rewind to 0).

    The region branch wraps the cursor only AFTER it passes ``t_out`` — it does not auto-seek
    into the region on the first pass. So the realistic flow (the one the 19-03 panel drives) is
    to seek to the in-bound first, then play; the run then stays inside the region and repeats.
    """
    items = _items([i * 100 for i in range(10)])  # t_ns 0,100,...,900
    recorded = []
    # Cap at 10 publishes so we observe ≥2 passes through the 4-item region then stop.
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=False, max_messages=10)
    r.set_loop_region(200, 500)
    r.seek(200)  # the panel seeks to t_in when enabling region-loop (offset == t_in, t0==0)
    r.play()
    r.run()

    # Every published item is inside the region [200..500]; the snippet repeats (never t_ns 0).
    published_t = [it.t_ns for it in recorded]
    assert all(200 <= t <= 500 for t in published_t), published_t
    assert 0 not in published_t  # NOT a whole-bag rewind to index 0
    # The region's four items {200,300,400,500} cycle in order across the passes.
    assert published_t[:4] == [200, 300, 400, 500]
    assert published_t[4] == 200  # wrapped back to the in-bound, not to 0


def test_scheduler_region_plus_max_messages_bound_wins_done():
    """W4: a region + a max_messages bound stops at DONE on the bound — the bound beats the wrap."""
    items = _items([i * 100 for i in range(10)])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, max_messages=3)
    r.set_loop_region(200, 800)
    r.play()
    r.run()

    assert len(recorded) == 3  # exactly the bound — the region wrap did not defeat it
    assert r.state is State.DONE


def test_scheduler_clear_region_restores_whole_bag_loop():
    """clear_loop_region restores the EXACT whole-bag loop=True behavior (index-0 rewind)."""
    n = 4
    items = _items([i * 100 for i in range(n)])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=True, max_messages=2 * n)
    r.set_loop_region(100, 200)
    r.clear_loop_region()  # back to whole-bag loop
    r.play()
    r.run()

    # Whole-bag loop=True + max=2*n: the full stream republishes from index 0 (NOT the region).
    assert [it.t_ns for it in recorded] == [0, 100, 200, 300, 0, 100, 200, 300]


def test_scheduler_clear_region_restores_no_loop_done():
    """clear_loop_region with loop=False restores the clean whole-bag DONE at end-of-stream."""
    items = _items([0, 100, 200])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=False)
    r.set_loop_region(0, 100)
    r.clear_loop_region()
    r.play()
    r.run()

    assert [it.t_ns for it in recorded] == [0, 100, 200]  # whole bag once, then DONE
    assert r.state is State.DONE


def test_scheduler_region_precedence_over_whole_bag_loop():
    """A region wins over whole-bag loop=True: the cursor wraps to the in-index, NOT index 0."""
    items = _items([i * 100 for i in range(10)])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None, loop=True, max_messages=10)
    r.set_loop_region(300, 500)
    r.seek(300)  # seek into the region first (the panel's flow)
    r.play()
    r.run()

    published_t = [it.t_ns for it in recorded]
    assert all(300 <= t <= 500 for t in published_t), published_t
    assert 0 not in published_t  # the region wins; no whole-bag rewind to 0
    assert published_t[:3] == [300, 400, 500]
    assert published_t[3] == 300  # wrapped to the in-bound


def test_scheduler_region_in_bound_past_end_done():
    """An in-bound past the last t_ns resolves to DONE on wrap — no infinite no-publish loop."""
    items = _items([0, 100, 200, 300])  # last t_ns is 300
    recorded = []
    # in-bound 1000 is past the end; out-bound 2000 keeps the region "active" until the wrap.
    r = Replayer(items, recorded.append, sleep=lambda s: None, max_messages=100)
    r.set_loop_region(1000, 2000)
    r.play()
    r.run()

    # Nothing is in [1000,2000], so the whole stream plays once, then the wrap scan finds no
    # item at/after 1000 -> cursor == len -> DONE (not an infinite empty loop).
    assert [it.t_ns for it in recorded] == [0, 100, 200, 300]
    assert r.state is State.DONE


# --------------------------------------------------------------------------- #
# Phase 21 (REP-05) library plumbing: the --start-paused mapping is "do not play()"
# -> run() publishes 0 and returns PAUSED; the build_publish_sink remap kwarg keeps
# the no-kwargs 2-tuple/sink.tracker back-compat. (The remap republish-on-new-name +
# /clock are -m live proofs; the CLI flag forwarding is in 21-02.)
# --------------------------------------------------------------------------- #


def test_scheduler_not_played_publishes_nothing():
    """The --start-paused mapping: a Replayer never play()-ed publishes 0 on run(), stays PAUSED."""
    items = _items([0, 100, 200])
    recorded = []
    r = Replayer(items, recorded.append, sleep=lambda s: None)
    # NOTE: no r.play() — this is exactly what replay(start_paused=True) does.
    r.run()
    assert recorded == []
    assert r.state is State.PAUSED


# --------------------------------------------------------------------------- #
# cli — the thin rosbagger-replay CLI (Plan 03), via typer's CliRunner (ENV=offline)
# --------------------------------------------------------------------------- #
#
# These run in the ROS-free uv venv. The CLI's command body lazy-imports the package
# front door (`from rosbagger_replay import replay_bag as replay_api`); we MOCK that front
# door by monkeypatching the `replay_bag` ATTRIBUTE on the `rosbagger_replay` package so no
# real ROS runs (mirrors the Phase-12 attribute-patch discipline — NOT a brittle string
# target). The app has a SINGLE command, so typer flattens it: it is invoked as
# `rosbagger-replay <bag> [opts]` (the command name is optional), so the tests invoke the
# flat form with the BAG positional first. `--help` builds purely from the typer decorators
# (no ROS import), so it exits 0 and we can grep the help text. A NoMessagesToReplayError
# raised by the mocked API must surface as a clean Exit(1) (the @_capability_errors
# wrapper) — CliRunner sees a SystemExit, never the raw RuntimeError escaping.

from typer.testing import CliRunner  # noqa: E402

import rosbagger_replay  # noqa: E402
from rosbagger_replay.cli import app  # noqa: E402
from rosbagger_replay.errors import NoMessagesToReplayError  # noqa: E402

_runner = CliRunner()


def test_cli_replay_help_exits_zero():
    """``rosbagger-replay --help`` exits 0 (help builds without any ROS import)."""
    result = _runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_cli_replay_help_documents_end_folded_into_duration():
    """W5: ``--help`` documents that --end is folded into --duration (D-10 accounted for).

    The locked D-10 flag list names "optional --duration/--end"; this v1 CLI implements
    --duration and folds --end into it. The help text must SAY SO (not silently drop --end),
    so grep the rendered help for both "--end" and "--duration".
    """
    result = _runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--duration" in result.output
    assert "--end" in result.output  # explicitly accounted for, not silently dropped


def test_cli_replay_parses_and_forwards_flags(monkeypatch):
    """``replay BAG --rate 5 --max-messages 3 --topics /imu`` forwards parsed flags to the API.

    The package front door is mocked (attribute patch on the `rosbagger_replay` package, the
    target the CLI's lazy `from rosbagger_replay import replay_bag` resolves), so no ROS runs.
    Asserts the call lands with rate=5.0, max_messages=3, topics={"/imu"}.
    """
    calls = {}

    def fake_replay_bag(bag, **kwargs):
        calls["bag"] = bag
        calls.update(kwargs)
        return 3

    monkeypatch.setattr(rosbagger_replay, "replay_bag", fake_replay_bag)

    result = _runner.invoke(
        app, ["/tmp/bag", "--rate", "5", "--max-messages", "3", "--topics", "/imu"]
    )

    assert result.exit_code == 0, result.output
    assert calls["bag"] == "/tmp/bag"
    assert calls["rate"] == 5.0
    assert calls["max_messages"] == 3
    assert calls["topics"] == {"/imu"}
    assert "Published 3 messages" in result.output


def test_cli_replay_topics_omitted_forwards_none(monkeypatch):
    """With no --topics, the CLI forwards ``topics=None`` (publish everything), not an empty set."""
    calls = {}

    def fake_replay_bag(bag, **kwargs):
        calls.update(kwargs)
        return 9

    monkeypatch.setattr(rosbagger_replay, "replay_bag", fake_replay_bag)

    result = _runner.invoke(app, ["/tmp/bag"])
    assert result.exit_code == 0, result.output
    assert calls["topics"] is None
    assert calls["rate"] == 1.0  # default
    assert calls["loop"] is False  # default


def test_cli_replay_no_messages_exits_one_cleanly(monkeypatch):
    """A NoMessagesToReplayError from the API surfaces as a clean Exit(1) — no traceback.

    The mocked front door raises the typed teaching error; ``@_capability_errors`` catches
    it and raises ``typer.Exit(1)``. CliRunner must see a clean ``SystemExit`` (code 1) with
    the teaching message printed — and crucially NO ``NoMessagesToReplayError`` escaping
    (which would mean a traceback leaked). Mirrors the record CLI error test.
    """

    def fake_replay_bag(bag, **kwargs):
        raise NoMessagesToReplayError(bag_paths=bag, topics=kwargs.get("topics"))

    monkeypatch.setattr(rosbagger_replay, "replay_bag", fake_replay_bag)

    result = _runner.invoke(app, ["/tmp/bag", "--topics", "/nope"])

    assert result.exit_code == 1  # clean Exit(1), not a crash
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, NoMessagesToReplayError)
    assert "No messages to replay" in result.output


def test_cli_replay_help_exposes_parity_flags():
    """SC1: --help exposes the Phase-21 parity flags alongside the existing ones."""
    result = _runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for flag in (
        "--clock",
        "--delay",
        "--remap",
        "--start-paused",
        "-p",
        "--region-start",
        "--region-end",
    ):
        assert flag in result.output, f"{flag} missing from --help:\n{result.output}"


def test_cli_replay_help_documents_deferred_services():
    """SC3: --help documents the deferred runtime services + single-pass region stop."""
    result = _runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # At least one deferred runtime service is named, and the single-pass deferral is noted.
    assert "toggle_paused" in result.output or "~/seek" in result.output
    assert "single-pass" in result.output


def test_cli_replay_forwards_parity_flags(monkeypatch):
    """SC2: --clock/--delay/--start-paused/--region-start/--region-end forward the right kwargs."""
    calls = {}

    def fake_replay_bag(bag, **kwargs):
        calls.update(kwargs)
        return 0

    monkeypatch.setattr(rosbagger_replay, "replay_bag", fake_replay_bag)

    result = _runner.invoke(
        app,
        [
            "/tmp/bag",
            "--clock",
            "--delay",
            "2",
            "--start-paused",
            "--region-start",
            "1",
            "--region-end",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls["publish_clock"] is True
    assert calls["delay"] == 2.0
    assert calls["start_paused"] is True
    assert calls["region_start"] == 1.0
    assert calls["region_end"] == 3.0

    # The -p short alias also flips start_paused.
    calls.clear()
    result = _runner.invoke(app, ["/tmp/bag", "-p"])
    assert result.exit_code == 0, result.output
    assert calls["start_paused"] is True


def test_cli_replay_remap_parses_pairs(monkeypatch):
    """--remap a:=b --remap c:=d -> remap={'a':'b','c':'d'}; no --remap -> remap=None."""
    calls = {}

    def fake_replay_bag(bag, **kwargs):
        calls.update(kwargs)
        return 0

    monkeypatch.setattr(rosbagger_replay, "replay_bag", fake_replay_bag)

    result = _runner.invoke(app, ["/tmp/bag", "--remap", "a:=b", "--remap", "c:=d"])
    assert result.exit_code == 0, result.output
    assert calls["remap"] == {"a": "b", "c": "d"}

    calls.clear()
    result = _runner.invoke(app, ["/tmp/bag"])
    assert result.exit_code == 0, result.output
    assert calls["remap"] is None


def test_cli_replay_remap_malformed_errors_cleanly(monkeypatch):
    """A malformed --remap (no ':=') is a clean usage error, not a raw traceback."""
    monkeypatch.setattr(rosbagger_replay, "replay_bag", lambda bag, **kwargs: 0)
    result = _runner.invoke(app, ["/tmp/bag", "--remap", "foo"])
    assert result.exit_code != 0
    # typer renders BadParameter as a usage error (SystemExit), not an escaping exception.
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_source_standard_def_less_bag_without_typestore(tmp_path):
    """load_items opens a standard def-less bag with NO default_typestore (T2 fallback).

    Previously load_items opened a raw AnyReader, so a bare load_items(real_db3) raised the
    no-defs AnyReaderError — the TUI replay panel's exact crash. It now routes through the
    shared open_bag chokepoint, which falls back to the env-resolved typestore.
    """
    bag = write_ros2_sqlite_bag_defless(tmp_path / "defless")
    items = load_items(bag)  # no default_typestore — the fallback resolves it
    assert len(items) == 9  # 3 topics x 3 messages
    assert all(isinstance(it.cdr, bytes) for it in items)
