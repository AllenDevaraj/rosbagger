"""SQL-safe identifier quoting via ``sqlglot`` (the SQL-injection defense).

Column and table names in rosbagger are derived from **untrusted bag content**:
table names come from topic strings and column names from message field names
(and, transitively, frame_ids in custom messages). In Phase 5 those names are
interpolated into SQL as identifiers, so they MUST be rendered as injection-safe
*quoted* identifiers — never hand-concatenated with an f-string.

This module exposes the one helper that does it correctly. ``sqlglot``'s
``exp.to_identifier(name, quoted=True)`` quotes the name AND escapes an embedded
quote by doubling it (``weird"name`` -> ``"weird""name"``), which neutralizes a
hostile name like ``x"; DROP TABLE y;--`` into a single quoted identifier
(``"x""; DROP TABLE y;--"``) — VERIFIED (research Pattern 6, threat T-03-06).

Phase 3 only emits the *mechanism*; Phase 5 calls it at SQL-build time. It is
isolated here so the rule "all identifiers go through ``sqlglot``, never an
f-string" has a single, testable home.

Offline note: ``sqlglot`` is a pure-Python locked dependency and is NOT a ROS
module, so importing it is offline-safe. ``rosbagger_core/__init__`` does not
import this subpackage at top level, so ``import rosbagger_core`` stays light.
No ``import duckdb`` (that is Phase 5).
"""

from __future__ import annotations

from sqlglot import exp


def quote_ident(name: str, dialect: str = "duckdb") -> str:
    """Render ``name`` as a SQL-injection-safe quoted identifier.

    Uses ``sqlglot.exp.to_identifier(name, quoted=True)`` so the name is quoted
    and any embedded quote is escaped by doubling — the correct identifier-safety
    boundary (research Pattern 6; threat T-03-06). Do NOT hand-quote with an
    f-string (``f'"{name}"'``): that misses embedded-quote escaping and is the
    documented anti-pattern.

    Examples (VERIFIED):
        ``quote_ident("twist.twist.linear.x")`` -> ``'"twist.twist.linear.x"'``
        ``quote_ident('weird"name')``           -> ``'"weird""name"'``
        ``quote_ident('x"; DROP TABLE y;--')``   -> ``'"x""; DROP TABLE y;--"'``

    Args:
        name: the raw identifier (a dotted column name, a sanitized table name, …).
        dialect: the SQL dialect to render for; defaults to ``"duckdb"`` (the
            default query backend). Phase 5 may pass another dialect behind the
            swappable backend seam.

    Returns:
        The quoted, escaped identifier string, safe to interpolate into SQL.
    """
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)
