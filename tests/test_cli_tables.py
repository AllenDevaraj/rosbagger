"""CliRunner smoke tests for the ``bagq tables`` subcommand (INSP-03).

These prove the thin CLI wires the core ``collect_table_schemas`` API to a
rich-rendered per-topic column table and exits 0 — WITHOUT asserting exact rich
box-drawing/whitespace (only the stable data: table names, a representative
column name, and the heavy-blob ``data`` column shown + marked ``lazy``). They
also exercise the two render branches the host-coverage note calls out — the
heavy-blob annotation and the multi-msgtype skip / "no topics" path — so the
``--cov=bagq`` gate is met by exercising real behavior, not by weakening it.

LOCAL-RUN REQUIREMENT (04-RESEARCH.md): this dev host sources ROS 2 Humble onto
``PYTHONPATH``; run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_tables.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_reader.py / tests/test_cli_info.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from bagq.cli import _render_table_schemas, app  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (3 topics) for the CLI to list tables for."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_tables_bag"))


def test_tables_exits_zero_and_shows_table_names_and_columns(ros1_bag: Path) -> None:
    """``bagq tables BAG`` exits 0 and prints each table name + columns incl. ``data``.

    Asserts only stable data (INSP-03) — never rich box-drawing/whitespace. The
    three sanitized table names, a representative standard column (``t_ns``), and
    the heavy-blob column ``data`` must all appear in the output.
    """
    result = runner.invoke(app, ["tables", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    for table_name in ("cmd_vel", "imu", "image"):
        assert table_name in out
    assert "t_ns" in out  # a standard column (proves columns are listed)
    assert "data" in out  # the Image heavy-blob column is SHOWN, not hidden


def test_tables_marks_heavy_blob_as_lazy(ros1_bag: Path) -> None:
    """The heavy-blob ``data`` column is visually marked lazy (Pattern 4 / A2)."""
    result = runner.invoke(app, ["tables", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    assert "lazy" in result.stdout  # blob annotation present (not hidden)


def test_help_lists_info_and_tables_subcommands() -> None:
    """``bagq --help`` lists BOTH the ``info`` and the new ``tables`` subcommand."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "info" in result.stdout
    assert "tables" in result.stdout


def test_tables_missing_bag_propagates_error(tmp_path: Path) -> None:
    """A nonexistent bag path surfaces an error (non-zero exit); Phase 7 owns teaching."""
    missing = tmp_path / "does_not_exist.bag"
    result = runner.invoke(app, ["tables", str(missing)])
    assert result.exit_code != 0


def test_render_no_topics_prints_no_topics(capsys) -> None:
    """An empty schema list renders a ``no topics`` line rather than an empty table."""
    _render_table_schemas([])
    assert "no topics" in capsys.readouterr().out
