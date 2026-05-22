---
phase: 06-output-export
reviewed: 2026-05-22T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - packages/bagq/src/bagq/cli.py
  - packages/rosbagger-core/src/rosbagger_core/output/__init__.py
  - packages/rosbagger-core/src/rosbagger_core/output/export.py
  - packages/rosbagger-core/src/rosbagger_core/output/plot.py
  - packages/rosbagger-core/src/rosbagger_core/output/render.py
  - tests/test_cli_query.py
  - tests/test_offline_guard.py
  - tests/test_output_export.py
  - tests/test_output_plot.py
  - tests/test_output_render.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-05-22
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 6 adds the `rosbagger_core.output` module (render/export/plot) and the `bagq query`
CLI command. The implementation is, on the whole, careful and well-reasoned, and the
highest-risk surfaces hold up under empirical scrutiny:

- **SQL injection (T-06-01) is correctly defended.** The `COPY result TO '<path>'` literal
  single-quote-escapes (`'` → `''`). I verified empirically (duckdb 1.5.3) that a path
  containing `'` is written to the literal name and that backslashes in the path are NOT
  reinterpreted as escape sequences (DuckDB single-quoted literals are SQL-standard, no
  backslash processing). The `result` identifier is fixed and the format comes from a
  closed `{csv, parquet}` map — no user text reaches the SQL grammar except the escaped
  path literal. The defense is sound.
- **Offline invariant is preserved perfectly.** Verified in a fresh interpreter that
  `import rosbagger_core.output` and `import bagq.cli` leave `duckdb`/`sqlglot`/`pyarrow`/
  `matplotlib`/`numpy` out of `sys.modules`. All heavy imports are correctly placed inside
  function bodies.
- **Temporal-safe rendering is correct.** Confirmed `to_pylist()`/`str()` genuinely raise
  `ValueError` on `timestamp[ns]`, and the `combine_chunks().to_numpy()` → `datetime64[ns]`
  path with `x != x` NaT→`""` handling works, including the 0-row and `max_rows` cases.
- **Figure cleanup is correct** (`plt.close(fig)` in `finally`; verified no leak across
  repeated calls).
- **Numeric y-column selection is correct.** The `list<uint8>` blob is naturally excluded
  (LIST wrapper makes `is_integer` False); the `t`-fallback x-axis (timestamp[ns]) plots
  without crashing; `--plot=FILE`, bare `--plot`, and `--plot` taking precedence over `-o`
  all work.
- All 37 phase-6 tests pass; output module files are at 100% statement coverage.

The defects below are real but none are blockers. The two that matter most are a path
extension-parsing bug in `write_table` and a portability/testability gap in the
`--format csv` stdout-streaming path (which contradicts the project's "runs anywhere"
constraint and is the one CLI branch with no test).

## Warnings

### WR-01: `write_table` parses the extension from the whole path, mis-handling dotted directory names

**File:** `packages/rosbagger-core/src/rosbagger_core/output/export.py:81`
**Issue:** The format-selection extension is computed with `rsplit(".", 1)` over the ENTIRE
path string, not the basename:

```python
ext = path_str.lower().rsplit(".", 1)[-1] if "." in path_str else ""
```

When a *directory* component contains a dot and the *file* has no extension, this extracts
a garbage "extension" that spans the path separator. Verified:

```
'v1.0/output'        -> ext='0/output'      -> ValueError "Unknown output extension '0/output'"
'my.results/data'    -> ext='results/data'  -> ValueError "Unknown output extension 'results/data'"
'/home/a.b/results'  -> ext='b/results'     -> ValueError
```

A user who organizes output into a versioned/dotted directory (`-o runs.2026/result` or
`-o v1.0/out.csv` is fine, but `-o results.d/myfile` is not) gets a confusing error whose
message leaks a mangled token containing a slash. This is a correctness/UX defect; no data
loss (the write simply never happens, and the case is also rejected by design since the
file has no extension — but for the WRONG reason and with a misleading message).

**Fix:** Parse the extension from the basename only, using the stdlib:

```python
import os

stem, dot_ext = os.path.splitext(os.path.basename(path_str))
ext = dot_ext[1:].lower()  # drop the leading '.'; '' when there is no extension
opts = _FORMAT_OPTS.get(ext)
```

`os.path.splitext` on `'v1.0/output'` correctly yields `''`, and on `'out.csv'` yields
`'.csv'`. This also makes the error message clean (`Unknown output extension ''`).

### WR-02: `--format csv` streams via `COPY TO '/dev/stdout'`, which is OS-fd-level (uncapturable, non-portable to Windows)

**File:** `packages/bagq/src/bagq/cli.py:324-329`, `packages/rosbagger-core/src/rosbagger_core/output/export.py:88-102`
**Issue:** `bagq query --format csv` (no `-o`) calls `write_csv_stream(result)`, which runs
`COPY result TO '/dev/stdout' (FORMAT CSV, HEADER)`. DuckDB opens `/dev/stdout` as a file at
the OS level and writes to **file descriptor 1 directly** — it does NOT go through Python's
`sys.stdout`. Two consequences, both verified:

1. **Uncapturable by the standard test/redirection layer.** Under `CliRunner.invoke(...)`,
   `result.stdout` is `''` while the CSV (`t_ns,topic\n1000000000,/cmd_vel...`) leaks to the
   real terminal fd. The same applies to pytest `capsys` and to any code that swaps
   `sys.stdout`. This is almost certainly *why* this branch has no CLI test (see WR-03) —
   a `CliRunner` assertion on `result.stdout` cannot see the output.
2. **Non-portable.** `/dev/stdout` does not exist on Windows; `COPY TO '/dev/stdout'` fails
   there with an IO error. CLAUDE.md states "offline tools run anywhere" and "portability:
   offline tools run anywhere, CI included." CI is Linux so this passes, masking the gap.
   The 06-RESEARCH note that chose `/dev/stdout` (A2) never addressed Windows.

Output-ordering relative to other `typer.echo`/`print` calls is also not guaranteed because
two independent writers share fd 1.

**Fix:** Keep the duckdb/COPY logic in core (offline invariant), but have it write CSV into a
buffer and return the text, then let the CLI print it through `typer.echo`/`sys.stdout`:

```python
# export.py — write to a temp file, read it back, return the bytes/str:
def csv_to_string(table: pyarrow.Table) -> str:
    import tempfile, os, duckdb
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        _copy_to(table, tmp, _FORMAT_OPTS["csv"])
        with open(tmp, encoding="utf-8") as f:
            return f.read()
    finally:
        os.unlink(tmp)
```
```python
# cli.py:
elif fmt == "csv":
    sys.stdout.write(csv_to_string(result))
```

This is portable, capturable, and keeps duckdb out of `cli.py`. If streaming truly large
results to stdout is a goal, gate `/dev/stdout` behind an `os.name == "posix"` check and fall
back to the buffer path elsewhere.

### WR-03: No CLI test for the `--format csv` branch (the streaming path is unexercised)

**File:** `tests/test_cli_query.py` (entire file — the branch is absent)
**Issue:** `tests/test_cli_query.py` covers `table` (default), `-o .csv`, `-o .parquet`,
`--format json`, `--format parquet` (error), and unknown-format (error) — but never
`--format csv`. The cli.py coverage report confirms line 329 (`write_csv_stream(result)`)
is the lone uncovered statement in the `query` body. So the one `--format` value that wires
the CLI to `write_csv_stream` ships with zero CLI-level coverage; the `_copy_to`/escape path
is covered only by the direct `test_output_export.py` calls. A regression in the `fmt ==
"csv"` dispatch (e.g. wrong helper, missing call) would not be caught.

This gap is causally linked to WR-02: a naive `assert "t_ns,topic" in result.stdout` test
would FAIL because the OS-fd output never lands in `result.stdout`. Fixing WR-02 (return a
string, echo via Python) makes this branch testable.

**Fix:** After applying WR-02, add:

```python
def test_query_format_csv_streams_to_stdout(ros1_bag: Path) -> None:
    result = runner.invoke(
        app, ["query", "SELECT t_ns, topic FROM cmd_vel", str(ros1_bag), "--format", "csv"]
    )
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "t_ns,topic"
    assert "/cmd_vel" in result.stdout
```

## Info

### IN-01: `--plot ""` (empty path) silently writes a hidden `.png` and reports `Wrote `

**File:** `packages/bagq/src/bagq/cli.py:309-312`
**Issue:** `--plot` is an optional-value flag, so `--plot ""` passes the empty string (not the
sentinel). `target = ""`, `plot_table(result, "")` is called, and matplotlib's
`savefig("")` writes a hidden file named `.png` in CWD. The CLI then echoes `Wrote ` (a
blank target). Verified: a `.png` file appears with exit code 0 and a blank confirmation.
This is user error, not a security or data-loss issue, but the silent hidden-file write plus
the blank message is poor feedback.

**Fix:** Reject an empty/whitespace plot target before calling `plot_table`:

```python
if plot is not None:
    target = _PLOT_DEFAULT_FILE if plot == _PLOT_DEFAULT else plot
    if not target.strip():
        raise typer.BadParameter("--plot needs a non-empty filename (or pass it bare for plot.png)")
    plot_table(result, target)
    typer.echo(f"Wrote {target}")
    return
```

### IN-02: `--plot FILE` confirmation message is wrong when matplotlib appends an extension

**File:** `packages/bagq/src/bagq/cli.py:310-312`; `packages/rosbagger-core/src/rosbagger_core/output/plot.py:104`
**Issue:** `plot_table` passes `str(path)` straight to `fig.savefig`. When the path has no
recognized image extension, matplotlib appends `.png` (verified: `savefig(".../chart")`
writes `chart.png`). The CLI, however, echoes the *requested* target — `Wrote chart` — while
the actual file is `chart.png`. The confirmation line then names a file that does not exist.
(A path with an extension matplotlib does not support, e.g. `--plot out.csv`, raises a
`ValueError: Format 'csv' is not supported` that propagates — acceptable per the "Phase 7
owns error formatting" design, but worth noting it is a non-obvious failure mode for users.)

**Fix:** Either normalize the target to `.png` before plotting and echoing, or have
`plot_table` return the actual path written. Simplest:

```python
target = _PLOT_DEFAULT_FILE if plot == _PLOT_DEFAULT else plot
if "." not in os.path.basename(target):
    target += ".png"
plot_table(result, target)
typer.echo(f"Wrote {target}")
```

### IN-03: `to_json` raises an opaque `TypeError` on `binary`/`large_binary` columns

**File:** `packages/rosbagger-core/src/rosbagger_core/output/render.py:92-97`
**Issue:** `to_json` casts only temporal columns specially; everything else goes through
`to_pylist()` then `json.dumps`. A `pyarrow.binary()`/`large_binary()` column yields Python
`bytes`, which `json.dumps` cannot serialize (`TypeError: Object of type bytes is not JSON
serializable`). NOTE: this is NOT currently reachable through the normal query path — the
only blob in the schema (`Image.data` = `uint8[]`) materializes as `list<uint8>`, which is
JSON-serializable as a list of ints (verified: `SELECT * FROM image --format json` succeeds).
But the function makes no guard, so any future message type or backend that produces a
`binary` Arrow column would crash with an opaque error instead of a clear message. Latent
robustness gap, low priority.

**Fix (defensive):** Coerce binary columns to a JSON-safe form (hex string or list of ints)
alongside the temporal special-case, e.g.:

```python
if pa.types.is_binary(col.type) or pa.types.is_large_binary(col.type):
    cols[name] = [None if v is None else v.hex() for v in col.to_pylist()]
    continue
```

### IN-04: Suite-level coverage gate fails at 75% (not a phase-6 defect, but blocks `--cov` runs)

**File:** project test config (coverage `fail-under=80`)
**Issue:** Running the phase-6 test files alone fails the global `fail-under=80` gate (total
75.29%) because the run includes `inspect.py` (0% — its tests are not in this file set) and
partial reader/schema coverage. The phase-6 output modules themselves are at 100%. This is a
test-invocation artifact (running a subset under a whole-repo coverage gate), not a code
defect in this phase — but be aware that `pytest <phase-6 files> --cov` will report failure
even though every phase-6 line is covered. The full suite presumably clears 80%.

**Fix:** None required for phase 6. If subset runs are common, scope coverage to the changed
packages (`--cov=rosbagger_core.output --cov=bagq.cli`) or run the full suite for the gate.

---

_Reviewed: 2026-05-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
