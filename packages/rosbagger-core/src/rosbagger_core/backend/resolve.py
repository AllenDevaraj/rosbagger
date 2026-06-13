"""SQL → referenced-tables / -columns / star resolver via ``sqlglot``.

This is the "what does this SQL touch?" half of the query orchestrator
(``backend/query.py``): given the user's SQL, learn which *tables* it
references (so only those topics are loaded — QURY-05), which *columns* it
references (so a heavy blob is materialized only when named — the QURY-07
``include=`` seam), and whether it is a ``SELECT *`` (which means "give me
everything, heavy blobs included" — 05-RESEARCH Pitfall 3 / A1).

Why ``sqlglot`` and not a regex (05-RESEARCH "Don't Hand-Roll"): a regex breaks
on the first CTE, subquery, JOIN, alias, or quoted dotted column. ``sqlglot``
parses to an AST and walks it correctly across all of those — and it is already a
locked dependency, used by ``schema/identifiers.py`` for the quoting boundary.

Offline note: ``import sqlglot`` at module level here is SAFE — ``sqlglot`` is a
pure-Python locked dependency, NOT a ROS module (mirrors ``schema/identifiers.py``).
``rosbagger_core/__init__`` and ``rosbagger_core/backend/__init__`` do NOT import
this module at top level, so ``import rosbagger_core`` / ``import
rosbagger_core.backend`` stay light (offline-guard invariant). The duckdb
dependency is never pulled in here; it lives only in ``duckdb_backend.py``.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


def parse(sql: str, dialect: str = "duckdb") -> exp.Expression:
    """Parse ``sql`` once into a ``sqlglot`` AST (the duckdb dialect by default).

    The orchestrator parses ONCE here and reuses the returned tree for
    :func:`referenced_tables_in`, :func:`referenced_columns`, and
    :func:`has_star` — so a query is never re-parsed three times.
    """
    return sqlglot.parse_one(sql, dialect=dialect)


def referenced_tables_in(tree: exp.Expression) -> set[str]:
    """Base-table names referenced by an already-parsed ``tree``, minus CTE aliases.

    Collects every ``exp.Table`` ``.name`` (the bare base-table name; ``.db`` is
    the schema qualifier — ``main.imu`` → ``"imu"``) and SUBTRACTS the
    ``exp.CTE`` ``alias_or_name``s, so a CTE name is never mistaken for a topic
    table (05-RESEARCH Pattern 2). Without the subtraction,
    ``WITH fast AS (...) SELECT * FROM fast`` would wrongly yield
    ``{"fast", "cmd_vel"}``; with it, ``{"cmd_vel"}``. Aliases resolve to the
    base name (``FROM imu AS a`` → ``"imu"``, not ``"a"``).
    """
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name not in cte_names}


def referenced_tables(sql: str, dialect: str = "duckdb") -> set[str]:
    """Parse ``sql`` and return its CTE-subtracted base-table names.

    Convenience wrapper over :func:`parse` + :func:`referenced_tables_in` for
    callers (and tests) that have only the SQL string. The orchestrator prefers
    parsing once via :func:`parse` and passing the tree to
    :func:`referenced_tables_in` to avoid double-parsing.
    """
    return referenced_tables_in(parse(sql, dialect))


def referenced_columns(tree: exp.Expression) -> set[str]:
    """Column names referenced by an already-parsed ``tree``.

    Collects every ``exp.Column`` ``.name``. A quoted dotted column
    (``"linear.x"``) parses to ``.name == "linear.x"`` — exactly the dotted ROS
    column name the schema uses, which is why the heavy-blob ``include`` key
    being the dotted column name (Phase 3 decision) lines up perfectly
    (05-RESEARCH Pattern 3). Note: a ``SELECT *`` produces NO ``exp.Column``
    nodes (see :func:`has_star`).
    """
    return {c.name for c in tree.find_all(exp.Column)}


def has_star(tree: exp.Expression) -> bool:
    """True iff the parsed ``tree`` PROJECTS a ``SELECT *`` (a projection ``exp.Star``).

    A *projection* star sits DIRECTLY in a ``SELECT``'s projection list: a bare ``*``
    (an ``exp.Star`` whose parent is the ``Select``) or a qualified ``t.*`` (an
    ``exp.Column`` wrapping the ``Star``). The orchestrator treats such a star as
    "include this topic's heavy blobs too" — otherwise ``SELECT * FROM image`` would
    silently drop ``image.data`` (Pitfall 3 / A1).

    A ``Star`` NESTED INSIDE A FUNCTION CALL is NOT a projection star: ``COUNT(*)``,
    ``array_agg(*)``, etc. select no columns, so treating them as "include heavy blobs"
    needlessly materialized every blob — ``SELECT COUNT(*) FROM image`` decoded every
    ``image.data`` payload just to count rows (newA1). ``find_all(exp.Star)`` matched
    those too (it walks the WHOLE tree); we now keep only a ``Star`` (or its
    qualified-``Star`` ``Column``) that is a direct expression of a ``Select``
    projection, never one wrapped in a function. (A star inside a sub-SELECT's
    projection still counts — that sub-SELECT genuinely selects all of its source
    topic's columns, blobs included.)
    """
    for star in tree.find_all(exp.Star):
        # A qualified star ``t.*`` parses as ``Column(this=Star)`` — treat the Column as
        # the projection node; a bare ``*`` is the Star itself (VERIFIED via sqlglot).
        parent = star.parent
        node = parent if isinstance(parent, exp.Column) and parent.this is star else star
        owner = node.parent
        # Identity (`is`) membership, NOT `==`: sqlglot's `Expression.__eq__` compares by
        # rendered SQL, so two distinct `*` nodes would compare equal under `in`.
        if isinstance(owner, exp.Select) and any(e is node for e in owner.expressions):
            return True
    return False
