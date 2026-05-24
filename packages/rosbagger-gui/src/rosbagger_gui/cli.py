"""``rosbagger-gui`` console-script entry point (D-02 launch-arg ``<bag-path>``).

A thin stdlib-``argparse`` front door: parses an OPTIONAL bag path and launches
``RosbaggerApp(bag_path=...).run()``. argparse (not typer) keeps the launcher
dependency-free and gives ``--help`` a clean exit 0 WITHOUT constructing the App
(so ``rosbagger-gui --help`` never starts a TUI). ``RosbaggerApp`` is imported
inside :func:`main` so ``--help`` does not pay the textual/app import cost — and
the package top stays import-light.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosbagger-gui",
        description=(
            "Launch the rosbagger TUI cockpit (inspect / query / tf / record / replay). "
            "Pass a bag path to open it on launch, or open one from the in-TUI picker."
        ),
    )
    parser.add_argument(
        "bag_path",
        nargs="?",
        default=None,
        metavar="BAG",
        help="optional path to a ROS 1 / ROS 2 sqlite3 / MCAP bag to open on launch",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Parse ``argv`` and run the App with the optional launch bag (D-02)."""
    args = _build_parser().parse_args(argv)
    from .app import RosbaggerApp

    RosbaggerApp(bag_path=args.bag_path).run()
