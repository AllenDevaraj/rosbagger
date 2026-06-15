"""The event-sidecar I/O layer (EVNT-01 write/read half — SC2).

An *event* annotates a span of bag time: ``(t_start_ns, t_end_ns, label, note)``. v1
events live in a tiny Parquet *sidecar* next to the bag, ``<bag>.events.parquet`` (D-11),
so they travel with the bag and need no schema migration. This module owns the three
sidecar primitives:

* :func:`sidecar_path` — derive ``<bag>.events.parquet`` from a bag path, file-vs-dir-aware.
* :func:`add_event` — write/append one event row (read existing -> concat -> rewrite; D-13).
* :func:`list_events` — read the sidecar back as a ``pyarrow.Table`` (SC2), or an empty
  fixed-schema table when no sidecar exists.

It also hosts one PURE presentation helper, :func:`event_marker_fractions` (R8), shared by the
replay panels to map event start timestamps onto 0..1 scrubber positions — kept here, next to
``list_events`` that both panels already import, so the mapping (and its zero-span guard) lives
in one offline-testable place instead of hand-mirrored across the Qt and TUI panels.

The ``events``-table query hook (the reserved-name registration + interval join, SC3) is
Plan 11-04 and builds on :func:`sidecar_path` from here.

PATH DERIVATION (D-11 / 11-RESEARCH Pitfall 7): a ROS 1 ``.bag`` and an ``.mcap`` are
single FILES whose real extension is stripped (``Path.with_suffix``); a ROS 2 bag is a
DIRECTORY whose name has no such extension, so ``.events.parquet`` is APPENDED to the full
name. ``with_suffix`` must NEVER touch a directory bag — a dotted directory name like
``v1.2/`` would lose its last segment (``-> v1.events.parquet``). The file-vs-dir branch
keeps the derivation deterministic across all three bag shapes.

EVENT SCHEMA (D-12): the fixed v1 schema is ``t_start_ns BIGINT``, ``t_end_ns BIGINT``,
``label VARCHAR``, ``note VARCHAR`` (nullable). A point/instant event has
``t_start_ns == t_end_ns``. The ``_ns`` columns line up with the topic tables' ``t_ns`` so
the Plan 11-04 interval join (``... ON data.t_ns BETWEEN e.t_start_ns AND e.t_end_ns``) is
a standard SQL join with no special operator.

WRITE PATH (D-13): the sidecar is written by REUSING the locked DuckDB-``COPY`` Parquet
writer :func:`rosbagger_core.output.export.write_table`, whose single-quote-escape of the
path literal (``'`` -> ``''``) is the one SQL-literal boundary (threat T-06-01). This
module builds NO second ``COPY``. Events files are tiny, so an append is a whole-file
read -> ``pa.concat_tables`` -> rewrite (no in-place Parquet append needed).

OFFLINE INVARIANT (11-RESEARCH Pitfall 5): the module top is stdlib-only (``pathlib``);
``pyarrow`` / ``pyarrow.parquet`` and the ``output.export`` writer are imported INSIDE the
function bodies (mirroring ``output/export.py`` / ``backend/query.py``). So
``import rosbagger_core.events`` pulls in none of ``{duckdb, sqlglot, pyarrow}`` — Plan
11-04 adds the formal offline-guard assertion for this module; this plan keeps it
importable-light. ``sidecar_path`` is stdlib-only and may stay at module top.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow

# FILE-bag suffixes: a ROS 1 ``.bag`` and an MCAP ``.mcap`` are single files whose real
# extension is stripped. Anything else (a ROS 2 bag directory) appends to the full name.
_FILE_BAG_SUFFIXES = {".bag", ".mcap"}

# The sidecar suffix appended to a directory bag's full name (D-11).
_SIDECAR_SUFFIX = ".events.parquet"


def _event_schema() -> pyarrow.Schema:
    """Build the fixed v1 event schema (D-12) — ``pyarrow`` imported lazily here.

    Built inside a function (NOT a module-level constant) so ``pyarrow`` is not imported
    at module top — the offline invariant (11-RESEARCH Pitfall 5).
    """
    import pyarrow as pa

    return pa.schema(
        [
            ("t_start_ns", pa.int64()),
            ("t_end_ns", pa.int64()),
            ("label", pa.string()),
            ("note", pa.string()),  # nullable
        ]
    )


def sidecar_path(bag: str | Path) -> Path:
    """Derive the ``<bag>.events.parquet`` sidecar path from ``bag``, file-vs-dir-aware.

    A ROS 1 ``.bag`` file and an ``.mcap`` file strip their real extension
    (``Path.with_suffix``); a ROS 2 directory bag (any other suffix) APPENDS
    ``.events.parquet`` to its full name. ``with_suffix`` is NEVER used on a directory bag
    — a dotted directory name (``v1.2``) would otherwise lose its last segment
    (``-> v1.events.parquet``; D-11 / 11-RESEARCH Pitfall 7). stdlib-only (``pathlib``).

    Args:
        bag: the bag path (a ``.bag``/``.mcap`` file, or a ROS 2 bag directory).

    Returns:
        The deterministic sibling sidecar path ``<bag>.events.parquet``.
    """
    bag = Path(bag)
    if bag.suffix.lower() in _FILE_BAG_SUFFIXES:  # FILE bags: strip the real extension
        return bag.with_suffix(_SIDECAR_SUFFIX)
    return bag.parent / (bag.name + _SIDECAR_SUFFIX)  # DIR bag: append, never strip


def add_event(
    bag: str | Path,
    *,
    t_start_ns: int,
    t_end_ns: int,
    label: str,
    note: str | None = None,
) -> Path:
    """Append one event row to the bag's sidecar, creating it if absent (D-12 / D-13).

    Builds a 1-row table in the fixed v1 schema (D-12). If the sidecar already exists, its
    rows are read and the new row concatenated onto the end (insertion order preserved);
    otherwise the new row is the whole table. The result is written by REUSING the locked
    DuckDB-``COPY`` Parquet writer (:func:`rosbagger_core.output.export.write_table`, D-13)
    — this module builds no second ``COPY``, so the T-06-01 path quote-escape stays the
    single SQL-literal boundary. Events files are tiny, so the whole file is rewritten
    (no in-place Parquet append). A point/instant event has ``t_start_ns == t_end_ns``.

    Heavy imports (``pyarrow``, ``pyarrow.parquet``, the export writer) are lazy here —
    the offline invariant (11-RESEARCH Pitfall 5).

    Args:
        bag: the bag path; the sidecar is derived via :func:`sidecar_path`.
        t_start_ns: event start time in nanoseconds (BIGINT).
        t_end_ns: event end time in nanoseconds (BIGINT); equal to ``t_start_ns`` for a
            point/instant event.
        label: the event label (VARCHAR).
        note: an optional free-text note (VARCHAR, nullable).

    Returns:
        The sidecar path that was written.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from rosbagger_core.output.export import write_table

    schema = _event_schema()
    row = pa.table(
        {
            "t_start_ns": [t_start_ns],
            "t_end_ns": [t_end_ns],
            "label": [label],
            "note": [note],
        },
        schema=schema,
    )

    path = sidecar_path(bag)
    if path.exists():
        existing = pq.read_table(path)
        combined = pa.concat_tables([existing, row])
    else:
        combined = row

    write_table(combined, str(path))  # reuse the locked Parquet writer (D-13) — no 2nd copy
    return path


def list_events(bag: str | Path) -> pyarrow.Table:
    """Read the bag's event sidecar back as a ``pyarrow.Table`` (SC2).

    Returns the sidecar's rows when ``<bag>.events.parquet`` exists; otherwise an EMPTY
    table carrying the fixed v1 schema (the four D-12 columns) so callers never crash on a
    missing sidecar. ``pyarrow`` is imported lazily here (the offline invariant).

    Args:
        bag: the bag path; the sidecar is derived via :func:`sidecar_path`.

    Returns:
        The event rows as a ``pyarrow.Table``, or a 0-row table with the fixed v1 schema
        when no sidecar exists.
    """
    import pyarrow.parquet as pq

    path = sidecar_path(bag)
    if path.exists():
        return pq.read_table(path)
    return _event_schema().empty_table()


def event_marker_fractions(
    starts_ns: list[int],
    labels: list[object],
    bag_start_ns: int,
    bag_end_ns: int,
) -> list[tuple[float, str]]:
    """Map event start timestamps to ``(fraction, label)`` scrubber marks (R8 — pure, offline).

    Both replay panels (the Qt desktop and the Textual TUI) overlay jump-to-event markers on
    their timeline scrubber, mapping each event's ``t_start_ns`` to a 0..1 position via
    ``(t_start_ns - bag_start_ns) / span``. This is the one shared home for that arithmetic and
    for the three correctness details that used to be hand-mirrored across both packages: the
    ``max(1, ...)`` zero-span div-by-zero guard, the ``str(label)`` coercion, and ``strict=False``
    (the two columns differ in length only on a malformed sidecar). ``bag_start_ns`` /
    ``bag_end_ns`` are the reader's O(1) bounds (F1); the caller owns the empty-bag short-circuit.
    """
    span = max(1, bag_end_ns - bag_start_ns)
    return [
        ((start - bag_start_ns) / span, str(label))
        for start, label in zip(starts_ns, labels, strict=False)
    ]
