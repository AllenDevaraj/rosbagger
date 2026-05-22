"""The swappable query-backend seam: the ``QueryBackend`` ABC.

This is the typed contract every concrete query backend satisfies — the
swappable seam mandated by design decision 6 (DuckDB-by-default, but pluggable).
Impl #1 is :class:`~rosbagger_core.backend.duckdb_backend.DuckDBBackend` (an
in-memory DuckDB engine); a future ``PolarsBackend`` / ``SQLiteBackend`` slots in
behind this same interface without restructuring the orchestrator.

It deliberately imports ONLY the standard library (``abc``) — no ``duckdb``, no
``sqlglot``, and no ``pyarrow``. Keeping the abstract seam light is load-bearing:
it preserves the offline invariant (``import rosbagger_core`` must not pull the
heavy query stack — Phase 1 decision, enforced by ``tests/test_offline_guard.py``)
and mirrors the ``reader/base.py`` ABC. Concrete backends do the heavy importing
inside their own modules; ``execute`` is therefore typed as returning ``object``
so this module never names ``pyarrow`` (the real return is a ``pyarrow.Table``).
"""

from __future__ import annotations

import abc


class QueryBackend(abc.ABC):
    """Swappable SQL-execution seam over registered Arrow tables.

    A backend registers each topic's ``pyarrow.Table`` under its sanitized table
    name, executes a SQL string against the registered relations, and returns the
    result as a ``pyarrow.Table``. Concrete backends implement
    ``register_table``/``execute``/``close`` and inherit the context-manager
    lifecycle (``__enter__``/``__exit__``) for free — use
    ``with DuckDBBackend() as backend:`` so the underlying connection is always
    released, even on error.

    The seam is backend-neutral: ``table``/``execute`` are typed as ``object`` so
    this module names no ``pyarrow``. Impl #1 is ``DuckDBBackend``; the contract
    is what a future ``PolarsBackend``/``SQLiteBackend`` must satisfy.
    """

    @abc.abstractmethod
    def register_table(self, name: str, table: object) -> None:
        """Register an Arrow ``table`` as a queryable relation named ``name``.

        ``name`` is the sanitized table name (Phase 3 ``TableNameResolver``);
        ``table`` is a ``pyarrow.Table`` (typed ``object`` here so the seam names
        no ``pyarrow``). Registering is zero-copy for backends that support it
        (DuckDB does).
        """
        ...

    @abc.abstractmethod
    def execute(self, sql: str) -> object:
        """Execute ``sql`` against the registered relations, returning Arrow.

        Returns a ``pyarrow.Table`` (typed ``object`` so this module names no
        ``pyarrow``). An empty result still carries the full column schema.
        """
        ...

    @abc.abstractmethod
    def close(self) -> None:
        """Release the underlying engine/connection. Implementations MUST be idempotent."""
        ...

    # Shared lifecycle — concrete backends inherit this for free.
    def __enter__(self) -> QueryBackend:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False
