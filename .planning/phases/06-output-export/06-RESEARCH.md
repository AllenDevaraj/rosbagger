# Phase 6: Output & Export - Research

**Researched:** 2026-05-22
**Domain:** Rendering and exporting a materialized `pyarrow.Table` query result — stdout table (rich), CSV/Parquet writers, and a minimal headless matplotlib line plot
**Confidence:** HIGH

## Summary

Phase 6 turns the `pyarrow.Table` that Phase 5's `query(sql, reader)` returns into the four
user-facing OUTPUT forms (OUT-01..04): a pretty stdout table by default, `-o out.csv` /
`-o out.parquet` file exports, and a `--plot` line chart of numeric columns vs `t`. The input
is fully materialized Arrow (the backend has already closed by the time `query()` returns), so
the writers/renderers are a **pure presentation layer over a `pyarrow.Table`** — no reader, no
SQL, no backend re-entry required for the table/CSV/Parquet paths.

Three findings, all verified end-to-end this session with the installed stack
(`pyarrow 24.0.0`, `duckdb 1.5.3`, `numpy 2.2.6`, `rich 15.0.0`, `typer 0.25.1`), materially
shape the plan:

1. **CSV: pyarrow `write_csv` cannot serialize LIST/STRUCT columns — DuckDB `COPY ... TO` can.**
   `pyarrow.csv.write_csv` raises `ArrowInvalid: Unsupported Type:list<item: float>` the moment
   a result carries a `LIST` column (and every `LaserScan.ranges`, `Imu.orientation_covariance`,
   etc. is one). DuckDB `COPY res TO 'f.csv' (FORMAT CSV, HEADER)` renders the same column as
   `"[1.0, 2.0, 3.0]"` and a STRUCT-in-LIST as `"[{'x': 1.0, 'y': 2.0}]"` — graceful, lossy-but-
   readable. **Recommendation: CSV export must go through DuckDB `COPY`, not pyarrow's CSV
   writer.** Parquet is a tie (both round-trip LIST/STRUCT perfectly), so route Parquet through
   DuckDB `COPY` too for one uniform export path. [VERIFIED: this session]

2. **`timestamp[ns]` columns crash naive `to_pylist()`/`str()` rendering.** `t` and `stamp` are
   `TIMESTAMP_NS` (QURY-04). Calling `.to_pylist()`, `.as_py()`, or even `str()` on a
   `timestamp[ns]` scalar raises `ValueError: Nanosecond resolution temporal type ... is not
   safely convertible to microseconds to convert to datetime.datetime` (pandas not installed,
   and nanoseconds exceed `datetime`'s microsecond floor). The stdout-table renderer **must**
   special-case temporal columns: convert via `column.to_numpy(zero_copy_only=False)` →
   `datetime64[ns]` (full precision, nulls become `NaT`), then `str()` each element. Every
   non-temporal column is fine via `to_pylist()`. [VERIFIED: this session]

3. **`--plot` must plot against `t_ns` (BIGINT), set the Agg backend before importing pyplot,
   and is testable only if matplotlib is added to the dev group.** matplotlib is NOT in the base
   install (it is the `bagq[plot]` extra) and NOT currently in `.venv`. I installed it
   (`matplotlib 3.10.9`) and verified a headless line plot with `DISPLAY` unset succeeds
   (`matplotlib.use("Agg")` → `fig.savefig(...)` → 26 KB PNG), then uninstalled it to restore
   the lean env. Both `t_ns` (int64) and `t` (datetime64 via `to_numpy`) work as the x-axis, but
   `t_ns` avoids the `timestamp[ns]→datetime` crash class entirely and is the safer default.
   [VERIFIED: this session]

**Primary recommendation:** Add an `output` module to **`rosbagger_core`** (backend-neutral,
takes a `pyarrow.Table`) with three thin helpers: `write_table(table, path)` (extension →
DuckDB `COPY` CSV/Parquet), `render_table(table, console)` (rich, temporal-safe), and
`plot_table(table, path)` (lazy matplotlib import, Agg, numeric-cols-vs-`t_ns`). Wire a thin
`bagq query "<SQL>" BAG... [-o OUT] [--plot [FILE]] [--format ...]` typer command that opens a
`RosbagsReader`, calls `query()`, and routes to one of the three. Add `matplotlib>=3.8` to the
root `[dependency-groups] dev` so CI can exercise `--plot`; keep the base `bagq` install lean
via the existing `plot` extra. Handle `ImportError` for matplotlib with a "install `bagq[plot]`"
message.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Stdout table rendering (OUT-01) | `bagq` CLI (rich) | `rosbagger_core.output` (row coercion) | Matches the established `_render_bag_info`/`_render_table_schemas` pattern — rich rendering is a CLI concern; the temporal-safe row coercion is reusable and belongs in core |
| CSV / Parquet export (OUT-02/03) | `rosbagger_core.output` | `backend` (DuckDB `COPY`) | Backend-neutral writer taking a `pyarrow.Table`; uses a short-lived DuckDB connection because `COPY` is the only path that serializes LIST/STRUCT to CSV |
| `--plot` line chart (OUT-04) | `rosbagger_core.output` | `bagq` CLI (flag + file default) | matplotlib import is heavy + optional → lives behind a lazy core function; the CLI owns the `--plot [FILE]` flag ergonomics and the default-filename choice |
| `bagq query` command wiring | `bagq` CLI | `rosbagger_core.backend.query` | Thin CLI: open reader → `query()` → route to writer/renderer (API-first decision 1) |
| Numeric-column selection for plot | `rosbagger_core.output` | — | `pyarrow.types.is_integer`/`is_floating` predicate over the result schema |
| Output-format routing (`--format`) | `bagq` CLI | — | Pure CLI dispatch (table/csv/parquet/json → the right helper) |

**Why this matters:** The offline invariant (`import rosbagger_core` must stay light —
`tests/test_offline_guard.py`) means **matplotlib, pyarrow, and duckdb may be imported only
inside the functions that use them**, never at any module top level. The `output` module
top-level must import only stdlib (mirror `backend/query.py`); `rosbagger_core/__init__` must
not import `output`. The CLI (`bagq/cli.py`) keeps its top level to typer/rich only and imports
the core output API lazily inside the `query` command body — exactly as `info`/`tables` already
do.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `duckdb` | 1.5.3 (installed; constraint `>=1.4,<2`) | CSV + Parquet export via `COPY res TO 'f' (FORMAT ...)` — the only writer that serializes LIST/STRUCT to CSV | Already a locked core dep (Phase 5); design spec line 108 explicitly says "Parquet (native via DuckDB `COPY ... TO`)" |
| `pyarrow` | 24.0.0 (installed; constraint `>=18`) | The result `Table`; `to_numpy`/`to_pylist`/`types` for row coercion + numeric detection; `pyarrow.parquet.read_table` in tests | The backend-neutral contract `query()` returns |
| `rich` | 15.0.0 (installed via `bagq` deps) | Stdout table rendering (`rich.table.Table` / `rich.console.Console`) | Already the `bagq` table-output dep; `info`/`tables` use it |
| `typer` | 0.25.1 (installed via `bagq` deps) | The `bagq query` command + `-o`/`--plot`/`--format` options | The established CLI lib (decision: `typer`/`click`) |

### Supporting (plot path only)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `matplotlib` | 3.10.9 verified (constraint `>=3.8`) | The `--plot` line chart, headless via `Agg` | OUT-04 only; OPTIONAL `bagq[plot]` extra at runtime, ADD to root `dev` group for CI test exercise |
| `numpy` | 2.2.6 (installed transitively via pyarrow) | `Array.to_numpy(zero_copy_only=False)` for plot y-values and temporal-safe `datetime64[ns]` | Already present; no new dep — pyarrow pulls it |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DuckDB `COPY` for CSV | `pyarrow.csv.write_csv` | **REJECTED for CSV:** raises `ArrowInvalid` on any LIST column (verified). pyarrow CSV only works on a scalar-only subset — not viable for arbitrary query results |
| DuckDB `COPY` for Parquet | `pyarrow.parquet.write_table` | Both round-trip LIST/STRUCT perfectly (verified). pyarrow direct avoids the DuckDB round-trip and is backend-neutral; **but** using `COPY` for BOTH formats yields one uniform writer and matches the design spec ("native via DuckDB `COPY`"). Recommend `COPY` for both; pyarrow-direct Parquet is an acceptable fallback if avoiding DuckDB re-entry is preferred |
| `t_ns` (BIGINT) plot x-axis | `t` (TIMESTAMP_NS) | Both plottable (verified). `t_ns` is integer → no temporal-conversion crash class, simpler. Default to `t_ns`; fall back to `t` (via `to_numpy`→datetime64) only if `t_ns` absent from the result |
| rich table | `tabulate` / plain print | rich is already the dep and matches `info`/`tables`; no reason to add `tabulate` |

**Installation:** No new RUNTIME dependency for the table/CSV/Parquet paths (duckdb, pyarrow,
rich, typer all already installed/locked). For `--plot`:

```bash
# Already declared as the bagq[plot] extra (keep — base install stays lean):
#   packages/bagq/pyproject.toml -> [project.optional-dependencies] plot = ["matplotlib>=3.8"]
# ADD to the root dev group so CI/tests can exercise --plot:
#   pyproject.toml -> [dependency-groups] dev = [..., "matplotlib>=3.8"]
uv add --dev "matplotlib>=3.8"   # or hand-edit the dev group, then `uv sync`
```

**Version verification (this session):**
```
pyarrow     24.0.0   [VERIFIED: importlib.metadata]
duckdb      1.5.3    [VERIFIED: importlib.metadata]
rich        15.0.0   [VERIFIED: importlib.metadata]
typer       0.25.1   [VERIFIED: importlib.metadata]
numpy       2.2.6    [VERIFIED: importlib.metadata — transitive via pyarrow]
matplotlib  3.10.9   [VERIFIED: uv pip install matplotlib>=3.8 → import + Agg savefig succeeded headless; then uninstalled to restore lean env]
python      3.10.12  [VERIFIED]
```

## Package Legitimacy Audit

> The only package this phase ADDS to an install set is `matplotlib`, and it is already a
> declared, locked dependency (`bagq[plot]` extra, constraint `>=3.8`). The phase adds it to the
> root `dev` group as well — same package, no new name. slopcheck was not run because the package
> is pre-declared, mature, and was successfully imported + exercised (headless Agg plot) this
> session. duckdb/pyarrow/rich/typer are all pre-existing locked deps from Phases 1/5.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| matplotlib | PyPI | mature (3.x, since 2003) | very high | github.com/matplotlib/matplotlib | n/a (pre-declared extra) | Approved — already locked as `bagq[plot]`; add to `dev` group |
| duckdb | PyPI | mature | very high | github.com/duckdb/duckdb | n/a (installed/locked) | Approved — Phase 5 dep |
| pyarrow | PyPI | mature | very high | github.com/apache/arrow | n/a (installed/locked) | Approved — core dep |
| rich | PyPI | mature | very high | github.com/Textualize/rich | n/a (installed/locked) | Approved — bagq dep |
| typer | PyPI | mature | very high | github.com/fastapi/typer | n/a (installed/locked) | Approved — bagq dep |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
  bagq query "<SQL>" BAG... [-o OUT] [--plot [FILE]] [--format table|csv|parquet|json]
        │
        ▼  (bagq/cli.py — thin command; lazy-imports core)
  ┌─────────────────────────────────────────────────────────────────────┐
  │ with RosbagsReader(bags) as reader:        # reader lifecycle owned   │
  │     result = query(sql, reader)            # Phase 5 → pyarrow.Table  │
  │                                            # (backend already closed) │
  └─────────────────────────────────────────────────────────────────────┘
        │  result: pyarrow.Table (fully materialized)
        ▼
  ┌──────────────── route on -o / --plot / --format ────────────────┐
  │                                                                  │
  ├─ no -o, format=table (DEFAULT) ─► output.render_table(t, console)│  OUT-01
  │     temporal cols → to_numpy(datetime64); rest → to_pylist();    │
  │     rich.Table; row-cap with "... N more rows" footer            │
  │                                                                  │
  ├─ -o out.csv     OR format=csv     ─► output.write_table(t, path) │  OUT-02
  ├─ -o out.parquet OR format=parquet ─► output.write_table(t, path) │  OUT-03
  │     ext → FORMAT; DuckDB: register(t) → COPY ... TO (handles     │
  │     LIST/STRUCT in CSV; round-trips both in Parquet)             │
  │                                                                  │
  ├─ format=json ─► json.dumps(t.to_pylist())  (temporal-safe shape) │
  │                                                                  │
  └─ --plot [FILE] ─► output.plot_table(t, file)                     │  OUT-04
        lazy `import matplotlib; matplotlib.use("Agg")` → ImportError│
        → "install bagq[plot]"; x=t_ns (fallback t); y=numeric cols  │
        excluding t_ns/topic/LIST; savefig(file)                     │
```

File-to-implementation mapping is in the Component Responsibilities note below, not in the
diagram.

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/
└── output/                  # NEW — backend-neutral presentation over a pyarrow.Table
    ├── __init__.py          # stdlib-only top level (mirror backend/query.py); lazy heavy imports
    ├── export.py            # write_table(table, path): ext → DuckDB COPY (CSV/Parquet)
    ├── render.py            # rows_for_display(table) → list[list[str]] (temporal-safe coercion)
    └── plot.py              # plot_table(table, path): lazy matplotlib, Agg, numeric vs t_ns

packages/bagq/src/bagq/
└── cli.py                   # ADD `query` command + a thin _render_result(table, console) (rich)
```

**Note (where `bagq query` belongs — Phase 6 vs 7):** Build the `bagq query` command HERE in
Phase 6. OUT-01..04 are unobservable without it (you cannot demonstrate "results print as a
table" or "`-o out.csv` writes a file" without the command that produces the result). Phase 7
("CLI & Teaching Errors", CLI-02/03/04) then *enriches* the already-wired command's error
handling (did-you-mean on `UnknownTableError`, unknown-column hints, custom-msg registration
help) — it does not create the command. CLI-01 ("`bagq query` runs a query end-to-end") is
mapped to Phase 7 in REQUIREMENTS.md, but the command skeleton is a hard prerequisite for
demonstrating Phase 6's success criteria, so build the skeleton now and let Phase 7 layer
teaching errors on top. **Flag this split to the planner; it is a scope-boundary judgment call.**

### Pattern 1: Backend-neutral output module, lazy heavy imports
**What:** An `output` package whose top level imports only stdlib; pyarrow/duckdb/matplotlib are
imported *inside* the functions that use them.
**When to use:** Always — it is the load-bearing offline invariant (`test_offline_guard.py`
asserts `duckdb`/`sqlglot`/`pyarrow` stay out of `sys.modules` after `import rosbagger_core`).
**Example:**
```python
# Source: mirrors packages/rosbagger-core/src/rosbagger_core/backend/query.py (this repo)
# rosbagger_core/output/export.py
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import pyarrow

def write_table(table: "pyarrow.Table", path: str) -> None:
    """Write a result table to CSV or Parquet, chosen by file extension."""
    import duckdb  # lazy — heavy, offline invariant
    fmt = _format_for(path)            # ".csv" -> CSV, ".parquet" -> PARQUET
    con = duckdb.connect()
    try:
        con.register("result", table)
        con.execute(f"COPY result TO '{path}' (FORMAT {fmt}{', HEADER' if fmt=='CSV' else ''})")
    finally:
        con.close()
```

### Pattern 2: Temporal-safe row coercion for rich rendering
**What:** Convert a `pyarrow.Table` to display rows without crashing on `timestamp[ns]`.
**When to use:** OUT-01 stdout table and `--format json` (any path that materializes cells).
**Example:**
```python
# Source: verified this session (pyarrow 24.0.0)
# rosbagger_core/output/render.py
def rows_for_display(table, *, max_rows: int | None = None):
    import pyarrow as pa
    n = table.num_rows if max_rows is None else min(table.num_rows, max_rows)
    view = table.slice(0, n)
    cols = {}
    for name in view.column_names:
        col = view.column(name)
        if pa.types.is_temporal(col.type):
            # to_pylist()/str() on timestamp[ns] RAISES ValueError; datetime64 is safe.
            arr = col.combine_chunks().to_numpy(zero_copy_only=False)
            cols[name] = ["" if x != x else str(x) for x in arr]   # NaT -> "" (x!=x catches NaT)
        else:
            cols[name] = ["" if v is None else str(v) for v in col.to_pylist()]
    return view.column_names, [list(r) for r in zip(*[cols[c] for c in view.column_names])]
```

### Pattern 3: `--plot` headless, numeric-vs-`t_ns`
**What:** A minimal matplotlib line chart; Agg backend set BEFORE pyplot import; numeric columns
on y, `t_ns` (fallback `t`) on x.
**When to use:** OUT-04 only.
**Example:**
```python
# Source: verified headless (DISPLAY unset) this session (matplotlib 3.10.9)
# rosbagger_core/output/plot.py
def plot_table(table, path: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")             # MUST precede pyplot import; no display / CI-safe
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise RuntimeError("Plotting needs matplotlib. Install with: pip install 'bagq[plot]'") from e
    import pyarrow.types as pat

    x_name = "t_ns" if "t_ns" in table.column_names else ("t" if "t" in table.column_names else None)
    y_cols = [n for n in table.column_names
              if (pat.is_integer(table.column(n).type) or pat.is_floating(table.column(n).type))
              and n not in ("t_ns",)]
    if x_name is None or not y_cols:
        raise ValueError("Nothing to plot: need a t/t_ns column and ≥1 numeric result column.")
    x = table.column(x_name).to_numpy(zero_copy_only=False)
    fig, ax = plt.subplots()
    for yc in y_cols:
        ax.plot(x, table.column(yc).to_numpy(zero_copy_only=False), label=yc)
    ax.set_xlabel(x_name); ax.legend()
    fig.savefig(path); plt.close(fig)
```

### Pattern 4: `--plot [FILE]` optional-value flag (typer/click)
**What:** A flag that may be passed bare (`--plot` → default filename) OR with a value
(`--plot chart.png`).
**When to use:** The `bagq query --plot` option.
**Example:**
```python
# Source: verified this session (click via typer 0.25.1)
# A plain typer.Option with a value REQUIRES the value. For an OPTIONAL value, pass the
# click kwargs through typer.Option(...):
#   is_flag=False, flag_value=<sentinel>, default=None
#   omitted        -> None         ("no plot")
#   --plot         -> <sentinel>   ("plot to default filename")
#   --plot FILE    -> "FILE"
import typer
_PLOT_DEFAULT = "\x00bagq-default-plot"   # sentinel distinct from any real path
plot: str | None = typer.Option(
    None, "--plot", is_flag=False, flag_value=_PLOT_DEFAULT,
    help="Plot numeric columns vs t. Bare = write <default>.png; --plot FILE = that file.",
)
# default filename suggestion: "plot.png" in CWD (document it).
```

### Anti-Patterns to Avoid
- **Importing matplotlib/pyarrow/duckdb at any module top level in `output/` or `cli.py`** —
  breaks `test_offline_guard.py`. Import inside function bodies (mirror `backend/query.py` and
  the `info`/`tables` commands).
- **`pyarrow.csv.write_csv` for CSV export** — raises `ArrowInvalid` on LIST columns. Use DuckDB
  `COPY`.
- **`result.to_pylist()` / `str(scalar)` on a result that may contain `t`/`stamp`** — raises
  `ValueError` for `timestamp[ns]`. Coerce temporal columns via `to_numpy()` first.
- **Plotting against `t` by default** — works but re-introduces the ns→datetime conversion
  surface. Prefer `t_ns`.
- **Forgetting `matplotlib.use("Agg")` before `import matplotlib.pyplot`** — on a headless box
  pyplot may select an interactive backend and fail. Set Agg first.
- **Indexing `result[0]` to "check for rows"** — a 0-row result still has a full schema; index
  errors. Use `table.num_rows`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV/Parquet serialization of LIST/STRUCT | A custom row-stringifier + manual CSV quoting | DuckDB `COPY ... TO` | DuckDB renders nested types as `[...]`/`{...}` and handles quoting/escaping; reinventing CSV quoting is a classic bug farm |
| Parquet column types/encoding | Manual Arrow→Parquet field mapping | DuckDB `COPY (FORMAT PARQUET)` or `pyarrow.parquet.write_table` | Both preserve the full nested schema round-trip (verified) |
| Pretty stdout table layout | Manual column-width math + box-drawing | `rich.table.Table` | Already the dep; `info`/`tables` set the precedent |
| Numeric type detection | `str(arrow_type).startswith("int")` string matching | `pyarrow.types.is_integer` / `is_floating` | Robust predicates (verified across all int/uint/float/bool/temporal/nested) |
| Nanosecond timestamp → string | Manual `divmod` on epoch ns | `column.to_numpy(zero_copy_only=False)` (→ `datetime64[ns]`) | Avoids the `datetime` microsecond-floor crash; full-precision, null-safe (NaT) |

**Key insight:** The result is already Arrow and DuckDB is already a dependency. The entire
export path is "register the Arrow table, run one `COPY`." The only genuinely new code is the
temporal-safe rich coercion and the minimal plot — both small and fully specified above.

## Runtime State Inventory

> Not applicable — Phase 6 is a greenfield additive feature (new `output` module + new `bagq
> query` command + a dev-group dependency). No rename/refactor/migration. No stored data, live
> service config, OS-registered state, secrets, or stale build artifacts are touched. The one
> dependency-graph change (add `matplotlib` to the `dev` group) is a `uv sync` away and carries
> no migration. **None — verified by scope (additive new module/command only).**

## Common Pitfalls

### Pitfall 1: `timestamp[ns]` column crashes the stdout table / JSON
**What goes wrong:** `result.to_pylist()` or `str(cell)` raises `ValueError: Nanosecond
resolution temporal type ... not safely convertible to ... datetime.datetime`.
**Why it happens:** `t` and `stamp` are `timestamp[ns]` (QURY-04). Python `datetime` tops out at
microsecond resolution and pandas (which pyarrow would use for ns Timestamps) is not installed.
**How to avoid:** In the renderer, branch on `pyarrow.types.is_temporal(col.type)` and convert
those columns via `col.to_numpy(zero_copy_only=False)` (→ `datetime64[ns]`, then `str()`); use
`to_pylist()` only for non-temporal columns. (Pattern 2.)
**Warning signs:** A test with the `/imu` fixture (has `header.stamp`) or any `SELECT t, ...`
that throws `ValueError` on render. [VERIFIED: this session]

### Pitfall 2: CSV export blows up on LIST columns
**What goes wrong:** `pyarrow.csv.write_csv(result, path)` raises `ArrowInvalid: Unsupported
Type:list<...>` whenever the result has an array column (e.g. `SELECT ranges FROM scan`,
`SELECT orientation_covariance FROM imu`).
**Why it happens:** Arrow's CSV writer only supports primitive/temporal/string columns.
**How to avoid:** Export CSV via DuckDB `COPY result TO 'f.csv' (FORMAT CSV, HEADER)`, which
renders LIST as `"[1.0, 2.0, 3.0]"` and STRUCT as `"[{'x': 1.0}]"`. (Pattern 1.)
**Warning signs:** Any CSV test using the `/imu` fixture (covariance arrays) fails with
`ArrowInvalid`. [VERIFIED: this session]

### Pitfall 3: Empty result set (0 rows)
**What goes wrong:** Code that does `result[0]`, `result.to_pylist()[0]`, or assumes ≥1 row to
infer columns crashes on a `WHERE` that matches nothing.
**Why it happens:** A 0-row result still carries the full column schema (Phase 5 RESEARCH Pitfall
4) — but there are no rows to iterate.
**How to avoid:** All three sinks already handle 0 rows gracefully when written correctly: rich
prints a header-only table (iterate `table.num_rows`), DuckDB `COPY` writes a header-only CSV
(`'t,t_ns,topic\n'`) and a 0-row Parquet with the schema preserved, and `--plot` should print a
clear "0 rows — nothing to plot" message rather than emitting a blank chart. **Verify all four
outputs against a deliberately-empty result.** [VERIFIED: header-only CSV + 0-row Parquet this
session]

### Pitfall 4: `--plot` with no numeric columns
**What goes wrong:** `SELECT topic, "frame_id" FROM ...` then `--plot` has nothing to put on the
y-axis (or a `SELECT t_ns` alone — `t_ns` is excluded as the x-axis).
**Why it happens:** Only `int`/`float` columns are plottable; `topic`/string/LIST/STRUCT are not,
and `t_ns`/`t` are the x-axis, not y-series.
**How to avoid:** Detect the empty y-column set and raise/print a clear message: "No numeric
columns to plot (numeric = int/float, excluding the time column)." Likewise if neither `t` nor
`t_ns` is present. (Pattern 3.) [VERIFIED: empty y-set detection this session]

### Pitfall 5: matplotlib not installed at runtime
**What goes wrong:** `--plot` on a base `bagq` install (no `[plot]` extra) raises a bare
`ModuleNotFoundError`.
**Why it happens:** matplotlib is intentionally the optional `bagq[plot]` extra to keep the base
install lean.
**How to avoid:** Catch `ImportError` around the matplotlib import and re-raise/exit with a
teaching message: "Plotting needs matplotlib. Install with: `pip install 'bagq[plot]'`."
(Pattern 3.) For TESTS, add `matplotlib>=3.8` to the root `dev` group AND guard the plot test
file with `pytest.importorskip("matplotlib")` so a contributor without the dev group is skipped,
not errored.

### Pitfall 6: Breaking the offline-import guard
**What goes wrong:** A top-level `import pyarrow`/`import duckdb`/`import matplotlib` in
`output/__init__.py`, `output/*.py`, or `bagq/cli.py` makes `test_offline_guard.py` fail
(`duckdb`/`sqlglot`/`pyarrow` leak into `sys.modules` after `import rosbagger_core`; the test
spawns a fresh interpreter so it is unmaskable).
**Why it happens:** Convenience top-level imports.
**How to avoid:** stdlib-only module top levels; import the heavy stack inside function bodies
(mirror `backend/query.py`). Do NOT import `output` from `rosbagger_core/__init__`.
**Warning signs:** `tests/test_offline_guard.py::test_*heavy*` regression.

### Pitfall 7: matplotlib state leaks across plots (figures not closed)
**What goes wrong:** Repeated `--plot` calls (or a test loop) accumulate open figures → memory
growth / warnings.
**Why it happens:** `plt.subplots()` without a matching `plt.close(fig)`.
**How to avoid:** Always `plt.close(fig)` after `savefig` (Pattern 3). Use the OO API
(`fig, ax = plt.subplots()`), not the implicit `plt.plot` global state.

## Code Examples

### Export by extension (OUT-02/03)
```python
# Source: verified this session (duckdb 1.5.3) — CSV renders LIST/STRUCT, Parquet round-trips
import duckdb
def write_table(table, path):                # table: pyarrow.Table from query()
    ext = path.lower().rsplit(".", 1)[-1]
    fmt = {"csv": "CSV", "parquet": "PARQUET"}.get(ext)
    if fmt is None:
        raise ValueError(f"Unknown output extension {ext!r}; use .csv or .parquet")
    con = duckdb.connect()
    try:
        con.register("result", table)
        opts = "FORMAT CSV, HEADER" if fmt == "CSV" else "FORMAT PARQUET"
        con.execute(f"COPY result TO '{path}' ({opts})")
    finally:
        con.close()
```

### Stdout table (OUT-01) — wired into bagq/cli.py
```python
# Source: mirrors _render_table_schemas in this repo's bagq/cli.py + Pattern 2 coercion
from rich.console import Console
from rich.table import Table
def _render_result(table, console=None, max_rows=100):
    console = console or Console()
    if table.num_rows == 0:
        console.print("(0 rows)")
        # still show columns so the user sees the result shape:
        console.print(", ".join(table.column_names))
        return
    names, rows = rows_for_display(table, max_rows=max_rows)   # Pattern 2
    rt = Table()
    for name in names:
        rt.add_column(name)
    for row in rows:
        rt.add_row(*row)
    console.print(rt)
    if table.num_rows > max_rows:
        console.print(f"... {table.num_rows - max_rows} more rows ({table.num_rows} total)")
```

### `--format json` shape
```python
# Source: verified this session — to_pylist() is the natural records shape, BUT guard temporal cols.
# For json, either (a) cast t/stamp columns to int64 (raw ns) before to_pylist(), or
# (b) cast temporal columns to strings via the Pattern-2 coercion. Recommend casting t/stamp
# to int64 (raw ns) so json stays machine-parseable:
import json, pyarrow as pa
def to_json(table):
    cols = {}
    for name in table.column_names:
        col = table.column(name)
        cols[name] = (col.cast(pa.int64()) if pa.types.is_temporal(col.type) else col).to_pylist()
    records = [dict(zip(table.column_names, vals)) for vals in zip(*cols.values())]
    return json.dumps(records)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `con.fetch_arrow_table()` | `con.to_arrow_table()` (used by Phase 5 `execute`) | duckdb ≥1.x | N/A here — Phase 6 receives an already-materialized Table; export uses `COPY`, not a fetch |
| `pyarrow` ns Timestamp → `datetime` | requires pandas; without it `to_pylist()` raises | pyarrow ≥ ~13 | Forces the `to_numpy(datetime64)` coercion path for rendering (Pitfall 1) |

**Deprecated/outdated:** None relevant to this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default `--plot` (bare) filename should be `plot.png` in CWD | Pattern 4 | Low — cosmetic; planner/discuss can pick another default (e.g. derived from first bag name). Document whatever is chosen |
| A2 | `--format csv`/`parquet` WITHOUT `-o` should still require a path (write to a file), i.e. CSV/Parquet are file formats; only `table`/`json` go to stdout | stdout table section | Medium — alternative is "stream CSV to stdout." Recommend: `--format csv` with no `-o` streams CSV to stdout (DuckDB can `COPY ... TO '/dev/stdout'` OR pyarrow can write to a buffer for scalar-only). Needs a decision; see Open Questions Q2 |
| A3 | Default stdout row cap = 100 rows with a "... N more rows" footer | Code Examples / OUT-01 | Low — a cap prevents dumping a million rows to a terminal; exact number is tunable |
| A4 | `bagq query` command is built in Phase 6 (skeleton), Phase 7 adds teaching errors | Recommended Project Structure | Medium — REQUIREMENTS.md maps CLI-01 to Phase 7. If the planner insists the command is wholly Phase 7, Phase 6's success criteria can't be demonstrated. Recommend building the skeleton now; flag to planner |
| A5 | JSON output casts `t`/`stamp` to int64 (raw ns) rather than ISO strings | `--format json` example | Low — both are defensible; raw ns is machine-parseable and avoids precision loss. Discuss if ISO-8601 is preferred |

**If this table is empty:** (it is not — these are genuine open choices for discuss-phase / the
planner to confirm.)

## Open Questions

1. **Where exactly does `bagq query` live — Phase 6 or Phase 7?**
   - What we know: OUT-01..04 (Phase 6) are unobservable without the command; CLI-01..04 are
     mapped to Phase 7; the design spec defines the full `bagq query` signature.
   - What's unclear: whether the orchestrator wants the command skeleton in 6 or all of it in 7.
   - Recommendation: Build the command skeleton + output routing in Phase 6 (so success criteria
     are demonstrable); Phase 7 enriches error handling only. Surface to the planner explicitly.

2. **`--format csv`/`parquet` with no `-o`: stream to stdout, or require `-o`?**
   - What we know: `table`/`json` naturally go to stdout; CSV/Parquet are file formats. DuckDB
     can `COPY ... TO '/dev/stdout' (FORMAT CSV, HEADER)` (Parquet-to-stdout is binary, rarely
     wanted).
   - What's unclear: the intended UX — does `--format csv` alone print CSV to the terminal?
   - Recommendation: `--format csv` with no `-o` → stream CSV to stdout; `--format parquet` with
     no `-o` → error ("Parquet is binary; specify -o out.parquet"). `-o` always wins and picks
     format by extension. Confirm in discuss-phase.

3. **Default `--plot` filename.**
   - What we know: a bare `--plot` needs a default path.
   - Recommendation: `plot.png` in CWD; or derive from the first bag stem (`<bag>.plot.png`).
     Low-stakes; pick one and document it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `duckdb` | CSV/Parquet export (`COPY`) | ✓ | 1.5.3 | — |
| `pyarrow` | result Table, coercion, numeric detection | ✓ | 24.0.0 | — |
| `numpy` | `to_numpy` for plot y-values + temporal-safe render | ✓ (via pyarrow) | 2.2.6 | — |
| `rich` | stdout table | ✓ | 15.0.0 | — |
| `typer` | `bagq query` command + options | ✓ | 0.25.1 | — |
| `matplotlib` | `--plot` (OUT-04) | ✗ in base/dev; ✓ when installed | 3.10.9 verified | Runtime: graceful `ImportError`→"install bagq[plot]". Tests: add to `dev` group + `pytest.importorskip` |

**Missing dependencies with no fallback:** none (all export/render deps present).
**Missing dependencies with fallback:** `matplotlib` — not installed in `.venv`. For `--plot` to
be exercised by tests/CI, add `matplotlib>=3.8` to the root `[dependency-groups] dev`. At
runtime, base-install users get a clear "install `bagq[plot]`" message (the existing extra). I
verified install→import→Agg headless `savefig`→uninstall this session, so the path is sound.

## Validation Architecture

> SKIPPED — `workflow.nyquist_validation` is explicitly `false` in `.planning/config.json`.

The repo nonetheless enforces a `--cov-fail-under=80` gate (`[tool.pytest.ini_options]` in the
root `pyproject.toml`) covering `rosbagger_core` and `bagq`. Phase 6 tests should therefore
exercise real behavior (not weaken coverage), following the established CLI-test pattern
(`tests/test_cli_tables.py`): `typer.testing.CliRunner` invoking `app`, asserting stable data
(not rich box-drawing). Test ideas for the planner:
- `output.write_table` → CSV (assert header + a LIST cell renders as `"[...]"`) and Parquet
  (assert `pyarrow.parquet.read_table` round-trips the schema) using the `/imu` fixture (LIST
  columns) and `/cmd_vel` (scalars).
- `output.render` rows on a result containing `t`/`stamp` (the `/imu` fixture) — proves the
  temporal-safe coercion (regression for Pitfall 1).
- Empty-result path (a `WHERE 1=0` query) → header-only CSV, 0-row Parquet, "(0 rows)" table.
- `output.plot_table` guarded by `pytest.importorskip("matplotlib")`: assert a non-empty PNG is
  written headless; assert the no-numeric-columns and no-`t` cases raise/ message.
- `bagq query` CliRunner smoke: `-o tmp.csv` writes a file; default prints a table; `--plot
  tmp.png` writes a PNG (importorskip).
- **LOCAL-RUN NOTE (carried from Phase 4/5):** this dev host sources ROS 2 onto `PYTHONPATH`; run
  reader-touching tests locally as `PYTHONPATH="" uv run pytest ...`. CI is ROS-free.

## Security Domain

> `security_enforcement` is not present in `.planning/config.json`. Phase 6 is a local,
> single-user, offline CLI presentation layer; the threat surface is minimal but two items are
> worth a note for the planner.

### Applicable controls (lightweight)

| Concern | Applies | Standard Control |
|---------|---------|------------------|
| Output path handling (`-o`, `--plot FILE`) | yes | The path is user-supplied on their own CLI — not an injection vector into a service. But the DuckDB `COPY result TO '<path>'` interpolates the path into a SQL string. A path containing a single quote (`'`) would break/inject the `COPY` statement. **Mitigation:** use DuckDB's parameterized `COPY` is not available for the target literal; instead validate/escape the path (reject or escape `'`), or write to a `pathlib.Path` and pass `str()` with quote-escaping (`path.replace("'", "''")`). Low severity (user attacks only themselves) but worth a clean escape. |
| SQL forwarding | n/a (Phase 5 owns it) | Phase 5 RESEARCH established the user's SQL is the trusted interface (T-05-04); Phase 6 adds no new SQL surface except the `COPY` path literal above |
| Untrusted bag content → output | yes (low) | Bag-derived strings (topic names, string fields) flow into stdout/CSV. rich and DuckDB `COPY` both escape/quote correctly; do not hand-build CSV. No further control needed |

**Key note for the planner:** the one genuinely new (if low-severity) security surface is the
`COPY result TO '<user path>'` literal. Escape the path (`'` → `''`) or validate the extension +
reject quotes before interpolating. This is the only place Phase 6 builds SQL.

## Sources

### Primary (HIGH confidence — verified this session)
- `pyarrow 24.0.0` runtime experiments: `csv.write_csv` raises `ArrowInvalid` on LIST; Parquet
  round-trips LIST/STRUCT; `timestamp[ns]` `to_pylist`/`str` raises `ValueError`;
  `to_numpy(zero_copy_only=False)` → `datetime64[ns]`; `pyarrow.types.is_integer`/`is_floating`/
  `is_temporal` predicates.
- `duckdb 1.5.3` runtime experiments: `COPY res TO 'f.csv' (FORMAT CSV, HEADER)` renders
  LIST/STRUCT; `COPY ... (FORMAT PARQUET)` round-trips; header-only CSV + 0-row Parquet on empty.
- `matplotlib 3.10.9` runtime: `matplotlib.use("Agg")` → headless `fig.savefig` with `DISPLAY`
  unset succeeds (PNG written), for both `t_ns` (int) and `t` (datetime64) x-axes.
- `typer 0.25.1` / `click`: `is_flag=False, flag_value=<sentinel>, default=None` gives an
  optional-value flag (omitted/bare/with-value all distinguishable).
- This repo: `backend/query.py` (input contract + offline-lazy-import pattern), `schema/model.py`
  + `schema/types.py` (result column types: dotted names, `timestamp[ns]` `t`/`stamp`, `int64`
  `t_ns`, LIST/STRUCT, heavy blobs), `bagq/cli.py` (thin-CLI + rich render pattern),
  `tests/test_cli_tables.py` + `test_offline_guard.py` (test patterns + the offline invariant),
  `tools/make_fixtures.py` (fixture topics/types available for tests).
- `.planning/REQUIREMENTS.md` (OUT-01..04, CLI mapping), `docs/.../rosbagger-design.md` (lines
  108, 116, 119 — output writers, `bagq query` signature, intentionally-minimal plot),
  `.planning/phases/05-query-engine/05-RESEARCH.md` (Pitfall 4: 0-row result keeps schema; the
  `to_arrow_table` note).

### Secondary (MEDIUM confidence)
- (none — all claims verified directly against the installed stack and repo this session.)

### Tertiary (LOW confidence)
- (none.)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package version confirmed via `importlib.metadata`; export/render
  behaviors confirmed by running them.
- Architecture: HIGH — directly mirrors the shipped `backend/query.py` offline-lazy-import
  discipline and the `bagq/cli.py` thin-CLI pattern; tier ownership follows the API-first
  decision already in force.
- Pitfalls: HIGH — all six technical pitfalls (CSV-LIST, ns-timestamp, empty result, no-numeric,
  matplotlib-missing, offline-guard) were reproduced or directly verified this session.
- Open scope question (Phase 6 vs 7 for `bagq query`): MEDIUM — a planning judgment call, flagged
  for the planner, not a technical unknown.

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (stable; the stack is mature and pinned. matplotlib was the only
moving piece and its `>=3.8` floor is already declared.)
