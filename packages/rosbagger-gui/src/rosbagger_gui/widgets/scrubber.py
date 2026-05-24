"""``Scrubber`` — a custom timeline Widget for the replay panel (Plan 14-06, D-09).

A horizontal bar with:

* a **playhead** at a reactive ``position`` (0.0 .. 1.0) the panel updates as the
  scheduler advances (the cursor's fraction of the bag span), and
* an overlaid set of **event markers** — ``(fraction, label)`` tuples the panel sets
  from the bag's ``<bag>.events.parquet`` sidecar (``list_events``) — so a user can
  see where annotated events sit on the timeline and jump to them.

CLICK -> FRACTION ONLY (the seam, D-09): on a click anywhere on the bar the widget
computes the click's fraction along the bar width (0..1) and POSTS a
:class:`Scrubber.Seeked` message carrying that fraction. The widget contains no
transport state machine and no position-setter call of its own — it is a pure
presentation + input widget. The panel handles ``Scrubber.Seeked`` and maps the
fraction onto the scheduler's bag-relative jump (the transport mapping is the panel's
job, not the widget's). A click on (or very near) a marker snaps to that marker's
fraction so jump-to-event is exact.

OFFLINE-CLEAN (Pitfall 2): this module imports ONLY ``textual`` + stdlib. It names no
live-module symbol and never touches ROS — importing this widget module is trivially
offline-safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

# Glyphs for the bar (rendered cells), the playhead, and an event marker. ASCII-ish
# box glyphs keep the widget terminal-portable.
_BAR_GLYPH = "─"
_PLAYHEAD_GLYPH = "▮"
_MARKER_GLYPH = "▼"

# A click within this many fractional units of a marker snaps to that marker (so a
# jump-to-event click lands exactly on the event time, not one cell off).
_MARKER_SNAP_FRACTION = 0.02


@dataclass(frozen=True)
class EventMark:
    """One timeline marker: a ``fraction`` (0..1) along the bar and its ``label``."""

    fraction: float
    label: str


class Scrubber(Widget):
    """A custom timeline bar: a reactive playhead + event markers; click -> fraction.

    The panel drives :attr:`position` (the playhead, 0..1) and :meth:`set_markers`
    (the event overlay), and listens for the :class:`Scrubber.Seeked` message the
    widget posts on a click. The widget itself maps NOTHING to the scheduler — it
    only reports where on the bar the user clicked (a fraction) and where the playhead
    currently is.
    """

    # The playhead position as a fraction of the bag span (0.0 .. 1.0). Reactive so the
    # panel can write self.scrubber.position = frac (via call_from_thread) and the bar
    # re-renders. clamp/refresh handled in the watcher.
    position: reactive[float] = reactive(0.0)

    class Seeked(Message):
        """Posted when the user clicks the bar — carries the click ``fraction`` (0..1).

        The panel handles this (``on_scrubber_seeked``) and maps the fraction onto the
        scheduler's bag-relative jump — the WIDGET sets no position itself.
        """

        def __init__(self, fraction: float) -> None:
            self.fraction = fraction
            super().__init__()

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Event markers (fraction, label) the panel sets from list_events(bag). Empty
        # until the panel populates them; never holds any transport/position state.
        self._markers: list[EventMark] = []

    # ------------------------------------------------------------------ panel API

    def set_markers(self, marks: list[tuple[float, str]]) -> None:
        """Set the event-marker overlay from ``(fraction, label)`` tuples (panel-driven).

        Called by the replay panel after it reads ``list_events(bag)`` and maps each
        row to a bar fraction. Fractions are clamped to ``[0, 1]``. Triggers a re-render
        so the markers appear. No transport logic here — the panel owns where the
        fractions came from and what a marker click means.
        """
        self._markers = [EventMark(fraction=_clamp01(frac), label=label) for frac, label in marks]
        self.refresh()

    @property
    def markers(self) -> list[EventMark]:
        """The current event markers (a copy-safe read for the panel/tests)."""
        return list(self._markers)

    def watch_position(self, _old: float, _new: float) -> None:
        """Re-render the bar whenever the playhead ``position`` changes."""
        self.refresh()

    # ------------------------------------------------------------------ rendering

    def render(self) -> RenderableType:
        """Render the bar with the playhead + event markers overlaid.

        The bar is ``width`` cells wide; the playhead cell is ``round(position *
        (width - 1))`` and each marker cell is ``round(fraction * (width - 1))``. The
        playhead takes precedence over a marker on the same cell. Pure presentation —
        no module/transport logic.
        """
        width = max(1, self.size.width or 1)
        cells = [_BAR_GLYPH] * width
        last = width - 1

        # Event markers first, so the playhead can overwrite a colliding cell.
        for mark in self._markers:
            idx = round(_clamp01(mark.fraction) * last)
            if 0 <= idx <= last:
                cells[idx] = _MARKER_GLYPH

        playhead = round(_clamp01(self.position) * last)
        if 0 <= playhead <= last:
            cells[playhead] = _PLAYHEAD_GLYPH

        return Text("".join(cells))

    # --------------------------------------------------------------------- input

    def on_click(self, event: Click) -> None:
        """Map a click on the bar to a fraction (0..1) and post :class:`Seeked`.

        Computes the click fraction from the click x-offset over the bar width. If the
        click is within :data:`_MARKER_SNAP_FRACTION` of an event marker, snaps to that
        marker's fraction (exact jump-to-event). Posts ``Seeked(fraction)`` — the panel
        does the position jump; the widget never touches the scheduler.
        """
        width = max(1, self.size.width or 1)
        # event.x is the click offset within the widget's content region (0-based).
        raw = event.x / (width - 1) if width > 1 else 0.0
        fraction = _clamp01(raw)

        # Snap to the nearest marker if the click landed close to one (jump-to-event).
        nearest = self._nearest_marker(fraction)
        if nearest is not None and abs(nearest.fraction - fraction) <= _MARKER_SNAP_FRACTION:
            fraction = nearest.fraction

        self.post_message(self.Seeked(fraction))

    def _nearest_marker(self, fraction: float) -> EventMark | None:
        """Return the marker closest to ``fraction`` (or ``None`` when there are none)."""
        if not self._markers:
            return None
        return min(self._markers, key=lambda m: abs(m.fraction - fraction))


def _clamp01(value: float) -> float:
    """Clamp ``value`` into the inclusive ``[0.0, 1.0]`` range."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
