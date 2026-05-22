"""``build_table_schema`` — the recursive flattening walk (QURY-02, QURY-04).

The project-glue half of Phase 3: given a message-type string and the ``rosbags``
typestore, it walks the declared field-AST (``get_msgdef(msgtype).fields``) into a
backend-neutral :class:`~rosbagger_core.schema.model.TableSchema` — nested scalars
flattened to dotted column names (``linear.x``, ``header.stamp.sec``; QURY-02),
arrays/sub-message-arrays kept as single ``LIST`` / ``LIST``-of-``STRUCT`` leaf
columns (the type side is done in :mod:`~rosbagger_core.schema.types`; QURY-03),
and the four always-present columns ``t``/``t_ns``/``stamp``/``topic`` prepended in
that fixed order (QURY-04).

It introspects the **declared** type via the typestore AST — never a single
message's runtime values — so the schema is stable across every message on a
topic (including empty arrays and headerless messages; research Pitfall 1).

Row-VALUE extraction and the live ``pyarrow.Table`` build are NOT here — they land
in plan ``03-03`` (this module produces the ``TableSchema``/columns only). Each
:class:`ColumnDef` carries its ``ros_path`` (the attribute chain to follow on a
deserialized message), so ``03-03``'s extractor walks it without re-deriving the
shape.

Offline note: importing ``pyarrow`` + ``rosbags.interfaces.Nodetype`` here is SAFE
(neither is a forbidden ROS module); ``rosbagger_core/__init__`` does not import
this subpackage at top level, so ``import rosbagger_core`` stays light. No
``import duckdb`` (Phase 5).
"""

from __future__ import annotations

from collections.abc import Iterator

import pyarrow as pa
from rosbags.interfaces import Nodetype

from .model import ColumnDef, TableSchema
from .names import sanitize_table_name
from .types import arrow_type_of

# The four always-present columns, in fixed order (QURY-04; research Pattern 3).
# Their Arrow types map to DuckDB TIMESTAMP_NS / BIGINT / TIMESTAMP_NS / VARCHAR
# (VERIFIED round-trip). `stamp` is nullable (headerless topics like /cmd_vel get
# an all-NULL stamp); nullability is an Arrow-field property applied at the
# pyarrow.Schema build in 03-03, not on these backend-neutral ColumnDefs.
STANDARD_COLUMNS: list[tuple[str, pa.DataType]] = [
    ("t", pa.timestamp("ns")),  # log/receive time      -> TIMESTAMP_NS
    ("t_ns", pa.int64()),  # exact ns               -> BIGINT
    ("stamp", pa.timestamp("ns")),  # header.stamp or NULL   -> TIMESTAMP_NS (nullable)
    ("topic", pa.string()),  # raw topic string       -> VARCHAR
]


def _walk_fields(
    msgtype: str,
    typestore,
    prefix: tuple[str, ...] = (),
    seen: frozenset[str] = frozenset(),
) -> Iterator[tuple[str, tuple[str, ...], pa.DataType, bool]]:
    """Yield ``(dotted_name, ros_path, arrow_type, is_heavy_blob)`` leaves.

    The shared flattening traversal (research Pattern 4). It recurses ONLY into
    ``Nodetype.NAME`` sub-messages, extending the dotted path; at every other node
    (``BASE``/``ARRAY``/``SEQUENCE``) it emits exactly one leaf column whose Arrow
    type comes from :func:`~rosbagger_core.schema.types.arrow_type_of`. Crucially
    it STOPS descending at ``ARRAY``/``SEQUENCE`` — that whole subtree becomes one
    ``LIST`` (or ``LIST``-of-``STRUCT``) column; it never dots into the element
    (Pitfall 4). Declared field order is preserved (the AST is ordered).

    ``seen`` carries the sub-message types on the current recursion path to break
    a (rare) self-referential custom definition (Pitfall 5) — cheap insurance;
    no standard ROS type needs it.
    """
    for fname, ftype in typestore.get_msgdef(msgtype).fields:
        path = (*prefix, fname)
        nt = ftype[0]
        if nt == Nodetype.NAME:  # sub-message -> recurse with a dotted prefix
            submsgtype = ftype[1] if isinstance(ftype[1], str) else ftype[1][0]
            if submsgtype in seen:  # cycle guard (Pitfall 5) — emit as a leaf, stop
                arrow_type, heavy = arrow_type_of(ftype, typestore)
                yield (".".join(path), path, arrow_type, heavy)
                continue
            yield from _walk_fields(submsgtype, typestore, path, seen | {submsgtype})
        else:  # BASE / ARRAY / SEQUENCE -> a single leaf column
            arrow_type, heavy = arrow_type_of(ftype, typestore)
            yield (".".join(path), path, arrow_type, heavy)


def build_table_schema(msgtype: str, typestore, *, topic: str) -> TableSchema:
    """Build the per-topic :class:`TableSchema` from a declared message type.

    Walks ``typestore.get_msgdef(msgtype).fields`` (the VERIFIED ``Nodetype`` AST)
    to produce, in order:

    1. the four standard columns ``t``/``t_ns``/``stamp``/``topic`` (empty
       ``ros_path``, ``is_heavy_blob=False`` — their values come straight off the
       Phase 2 ``Message`` record, not from the message body), then
    2. one :class:`ColumnDef` per flattened leaf: nested scalars as dotted columns
       (``linear.x``, ``header.stamp.sec``), arrays/sub-message-arrays as single
       ``LIST`` / ``LIST``-of-``STRUCT`` columns (recursion stops at the array).

    The top-level ``stamp`` column coexists with the nested ``header.stamp.*``
    columns by design — they have distinct names and are NOT de-duplicated
    (Pitfall 6). The schema is value-independent: it is identical for every
    message on the topic, including empty arrays and headerless messages.

    Args:
        msgtype: the message type string (e.g. ``geometry_msgs/msg/Twist``).
        typestore: the ``rosbags`` ``Typestore`` (the introspection source;
            downstream wiring fetches it from ``reader._reader.typestore``).
        topic: the topic this table is for; ``table_name`` is
            :func:`~rosbagger_core.schema.names.sanitize_table_name` of it. Both
            ``topic`` and ``msgtype`` are recorded on the returned schema.

    Returns:
        A :class:`TableSchema` with the standard columns first, then the
        message's flattened columns in declared order.
    """
    columns: list[ColumnDef] = [
        ColumnDef(name=name, arrow_type=arrow_type, ros_path=(), is_heavy_blob=False)
        for name, arrow_type in STANDARD_COLUMNS
    ]
    columns.extend(
        ColumnDef(name=name, arrow_type=arrow_type, ros_path=path, is_heavy_blob=heavy)
        for name, path, arrow_type, heavy in _walk_fields(msgtype, typestore)
    )
    return TableSchema(
        table_name=sanitize_table_name(topic),
        topic=topic,
        msgtype=msgtype,
        columns=columns,
    )
