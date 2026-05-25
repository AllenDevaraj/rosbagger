"""``set_status`` — the shared accessible status-label helper (17-02 / D-02, D-09).

Generalized from ``query_panel._set_status`` so inspect / tf / query all surface status +
teaching errors through ONE accessible code path. THIN-FACE (D-09): this builds NO message
text — ``text`` is set verbatim (teaching errors stay ``str(exc)``); it only handles
presentation (text + a11y description), the error AFFORDANCE (objectName), and the screen
reader announcement.

The error COLOR is NOT an inline stylesheet literal: per D-03 the helper toggles the
``status_error`` objectName so the theme QSS (``theme/qss.py`` ``QLabel#status_error``
selector, owned by 17-01) supplies the red foreground/border. On the non-error path the
label's ORIGINAL objectName is restored so a once-shown error affordance clears on the next
success. Changing an objectName does not re-evaluate QSS by itself, so the helper
unpolishes/polishes the label after each toggle (the standard Qt live-restyle dance).

OFFSCREEN GUARD (D-09 / RESEARCH Pitfall 1 / commit 7e99a5f): on the error path it posts a
``QAccessible`` Alert so screen readers announce the teaching message — but ONLY when the
platform is not ``offscreen``. Posting a ``QAccessibleEvent`` into a running event loop under
the offscreen backend crashes at the C++ level (a segfault no Python ``try/except`` can
catch); the announce is additionally wrapped in ``contextlib.suppress`` as best-effort.

OFFLINE-CLEAN (D-08, Pitfall 4): imports ONLY PySide6 + stdlib.
"""

from __future__ import annotations

import contextlib

from PySide6.QtGui import QAccessible, QAccessibleEvent, QGuiApplication
from PySide6.QtWidgets import QLabel

# The objectName carrying the semantic error affordance — keyed by the theme QSS
# ``QLabel#status_error`` selector (theme/qss.py, D-03). On the non-error path the label's
# ORIGINAL objectName (captured as a dynamic property the first time it is needed) is restored.
_ERROR_OBJECT_NAME = "status_error"
# The dynamic property used to remember the label's non-error objectName across error toggles.
_BASE_NAME_PROP = "_status_base_object_name"


def _repolish(label: QLabel) -> None:
    """Re-evaluate the label's QSS after an objectName change (the Qt live-restyle dance)."""
    style = label.style()
    style.unpolish(label)
    style.polish(label)
    label.update()


def set_status(label: QLabel, text: str, *, is_error: bool = False) -> None:
    """Set ``label`` text + a11y description; toggle the error affordance + announce on error.

    Presentation-only helper (THIN-FACE, D-09): ``text`` is set VERBATIM (teaching errors
    stay ``str(exc)``). It (1) sets the label text, (2) mirrors it into the accessible
    description so assistive tech exposes the value, (3) toggles the ``status_error``
    objectName (NOT an inline stylesheet — the color comes from the theme QSS, D-03) so the
    error affordance shows on the error path and clears back to the label's original
    objectName otherwise, repolishing so the QSS re-evaluates live, and (4) on the error path
    posts a ``QAccessible`` Alert so screen readers announce it — guarded by
    ``platformName() != "offscreen"`` (offscreen has no a11y bridge and posting there
    segfaults at the C++ level, uncatchable) and wrapped in ``contextlib.suppress`` as
    best-effort (commit 7e99a5f, T-17-05).
    """
    label.setText(text)
    label.setAccessibleDescription(text)

    # Remember the label's non-error objectName once so we can restore it on success. Captured
    # lazily the first time set_status touches the label (its original objectName at that point).
    base_name = label.property(_BASE_NAME_PROP)
    if base_name is None:
        current = label.objectName()
        base_name = current if current != _ERROR_OBJECT_NAME else ""
        label.setProperty(_BASE_NAME_PROP, base_name)

    desired = _ERROR_OBJECT_NAME if is_error else str(base_name)
    if label.objectName() != desired:
        label.setObjectName(desired)
        _repolish(label)

    if is_error and QGuiApplication.platformName() != "offscreen":
        # Announcement is best-effort; never crash the GUI if the a11y bridge rejects it.
        with contextlib.suppress(Exception):
            QAccessible.updateAccessibility(QAccessibleEvent(label, QAccessible.Alert))
