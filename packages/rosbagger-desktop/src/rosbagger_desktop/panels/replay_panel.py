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
import subprocess
import sys

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
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
        # The publish sink (Phase 20): kept so a static re-publish after a seek can push the
        # tracked latched topics back through it (republish_static reads sink.tracker).
        self._sink: object | None = None
        self._bag_span_ns: int = 0
        self._item_count: int = 0
        # Kept drive-thread ref (Pitfall 2 — the GC must not collect a live thread).
        self._drive_thread: QThread | None = None
        # Kept drive-WORKER ref too (CR-02): run_on_thread returns (thread, worker) and BOTH must
        # be held. The BlockingWorker is a parentless QObject; dropping it (the old ``, _ =``) let
        # the GC collect it before the queued ``thread.started → worker.run`` fired, so ``run()``
        # never executed — the thread spun as an empty shell (0 published, playhead frozen at 0,
        # nothing on the wire for RViz). The inspect/query/tf panels already keep self._*_worker;
        # this matches them. Cleared in _on_drive_finished (the worker deleteLater's on finish).
        self._drive_worker: BlockingWorker | None = None
        # Phase 22 — the live Rerun mirror. self._rerun_sink (set on toggle-on by _open_rerun) is
        # read LIVE by the drive tee in _ensure_transport, so toggling needs no transport rebuild;
        # self._rerun_rec is the RecordingStream/viewer handle. The mirror is transport-INDEPENDENT:
        # it survives a rate-change rebuild; torn down ONLY in _close_rerun / closeEvent (never
        # _teardown_transport). self._install_* hold the kept-ref pip-install worker (CR-02: never
        # drop the worker into `_`, or the GC collects it before run() fires — the 260529-k6m bug).
        self._rerun_sink: object | None = None
        self._rerun_rec: object | None = None
        self._install_thread: QThread | None = None
        self._install_worker: BlockingWorker | None = None
        # Live-playhead poll (Phase 18 / SC2): a UI-thread QTimer that, while the drive worker
        # runs Replayer.run() on its thread, periodically reads the now-thread-safe
        # position_fraction and advances the scrubber playhead so the timeline tracks playback
        # in real time (previously the playhead only updated at DONE). Started in _start_drive,
        # stopped in _on_drive_finished AND closeEvent. ~60ms ≈ 16 fps — smooth without churn.
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(60)
        self._position_timer.timeout.connect(self._update_position)

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
        # Phase 22: the live Rerun mirror toggle. Checkable so it reads as on/off; sits at the END
        # of the strip behind a stretch so it presents as a "view" action, not a transport control.
        self._rerun_button = QPushButton("Open in Rerun")
        self._rerun_button.setCheckable(True)
        control_bar = QHBoxLayout()
        control_bar.addWidget(self._play_button)
        control_bar.addWidget(self._pause_button)
        control_bar.addWidget(self._step_button)
        control_bar.addWidget(QLabel("rate:"))
        control_bar.addWidget(self._rate_input)
        control_bar.addWidget(self._loop_checkbox)
        control_bar.addStretch(1)
        control_bar.addWidget(self._rerun_button)

        # Snippet loop region (Phase 19, REP-03): the durable unit is the FRACTION (the bag span
        # can change on a transport rebuild); converted to absolute t_ns at apply time the same
        # way seek maps a fraction. Re-applied in _ensure_transport so it survives pause/seek/play.
        self._loop_in_frac: float | None = None
        self._loop_out_frac: float | None = None

        # Collapsible "Advanced" sub-panel (the side sub-panel the user asked for): a checkable
        # QToolButton header toggles a QGroupBox body holding the region-loop controls, so the
        # main transport strip stays uncluttered. Starts collapsed.
        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setText("Advanced")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setChecked(False)
        self._advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._advanced_toggle.setArrowType(Qt.RightArrow)
        self._region_checkbox = QCheckBox("Loop region")
        self._set_in_button = QPushButton("Set In")
        self._set_out_button = QPushButton("Set Out")
        region_row = QHBoxLayout()
        region_row.addWidget(self._region_checkbox)
        region_row.addWidget(self._set_in_button)
        region_row.addWidget(self._set_out_button)
        region_row.addStretch(1)
        # Phase 20 (REP-04): opt-in RViz-fidelity toggles, default OFF — publish /clock for
        # use_sim_time nodes, and re-publish latched/static topics (/tf_static) after a seek so a
        # fresh scene re-primes (the concrete fix for the Phase-18 backward-scrub limitation).
        self._clock_checkbox = QCheckBox("Publish /clock")
        self._static_seek_checkbox = QCheckBox("Re-publish static on seek")
        self._clock_checkbox.setChecked(False)
        self._static_seek_checkbox.setChecked(False)
        self._advanced_body = QGroupBox("Replay region & fidelity")
        body_layout = QVBoxLayout(self._advanced_body)
        body_layout.addLayout(region_row)
        body_layout.addWidget(self._clock_checkbox)
        body_layout.addWidget(self._static_seek_checkbox)
        self._advanced_body.setVisible(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._scrubber)
        layout.addLayout(control_bar)
        layout.addWidget(self._advanced_toggle)
        layout.addWidget(self._advanced_body)
        layout.addStretch(1)

        self._play_button.clicked.connect(self._play)
        self._pause_button.clicked.connect(self._pause)
        self._step_button.clicked.connect(self._step)
        self._rate_input.returnPressed.connect(self._apply_rate)
        self._loop_checkbox.toggled.connect(self._apply_loop)
        self._rerun_button.toggled.connect(self._toggle_rerun)
        self._scrubber.seeked.connect(self._on_seeked)
        self._advanced_toggle.toggled.connect(self._on_advanced_toggled)
        self._region_checkbox.toggled.connect(self._on_region_toggled)
        self._set_in_button.clicked.connect(self._on_set_in)
        self._set_out_button.clicked.connect(self._on_set_out)
        self._scrubber.region_changed.connect(self._on_region_changed)

    # ------------------------------------------------------------------ accessors

    @property
    def status_label(self) -> QLabel:
        """The status/teaching line (tests assert the transport + terminal messages here)."""
        return self._status

    @property
    def advanced_toggle(self) -> QToolButton:
        """The collapsible advanced sub-panel header (checkable; toggles the body, Phase 19)."""
        return self._advanced_toggle

    @property
    def advanced_body(self) -> QGroupBox:
        """The advanced sub-panel body (region-loop controls; hidden until expanded)."""
        return self._advanced_body

    @property
    def region_checkbox(self) -> QCheckBox:
        """The 'Loop region' toggle (on => scheduler region active; off => cleared)."""
        return self._region_checkbox

    @property
    def set_in_button(self) -> QPushButton:
        """The 'Set In' button (snaps the region in-bound to the live playhead)."""
        return self._set_in_button

    @property
    def set_out_button(self) -> QPushButton:
        """The 'Set Out' button (snaps the region out-bound to the live playhead)."""
        return self._set_out_button

    @property
    def clock_checkbox(self) -> QCheckBox:
        """The 'Publish /clock' toggle (Phase 20; on => build_publish_sink(publish_clock=True))."""
        return self._clock_checkbox

    @property
    def static_seek_checkbox(self) -> QCheckBox:
        """The 'Re-publish static on seek' toggle (Phase 20; on => track + re-prime /tf_static)."""
        return self._static_seek_checkbox

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

    @property
    def rerun_button(self) -> QPushButton:
        """The 'Open in Rerun' toggle (Phase 22 — live-mirrors Play into the Rerun viewer)."""
        return self._rerun_button

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
        """Stop the playhead timer + drive thread + tear down the rclpy context (WR-05)."""
        self._position_timer.stop()  # Phase 18: never fire the poll after teardown
        stop_thread(self._drive_thread)
        stop_thread(self._install_thread)  # Phase 22: stop a running pip-install worker
        self._close_rerun()  # Phase 22: drop the mirror + flush (transport-independent)
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
            # Phase 20 (REP-04): thread the opt-in RViz-fidelity toggles (default off => today's
            # call). publish_clock emits /clock per publish; static_topics tracks /tf_static so a
            # post-seek republish_static (in _on_seeked) re-primes a fresh scene. Keep the sink
            # ref so the republish-after-seek path can reach sink.tracker.
            publish_clock = self._clock_checkbox.isChecked()
            static_topics = (
                frozenset({"/tf_static"}) if self._static_seek_checkbox.isChecked() else frozenset()
            )
            sink, self._published = build_publish_sink(
                self._node, publish_clock=publish_clock, static_topics=static_topics
            )
            self._sink = sink  # the BARE publish sink (republish_static reads sink.tracker)

            # Phase 22 — the dynamic Rerun tee. The Replayer drives THIS composed sink: it always
            # publishes to ROS (unchanged), then — only while the mirror is on — also logs to Rerun.
            # It reads self._rerun_sink LIVE, so toggling Open-in-Rerun needs no transport rebuild,
            # and build_publish_sink / self._sink stay byte-for-byte the production publish path.
            def _drive_sink(item: object) -> None:
                sink(item)
                rerun_sink = self._rerun_sink
                if rerun_sink is not None:
                    rerun_sink(item)

            self._replayer = Replayer(
                items, _drive_sink, rate=rate, loop=self._loop_checkbox.isChecked()
            )
            self._item_count = len(items)
            self._bag_span_ns = items[-1].t_ns - items[0].t_ns
            # Phase 19: re-apply a region set before this (re)build so it survives pause/seek/play.
            # The fraction is the durable unit; reflect it onto the scrubber band, and onto the
            # rebuilt scheduler when region-loop is active (set_loop_region + seek into the region).
            if self._loop_in_frac is not None and self._loop_out_frac is not None:
                self._scrubber.set_loop_region(self._loop_in_frac, self._loop_out_frac)
                if self._region_checkbox.isChecked():
                    self._apply_region_to_scheduler()
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
        self._sink = None
        self._created_ctx = False
        if node is not None:
            with contextlib.suppress(Exception):
                node.destroy_node()
        if created:
            import rclpy

            with contextlib.suppress(Exception):
                rclpy.shutdown()

    # --------------------------------------------------------------- Rerun mirror (Phase 22)

    def _toggle_rerun(self, checked: bool) -> None:
        """Open-in-Rerun toggle: open the live mirror (on) or stop it (off).

        Gated on ROS (the mirror is live) + ``rerun_available()``; when rerun-sdk is missing the
        install-on-click path runs pip in a worker. ``open_viewer`` / ``build_rerun_sink`` are
        reached via the ``rosbagger_rerun`` module attribute so tests can monkeypatch them. The
        lazy ``import rosbagger_rerun`` keeps this module's top ROS-free AND rerun-free.
        """
        if not checked:
            self._close_rerun()
            return
        if not self._ros_available():
            set_status(self._status, "Source ROS 2 to mirror replay to Rerun.", is_error=True)
            self._rerun_button.setChecked(False)
            return
        import rosbagger_rerun

        if rosbagger_rerun.rerun_available():
            self._open_rerun()
        else:
            self._install_rerun()

    def _open_rerun(self) -> None:
        """Spawn the Rerun viewer + build the mirror sink (read live by the drive tee)."""
        import rosbagger_rerun

        try:
            rec = rosbagger_rerun.open_viewer()
            self._rerun_sink, _ = rosbagger_rerun.build_rerun_sink(rec)
            self._rerun_rec = rec
            self._rerun_button.setText("Open in Rerun")
            set_status(self._status, "Mirroring replay to Rerun (press Play).")
        except Exception as exc:  # noqa: BLE001 - teach, don't crash the panel
            set_status(self._status, f"Rerun open failed: {exc}", is_error=True)
            self._rerun_button.setChecked(False)

    def _close_rerun(self) -> None:
        """Stop the mirror: drop the sink (the tee goes inert) + best-effort flush the recording."""
        self._rerun_sink = None
        rec = self._rerun_rec
        self._rerun_rec = None
        if rec is not None:
            with contextlib.suppress(Exception):
                rec.flush()
        self._rerun_button.setText("Open in Rerun")

    def _install_rerun(self) -> None:
        """Install rerun-sdk on-click in a kept-ref worker (CR-02), then open the mirror.

        Runs pip OFF the UI thread so the window never freezes; BOTH the thread AND worker refs
        are kept (dropping the worker into ``_`` is the 260529-k6m GC bug). On finish:
        ``_on_install_result`` opens the mirror, ``_on_install_failed`` teaches the manual command,
        ``_on_install_finished`` clears the refs (mirrors ``_on_drive_finished``).
        """
        self._rerun_button.setText("Open in Rerun (install)")
        set_status(self._status, "Installing rerun-sdk…")
        worker = BlockingWorker(
            lambda: subprocess.run(
                [sys.executable, "-m", "pip", "install", "rerun-sdk>=0.31,<0.33"],
                check=True,
                capture_output=True,
            ),
            label="Rerun install failed",
        )
        self._install_thread, self._install_worker = run_on_thread(
            self,
            worker,
            self._on_install_result,
            self._on_install_failed,
            self._on_install_finished,
        )

    def _on_install_result(self, _value: object) -> None:
        """pip install succeeded — re-probe (invalidating import caches) and open the mirror."""
        import importlib

        import rosbagger_rerun

        importlib.invalidate_caches()
        if rosbagger_rerun.rerun_available():
            self._open_rerun()
        else:
            set_status(
                self._status,
                "rerun-sdk installed but not importable yet — toggle again.",
                is_error=True,
            )
            self._rerun_button.setChecked(False)
            self._rerun_button.setText("Open in Rerun (install)")

    def _on_install_failed(self, message: str) -> None:
        """pip install failed — teach the manual command instead of crashing."""
        set_status(
            self._status,
            f'{message} — install manually: pip install "rerun-sdk>=0.31,<0.33"',
            is_error=True,
        )
        self._rerun_button.setChecked(False)
        self._rerun_button.setText("Open in Rerun (install)")

    def _on_install_finished(self) -> None:
        """Drop the install worker refs now the pip run is done (mirrors _on_drive_finished)."""
        self._install_thread = None
        self._install_worker = None

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

        Phase 18 (REP-02): ``set_rate`` is now LIVE — the rate can change while the drive worker
        runs. 18-01 made ``Replayer.set_rate`` thread-safe (lock-guarded mutation + a wake so the
        change takes effect at the next paced gap), so the old "pause before changing the rate"
        guard is gone and the rate input stays enabled throughout playback (see ``_start_drive``).
        """
        if self._replayer is None:
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

        Phase 18 (REP-02): the loop toggle is now LIVE. 18-01 made ``Replayer.loop`` a
        lock-guarded property, so writing it from the UI thread while ``run()`` reads it at the
        end-of-stream branch is race-free — the old "pause before toggling loop" guard is gone
        and the checkbox stays enabled throughout playback (see ``_start_drive``).
        """
        if self._replayer is None:
            return
        self._replayer.loop = checked  # type: ignore[union-attr]

    # ----------------------------------------------------------------- scrubber/seek

    def _on_seeked(self, fraction: float) -> None:
        """A scrubber/marker seek maps a fraction onto ``replayer.seek`` (D-14, the only setter).

        ``seek`` is the ONLY position-setter: fraction → bag-relative nanoseconds. A
        seek-past-end lands ``cursor == len(items)`` (a clean DONE).

        Phase 18 (REP-02): seeking is now LIVE — the user can drag the scrubber back and forth
        WHILE it plays. 18-01 made ``Replayer.seek`` thread-safe (lock-guarded jump + a wake +
        the cursor-unchanged advance guard so a mid-publish seek is honored, not clobbered), so
        the old "pause before seeking" guard is gone. HONESTY: a backward drag is a *jump to an
        earlier timestamp + forward republish*, NOT a visual rewind — RViz (any live subscriber)
        only ever renders what we publish from the seek point onward. The status says
        "resuming forward" so the user never reads it as reverse playback. (Making a backward
        scrub *look* right in RViz — re-publishing latched/static topics + ``/clock`` — is the
        Phase-20 fidelity work, opt-in via the Advanced sub-panel's "Re-publish static on seek"
        toggle: when on, this re-primes the tracked static topics through the sink AFTER the jump.)
        """
        if not self._ensure_transport():
            return
        # Compare against the current playhead BEFORE the jump to detect a backward drag.
        prev_fraction = self._replayer.position_fraction  # type: ignore[union-attr]
        t_offset_ns = int(fraction * self._bag_span_ns)
        self._replayer.seek(t_offset_ns)  # type: ignore[union-attr]
        self._update_position()
        if fraction < prev_fraction:
            set_status(self._status, f"Seeking to {fraction * 100:.0f}% — resuming forward.")
        else:
            set_status(self._status, f"Seeked to {fraction * 100:.0f}% of the bag.")
        # Phase 20 (REP-04): when enabled, re-publish the tracked latched/static topics AFTER the
        # seek so a fresh scene re-primes in RViz (the concrete fix for the backward-scrub
        # limitation). republish_static is a no-op when the sink has no tracker. Lazy import keeps
        # the panel module top ROS-free; the scheduler is NOT involved (publish-path concern).
        if self._static_seek_checkbox.isChecked() and self._sink is not None:
            from rosbagger_replay import republish_static

            republish_static(self._sink)

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

    # --------------------------------------------------------- region loop (Phase 19)

    def _on_advanced_toggled(self, checked: bool) -> None:
        """Show/hide the advanced sub-panel body + flip the header arrow (collapsible, Phase 19)."""
        self._advanced_body.setVisible(checked)
        self._advanced_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def _region_abs_ns(self, in_frac: float, out_frac: float) -> tuple[int, int]:
        """Map region fractions to ABSOLUTE bag-relative t_ns the SAME way ``seek`` maps a fraction.

        ``seek`` treats ``int(fraction * bag_span_ns)`` as a bag-relative offset (t0-relative),
        and ``Replayer.seek`` adds ``items[0].t_ns`` internally; ``set_loop_region`` takes
        absolute t_ns, so the scheduler's ``seek`` scan and the region bounds share one basis.
        We pass the offset form (``int(frac * bag_span_ns)``) as the absolute bound because the
        scheduler compares against ``items[cursor].t_ns`` — see the note in 19-03 RESEARCH; the
        panel always seeks to the in-bound when enabling region-loop so the cursor enters the
        region. Both bounds use the identical mapping for consistency.
        """
        return int(in_frac * self._bag_span_ns), int(out_frac * self._bag_span_ns)

    def _apply_region_to_scheduler(self) -> None:
        """Push the stored region onto the scheduler when active + seek into it (UI-thread helper).

        Called when the region checkbox is on and both bounds are set. Converts the durable
        fractions to absolute t_ns and calls ``replayer.set_loop_region`` (lock-guarded in
        19-01); also seeks the cursor to the in-bound so playback enters the region (the
        scheduler only wraps AFTER the cursor passes the out-bound).
        """
        if self._replayer is None:
            return
        if self._loop_in_frac is None or self._loop_out_frac is None:
            return
        in_ns, out_ns = self._region_abs_ns(self._loop_in_frac, self._loop_out_frac)
        self._replayer.set_loop_region(in_ns, out_ns)  # type: ignore[union-attr]
        self._replayer.seek(in_ns)  # type: ignore[union-attr]  # enter the region
        self._update_position()

    def _set_region_bound(self, which: str) -> None:
        """Snap the in/out region bound to the live playhead (Set-In / Set-Out, Phase 19).

        Reads ``position_fraction`` (the live cursor), stores it as the chosen bound (keeping
        in<=out), reflects BOTH bounds onto the scrubber band, and — when region-loop is active
        — onto the scheduler. The durable unit is the fraction (survives a transport rebuild).
        """
        if not self._ensure_transport():
            return
        frac = self._replayer.position_fraction  # type: ignore[union-attr]
        if which == "in":
            self._loop_in_frac = frac
            if self._loop_out_frac is None or self._loop_out_frac < frac:
                self._loop_out_frac = frac  # keep in<=out
        else:  # "out"
            self._loop_out_frac = frac
            if self._loop_in_frac is None or self._loop_in_frac > frac:
                self._loop_in_frac = frac  # keep in<=out
        self._scrubber.set_loop_region(self._loop_in_frac, self._loop_out_frac)
        if self._region_checkbox.isChecked():
            self._apply_region_to_scheduler()
        set_status(
            self._status,
            f"Loop region {self._loop_in_frac * 100:.0f}%–{self._loop_out_frac * 100:.0f}%.",
        )

    def _on_set_in(self) -> None:
        """Set the region in-bound to the current playhead (Set-In button)."""
        self._set_region_bound("in")

    def _on_set_out(self) -> None:
        """Set the region out-bound to the current playhead (Set-Out button)."""
        self._set_region_bound("out")

    def _on_region_toggled(self, checked: bool) -> None:
        """Loop-region checkbox: ON => scheduler region active (+seek in); OFF => cleared."""
        if self._replayer is None:
            return
        if checked and self._loop_in_frac is not None and self._loop_out_frac is not None:
            self._apply_region_to_scheduler()
            set_status(self._status, "Loop region on.")
        else:
            self._replayer.clear_loop_region()  # type: ignore[union-attr]
            set_status(self._status, "Loop region off.")

    def _on_region_changed(self, in_frac: float, out_frac: float) -> None:
        """A USER scrubber handle drag updated the region — store it + sync the scheduler.

        Stores the durable fractions and, when region-loop is active, pushes them onto the
        scheduler (converted to absolute t_ns). The scrubber is already showing the new band
        (it emitted this), so we do NOT call set_loop_region back on it (no feedback loop).
        """
        self._loop_in_frac = in_frac
        self._loop_out_frac = out_frac
        if self._replayer is not None and self._region_checkbox.isChecked():
            self._apply_region_to_scheduler()
        set_status(self._status, f"Loop region {in_frac * 100:.0f}%–{out_frac * 100:.0f}%.")

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

        # Phase 18 (REP-02): rate/loop/seek are now LIVE — 18-01 made the Replayer thread-safe,
        # so the controls stay ENABLED for the whole drive (no setEnabled(False) here, no
        # re-enable in _on_drive_finished). Start the live-playhead poll so the scrubber tracks
        # playback in real time; it is stopped in _on_drive_finished (every outcome) + closeEvent.
        self._position_timer.start()

        worker = BlockingWorker(work, label="Replay failed")
        self._drive_thread, self._drive_worker = run_on_thread(
            self,
            worker,
            on_result=self._on_drive_done,
            on_failed=self._on_drive_failed,
            on_finished=self._on_drive_finished,  # clear ref + stop the live-playhead poll
        )

    def _on_drive_failed(self, message: str) -> None:
        """Render a drive-worker error VERBATIM through the accessible helper (D-02/D-09).

        The worker emits ``"Replay failed: <exc>"`` (never a traceback). Routed through the
        shared ``set_status`` with ``is_error=True`` so the error affordance shows + a screen
        reader Alert fires on a real desktop (guarded no-op offscreen). Content unchanged.
        """
        set_status(self._status, message, is_error=True)

    def _on_drive_finished(self) -> None:
        """Drop the drive-thread ref + stop the live-playhead poll when the worker finishes.

        CR-01: ``run_on_thread`` wires ``thread.finished → thread.deleteLater``, so once the
        worker finishes the underlying C++ ``QThread`` is destroyed; keeping the stale Python
        wrapper in ``self._drive_thread`` makes a later ``stop_thread``/``_drive_running`` probe
        touch a deleted object. Phase 18: stop the live-playhead QTimer (the drive is over, so
        the poll has nothing to track) — bounded start↔stop with ``_start_drive``. The rate/loop
        controls are NOT re-enabled here because Phase 18 never disables them (they are live).
        Connected via ``on_finished`` (wired before the teardown chain), this runs on the UI
        thread on EVERY drive outcome (result OR failure).
        """
        self._drive_thread = None
        self._drive_worker = None  # CR-02: drop our worker ref now the drive is done
        self._position_timer.stop()

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
