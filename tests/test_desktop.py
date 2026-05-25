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

    # All offline nav rows are present and enabled (offline panels always enabled, D-08).
    from PySide6.QtCore import Qt

    assert window._nav.count() == 3
    for row in range(window._nav.count()):
        assert bool(window._nav.item(row).flags() & Qt.ItemIsEnabled), (
            "an offline nav row was unexpectedly disabled"
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
    """SC2/SC3 (query): the Query panel drives a REAL ``query()`` over a fixture bag.

    Writes a ROS 2 sqlite3 fixture bag, opens ``MainWindow`` on it, shows the Query
    panel so its ``refresh_view()`` builds the schema tree, derives a known table name
    from the panel's own schema tree (so the test is robust to fixture topic changes),
    sets a ``SELECT * FROM <table> LIMIT 1`` and triggers Run via the Run button. The
    results ``QTableWidget`` must then carry real ``rosbagger_core.backend.query.query``
    rows (``rowCount() > 0`` and ``columnCount() > 0``) — SC2/SC3.

    A second leg drives a SELECT over a clearly-unknown table and asserts the status
    label shows a non-empty teaching string with NO exception raised (the
    UnknownTableError path; T-16-02-TEACH). pytest-qt is synchronous — no ``await``.
    """
    from PySide6.QtCore import Qt
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

    # Run a real SELECT and assert rows landed in the results table (SC2/SC3).
    panel.sql_input.setText(f"SELECT * FROM {table_name} LIMIT 1")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)

    assert panel.results_table.rowCount() > 0, (
        "query results table had 0 rows; expected real query() rows from a fixture table"
    )
    assert panel.results_table.columnCount() > 0, (
        "query results table had 0 columns; expected real query() columns"
    )
    # A successful query enables export (D-06).
    assert panel.export_csv_button.isEnabled()
    assert panel.export_parquet_button.isEnabled()

    # Teaching path: an unknown table sets a non-empty status string, no exception.
    panel.sql_input.setText("SELECT * FROM definitely_not_a_real_table")
    qtbot.mouseClick(panel.run_button, Qt.LeftButton)
    status_text = panel.status_label.text()
    assert status_text, "query status was empty; expected an UnknownTableError teaching message"
    assert "row(s)" not in status_text, (
        "unknown-table query should NOT report a row count; expected the teaching error text"
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

    # The offline rows stay enabled even with ROS absent (D-08).
    assert window._nav.count() == 3
    for row in range(window._nav.count()):
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
