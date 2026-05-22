"""``RosbagsReader`` — the v1 concrete reader, a thin adapter over ``AnyReader``.

This is impl #1 of the ``BagReader`` seam (design spec §4.1): it wraps
``rosbags.highlevel.AnyReader`` to open ROS 1 ``.bag`` / ROS 2 sqlite3 / ROS 2
MCAP bags uniformly (READ-01/02/03), lazily yield ``Message`` records with a
correctly derived ``stamp`` (READ-04), expose ``topics``/``connections``
metadata without full deserialization (for Phase 4 Inspect), and accept a list
of same-format bag paths read as one logical, time-ordered dataset (READ-05).

The heavy lifting — format detection, message-definition registration,
deserialization, and multi-bag merge — is already done by ``AnyReader``. This
adapter's only real work is mapping its ``(connection, t_ns, rawdata)`` tuples
into the project's ``Message`` shape and deriving the four fields, especially
the uniform ``stamp`` extraction that works for both ROS 1 and ROS 2.

Offline invariant: ``import rosbags`` at module level here is SAFE. The guard
(``tests/test_offline_guard.py``) only blocks the forbidden ROS runtime modules,
and only over the import graph of ``import rosbagger_core`` / ``import bagq`` —
neither of which imports this module at top level. ``rosbags`` itself pulls in
no ROS modules.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

from rosbags.highlevel import AnyReader

from .base import BagReader, Message


def _stamp_ns(msg: object) -> int | None:
    """Uniform ``header.stamp`` extraction in nanoseconds, or ``None``.

    Works for ROS 1 and ROS 2 alike: ``rosbags`` normalizes ``header.stamp`` to
    ``builtin_interfaces/msg/Time`` with ``.sec``/``.nanosec`` for BOTH (ROS 1's
    native ``secs``/``nsecs`` never surfaces). Duck-typed throughout — many
    message types (e.g. ``geometry_msgs/msg/Twist``) have no ``header`` at all,
    so a missing header or stamp yields ``None`` rather than raising.
    """
    header = getattr(msg, "header", None)
    if header is None:
        return None
    st = getattr(header, "stamp", None)
    if st is None or not (hasattr(st, "sec") and hasattr(st, "nanosec")):
        return None
    return st.sec * 1_000_000_000 + st.nanosec


class RosbagsReader(BagReader):
    """``BagReader`` implementation #1, wrapping ``rosbags.highlevel.AnyReader``.

    Accepts a single bag path or an iterable of same-format paths; the paths are
    handed straight to ``AnyReader``, which merge-sorts the per-bag streams by
    timestamp (READ-05 — no hand-rolled merge). ``read()`` is a lazy generator
    that deserializes one message at a time. Inherits the context-manager
    lifecycle (``__enter__``/``__exit__``) from ``BagReader``.
    """

    def __init__(
        self,
        paths: str | Path | Iterable[str | Path],
        *,
        default_typestore: object = None,
    ) -> None:
        """Normalize ``paths`` to ``list[Path]``; do NOT open (open is explicit).

        A lone ``str``/``Path`` is wrapped in a one-element list; an iterable of
        them is coerced element-wise. Coercion to ``Path`` is required because
        ``AnyReader`` calls ``.exists()``/``.suffix`` on each input, so a bare
        ``str`` would raise ``AttributeError``.

        ``default_typestore`` is an optional passthrough for legacy ROS 2 bags
        that lack embedded message definitions; modern bags embed their defs and
        need none.
        """
        if isinstance(paths, (str, Path)):
            self._paths: list[Path] = [Path(paths)]
        else:
            self._paths = [Path(p) for p in paths]
        self._default_typestore = default_typestore
        self._reader: AnyReader | None = None

    def open(self) -> None:
        """Construct and open the underlying ``AnyReader`` over the bag paths.

        Construction may raise ``AnyReaderError`` (mixed formats / missing
        embedded defs) or ``FileNotFoundError`` (missing path); both propagate
        unchanged for v1 (fail closed — error-wrapping is deferred to Phase 7).
        """
        reader = AnyReader(self._paths, default_typestore=self._default_typestore)
        reader.open()
        self._reader = reader

    def close(self) -> None:
        """Release the underlying ``AnyReader``. Idempotent (safe if not open)."""
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def read(self, *, topics: set[str] | None = None) -> Iterator[Message]:
        """Lazily yield ``Message`` records, time-ordered across all opened bags.

        ``AnyReader.messages()`` already merges the per-bag streams by timestamp,
        so the combined stream is globally time-ordered — no reordering is
        hand-rolled here. Each message is deserialized one at a time inside the
        loop; the bag is never list-materialized.

        ``topics`` is an optional CONNECTION-LEVEL filter (the QURY-05 lazy
        seam): when given, the matching ``connections`` are passed to
        ``AnyReader.messages(connections=...)`` so ONLY those topics' raw
        messages are ever yielded — the others are never even handed to
        ``deserialize``. This is materially different from filtering AFTER read
        (``for m in read(): if m.topic in topics``), which would still pay full
        deserialization for every unreferenced topic (05-RESEARCH Pitfall 2). An
        unknown topic name simply matches no connection (an empty stream), not an
        error. ``topics=None`` (the default) reads every topic, unchanged.
        """
        if self._reader is None:
            raise RuntimeError("RosbagsReader.read() called before open()")
        if topics is None:
            stream = self._reader.messages()
        else:
            # Connection-level filter: select only the referenced topics'
            # connections so unreferenced topics are never deserialized
            # (05-RESEARCH Pattern 5; VERIFIED AnyReader.messages(connections=...)).
            conns = [c for c in self._reader.connections if c.topic in topics]
            # An EMPTY connection list is NOT "no filter": rosbags treats
            # ``messages(connections=())`` as its all-connections default, so
            # passing [] would yield everything. A caller that filtered to zero
            # topics means zero messages — short-circuit to an empty stream so
            # ``read(topics=set())`` / an unknown topic yields nothing, not all.
            if not conns:
                return
            stream = self._reader.messages(connections=conns)
        for connection, t_ns, rawdata in stream:
            msg = self._reader.deserialize(rawdata, connection.msgtype)
            yield Message(
                topic=connection.topic,
                t=t_ns,
                t_ns=t_ns,
                stamp=_stamp_ns(msg),
                msgtype=connection.msgtype,
                msg=msg,
            )

    @property
    def topics(self) -> Mapping[str, object]:
        """Topic name -> ``TopicInfo`` metadata, without full deserialization."""
        if self._reader is None:
            raise RuntimeError("RosbagsReader.topics accessed before open()")
        return self._reader.topics

    @property
    def connections(self) -> Sequence[object]:
        """Per-connection metadata, without full deserialization."""
        if self._reader is None:
            raise RuntimeError("RosbagsReader.connections accessed before open()")
        return self._reader.connections

    # --- Additive O(1) metadata passthroughs (Phase 4 Inspect) --------------
    # Each mirrors the ``topics`` before-open guard exactly: all whole-bag
    # metadata is read straight off ``AnyReader`` (computed as min/max/sum over
    # the sub-readers — no message deserialization). ``paths`` is the lone
    # exception: it reads no ``_reader`` and is callable before open().

    @property
    def message_count(self) -> int:
        """Total message count across all opened bags (O(1); whole-bag)."""
        if self._reader is None:
            raise RuntimeError("RosbagsReader.message_count accessed before open()")
        return self._reader.message_count

    @property
    def duration(self) -> int:
        """Whole-bag duration in nanoseconds (``end_time - start_time``).

        Meaningless when ``message_count == 0`` (``AnyReader`` returns a
        large-negative value for an empty bag); callers guard on the count.
        """
        if self._reader is None:
            raise RuntimeError("RosbagsReader.duration accessed before open()")
        return self._reader.duration

    @property
    def start_time(self) -> int:
        """Earliest log time across all opened bags, in nanoseconds (O(1))."""
        if self._reader is None:
            raise RuntimeError("RosbagsReader.start_time accessed before open()")
        return self._reader.start_time

    @property
    def end_time(self) -> int:
        """Latest log time across all opened bags, in nanoseconds (O(1))."""
        if self._reader is None:
            raise RuntimeError("RosbagsReader.end_time accessed before open()")
        return self._reader.end_time

    @property
    def typestore(self) -> object:
        """The ``rosbags`` ``Typestore`` registered in ``AnyReader.open()``.

        Loosely typed as ``object`` so the ``BagReader`` contract stays
        backend-agnostic (Phase 4 ``tables`` feeds it to ``build_table_schema``).
        """
        if self._reader is None:
            raise RuntimeError("RosbagsReader.typestore accessed before open()")
        return self._reader.typestore

    @property
    def paths(self) -> list:
        """The opened bag paths, as a fresh copy (for size; multi-bag READ-05).

        Reads no ``_reader``, so it is callable WITHOUT open(): the paths are
        known at construction. Returns a copy so callers cannot mutate state.
        """
        return list(self._paths)
