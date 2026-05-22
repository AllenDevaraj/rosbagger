"""The backend-neutral public schema model: ``ColumnDef`` + ``TableSchema``.

This is the stable, dependency-free contract every later Phase 3 plan produces
and that downstream phases consume:

* Phase 3 (this phase) — ``03-02``/``03-03`` build these from the ``rosbags``
  typestore field-AST (flattening nested scalars to dotted columns, arrays to
  ``LIST`` / sub-message arrays to ``LIST`` of ``STRUCT``, the four always-present
  ``t``/``t_ns``/``stamp``/``topic`` columns, and the lazy heavy-blob exclusion).
* Phase 4 (``bagq tables``) — renders a ``TableSchema`` (table name + columns).
* Phase 5 (``QueryBackend`` / DuckDB) — ingests the ``arrow_schema`` and drives
  the heavy-blob ``include`` set from the columns a parsed SQL query references.

It deliberately imports ONLY the standard library — no ``pyarrow``, no
``rosbags``, and **no** ``duckdb``. ``ColumnDef.arrow_type`` is therefore typed
loosely as ``object``: this module describes the shape of a table without
binding to the Arrow type system, which keeps the offline-import graph light
(``import rosbagger_core`` must not pull the heavy stack — Phase 1 decision) and
keeps these dataclasses trivially unit-testable. The actual ``pyarrow`` build
lives behind ``arrow_schema`` and is filled in by plan ``03-03``; here it is a
documented ``NotImplementedError`` stub.

``include`` keys (for ``column_names`` / ``arrow_schema``) are the **dotted
column name** — the same string used as the column's ``name`` and as the Arrow
column name downstream (research Open Question 2). For the standard heavy blobs
(``Image.data``, ``PointCloud2.data``) that degenerates to the bare top-level
name; keying on the dotted name also handles a hypothetical nested blob.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnDef:
    """One flattened column of a per-topic table.

    Frozen + slotted: an immutable value object describing a single output
    column, independent of any query backend.

    Fields:
        name: The output column name. For nested scalars this is the dotted,
            faithful path (e.g. ``"twist.linear.x"``); for the prepended
            standard columns it is ``t`` / ``t_ns`` / ``stamp`` / ``topic``.
            This is also the SQL identifier (quoted via ``sqlglot`` at SQL-build
            time in Phase 5 — never concatenated raw).
        arrow_type: The column's Arrow ``DataType``, typed loosely as ``object``
            so this module imports no ``pyarrow``. Plans ``03-02``/``03-03``
            populate it with a real ``pyarrow.DataType``; callers that only need
            the schema shape (Phase 4) can ignore it.
        ros_path: The tuple of attribute names to follow on a deserialized
            message to reach this column's value (e.g. ``("linear", "x")`` ->
            ``msg.linear.x``). The row extractor in ``03-02`` walks this.
        is_heavy_blob: ``True`` iff this is a heavy byte blob — structurally a
            variable-length ``SEQUENCE`` of ``uint8``/``byte``/``char`` (e.g.
            ``Image.data``). Heavy-blob columns are omitted from the default
            schema/row build (QURY-07) unless a caller names them in ``include``.
    """

    name: str
    arrow_type: object
    ros_path: tuple[str, ...]
    is_heavy_blob: bool


@dataclass(frozen=True, slots=True)
class TableSchema:
    """The backend-neutral description of one topic's table.

    Frozen + slotted. Produced once per topic by ``build_table_schema`` (plan
    ``03-02``); rendered by Phase 4 and ingested by Phase 5.

    Fields:
        table_name: The sanitized, collision-resolved table name
            (``/camera/image_raw`` -> ``camera_image_raw``; see
            ``rosbagger_core.schema.names``).
        topic: The original topic string (e.g. ``/camera/image_raw``). Kept so
            Phase 4 can print the topic -> table mapping.
        msgtype: The message type string (e.g. ``sensor_msgs/msg/Image``).
        columns: The flattened columns in declared order — the four standard
            columns first, then the message's flattened fields.
    """

    table_name: str
    topic: str
    msgtype: str
    columns: list[ColumnDef]

    def column_names(self, include: set[str] | None = None) -> list[str]:
        """Return column names in declared order, applying the heavy-blob filter.

        By default (``include=None``) heavy-blob columns (``is_heavy_blob`` is
        ``True``) are omitted — the QURY-07 lazy-materialization default. A
        heavy-blob column is re-included only when its ``name`` appears in
        ``include``.

        The ``include`` keys are the **dotted column name** (the same string as
        ``ColumnDef.name`` and the downstream Arrow column name — research Open
        Question 2). Phase 5 computes this set from the columns a parsed SQL
        query references; for the standard blobs it is simply ``{"data"}``.

        Non-heavy columns are always included regardless of ``include``.
        """
        allowed = include or set()
        return [col.name for col in self.columns if not col.is_heavy_blob or col.name in allowed]

    def arrow_schema(self, include: set[str] | None = None) -> object:
        """Build the ``pyarrow.Schema`` for this table (the Phase 5 ingest seam).

        Deferred: the Arrow build lands in plan ``03-03`` (it needs ``pyarrow``,
        which this backend-neutral module intentionally does not import). The
        ``include`` set will follow the same dotted-name heavy-blob contract as
        ``column_names`` — heavy blobs omitted unless named.
        """
        raise NotImplementedError("filled in 03-03")
