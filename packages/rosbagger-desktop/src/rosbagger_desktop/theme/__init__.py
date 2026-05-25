"""The ``theme`` subpackage — the rosbagger-desktop design system (D-03/D-04/D-06).

Import surface for the rest of the package. The two LOWER tiers are pure + Qt-free:

* :data:`Tokens` / :data:`DARK` / :data:`LIGHT` (``tokens.py``) — pure design data.
* :func:`build_qss` (``qss.py``) — pure token→QSS string function (the single place QSS lives).

``ThemeManager`` (``manager.py``) is the ONLY tier that touches ``QApplication``/``QSettings``;
it is re-exported here too (Task 2) but lives behind a PySide6 import. The package ``__init__``
does NOT eagerly import ``manager`` — it is bound lazily via ``__getattr__`` so a Qt-free
consumer can ``from rosbagger_desktop.theme import DARK, build_qss`` without pulling PySide6,
while ``from rosbagger_desktop.theme import ThemeManager`` still works on demand (D-08).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .qss import build_qss
from .tokens import DARK, LIGHT, Tokens

if TYPE_CHECKING:  # type-checker sees the symbol without an eager runtime import
    from .manager import ThemeManager

__all__ = ["DARK", "LIGHT", "Tokens", "ThemeManager", "build_qss"]


def __getattr__(name: str) -> object:
    """Lazily resolve ``ThemeManager`` so importing this package stays Qt-import-light.

    Binding ``ThemeManager`` eagerly would pull ``manager`` (and thus PySide6) on every
    ``import rosbagger_desktop.theme``; deferring it keeps token/qss-only consumers Qt-free
    (D-08) while ``from rosbagger_desktop.theme import ThemeManager`` resolves on first use.
    """
    if name == "ThemeManager":
        from .manager import ThemeManager

        return ThemeManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
