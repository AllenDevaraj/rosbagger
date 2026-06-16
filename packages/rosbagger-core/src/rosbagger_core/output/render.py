"""Temporal-safe row coercion for rich rendering + JSON records.

``rows_for_display`` and ``to_json`` materialize a ``pyarrow.Table`` into display
strings / JSON-safe records WITHOUT crashing on the ``timestamp[ns]`` ``t``/``stamp``
columns every query result carries (QURY-04). Naive ``to_pylist()`` / ``str()`` on a
``timestamp[ns]`` scalar raises ``ValueError`` (nanosecond resolution exceeds
``datetime``'s microsecond floor, and pandas is not installed) — so temporal columns
take a different code path (06-RESEARCH Pitfall 1 / Pattern 2):

* :func:`rows_for_display` converts temporal columns via
  ``combine_chunks().to_numpy(zero_copy_only=False)`` → ``datetime64[ns]`` then
  ``str()`` (NaT → ``""``); every other column via ``to_pylist()`` (None → ``""``).
* :func:`to_json` casts temporal columns to int64 raw-ns BEFORE ``to_pylist()`` so the
  JSON stays machine-parseable (decision A5 — raw ns, not ISO strings).

OFFLINE INVARIANT: stdlib-only at module scope; ``import pyarrow`` is inside the
function bodies (and a ``TYPE_CHECKING`` import is for annotations only), mirroring
``backend/query.py``. This module loads no heavy stack on import.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow


def _json_safe(value):
    """Replace non-finite floats (NaN / +/-inf — invalid JSON) with ``None``, recursively.

    ``json.dumps`` defaults to ``allow_nan=True``, emitting bare ``NaN`` / ``Infinity``
    / ``-Infinity`` tokens that strict parsers (JavaScript ``JSON.parse``, Go) reject —
    breaking the "machine-parseable output" contract. Non-finite floats are common in
    real ROS data (LaserScan ``ranges`` carry ``inf``; Imu/Odometry covariance carries
    ``NaN``), and they reach ``to_json`` via scalar, ``LIST``, and ``LIST``-of-``STRUCT``
    columns — so walk dicts and lists too. ``allow_nan=False`` would RAISE rather than
    degrade, so it is deliberately NOT used; sanitizing to ``null`` keeps the row.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def rows_for_display(
    table: pyarrow.Table,
    *,
    max_rows: int | None = None,
) -> tuple[list[str], list[list[str]]]:
    """Coerce ``table`` into ``(column_names, rows)`` of display strings, temporal-safe.

    Slices to at most ``max_rows`` rows (all rows when ``None``). Each column is
    stringified: a temporal column (``timestamp[ns]`` ``t``/``stamp``) is converted via
    ``combine_chunks().to_numpy(zero_copy_only=False)`` → ``datetime64[ns]`` then
    ``str()`` — the only path that does NOT raise ``ValueError`` on nanosecond
    timestamps (06-RESEARCH Pitfall 1); NaT renders as ``""``. Every non-temporal
    column goes through ``to_pylist()`` with ``None`` → ``""``.

    A 0-row table returns the full column-name list and an empty rows list (no index
    error — 06-RESEARCH Pitfall 3). ``rows`` is the row-major transpose of the columns.

    Args:
        table: the result ``pyarrow.Table`` from ``query()``.
        max_rows: cap the number of rows returned (``None`` = all rows).

    Returns:
        ``(column_names, rows)`` where ``rows`` is a list of per-row string lists.
    """
    import pyarrow as pa

    n = table.num_rows if max_rows is None else min(table.num_rows, max_rows)
    view = table.slice(0, n)
    names = view.column_names
    cols: dict[str, list[str]] = {}
    for name in names:
        col = view.column(name)
        if pa.types.is_temporal(col.type):
            # to_pylist()/str() on timestamp[ns] RAISES ValueError; datetime64 is safe.
            # x != x is True only for NaN/NaT, so it catches the null sentinel.
            arr = col.combine_chunks().to_numpy(zero_copy_only=False)
            cols[name] = ["" if x != x else str(x) for x in arr]
        else:
            cols[name] = ["" if v is None else str(v) for v in col.to_pylist()]
    rows = [list(row) for row in zip(*[cols[name] for name in names], strict=True)]
    return names, rows


def to_json(table: pyarrow.Table) -> str:
    """Serialize ``table`` to a JSON string of records, temporal-safe.

    Each record is a ``{column: value}`` dict; columns are emitted in schema order.
    Temporal columns (``t``/``stamp``) are cast to ``int64`` (raw nanoseconds) BEFORE
    ``to_pylist()`` so the JSON is machine-parseable and lossless (decision A5 — raw ns,
    NOT ISO-8601 strings) and never hits the ``timestamp[ns]`` → ``datetime`` crash.
    A 0-row table yields ``"[]"``.

    Args:
        table: the result ``pyarrow.Table`` from ``query()``.

    Returns:
        A JSON string: a list of record dicts.
    """
    import json

    import pyarrow as pa

    names = table.column_names
    cols: dict[str, list] = {}
    for name in names:
        col = table.column(name)
        if pa.types.is_temporal(col.type):
            col = col.cast(pa.int64())  # raw nanoseconds (A5)
        cols[name] = col.to_pylist()
    records = [
        dict(zip(names, vals, strict=True))
        for vals in zip(*[cols[name] for name in names], strict=True)
    ]
    # Sanitize non-finite floats (NaN/inf) to null so the output is valid, strictly
    # parseable JSON (json.dumps would otherwise emit bare NaN/Infinity tokens).
    return json.dumps(_json_safe(records))
