"""Headless pytest-qt proof tests (Phase 16 / SC1 + SC3) — ROS-FREE, display-FREE.

This is the PROOF layer for the native PySide6 desktop cockpit (Phase 16, Plan 01).
It drives the real :class:`~rosbagger_desktop.main_window.MainWindow` headlessly via
the pytest-qt ``qtbot`` fixture (the Qt analog of the TUI's ``App.run_test()`` /
``Pilot``) against fixture bags written by the ROS-FREE ``tools.make_fixtures`` writers,
and asserts the Plan-01 success criteria become passing automated tests:

* **SC1 (partial) — offline panels present + enabled.** ``MainWindow`` exposes the
  inspect and tf panels (reachable via the ``panels`` accessor) with enabled nav rows
  (``test_app_has_offline_panels``). The five-panel completeness is asserted in Plan 03
  once the query/record/replay rows exist.
* **SC3 (partial) — inspect drives REAL core output.** Selecting/refreshing the inspect
  panel over a ROS 2 fixture bag lands real ``collect_bag_info`` topic rows in the
  bag-info ``QTableWidget`` (``test_inspect_panel_shows_real_topics``).
* **SC3 (tf) — tf renders or teaches.** A ``/tf`` fixture populates the edges table
  (> 0 rows); a plain no-``/tf`` fixture shows the ``NoTransformsError`` teaching text
  without crashing (``test_tf_panel_renders_or_teaches``).
* **Capability gate exercised.** Forcing ``ros_available`` -> ``False`` runs the gate
  path without error; the offline panels stay enabled
  (``test_capability_gate_keeps_offline_panels_enabled``).

OFFSCREEN (16-RESEARCH Pitfall 3): ``QT_QPA_PLATFORM=offscreen`` is set at the TOP of
this module BEFORE any PySide6 import, so no real window appears and the suite runs
headless in CI. Per the offscreen caveat, tests assert OBSERVABLE state (rowCount, label
text, widget enabled) — never pixels or hover tooltips.

SELF-CONTAINED HARNESS: mirrors tests/test_gui.py — this module owns its own repo-root +
package-src ``sys.path`` inserts (so ``tools.make_fixtures`` and ``rosbagger_desktop``
resolve regardless of launch) and writes its OWN fixture bags into ``tmp_path``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # BEFORE any PySide6 import (Pitfall 3)

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# Self-contained src/repo-root resolution (mirrors tests/test_gui.py): put the repo
# root + the desktop/core src trees on the path so ``tools.make_fixtures`` and
# ``rosbagger_desktop`` import regardless of how the suite is launched. Harmless when
# already importable (the membership check guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (
    _REPO_ROOT,
    _REPO_ROOT / "packages" / "rosbagger-desktop" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.make_fixtures import write_ros2_sqlite_bag, write_tf_bag  # noqa: E402

import rosbagger_desktop.capabilities  # noqa: E402  (forced-no-ROS monkeypatch target)
from rosbagger_desktop.main_window import MainWindow  # noqa: E402


def test_app_has_offline_panels(qtbot) -> None:
    """SC1 (partial): the inspect/query/tf panels are present and their nav rows enabled.

    Constructs ``MainWindow`` with no bag, asserts the inspect/query/tf panels are
    reachable via the public ``panels`` accessor (and the named attributes), and that
    all three nav rows are enabled (offline panels are always enabled, D-08). The
    five-panel completeness is asserted in Plan 03 once the record/replay rows exist.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert "inspect" in window.panels
    assert "query" in window.panels
    assert "tf" in window.panels
    assert window.panels["inspect"] is window.inspect_panel
    assert window.panels["query"] is window.query_panel
    assert window.panels["tf"] is window.tf_panel

    # The five-panel nav exists (inspect/query/tf/record/replay, Plan 03 SC1). The three
    # OFFLINE rows are always enabled (D-08); the two live rows' enabled state depends on
    # the gate (asserted in test_live_panels_disabled_without_ros), so this test asserts
    # only the offline trio stays enabled.
    from PySide6.QtCore import Qt

    assert window._nav.count() == 5
    offline_index = {
        pid: i
        for i, (pid, *_rest) in enumerate(window._registry)
        if pid in ("inspect", "query", "tf")
    }
    for row in offline_index.values():
        assert bool(window._nav.item(row).flags() & Qt.ItemIsEnabled), (
            "an offline nav row was unexpectedly disabled"
        )


def test_app_has_five_panels(qtbot) -> None:
    """SC1: all five panels (inspect/query/tf/record/replay) are present + their nav rows.

    Constructs ``MainWindow`` with no bag, asserts all five panels are reachable via the
    public ``panels`` accessor (and the named attributes), and that the nav holds exactly
    five rows — the full five-panel parity completeness (SC1/SC2). Record/replay are the
    two live rows added in Plan 03; their enabled/disabled state is asserted by the
    capability-gate test below (it depends on whether the box has ROS sourced).
    """
    window = MainWindow()
    qtbot.addWidget(window)

    for panel_id in ("inspect", "query", "tf", "record", "replay"):
        assert panel_id in window.panels, f"{panel_id} panel missing from the registry"
    assert window.panels["inspect"] is window.inspect_panel
    assert window.panels["query"] is window.query_panel
    assert window.panels["tf"] is window.tf_panel
    assert window.panels["record"] is window.record_panel
    assert window.panels["replay"] is window.replay_panel

    assert window._nav.count() == 5, "expected five nav rows (inspect/query/tf/record/replay)"


def test_live_panels_disabled_without_ros(qtbot, tmp_path: Path, monkeypatch) -> None:
    """SC2/SC4: with ROS forced absent the live nav rows are disabled, the offline ones aren't.

    Monkeypatches ``rosbagger_desktop.capabilities.ros_available`` → ``False`` BEFORE
    constructing the window so the D-09 gate runs deterministically on this ROS-equipped
    dev box. Asserts the record + replay nav items are disabled (the capability gate) while
    inspect/query/tf stay enabled, and that the offline panels still function without ROS
    (the inspect bag-info table fills from real core output) — proving "offline panels work
    without ROS", not merely "live panels are gated".
    """
    from PySide6.QtCore import Qt

    monkeypatch.setattr(rosbagger_desktop.capabilities, "ros_available", lambda: False)

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.ros_available is False, "forced-no-ROS window must report ros_available False"

    # Map panel id → nav row index from the registry order (inspect/query/tf/record/replay).
    nav_index = {pid: i for i, (pid, *_rest) in enumerate(window._registry)}

    # LIVE rows (record/replay): nav item disabled by the gate.
    for live_id in ("record", "replay"):
        item = window._nav.item(nav_index[live_id])
        assert not bool(item.flags() & Qt.ItemIsEnabled), (
            f"{live_id} nav row should be disabled with ROS absent (capability gate)"
        )

    # OFFLINE rows (inspect/query/tf): NOT disabled — always enabled (D-08).
    for offline_id in ("inspect", "query", "tf"):
        item = window._nav.item(nav_index[offline_id])
        assert bool(item.flags() & Qt.ItemIsEnabled), (
            f"{offline_id} nav row should stay enabled with ROS absent"
        )

    # And the offline panels WORK without ROS: open a fixture, refresh, get real rows.
    bag = write_ros2_sqlite_bag(tmp_path)
    window._open_reader(bag)
    window.inspect_panel.refresh_view()
    assert window.inspect_panel.bag_info_table.rowCount() > 0, (
        "offline inspect panel did not render real topics without ROS"
    )


def test_inspect_panel_shows_real_topics(qtbot, tmp_path: Path) -> None:
    """SC3 (inspect): the inspect panel renders REAL ``collect_bag_info`` topic rows.

    Writes a ROS 2 sqlite3 fixture bag (3 topics), opens ``MainWindow`` on it, drives
    the inspect panel's ``refresh_view()``, and asserts the bag-info table has > 0 rows
    — i.e. real ``rosbagger_core.inspect`` output reached the widget.
    """
    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    window.inspect_panel.refresh_view()
    assert window.inspect_panel.bag_info_table.rowCount() > 0, (
        "inspect bag-info had 0 rows; expected real topics from collect_bag_info"
    )


def test_tf_panel_renders_or_teaches(qtbot, tmp_path: Path) -> None:
    """SC3 (tf): a /tf bag populates the edges table; a no-/tf bag shows the teaching text.

    Populated path: a ``write_tf_bag`` ROS 2 fixture (``/tf`` + ``/tf_static``) yields
    > 0 edge rows. Teaching path: a plain ``write_ros2_sqlite_bag`` fixture (no ``/tf``)
    makes ``collect_tf_report`` raise ``NoTransformsError`` — caught and rendered on the
    status line, with the edges table empty and no crash (T-16-TF).
    """
    # Populated path: a /tf bag yields edge rows.
    tf_dir = tmp_path / "with_tf"
    tf_bag = write_tf_bag(tf_dir, ros1=False, storage="sqlite3")
    tf_window = MainWindow(bag_path=str(tf_bag))
    qtbot.addWidget(tf_window)
    tf_window.tf_panel.refresh_view()
    assert tf_window.tf_panel.edges_table.rowCount() > 0, (
        "tf edges table had 0 rows on a /tf bag; expected real collect_tf_report edges"
    )

    # Teaching path: a no-/tf bag shows the NoTransformsError teaching text, no crash.
    plain_dir = tmp_path / "no_tf"
    plain_bag = write_ros2_sqlite_bag(plain_dir)
    plain_window = MainWindow(bag_path=str(plain_bag))
    qtbot.addWidget(plain_window)
    plain_window.tf_panel.refresh_view()
    assert plain_window.tf_panel.edges_table.rowCount() == 0, (
        "tf edges table should be empty on a no-/tf bag"
    )
    status_text = plain_window.tf_panel.status_label.text()
    assert status_text != "Open a bag with /tf to analyze", (
        "tf status should show the NoTransformsError teaching text, not the empty-state line"
    )
    assert status_text, "tf status label was empty; expected a NoTransformsError teaching message"


def test_query_panel_runs_real_core(qtbot, tmp_path: Path) -> None:
    """SC2/SC3 (query): the Query panel drives a REAL THREADED ``query()`` over a fixture bag.

    Writes a ROS 2 sqlite3 fixture bag, opens ``MainWindow`` on it, shows the Query
    panel so its ``refresh_view()`` builds the schema tree, derives a known table name
    from the panel's own schema tree (so the test is robust to fixture topic changes),
    sets a ``SELECT * FROM <table> LIMIT 1`` and triggers Run via the Run button. Because
    ``query()`` now runs on a ``BlockingWorker`` thread (P1), the result arrives via signal
    — so the test ``waitUntil``s the lazy ``QAbstractTableModel`` populates rather than
    asserting synchronously. The results view must then carry real
    ``rosbagger_core.backend.query.query`` rows/cols via the model (SC2/SC3).

    Second leg (TEACHING): a SELECT over a clearly-unknown table arrives on the worker's
    ``failed`` slot as ``str(exc)`` — the status shows a non-empty teaching string with no
    "row(s)" and NO exception raised (the UnknownTableError path; T-16-02-TEACH / T-is6-01).

    Third leg (NON-BLOCKING): after a successful Run the worker tears down and the
    ``_query_thread`` ref is cleared on the UI thread (proving the off-thread path ran and
    Run was re-enabled) — the P1 responsiveness contract.
    """
    from PySide6.QtCore import QAbstractTableModel, Qt
    from PySide6.QtWidgets import QTreeWidget

    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    panel = window.query_panel
    panel.refresh_view()  # build the schema tree from real collect_table_schemas

    # Derive a real table name from the panel's own schema tree (no hardcoded fixture).
    tree: QTreeWidget = panel.schema_tree
    assert tree.topLevelItemCount() > 0, "schema tree had no tables from collect_table_schemas"
    table_name = tree.topLevelItem(0).text(0)

    # Run a real SELECT; the result lands on the worker thread → wait for the model to fill.
    panel.sql_input.setText(f"SELECT * FROM {table_name} LIMIT 1")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: panel.results_table.model().rowCount() > 0, timeout=5000)

    # Rows/cols rendered via the QAbstractTableModel-backed view (SC2/SC3, P2).
    model = panel.results_table.model()
    assert model is not None, "results view had no model"
    assert isinstance(model, QAbstractTableModel), "results view is not QAbstractTableModel-backed"
    assert model.columnCount() > 0, "query results model had 0 columns; expected real query() cols"
    # A successful query enables export (D-06) and re-enables Run (P1).
    assert panel.export_csv_button.isEnabled()
    assert panel.export_parquet_button.isEnabled()

    # Third leg (NON-BLOCKING): the worker completed and cleared its thread ref on the UI thread.
    qtbot.waitUntil(lambda: getattr(panel, "_query_thread", None) is None, timeout=5000)
    assert panel.run_button.isEnabled(), "Run was not re-enabled after the worker finished"

    # Teaching path: an unknown table sets a non-empty status string (no "row(s)"), no exception.
    panel.sql_input.setText("SELECT * FROM definitely_not_a_real_table")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: "row(s)" not in panel.status_label.text()
        and panel.status_label.text() not in ("", "Running…"),
        timeout=5000,
    )
    status_text = panel.status_label.text()
    assert status_text, "query status was empty; expected an UnknownTableError teaching message"
    assert "row(s)" not in status_text, (
        "unknown-table query should NOT report a row count; expected the teaching error text"
    )


def test_query_panel_regions_live_in_splitter(qtbot, tmp_path: Path) -> None:
    """P2-layout: the schema tree, results view, and history list live under one QSplitter.

    Opens ``MainWindow`` on a ROS 2 fixture bag, refreshes the Query panel so the schema
    tree builds, finds the panel's ``QSplitter`` and asserts the three resizable regions
    are descendants of it (robust to the history-container wrapper via ``isAncestorOf``)
    — proving the regions were regrouped under user-draggable control rather than the old
    flat fixed-stretch stacking.
    """
    from PySide6.QtWidgets import QSplitter

    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    panel = window.query_panel
    panel.refresh_view()

    splitter = panel.findChild(QSplitter)
    assert splitter is not None, "Query panel has no QSplitter; regions are not user-resizable"

    # The three resizable regions are descendants of the splitter (history via its wrapper).
    assert splitter.isAncestorOf(panel.schema_tree), "schema tree is not inside the splitter"
    assert splitter.isAncestorOf(panel.results_table), "results view is not inside the splitter"
    assert splitter.isAncestorOf(panel.history_list), "history list is not inside the splitter"


def test_query_status_announces_and_styles_errors(qtbot, tmp_path: Path) -> None:
    """P2-a11y: the status label is accessibly named, styles+announces errors, clears on success.

    Opens ``MainWindow`` on a ROS 2 fixture bag and derives a real table name from the
    panel's own schema tree (fixture-robust). Asserts the status label carries an accessible
    name. Drives the teaching-error path (unknown table) over the ``BlockingWorker`` thread
    and ``waitUntil`` the status settles to a non-empty teaching string with no "row(s)",
    then asserts the error style is applied (non-empty ``styleSheet()``) and the verbatim
    text survived without raising headlessly. Finally runs a successful query and asserts the
    status reports "row(s)" again AND the error style is cleared (neutral/empty stylesheet) —
    proving the error styling is path-scoped.
    """
    from PySide6.QtCore import Qt

    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    panel = window.query_panel
    panel.refresh_view()
    table_name = panel.schema_tree.topLevelItem(0).text(0)

    # The status region is named for assistive tech.
    assert panel.status_label.accessibleName(), "status label has no accessible name (P2-a11y)"

    # Teaching-error path: unknown table → non-empty teaching status, no "row(s)", no crash.
    panel.sql_input.setText("SELECT * FROM definitely_not_a_real_table")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: "row(s)" not in panel.status_label.text()
        and panel.status_label.text() not in ("", "Running…"),
        timeout=5000,
    )
    error_text = panel.status_label.text()
    assert error_text, "expected an UnknownTableError teaching message"
    assert "row(s)" not in error_text, "teaching error must not report a row count"
    # 17-02 / D-03: the error affordance is now the ``status_error`` objectName (color comes
    # from the theme QSS ``QLabel#status_error`` selector), NOT an inline stylesheet literal.
    assert panel.status_label.objectName() == "status_error", (
        "error path did not toggle the status_error objectName affordance (D-03)"
    )

    # Success path: a real query CLEARS the error affordance and reports "row(s)" again.
    panel.sql_input.setText(f"SELECT * FROM {table_name} LIMIT 1")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    qtbot.waitUntil(
        lambda: "row(s)" in panel.status_label.text(),
        timeout=5000,
    )
    assert panel.status_label.objectName() != "status_error", (
        "error affordance was not cleared on success (styling must be path-scoped, P2-a11y)"
    )


def test_capability_gate_keeps_offline_panels_enabled(qtbot, tmp_path: Path, monkeypatch) -> None:
    """The capability gate runs (ROS forced absent) and leaves the offline panels enabled.

    Forces ``rosbagger_desktop.capabilities.ros_available`` BEFORE constructing the
    window so the D-09 gate path is exercised deterministically regardless of whether
    this box has ROS sourced. The monkeypatch wiring is proven both ways: forcing
    ``True`` flows to ``window.ros_available is True`` (so the patch is genuinely the
    source of the gate's input, not the ambient venv), then forcing ``False`` runs the
    gate. There are no LIVE rows yet (Plan 03 adds record/replay), so the assertion is
    that the gate code runs WITHOUT error and the two offline panels remain present +
    enabled — the gate is in place and inert for offline rows.
    """
    # Prove the monkeypatch is the real source of the gate input (force True).
    monkeypatch.setattr(rosbagger_desktop.capabilities, "ros_available", lambda: True)
    available_window = MainWindow()
    qtbot.addWidget(available_window)
    assert available_window.ros_available is True, "forced-True patch did not reach the gate input"

    # Now force ROS absent and exercise the gate path.
    monkeypatch.setattr(rosbagger_desktop.capabilities, "ros_available", lambda: False)

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.ros_available is False, "forced-no-ROS window must report ros_available False"

    from PySide6.QtCore import Qt

    # The full five-panel nav exists; the three OFFLINE rows stay enabled even with ROS
    # absent (D-08), while the live record/replay rows are gated (asserted in detail by
    # test_live_panels_disabled_without_ros). This test focuses on the offline trio.
    assert window._nav.count() == 5
    offline_index = {
        pid: i
        for i, (pid, *_rest) in enumerate(window._registry)
        if pid in ("inspect", "query", "tf")
    }
    for row in offline_index.values():
        assert bool(window._nav.item(row).flags() & Qt.ItemIsEnabled), (
            "an offline nav row was disabled by the capability gate"
        )

    # And the offline panel still works without ROS: open a fixture, refresh, get rows.
    bag = write_ros2_sqlite_bag(tmp_path)
    window._open_reader(bag)
    window.inspect_panel.refresh_view()
    assert window.inspect_panel.bag_info_table.rowCount() > 0, (
        "offline inspect panel did not render real topics without ROS"
    )


def test_stop_thread_survives_deleted_qthread(qtbot) -> None:
    """CR-01: ``stop_thread`` is a no-op on a ``deleteLater``'d (destroyed) QThread.

    Reproduces the use-after-free class: ``run_on_thread`` wires
    ``thread.finished → thread.deleteLater``, so once a worker finishes the underlying C++
    ``QThread`` is destroyed while a panel may still hold the stale Python wrapper. Touching
    ``isRunning()`` on that object raises ``RuntimeError: Internal C++ object already deleted``
    — and pre-fix that fired inside ``closeEvent``, aborting window teardown. After the fix
    ``stop_thread`` swallows the RuntimeError and returns cleanly.
    """
    from PySide6.QtCore import QThread

    from rosbagger_desktop.workers import stop_thread

    thread = QThread()
    thread.deleteLater()  # schedule destruction of the underlying C++ object
    # Force the deferred delete to actually run so the C++ object is gone.
    qtbot.wait(10)

    # Pre-fix this raised RuntimeError; post-fix it is a clean no-op.
    stop_thread(thread)


def test_replay_panel_close_after_finished_run_is_safe(qtbot) -> None:
    """CR-01: the replay panel's drive-thread ref is nulled on finish, so close is safe.

    Directly exercises the ref-clearing slot (``_clear_drive_thread``, wired via ``on_finished``)
    and then closes the panel. Pre-fix the stale ``_drive_thread`` wrapper survived a completed
    run and ``closeEvent`` → ``stop_thread`` touched the destroyed C++ object; post-fix the ref
    is ``None`` after finish and the (also-hardened) ``stop_thread`` makes close a no-op.
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    # Simulate a stale ref that a finished worker would have left, then the finish callback.
    panel._drive_thread = object()  # type: ignore[assignment]  # stand-in stale handle
    panel._rate_input.setEnabled(False)  # _start_drive disables these during a drive (CR-02)
    panel._loop_checkbox.setEnabled(False)
    panel._on_drive_finished()
    assert panel._drive_thread is None, "drive-thread ref was not cleared on finish (CR-01)"
    assert panel._rate_input.isEnabled(), "rate input not re-enabled after drive (CR-02)"
    assert panel._loop_checkbox.isEnabled(), "loop checkbox not re-enabled after drive (CR-02)"

    # closeEvent must not raise even with no live transport / no thread.
    panel.close()


def test_record_panel_close_after_finished_run_is_safe(qtbot) -> None:
    """CR-01: the record panel nulls its worker refs on finish, so close is safe.

    Exercises both ref-clearing slots (``_clear_discover_thread`` and ``_on_record_finished``)
    then closes the panel — the discovery + record threads must both end at ``None`` and the
    close must not touch a destroyed C++ object.
    """
    from rosbagger_desktop.panels.record_panel import RecordPanel

    panel = RecordPanel()
    qtbot.addWidget(panel)

    panel._discover_thread = object()  # type: ignore[assignment]
    panel._record_thread = object()  # type: ignore[assignment]
    panel._clear_discover_thread()
    panel._on_record_finished()
    assert panel._discover_thread is None, "discover-thread ref not cleared on finish (CR-01)"
    assert panel._record_thread is None, "record-thread ref not cleared on finish (CR-01)"

    panel.close()


def test_replay_rate_contract_agrees_on_play_and_enter(qtbot) -> None:
    """WR-06: an invalid rate is REJECTED on both Play(-build) and Enter — never coerced to 1.0.

    Pre-fix the transport-build path (``_read_rate``) silently coerced a bad rate to 1.0 while
    the Enter handler (``_apply_rate``) rejected it — the two paths disagreed for the same
    widget. Both now route through ``_validated_rate``: an invalid entry sets a teaching status
    and refuses (returns ``None`` / builds nothing), and a valid entry parses cleanly.
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    # Invalid (non-numeric): the SINGLE validator rejects with a teaching status, returns None.
    panel.rate_input.setText("fast")
    assert panel._validated_rate() is None, "non-numeric rate was not rejected (WR-06)"
    assert "Invalid rate" in panel.status_label.text()

    # Invalid (<= 0): same rejection.
    panel.rate_input.setText("0")
    assert panel._validated_rate() is None, "non-positive rate was not rejected (WR-06)"
    assert "Invalid rate" in panel.status_label.text()

    # Valid: parses to the float (no coerce).
    panel.rate_input.setText("2.5")
    assert panel._validated_rate() == 2.5, "a valid rate did not parse cleanly (WR-06)"

    # The Enter handler agrees: with a sentinel replayer, a bad rate is rejected (no set_rate).
    class _Sentinel:
        def __init__(self) -> None:
            self.rate_calls: list[float] = []

        def set_rate(self, rate: float) -> None:
            self.rate_calls.append(rate)

    sentinel = _Sentinel()
    panel._replayer = sentinel  # type: ignore[assignment]
    panel.rate_input.setText("bad")
    panel._apply_rate()
    assert sentinel.rate_calls == [], "Enter handler coerced an invalid rate instead of rejecting"
    assert "Invalid rate" in panel.status_label.text()


def test_finish_record_guards_non_tuple_result(qtbot) -> None:
    """WR-02: a non-2-tuple worker result becomes a teaching status, never an event-loop crash.

    Pre-fix ``_finish_record`` did ``captured, out = result`` unconditionally — a non-2-tuple
    payload (typed ``object``) raised an unhandled ``TypeError``/``ValueError`` on the UI thread.
    Drives the slot with a bare int and a wrong-length tuple (each must set a status and NOT
    raise), then with the real ``(captured, out)`` shape (the happy path still formats cleanly).
    """
    from rosbagger_desktop.panels.record_panel import RecordPanel

    panel = RecordPanel()
    qtbot.addWidget(panel)

    # Bad shape (bare int, as record() historically returned): teaching status, no exception.
    panel._finish_record(42)
    assert "unexpected result" in panel.status_label.text(), (
        "a non-tuple record result must surface a teaching status, not crash (WR-02)"
    )

    # Bad shape (wrong-length tuple): same defensive path.
    panel._finish_record((1, 2, 3))
    assert "unexpected result" in panel.status_label.text(), (
        "a wrong-length tuple result must surface a teaching status (WR-02)"
    )

    # Happy path (the worker's real (captured, out) contract): formats the terminal status.
    panel._finish_record((7, "out.mcap"))
    assert "Recorded 7 message(s)" in panel.status_label.text()
    assert "out.mcap" in panel.status_label.text()


def test_open_reader_clears_bag_path_on_failed_open(qtbot, tmp_path: Path, monkeypatch) -> None:
    """WR-04: a failed re-open leaves ``reader`` None AND ``_bag_path`` consistent (cleared).

    Opens a valid fixture so the window holds a reader + ``_bag_path``, stubs the warning dialog
    (no native modal under offscreen), then re-opens a bad path. Pre-fix the failure path nulled
    ``reader`` but left the stale ``_bag_path`` pointing at the old bag — inconsistent state. Now
    both end consistent: ``reader is None`` and ``_bag_path is None`` after the failed open.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    window = MainWindow()
    qtbot.addWidget(window)

    # First, a successful open: reader + _bag_path are both set and agree.
    bag = write_ros2_sqlite_bag(tmp_path)
    window._open_reader(bag)
    assert window.reader is not None, "valid bag should open a reader"
    assert window._bag_path == bag, "valid open should record the bag path"

    # Now a failed re-open over a non-existent path: BOTH must end consistent (None).
    window._open_reader(tmp_path / "does-not-exist.mcap")
    assert window.reader is None, "failed open must leave reader None"
    assert window._bag_path is None, (
        "failed open must clear _bag_path to stay consistent with reader (WR-04)"
    )


def test_query_export_uses_save_dialog(qtbot, tmp_path: Path, monkeypatch) -> None:
    """WR-03: export routes through ``QFileDialog.getSaveFileName`` to a user-chosen path.

    Runs a real query over a fixture bag so a result exists, stubs the save dialog to return a
    tmp path (no native dialog under offscreen), clicks Export CSV, and asserts the file landed
    at the CHOSEN path (not the old fixed CWD ``query_result.csv``). A second leg returns an
    empty string (the user cancelled) and asserts NO file is written — a clean no-op.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)
    panel = window.query_panel
    panel.refresh_view()
    table_name = panel.schema_tree.topLevelItem(0).text(0)
    panel.sql_input.setText(f"SELECT * FROM {table_name} LIMIT 1")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    # query() runs on a worker thread (P1) → wait for the model to populate before exporting.
    qtbot.waitUntil(lambda: panel.results_table.model().rowCount() > 0, timeout=5000)

    # User picks a destination → the file is written there (WR-03, not a fixed CWD path).
    chosen = tmp_path / "chosen_export.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(chosen), "CSV (*.csv)")
    )
    qtbot.mouseClick(panel.export_csv_button, Qt.LeftButton)
    assert chosen.exists(), "export did not write to the user-chosen save-dialog path (WR-03)"
    assert str(chosen) in panel.status_label.text(), "status did not report the chosen path"

    # User cancels the dialog (empty path) → nothing is written, no crash.
    cancelled = tmp_path / "should_not_exist.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    qtbot.mouseClick(panel.export_parquet_button, Qt.LeftButton)
    assert not cancelled.exists()


def test_query_export_surfaces_arrow_error_as_status(qtbot, tmp_path: Path, monkeypatch) -> None:
    """WR-05: a non-ValueError/OSError export error becomes a teaching status, not a crash.

    ``write_table`` can raise Arrow's own exceptions (``ArrowInvalid`` / ``ArrowNotImplemented``)
    which are NOT ``ValueError``/``OSError``. With the catch broadened to ``Exception``, such an
    error must land on the status label ("Export failed: …") rather than propagating into the
    Qt event loop. Stubs ``write_table`` to raise a non-ValueError/OSError exception.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog

    import rosbagger_core.output.export as export_mod

    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)
    panel = window.query_panel
    panel.refresh_view()
    table_name = panel.schema_tree.topLevelItem(0).text(0)
    panel.sql_input.setText(f"SELECT * FROM {table_name} LIMIT 1")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    # query() runs on a worker thread (P1) → wait for the model to populate before exporting.
    qtbot.waitUntil(lambda: panel.results_table.model().rowCount() > 0, timeout=5000)

    class _FakeArrowError(Exception):
        """Stand-in for an Arrow exception (not a ValueError/OSError)."""

    def _boom(*_a, **_k):
        raise _FakeArrowError("unwritable column type")

    monkeypatch.setattr(export_mod, "write_table", _boom)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x.parquet"), "")
    )

    # Pre-fix this propagated into the event loop; post-fix it is a teaching status.
    qtbot.mouseClick(panel.export_parquet_button, Qt.LeftButton)
    assert "Export failed" in panel.status_label.text(), (
        "an Arrow-style export error was not surfaced as a teaching status (WR-05)"
    )


def test_record_releases_replay_context_before_scan(qtbot, monkeypatch) -> None:
    """WR-01: a record scan/start tears down a replay-owned rclpy context first.

    ``rosbagger_record``'s ``list_topics``/``record`` call ``rclpy.init()`` unconditionally
    (no re-entrant guard, outside this phase's editable scope), so a live replay-owned context
    would make the record worker's ``init()`` clash. The record panel mitigates by releasing
    the replay panel's OWN context (``_created_ctx``) before launching a worker. This isolates
    that mitigation: a stub replay panel reporting ``_created_ctx=True`` must have its
    ``_teardown_transport`` called; one reporting ``False`` must be left alone.
    """
    from rosbagger_desktop.panels.record_panel import RecordPanel

    class _StubReplay:
        def __init__(self, created: bool) -> None:
            self._created_ctx = created
            self.torn_down = False

        def _teardown_transport(self) -> None:
            self.torn_down = True

    panel = RecordPanel()
    qtbot.addWidget(panel)

    # Replay owns a live context → record must release it before its own init().
    owned = _StubReplay(created=True)
    monkeypatch.setattr(panel, "window", lambda: type("W", (), {"replay_panel": owned})())
    panel._release_replay_context()
    assert owned.torn_down, "record did not release the replay-owned rclpy context (WR-01)"

    # Replay did NOT create the context → record must NOT touch it.
    foreign = _StubReplay(created=False)
    monkeypatch.setattr(panel, "window", lambda: type("W", (), {"replay_panel": foreign})())
    panel._release_replay_context()
    assert not foreign.torn_down, "record tore down a context the replay panel did not own"


# --------------------------------------------------------------------------------------
# Phase 17 Plan 01 — design-token + QSS theme foundation (D-03/D-04/D-06/D-07/D-08).
#
# The cleanest proof the design system is token-driven (17-RESEARCH Pitfall 4): build_qss
# is a PURE function over a Tokens dataclass — these tests call it with NO QApplication and
# assert each baked token hex appears in the emitted stylesheet. The theme_apply/theme_toggle
# tests below DO drive a QApplication (qtbot) but scope QSettings to a unique temp org/app so
# the dev box's real ~/.config is never polluted (17-RESEARCH Wave 0 note / T-17-02).
# --------------------------------------------------------------------------------------


def test_qss_dark_contains_every_dark_token_hex() -> None:
    """build_qss(DARK) is a pure non-empty string carrying DARK's baked token hex (D-03/D-04).

    No QApplication is constructed — build_qss is a pure token→string function, the single
    place QSS strings live (D-03). Each DARK color token must appear verbatim in the output,
    proving the stylesheet is genuinely token-driven rather than hand-written literals.
    """
    from rosbagger_desktop.theme import DARK, build_qss

    qss = build_qss(DARK)
    assert isinstance(qss, str) and qss.strip(), "build_qss(DARK) must be a non-empty string"
    for hexval in (DARK.bg, DARK.surface, DARK.text, DARK.accent, DARK.error, DARK.border):
        assert hexval in qss, f"DARK token {hexval} missing from build_qss(DARK)"


def test_qss_light_contains_every_light_token_hex_and_differs_from_dark() -> None:
    """build_qss(LIGHT) carries LIGHT's hex AND differs from build_qss(DARK) (D-05).

    Each LIGHT color token appears in the LIGHT stylesheet, and the two themes' outputs
    differ — proving both palettes are real and distinct, not one shared string.
    """
    from rosbagger_desktop.theme import DARK, LIGHT, build_qss

    light = build_qss(LIGHT)
    assert isinstance(light, str) and light.strip(), "build_qss(LIGHT) must be a non-empty string"
    for hexval in (LIGHT.bg, LIGHT.surface, LIGHT.text, LIGHT.accent, LIGHT.error, LIGHT.border):
        assert hexval in light, f"LIGHT token {hexval} missing from build_qss(LIGHT)"
    assert build_qss(DARK) != light, "DARK and LIGHT stylesheets must differ"


def test_qss_targets_the_non_inheriting_selectors() -> None:
    """build_qss targets QTableView grid/selection, QHeaderView::section, QSplitter::handle.

    17-RESEARCH Pitfall 3: these elements do NOT inherit QWidget styling, so the stylesheet
    must name them explicitly. Also asserts the #status_error objectName selector exists (it
    replaces query_panel's inline _STATUS_ERROR_STYLE literal in 17-03).
    """
    from rosbagger_desktop.theme import DARK, build_qss

    qss = build_qss(DARK)
    assert "QTableView" in qss
    assert "gridline-color" in qss
    assert "selection-background-color" in qss
    assert "QHeaderView::section" in qss
    assert "QSplitter::handle" in qss
    assert "#status_error" in qss


def test_qss_tokens_module_imports_no_pyside6() -> None:
    """A fresh-interpreter import of theme.tokens + theme.qss leaves no PySide6 (D-08/Pitfall 6).

    tokens.py is pure data and qss.py is a pure string function — neither may import Qt at
    module level, or the offline+Qt-free import graph would be at risk. A FRESH subprocess
    (empty PYTHONPATH neutralizes the host ROS leak) asserts no PySide6/shiboken6 lands in
    sys.modules after importing both theme modules.
    """
    import subprocess

    code = (
        "import sys; import rosbagger_desktop.theme.tokens; import rosbagger_desktop.theme.qss; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'PySide6', 'shiboken6'}]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": ""},
    )
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"theme.tokens/theme.qss pulled in Qt at import: {leaked}"


import pytest  # noqa: E402


@pytest.fixture
def theme_scope(tmp_path: Path):
    """Scope QSettings to a tmp .conf + reset the global app stylesheet on teardown.

    T-17-02 / 17-RESEARCH Wave 0: points QSettings's IniFormat path under ``tmp_path`` and uses
    a unique org/app name so the dev box's real ``~/.config/rosbagger/rosbagger-desktop.conf``
    is NEVER written/read by a theme test, and clears any pre-existing ``ui/theme`` so each test
    starts from the dark default.

    On teardown it clears the global ``QApplication`` stylesheet the theme tests set: a leftover
    app-wide QSS string interacts with later offscreen widgets' style unpolish during GC and
    aggravates the known offscreen teardown Bus-error race (CONTEXT host note). Resetting it
    isolates each theme test's global Qt mutation from a sibling test's teardown.
    """
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("rosbagger-test")
    QCoreApplication.setApplicationName("rosbagger-desktop-test")
    QSettings().remove("ui/theme")  # start each test from the dark default
    yield
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet("")  # clear the global stylesheet so it does not bleed into teardown


def test_theme_apply_sets_stylesheet_with_active_bg(qtbot, theme_scope) -> None:
    """ThemeManager().apply() themes the running QApplication with the active bg hex (D-06).

    With a fresh (dark-default) QSettings scope, constructing a ThemeManager and calling
    apply() must leave QApplication.instance().styleSheet() non-empty and containing the
    DARK bg hex — proving the manager actually drives the live app stylesheet (Pitfall 4).
    """
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.theme import DARK, ThemeManager

    manager = ThemeManager()
    assert manager.name == "dark", "default (unset) ui/theme should report 'dark'"
    manager.apply()

    sheet = QApplication.instance().styleSheet()
    assert sheet, "apply() left the app stylesheet empty"
    assert DARK.bg in sheet, "applied stylesheet does not contain the active (DARK) bg hex"


def test_theme_toggle_flips_settings_and_live_stylesheet(qtbot, theme_scope) -> None:
    """toggle() flips the persisted ui/theme AND the live stylesheet to the other theme (D-06).

    Starts dark, toggles, and asserts BOTH the QSettings ui/theme value flipped to "light"
    AND the live app stylesheet now contains the LIGHT bg hex (and no longer the DARK bg) —
    the no-relaunch live flip (17-RESEARCH Pattern 2), persisted immediately.
    """
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.theme import DARK, LIGHT, ThemeManager

    manager = ThemeManager()
    manager.apply()
    assert manager.name == "dark"

    manager.toggle()
    assert manager.name == "light", "toggle() did not flip the manager name to light"
    assert QSettings().value("ui/theme") == "light", "toggle() did not persist ui/theme=light"

    sheet = QApplication.instance().styleSheet()
    assert LIGHT.bg in sheet, "live stylesheet did not flip to the LIGHT bg hex after toggle"
    assert DARK.bg not in sheet, "live stylesheet still carries the DARK bg after toggle"


def test_theme_honors_persisted_light_on_construction(qtbot, theme_scope) -> None:
    """A pre-persisted ui/theme="light" is honored on the NEXT ThemeManager construction (D-06).

    Writes "light" to the temp QSettings scope, then constructs a fresh ThemeManager and
    asserts it reports name=="light" and applies the LIGHT stylesheet — the persistence
    round-trip across launches.
    """
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.theme import LIGHT, ThemeManager

    QSettings().setValue("ui/theme", "light")

    manager = ThemeManager()
    assert manager.name == "light", "a persisted ui/theme=light was not honored on construction"
    manager.apply()
    assert LIGHT.bg in QApplication.instance().styleSheet(), (
        "a pre-persisted light theme did not apply the LIGHT stylesheet"
    )


def test_theme_tolerates_garbage_persisted_value(qtbot, theme_scope) -> None:
    """A hand-edited/garbage ui/theme value degrades to the dark default, no crash (T-17-01).

    A tampered .conf could carry any string. The manager must select DARK unless the stored
    value is exactly "light" — never crash on an unexpected value.
    """
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.theme import DARK, ThemeManager

    QSettings().setValue("ui/theme", "chartreuse-nonsense")

    manager = ThemeManager()
    manager.apply()  # must not raise
    assert DARK.bg in QApplication.instance().styleSheet(), (
        "a garbage persisted theme value did not fall back to the DARK default (T-17-01)"
    )


def test_cli_main_wires_identity_and_theme(qtbot, theme_scope, monkeypatch) -> None:
    """cli.main sets org/app identity and applies a theme before show (no real exec loop).

    Stubs QApplication.exec to return 0 immediately so main() does not block; the ``theme_scope``
    fixture already points QSettings's IniFormat path under tmp_path (so main()'s real
    "rosbagger" scope writes there, not ~/.config) and clears the global stylesheet on teardown.
    Asserts that after main() the QApplication carries a non-empty stylesheet (the theme was
    applied before show) and the org/app identity was set to the rosbagger scope.
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop import cli

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    rc = cli.main([])
    assert rc == 0
    assert QApplication.instance().styleSheet(), "cli.main did not apply a theme before show"
    assert QCoreApplication.organizationName() == "rosbagger", "cli.main did not set org identity"
    assert QCoreApplication.applicationName() == "rosbagger-desktop", (
        "cli.main did not set app identity"
    )


def test_view_menu_theme_toggle_flips_live(qtbot, theme_scope) -> None:
    """The View-menu checkable action flips theme_manager.name AND the live stylesheet (D-06).

    Builds a MainWindow (which self-constructs a ThemeManager when none is passed), triggers
    its View ▸ Dark theme action, and asserts BOTH the manager name and the live
    QApplication.styleSheet() flipped to the other theme — the no-relaunch live toggle wired
    into the shell. QSettings is scoped to tmp_path so the dev box conf is untouched (T-17-02).
    """
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.main_window import MainWindow
    from rosbagger_desktop.theme import DARK, LIGHT

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.theme_manager is not None, "a directly-built window must self-construct a manager"
    assert window.theme_action.isCheckable(), "the View theme action must be checkable"
    assert window.theme_manager.name == "dark", "fresh scope should default to dark"
    assert window.theme_action.isChecked(), "the action should reflect the dark default as checked"

    # Trigger the action (the user clicking the menu item) → live flip to light + persist.
    window.theme_action.trigger()
    assert window.theme_manager.name == "light", "the toggle action did not flip the manager name"
    assert not window.theme_action.isChecked(), "the action check state did not follow the flip"
    sheet = QApplication.instance().styleSheet()
    assert LIGHT.bg in sheet, "the live app stylesheet did not flip to LIGHT after the action"
    assert DARK.bg not in sheet, "the live app stylesheet still carries DARK after the action"

    # Trigger again → back to dark.
    window.theme_action.trigger()
    assert window.theme_manager.name == "dark", "the second toggle did not flip back to dark"
    assert window.theme_action.isChecked()


def test_main_window_builds_without_theme_manager_arg(qtbot) -> None:
    """An existing MainWindow() construction (no theme_manager) still builds + has a View menu.

    Regression-guards the Phase 16 call sites (and the bag-only path): omitting the new
    theme_manager arg must still build a themeable window with a working View toggle.
    """
    from rosbagger_desktop.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.theme_manager is not None, "no-arg window did not self-construct a ThemeManager"
    assert window.theme_action is not None, "no-arg window has no View theme action"


def test_replay_rate_loop_guarded_while_drive_running(qtbot, monkeypatch) -> None:
    """CR-02: rate/loop mutations are refused while a drive worker runs (no UI-thread race).

    The pure ``Replayer`` is a non-thread-safe state machine whose ``run()`` reads ``_rate`` and
    ``loop`` on the worker thread; mutating them from the UI thread mid-drive is a data race.
    With ``_drive_running()`` forced True and a sentinel replayer in place, ``_apply_rate`` /
    ``_apply_loop`` must NOT touch the replayer and must show a teaching status — mirroring the
    Play/Step/seek guard. (A real concurrent drive needs ROS; this isolates the guard logic.)
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    class _Sentinel:
        """Stand-in Replayer that records any mutation the guard should have blocked."""

        def __init__(self) -> None:
            self.loop = False
            self.rate_calls: list[float] = []

        def set_rate(self, rate: float) -> None:
            self.rate_calls.append(rate)

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    sentinel = _Sentinel()
    panel._replayer = sentinel  # type: ignore[assignment]
    # Force the "a drive worker is running" condition without a real ROS thread.
    monkeypatch.setattr(panel, "_drive_running", lambda: True)

    panel._rate_input.setText("2.0")
    panel._apply_rate()
    assert sentinel.rate_calls == [], "rate was mutated while a drive worker was running (CR-02)"
    assert "Pause before changing the rate" in panel.status_label.text()

    panel._apply_loop(True)
    assert sentinel.loop is False, "loop was mutated while a drive worker was running (CR-02)"
    assert "Pause before toggling loop" in panel.status_label.text()

    # Sanity: with no drive running the same calls DO apply (the guard is the only blocker).
    monkeypatch.setattr(panel, "_drive_running", lambda: False)
    panel._apply_rate()
    panel._apply_loop(True)
    assert sentinel.rate_calls == [2.0], "rate did not apply when no drive was running"
    assert sentinel.loop is True, "loop did not apply when no drive was running"


# ---------------------------------------------------------------------------
# 17-02: shared widgets/ models + accessible status helper
# ---------------------------------------------------------------------------


def test_rows_model_renders_headers_and_cells() -> None:
    """RowsTableModel renders its headers + list-of-tuple rows lazily via ``str()`` (D-02).

    A pure model unit test (no QApplication needed): a two-column model over one tuple row
    reports the right dimensions, str()-renders each cell on the DisplayRole, and exposes the
    headers on the horizontal header. Mirrors the lifted ``_ResultTableModel`` contract for the
    inspect/tf dataclass-row path.
    """
    from PySide6.QtCore import Qt

    from rosbagger_desktop.widgets import RowsTableModel

    model = RowsTableModel(["a", "b"], [("1", "2")])
    assert model.rowCount() == 1, "expected one row"
    assert model.columnCount() == 2, "expected two columns (one per header)"
    assert model.data(model.index(0, 0)) == "1", "cell (0,0) did not str()-render"
    assert model.data(model.index(0, 1)) == "2", "cell (0,1) did not str()-render"
    assert model.headerData(0, Qt.Horizontal) == "a", "header section 0 wrong"
    assert model.headerData(1, Qt.Horizontal) == "b", "header section 1 wrong"
    # Non-str inputs are str()-rendered (temporal-safe rule: never convert, only str()).
    model2 = RowsTableModel(["n"], [(42,)])  # type: ignore[list-item]
    assert model2.data(model2.index(0, 0)) == "42", "non-str cell was not str()-rendered"


def test_rows_model_set_rows_resets_bound_view(qtbot) -> None:
    """RowsTableModel.set_rows swaps rows inside begin/endResetModel so a bound view refreshes.

    Binds the model to a real ``QTableView`` and asserts the view's model sees the new row
    count after ``set_rows`` — proving the begin/endResetModel wrapping notifies the view.
    """
    from PySide6.QtWidgets import QTableView

    from rosbagger_desktop.widgets import RowsTableModel

    model = RowsTableModel(["x", "y"])
    view = QTableView()
    qtbot.addWidget(view)
    view.setModel(model)
    assert view.model().rowCount() == 0, "fresh model should be empty"

    model.set_rows([("1", "2"), ("3", "4")])
    assert view.model().rowCount() == 2, "set_rows did not propagate the new rows to the view"
    assert view.model().data(view.model().index(1, 0)) == "3", "swapped row not rendered"


def test_set_status_sets_text_a11y_and_error_affordance(qtbot) -> None:
    """set_status sets text + accessibleDescription and toggles the status_error objectName.

    Under offscreen the error path is a NO-OP announce (no QAccessible Alert → no segfault)
    but STILL sets the ``status_error`` objectName affordance (the color comes from the theme
    QSS, D-03). A subsequent non-error call restores the label's original objectName so the
    affordance is path-scoped, and the accessible description tracks the text both ways.
    """
    from PySide6.QtWidgets import QLabel

    from rosbagger_desktop.widgets import set_status

    label = QLabel()
    label.setObjectName("inspect_status")  # a non-error base objectName to restore to
    qtbot.addWidget(label)

    # Error path: text + a11y description set, status_error objectName applied, no crash.
    set_status(label, "boom — teaching message", is_error=True)
    assert label.text() == "boom — teaching message"
    assert label.accessibleDescription() == "boom — teaching message"
    assert label.objectName() == "status_error", "error path did not toggle status_error (D-03)"

    # Success path: original objectName restored (affordance cleared), description tracks text.
    set_status(label, "all good")
    assert label.text() == "all good"
    assert label.accessibleDescription() == "all good"
    assert label.objectName() == "inspect_status", "non-error path did not restore base objectName"
