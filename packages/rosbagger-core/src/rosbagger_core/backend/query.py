"""The query orchestrator: ``query(sql, reader)`` → ``pyarrow.Table`` (QURY-05/06).

This is the top-level wiring that ties together everything Phases 2-5 built. Given
the user's SQL and an OPEN ``BagReader``, it:

1. **Resolves** (``backend/resolve.py`` / ``sqlglot``) which *tables* the SQL
   references (CTE-subtracted), which *columns*, and whether it is a ``SELECT *``.
2. **Inverts** the per-bag topic→table map (the same shared ``TableNameResolver``
   pass as ``inspect.collect_table_schemas``, skipping multi-msgtype topics) to
   learn which *topic* each referenced table name maps to — raising a clear
   ``UnknownTableError`` (listing the available tables) on an unmapped name BEFORE
   loading anything (05-RESEARCH Pattern 4 / threat T-05-06).
3. **Lazy-loads** ONLY the referenced topics via ``reader.read(topics={topic})``
   (the connection-filtered seam from Task 1 — unreferenced topics are never
   deserialized; QURY-05 / 05-RESEARCH Pitfall 2), building each into a typed
   ``pyarrow.Table``. The heavy-blob ``include`` set is the referenced columns
   that are heavy blobs, OR all of a topic's heavy blobs when the SQL is a
   ``SELECT *`` (05-RESEARCH Pitfall 3 / A1 — ``SELECT *`` materializes blobs).
4. **Registers** each Arrow table under its sanitized table name and **executes**
   the SQL through the swappable ``QueryBackend`` (default ``DuckDBBackend``),
   returning the result ``pyarrow.Table`` (QURY-06).

Trust boundary (threat T-05-04/T-05-05): the USER's SQL is the INTENDED interface
of a local single-user CLI — it is forwarded to ``backend.execute`` AS-IS, not an
injection vector. The untrusted input is bag-derived NAMES, and tables are
registered under ``TableNameResolver`` names (the ``[0-9A-Za-z_]`` allow-list,
Phase 3 T-03-01); this orchestrator interpolates NO identifier itself (it builds
no SQL), so no new injection surface is introduced.

OFFLINE INVARIANT (05-RESEARCH Anti-Patterns): the heavy stack
(``schema``/``pyarrow``, ``resolve``/``sqlglot``, ``duckdb_backend``/``duckdb``) is
imported LAZILY inside :func:`query` — never at this module's top level — so
``import rosbagger_core`` and ``import rosbagger_core.backend`` stay light
(``tests/test_offline_guard.py``). This module is reached via
``from rosbagger_core.backend.query import query`` (``backend/__init__`` adds no
eager import). Only the standard library + the local ``QueryBackend`` ABC (itself
stdlib-only) are imported at module scope.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rosbagger_core.errors import UnknownColumnError, UnknownTableError

from .base import QueryBackend

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow

    from rosbagger_core.reader import BagReader

# UnknownTableError moved to rosbagger_core.errors (the stdlib-only shared home);
# imported above and re-exported here so the canonical class is identical and any
# existing ``from rosbagger_core.backend.query import UnknownTableError`` still
# resolves it. ``errors`` is stdlib-only (difflib), so this top-level import does
# NOT break the offline invariant (test_offline_guard.py). 07-02 also imports
# ``UnknownColumnError`` for the BinderException -> typed-error mapping in query().
__all__ = ["UnknownColumnError", "UnknownTableError", "query"]

# DuckDB's unknown-column BinderException message embeds the offending column as
# 'Referenced column "X" not found in FROM clause! ...'. We catch the exception by
# TYPE (robust across locales/versions); this stdlib regex parses the message ONLY
# to recover the column NAME for the teaching error (07-RESEARCH §2; a miss degrades
# the name to "?" while still listing the table's columns). ``re`` is stdlib — safe
# at module top, no offline-invariant impact.
_BINDER_COL = re.compile(r'Referenced column "([^"]+)" not found')


def _topic_table_maps(reader: BagReader) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build ``(topic_to_table, table_to_topic, topic_to_msgtype)`` from the reader.

    Mirrors ``inspect.collect_table_schemas`` exactly: a SHARED
    ``TableNameResolver`` over ``sorted(reader.topics.items())`` so collision
    resolution is deterministic, SKIPPING any topic whose ``info.msgtype is None``
    (a multi-msgtype topic — passing ``None`` to ``build_table_schema`` raises
    ``KeyError: None``; 05-RESEARCH Pattern 4 / Pitfall 4). The inversion is safe
    because the resolver guarantees unique table names, so no topic is dropped.
    """
    from rosbagger_core.schema import TableNameResolver

    resolver = TableNameResolver()  # shared so collision state accumulates across topics
    topic_to_table: dict[str, str] = {}
    topic_to_msgtype: dict[str, str] = {}
    for topic, info in sorted(reader.topics.items()):
        if info.msgtype is None:  # multi-msgtype topic — skip, never pass None
            continue
        topic_to_table[topic] = resolver.resolve(topic)
        topic_to_msgtype[topic] = info.msgtype
    table_to_topic = {table: topic for topic, table in topic_to_table.items()}
    return topic_to_table, table_to_topic, topic_to_msgtype


def query(
    sql: str,
    reader: BagReader,
    *,
    backend: QueryBackend | None = None,
) -> pyarrow.Table:
    """Run ``sql`` over an OPEN ``reader``, returning the result as a ``pyarrow.Table``.

    Loads ONLY the topics the SQL references (connection-filtered, so unreferenced
    topics are never deserialized — QURY-05), registers each as a relation in the
    swappable ``backend`` (default a fresh in-memory ``DuckDBBackend``), executes,
    and returns Arrow (QURY-06). A ``SELECT *`` materializes a topic's heavy blobs;
    an explicit projection naming no blob omits them (the QURY-07 lazy default). An
    unmapped table name raises :class:`UnknownTableError` (listing the available
    tables) BEFORE anything is loaded.

    Args:
        sql: the user's SQL — the trusted interface; forwarded to ``execute``
            as-is (NOT an injection vector; threat T-05-04).
        reader: an ALREADY-OPEN ``BagReader`` (the caller owns the
            ``with RosbagsReader(...) as reader:`` lifecycle — Open Q2). Its
            ``topics``/``typestore`` drive table resolution and schema build.
        backend: an optional ``QueryBackend`` (swappable per call). Defaults to a
            fresh ``DuckDBBackend``; entered via ``with`` so its connection is
            released even on error (Open Q3 / 05-RESEARCH Pitfall 5). ``execute``
            fully materializes the result Arrow table before the backend closes,
            so the returned table outlives the connection.

    Returns:
        The query result as a ``pyarrow.Table`` (a 0-row result still carries the
        full column schema — 05-RESEARCH Pitfall 4; callers must not index
        ``result[0]``).

    Raises:
        UnknownTableError: a referenced table name maps to no topic in the bag.
    """
    # Lazy imports (offline invariant): keep this module's top level — and thus
    # `import rosbagger_core.backend` — free of the heavy duckdb/sqlglot/pyarrow
    # stack. Mirrors inspect.collect_table_schemas.
    from rosbagger_core.backend.resolve import (
        has_star,
        parse,
        referenced_columns,
        referenced_tables_in,
    )
    from rosbagger_core.schema import build_arrow_table, build_table_schema

    # Step 1 — parse ONCE, then derive tables / columns / star from the one tree.
    tree = parse(sql)
    tables = referenced_tables_in(tree)
    columns = referenced_columns(tree)
    star = has_star(tree)

    # Step 2 — build the per-bag topic↔table map and invert it (Pattern 4).
    topic_to_table, table_to_topic, topic_to_msgtype = _topic_table_maps(reader)

    # Step 3 — resolve each referenced table name to a topic; an unmapped name
    # raises a clear error listing the available tables, BEFORE any load
    # (T-05-06: no silent empty result). v1 just lists; Phase 7 owns did-you-mean.
    referenced_topics: list[str] = []
    for table in tables:
        topic = table_to_topic.get(table)
        if topic is None:
            # The constructor now owns the message + the difflib did-you-mean (CLI-02);
            # pass it the offending name and the available table names.
            raise UnknownTableError(table, sorted(table_to_topic))
        referenced_topics.append(topic)

    # Step 4 — load only the referenced topics, register, execute. The backend is
    # entered via `with` so its connection is released even on error; `execute`
    # materializes the Arrow result before close, so the return outlives it.
    typestore = reader.typestore
    own_backend = backend is None
    backend = backend if backend is not None else _default_backend()
    try:
        for topic in referenced_topics:
            schema = build_table_schema(topic_to_msgtype[topic], typestore, topic=topic)
            # Heavy-blob include set: the referenced columns that are heavy blobs,
            # OR ALL of this topic's heavy blobs when the SQL is a SELECT *
            # (05-RESEARCH Pitfall 3 / A1 — a star materializes blobs).
            heavy = {c.name for c in schema.columns if c.is_heavy_blob}
            include = heavy if star else (heavy & columns)
            msgs = reader.read(topics={topic})  # the Task 1 connection-filtered seam
            arrow = build_arrow_table(msgs, schema, include=include)
            # Register under the SANITIZED table name — the name the SQL references.
            backend.register_table(topic_to_table[topic], arrow)
        # Step 5 — forward the user's SQL as-is (trusted interface; T-05-04).
        return backend.execute(sql)
    finally:
        # Own the lifecycle only for the default backend; a caller-supplied
        # backend is the caller's to close (it may be reused across queries).
        if own_backend:
            backend.close()


def _default_backend() -> QueryBackend:
    """Construct the default ``DuckDBBackend`` (imported lazily — duckdb is heavy).

    Isolated so ``duckdb`` is pulled in ONLY when the default backend is actually
    constructed (a caller passing their own ``backend=`` never triggers the
    import) — preserving the offline invariant.
    """
    from rosbagger_core.backend.duckdb_backend import DuckDBBackend

    return DuckDBBackend()
