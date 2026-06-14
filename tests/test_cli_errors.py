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

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    write_def_less_bag,
    write_ros1_bag,
    write_ros2_sqlite_bag_defless,
)

import bagq.cli as cli  # noqa: E402
from bagq.cli import app  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for the error-path tests."""
    return write_ros1_bag(tmp_path_factory.mktemp("cli_errors_bag"))


@pytest.fixture(scope="session")
def def_less_bag(tmp_path_factory) -> Path:
    """A ROS 2 sqlite bag with its message_definitions stripped (CLI-04 trigger).

    Opening it with no ``default_typestore`` raises the "no type definitions"
    ``AnyReaderError`` at ``open()``, which the reader wraps to ``UnresolvedTypeError``.
    """
    return write_def_less_bag(tmp_path_factory.mktemp("def_less"))


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


# ---------------------------------------------------------------------------
# 07-02 — the three teaching errors presented through the widened wrapper
# ---------------------------------------------------------------------------


def test_unknown_table_did_you_mean_suggestion(ros1_bag: Path) -> None:
    """CLI-02: a near-miss table name prints a difflib did-you-mean + exits 1.

    ``cmdvel`` is one edit from the real ``cmd_vel`` table (difflib cutoff 0.6 hits), so
    the message must suggest it rather than only listing the available tables.
    """
    result = runner.invoke(app, ["query", "SELECT * FROM cmdvel", str(ros1_bag)])
    assert result.exit_code == 1
    # A clean typer.Exit(1) surfaces to CliRunner as SystemExit (07-RESEARCH §6 / 07-01),
    # NOT None and NOT the raw UnknownTableError — i.e. no domain-error traceback leaked.
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, ValueError)
    assert "Did you mean" in result.output
    assert "cmd_vel" in result.output


def test_unknown_column_lists_table_columns(ros1_bag: Path) -> None:
    """CLI-03: a bad column prints that table's columns + exits 1."""
    result = runner.invoke(app, ["query", "SELECT nonexistent_col FROM cmd_vel", str(ros1_bag)])
    assert result.exit_code == 1
    # Clean Exit(1) -> SystemExit (not None, not the raw UnknownColumnError).
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, ValueError)
    assert "Columns in cmd_vel" in result.output
    assert "nonexistent_col" in result.output


@pytest.mark.parametrize(
    ("command", "extra"),
    [
        ("info", []),
        ("tables", []),
        ("query", ["SELECT * FROM widget"]),
    ],
)
def test_def_less_bag_teaches_registration_for_all_commands(
    def_less_bag: Path, command: str, extra: list[str]
) -> None:
    """CLI-04: info/tables/query each exit 1 with registration guidance, no traceback.

    The error fires at ``reader.open()`` (07-RESEARCH Pitfall 5), so it surfaces
    identically for all three commands; for ``query`` the SQL argument precedes the bag.
    """
    args = [command, *extra, str(def_less_bag)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    # Clean Exit(1) -> SystemExit (not None, not the raw UnresolvedTypeError).
    assert isinstance(result.exception, SystemExit)
    assert not isinstance(result.exception, ValueError)
    assert "register" in result.output
    assert "get_types_from_msg" in result.output


def test_missing_path_still_raises_file_not_found_at_reader() -> None:
    """Pitfall 3: a missing bag path is NOT mislabeled as a type-registration problem.

    The reader wraps ONLY the "no type definitions" ``AnyReaderError``; a missing path
    raises ``FileNotFoundError`` (never even an ``AnyReaderError``), which must propagate
    as itself — proven at the reader boundary (the CLI separately renders it as a clean
    ``Error: ...`` via the wrapper's ``FileNotFoundError`` branch).
    """
    with pytest.raises(FileNotFoundError):
        RosbagsReader("/no/such/bag").open()


# ---------------------------------------------------------------------------
# T1 — a STANDARD def-less bag (real .db3) now opens from every face via the
# reader's env-resolved default-typestore fallback; CUSTOM types still teach.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def std_def_less_bag(tmp_path_factory) -> Path:
    """A ROS 2 sqlite bag with STANDARD types but its definitions stripped (real .db3 shape).

    Opening with no typestore raised the no-defs error before T1; the reader now falls back
    to the env-resolved default typestore (ROS2_HUMBLE), whose standard types DO cover it.
    """
    return write_ros2_sqlite_bag_defless(tmp_path_factory.mktemp("std_def_less"))


def test_reader_opens_standard_def_less_bag_without_explicit_typestore(
    std_def_less_bag: Path,
) -> None:
    """RosbagsReader (no default_typestore) opens a standard def-less bag and reads it (T1)."""
    with RosbagsReader(std_def_less_bag) as reader:
        assert "/imu" in reader.topics
        rows = [m.t_ns for m in reader.read(topics={"/imu"})]
    assert rows == [1_000_000_000, 1_100_000_000, 1_200_000_000]


@pytest.mark.parametrize(
    ("command", "extra"),
    [("info", []), ("tables", []), ("query", ["SELECT t_ns FROM imu"])],
)
def test_bagq_opens_standard_def_less_bag(
    std_def_less_bag: Path, command: str, extra: list[str]
) -> None:
    """bagq info/tables/query now exit 0 on a standard real .db3 (the flagship T1 win)."""
    result = runner.invoke(app, [command, *extra, str(std_def_less_bag)])
    assert result.exit_code == 0, result.output


def test_custom_def_less_bag_still_teaches_via_reader(def_less_bag: Path) -> None:
    """A CUSTOM-type def-less bag still raises UnresolvedTypeError at the reader (CLI-04).

    The fallback typestore does not cover my_pkg/msg/Widget, so the coverage verify trips and
    the teaching error is preserved — even though no typestore was passed.
    """
    from rosbagger_core.errors import UnresolvedTypeError

    with pytest.raises(UnresolvedTypeError):
        RosbagsReader(def_less_bag).open()


def test_failed_open_does_not_leak_fds_or_leave_dangling_reader(def_less_bag: Path) -> None:
    """Repeated failed opens of a custom def-less bag don't accumulate fds (newE19).

    rosbags opens all sub-readers before raising the post-loop no-defs error; the reader now
    force-closes them on every discard path. We assert the Linux fd count is stable across
    many failed opens and that a failed open leaves no dangling _reader (close() is safe).
    """
    from rosbagger_core.errors import UnresolvedTypeError

    fd_dir = Path("/proc/self/fd")
    if not fd_dir.exists():
        pytest.skip("fd-count check needs /proc (Linux)")

    def fd_count() -> int:
        return len(list(fd_dir.iterdir()))

    # Warm up once (first open may cache module/type state that opens its own fds).
    r0 = RosbagsReader(def_less_bag)
    with pytest.raises(UnresolvedTypeError):
        r0.open()
    r0.close()  # safe even though open() failed (idempotent, _reader is None)

    before = fd_count()
    for _ in range(25):
        r = RosbagsReader(def_less_bag)
        with pytest.raises(UnresolvedTypeError):
            r.open()
        r.close()
    after = fd_count()
    # Allow a tiny slack for unrelated runtime fds; a real leak would be ~25-50+.
    assert after - before <= 2, f"fd leak: {before} -> {after}"
