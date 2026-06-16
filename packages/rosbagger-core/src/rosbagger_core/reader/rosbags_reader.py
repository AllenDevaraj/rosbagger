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

import contextlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

from rosbags.highlevel import AnyReader, AnyReaderError

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


def _force_close_subreaders(reader: AnyReader) -> None:
    """Release a (possibly partially-opened) ``AnyReader``'s handles without leaking (newE19).

    ``AnyReader.close()`` asserts ``self.isopen`` — which is ``False`` when ``open()`` raised
    its post-loop ``"no type definitions"`` error AFTER opening the sub-readers — so calling
    ``close()`` there would itself raise and the underlying sqlite3 / ``.bag`` / ``.mcap``
    file handles would leak. Try the normal close first (a cleanly-opened reader being
    discarded after a coverage-verify failure), then fall back to closing each sub-reader
    directly, ignoring per-reader errors. Safe to call on any ``AnyReader`` in any state.
    """
    try:
        reader.close()
        return
    except Exception:  # noqa: BLE001 - assert/close failure must not mask the real error
        pass
    for sub in getattr(reader, "readers", ()):
        with contextlib.suppress(Exception):  # best-effort fd release
            sub.close()


def _unresolved_msgtypes(reader: AnyReader, typestore: object) -> set[str]:
    """Connection msgtypes the ``typestore`` cannot resolve (custom types it lacks).

    Used after a def-less bag is re-opened with the fallback typestore: if any connection's
    msgtype is absent from the store (``get_msgdef`` raises), the bag carries custom types
    the fallback does not cover, so the reader must still teach (CLI-04) rather than open.
    """
    unresolved: set[str] = set()
    get_msgdef = typestore.get_msgdef
    for conn in reader.connections:
        try:
            get_msgdef(conn.msgtype)
        except Exception:  # noqa: BLE001 - any lookup failure means "not covered"
            unresolved.add(conn.msgtype)
    return unresolved


def open_bag(
    paths: Iterable[str | Path],
    *,
    default_typestore: object = None,
) -> AnyReader:
    """Open an ``AnyReader`` over ``paths``, owning the typestore fallback + error translation (T2).

    The SINGLE bag-open chokepoint shared by :class:`RosbagsReader`, the edit pipeline
    (``edit_bag``), and the replay source (``load_items``) — previously three independent
    opens with divergent handling of the same ``"no type definitions"`` failure (one wrapped
    it, one copy-pasted the string match with no typestore, one didn't wrap it at all).

    With NO explicit ``default_typestore``: open with the bag's embedded defs; on the specific
    ``"no type definitions"`` error fall back to the env-resolved default typestore (T1) and
    verify it covers the bag's connection msgtypes — raising :class:`UnresolvedTypeError`
    (CLI-04 teaching) only when a custom type is uncovered. With an explicit typestore: honor
    it (no fallback, no coverage verify), translating only the no-defs error. Never leaks the
    partially-opened sub-readers rosbags leaves behind on the no-defs path (newE19).

    Returns an OPEN ``AnyReader``; the caller owns ``close()``. A non-no-defs ``AnyReaderError``
    (e.g. a mixed-format merge) propagates unchanged (Pitfall 3); ``FileNotFoundError`` (a
    missing path) is never caught here.
    """
    from rosbagger_core.errors import UnresolvedTypeError

    path_list = [Path(p) for p in paths]

    # Explicit typestore: the caller owns the choice — open as-is, translating only no-defs.
    if default_typestore is not None:
        reader = AnyReader(path_list, default_typestore=default_typestore)
        try:
            reader.open()
        except AnyReaderError as e:
            _force_close_subreaders(reader)
            if "no type definitions" in str(e):
                raise UnresolvedTypeError(str(e)) from e
            raise
        return reader

    # No explicit typestore: try the bag's embedded defs first (modern bags self-describe).
    reader = AnyReader(path_list)
    try:
        reader.open()
    except AnyReaderError as e:
        _force_close_subreaders(reader)  # newE19 — never leak the partial open
        if "no type definitions" not in str(e):
            raise
        return _open_with_fallback_typestore(path_list, str(e))
    return reader


def _open_with_fallback_typestore(path_list: list[Path], original_detail: str) -> AnyReader:
    """Retry a def-less open with the env-resolved default typestore, verifying coverage (T1/T2).

    Opens with :func:`rosbagger_core.typestore.resolve_default_typestore`; if any connection's
    msgtype is NOT in that typestore (a custom type the store lacks), closes the reader (no fd
    leak — newE19) and raises :class:`UnresolvedTypeError` — so a standard real ``.db3`` opens
    while a custom-type def-less bag still teaches.
    """
    from rosbagger_core.errors import UnresolvedTypeError
    from rosbagger_core.typestore import resolve_default_typestore

    typestore = resolve_default_typestore()
    reader = AnyReader(path_list, default_typestore=typestore)
    try:
        reader.open()
        unresolved = _unresolved_msgtypes(reader, typestore)
        if unresolved:
            raise UnresolvedTypeError(
                f"{original_detail} (the default typestore does not cover: "
                f"{', '.join(sorted(unresolved))})"
            )
    except BaseException:
        _force_close_subreaders(reader)
        raise
    return reader


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

        Def-less bags (T1): real ``rosbag2`` recordings embed NO message definitions, so they
        need a typestore. Rather than make each face hard-code one, when NO explicit
        ``default_typestore`` was given the reader opens with the bag's own embedded defs
        first and, on the SPECIFIC ``"no type definitions"`` ``AnyReaderError``, falls back to
        the environment-resolved default typestore (``rosbagger_core.typestore``). It then
        VERIFIES that fallback actually covers the bag's connection types — if a custom type
        is uncovered, it closes the reader and raises :class:`UnresolvedTypeError` with
        registration guidance (CLI-04 preserved). Net effect: a STANDARD real ``.db3`` now
        opens identically from every face (bagq included), while a CUSTOM-type def-less bag
        still teaches. When the caller DID pass an explicit typestore, that choice is honored
        unchanged (no fallback, no coverage verify).

        fd safety (newE19): ``AnyReader.open()`` opens all sub-readers before raising the
        post-loop no-defs error, and its own ``close()`` asserts ``isopen`` — so a discarded
        reader leaks file handles unless its sub-readers are closed by hand
        (:func:`_force_close_subreaders`), which this method does on every discard path.

        Every OTHER failure propagates UNCHANGED so it is not mislabeled as a
        type-registration problem (07-RESEARCH Pitfall 3): a non-no-defs ``AnyReaderError``
        (e.g. mixed ROS 1 / ROS 2 paths) re-raises as itself, and ``FileNotFoundError``
        (missing path) is never even caught here.

        The open/fallback/verify/translate logic lives in the shared module-level
        :func:`open_bag` (T2) so the edit pipeline and replay source open bags identically.
        """
        self._reader = open_bag(self._paths, default_typestore=self._default_typestore)

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
        # Validate + select the stream EAGERLY here (the yield loop lives in
        # _iter_messages): read() returns a generator, so were the body one generator the
        # not-open guard and the empty-topics short-circuit would only run when the caller
        # first advances the iterator — surfacing the error at the consumer rather than the
        # misuse site. Every sibling state guard (topics/connections/...) fails fast as a
        # plain property; this keeps read() consistent while preserving lazy streaming.
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
                return iter(())
            stream = self._reader.messages(connections=conns)
        return self._iter_messages(stream)

    def _iter_messages(self, stream) -> Iterator[Message]:
        """The lazy yield loop for :meth:`read` — deserialize + wrap one message at a time."""
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
