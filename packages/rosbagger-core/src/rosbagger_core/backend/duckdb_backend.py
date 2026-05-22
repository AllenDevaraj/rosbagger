"""The default :class:`QueryBackend`: DuckDB over one in-memory connection.

``DuckDBBackend`` is impl #1 of the swappable query seam (design decision 6). It
owns a single in-memory ``duckdb.connect()`` for its lifetime, registers each
topic's ``pyarrow.Table`` zero-copy via ``con.register``, executes SQL against
those relations, and returns the result as a ``pyarrow.Table`` via the current
``to_arrow_table()`` API (NEVER the deprecated ``fetch_arrow_table()``, which
emits a ``DeprecationWarning`` in duckdb 1.5.3 — 05-RESEARCH State of the Art).

``import duckdb`` lives at this module's top level **and only here**: this is the
sole module in ``rosbagger_core`` allowed to import ``duckdb`` (the offline-guard
boundary — 05-RESEARCH Architectural Responsibility Map / Anti-Patterns).
``rosbagger_core/__init__`` and ``rosbagger_core/backend/__init__`` stay light, so
``import rosbagger_core`` never pulls ``duckdb``; the entry point for this impl is
``import rosbagger_core.backend.duckdb_backend``.

One connection per backend instance (05-RESEARCH Pitfall 5): the lifecycle is
owned by the context manager — ``with DuckDBBackend() as backend:`` guarantees the
connection is closed even on error. ``close()`` is idempotent (mirrors
``RosbagsReader.close``), so a double-close is safe.
"""

from __future__ import annotations

import duckdb

from .base import QueryBackend


class DuckDBBackend(QueryBackend):
    """A :class:`QueryBackend` backed by one in-memory DuckDB connection.

    Registers Arrow tables zero-copy and executes SQL against them, returning a
    ``pyarrow.Table``. One in-memory connection per instance; closed via the
    inherited context-manager lifecycle.
    """

    def __init__(self) -> None:
        """Open one in-memory DuckDB connection owned by this backend instance."""
        self._con: duckdb.DuckDBPyConnection | None = duckdb.connect()

    def register_table(self, name: str, table: object) -> None:
        """Register an Arrow ``table`` as a DuckDB relation named ``name`` (zero-copy).

        ``table`` is a ``pyarrow.Table`` (typed ``object`` at the seam). Do NOT
        unregister mid-query — a stale relation raises ``CatalogException``
        (05-RESEARCH Pitfall 5).
        """
        self._require_open().register(name, table)

    def execute(self, sql: str) -> object:
        """Execute ``sql`` and return the result as a ``pyarrow.Table``.

        Uses ``con.execute(sql).to_arrow_table()`` — the current API; NOT the
        deprecated ``fetch_arrow_table()``. An empty result still carries the
        full column schema (05-RESEARCH Pitfall 4). The return is typed ``object``
        so this signature does not leak ``pyarrow`` into the seam's vocabulary.
        """
        return self._require_open().execute(sql).to_arrow_table()

    def close(self) -> None:
        """Close the in-memory connection. Idempotent (safe if already closed)."""
        if self._con is not None:
            self._con.close()
            self._con = None

    def _require_open(self) -> duckdb.DuckDBPyConnection:
        """Return the live connection, or raise if the backend has been closed."""
        if self._con is None:
            raise RuntimeError("DuckDBBackend is closed; open a new backend to run queries.")
        return self._con
