---
phase: 07-cli-teaching-errors
plan: 01
subsystem: cli
tags: [typer, click, duckdb, csv, error-handling, teaching-errors, portability]

# Dependency graph
requires:
  - phase: 05-query-engine
    provides: "query(sql, reader) + UnknownTableError (the first typed error the wrapper catches)"
  - phase: 06-output-formats
    provides: "output/export.py (_copy_to COPY core + T-06-01 escape), write_table, write_csv_stream, the bagq query --format csv routing"
provides:
  - "teaching_errors(fn) decorator in bagq/cli.py — the shared CLI-01 clean-exit MECHANISM (catch known typed errors -> one-line message + Exit(1), no traceback)"
  - "@teaching_errors applied to info / tables / query"
  - "rosbagger_core.output.write_csv_to_string — portable buffered CSV (temp file -> read-back -> unlink), CliRunner-capturable, no /dev/stdout (WR-02 fixed)"
  - "WR-01 fix: write_table extension parse via os.path.splitext(os.path.basename(path))"
  - "bagq/__main__.py — python -m bagq runs the same app (PATH-independent smoke entry)"
affects: [07-02-teaching-errors]

# Tech tracking
tech-stack:
  added: []  # no new packages — difflib/os/tempfile are stdlib; typer/duckdb already locked
  patterns:
    - "Shared @teaching_errors decorator (functools.wraps) catching ONLY the known typed-error set + FileNotFoundError; structured so 07-02 widens the catch in one line"
    - "Portable buffered writer (write_csv_to_string) instead of /dev/stdout COPY; CLI echoes via typer.echo for CliRunner-capturable, OS-portable output"

key-files:
  created:
    - packages/bagq/src/bagq/__main__.py
    - tests/test_cli_errors.py
  modified:
    - packages/bagq/src/bagq/cli.py
    - packages/rosbagger-core/src/rosbagger_core/output/export.py
    - packages/rosbagger-core/src/rosbagger_core/output/__init__.py
    - tests/test_output_export.py
    - tests/test_cli_query.py

key-decisions:
  - "teaching_errors catches ONLY UnknownTableError + FileNotFoundError (no bare except Exception) — a monkeypatched KeyError test proves real bugs still surface as a traceback (Pitfall 4)"
  - "A clean typer.Exit(1) surfaces to CliRunner as SystemExit (NOT None) — the no-traceback assertion checks isinstance(exception, SystemExit) and that the raw UnknownTableError (ValueError) did NOT escape"
  - "Added bagq/__main__.py so the real-shell smoke uses `python -m bagq` (PATH-independent) per the plan's preferred form, rather than shutil.which('bagq')"
  - "write_csv_stream RETAINED for back-compat (its /dev/stdout default marked superseded); the CLI now routes --format csv through write_csv_to_string"
  - "New WR-01/WR-02 export tests added to the existing tests/test_output_export.py (not a new tests/test_export.py) to keep one export-test file"

patterns-established:
  - "07-02 widens the teaching CONTENT by adding new typed errors to ONE import + ONE except tuple in teaching_errors (mechanism unchanged)"
  - "Buffered-writer-in-core / echo-in-CLI keeps duckdb out of cli.py (offline invariant) while making output CliRunner-capturable + portable"

requirements-completed: [CLI-01]

# Metrics
duration: 9min
completed: 2026-05-22
---

# Phase 7 Plan 01: CLI Finalization & Clean Error Exits Summary

**A shared `teaching_errors` decorator makes `bagq query`/`info`/`tables` fail with a one-line message + exit 1 (never a traceback), plus a portable buffered `write_csv_to_string` (no `/dev/stdout`) and a basename-scoped `-o` extension parse (WR-01/WR-02 fixed).**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-05-22T17:38:00Z
- **Completed:** 2026-05-22T17:47:16Z
- **Tasks:** 2 (both TDD: RED tests written first, then implementation)
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- **Clean error-exit mechanism (CLI-01, the load-bearing add):** `teaching_errors(fn)` in `cli.py` catches the KNOWN typed set (`UnknownTableError`) + `FileNotFoundError`, prints via `typer.secho(..., err=True)`, and `raise typer.Exit(1)` — no Python traceback. Applied to `info`/`tables`/`query`. A monkeypatched `KeyError` test proves a genuine bug is NOT swallowed (it still surfaces). The wrapper is structured so 07-02 widens the catch with one import line + one `except` name.
- **WR-02 portability fix:** `rosbagger_core.output.write_csv_to_string(table) -> str` buffers the DuckDB `COPY` to a `tempfile.mkstemp` file, reads it back as UTF-8, and unlinks in a `finally` (no leak, no `/dev/stdout`). The CLI routes `--format csv` (no `-o`) through it via `typer.echo(..., nl=False)` — now CliRunner-capturable and OS-portable. Reuses `_copy_to` so the T-06-01 quote-escape stays the single SQL-literal boundary; LIST columns render bracketed (DuckDB COPY, not pyarrow.csv).
- **WR-01 robustness fix:** `write_table` parses the extension via `os.path.splitext(os.path.basename(path))[1].lstrip(".").lower()` instead of a whole-path `rsplit(".", 1)` — a dotted parent dir (`/home/u/v1.2/results/output`) no longer misfires, and `.../2024.05.21/run.csv` correctly selects CSV.
- **CLI-01 confirmed end-to-end:** a real-shell `subprocess.run([sys.executable, "-m", "bagq", "query", ...])` smoke returns exit 0 with a `/cmd_vel` row in real stdout; `bagq/__main__.py` enables `python -m bagq`.

## Task Commits

Each task was committed atomically (both TDD — RED tests + GREEN implementation in one commit each):

1. **Task 1: WR-01 + WR-02 fixes in output/export.py** - `e2119af` (fix)
2. **Task 2: teaching_errors wrapper + portable --format csv route** - `09fa1c3` (feat)

**Plan metadata:** (this SUMMARY + STATE.md + ROADMAP.md) — see the final `docs(07-01)` commit.

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/output/export.py` - Added `write_csv_to_string` (portable buffered CSV); WR-01 `splitext(basename)` extension parse in `write_table`; `write_csv_stream` docstring marks `/dev/stdout` superseded (function kept for back-compat).
- `packages/rosbagger-core/src/rosbagger_core/output/__init__.py` - Re-export `write_csv_to_string` (+ `__all__`); updated module docstring.
- `packages/bagq/src/bagq/cli.py` - `teaching_errors` decorator; `@teaching_errors` on `info`/`tables`/`query`; `--format csv` routed through `write_csv_to_string` + `typer.echo`; `import functools`.
- `packages/bagq/src/bagq/__main__.py` - NEW: `python -m bagq` runs the typer app (PATH-independent smoke entry).
- `tests/test_output_export.py` - Added `write_csv_to_string` tests (header+rows, bracketed-LIST, no-temp-leak) and WR-01 tests (dotted-parent raises, date-dir selects CSV).
- `tests/test_cli_query.py` - Added the now-capturable `--format csv` stdout test.
- `tests/test_cli_errors.py` - NEW: unknown-table clean Exit(1); KeyError NOT swallowed; real-shell smoke; wrapper-applied-to-all-three.

## Decisions Made

- **Catch set is exactly `{UnknownTableError, FileNotFoundError}`** — no bare `except Exception`; the KeyError test enforces that real bugs still traceback (07-RESEARCH Pitfall 4).
- **`bagq/__main__.py` over `shutil.which("bagq")`** for the smoke test — `sys.executable -m bagq` is interpreter-correct and PATH-independent (the plan allowed either; this matches its preferred phrasing).
- **`write_csv_stream` kept** (not deleted) per the plan; only its `/dev/stdout` default is superseded by `write_csv_to_string`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RED test asserted `result.exception is None`; corrected to the verified `SystemExit` clean-exit signal**
- **Found during:** Task 2 (teaching_errors wrapper)
- **Issue:** The first-drafted unknown-table test asserted `result.exception is None` to mean "no traceback". A clean `typer.Exit(1)` actually surfaces to CliRunner as `SystemExit(1)` (verified empirically this session and noted in 07-RESEARCH §6) — so the assertion failed for the wrong reason while the behavior was correct (clean message, no domain-error traceback).
- **Fix:** Assert `isinstance(result.exception, SystemExit)` AND `not isinstance(result.exception, ValueError)` (the raw `UnknownTableError` is a `ValueError`, so this proves it did not escape). This is a strictly better expression of "no leaked traceback" and contrasts cleanly with the KeyError test (where the exception IS the raw `KeyError`).
- **Files modified:** tests/test_cli_errors.py
- **Verification:** `tests/test_cli_errors.py` 5/5 pass; the KeyError-not-swallowed test still distinguishes a real bug from a clean exit.
- **Committed in:** `09fa1c3` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 test-correctness bug). No production-code deviations.
**Impact on plan:** Minor. The fix makes the no-traceback assertion match the verified runtime contract; no scope change. Two doc-vs-file notes (below) are not deviations — they are the plan's own escape hatches taken.

## Issues Encountered

- **`python -m bagq` was not runnable** (no `__main__.py`; only the `bagq` console script existed). The plan anticipated this ("if `-m bagq` is unsupported, invoke via `shutil.which('bagq')`"); resolved by adding `bagq/__main__.py` so the preferred `python -m bagq` smoke form works.
- **Plan `files_modified` listed `tests/test_export.py`** but the established export-test file is `tests/test_output_export.py` (and the task's `<read_first>` references that file). Added the new WR-01/WR-02 tests there to keep a single export-test file rather than splitting into a near-duplicate `tests/test_export.py`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **07-02 (Teaching Errors) is unblocked:** the shared `teaching_errors` mechanism is in place. 07-02 widens it by adding `UnknownColumnError` / `UnresolvedTypeError` to the one lazy import + the one `except (...)` tuple in the wrapper, and enriches `UnknownTableError` with did-you-mean content. No structural change to `cli.py` needed.
- `--format csv` is now CliRunner-capturable and OS-portable; the `-o` extension parse is robust on dotted-parent / date-dir paths.
- Full suite 229 passed at 97.81% coverage (≥80% gate); ruff format-check + lint clean; offline guard 5/5; real-shell smoke green.

## Self-Check: PASSED

All created/modified files exist on disk; both task commits (`e2119af`, `09fa1c3`) are in git history. Full suite 229 passed at 97.81% (≥80% gate); ruff format-check + lint clean; offline guard 5/5.

---
*Phase: 07-cli-teaching-errors*
*Completed: 2026-05-22*
