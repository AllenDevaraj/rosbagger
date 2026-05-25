"""``BlockingWorker`` — the Qt concurrency scaffolding for the live panels (D-15).

The desktop analog of the TUI's ``@work(thread=True)`` + ``call_from_thread``: a plain
:class:`PySide6.QtCore.QObject` worker holding a blocking callable, ``moveToThread``'d
onto a :class:`PySide6.QtCore.QThread`, started via the thread's ``started`` signal, and
emitting ``result`` / ``failed`` / ``finished`` signals back to the UI thread (16-RESEARCH
Pattern 3). We **never** subclass ``QThread`` and put work in ``run()`` (the documented
anti-pattern); the worker-object + ``moveToThread`` form has clean signal-based teardown
and is the leak-free analog of the TUI worker model.

THE TEACHING-ERROR CONTRACT (Pitfall 1 / D-15): the worker try/calls the blocking work;
a *known* teaching error (the live-module capability errors) is emitted on ``failed`` as
``str(exc)`` (the message CONTENT is built in core — the GUI only presents it), any other
``Exception`` is emitted on ``failed`` with a one-line ``label`` prefix (NEVER a traceback
to the UI), and ``finished`` always fires in a ``finally`` so the teardown wiring runs on
every path. On success the work's return value is emitted on ``result``.

TEARDOWN DISCIPLINE (Pitfall 2 — "QThread: Destroyed while thread is still running"):
:func:`run_on_thread` wires ``thread.started → worker.run``, ``worker.finished →
thread.quit``, ``worker.finished → worker.deleteLater``, ``thread.finished →
thread.deleteLater``, KEEPS references on the panel (so the GC can't collect a live
thread), and starts the thread. A panel closing while a thread runs must
``quit()`` + ``wait()`` it (see :func:`stop_thread`).

OFFLINE-CLEAN: this module imports ONLY PySide6 + stdlib (``collections.abc`` typing). It
names no live-module symbol — the blocking callable is passed IN by the panel (which lazily
imports ``rosbagger_record`` / ``rosbagger_replay`` / ``rclpy`` inside the callable body),
so importing ``rosbagger_desktop.workers`` pulls in no ROS / heavy stack.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class BlockingWorker(QObject):
    """A ``QObject`` worker that runs ONE blocking callable off the UI thread (Pattern 3).

    Construct with the blocking ``work`` callable (e.g. a lambda closing over the lazily
    imported ``list_record_topics`` / ``record_topics`` / ``Replayer.run``), an optional
    tuple of *teaching* exception types whose ``str(exc)`` is presented verbatim, and a
    ``label`` prefixing any unexpected-error message. ``moveToThread`` it onto a
    :class:`QThread`, connect the thread's ``started`` to :meth:`run`, and connect
    :attr:`result` / :attr:`failed` to UI-thread slots — exactly what :func:`run_on_thread`
    does. The worker NEVER touches a widget itself; it only emits, and the panel's slots
    (running on the UI thread) update widgets.
    """

    # The work's return value (on success). object — the panel knows the concrete type.
    result = Signal(object)
    # A teaching message (str(exc) for a known error, or "<label>: <exc>" otherwise).
    failed = Signal(str)
    # Always emitted in a finally — drives thread.quit + the deleteLater teardown.
    finished = Signal()

    def __init__(
        self,
        work: Callable[[], object],
        teaching_errors: Iterable[type[BaseException]] = (),
        label: str = "Operation failed",
    ) -> None:
        """Hold the blocking ``work`` callable + the teaching-error policy (no work runs yet)."""
        super().__init__()
        self._work = work
        self._teaching = tuple(teaching_errors)
        self._label = label

    @Slot()
    def run(self) -> None:
        """Run the blocking callable off the UI thread; emit result/failed; always finish.

        Called via ``thread.started`` so it executes on the worker thread (Pitfall 1 — the
        UI event loop never blocks). A teaching error emits ``str(exc)`` verbatim (the core
        message); any other ``Exception`` emits a one-line ``"<label>: <exc>"`` (never a
        traceback to the UI). ``finished`` fires in the ``finally`` on every path so the
        ``thread.quit`` + ``deleteLater`` teardown always runs.
        """
        try:
            value = self._work()
        except self._teaching as exc:  # known capability/teaching error — present verbatim
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface as teaching text, not a crash
            self.failed.emit(f"{self._label}: {exc}")
        else:
            self.result.emit(value)
        finally:
            self.finished.emit()


def run_on_thread(
    owner: QObject,
    worker: BlockingWorker,
    on_result: Callable[[object], None],
    on_failed: Callable[[str], None],
    on_finished: Callable[[], None] | None = None,
) -> tuple[QThread, BlockingWorker]:
    """Move ``worker`` onto a fresh ``QThread``, wire the Pattern-3 teardown, and start it.

    Connects ``thread.started → worker.run``, the worker's ``result`` / ``failed`` to the
    panel's UI-thread slots, and the Pitfall-2 teardown chain (``worker.finished →
    thread.quit`` / ``worker.deleteLater``; ``thread.finished → thread.deleteLater``). The
    returned ``(thread, worker)`` pair MUST be kept on the panel (a ``self._thread`` /
    ``self._worker`` ref) so the GC does not collect a live thread mid-run; :func:`stop_thread`
    tears it down on close.

    ``on_finished`` (optional) runs after the work finishes (post-result/failed) on the UI
    thread — panels use it to re-enable controls regardless of outcome.
    """
    thread = QThread(owner)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.result.connect(on_result)
    worker.failed.connect(on_failed)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    # Teardown discipline (Pitfall 2): quit the loop + delete both objects on finish.
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker


def stop_thread(thread: QThread | None) -> None:
    """Best-effort ``quit()`` + ``wait()`` a (possibly running) thread (Pitfall 2 close path).

    Called from a panel's close/teardown so a live worker thread is stopped before its
    objects are destroyed — avoiding "QThread: Destroyed while thread is still running".
    ``None`` / an already-finished thread is a no-op. For a *bounded* record the
    ``duration`` is what actually ends the work; this only waits for the loop to exit.

    CR-01: ``thread.finished → thread.deleteLater`` destroys the underlying C++ ``QThread``
    once a worker finishes, but a panel may still hold the stale Python wrapper (panels clear
    their ref via ``on_finished``, but a close racing the finish — or any missed clear — would
    leave a dangling handle). Touching ``isRunning()`` on a ``deleteLater``'d object raises
    ``RuntimeError: Internal C++ object already deleted``; inside ``closeEvent`` that aborts
    window teardown. So guard the ``isRunning()`` probe and treat a deleted object as a no-op.
    """
    if thread is None:
        return
    try:
        running = thread.isRunning()
    except RuntimeError:  # underlying C++ QThread already deleted (finished + deleteLater'd)
        return
    if running:
        thread.quit()
        thread.wait()
