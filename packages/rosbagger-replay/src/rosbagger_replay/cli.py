"""The thin ``rosbagger-replay`` CLI — publish a bag to live ROS 2 topics (D-02/D-10).

The console-script target ``rosbagger-replay = "rosbagger_replay.cli:app"`` (declared in
Plan 01's ``pyproject.toml``). Mirrors ``rosbagger_record/cli.py`` discipline: a
``typer.Typer`` app whose command body LAZY-imports the package API, so the module's TOP
LEVEL pulls NO ``rclpy`` / ``rosidl_runtime_py`` (it imports only ``__future__`` + stdlib
``functools`` + ``typing`` + ``typer``). The ROS import only happens when the command
actually runs, behind the package's lazy ``_require_ros()`` boundary (D-03/D-12).

THIN BY DESIGN (API-first, D-02): this module parses CLI args and calls the
``rosbagger_replay`` package API (``replay_bag``). It contains NO publish logic, NO
``rclpy`` calls, NO ``create_publisher`` / ``deserialize_message`` — all of that lives in
``replay.py``. The Phase-14 GUI Replay panel is the OTHER thin face over the same API.
``rosbagger-replay`` is a SEPARATE console script, NEVER a ``bagq`` subcommand, so
``bagq``'s import graph stays 100% offline.

CAPABILITY ERRORS PRESENT CLEANLY (no traceback): the package's teaching capability
errors — :class:`~rosbagger_replay.errors.RosNotAvailableError` ("source your ROS 2
environment") and :class:`~rosbagger_replay.errors.NoMessagesToReplayError` (the selection
matched no messages) — are caught by :func:`_capability_errors` and printed as a single
red stderr line + ``Exit(1)``. A genuine programming bug still surfaces as a traceback (no
bare ``except Exception``).

D-10 LOCKED-FLAG ACCOUNTING (W5): D-10 locks the v1 CLI surface as
``--rate`` / ``--loop`` / ``--start``(``--seek``) / ``--topics`` and "optional
--duration/--end". This CLI implements ``--duration`` and FOLDS ``--end`` into it: a
bounded run is expressed as a DURATION (seconds), not an absolute/relative end-timestamp,
because the v1 scheduler's bounded stop is a monotonic-duration / ``max_messages`` gate
(Plan 02), NOT a bag-timestamp horizon — a true ``--end`` would require a ``t_ns``-relative
stop predicate the scheduler does not yet expose. With the materialized-list source,
``--duration`` + ``--max-messages`` fully cover the "stop early" need (the SC tests rely on
exactly this). A true absolute/relative ``--end`` is therefore a DEFERRED ENHANCEMENT
(noted in the ``--duration`` help text), NOT a silent scope reduction — the stop-early
capability ships via ``--duration`` / ``--max-messages``.
"""

from __future__ import annotations

import functools
from typing import Annotated

import typer

app = typer.Typer(
    add_completion=False,
    help=(
        "rosbagger-replay — publish a bag's messages to live ROS 2 topics with transport "
        "controls. Requires a sourced ROS 2 environment."
    ),
    no_args_is_help=True,
)


def _capability_errors(fn):
    """Wrap a command body: turn the KNOWN capability errors into a clean line + ``Exit(1)``.

    Catches ONLY the known capability set: :class:`RosNotAvailableError` (ROS 2 not sourced
    — its message points the user at ``source /opt/ros/humble/setup.bash``) and
    :class:`NoMessagesToReplayError` (the selection matched no messages — the day-one
    mistake of a mistyped or absent ``--topics`` name; its message names the remedy). A
    bare ``except Exception`` is deliberately NOT used: a genuine programming bug must still
    surface as a traceback so it can be diagnosed.

    The errors are imported LAZILY inside the wrapper so ``cli.py``'s top level stays
    typer-only (offline-guard discipline); ``errors.py`` is stdlib-only, so this import
    pulls no ROS until a wrapped command actually runs.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object):
        # Lazy import — keeps cli.py top level ROS-free (offline invariant). errors.py is
        # stdlib-only, so importing it binds no rclpy/rosidl.
        from rosbagger_replay.errors import (
            NoMessagesToReplayError,
            RosNotAvailableError,
        )

        try:
            return fn(*args, **kwargs)
        except (RosNotAvailableError, NoMessagesToReplayError) as e:
            # Each carries its own teaching message (source ROS / check the bag path +
            # --topics). Present cleanly with no traceback.
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
        # NOTE: NO `except Exception` — real bugs (KeyError/AttributeError/…) must still
        # traceback. The empty-selection failure is a typed NoMessagesToReplayError (caught
        # above), so the most common day-one mistake prints one clean teaching line.

    return wrapper


@app.command()
@_capability_errors
def replay(
    bag: Annotated[
        str,
        typer.Argument(help="Bag path to replay (ROS 1 / ROS 2 sqlite3 / MCAP)."),
    ],
    rate: Annotated[
        float,
        typer.Option("--rate", help="Schedule scale: >1 plays faster, <1 slower (D-08)."),
    ] = 1.0,
    loop: Annotated[
        bool,
        typer.Option(
            "--loop",
            help="Restart at end-of-bag (bound with --duration/--max-messages).",
        ),
    ] = False,
    start: Annotated[
        float,
        typer.Option(
            "--start",
            "--seek",
            help="Seek to this many SECONDS into the bag before publishing (D-09/D-10).",
        ),
    ] = 0.0,
    topics: Annotated[
        list[str] | None,
        typer.Option("--topics", help="Publish only this subset of topics (default: all)."),
    ] = None,
    duration: Annotated[
        float | None,
        typer.Option(
            "--duration",
            help=(
                "Stop after N seconds of replay (D-10). NOTE: --end is folded into "
                "--duration for v1 — a true absolute/relative --end is a deferred "
                "enhancement (the scheduler bounds on monotonic duration, not a bag "
                "timestamp horizon)."
            ),
        ),
    ] = None,
    max_messages: Annotated[
        int | None,
        typer.Option("--max-messages", help="Stop after publishing this many messages (D-10)."),
    ] = None,
    clock: Annotated[
        bool,
        typer.Option(
            "--clock",
            help="Publish /clock (rosgraph_msgs/Clock) per message for use_sim_time nodes.",
        ),
    ] = False,
    delay: Annotated[
        float,
        typer.Option(
            "--delay",
            help="Sleep N seconds after building the transport but BEFORE publishing "
            "(lets subscribers discover; ros2 bag play --delay parity).",
        ),
    ] = 0.0,
    remap: Annotated[
        list[str] | None,
        typer.Option(
            "--remap",
            help="Publish a topic under a new name: --remap old:=new (repeatable).",
        ),
    ] = None,
    start_paused: Annotated[
        bool,
        typer.Option(
            "--start-paused",
            "-p",
            help="Begin PAUSED (publish nothing). Non-interactive here — this CLI has no "
            "resume; interactive control is in the GUI.",
        ),
    ] = False,
    region_start: Annotated[
        float | None,
        typer.Option(
            "--region-start",
            help="Play from this many SECONDS in (bounded-region in-point).",
        ),
    ] = None,
    region_end: Annotated[
        float | None,
        typer.Option(
            "--region-end",
            help="Play to this many SECONDS in (region out-point). Requires --region-start. The "
            "[in,out] snippet REPEATS (independent of --loop) until you bound it with "
            "--duration/--max-messages or interrupt (Ctrl-C); a single-pass [in,out] stop is "
            "deferred (see --end/--duration).",
        ),
    ] = None,
) -> None:
    """Replay ``bag`` to live ROS 2 topics with transport controls (REP-01 / SC1).

    Publishes the bag's messages on their original topic names at the sane default QoS.
    ``--rate`` scales the schedule; ``--start``/``--seek`` jumps N seconds in before
    publishing; ``--topics`` limits the published subset; ``--loop`` restarts at
    end-of-bag; ``--duration`` / ``--max-messages`` bound the run (D-10 — the bounded mode
    the live test relies on; ``--end`` is folded into ``--duration`` for v1, see the
    module docstring + the ``--duration`` help).

    Phase-21 parity flags (REP-05): ``--clock`` publishes /clock per message; ``--delay``
    sleeps before publishing; ``--remap old:=new`` (repeatable) publishes a topic under a new
    name; ``--start-paused``/``-p`` begins paused; ``--region-start``/``--region-end`` (seconds)
    bound a snippet region that REPEATS until bounded by ``--duration``/``--max-messages`` (or
    Ctrl-C) — independent of ``--loop`` (which is a no-op while a region is set).

    OUT OF SCOPE (deferred, NOT silently missing — SC3): the runtime ROS playback services
    ``~/seek`` / ``~/set_rate`` / ``~/play_next`` / ``~/burst`` / ``~/toggle_paused`` are not
    exposed — they need a long-lived spinning node, and interactive transport control lives in
    the GUI (rosbagger-desktop). A single-pass ``[in,out]`` region stop is also deferred: the
    region REPEATS with ``--loop`` (the scheduler bounds on monotonic duration / max-messages,
    not a bag-timestamp horizon — the same deferral ``--end``-folded-into-``--duration`` records).

    Thin verb over ``rosbagger_replay.replay_bag`` (API-first, D-02): it forwards the
    parsed flags and prints the published count. ``replay_bag()`` is the single
    orchestrator of load→schedule→publish; the CLI re-implements none of it.
    """
    # Validate flags UP FRONT — clean usage errors (no traceback) before any ROS spin-up.
    # rate<=0 would otherwise reach Replayer.__init__'s ValueError only after rclpy + the
    # node + the publish sink are built (it is not a @_capability_errors type), surfacing as
    # an ugly traceback; --region-end alone was silently dropped (the library acts on the
    # region only when BOTH bounds are present).
    if rate <= 0:
        raise typer.BadParameter("--rate must be > 0", param_hint="--rate")
    if region_end is not None and region_start is None:
        raise typer.BadParameter("--region-end requires --region-start", param_hint="--region-end")
    if region_start is not None and duration is None and max_messages is None:
        typer.secho(
            "Note: a --region-* snippet REPEATS until interrupted (Ctrl-C); bound it with "
            "--duration or --max-messages to stop automatically.",
            fg=typer.colors.YELLOW,
            err=True,
        )

    # Lazy package-API import (offline invariant): the front-door function goes through
    # _require_ros() first (clean RosNotAvailableError if ROS is absent, caught by
    # @_capability_errors) then does the heavy rclpy publish in replay.py. We import the
    # submodule-shadow-proof alias (`replay_bag`) so the call resolves to the FUNCTION even
    # if `rosbagger_replay.replay` (the submodule) was imported earlier in the process
    # (which would rebind the bare `replay` attribute to the module).
    from rosbagger_replay import replay_bag as replay_api

    # Parse --remap old:=new pairs into a dict; a malformed value is a clean usage error
    # (typer.BadParameter -> non-zero exit, no traceback), never a silent accept.
    parsed_remap: dict[str, str] | None = None
    if remap:
        parsed_remap = {}
        for pair in remap:
            old, sep, new = pair.partition(":=")
            if not sep or not old or not new:
                raise typer.BadParameter(f"--remap expects old:=new, got {pair!r}")
            parsed_remap[old] = new

    n = replay_api(
        bag,
        # WR-06: explicit `is not None` (matches the scheduler's is-not-None discipline) — an
        # omitted --topics is None ("publish everything"); a truthiness test would conflate
        # None with an empty selection. Behavior for omitted --topics is unchanged.
        topics=set(topics) if topics is not None else None,
        rate=rate,
        loop=loop,
        start=start,
        duration=duration,
        max_messages=max_messages,
        # Phase-21 parity flags forwarded to the library params (21-01).
        publish_clock=clock,
        delay=delay,
        remap=parsed_remap,
        start_paused=start_paused,
        region_start=region_start,
        region_end=region_end,
    )
    typer.echo(f"Published {n} messages from {bag}")


if __name__ == "__main__":  # pragma: no cover
    app()
