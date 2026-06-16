"""Headless GUI proof tests (GUI-01 / SC1+SC2+SC3) — ROS-FREE in CI.

This is the PROOF layer for the Textual cockpit (Phase 14). It drives the real
``RosbaggerApp`` headlessly via ``App.run_test()`` / ``Pilot`` against a fixture bag
written into ``tmp_path`` by the ROS-FREE ``tools.make_fixtures`` writer (the same
writer the reader / query / tf suites use), and asserts the three GUI-01 success
criteria become passing automated tests:

* **SC1 — five panels exposed.** Launching ``RosbaggerApp`` exposes all five panels:
  the five sidebar ``nav-*`` ids AND the five ``ContentSwitcher`` panel ids are all
  queryable (``test_app_has_five_panels``).
* **SC2 — capability-gating.** With ROS forced ABSENT (monkeypatch
  ``rosbagger_gui._detect_ros`` → ``False`` so the assertion is meaningful on this
  ROS-equipped dev box), the LIVE panels (record/replay) + their nav items are
  ``disabled`` while the OFFLINE panels (inspect/query/tf) are NOT — and the offline
  panels still WORK without ROS (``test_live_panels_disabled_without_ros``).
* **SC3 — inspect + query drive REAL ``rosbagger_core`` output to the widgets.**
  Selecting the inspect panel renders real ``collect_bag_info`` topic rows into the
  ``bag-info`` DataTable (``test_inspect_panel_shows_real_topics``); typing a SELECT
  over a known fixture table into ``sql-input`` and pressing Enter runs the real
  ``query()`` and lands its rows in the ``results`` DataTable
  (``test_query_panel_runs_real_core``). Both are ROS-FREE.

ASYNC (14-RESEARCH Pitfall 3): ``asyncio_mode="auto"`` is set in the root pyproject
(Plan 14-02), so these are plain ``async def`` tests — no per-test ``@pytest.mark.asyncio``
marker is needed and they are NOT skipped.

PAUSE-BEFORE-ASSERT (14-RESEARCH Pitfall 4): every interaction is followed by
``await pilot.pause()`` to flush the Textual message pump before asserting, so an
assertion never races an un-applied mount / switch / query result.

SELF-CONTAINED HARNESS: mirrors the reader / tf suites — this module owns its own
repo-root ``sys.path`` insert (so ``tools.make_fixtures`` resolves when only the repo
root is on the path) and writes its OWN fixture bag into ``tmp_path``; it reuses no
shared fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from textual.widgets import Button, ContentSwitcher, DataTable, Input, ListItem, Static

# Self-contained src/repo-root resolution (mirrors tests/test_tf.py / test_reader.py):
# put the repo root + the gui/core src trees on the path so ``tools.make_fixtures`` and
# ``rosbagger_gui`` import regardless of how the suite is launched. Harmless when already
# importable (the membership check guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (
    _REPO_ROOT,
    _REPO_ROOT / "packages" / "rosbagger-gui" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.make_fixtures import write_ros2_sqlite_bag  # noqa: E402

import rosbagger_gui  # noqa: E402  (forced-no-ROS monkeypatch target for SC2)
from rosbagger_gui.app import RosbaggerApp  # noqa: E402

# The known fixture topics (tools.make_fixtures) → tables. /imu and /cmd_vel become the
# ``imu`` / ``cmd_vel`` query tables; SC3 queries one of them and asserts a real row.
_EXPECTED_TABLES = {"imu", "cmd_vel", "image"}


@pytest.fixture
def bag(tmp_path: Path) -> Path:
    """Write a ROS 2 sqlite3 fixture bag into ``tmp_path`` (ROS-FREE) and return it.

    The same ``write_ros2_sqlite_bag`` writer the reader / query suites use: 3 topics
    (``/imu``, ``/cmd_vel``, ``/image``), 3 messages each. The App opens it with the
    ROS-2-Humble typestore default (14-02), so SC3 reads real core output off it.
    """
    return write_ros2_sqlite_bag(tmp_path)


async def test_app_has_five_panels(bag: Path) -> None:
    """SC1: the launched App exposes all five panels (nav ids + ContentSwitcher ids).

    Drives the real ``RosbaggerApp`` headlessly and asserts the five ``nav-*`` sidebar
    ListItems AND the five ``ContentSwitcher`` panel widgets are all mounted/queryable —
    the cockpit surfaces inspect/query/tf/record/replay over the module APIs (D-01).
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()  # flush mount before asserting (Pitfall 4)

        panel_ids = ("inspect", "query", "tf", "record", "replay")
        for panel_id in panel_ids:
            # The sidebar nav ListItem (id = "nav-" + panel id) must exist.
            assert app.query_one(f"#nav-{panel_id}", ListItem) is not None
            # The ContentSwitcher child panel (id = panel id) must exist.
            assert app.query_one(f"#{panel_id}") is not None

        # The ContentSwitcher itself holds exactly the five panel children.
        switcher = app.query_one("#content", ContentSwitcher)
        switcher_child_ids = {child.id for child in switcher.children}
        assert switcher_child_ids == set(panel_ids)


async def test_live_panels_disabled_without_ros(bag: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SC2: with ROS forced absent the LIVE panels are disabled, the OFFLINE ones are not.

    Forces the no-ROS condition DETERMINISTICALLY (monkeypatch
    ``rosbagger_gui._detect_ros`` → ``False`` BEFORE constructing the App, so the
    capability gate is exercised even on this ROS-equipped dev box). Asserts the live
    record/replay nav items + panel widgets are ``disabled`` while the offline
    inspect/query/tf ones are NOT — and that the offline panels still render real data
    without ROS (the inspect ``bag-info`` table fills), so "offline panels work without
    ROS" is proven, not merely "live panels are gated".
    """
    # Force ROS absent for THIS app (monkeypatch the probe the App ctor calls in 14-02).
    monkeypatch.setattr(rosbagger_gui, "_detect_ros", lambda: False)

    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()  # flush mount + the on_mount gate before asserting (Pitfall 4)

        assert app.ros_available is False, "forced-no-ROS app must report ros_available False"

        # LIVE panels (record/replay): both the nav item AND the panel widget disabled.
        for live_id in ("record", "replay"):
            assert app.query_one(f"#nav-{live_id}", ListItem).disabled is True
            assert app.query_one(f"#{live_id}").disabled is True

        # OFFLINE panels (inspect/query/tf): NOT disabled — always enabled (D-03).
        for offline_id in ("inspect", "query", "tf"):
            assert app.query_one(f"#nav-{offline_id}", ListItem).disabled is False
            assert app.query_one(f"#{offline_id}").disabled is False

        # And the offline panels WORK without ROS: the inspect bag-info table fills from
        # real core output even with ros_available False.
        await pilot.click("#nav-inspect")
        await pilot.pause()
        bag_info = app.query_one("#bag-info", DataTable)
        assert bag_info.row_count >= 1, "inspect panel did not render real topics without ROS"


async def test_inspect_panel_shows_real_topics(bag: Path) -> None:
    """SC3 (inspect): the inspect panel renders REAL ``collect_bag_info`` topic rows.

    Selects the inspect panel against the fixture bag and asserts the ``bag-info``
    DataTable has at least one row — i.e. real ``rosbagger_core.inspect`` topic output
    reached the widget (the fixture has 3 topics, so ``row_count >= 1`` is a safe lower
    bound). ``row_count`` is the stable 8.2.7 DataTable accessor (the column-introspection
    accessor shifted across versions; row_count did not — verified against textual 8.2.7).
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-inspect")
        await pilot.pause()  # flush the panel switch + refresh_view before asserting

        bag_info = app.query_one("#bag-info", DataTable)
        assert bag_info.row_count >= 1, (
            f"inspect bag-info had {bag_info.row_count} rows; expected real topics from core"
        )


async def test_inspect_and_tf_panels_render_with_height(bag: Path) -> None:
    """GUI-01 blank-panel regression guard: the inspect/tf panels render at non-zero height.

    ``test_inspect_panel_shows_real_topics`` only asserts ``row_count`` — which PASSED even
    while ``InspectPanel`` / ``TfPanel`` (bare ``textual.widget.Widget`` subclasses with no
    intrinsic height) laid out at height 0 and rendered their populated DataTables INVISIBLE.
    Rendered region height, NOT row_count, is the assertion that catches that collapse: a
    DataTable at ``region.height == 0`` is invisible, so this fails if either panel regresses.

    Inspect: click ``#nav-inspect`` and assert the ``#bag-info`` DataTable has
    ``region.height > 0`` (the precise regression signal) AND ``row_count >= 1`` (so the
    table is both VISIBLE and carrying real core data, not merely sized-but-empty).

    TF: click ``#nav-tf`` and assert the ``#tf-edges`` DataTable has ``region.height > 0``.
    The fixture bag has no ``/tf``, so the tf panel shows the teaching status line and the
    edges table may be empty — assert on region height ONLY for tf (NOT row_count), since
    "no transforms" is a valid empty state.
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.click("#nav-inspect")
        await pilot.pause()  # flush the panel switch + refresh_view before asserting
        bag_info = app.query_one("#bag-info", DataTable)
        assert bag_info.region.height > 0, (
            f"inspect #bag-info rendered at height {bag_info.region.height}; "
            "the panel collapsed to height 0 (GUI-01 blank-panel regression)"
        )
        assert bag_info.row_count >= 1, (
            "inspect #bag-info is sized but empty; expected real topics from core"
        )

        await pilot.click("#nav-tf")
        await pilot.pause()  # flush the panel switch + refresh_view before asserting
        tf_edges = app.query_one("#tf-edges", DataTable)
        assert tf_edges.region.height > 0, (
            f"tf #tf-edges rendered at height {tf_edges.region.height}; "
            "the panel collapsed to height 0 (GUI-01 blank-panel regression)"
        )


async def test_query_panel_runs_real_core(bag: Path) -> None:
    """SC3 (query): a SELECT over a fixture table lands REAL ``query()`` rows in ``results``.

    Selects the query panel, sets ``sql-input`` to ``SELECT topic, t_ns FROM imu LIMIT 1``
    (``imu`` is the known fixture table from ``write_ros2_sqlite_bag``), and presses Enter
    — the SC3 ``press("enter")`` path (the Run BUTTON can miss on the default 80-col
    viewport in the headless harness; the Enter-on-input path is the documented robust
    trigger, 14-04 SUMMARY). Asserts the ``results`` DataTable row_count == 1, i.e. real
    ``rosbagger_core.backend.query.query()`` output reached the widget. ``row_count`` is
    the stable 8.2.7 accessor.
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-query")
        await pilot.pause()  # flush the switch + schema-tree refresh

        # Set the SQL string + run via the Enter-on-input path (NOT a Run-button click,
        # which can miss off-screen on the default viewport — 14-04 harness caveat).
        sql_input = app.query_one("#sql-input", Input)
        sql_input.focus()
        await pilot.pause()
        sql_input.value = "SELECT topic, t_ns FROM imu LIMIT 1"
        await pilot.press("enter")
        # F6: query() now runs on a thread worker; wait for it before asserting on the widget it
        # updates via call_from_thread (pilot.pause() alone is a CPU-idle heuristic that can break
        # EARLY while the worker blocks on I/O — see tests/test_gui_live.py's worker-wait note).
        await app.workers.wait_for_complete()
        await pilot.pause()  # flush the call_from_thread render before asserting

        results = app.query_one("#results", DataTable)
        assert results.row_count == 1, (
            f"query results had {results.row_count} rows; expected exactly 1 real query() row"
        )


async def test_query_panel_select_star_renders_timestamp_columns(bag: Path) -> None:
    """SW2: `SELECT *` (which projects the timestamp[ns] `t`/`stamp` columns) renders rows.

    Before the fix the TUI panel's _fill_results called table.to_pylist(), which RAISES
    ValueError on a timestamp[ns] column with no pandas — and the crash was outside the run
    handler's try/except, so the query action broke. rows_for_display renders it safely.
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-query")
        await pilot.pause()
        sql_input = app.query_one("#sql-input", Input)
        sql_input.focus()
        await pilot.pause()
        sql_input.value = "SELECT * FROM imu"
        await pilot.press("enter")
        # F6: let the query worker finish (call_from_thread render).
        await app.workers.wait_for_complete()
        await pilot.pause()
        results = app.query_one("#results", DataTable)
        assert results.row_count == 3, (
            f"SELECT * rendered {results.row_count} rows; expected 3 (timestamp columns "
            "must not crash _fill_results)"
        )


async def test_inspect_panel_unresolvable_type_teaches_not_crashes(
    bag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A core failure inspecting a bag (e.g. get_msgdef KeyError on a custom-type def-less bag)
    teaches in the header instead of crashing the TUI.

    Regression for the audit bug: InspectPanel.refresh_view called collect_bag_info /
    collect_table_schemas unguarded, so a bare KeyError out of the schema walk bubbled out of
    the event handler and (exit_on_error=True) tore down the cockpit. We simulate the failure by
    forcing collect_table_schemas to raise — TfPanel already guards its analogous failure.
    """
    import rosbagger_core.inspect as insp

    def boom(_reader: object) -> None:
        raise KeyError("pkg/msg/CustomType")

    monkeypatch.setattr(insp, "collect_table_schemas", boom)

    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-inspect")
        await pilot.pause()  # flush the panel switch + refresh_view

        # Reaching here proves the app did not panic; the failure became a teaching line.
        header = str(app.query_one("#inspect-header", Static).render())
        assert "Cannot inspect" in header, f"expected a teaching header, got {header!r}"


async def test_query_panel_malformed_sql_teaches_instead_of_crashing(bag: Path) -> None:
    """A SQL typo (sqlglot ParseError / DuckDB catalog error) teaches, never crashes the TUI.

    Regression for the audit HIGH bug: ``_execute_query_worker`` caught only the three
    semantic teaching errors, so a parse/binder/catalog error escaped the thread worker
    and — with the app's default ``exit_on_error=True`` — panicked the whole cockpit. A
    SQL typo is the most common interactive-SQL mistake. The broad fallback surfaces it as
    a ``Query failed: …`` status line instead. Reaching the assertion at all proves the
    app did not panic.
    """
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-query")
        await pilot.pause()
        sql_input = app.query_one("#sql-input", Input)
        sql_input.focus()
        await pilot.pause()
        # An unknown scalar function -> DuckDB Catalog Error, which is NOT one of the three
        # teaching errors and (unlike a missing column) does not match the binder-column regex,
        # so it is re-raised out of query() — the exact escape path that used to crash the app.
        sql_input.value = "SELECT made_up_fn(t_ns) FROM imu"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()  # flush the call_from_thread status update

        status = str(app.query_one("#query-status", Static).render())
        assert "Query failed" in status, f"expected a teaching status, got {status!r}"
        # No result was produced, so export stays disabled (no half-rendered state).
        assert app.query_one("#export-csv", Button).disabled is True


async def test_replay_panel_rejects_bad_rate_on_play(
    bag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """newD16: pressing Play with a bad rate teaches 'Invalid rate' instead of silently 1.0.

    The TUI replay panel's old ``_read_rate`` coerced a non-numeric / ``<=0`` entry to 1.0 at
    transport-build time, so Play quietly played at 1.0 while reporting ``"Playing… rate 1"``.
    The fix validates the rate up front in ``_ensure_transport`` — BEFORE any ``import rclpy`` —
    so the rejection path is exercisable OFFLINE: we force ``ros_available`` True (so the Play
    handler runs) and the bad rate short-circuits the build before the ROS context, no ROS
    needed. Asserts the teaching status AND that no transport was built.
    """
    # Force ROS "present" so the Play handler runs; the bad rate returns before `import rclpy`.
    # app.py binds `_detect_ros` at import (`from . import _detect_ros`), so patch the name on
    # the app module — patching the package attr would miss the already-bound reference.
    monkeypatch.setattr("rosbagger_gui.app._detect_ros", lambda: True)

    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.ros_available is True
        await pilot.click("#nav-replay")
        await pilot.pause()

        panel = app.query_one("#replay")
        app.query_one("#replay-rate", Input).value = "abc"
        panel._play()  # noqa: SLF001 - drive the Play handler directly (the build-path under test)
        await pilot.pause()

        status = str(app.query_one("#replay-status", Static).render())
        assert "Invalid rate" in status, f"expected a teaching status, got {status!r}"
        # The bad rate refused the build (no half-built transport, no silent rate-1 playback).
        assert panel._replayer is None  # noqa: SLF001


async def test_query_schema_tree_cached_across_revisits(
    bag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7 (TUI): re-visiting the Query tab does NOT rebuild the schema Tree (reader-identity cache).

    ``on_show`` calls ``refresh_view`` on every Query-tab visit. We measure the DELTA in
    ``collect_table_schemas`` calls across a query → tf → query revisit (the TF panel does NOT
    call ``collect_table_schemas``, unlike inspect — so any delta is the query panel rebuilding).
    A working cache => zero delta on the revisit.
    """
    import rosbagger_core.inspect as insp

    calls: list[int] = []
    real = insp.collect_table_schemas
    monkeypatch.setattr(
        insp, "collect_table_schemas", lambda reader: (calls.append(1), real(reader))[1]
    )

    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#nav-query")
        await pilot.pause()
        before = len(calls)  # the query tree was built (at most) once by now
        await pilot.click("#nav-tf")  # tf does NOT call collect_table_schemas
        await pilot.pause()
        await pilot.click("#nav-query")  # revisit — must hit the cache, not rebuild
        await pilot.pause()
        assert len(calls) == before, (
            f"revisiting the Query tab rebuilt the schema Tree ({len(calls) - before} extra "
            "collect_table_schemas calls); the reader-identity cache should make it a no-op"
        )
