"""``Scrubber`` — a Qt timeline widget for the replay panel (D-14, Qt port of the TUI).

A horizontal :class:`PySide6.QtWidgets.QSlider`-style timeline with:

* a **playhead** at a ``position`` (0.0 .. 1.0) the replay panel sets as the scheduler
  advances (the cursor's fraction of the bag span), and
* an overlaid set of **event markers** — ``(fraction, label)`` tuples the panel sets from
  the bag's events sidecar (``list_events``) — so a user can see where annotated events sit
  on the timeline and jump to them.

CLICK / DRAG -> FRACTION ONLY (the seam, D-14): on a user click or drag the widget computes
the fraction along the bar (0..1) and emits :attr:`seeked` carrying that fraction. The widget
contains NO transport state machine and no position-setter call of its own — it is pure
presentation + input. The panel handles :attr:`seeked` and maps the fraction onto the
scheduler's bag-relative jump (``replayer.seek(int(fraction * bag_span_ns))``); the mapping
is the panel's job, not the widget's. A click on (or very near) a marker SNAPS to that
marker's fraction so jump-to-event is exact (the ``_MARKER_SNAP_FRACTION`` port of the TUI).

This is the Qt analog of the TUI ``Scrubber.Seeked`` message: a programmatic ``position``
set (via :meth:`set_position`, driven from a UI-thread slot after the drive worker returns)
must NOT re-emit ``seeked`` — only a USER interaction does (``_emit_on_release`` guards the
programmatic path).

OFFLINE-CLEAN (Pitfall 4): this module imports ONLY PySide6 + stdlib (``dataclasses``). It
names no live-module symbol and never touches ROS — importing it is trivially offline-safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSlider

# The slider works in integer steps; 1000 gives a smooth 0..1 fraction (value / _RESOLUTION).
_RESOLUTION = 1000

# A click/drag within this many fractional units of a marker snaps to that marker (so a
# jump-to-event lands exactly on the event time, not one step off). Ported from the TUI.
_MARKER_SNAP_FRACTION = 0.02

# Marker glyph colour (drawn as a small tick above the groove).
_MARKER_COLOR = QColor(220, 120, 40)
_MARKER_PIXELS = 6  # tick height in px


@dataclass(frozen=True)
class EventMark:
    """One timeline marker: a ``fraction`` (0..1) along the bar and its ``label``."""

    fraction: float
    label: str


class Scrubber(QSlider):
    """A horizontal timeline slider: a playhead + event markers; user input -> fraction.

    The panel drives :meth:`set_position` (the playhead, 0..1) and :meth:`set_markers` (the
    event overlay), and listens for the :attr:`seeked` signal the widget emits on a USER
    click/drag. The widget itself maps NOTHING to the scheduler — it only reports where on
    the bar the user moved to (a fraction). A programmatic ``set_position`` never re-emits
    ``seeked`` (the panel sets the playhead from the scheduler; only a user seek triggers a
    new jump).
    """

    # Emitted on a USER click/drag — carries the click/drag fraction (0..1). The panel maps
    # it onto replayer.seek; the widget sets no scheduler position itself.
    seeked = Signal(float)

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Build a 0.._RESOLUTION horizontal slider; markers empty until the panel sets them."""
        super().__init__(Qt.Horizontal, *args, **kwargs)  # type: ignore[arg-type]
        self.setRange(0, _RESOLUTION)
        self.setValue(0)
        # Event markers (fraction, label) the panel sets from list_events(bag); never holds
        # any transport/position state.
        self._markers: list[EventMark] = []
        # Guards the programmatic set_position path so it does not re-emit seeked.
        self._suppress_emit = False
        # A user drag/click changes the value; on a USER change we snap + emit a fraction.
        self.valueChanged.connect(self._on_value_changed)

    # ------------------------------------------------------------------ panel API

    def set_markers(self, marks: list[tuple[float, str]]) -> None:
        """Set the event-marker overlay from ``(fraction, label)`` tuples (panel-driven).

        Called by the replay panel after it reads ``list_events(bag)`` and maps each row to
        a bar fraction. Fractions are clamped to ``[0, 1]``. Triggers a repaint so the
        markers appear. No transport logic here — the panel owns where the fractions came
        from and what a marker click means.
        """
        self._markers = [EventMark(fraction=_clamp01(frac), label=label) for frac, label in marks]
        self.update()

    @property
    def markers(self) -> list[EventMark]:
        """The current event markers (a copy-safe read for the panel/tests)."""
        return list(self._markers)

    def set_position(self, fraction: float) -> None:
        """Set the playhead to ``fraction`` (0..1) WITHOUT emitting ``seeked`` (panel-driven).

        Called from a UI-thread slot after the drive worker pushes the Replayer's
        ``position_fraction`` back — a programmatic move, NOT a user seek, so the emit is
        suppressed (otherwise reflecting the cursor would trigger a fresh jump). The Qt
        analog of writing the TUI ``Scrubber.position`` reactive.
        """
        self._suppress_emit = True
        try:
            self.setValue(round(_clamp01(fraction) * _RESOLUTION))
        finally:
            self._suppress_emit = False

    @property
    def position(self) -> float:
        """The current playhead position as a 0..1 fraction (the slider value / resolution)."""
        return self.value() / _RESOLUTION

    # --------------------------------------------------------------------- input

    def _on_value_changed(self, value: int) -> None:
        """A USER value change → snap near a marker, then emit ``seeked`` (the D-14 seam).

        A programmatic :meth:`set_position` sets ``_suppress_emit`` so reflecting the
        scheduler cursor never re-triggers a seek; only a click/drag reaches the emit. The
        fraction snaps to the nearest event marker within ``_MARKER_SNAP_FRACTION`` so a
        jump-to-event click lands exactly on the event time.
        """
        if self._suppress_emit:
            return
        fraction = _clamp01(value / _RESOLUTION)
        nearest = self._nearest_marker(fraction)
        if nearest is not None and abs(nearest.fraction - fraction) <= _MARKER_SNAP_FRACTION:
            fraction = nearest.fraction
        self.seeked.emit(fraction)

    def _nearest_marker(self, fraction: float) -> EventMark | None:
        """Return the marker closest to ``fraction`` (or ``None`` when there are none)."""
        if not self._markers:
            return None
        return min(self._markers, key=lambda m: abs(m.fraction - fraction))

    # ------------------------------------------------------------------ rendering

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override name
        """Draw the standard slider, then overlay the event markers as ticks (presentation).

        Pure presentation — no module/transport logic. The base slider draws the groove +
        playhead handle; we draw a small coloured tick above the groove at each marker
        fraction so the user sees the annotated events on the timeline.
        """
        super().paintEvent(event)
        if not self._markers:
            return
        painter = QPainter(self)
        try:
            painter.setPen(_MARKER_COLOR)
            painter.setBrush(_MARKER_COLOR)
            width = max(1, self.width() - 1)
            for mark in self._markers:
                x = round(_clamp01(mark.fraction) * width)
                painter.fillRect(QRect(x, 0, 2, _MARKER_PIXELS), _MARKER_COLOR)
        finally:
            painter.end()


def _clamp01(value: float) -> float:
    """Clamp ``value`` into the inclusive ``[0.0, 1.0]`` range."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
