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
    import rclpy
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

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
    published = {"n": 0}
    try:
        node = rclpy.create_node("rosbagger_replayer")
        # topic -> (msg_cls, publisher); built lazily on first sight of each topic.
        pubs: dict[str, tuple] = {}

        def sink(item) -> None:
            if item.topic not in pubs:
                cls = get_message(item.msgtype)  # type string -> message class (VERIFIED)
                # Sane default QoS (depth-10 RELIABLE VOLATILE) — Pitfall 4. Per-topic
                # QoS override is a deferred enhancement (Phase 13 out of scope).
                pubs[item.topic] = (cls, node.create_publisher(cls, item.topic, 10))
            cls, pub = pubs[item.topic]
            msg = deserialize_message(item.cdr, cls)  # raw CDR -> typed message (VERIFIED)
            pub.publish(msg)  # any subscriber on the topic receives it (VERIFIED)
            published["n"] += 1

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
