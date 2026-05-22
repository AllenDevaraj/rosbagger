"""Tests for the ``--plot`` line chart (OUT-04): ``plot_table`` + the CLI flag.

The whole module is guarded by ``pytest.importorskip("matplotlib")`` (06-RESEARCH
Pitfall 5): matplotlib is the optional ``bagq[plot]`` extra and is added to the root
dev group so CI/``uv run`` have it — a contributor without the dev group is SKIPPED,
not errored. Assertions stay on stable facts (a PNG file exists and is non-empty, an
error is raised, ``--plot`` appears in ``--help``) — never on rendered pixels.

LOCAL-RUN REQUIREMENT (06-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_output_plot.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("matplotlib")  # skip the whole module without the optional plot extra

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_query.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from bagq.cli import app  # noqa: E402
from rosbagger_core.backend.query import query as run_query  # noqa: E402
from rosbagger_core.output import plot_table  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for plot queries to run on."""
    return write_ros1_bag(tmp_path_factory.mktemp("plot_bag"))


def _result(bag: Path, sql: str):
    """Run ``sql`` against ``bag`` and return the materialized result Table."""
    with RosbagsReader([bag]) as reader:
        return run_query(sql, reader)


# --- plot_table (the core helper) -------------------------------------------------


def test_plot_table_writes_nonempty_png(ros1_bag: Path, tmp_path: Path) -> None:
    """A numeric-vs-t_ns result writes a non-empty PNG (headless Agg backend).

    ``linear.x`` is a ``double`` Twist scalar (verified via the schema); ``t_ns`` is the
    x-axis. The PNG must exist and have size > 0 with DISPLAY unset.
    """
    result = _result(ros1_bag, 'SELECT t_ns, "linear.x" FROM cmd_vel')
    out = tmp_path / "chart.png"
    plot_table(result, out)
    assert out.exists()
    assert os.path.getsize(out) > 0


def test_plot_table_no_numeric_columns_raises(ros1_bag: Path, tmp_path: Path) -> None:
    """A result with only ``topic`` (a string) raises a clear nothing-to-plot ValueError."""
    result = _result(ros1_bag, "SELECT topic FROM cmd_vel")
    out = tmp_path / "nope.png"
    with pytest.raises(ValueError, match="(?i)nothing to plot|numeric"):
        plot_table(result, out)
    assert not out.exists()


def test_plot_table_only_t_ns_raises(ros1_bag: Path, tmp_path: Path) -> None:
    """``SELECT t_ns`` alone has no y-series (t_ns is the x-axis) — raises ValueError."""
    result = _result(ros1_bag, "SELECT t_ns FROM cmd_vel")
    out = tmp_path / "only-x.png"
    with pytest.raises(ValueError, match="(?i)nothing to plot|numeric"):
        plot_table(result, out)


def test_plot_table_no_time_column_raises(ros1_bag: Path, tmp_path: Path) -> None:
    """A numeric result with neither ``t`` nor ``t_ns`` raises a clear no-x-column error."""
    result = _result(ros1_bag, 'SELECT "linear.x" FROM cmd_vel')
    out = tmp_path / "no-x.png"
    with pytest.raises(ValueError, match="(?i)nothing to plot|t_ns"):
        plot_table(result, out)


def test_plot_table_zero_rows_raises(ros1_bag: Path, tmp_path: Path) -> None:
    """A 0-row result raises a clear 'nothing to plot' message, not a blank chart."""
    result = _result(ros1_bag, 'SELECT t_ns, "linear.x" FROM cmd_vel WHERE 1=0')
    out = tmp_path / "empty.png"
    with pytest.raises(ValueError, match="(?i)0 rows|nothing to plot"):
        plot_table(result, out)
    assert not out.exists()


def test_plot_table_closes_figures(ros1_bag: Path, tmp_path: Path) -> None:
    """Repeated plot_table calls leave no open figures (Pitfall 7 — figure-leak DoS)."""
    import matplotlib.pyplot as plt

    result = _result(ros1_bag, 'SELECT t_ns, "linear.x" FROM cmd_vel')
    for i in range(3):
        plot_table(result, tmp_path / f"loop-{i}.png")
    assert plt.get_fignums() == []


# --- bagq query --plot [FILE] (the CLI flag, OUT-04) ------------------------------


def test_query_plot_with_file_writes_png(ros1_bag: Path, tmp_path: Path) -> None:
    """``--plot <tmp>.png`` exits 0 and writes that exact non-empty PNG (OUT-04)."""
    out = tmp_path / "chart.png"
    result = runner.invoke(
        app, ["query", 'SELECT t_ns, "linear.x" FROM cmd_vel', str(ros1_bag), "--plot", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert os.path.getsize(out) > 0


def test_query_bare_plot_writes_default_filename(
    ros1_bag: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare ``--plot`` (no value) exits 0 and writes the default ``plot.png`` in CWD (A1)."""
    monkeypatch.chdir(tmp_path)  # so the default plot.png lands in tmp, not the repo
    result = runner.invoke(
        app, ["query", 'SELECT t_ns, "linear.x" FROM cmd_vel', str(ros1_bag), "--plot"]
    )
    assert result.exit_code == 0, result.output
    default = tmp_path / "plot.png"
    assert default.exists()
    assert os.path.getsize(default) > 0


def test_query_plot_no_numeric_columns_errors(ros1_bag: Path) -> None:
    """``--plot`` on a no-numeric result exits non-zero (nothing-to-plot ValueError propagates)."""
    result = runner.invoke(
        app, ["query", "SELECT topic FROM cmd_vel", str(ros1_bag), "--plot", "x.png"]
    )
    assert result.exit_code != 0


def test_help_lists_plot_option() -> None:
    """``bagq query --help`` lists the ``--plot`` option on the query command."""
    result = runner.invoke(app, ["query", "--help"])
    assert result.exit_code == 0
    assert "--plot" in result.stdout
