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
    alias: bool = True,
    backend: QueryBackend | None = None,
) -> pyarrow.Table:
    """Run ``sql`` over an OPEN ``reader``, returning the result as a ``pyarrow.Table``.

    Loads ONLY the topics the SQL references (connection-filtered, so unreferenced
    topics are never deserialized — QURY-05), registers each as a relation in the
    swappable ``backend`` (default a fresh in-memory ``DuckDBBackend``), executes,
    and returns Arrow (QURY-06). A ``SELECT *`` materializes a topic's heavy blobs;
    an explicit projection naming no blob omits them (the QURY-07 lazy default), and
    materializes ONLY the referenced columns ∪ the four standard columns (the QURY-09
    projection pushdown — Plan 10-03). An unmapped table name raises
    :class:`UnknownTableError` (listing the available tables) BEFORE anything loads.

    Pipeline (D-02 / 10-RESEARCH Pattern 4): ``parse`` → build per-topic
    ``TableSchema`` up front (O(1) metadata, no ``reader.read()``) → (if ``alias``)
    expand the alias pack on the parsed tree, gated to the single-base-topic case
    (Open Q1) → recompute ``referenced_tables``/``referenced_columns``/``has_star``
    on the (possibly rewritten) tree → load only referenced topics, materializing
    per-topic ``include`` (heavy-blob) ∧ ``restrict`` (projection) column sets →
    forward the REWRITTEN SQL (``tree.sql("duckdb")``) to ``backend.execute``.

    Args:
        sql: the user's SQL — the trusted interface. The orchestrator NEVER builds
            SQL by string concatenation; when ``alias`` expands a short token it
            does so inside the ``sqlglot`` AST (quoted identifiers) and forwards
            ``tree.sql("duckdb")`` — the same trusted-SQL boundary as Phase 5
            (threat T-05-04 / T-10-07), not an injection vector.
        reader: an ALREADY-OPEN ``BagReader`` (the caller owns the
            ``with RosbagsReader(...) as reader:`` lifecycle — Open Q2). Its
            ``topics``/``typestore`` drive table resolution and schema build.
        alias: when ``True`` (default, D-11) expand the built-in alias pack
            (``vx`` → the per-msgtype dotted velocity column) — but ONLY when the
            query references exactly one distinct base topic (Open Q1), so a
            JOIN/CTE/multi-topic query is a safe no-op. ``alias=False`` (the
            ``--no-alias`` escape hatch) disables expansion entirely.
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
    # stack. Mirrors inspect.collect_table_schemas. `expand_aliases` is sqlglot-only
    # (pure-Python) but is imported HERE all the same to keep the module top stdlib-light.
    from rosbagger_core.backend.alias import expand_aliases
    from rosbagger_core.backend.resolve import (
        has_star,
        parse,
        referenced_columns,
        referenced_tables_in,
    )
    from rosbagger_core.schema import build_arrow_table, build_table_schema

    # Step 1 — parse ONCE. Resolution (tables/columns/star) is DEFERRED until after
    # the alias rewrite (Step 4) so the projection + heavy-blob sets see the EXPANDED
    # dotted names (D-02 — the rewrite MUST precede `referenced_*`).
    tree = parse(sql)

    # Step 2 — build the per-bag topic↔table map and invert it (Pattern 4).
    topic_to_table, table_to_topic, topic_to_msgtype = _topic_table_maps(reader)

    # Step 3 — HOIST schema construction (10-RESEARCH Pattern 4). Build every mapped
    # topic's TableSchema up front, keyed by its SANITIZED table name. This is O(1)
    # metadata (no `reader.read()`), so it is cheap to do before resolution — and it
    # gives the alias existence-gate (D-04) the per-topic column-name sets it needs.
    # The same schemas are REUSED in the load loop below (no double-build). The
    # `typestore` binding is hoisted here with it (it was previously bound in Step 4,
    # AFTER this point — without the move build_table_schema would NameError).
    typestore = reader.typestore
    schemas_by_table = {
        topic_to_table[topic]: build_table_schema(topic_to_msgtype[topic], typestore, topic=topic)
        for topic in topic_to_table
    }

    # Step 4 — alias expansion (D-02), gated to the single-base-topic case (Open Q1).
    # Map the referenced base tables (CTE-subtracted) through to their topics; ignore
    # names that map to no topic (those raise UnknownTableError below). Only when
    # EXACTLY ONE distinct base topic resolves do we expand — keyed on that topic's
    # msgtype and existence-gated on its schema column names. With zero or >1 base
    # topics (JOIN/CTE/multi-topic) OR `alias=False`, expansion is skipped (safe
    # no-op, A3 / Pitfall 2) so an ambiguous short token is left for DuckDB to reject.
    if alias:
        base_tables = [t for t in referenced_tables_in(tree) if t in table_to_topic]
        if len(base_tables) == 1:
            only_table = base_tables[0]
            schema = schemas_by_table[only_table]
            tree = expand_aliases(
                tree,
                schema.msgtype,
                {c.name for c in schema.columns},
            )

    # Step 5 — derive tables / columns / star from the (possibly rewritten) tree
    # (D-02 — these MUST run after expansion so they see the expanded dotted names).
    tables = referenced_tables_in(tree)
    columns = referenced_columns(tree)
    star = has_star(tree)

    # Step 6 — resolve each referenced table name to a topic; an unmapped name
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

    # Step 7 — load only the referenced topics, register, execute. The backend is
    # entered via `with` so its connection is released even on error; `execute`
    # materializes the Arrow result before close, so the return outlives it.
    own_backend = backend is None
    backend = backend if backend is not None else _default_backend()
    # Accumulate each referenced table's columns (keyed by the SANITIZED table name
    # the SQL uses) so an unknown-column error can list them WITHOUT rebuilding
    # (07-RESEARCH §2 / Open Q2 — all referenced tables' columns, grouped; the
    # single-FROM case collapses to one entry).
    columns_by_table: dict[str, list[str]] = {}
    try:
        for topic in referenced_topics:
            # Reuse the hoisted schema (Step 3) — no double-build (Pattern 4).
            schema = schemas_by_table[topic_to_table[topic]]
            columns_by_table[topic_to_table[topic]] = [c.name for c in schema.columns]
            # Heavy-blob include set: the referenced columns that are heavy blobs,
            # OR ALL of this topic's heavy blobs when the SQL is a SELECT *
            # (05-RESEARCH Pitfall 3 / A1 — a star materializes blobs).
            heavy = {c.name for c in schema.columns if c.is_heavy_blob}
            include = heavy if star else (heavy & columns)
            msgs = reader.read(topics={topic})  # the Task 1 connection-filtered seam
            arrow = build_arrow_table(msgs, schema, include=include)
            # Register under the SANITIZED table name — the name the SQL references.
            backend.register_table(topic_to_table[topic], arrow)
        # Step 8 — forward the REWRITTEN SQL (`tree.sql("duckdb")`, D-02): when alias
        # expansion ran, `tree` carries the expanded dotted columns, so the regenerated
        # SQL is what must reach DuckDB; when it did not, `tree` is the parsed original,
        # so this round-trips the user's SQL unchanged. The string is sqlglot-rendered
        # from the AST (never hand-concatenated), preserving the trusted-SQL boundary
        # (T-05-04 / T-10-07). An unknown column surfaces as duckdb.BinderException;
        # catch it by TYPE (robust), then NARROW to the unknown-column case by message
        # before re-mapping (CR-01). duckdb.BinderException is NOT specific to unknown
        # columns — DuckDB raises the SAME type for GROUP BY / HAVING / other binder-stage
        # errors. Only when the `_BINDER_COL` regex matches ('Referenced column "X" not
        # found') is it truly an unknown column: raise the typed UnknownColumnError
        # carrying the referenced tables' columns (CLI-03). On a NON-match
        # (GROUP BY/HAVING/other), re-raise the ORIGINAL BinderException unchanged so the
        # real DuckDB error surfaces verbatim. The catch inspects the EXCEPTION, not the
        # SQL string, so forwarding the rewritten SQL does not affect it. duckdb is
        # imported LAZILY here — already pulled in via _default_backend(), but the explicit
        # import keeps the module top stdlib-light (offline; 07-RESEARCH §2 / Pitfall 6).
        try:
            return backend.execute(tree.sql("duckdb"))
        except duckdb_binder_exception() as e:
            m = _BINDER_COL.search(str(e))
            if m is None:
                raise  # not an unknown-column error (e.g. GROUP BY/HAVING) — surface as-is
            raise UnknownColumnError(m.group(1), columns_by_table) from e
    finally:
        # Own the lifecycle only for the default backend; a caller-supplied
        # backend is the caller's to close (it may be reused across queries). This
        # finally still runs on the BinderException -> UnknownColumnError path.
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


def duckdb_binder_exception() -> type[Exception]:
    """Return ``duckdb.BinderException`` (the unknown-column signal), imported lazily.

    Isolated like ``_default_backend`` so ``import duckdb`` never happens at this
    module's top level (offline invariant — ``import rosbagger_core.backend`` /
    ``rosbagger_core.errors`` must not pull duckdb; 07-RESEARCH Pitfall 6). Called
    only in the ``except`` clause around ``backend.execute`` in :func:`query`, where
    duckdb is already loaded via the default backend.
    """
    import duckdb

    return duckdb.BinderException
