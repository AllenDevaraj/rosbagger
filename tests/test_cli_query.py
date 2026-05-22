"""CliRunner smoke tests for the ``bagq query`` subcommand (OUT-01/02/03 wiring).

These prove the thin CLI wires Phase 5's ``query()`` to the Phase 6 output routing and
exits 0 — WITHOUT asserting rich box-drawing/whitespace (only stable data: a column
name, a topic value, a written file's header, parsed JSON records, the ``(0 rows)``
line, the binary-to-stdout guard, and the ``query`` subcommand in ``--help``).

LOCAL-RUN REQUIREMENT (06-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_query.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_tables.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from bagq.cli import _render_result, app  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for the query command to run on."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_query_bag"))


def test_query_default_prints_table(ros1_bag: Path) -> None:
    """``bagq query "<SQL>" BAG`` exits 0 and prints the result (col name + a topic value)."""
    result = runner.invoke(app, ["query", "SELECT t, t_ns, topic FROM cmd_vel", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    assert "t_ns" in result.stdout  # a column header
    assert "/cmd_vel" in result.stdout  # a topic value (proves rows rendered)


def test_query_output_csv_writes_file(ros1_bag: Path, tmp_path: Path) -> None:
    """``-o <tmp>.csv`` exits 0 and writes a CSV file whose header reads back (OUT-02)."""
    out = tmp_path / "result.csv"
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.read_text().splitlines()[0] == "t_ns,topic"


def test_query_output_parquet_writes_file(ros1_bag: Path, tmp_path: Path) -> None:
    """``-o <tmp>.parquet`` exits 0 and writes a Parquet file that reads back (OUT-03)."""
    import pyarrow.parquet as pq

    out = tmp_path / "result.parquet"
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    back = pq.read_table(str(out))
    assert back.column_names == ["t_ns", "topic"]
    assert back.num_rows == 3


def test_query_format_json_prints_records(ros1_bag: Path) -> None:
    """``--format json`` exits 0 and prints a non-empty list of dicts with a ``t_ns`` key."""
    result = runner.invoke(
        app, ["query", "SELECT t, t_ns, topic FROM cmd_vel", str(ros1_bag), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, list) and len(payload) == 3
    assert "t_ns" in payload[0]


def test_query_format_csv_prints_capturable_csv(ros1_bag: Path) -> None:
    """``--format csv`` (no ``-o``) prints CSV that CliRunner CAPTURES (WR-02 fix).

    Previously impossible: the old ``write_csv_stream`` wrote to ``/dev/stdout`` at OS
    fd 1, so ``result.output`` was empty (and the path broke on Windows). Routed through
    ``write_csv_to_string`` + ``typer.echo``, the CSV now appears in ``result.output``.
    """
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "--format", "csv"]
    )
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "t_ns,topic"  # the CSV header is now captured
    assert "/cmd_vel" in result.stdout  # a topic value rendered


def test_query_empty_result_prints_zero_rows(ros1_bag: Path) -> None:
    """A ``WHERE 1=0`` query with the default format exits 0 and prints ``(0 rows)``."""
    result = runner.invoke(
        app, ["query", "SELECT t, t_ns, topic FROM cmd_vel WHERE 1=0", str(ros1_bag)]
    )
    assert result.exit_code == 0, result.output
    assert "(0 rows)" in result.stdout


def test_query_format_parquet_without_output_errors(ros1_bag: Path) -> None:
    """``--format parquet`` with no ``-o`` exits non-zero (binary-to-stdout guard, A2)."""
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "--format", "parquet"]
    )
    assert result.exit_code != 0


def test_query_unknown_format_errors(ros1_bag: Path) -> None:
    """An unknown ``--format`` value exits non-zero (listing the four formats)."""
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "--format", "xml"]
    )
    assert result.exit_code != 0


def test_help_lists_query_subcommand() -> None:
    """``bagq --help`` lists the ``query`` subcommand alongside info/tables."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "query" in result.stdout


def test_render_result_zero_rows_prints_shape(capsys) -> None:
    """``_render_result`` on a 0-row table prints ``(0 rows)`` + the column names.

    Built directly (a fresh fixture-backed empty result) so the Pitfall-3 branch is
    exercised without rich box-drawing in the assertion.
    """
    import pyarrow as pa

    empty = pa.table(
        {"t_ns": pa.array([], type=pa.int64()), "topic": pa.array([], type=pa.string())}
    )
    _render_result(empty)
    out = capsys.readouterr().out
    assert "(0 rows)" in out
    assert "t_ns" in out and "topic" in out
