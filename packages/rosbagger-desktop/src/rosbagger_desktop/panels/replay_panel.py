"""Replay panel (LIVE, D-14) — a thin Qt face over ``rosbagger-replay``.

LIVE PANEL (D-09): capability-gated. When ``rclpy`` is not importable the ``MainWindow``
disables this panel's nav row with a teaching tooltip; the transport controls below skip. The
Qt analog of the TUI ``rosbagger_gui.panels.replay``, ported one-to-one into PySide6 widgets
+ a ``QThread`` drive worker.

WHAT IT DOES (when ROS is available — the gate enabled it):

* **Build the transport once (D-14 / D-05 — the SHARED publish path).** :meth:`_ensure_transport`
  is idempotent: it lazily imports ``rclpy`` + the ``rosbagger_replay`` front door, loads
  ``items = load_items(bag)`` (the bag is ``reader.paths[0]`` from the App's shared reader,
  D-02), creates the panel's OWN ``rclpy`` context only when ``not rclpy.ok()`` (the WR-04
  re-entrant-safe guard — record whether WE created it), builds
  ``sink, self._published = build_publish_sink(node)`` (the SINGLE production publish path,
  D-05 — the panel inlines NO publisher-build / deserialize mechanics), and constructs the
  pure ``Replayer(items, sink, rate=…, loop=…)``. ``self._bag_span_ns = items[-1].t_ns -
  items[0].t_ns``.
* **Six transport controls over the pure ``Replayer``.** Play / Pause / Step buttons, a rate
  line-edit (``set_rate`` on ``returnPressed`` — ``ValueError`` → teaching status, never a
  silent coerce), and a loop checkbox (``replayer.loop``) forward straight to the scheduler.
  A ``Scrubber.seeked(fraction)`` maps to ``replayer.seek(int(fraction * bag_span_ns))``
  (seek is the ONLY position-setter).
* **Drive loop on a QThread worker (Pitfall 1 / T-16-03-BLOCK).** ``Replayer.run()`` (the
  BLOCKING drive loop) runs on a :class:`~rosbagger_desktop.workers.BlockingWorker`; Play
  (re)starts it, Step runs it once. Play/Step are guarded by :meth:`_drive_running` (a
  teaching status while a drive worker runs — Pitfall 7 / WR-06; Pause stays allowed). After
  ``run()`` returns, a UI-thread slot pushes the final ``position_fraction`` onto the scrubber
  and a terminal status (published count at ``State.DONE``).
* **Jump-to-event markers (D-14).** :meth:`_load_markers` (on show, when ros_available + a
  bag) lazily reads ``list_events(bag)`` + ``load_items(bag)`` and maps each row to
  ``((t_start_ns - bag_start_ns) / max(1, span), label)`` on the scrubber; any read failure
  leaves markers empty (an aid, not a gate).

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): this module's TOP LEVEL imports ONLY PySide6 +
stdlib + the local ``Scrubber`` / ``workers`` symbols. EVERY ``rosbagger_replay`` / ``rclpy``
/ ``rosbagger_core.events`` import lives INSIDE a method / worker body — ``import
rosbagger_desktop.panels.replay_panel`` pulls no ``rclpy`` / ``rosbag2_py``.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..widgets import Scrubber, set_status
from ..workers import BlockingWorker, run_on_thread, stop_thread

REPLAY_HINT = "Source your ROS 2 environment to enable live replay (rosbagger-replay)."

# Default schedule rate (D-08). The rate line-edit parses to a float > 0; an invalid entry is
# rejected with a teaching status (never a ZeroDivisionError / busy-wait — the scheduler
# validates > 0 too, raising ValueError on <= 0).
_DEFAULT_RATE = "1.0"


class ReplayPanel(QWidget):
    """Replay view — publish a bag to live ROS topics with transport controls (live, D-14)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status line, scrubber, and the six-control transport strip."""
        super().__init__(parent)

        # The pure Replayer + its own rclpy context/node, built lazily on first Play/Step/seek
        # (all ROS objects — never touched at import). _published is the shared
        # source-of-truth count dict from build_publish_sink.
        self._replayer: object | None = None
        self._node: object | None = None
        self._created_ctx: bool = False
        self._published: dict[str, int] | None = None
        self._bag_span_ns: int = 0
        self._item_count: int = 0
        # Kept drive-thread ref (Pitfall 2 — the GC must not collect a live thread).
        self._drive_thread: QThread | None = None

        # Status line as an accessibly-named region (D-02 a11y parity); a stable objectName lets
        # the shared status helper restore it after an error toggle and the theme style it.
        self._status = QLabel(REPLAY_HINT)
        self._status.setObjectName("replay_status")
        self._status.setAccessibleName("Replay status")
        self._status.setAccessibleDescription(REPLAY_HINT)
        self._status.setProperty("heading", True)
        self._scrubber = Scrubber()

        self._play_button = QPushButton("Play")
        self._pause_button = QPushButton("Pause")
        self._step_button = QPushButton("Step")
        self._rate_input = QLineEdit(_DEFAULT_RATE)
        self._rate_input.setPlaceholderText("rate (>0)")
        self._loop_checkbox = QCheckBox("loop")
        control_bar = QHBoxLayout()
        control_bar.addWidget(self._play_button)
        control_bar.addWidget(self._pause_button)
        control_bar.addWidget(self._step_button)
        control_bar.addWidget(QLabel("rate:"))
        control_bar.addWidget(self._rate_input)
        control_bar.addWidget(self._loop_checkbox)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._scrubber)
        layout.addLayout(control_bar)
        layout.addStretch(1)

        self._play_button.clicked.connect(self._play)
        self._pause_button.clicked.connect(self._pause)
        self._step_button.clicked.connect(self._step)
        self._rate_input.returnPressed.connect(self._apply_rate)
        self._loop_checkbox.toggled.connect(self._apply_loop)
        self._scrubber.seeked.connect(self._on_seeked)

    # ------------------------------------------------------------------ accessors

    @property
    def status_label(self) -> QLabel:
        """The status/teaching line (tests assert the transport + terminal messages here)."""
        return self._status

    @property
    def scrubber(self) -> Scrubber:
        """The timeline scrubber (playhead + event markers; user input → seek fraction)."""
        return self._scrubber

    @property
    def play_button(self) -> QPushButton:
        """The Play button (tests click it to drive a real ``Replayer.run()``)."""
        return self._play_button

    @property
    def pause_button(self) -> QPushButton:
        """The Pause button."""
        return self._pause_button

    @property
    def step_button(self) -> QPushButton:
        """The Step button (publish exactly one item then re-pause)."""
        return self._step_button

    @property
    def rate_input(self) -> QLineEdit:
        """The rate line-edit (parses to a float > 0 via the scheduler's ``set_rate``)."""
        return self._rate_input

    @property
    def loop_checkbox(self) -> QCheckBox:
        """The loop checkbox (forwards to ``replayer.loop``)."""
        return self._loop_checkbox

    # ------------------------------------------------------------------ lifecycle

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Source the event markers when the panel becomes the active stacked view (D-14)."""
        super().showEvent(event)
        if not self._ros_available():
            set_status(self._status, REPLAY_HINT, is_error=True)
            return
        if self._bag_path() is None:
            set_status(self._status, "Open a bag to replay (no bag loaded).", is_error=True)
            return
        self._load_markers()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Stop the drive thread + tear down the panel's own rclpy context (Pitfalls 2 / WR-05)."""
        stop_thread(self._drive_thread)
        self._teardown_transport()
        super().closeEvent(event)

    def _ros_available(self) -> bool:
        """Whether the window reports a sourced ROS 2 environment (D-09 gate input)."""
        return bool(getattr(self.window(), "ros_available", False))

    # ------------------------------------------------------------------ bag/source

    def _bag_path(self) -> object | None:
        """The single shared bag path from the window's reader (D-02), or ``None``.

        ``RosbagsReader.paths`` is callable before open and returns a copy; the window owns
        exactly one reader, so the first path is the bag to replay.
        """
        reader = getattr(self.window(), "reader", None)
        if reader is None:
            return None
        paths = reader.paths
        return paths[0] if paths else None

    def _default_typestore(self) -> object | None:
        """The window's ROS-2-Humble typestore (Pitfall 5), or ``None`` with no window.

        A real ``rosbag2`` sqlite3 recording embeds no message definitions, so ``load_items``
        must be handed this typestore or ``rosbags`` raises "Bag contains no type definitions".
        The same channel as ``_bag_path`` / ``_ros_available`` — reach the window for the shared
        typestore the OFFLINE reader was built with, so replay deserializes identically (D-02).
        """
        return getattr(self.window(), "default_typestore", None)

    # --------------------------------------------------------------- transport build

    def _validated_rate(self) -> float | None:
        """Parse the rate line-edit to a float > 0, or set a teaching status and return ``None``.

        WR-06: ``_apply_rate`` (the returnPressed handler) REJECTS an invalid rate with a
        teaching status rather than silently coercing to 1.0, but the transport-build path used
        to silently coerce — so pressing Play with an invalid rate quietly played at 1.0 while
        the box showed the bad text. This is the SINGLE rate-parsing contract for the widget:
        both Enter and Play/Step go through the same validate-or-reject logic. A non-numeric or
        ``<= 0`` entry sets the teaching status and returns ``None`` (the caller refuses to
        build / play); a valid entry returns the float.
        """
        raw = self._rate_input.text().strip()
        try:
            value = float(raw)
        except ValueError:
            set_status(self._status, f"Invalid rate {raw!r}: enter a number > 0.", is_error=True)
            return None
        if value <= 0:
            set_status(self._status, f"Invalid rate {raw!r}: enter a number > 0.", is_error=True)
            return None
        return value

    def _ensure_transport(self) -> bool:
        """Build the pure Replayer + shared sink in the panel's OWN rclpy context (D-14/D-05).

        Idempotent: once built, returns ``True`` immediately. Lazily imports
        ``rosbagger_replay`` + ``rclpy`` INSIDE this body (the offline invariant). Creates the
        panel's own context (only initialising it when WE created it — the re-entrant-safe
        WR-04 guard), builds the SHARED ``build_publish_sink`` (no inlined publish mechanics,
        D-05), loads the items, and constructs the ``Replayer``. Returns ``False`` (with a
        teaching status) on a capability error, an empty/missing bag, OR an invalid rate.

        WR-06: the initial ``rate`` comes from :meth:`_validated_rate` (the SAME validate-or-reject
        contract as the Enter handler) — an invalid rate refuses to build the transport with a
        teaching status rather than silently coercing to 1.0. A seek (which calls this when the
        transport may not yet exist) therefore inherits the same rejection.
        """
        if self._replayer is not None:
            return True

        bag = self._bag_path()
        if bag is None:
            set_status(self._status, "Open a bag to replay (no bag loaded).", is_error=True)
            return False

        rate = self._validated_rate()
        if rate is None:  # _validated_rate set the teaching status (WR-06)
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
            items = load_items(bag, default_typestore=self._default_typestore())
            if not items:
                raise NoMessagesToReplayError(bag_paths=bag, topics=None)

            # WR-04: only manage the context WE create — a re-entrant caller may already have
            # one. init only if absent; remember whether we created it so teardown only shuts
            # down our own context.
            self._created_ctx = not rclpy.ok()
            if self._created_ctx:
                rclpy.init()
            self._node = rclpy.create_node("rosbagger_desktop_replayer")
            # The SINGLE production publish sink (D-05) — same mechanics replay() drives.
            sink, self._published = build_publish_sink(self._node)
            self._replayer = Replayer(items, sink, rate=rate, loop=self._loop_checkbox.isChecked())
            self._item_count = len(items)
            self._bag_span_ns = items[-1].t_ns - items[0].t_ns
        except RosNotAvailableError as exc:
            set_status(self._status, str(exc), is_error=True)
            self._teardown_transport()
            return False
        except NoMessagesToReplayError as exc:
            set_status(self._status, str(exc), is_error=True)
            self._teardown_transport()
            return False
        except Exception as exc:  # noqa: BLE001 - surface any live build failure as teaching text
            set_status(self._status, f"Replay setup failed: {exc}", is_error=True)
            self._teardown_transport()
            return False
        return True

    def _teardown_transport(self) -> None:
        """Best-effort destroy the node + shut down only our own context (WR-04/WR-05)."""
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

    def _drive_running(self) -> bool:
        """True while the drive worker is mid-flight (WR-06 / Pitfall 7 guard).

        The pure ``Replayer`` is a non-thread-safe state machine and there is ONE exclusive
        drive thread; issuing a second Play/Step while ``run()`` executes on the worker thread
        would mutate ``self._state`` from the UI thread while ``run()`` reads it on the worker
        thread — an undefined interleaving. So Play/Step are only issued BETWEEN run segments;
        a control pressed while the worker runs is ignored with a teaching status. Pause stays
        allowed (it asks the running loop to stop at the next boundary).
        """
        return self._drive_thread is not None and self._drive_thread.isRunning()

    def _play(self) -> None:
        """Resume publishing from the held cursor (→ PLAYING) and (re)start the drive worker."""
        if not self._ros_available():
            set_status(self._status, REPLAY_HINT, is_error=True)
            return
        if self._drive_running():
            set_status(
                self._status, "Already playing — pause before issuing a new control.", is_error=True
            )
            return
        if not self._ensure_transport():
            return
        self._replayer.play()  # type: ignore[union-attr]
        # WR-06: report the Replayer's ACTUAL rate (set_rate's validated value), not a re-read of
        # the raw input — the input and the running scheduler can no longer disagree.
        rate = self._replayer.rate  # type: ignore[union-attr]
        set_status(self._status, f"Playing… ({self._item_count} msg, rate {rate:g})")
        self._start_drive()

    def _pause(self) -> None:
        """Pause publishing but HOLD the cursor (→ PAUSED). The worker returns on its own."""
        if self._replayer is None:
            return
        self._replayer.pause()  # type: ignore[union-attr]
        set_status(self._status, "Paused.")

    def _step(self) -> None:
        """Arm a single-step (publish one item then re-pause, D-14) + run the worker once."""
        if not self._ros_available():
            set_status(self._status, REPLAY_HINT, is_error=True)
            return
        if self._drive_running():
            set_status(
                self._status, "Pause before stepping (a play worker is running).", is_error=True
            )
            return
        if not self._ensure_transport():
            return
        self._replayer.step()  # type: ignore[union-attr]
        set_status(self._status, "Stepped one message.")
        self._start_drive()

    def _apply_rate(self) -> None:
        """Apply a new schedule rate when the rate line-edit is submitted (set_rate, D-08).

        Parse the raw entry ONCE and branch on validity: a non-numeric or ``<= 0`` entry is
        REJECTED with a teaching status (never silently coerced to 1.0). The scheduler's
        ``set_rate`` is the single validator (it raises ``ValueError`` on ``<= 0``).

        CR-02: the ``Replayer`` is a non-thread-safe state machine; ``run()`` reads ``self._rate``
        every scheduler iteration on the worker thread, so mutating it from the UI thread
        mid-drive is an unsynchronized read/write — the exact race the Play/Step/seek guard was
        added to prevent. Guard this the same way (only mutate between run segments). The rate
        input is also disabled while ``_drive_running`` (belt-and-suspenders), so this guard is
        the second line of defence against a queued/late ``returnPressed``.
        """
        if self._replayer is None:
            return
        if self._drive_running():
            set_status(
                self._status,
                "Pause before changing the rate (a play worker is running).",
                is_error=True,
            )
            return
        # WR-06: the SAME validate-or-reject contract the Play/Step build path uses
        # (_validated_rate) — both paths agree on the widget's contract, never a silent coerce.
        rate = self._validated_rate()
        if rate is None:  # _validated_rate set the teaching status
            return
        self._replayer.set_rate(rate)  # type: ignore[union-attr]  # set_rate also rejects <= 0
        set_status(self._status, f"Rate set to {rate:g}.")

    def _apply_loop(self, checked: bool) -> None:
        """Forward the loop toggle to ``replayer.loop`` (D-14; wrap rewinds to 0, WR-02).

        CR-02: ``run()`` reads ``self.loop`` at the end-of-stream branch on the worker thread, so
        the UI thread must not write it mid-drive (same non-thread-safe-state-machine race as the
        rate). Guard it like the other transport controls — ignore the toggle with a teaching
        status while a drive worker runs. The checkbox is also disabled while ``_drive_running``.
        """
        if self._replayer is None:
            return
        if self._drive_running():
            set_status(
                self._status,
                "Pause before toggling loop (a play worker is running).",
                is_error=True,
            )
            return
        self._replayer.loop = checked  # type: ignore[union-attr]

    # ----------------------------------------------------------------- scrubber/seek

    def _on_seeked(self, fraction: float) -> None:
        """A scrubber/marker seek maps a fraction onto ``replayer.seek`` (D-14, the only setter).

        ``seek`` is the ONLY position-setter: fraction → bag-relative nanoseconds. A
        seek-past-end lands ``cursor == len(items)`` (a clean DONE). A seek while a drive
        worker runs is ignored with a teaching status (the Replayer is non-thread-safe; only
        mutate it between run segments — WR-06).
        """
        if self._drive_running():
            set_status(
                self._status, "Pause before seeking (a play worker is running).", is_error=True
            )
            return
        if not self._ensure_transport():
            return
        t_offset_ns = int(fraction * self._bag_span_ns)
        self._replayer.seek(t_offset_ns)  # type: ignore[union-attr]
        self._update_position()
        set_status(self._status, f"Seeked to {fraction * 100:.0f}% of the bag.")

    def _update_position(self) -> None:
        """Reflect the Replayer cursor onto the scrubber playhead (UI-thread helper).

        Uses the Replayer's TIME-fraction accessor (``position_fraction``) — NOT the index —
        so the playhead agrees with the time-fraction basis the seek mapping
        (``fraction * bag_span_ns``) and the event markers ``(t - bag_start) / span`` use.
        """
        if self._replayer is None or self._item_count == 0:
            return
        fraction = self._replayer.position_fraction  # type: ignore[union-attr]
        self._scrubber.set_position(fraction)

    # --------------------------------------------------------------- event markers

    def _load_markers(self) -> None:
        """Read the event sidecar and overlay jump-to-event markers on the scrubber (D-14).

        Lazily imports ``list_events`` (the offline-safe events I/O) + ``load_items`` INSIDE
        this body and maps each row to a ``(fraction, label)`` via
        ``(t_start_ns - bag_start_ns) / max(1, span)``. ``bag_start_ns`` / ``span`` come from
        ``load_items(bag)`` ALONE (WR-04 — merely viewing the Replay tab must NOT build the
        publish transport; that stays lazy on first Play/Step/seek). On any read failure the
        markers are left empty — markers are an aid, not a gate.
        """
        bag = self._bag_path()
        if bag is None:
            return
        try:
            from rosbagger_core.events import list_events

            table = list_events(bag)
            if table.num_rows == 0:
                self._scrubber.set_markers([])
                return

            from rosbagger_replay import load_items

            items = load_items(bag, default_typestore=self._default_typestore())
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
            self._scrubber.set_markers(marks)
        except Exception:  # noqa: BLE001 - markers are an aid; a sidecar read failure never crashes
            return

    # --------------------------------------------------------------- the drive loop

    def _start_drive(self) -> None:
        """Drive ``Replayer.run()`` off the UI thread on a QThread worker (Pitfall 1).

        ``run()`` is the BLOCKING scheduler drive loop; running it on a
        :class:`~rosbagger_desktop.workers.BlockingWorker` keeps the UI responsive (transport
        methods fire from the UI handlers between run segments). After ``run()`` returns the
        final playhead + a terminal status are pushed back via the worker's ``result`` slot
        (UI thread).
        """
        replayer = self._replayer
        if replayer is None:
            return

        def work() -> object:
            replayer.run()  # type: ignore[union-attr]  # BLOCKING drive loop
            return None

        # CR-02: the rate/loop controls mutate the non-thread-safe Replayer; disable them for
        # the duration of the drive so a returnPressed/toggled can't race run() on the worker
        # thread (mirrors the record panel's Start/Dismiss enable/disable). They are re-enabled
        # on every drive outcome via _on_drive_finished (wired on on_finished).
        self._rate_input.setEnabled(False)
        self._loop_checkbox.setEnabled(False)

        worker = BlockingWorker(work, label="Replay failed")
        self._drive_thread, _ = run_on_thread(
            self,
            worker,
            on_result=self._on_drive_done,
            on_failed=self._on_drive_failed,
            on_finished=self._on_drive_finished,  # CR-01/CR-02: clear ref + re-enable controls
        )

    def _on_drive_failed(self, message: str) -> None:
        """Render a drive-worker error VERBATIM through the accessible helper (D-02/D-09).

        The worker emits ``"Replay failed: <exc>"`` (never a traceback). Routed through the
        shared ``set_status`` with ``is_error=True`` so the error affordance shows + a screen
        reader Alert fires on a real desktop (guarded no-op offscreen). Content unchanged.
        """
        set_status(self._status, message, is_error=True)

    def _on_drive_finished(self) -> None:
        """Drop the drive-thread ref + re-enable rate/loop controls when the worker finishes.

        CR-01: ``run_on_thread`` wires ``thread.finished → thread.deleteLater``, so once the
        worker finishes the underlying C++ ``QThread`` is destroyed; keeping the stale Python
        wrapper in ``self._drive_thread`` makes a later ``stop_thread``/``_drive_running`` probe
        touch a deleted object. CR-02: re-enable the rate input + loop checkbox that
        ``_start_drive`` disabled so they are mutable again between run segments. Connected via
        ``on_finished`` (wired before the teardown chain), this runs on the UI thread on EVERY
        drive outcome (result OR failure).
        """
        self._drive_thread = None
        self._rate_input.setEnabled(True)
        self._loop_checkbox.setEnabled(True)

    def _on_drive_done(self, _result: object) -> None:
        """Push the final playhead + a terminal status after the drive worker returns (UI thread).

        ``State.DONE`` is end-of-track; report the published count (from the shared
        ``build_publish_sink`` count dict, D-05). Lazily imports the scheduler ``State`` so the
        module top stays ROS-free.
        """
        self._update_position()
        replayer = self._replayer
        if replayer is None:
            return
        from rosbagger_replay.scheduler import State

        if replayer.state is State.DONE:  # type: ignore[union-attr]
            published = self._published["n"] if self._published else 0
            set_status(self._status, f"Done — published {published} message(s).")
