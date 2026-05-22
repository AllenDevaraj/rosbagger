"""CliRunner smoke tests for the ``bagq info`` subcommand (INSP-01 / INSP-02).

These prove the thin CLI wires the core inspect API to a rich-rendered table +
footer and exits 0 — WITHOUT asserting exact rich box-drawing/whitespace (only
the stable data: topic names, msgtype strings, the count). They also exercise
the render branches the host-coverage note calls out — the empty-bag ``—``
duration/Hz path and the byte -> human-readable size formatting — so the
``--cov=bagq`` gate is met by exercising real behavior, not by weakening it.

LOCAL-RUN REQUIREMENT (04-RESEARCH.md): this dev host sources ROS 2 Humble onto
``PYTHONPATH``; run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_info.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_reader.py / tests/test_inspect_info.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from bagq.cli import _human_size, _render_bag_info, app  # noqa: E402

runner = CliRunner()

EXPECTED_TOPICS = ("/cmd_vel", "/imu", "/image")
EXPECTED_MSGTYPES = (
    "geometry_msgs/msg/Twist",
    "sensor_msgs/msg/Imu",
    "sensor_msgs/msg/Image",
)


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (9 messages, 3 topics) for the CLI to inspect."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_info_bag"))


def test_info_exits_zero_and_shows_topics_types_counts(ros1_bag: Path) -> None:
    """``bagq info BAG`` exits 0 and prints the three topics, msgtypes, and count 3.

    Asserts only stable data (INSP-01) — never rich box-drawing/whitespace. rich
    may wrap long msgtype cells, so we assert on the topic short-names and the
    msgtype trailing segments that survive wrapping.
    """
    result = runner.invoke(app, ["info", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    for topic in ("cmd_vel", "imu", "image"):
        assert topic in out
    for msgtype in EXPECTED_MSGTYPES:
        # rich may insert a soft-wrap; assert the type's leaf name is present.
        leaf = msgtype.rsplit("/", 1)[-1]
        assert leaf in out
    assert "3" in out  # per-topic count


def test_info_footer_shows_duration_count_size(ros1_bag: Path) -> None:
    """The footer renders a duration, the message count, and a human-readable size."""
    result = runner.invoke(app, ["info", str(ros1_bag)])
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "duration" in out
    assert "9 messages" in out  # whole-bag count (INSP-02)
    # human-readable size unit appears (ros1.bag is ~9 KB).
    assert "KB" in out or "MB" in out or "B" in out


def test_help_lists_info_subcommand() -> None:
    """``bagq --help`` still works and lists the new ``info`` subcommand."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "info" in result.stdout


def test_info_missing_bag_propagates_error(tmp_path: Path) -> None:
    """A nonexistent bag path surfaces an error (non-zero exit); Phase 7 owns teaching."""
    missing = tmp_path / "does_not_exist.bag"
    result = runner.invoke(app, ["info", str(missing)])
    assert result.exit_code != 0


def test_human_size_formats_units() -> None:
    """``_human_size`` covers the B / KB / MB / GB unit branches (presentation only)."""
    assert _human_size(512) == "512 B"
    assert _human_size(1536) == "1.5 KB"  # 1.5 * 1024
    assert _human_size(5 * 1024 * 1024) == "5.0 MB"
    assert _human_size(3 * 1024 * 1024 * 1024) == "3.0 GB"
    # beyond GB stays in GB (the renderer never exceeds GB for real bags)
    assert _human_size(2048 * 1024 * 1024 * 1024).endswith("GB")


def test_render_empty_bag_uses_em_dash(capsys) -> None:
    """An empty/None-duration BagInfo renders ``—`` for duration and Hz (no crash).

    Uses a minimal stand-in object with the BagInfo/TopicInfo shape so the
    empty-bag render branch is exercised without writing a zero-message bag.
    """
    from dataclasses import dataclass

    @dataclass
    class _TI:
        topic: str
        msgtype: str | None
        count: int
        hz: float | None

    @dataclass
    class _BI:
        topics: list
        message_count: int
        start_time_ns: int | None
        end_time_ns: int | None
        duration_ns: int | None
        size_bytes: int

    empty = _BI(
        topics=[_TI(topic="/mixed", msgtype=None, count=0, hz=None)],
        message_count=0,
        start_time_ns=None,
        end_time_ns=None,
        duration_ns=None,
        size_bytes=0,
    )
    _render_bag_info(empty)
    out = capsys.readouterr().out
    assert "—" in out  # None duration AND None Hz both render as the em dash
    assert "<mixed>" in out  # None msgtype renders as <mixed>
    assert "0 messages" in out
