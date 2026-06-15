"""Fixture-backed proof of the EVNT-01 event-sidecar I/O layer (SC2), no ROS install.

These tests exercise ``rosbagger_core.events`` — the ``<bag>.events.parquet`` sidecar
``sidecar_path`` derivation (D-11), ``add_event`` (write/append the fixed v1 schema, D-12),
and ``list_events`` (read it back, D-13) — purely over filesystem paths under ``tmp_path``;
no ``AnyReader`` read of bag content is needed (SC2 is pure sidecar I/O):

* **Path derivation (D-11 / Pitfall 7)** — a ROS 1 ``.bag`` file and an ``.mcap`` file
  strip their real extension (``with_suffix``); a ROS 2 DIRECTORY bag (any other suffix,
  incl. a *dotted* directory name like ``v1.2``) APPENDS ``.events.parquet`` to the full
  name, NEVER losing its last segment.
* **SC2 (write -> read-back)** — an ``add_event`` row is read back by ``list_events`` with
  the same four column values and the fixed v1 schema (the ``_ns`` columns are int64).
* **Append (D-13)** — a second ``add_event`` grows the sidecar to 2 rows in insertion order.
* **Point event (D-12)** — an instant event (``t_start_ns == t_end_ns``) round-trips.
* **Nullable note (D-12)** — ``note=None`` round-trips as a null cell.
* **Absent sidecar** — ``list_events`` on a bag with no sidecar returns a 0-row table that
  still carries the four columns (callers never crash on a missing sidecar).

LOCAL-RUN REQUIREMENT (MEMORY.md / 11-RESEARCH): this dev host sources ROS 2 onto
``PYTHONPATH``, which crashes a bare ``uv run pytest`` on collection. Run locally with the
host leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_events.py -q

CI is ROS-free, so it needs NO prefix — this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

from pathlib import Path

from rosbagger_core.events import (
    add_event,
    event_marker_fractions,
    list_events,
    sidecar_path,
)

_EVENT_COLUMNS = ["t_start_ns", "t_end_ns", "label", "note"]


# --- Path derivation (D-11 / Pitfall 7) -----------------------------------------------


def test_path_ros1_file_strips_bag_extension() -> None:
    """A ROS 1 ``.bag`` FILE strips its real extension (``with_suffix``)."""
    assert sidecar_path(Path("/data/run.bag")) == Path("/data/run.events.parquet")


def test_path_mcap_file_strips_mcap_extension() -> None:
    """An ``.mcap`` FILE strips its real extension (``with_suffix``)."""
    assert sidecar_path(Path("/data/run.mcap")) == Path("/data/run.events.parquet")


def test_path_ros2_directory_appends_to_full_name() -> None:
    """A ROS 2 DIRECTORY bag (no .bag/.mcap suffix) APPENDS, never strips."""
    assert sidecar_path(Path("/data/ros2_sqlite")) == Path("/data/ros2_sqlite.events.parquet")


def test_path_dotted_directory_name_keeps_last_segment() -> None:
    """A dotted directory name (``v1.2``) does NOT lose its ``.2`` (Pitfall 7).

    ``Path.with_suffix`` would corrupt this to ``/data/v1.events.parquet``; the file-vs-dir
    branch must append ``.events.parquet`` to the FULL directory name instead.
    """
    assert sidecar_path(Path("/data/v1.2")) == Path("/data/v1.2.events.parquet")


# --- SC2: write -> read-back ----------------------------------------------------------


def test_sidecar_write_then_read_back_one_row(tmp_path: Path) -> None:
    """SC2: an ``add_event`` row is read back with matching values + the fixed v1 schema."""
    bag = tmp_path / "run.bag"  # the sidecar sits next to it; the bag itself need not exist
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="turn", note="left")

    table = list_events(bag)
    assert table.num_rows == 1
    assert table.column_names == _EVENT_COLUMNS

    row = table.to_pylist()[0]
    assert row == {
        "t_start_ns": 1_000_000_000,
        "t_end_ns": 1_100_000_000,
        "label": "turn",
        "note": "left",
    }

    # D-12: the *_ns columns are int64/BIGINT so they line up with the topic tables' t_ns.
    schema = table.schema
    assert schema.field("t_start_ns").type == _int64()
    assert schema.field("t_end_ns").type == _int64()


def test_sidecar_file_is_written_next_to_bag(tmp_path: Path) -> None:
    """``add_event`` materializes the sidecar at the derived ``<bag>.events.parquet`` path."""
    bag = tmp_path / "run.bag"
    add_event(bag, t_start_ns=0, t_end_ns=0, label="start")
    assert sidecar_path(bag).exists()


# --- Append grows the row count (D-13) ------------------------------------------------


def test_append_grows_row_count_in_insertion_order(tmp_path: Path) -> None:
    """A second ``add_event`` grows the sidecar to 2 rows in order (read->concat->rewrite)."""
    bag = tmp_path / "run.bag"
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="first", note="a")
    add_event(bag, t_start_ns=2_000_000_000, t_end_ns=2_200_000_000, label="second", note="b")

    table = list_events(bag)
    assert table.num_rows == 2
    labels = table.column("label").to_pylist()
    assert labels == ["first", "second"]  # insertion order preserved


# --- Point/instant event (D-12) -------------------------------------------------------


def test_point_event_roundtrips_with_equal_start_end(tmp_path: Path) -> None:
    """A point event (``t_start_ns == t_end_ns``) round-trips (D-12 — an instant event)."""
    bag = tmp_path / "run.bag"
    add_event(bag, t_start_ns=1_500_000_000, t_end_ns=1_500_000_000, label="mark")

    row = list_events(bag).to_pylist()[0]
    assert row["t_start_ns"] == row["t_end_ns"] == 1_500_000_000
    assert row["label"] == "mark"


# --- Nullable note (D-12) -------------------------------------------------------------


def test_null_note_roundtrips(tmp_path: Path) -> None:
    """``add_event(..., note=None)`` round-trips with a null ``note`` (the column is nullable)."""
    bag = tmp_path / "run.bag"
    add_event(bag, t_start_ns=1_000_000_000, t_end_ns=1_100_000_000, label="turn")

    row = list_events(bag).to_pylist()[0]
    assert row["note"] is None


# --- Absent sidecar -------------------------------------------------------------------


def test_list_events_absent_sidecar_returns_empty_four_column_table(tmp_path: Path) -> None:
    """``list_events`` on a bag with no sidecar returns a 0-row table with the four columns."""
    bag = tmp_path / "never_written.bag"
    assert not sidecar_path(bag).exists()

    table = list_events(bag)
    assert table.num_rows == 0
    assert table.column_names == _EVENT_COLUMNS


def _int64():
    """Lazily fetch ``pyarrow.int64()`` (no pyarrow at this test module's top)."""
    import pyarrow as pa

    return pa.int64()


# --- event_marker_fractions (R8 — the shared scrubber-marker math) --------------------


def test_event_marker_fractions_maps_endpoints_and_midpoint():
    """R8: start timestamps map to (fraction, label) — 0.0/0.5/1.0 at the bounds + midpoint."""
    marks = event_marker_fractions([100, 150, 200], ["a", "b", "c"], 100, 200)
    assert marks == [(0.0, "a"), (0.5, "b"), (1.0, "c")]


def test_event_marker_fractions_guards_zero_span_and_coerces_label():
    """R8: a zero-span bag clamps span to 1 (no ZeroDivisionError) and str()-coerces the label."""
    assert event_marker_fractions([100], [None], 100, 100) == [(0.0, "None")]
