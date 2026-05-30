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

from tools.make_fixtures import (  # noqa: E402
    write_ros2_sqlite_bag,
    write_ros2_sqlite_bag_defless,
    write_tf_bag,
)

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


def test_no_inline_color_in_any_panel_or_shell(qtbot) -> None:
    """SC1/D-03: no panel or shell widget carries an inline stylesheet — color is app-level.

    Constructs ``MainWindow`` (all five panels) and walks EVERY descendant ``QWidget`` of each
    panel and the shell chrome (nav rail / panel stack / central), asserting each widget's own
    ``.styleSheet()`` is empty. Per D-03 ALL color/QSS lives in the app-level theme
    (``theme/qss.py``) targeted by objectNames / dynamic properties — never an inline per-widget
    literal. The single app stylesheet on ``QApplication`` is where color belongs; an inline
    widget stylesheet would breach the single-source rule (T-17-09).
    """
    from PySide6.QtWidgets import QWidget

    window = MainWindow()
    qtbot.addWidget(window)

    roots: list[QWidget] = [window._nav, window._stack, window.centralWidget()]
    roots.extend(window.panels.values())

    seen: set[int] = set()
    for root in roots:
        for widget in [root, *root.findChildren(QWidget)]:
            if id(widget) in seen:
                continue
            seen.add(id(widget))
            assert widget.styleSheet() == "", (
                f"{widget.objectName() or type(widget).__name__} carries an inline stylesheet — "
                "color must live only in the app-level theme/qss.py (D-03)"
            )


def test_shell_and_panels_carry_theme_object_names(qtbot) -> None:
    """SC1/D-03: the shell chrome + each panel's status/header expose theme objectNames.

    The theme QSS targets these objectNames (nav rail / panel stack / central + per-panel
    status lines), so asserting they are set proves the panels opt into the centralized theme
    rather than styling themselves inline.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    assert window._nav.objectName() == "nav_list"
    assert window._stack.objectName() == "panel_stack"
    assert window.centralWidget().objectName() == "shell_central"

    assert window.inspect_panel.status_label.objectName() == "inspect_status"
    assert window.query_panel.status_label.objectName() == "query_status"
    assert window.tf_panel.status_label.objectName() == "tf_status"
    assert window.record_panel.status_label.objectName() == "record_status"
    assert window.replay_panel.status_label.objectName() == "replay_status"


def test_record_replay_status_is_accessible_and_error_styled(qtbot) -> None:
    """D-02: record + replay status labels are accessibly named and route errors through set_status.

    Builds both live panels and asserts each status label exposes an ``accessibleName`` (so a
    screen reader announces a named status region) and a base objectName the theme QSS targets.
    Then drives an ERROR path on each (an invalid rate on replay; the no-ROS hint on record via a
    forced-no-ROS scan) and asserts the shared ``set_status`` toggled the ``status_error``
    objectName affordance (the color comes from the theme QSS — D-03, no inline literal) without
    crashing under offscreen Qt (the QAccessible Alert is guarded, D-09).
    """
    from rosbagger_desktop.panels.record_panel import RecordPanel
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    record = RecordPanel()
    replay = ReplayPanel()
    qtbot.addWidget(record)
    qtbot.addWidget(replay)

    # Accessibly named + theme-targeted base objectName on both (D-02 a11y parity).
    assert record.status_label.accessibleName() == "Record status"
    assert record.status_label.objectName() == "record_status"
    assert replay.status_label.accessibleName() == "Replay status"
    assert replay.status_label.objectName() == "replay_status"

    # Replay error path: an invalid rate routes through set_status(is_error=True) → status_error.
    replay.rate_input.setText("fast")
    assert replay._validated_rate() is None  # the error path sets the teaching status + affordance
    assert replay.status_label.objectName() == "status_error", (
        "replay invalid-rate did not toggle the status_error affordance (D-02/D-03)"
    )
    assert "Invalid rate" in replay.status_label.text()

    # Record error path: a scan with ROS forced absent routes the no-ROS hint as an error. The
    # panel reads ros_available off its window(); with no parent window the getattr default is
    # False, so the scan takes the teaching-hint error branch.
    record._scan_topics()
    assert record.status_label.objectName() == "status_error", (
        "record no-ROS hint did not toggle the status_error affordance (D-02/D-03)"
    )

    # A subsequent success-path status clears the affordance back to the base objectName.
    from rosbagger_desktop.widgets import set_status

    set_status(record.status_label, "all good")
    assert record.status_label.objectName() == "record_status", (
        "record success path did not restore the base objectName (path-scoped affordance)"
    )


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
    # 17-02 / D-02: inspect now refreshes OFF the UI thread on a BlockingWorker — wait for
    # the model to populate via the worker's result slot rather than asserting synchronously.
    bag = write_ros2_sqlite_bag(tmp_path)
    window._open_reader(bag)
    window.inspect_panel.refresh_view()
    qtbot.waitUntil(
        lambda: window.inspect_panel.bag_info_table.model().rowCount() > 0, timeout=5000
    )
    assert window.inspect_panel.bag_info_table.model().rowCount() > 0, (
        "offline inspect panel did not render real topics without ROS"
    )


def test_inspect_panel_shows_real_topics(qtbot, tmp_path: Path) -> None:
    """SC3 (inspect): the inspect panel renders REAL ``collect_bag_info`` topic rows.

    Writes a ROS 2 sqlite3 fixture bag (3 topics), opens ``MainWindow`` on it, drives
    the inspect panel's ``refresh_view()``, and asserts the bag-info table's MODEL has > 0
    rows — i.e. real ``rosbagger_core.inspect`` output reached the view (17-02 / D-02 model/
    view). Because ``collect_*`` now runs OFF the UI thread on a ``BlockingWorker`` (P1), the
    rows arrive via signal — the test ``waitUntil``s the model populates.
    """
    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    window.inspect_panel.refresh_view()
    qtbot.waitUntil(
        lambda: window.inspect_panel.bag_info_table.model().rowCount() > 0, timeout=5000
    )
    assert window.inspect_panel.bag_info_table.model().rowCount() > 0, (
        "inspect bag-info had 0 rows; expected real topics from collect_bag_info"
    )
    # The schemas view also fills (one row per (table, column)).
    assert window.inspect_panel.schemas_table.model().rowCount() > 0, (
        "inspect schemas had 0 rows; expected real collect_table_schemas rows"
    )


def test_tf_panel_renders_or_teaches(qtbot, tmp_path: Path) -> None:
    """SC3 (tf): a /tf bag populates the edges table; a no-/tf bag shows the teaching text.

    Populated path: a ``write_tf_bag`` ROS 2 fixture (``/tf`` + ``/tf_static``) yields
    > 0 edge rows. Teaching path: a plain ``write_ros2_sqlite_bag`` fixture (no ``/tf``)
    makes ``collect_tf_report`` raise ``NoTransformsError`` — caught and rendered on the
    status line, with the edges table empty and no crash (T-16-TF).
    """
    # Populated path: a /tf bag yields edge rows. 17-02 / D-02: collect_tf_report now runs
    # OFF the UI thread on a BlockingWorker — wait for the model to populate via the result
    # slot rather than asserting synchronously.
    tf_dir = tmp_path / "with_tf"
    tf_bag = write_tf_bag(tf_dir, ros1=False, storage="sqlite3")
    tf_window = MainWindow(bag_path=str(tf_bag))
    qtbot.addWidget(tf_window)
    tf_window.tf_panel.refresh_view()
    qtbot.waitUntil(lambda: tf_window.tf_panel.edges_table.model().rowCount() > 0, timeout=5000)
    assert tf_window.tf_panel.edges_table.model().rowCount() > 0, (
        "tf edges table had 0 rows on a /tf bag; expected real collect_tf_report edges"
    )

    # Teaching path: a no-/tf bag shows the NoTransformsError teaching text, no crash. The
    # NoTransformsError now arrives on the worker's failed slot and is routed through the
    # shared accessible set_status — wait for the status to settle off the empty-state line.
    plain_dir = tmp_path / "no_tf"
    plain_bag = write_ros2_sqlite_bag(plain_dir)
    plain_window = MainWindow(bag_path=str(plain_bag))
    qtbot.addWidget(plain_window)
    plain_window.tf_panel.refresh_view()
    qtbot.waitUntil(
        lambda: plain_window.tf_panel.status_label.text() != "Open a bag with /tf to analyze",
        timeout=5000,
    )
    assert plain_window.tf_panel.edges_table.model().rowCount() == 0, (
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
        lambda: (
            "row(s)" not in panel.status_label.text()
            and panel.status_label.text() not in ("", "Running…")
        ),
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
        lambda: (
            "row(s)" not in panel.status_label.text()
            and panel.status_label.text() not in ("", "Running…")
        ),
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
    # 17-02 / D-02: inspect refreshes OFF the UI thread on a BlockingWorker — wait for the
    # model to populate via the worker's result slot rather than asserting synchronously.
    bag = write_ros2_sqlite_bag(tmp_path)
    window._open_reader(bag)
    window.inspect_panel.refresh_view()
    qtbot.waitUntil(
        lambda: window.inspect_panel.bag_info_table.model().rowCount() > 0, timeout=5000
    )
    assert window.inspect_panel.bag_info_table.model().rowCount() > 0, (
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

    Directly exercises the ref-clearing slot (``_on_drive_finished``, wired via ``on_finished``)
    and then closes the panel. Pre-fix the stale ``_drive_thread`` wrapper survived a completed
    run and ``closeEvent`` → ``stop_thread`` touched the destroyed C++ object; post-fix the ref
    is ``None`` after finish and the (also-hardened) ``stop_thread`` makes close a no-op.

    Phase 18 (REP-02): ``_on_drive_finished`` no longer re-enables rate/loop (they stay live
    throughout the drive — never disabled) and now STOPS the live-playhead timer. Assert the
    timer is stopped on finish; the controls are simply expected to remain enabled.
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    # Simulate a stale ref that a finished worker would have left + a running live-playhead
    # timer (as _start_drive leaves it), then the finish callback.
    panel._drive_thread = object()  # type: ignore[assignment]  # stand-in stale handle
    panel._position_timer.start()
    panel._on_drive_finished()
    assert panel._drive_thread is None, "drive-thread ref was not cleared on finish (CR-01)"
    assert not panel._position_timer.isActive(), "playhead timer not stopped on finish (Phase 18)"
    # Phase 18: rate/loop are LIVE — never disabled, so they remain enabled after a drive.
    assert panel._rate_input.isEnabled()
    assert panel._loop_checkbox.isEnabled()

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


def test_theme_toggle_restyles_all_five_panels_live(qtbot, theme_scope) -> None:
    """SC: the live View-menu toggle flips the theme across the shell + all five panels.

    Constructs ``MainWindow`` with all five panels and applies the (dark-default) theme, then
    captures ``QApplication.styleSheet()``, fires the View ▸ Dark theme action, and asserts the
    app stylesheet flipped to the LIGHT bg hex (and dropped the DARK bg) AND the manager name
    flipped — the offscreen-PROVABLE state (RESEARCH Pitfall 4: assert stylesheet content + the
    manager's flipped name, NOT pixels). All five panels are present and themed app-level — their
    own ``.styleSheet()`` is empty (color is the single app stylesheet, D-03), so re-polishing the
    one app sheet reaches every panel. Toggling back restores the DARK bg.
    """
    from PySide6.QtWidgets import QApplication

    from rosbagger_desktop.main_window import MainWindow
    from rosbagger_desktop.theme import DARK, LIGHT

    window = MainWindow()
    qtbot.addWidget(window)
    window.theme_manager.apply()  # ensure the dark default is on the live app first

    # All five panels exist and carry NO inline stylesheet — color is the single app-level sheet.
    for panel_id in ("inspect", "query", "tf", "record", "replay"):
        assert panel_id in window.panels, f"{panel_id} missing from the five-panel registry"
        assert window.panels[panel_id].styleSheet() == "", (
            f"{panel_id} panel carries an inline stylesheet — color must be app-level (D-03)"
        )

    before = QApplication.instance().styleSheet()
    assert DARK.bg in before, "the dark-default app stylesheet was not applied before the toggle"

    # Fire the live toggle (the user clicking View ▸ Dark theme).
    window.theme_action.trigger()
    after = QApplication.instance().styleSheet()
    assert after != before, "the app stylesheet did not change after the live toggle"
    assert LIGHT.bg in after, "the toggled app stylesheet did not flip to the LIGHT bg hex"
    assert DARK.bg not in after, "the toggled app stylesheet still carries the DARK bg"
    assert window.theme_manager.name == "light", "the toggle did not flip the manager name"

    # Toggle back → the whole window restyles to DARK again (live, no relaunch).
    window.theme_action.trigger()
    restored = QApplication.instance().styleSheet()
    assert DARK.bg in restored, "toggling back did not restore the DARK bg across the cockpit"
    assert window.theme_manager.name == "dark"


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


def test_replay_rate_loop_seek_live_while_drive_running(qtbot, monkeypatch) -> None:
    """Phase 18 (REP-02): rate/loop/seek apply LIVE while a drive worker runs — no "pause" gate.

    18-01 made the ``Replayer`` thread-safe (lock-guarded setters + a wake + the cursor-unchanged
    advance guard), so the desktop no longer refuses mid-play control. With ``_drive_running()``
    forced True and a sentinel replayer in place, ``_apply_rate`` / ``_apply_loop`` / ``_on_seeked``
    MUST reach the replayer (the inverse of the old CR-02 guard) and must NOT show any "Pause
    before …" teaching status. (A real concurrent drive needs ROS; this isolates the control
    logic.) The rate input + loop checkbox also stay ENABLED throughout a drive (see
    ``test_replay_controls_stay_enabled_during_drive``).
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    class _Sentinel:
        """Stand-in Replayer that records the mutations the panel forwards while playing."""

        def __init__(self) -> None:
            self.loop = False
            self.rate_calls: list[float] = []
            self.seek_calls: list[int] = []
            self.position_fraction = 0.5

        def set_rate(self, rate: float) -> None:
            self.rate_calls.append(rate)

        def seek(self, t_offset_ns: int) -> None:
            self.seek_calls.append(t_offset_ns)

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    sentinel = _Sentinel()
    panel._replayer = sentinel  # type: ignore[assignment]
    panel._bag_span_ns = 1_000  # so a fraction maps to a concrete ns offset
    panel._item_count = 10  # _update_position is a no-op when item_count == 0
    # Force the "a drive worker is running" condition without a real ROS thread.
    monkeypatch.setattr(panel, "_drive_running", lambda: True)

    panel._rate_input.setText("2.0")
    panel._apply_rate()
    assert sentinel.rate_calls == [2.0], "rate did not apply LIVE while the drive worker ran"
    assert "Pause before" not in panel.status_label.text()

    panel._apply_loop(True)
    assert sentinel.loop is True, "loop did not apply LIVE while the drive worker ran"
    assert "Pause before" not in panel.status_label.text()

    # A forward seek applies live (no _ensure_transport rebuild — transport already exists).
    panel._on_seeked(0.8)
    assert sentinel.seek_calls == [800], "seek did not apply LIVE while the drive worker ran"
    assert "Pause before" not in panel.status_label.text()


def test_replay_backward_seek_status_says_resuming_forward(qtbot) -> None:
    """Phase 18 (REP-02 / SC3): a backward drag honestly reports a forward resume, not a rewind.

    A backward scrub is a JUMP to an earlier timestamp + forward republish — RViz only renders
    what we publish from the seek point onward. ``_on_seeked`` compares the requested fraction to
    the current playhead and, when seeking backward, sets a "resuming forward" status (never
    implying reverse playback). A forward seek keeps the plain "Seeked to N%" status.
    """
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    class _Sentinel:
        def __init__(self) -> None:
            self.position_fraction = 0.6  # current playhead at 60%
            self.seek_calls: list[int] = []

        def seek(self, t_offset_ns: int) -> None:
            self.seek_calls.append(t_offset_ns)
            # Reflect the jump so a subsequent read mirrors a real Replayer.
            self.position_fraction = t_offset_ns / 1_000

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    sentinel = _Sentinel()
    panel._replayer = sentinel  # type: ignore[assignment]
    panel._bag_span_ns = 1_000
    panel._item_count = 10

    # Backward: from 60% to 20% — must say "resuming forward", never "rewind".
    panel._on_seeked(0.2)
    assert sentinel.seek_calls[-1] == 200
    text = panel.status_label.text()
    assert "resuming forward" in text
    assert "rewind" not in text.lower()

    # Forward: from 20% to 90% — the plain seeked status.
    panel._on_seeked(0.9)
    assert "resuming forward" not in panel.status_label.text()
    assert "90%" in panel.status_label.text()


def test_replay_controls_stay_enabled_during_drive(qtbot, monkeypatch) -> None:
    """Phase 18 (REP-02 / SC2): _start_drive keeps rate/loop enabled and starts the playhead poll.

    Pre-Phase-18 ``_start_drive`` disabled the rate input + loop checkbox for the drive's
    duration (the CR-02 belt-and-suspenders for the non-thread-safe Replayer). Now that the
    Replayer is thread-safe the controls stay live, and ``_start_drive`` starts the QTimer that
    polls ``position_fraction`` so the playhead tracks playback. Stub ``run_on_thread`` so no
    real thread/ROS is needed — we only assert the enable state + the timer is active.
    """
    import rosbagger_desktop.panels.replay_panel as rp
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    class _Replayer:
        position_fraction = 0.0

        def run(self) -> None:  # never actually called — run_on_thread is stubbed
            pass

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel._replayer = _Replayer()  # type: ignore[assignment]
    panel._item_count = 5

    # Stub the thread launcher so _start_drive does not spawn a real QThread/worker.
    monkeypatch.setattr(rp, "run_on_thread", lambda *a, **k: (object(), object()))

    panel._start_drive()

    assert panel._rate_input.isEnabled(), "rate input must stay enabled during a live drive"
    assert panel._loop_checkbox.isEnabled(), "loop checkbox must stay enabled during a live drive"
    assert panel._position_timer.isActive(), "playhead poll timer was not started by _start_drive"

    panel._position_timer.stop()  # clean up so the timer does not fire after the test


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


# --------------------------------------------------------------------------- #
# quick-260528-3w6: replay of a typestore-less ROS 2 sqlite3 bag (real rosbag2 #
# recording) must thread the window's ROS2_HUMBLE typestore into load_items so #
# rosbags can deserialize — otherwise Play raises AnyReaderError "Bag contains  #
# no type definitions". The OFFLINE reader already passes it (main_window.py    #
# Pitfall 5); these guard the replay face passing the SAME typestore.           #
# --------------------------------------------------------------------------- #


def test_window_typestore_resolves_defless_sqlite_bag(qtbot, tmp_path: Path) -> None:
    """quick-3w6 (A): MainWindow exposes a typestore that loads a def-less sqlite3 bag.

    A real rosbag2 sqlite3 recording embeds NO message definitions, so the replay
    loader needs a typestore. The window must expose the SAME ROS2_HUMBLE typestore the
    offline reader uses (Pitfall 5). Asserts ``window.default_typestore`` is non-None AND
    that feeding it to ``rosbagger_replay.load_items`` resolves the def-less fixture that
    fails WITHOUT it — i.e. the window provides what the replay path needs.
    """
    from rosbagger_replay import load_items

    bag = write_ros2_sqlite_bag_defless(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    # The fixture is genuinely def-less: load_items with no typestore reproduces the bug.
    import pytest
    from rosbags.highlevel import AnyReaderError

    with pytest.raises(AnyReaderError):
        load_items(bag)

    # The window exposes the resolving typestore, and it actually loads the bag.
    assert window.default_typestore is not None, "MainWindow did not expose default_typestore"
    items = load_items(bag, default_typestore=window.default_typestore)
    assert len(items) > 0, "window.default_typestore did not resolve the def-less sqlite3 bag"


def test_replay_panel_threads_typestore_into_load_items(qtbot, tmp_path: Path, monkeypatch) -> None:
    """quick-3w6 (B): the replay panel passes window.default_typestore into load_items.

    Drives the rclpy-FREE ``_load_markers`` path (the marker overlay also reads the bag via
    ``load_items``) so this runs headlessly in CI. Stubs ``list_events`` to a one-row sidecar
    so the method proceeds past the events gate, and spies ``rosbagger_replay.load_items`` to
    capture its kwargs. Asserts the panel forwarded ``default_typestore=window.default_typestore``
    — before the fix the panel called ``load_items(bag)`` with no typestore (kwargs empty).
    """
    import pyarrow as pa

    import rosbagger_core.events as events_mod
    import rosbagger_replay as replay_mod

    bag = write_ros2_sqlite_bag_defless(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)

    # One-row event sidecar so _load_markers proceeds to load_items (num_rows > 0).
    monkeypatch.setattr(
        events_mod,
        "list_events",
        lambda _bag: pa.table({"t_start_ns": [0], "label": ["e"]}),
    )

    captured: dict[str, object] = {}
    real_load = replay_mod.load_items

    def spy(_bag, **kwargs):
        captured["kwargs"] = kwargs
        return real_load(_bag, **kwargs)  # honestly load with whatever the panel passed

    monkeypatch.setattr(replay_mod, "load_items", spy)

    window.replay_panel._load_markers()

    assert "kwargs" in captured, "replay panel never reached load_items in _load_markers"
    assert captured["kwargs"].get("default_typestore") is window.default_typestore, (
        "replay panel did not thread window.default_typestore into load_items"
    )
    assert captured["kwargs"]["default_typestore"] is not None


# --------------------------------------------------------------------------- #
# Scrubber loop-region (Phase 19, REP-03 / SC2): dual In/Out handles + shaded
# region band. Region markable programmatically (panel Set-In/Out buttons,
# silent) AND by a user handle drag (emits region_changed). The region/handle
# colours come from theme tokens (region_fill / region_handle) — no inline hex.
# --------------------------------------------------------------------------- #


def test_tokens_have_region_fields() -> None:
    """DARK/LIGHT carry region_fill/region_handle and qss surfaces them (no inline widget hex)."""
    from rosbagger_desktop.theme.qss import region_colors
    from rosbagger_desktop.theme.tokens import DARK, LIGHT

    for tok in (DARK, LIGHT):
        for value in (tok.region_fill, tok.region_handle):
            assert isinstance(value, str) and value.startswith("#") and len(value) == 7, value
    # The accessor returns the active palette's (fill, handle) so the widget never inlines hex.
    assert region_colors(DARK) == (DARK.region_fill, DARK.region_handle)
    assert region_colors(LIGHT) == (LIGHT.region_fill, LIGHT.region_handle)


def test_scrubber_set_and_clear_loop_region(qtbot) -> None:
    """set_loop_region normalizes in<=out + clamps; loop_region reads back; clear -> None."""
    from rosbagger_desktop.widgets import Scrubber

    scrubber = Scrubber()
    qtbot.addWidget(scrubber)

    assert scrubber.loop_region is None  # no region by default

    scrubber.set_loop_region(0.2, 0.6)
    assert scrubber.loop_region == (pytest.approx(0.2), pytest.approx(0.6))

    scrubber.set_loop_region(0.6, 0.2)  # reversed -> normalized to (0.2, 0.6)
    assert scrubber.loop_region == (pytest.approx(0.2), pytest.approx(0.6))

    scrubber.set_loop_region(-0.5, 1.5)  # out-of-range -> clamped to (0.0, 1.0)
    assert scrubber.loop_region == (pytest.approx(0.0), pytest.approx(1.0))

    scrubber.clear_loop_region()
    assert scrubber.loop_region is None


def test_scrubber_programmatic_set_does_not_emit_region_changed(qtbot) -> None:
    """A programmatic set_loop_region/clear_loop_region is SILENT — only a user drag emits."""
    from rosbagger_desktop.widgets import Scrubber

    scrubber = Scrubber()
    qtbot.addWidget(scrubber)

    emitted: list[tuple[float, float]] = []
    scrubber.region_changed.connect(lambda a, b: emitted.append((a, b)))

    scrubber.set_loop_region(0.1, 0.9)
    scrubber.clear_loop_region()
    assert emitted == [], "programmatic region set/clear must not emit region_changed"


def test_scrubber_handle_drag_emits_region_changed(qtbot) -> None:
    """SC2: dragging a handle updates that bound (clamped, in<=out) and emits region_changed."""
    from rosbagger_desktop.widgets import Scrubber

    scrubber = Scrubber()
    qtbot.addWidget(scrubber)

    emitted: list[tuple[float, float]] = []
    scrubber.region_changed.connect(lambda a, b: emitted.append((a, b)))

    scrubber.set_loop_region(0.2, 0.6)
    emitted.clear()  # ignore the programmatic set (it is silent anyway)

    # Drag the OUT handle right to 0.8 — IN unchanged, region_changed fires with (0.2, 0.8).
    scrubber._update_drag_handle("out", 0.8)
    assert scrubber.loop_region == (pytest.approx(0.2), pytest.approx(0.8))
    assert emitted[-1] == (pytest.approx(0.2), pytest.approx(0.8))

    # Drag the IN handle PAST out (0.95) — clamped so in<=out (lands at the out bound, 0.8).
    scrubber._update_drag_handle("in", 0.95)
    in_frac, out_frac = scrubber.loop_region
    assert in_frac <= out_frac
    assert in_frac == pytest.approx(0.8)


def test_scrubber_click_far_from_handle_falls_through_to_seek(qtbot) -> None:
    """A press far from any handle is NOT a region grab — the playhead seek path is preserved."""
    from rosbagger_desktop.widgets import Scrubber

    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(200, 30)

    # With a region near the left edge, a hit-test far to the right finds no handle.
    scrubber.set_loop_region(0.05, 0.10)
    assert scrubber._handle_at(190) is None  # far right -> no handle -> falls through to seek
    # And a press near the OUT handle's pixel DOES grab it.
    width = max(1, scrubber.width() - 1)
    assert scrubber._handle_at(round(0.10 * width)) == "out"

    # The base playhead path still emits seeked on a programmatic-free value change.
    seeked: list[float] = []
    scrubber.seeked.connect(seeked.append)
    scrubber.setValue(500)  # a user-style value change (not _suppress_emit) -> seeked
    assert seeked and seeked[-1] == pytest.approx(0.5)


def test_scrubber_paint_with_region_does_not_crash(qtbot) -> None:
    """paintEvent with a region set draws the band + two handles without raising (token colours)."""
    from rosbagger_desktop.widgets import Scrubber

    scrubber = Scrubber()
    qtbot.addWidget(scrubber)
    scrubber.resize(200, 30)
    scrubber.set_loop_region(0.25, 0.75)
    scrubber.show()
    scrubber.repaint()  # force a synchronous paintEvent — must not raise
    # Sanity: still reads back the region after a paint.
    assert scrubber.loop_region == (pytest.approx(0.25), pytest.approx(0.75))


# --------------------------------------------------------------------------- #
# Replay advanced sub-panel + snippet loop region (Phase 19, REP-03 / SC3+SC4):
# a collapsible "Advanced" sub-panel with a Loop-region toggle + Set-In/Out
# buttons, wired to BOTH the Scrubber handles and the scheduler region; the
# region survives a transport rebuild (pause/seek/play). Sentinel-stub replayer
# pattern mirrors the live-control tests above.
# --------------------------------------------------------------------------- #


class _RegionReplayerStub:
    """A stand-in Replayer recording the region calls + serving a scripted position_fraction."""

    def __init__(self, position: float = 0.0) -> None:
        self.position_fraction = position
        self.set_region_calls: list[tuple[int, int]] = []
        self.clear_calls = 0
        self.seek_calls: list[int] = []

    def set_loop_region(self, in_ns: int, out_ns: int) -> None:
        self.set_region_calls.append((in_ns, out_ns))

    def clear_loop_region(self) -> None:
        self.clear_calls += 1

    def seek(self, t_offset_ns: int) -> None:
        self.seek_calls.append(t_offset_ns)


def test_replay_advanced_subpanel_exists_and_toggles(qtbot) -> None:
    """SC3: the Replay tab has a collapsible Advanced sub-panel that shows/hides its body."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel.show()

    # The header is a checkable toggle; the body starts hidden (collapsed) and holds the controls.
    assert panel.advanced_toggle.isCheckable()
    assert not panel.advanced_body.isVisible()
    assert panel.region_checkbox is not None
    assert panel.set_in_button is not None and panel.set_out_button is not None

    panel.advanced_toggle.setChecked(True)
    assert panel.advanced_body.isVisible(), "expanding the header did not show the advanced body"
    panel.advanced_toggle.setChecked(False)
    assert not panel.advanced_body.isVisible(), "collapsing the header did not hide the body"


def test_replay_set_in_out_read_position_fraction_and_set_both(qtbot) -> None:
    """SC3: Set-In/Out read position_fraction and set the bound on scrubber + active scheduler."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    stub = _RegionReplayerStub(position=0.3)
    panel._replayer = stub  # type: ignore[assignment]
    panel._bag_span_ns = 1_000
    panel._item_count = 10
    panel._region_checkbox.setChecked(True)  # region active -> scheduler is driven

    panel._on_set_in()  # reads position_fraction 0.3 -> in bound
    stub.position_fraction = 0.7
    panel._on_set_out()  # reads 0.7 -> out bound

    assert panel._loop_in_frac == pytest.approx(0.3)
    assert panel._loop_out_frac == pytest.approx(0.7)
    assert panel.scrubber.loop_region == (pytest.approx(0.3), pytest.approx(0.7))
    # Scheduler was driven with absolute t_ns (int(frac * bag_span_ns)).
    assert stub.set_region_calls[-1] == (300, 700)


def test_replay_loop_region_checkbox_on_off_calls_scheduler(qtbot) -> None:
    """The Loop-region checkbox ON calls set_loop_region (active); OFF calls clear_loop_region."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    stub = _RegionReplayerStub(position=0.0)
    panel._replayer = stub  # type: ignore[assignment]
    panel._bag_span_ns = 1_000
    panel._item_count = 10
    panel._loop_in_frac = 0.2
    panel._loop_out_frac = 0.6

    panel._region_checkbox.setChecked(True)  # -> set_loop_region(200, 600)
    assert stub.set_region_calls[-1] == (200, 600)

    panel._region_checkbox.setChecked(False)  # -> clear_loop_region
    assert stub.clear_calls >= 1


def test_replay_region_changed_updates_scheduler_and_status(qtbot) -> None:
    """A user handle drag (region_changed) stores the region + drives the active scheduler."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    stub = _RegionReplayerStub(position=0.0)
    panel._replayer = stub  # type: ignore[assignment]
    panel._bag_span_ns = 1_000
    panel._item_count = 10
    panel._region_checkbox.setChecked(True)

    panel._on_region_changed(0.2, 0.6)
    assert panel._loop_in_frac == pytest.approx(0.2)
    assert panel._loop_out_frac == pytest.approx(0.6)
    assert stub.set_region_calls[-1] == (200, 600)
    assert "Loop region" in panel.status_label.text()


def test_replay_region_survives_pause_seek_play_cycle(qtbot, monkeypatch) -> None:
    """SC4: a stored region is re-applied to a rebuilt Replayer (survives a transport rebuild)."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    # Store a region + activate it (as the user would have), with an initial replayer in place.
    panel._loop_in_frac = 0.25
    panel._loop_out_frac = 0.75
    panel._region_checkbox.setChecked(True)

    # Simulate a transport rebuild: stub out the heavy build so _ensure_transport installs a
    # fresh sentinel replayer + bag span, then runs the Phase-19 region re-apply tail.
    rebuilt = _RegionReplayerStub(position=0.0)

    def fake_ensure(self) -> bool:
        self._replayer = rebuilt
        self._bag_span_ns = 1_000
        self._item_count = 10
        # The real _ensure_transport's Phase-19 tail (re-apply the stored region on rebuild):
        if self._loop_in_frac is not None and self._loop_out_frac is not None:
            self._scrubber.set_loop_region(self._loop_in_frac, self._loop_out_frac)
            if self._region_checkbox.isChecked():
                self._apply_region_to_scheduler()
        return True

    monkeypatch.setattr(ReplayPanel, "_ensure_transport", fake_ensure)
    assert panel._ensure_transport()

    # The rebuilt replayer got the region re-applied (NOT lost across the rebuild).
    assert rebuilt.set_region_calls and rebuilt.set_region_calls[-1] == (250, 750)
    assert panel.scrubber.loop_region == (pytest.approx(0.25), pytest.approx(0.75))


# --------------------------------------------------------------------------- #
# Replay RViz-fidelity toggles (Phase 20, REP-04 / SC3): "Publish /clock" +
# "Re-publish static on seek" in the Advanced sub-panel, default OFF, threaded
# into build_publish_sink at transport build, and a post-seek static re-prime.
# --------------------------------------------------------------------------- #


def test_replay_fidelity_toggles_exist_and_default_off(qtbot) -> None:
    """SC3: the two fidelity toggles live in the Advanced sub-panel and default OFF."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    assert not panel.clock_checkbox.isChecked()
    assert not panel.static_seek_checkbox.isChecked()
    # Both ride inside the Phase-19 collapsible Advanced body.
    assert panel.clock_checkbox.parent() is panel.advanced_body
    assert panel.static_seek_checkbox.parent() is panel.advanced_body


def _drive_ensure_transport_with_sink_spy(panel, monkeypatch, qtbot):
    """Stub the lazy ROS bits so _ensure_transport runs offline + spy build_publish_sink kwargs.

    Returns the captured-kwargs dict. Mirrors the typestore-threading spy pattern: monkeypatch
    the front-door rosbagger_replay symbols the panel lazy-imports inside _ensure_transport.
    """
    import types

    captured: dict = {}

    def fake_build_publish_sink(node, **kwargs):
        captured.update(kwargs)
        sink = lambda item: None  # noqa: E731 - a trivial stub sink
        sink.tracker = None
        return sink, {"n": 0}

    # A fake rosbagger_replay module exposing exactly what _ensure_transport imports.
    fake = types.ModuleType("rosbagger_replay")
    fake.NoMessagesToReplayError = type("NoMessagesToReplayError", (Exception,), {})
    fake.RosNotAvailableError = type("RosNotAvailableError", (Exception,), {})
    fake.build_publish_sink = fake_build_publish_sink
    fake.load_items = lambda *a, **k: [
        types.SimpleNamespace(t_ns=0, topic="/a"),
        types.SimpleNamespace(t_ns=1000, topic="/a"),
    ]

    class _Replayer:
        def __init__(self, items, sink, **kwargs):
            self._items = items

        position_fraction = 0.0

    fake.Replayer = _Replayer
    monkeypatch.setitem(sys.modules, "rosbagger_replay", fake)

    # Stub rclpy so _ensure_transport's `import rclpy` + node/context calls succeed offline.
    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.ok = lambda: True  # we did NOT create the context -> no init/shutdown
    fake_rclpy.create_node = lambda name: types.SimpleNamespace(
        create_publisher=lambda *a, **k: None, destroy_node=lambda: None
    )
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)

    # A bag path so _bag_path() is non-None (the window getattr default is None otherwise).
    monkeypatch.setattr(panel, "_bag_path", lambda: "/tmp/fake.bag")
    monkeypatch.setattr(panel, "_default_typestore", lambda: object())

    assert panel._ensure_transport() is True
    return captured


def test_replay_clock_toggle_threads_publish_clock_into_sink(qtbot, monkeypatch) -> None:
    """SC3: checking 'Publish /clock' threads publish_clock=True into build_publish_sink."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel.clock_checkbox.setChecked(True)

    captured = _drive_ensure_transport_with_sink_spy(panel, monkeypatch, qtbot)
    assert captured.get("publish_clock") is True


def test_replay_static_toggle_threads_static_topics_into_sink(qtbot, monkeypatch) -> None:
    """SC3: checking 'Re-publish static on seek' threads static_topics={'/tf_static'}."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel.static_seek_checkbox.setChecked(True)

    captured = _drive_ensure_transport_with_sink_spy(panel, monkeypatch, qtbot)
    assert captured.get("static_topics") == frozenset({"/tf_static"})


def test_replay_fidelity_toggles_default_off_passes_no_new_kwargs(qtbot, monkeypatch) -> None:
    """Defaults OFF preserve today's call shape: publish_clock False + static_topics empty."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    # both unchecked (default)

    captured = _drive_ensure_transport_with_sink_spy(panel, monkeypatch, qtbot)
    assert captured.get("publish_clock") is False
    assert captured.get("static_topics") == frozenset()


def test_replay_seek_with_static_toggle_republishes_after_seek(qtbot, monkeypatch) -> None:
    """SC3: a seek with the static toggle on calls republish_static AFTER replayer.seek."""
    import types

    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel.static_seek_checkbox.setChecked(True)

    order: list[str] = []

    class _Replayer:
        position_fraction = 0.5

        def seek(self, t_offset_ns):
            order.append("seek")

    panel._replayer = _Replayer()
    panel._bag_span_ns = 1_000
    panel._item_count = 10
    panel._sink = types.SimpleNamespace(tracker=object())  # non-None sink
    monkeypatch.setattr(panel, "_ensure_transport", lambda: True)  # transport already built

    # Spy republish_static on the front door the panel lazy-imports.
    fake = types.ModuleType("rosbagger_replay")
    fake.republish_static = lambda sink: order.append("republish") or 1
    monkeypatch.setitem(sys.modules, "rosbagger_replay", fake)

    panel._on_seeked(0.2)
    assert order == ["seek", "republish"], f"expected seek before republish, got {order}"


def test_replay_seek_static_republish_noop_when_no_sink(qtbot, monkeypatch) -> None:
    """The republish-after-seek is a safe no-op when no sink is built (toggle on, _sink None)."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    panel.static_seek_checkbox.setChecked(True)

    class _Replayer:
        position_fraction = 0.5

        def seek(self, t_offset_ns):
            pass

    panel._replayer = _Replayer()
    panel._bag_span_ns = 1_000
    panel._item_count = 10
    panel._sink = None  # transport not built
    monkeypatch.setattr(panel, "_ensure_transport", lambda: True)

    # Must not raise (the `self._sink is not None` guard skips republish_static).
    panel._on_seeked(0.2)


def test_replay_rerun_button_present(qtbot) -> None:
    """Phase 22: Replay strip has a checkable 'Open in Rerun' button; mirror inert by default."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    assert panel.rerun_button.text() == "Open in Rerun"
    assert panel.rerun_button.isCheckable()
    assert panel._rerun_sink is None  # the drive tee is inert until the mirror is toggled on


def test_replay_rerun_toggle_unavailable_enters_install_state(qtbot, monkeypatch) -> None:
    """Toggling on with ROS up but rerun-sdk absent enters the install state — no pip, no viewer.

    Patches `_ros_available`→True (so we pass the ROS gate), `rerun_available`→False (so we take
    the install-on-click branch), and `run_on_thread`→no-op (so the pip worker never actually
    spawns). Asserts the button relabels + the 'Installing…' status fires WITHOUT opening a mirror.
    """
    import rosbagger_rerun
    from rosbagger_desktop.panels import replay_panel as replay_panel_mod
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    monkeypatch.setattr(panel, "_ros_available", lambda: True)
    monkeypatch.setattr(rosbagger_rerun, "rerun_available", lambda: False)
    monkeypatch.setattr(replay_panel_mod, "run_on_thread", lambda *a, **k: (None, None))

    panel.rerun_button.click()  # programmatic (mouseClick drops on a non-visible widget)

    assert panel.rerun_button.text() == "Open in Rerun (install)"
    assert panel._rerun_sink is None  # no mirror opened, no viewer spawned
    assert "Installing" in panel.status_label.text()


def test_replay_rerun_close_drops_sink_and_flushes(qtbot) -> None:
    """The toggle-off path drops the sink, flushes the recording, and resets the label."""
    from rosbagger_desktop.panels.replay_panel import ReplayPanel

    panel = ReplayPanel()
    qtbot.addWidget(panel)
    flushed = {"n": 0}

    class _Rec:
        def flush(self):
            flushed["n"] += 1

    panel._rerun_sink = lambda item: None
    panel._rerun_rec = _Rec()

    panel._close_rerun()

    assert panel._rerun_sink is None
    assert panel._rerun_rec is None
    assert flushed["n"] == 1
    assert panel.rerun_button.text() == "Open in Rerun"


def test_replay_pause_then_immediate_play_resumes(qtbot, monkeypatch) -> None:
    """260530-2iv: pause then IMMEDIATELY play must RESUME, not reject with 'Already playing'.

    Regression for the race where a post-pause worker is still finishing (thread isRunning()) but
    the Replayer is already PAUSED — the old guard wrongly rejected the resume. A fake replayer
    whose run() blocks until pause() reproduces the exact timing without ROS.
    """
    import threading

    from rosbagger_desktop.panels.replay_panel import ReplayPanel
    from rosbagger_replay.scheduler import State

    panel = ReplayPanel()
    qtbot.addWidget(panel)

    class _FakeReplayer:
        def __init__(self) -> None:
            self.rate = 1.0
            self.state = State.PAUSED
            self.position_fraction = 0.0
            self._resume = threading.Event()

        def play(self) -> None:
            self.state = State.PLAYING
            self._resume.clear()

        def pause(self) -> None:
            self.state = State.PAUSED
            self._resume.set()  # let the blocked run() return

        def run(self) -> None:
            self._resume.wait(timeout=5.0)

    fake = _FakeReplayer()
    panel._replayer = fake
    panel._item_count = 3
    monkeypatch.setattr(panel, "_ros_available", lambda: True)
    monkeypatch.setattr(panel, "_ensure_transport", lambda: True)

    panel.play_button.click()
    qtbot.wait(50)
    panel.pause_button.click()  # → fake.pause(); run() returns, `finished` not yet processed
    panel.play_button.click()  # IMMEDIATE play (the race) — must defer, not reject
    assert "already playing" not in panel.status_label.text().lower(), panel.status_label.text()

    # The deferred resume fires once the finishing worker stops → the drive restarts.
    qtbot.waitUntil(panel._drive_running, timeout=3000)

    # Cleanup: pause so the resumed worker returns (keeps teardown fast).
    panel.pause_button.click()
    qtbot.waitUntil(lambda: not panel._drive_running(), timeout=3000)
