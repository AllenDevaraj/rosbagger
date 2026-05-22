"""bagq CLI entry point.

Defines the typer application bound to the symbol ``app`` so the console-script
``bagq = "bagq.cli:app"`` resolves. Phase 1 shipped a minimal runnable surface
(``bagq --help`` / ``bagq --version``); Phase 4 added the first real subcommands,
``bagq info`` (the Inspect overview) and ``bagq tables`` (per-topic table name +
column schema). Phase 6 adds ``bagq query`` — run SQL over a bag and route the
result to a rich stdout table (default), a CSV/Parquet file (``-o``), or
``--format csv|parquet|json``.

Keep this module light: import only typer/rich at top level — do NOT import
rosbagger-core's heavy stack (``rosbags``/``pyarrow``/``duckdb``) here. The
``info``/``tables``/``query`` commands import the core API LAZILY inside their
bodies, so ``bagq --help`` stays fast and pays no ``rosbags`` import cost
(offline-guard discipline; ``tests/test_offline_guard.py``).

Per design decision 1 (API-first), all computation lives in
``rosbagger_core.inspect``; this module only renders the returned dataclasses.
The lone presentation-side arithmetic is byte -> human-readable size formatting,
which is deliberately a CLI concern (the API keeps ``size_bytes`` raw).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import click
import typer
from rich.console import Console
from rich.table import Table
from typer.core import TyperCommand

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    import pyarrow

from bagq import __version__

app = typer.Typer(
    add_completion=False,
    help="bagq — query ROS 1 / ROS 2 / MCAP bags with SQL. No ROS install required.",
    no_args_is_help=True,
)

# `bagq query --plot` is an OPTIONAL-VALUE flag (06-RESEARCH Pattern 4): omitted writes
# nothing, bare `--plot` writes the default filename, `--plot FILE` writes that file. The
# native click idiom is `is_flag=False, flag_value=<sentinel>, default=None`, but typer
# 0.25.1 SILENTLY DROPS `flag_value` when it converts `typer.Option` -> click (see
# typer.main.get_click_param: it only forwards `is_flag` for bool params and never reads
# `flag_value`), so a bare `--plot` errors with "requires an argument". `_PlotCommand`
# below (a `TyperCommand` subclass passed via `@app.command(cls=...)`) restores the idiom
# by REBUILDING the `--plot` option as a native `click.Option` after typer constructs the
# command — keeping `query` a normal typer command and `app` a normal `typer.Typer` (so
# the `bagq.cli:app` entry point and the 06-01 CliRunner tests are untouched).
_PLOT_DEFAULT = "\x00bagq-default-plot"  # bare --plot sentinel; resolves to _PLOT_DEFAULT_FILE
_PLOT_DEFAULT_FILE = "plot.png"  # the default chart filename in CWD (decision A1)


def teaching_errors(fn):
    """Wrap a command body: turn the KNOWN typed errors into a clean message + ``Exit(1)``.

    The shared CLI-01 error-exit MECHANISM (07-RESEARCH Pattern 4): a command that raises
    one of the expected, data-carrying errors should print a single teaching line to
    stderr and exit non-zero — NEVER dump a Python traceback (the difference between a
    tool and a script). ``info``/``tables``/``query`` all wear this decorator.

    Catches ONLY the known set (07-RESEARCH Pitfall 4): ``UnknownTableError`` (a SQL table
    that maps to no topic — its message already lists the available tables) and
    ``FileNotFoundError`` (a missing bag path). A bare ``except Exception`` is deliberately
    NOT used: a genuine programming bug (``KeyError``/``AttributeError``/…) must still
    surface as a traceback so it can be diagnosed.

    07-02 WIDENS the teaching CONTENT by adding new typed errors (``UnknownColumnError`` /
    ``UnresolvedTypeError``) to the import below and to the ``except (...)`` tuple — a
    one-line change at each, with the wrapper structure unchanged.

    The errors are imported LAZILY inside the wrapper so ``cli.py``'s top level stays
    typer/rich-only (offline-guard discipline); ``rosbagger_core.backend.query`` is
    stdlib-light at module scope, so this import pulls no heavy stack until the wrapped
    command is actually invoked.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Lazy import — keeps cli.py top level free of rosbagger_core (offline invariant).
        # 07-02 adds the new typed errors to this import + the except tuple below.
        from rosbagger_core.backend.query import UnknownTableError

        try:
            return fn(*args, **kwargs)
        except UnknownTableError as e:
            # The message already carries the available-tables list (CLI-02 content lands
            # in 07-02); present it cleanly with no traceback.
            typer.secho(str(e), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
        except FileNotFoundError as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
        # NOTE (Pitfall 4): NO `except Exception` — real bugs must still traceback.

    return wrapper


class _PlotCommand(TyperCommand):
    """A ``TyperCommand`` that makes ``--plot`` a click optional-value flag.

    typer 0.25.1 cannot express an optional-value flag (it drops ``flag_value`` during the
    ``typer.Option`` -> click conversion), so this subclass post-processes the command's
    params — typer rebuilds them on every ``get_command`` call, so the fix must run at
    construction time — and REPLACES the ``--plot`` option with a freshly-built
    ``click.Option(is_flag=False, flag_value=_PLOT_DEFAULT, default=None)``. Reconstructing
    (rather than mutating ``is_flag``/``flag_value`` in place) is required because click
    derives the optional-value parser behaviour in ``click.Option.__init__``. The result:
    omitted -> ``None``; bare ``--plot`` -> ``_PLOT_DEFAULT``; ``--plot FILE`` -> ``"FILE"``.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        for i, param in enumerate(self.params):
            if isinstance(param, click.Option) and "--plot" in param.opts:
                self.params[i] = click.Option(
                    list(param.opts),
                    is_flag=False,
                    flag_value=_PLOT_DEFAULT,
                    default=None,
                    help=param.help,
                )


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"bagq {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the bagq version and exit.",
    ),
) -> None:
    """bagq command-line interface."""


def _human_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB / GB / TB).

    Presentation-only (the inspect API keeps ``size_bytes`` raw — Open Q2).
    Uses 1024-based units; whole bytes print without a decimal, larger units
    print one decimal (e.g. ``9.2 KB``, ``29.3 KB``, ``1.5 MB``).
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"  # pragma: no cover - unreachable (GB branch returns first)


def _render_bag_info(info, console: Console | None = None) -> None:
    """Render a ``BagInfo`` as a rich topic table plus a whole-bag footer line.

    Columns: topic, msgtype, count (right-justified), Hz (right-justified). A
    ``None`` msgtype (multi-msgtype topic) renders as ``<mixed>``; a ``None`` Hz
    (empty/zero-duration bag) renders as ``—``. The footer summarizes duration
    (seconds, or ``—`` when None), message count, and human-readable size.
    """
    console = console or Console()
    table = Table(title="Bag overview")
    table.add_column("topic")
    table.add_column("msgtype")
    table.add_column("count", justify="right")
    table.add_column("Hz", justify="right")
    for ti in info.topics:
        hz = f"{ti.hz:.1f}" if ti.hz is not None else "—"
        table.add_row(ti.topic, ti.msgtype or "<mixed>", str(ti.count), hz)
    console.print(table)

    duration = f"{info.duration_ns / 1e9:.2f}s" if info.duration_ns is not None else "—"
    console.print(
        f"duration: {duration} · {info.message_count} messages · {_human_size(info.size_bytes)}"
    )


@app.command()
@teaching_errors
def info(
    bags: Annotated[
        list[Path],
        typer.Argument(help="One or more bag paths (file or directory)."),
    ],
) -> None:
    """List each topic's message type, count, and approximate Hz, plus duration and size."""
    # Import the core API lazily (inside the body) so module import stays light
    # and `bagq --help` pays no rosbags import cost.
    from rosbagger_core.inspect import collect_bag_info
    from rosbagger_core.reader import RosbagsReader

    # FileNotFoundError (missing bag) is caught by @teaching_errors -> clean Exit(1).
    # Other AnyReaderError cases still propagate (07-02 adds UnresolvedTypeError).
    with RosbagsReader(bags) as reader:
        bag_info = collect_bag_info(reader)
    _render_bag_info(bag_info)


def _render_table_schemas(schemas, console: Console | None = None) -> None:
    """Render a list of ``TableSchema`` as one rich column table per topic (INSP-03).

    For each schema, prints a ``topic → table_name`` heading then a rich table
    listing EVERY column: its dotted/standard ``name``, the rendered
    ``str(arrow_type)`` (e.g. ``timestamp[ns]``, ``int64``, ``list<item: uint8>``),
    and a heavy-blob marker. Heavy blobs are SHOWN and annotated ``lazy``, never
    hidden (Assumption A2 / Pattern 4) — the user is asking "what columns exist?",
    and the blob's bytes are never read (its name + type only; threat T-04-07).
    Uses ``ColumnDef.is_heavy_blob`` directly, not ``column_names(include=...)``.

    With no topics (e.g. an empty/zero-connection bag) prints a "no topics" line
    rather than emitting an empty table.
    """
    console = console or Console()
    if not schemas:
        console.print("no topics")
        return
    for schema in schemas:
        console.print(f"{schema.topic} → {schema.table_name}")
        table = Table()
        table.add_column("column")
        table.add_column("type")
        table.add_column("lazy")
        for col in schema.columns:
            marker = "lazy (blob)" if col.is_heavy_blob else ""
            table.add_row(col.name, str(col.arrow_type), marker)
        console.print(table)


@app.command()
@teaching_errors
def tables(
    bags: Annotated[
        list[Path],
        typer.Argument(help="One or more bag paths (file or directory)."),
    ],
) -> None:
    """Print each topic's table name and column schema (heavy blobs marked lazy)."""
    # Import the core API lazily (inside the body) so module import stays light
    # and `bagq --help` pays no rosbags import cost.
    from rosbagger_core.inspect import collect_table_schemas
    from rosbagger_core.reader import RosbagsReader

    # FileNotFoundError (missing bag) is caught by @teaching_errors -> clean Exit(1).
    # Other AnyReaderError cases still propagate (07-02 adds UnresolvedTypeError).
    with RosbagsReader(bags) as reader:
        schemas = collect_table_schemas(reader)
    _render_table_schemas(schemas)


def _render_result(
    table: pyarrow.Table,
    console: Console | None = None,
    max_rows: int = 100,
) -> None:
    """Render a result ``pyarrow.Table`` as a rich stdout table (OUT-01).

    A 0-row result prints ``(0 rows)`` followed by the comma-joined column names, so
    the user still sees the result shape rather than a blank table (06-RESEARCH
    Pitfall 3). Otherwise builds a ``rich.table.Table`` from the temporal-safe
    coercion in :func:`rosbagger_core.output.rows_for_display` (the renderer does NOT
    re-implement coercion — ``timestamp[ns]`` ``t``/``stamp`` would crash a naive
    ``str()``; Pitfall 1), capped at ``max_rows`` rows with a ``... N more rows``
    footer when the result is larger.
    """
    from rosbagger_core.output import rows_for_display

    console = console or Console()
    if table.num_rows == 0:
        console.print("(0 rows)")
        # Still show the columns so the user sees the result shape (Pitfall 3).
        console.print(", ".join(table.column_names))
        return
    names, rows = rows_for_display(table, max_rows=max_rows)
    rt = Table()
    for name in names:
        rt.add_column(name)
    for row in rows:
        rt.add_row(*row)
    console.print(rt)
    if table.num_rows > max_rows:
        console.print(f"... {table.num_rows - max_rows} more rows ({table.num_rows} total)")


@app.command(cls=_PlotCommand)
@teaching_errors
def query(
    sql: Annotated[
        str,
        typer.Argument(help='SQL to run, e.g. "SELECT t, t_ns FROM cmd_vel".'),
    ],
    bags: Annotated[
        list[Path],
        typer.Argument(help="One or more bag paths (file or directory)."),
    ],
    out: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Write CSV/Parquet by extension (.csv/.parquet)."),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option("--format", help="table|csv|parquet|json (default table)."),
    ] = "table",
    plot: Annotated[
        str | None,
        # Declared as a plain string option; `_PlotCommand` (the `cls=` above) rebuilds it
        # into a click optional-value flag (typer can't carry `flag_value` itself — see the
        # `_PlotCommand` docstring). Omitted -> None; bare `--plot` -> `_PLOT_DEFAULT`
        # sentinel; `--plot FILE` -> "FILE".
        typer.Option(
            "--plot",
            help="Plot numeric columns vs t. Bare = write plot.png; --plot FILE = that file.",
        ),
    ] = None,
) -> None:
    """Run a SQL query over one or more bags and print or export the result.

    Default prints a rich table to stdout (OUT-01). ``-o out.csv`` / ``-o out.parquet``
    write a file by extension (OUT-02/03). ``--format`` selects the sink when no ``-o``
    is given: ``table`` (default), ``csv`` (streams CSV to stdout), ``parquet`` (errors
    — binary), or ``json`` (temporal-safe records). ``-o`` always wins over ``--format``.
    ``--plot`` is its own output sink (OUT-04): a minimal headless line chart of the
    numeric result columns vs ``t_ns``; bare ``--plot`` writes ``plot.png`` in CWD,
    ``--plot FILE`` writes that file. When ``--plot`` is given it takes precedence over
    table/``--format`` rendering.
    """
    # Import the core API lazily (inside the body) so module import stays light and
    # `bagq --help` pays no rosbags/duckdb/pyarrow import cost (offline-guard).
    from rosbagger_core.backend.query import query as run_query
    from rosbagger_core.output import plot_table, to_json, write_csv_to_string, write_table
    from rosbagger_core.reader import RosbagsReader

    # UnknownTableError (unknown table) and FileNotFoundError (missing bag) are caught by
    # the @teaching_errors wrapper -> a clean one-line message + Exit(1), no traceback.
    # The result Arrow table is fully materialized inside query() (the backend closes
    # before it returns), so it outlives the reader `with` block.
    with RosbagsReader(bags) as reader:
        result = run_query(sql, reader)

    # --plot is its own output sink (OUT-04) and takes precedence: when set, plot and
    # return, ignoring table/-o/--format. The bare-flag sentinel resolves to plot.png
    # (decision A1); --plot FILE writes that file. The RuntimeError (matplotlib missing
    # -> teaching "install bagq[plot]") and any ValueError (nothing to plot) PROPAGATE —
    # Phase 7 owns formatting errors; do NOT swallow them here.
    if plot is not None:
        target = _PLOT_DEFAULT_FILE if plot == _PLOT_DEFAULT else plot
        plot_table(result, target)
        typer.echo(f"Wrote {target}")
        return

    # Route by precedence: an explicit -o wins and picks the format by extension.
    if out is not None:
        write_table(result, str(out))
        typer.echo(f"Wrote {out} ({result.num_rows} rows)")
        return

    # No -o: dispatch on --format.
    if fmt == "table":
        _render_result(result)
    elif fmt == "csv":
        # --format csv with no -o prints CSV to stdout (decision A2). write_csv_to_string
        # buffers the COPY to a temp file in core and RETURNS the text; the CLI echoes it
        # via Python (typer.echo) — CliRunner-capturable and OS-portable (WR-02; no
        # /dev/stdout). nl=False because the CSV already ends in its own newline. The
        # COPY/escape stays in core, so cli.py imports no duckdb (offline invariant).
        typer.echo(write_csv_to_string(result), nl=False)
    elif fmt == "parquet":
        raise typer.BadParameter("Parquet is binary; specify -o out.parquet")
    elif fmt == "json":
        typer.echo(to_json(result))
    else:
        raise typer.BadParameter(f"Unknown format {fmt!r}; use table|csv|parquet|json")


if __name__ == "__main__":  # pragma: no cover
    app()
