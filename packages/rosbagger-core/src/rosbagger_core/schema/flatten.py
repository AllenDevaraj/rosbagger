"""The flattening walk + the row-extract / Arrow-build half of Phase 3.

The project-glue of Phase 3, in two cooperating halves:

* **Schema build** (``03-02``): given a message-type string and the ``rosbags``
  typestore, ``build_table_schema`` walks the declared field-AST
  (``get_msgdef(msgtype).fields``) into a backend-neutral
  :class:`~rosbagger_core.schema.model.TableSchema` — nested scalars flattened to
  dotted column names (``linear.x``, ``header.stamp.sec``; QURY-02),
  arrays/sub-message-arrays kept as single ``LIST`` / ``LIST``-of-``STRUCT`` leaf
  columns (the type side lives in :mod:`~rosbagger_core.schema.types`; QURY-03),
  and the four always-present columns ``t``/``t_ns``/``stamp``/``topic``
  prepended in that fixed order (QURY-04). It introspects the **declared** type —
  never a single message's runtime values — so the schema is stable across every
  message on a topic (including empty arrays and headerless messages; Pitfall 1).

* **Row extract + Arrow build** (``03-03``): ``flatten_message`` pulls each
  non-standard leaf's value off a deserialized message by following its
  ``ros_path`` (``reduce(getattr, path, msg)``), and ``build_arrow_table`` turns a
  stream of Phase 2 :class:`~rosbagger_core.reader.Message` records into a typed
  ``pyarrow.Table`` whose schema is exactly ``schema.arrow_schema(include=...)``.
  Each column array is built with its explicit ``ColumnDef.arrow_type`` (never
  inferred — Pitfall 1), ndarray array-values are passed straight through
  (Pitfall 2), the standard columns come off the ``Message`` record, and heavy
  byte blobs are skipped unless named in ``include`` (the QURY-07 lazy seam Phase
  5 drives). An empty stream still yields a typed empty Table (RESEARCH §7).

Each :class:`ColumnDef` carries its ``ros_path`` (the attribute chain to follow on
a deserialized message); the standard columns have an empty ``ros_path`` and take
their values straight off the ``Message``.

Offline note: importing ``pyarrow`` + ``rosbags.interfaces.Nodetype`` here is SAFE
(neither is a forbidden ROS module); ``rosbagger_core/__init__`` does not import
this subpackage at top level, so ``import rosbagger_core`` stays light. No
``import duckdb``, no SQL execution (Phase 5).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import reduce

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
    # WR-01 fix: enforce a UNIQUE-NAME invariant on the body columns. A message
    # body field literally named `t`/`t_ns`/`stamp`/`topic` (or a body name that
    # repeats) would otherwise produce duplicate column `name`s, which collapses
    # build_arrow_table's name-keyed `values` dict and raises ArrowTypeError
    # (05-RESEARCH Pitfall 1, VERIFIED). We rename the colliding BODY column
    # (suffix `_` until unique), keeping its ros_path/arrow_type/is_heavy_blob
    # exactly as `_walk_fields` produced them so the value still extracts. The
    # four standard columns are NEVER renamed — `t`/`t_ns`/`stamp`/`topic` are
    # the documented QURY-04 contract (the "namespace the standard column"
    # alternative is rejected, RESEARCH Pitfall 1).
    taken: set[str] = set(_STANDARD_COLUMN_NAMES)
    for name, path, arrow_type, heavy in _walk_fields(msgtype, typestore):
        unique_name = name
        while unique_name in taken:
            unique_name += "_"
        taken.add(unique_name)
        columns.append(
            ColumnDef(name=unique_name, arrow_type=arrow_type, ros_path=path, is_heavy_blob=heavy)
        )
    return TableSchema(
        table_name=sanitize_table_name(topic),
        topic=topic,
        msgtype=msgtype,
        columns=columns,
    )


# The standard-column names (those with an empty ros_path); their values come off
# the Phase 2 Message record, NOT the message body. `t` and `stamp` are int-ns
# values materialized as pa.timestamp("ns") (Pattern 3 / Pitfall 6).
_STANDARD_COLUMN_NAMES = frozenset(name for name, _ in STANDARD_COLUMNS)


def _is_data_column(col: ColumnDef) -> bool:
    """True for a flattened message-body column (a non-empty ``ros_path``).

    The four standard columns carry an empty ``ros_path`` and are sourced from
    the ``Message`` record, so they are NOT data columns.
    """
    return bool(col.ros_path)


def flatten_message(msg, schema: TableSchema, *, include: set[str] | None = None) -> dict:
    """Extract ``{dotted_col_name: value}`` for a message's body columns.

    Walks the schema's **data** columns (those with a non-empty ``ros_path`` —
    i.e. everything except the four standard columns) and pulls each value off
    the deserialized ``msg`` via ``reduce(getattr, col.ros_path, msg)`` (research
    Pattern 4): e.g. ``("linear", "x")`` -> ``msg.linear.x``. Scalar leaves come
    back as native ``int``/``float``/``str``/``bool``; array leaves come back as a
    ``numpy.ndarray`` and are passed through unchanged (NOT ``.tolist()``'d —
    Pitfall 2) for ``pyarrow`` to ingest directly.

    Heavy byte blobs (``is_heavy_blob``) are omitted unless their dotted ``name``
    is in ``include`` (the QURY-07 lazy seam, keyed on the dotted column name —
    research Open Question 2). The standard columns are never part of the body
    extraction; ``build_arrow_table`` sources them from the ``Message`` record.

    Args:
        msg: a deserialized ``rosbags`` message object (the ``Message.msg`` body).
        schema: the :class:`TableSchema` for this topic (its columns drive the walk).
        include: dotted column names of heavy blobs to re-include (default: none).

    Returns:
        A dict mapping each extracted column's dotted name to its raw value.
    """
    allowed = include or set()
    return {
        col.name: reduce(getattr, col.ros_path, msg)
        for col in schema.columns
        if _is_data_column(col) and (not col.is_heavy_blob or col.name in allowed)
    }


def build_arrow_table(
    messages: Iterable,
    schema: TableSchema,
    *,
    include: set[str] | None = None,
) -> pa.Table:
    """Build a typed ``pyarrow.Table`` for one topic from a stream of Messages.

    Consumes ``messages`` (an iterable of Phase 2
    :class:`~rosbagger_core.reader.Message`) **once**, accumulating parallel
    per-column value lists, then builds each column array with its explicit
    ``ColumnDef.arrow_type`` (``pa.array(values, type=...)`` — never inferred, so
    an empty ``SEQUENCE`` cannot destabilize the type; Pitfall 1) and assembles a
    ``pyarrow.Table`` whose schema is exactly ``schema.arrow_schema(include=include)``.

    Column sourcing:

    * Standard columns come off each ``Message``: ``t`` and ``stamp`` from the
      int-ns values typed ``pa.timestamp("ns")`` (a ``None`` ``stamp`` -> NULL,
      e.g. headerless ``/cmd_vel``), ``t_ns`` as ``pa.int64()``, ``topic`` as
      ``pa.string()`` (Pattern 3 / Pitfall 6).
    * Data columns come from :func:`flatten_message` (ndarrays passed straight
      through — Pitfall 2).

    Heavy byte blobs are skipped unless named in ``include`` (the QURY-07 lazy
    seam Phase 5 drives from parsed SQL). A zero-message stream still returns a
    Table carrying the full typed schema (RESEARCH §7).

    Does NOT ``import duckdb`` or run SQL — it emits backend-neutral Arrow that
    Phase 5 registers zero-copy.

    Args:
        messages: an iterable of ``Message`` records (consumed once).
        schema: the :class:`TableSchema` for this topic.
        include: dotted column names of heavy blobs to materialize (default: none).

    Returns:
        A ``pyarrow.Table`` matching ``schema.arrow_schema(include=include)``.
    """
    arrow_schema = schema.arrow_schema(include=include)
    # The kept columns, in declared order, are exactly the fields of arrow_schema
    # (it applies the same heavy-blob filter) — drive off it to stay in lockstep.
    kept = [col for col in schema.columns if col.name in arrow_schema.names]
    # This name-keyed dict relies on the UNIQUE-NAME invariant build_table_schema
    # guarantees (WR-01 fix): colliding body columns are pre-renamed there, so no
    # two ColumnDefs share a `name` and no column collapses here (RESEARCH
    # Pitfall 1 "Note for planner" — no code change needed here once names are
    # unique).
    values: dict[str, list] = {col.name: [] for col in kept}

    for msg in messages:
        body = flatten_message(msg.msg, schema, include=include)
        for col in kept:
            # Data columns come from the message body; the standard columns
            # (empty ros_path) come off the Message record by the same name.
            value = body[col.name] if _is_data_column(col) else getattr(msg, col.name)
            values[col.name].append(value)

    arrays = [pa.array(values[field.name], type=field.type) for field in arrow_schema]
    return pa.table(arrays, schema=arrow_schema)
