"""Output subpackage — backend-neutral presentation over a ``pyarrow.Table``.

Phase 6 turns the fully-materialized ``pyarrow.Table`` that
``rosbagger_core.backend.query.query`` returns into user-facing OUTPUT forms:

* :func:`~rosbagger_core.output.render.rows_for_display` — temporal-safe row
  coercion for the rich stdout table (OUT-01); ``timestamp[ns]`` ``t``/``stamp``
  columns are converted via ``to_numpy`` so naive ``to_pylist()``/``str()`` does
  not raise ``ValueError`` (06-RESEARCH Pitfall 1).
* :func:`~rosbagger_core.output.render.to_json` — temporal-safe JSON records
  (``t``/``stamp`` cast to int64 raw-ns per decision A5; machine-parseable).
* :func:`~rosbagger_core.output.export.write_table` — CSV/Parquet export by file
  extension, BOTH via DuckDB ``COPY`` (the only writer that serializes LIST/STRUCT
  columns to CSV; 06-RESEARCH Pitfall 2 / Pattern 1).
* :func:`~rosbagger_core.output.export.write_csv_stream` — CSV to ``/dev/stdout``
  (no extension detection) for ``bagq query --format csv`` with no ``-o`` (A2).

OFFLINE INVARIANT (06-RESEARCH Pitfall 6): this package's top level — and the
``.render``/``.export`` module top levels it re-exports from — import ONLY the
standard library. The heavy stack (``pyarrow``/``duckdb``) is imported INSIDE the
function bodies (mirror ``backend/query.py``). Re-exporting ``rows_for_display`` /
``to_json`` / ``write_table`` is therefore safe: the names are bound but no heavy
import fires until a function is actually called. This package is NOT imported
from ``rosbagger_core/__init__``, so ``import rosbagger_core`` stays light; even
``import rosbagger_core.output`` must leave duckdb/sqlglot/pyarrow out of
``sys.modules`` (regression test in ``tests/test_offline_guard.py``).
"""

from __future__ import annotations

from .export import write_csv_stream, write_table
from .render import rows_for_display, to_json

__all__ = ["rows_for_display", "to_json", "write_csv_stream", "write_table"]
