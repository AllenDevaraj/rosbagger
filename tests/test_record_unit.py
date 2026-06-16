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

from rosbagger_record import (
    McapStorageUnavailableError,
    NoTopicsMatchedError,
    RosNotAvailableError,
    record,
)
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


def test_select_invalid_regex_raises_typed_pattern_error():
    """A malformed --regex raises InvalidPatternError (clean teaching), not a raw re.error.

    Regression for the audit bug: select_topics passed the pattern straight to re.search, so a
    user typo got the programming-bug (traceback) treatment. It is now compiled and re.error is
    converted to a typed InvalidPatternError the CLI's _capability_errors presents cleanly.
    """
    from rosbagger_record import InvalidPatternError

    discovered = {"/a": "T", "/b": "U"}
    with pytest.raises(InvalidPatternError) as excinfo:
        select_topics(discovered, regex="[unclosed")
    err = excinfo.value
    assert err.kind == "regex"
    assert err.pattern == "[unclosed"
    assert "[unclosed" in str(err)
    # The same applies to a malformed --exclude.
    with pytest.raises(InvalidPatternError):
        select_topics(discovered, all_topics=True, exclude="(")


def test_select_is_deterministic_and_preserves_discovered_order():
    """Output iterates ``discovered`` insertion order (stable) and keeps the type strings."""
    discovered = {"/z": "Z", "/a": "A", "/m": "M"}
    assert list(select_topics(discovered, all_topics=True).items()) == [
        ("/z", "Z"),
        ("/a", "A"),
        ("/m", "M"),
    ]


# --------------------------------------------------------------------------- #
# _missing_positional_topics — the record warning's pure set difference (no ROS)
# --------------------------------------------------------------------------- #


def test_missing_positional_topics_reports_partial_typo():
    """`record /real /typo` -> the unpublished /typo is reported (the partial-drop warning)."""
    from rosbagger_record.record import _missing_positional_topics

    discovered = {"/real": "T"}
    assert _missing_positional_topics(["/real", "/typo"], discovered, all_topics=False) == ["/typo"]


def test_missing_positional_topics_empty_for_all_topics_and_no_names():
    """all_topics (or no positional names) makes no per-name request -> nothing 'missing'."""
    from rosbagger_record.record import _missing_positional_topics

    discovered = {"/a": "T"}
    assert _missing_positional_topics(["/x"], discovered, all_topics=True) == []
    assert _missing_positional_topics([], discovered, all_topics=False) == []


# --------------------------------------------------------------------------- #
# _adapt_subscription_qos — match publishers' offered QoS (no ROS; pure decision)
# --------------------------------------------------------------------------- #


def test_adapt_qos_downgrades_to_best_effort_for_best_effort_publisher():
    """A BEST_EFFORT publisher downgrades the subscription so it is not silently dropped."""
    from types import SimpleNamespace

    from rosbagger_record.record import _adapt_subscription_qos

    qos = SimpleNamespace(reliability="RELIABLE", durability="VOLATILE")
    infos = [
        SimpleNamespace(qos_profile=SimpleNamespace(reliability="BEST", durability="VOLATILE")),
    ]
    _adapt_subscription_qos(qos, infos, best_effort="BEST", transient_local="TL")
    assert qos.reliability == "BEST"
    assert qos.durability == "VOLATILE"  # unchanged (no TRANSIENT_LOCAL publisher)


def test_adapt_qos_adopts_transient_local_and_keeps_reliable_default():
    """A TRANSIENT_LOCAL publisher is adopted; all-RELIABLE publishers keep RELIABLE."""
    from types import SimpleNamespace

    from rosbagger_record.record import _adapt_subscription_qos

    qos = SimpleNamespace(reliability="RELIABLE", durability="VOLATILE")
    infos = [
        SimpleNamespace(qos_profile=SimpleNamespace(reliability="RELIABLE", durability="TL")),
        SimpleNamespace(qos_profile=SimpleNamespace(reliability="RELIABLE", durability="VOLATILE")),
    ]
    _adapt_subscription_qos(qos, infos, best_effort="BEST", transient_local="TL")
    assert qos.reliability == "RELIABLE"  # no BEST_EFFORT publisher -> stays reliable
    assert qos.durability == "TL"  # any TRANSIENT_LOCAL publisher -> adopt it


def test_adapt_qos_no_publishers_leaves_default():
    """With no visible publishers the QoS is left at the reliable depth-10 default."""
    from types import SimpleNamespace

    from rosbagger_record.record import _adapt_subscription_qos

    qos = SimpleNamespace(reliability="RELIABLE", durability="VOLATILE")
    _adapt_subscription_qos(qos, [], best_effort="BEST", transient_local="TL")
    assert qos.reliability == "RELIABLE"
    assert qos.durability == "VOLATILE"


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

from rosbagger_record.record import _check_storage, _run, _should_stop  # noqa: E402


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
# _run — the duration-bounded spin loop (WR-03 closes the coverage gap), rclpy
# MOCKED via sys.modules + a monotonic-clock seam (WR-01/WR-02 locked here)
# --------------------------------------------------------------------------- #
#
# WHY THIS EXISTS (WR-03): _should_stop is unit-tested in isolation above, but _run —
# the function that BUILDS the deadline (`time.monotonic() + duration if duration is
# not None else None`) and drives the spin loop — previously had ZERO coverage (the
# mocked record() tests monkeypatch _run away; the live test only drives --max-messages).
# That let the WR-01 falsy bug (`if duration` turning `--duration 0` into an UNBOUNDED
# record) and the WR-02 wall-clock deadline ship untested. These drive _run directly
# with `rclpy` injected (ok()->True, spin_once a no-op) and a FAKE monotonic clock
# (monkeypatch ri.time.monotonic) so the loop terminates deterministically offline.
#
# CLOCK SEAM (WR-02): _run now reads time.monotonic() (NOT time.time()), so we patch
# `monotonic` on the module's `time` reference. The clock is a scripted iterator: the
# 1st read builds the deadline, each later read is a per-spin _should_stop check.


def _fake_monotonic(monkeypatch, values):
    """Patch ``record.time.monotonic`` to yield ``values`` in order (a scripted clock).

    A safety sentinel after the scripted reads raises if the loop spins more times than
    expected — so a regression that fails to stop (e.g. the WR-01 falsy bug returning to
    an unbounded deadline) surfaces as a loud StopIteration-style error, NOT a hang.
    """
    import rosbagger_record.record as ri

    clock = iter(values)

    def _next() -> float:
        try:
            return next(clock)
        except StopIteration:  # pragma: no cover - only hit if the loop fails to stop
            raise AssertionError(
                "_run read the clock more times than scripted — it did not stop at the "
                "deadline (WR-01/WR-02 regression: loop is effectively unbounded)."
            ) from None

    monkeypatch.setattr(ri.time, "monotonic", _next)
    return ri


def test_run_stops_at_duration_deadline(monkeypatch):
    """``_run`` terminates once the monotonic clock reaches the ``--duration`` deadline.

    rclpy.ok() stays True and spin_once is a no-op, so ONLY the deadline can end the loop.
    The scripted clock: 100.0 (build deadline=100.05), 100.0 (check#1 < deadline -> spin),
    100.06 (check#2 >= deadline -> break). If the deadline arithmetic regressed, the loop
    would exhaust the clock and the sentinel would fail loudly rather than hang.
    """
    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    _fake_monotonic(monkeypatch, [100.0, 100.0, 100.06])

    _run(MagicMock(), {"n": 0}, duration=0.05)  # must RETURN, not hang

    # one spin happened (check#1 was below the deadline), then check#2 broke the loop
    assert fake_rclpy.spin_once.call_count == 1


def test_run_duration_zero_stops_immediately(monkeypatch):
    """WR-01 REGRESSION: ``--duration 0`` stops at once — it is NOT an unbounded record.

    With the old truthiness guard (`deadline = ... if duration else None`), ``duration=0``
    fell to ``deadline=None`` (unbounded) and this loop would spin forever (only SIGINT/
    max_messages could end it). With the ``is not None`` fix, deadline == now at the first
    check, ``_should_stop`` is True immediately, and NO spin happens. The scripted clock
    has exactly two reads (build + the single check); a third read means it failed to stop.
    """
    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    # build: deadline = 200.0 + 0 = 200.0 ; check#1: now=200.0 >= 200.0 -> stop at once
    _fake_monotonic(monkeypatch, [200.0, 200.0])

    _run(MagicMock(), {"n": 0}, duration=0)  # must RETURN immediately, never spin

    fake_rclpy.spin_once.assert_not_called()  # stopped before the first spin (duration 0)


def test_run_unbounded_stops_when_rclpy_not_ok(monkeypatch):
    """With no bounds, ``_run`` spins until ``rclpy.ok()`` flips False (SIGINT — D-09).

    Covers the unbounded branch: deadline stays None (duration omitted), max_messages None,
    so only ``rclpy.ok()`` ends the loop. ok() returns True for two spins then False. With
    ``duration`` omitted the deadline build takes the ``else None`` branch WITHOUT reading
    the clock, so the clock is read once per True-iteration (the _should_stop check) — two
    reads total; the final ok()->False exits before any further read.
    """
    fake_rclpy = MagicMock()
    fake_rclpy.ok.side_effect = [True, True, False]  # two spins, then SIGINT
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    _fake_monotonic(monkeypatch, [0.0, 0.0])  # no deadline build read + 2 per-spin checks

    _run(MagicMock(), {"n": 0})  # unbounded -> ends only when ok() goes False

    assert fake_rclpy.spin_once.call_count == 2  # spun until ok() flipped False


def test_run_stops_immediately_when_stop_event_preset(monkeypatch):
    """C8: a stop_event already set breaks _run BEFORE the first spin (cooperative early-stop).

    rclpy.ok() stays True (never SIGINT) and there is no bound, so ONLY the stop_event can end
    the loop — it is checked before _should_stop and before spin_once, so a pre-set event stops
    immediately (the close-path fix: the bag's finally still finalizes; the join returns at once).
    """
    import threading

    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)

    ev = threading.Event()
    ev.set()
    _run(MagicMock(), {"n": 0}, stop_event=ev)

    fake_rclpy.spin_once.assert_not_called()  # broke before any spin (stop wins immediately)


def test_run_stops_at_next_spin_when_stop_event_set_midloop(monkeypatch):
    """C8: a stop_event set mid-loop ends _run at the NEXT iteration's check — no bound needed."""
    import threading

    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)

    ev = threading.Event()
    spins = {"n": 0}

    def spin(_node, timeout_sec):  # noqa: ARG001 - rclpy.spin_once signature
        spins["n"] += 1
        if spins["n"] >= 3:
            ev.set()  # a closeEvent on another thread would do this

    fake_rclpy.spin_once.side_effect = spin
    _run(MagicMock(), {"n": 0}, stop_event=ev)

    assert spins["n"] == 3  # spun 3×, then the stop_event broke the loop before a 4th spin


# --------------------------------------------------------------------------- #
# WR-04 re-entrant rclpy lifecycle (C2/C5): record()/list_topics() must NOT init or
# shut down a context they did NOT create — a shared GUI context (a live replay node)
# has to survive a record/discovery scan. rclpy MOCKED via sys.modules (Pitfall 6).
# --------------------------------------------------------------------------- #


def test_list_topics_reentrant_preserves_shared_context(monkeypatch):
    """C5/WR-04: with a context already up (``rclpy.ok()`` True), ``list_topics`` neither inits
    nor shuts it down — so a live replay node's shared context survives a discovery scan."""
    import rosbagger_record.record as ri

    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True  # a context already exists (e.g. a live replay node)
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setattr(ri, "discover_topics", lambda node: {"/a": "std_msgs/msg/String"})

    assert ri.list_topics() == {"/a": "std_msgs/msg/String"}
    fake_rclpy.init.assert_not_called()
    fake_rclpy.shutdown.assert_not_called()
    fake_rclpy.create_node.return_value.destroy_node.assert_called_once()


def test_list_topics_owning_context_inits_and_shuts_down(monkeypatch):
    """WR-04: with NO pre-existing context (``rclpy.ok()`` False), ``list_topics`` inits + shuts
    down the context it created — the standalone-CLI path is byte-for-byte unchanged."""
    import rosbagger_record.record as ri

    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = False
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setattr(ri, "discover_topics", lambda node: {})

    ri.list_topics()
    fake_rclpy.init.assert_called_once()
    fake_rclpy.shutdown.assert_called_once()


def test_record_reentrant_preserves_shared_context(monkeypatch):
    """C2/WR-04: ``record()`` with a context already up neither inits nor shuts it down — so an
    unconditional ``rclpy.shutdown()`` can no longer kill a live replay node's shared context.

    The full record pipeline (storage check / discover / select / writer / subscribe / run loop)
    is stubbed so the test isolates the rclpy LIFECYCLE; the writer's ``close()`` still fires in
    the finally (a MagicMock), proving teardown order is unchanged while init/shutdown are skipped.
    """
    import rosbagger_record.record as ri

    fake_rclpy = MagicMock()
    fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setattr(ri, "_check_storage", lambda storage: None)
    monkeypatch.setattr(ri, "discover_topics", lambda node: {"/a": "std_msgs/msg/String"})
    monkeypatch.setattr(ri, "select_topics", lambda *a, **k: {"/a": "std_msgs/msg/String"})
    writer = MagicMock()
    monkeypatch.setattr(ri, "_make_writer", lambda out, storage: writer)
    monkeypatch.setattr(ri, "_subscribe_and_record", lambda *a, **k: None)
    monkeypatch.setattr(ri, "_run", lambda *a, **k: None)

    ri.record(["/a"], "out.bag", duration=1.0)
    fake_rclpy.init.assert_not_called()
    fake_rclpy.shutdown.assert_not_called()
    # the bag is STILL finalized (finally) — only init/shutdown skip
    writer.close.assert_called_once()


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

    # _subscribe_and_record now adapts the subscription QoS to the topic's publishers, so the
    # node's get_publishers_info_by_topic must be iterable (no publishers -> keep the default).
    fake_rclpy.create_node.return_value.get_publishers_info_by_topic.return_value = []

    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    # `from rclpy.qos import ...` is a SUBMODULE import — a bare MagicMock for `rclpy` does not
    # satisfy it, so inject the qos submodule explicitly (its QoSProfile/policy attrs auto-mock).
    monkeypatch.setitem(sys.modules, "rclpy.qos", fake_rclpy.qos)
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
    empty; ``record()`` must raise the teaching ``NoTopicsMatchedError`` (WR-04 — a typed
    error the CLI catches cleanly, NOT a bare ``ValueError``) BEFORE opening the writer
    (assert ``SequentialWriter.open`` was never called — nothing was created). The error
    carries the structured selection inputs + what WAS discoverable for the teaching line.
    """
    record_impl, writer = mocked_ros
    monkeypatch.setattr(
        record_impl,
        "discover_topics",
        lambda node, **kw: {"/other": "std_msgs/msg/String"},  # not the requested topic
    )

    with pytest.raises(NoTopicsMatchedError, match="No live topics matched") as excinfo:
        record_impl.record(["/telemetry"], "/tmp/out", storage="mcap")

    err = excinfo.value
    assert err.topics == ["/telemetry"]  # structured: what the user asked for
    assert err.discovered == ["/other"]  # structured: what was actually live
    assert "/other" in str(err)  # the teaching line names what IS discoverable
    assert "rosbagger-record list" in str(err)  # ...and the remedy
    writer.open.assert_not_called()  # bailed out before opening the writer
    writer.close.assert_not_called()  # nothing to finalize — writer never opened


# --------------------------------------------------------------------------- #
# cli — the thin rosbagger-record CLI (Plan 03), via typer's CliRunner (ENV=offline)
# --------------------------------------------------------------------------- #
#
# These run in the ROS-free uv venv. `--help` for the app + both verbs must exit 0
# (help text is built from the typer decorators, NO ROS import). Invoking `list` /
# `record` with ROS absent must surface the package's RosNotAvailableError as a CLEAN
# Exit(1) (the @_capability_errors wrapper) — CliRunner sees a SystemExit, NOT the raw
# RosNotAvailableError escaping. We pair CliRunner with the `no_ros` meta-path blocker so
# the lazy `import rclpy` inside record.py raises ImportError (which _require_ros turns
# into the teaching error) deterministically, regardless of the host's ROS-on-PYTHONPATH.

from typer.testing import CliRunner  # noqa: E402

from rosbagger_record.cli import Storage, app  # noqa: E402

_runner = CliRunner()


def test_cli_app_help_exits_zero():
    """``rosbagger-record --help`` exits 0 and shows the app help (no ROS import)."""
    result = _runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # both verbs are advertised in the top-level help
    assert "list" in result.output
    assert "record" in result.output


def test_cli_list_help_exits_zero():
    """``rosbagger-record list --help`` exits 0 (help builds without ROS)."""
    result = _runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0


def test_cli_record_help_exits_zero_and_shows_storage_mcap_default():
    """``record --help`` exits 0 and shows ``--storage`` with the mcap default (D-08)."""
    result = _runner.invoke(app, ["record", "--help"])
    assert result.exit_code == 0
    assert "--storage" in result.output
    # the default is mcap (D-08 not weakened) — typer renders the default in the help
    assert "mcap" in result.output


def test_cli_record_storage_rejects_invalid_choice_at_parse_time():
    """``--storage bogus`` is REJECTED AT PARSE TIME (W2): a constrained choice, not a bare str.

    No ROS is touched — the Enum-backed choice fails during click parsing (exit code 2,
    the usage-error code), proving the parse-time constraint the threat model claims
    (T-12-02). A bare ``str`` option would have accepted ``bogus`` and only failed later.
    """
    result = _runner.invoke(app, ["record", "/telemetry", "-o", "/tmp/out", "--storage", "bogus"])
    assert result.exit_code == 2  # click usage error (invalid choice), before any ROS work
    # Either the bad value or the allowed set is named in the parse-error message.
    assert "bogus" in result.output or "mcap" in result.output


def test_cli_record_requires_output_option():
    """``record`` with no ``-o`` is a parse error (the output is required), no ROS touched."""
    result = _runner.invoke(app, ["record", "/telemetry"])
    assert result.exit_code == 2  # missing required option -> click usage error


def test_cli_list_ros_absent_exits_one_cleanly(no_ros):
    """``list`` with ROS absent exits 1 via Exit(1) — SystemExit, NOT a raw RuntimeError.

    The `no_ros` blocker makes the lazy `import rclpy` fail; `_require_ros()` raises the
    teaching ``RosNotAvailableError``; ``@_capability_errors`` catches it and raises
    ``typer.Exit(1)``. CliRunner surfaces that as a ``SystemExit`` with code 1 — assert the
    raw ``RosNotAvailableError`` did NOT escape (no traceback for a capability error).
    """
    result = _runner.invoke(app, ["list"])
    assert result.exit_code == 1
    # The exception that reached CliRunner (if any) is a clean SystemExit from typer.Exit,
    # never the raw RosNotAvailableError (which would mean a traceback leaked).
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, RosNotAvailableError)


def test_cli_record_ros_absent_exits_one_cleanly(no_ros):
    """``record`` with ROS absent exits 1 cleanly (SystemExit), no raw RuntimeError escapes."""
    result = _runner.invoke(app, ["record", "/telemetry", "-o", "/tmp/rec"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, RosNotAvailableError)


def test_cli_storage_enum_values_are_mcap_and_sqlite3():
    """The ``--storage`` choice set is exactly {mcap, sqlite3} (D-08 + the sqlite3 escape)."""
    assert {s.value for s in Storage} == {"mcap", "sqlite3"}
    assert Storage.MCAP.value == "mcap"  # the default


def test_cli_record_empty_selection_exits_one_cleanly(monkeypatch):
    """WR-04 REGRESSION: a mistyped/unpublished topic exits 1 with a clean teaching line.

    The most common day-one mistake — recording a topic that is not currently published —
    must NOT dump a raw ``ValueError`` traceback. We mock the full ROS stack so the CLI
    front door clears ``_require_ros()`` and the storage gate (``mcap`` registered), then
    force discovery to return a map WITHOUT the requested topic so selection is empty.
    ``record()`` raises the typed ``NoTopicsMatchedError``; ``@_capability_errors`` catches
    it and raises ``typer.Exit(1)``. CliRunner must see a clean ``SystemExit`` (code 1) with
    the teaching message in the output — and crucially NO ``NoTopicsMatchedError`` /
    ``ValueError`` escaping (which would mean a traceback leaked, the bug WR-04 fixes).

    NOTE: this drives the REAL `record_topics` front door through the CLI (not the impl
    directly), so it exercises the full WR-04 path end to end: lazy import -> _require_ros
    (mocked OK) -> .record impl -> empty selection -> typed error -> decorator -> Exit(1).
    """
    import rosbagger_record.record as record_impl

    # Mock the ROS stack so _require_ros() (in the package front door) succeeds and the
    # impl's lazy `import rclpy` / `import rosbag2_py` bind these mocks. mcap is registered
    # so the storage gate passes and we actually reach the empty-selection branch.
    fake_rclpy = MagicMock()
    fake_rosbag2_py = MagicMock()
    fake_rosbag2_py.get_registered_writers.return_value = {"mcap", "sqlite3"}
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    monkeypatch.setitem(sys.modules, "rosbag2_py", fake_rosbag2_py)

    # Discovery returns a map that does NOT contain the requested /telemetry -> empty
    # selection -> NoTopicsMatchedError raised BEFORE any writer is opened.
    monkeypatch.setattr(
        record_impl,
        "discover_topics",
        lambda node, **kw: {"/other": "std_msgs/msg/String"},
    )

    result = _runner.invoke(app, ["record", "/telemetry", "-o", "/tmp/rec"])

    assert result.exit_code == 1  # clean Exit(1), not a crash (which CliRunner reports as 1 too)
    # The exception reaching CliRunner is a clean SystemExit from typer.Exit, never the raw
    # typed error (which would mean the @_capability_errors decorator failed to catch it and
    # a traceback leaked) — this is the heart of the WR-04 fix.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, NoTopicsMatchedError)
    assert not isinstance(result.exception, ValueError)
    # The teaching message (and its remedy) is printed cleanly, not buried under a trace.
    assert "No live topics matched" in result.output
    assert "rosbagger-record list" in result.output
