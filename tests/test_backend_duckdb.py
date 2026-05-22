"""The QueryBackend seam + its DuckDBBackend default impl (QURY-06).

These prove the swappable backend boundary (design decision 6) end-to-end against
hand-built ``pyarrow`` tables:

* ``backend/base.py`` — ``QueryBackend(abc.ABC)`` with abstract ``register_table``
  / ``execute`` / ``close`` and the inherited ``__enter__``/``__exit__``
  context-manager lifecycle (mirrors ``reader/base.py``). Stdlib-only — names no
  ``duckdb``/``pyarrow``.
* ``backend/duckdb_backend.py`` — ``DuckDBBackend(QueryBackend)`` over one
  in-memory ``duckdb.connect()``: ``register_table`` via ``con.register``,
  ``execute`` via ``con.execute(sql).to_arrow_table()`` (NOT the deprecated
  ``fetch_arrow_table``), idempotent ``close``. ``duckdb`` is imported ONLY in
  this module (the offline-guard boundary).

Result columns are asserted via ``t_ns`` (the BIGINT column), NOT a
``timestamp[ns]`` column — ``.to_pylist()`` on a real ns timestamp can raise in
pure Python (05-RESEARCH Pitfall 6); the backend returns Arrow untouched so this
is purely a test-side choice.

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized (with coverage, per the project gate)::

    PYTHONPATH="" uv run pytest tests/test_backend_duckdb.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import abc
import sys
import warnings
from pathlib import Path

import pyarrow as pa
import pytest

# Scoped repo-root sys.path insert (mirrors tests/test_schema_arrow.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rosbagger_core.backend.base import QueryBackend  # noqa: E402  (3rd-party stack)
from rosbagger_core.backend.duckdb_backend import DuckDBBackend  # noqa: E402


def _cmd_vel_table() -> pa.Table:
    """A small two-row Arrow table shaped like a flattened /cmd_vel topic.

    ``t_ns`` is BIGINT (asserted in pure Python without the ns-timestamp pitfall);
    ``"linear.x"`` is the quoted dotted column the WHERE clause filters on.
    """
    return pa.table(
        {
            "t_ns": pa.array([1_100_000_000, 1_200_000_000], type=pa.int64()),
            "linear.x": pa.array([1.0, 2.0], type=pa.float64()),
            "topic": pa.array(["/cmd_vel", "/cmd_vel"], type=pa.string()),
        }
    )


def _imu_table() -> pa.Table:
    """A second topic-shaped table, to prove two relations on one connection."""
    return pa.table(
        {
            "t_ns": pa.array([1_050_000_000, 1_150_000_000], type=pa.int64()),
            "topic": pa.array(["/imu", "/imu"], type=pa.string()),
        }
    )


# ---------------------------------------------------------------------------
# Behavior 1 — DuckDBBackend is a QueryBackend; QueryBackend is an abstract ABC.
# ---------------------------------------------------------------------------


def test_duckdb_backend_is_a_query_backend_subclass() -> None:
    """issubclass(DuckDBBackend, QueryBackend) and QueryBackend is an abc.ABC."""
    assert issubclass(DuckDBBackend, QueryBackend)
    assert isinstance(QueryBackend, abc.ABCMeta)


def test_query_backend_cannot_be_instantiated_directly() -> None:
    """QueryBackend is abstract — instantiating it raises TypeError."""
    with pytest.raises(TypeError):
        QueryBackend()  # type: ignore[abstract]


def test_query_backend_declares_the_three_abstract_methods() -> None:
    """register_table / execute / close are all abstract on the seam."""
    assert QueryBackend.__abstractmethods__ == frozenset({"register_table", "execute", "close"})


# ---------------------------------------------------------------------------
# Behavior 2 — register_table + execute returns the correctly filtered rows.
# ---------------------------------------------------------------------------


def test_register_and_execute_returns_filtered_arrow_rows() -> None:
    """A registered Arrow table queried with a quoted dotted column filters rows.

    SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5 returns only the
    matching rows, as a pyarrow.Table with the expected columns and values.
    """
    with DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        result = backend.execute('SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5')
    assert isinstance(result, pa.Table)
    assert result.schema.names == ["t_ns", "linear.x"]
    # Both fixture rows have linear.x > 0.5 (1.0, 2.0) -> both returned, in order.
    assert result.column("t_ns").to_pylist() == [1_100_000_000, 1_200_000_000]
    assert result.column("linear.x").to_pylist() == [1.0, 2.0]


def test_where_clause_actually_filters() -> None:
    """A stricter predicate proves the WHERE is applied (not all rows returned)."""
    with DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        result = backend.execute('SELECT t_ns FROM cmd_vel WHERE "linear.x" > 1.5')
    # Only the second row (linear.x == 2.0) matches.
    assert result.column("t_ns").to_pylist() == [1_200_000_000]


# ---------------------------------------------------------------------------
# Behavior 3 — execute uses to_arrow_table() and emits NO DeprecationWarning.
# ---------------------------------------------------------------------------


def test_execute_emits_no_deprecation_warning() -> None:
    """execute() must use to_arrow_table (not the deprecated fetch_arrow_table).

    Asserted by recording warnings around execute and confirming none are a
    DeprecationWarning (RESEARCH State of the Art / Pitfall on the deprecated API).
    """
    with DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            backend.execute("SELECT t_ns FROM cmd_vel")
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations == [], f"execute emitted DeprecationWarning(s): {deprecations}"


# ---------------------------------------------------------------------------
# Behavior 4 — two tables on one backend share a single in-memory connection.
# ---------------------------------------------------------------------------


def test_two_tables_share_one_connection() -> None:
    """Two registered tables are cross-referenceable in one query (one connection)."""
    with DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        backend.register_table("imu", _imu_table())
        result = backend.execute(
            "SELECT topic, t_ns FROM cmd_vel UNION ALL SELECT topic, t_ns FROM imu"
        )
    # All four rows (2 per table) come back from the single shared connection.
    assert sorted(result.column("t_ns").to_pylist()) == [
        1_050_000_000,
        1_100_000_000,
        1_150_000_000,
        1_200_000_000,
    ]
    assert set(result.column("topic").to_pylist()) == {"/cmd_vel", "/imu"}


# ---------------------------------------------------------------------------
# Behavior 5 — context-manager lifecycle, idempotent close, empty-result schema.
# ---------------------------------------------------------------------------


def test_context_manager_enters_and_exits_cleanly(recwarn) -> None:
    """`with DuckDBBackend() as b:` enters/exits with no ResourceWarning."""
    with DuckDBBackend() as backend:
        assert isinstance(backend, DuckDBBackend)
        backend.register_table("cmd_vel", _cmd_vel_table())
        backend.execute("SELECT t_ns FROM cmd_vel")
    # After the with-block the connection is released — no ResourceWarning.
    assert [w for w in recwarn.list if issubclass(w.category, ResourceWarning)] == []


def test_close_is_idempotent() -> None:
    """close() twice is safe (mirrors RosbagsReader.close — guards a closed handle)."""
    backend = DuckDBBackend()
    backend.register_table("cmd_vel", _cmd_vel_table())
    backend.close()
    backend.close()  # second close must not raise


def test_empty_result_keeps_full_schema() -> None:
    """A 0-row result still carries the full column schema (RESEARCH Pitfall 4)."""
    with DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        # No row has linear.x > 100 -> empty result, full schema preserved.
        result = backend.execute('SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 100')
    assert result.num_rows == 0
    assert result.schema.names == ["t_ns", "linear.x"]


def test_exit_returns_false_does_not_swallow_exceptions() -> None:
    """__exit__ returns False, so an exception inside the with-block propagates."""
    with pytest.raises(ValueError, match="boom"), DuckDBBackend() as backend:
        backend.register_table("cmd_vel", _cmd_vel_table())
        raise ValueError("boom")
