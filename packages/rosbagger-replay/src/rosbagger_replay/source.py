"""The raw-CDR source seam for replay (D-05 — RESOLVED, VERIFIED end-to-end).

Reads a bag through the v1 ``rosbags`` ``AnyReader`` and yields an ordered stream
of :class:`ReplayItem` ``(t_ns, topic, msgtype, cdr)`` records whose ``cdr`` is
ALWAYS CDR bytes — ready to hand straight to ``rclpy.serialization.deserialize_message``
in the live publish sink (Plan 03). This is the offline foundation of replay: it is
PURE — it imports ``rosbags`` only (and lazily, inside :func:`load_items`), NEVER
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` — exactly like
``rosbagger_core.reader.rosbags_reader``. The pure transport scheduler (Plan 02)
consumes this item stream; the rclpy sink (Plan 03) publishes it.

WHY ``AnyReader`` DIRECTLY (not ``RosbagsReader``): the seam needs the raw
``(connection, t_ns, rawdata)`` tuples plus the ROS 1 ``deserialize -> serialize_cdr``
bridge, which ``RosbagsReader.read()`` hides behind already-deserialized ``Message``
records. The tentative ``rosbag2_py.SequentialReader`` default was OVERTURNED by
RESEARCH (it raises ``yaml-cpp: bad conversion`` on the project's rosbags-written
fixtures); the v1 reader opens all three formats and natively exposes raw bytes.

WIRE-FORMAT BRIDGE (D-05, VERIFIED): ROS 2 bag raw bytes ARE CDR (pass straight
through). ROS 1 bag raw bytes are ROS 1 wire format (NOT CDR) and must be bridged
via ``reader.deserialize(raw, msgtype) -> reader.typestore.serialize_cdr(obj, msgtype)``
before publish. The yielded ``cdr`` is therefore always CDR, never a rosbags object.

A2 (v1): :func:`load_items` materializes a ``list`` rather than streaming. The
fixtures are tiny, and a list makes seek / index-landing (Plan 02, SC3) trivial.
Streaming (a generator over very large bags) is a deferred enhancement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReplayItem:
    """One replayable message: its log timestamp, topic, type, and CDR payload.

    ``cdr`` is always CDR bytes (ROS 2 passthrough or ROS 1 bridged), so the
    live publish sink can feed it directly to ``rclpy.serialization.deserialize_message``
    without re-touching the rosbags object model. Frozen + slotted: items are
    immutable value records and there can be many of them.
    """

    t_ns: int
    topic: str
    msgtype: str
    cdr: bytes


def _as_path_list(bag_paths: str | Path | Iterable[str | Path]) -> list[Path]:
    """Normalize a single str/Path or an iterable of them to ``list[Path]``.

    Mirrors ``RosbagsReader.__init__`` coercion: ``AnyReader`` calls
    ``.exists()`` / ``.suffix`` on each input, so a bare ``str`` would raise.
    """
    if isinstance(bag_paths, (str, Path)):
        return [Path(bag_paths)]
    return [Path(p) for p in bag_paths]


def load_items(
    bag_paths: str | Path | Iterable[str | Path],
    *,
    topics: set[str] | None = None,
    default_typestore: object = None,
) -> list[ReplayItem]:
    """Load a bag into a time-ordered list of CDR :class:`ReplayItem` records.

    Reads ``bag_paths`` through ``rosbags.highlevel.AnyReader`` (imported lazily
    inside the body so the module top stays clean and the offline-guard rosbags
    check is trivially green for the package's other modules). The combined stream
    is already time-ordered across bags (``AnyReader.messages()`` merge-sorts by
    timestamp — no hand-rolled merge).

    ``topics`` is an optional CONNECTION-LEVEL subset filter: when given, only the
    matching connections are passed to ``messages(connections=...)``, so
    unreferenced topics are never even handed to the bridge. An empty match
    short-circuits to ``[]`` (the QURY-05 empty-selection guard) — it does NOT pass
    an empty connection list, which ``rosbags`` treats as "all connections".

    ``default_typestore`` is the optional ``rosbags`` typestore for legacy ROS 2
    bags lacking embedded defs (e.g. the ROS 2 sqlite3 fixture needs
    ``get_typestore(Stores.ROS2_HUMBLE)``); self-describing MCAP / ROS 1 bags need
    none.

    Each ``(connection, t_ns, rawdata)`` becomes a ``ReplayItem`` with CDR bytes:
    ROS 2 ``rawdata`` IS CDR (passed through); ROS 1 ``rawdata`` is ROS 1 wire format
    and is bridged via ``deserialize -> serialize_cdr`` (Pitfall 2). The reader is
    always closed in a ``finally``.
    """
    # Lazy ROS-free imports (offline invariant — rosbags only, never at module top, never
    # rclpy/rosbag2_py). ConnectionExtRosbag1 is the rosbags ROS 1 connection-extension type
    # used for the IN-01 isinstance detection below. open_bag is the SHARED core bag-open
    # chokepoint (T2): it owns the env-resolved typestore fallback, the no-defs ->
    # UnresolvedTypeError translation, and the fd-leak-safe close — so a bare load_items(bag)
    # (e.g. the TUI replay panel) now opens a real def-less .db3 instead of raising a raw
    # AnyReaderError. An explicit default_typestore is still honored unchanged.
    from rosbags.interfaces import ConnectionExtRosbag1

    from rosbagger_core.reader import open_bag

    items: list[ReplayItem] = []
    reader = open_bag(_as_path_list(bag_paths), default_typestore=default_typestore)
    try:
        conns = reader.connections
        if topics is not None:
            conns = [c for c in conns if c.topic in topics]
            # An EMPTY connection list is NOT "no filter": rosbags treats
            # messages(connections=()) as its all-connections default, so a
            # zero-match filter must short-circuit to [] rather than yield all.
            if not conns:
                return []
        for conn, t_ns, rawdata in reader.messages(connections=conns):
            ext = getattr(conn, "ext", None)
            # IN-01: detect ROS 1 connections via isinstance against the imported rosbags type
            # (robust to a class rename/relocate) rather than a fragile class-name string compare.
            is_ros1 = isinstance(ext, ConnectionExtRosbag1)
            if is_ros1:
                # ROS 1 raw bytes are ROS 1 wire format, NOT CDR — bridge to CDR.
                obj = reader.deserialize(rawdata, conn.msgtype)
                cdr = bytes(reader.typestore.serialize_cdr(obj, conn.msgtype))
            else:
                cdr = bytes(rawdata)  # ROS 2 rawdata IS CDR (VERIFIED).
            items.append(ReplayItem(t_ns, conn.topic, conn.msgtype, cdr))
    finally:
        reader.close()
    return items  # AnyReader.messages() is already time-ordered across bags.
