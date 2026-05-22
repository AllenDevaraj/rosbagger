"""Backend subpackage — the swappable ``QueryBackend`` seam (DuckDB default).

This package houses the Phase 5 query engine:

* ``backend/base.py`` — the ``QueryBackend`` ABC (stdlib-only seam).
* ``backend/duckdb_backend.py`` — ``DuckDBBackend``, the default impl (the ONLY
  module that imports ``duckdb``).
* ``backend/resolve.py`` — the ``sqlglot`` SQL resolver (referenced tables /
  columns / star).
* ``backend/query.py`` — the ``query(sql, reader)`` orchestrator.

LIGHT BY DESIGN (offline invariant — ``tests/test_offline_guard.py``): this
``__init__`` adds NO eager import, so ``import rosbagger_core.backend`` pulls in
NEITHER ``duckdb``/``sqlglot``/``pyarrow`` NOR the orchestrator. The heavy stack
loads only when a backend/orchestrator function is actually called. Import the
pieces explicitly at the call site::

    from rosbagger_core.backend.query import query
    from rosbagger_core.backend.duckdb_backend import DuckDBBackend
    from rosbagger_core.backend.base import QueryBackend

That mirrors the ``reader`` / ``schema`` subpackage discipline and keeps both
``import rosbagger_core`` and ``import rosbagger_core.backend`` free of the heavy
query stack.
"""
