"""bagq CLI entry point.

Defines the typer application bound to the symbol ``app`` so the console-script
``bagq = "bagq.cli:app"`` resolves. Phase 1 shipped a minimal runnable surface
(``bagq --help`` / ``bagq --version``); Phase 4 adds the first real subcommand,
``bagq info`` (the Inspect overview).

Keep this module light: import only typer/rich at top level — do NOT import
rosbagger-core's heavy stack (``rosbags``/``pyarrow``) here. The ``info`` command
imports the core inspect API LAZILY inside its body, so ``bagq --help`` stays
fast and pays no ``rosbags`` import cost (offline-guard discipline).

Per design decision 1 (API-first), all computation lives in
``rosbagger_core.inspect``; this module only renders the returned dataclasses.
The lone presentation-side arithmetic is byte -> human-readable size formatting,
which is deliberately a CLI concern (the API keeps ``size_bytes`` raw).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bagq import __version__

app = typer.Typer(
    add_completion=False,
    help="bagq — query ROS 1 / ROS 2 / MCAP bags with SQL. No ROS install required.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"bagq {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the bagq version and exit.",
    ),
) -> None:
    """bagq command-line interface."""


def _human_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB / GB / TB).

    Presentation-only (the inspect API keeps ``size_bytes`` raw — Open Q2).
    Uses 1024-based units; whole bytes print without a decimal, larger units
    print one decimal (e.g. ``9.2 KB``, ``29.3 KB``, ``1.5 MB``).
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"  # pragma: no cover - unreachable (GB branch returns first)


def _render_bag_info(info, console: Console | None = None) -> None:
    """Render a ``BagInfo`` as a rich topic table plus a whole-bag footer line.

    Columns: topic, msgtype, count (right-justified), Hz (right-justified). A
    ``None`` msgtype (multi-msgtype topic) renders as ``<mixed>``; a ``None`` Hz
    (empty/zero-duration bag) renders as ``—``. The footer summarizes duration
    (seconds, or ``—`` when None), message count, and human-readable size.
    """
    console = console or Console()
    table = Table(title="Bag overview")
    table.add_column("topic")
    table.add_column("msgtype")
    table.add_column("count", justify="right")
    table.add_column("Hz", justify="right")
    for ti in info.topics:
        hz = f"{ti.hz:.1f}" if ti.hz is not None else "—"
        table.add_row(ti.topic, ti.msgtype or "<mixed>", str(ti.count), hz)
    console.print(table)

    duration = f"{info.duration_ns / 1e9:.2f}s" if info.duration_ns is not None else "—"
    console.print(
        f"duration: {duration} · {info.message_count} messages · {_human_size(info.size_bytes)}"
    )


@app.command()
def info(
    bags: Annotated[
        list[Path],
        typer.Argument(help="One or more bag paths (file or directory)."),
    ],
) -> None:
    """List each topic's message type, count, and approximate Hz, plus duration and size."""
    # Import the core API lazily (inside the body) so module import stays light
    # and `bagq --help` pays no rosbags import cost.
    from rosbagger_core.inspect import collect_bag_info
    from rosbagger_core.reader import RosbagsReader

    # AnyReaderError / FileNotFoundError propagate unchanged — Phase 7 owns
    # turning them into teaching error messages.
    with RosbagsReader(bags) as reader:
        bag_info = collect_bag_info(reader)
    _render_bag_info(bag_info)


if __name__ == "__main__":  # pragma: no cover
    app()
