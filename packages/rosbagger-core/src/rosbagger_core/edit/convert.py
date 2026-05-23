"""The cross-format converter-factory wrapper (Plan 11-02, D-04 convert half).

The genuinely hard part of cross-format conversion (ROS 1 ↔ ROS 2) — the ROS 1
``std_msgs/Header.seq`` field that ROS 2 dropped, message-definition translation,
the per-msgtype raw-copy-vs-migrate decision, legacy type renames — is ALREADY
solved inside ``rosbags`` (11-RESEARCH "Don't Hand-Roll"). This module is a thin
orchestration layer over the library's own converter factory; it builds NO
byte-level migration logic itself.

:func:`make_payload_converters` returns, per kept connection (keyed by the source
``Connection``'s object identity — the ROS 2 ``Connection`` is unhashable, matching
the ``edit_bag`` connection map), the ``Callable[[bytes | memoryview], memoryview]``
that converts that msgtype's payload from the source wireformat to the destination.
It delegates entirely to ``rosbags.convert.converter``:

* :func:`is_same_wireformat` recursively compares the source/destination field
  definitions (including nested submessages + arrays) — far more correct than a
  format-string compare.
* :func:`generate_message_converter` returns the right callable PER msgtype:
  ``memoryview`` identity (same wireformat AND same ``is2``), ``cdr_to_ros1`` /
  ``ros1_to_cdr`` (byte-level, same field layout across versions), or
  ``migrate_bytes`` (full deserialize → migrate fields → reserialize, used when the
  field set differs — e.g. the ``Header.seq`` case). A SHARED ``cache`` dict is
  threaded across all connections so repeated msgtypes reuse the compiled converter.

When the source and destination wireformats AGREE for every msgtype
(``src_is2 == dst_is2`` and matching field defs — ROS 1 → ROS 1, or
ROS 2-sqlite3 ↔ MCAP, both CDR), every converter is the ``memoryview`` identity, so
``edit_bag`` copies the raw bytes losslessly (the D-04 raw-copy half, unchanged from
Plan 11-01) — this module is only ENGAGED when the wireformats differ.

DESTINATION typestore: the target ROS version's built-in store —
``get_typestore(Stores.ROS1_NOETIC)`` for a ROS 1 (``.bag``) destination,
``get_typestore(Stores.ROS2_HUMBLE)`` for a ROS 2 destination (mirrors
``tools/make_fixtures.py``). The destination msgtype is the SAME as the source for
the fixture corpus (Twist/Imu/Image are named identically across ROS versions);
``rosbags`` handles legacy renames internally via ``STATIC_MSGTYPE_RENAMES``.

OFFLINE INVARIANT (11-RESEARCH Pitfall 5): every ``rosbags`` import is LAZY inside a
function body, so ``import rosbagger_core.edit`` (which never imports this module at
top level) pulls in no ``rosbags`` / heavy stack.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from rosbags.interfaces import Connection
    from rosbags.typesys.store import Typestore

# A per-payload converter: source raw bytes -> destination raw bytes (memoryview).
PayloadConverter = Callable[["bytes | memoryview"], "memoryview"]


def dst_typestore(dst_is2: bool):
    """Return the destination built-in typestore for the target ROS version.

    ``dst_is2`` follows the rosbags ``is2 = dst.suffix != '.bag'`` rule: a ROS 2
    destination uses ``Stores.ROS2_HUMBLE``; a ROS 1 (``.bag``) destination uses
    ``Stores.ROS1_NOETIC`` (mirrors ``tools/make_fixtures.py``). The ``rosbags``
    import is lazy so the edit module stays light (offline invariant).
    """
    from rosbags.typesys import Stores, get_typestore

    return get_typestore(Stores.ROS2_HUMBLE if dst_is2 else Stores.ROS1_NOETIC)


def make_payload_converters(
    connections: list[Connection],
    src_typestore: Typestore,
    dst_ts: Typestore,
    *,
    src_is2: bool,
    dst_is2: bool,
) -> dict[int, PayloadConverter]:
    """Build a per-connection payload converter keyed by ``id(connection)``.

    This is the single point that implements the D-04 raw-copy-vs-convert split, PER
    message type, by delegating to ``rosbags.convert.converter``:

    * :func:`is_same_wireformat` recursively compares the source/destination field
      defs (nested submessages + arrays). When it returns ``True`` AND
      ``src_is2 == dst_is2``, the payload bytes are already compatible, so the
      converter is the ``memoryview`` IDENTITY — a lossless raw copy (the same-format
      edit path: ROS 1 -> ROS 1, ROS 2-sqlite3 <-> MCAP).
    * Otherwise :func:`generate_message_converter` returns the correct migrating
      callable for that msgtype — ``cdr_to_ros1`` / ``ros1_to_cdr`` (byte-level) or
      ``migrate_bytes`` (deserialize -> migrate fields -> reserialize, the
      ``Header.seq`` case). A SHARED ``cache`` dict is threaded across all connections
      so a repeated msgtype reuses the compiled converter.

    The map is keyed by the source ``Connection``'s object identity to match the
    ``edit_bag`` connection map (the ROS 2 ``Connection`` NamedTuple is unhashable;
    ``messages()`` yields identity-stable objects — Plan 11-01). The destination
    msgtype equals the source msgtype (``rosbags`` resolves legacy renames
    internally); for the fixture corpus the names are identical across ROS versions.
    ALL byte manipulation is the library's — never hand-rolled here (Don't Hand-Roll).
    """
    # Lazy import keeps `import rosbagger_core.edit` off the rosbags graph (Pitfall 5).
    from rosbags.convert.converter import generate_message_converter, is_same_wireformat

    cache: dict[str, object] = {}  # shared across msgtypes — the factory's compiled-converter cache
    converters: dict[int, PayloadConverter] = {}
    for conn in connections:
        if src_is2 == dst_is2 and is_same_wireformat(
            src_typestore, dst_ts, conn.msgtype, conn.msgtype
        ):
            # Same wireformat -> the bytes need no migration; the identity raw-copies
            # them (memoryview accepts both bytes and memoryview, returns memoryview).
            converters[id(conn)] = memoryview
            continue
        converters[id(conn)] = generate_message_converter(
            src_typestore,
            dst_ts,
            conn.msgtype,
            conn.msgtype,  # dst msgtype == src msgtype (rosbags handles legacy renames)
            cache,
            src_is2=src_is2,
            dst_is2=dst_is2,
        )
    return converters
