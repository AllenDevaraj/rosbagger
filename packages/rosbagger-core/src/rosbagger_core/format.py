"""Shared human-readable formatters for the three faces (R2/R3).

``human_size`` (byte counts) and ``human_dur`` (nanosecond durations) were each implemented
independently in ``bagq``, the Textual GUI, and the PySide6 desktop — and had already drifted:
the ``bagq`` ``_human_size`` stopped at ``GB`` (``if size < 1024.0 or unit == "GB"``), so a
2 TiB bag printed ``2048.0 GB`` while the GUIs printed ``2.0 TB`` for the same bag. This is the
single home; the three faces now delegate here so they can never diverge again.

Presentation-only: the core APIs keep ``size_bytes`` / durations as raw values (display
formatting is the face's job). OFFLINE INVARIANT: stdlib-only and NOT imported by
``rosbagger_core/__init__`` — ``import rosbagger_core`` stays light; importing this module
pulls no heavy stack (``tests/test_offline_guard.py``).
"""

from __future__ import annotations

# 1024-based units, B through PB. Going to PB (not stopping at GB) is the fix for the bagq
# drift; a real bag never reaches PB, but dividing all the way through keeps TB-scale bags
# (multi-hour lidar recordings) honest instead of printing thousands of GB.
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(num_bytes: int) -> str:
    """Format a byte count human-readably, 1024-based (``B``/``KB``/``MB``/``GB``/``TB``/``PB``).

    Whole bytes print with no decimal (``512 B``); larger units print one decimal
    (``9.2 KB``, ``1.5 MB``, ``2.0 TB``). The last unit (``PB``) is the cap — a value beyond
    it just keeps scaling in PB rather than rolling off the unit list.
    """
    size = float(num_bytes)
    for unit in _SIZE_UNITS:
        if size < 1024.0 or unit == _SIZE_UNITS[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} {_SIZE_UNITS[-1]}"  # pragma: no cover - loop always returns


def human_dur(ns: int) -> str:
    """Format a nanosecond duration human-readably (the TF gap/interval renderer).

    Sub-second values print as milliseconds — a whole number of ms drops the decimal
    (``800ms``), a fractional ms keeps one (``1.5ms``); a second or more prints seconds with
    two decimals (``12.40s``). The seeded ``800_000_000`` ns dropout renders as ``800ms``.
    """
    ms = ns / 1e6
    if ms < 1000.0:
        return f"{int(ms)}ms" if ms == int(ms) else f"{ms:.1f}ms"
    return f"{ns / 1e9:.2f}s"
