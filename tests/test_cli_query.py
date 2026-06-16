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


def test_query_format_preflight_fails_before_running_query(ros1_bag: Path) -> None:
    """``--format parquet`` (no -o) is rejected BEFORE the query runs (fast-fail preflight).

    Proven by referencing a bogus table: if the query ran first it would raise
    UnknownTableError (exit 1); the up-front --format preflight wins with a clean BadParameter
    (exit 2) naming the binary-to-stdout guard — no minutes-long scan wasted on a typo.
    """
    result = runner.invoke(
        app, ["query", "SELECT * FROM no_such_table", str(ros1_bag), "--format", "parquet"]
    )
    assert result.exit_code == 2  # BadParameter, before the query's UnknownTableError (exit 1)
    assert "Parquet is binary" in result.output


def test_query_plot_error_presents_cleanly(ros1_bag: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A plot-sink error (e.g. matplotlib missing) presents as a clean error, not a traceback.

    @teaching_errors does NOT catch plot_table's RuntimeError/ValueError, so they previously
    escaped as a raw traceback. The query handler now maps them to a clean BadParameter.
    """

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("matplotlib is not installed; install bagq[plot]")

    monkeypatch.setattr("rosbagger_core.output.plot_table", boom)
    result = runner.invoke(app, ["query", "SELECT t_ns FROM imu", str(ros1_bag), "--plot"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "matplotlib" in result.output  # the teaching text, not a traceback


def test_help_lists_query_subcommand() -> None:
    """``bagq --help`` lists the ``query`` subcommand alongside info/tables."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "query" in result.stdout


def test_query_no_alias_default_expands_vx(ros1_bag: Path) -> None:
    """Aliases ON by default (D-11): ``SELECT vx FROM cmd_vel`` exits 0 and renders rows.

    ``/cmd_vel`` is a ``geometry_msgs/msg/Twist`` (no header), so the built-in alias pack
    expands ``vx`` -> the dotted ``linear.x``; the query resolves and prints the result.
    Asserts a stable signal (the value ``0.0`` of the first ``linear.x`` row), NOT rich
    box-drawing — mirroring ``test_query_default_prints_table``'s data-only style.
    """
    result = runner.invoke(app, ["query", "SELECT vx FROM cmd_vel", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    assert "linear.x" in result.stdout  # the expanded dotted column header
    assert "0.0" in result.stdout  # the first cmd_vel linear.x value (proves a row rendered)


def test_query_no_alias_flag_disables_expansion(ros1_bag: Path) -> None:
    """``--no-alias`` disables the pack: ``vx`` is no longer a column -> a clean Exit(1).

    With expansion off, ``vx`` is not a real column of the Twist schema, so DuckDB's
    binder rejects it and ``query()`` re-maps it to ``UnknownColumnError`` — surfaced by
    ``@teaching_errors`` as a single stderr teaching line + ``Exit(1)`` with NO traceback.
    Mirrors the 07/09 no-traceback convention: a clean ``typer.Exit(1)`` reaches CliRunner
    as ``SystemExit`` (NOT a raw ``ValueError``); the message names the unknown column.
    """
    result = runner.invoke(app, ["query", "--no-alias", "SELECT vx FROM cmd_vel", str(ros1_bag)])
    assert result.exit_code == 1, result.output
    assert "vx" in result.output  # the teaching message names the unknown column
    # No traceback escaped: a clean Exit(1) is SystemExit, and the raw typed error did not
    # leak through @teaching_errors (07/09 convention).
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, ValueError)


def test_query_help_lists_no_alias_option() -> None:
    """``bagq query --help`` lists the ``--no-alias`` option (it is registered)."""
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--no-alias" in result.stdout


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


def test_query_bad_output_extension_fails_fast_clean(ros1_bag: Path, tmp_path: Path) -> None:
    """`-o out.txt` is rejected BEFORE the query runs, with a clean message (newA6).

    The extension was validated only inside write_table — AFTER materializing the
    result — and raised a bare ValueError that @teaching_errors does not catch, so the
    user got a Python traceback after waiting for the whole query. It is now preflighted
    to a typer.BadParameter: a clean message, no traceback, and no output file written.
    """
    import re

    out = tmp_path / "result.txt"
    result = runner.invoke(
        app, ["query", "SELECT t_ns FROM cmd_vel", str(ros1_bag), "-o", str(out)]
    )
    assert result.exit_code != 0
    # rich renders the BadParameter inside a box, wrapping the message across border
    # chars — collapse box-drawing + whitespace before matching the phrase.
    flat = re.sub(r"[│╭╮╰╯─\s]+", " ", result.output)
    assert "Unknown output extension 'txt'; use .csv or .parquet" in flat
    # No raw ValueError traceback escaped (BadParameter -> click usage error, exit 2).
    assert not isinstance(result.exception, ValueError)
    assert not out.exists()
