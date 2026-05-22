"""Teaching-error tests for the ``bagq`` CLI (CLI-01 clean-exit mechanism).

These prove the shared ``teaching_errors`` wrapper turns the KNOWN typed errors into a
clean one-line message + ``exit 1`` (NO Python traceback), while a genuine programming
bug (an unexpected ``KeyError``) is NOT swallowed — it still surfaces as an exception
(06-RESEARCH Pitfall 4). A real-shell ``subprocess.run`` smoke proves ``bagq query`` runs
end-to-end with exit 0 (CLI-01), guarding the WR-02 CSV path past CliRunner.

CliRunner note (06-RESEARCH §6): this typer/click version exposes no ``mix_stderr``
kwarg, and ``err=True`` output lands in ``result.output`` — so teaching-error assertions
read ``result.output`` (not a separate stderr stream).

LOCAL-RUN REQUIREMENT (07-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_cli_errors.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override (the
subprocess smoke passes ``PYTHONPATH=""`` explicitly so it is correct on both).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# `tools` is a dev-only repo-root package; put the repo root on sys.path here,
# scoped to this file (mirrors tests/test_cli_query.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

import bagq.cli as cli  # noqa: E402
from bagq.cli import app  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for the error-path tests."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_errors_bag"))


def test_unknown_table_exits_one_with_clean_message(ros1_bag: Path) -> None:
    """An unknown table prints a non-empty message + exits 1 with NO traceback (CLI-01).

    Today (pre-fix) this exits 1 with EMPTY output and an uncaught ``UnknownTableError``
    (a raw traceback in a real shell). The ``teaching_errors`` wrapper must catch it,
    print cleanly via ``typer.secho(err=True)``, and ``raise typer.Exit(1)``.
    """
    result = runner.invoke(app, ["query", "SELECT * FROM nonexistent", str(ros1_bag)])
    assert result.exit_code == 1
    assert result.output.strip()  # a non-empty teaching message (not blank)
    # A clean ``typer.Exit(1)`` surfaces to CliRunner as ``SystemExit`` (07-RESEARCH §6),
    # NOT the raw ``UnknownTableError`` — i.e. no domain-error traceback leaked. (Contrast
    # the KeyError test below, where the exception IS the raw KeyError.)
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, ValueError)  # UnknownTableError did not escape
    assert "nonexistent" in result.output  # the offending name is echoed back


def test_real_bug_keyerror_is_not_swallowed(ros1_bag: Path, monkeypatch) -> None:
    """A genuine ``KeyError`` from the query path is NOT converted to a clean Exit(1).

    06-RESEARCH Pitfall 4: the wrapper catches ONLY the known typed set — real bugs must
    still surface (a traceback), never be masked as "Error: ... exit 1". We monkeypatch
    the lazily-imported ``run_query`` symbol to raise ``KeyError`` and assert the wrapper
    let it through (CliRunner re-raises it as ``result.exception``).
    """

    def _boom(*_args, **_kwargs):
        raise KeyError("simulated internal bug")

    # cli.query imports `query as run_query` from rosbagger_core.backend.query inside its
    # body; patch it at the source module so the lazy import binds the boom.
    import rosbagger_core.backend.query as qmod

    monkeypatch.setattr(qmod, "query", _boom)

    result = runner.invoke(app, ["query", "SELECT * FROM cmd_vel", str(ros1_bag)])
    # The wrapper must NOT have turned this into a clean Exit(1): either a non-1 exit
    # code or a surfaced exception proves the KeyError was not swallowed.
    assert result.exit_code != 1 or result.exception is not None
    assert isinstance(result.exception, KeyError)


def test_query_real_shell_smoke_exits_zero(ros1_bag: Path) -> None:
    """A REAL shell ``python -m bagq query "<SQL>" BAG`` returns 0 with a row (CLI-01).

    Not CliRunner — an actual subprocess, so this guards the end-to-end console path
    (and the WR-02 CSV route, which CliRunner could not observe via ``/dev/stdout``).
    ``PYTHONPATH=""`` neutralizes this host's ROS-on-PYTHONPATH leak.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "bagq", "query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert "/cmd_vel" in proc.stdout  # a real row in real stdout


def test_teaching_errors_wrapper_is_applied_to_all_three_commands() -> None:
    """``info``/``tables``/``query`` are all wrapped (the shared mechanism, not per-command).

    ``functools.wraps`` preserves ``__wrapped__`` on the decorated callable; assert it is
    present on each command's registered callback so 07-02 can widen ONE catch site.
    """
    for name in ("info", "tables", "query"):
        fn = getattr(cli, name)
        assert hasattr(fn, "__wrapped__"), f"{name} is not wrapped by teaching_errors"
