"""Replay panel (LIVE, D-09/D-09a) — a thin face over ``rosbagger-replay``.

LIVE PANEL (D-03): capability-gated. When ``rclpy`` is not importable the App sets
this widget ``disabled=True`` (in ``RosbaggerApp.on_mount``) and it shows a teaching
hint to source a ROS 2 environment; the transport controls below never run in that
state.

WHAT IT DOES (when ROS is available — the tier-1 gate enabled it in 14-02):

* **Build the transport once (D-09a — the SHARED publish path).** Lazily creates the
  panel's OWN ``rclpy`` context + node (guarding ``rclpy.ok()`` and only
  initialising/shutting down the context the panel created — the re-entrant-safe WR-04
  discipline ``replay.py`` uses), builds ``sink, published = build_publish_sink(node)``
  (the SINGLE Plan-14-01 publish sink — the panel inlines none of the publisher-build
  / message-deserialise mechanics), loads ``items = load_items(bag, ...)``, and
  constructs the pure ``Replayer(items, sink, ...)``. There is no second publish path.
* **Six transport controls over the pure ``Replayer`` (D-07).** Play / Pause / Step
  buttons, a rate ``Input`` (``set_rate``), and a loop ``Switch`` (``replayer.loop``)
  forward straight to the scheduler's controls; a scrubber click maps a fraction onto
  ``replayer.seek(int(fraction * bag_span_ns))`` (``seek`` is the only position-setter,
  W3). ``bag_span`` is ``items[-1].t_ns - items[0].t_ns``.
* **Drive loop in a thread worker (Pitfall 1 / T-14-06-01).** ``Replayer.run()`` (the
  BLOCKING drive loop) runs in a ``@work(exclusive=True, thread=True)`` worker so the
  event loop never blocks; Play (re)starts the worker, Pause/Step set the scheduler
  state and (for Step) run the worker once (one-then-pause). The worker polls
  ``replayer.state``/``replayer.cursor`` and pushes the scrubber ``position`` back to
  the UI thread via ``self.app.call_from_thread``. ``State.DONE`` / ``cursor ==
  len(items)`` is end-of-track (Pitfall 6); a loop wrap rewinds to index 0, not the
  last seek (WR-02) — both owned by the scheduler contract.
* **Jump-to-event markers (D-09).** Lazily reads ``list_events(bag)`` and maps each
  row to a ``(fraction, label)`` via ``(t_start_ns - bag_start_ns) / span`` (14-RESEARCH
  Code Example 4), setting them on the scrubber; a marker click seeks to that event's
  time (same fraction -> ``seek`` mapping).

OFFLINE-IMPORT INVARIANT (D-03 / Pitfall 2 / T-14-06-03): this module's TOP LEVEL
imports ONLY ``textual`` (+ ``__future__`` + the pure ``Scrubber`` widget). EVERY
``rosbagger_replay`` / ``rclpy`` / ``rosbagger_core.events`` import lives INSIDE a
worker / method body — ``import rosbagger_gui.panels.replay`` pulls no ``rclpy`` /
``rosbag2_py``. The teaching capability errors (``RosNotAvailableError`` /
``NoMessagesToReplayError``) are caught and surfaced on the status line (D-09),
never a traceback.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Input, Static, Switch
from textual.worker import get_current_worker

from rosbagger_gui.widgets import Scrubber

REPLAY_HINT = "Source your ROS 2 environment to enable live replay (rosbagger-replay)."

# Default schedule rate (D-08). The rate Input parses to a float > 0; an invalid entry
# is rejected with a teaching status (never a ZeroDivisionError / busy-wait — the
# scheduler validates > 0 too).
_DEFAULT_RATE = "1.0"


class ReplayPanel(Widget):
    """Replay view — publish a bag to live ROS topics with transport controls (live)."""

    def compose(self) -> ComposeResult:
        """The status line, the scrubber timeline, and the transport control strip."""
        yield Static(REPLAY_HINT, id="replay-status")
        yield Scrubber(id="replay-scrubber")
        yield Button("Play", id="replay-play", variant="success")
        yield Button("Pause", id="replay-pause")
        yield Button("Step", id="replay-step")
        yield Input(value=_DEFAULT_RATE, placeholder="rate (>0)", id="replay-rate")
        yield Switch(value=False, id="replay-loop")

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # The pure Replayer + its own rclpy context/node, built lazily on first Play
        # (all ROS objects — never touched at import). _published is the shared
        # source-of-truth count dict from build_publish_sink.
        self._replayer: object | None = None
        self._node: object | None = None
        self._created_ctx: bool = False
        self._published: dict[str, int] | None = None
        self._bag_span_ns: int = 0
        self._item_count: int = 0

    # ----------------------------------------------------------------- lifecycle

    def on_show(self) -> None:
        """Source the event markers when the panel becomes the active view (D-09)."""
        if not getattr(self.app, "ros_available", False):
            self._show_status(REPLAY_HINT)
            return
        if self._bag_path() is None:
            self._show_status("Open a bag to replay (no bag loaded).")
            return
        self._load_markers()

    def on_unmount(self) -> None:
        """Tear down the panel's own rclpy context on shutdown (best-effort, WR-05)."""
        self._teardown_transport()

    # ----------------------------------------------------------------- bag/source

    def _bag_path(self) -> object | None:
        """The single shared bag path from the App's reader (D-02), or ``None``.

        ``RosbagsReader.paths`` is callable before open and returns a copy; the App
        owns exactly one reader, so the first path is the bag to replay.
        """
        reader = getattr(self.app, "reader", None)
        if reader is None:
            return None
        paths = reader.paths
        return paths[0] if paths else None

    # --------------------------------------------------------------- transport build

    def _ensure_transport(self) -> bool:
        """Build the pure Replayer + shared sink in the panel's OWN rclpy context (D-09a).

        Idempotent: once built, returns ``True`` immediately. Lazily imports
        ``rosbagger_replay`` (the package front door) + ``rclpy`` INSIDE this body (the
        offline invariant). Creates the panel's own context (only initialising it when
        we created it — the re-entrant-safe WR-04 guard), builds the SHARED
        ``build_publish_sink`` (no inlined publish mechanics), loads the items, and
        constructs the ``Replayer``. Returns ``False`` (with a teaching status) on a
        capability error or an empty/missing bag.
        """
        if self._replayer is not None:
            return True

        bag = self._bag_path()
        if bag is None:
            self._show_status("Open a bag to replay (no bag loaded).")
            return False

        # newD16: validate the rate BEFORE building any ROS context — a bad/<=0 entry teaches
        # here and refuses to build, instead of the old _read_rate() silently coercing it to 1.0
        # and Play reporting "rate 1". (Done before rclpy.init() so a bad rate never leaves a
        # half-built context behind — the WR-04 clean-teaching discipline.)
        try:
            rate = self._parse_rate()
        except ValueError:
            raw = self.query_one("#replay-rate", Input).value.strip()
            self._show_status(f"Invalid rate {raw!r}: enter a number > 0.")
            return False

        import rclpy

        from rosbagger_replay import (
            NoMessagesToReplayError,
            Replayer,
            RosNotAvailableError,
            build_publish_sink,
            load_items,
        )

        try:
            items = load_items(bag)
            if not items:
                raise NoMessagesToReplayError(bag_paths=bag, topics=None)

            # WR-04: only manage the context WE create — a re-entrant caller may already
            # have one. init only if absent; remember whether we created it so teardown
            # only shuts down our own context.
            self._created_ctx = not rclpy.ok()
            if self._created_ctx:
                rclpy.init()
            self._node = rclpy.create_node("rosbagger_gui_replayer")
            # The SINGLE production publish sink (D-09a) — same mechanics replay() drives.
            sink, self._published = build_publish_sink(self._node)
            loop_on = self.query_one("#replay-loop", Switch).value
            self._replayer = Replayer(items, sink, rate=rate, loop=loop_on)
            self._item_count = len(items)
            self._bag_span_ns = items[-1].t_ns - items[0].t_ns
        except RosNotAvailableError as exc:
            self._show_status(str(exc))
            self._teardown_transport()
            return False
        except NoMessagesToReplayError as exc:
            self._show_status(str(exc))
            self._teardown_transport()
            return False
        except Exception as exc:  # noqa: BLE001 - surface any live build failure as teaching text
            self._show_status(f"Replay setup failed: {exc}")
            self._teardown_transport()
            return False
        return True

    def _teardown_transport(self) -> None:
        """Best-effort destroy the node + shut down only our own context (WR-04/WR-05)."""
        import contextlib

        node = self._node
        created = self._created_ctx
        self._replayer = None
        self._node = None
        self._published = None
        self._created_ctx = False
        if node is not None:
            with contextlib.suppress(Exception):
                node.destroy_node()
        if created:
            import rclpy

            with contextlib.suppress(Exception):
                rclpy.shutdown()

    # ------------------------------------------------------------------- controls

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route Play / Pause / Step to the pure Replayer + the drive worker."""
        if not getattr(self.app, "ros_available", False):
            return
        if event.button.id == "replay-play":
            self._play()
        elif event.button.id == "replay-pause":
            self._pause()
        elif event.button.id == "replay-step":
            self._step()

    def _drive_running(self) -> bool:
        """True while a ``replay-run`` drive worker is mid-flight (WR-06 guard).

        The pure ``Replayer`` is a non-thread-safe state machine and the drive worker is
        ``exclusive=True`` — issuing a second Play/Step while ``run()`` executes on the
        worker thread would (a) cancel the in-flight playback worker and (b) mutate
        ``self._state`` from the UI thread while ``run()`` reads it on the worker thread,
        an undefined interleaving. So Play/Step are only issued BETWEEN run segments: a
        control pressed while a worker runs is ignored with a teaching status. Pause is
        still allowed (it asks the running loop to stop at the next boundary).
        """
        return any(w.group == "replay-run" and w.is_running for w in self.workers)

    def _play(self) -> None:
        """Resume publishing from the held cursor (-> PLAYING) and (re)start the worker."""
        if self._drive_running():
            self._show_status("Already playing — pause before issuing a new control.")
            return
        if not self._ensure_transport():
            return
        self._replayer.play()  # type: ignore[union-attr]
        # Report the Replayer's ACTUAL rate (validated at build), not a re-read of the box (newD16).
        rate = self._replayer.rate  # type: ignore[union-attr]
        self._show_status(f"Playing… ({self._item_count} msg, rate {rate:g})")
        self._drive_worker()

    def _pause(self) -> None:
        """Pause publishing but HOLD the cursor (-> PAUSED). The worker returns on its own."""
        if self._replayer is None:
            return
        self._replayer.pause()  # type: ignore[union-attr]
        self._show_status("Paused.")

    def _step(self) -> None:
        """Arm a single-step (publish exactly one item then re-pause, D-09) + run once."""
        if self._drive_running():
            self._show_status("Pause before stepping (a play worker is running).")
            return
        if not self._ensure_transport():
            return
        self._replayer.step()  # type: ignore[union-attr]
        self._show_status("Stepped one message.")
        self._drive_worker()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply a new schedule rate when the rate Input is submitted (set_rate, D-08).

        Parse the raw entry ONCE and branch on validity (WR-02): a non-numeric or ``<= 0``
        entry is REJECTED with a teaching status (never silently coerced to 1.0). The
        scheduler's ``set_rate`` is the single validator (it raises ``ValueError`` on
        ``<= 0``), so ``abc`` or ``-2`` teaches instead of resetting to 1 and reporting it
        as a successful "Rate set to 1.".
        """
        if event.input.id != "replay-rate":
            return
        if self._replayer is None:
            return
        raw = self.query_one("#replay-rate", Input).value.strip()
        try:
            rate = float(raw)
            self._replayer.set_rate(rate)  # type: ignore[union-attr]  # raises ValueError on <= 0
        except ValueError:
            self._show_status(f"Invalid rate {raw!r}: enter a number > 0.")
            return
        self._show_status(f"Rate set to {rate:g}.")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Forward the loop toggle to ``replayer.loop`` (D-09; wrap rewinds to 0, WR-02)."""
        if event.switch.id != "replay-loop":
            return
        if self._replayer is not None:
            self._replayer.loop = event.value  # type: ignore[union-attr]

    def _parse_rate(self) -> float:
        """Parse the rate Input to a float > 0, raising ValueError on a bad/``<=0`` entry (newD16).

        The SINGLE rate-parse contract for the build path: ``_ensure_transport`` calls it so a bad
        rate teaches on Play/Step (and refuses to build) instead of the old ``_read_rate`` silently
        coercing it to 1.0 and ``_play`` reporting ``"Playing… rate 1"`` — a quiet wrong-rate. The
        Enter handler already validated via the scheduler's ``set_rate``; this closes the build
        path the same way the desktop panel's ``_validated_rate`` does. The scheduler enforces
        ``> 0`` too, so this is the widget-edge guard with a teaching message.
        """
        raw = self.query_one("#replay-rate", Input).value.strip()
        rate = float(raw)  # ValueError on a non-numeric entry
        if rate <= 0:
            raise ValueError("rate must be > 0")
        return rate

    # ----------------------------------------------------------------- scrubber/seek

    def on_scrubber_seeked(self, event: Scrubber.Seeked) -> None:
        """A scrubber/marker click maps a fraction onto ``replayer.seek`` (D-09, W3).

        ``seek`` is the ONLY position-setter: fraction -> bag-relative nanoseconds. A
        seek-past-end lands ``cursor == len(items)`` (a clean DONE — Pitfall 6).
        """
        if not self._ensure_transport():
            return
        t_offset_ns = int(event.fraction * self._bag_span_ns)
        self._replayer.seek(t_offset_ns)  # type: ignore[union-attr]
        self._update_position()
        self._show_status(f"Seeked to {event.fraction * 100:.0f}% of the bag.")

    def _update_position(self) -> None:
        """Reflect the Replayer cursor onto the scrubber playhead (UI-thread helper).

        Uses the Replayer's TIME-fraction accessor (``position_fraction``, WR-01) — NOT
        the index — so the playhead agrees with the time-fraction basis the seek mapping
        (``fraction * bag_span_ns``) and the event markers ``(t - bag_start) / span`` use.
        On a non-uniform bag the index basis drifted off the markers; time keeps them aligned.
        """
        if self._replayer is None or self._item_count == 0:
            return
        fraction = self._replayer.position_fraction  # type: ignore[union-attr]
        self.query_one("#replay-scrubber", Scrubber).position = fraction

    # --------------------------------------------------------------- event markers

    def _load_markers(self) -> None:
        """Read the event sidecar and overlay jump-to-event markers on the scrubber (D-09).

        Lazily imports ``list_events`` (the offline-safe events I/O) INSIDE this body and
        maps each row to a ``(fraction, label)`` via the 14-RESEARCH Code Example 4
        formula ``(t_start_ns - bag_start_ns) / max(1, span)``. ``bag_start_ns`` /
        ``span`` come from the same items the transport uses (built lazily). On any read
        failure the markers are simply left empty — markers are an aid, not a gate.
        """
        bag = self._bag_path()
        if bag is None:
            return
        try:
            from rosbagger_core.events import list_events

            table = list_events(bag)
            if table.num_rows == 0:
                self.query_one("#replay-scrubber", Scrubber).set_markers([])
                return

            # bag_start_ns / span come from load_items(bag) ALONE (WR-04): merely viewing
            # the Replay tab must NOT build the publish transport (rclpy.init + node +
            # publishers) — that stays lazy on first Play/Step/seek per the panel contract.
            # The marker fractions need only the item timestamps, which load_items provides
            # without any ROS context, so they line up with the seek mapping all the same.
            from rosbagger_replay import load_items

            items = load_items(bag)
            if not items:
                return
            bag_start_ns = items[0].t_ns
            span = max(1, items[-1].t_ns - bag_start_ns)

            starts = table.column("t_start_ns").to_pylist()
            labels = table.column("label").to_pylist()
            marks = [
                ((start - bag_start_ns) / span, str(label))
                for start, label in zip(starts, labels, strict=False)
            ]
            self.query_one("#replay-scrubber", Scrubber).set_markers(marks)
        except Exception:  # noqa: BLE001 - markers are an aid; a sidecar read failure never crashes the panel
            return

    # --------------------------------------------------------------- the drive loop

    @work(exclusive=True, thread=True, group="replay-run")
    def _drive_worker(self) -> None:
        """THREAD worker: drive ``Replayer.run()`` off the event loop (Pitfall 1 / T-14-06-01).

        ``run()`` is the BLOCKING scheduler drive loop; running it in a
        ``@work(thread=True)`` worker keeps the TUI responsive (transport methods fire
        from the UI handlers between run segments). After ``run()`` returns (PAUSED after
        a step, DONE at end-of-track, or a bound trip) the final cursor position + a
        terminal status are pushed back to the UI thread via ``call_from_thread``
        (thread-safe widget updates). ``State.DONE`` / ``cursor == len(items)`` is
        end-of-track (Pitfall 6); a loop wrap rewinds to 0 (WR-02) — both per the
        scheduler contract, not re-implemented here.
        """
        replayer = self._replayer
        if replayer is None:
            return

        from rosbagger_replay import Replayer  # noqa: F401 - bind for the State import below
        from rosbagger_replay.scheduler import State

        worker = get_current_worker()
        try:
            replayer.run()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - surface a drive-loop failure as teaching text, not a crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self._show_status, f"Replay failed: {exc}")
            return

        if worker.is_cancelled:
            return
        # Push the final playhead + a terminal status back to the UI thread.
        self.app.call_from_thread(self._update_position)
        if replayer.state is State.DONE:  # type: ignore[union-attr]
            published = self._published["n"] if self._published else 0
            self.app.call_from_thread(
                self._show_status, f"Done — published {published} message(s)."
            )

    # ----------------------------------------------------------------- ui helpers

    def _show_status(self, message: str) -> None:
        """Render ``message`` to the status line (UI-thread helper for ``call_from_thread``)."""
        self.query_one("#replay-status", Static).update(message)
