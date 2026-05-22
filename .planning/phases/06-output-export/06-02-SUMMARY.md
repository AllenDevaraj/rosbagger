---
phase: 06-output-export
plan: 02
subsystem: output
tags: [matplotlib, plot, pyarrow, typer, click, cli, headless, agg]

# Dependency graph
requires:
  - phase: 06-output-export (06-01)
    provides: "rosbagger_core.output module (rows_for_display/to_json/write_table/write_csv_stream) + the thin `bagq query \"<SQL>\" BAG [-o OUT] [--format ...]` command to extend"
  - phase: 05-query-engine
    provides: "query(sql, reader) -> fully-materialized pyarrow.Table (the plot input)"
  - phase: 03-message-table-schema
    provides: "result column types (t/stamp timestamp[ns], t_ns int64, topic string, dotted body cols, LIST/STRUCT) — drives numeric-column detection"
provides:
  - "rosbagger_core.output.plot_table(table, path) — minimal headless (Agg) matplotlib line chart of numeric result columns vs t_ns; lazy/optional matplotlib"
  - "`bagq query ... --plot [FILE]` (OUT-04): bare --plot writes plot.png, --plot FILE writes that file"
  - "matplotlib>=3.8 in the root [dependency-groups] dev (also the bagq[plot] extra) so CI/tests exercise --plot; uv.lock updated"
affects: [07-cli-teaching-errors, 08-packaging-docs-release]

# Tech tracking
tech-stack:
  added: ["matplotlib>=3.8 (dev group; runtime via bagq[plot] extra)"]
  patterns:
    - "Lazy + optional heavy import: matplotlib (and pyarrow) imported INSIDE plot_table; ImportError -> teaching RuntimeError (install bagq[plot]); module top level stays stdlib-only (offline invariant)"
    - "Headless-first plotting: matplotlib.use('Agg') BEFORE importing pyplot; plt.close(fig) after savefig (figure-leak DoS mitigation, T-06-05)"
    - "Optional-value CLI flag via a TyperCommand subclass that rebuilds the option as a native click.Option (typer 0.25.1 cannot carry flag_value)"

key-files:
  created:
    - "packages/rosbagger-core/src/rosbagger_core/output/plot.py"
    - "tests/test_output_plot.py"
  modified:
    - "packages/rosbagger-core/src/rosbagger_core/output/__init__.py (re-export plot_table)"
    - "packages/bagq/src/bagq/cli.py (--plot [FILE] flag + _PlotCommand)"
    - "pyproject.toml (matplotlib>=3.8 in dev group)"
    - "uv.lock (matplotlib resolved)"

key-decisions:
  - "x-axis is t_ns (int64), not t (timestamp[ns]) — sidesteps the ns->datetime crash class (06-RESEARCH); falls back to t only when t_ns absent"
  - "Numeric y-cols via pyarrow.types.is_integer/is_floating (excludes topic/string/LIST/STRUCT and t_ns) — robust over string type-name matching"
  - "matplotlib stays the optional bagq[plot] extra at runtime; added to the dev group only so CI/tests run --plot; tests guard with pytest.importorskip('matplotlib')"
  - "--plot is its own output sink and takes precedence over -o/--format (plot and return); RuntimeError/ValueError propagate (Phase 7 owns teaching errors)"
  - "DEVIATION (Rule 3): RESEARCH Pattern 4's typer.Option(is_flag=False, flag_value=...) idiom does NOT work on pinned typer 0.25.1 (flag_value is dropped during click conversion) — restored via a _PlotCommand(TyperCommand) cls= that rebuilds --plot as a native click.Option"

patterns-established:
  - "Optional dependency behind a lazy in-function import with a teaching error, kept out of the offline import graph"
  - "Typer optional-value flag (omitted/bare/with-value) via a minimal TyperCommand subclass — zero ripple to the typer app / entry point"

requirements-completed: [OUT-04]

# Metrics
duration: 12min
completed: 2026-05-22
---

# Phase 6 Plan 02: --plot Line Chart (OUT-04) Summary

**`bagq query "<SQL>" BAG --plot [FILE]` renders a minimal headless (Agg) matplotlib line chart of the numeric result columns vs `t_ns` via a lazy/optional `rosbagger_core.output.plot_table`; matplotlib added to the dev group so CI exercises it.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-22T16:56:04Z
- **Completed:** 2026-05-22T17:08:24Z
- **Tasks:** 3 (Task 1 via TDD: RED + GREEN)
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments
- `plot_table(table, path)` — a minimal headless line chart of the int/float result columns (excluding `topic`/string/LIST/STRUCT and the `t_ns` x-axis) against `t_ns` (fallback `t`), written as a PNG; `matplotlib.use("Agg")` before pyplot (DISPLAY-unset safe), `plt.close(fig)` after savefig (figure-leak mitigation).
- Clear errors instead of blank charts: 0-row, no-numeric-column, and no-`t`/`t_ns` results all raise a teaching `ValueError`; a missing matplotlib raises a teaching `RuntimeError` ("install `bagq[plot]`"), never a bare `ModuleNotFoundError`.
- `bagq query ... --plot [FILE]` wired (OUT-04): bare `--plot` → `plot.png` in CWD, `--plot FILE` → that file; verified end-to-end on a `cmd_vel "linear.x"` vs `t_ns` query (23.5 KB PNG).
- matplotlib>=3.8 added to the root dev group (also the existing `bagq[plot]` extra); `uv lock` + `uv sync` resolved + installed it; `uv.lock` committed.
- Offline invariant intact: `import rosbagger_core.output` (and `import bagq.cli`) still leak no duckdb/sqlglot/pyarrow/matplotlib.

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED): failing plot_table tests + matplotlib dev dep** - `bb64485` (test) — adds matplotlib to the dev group (+ uv.lock) and the `importorskip`-guarded failing tests
2. **Task 1 (TDD GREEN): plot_table implementation + re-export** - `aeef646` (feat)
3. **Task 2: --plot [FILE] optional-value flag on bagq query** - `55e8245` (feat)
4. **Task 3: cover matplotlib-missing teaching path; full suite green** - `8b323d7` (test)

**Plan metadata:** _(this commit)_ (docs: complete plan)

_Note: Task 1 is a TDD task (RED `bb64485` → GREEN `aeef646`); no REFACTOR commit was needed (the Pattern-3 implementation was already clean)._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/output/plot.py` - `plot_table`: lazy/optional matplotlib (Agg before pyplot), numeric-vs-`t_ns`, teaching errors, figure close
- `packages/rosbagger-core/src/rosbagger_core/output/__init__.py` - re-export `plot_table` (top level stays stdlib-only)
- `packages/bagq/src/bagq/cli.py` - `--plot [FILE]` option + `_PlotCommand(TyperCommand)` + plot routing on `query`
- `pyproject.toml` - `matplotlib>=3.8` in `[dependency-groups] dev`
- `uv.lock` - matplotlib resolved into the dev group
- `tests/test_output_plot.py` - `importorskip`-guarded: numeric PNG, no-numeric / only-`t_ns` / no-`t_ns` / 0-row / figure-close / matplotlib-missing; CLI `--plot FILE`, bare `--plot`, no-numeric error, `--help`

## Decisions Made
- **x = `t_ns` (int64), not `t`:** avoids the `timestamp[ns]`→`datetime` conversion crash class entirely (06-RESEARCH Pitfall 1); `t` is the fallback only when `t_ns` is absent.
- **Numeric detection via `pyarrow.types.is_integer`/`is_floating`:** naturally excludes `topic`/string/LIST/STRUCT; `t_ns` excluded as the x-axis.
- **matplotlib optional at runtime, dev-only for tests:** kept the base `bagq` install lean (the `bagq[plot]` extra unchanged); added to the dev group so CI/`uv run` exercise `--plot`; the plot test module is `pytest.importorskip("matplotlib")`-guarded so a contributor without the dev group is skipped, not errored.
- **`--plot` is its own output sink and takes precedence:** when set, plot and return (ignore table/`-o`/`--format`); `RuntimeError`/`ValueError` propagate (Phase 7 owns teaching-error formatting).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] RESEARCH Pattern 4 optional-value-flag idiom does not work on pinned typer 0.25.1**
- **Found during:** Task 2 (`--plot [FILE]` flag wiring)
- **Issue:** The plan/06-RESEARCH Pattern 4 idiom — `typer.Option("--plot", is_flag=False, flag_value=_PLOT_DEFAULT, default=None)` — does **not** produce an optional-value flag on the pinned typer (`0.25.1`, click `8.4.1`). Reading typer's source (`typer.main.get_click_param`) confirmed typer **silently drops `flag_value`** during the `typer.Option`→click conversion (it only forwards a computed `is_flag` for bool params, and `count`; it never reads `flag_value`). The result: bare `--plot` errored with "Option '--plot' requires an argument" (exit 2), and typer also emitted a `DeprecationWarning` that `is_flag`/`flag_value` are unsupported. Post-hoc param injection was ruled out because typer **rebuilds** the command group on every `get_command(app)` call (verified), so mutations don't survive to the real `app()` invocation. Converting `query` to a native click command was ruled out because it ripples into 06-01's `test_cli_query.py` (which invokes `app` via `typer.testing.CliRunner`, which only accepts a `typer.Typer`) and touches the `bagq.cli:app` entry-point contract.
- **Fix:** Added a small, documented `_PlotCommand(TyperCommand)` and registered the command with `@app.command(cls=_PlotCommand)`. In its `__init__` (which runs at every command build), it locates the `--plot` option and **replaces** it with a freshly-constructed native `click.Option(["--plot"], is_flag=False, flag_value=_PLOT_DEFAULT, default=None)` — reconstruction (not in-place mutation) is required because click derives the optional-value parser behaviour in `click.Option.__init__`. The `--plot` `typer.Option` in the signature was reduced to a plain string option (no `is_flag`/`flag_value`), clearing the `DeprecationWarning`. `app` stays a `typer.Typer` and `query` stays a typer command, so the entry point and all 06-01 CliRunner tests are untouched (verified: 14/14 still pass).
- **Files modified:** `packages/bagq/src/bagq/cli.py`
- **Verification:** Omitted → `None` (no plot); bare `--plot` → `plot.png`; `--plot FILE` → that file; `--help` lists `--plot`; no DeprecationWarning; offline import of `bagq.cli` leaks no heavy/optional stack. Full plot suite (11 tests) + 06-01 CLI/guard suite (14) green.
- **Committed in:** `55e8245` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The mechanism for declaring one CLI option changed (a `TyperCommand` subclass instead of the non-functional `typer.Option` kwargs), but the user-facing contract — `bagq query ... --plot [FILE]` with omitted/bare/with-value semantics, the `bagq.cli:app` entry point, and the OUT-04 success criteria — is exactly as specified. `click` is already a `typer` dependency (no new package). No scope creep.

## Issues Encountered
- The `--plot` flag idiom required reading typer 0.25.1 source and several composition experiments (post-hoc injection, native-click composition, callback wrapping) before settling on the zero-ripple `TyperCommand` subclass. Captured in the deviation above.

## Known Stubs
None — `plot_table` is fully wired to real Arrow result data (no placeholder/empty-data paths); the CLI calls it on the live `query()` result.

## User Setup Required
None for the base install. `--plot` requires the optional plot extra: `pip install 'bagq[plot]'` (or it is already present in the dev group for contributors). A missing matplotlib surfaces a teaching `RuntimeError`, not a crash.

## Next Phase Readiness
- **Phase 6 COMPLETE (2/2).** All four output forms shipped: stdout table (OUT-01), CSV (OUT-02), Parquet (OUT-03), and `--plot` (OUT-04).
- Phase 7 (CLI & Teaching Errors) can now layer did-you-mean / teaching errors onto the already-wired `bagq query` command (its `RuntimeError`/`ValueError`/`UnknownTableError` currently propagate raw, by design).
- Full suite: 219 passed at 98.04% coverage (≥80% gate); `plot.py` 100%; ruff format-check + lint clean.

## Self-Check: PASSED

- Created files exist: `output/plot.py`, `tests/test_output_plot.py`, `06-02-SUMMARY.md`.
- Task commits exist: `bb64485` (RED), `aeef646` (GREEN), `55e8245` (Task 2), `8b323d7` (Task 3).
- `uv.lock` carries the resolved matplotlib (dev group).

---
*Phase: 06-output-export*
*Completed: 2026-05-22*
