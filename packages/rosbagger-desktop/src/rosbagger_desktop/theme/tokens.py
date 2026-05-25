"""Design tokens — the single source of styling values (D-03), pure data, NO Qt import.

This module is the bottom of the theme stack: a frozen :class:`Tokens` dataclass plus the
two concrete palettes :data:`DARK` and :data:`LIGHT`. It imports ONLY ``dataclasses`` from
the stdlib — no PySide6 — so it stays trivially offline/Qt-free (D-08, 17-RESEARCH Pitfall 6)
and is unit-testable with no ``QApplication`` (the cleanest proof the system is token-driven,
17-RESEARCH Pitfall 4).

PALETTE DIRECTION (D-07): the usage scene is a robotics engineer reading dense bag tables at
a desk — favor a CALM, focused surface, one restrained accent, a single semantic error hue.
The dark default is a true NEUTRAL-WARM dark, deliberately AVOIDING the category-reflex
navy/cyan "developer tool" look; the light theme is a low-chroma calm paper surface.

OKLCH AUTHORING (D-07, 17-RESEARCH OKLCH section): each color is reasoned about in OKLCH for
perceptual uniformity, then BAKED to a final sRGB ``#rrggbb`` at design time — the source
``oklch(...)`` lives in the trailing comment for future reasoning. There is NO runtime color
conversion (it would add code/complexity for a value that never changes and risks pulling a
color library into the Qt package); we ship hex.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    """An immutable design-token palette — color + spacing + type scale (D-03).

    All color fields are baked sRGB ``#rrggbb`` strings (authored in OKLCH, see module
    docstring). Spacing/radius/font fields are integer pixel values. ``frozen=True`` makes
    each instance a hashable, accidentally-immutable value object — a palette is a constant.
    """

    # Color (baked sRGB hex; authored in OKLCH — see trailing comments on DARK/LIGHT).
    bg: str
    surface: str
    text: str
    text_muted: str
    accent: str
    error: str
    border: str
    # Spacing + shape (px).
    space_sm: int
    space_md: int
    radius: int
    # Type scale (px).
    font_size_base: int
    font_size_mono: int


# Neutral-warm dark default (NOT category-reflex navy/cyan, D-07): a calm desk surface with
# one restrained blue accent and a single warm-red error hue. Hues sit near 250-255 (a
# barely-blue warm neutral) so the surface reads as "warm graphite," not "tool navy."
DARK = Tokens(
    bg="#1b1c1f",  # oklch(0.21 0.006 260) — warm-neutral graphite base
    surface="#24262b",  # oklch(0.26 0.008 260) — raised panel/table surface
    text="#e7e8ea",  # oklch(0.92 0.004 260) — near-white body text, low chroma
    text_muted="#9a9ea6",  # oklch(0.68 0.008 260) — secondary/header text
    accent="#5b9dd6",  # oklch(0.68 0.10 245) — restrained blue selection/links
    error="#e06c75",  # oklch(0.66 0.16 22)  — single warm-red semantic error
    border="#34373d",  # oklch(0.31 0.006 260) — hairline dividers / gridlines
    space_sm=4,
    space_md=8,
    radius=4,
    font_size_base=13,
    font_size_mono=12,
)

# Low-chroma calm light surface (D-07): a near-paper background with a slightly deeper accent
# and a darker error hue tuned for contrast on a light field.
LIGHT = Tokens(
    bg="#f6f7f8",  # oklch(0.97 0.003 260) — calm off-white paper base
    surface="#ffffff",  # oklch(1.00 0.000 0)   — pure-white raised panel/table surface
    text="#1d1f23",  # oklch(0.23 0.006 260) — near-black body text
    text_muted="#5c616a",  # oklch(0.48 0.010 260) — secondary/header text
    accent="#2f6fb0",  # oklch(0.52 0.12 250) — deeper blue accent for light-field contrast
    error="#c0392b",  # oklch(0.52 0.17 27)  — darker red error for light-field contrast
    border="#d8dbdf",  # oklch(0.88 0.004 260) — hairline dividers / gridlines
    space_sm=4,
    space_md=8,
    radius=4,
    font_size_base=13,
    font_size_mono=12,
)
