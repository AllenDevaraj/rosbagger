"""CSV / Parquet export of a result ``pyarrow.Table`` via DuckDB ``COPY``.

``write_table(table, path)`` picks the format from the file extension (``.csv`` →
``FORMAT CSV, HEADER``; ``.parquet`` → ``FORMAT PARQUET``) and writes via a short-lived
DuckDB connection: ``con.register("result", table)`` then a single
``COPY result TO '<path>' (...)``. Both formats go through DuckDB ``COPY`` for one
uniform writer because ``COPY`` is the ONLY path that serializes LIST/STRUCT columns to
CSV — ``pyarrow.csv.write_csv`` raises ``ArrowInvalid`` on any LIST column (and every
``Imu.orientation_covariance`` / ``LaserScan.ranges`` is one; 06-RESEARCH Pitfall 2 /
Pattern 1). DuckDB renders such a column as ``"[1.0, 2.0, 3.0]"`` and round-trips it
losslessly in Parquet.

SECURITY (06-RESEARCH Security Domain — threat T-06-01): the output path is the ONE
place this phase builds SQL (it is interpolated into the ``COPY ... TO '<path>'``
literal). A path containing a single quote could break/inject the statement, so the
literal is escaped (``'`` → ``''``) before interpolation. The format is chosen from a
closed ``{csv, parquet}`` map — never from user text. This is a local single-user CLI
(the user supplies their own output path), so the disposition for path traversal itself
is *accept* (T-06-02); the quote-escape is the clean SQL-literal defense.

OFFLINE INVARIANT: stdlib-only at module scope; ``import duckdb`` is inside the function
body (and a ``TYPE_CHECKING`` import is for annotations only), mirroring
``backend/query.py`` / ``backend/duckdb_backend.py``. This module loads no heavy stack
on import.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow

# The closed format map: file extension (lowercased, no dot) → DuckDB COPY options.
# Chosen from this map only — never built from user text (threat T-06-01).
_FORMAT_OPTS = {
    "csv": "FORMAT CSV, HEADER",
    "parquet": "FORMAT PARQUET",
}


def _copy_to(table: pyarrow.Table, path_str: str, opts: str) -> None:
    """Run a single DuckDB ``COPY result TO '<path>' (<opts>)`` for ``table``.

    The shared export core: open a short-lived ``duckdb.connect()``, register ``table``
    as ``result``, ``COPY`` it out, and always close the connection. SECURITY (threat
    T-06-01): the path literal is single-quote-escaped (``'`` → ``''``) before
    interpolation — the ONE place this phase builds SQL. ``opts`` is supplied by the
    caller from the closed ``_FORMAT_OPTS`` map, never from user text.
    """
    import duckdb  # lazy — heavy, offline invariant (mirror backend/query.py)

    safe = path_str.replace("'", "''")
    con = duckdb.connect()
    try:
        con.register("result", table)
        con.execute(f"COPY result TO '{safe}' ({opts})")
    finally:
        con.close()


def write_table(table: pyarrow.Table, path: str | os.PathLike[str]) -> None:
    """Write ``table`` to CSV or Parquet, format chosen by ``path``'s extension.

    ``.csv`` writes a header + comma-separated rows (LIST columns render as bracketed
    strings); ``.parquet`` writes a Parquet file whose schema + rows round-trip via
    ``pyarrow.parquet.read_table``. A 0-row table writes a header-only CSV / a 0-row
    Parquet with the schema preserved (06-RESEARCH Pitfall 3). Export goes through a
    short-lived DuckDB ``COPY`` (NOT ``pyarrow.csv.write_csv`` — Pitfall 2). The path
    literal is single-quote-escaped before interpolation (threat T-06-01).

    Args:
        table: the result ``pyarrow.Table`` from ``query()``.
        path: the output path; the extension selects the format.

    Raises:
        ValueError: the extension is neither ``.csv`` nor ``.parquet``.
    """
    path_str = str(path)
    ext = path_str.lower().rsplit(".", 1)[-1] if "." in path_str else ""
    opts = _FORMAT_OPTS.get(ext)
    if opts is None:
        raise ValueError(f"Unknown output extension {ext!r}; use .csv or .parquet")
    _copy_to(table, path_str, opts)


def write_csv_stream(table: pyarrow.Table, path: str | os.PathLike[str] = "/dev/stdout") -> None:
    """Write ``table`` as CSV to ``path`` (default ``/dev/stdout``) via DuckDB ``COPY``.

    The streaming companion to :func:`write_table`: forces ``FORMAT CSV, HEADER`` with NO
    extension detection, so an extensionless target like ``/dev/stdout`` works (it is a
    valid DuckDB ``COPY`` target). This backs ``bagq query --format csv`` with no ``-o``
    (decision A2 — stream CSV to stdout), keeping the ``COPY`` construction + path
    quote-escape (T-06-01) in this core module rather than in the CLI (so ``bagq/cli.py``
    never imports duckdb; offline invariant).

    Args:
        table: the result ``pyarrow.Table`` from ``query()``.
        path: the CSV destination; defaults to ``/dev/stdout``.
    """
    _copy_to(table, str(path), _FORMAT_OPTS["csv"])
