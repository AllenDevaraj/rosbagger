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
from itertools import islice
from typing import TYPE_CHECKING

from rosbagger_core.errors import (
    MixedTypeTopicError,
    MultiBagEventsError,
    UnknownColumnError,
    UnknownTableError,
)

from .base import QueryBackend

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow

    from rosbagger_core.reader import BagReader
    from rosbagger_core.schema import TableSchema

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

# The four always-present standard columns (QURY-04). D-07: projection MUST always
# materialize these — they anchor ordering, `--plot` (vs t_ns), and time-joins, so a
# `SELECT vx` stays plottable. The orchestrator unions them into the per-topic
# `restrict` set (10-RESEARCH Pitfall 3 / Code Example 4); they are NOT special-cased
# in the schema layer (Plan 10-02 left that to here). Mirrors the names of
# ``schema.flatten.STANDARD_COLUMNS`` but is a stdlib-only frozenset so referencing it
# at this module's top level does not pull the heavy stack (offline invariant).
_STANDARD_COLUMNS: frozenset[str] = frozenset({"t", "t_ns", "stamp", "topic"})

# The RESERVED table name for the per-bag event sidecar (D-14). When the SQL
# references `events`, query() registers `<bag>.events.parquet` (loaded via
# `rosbagger_core.events.list_events`) under this name instead of resolving it as a
# topic — so a standard `BETWEEN` interval join (`... ON data.t_ns BETWEEN
# events.t_start_ns AND events.t_end_ns`) works natively (D-15). It is SUBTRACTED from
# the topic-resolution set so it never raises `UnknownTableError`; when no sidecar
# exists an EMPTY-schema relation is registered (Open Q3). A plain stdlib str constant —
# no offline-invariant impact.
_EVENTS_TABLE = "events"


def _topic_table_maps(
    reader: BagReader,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Build ``(topic_to_table, table_to_topic, topic_to_msgtype, mixed_type_topics)``.

    Mirrors ``inspect.collect_table_schemas`` exactly: a SHARED
    ``TableNameResolver`` over ``sorted(reader.topics.items())`` so collision
    resolution is deterministic, SKIPPING any topic whose ``info.msgtype is None``
    (a multi-msgtype topic — passing ``None`` to ``build_table_schema`` raises
    ``KeyError: None``; 05-RESEARCH Pattern 4 / Pitfall 4). The inversion is safe
    because the resolver guarantees unique table names, so no topic is dropped.

    A skipped multi-msgtype topic is recorded in ``mixed_type_topics`` keyed by its
    base sanitized name (``sanitize_table_name`` — NOT the shared resolver, so a skipped
    topic never consumes a collision suffix and the real topics' names stay identical to
    before). query() uses it to raise a truthful :class:`MixedTypeTopicError` instead of
    a misleading :class:`UnknownTableError` when such a topic is referenced (newE22).
    """
    from rosbagger_core.schema import TableNameResolver, sanitize_table_name

    resolver = TableNameResolver()  # shared so collision state accumulates across topics
    topic_to_table: dict[str, str] = {}
    topic_to_msgtype: dict[str, str] = {}
    mixed_type_topics: dict[str, str] = {}  # base sanitized table name -> topic (newE22)
    for topic, info in sorted(reader.topics.items()):
        if info.msgtype is None:  # multi-msgtype topic — skip, never pass None
            mixed_type_topics[sanitize_table_name(topic)] = topic
            continue
        topic_to_table[topic] = resolver.resolve(topic)
        topic_to_msgtype[topic] = info.msgtype
    table_to_topic = {table: topic for topic, table in topic_to_table.items()}
    return topic_to_table, table_to_topic, topic_to_msgtype, mixed_type_topics


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

    ``events`` is a RESERVED table name (D-14): when the SQL references it AND no real
    topic owns that table name, query() SUBTRACTS it from the topic-resolution set (so
    it never raises :class:`UnknownTableError`) and registers the per-bag sidecar
    (``<bag>.events.parquet``, loaded via ``rosbagger_core.events.list_events`` next to
    the single ``reader.paths[0]``) under the name ``events``. A standard SQL ``BETWEEN``
    interval join (``... ON data.t_ns BETWEEN events.t_start_ns AND events.t_end_ns``)
    then runs natively against it (D-15, no special operator). When no sidecar exists an
    EMPTY-schema ``events`` relation is registered, so a SELECT/join yields zero rows
    rather than erroring (Open Q3). v1 is single-bag; multi-bag events are deferred.

    The reservation is GATED on the name being otherwise unclaimed (CR-01): a bag with a
    REAL topic that sanitizes to ``events`` (e.g. a published ``/events`` topic) resolves
    and loads that topic normally — the sidecar is reserved ONLY when no topic owns the
    name, so a real ``/events`` topic's data is never silently shadowed by the sidecar.

    Pipeline (D-02 / 10-RESEARCH Pattern 4): ``parse`` → build per-topic
    ``TableSchema`` up front (O(1) metadata, no ``reader.read()``) → (if ``alias``)
    expand the alias pack on the parsed tree, gated to the single-base-topic case
    (Open Q1) → recompute ``referenced_tables``/``referenced_columns``/``has_star``
    on the (possibly rewritten) tree → load only referenced topics, materializing
    per-topic ``include`` (heavy-blob) ∧ ``restrict`` (projection) column sets →
    forward SQL to ``backend.execute``: the user's RAW string VERBATIM, unless alias
    expansion actually rewrote the tree, in which case the re-rendered
    ``tree.sql("duckdb")`` is sent so the expanded dotted columns reach DuckDB (WR-01
    — the no-expansion path, including ``--no-alias``, keeps the Phase 5 trusted-SQL-
    as-is boundary rather than round-tripping through sqlglot's renderer).

    Args:
        sql: the user's SQL — the trusted interface. It is forwarded to
            ``backend.execute`` UNCHANGED unless an alias is expanded; the
            orchestrator NEVER builds SQL by string concatenation. When ``alias``
            expands a short token it does so inside the ``sqlglot`` AST (quoted
            identifiers) and forwards the re-rendered ``tree.sql("duckdb")`` instead
            — the same trusted-SQL boundary as Phase 5 (threat T-05-04 / T-10-07),
            not an injection vector. With no expansion (``--no-alias`` or a no-match
            query) the raw string round-trips verbatim (WR-01).
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
    topic_to_table, table_to_topic, topic_to_msgtype, mixed_type_topics = _topic_table_maps(reader)

    # Step 3 — schema construction, ON DEMAND and memoized (10-RESEARCH Pattern 4).
    # `_schema_for(table)` builds a topic's TableSchema the first time it is needed and
    # caches it, so the alias gate (Step 4) and the load loop (Step 7) reuse one build
    # per referenced table (no double-build). It is built ONLY for tables the SQL
    # actually references — NOT for every topic in the bag (newA4). The previous eager
    # comprehension built a schema for every mapped topic up front, so one unbuildable
    # topic (a vendor msgtype absent from a caller-supplied default_typestore, or a
    # recursive type) raised here — before resolution — and crashed queries that never
    # touched it. Building is O(1) metadata (no `reader.read()`). The `typestore` binding
    # is captured in the closure.
    typestore = reader.typestore
    schemas_by_table: dict[str, TableSchema] = {}

    def _schema_for(table: str) -> TableSchema:
        """Build (once) and return the schema for a real topic table. Caller guarantees
        ``table`` is in ``table_to_topic`` (a resolved topic table, never ``events``)."""
        if table not in schemas_by_table:
            topic = table_to_topic[table]
            schemas_by_table[table] = build_table_schema(
                topic_to_msgtype[topic], typestore, topic=topic
            )
        return schemas_by_table[table]

    # Case-INSENSITIVE table resolution (newA5). DuckDB folds identifier case, and the
    # orchestrator forwards the user's SQL verbatim, so DuckDB happily matches `imu`
    # against a relation registered as `Imu`. The orchestrator's OWN pre-flight
    # resolution must fold case the same way — otherwise an unquoted lowercase reference
    # to a capitalized topic's table (a `/Imu` bag, `FROM imu`) raised UnknownTableError
    # for SQL the backend would have accepted. `TableNameResolver` already dedupes table
    # names case-insensitively (names.py), so lower-casing the keys can never collapse
    # two DISTINCT topics into one bucket. The exact map is tried first (fast path /
    # exact-case win); the folded map is the fallback.
    table_to_topic_ci = {table.lower(): topic for table, topic in table_to_topic.items()}

    def _resolve_table(table: str) -> str | None:
        """Resolve a SQL table name to its topic, case-insensitively (newA5); None if unmapped."""
        topic = table_to_topic.get(table)
        if topic is None:
            topic = table_to_topic_ci.get(table.lower())
        return topic

    # Step 4 — alias expansion (D-02), gated to the single-base-topic case (Open Q1).
    # Map the referenced base tables (CTE-subtracted) through to their topics; ignore
    # names that map to no topic (those raise UnknownTableError below). Only when
    # EXACTLY ONE distinct base topic resolves do we expand — keyed on that topic's
    # msgtype and existence-gated on its schema column names. With zero or >1 base
    # topics (JOIN/CTE/multi-topic) OR `alias=False`, expansion is skipped (safe
    # no-op, A3 / Pitfall 2) so an ambiguous short token is left for DuckDB to reject.
    #
    # `expanded` (WR-01) tracks whether a rewrite ACTUALLY changed the SQL — Step 8
    # forwards the user's RAW `sql` verbatim unless it did, restoring the Phase 5
    # trusted-SQL-as-is boundary (T-05-04) for the `--no-alias` / no-match paths.
    # `expand_aliases` always returns a NEW tree (`tree.transform` copies — D-01), so
    # an `is`-identity check would ALWAYS read "changed"; instead we compare the
    # rendered SQL before/after (the reviewer-sanctioned robust signal), which the
    # alias path needs to render anyway. The existence-gate makes a no-resolving token
    # a true no-op, so an unchanged render reliably means "nothing was expanded."
    expanded = False
    if alias:
        # Resolve referenced base tables to their TOPICS (case-insensitively, newA5) and
        # count DISTINCT topics — so `FROM imu`/`FROM Imu` against one `/Imu` topic still
        # gates as the single-base-topic case (and two case-variant references to the same
        # topic never miscount as two).
        base_topics = {
            topic
            for table in referenced_tables_in(tree)
            if (topic := _resolve_table(table)) is not None
        }
        if len(base_topics) == 1:
            only_topic = next(iter(base_topics))
            schema = _schema_for(topic_to_table[only_topic])
            before = tree.sql("duckdb")
            new_tree = expand_aliases(
                tree,
                schema.msgtype,
                {c.name for c in schema.columns},
            )
            if new_tree.sql("duckdb") != before:  # a real rewrite occurred
                tree, expanded = new_tree, True

    # Step 5 — derive tables / columns / star from the (possibly rewritten) tree
    # (D-02 — these MUST run after expansion so they see the expanded dotted names).
    tables = referenced_tables_in(tree)
    columns = referenced_columns(tree)
    star = has_star(tree)

    # Step 5b — the RESERVED `events` table (D-14 / 11-RESEARCH Pattern 5). `events`
    # is NOT a topic: it is the per-bag event sidecar (`<bag>.events.parquet`). SUBTRACT
    # it from the topic-resolution set so it is NEVER resolved as a topic (it maps to
    # none → would raise UnknownTableError; 11-RESEARCH Anti-Pattern "Forwarding events
    # into the topic-resolution loop"). The topic-resolution loop (Step 6) and the load
    # loop (Step 7) therefore iterate `data_tables`, not `tables`. When `events_referenced`
    # the sidecar relation is registered AFTER the topic tables (Step 7b), and a standard
    # `BETWEEN` interval join then runs natively (D-15, no special operator). The alias
    # gate above is unaffected: it already filters `t in table_to_topic`, so `events`
    # (no topic) never counts toward the single-base-topic total.
    #
    # CR-01: a REAL bag topic that sanitizes to `events` (e.g. a published `/events`
    # topic) TAKES PRECEDENCE over the sidecar — otherwise its data would be silently
    # shadowed by the (typically empty) sidecar relation, returning the sidecar's 0 rows
    # with no error. `table_to_topic` is already built (Step 2), so we only reserve
    # `events` for the sidecar when NO real topic owns that table name; when a topic
    # does, `events` stays in `data_tables` and resolves+loads as an ordinary topic.
    events_is_real_topic = _EVENTS_TABLE in table_to_topic
    events_referenced = _EVENTS_TABLE in tables and not events_is_real_topic
    data_tables = tables - ({_EVENTS_TABLE} if events_referenced else set())

    # Step 6 — resolve each referenced (non-`events`) table name to a topic; an unmapped
    # name raises a clear error listing the available tables, BEFORE any load
    # (T-05-06: no silent empty result). v1 just lists; Phase 7 owns did-you-mean.
    # Case-fold the mixed-type map too (newE22 + newA5), so a reference to a mixed-type
    # topic is recognized regardless of the SQL's identifier case.
    mixed_type_topics_ci = {name.lower(): topic for name, topic in mixed_type_topics.items()}
    referenced_topics: list[str] = []
    seen_topics: set[str] = set()
    for table in data_tables:
        topic = _resolve_table(table)  # case-insensitive (newA5)
        if topic is None:
            # Distinguish a genuinely-absent table from a topic that EXISTS but was skipped
            # for carrying >1 message type (newE22). Such a topic is real but unqueryable,
            # so a UnknownTableError listing only the OTHER tables would wrongly read as
            # "the data is missing" — raise a truthful MixedTypeTopicError instead.
            mixed_topic = mixed_type_topics.get(table) or mixed_type_topics_ci.get(table.lower())
            if mixed_topic is not None:
                raise MixedTypeTopicError(mixed_topic, table)
            # The constructor now owns the message + the difflib did-you-mean (CLI-02);
            # pass it the offending name and the available table names.
            raise UnknownTableError(table, sorted(table_to_topic))
        # Dedupe: two case-variant references (`imu`, `Imu`) resolve to one topic — load
        # and register it once (newA5).
        if topic not in seen_topics:
            seen_topics.add(topic)
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
    # F2 — LIMIT pushdown: for a bare single-table `SELECT ... LIMIT k [OFFSET m]` (no
    # filter/sort/aggregate/join/etc.) only the first k+m messages can reach the result, so we
    # decode just those. Gated to exactly one referenced topic and no `events` sidecar — the only
    # shape where slicing one topic's lazily-read message stream is valid. _safe_limit_head returns
    # None for every shape where early-stop could change the result (then nothing changes below).
    limit_head = _safe_limit_head(tree)
    push_limit = limit_head is not None and len(referenced_topics) == 1 and not events_referenced
    try:
        for topic in referenced_topics:
            # Build (or reuse the cached) schema for this referenced topic (Step 3) —
            # no double-build (Pattern 4), and never for an unreferenced topic (newA4).
            schema = _schema_for(topic_to_table[topic])
            columns_by_table[topic_to_table[topic]] = [c.name for c in schema.columns]
            # Per-topic column filters (10-RESEARCH Code Example 4), composed:
            #   include  — heavy-blob filter (the UNCHANGED QURY-07 rule): a topic's
            #              heavy blobs, or only the REFERENCED heavy blobs when not a star.
            #   restrict — the QURY-09 projection (D-06): the referenced columns that
            #              exist in THIS topic's schema, unioned with the four standard
            #              columns (D-07, the Pitfall 3 safety net). Computed and applied
            #              PER topic against that topic's own schema_names — over-include
            #              on a JOIN, NEVER under-include (D-09); table-qualified
            #              projection stays deferred.
            # A SELECT * (incl. qualified `o.*`) DISABLES projection: restrict=None
            # restores today's full non-heavy + blob materialization (D-08). This is
            # CRITICAL — under a star `columns` is empty, so a naive `columns | STANDARD`
            # would drop every body column (Pitfall 4); the star branch sets restrict=None.
            schema_names = {c.name for c in schema.columns}
            heavy = {c.name for c in schema.columns if c.is_heavy_blob}
            if star:
                include, restrict = heavy, None
            else:
                include = heavy & columns
                restrict = (columns & schema_names) | _STANDARD_COLUMNS
            msgs = reader.read(topics={topic})  # the Task 1 connection-filtered seam
            if push_limit:
                # F2: reader.read is a lazy generator, so islice truly stops deserializing the
                # tail once k+m messages are in hand (the win on a peek query over a huge topic).
                msgs = islice(msgs, limit_head)
            arrow = build_arrow_table(msgs, schema, include=include, restrict=restrict)
            # Register under the SANITIZED table name — the name the SQL references.
            backend.register_table(topic_to_table[topic], arrow)
        # Step 7b — register the reserved `events` relation (D-14), AFTER the topic
        # tables and BEFORE `backend.execute`, so the interval join below sees it.
        # v1 is single-bag (D-14; multi-bag events deferred — CONTEXT Deferred Ideas):
        # the sidecar sits next to `reader.paths[0]`. `list_events` returns the sidecar
        # table when `<bag>.events.parquet` exists and the fixed-v1 EMPTY table when
        # absent — so a missing sidecar yields a registered EMPTY-schema relation
        # (SELECT/joins return zero rows, never a DuckDB "table does not exist"; Open Q3
        # LOCKED). `list_events` is imported LAZILY here to keep this module's top level —
        # and `import rosbagger_core.backend` — free of pyarrow (offline invariant).
        if events_referenced:
            # Multi-bag events are deferred (v1 is single-bag): the sidecar sits next to
            # reader.paths[0]. With >1 bag open, joining ONLY that bag's events against the
            # MERGED multi-bag stream silently dropped the 2nd..Nth bags' events (newE23) —
            # raise rather than return a quietly-wrong result.
            if len(reader.paths) > 1:
                raise MultiBagEventsError(len(reader.paths))
            from rosbagger_core.events import list_events

            backend.register_table(_EVENTS_TABLE, list_events(reader.paths[0]))
        # Step 8 — forward the SQL to the backend. WR-01: forward the user's RAW `sql`
        # VERBATIM unless alias expansion actually rewrote the tree (`expanded`). Only
        # the alias path round-trips through sqlglot's renderer (`tree.sql("duckdb")`),
        # because there the rewritten dotted columns MUST reach DuckDB; the `--no-alias`
        # path and any no-op-expansion default path send the original string unchanged,
        # restoring the Phase 5 "trusted SQL as-is" boundary (T-05-04) — sqlglot does
        # rewrite some surface syntax (`x::INT` -> `CAST(x AS INT)`, `list_value(...)` ->
        # `[...]`), so a `--no-alias` escape hatch that re-renders is not a true verbatim
        # bypass. When expansion DID run the string is sqlglot-rendered from the AST
        # (never hand-concatenated), preserving the same trusted-SQL boundary
        # (T-05-04 / T-10-07). An unknown column surfaces as duckdb.BinderException;
        # catch it by TYPE (robust), then NARROW to the unknown-column case by message
        # before re-mapping (CR-01). duckdb.BinderException is NOT specific to unknown
        # columns — DuckDB raises the SAME type for GROUP BY / HAVING / other binder-stage
        # errors. Only when the `_BINDER_COL` regex matches ('Referenced column "X" not
        # found') is it truly an unknown column: raise the typed UnknownColumnError
        # carrying the referenced tables' columns (CLI-03). On a NON-match
        # (GROUP BY/HAVING/other), re-raise the ORIGINAL BinderException unchanged so the
        # real DuckDB error surfaces verbatim. The catch inspects the EXCEPTION, not the
        # SQL string, so which SQL string is forwarded does not affect it. duckdb is
        # imported LAZILY here — already pulled in via _default_backend(), but the explicit
        # import keeps the module top stdlib-light (offline; 07-RESEARCH §2 / Pitfall 6).
        final_sql = tree.sql("duckdb") if expanded else sql
        try:
            return backend.execute(final_sql)
        except duckdb_binder_exception() as e:
            m = _BINDER_COL.search(str(e))
            if m is None:
                raise  # not an unknown-column error (e.g. GROUP BY/HAVING) — surface as-is
            # INVARIANT (WR-03): `columns_by_table` advertises each table's FULL schema
            # columns, but the registered relations carry only the PROJECTED subset
            # (`restrict`). This listing stays complete under projection pushdown because
            # `restrict ⊇ (referenced columns ∩ schema)` — every non-star column the SQL
            # references is unioned into that topic's `restrict` (Step 7, with the four
            # standard columns; D-06/D-07). So any column the binder rejects is genuinely
            # absent from the schema, NEVER merely projected away — the full-schema
            # listing in UnknownColumnError can therefore never name a column the user
            # "should" have been able to select. (If a future change lets the binder fire
            # on a schema column excluded from `restrict`, revisit this coupling.)
            raise UnknownColumnError(m.group(1), columns_by_table) from e
    finally:
        # Own the lifecycle only for the default backend; a caller-supplied
        # backend is the caller's to close (it may be reused across queries). This
        # finally still runs on the BinderException -> UnknownColumnError path.
        if own_backend:
            backend.close()


def _safe_limit_head(tree) -> int | None:
    """Rows to decode for a bare ``SELECT ... FROM <one table> LIMIT k [OFFSET m]`` (F2), else None.

    LIMIT pushdown is sound ONLY when the result is the first rows in scan order: a single real
    table and a literal LIMIT (plus an optional literal OFFSET), with NOTHING that filters,
    reorders, aggregates, or dedups across the full set. Detection is conservative — the Select's
    truthy args must be a subset of ``{expressions, from_, limit, offset}`` (so WHERE / ORDER BY /
    GROUP BY / HAVING / DISTINCT / QUALIFY / JOIN / CTE all bail), AND there must be no
    derived-table subquery in FROM, no aggregate or window function, and exactly one table. A
    UNION / INTERSECT parses as a non-Select and bails. Returns ``k + m`` (decode this many leading
    messages) or ``None`` when early-stop could change the result. ``sqlglot`` is imported lazily
    (the offline invariant — this module's top stays free of the heavy stack).
    """
    from sqlglot import expressions as exp

    if not isinstance(tree, exp.Select):
        return None
    allowed = {"expressions", "from_", "limit", "offset"}
    if any(value and key not in allowed for key, value in tree.args.items()):
        return None
    # A derived-table subquery in FROM, or a cross-row function, hides inside an allowed arg.
    if tree.find(exp.Subquery) is not None:
        return None
    if tree.find(exp.AggFunc) is not None or tree.find(exp.Window) is not None:
        return None
    if len(list(tree.find_all(exp.Table))) != 1:
        return None
    limit = tree.args.get("limit")
    if limit is None:
        return None
    count = limit.expression
    if not isinstance(count, exp.Literal) or count.is_string:
        return None
    head = int(count.name)
    if head < 0:
        return None
    offset = tree.args.get("offset")
    if offset is not None:
        off = offset.expression
        if not isinstance(off, exp.Literal) or off.is_string:
            return None
        off_n = int(off.name)
        if off_n < 0:
            return None
        head += off_n
    return head


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
