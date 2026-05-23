"""CliRunner smoke tests for the ``bagq events add`` / ``bagq events list`` verbs (D-02).

These prove the THIN events verbs wire the Phase 11 ``rosbagger_core.events`` sidecar
API (``add_event`` / ``list_events``) to the typer surface and exit 0 — the CLI itself
builds no sidecar I/O. The load-bearing assertion is the CLI ROUND-TRIP (SC2 surfaced at
the CLI): ``bagq events add SRC ...`` then ``bagq events list SRC`` shows the added event.
A point event (``--start == --end``) and the no-sidecar "no events" path are covered too.
Rich box-drawing / whitespace is never asserted — only the stable label text.

Each test writes the sidecar next to a FRESH per-test bag (a function-scoped fixture in a
fresh ``tmp_path``), so a written ``<bag>.events.parquet`` never leaks across tests.

LOCAL-RUN REQUIREMENT (11-RESEARCH): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_events.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_edit.py / tests/test_cli_query.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from bagq.cli import app  # noqa: E402

runner = CliRunner()


@pytest.fixture
def bag(tmp_path: Path) -> Path:
    """A fresh ROS 1 fixture bag per test (so a written sidecar never leaks)."""
    return write_ros1_bag(tmp_path / "events_bag")


def test_events_add_then_list_round_trips(bag: Path) -> None:
    """``bagq events add`` then ``bagq events list`` round-trips the event (SC2 at the CLI)."""
    add = runner.invoke(
        app,
        [
            "events",
            "add",
            str(bag),
            "--start",
            "1.0",
            "--end",
            "1.1",
            "--label",
            "turn",
            "--note",
            "left",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "turn" in add.stdout  # the confirmation line names the label

    lst = runner.invoke(app, ["events", "list", str(bag)])
    assert lst.exit_code == 0, lst.output
    assert "turn" in lst.stdout  # the added event is read back (the round-trip)


def test_events_add_point_event_round_trips(bag: Path) -> None:
    """A point event (``--start == --end``) also round-trips through add -> list."""
    add = runner.invoke(
        app,
        ["events", "add", str(bag), "--start", "1.0", "--end", "1.0", "--label", "mark"],
    )
    assert add.exit_code == 0, add.output

    lst = runner.invoke(app, ["events", "list", str(bag)])
    assert lst.exit_code == 0, lst.output
    assert "mark" in lst.stdout


def test_events_list_no_sidecar_prints_no_events(bag: Path) -> None:
    """``bagq events list`` on a bag with NO sidecar exits 0 and prints "no events"."""
    lst = runner.invoke(app, ["events", "list", str(bag)])  # no add first
    assert lst.exit_code == 0, lst.output
    assert "no events" in lst.stdout


def test_events_add_appends_second_event(bag: Path) -> None:
    """A second ``events add`` appends — ``events list`` then shows BOTH labels."""
    runner.invoke(
        app, ["events", "add", str(bag), "--start", "1.0", "--end", "1.1", "--label", "first"]
    )
    runner.invoke(
        app, ["events", "add", str(bag), "--start", "1.2", "--end", "1.3", "--label", "second"]
    )

    lst = runner.invoke(app, ["events", "list", str(bag)])
    assert lst.exit_code == 0, lst.output
    assert "first" in lst.stdout
    assert "second" in lst.stdout


def test_events_in_help() -> None:
    """``bagq --help`` lists the ``events`` sub-command group (the surface is wired)."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "events" in result.stdout
