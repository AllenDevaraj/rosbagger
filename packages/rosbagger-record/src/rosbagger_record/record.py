"""The live ``rclpy`` + ``rosbag2_py`` recording core (REC-01 / SC1+SC2+SC3).

This is the ONLY ROS-runtime-bound module in ``rosbagger-record`` — it wires the
three verified ROS-native primitives (``get_topic_names_and_types`` →
``create_subscription(raw=True)`` → ``rosbag2_py.SequentialWriter``) plus the
package's own pure-Python selection (delegated to :mod:`.discovery`) and
bounded-stop accounting into the distilled record pipeline that 12-RESEARCH ran
end-to-end on this box (external publisher → 4 msgs recorded → re-opened via the
v1 reader).

OFFLINE-IMPORT BOUNDARY (T-12-01 / D-03/D-11) — the load-bearing discipline:
``import rosbagger_record.record`` MUST succeed in the ROS-free uv venv WITHOUT
pulling ``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` into ``sys.modules``.
So this module's TOP LEVEL imports ONLY ``__future__`` + stdlib (``time``); EVERY
ROS import lives INSIDE a function body. ``tests/test_offline_guard.py`` (extended
in Plan 01) regression-locks this — a stray top-level ROS import fails it.

WHY THE STRUCTURE IS SPLIT THIS WAY (12-RESEARCH coverage recommendation b): the
pure-Python pieces — :func:`_should_stop` (bounded-stop accounting) and the
control flow of :func:`_check_storage` / :func:`record` (the storage gate, the
empty-selection guard, the ``finally: writer.close()``) — are unit-coverable in
the uv venv with ``rclpy`` / ``rosbag2_py`` MOCKED via ``sys.modules`` injection
(12-RESEARCH Pitfall 6). Only the irreducible ``rclpy`` wiring (``rclpy.init`` /
``spin_once`` loop body / ``create_subscription``) cannot run offline; it is
proven by Plan 03's LIVE test. ``rosbagger_record`` is intentionally kept OUT of
the ``--cov`` gate (gate stays ``--cov=rosbagger_core --cov=bagq``) so the live-only
wiring does not weaken the >=80% offline gate (decision inherited from Plan 01).

STORAGE GATE (D-08 refined): MCAP stays the PREFERRED DEFAULT (``record(...,
storage="mcap")``); a ``--storage {mcap,sqlite3}`` escape lets the recorder run on
this box, where only ``sqlite3`` is registered. :func:`_check_storage` consults
``rosbag2_py.get_registered_writers()`` BEFORE opening the writer and raises the
teaching :class:`~rosbagger_record.errors.McapStorageUnavailableError` if the
requested storage is unregistered. The default is NEVER silently downgraded.

VERIFIED APIs (12-RESEARCH Patterns 2/3/4/5 — each executed against ROS 2 Humble,
rclpy 3.3.21 / rosbag2_py 0.15.16): see the per-function docstrings.
"""

from __future__ import annotations

import time

from .discovery import discover_topics, select_topics
from .errors import McapStorageUnavailableError


def _check_storage(storage_id: str) -> None:
    """Capability gate: fail BEFORE opening if ``storage_id`` is unregistered (Pattern 5).

    Lazy-imports ``rosbag2_py`` and consults ``get_registered_writers()`` (VERIFIED
    to return ``{'sqlite3', ...test plugins}`` on this box — the ``mcap`` plugin is a
    separate apt package not installed here). If the requested ``storage_id`` is not
    among the registered writers, raises the teaching
    :class:`~rosbagger_record.errors.McapStorageUnavailableError` carrying the
    requested id and the sorted list of what IS available (D-08 refined / Pitfall 1).

    Per D-08: MCAP is the preferred default and is NOT silently downgraded — this
    gate only converts an unavailable-storage situation into an actionable error
    (install the plugin, or pass ``--storage sqlite3``); choosing ``sqlite3`` is the
    user's explicit escape, never an automatic fallback.
    """
    import rosbag2_py

    available = rosbag2_py.get_registered_writers()
    if storage_id not in available:
        raise McapStorageUnavailableError(storage_id, sorted(available))


def _should_stop(
    captured_n: int,
    now: float,
    *,
    max_messages: int | None,
    deadline: float | None,
) -> bool:
    """Pure bounded-stop predicate — the ONLY part of the spin loop unit-tested.

    Deliberately ROS-free (no ``rclpy`` import) so it is directly callable in the
    offline unit tests with plain values (12-RESEARCH coverage recommendation b).
    The loop calls this each spin; ``rclpy.ok()`` (the SIGINT signal — D-09) is
    checked separately in :func:`_run` so this stays pure.

    Returns ``True`` (stop) when EITHER bound is reached:

    * ``max_messages`` is set and ``captured_n >= max_messages`` (counted enough), or
    * ``deadline`` is set and ``now >= deadline`` (the ``--duration`` window elapsed).

    With both bounds ``None`` (unbounded) it always returns ``False`` — only SIGINT
    (via ``rclpy.ok()`` flipping ``False``) stops an unbounded run (D-09).
    """
    if max_messages is not None and captured_n >= max_messages:
        return True
    if deadline is not None and now >= deadline:  # noqa: SIM103 (clarity over collapse)
        return True
    return False


def _make_writer(out: str, storage_id: str):  # noqa: ANN201 (lazy rosbag2_py type)
    """Open a ``rosbag2_py.SequentialWriter`` for ``out`` (Pattern 2 — VERIFIED).

    Lazy-imports ``rosbag2_py``; builds a ``SequentialWriter`` and opens it with
    ``StorageOptions(uri=out, storage_id=storage_id)`` +
    ``ConverterOptions(input/output_serialization_format="cdr")``. CDR in/out keeps
    the ``raw=True`` payload (already CDR) a verbatim pass-through (D-05). Returns the
    open writer; the caller owns ``writer.close()`` (in a ``finally`` — SC3).
    """
    import rosbag2_py

    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(uri=out, storage_id=storage_id),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr",
            output_serialization_format="cdr",
        ),
    )
    return writer


def _subscribe_and_record(
    node,  # noqa: ANN001 (rclpy node — must not be named at module top)
    writer,  # noqa: ANN001 (rosbag2_py SequentialWriter)
    topic: str,
    type_str: str,
    counter: dict,
) -> None:
    """Register ``topic`` on the writer + subscribe ``raw=True`` (Pattern 2 + D-05).

    1. ``writer.create_topic(TopicMetadata(name=topic, type=type_str,
       serialization_format="cdr"))`` — declares the topic in the bag (empty
       ``offered_qos_profiles`` is fine; VERIFIED the bag re-opens).
    2. Resolve the discovered ``type_str`` to its message class via the lazy
       ``from rosidl_runtime_py.utilities import get_message`` (e.g.
       ``"std_msgs/msg/String"`` → ``String``) — needed because
       ``create_subscription`` wants the class, not the string.
    3. ``node.create_subscription(msg_cls, topic, on_raw, 10, raw=True)`` — the
       ``raw=True`` callback receives plain CDR ``bytes`` (VERIFIED in Humble), which
       :func:`on_raw` writes verbatim via ``writer.write(topic, bytes(data),
       node.get_clock().now().nanoseconds)`` (three positional args; recorder-clock
       timestamp per the verified probe) and bumps the shared ``counter["n"]`` so the
       bounded-stop loop can see the running count. ``bytes(data)`` is a safe identity
       that also tolerates a future distro handing a ``SerializedMessage``.

    No per-message deserialize/re-serialize happens (D-05) — the opaque payload goes
    straight to the writer, so no per-type parser is exposed to a hostile payload
    (T-12-04).
    """
    import rosbag2_py
    from rosidl_runtime_py.utilities import get_message

    writer.create_topic(
        rosbag2_py.TopicMetadata(name=topic, type=type_str, serialization_format="cdr")
    )
    msg_cls = get_message(type_str)

    def on_raw(data) -> None:  # noqa: ANN001 (raw=True delivers builtins.bytes)
        writer.write(topic, bytes(data), node.get_clock().now().nanoseconds)
        counter["n"] += 1

    node.create_subscription(msg_cls, topic, on_raw, 10, raw=True)


def _run(
    node,  # noqa: ANN001 (rclpy node)
    counter: dict,
    *,
    max_messages: int | None = None,
    duration: float | None = None,
) -> None:
    """Spin until a bound is hit OR SIGINT (Pattern 4 — VERIFIED primitives).

    ``rclpy.init()`` (called by :func:`record` / :func:`list_topics`) installs a
    SIGINT handler so ``rclpy.ok()`` flips ``False`` on Ctrl-C (D-09 graceful stop).
    The loop also checks the pure :func:`_should_stop` predicate each spin so a
    ``--max-messages`` count or a ``--duration`` deadline ends it deterministically
    (what makes Plan 03's live test reproducible). ``rclpy.spin_once`` with a short
    ``timeout_sec`` keeps the loop responsive to both the count and the deadline.

    The ``except KeyboardInterrupt`` is belt-and-suspenders (``rclpy.ok()`` usually
    absorbs the SIGINT first). This function does NOT close the writer — the caller's
    ``finally`` owns finalization on EVERY exit path (SC3); keeping ``close()`` in the
    caller means an exception escaping this loop still finalizes the bag.
    """
    import rclpy

    deadline = time.time() + duration if duration else None
    try:
        while rclpy.ok():
            if _should_stop(
                counter["n"], time.time(), max_messages=max_messages, deadline=deadline
            ):
                break
            rclpy.spin_once(node, timeout_sec=0.05)
    except KeyboardInterrupt:  # pragma: no cover - rclpy.ok() usually handles SIGINT
        pass


def record(
    topics: list[str],
    out: str,
    *,
    all_topics: bool = False,
    regex: str | None = None,
    exclude: str | None = None,
    storage: str = "mcap",
    max_messages: int | None = None,
    duration: float | None = None,
) -> int:
    """Record the selected ``topics`` to a bag at ``out``; return the captured count.

    The distilled VERIFIED pipeline (12-RESEARCH "Full record path (SC2)"):
    discover → select → ``raw=True`` subscribe → ``SequentialWriter`` → bounded/SIGINT
    stop → finalize (D-04/D-05/D-09). MCAP is the preferred default ``storage`` (D-08);
    pass ``storage="sqlite3"`` for the capability escape on this box.

    SELECTION (D-07): ``record()`` is the SINGLE orchestrator of discover→select. The
    selection knobs — positional ``topics``, ``all_topics`` (record everything
    published), ``regex`` (include filter), ``exclude`` (drop filter) — are threaded
    straight into the one :func:`~rosbagger_record.discovery.select_topics` call so the
    thin CLI (Plan 03) only forwards flags and never re-implements selection nor calls
    discovery itself (API-first, D-02 — the Phase-14 GUI is the other thin face). The
    precedence (base set → regex include → exclude) lives entirely in ``select_topics``.

    Order of operations (each step matters):

    1. Lazy ``import rclpy``; :func:`_check_storage` FIRST so an unavailable storage
       raises the teaching error BEFORE any ROS graph spins up (cheap fail).
    2. ``rclpy.init()`` + create the recorder node.
    3. ``discover_topics(node)`` (settle so external publishers appear — Pattern 3),
       then ``select_topics(discovered, topics=topics, all_topics=..., regex=...,
       exclude=...)`` (delegated to Plan 01's pure filter — selection is NOT
       re-implemented here). If the selection is EMPTY, raise a teaching ``ValueError``
       BEFORE opening the writer rather than silently recording an empty bag.
    4. Open the writer; subscribe + ``create_topic`` for each selected topic; run the
       bounded-stop loop. ``writer.close()`` is in a ``finally`` so the bag is
       finalized on EVERY exit path — including an exception in the loop (SC3 / T-12-05;
       Plan 02's mocked test proves close-on-error).
    5. Always ``node.destroy_node()`` + ``rclpy.shutdown()``.

    ``storage`` is the public flag name (the CLI's ``--storage``); the default string
    is literally ``"mcap"`` so D-08 is not weakened.
    """
    import rclpy

    _check_storage(storage)
    rclpy.init()
    counter = {"n": 0}
    node = None
    try:
        node = rclpy.create_node("rosbagger_recorder")
        discovered = discover_topics(node)
        selected = select_topics(
            discovered,
            topics=topics,
            all_topics=all_topics,
            regex=regex,
            exclude=exclude,
        )
        if not selected:
            raise ValueError(
                f"No live topics matched (topics={topics!r}, all={all_topics}, "
                f"regex={regex!r}, exclude={exclude!r}). Currently discoverable: "
                f"{sorted(discovered) or '(none)'}. "
                "Run `rosbagger-record list` to see what is being published, "
                "or pass --all to record everything."
            )
        writer = _make_writer(out, storage)
        try:
            for topic, type_str in selected.items():
                _subscribe_and_record(node, writer, topic, type_str, counter)
            _run(node, counter, max_messages=max_messages, duration=duration)
        finally:
            writer.close()  # ALWAYS finalize so the bag re-opens (SC3 / T-12-05)
        return counter["n"]
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


def list_topics() -> dict[str, str]:
    """List currently-discoverable live topics + their types (SC1, Pattern / Code Example).

    Lazy ``import rclpy``; ``rclpy.init()`` → create a short-lived node →
    :func:`~rosbagger_record.discovery.discover_topics` (settle + ``{topic: type_str}``)
    → always ``destroy_node()`` + ``rclpy.shutdown()``. The pure selection (``--regex``
    etc.) is applied by the caller / CLI over this map; this just returns the full
    discovered map.
    """
    import rclpy

    rclpy.init()
    node = None
    try:
        node = rclpy.create_node("rosbagger_record_list")
        return discover_topics(node)
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
