"""CliRunner smoke tests for the ``bagq edit`` / ``bagq convert`` subcommands (D-02).

These prove the THIN CLI verbs wire the Phase 11 ``rosbagger_core.edit`` API
(``edit_bag`` / ``EditOps``) to the typer surface and exit 0 — the CLI itself
builds no edit/convert logic. They assert only stable behavior: the output bag
re-opens (and, for the cross-format convert, DESERIALIZES — the SC1 contract via
the CLI), the dropped topic is gone, ``--drop`` + ``--keep`` together is rejected,
and a malformed ``--downsample`` / an overwrite attempt surface a clean non-zero
exit (no traceback). Rich box-drawing/whitespace is never asserted.

LOCAL-RUN REQUIREMENT (11-RESEARCH): this dev host sources ROS 2 onto
``PYTHONPATH``; run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_edit.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_query.py / tests/test_cli_tables.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    write_ros1_bag,
    write_ros2_sqlite_bag,
)

from bagq.cli import app  # noqa: E402

runner = CliRunner()

EXPECTED_TOPICS = {"/cmd_vel", "/imu", "/image"}


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for the edit/convert CLI."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_edit_ros1"))


@pytest.fixture(scope="session")
def ros2_bag(tmp_path_factory) -> Path:
    """A single ROS 2 sqlite3 fixture bag for the convert-to-ROS1 CLI direction."""
    return write_ros2_sqlite_bag(tmp_path_factory.mktemp("cli_edit_ros2"))


def _topics_via_anyreader(out: Path) -> set[str]:
    """Re-open ``out`` and return its topic set (a re-openability smoke check)."""
    from rosbags.highlevel import AnyReader

    with AnyReader([out]) as reader:
        return {c.topic for c in reader.connections}


def _deserialize_all(out: Path) -> dict[str, int]:
    """Re-open ``out`` and DESERIALIZE every message; return per-topic counts (SC1)."""
    from rosbags.highlevel import AnyReader

    counts: dict[str, int] = {}
    with AnyReader([out]) as reader:
        for connection, _t_ns, rawdata in reader.messages():
            msg = reader.deserialize(rawdata, connection.msgtype)
            assert msg is not None
            counts[connection.topic] = counts.get(connection.topic, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# bagq edit: --drop removes the named topic; the output re-opens (D-07)
# ---------------------------------------------------------------------------


def test_edit_drop_topic_exits_zero_and_drops(ros1_bag: Path, tmp_path: Path) -> None:
    """``bagq edit SRC -o OUT --drop /image`` exits 0 and OUT has no /image."""
    out = tmp_path / "edited.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--drop", "/image"])
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.stdout  # the count line (Open Q2)
    assert _topics_via_anyreader(out) == {"/cmd_vel", "/imu"}  # /image dropped


def test_edit_downsample_exits_zero(ros1_bag: Path, tmp_path: Path) -> None:
    """``bagq edit ... --downsample /imu:2`` exits 0 and keeps 2 of 3 /imu messages."""
    out = tmp_path / "ds.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--downsample", "/imu:2"])
    assert result.exit_code == 0, result.output
    counts = _deserialize_all(out)
    assert counts["/imu"] == 2  # 0th + 2nd survive every-2nd
    assert counts["/cmd_vel"] == 3  # untouched


def test_edit_trim_exits_zero(ros1_bag: Path, tmp_path: Path) -> None:
    """``bagq edit ... --trim 0.0 0.1`` exits 0 and keeps the first 2 messages/topic."""
    out = tmp_path / "trimmed.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--trim", "0.0", "0.1"])
    assert result.exit_code == 0, result.output
    counts = _deserialize_all(out)
    for topic in EXPECTED_TOPICS:
        assert counts[topic] == 2


# ---------------------------------------------------------------------------
# bagq convert: cross-format ROS1 -> ROS2 via the CLI; deserialize (SC1)
# ---------------------------------------------------------------------------


def test_convert_ros1_to_ros2_exits_zero_and_deserializes(ros1_bag: Path, tmp_path: Path) -> None:
    """``bagq convert ROS1 -o ROS2_DIR`` exits 0; OUT re-opens AND deserializes (SC1)."""
    out = tmp_path / "converted_ros2"  # directory dst -> ROS 2 sqlite3
    result = runner.invoke(app, ["convert", str(ros1_bag), "-o", str(out)])
    assert result.exit_code == 0, result.output
    counts = _deserialize_all(out)  # the headered /imu + /image MUST deserialize
    assert set(counts) == EXPECTED_TOPICS
    assert all(counts[t] == 3 for t in EXPECTED_TOPICS)


def test_convert_ros2_to_ros1_exits_zero_and_deserializes(ros2_bag: Path, tmp_path: Path) -> None:
    """``bagq convert ROS2 -o OUT.bag`` exits 0; the seq-field direction deserializes."""
    out = tmp_path / "converted.bag"
    result = runner.invoke(app, ["convert", str(ros2_bag), "-o", str(out)])
    assert result.exit_code == 0, result.output
    counts = _deserialize_all(out)
    assert set(counts) == EXPECTED_TOPICS


def test_convert_format_override_to_mcap(ros1_bag: Path, tmp_path: Path) -> None:
    """``bagq convert ... --format mcap`` exits 0 and writes an MCAP bag (deserializes)."""
    out = tmp_path / "as_mcap"  # no .mcap suffix; --format wins
    result = runner.invoke(app, ["convert", str(ros1_bag), "-o", str(out), "--format", "mcap"])
    assert result.exit_code == 0, result.output
    assert any(p.suffix == ".mcap" for p in out.iterdir())
    assert set(_deserialize_all(out)) == EXPECTED_TOPICS


# ---------------------------------------------------------------------------
# rejections: --drop+--keep together, malformed --downsample, overwrite (D-05/07)
# ---------------------------------------------------------------------------


def test_edit_drop_and_keep_together_rejected(ros1_bag: Path, tmp_path: Path) -> None:
    """``--drop`` + ``--keep`` together exits non-zero (BadParameter); no bag written."""
    out = tmp_path / "rejected.bag"
    result = runner.invoke(
        app,
        ["edit", str(ros1_bag), "-o", str(out), "--drop", "/image", "--keep", "/cmd_vel"],
    )
    assert result.exit_code != 0  # BadParameter -> non-zero exit
    assert not out.exists()  # nothing written on the rejected invocation


def test_edit_malformed_downsample_rejected(ros1_bag: Path, tmp_path: Path) -> None:
    """A ``--downsample`` without ``:N`` exits non-zero (clean BadParameter)."""
    out = tmp_path / "bad_ds.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--downsample", "/imu"])
    assert result.exit_code != 0
    assert not out.exists()


def test_edit_refuses_to_overwrite_input(ros1_bag: Path) -> None:
    """Pointing ``-o`` at the input bag exits non-zero (D-05; core ValueError mapped)."""
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(ros1_bag)])
    assert result.exit_code != 0  # overwrite refused -> BadParameter, no traceback


def test_edit_existing_output_clean_exit_no_traceback(ros1_bag: Path, tmp_path: Path) -> None:
    """WR-01: ``-o`` at an EXISTING (non-input) path exits cleanly — no WriterError traceback.

    Re-running an edit onto a path that already exists is an extremely common mistake.
    rosbags' Writer raises its own ``WriterError`` (not a ValueError) which the CLI's
    ``except ValueError`` would miss, dumping a raw traceback. The fix rewords it to a
    clean ValueError -> BadParameter: the exit is non-zero and the captured exception is
    Click's controlled ``SystemExit`` (a clean message), NEVER the raw ``WriterError``.
    """
    out = tmp_path / "already_there.bag"
    out.write_bytes(b"")  # the output path exists before the edit runs
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out)])
    assert result.exit_code != 0
    # No raw traceback: a clean BadParameter surfaces as a controlled SystemExit, not the
    # library's WriterError. (CliRunner sets .exception to the controlled SystemExit.)
    assert isinstance(result.exception, SystemExit)
    assert type(result.exception).__name__ != "WriterError"


def test_convert_existing_output_clean_exit_no_traceback(ros1_bag: Path, tmp_path: Path) -> None:
    """WR-01 (convert verb): an existing ``-o`` path also exits cleanly (no traceback)."""
    out = tmp_path / "convert_exists"  # ROS 2 dir dst that already exists
    out.mkdir()
    result = runner.invoke(app, ["convert", str(ros1_bag), "-o", str(out)])
    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)
    assert type(result.exception).__name__ != "WriterError"


def test_edit_backwards_trim_clean_exit(ros1_bag: Path, tmp_path: Path) -> None:
    """WR-02: a backwards ``--trim 5 1`` exits cleanly non-zero, writing no bag.

    A transposed trim window would otherwise be accepted and silently produce an empty
    output. The core EditOps rejects start > end with a ValueError, which the CLI maps to
    a clean BadParameter (controlled SystemExit, no traceback) and no bag is written.
    """
    out = tmp_path / "backwards.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--trim", "5", "1"])
    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)  # clean, not a raw traceback
    assert not out.exists()  # nothing written on the rejected invocation


def test_edit_contradictory_format_suffix_clean_exit(ros1_bag: Path, tmp_path: Path) -> None:
    """WR-03: ``--format sqlite3`` with a ``.bag`` ``-o`` exits cleanly, writing nothing.

    The contradiction would otherwise write a ROS 2 directory named ``out.bag/`` that
    cannot be re-opened. The core ValueError maps to a clean BadParameter and no bag is
    produced.
    """
    out = tmp_path / "contradiction.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--format", "sqlite3"])
    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)
    assert not out.exists()


# ---------------------------------------------------------------------------
# both verbs registered (CLI surface)
# ---------------------------------------------------------------------------


def test_edit_and_convert_in_help() -> None:
    """Both ``edit`` and ``convert`` appear in ``bagq --help`` (registered verbs)."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "edit" in result.stdout
    assert "convert" in result.stdout


# ---------------------------------------------------------------------------
# T3 — `bagq edit --keep cmd_vel` (no slash) keeps /cmd_vel, not an empty bag;
# a typo exits non-zero with a did-you-mean (no silent "Wrote (0 messages)").
# ---------------------------------------------------------------------------


def test_edit_keep_without_leading_slash_keeps_topic(ros1_bag: Path, tmp_path: Path) -> None:
    """`bagq edit SRC -o OUT --keep cmd_vel` exits 0 and writes 3 messages, not 0.

    Regression guard for the no-leading-slash data-loss fix.
    """
    out = tmp_path / "kept.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--keep", "cmd_vel"])
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output
    assert "(0 messages)" not in result.output  # the data-loss symptom must be gone


def test_edit_keep_typo_is_clean_error_with_suggestion(ros1_bag: Path, tmp_path: Path) -> None:
    """A misspelled --keep topic exits non-zero with a did-you-mean and writes no bag."""
    out = tmp_path / "typo.bag"
    result = runner.invoke(app, ["edit", str(ros1_bag), "-o", str(out), "--keep", "cmdvel"])
    assert result.exit_code != 0
    assert not isinstance(result.exception, AttributeError)  # no raw traceback
    flat = result.output.replace("\n", " ")
    assert "cmd_vel" in flat  # the suggestion / available topic
    assert not out.exists()  # nothing written on the error path
