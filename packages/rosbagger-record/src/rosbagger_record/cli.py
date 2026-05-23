"""The thin ``rosbagger-record`` CLI — discover live topics + record a subset (D-02).

The console-script target ``rosbagger-record = "rosbagger_record.cli:app"`` (declared
in Plan 01's ``pyproject.toml``). Mirrors ``bagq/cli.py`` discipline: a ``typer.Typer``
app whose command bodies LAZY-import the package API, so ``rosbagger-record --help``
stays fast and — crucially — the module's TOP LEVEL pulls NO ``rclpy`` / ``rosbag2_py``
(it imports only ``__future__`` + stdlib ``enum`` + ``typing`` + ``typer``). The ROS
import only happens when a command actually runs, behind the package's lazy
``_require_ros()`` boundary (D-03/D-11).

THIN BY DESIGN (API-first, D-02): this module parses CLI args and calls the
``rosbagger_record`` package API (``list_topics`` / ``record``). It contains NO recording
logic, NO ``rclpy`` calls, NO ``SequentialWriter`` / ``create_subscription`` /
``get_topic_names_and_types`` — all of that lives in ``record.py``. The Phase-14 GUI
Record panel is the OTHER thin face over the same API. ``rosbagger-record`` is a SEPARATE
console script, NEVER a ``bagq`` subcommand, so ``bagq``'s import graph stays 100% offline
(``tests/test_offline_guard.py`` regression-locks that no ``rosbagger_record`` leaks into
``bagq``).

CAPABILITY ERRORS PRESENT CLEANLY (no traceback): the package's teaching capability
errors — :class:`~rosbagger_record.errors.RosNotAvailableError` ("source your ROS 2
environment") and :class:`~rosbagger_record.errors.McapStorageUnavailableError` (the
storage plugin is not registered) — are caught by :func:`_capability_errors` and printed
as a single red stderr line + ``Exit(1)``, mirroring ``bagq``'s ``teaching_errors``
mechanism. A genuine programming bug still surfaces as a traceback (no bare
``except Exception``).
"""

from __future__ import annotations

import enum
import functools
from typing import Annotated

import typer

app = typer.Typer(
    add_completion=False,
    help=(
        "rosbagger-record — discover live ROS 2 topics and record a selected subset "
        "to a bag. Requires a sourced ROS 2 environment."
    ),
    no_args_is_help=True,
)


class Storage(str, enum.Enum):
    """The storage backends ``--storage`` accepts — a PARSE-TIME-CONSTRAINED choice (W2/T-12-02).

    A ``str`` Enum so typer renders ``--storage`` as a ``[mcap|sqlite3]`` choice and
    REJECTS any other value at PARSE time (before any ROS work), making the trust-boundary
    claim of the threat model real — the option is NOT a bare ``str``. ``mcap`` is the
    preferred default (D-08, not weakened); ``sqlite3`` is the capability escape (D-08
    refined) for boxes where the MCAP rosbag2 storage plugin is not installed. Subclassing
    ``str`` lets the member be passed straight to ``record(storage=...)`` as its ``.value``
    string.
    """

    MCAP = "mcap"
    SQLITE3 = "sqlite3"


def _capability_errors(fn):
    """Wrap a command body: turn the KNOWN capability errors into a clean line + ``Exit(1)``.

    The ``rosbagger-record`` analog of ``bagq``'s ``teaching_errors`` (CLI-01 mechanism):
    a command that raises one of the expected, data-carrying CAPABILITY errors prints a
    single teaching line to stderr and exits non-zero — never a Python traceback (the
    difference between a tool and a script).

    Catches ONLY the known capability set: :class:`RosNotAvailableError` (ROS 2 not
    sourced — its message points the user at ``source /opt/ros/humble/setup.bash``),
    :class:`McapStorageUnavailableError` (the requested storage plugin is unregistered —
    its message names the registered writers + the install / ``--storage sqlite3``
    remedy), and :class:`NoTopicsMatchedError` (the topic selection matched nothing live
    — the day-one mistake of a mistyped or unpublished topic; its message names what is
    discoverable + the ``rosbagger-record list`` / ``--all`` remedy, WR-04). A bare
    ``except Exception`` is deliberately NOT used: a genuine programming bug must still
    surface as a traceback so it can be diagnosed.

    The errors are imported LAZILY inside the wrapper so ``cli.py``'s top level stays
    typer-only (offline-guard discipline); ``errors.py`` is stdlib-only, so this import
    pulls no ROS until a wrapped command actually runs.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object):
        # Lazy import — keeps cli.py top level ROS-free (offline invariant). errors.py is
        # stdlib-only, so importing it binds no rclpy/rosbag2_py.
        from rosbagger_record.errors import (
            McapStorageUnavailableError,
            NoTopicsMatchedError,
            RosNotAvailableError,
        )

        try:
            return fn(*args, **kwargs)
        except (
            RosNotAvailableError,
            McapStorageUnavailableError,
            NoTopicsMatchedError,
        ) as e:
            # Each carries its own teaching message (source ROS / install the storage
            # plugin or use --storage sqlite3 / `rosbagger-record list` or --all for an
            # empty selection). Present cleanly with no traceback.
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
        # NOTE: NO `except Exception` — real bugs (KeyError/AttributeError/…) must still
        # traceback. WR-04: record()'s empty-selection failure is now a typed
        # NoTopicsMatchedError (caught above), so the most common day-one mistake — a
        # mistyped/unpublished topic — prints one clean teaching line instead of a raw
        # ValueError traceback, matching bagq's UnknownTableError discipline.

    return wrapper


@app.command(name="list")
@_capability_errors
def list_cmd() -> None:
    """List currently discoverable live topics + their types, then exit (SC1, D-06).

    Discovers every topic currently published on the ROS graph (after a brief DDS settle)
    and prints one ``topic    type`` line per topic, sorted by topic name. An empty graph
    prints a single "no topics discovered" line rather than nothing. Thin verb over
    ``rosbagger_record.list_topics`` (API-first, D-02) — the CLI does no discovery itself.
    """
    # Lazy package-API import (offline invariant): the front-door function goes through
    # _require_ros() first (clean RosNotAvailableError if ROS is absent, caught by
    # @_capability_errors) then does the heavy rclpy work in record.py. We import the
    # submodule-shadow-proof alias (`list_record_topics`) so the call resolves to the
    # FUNCTION even if `rosbagger_record.record` (the submodule) was imported earlier in
    # the process (which rebinds the bare `record` attribute to the module).
    from rosbagger_record import list_record_topics as list_topics

    discovered = list_topics()
    if not discovered:
        typer.echo("no topics discovered")
        return
    for topic in sorted(discovered):
        typer.echo(f"{topic}\t{discovered[topic]}")


@app.command()
@_capability_errors
def record(
    topics: Annotated[
        list[str] | None,
        typer.Argument(
            help="Topics to record (space-separated). Omit and pass --all to record everything.",
        ),
    ] = None,
    out: Annotated[
        str,
        typer.Option("-o", "--output", help="Output bag path."),
    ] = ...,  # type: ignore[assignment]  # required option (typer reads the Ellipsis default)
    all_topics: Annotated[
        bool,
        typer.Option("--all", help="Record every currently-published topic."),
    ] = False,
    regex: Annotated[
        str | None,
        typer.Option("--regex", help="Include only topics whose name matches this pattern."),
    ] = None,
    exclude: Annotated[
        str | None,
        typer.Option("--exclude", help="Exclude topics whose name matches this pattern."),
    ] = None,
    storage: Annotated[
        Storage,
        typer.Option(
            "--storage",
            help="Bag storage backend (mcap default; sqlite3 escape where mcap is absent).",
            case_sensitive=False,
        ),
    ] = Storage.MCAP,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="Stop after this many seconds (bounded record)."),
    ] = None,
    max_messages: Annotated[
        int | None,
        typer.Option("--max-messages", help="Stop after capturing this many messages."),
    ] = None,
) -> None:
    """Record a selected subset of live topics to a bag (SC2, D-07/D-08/D-09).

    Selection (D-07): pass positional topic names, or ``--all`` to record everything
    currently published; ``--regex`` keeps only matching names and ``--exclude`` drops
    matching ones (precedence: base set → regex include → exclude). The output goes to
    ``-o OUT`` in ``--storage`` format — ``mcap`` by default (D-08), ``sqlite3`` as the
    capability escape where the MCAP plugin is not installed. Recording runs until
    Ctrl-C (graceful finalize so the bag re-opens), or stops early at ``--duration``
    seconds / ``--max-messages`` (D-09 — the bounded mode the live test relies on).

    Thin verb over ``rosbagger_record.record`` (API-first, D-02): it forwards the parsed
    flags and prints the captured count. ``record()`` is the single orchestrator of
    discover→select→record; the CLI re-implements none of it.
    """
    # Lazy package-API import (offline invariant): the front-door function goes through
    # _require_ros() (clean RosNotAvailableError if ROS is absent). The storage gate
    # (McapStorageUnavailableError) and the empty-selection NoTopicsMatchedError surface
    # from it too; all three capability errors are caught by @_capability_errors and
    # printed as one clean line + Exit(1), no traceback (WR-04). We import
    # the submodule-shadow-proof alias (`record_topics`) so this resolves to the FUNCTION
    # even when `rosbagger_record.record` (the submodule) was imported earlier in the
    # process — `from rosbagger_record import record` would otherwise yield the MODULE.
    from rosbagger_record import record_topics as record_api

    n = record_api(
        list(topics or []),
        out,
        all_topics=all_topics,
        regex=regex,
        exclude=exclude,
        storage=storage.value,
        duration=duration,
        max_messages=max_messages,
    )
    typer.echo(f"Recorded {n} messages to {out} ({storage.value})")


if __name__ == "__main__":  # pragma: no cover
    app()
