"""Record panel (LIVE, D-04/D-08) — a thin face over ``rosbagger-record``.

LIVE PANEL (D-03): capability-gated. When ``rclpy`` is not importable the App sets
this widget ``disabled=True`` (in ``RosbaggerApp.on_mount``) and it shows a teaching
hint to source a ROS 2 environment; the discovery scan + record controls below never
run in that state.

WHAT IT DOES (when ROS is available — the tier-1 gate enabled it in 14-02):

* **On show / mount → tier-2 discovery scan (D-04).** A ``@work(thread=True)`` worker
  lazily calls ``rosbagger_record.list_topics`` (which owns its own short-lived
  ``rclpy`` node + spin-to-settle) and posts the discovered ``{topic: type}`` map back
  to the UI thread via ``self.app.call_from_thread`` to fill a ``SelectionList``
  checklist. The blocking ROS scan NEVER runs on the event loop (RESEARCH Pitfall 1).
* **Start → real ``record()`` (D-08).** Reads the checked topics + the destination path
  + the storage choice and runs a SECOND ``@work(thread=True)`` worker that lazily calls
  the real ``rosbagger_record.record_topics`` (the submodule-shadow-proof alias of the
  ``record`` front door) with a bounded ``duration`` so the recorder self-terminates,
  posting the captured count back via ``call_from_thread``.
* **Stop → bounded end.** Cancels the record worker (``worker.cancel()``); the bounded
  ``duration`` is what actually ends ``record()``'s spin loop, and the cancel suppresses
  the late result callback so a Stop reads as a clean end.

OFFLINE-IMPORT INVARIANT (D-03 / Pitfall 2 / T-14-05-02): this module's TOP LEVEL
imports ONLY ``textual`` (+ ``__future__``). EVERY ``rosbagger_record`` / ``rclpy``
import lives INSIDE a worker / method body — ``import rosbagger_gui.panels.record``
pulls no ``rclpy`` / ``rosbag2_py``. The teaching capability errors
(``RosNotAvailableError`` / ``NoTopicsMatchedError`` / ``McapStorageUnavailableError``)
are caught and their message presented on the status line (D-04 — an empty/teaching
result still teaches), never a traceback.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Input, RadioButton, RadioSet, SelectionList, Static
from textual.worker import Worker, get_current_worker

# A bounded default record window (seconds). record() spins its own loop checking
# rclpy.ok() + _should_stop; the GUI drives a BOUNDED record so the worker self-
# terminates and Stop (worker.cancel + this bound) ends the loop deterministically —
# the panel never opens an unbounded record it could not stop from the event loop.
_DEFAULT_RECORD_SECONDS = 10.0

# Default destination + storage. MCAP stays the preferred default (D-08); sqlite3 is
# the explicit capability escape on a box where the mcap storage plugin is absent.
_DEFAULT_OUT = "rosbagger_record_out"
_STORAGES = ("mcap", "sqlite3")


class RecordPanel(Widget):
    """Record view — discover live ROS topics + record a selected subset (live)."""

    def compose(self) -> ComposeResult:
        """A topic checklist + destination/storage controls + start/stop + status."""
        yield Static("Live recording — discovering topics…", id="record-status")
        yield SelectionList[str](id="topic-checklist")
        yield Input(value=_DEFAULT_OUT, placeholder="output bag path", id="record-out")
        with RadioSet(id="record-storage"):
            yield RadioButton("mcap", value=True, id="storage-mcap")
            yield RadioButton("sqlite3", id="storage-sqlite3")
        yield Button("Start", id="record-start", variant="success")
        # WR-03: the bounded record() owns its own stop (the duration deadline + rclpy.ok);
        # there is no in-process interrupt hook the event loop can pull, so this control
        # CANNOT stop the in-flight capture early — it only dismisses the UI and lets the
        # bounded window finalize on its own. The label says so rather than promising a
        # "Stop" the panel cannot deliver.
        yield Button("Dismiss", id="record-stop", variant="error", disabled=True)

    def on_mount(self) -> None:
        """Kick off the tier-2 discovery scan once the widget tree exists."""
        self._scan_topics()

    def on_show(self) -> None:
        """Re-scan whenever the panel becomes the active ContentSwitcher view (D-04)."""
        self._scan_topics()

    # ------------------------------------------------------------------ discovery

    def _scan_topics(self) -> None:
        """Start the discovery worker when ROS is available (never on the event loop).

        The App's tier-1 ``ros_available`` gate (14-02) is the authority on whether the
        live panel is usable; when ROS is absent the panel is ``disabled`` and we skip
        the scan entirely (the teaching hint state). Otherwise the blocking discovery
        runs in the ``@work(thread=True)`` worker below.
        """
        if not getattr(self.app, "ros_available", False):
            self.query_one("#record-status", Static).update(
                "Source your ROS 2 environment to enable live recording (rosbagger-record)."
            )
            return
        self.query_one("#record-status", Static).update("Discovering live topics…")
        self._discover_worker()

    @work(exclusive=True, thread=True, group="record-discover")
    def _discover_worker(self) -> None:
        """THREAD worker: live ``discover_topics`` scan → checklist (D-04 / Pitfall 1).

        Lazily imports the ``rosbagger_record`` front door INSIDE the worker body (the
        offline-import invariant) and calls ``list_topics`` — which owns its own
        short-lived ``rclpy`` node + spin-to-settle, so the panel duplicates NO node
        mechanics. The blocking call runs on this thread, never the event loop; the
        ``{topic: type}`` result is marshalled back to the UI thread via
        ``self.app.call_from_thread`` (thread-safe widget update). The teaching
        capability errors are caught and surfaced to the status line — an empty/teaching
        result still teaches (D-04).
        """
        from rosbagger_record import (
            McapStorageUnavailableError,
            NoTopicsMatchedError,
            RosNotAvailableError,
        )

        try:
            # list_record_topics is the submodule-shadow-proof alias of the lazy
            # list_topics front door (it owns its own rclpy node — no node mechanics
            # duplicated here).
            from rosbagger_record import list_record_topics

            discovered = list_record_topics()
        except (
            RosNotAvailableError,
            NoTopicsMatchedError,
            McapStorageUnavailableError,
        ) as exc:
            self.app.call_from_thread(self._show_status, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface any live-scan failure as teaching text, not a crash
            self.app.call_from_thread(self._show_status, f"Topic discovery failed: {exc}")
            return

        self.app.call_from_thread(self._populate_checklist, dict(discovered))

    def _populate_checklist(self, mapping: dict[str, str]) -> None:
        """Fill the ``SelectionList`` from the discovered ``{topic: type}`` map (UI thread).

        Called via ``call_from_thread`` from the discovery worker — runs on the event
        loop thread, so touching widgets here is safe. Each option carries the topic
        NAME as its value (the Start handler reads the selected values verbatim — the
        panel constructs no selection logic; ``record()`` owns discover→select→record).
        """
        checklist = self.query_one("#topic-checklist", SelectionList)
        checklist.clear_options()
        for topic in sorted(mapping):
            checklist.add_option((f"{topic}  ({mapping[topic]})", topic))
        status = self.query_one("#record-status", Static)
        if mapping:
            status.update(f"Discovered {len(mapping)} topic(s) — select + Start to record.")
        else:
            status.update("No live topics discovered. Publish some, then re-open this panel.")

    def _show_status(self, message: str) -> None:
        """Render ``message`` to the status line (UI-thread helper for ``call_from_thread``)."""
        self.query_one("#record-status", Static).update(message)

    # --------------------------------------------------------------------- record

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route Start/Stop to the record worker lifecycle."""
        if event.button.id == "record-start":
            self._start_record()
        elif event.button.id == "record-stop":
            self._stop_record()

    def _selected_storage(self) -> str:
        """Read the chosen storage from the ``RadioSet`` (default mcap, D-08)."""
        radio = self.query_one("#record-storage", RadioSet)
        pressed = radio.pressed_button
        if pressed is not None and pressed.label is not None:
            label = str(pressed.label)
            if label in _STORAGES:
                return label
        return "mcap"

    def _start_record(self) -> None:
        """Read the checked topics + out path + storage, then start the record worker.

        Gathers the UI selection on the event loop (cheap), guards the empty-selection
        case with a teaching status (rather than handing ``record()`` an empty list),
        then launches the ``@work(thread=True)`` record worker. NO ROS call happens
        here — the blocking ``record()`` runs in the worker (Pitfall 1).
        """
        if not getattr(self.app, "ros_available", False):
            return
        # WR-06 (mirrors the query/replay panels): record() spins its own loop until its bounded
        # duration and exposes no interrupt hook, so a worker cancelled by Dismiss keeps WRITING.
        # Dismiss re-enables Start, so a second Start would launch a second record_topics against
        # the SAME out path while the first still writes (a clobbered bag / confusing failure).
        # Refuse a Start while a record worker is still in flight.
        if any(w.group == "record-run" and w.is_running for w in self.workers):
            self._show_status("A record is still in flight — wait for it to finalize.")
            return
        checklist = self.query_one("#topic-checklist", SelectionList)
        selected: list[str] = list(checklist.selected)
        if not selected:
            self._show_status("Select at least one topic to record.")
            return
        out = self.query_one("#record-out", Input).value.strip() or _DEFAULT_OUT
        storage = self._selected_storage()
        self.query_one("#record-start", Button).disabled = True
        self.query_one("#record-stop", Button).disabled = False
        self._show_status(
            f"Recording {len(selected)} topic(s) → {out} "
            f"({storage}, up to {_DEFAULT_RECORD_SECONDS:.0f}s)…"
        )
        self._record_worker(selected, out, storage)

    @work(exclusive=True, thread=True, group="record-run")
    def _record_worker(self, topics: list[str], out: str, storage: str) -> None:
        """THREAD worker: drive the real ``record()`` API (D-08 / Pitfall 1).

        Lazily imports ``rosbagger_record.record_topics`` (the submodule-shadow-proof
        alias of the ``record`` front door — importing the ``record`` SUBMODULE anywhere
        rebinds the bare ``record`` name to the module, so the alias is the safe handle)
        and calls it with the chosen topics, out path, and storage plus a BOUNDED
        ``duration`` so the recorder self-terminates (and Stop's ``worker.cancel`` ends
        it). ``record()`` is the SINGLE discover→select→record orchestrator — the panel
        forwards the user's chosen ``topics`` and constructs no selection. The captured
        count (or a teaching-error message) is posted back via ``call_from_thread``; a
        cancelled worker suppresses the late status write so Stop reads as a clean end.
        """
        from rosbagger_record import (
            McapStorageUnavailableError,
            NoTopicsMatchedError,
            RosNotAvailableError,
            record_topics,
        )

        worker = get_current_worker()
        try:
            captured = record_topics(topics, out, storage=storage, duration=_DEFAULT_RECORD_SECONDS)
        except (
            RosNotAvailableError,
            NoTopicsMatchedError,
            McapStorageUnavailableError,
        ) as exc:
            if not worker.is_cancelled:
                self.app.call_from_thread(self._finish_record, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface any record failure as teaching text, not a crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self._finish_record, f"Recording failed: {exc}")
            return

        if not worker.is_cancelled:
            self.app.call_from_thread(
                self._finish_record, f"Recorded {captured} message(s) → {out}"
            )

    def _stop_record(self) -> None:
        """Dismiss the in-flight record UI; the bounded ``duration`` is what ends recording.

        WR-03: ``record()`` spins its own loop (``rclpy.ok()`` + the bounded
        ``_should_stop`` deadline) and exposes NO in-process interrupt hook the event loop
        can pull — so this control does NOT stop the capture early. Cancelling the worker
        only suppresses the late result callback (the recorder keeps writing until its
        bounded window elapses, then finalizes on its own). The status says so rather than
        claiming an immediate stop the panel cannot deliver.
        """
        self.workers.cancel_group(self, "record-run")
        self._finish_record(
            f"Dismissed — the bounded record finalizes on its own "
            f"(up to {_DEFAULT_RECORD_SECONDS:.0f}s)."
        )

    def _finish_record(self, message: str) -> None:
        """Reset Start/Stop + write the final status (UI-thread helper)."""
        self.query_one("#record-start", Button).disabled = False
        self.query_one("#record-stop", Button).disabled = True
        self._show_status(message)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Re-enable Start when the record worker leaves the RUNNING state (safety net)."""
        if event.worker.group == "record-run" and not event.worker.is_running:
            self.query_one("#record-start", Button).disabled = False
            self.query_one("#record-stop", Button).disabled = True
