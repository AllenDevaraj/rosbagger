"""The live rclpy publish FRONT DOOR + SINK for replay (D-04 — VERIFIED end-to-end).

This is the ONLY ROS-bound module in ``rosbagger_replay``: it owns ``rclpy.init()`` /
``rclpy.shutdown()``, builds the per-topic publisher dict, wires the publish sink the
pure :class:`rosbagger_replay.scheduler.Replayer` drives, handles ``--start`` seek, and
finalizes in a ``finally``. It is the single production publish path — the CLI, the
Phase-14 GUI, and the SC1 live test all call this through the ``__init__`` front door;
there is NO second publish path.

OFFLINE INVARIANT (D-03/D-12): there is NO module-top ROS import. Every ``rclpy`` /
``rclpy.serialization`` / ``rosidl_runtime_py`` import lives INSIDE :func:`replay`'s
body, behind the package front door's ``_require_ros()`` guard, so ``import
rosbagger_replay`` (and a stray ``import rosbagger_replay.replay`` collection scan)
stays ROS-free in the uv venv.

THE VERIFIED PUBLISH PATH (13-RESEARCH Pattern 4 + Code Examples — run on box):
``get_message(type_str)`` resolves a type string to its message class;
``node.create_publisher(cls, topic, 10)`` builds one generic publisher per topic at the
sane default QoS (depth-10 RELIABLE VOLATILE — Pitfall 4);
``deserialize_message(item.cdr, cls)`` turns the raw CDR bytes into a typed message;
``pub.publish(msg)`` delivers it to any subscriber (VERIFIED).

NEVER publish a rosbags ``Message.msg`` object directly (Pitfall 3 — it has no
``_TYPE_SUPPORT`` and ``rclpy`` rejects it). The source seam already bridged ROS 1 bag
bytes to CDR (Pitfall 2), so ``item.cdr`` is ALWAYS CDR ready for ``deserialize_message``.

NO interactive keyboard mode (deferred — D-10 discretion): the API + the CLI's
non-interactive flags fully exercise the six controls (SC2 is proven against the pure
:class:`Replayer` offline). The bounded ``--duration`` / ``--max-messages`` stop is owned
by the scheduler (Plan 02 — ``is not None`` guards, monotonic clock); this sink just
counts published messages.
"""

from __future__ import annotations

import contextlib


def build_publish_sink(node, *, publish_clock: bool = False, static_topics=frozenset()):
    """Build the single rclpy publish sink + its source-of-truth count dict (D-09a).

    This is the ONE reusable publish-mechanics function shared by BOTH ``replay()``
    (the run-to-completion CLI front door) and the Phase-14 GUI replay panel (which
    drives the pure :class:`~rosbagger_replay.scheduler.Replayer` directly for live
    play/pause/step/seek/rate/loop). Factoring the ~15-line sink out here keeps a
    SINGLE production publish path — neither caller re-implements the
    ``get_message`` -> ``create_publisher`` -> ``deserialize_message`` -> ``publish``
    mechanics.

    OFFLINE INVARIANT (D-03/D-12): the ``rclpy.serialization`` / ``rosidl_runtime_py``
    imports live INSIDE this function body (never at module top), so importing
    ``rosbagger_replay`` stays ROS-free; this function is only ever called behind the
    package front door's ``_require_ros()`` guard.

    Phase-20 RViz fidelity (REP-04) — two OPT-IN, keyword-only behaviors, DEFAULT OFF
    (so ``build_publish_sink(node)`` and its existing 2-tuple unpacking are byte-for-byte
    unchanged):

    * ``publish_clock=True`` — also publish ``rosgraph_msgs/msg/Clock`` on ``/clock`` once
      per published item, carrying that item's bag time (``clock_stamp_ns(item.t_ns)``), so
      downstream ``use_sim_time`` nodes (incl. RViz) track bag time instead of wall-clock.
      The Clock class + the ``/clock`` publisher are resolved ONCE (captured in the closure),
      never per-item. The ``get_message`` import stays lazy (offline invariant).
    * ``static_topics`` (a set of topic names, e.g. ``{"/tf_static"}``) — feed each published
      item to a :class:`~rosbagger_replay.fidelity.StaticTracker`, retaining the latest message
      per static (latched / ``transient_local``) topic. After a seek a caller invokes
      :func:`republish_static` to re-push the tracked set through THIS sink so a fresh
      subscriber re-primes its scene (the concrete fix for the Phase-18 backward-scrub
      limitation). This is a publish-path concern layered around seek — the pure scheduler is
      untouched.

    Args:
        node: an initialized ``rclpy`` node used to create the per-topic publishers.
        publish_clock: when ``True``, publish ``/clock`` per item (default ``False``).
        static_topics: topic names to track for static re-publish (default empty = off).

    Returns:
        A ``(sink, published)`` pair where ``sink(item) -> None`` is the publish
        closure the :class:`Replayer` drives and ``published`` is the ``{"n": 0}``
        count dict (the WR-07 source-of-truth published-message counter). When
        ``static_topics`` is set, the :class:`StaticTracker` is reachable as
        ``sink.tracker`` (a back-compatible attribute — the 2-tuple return is unchanged so
        both existing ``sink, published = build_publish_sink(node)`` call sites still work);
        :func:`republish_static` reads it after a seek.
    """
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    from .fidelity import StaticTracker, clock_stamp_ns

    published = {"n": 0}
    # topic -> (msg_cls, publisher); built lazily on first sight of each topic.
    pubs: dict[str, tuple] = {}

    # Phase-20 opt-ins, both off by default. The StaticTracker is pure (20-01); the /clock
    # publisher + Clock class are resolved ONCE here (never per-item — Pitfall C publisher churn).
    tracker = StaticTracker(static_topics) if static_topics else None
    clock_pub = None
    clock_cls = None
    if publish_clock:
        clock_cls = get_message("rosgraph_msgs/msg/Clock")
        clock_pub = node.create_publisher(clock_cls, "/clock", 10)

    def sink(item) -> None:
        if item.topic not in pubs:
            cls = get_message(item.msgtype)  # type string -> message class (VERIFIED)
            # Sane default QoS (depth-10 RELIABLE VOLATILE) — Pitfall 4. Per-topic
            # QoS override is a deferred enhancement (Phase 13 out of scope).
            pubs[item.topic] = (cls, node.create_publisher(cls, item.topic, 10))
        cls, pub = pubs[item.topic]
        msg = deserialize_message(item.cdr, cls)  # raw CDR -> typed message (VERIFIED)
        pub.publish(msg)  # any subscriber on the topic receives it (VERIFIED)
        # WR-07: published["n"] is the SOURCE OF TRUTH for the returned count. The
        # scheduler's own max_messages bound counts SINK INVOCATIONS, not this counter —
        # the two cannot diverge today because the sink fires exactly once per scheduler
        # publish (one increment per drive-loop publish). If a future sink ever filtered
        # or dropped a message, this counter and the scheduler's bound would need to be
        # reconciled (the bound would over-run); they agree only under the one-fire coupling.
        published["n"] += 1
        # Phase-20: record static-topic state + emit /clock (both no-ops when opted out).
        if tracker is not None:
            tracker.record(item)
        if clock_pub is not None:
            cmsg = clock_cls()
            cmsg.clock.sec, cmsg.clock.nanosec = clock_stamp_ns(item.t_ns)
            clock_pub.publish(cmsg)

    # Expose the tracker on the sink (back-compatible: the 2-tuple return is unchanged, so the
    # existing `sink, published = build_publish_sink(node)` unpackings keep working). A caller
    # that opted into static_topics reaches it via sink.tracker for republish_static after a seek.
    sink.tracker = tracker  # type: ignore[attr-defined]
    return sink, published


def republish_static(sink) -> int:
    """Re-push a sink's tracked static items through it (call AFTER a seek) — returns the count.

    Reads the :class:`~rosbagger_replay.fidelity.StaticTracker` attached to ``sink`` by
    :func:`build_publish_sink` (``sink.tracker``); for each tracked latest static item, calls
    ``sink(item)`` so a fresh subscriber re-primes its scene after a replay seek jumped past the
    one-shot latched publish (the Phase-18 backward-scrub fidelity fix). A no-op (returns ``0``)
    when the sink has no tracker (static re-publish not enabled). The pure scheduler is NOT
    involved — this is a publish-path concern layered around seek by the caller (the desktop
    panel's ``_on_seeked`` in 20-03).
    """
    tracker = getattr(sink, "tracker", None)
    if tracker is None:
        return 0
    items = tracker.republish_items()
    for item in items:
        sink(item)
    return len(items)


def replay(
    bag_paths,
    *,
    topics=None,
    rate: float = 1.0,
    loop: bool = False,
    start: float = 0.0,
    duration: float | None = None,
    max_messages: int | None = None,
    default_typestore: object = None,
) -> int:
    """Publish a bag's messages to live ROS 2 topics; return the count published (SC1).

    Loads ``bag_paths`` into a time-ordered CDR stream via the pure
    :func:`rosbagger_replay.source.load_items` seam, then drives the pure
    :class:`rosbagger_replay.scheduler.Replayer` over an rclpy publish sink. An empty
    selection raises the teaching :class:`~rosbagger_replay.errors.NoMessagesToReplayError`
    BEFORE ``rclpy.init()`` (WR-04 clean teaching, Pitfall 6 — no half-built ROS context).

    Args:
        bag_paths: a bag path (str/Path) or iterable of them (forwarded to ``load_items``).
        topics: optional subset of topic names to publish (``None`` = every topic).
        rate: schedule scale (``> 0``); ``> 1`` plays faster, ``< 1`` slower (D-08).
        loop: when ``True`` restart at end-of-bag (bound with ``--duration`` / ``--max-messages``).
        start: a SECONDS offset (D-09/D-10) — converted to ``replayer.seek(int(start * 1e9))``
            (NANOSECONDS, bag-relative). NOT a scheduler ctor param (W3: ``seek`` is the
            only position-setter; the Replayer has no ``start`` kwarg).
        duration: optional bounded stop in seconds (scheduler ``is not None`` guard, WR-01).
        max_messages: optional bounded stop after this many publishes (WR-01).
        default_typestore: optional rosbags typestore for legacy ROS 2 bags lacking embedded
            defs (e.g. the ROS 2 sqlite3 fixture needs ``get_typestore(Stores.ROS2_HUMBLE)``);
            a harmless no-op for self-describing MCAP / ROS 1.

    Returns:
        The number of messages actually published.
    """
    # Lazy ROS imports (offline invariant — never at module top). The package front door
    # (__init__.replay) already called _require_ros(); these bind the sourced ROS distro.
    # The publish mechanics (get_message/deserialize_message/create_publisher/publish) live
    # in build_publish_sink — the SINGLE production publish path shared with the Phase-14 GUI.
    import rclpy

    from .errors import NoMessagesToReplayError
    from .scheduler import Replayer
    from .source import load_items

    items = load_items(bag_paths, topics=topics, default_typestore=default_typestore)
    if not items:
        # Empty selection / empty bag -> teaching error BEFORE any ROS context exists
        # (WR-04 / Pitfall 6): caught by the CLI's @_capability_errors as a clean Exit(1).
        raise NoMessagesToReplayError(bag_paths=bag_paths, topics=topics)

    # WR-04: only manage the rclpy context WE create. A re-entrant caller (the Phase-14 GUI
    # owns its own long-lived context) may already have an initialized context — calling
    # rclpy.init() again would raise, and an unconditional shutdown() in finally would tear
    # the caller's context out from under it. Guard on rclpy.ok(): init only if we created it,
    # and shutdown only that same context (created_ctx) in finally.
    created_ctx = not rclpy.ok()
    if created_ctx:
        rclpy.init()
    node = None
    try:
        node = rclpy.create_node("rosbagger_replayer")
        # The SINGLE production publish sink (D-09a) — same mechanics the Phase-14 GUI drives.
        sink, published = build_publish_sink(node)

        # The Replayer has NO `start` ctor param (W3): map the --start SECONDS offset onto
        # seek(t_offset_ns) (bag-relative NANOSECONDS) before playing.
        replayer = Replayer(
            items,
            sink,
            rate=rate,
            loop=loop,
            duration=duration,
            max_messages=max_messages,
        )
        if start:
            replayer.seek(int(start * 1e9))
        replayer.play()
        replayer.run()
        return published["n"]
    finally:
        # Finalize on EVERY exit path (normal end, bound trip, or a raised exception):
        # tear down the node + the rclpy context so a re-run / the next process is clean.
        # WR-05: each teardown is best-effort so a cleanup raise (e.g. context already torn
        # down, or a publisher mid-flight) does NOT mask the ORIGINAL publish exception the
        # finally exists for. WR-04: only shut down the context if WE created it.
        if node is not None:
            with contextlib.suppress(Exception):
                node.destroy_node()
        if created_ctx:
            with contextlib.suppress(Exception):
                rclpy.shutdown()
