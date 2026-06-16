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

import re
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

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    make_all_fixtures,
    write_ros1_bag,
    write_ros2_mcap_bag,
    write_ros2_sqlite_bag,
)

from rosbagger_core.backend.base import QueryBackend  # noqa: E402
from rosbagger_core.backend.duckdb_backend import DuckDBBackend  # noqa: E402  (3rd-party)
from rosbagger_core.backend.query import (  # noqa: E402
    UnknownColumnError,
    UnknownTableError,
    _safe_limit_head,
    query,
)
from rosbagger_core.backend.resolve import parse  # noqa: E402
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
# WR-01 — the user's RAW SQL is forwarded VERBATIM unless alias expansion ran.
#
# Phase 5's trusted-SQL-as-is boundary (T-05-04) means a query that triggers NO
# alias rewrite must reach the backend BYTE-FOR-BYTE — never round-tripped through
# sqlglot's renderer (which rewrites surface syntax, e.g. `x::INTEGER` ->
# `CAST(x AS INT)`). These observe the EXACT string handed to `backend.execute`
# via a recording spy (the existing `backend=` seam), proving:
#   * a `--no-alias` query is executed verbatim (no sqlglot normalization), and
#   * an alias-EXPANDED query DOES forward the re-rendered (dotted) SQL.
# `t_ns` is a real standard column, so `SELECT t_ns::INTEGER FROM cmd_vel` runs for
# real; sqlglot would re-render `::INTEGER` to `CAST(... AS INT)` if the orchestrator
# normalized it — so an unchanged capture is a sharp proof of verbatim forwarding.
# ---------------------------------------------------------------------------


class _SQLCapturingBackend(QueryBackend):
    """A QueryBackend spy that records the EXACT SQL string passed to `execute`.

    Wraps a real DuckDBBackend so the query runs end-to-end (register/execute/close
    forward), while capturing every string handed to `execute` in `executed_sql`.
    The WR-01 assertions read `executed_sql[-1]` — the literal text query() forwarded
    to the backend, NOT a value re-derived in the test.
    """

    def __init__(self) -> None:
        self._inner = DuckDBBackend()
        self.executed_sql: list[str] = []

    def register_table(self, name: str, table: object) -> None:
        self._inner.register_table(name, table)

    def execute(self, sql: str) -> object:
        self.executed_sql.append(sql)  # the capture — the WR-01 proof reads this
        return self._inner.execute(sql)

    def close(self) -> None:
        self._inner.close()


def test_query_no_alias_forwards_raw_sql_verbatim(fixture_bags: dict[str, Path]) -> None:
    """WR-01: `alias=False` forwards the user's SQL byte-for-byte (no sqlglot re-render).

    `SELECT t_ns::INTEGER FROM cmd_vel` would re-render to
    `SELECT CAST(t_ns AS INT) FROM cmd_vel` if normalized through sqlglot. With the
    raw-SQL fallback, the spy captures the ORIGINAL `::INTEGER` text unchanged — the
    `--no-alias` escape hatch is a true verbatim bypass again.
    """
    raw = "SELECT t_ns::INTEGER FROM cmd_vel"
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, _SQLCapturingBackend() as spy:
        query(raw, reader, alias=False, backend=spy)
    assert spy.executed_sql == [raw]  # exact string forwarded — no round-trip
    assert "CAST" not in spy.executed_sql[-1]  # NOT the sqlglot-normalized form


def test_query_no_op_alias_forwards_raw_sql_verbatim(fixture_bags: dict[str, Path]) -> None:
    """WR-01: a query that triggers NO expansion (default `alias=True`) is also verbatim.

    `SELECT t_ns::INTEGER FROM cmd_vel` references no alias token, so even with the
    alias pack enabled nothing is rewritten — the SQL-comparison signal reads "no
    change" and the raw string is forwarded unchanged (not the `CAST(... AS INT)`
    round-trip). This pins the default no-match path, not just `--no-alias`.
    """
    raw = "SELECT t_ns::INTEGER FROM cmd_vel"
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, _SQLCapturingBackend() as spy:
        query(raw, reader, backend=spy)  # alias=True default; no alias token present
    assert spy.executed_sql == [raw]
    assert "CAST" not in spy.executed_sql[-1]


def test_query_alias_expansion_forwards_rewritten_sql(fixture_bags: dict[str, Path]) -> None:
    """WR-01 (other side): when an alias IS expanded, the REWRITTEN SQL is forwarded.

    `SELECT vx FROM cmd_vel` expands `vx` -> `"linear.x"`, so the string reaching the
    backend is the re-rendered tree carrying the dotted column — NOT the original
    `vx`. This confirms the fix preserves the alias path (D-02): expansion still
    re-renders, only the no-expansion paths fall back to verbatim.
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader, _SQLCapturingBackend() as spy:
        query("SELECT vx FROM cmd_vel", reader, backend=spy)
    forwarded = spy.executed_sql[-1]
    assert '"linear.x"' in forwarded  # the expanded dotted column reached the backend
    assert re.search(r"\bvx\b", forwarded) is None, forwarded  # no bare alias survives


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


# ---------------------------------------------------------------------------
# The reserved `events` table (Plan 11-04 / D-14 / D-15 / SC3).
#
# These write a sidecar NEXT TO a FRESH per-test bag (never the shared session
# fixtures), so the `<bag>.events.parquet` they create is isolated and cannot
# leak into the other query tests. Each format gets its own throwaway bag via the
# per-format writers (mirrors tests/test_cli_edit.py's per-format fixtures).
# ---------------------------------------------------------------------------

# The per-format writer for each FORMATS key — used to materialize an isolated bag
# (with no shared sidecar) for the events tests.
_WRITERS = {
    "ros1": write_ros1_bag,
    "ros2_sqlite": write_ros2_sqlite_bag,
    "ros2_mcap": write_ros2_mcap_bag,
}


@pytest.mark.parametrize("fmt", FORMATS)
def test_query_events_join_returns_windowed_rows(tmp_path: Path, fmt: str) -> None:
    """SC3: a standard `BETWEEN` interval join against the reserved `events` table.

    Write an event window `[1.0s, 1.1s]` next to a fresh bag, then join `/imu` to
    `events` on `i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns`. The 3-message fixture
    logs /imu at t_ns = 1.0/1.1/1.2s, so the window selects EXACTLY the 1.0s + 1.1s
    rows (the 1.2s row is outside) — the VERIFIED RESEARCH result (D-15, no special
    operator). Parametrized over ROS1 + ROS2-sqlite3 + MCAP (D-10).
    """
    from rosbagger_core.events import add_event

    bag = _WRITERS[fmt](tmp_path / fmt)
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="window")
    sql = "SELECT i.t_ns FROM imu i JOIN events e ON i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns"
    with RosbagsReader(bag) as reader:
        result = query(sql, reader)
    assert isinstance(result, pa.Table)
    assert set(result.column("t_ns").to_pylist()) == {1_000_000_000, 1_100_000_000}


def test_query_events_reserved_name_not_unknown_table(tmp_path: Path) -> None:
    """`SELECT * FROM events` with a sidecar present returns the event rows (no error).

    `events` is SUBTRACTED from topic resolution (D-14), so it is NEVER mistaken for
    a topic and NEVER raises `UnknownTableError`. With a sidecar present, the rows
    come back with the fixed v1 schema (label/t_start_ns/...).
    """
    from rosbagger_core.events import add_event

    bag = write_ros1_bag(tmp_path / "reserved")
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="turn", note="left")
    with RosbagsReader(bag) as reader:
        result = query("SELECT * FROM events", reader)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 1
    assert set(result.column_names) == {"t_start_ns", "t_end_ns", "label", "note"}
    assert result.column("label").to_pylist() == ["turn"]


def test_query_events_absent_sidecar_yields_zero_rows(tmp_path: Path) -> None:
    """No sidecar -> `SELECT * FROM events` is a 0-row table, NOT an error (Open Q3).

    When no `<bag>.events.parquet` exists, query() registers an EMPTY-schema `events`
    relation (the fixed v1 four columns), so a SELECT/join yields zero rows rather
    than a DuckDB "table does not exist" or an `UnknownTableError` (Open Q3 LOCKED —
    predictable behavior).
    """
    bag = write_ros1_bag(tmp_path / "absent")  # NO add_event -> no sidecar
    with RosbagsReader(bag) as reader:
        result = query("SELECT * FROM events", reader)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 0
    assert set(result.column_names) == {"t_start_ns", "t_end_ns", "label", "note"}


def _write_bag_with_events_topic(dest_dir: Path, *, topic: str = "/events") -> Path:
    """Write a ROS 1 bag whose ONLY topic is a real ``events``-named topic (CR-01 fixture).

    ``topic`` (default ``/events``) sanitizes to a table name that collides with the
    reserved event sidecar — pass ``/Events`` for the case-variant collision. The topic
    carries 3 ``geometry_msgs/msg/Twist`` messages (headerless, no covariance) at
    t = 1.0 / 1.1 / 1.2 s with ``linear.x`` = 0.0 / 1.0 / 2.0, mirroring the corpus's
    ``/cmd_vel`` content so the rows are easy to assert.
    """
    from rosbags.rosbag1 import Writer as Ros1Writer
    from rosbags.typesys import Stores, get_typestore

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "events_topic.bag"
    ts = get_typestore(Stores.ROS1_NOETIC)
    vector3_t = ts.types["geometry_msgs/msg/Vector3"]
    twist_t = ts.types["geometry_msgs/msg/Twist"]
    with Ros1Writer(path) as writer:
        conn = writer.add_connection(topic, "geometry_msgs/msg/Twist", typestore=ts)
        for i in range(3):
            msg = twist_t(
                linear=vector3_t(x=float(i), y=0.0, z=0.0),
                angular=vector3_t(x=0.0, y=0.0, z=0.1 * i),
            )
            writer.write(
                conn,
                1_000_000_000 + i * 100_000_000,
                ts.serialize_ros1(msg, "geometry_msgs/msg/Twist"),
            )
    return path


def test_query_real_events_topic_not_shadowed_by_sidecar(tmp_path: Path) -> None:
    """CR-01: a REAL `/events` topic returns ITS rows from `SELECT * FROM events`.

    A bag publishing an `/events` topic sanitizes that topic to the table name `events`,
    which collides with the reserved event-sidecar name. Before the fix the sidecar
    silently shadowed the topic (0 rows, the sidecar's 4-column schema) with no error.
    The topic must take precedence: `SELECT * FROM events` returns the 3 Twist rows
    (linear.x = 0/1/2), NOT the empty sidecar relation.
    """
    bag = _write_bag_with_events_topic(tmp_path / "real_events")
    with RosbagsReader(bag) as reader:
        result = query("SELECT * FROM events", reader)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 3  # the topic's rows, not the sidecar's 0 rows
    # The Twist topic flattens to dotted columns — the sidecar's schema is
    # {t_start_ns, t_end_ns, label, note}, which must NOT be what we got back.
    assert "linear.x" in result.column_names
    assert set(result.column_names) != {"t_start_ns", "t_end_ns", "label", "note"}
    assert result.column("linear.x").to_pylist() == [0.0, 1.0, 2.0]


def test_query_capitalized_events_topic_not_shadowed_by_sidecar(tmp_path: Path) -> None:
    """CR-01 (case-insensitive): a real `/Events` topic queried as `events` returns ITS rows.

    Regression for the audit bug: `/Events` sanitizes to table name `Events`, but the
    CR-01 precedence guard compared against the EXACT-case table map, so it missed the
    case-variant and `events_referenced` reserved the name for the (empty) sidecar —
    silently shadowing the real topic with 0 rows. Everything else in query() folds
    identifier case (newA5), so the guard must too. `SELECT * FROM events` must return
    the 3 Twist rows, not the empty sidecar relation.
    """
    bag = _write_bag_with_events_topic(tmp_path / "cap_events", topic="/Events")
    with RosbagsReader(bag) as reader:
        result = query("SELECT * FROM events", reader)
    assert result.num_rows == 3  # the /Events topic's rows, not the empty sidecar's 0
    assert "linear.x" in result.column_names
    assert set(result.column_names) != {"t_start_ns", "t_end_ns", "label", "note"}
    assert result.column("linear.x").to_pylist() == [0.0, 1.0, 2.0]


def test_query_real_events_topic_wins_even_with_sidecar_present(tmp_path: Path) -> None:
    """CR-01: even if a sidecar ALSO exists, the real `/events` topic still wins.

    A `<bag>.events.parquet` sidecar sitting next to a bag that ALSO has a real
    `/events` topic must not hide the topic — the topic owns the `events` table name,
    so `SELECT * FROM events` returns the topic's 3 Twist rows, never the sidecar row.
    """
    from rosbagger_core.events import add_event

    bag = _write_bag_with_events_topic(tmp_path / "events_and_sidecar")
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="sidecar")
    with RosbagsReader(bag) as reader:
        result = query("SELECT * FROM events", reader)
    assert result.num_rows == 3  # topic rows, not the 1 sidecar row
    assert "linear.x" in result.column_names
    assert "label" not in result.column_names  # the sidecar schema did NOT win


def test_query_events_join_does_not_break_aliasing(tmp_path: Path) -> None:
    """A topic-JOIN-events query keeps the single-base-topic alias gate behavior.

    `events` maps to no topic, so the alias gate's `t in table_to_topic` filter
    leaves exactly ONE mapped base topic (`cmd_vel`) — aliasing is unaffected, and
    the unqualified `vx` alias STILL expands to `linear.x` (the existence-gate keys
    on cmd_vel's Twist pack) while `events` is subtracted from topic resolution. The
    window `[1.0s, 1.1s]` selects the 1.0s + 1.1s /cmd_vel rows, whose linear.x
    (== vx == float(i)) are 0.0 and 1.0. (Per the plan: a qualified `c.vx` is
    deliberately NOT expanded by the alias rewrite — `expand_aliases` only rewrites
    UNqualified short columns; so this positive assertion uses bare `vx`, which the
    JOIN does not make ambiguous because `events` has no `vx` column.)
    """
    from rosbagger_core.events import add_event

    bag = write_ros1_bag(tmp_path / "alias")
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="window")
    sql = "SELECT vx FROM cmd_vel JOIN events e ON t_ns BETWEEN e.t_start_ns AND e.t_end_ns"
    with RosbagsReader(bag) as reader:
        result = query(sql, reader)
    # vx expands to linear.x; the result column is the dotted expanded name.
    assert result.num_rows == 2
    assert sorted(result.column("linear.x").to_pylist()) == [0.0, 1.0]


# ---------------------------------------------------------------------------
# newA4 — schemas are built ONLY for referenced topics, never for every topic.
# ---------------------------------------------------------------------------


def test_query_builds_schema_only_for_referenced_topics(
    fixture_bags: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unbuildable UNREFERENCED topic must not crash a query (newA4).

    The orchestrator previously built a TableSchema for EVERY topic in the bag up
    front (Step 3 eager comprehension), so one unbuildable topic (a vendor msgtype
    absent from a caller-supplied typestore, or a recursive type) raised before
    resolution and crashed queries that never touched it. We patch
    ``build_table_schema`` to FAIL for ``/image`` and assert that querying ``/cmd_vel``
    still succeeds and that ``/image`` (and ``/imu``) were never built.
    """
    import rosbagger_core.schema as schema_mod

    real_build = schema_mod.build_table_schema
    built: list[str] = []

    def spy(msgtype: str, typestore: object, *, topic: str):
        built.append(topic)
        if topic == "/image":  # simulate an unbuildable, unreferenced topic
            raise KeyError("simulated unbuildable topic /image")
        return real_build(msgtype, typestore, topic=topic)

    # query() does `from rosbagger_core.schema import build_table_schema` at call time,
    # so patching the package attribute is picked up by the function-local import.
    monkeypatch.setattr(schema_mod, "build_table_schema", spy)

    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT t_ns FROM cmd_vel", reader)

    assert result.column("t_ns").to_pylist() == [1_000_000_000, 1_100_000_000, 1_200_000_000]
    # Only the referenced topic was built — /image (unbuildable) and /imu never were.
    assert built == ["/cmd_vel"]


# ---------------------------------------------------------------------------
# newA5 — table-name resolution is case-insensitive (DuckDB folds identifiers).
# ---------------------------------------------------------------------------


def test_query_table_name_resolves_case_insensitively(tmp_path: Path) -> None:
    """A lowercase reference to a capitalized topic's table resolves (newA5).

    A bag with topic ``/Imu`` has table name ``Imu``. The orchestrator resolved table
    names with a case-SENSITIVE dict lookup, so ``SELECT ... FROM imu`` raised
    UnknownTableError even though DuckDB (case-insensitive) would have matched the
    registered ``Imu`` relation had the SQL reached it. Resolution now folds case.
    """
    from tools.make_fixtures import write_capitalized_topic_bag

    bag = write_capitalized_topic_bag(tmp_path)  # topic /Imu -> table "Imu"
    with RosbagsReader(bag) as reader:
        lower = query("SELECT t_ns FROM imu", reader)
        exact = query("SELECT t_ns FROM Imu", reader)
    assert lower.column("t_ns").to_pylist() == [1_000_000_000, 1_100_000_000, 1_200_000_000]
    assert exact.column("t_ns").to_pylist() == lower.column("t_ns").to_pylist()


# ---------------------------------------------------------------------------
# F2 — narrow, provably-safe LIMIT pushdown (decode only the first k+m messages).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,expected",
    [
        # SAFE — a bare single-table scan with a literal LIMIT (and optional OFFSET).
        ("SELECT * FROM imu LIMIT 5", 5),
        ("SELECT t_ns FROM imu LIMIT 5", 5),
        ("SELECT a, b FROM imu LIMIT 5 OFFSET 3", 8),
        ("SELECT * FROM imu AS i LIMIT 1", 1),
        ('SELECT "linear.x" + 1 AS s FROM cmd_vel LIMIT 2', 2),  # row-wise expr is safe
        ("SELECT * FROM imu LIMIT 0", 0),
        # UNSAFE — early-stop would change the result, so NO pushdown (None).
        ("SELECT * FROM imu", None),  # no LIMIT at all
        ("SELECT * FROM imu WHERE a > 1 LIMIT 5", None),  # filter
        ("SELECT * FROM imu ORDER BY t_ns LIMIT 5", None),  # reorder
        ("SELECT a FROM imu GROUP BY a LIMIT 5", None),  # grouping
        ("SELECT count(*) FROM imu LIMIT 5", None),  # aggregate
        ("SELECT DISTINCT a FROM imu LIMIT 5", None),  # dedup
        ("SELECT a, count(*) FROM imu GROUP BY a HAVING count(*) > 1 LIMIT 5", None),
        ("SELECT * FROM a JOIN b ON a.x = b.x LIMIT 5", None),  # join
        ("SELECT * FROM imu, other LIMIT 5", None),  # comma-join
        ("SELECT * FROM (SELECT * FROM imu) LIMIT 5", None),  # derived table
        ("WITH c AS (SELECT * FROM imu) SELECT * FROM c LIMIT 5", None),  # CTE
        ("SELECT * FROM imu UNION SELECT * FROM other LIMIT 5", None),  # set op
        ("SELECT row_number() OVER () AS r FROM imu LIMIT 5", None),  # window
        # A numeric-but-non-integer LIMIT/OFFSET is valid SQL (DuckDB ceils it) but is NOT
        # a safe islice count — bail to None instead of crashing with int('1.5') ValueError.
        ("SELECT * FROM imu LIMIT 1.5", None),
        ("SELECT * FROM imu LIMIT 5 OFFSET 1.5", None),
    ],
)
def test_safe_limit_head_detection(sql: str, expected: int | None) -> None:
    """The LIMIT-pushdown gate fires for a bare scan+LIMIT and bails on every other shape (F2)."""
    assert _safe_limit_head(parse(sql)) == expected


def test_non_integer_limit_does_not_crash_query(fixture_bags: dict[str, Path]) -> None:
    """A valid non-integer LIMIT (1.5) bails the pushdown and runs via DuckDB — no ValueError.

    Regression for the audit bug: `_safe_limit_head` did `int(count.name)` on a non-string
    Literal, so `LIMIT 1.5` (which DuckDB accepts) crashed the whole query() with a
    ValueError before DuckDB ran. The pushdown now returns None for a non-integer literal
    and the query executes normally.
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        result = query("SELECT t_ns FROM imu LIMIT 1.5", reader)
    assert result.num_rows >= 1  # ran without crashing (DuckDB ceils 1.5 -> 2 rows)


@pytest.mark.parametrize("fmt", FORMATS)
def test_limit_pushdown_matches_full_scan(fixture_bags: dict[str, Path], fmt: str) -> None:
    """LIMIT / OFFSET pushdown returns the SAME rows as a full scan; ORDER BY stays correct (F2).

    cmd_vel has three messages (t_ns 1.0/1.1/1.2e9). A bare LIMIT/OFFSET must match the full-scan
    prefix, and an ORDER BY ... LIMIT must still return the globally-sorted top — proving pushdown
    is NOT applied when a reorder is present (else it would slice the wrong rows then sort them).
    """
    desc_sql = "SELECT t_ns FROM cmd_vel ORDER BY t_ns DESC LIMIT 2"
    with RosbagsReader(fixture_bags[fmt]) as reader:
        full = query("SELECT t_ns FROM cmd_vel", reader).column("t_ns").to_pylist()
        lim = query("SELECT t_ns FROM cmd_vel LIMIT 2", reader).column("t_ns").to_pylist()
        off = query("SELECT t_ns FROM cmd_vel LIMIT 2 OFFSET 1", reader).column("t_ns").to_pylist()
        desc = query(desc_sql, reader).column("t_ns").to_pylist()
    assert len(full) >= 3
    assert lim == full[:2]
    assert off == full[1:3]
    assert desc == sorted(full, reverse=True)[:2]


@pytest.mark.parametrize("fmt", FORMATS)
def test_limit_pushdown_stops_decoding_early(fixture_bags: dict[str, Path], fmt: str) -> None:
    """A bare LIMIT decodes only k messages; an ORDER BY ... LIMIT still decodes them all (F2).

    Wraps the reader to count messages actually pulled from ``reader.read``. The bare-LIMIT query
    slices the lazy stream to k (so exactly k are deserialized); the ORDER BY query gets no
    pushdown and pulls the whole cmd_vel stream.
    """

    class _CountingReader:
        def __init__(self, inner: object) -> None:
            self._inner = inner
            self.pulled = 0

        def read(self, **kwargs: object):
            for msg in self._inner.read(**kwargs):
                self.pulled += 1
                yield msg

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

    with RosbagsReader(fixture_bags[fmt]) as reader:
        bare = _CountingReader(reader)
        query("SELECT t_ns FROM cmd_vel LIMIT 2", bare)
        ordered = _CountingReader(reader)
        query("SELECT t_ns FROM cmd_vel ORDER BY t_ns DESC LIMIT 2", ordered)
    assert bare.pulled == 2, f"bare LIMIT should decode exactly 2 messages, decoded {bare.pulled}"
    assert ordered.pulled == 3, f"ORDER BY LIMIT must decode all 3, got {ordered.pulled}"
