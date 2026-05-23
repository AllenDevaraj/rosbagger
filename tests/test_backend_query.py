"""End-to-end tests for the ``query(sql, reader)`` orchestrator (05-02 Task 2).

These prove the full QURY-05/06 path against the REAL fixture corpus and the REAL
``rosbags`` typestore — reader → resolve → invert → lazy-load → register → DuckDB
→ ``pyarrow.Table``:

* The VERIFIED end-to-end result (05-RESEARCH Code Examples) across all three
  formats: ``SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5`` →
  ``t_ns=[1_100_000_000, 1_200_000_000]``, ``linear.x=[1.0, 2.0]`` (criterion #1).
* Only the referenced topic is loaded — ``/imu``/``/image`` are never deserialized
  during a ``/cmd_vel`` query (criterion #2; reusing Task 1's monkeypatch proof).
* ``SELECT *`` materializes the heavy ``data`` blob; an explicit projection naming
  no blob omits it (QURY-07 seam; 05-RESEARCH Pitfall 3).
* An unknown table name raises a clear error LISTING the available tables.
* A WHERE matching nothing returns a 0-row Table with the full schema (Pitfall 4).
* The backend is swappable via ``backend=`` (a caller-supplied ``DuckDBBackend``).

Result columns are asserted via ``t_ns`` (BIGINT) / ``"linear.x"`` (DOUBLE), NOT a
``timestamp[ns]`` column — ``.to_pylist()`` on a real ns timestamp can raise in
pure Python (05-RESEARCH Pitfall 6).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized::

    PYTHONPATH="" uv run pytest tests/test_backend_query.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pytest

# `tools` is a dev-only package at the repo root (NOT an installed distribution),
# so it is not on sys.path under pytest's default import mode. Put the repo root
# on sys.path here — scoped to this test file (mirrors tests/test_schema_arrow.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures  # noqa: E402  (after sys.path setup)

from rosbagger_core.backend.base import QueryBackend  # noqa: E402
from rosbagger_core.backend.duckdb_backend import DuckDBBackend  # noqa: E402  (3rd-party)
from rosbagger_core.backend.query import (  # noqa: E402
    UnknownColumnError,
    UnknownTableError,
    query,
)
from rosbagger_core.reader import RosbagsReader  # noqa: E402

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("query_bags")
    return make_all_fixtures(dest)


# ---------------------------------------------------------------------------
# Criterion #1 — a SELECT returns correct rows end-to-end, all three formats.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_cmd_vel_filtered_rows_across_formats(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """The VERIFIED end-to-end /cmd_vel filter result holds for every format.

    SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5
      -> t_ns = [1_100_000_000, 1_200_000_000], linear.x = [1.0, 2.0]
    """
    sql = 'SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5'
    with RosbagsReader(fixture_bags[fmt]) as reader:
        result = query(sql, reader)
    assert isinstance(result, pa.Table)
    assert result.schema.names == ["t_ns", "linear.x"]
    assert result.column("t_ns").to_pylist() == [1_100_000_000, 1_200_000_000]
    assert result.column("linear.x").to_pylist() == [1.0, 2.0]


def test_query_returns_full_unfiltered_series(fixture_bags: dict[str, Path]) -> None:
    """A predicate-free select returns the full /cmd_vel linear.x series (0,1,2)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query('SELECT t_ns, "linear.x" FROM cmd_vel', reader)
    assert result.column("linear.x").to_pylist() == [0.0, 1.0, 2.0]
    assert result.column("t_ns").to_pylist() == [
        1_000_000_000,
        1_100_000_000,
        1_200_000_000,
    ]


# ---------------------------------------------------------------------------
# Criterion #2 — only the referenced topic is loaded (end-to-end proof).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_loads_only_referenced_topic(fixture_bags: dict[str, Path], fmt: str) -> None:
    """During a /cmd_vel query, /imu and /image are NEVER deserialized (QURY-05).

    Reuses Task 1's technique: record every msgtype the underlying ``deserialize``
    is asked to decode, then assert it is exactly the three Twist messages.
    """
    with RosbagsReader(fixture_bags[fmt]) as reader:
        decoded: list[str] = []
        real_deserialize = reader._reader.deserialize

        def recording_deserialize(rawdata, msgtype):
            decoded.append(msgtype)
            return real_deserialize(rawdata, msgtype)

        reader._reader.deserialize = recording_deserialize
        query('SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5', reader)

    assert decoded == ["geometry_msgs/msg/Twist"] * 3
    assert "sensor_msgs/msg/Imu" not in decoded
    assert "sensor_msgs/msg/Image" not in decoded


# ---------------------------------------------------------------------------
# QURY-07 seam — SELECT * materializes the heavy blob; a projection omits it.
# ---------------------------------------------------------------------------


def test_query_select_star_includes_heavy_blob(fixture_bags: dict[str, Path]) -> None:
    """SELECT * FROM image materializes the heavy ``data`` blob (Pitfall 3 / A1)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT * FROM image", reader)
    assert "data" in result.schema.names
    assert result.schema.field("data").type == pa.list_(pa.uint8())
    # The 2x2x3 ramp fixture content survives the round-trip.
    assert result.column("data").to_pylist()[0] == list(range(12))


def test_query_projection_omits_heavy_blob(fixture_bags: dict[str, Path]) -> None:
    """SELECT t_ns FROM image does NOT materialize ``data`` (the lazy default)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT t_ns FROM image", reader)
    assert "data" not in result.schema.names
    assert result.schema.names == ["t_ns"]


def test_query_naming_blob_column_includes_it(fixture_bags: dict[str, Path]) -> None:
    """Explicitly selecting ``data`` materializes the blob (referenced-column include)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT t_ns, data FROM image", reader)
    assert "data" in result.schema.names
    assert result.column("data").to_pylist()[0] == list(range(12))


# ---------------------------------------------------------------------------
# Unknown table — a clear error listing the available tables (T-05-06).
# ---------------------------------------------------------------------------


def test_query_unknown_table_lists_available(fixture_bags: dict[str, Path]) -> None:
    """SELECT * FROM does_not_exist raises an error LISTING cmd_vel/image/imu."""
    with (
        RosbagsReader(fixture_bags["ros2_sqlite"]) as reader,
        pytest.raises(UnknownTableError) as excinfo,
    ):
        query("SELECT * FROM does_not_exist", reader)
    message = str(excinfo.value)
    assert "does_not_exist" in message
    for available in ("cmd_vel", "image", "imu"):
        assert available in message


def test_unknown_table_error_is_a_value_error() -> None:
    """UnknownTableError subclasses ValueError (existing handlers still catch it)."""
    assert issubclass(UnknownTableError, ValueError)


def test_query_unknown_table_raises_before_loading(fixture_bags: dict[str, Path]) -> None:
    """The unknown-table error fires BEFORE any message is deserialized (Pattern 4)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        real_deserialize = reader._reader.deserialize
        decoded: list[str] = []

        def recording_deserialize(rawdata, msgtype):
            decoded.append(msgtype)
            return real_deserialize(rawdata, msgtype)

        reader._reader.deserialize = recording_deserialize
        with pytest.raises(UnknownTableError):
            query("SELECT * FROM does_not_exist", reader)
    assert decoded == []  # nothing was loaded before the error


# ---------------------------------------------------------------------------
# Empty result + swappable backend.
# ---------------------------------------------------------------------------


def test_query_empty_result_keeps_full_schema(fixture_bags: dict[str, Path]) -> None:
    """A WHERE matching nothing returns a 0-row Table with the full schema (Pitfall 4)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query('SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 100', reader)
    assert result.num_rows == 0
    assert result.schema.names == ["t_ns", "linear.x"]


def test_query_accepts_a_supplied_backend(fixture_bags: dict[str, Path]) -> None:
    """A caller-supplied DuckDBBackend is used (the backend is swappable per call)."""
    sql = 'SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5'
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, DuckDBBackend() as backend:
        result = query(sql, reader, backend=backend)
        assert result.column("t_ns").to_pylist() == [1_100_000_000, 1_200_000_000]
        # A caller-supplied backend is NOT closed by query() — it stays usable,
        # so a second query on the same backend instance still works.
        again = query("SELECT t_ns FROM cmd_vel", reader, backend=backend)
        assert again.column("t_ns").to_pylist() == [
            1_000_000_000,
            1_100_000_000,
            1_200_000_000,
        ]


def test_query_join_across_two_topics(fixture_bags: dict[str, Path]) -> None:
    """A JOIN loads BOTH referenced topics and executes (multi-table resolution)."""
    sql = (
        "SELECT c.t_ns FROM cmd_vel AS c JOIN imu AS i ON c.t_ns = i.t_ns "
        'WHERE c."linear.x" > 0.5 ORDER BY c.t_ns'
    )
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query(sql, reader)
    assert result.column("t_ns").to_pylist() == [1_100_000_000, 1_200_000_000]


# ---------------------------------------------------------------------------
# Offline invariant — importing the backend package stays light.
# ---------------------------------------------------------------------------


def test_import_backend_package_does_not_pull_heavy_stack() -> None:
    """`import rosbagger_core.backend` pulls NO duckdb/sqlglot/pyarrow (fresh subproc).

    Spawned in a FRESH interpreter so an already-imported heavy module in THIS
    test process cannot mask a leak (same technique as test_offline_guard.py).
    Even importing the orchestrator's PACKAGE must not eagerly load the stack —
    query.py imports it lazily inside the function.
    """
    import subprocess

    code = (
        "import sys; import rosbagger_core.backend; "
        "heavy={'duckdb','sqlglot','pyarrow'}; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in heavy]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": ""},
    )
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"import rosbagger_core.backend leaked the heavy stack: {leaked}"


# ---------------------------------------------------------------------------
# QURY-08 — alias expansion wired into query() (Plan 10-03 Task 1 / SC1).
#
# The /cmd_vel fixture is geometry_msgs/msg/Twist, whose pack maps `vx`->`linear.x`
# (the shallowest velocity path). These prove the alias half end-to-end: the short
# token is expanded BEFORE resolution (D-02), gated to the single-base-topic case
# (Open Q1), the `alias=False` escape hatch threads through, and the REWRITTEN SQL
# (output aliases preserved) is what reaches the backend.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_alias_vx_resolves_end_to_end(fixture_bags: dict[str, Path], fmt: str) -> None:
    """SC1: `SELECT vx FROM cmd_vel` returns the linear.x series across all 3 formats.

    Proves `vx` expanded to the Twist `linear.x` dotted column and the query ran:
    the fixture's linear.x series is (0.0, 1.0, 2.0).
    """
    with RosbagsReader(fixture_bags[fmt]) as reader:
        result = query("SELECT vx FROM cmd_vel", reader)
    # The expanded column surfaces under its dotted name `linear.x`.
    assert result.column("linear.x").to_pylist() == [0.0, 1.0, 2.0]


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_alias_disabled_raises_unknown_column(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """`alias=False` disables expansion, so `vx` (not a real column) is rejected.

    With expansion off the rewritten tree is unchanged, so DuckDB's binder sees the
    bare `vx` token and raises — surfaced as the typed UnknownColumnError teaching
    path. Proves the `--no-alias`/`alias=False` flag threads through query().
    """
    with (
        RosbagsReader(fixture_bags[fmt]) as reader,
        pytest.raises(UnknownColumnError),
    ):
        query("SELECT vx FROM cmd_vel", reader, alias=False)


def test_query_alias_join_no_op_leaves_short_token_untouched(
    fixture_bags: dict[str, Path],
) -> None:
    """A JOIN of two distinct base topics is OUTSIDE the single-base-topic gate.

    `vx` resolves on the Twist /cmd_vel topic, but with a second base topic (/imu)
    referenced, the gate skips expansion (Open Q1) — so the unqualified `vx` is left
    untouched and DuckDB's binder rejects it (UnknownColumnError). This pins the
    no-expansion-on-multi-topic safety property that protects the existing JOIN test.
    """
    sql = "SELECT vx FROM cmd_vel AS c JOIN imu AS i ON c.t_ns = i.t_ns"
    with (
        RosbagsReader(fixture_bags["ros2_sqlite"]) as reader,
        pytest.raises(UnknownColumnError),
    ):
        query(sql, reader)


def test_query_alias_rewritten_sql_preserves_output_alias(
    fixture_bags: dict[str, Path],
) -> None:
    """The REWRITTEN SQL is forwarded: `vx AS speed` keeps `speed` as the output name.

    `vx` (an exp.Column) expands to `"linear.x"`; `speed` (an exp.Alias) is untouched
    — so the result column is named `speed` (D-02 forwards `tree.sql("duckdb")`).
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT vx AS speed FROM cmd_vel", reader)
    assert result.schema.names == ["speed"]
    assert result.column("speed").to_pylist() == [0.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# QURY-09 — projection pushdown wired into query() (Plan 10-03 Task 2 / SC2/SC3).
#
# SC3 is proven by OBSERVING what query() actually materializes — not by re-deriving
# the restrict set in the test. A recording QueryBackend (the existing `backend=`
# seam) WRAPS a real DuckDBBackend: it forwards register_table/execute/close so the
# query runs for real, while capturing each registered pyarrow.Table keyed by name.
# Asserting on the captured table's `column_names` is sufficient proof (research A4):
# a column absent from the registered Table cannot have had its reduce(getattr) run.
# ---------------------------------------------------------------------------


class _RecordingBackend(QueryBackend):
    """A QueryBackend spy that captures each registered Arrow table, wrapping a real one.

    Implements the ABC (register_table/execute/close) by forwarding to an inner
    DuckDBBackend so `execute` returns real query results, while stashing every
    table handed to `register_table` keyed by name. The SC3 assertion reads
    `.registered[name].column_names` — the EXACT column set query() computed and
    passed to build_arrow_table (the load-bearing capture-on-register, research A4).
    """

    def __init__(self) -> None:
        self._inner = DuckDBBackend()
        self.registered: dict[str, pa.Table] = {}

    def register_table(self, name: str, table: object) -> None:
        self.registered[name] = table  # the capture — the SC3 proof reads this
        self._inner.register_table(name, table)

    def execute(self, sql: str) -> object:
        return self._inner.execute(sql)

    def close(self) -> None:
        self._inner.close()


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_projection_materializes_only_referenced_plus_standard(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """SC3: `SELECT vx FROM cmd_vel` materializes exactly {linear.x} ∪ the 4 standard cols.

    Observed via a recording backend wrapping a real DuckDBBackend (the `backend=`
    seam): the table query() registers for `cmd_vel` carries exactly
    {linear.x, t, t_ns, stamp, topic} and EXCLUDES the unreferenced light columns
    angular.z / linear.y (and any heavy blob). This proves the integrated wiring
    alias-expansion -> restrict computation -> build_arrow_table as it runs INSIDE
    query() — not a restrict expression re-derived in the test (research A4 /
    Code Example 5). Parametrized over ROS1 + ROS2-sqlite + MCAP (D-10).
    """
    with RosbagsReader(fixture_bags[fmt]) as reader, _RecordingBackend() as spy:
        query("SELECT vx FROM cmd_vel", reader, backend=spy)
        registered = spy.registered["cmd_vel"]
    assert set(registered.column_names) == {"linear.x", "t", "t_ns", "stamp", "topic"}
    assert "angular.z" not in registered.column_names
    assert "linear.y" not in registered.column_names


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_projection_filtered_rows_still_correct(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Regression: the filtered-rows result still holds with projection ON (all 3 formats).

    `SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5` -> linear.x [1.0, 2.0]
    — projection narrows what is loaded, never what the query returns.
    """
    sql = 'SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5'
    with RosbagsReader(fixture_bags[fmt]) as reader:
        result = query(sql, reader)
    assert result.column("linear.x").to_pylist() == [1.0, 2.0]
    assert result.column("t_ns").to_pylist() == [1_100_000_000, 1_200_000_000]


def test_query_star_disables_projection(fixture_bags: dict[str, Path]) -> None:
    """`SELECT * FROM cmd_vel` materializes ALL non-heavy columns (projection off, D-08).

    Pitfall 4: under a star `referenced_columns` is empty, so a naive `columns | STD`
    would drop every body column — the star path MUST pass `restrict=None`. Observed
    via the recording backend: the registered table keeps angular.z AND linear.y
    (NOT collapsed to just the four standard columns).
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, _RecordingBackend() as spy:
        query("SELECT * FROM cmd_vel", reader, backend=spy)
        registered = spy.registered["cmd_vel"]
    assert "angular.z" in registered.column_names
    assert "linear.y" in registered.column_names
    assert "linear.x" in registered.column_names


def test_query_qualified_star_disables_projection(fixture_bags: dict[str, Path]) -> None:
    """`SELECT o.* FROM cmd_vel AS o` also disables projection (qualified star, Pitfall 5).

    `has_star` is true for `o.*`, so D-08 routes to `restrict=None` before the `'*'`
    column name matters. The observed registered table is the full non-heavy set.
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, _RecordingBackend() as spy:
        query("SELECT o.* FROM cmd_vel AS o", reader, backend=spy)
        registered = spy.registered["cmd_vel"]
    assert "angular.z" in registered.column_names
    assert "linear.y" in registered.column_names
