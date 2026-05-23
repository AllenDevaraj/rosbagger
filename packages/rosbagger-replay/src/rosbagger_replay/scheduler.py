"""The PURE-PYTHON transport scheduler for replay (D-06..D-09 — the testability payoff).

This is the architectural heart of replay: a ROS-free state machine over an ordered
list of items (anything with a ``.t_ns``; in production
:class:`rosbagger_replay.source.ReplayItem`).
It owns the full transport contract — the four-state machine (PLAYING/PAUSED/STEPPING/DONE),
the six controls (play / pause / step / seek / set_rate / loop), monotonic inter-message
pacing scaled by ``rate``, and an optional bounded stop (``max_messages`` / ``duration``) —
and emits "publish item X now" decisions to an INJECTABLE ``sink`` callback. The clock and
sleep are injectable too, so the entire state machine is unit-tested deterministically with
a fake clock + a recording sink — no real sleeping, no ROS (D-11 tier 1, where SC2 + SC3 are
proven offline).

It imports ONLY stdlib (``time``, ``enum.Enum``, ``collections.abc.Callable``) — NEVER
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py``, and NOT ``source.py`` at module top: the
:class:`Replayer` is GENERIC over "items with a ``.t_ns``", so it just indexes a list and
reads ``item.t_ns``. The only live surface (Plan 03's rclpy publish sink) is a ~15-line
injectable callback layered ON TOP of this; all transport decisions live here, ROS-free.

PACING / RATE (D-08): between consecutive items spaced ``Δt_ns`` apart the scheduler sleeps
``Δt_ns / 1e9 / rate`` seconds — ``rate > 1`` plays faster, ``rate < 1`` slower; the first
item incurs no pre-sleep. ``rate`` is validated ``> 0`` (no ZeroDivisionError, no busy-wait;
RESEARCH Pitfall 5). The clock used for the optional ``duration`` bound is ``time.monotonic``
(NEVER wall-clock — Phase-12 WR-02), injectable for deterministic tests.

SEEK (D-09, W3): :meth:`seek` is the ONLY position-setting control — there is no ``start``
index ctor parameter (the W3 "start overload" trap). It lands the cursor on the first item
with ``t_ns >= items[0].t_ns + t_offset_ns``, skipping intervening items WITHOUT publishing;
seeking past the end lands ``cursor == len(items)`` (a clean DONE, no IndexError — Pitfall 6).

LOOP vs BOUND (D-09, W4): ``loop=True`` restarts the cursor at end-of-stream; ``loop=False``
reaches DONE. A bounded stop (``max_messages`` / ``duration``) is checked with ``is not None``
guards (``max_messages=0`` means zero, NOT unbounded — Phase-12 WR-01) and fires IMMEDIATELY
after each publish, BEFORE the end-of-stream loop-reset — so a bound that lands exactly on the
final item wins over ``loop``'s wraparound (DONE wins over loop-reset, the W4 boundary).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum


class State(Enum):
    """The replay transport state machine (D-06/D-09)."""

    PLAYING = "playing"
    PAUSED = "paused"
    STEPPING = "stepping"
    DONE = "done"


class Replayer:
    """A pure, ROS-free transport scheduler over an ordered list of ``.t_ns``-bearing items.

    Drives the six transport controls (D-07) and monotonic pacing (D-08) over ``items``,
    emitting each item to ``sink`` when it is time to publish. ``clock``, ``sleep``, and
    ``sink`` are all injectable so the whole suite runs instantly with a fake clock + a
    ``list.append`` sink — no real sleeping, no ROS (D-11 tier 1).

    Args:
        items: an ordered (non-decreasing ``t_ns``) sequence of items to replay; each item
            needs a ``.t_ns`` int (the scheduler is generic over the rest — topic/msgtype/cdr
            are opaque and handed straight to the sink).
        sink: the publish callback ``sink(item) -> None`` (rclpy publisher in production;
            ``list.append`` in tests).
        clock: a monotonic clock used only for the optional ``duration`` bound (D-08, WR-02);
            injectable for deterministic tests.
        sleep: the inter-message pacing sleep (``time.sleep`` in production; a recording
            no-op in tests).
        rate: schedule scale (``> 0``); the slept ``Δt`` is divided by ``rate``. Validated here.
        loop: when ``True`` the cursor restarts at end-of-stream; ``False`` reaches DONE (D-09).
            NOTE (WR-02): a loop wrap restarts at index ``0`` — NOT at the last :meth:`seek`
            target. ``seek`` is the sole position-setter for an explicit jump, but the loop
            reset deliberately rewinds to the start of the stream, so a prior offset-seek is
            NOT preserved across a wrap (seek to 5s then loop -> wrap restarts at 0, not 5s).
        max_messages: optional bound — halt after exactly this many sink calls (``is not None``
            guard so ``0`` means zero, not unbounded — WR-01).
        duration: optional bound (seconds) — halt once the injected clock has advanced
            ``>= duration`` since :meth:`run` began (monotonic, WR-02).

    Note:
        There is NO ``start`` index parameter (W3): :meth:`seek` is the single position
        control. The CLI's ``--start``/``--seek`` (seconds) maps to
        ``replayer.seek(int(start * 1e9))`` in Plan 03.
    """

    def __init__(
        self,
        items,
        sink: Callable[[object], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rate: float = 1.0,
        loop: bool = False,
        max_messages: int | None = None,
        duration: float | None = None,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self._items = items
        self._sink = sink
        self._clock = clock
        self._sleep = sleep
        self._rate = rate
        self.loop = loop
        self._max_messages = max_messages
        self._duration = duration
        self._cursor = 0
        self._state = State.PAUSED

    # --- introspection (read-only) ---
    @property
    def state(self) -> State:
        """The current transport state."""
        return self._state

    @property
    def cursor(self) -> int:
        """The index of the next item to publish (held across pause; advanced by publish/seek)."""
        return self._cursor

    @property
    def rate(self) -> float:
        """The current schedule scale (always ``> 0``)."""
        return self._rate

    # --- the six controls (D-07) ---
    def play(self) -> None:
        """Resume publishing from the held cursor (-> PLAYING)."""
        self._state = State.PLAYING

    def pause(self) -> None:
        """Stop publishing but HOLD the cursor (-> PAUSED); a later play()+run() resumes."""
        self._state = State.PAUSED

    def step(self) -> None:
        """Arm a single-step: the next run() publishes EXACTLY one item then re-pauses (D-09)."""
        self._state = State.STEPPING

    def set_rate(self, x: float) -> None:
        """Set the schedule scale; ``x <= 0`` raises ValueError (no busy-wait / div-by-zero)."""
        if x <= 0:
            raise ValueError("rate must be > 0")
        self._rate = x

    def seek(self, t_offset_ns: int) -> None:
        """Jump the cursor to the first item at/after a bag-relative time (D-09, W3).

        Sets the cursor to the first index ``i`` with
        ``items[i].t_ns >= items[0].t_ns + t_offset_ns``; intervening items are skipped
        WITHOUT publishing. Seeking past the last timestamp lands ``cursor == len(items)``
        (run() then reaches DONE without publishing — no IndexError, Pitfall 6). This is the
        ONLY position-setter (W3).
        """
        t0 = self._items[0].t_ns if self._items else 0
        target = t0 + t_offset_ns
        self._cursor = next(
            (i for i, it in enumerate(self._items) if it.t_ns >= target),
            len(self._items),
        )

    # --- the drive loop (D-08 pacing + D-09 step/loop/DONE + WR-01/WR-02 bound, W4 ordering) ---
    def run(self) -> None:
        """Drive the schedule until PAUSED (after a step), DONE, or a bound trips.

        For each published item beyond the first, sleep the inter-message ``Δt`` scaled by
        ``rate`` (D-08; ``time.sleep``, never a busy-wait — Pitfall 5). After each publish the
        bounded-stop guards (``max_messages`` / ``duration``, both ``is not None`` — WR-01/WR-02)
        fire BEFORE the end-of-stream loop-reset, so a bound landing exactly on the last item
        wins over ``loop`` (DONE wins over loop-reset — the W4 boundary).
        """
        start_clock = self._clock()
        published = 0
        # A zero-publish bound (max_messages=0, WR-01) or duration<=0 must halt BEFORE the
        # first publish — check it up front. Also covers seek-past-end (cursor==len below).
        if self._max_messages is not None and published >= self._max_messages:
            self._state = State.DONE
            return
        if self._duration is not None and (self._clock() - start_clock) >= self._duration:
            self._state = State.DONE
            return
        while self._state in (State.PLAYING, State.STEPPING) and self._cursor < len(self._items):
            if self._cursor > 0:
                dt_ns = self._items[self._cursor].t_ns - self._items[self._cursor - 1].t_ns
                self._sleep(max(0.0, dt_ns / 1e9 / self._rate))
            stepping = self._state is State.STEPPING
            self._sink(self._items[self._cursor])
            self._cursor += 1
            published += 1
            # Bound checks fire BEFORE the loop-reset (W4): DONE wins over loop=True's wrap.
            if self._max_messages is not None and published >= self._max_messages:
                self._state = State.DONE
                return
            if self._duration is not None and (self._clock() - start_clock) >= self._duration:
                self._state = State.DONE
                return
            if stepping:
                self._state = State.PAUSED  # step = one-then-pause (D-09)
                return
            if self._cursor >= len(self._items):
                if self.loop:
                    # loop restart (D-09): rewind to index 0, NOT the last seek target (WR-02).
                    self._cursor = 0
                else:
                    self._state = State.DONE  # clean end (D-09)
        else:
            # The while body never ran because the cursor was already at end-of-stream
            # (e.g. seek-past-end) while PLAYING/STEPPING: reach a clean DONE, no IndexError.
            if self._state in (State.PLAYING, State.STEPPING) and self._cursor >= len(self._items):
                self._state = State.DONE
