"""``ThemeManager`` — apply / toggle / persist the active theme (D-06), the ONLY Qt tier.

This is the only theme module that touches ``QApplication`` and ``QSettings`` (17-RESEARCH
Pattern 2). It owns the active theme NAME, applies the corresponding pure ``build_qss`` string
to the running app, force-refreshes already-shown widgets so the flip is visible without a
relaunch, and persists the choice across launches via ``QSettings``.

PERSISTENCE (D-06): the active name is read from ``QSettings().value("ui/theme", "dark")`` at
construction and written back on every ``toggle()``. Identity (``setOrganizationName`` /
``setApplicationName``) is set ONCE in ``cli.main`` so the conf lands at
``~/.config/rosbagger/rosbagger-desktop.conf`` on Linux (17-RESEARCH, verified).

ROBUSTNESS (T-17-01): a tampered/garbage persisted value is treated as the dark default —
:meth:`apply` selects LIGHT only when the name is exactly ``"light"``, else DARK. No crash on
a hand-edited conf file.

LIVE FLIP (17-RESEARCH Pitfall 2): ``setStyleSheet`` re-applies, but widgets already painted
cache style data; :meth:`apply` iterates the app's top-level widgets and does
``unpolish/polish/update`` so the new theme actually repaints.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QApplication

from .qss import build_qss
from .tokens import DARK, LIGHT


class ThemeManager(QObject):
    """Owns the active theme name; applies/toggles/persists it on the running app (D-06)."""

    _KEY = "ui/theme"

    def __init__(self) -> None:
        """Read the persisted theme name (defaulting to ``"dark"``) — see class docstring."""
        super().__init__()
        # str() coerces a QSettings value (which may come back as a non-str on some backends)
        # to a plain string so the == "light" check below is always well-defined (T-17-01).
        self._name = str(QSettings().value(self._KEY, "dark"))

    @property
    def name(self) -> str:
        """The active theme name, ``"dark"`` | ``"light"`` (a test accessor; D-06).

        Normalizes any non-``"light"`` stored value to ``"dark"`` so the reported name always
        matches the palette :meth:`apply` would select (T-17-01 — garbage degrades to dark).
        """
        return "light" if self._name == "light" else "dark"

    def apply(self) -> None:
        """Style the running ``QApplication`` with the active theme + flush shown widgets.

        Selects LIGHT only when the name is exactly ``"light"``; any other value (including a
        tampered conf) falls back to DARK (T-17-01). After ``setStyleSheet`` it unpolishes/
        polishes/updates each top-level widget so an already-shown window repaints in the new
        theme without a relaunch (17-RESEARCH Pitfall 2).
        """
        tokens = LIGHT if self.name == "light" else DARK
        app = QApplication.instance()
        if app is None:  # defensive: apply() is meaningless without a running app
            return
        app.setStyleSheet(build_qss(tokens))
        for widget in app.topLevelWidgets():
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()

    def toggle(self) -> None:
        """Flip dark↔light, persist the new name immediately, then apply it live (D-06)."""
        self._name = "light" if self.name == "dark" else "dark"
        QSettings().setValue(self._KEY, self._name)  # persist BEFORE apply (survives a crash)
        self.apply()
