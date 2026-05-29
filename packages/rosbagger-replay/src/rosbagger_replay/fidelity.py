"""The PURE, ROS-free RViz-fidelity decision tier for replay (Phase 20, REP-04).

This is the offline half of the Phase-12/13 two-tier split: the DECISION logic for making a
seek "look right" in RViz lives here as stdlib-only, unit-testable code; the actual
``pub.publish()`` / ``rosgraph_msgs/msg/Clock`` construction is the LIVE boundary in
``replay.py`` (Plan 20-02). Keeping the logic here means SC2 (static re-publish) has a
deterministic, ROS-free CI proof and ``import rosbagger_replay`` stays ROS-free.

Two pieces:

* :class:`StaticTracker` — as the stream plays, record the LATEST message per "static"
  (latched / ``transient_local``) topic (default ``/tf_static``). After a seek, the live sink
  re-publishes :meth:`StaticTracker.republish_items` so a fresh subscriber re-primes its scene
  instead of RViz layering stale geometry over newly-published messages. The tracker keeps
  exactly one latest item per CONFIGURED topic — bounded by the static set, never message
  history (so a long replay does not grow memory).
* :func:`clock_stamp_ns` — split an absolute bag ``t_ns`` into ``(sec, nanosec)`` for a
  ``Clock`` message's ``.clock`` field. Pure arithmetic; the live ``Clock`` build is 20-02.

OFFLINE INVARIANT (D-03/D-12): this module imports ONLY stdlib. It operates on the
rosbags-free :class:`~rosbagger_replay.source.ReplayItem` value record (imported under
``TYPE_CHECKING`` for typing only; at run time it just duck-types ``item.topic``), so it
binds none of the ROS runtime — re-exporting it from the package front door is ROS-free,
exactly like ``errors.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .source import ReplayItem

# The default "static" topic set: ROS 2 latches /tf_static (transient_local), so a subscriber
# that joins after the one-shot publish — or after a replay seek jumps past it — never sees the
# static transforms unless they are re-published. /tf_static is the canonical case; callers can
# extend the set (e.g. a latched /map) via the StaticTracker constructor.
_DEFAULT_STATIC_TOPICS = frozenset({"/tf_static"})


class StaticTracker:
    """Record the latest message per configured static topic, for re-publish after a seek.

    Construct with the set of topic names to treat as static (default ``{"/tf_static"}``).
    The live sink calls :meth:`record` on every published item; :meth:`record` keeps only the
    LATEST item per tracked topic (latest wins — a static topic's current value is all that
    matters). After a seek, the caller re-publishes :meth:`republish_items` so a fresh
    subscriber re-primes. Non-static topics are ignored, so the tracker's memory is bounded by
    the size of the static set, not by the number of messages replayed.
    """

    def __init__(self, static_topics: frozenset[str] | set[str] = _DEFAULT_STATIC_TOPICS) -> None:
        """Store the static-topic set (frozen) + an empty topic -> latest-item map."""
        self._static_topics = frozenset(static_topics)
        self._latest: dict[str, ReplayItem] = {}

    def record(self, item: ReplayItem) -> None:
        """Record ``item`` as the latest for its topic IFF the topic is in the static set.

        Latest wins (a later item on the same static topic replaces the earlier one). An item
        on a non-static topic is ignored — the tracker only retains static-topic state.
        """
        if item.topic in self._static_topics:
            self._latest[item.topic] = item

    def republish_items(self) -> list[ReplayItem]:
        """Return one latest item per tracked static topic (the set to re-publish on seek)."""
        return list(self._latest.values())

    def clear(self) -> None:
        """Forget all tracked static items (e.g. on a fresh load / teardown)."""
        self._latest.clear()


def clock_stamp_ns(t_ns: int) -> tuple[int, int]:
    """Split an absolute bag ``t_ns`` into ``(sec, nanosec)`` for a ``Clock`` ``.clock`` stamp.

    Pure arithmetic via ``divmod`` — for a non-negative ``t_ns`` this guarantees
    ``0 <= nanosec < 1_000_000_000``, a well-formed ROS time stamp. The actual
    ``rosgraph_msgs/msg/Clock`` construction is the live boundary in ``replay.py`` (20-02);
    only this time math is pure and tested here.
    """
    sec, nanosec = divmod(t_ns, 1_000_000_000)
    return int(sec), int(nanosec)
