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
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSlider

from ..theme.qss import region_colors

# The slider works in integer steps; 1000 gives a smooth 0..1 fraction (value / _RESOLUTION).
_RESOLUTION = 1000

# A click/drag within this many fractional units of a marker snaps to that marker (so a
# jump-to-event lands exactly on the event time, not one step off). Ported from the TUI.
_MARKER_SNAP_FRACTION = 0.02

# Marker glyph colour (drawn as a small tick above the groove).
_MARKER_COLOR = QColor(220, 120, 40)
_MARKER_PIXELS = 6  # tick height in px

# Region (Phase 19): colours come from the theme tokens (region_colors accessor — NO inline
# hex here, D-03), built into QColors once at import. The band is drawn semi-transparent.
_REGION_FILL_HEX, _REGION_HANDLE_HEX = region_colors()
_REGION_FILL_ALPHA = 70  # 0..255 translucency for the shaded snippet band
_REGION_HANDLE_PX = 3  # handle bar width in px
# A press within this many px of a handle grabs it (else the press falls through to the
# base QSlider playhead seek, preserving the existing `seeked` path — Phase-18 live scrub).
_HANDLE_GRAB_PX = 8


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

    # Emitted ONLY on a USER drag of an In/Out region handle (Phase 19) — carries the resulting
    # (in_frac, out_frac). The panel maps it onto replayer.set_loop_region. A programmatic
    # set_loop_region (from the Set-In/Out buttons) does NOT emit this (no feedback loop).
    region_changed = Signal(float, float)

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
        # Loop region (Phase 19): in/out fractions (None = no region) + the handle a user is
        # currently dragging ("in"/"out"/None). Set programmatically (panel buttons) or by a
        # user handle drag; painted as a shaded band + two handle bars.
        self._loop_in: float | None = None
        self._loop_out: float | None = None
        self._drag_handle: str | None = None
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

    # ------------------------------------------------------------ loop region (Phase 19)

    def set_loop_region(self, in_frac: float, out_frac: float) -> None:
        """Set the loop-region band to ``[in_frac, out_frac]`` (0..1) — programmatic, NO emit.

        Called by the panel (19-03) from the Set-In/Set-Out buttons. Clamps both to ``[0,1]``
        and keeps ``in <= out`` (swaps if reversed). Repaints, but does NOT emit
        :attr:`region_changed` — only a USER handle drag does (so reflecting the scheduler
        region back never re-triggers a scheduler write, mirroring ``set_position``).
        """
        lo, hi = (in_frac, out_frac) if in_frac <= out_frac else (out_frac, in_frac)
        self._loop_in = _clamp01(lo)
        self._loop_out = _clamp01(hi)
        self.update()

    def clear_loop_region(self) -> None:
        """Clear the loop region (no band, no handles) — programmatic, NO emit."""
        self._loop_in = None
        self._loop_out = None
        self.update()

    @property
    def loop_region(self) -> tuple[float, float] | None:
        """The region as ``(in_frac, out_frac)`` when set, else ``None`` (both-or-neither)."""
        if self._loop_in is not None and self._loop_out is not None:
            return (self._loop_in, self._loop_out)
        return None

    def _handle_at(self, x_px: int) -> str | None:
        """Return ``"in"``/``"out"`` if ``x_px`` is within grab tolerance of a handle, else None.

        The hit-test the press handler uses to decide between grabbing a region handle and
        falling through to the base playhead seek. Picks the CLOSER handle when both are in
        range (degenerate near-equal in/out). Returns None when no region is set.
        """
        if self._loop_in is None or self._loop_out is None:
            return None
        width = max(1, self.width() - 1)
        x_in = round(self._loop_in * width)
        x_out = round(self._loop_out * width)
        d_in = abs(x_px - x_in)
        d_out = abs(x_px - x_out)
        if min(d_in, d_out) > _HANDLE_GRAB_PX:
            return None
        return "in" if d_in <= d_out else "out"

    def _update_drag_handle(self, handle: str, fraction: float) -> None:
        """Move the dragged handle to ``fraction`` (clamped, in<=out kept) + emit region_changed.

        The single mutate-and-emit point for a USER handle drag — driven by
        :meth:`mouseMoveEvent` in production and called directly in headless tests (a real
        offscreen mouse drag on a QSlider is fiddly). Clamps the dragged handle against the
        other so the region never inverts.
        """
        fraction = _clamp01(fraction)
        if handle == "in":
            self._loop_in = min(fraction, self._loop_out if self._loop_out is not None else 1.0)
        else:  # "out"
            self._loop_out = max(fraction, self._loop_in if self._loop_in is not None else 0.0)
        self.update()
        self.region_changed.emit(self._loop_in, self._loop_out)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """Grab a region handle if the press is near one; else fall through to the playhead seek.

        Only a press within ``_HANDLE_GRAB_PX`` of an In/Out handle enters region-drag mode
        (suppressing the base QSlider playhead jump). Any other press calls ``super()`` so the
        existing ``seeked`` playhead-seek path (Phase-18 live scrubbing) is untouched.
        """
        handle = self._handle_at(round(event.position().x()))
        if handle is not None:
            self._drag_handle = handle
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """Drag the grabbed region handle (emits region_changed); else the base drag-seek."""
        if self._drag_handle is not None:
            width = max(1, self.width() - 1)
            self._update_drag_handle(self._drag_handle, event.position().x() / width)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override name
        """End a region-handle drag; otherwise the base release (playhead)."""
        if self._drag_handle is not None:
            self._drag_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ rendering

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override name
        """Draw the slider, then overlay the loop-region band/handles + the event-marker ticks.

        Pure presentation — no module/transport logic. The base slider draws the groove +
        playhead handle; on top we draw (Phase 19) a semi-transparent loop-region band with two
        In/Out handle bars (when a region is set), then a small coloured tick at each event
        marker. Region/handle colours come from the theme tokens (``region_colors`` — no inline
        hex). Nothing is overlaid when there is neither a region nor markers.
        """
        super().paintEvent(event)
        has_region = self._loop_in is not None and self._loop_out is not None
        if not has_region and not self._markers:
            return
        painter = QPainter(self)
        try:
            width = max(1, self.width() - 1)
            if has_region:
                x_in = round(self._loop_in * width)
                x_out = round(self._loop_out * width)
                fill = QColor(_REGION_FILL_HEX)
                fill.setAlpha(_REGION_FILL_ALPHA)
                painter.fillRect(QRect(x_in, 0, max(1, x_out - x_in), self.height()), fill)
                handle = QColor(_REGION_HANDLE_HEX)
                for x in (x_in, x_out):
                    painter.fillRect(QRect(x, 0, _REGION_HANDLE_PX, self.height()), handle)
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
