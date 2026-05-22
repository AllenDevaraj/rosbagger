"""Minimal headless line plot of a result ``pyarrow.Table`` (OUT-04).

``plot_table(table, path)`` draws an intentionally-minimal matplotlib line chart — the
NUMERIC result columns (int/float Arrow types) on the y-axis against ``t_ns`` (BIGINT,
fallback ``t``) on the x-axis — and writes it as a PNG to ``path``. This is NOT a
PlotJuggler rebuild; it is the fourth output form, gated behind an optional dependency.

Design decisions transcribed from 06-RESEARCH (all VERIFIED headless this session):

* **Headless Agg backend (Pitfall 6-of-plot):** ``matplotlib.use("Agg")`` is called
  BEFORE ``import matplotlib.pyplot`` so a box with ``DISPLAY`` unset (CI, servers) does
  not select an interactive backend and crash.
* **x = ``t_ns`` (BIGINT), not ``t``:** ``t_ns`` is integer, so it sidesteps the
  ``timestamp[ns]`` → ``datetime`` conversion crash class entirely (06-RESEARCH Pitfall 1);
  ``t`` is the fallback only when ``t_ns`` is absent.
* **Numeric y-columns via ``pyarrow.types``:** ``is_integer``/``is_floating`` predicates
  select the y-series and naturally EXCLUDE ``topic``/string/LIST/STRUCT columns; ``t_ns``
  is excluded too (it is the x-axis).
* **Clear errors, never a blank chart:** 0 rows (Pitfall 3), no numeric y-column or no
  ``t``/``t_ns`` x-column (Pitfall 4) raise ``ValueError`` with a teaching message.
* **Figure closed after savefig (Pitfall 7 — figure-leak DoS, threat T-06-05):**
  ``plt.close(fig)`` always runs so repeated ``--plot`` calls / test loops do not leak.

OFFLINE INVARIANT (06-RESEARCH Pitfall 6): stdlib-only at module scope — matplotlib AND
pyarrow are imported INSIDE :func:`plot_table` (the ``TYPE_CHECKING`` import is for
annotations only), mirroring ``backend/query.py`` and the sibling ``render.py`` /
``export.py``. ``import rosbagger_core.output`` therefore pulls in NO matplotlib / pyarrow
/ duckdb (regression test in ``tests/test_offline_guard.py``). matplotlib is the optional
``bagq[plot]`` extra, so a missing matplotlib raises a teaching ``RuntimeError`` ("install
``bagq[plot]``"; Pitfall 5), never a bare ``ModuleNotFoundError``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow


def plot_table(table: pyarrow.Table, path: str | os.PathLike[str]) -> None:
    """Plot the numeric columns of ``table`` against ``t_ns`` and write a PNG to ``path``.

    Builds a minimal matplotlib line chart: one line per NUMERIC result column (int/float
    Arrow type) on the y-axis, against the ``t_ns`` (fallback ``t``) column on the x-axis,
    saved as a PNG. The matplotlib backend is forced to headless ``Agg`` BEFORE pyplot is
    imported, so the write succeeds with ``DISPLAY`` unset (06-RESEARCH Pattern 3). The
    figure is always closed after ``savefig`` (Pitfall 7 / threat T-06-05).

    Numeric y-columns are detected with ``pyarrow.types.is_integer``/``is_floating``, which
    excludes ``topic``/string/LIST/STRUCT columns; ``t_ns`` itself is excluded (it is the
    x-axis).

    Args:
        table: the result ``pyarrow.Table`` from ``query()``.
        path: the PNG destination (the user-supplied path or the ``plot.png`` default).

    Raises:
        RuntimeError: matplotlib is not installed (the optional ``bagq[plot]`` extra) —
            the message tells the user to ``pip install 'bagq[plot]'`` (Pitfall 5), not a
            bare ``ModuleNotFoundError``.
        ValueError: the result has 0 rows (Pitfall 3), or has no ``t``/``t_ns`` x-column
            or no numeric y-column (Pitfall 4) — a clear nothing-to-plot message instead
            of a blank chart.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")  # MUST precede the pyplot import; headless / CI-safe
        import matplotlib.pyplot as plt
    except ImportError as exc:  # the optional bagq[plot] extra is not installed
        raise RuntimeError(
            "Plotting needs matplotlib. Install with: pip install 'bagq[plot]'"
        ) from exc

    import pyarrow.types as pat

    # 0-row result: clear signal, never a blank chart (Pitfall 3). A 0-row Table still
    # carries the full schema, so check num_rows (NOT indexing) first.
    if table.num_rows == 0:
        raise ValueError("0 rows — nothing to plot.")

    names = table.column_names
    x_name = "t_ns" if "t_ns" in names else ("t" if "t" in names else None)
    # Numeric = int/float Arrow types; exclude t_ns (the x-axis). is_integer/is_floating
    # naturally exclude topic/string/LIST/STRUCT (Pitfall 4 — robust over string matching).
    y_cols = [
        name
        for name in names
        if name != "t_ns"
        and (pat.is_integer(table.column(name).type) or pat.is_floating(table.column(name).type))
    ]
    if x_name is None or not y_cols:
        raise ValueError("Nothing to plot: need a t/t_ns column and >=1 numeric result column.")

    x = table.column(x_name).to_numpy(zero_copy_only=False)
    fig, ax = plt.subplots()
    try:
        for y_name in y_cols:
            ax.plot(x, table.column(y_name).to_numpy(zero_copy_only=False), label=y_name)
        ax.set_xlabel(x_name)
        ax.legend()
        fig.savefig(str(path))
    finally:
        plt.close(fig)  # always close — repeated plots must not leak figures (Pitfall 7)
