"""Record panel (LIVE, D-13) — a thin Qt face over ``rosbagger-record``.

LIVE PANEL (D-09): capability-gated. When ``rclpy`` is not importable the ``MainWindow``
disables this panel's nav row with a teaching tooltip (the D-09 gate); the discovery scan +
record controls below skip entirely (the teaching-hint state). The Qt analog of the TUI
``rosbagger_gui.panels.record``, ported one-to-one into PySide6 widgets + ``QThread`` workers.

WHAT IT DOES (when ROS is available — the gate enabled it):

* **On show → tier-2 discovery scan (D-13).** A :class:`~rosbagger_desktop.workers.BlockingWorker`
  on a ``QThread`` lazily calls ``rosbagger_record.list_record_topics`` (which owns its own
  short-lived ``rclpy`` node + spin-to-settle) and emits the ``{topic: type}`` map back to a
  UI-thread slot that fills a checkable ``QListWidget``. The blocking ROS scan NEVER runs on
  the UI thread (Pitfall 1).
* **Start → real ``record_topics()`` (D-13).** Reads the checked topics + the destination
  path + the storage choice and runs a SECOND ``QThread`` worker that lazily calls the real
  ``rosbagger_record.record_topics`` (the submodule-shadow-proof alias) with a BOUNDED
  ``duration`` so the recorder self-terminates; the captured count (or a teaching-error
  message) comes back via a signal to a UI-thread slot.
* **Dismiss → bounded end (WR-03).** ``record_topics`` exposes NO in-process early-stop hook;
  the bounded ``duration`` is what ends the capture. Dismiss tears down the worker thread
  (``quit`` + ``wait``) and writes the WR-03 "the bounded record finalizes on its own"
  status — it does NOT stop the in-flight capture early.

OFFLINE-IMPORT INVARIANT (D-08, Pitfall 4): this module's TOP LEVEL imports ONLY PySide6 +
stdlib + the local ``workers`` symbols. EVERY ``rosbagger_record`` / ``rclpy`` import lives
INSIDE a worker callable — ``import rosbagger_desktop.panels.record_panel`` pulls no
``rclpy`` / ``rosbag2_py``. The teaching capability errors are caught in the worker and
their message presented on the status line, never a traceback.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..widgets import set_status
from ..workers import BlockingWorker, run_on_thread, stop_thread

# A bounded default record window (seconds). record_topics() spins its own loop checking
# rclpy.ok() + the bounded deadline; the GUI drives a BOUNDED record so the worker self-
# terminates — the panel never opens an unbounded record it could not stop from the UI
# thread (WR-03 / the DoS mitigation T-16-03-BLOCK).
_DEFAULT_RECORD_SECONDS = 10.0

# Default destination + storage. MCAP stays the preferred default (D-08); sqlite3 is the
# explicit capability escape on a box where the mcap storage plugin is absent.
_DEFAULT_OUT = "rosbagger_record_out"
_STORAGES = ("mcap", "sqlite3")

# Teaching hint shown when ROS is absent (the gate also disables the nav row; this is the
# in-panel state should it ever be reached without a sourced environment).
_NO_ROS_HINT = "Source your ROS 2 environment to enable live recording (rosbagger-record)."


class RecordPanel(QWidget):
    """Record view — discover live ROS topics + record a selected subset (live, D-13)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the status line, topic checklist, output/storage controls, Start/Dismiss."""
        super().__init__(parent)

        # Kept thread/worker refs (Pitfall 2 — the GC must not collect a live thread). BOTH the
        # thread AND the worker must be held: run_on_thread returns (thread, worker) and the
        # BlockingWorker is a parentless QObject — dropping it (the old ``, _ =``) let the GC
        # collect it before the queued ``thread.started → worker.run`` fired, so the scan/record
        # never executed (CR-02 — the same bug fixed in the replay panel). The worker refs are
        # cleared in the respective _on_*_finished slots (the worker deleteLater's on finish).
        self._discover_thread: QThread | None = None
        self._discover_worker: BlockingWorker | None = None
        self._record_thread: QThread | None = None
        self._record_worker: BlockingWorker | None = None

        # Status line as an accessibly-named region (D-02 a11y parity); a stable objectName lets
        # the shared status helper restore it after an error toggle and the theme style it.
        self._status = QLabel("Live recording — open the panel to discover topics.")
        self._status.setObjectName("record_status")
        self._status.setAccessibleName("Record status")
        self._status.setAccessibleDescription("Live recording — open the panel to discover topics.")
        self._status.setProperty("heading", True)

        # Topic checklist: a QListWidget with checkable items (the Qt analog of the TUI
        # SelectionList). Each item carries the topic NAME — Start reads the checked names.
        self._topic_list = QListWidget()

        # Output path + storage selector.
        self._out_input = QLineEdit(_DEFAULT_OUT)
        self._out_input.setPlaceholderText("output bag path")
        self._storage_mcap = QRadioButton("mcap")
        self._storage_sqlite = QRadioButton("sqlite3")
        self._storage_mcap.setChecked(True)  # mcap default (D-08)
        storage_bar = QHBoxLayout()
        storage_bar.addWidget(QLabel("storage:"))
        storage_bar.addWidget(self._storage_mcap)
        storage_bar.addWidget(self._storage_sqlite)
        storage_bar.addStretch(1)

        # Start + Dismiss. Dismiss is disabled until a record is in flight; its label says
        # the bounded record finalizes on its own (WR-03 — no early-stop hook to promise).
        self._start_button = QPushButton("Start")
        self._dismiss_button = QPushButton("Dismiss")
        self._dismiss_button.setEnabled(False)
        button_bar = QHBoxLayout()
        button_bar.addWidget(self._start_button)
        button_bar.addWidget(self._dismiss_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._topic_list, 1)
        layout.addWidget(self._out_input)
        layout.addLayout(storage_bar)
        layout.addLayout(button_bar)

        self._start_button.clicked.connect(self._start_record)
        self._dismiss_button.clicked.connect(self._dismiss_record)

    # ------------------------------------------------------------------ accessors

    @property
    def status_label(self) -> QLabel:
        """The status/teaching line (tests assert the discovery + record messages here)."""
        return self._status

    @property
    def topic_list(self) -> QListWidget:
        """The topic checklist (tests check/read the discovered topic items here)."""
        return self._topic_list

    @property
    def start_button(self) -> QPushButton:
        """The Start button (tests click it to drive a real bounded ``record_topics``)."""
        return self._start_button

    @property
    def dismiss_button(self) -> QPushButton:
        """The Dismiss button (disabled until a record is in flight)."""
        return self._dismiss_button

    @property
    def out_input(self) -> QLineEdit:
        """The output-path line-edit (default ``rosbagger_record_out``)."""
        return self._out_input

    # ------------------------------------------------------------------ lifecycle

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Re-run the discovery scan whenever the panel becomes the active stacked view."""
        super().showEvent(event)
        self._scan_topics()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name
        """Stop any running worker thread on close (Pitfall 2 — no destroyed-while-running)."""
        stop_thread(self._discover_thread)
        stop_thread(self._record_thread)
        super().closeEvent(event)

    def _ros_available(self) -> bool:
        """Whether the window reports a sourced ROS 2 environment (D-09 gate input)."""
        return bool(getattr(self.window(), "ros_available", False))

    def _release_replay_context(self) -> None:
        """Tear down the replay panel's OWN rclpy context before a record scan/start (WR-01).

        The two live panels share one process-wide ``rclpy`` context. The replay panel guards
        its ``rclpy.init()`` with the re-entrant ``rclpy.ok()`` check (WR-04) and keeps its
        context alive until teardown; but ``rosbagger_record.record``'s ``list_topics`` /
        ``record`` call ``rclpy.init()`` UNCONDITIONALLY (no re-entrant guard, and that module is
        outside this phase's editable scope). So if the user visited Replay and pressed
        Play/Step/seek (building the replay context) and then switches to Record, the
        discovery/record worker's ``rclpy.init()`` raises "context already initialized" and the
        worker surfaces it as a teaching error — recording is silently non-functional for the
        rest of the session.

        Mitigate in-panel: if the replay panel created (and still owns) the only live context,
        tear it down here so the record worker can ``init()`` cleanly. We only tear down a
        context the replay panel itself created (``_created_ctx``) — never one we did not build.
        Best-effort and defensive: a missing/incompatible replay panel is a no-op.
        """
        replay = getattr(self.window(), "replay_panel", None)
        if replay is None:
            return
        # Only release a context the replay panel itself created (mirrors its WR-04 ownership).
        if getattr(replay, "_created_ctx", False):
            teardown = getattr(replay, "_teardown_transport", None)
            if callable(teardown):
                teardown()

    # ------------------------------------------------------------------ discovery

    def _scan_topics(self) -> None:
        """Start the discovery worker when ROS is available (never on the UI thread, D-13).

        When ROS is absent the panel shows the teaching hint and skips the scan (the gate
        also disabled the nav row). Otherwise the blocking ``list_record_topics`` runs in a
        ``QThread`` worker (Pitfall 1); a fresh scan replaces any in-flight one.
        """
        if not self._ros_available():
            set_status(self._status, _NO_ROS_HINT, is_error=True)
            return
        if self._discover_thread is not None and self._discover_thread.isRunning():
            return  # a scan is already running; let it finish
        # WR-01: release the replay panel's own rclpy context so the unconditional
        # rclpy.init() inside list_record_topics does not clash with a live replay context.
        self._release_replay_context()
        set_status(self._status, "Discovering live topics…")

        def work() -> dict:
            # Lazy import (D-08): list_record_topics owns its own rclpy node — no node
            # mechanics duplicated here. The teaching errors are caught by the worker.
            from rosbagger_record import list_record_topics

            return dict(list_record_topics())

        from importlib import import_module

        worker = BlockingWorker(
            work,
            teaching_errors=_record_teaching_errors(import_module),
            label="Topic discovery failed",
        )
        self._discover_thread, self._discover_worker = run_on_thread(
            self,
            worker,
            on_result=self._populate_checklist,
            on_failed=self._on_discover_failed,
            on_finished=self._clear_discover_thread,  # CR-01: null the ref before deleteLater
        )

    def _on_discover_failed(self, message: str) -> None:
        """Render a discovery teaching-error VERBATIM through the accessible helper (D-02/D-09).

        The worker emits ``str(exc)`` for the capability teaching errors (or
        ``"Topic discovery failed: <exc>"`` otherwise) — never a traceback. Routed through the
        shared ``set_status`` with ``is_error=True`` so the error affordance shows + a screen
        reader Alert fires on a real desktop (guarded no-op offscreen). Content unchanged
        (THIN-FACE, D-09 — core owns the strings).
        """
        set_status(self._status, message, is_error=True)

    def _clear_discover_thread(self) -> None:
        """Drop the kept discover-thread ref when the worker finishes (CR-01 — UI thread).

        ``run_on_thread`` wires ``thread.finished → thread.deleteLater``; without clearing the
        Python wrapper a later ``stop_thread``/``isRunning`` probe on close touches a deleted
        C++ object and raises. Connected via ``on_finished`` so it runs on the UI thread.
        """
        self._discover_thread = None
        self._discover_worker = None  # CR-02: drop our worker ref now the scan is done

    def _populate_checklist(self, mapping: object) -> None:
        """Fill the checklist from the discovered ``{topic: type}`` map (UI-thread slot).

        Runs on the UI thread (a worker ``result`` signal), so touching widgets is safe.
        Each item carries the topic NAME on the user role; the Start handler reads the
        checked names verbatim — the panel constructs no selection logic.
        """
        topics: dict[str, str] = dict(mapping) if mapping else {}
        self._topic_list.clear()
        for topic in sorted(topics):
            item = QListWidgetItem(f"{topic}  ({topics[topic]})")
            item.setData(int(Qt.UserRole), topic)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self._topic_list.addItem(item)
        if topics:
            set_status(
                self._status, f"Discovered {len(topics)} topic(s) — select + Start to record."
            )
        else:
            set_status(self._status, "No live topics discovered. Publish some, then re-open.")

    def _checked_topics(self) -> list[str]:
        """The topic names of the checked checklist items (verbatim, no selection logic)."""
        selected: list[str] = []
        for row in range(self._topic_list.count()):
            item = self._topic_list.item(row)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(int(Qt.UserRole))))
        return selected

    # --------------------------------------------------------------------- record

    def _selected_storage(self) -> str:
        """Read the chosen storage from the radio buttons (default mcap, D-08)."""
        return "sqlite3" if self._storage_sqlite.isChecked() else "mcap"

    def _start_record(self) -> None:
        """Read checked topics + path + storage, then start the bounded record worker (D-13).

        Gathers the UI selection on the UI thread (cheap), guards the empty-selection case
        with a teaching status (never handing ``record_topics`` an empty list), then launches
        the ``QThread`` record worker. NO ROS call happens here — the blocking
        ``record_topics`` runs in the worker (Pitfall 1).
        """
        if not self._ros_available():
            set_status(self._status, _NO_ROS_HINT, is_error=True)
            return
        if self._record_thread is not None and self._record_thread.isRunning():
            set_status(
                self._status,
                "A record is already in flight (bounded — wait for it to finish).",
                is_error=True,
            )
            return
        topics = self._checked_topics()
        if not topics:
            set_status(self._status, "Select at least one topic to record.", is_error=True)
            return
        out = self._out_input.text().strip() or _DEFAULT_OUT
        storage = self._selected_storage()
        # WR-01: release the replay panel's own rclpy context so record_topics'
        # unconditional rclpy.init() does not clash with a live replay context.
        self._release_replay_context()
        self._start_button.setEnabled(False)
        self._dismiss_button.setEnabled(True)
        set_status(
            self._status,
            f"Recording {len(topics)} topic(s) → {out} "
            f"({storage}, up to {_DEFAULT_RECORD_SECONDS:.0f}s)…",
        )

        def work() -> object:
            # Lazy import (D-08): record_topics is the submodule-shadow-proof alias of the
            # record front door (the SINGLE discover→select→record orchestrator, D-13). The
            # bounded duration makes the recorder self-terminate.
            from rosbagger_record import record_topics

            captured = record_topics(topics, out, storage=storage, duration=_DEFAULT_RECORD_SECONDS)
            return (captured, out)

        from importlib import import_module

        worker = BlockingWorker(
            work,
            teaching_errors=_record_teaching_errors(import_module),
            label="Recording failed",
        )
        self._record_thread, self._record_worker = run_on_thread(
            self,
            worker,
            on_result=self._finish_record,
            on_failed=self._finish_record_status,
            on_finished=self._on_record_finished,
        )

    def _on_record_finished(self) -> None:
        """Reset the buttons AND drop the kept record-thread ref (CR-01 — UI thread).

        Runs on ``worker.finished`` (before ``thread.deleteLater``); clearing the ref keeps a
        later ``stop_thread`` probe on close from touching the deleted C++ ``QThread``.
        """
        self._reset_buttons()
        self._record_thread = None
        self._record_worker = None  # CR-02: drop our worker ref now the record is done

    def _dismiss_record(self) -> None:
        """Dismiss the in-flight record UI; the bounded ``duration`` is what ends recording.

        WR-03: ``record_topics`` spins its own loop (``rclpy.ok()`` + the bounded deadline)
        and exposes NO in-process interrupt hook — so this control does NOT stop the capture
        early. ``stop_thread`` quits+waits the worker loop (the recorder keeps writing until
        its bounded window elapses, then finalizes on its own). The status says so rather
        than claiming an immediate stop the panel cannot deliver.
        """
        self._reset_buttons()
        set_status(
            self._status,
            f"Dismissed — the bounded record finalizes on its own "
            f"(up to {_DEFAULT_RECORD_SECONDS:.0f}s).",
        )

    def _finish_record(self, result: object) -> None:
        """Write the captured-count terminal status (UI-thread slot for the worker result).

        WR-02: the worker success path emits ``(captured, out)`` (see ``work`` above), but
        ``result`` is typed ``object`` — a non-2-tuple payload (e.g. a future change to the
        worker's return) would make the unpack raise an unhandled ``TypeError``/``ValueError``
        in the Qt event loop. Guard the shape and surface a teaching status instead of crashing.
        """
        if not (isinstance(result, tuple) and len(result) == 2):
            set_status(self._status, f"Recorded (unexpected result: {result!r})", is_error=True)
            return
        captured, out = result
        set_status(self._status, f"Recorded {captured} message(s) → {out}")

    def _finish_record_status(self, message: str) -> None:
        """Write a teaching-error status from the record worker through the accessible helper.

        The worker emits ``str(exc)`` for the capability teaching errors (or
        ``"Recording failed: <exc>"`` otherwise). Routed through the shared ``set_status`` with
        ``is_error=True`` (error affordance + guarded a11y Alert, D-02/D-09); content unchanged.
        """
        set_status(self._status, message, is_error=True)

    def _reset_buttons(self) -> None:
        """Re-enable Start / disable Dismiss (UI-thread, after the record worker finishes)."""
        self._start_button.setEnabled(True)
        self._dismiss_button.setEnabled(False)


def _record_teaching_errors(import_module) -> tuple[type[BaseException], ...]:
    """Lazily resolve the ``rosbagger_record`` teaching-error classes (offline invariant).

    Imported via ``import_module`` INSIDE this helper (called only from a control handler /
    worker setup, never at module top) so importing the panel pulls no ``rosbagger_record``.
    Returns the capability errors whose ``str(exc)`` the worker presents verbatim; on a
    failure to resolve them (e.g. the package missing) it returns an empty tuple so any
    error falls through to the generic teaching path.
    """
    try:
        mod = import_module("rosbagger_record")
        return (
            mod.RosNotAvailableError,
            mod.NoTopicsMatchedError,
            mod.McapStorageUnavailableError,
        )
    except Exception:  # noqa: BLE001 - resolution failure falls back to the generic path
        return ()
