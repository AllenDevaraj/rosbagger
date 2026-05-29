"""``build_qss(tokens) -> str`` — the SINGLE place QSS strings live (D-03), pure + Qt-free.

This module turns a :class:`~rosbagger_desktop.theme.tokens.Tokens` palette into one QSS
stylesheet by f-stringing every token into a class/objectName-keyed sheet. It imports NO
PySide6 (it does not even need a ``QApplication``) so it stays offline/Qt-free (D-08,
17-RESEARCH Pitfall 6) and is unit-testable as a pure string (17-RESEARCH Pitfall 4).

The selectors deliberately name the elements that do NOT inherit ``QWidget`` styling
(17-RESEARCH Pitfall 3): ``QTableView`` grid/selection colors, ``QHeaderView::section``, and
``QSplitter::handle``. A ``#status_error`` objectName selector carries the semantic error
color — it replaces query_panel's inline ``_STATUS_ERROR_STYLE`` literal in 17-03, so panels
toggle an objectName instead of writing inline QSS (D-03 anti-pattern).
"""

from __future__ import annotations

from .tokens import DARK, Tokens


def region_colors(t: Tokens = DARK) -> tuple[str, str]:
    """The replay loop-region (fill, handle) baked sRGB hex for a palette (Phase 19).

    The ``Scrubber`` paints its region band + handles with a ``QPainter`` (not QSS), so it
    cannot read them from the stylesheet — it resolves them through THIS accessor instead, so
    the values still live in the token module (D-03: no inline color in the widget). Defaults
    to the ``DARK`` palette (the app's default theme); a future theme-aware Scrubber can pass
    the active ``Tokens``.
    """
    return (t.region_fill, t.region_handle)


def build_qss(t: Tokens) -> str:
    """Render ``t`` into one QSS stylesheet string (pure; no ``QApplication`` needed).

    Every visible color/spacing value is sourced from ``t`` — there are no hard-coded colors
    here, which is what makes the design system genuinely token-driven (D-03). Selectors for
    the non-inheriting table/header/splitter elements are named explicitly (Pitfall 3).
    """
    return f"""
    QWidget {{
        background-color: {t.bg};
        color: {t.text};
        font-size: {t.font_size_base}px;
    }}
    QMainWindow, QDialog {{
        background-color: {t.bg};
    }}

    /* Raised surfaces (panels, tables, inputs). */
    QListWidget, QTreeWidget, QTableView, QTextEdit, QPlainTextEdit, QLineEdit {{
        background-color: {t.surface};
        border: 1px solid {t.border};
        border-radius: {t.radius}px;
    }}

    /* Tables: grid + selection do NOT inherit QWidget styling (Pitfall 3). */
    QTableView {{
        gridline-color: {t.border};
        selection-background-color: {t.accent};
        selection-color: {t.bg};
        alternate-background-color: {t.bg};
    }}
    QHeaderView::section {{
        background-color: {t.surface};
        color: {t.text_muted};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: {t.space_sm}px {t.space_md}px;
    }}
    QTableView::item:selected {{
        background-color: {t.accent};
        color: {t.bg};
    }}

    /* Splitter handle is its own styleable element (Pitfall 3). */
    QSplitter::handle {{
        background-color: {t.border};
    }}

    /* Buttons + restrained accent affordances. */
    QPushButton {{
        background-color: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: {t.radius}px;
        padding: {t.space_sm}px {t.space_md}px;
    }}
    QPushButton:hover {{
        border-color: {t.accent};
    }}
    QPushButton:disabled {{
        color: {t.text_muted};
    }}

    QMenuBar, QMenu {{
        background-color: {t.surface};
        color: {t.text};
    }}
    QMenuBar::item:selected, QMenu::item:selected {{
        background-color: {t.accent};
        color: {t.bg};
    }}

    QLabel {{
        background-color: transparent;
        color: {t.text};
    }}
    QLabel[muted="true"] {{
        color: {t.text_muted};
    }}

    /* Section heading affordance (17-03 visual hierarchy, D-03): panels mark a section/header
       label with the dynamic property heading="true" instead of an inline font/color literal.
       A heading reads slightly larger + muted so dense data tables stay the focal point. */
    QLabel[heading="true"] {{
        color: {t.text_muted};
        font-size: {t.font_size_base + 1}px;
        font-weight: 600;
        padding: {t.space_sm}px {t.space_sm}px;
    }}

    /* Shell chrome (17-03): the cockpit nav rail + the central surface get objectName-keyed
       selectors so the shell itself reads as a deliberate frame, not a default-Qt gray box. */
    QListWidget#nav_list {{
        background-color: {t.surface};
        border: none;
        border-right: 1px solid {t.border};
        padding: {t.space_sm}px;
        outline: 0;
    }}
    QListWidget#nav_list::item {{
        padding: {t.space_sm}px {t.space_md}px;
        border-radius: {t.radius}px;
    }}
    QListWidget#nav_list::item:selected {{
        background-color: {t.accent};
        color: {t.bg};
    }}
    QWidget#shell_central {{
        background-color: {t.bg};
    }}
    QStackedWidget#panel_stack {{
        background-color: {t.bg};
    }}

    /* Semantic error status surface — objectName-keyed (replaces inline _STATUS_ERROR_STYLE
       in 17-03). Panels set objectName("status_error") instead of writing inline QSS (D-03). */
    QLabel#status_error {{
        color: {t.error};
        border: 1px solid {t.error};
        border-radius: {t.radius}px;
        padding: {t.space_sm}px;
    }}
    """
