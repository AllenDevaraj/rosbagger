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

import bisect
import threading
import time
from collections.abc import Callable
from enum import Enum

# A CPU-friendly republish cadence for a DEGENERATE zero-span loop (newD13): a one-message
# bag, or a stream whose timestamps are all equal, has no inter-message Δt to pace by, so a
# loop wrap would republish as fast as the CPU allows (100% busy-spin). When that case is
# detected the wrap republish is floored to this many seconds (scaled by ``rate``) — a steady,
# low cadence instead of a spin. Normal multi-item pacing never touches this.
_DEGENERATE_LOOP_PERIOD_S = 0.1


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

    Thread-safety (Phase 18, REP-02):
        :meth:`run` is meant to be driven on a worker thread while another thread (the
        desktop UI thread) issues transport commands LIVE — seek / set_rate / pause / play /
        step / ``loop=`` mid-playback. A ``threading.Lock`` guards the small mutate/advance
        critical sections so the cursor's read-modify-write in :meth:`run` cannot race a
        concurrent :meth:`seek` (the lost-update bug). The lock is NEVER held across the
        ``sink`` publish or the inter-message wait, so a live control is never blocked behind
        a slow publish or a long pacing gap. A ``threading.Event`` (``_wake``) makes the
        DEFAULT pacing wait interruptible: a setter wakes it so the new command takes effect
        promptly instead of after the full Δt. The control API stays fully SYNCHRONOUS —
        ``seek()`` then reading ``cursor`` reflects the jump immediately, exactly as before —
        so every Phase-13 single-threaded test is unaffected. The introspection reads
        (``state`` / ``cursor`` / ``position_fraction`` / ``rate``) are single-attribute and
        lock-free (atomic in CPython; acceptable for a UI poll).
    """

    def __init__(
        self,
        items,
        sink: Callable[[object], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
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
        # Thread-safety primitives (Phase 18): a lock guarding the cursor/state/rate
        # mutate+advance critical sections, and a wake Event that makes the DEFAULT pacing
        # wait interruptible (a setter sets it to cut a long inter-message gap short).
        self._lock = threading.Lock()
        self._wake = threading.Event()
        # Keep ``sleep`` injectable (the whole Phase-13 suite passes a recording sleep). Only
        # when the caller does NOT override it does production get the interruptible default —
        # so an injected recording sleep is still honored verbatim (T-18-01-C).
        self._sleep = sleep if sleep is not None else self._interruptible_sleep
        self._rate = rate
        self._loop = loop
        self._max_messages = max_messages
        self._duration = duration
        self._cursor = 0
        self._state = State.PAUSED
        # In/out region loop (Phase 19, REP-03) — ABSOLUTE t_ns bounds (None = no region). When
        # BOTH are set, run() wraps the cursor from the item past _loop_out_ns back to the first
        # item at/after _loop_in_ns (a snippet on repeat), DISTINCT from the whole-bag _loop
        # (which rewinds to index 0). Absolute t_ns so it shares position_fraction's basis.
        self._loop_in_ns: int | None = None
        self._loop_out_ns: int | None = None

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
    def position_fraction(self) -> float:
        """The cursor's position as a TIME fraction of the bag span, in ``[0.0, 1.0]``.

        Derived from the cursor item's ``t_ns`` relative to the bag span
        (``items[-1].t_ns - items[0].t_ns``) — NOT the index — so it agrees with the
        time-fraction basis ``seek`` and the event markers use (WR-01). An empty stream,
        a zero-span (single timestamp) bag, or a cursor at/past end-of-stream all return
        ``1.0``-or-``0.0`` cleanly without an IndexError or a divide-by-zero.
        """
        if not self._items:
            return 0.0
        if self._cursor >= len(self._items):
            return 1.0
        span = self._items[-1].t_ns - self._items[0].t_ns
        if span <= 0:
            return 0.0
        return min(1.0, (self._items[self._cursor].t_ns - self._items[0].t_ns) / span)

    @property
    def rate(self) -> float:
        """The current schedule scale (always ``> 0``)."""
        return self._rate

    @property
    def loop(self) -> bool:
        """Whether end-of-stream rewinds to index 0 (``True``) or reaches DONE (``False``).

        A plain bool, but exposed as a property so the setter can mutate it under the lock +
        wake the pacing wait (Phase 18) — a live ``replayer.loop = x`` toggle from the UI
        thread is then race-free against ``run()``'s end-of-stream read, while
        ``replayer.loop = x`` reads exactly like the former public attribute.
        """
        return self._loop

    @loop.setter
    def loop(self, value: bool) -> None:
        with self._lock:
            self._loop = bool(value)
        self._wake.set()

    @property
    def loop_region(self) -> tuple[int, int] | None:
        """The active loop region as ``(in_ns, out_ns)`` ABSOLUTE t_ns, or ``None`` (Phase 19).

        Returns the stored absolute bounds (``set_loop_region`` takes bag-relative offsets and
        adds ``items[0].t_ns`` — newD9). Lock-free single read (the setters always set/clear both
        bounds together, so this is a both-or-neither check). When a region is set, ``run()``
        wraps a snippet on repeat instead of reaching the whole-bag end; see
        :meth:`set_loop_region`.
        """
        if self._loop_in_ns is not None and self._loop_out_ns is not None:
            return (self._loop_in_ns, self._loop_out_ns)
        return None

    # --- pacing wait (interruptible default — Phase 18) ---
    def _interruptible_sleep(self, seconds: float) -> None:
        """The DEFAULT inter-message wait: block up to ``seconds`` OR until a setter wakes us.

        ``time.sleep`` would block the worker for the FULL inter-message Δt even if the UI
        thread issued a pause/seek/rate change a millisecond in — the control would not take
        effect until the gap elapsed. Waiting on ``self._wake`` instead lets any lock-guarded
        setter (which calls ``self._wake.set()``) cut the wait short, so the command lands
        promptly; ``run()`` then re-reads state after the wait and honors it. The flag is
        CLEARED by ``run()`` under the lock at the top of each iteration (NOT here) so a setter
        that fires during this wait — after that clear — reliably interrupts it; clearing here
        instead would race the clear against the next iteration's pending set. An injected
        ``sleep`` bypasses this entirely (T-18-01-C) — only the unset default is interruptible.
        """
        self._wake.wait(timeout=seconds)

    # --- the six controls (D-07); all lock-guarded + wake the pacing wait (Phase 18) ---
    def play(self) -> None:
        """Resume publishing from the held cursor (-> PLAYING)."""
        with self._lock:
            self._state = State.PLAYING
        self._wake.set()

    def pause(self) -> None:
        """Stop publishing but HOLD the cursor (-> PAUSED); a later play()+run() resumes."""
        with self._lock:
            self._state = State.PAUSED
        self._wake.set()

    def step(self) -> None:
        """Arm a single-step: the next run() publishes EXACTLY one item then re-pauses (D-09)."""
        with self._lock:
            self._state = State.STEPPING
        self._wake.set()

    def set_rate(self, x: float) -> None:
        """Set the schedule scale; ``x <= 0`` raises ValueError (no busy-wait / div-by-zero)."""
        if x <= 0:
            raise ValueError("rate must be > 0")
        with self._lock:
            self._rate = x
        self._wake.set()

    def seek(self, t_offset_ns: int) -> None:
        """Jump the cursor to the first item at/after a bag-relative time (D-09, W3).

        Sets the cursor to the first index ``i`` with
        ``items[i].t_ns >= items[0].t_ns + t_offset_ns``; intervening items are skipped
        WITHOUT publishing. Seeking past the last timestamp lands ``cursor == len(items)``
        (run() then reaches DONE without publishing — no IndexError, Pitfall 6). This is the
        ONLY position-setter (W3).

        Lock-guarded + wakes the pacing wait (Phase 18) so a seek issued WHILE ``run()`` is
        executing on another thread lands atomically against the drive loop's cursor advance
        (the advance uses a cursor-unchanged guard so this jump is never clobbered).
        """
        with self._lock:
            t0 = self._items[0].t_ns if self._items else 0
            self._cursor = self._first_index_at_or_after(t0 + t_offset_ns)
        self._wake.set()

    # --- region loop (Phase 19, REP-03); lock-guarded + wake, the Phase-18 contract ---
    def set_loop_region(self, in_ns: int, out_ns: int) -> None:
        """Set the in/out loop region to BAG-RELATIVE offsets (a snippet to repeat, D-09 / REP-03).

        ``in_ns`` / ``out_ns`` are offsets from the bag start (``items[0].t_ns``), the SAME basis
        :meth:`seek` uses — they are converted to absolute t_ns internally (``items[0].t_ns`` is
        added). This consistency fixes newD9: both callers (the CLI's ``region_start*1e9`` and the
        desktop's ``frac*bag_span_ns``) pass bag-relative offsets, but the region setter formerly
        stored them as ABSOLUTE and ``run()`` compared them against the absolute ``items[*].t_ns``
        — so on a real bag (t0 = a large ROS stamp) ``items[cursor].t_ns > out`` was always true
        and the cursor wrapped after every publish. Fixture streams started at t0==0, masking it.

        Normalizes so the lower value is the in-bound (``set_loop_region(500, 200)`` ==
        ``set_loop_region(200, 500)``). When a region is set, ``run()`` wraps the cursor from the
        item past the out-bound back to the first item at/after the in-bound — DISTINCT from the
        whole-bag :attr:`loop` (index-0 rewind), and taking PRECEDENCE over it when both are on.
        Lock-guarded + wakes the pacing wait so a region set WHILE ``run()`` executes on another
        thread is honored at the next advance with no data race (the Phase-18 contract).
        """
        t0 = self._items[0].t_ns if self._items else 0
        lo, hi = (in_ns, out_ns) if in_ns <= out_ns else (out_ns, in_ns)
        with self._lock:
            self._loop_in_ns = t0 + lo
            self._loop_out_ns = t0 + hi
        self._wake.set()

    def clear_loop_region(self) -> None:
        """Clear the loop region; ``run()`` reverts to the whole-bag loop/DONE branch (Phase 19).

        Lock-guarded + wakes (the Phase-18 contract) so clearing mid-run is race-free.
        """
        with self._lock:
            self._loop_in_ns = None
            self._loop_out_ns = None
        self._wake.set()

    # --- internal helpers (cursor resolution + degenerate-loop detection) ---
    def _first_index_at_or_after(self, t_ns: int) -> int:
        """Index of the first item with ``t_ns >= target`` (``len(items)`` if none) — O(log n).

        Items are non-decreasing in ``t_ns`` (``load_items`` time-orders them), so a binary
        search replaces the former O(n) linear ``next(i for ...)`` scan that ran UNDER the lock
        and stalled concurrent transport controls on a large bag (F4). ``bisect.bisect_left``
        with ``key=`` needs Python ≥3.10 (a project floor). Semantics are identical to the old
        scan, including the past-the-end ``len(items)`` landing (a clean DONE — Pitfall 6).
        """
        return bisect.bisect_left(self._items, t_ns, key=lambda it: it.t_ns)

    def _is_zero_span_loop(self) -> bool:
        """True when a loop is active over a stream with NO time span (newD13).

        A one-message bag, or a stream whose first and last timestamps are equal, has no
        inter-message Δt to pace by — so a loop wrap would republish with zero sleep and peg a
        CPU. Detect it (looping on AND ``items[-1].t_ns == items[0].t_ns``) so ``run()`` can
        floor the wrap cadence instead of busy-spinning. A non-looping or positive-span stream
        returns ``False`` and the normal Δt pacing is untouched.
        """
        looping = self._loop or self._loop_in_ns is not None
        if not looping or not self._items:
            return False
        return self._items[-1].t_ns == self._items[0].t_ns

    # --- the drive loop (D-08 pacing + D-09 step/loop/DONE + WR-01/WR-02 bound, W4 ordering) ---
    def run(self) -> None:
        """Drive the schedule until PAUSED (after a step), DONE, or a bound trips.

        For each published item beyond the first, sleep the inter-message ``Δt`` scaled by
        ``rate`` (D-08; ``time.sleep``, never a busy-wait — Pitfall 5). After each publish the
        bounded-stop guards (``max_messages`` / ``duration``, both ``is not None`` — WR-01/WR-02)
        fire BEFORE the end-of-stream loop-reset, so a bound landing exactly on the last item
        wins over ``loop`` (DONE wins over loop-reset — the W4 boundary).

        Thread-safety (Phase 18): the lock is held ONLY for the fast state/cursor/rate reads,
        the pacing-Δt computation, the cursor ADVANCE, and the bound/step/loop/DONE
        transitions — NEVER across ``self._sink(...)`` (the publish) or ``self._sleep(...)``
        (the wait), so a live UI-thread control is never blocked behind a slow publish or a
        long gap. The advance uses a cursor-unchanged guard so a concurrent :meth:`seek` that
        landed during the publish/wait is NOT clobbered back (the lost-update fix). State is
        re-read after the wait so a pause/seek/stop issued mid-gap is honored before the next
        publish. The single-threaded observable behavior is IDENTICAL to before — every
        Phase-13 test passes unchanged.
        """
        # A zero/negative bound (max_messages<=0, WR-01; duration<=0, WR-02) must halt BEFORE
        # the first publish. Special-case it up front WITHOUT re-reading the clock (WR-03): the
        # bound is then independent of how many times _clock() is called (a _FakeClock tick is
        # not consumed by this guard). The clock is read exactly once, after these guards.
        published = 0
        if self._max_messages is not None and self._max_messages <= 0:
            with self._lock:
                self._state = State.DONE
            return
        if self._duration is not None and self._duration <= 0:
            with self._lock:
                self._state = State.DONE
            return
        start_clock = self._clock()
        while True:
            # --- locked: read state/cursor, decide pacing, capture the snapshot ---
            with self._lock:
                # Clear any stale wake (e.g. play()'s set, or a setter from the previous
                # iteration) so the sleep we are about to compute waits afresh. Done UNDER the
                # lock so a setter racing this clear either (a) already mutated state we read
                # below, or (b) fires its set() after we release — interrupting the wait.
                self._wake.clear()
                state = self._state
                cursor = self._cursor
                if state not in (State.PLAYING, State.STEPPING):
                    break  # PAUSED/DONE (incl. seek-past-end's DONE, or a mid-run pause): stop
                if cursor >= len(self._items):
                    # Cursor already at end-of-stream while PLAYING/STEPPING (seek-past-end or
                    # an empty stream): clean DONE, no IndexError (Pitfall 6).
                    self._state = State.DONE
                    break
                # Pace ONLY while PLAYING (WR-01): a STEPPING single-advance publishes the next
                # item IMMEDIATELY (no pre-sleep) — stepping across a long gap must not block.
                do_pace = cursor > 0 and state is State.PLAYING
                sleep_s = 0.0
                if do_pace:
                    dt_ns = self._items[cursor].t_ns - self._items[cursor - 1].t_ns
                    sleep_s = max(0.0, dt_ns / 1e9 / self._rate)
                elif state is State.PLAYING and published > 0 and self._is_zero_span_loop():
                    # A loop wrap rewound the cursor to 0 on a ZERO-SPAN bag (one message, or all
                    # timestamps equal): there is no Δt, so the cursor>0 branch above never paces
                    # and the loop would republish at 100% CPU. Floor the wrap cadence (newD13).
                    # ``published > 0`` excludes the very first publish of this run() (no startup
                    # delay); the guard is False for any positive-span stream, so normal multi-
                    # item pacing — including a multi-item loop's instant wrap — is unchanged.
                    sleep_s = _DEGENERATE_LOOP_PERIOD_S / self._rate
                    do_pace = True

            # --- unlocked: pace, then re-read state so a mid-gap control is honored ---
            if do_pace:
                self._sleep(sleep_s)
                with self._lock:
                    state = self._state
                    cursor = self._cursor
                    if state not in (State.PLAYING, State.STEPPING):
                        break
                    if cursor >= len(self._items):
                        self._state = State.DONE
                        break

            stepping = state is State.STEPPING

            # --- unlocked: publish the captured item (cursor is a stable local index) ---
            self._sink(self._items[cursor])

            # --- locked: advance (cursor-unchanged guard), then bound/step/loop/DONE (W4) ---
            with self._lock:
                if self._cursor == cursor:
                    # No concurrent seek landed during the publish/wait — advance normally.
                    self._cursor = cursor + 1
                # else: a seek moved the cursor mid-publish; honor it (do NOT clobber).
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
                # Region loop (Phase 19) takes PRECEDENCE over the whole-bag _loop when a region
                # is set (a snippet is the more specific intent), but the bound guards above still
                # win over BOTH (W4 — DONE/bound beats any wrap). When NO region is set the
                # existing whole-bag _loop / DONE branch is UNCHANGED.
                if self._loop_in_ns is not None and self._loop_out_ns is not None:
                    # Wrap when we ran off the end OR the next item is past the region's out-bound.
                    if (
                        self._cursor >= len(self._items)
                        or self._items[self._cursor].t_ns > self._loop_out_ns
                    ):
                        # Jump back to the first item at/after the in-bound (the same bisect seek
                        # uses, F4). An in-bound past the end lands cursor == len -> DONE, so a
                        # region whose in-bound is past the stream never spins as a no-publish loop.
                        self._cursor = self._first_index_at_or_after(self._loop_in_ns)
                        if self._cursor >= len(self._items):
                            self._state = State.DONE
                    # else: keep playing forward toward the out-bound.
                elif self._cursor >= len(self._items):
                    if self._loop:
                        # loop restart (D-09): rewind to index 0, NOT the last seek target (WR-02).
                        self._cursor = 0
                    else:
                        self._state = State.DONE  # clean end (D-09)
