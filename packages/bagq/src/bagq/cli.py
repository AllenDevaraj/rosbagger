"""bagq CLI entry point.

Defines the typer application bound to the symbol ``app`` so the console-script
``bagq = "bagq.cli:app"`` resolves. Phase 1 ships a minimal runnable surface:
``bagq --help`` (typer provides this for a no-command app) and ``bagq --version``.
Real subcommands (``query`` / ``info`` / ``tables``) land in Phase 7.

Keep this module light: import only typer/rich — do NOT import rosbagger-core's
heavy stack here.
"""

import typer

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


if __name__ == "__main__":  # pragma: no cover
    app()
