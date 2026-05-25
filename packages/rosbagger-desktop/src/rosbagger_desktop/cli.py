"""``rosbagger-desktop`` console-script entry point (D-16 launch-arg ``<bag-path>``).

A thin stdlib-``argparse`` front door — the Qt analog of the TUI ``cli.py``: it
parses an OPTIONAL bag path, then constructs ``QApplication`` and the
:class:`~rosbagger_desktop.main_window.MainWindow` ONLY AFTER ``parse_args``.

ISOLATION INVARIANT (D-16, Pitfall 6): ``QApplication`` and ``MainWindow`` are
imported INSIDE :func:`main`, so ``rosbagger-desktop --help`` (and any argparse
error) reaches ``sys.exit`` and prints help WITHOUT ever importing PySide6 or
building a Qt object — the help path stays Qt-free on a headless box, and this
module's top level stays PySide6-free / ROS-free.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosbagger-desktop",
        description=(
            "Launch the rosbagger desktop GUI (inspect / query / tf / record / replay). "
            "Pass a bag path to open it on launch, or open one from the in-window picker."
        ),
    )
    parser.add_argument(
        "bag_path",
        nargs="?",
        default=None,
        metavar="BAG",
        help="optional ROS 1 / ROS 2 sqlite3 / MCAP bag to open on launch",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and launch the desktop window on the optional launch bag (D-16).

    ``--help`` / bad args exit at ``parse_args`` BEFORE any Qt import, so the help
    path builds no ``QApplication``. After a successful parse, ``QApplication`` and
    :class:`MainWindow` are imported inside the body, the window is shown, and the
    Qt event loop is entered (``app.exec()``).
    """
    args = _build_parser().parse_args(argv)

    # Imported INSIDE main (Qt-free top level, Pitfall 6): never reached on --help.
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .theme import ThemeManager

    # Reuse an existing QApplication if one is already running (e.g. a test harness owns the
    # singleton); Qt forbids a second instance. Otherwise create the one app for this process.
    app = QApplication.instance() or QApplication(
        sys.argv if argv is None else [sys.argv[0], *argv]
    )

    # Identity for QSettings persistence (D-06) — set ONCE, AFTER QApplication but BEFORE the
    # ThemeManager reads ui/theme. Lands the conf at ~/.config/rosbagger/rosbagger-desktop.conf
    # on Linux (17-RESEARCH, verified). Theme code lives entirely in rosbagger-desktop (D-08).
    QCoreApplication.setOrganizationName("rosbagger")
    QCoreApplication.setApplicationName("rosbagger-desktop")

    # Construct + apply the theme BEFORE show() so the window paints already-themed (no flash),
    # then hand the manager to MainWindow so the View-menu toggle can reach it (Task 3).
    theme_manager = ThemeManager()
    theme_manager.apply()

    window = MainWindow(bag_path=args.bag_path, theme_manager=theme_manager)
    window.show()
    return app.exec()
