---
phase: 07-cli-teaching-errors
plan: 02
subsystem: api
tags: [typer, duckdb, rosbags, difflib, errors, cli, sqlite3]

# Dependency graph
requires:
  - phase: 07-01
    provides: "teaching_errors(fn) decorator (clean message + Exit(1), no traceback) on info/tables/query, structured to widen in one import line + one except tuple"
  - phase: 05-02
    provides: "query(sql, reader) orchestrator with UnknownTableError + the try/finally backend lifecycle to wrap"
  - phase: 02-02
    provides: "RosbagsReader.open() — the single AnyReader choke point where AnyReaderError fires"
provides:
  - "stdlib-only rosbagger_core/errors.py: UnknownTableError (re-exported), UnknownColumnError, UnresolvedTypeError — all ValueError subclasses carrying their data"
  - "CLI-02: difflib did-you-mean on UnknownTableError (suggestion when a close table exists, else available-tables list)"
  - "CLI-03: duckdb.BinderException caught in query() -> UnknownColumnError listing all referenced tables' columns grouped by table"
  - "CLI-04: no-type-definitions AnyReaderError wrapped to UnresolvedTypeError at the reader boundary (surfaces via info/tables/query) with .msg/.idl registration guidance"
  - "tools.make_fixtures.write_def_less_bag — ROS2 sqlite bag with message_definitions stripped (the CLI-04 test fixture)"
affects: [08-packaging-docs-release]

# Tech tracking
tech-stack:
  added: []  # no new packages — difflib/re/sqlite3 are stdlib; duckdb/rosbags already locked
  patterns:
    - "Typed, framework-free ValueError subclasses CARRY domain data (suggestions, columns-by-table, guidance); the CLI only presents (API-first)"
    - "Catch a library exception by TYPE (duckdb.BinderException), parse its message ONLY for the offending name; lazy-import the library inside the except so the module top stays offline-light"
    - "Wrap a library error at the boundary where its meaning is unambiguous (reader open()), matching ONLY the specific substring so sibling errors propagate"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/errors.py
    - tests/test_errors.py
    - tests/test_query_errors.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/backend/query.py
    - packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py
    - packages/bagq/src/bagq/cli.py
    - tools/make_fixtures.py
    - tests/test_offline_guard.py
    - tests/test_cli_errors.py

key-decisions:
  - "errors.py defines ALL three typed errors in one stdlib-only module (difflib only); UnknownTableError canonical home moved here, re-exported from backend/query.py so the class identity is preserved"
  - "duckdb_binder_exception() helper isolates the lazy `import duckdb` so the BinderException catch never forces duckdb at module top (offline invariant); the catch sits INSIDE the existing try/finally so the default backend still close()s on the error path"
  - "Reader wrap matches the SPECIFIC 'no type definitions' substring; mixed-format AnyReaderError re-raises and FileNotFoundError is never caught (Pitfall 3 — not mislabeled)"
  - "write_def_less_bag uses ROS2 sqlite (the only rosbags-writable format where defs are separable) + stdlib sqlite3 DELETE FROM message_definitions"

patterns-established:
  - "Data-carrying typed errors: each ValueError subclass stores structured attributes (.name/.available/.suggestions, .column/.columns_by_table, .detail) AND builds the plain-text teaching message in core"
  - "Offline-light error mapping: library exceptions wrapped where the library is ALREADY imported (query() body, reader), errors.py imports only difflib (offline guard extended to cover it)"

requirements-completed: [CLI-02, CLI-03, CLI-04]

# Metrics
duration: 6min
completed: 2026-05-22
---

# Phase 7 Plan 2: Teaching Errors Summary

**Three errors-that-teach over 07-01's clean-exit mechanism: a stdlib-only `errors.py` whose `ValueError` subclasses carry did-you-mean table suggestions (CLI-02), the referenced tables' columns from a caught `duckdb.BinderException` (CLI-03), and `.msg`/`.idl` registration guidance wrapped around the reader's no-type-definitions `AnyReaderError` (CLI-04) — presented by a one-line-widened CLI wrapper.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-22T17:52:05Z
- **Completed:** 2026-05-22T17:58:47Z
- **Tasks:** 3
- **Files modified:** 9 (3 created, 6 modified)

## Accomplishments

- **`rosbagger_core/errors.py`** (stdlib-only, `difflib`): `UnknownTableError` (re-exported from `backend/query.py`, identity preserved), `UnknownColumnError`, and `UnresolvedTypeError` — all `ValueError` subclasses carrying their structured data and building plain-text teaching messages. Offline guard extended to prove the module pulls no duckdb/sqlglot/pyarrow and no rosbags.
- **CLI-02 (did-you-mean):** `UnknownTableError(name, available)` computes `difflib.get_close_matches(..., cutoff=0.6)` — a "Did you mean: cmd_vel?" line when a close table exists, else the available-tables list, else a no-tables note. `query()` raise site now passes `(table, sorted(available))`.
- **CLI-03 (column list):** `query()` accumulates `columns_by_table` during the load loop, then catches `duckdb.BinderException` (by TYPE) around `backend.execute(sql)`, parses the offending column via a `_BINDER_COL` regex, and raises `UnknownColumnError` listing all referenced tables' columns grouped by table. The catch sits inside the existing `try/finally`, so the default backend still closes on the error path; a valid query is unaffected.
- **CLI-04 (registration guidance):** `RosbagsReader.open()` wraps ONLY the "no type definitions" `AnyReaderError` into `UnresolvedTypeError` (cause preserved); other `AnyReaderError` and `FileNotFoundError` propagate unchanged. Surfaces identically through `bagq info` / `tables` / `query`. Added `tools.make_fixtures.write_def_less_bag` (ROS2 sqlite bag, `message_definitions` stripped via stdlib `sqlite3`) as the fixture.
- **CLI presentation:** `teaching_errors` widened in one line — imports all three from `rosbagger_core.errors` and catches them in one `except (...)` tuple. No bare `except Exception` (Pitfall 4 — the 07-01 KeyError test still proves real bugs surface).

## Task Commits

Each task was committed atomically:

1. **Task 1: errors.py + did-you-mean UnknownTableError (CLI-02)** - `1699f4e` (feat)
2. **Task 2: BinderException -> UnknownColumnError in query() (CLI-03)** - `62fc4ae` (feat)
3. **Task 3: UnresolvedTypeError at reader boundary + def-less fixture + widen CLI (CLI-04)** - `2d30a05` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/errors.py` - **Created.** Stdlib-only typed errors: `UnknownTableError`/`UnknownColumnError`/`UnresolvedTypeError`, each carrying data + a teaching message.
- `packages/rosbagger-core/src/rosbagger_core/backend/query.py` - Imports/re-exports `UnknownTableError` from `errors`; `_BINDER_COL` regex; load loop accumulates `columns_by_table`; `execute` wrapped in `except duckdb.BinderException -> UnknownColumnError`; `duckdb_binder_exception()` lazy-import helper.
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` - `open()` wraps the no-type-definitions `AnyReaderError` -> `UnresolvedTypeError` (cause preserved); other errors propagate (`AnyReaderError` import added).
- `packages/bagq/src/bagq/cli.py` - `teaching_errors` widened: imports all three errors from `rosbagger_core.errors`, catches them in one tuple.
- `tools/make_fixtures.py` - Added `write_def_less_bag` (+ `sqlite3` / `get_types_from_msg` imports, `_CUSTOM_MSG` constant).
- `tests/test_errors.py` - **Created.** Unit assertions for all three errors (message content, carried attributes, ValueError, re-export identity).
- `tests/test_query_errors.py` - **Created.** Fixture-backed: bad column -> `UnknownColumnError` listing cmd_vel cols; valid query still returns 3 rows.
- `tests/test_offline_guard.py` - Added `test_import_errors_does_not_pull_heavy_query_stack` + `test_import_errors_does_not_pull_rosbags`.
- `tests/test_cli_errors.py` - Added CLI-02/03/04 tests (CLI-04 parametrized across info/tables/query) + `def_less_bag` fixture + reader-level FileNotFoundError-propagates test.

## Decisions Made

- **All three errors in one `errors.py`:** Task 1's write defined `UnknownColumnError` and `UnresolvedTypeError` alongside `UnknownTableError` (Tasks 2/3 add them to the same module per the plan) — cleaner than three sequential edits, and the offline/isinstance behavior is identical. Per-task commits scope by the tests each exercises.
- **`duckdb_binder_exception()` helper:** keeps the lazy `import duckdb` inside a function so the BinderException catch never forces duckdb at `query.py`'s module top (offline invariant). The catch is nested inside the existing `try/finally` so `close()` still runs on the error path.
- **Specific-substring reader wrap:** only `"no type definitions"` is wrapped; mixed-format `AnyReaderError` re-raises and `FileNotFoundError` is never caught (Pitfall 3). Verified end-to-end before writing CLI tests (def-less bag raises `UnresolvedTypeError`; `/no/such/bag` raises `FileNotFoundError`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, test-only] No-traceback assertion: `result.exception is None` -> `isinstance(result.exception, SystemExit)`**
- **Found during:** Task 3 (CLI-02/03/04 CliRunner tests)
- **Issue:** The plan's `<behavior>` and the new CLI tests asserted `result.exception is None` for the clean-exit path. A clean `typer.Exit(1)` surfaces to CliRunner as `SystemExit(1)`, NOT `None` (07-RESEARCH §6; already established by the 07-01 `test_unknown_table_exits_one_with_clean_message` test and the 07-01 SUMMARY deviation). The five new tests failed on this assertion even though exit code 1 and the teaching message were both correct.
- **Fix:** Replaced `assert result.exception is None` with `assert isinstance(result.exception, SystemExit)` + `assert not isinstance(result.exception, ValueError)` (proving the domain error did not leak as a traceback), matching the verified 07-01 pattern. Production code unchanged.
- **Files modified:** tests/test_cli_errors.py
- **Verification:** All 5 tests pass; full suite 254 passed at 97.82%.
- **Committed in:** `2d30a05` (Task 3 commit)

**2. [Rule 3 - Blocking, lint] ruff isort reordered the after-sys.path import block in test_cli_errors.py**
- **Found during:** Task 3
- **Issue:** Adding `from rosbagger_core.reader import RosbagsReader` to the post-`sys.path` imports tripped ruff `I001` (unsorted block); `ruff format` alone does not reorganize imports.
- **Fix:** Ran `ruff check --fix` to organize the block (ruff grouped `rosbagger_core` with the `bagq` third-party imports, distinct from the repo-root `tools` import — matching the established convention in test_reader.py / test_cli_query.py).
- **Files modified:** tests/test_cli_errors.py
- **Verification:** `ruff check .` + `ruff format --check .` both clean.
- **Committed in:** `2d30a05` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 test-only bug, 1 lint/blocking). Both are test/lint-only — no production-code or scope change.
**Impact on plan:** All three requirements (CLI-02/03/04) delivered exactly as specified. The `result.exception is None` correction aligns the new tests with the codebase's verified CliRunner behavior (the same correction 07-01 already made).

## Issues Encountered

- The def-less-bag fixture is a load-bearing research assumption (A3): verified directly (`write_def_less_bag` -> `UnresolvedTypeError` at `open()` with the `AnyReaderError` cause; `/no/such/bag` -> `FileNotFoundError`) before building the CliRunner tests on top of it. Both behaviors confirmed.

## User Setup Required

None - no external service configuration required. No new packages added (difflib/re/sqlite3 are stdlib; duckdb/rosbags already locked).

## Next Phase Readiness

- **Phase 7 COMPLETE (2/2).** All CLI-01..04 delivered: clean-exit mechanism (07-01) + the three errors-that-teach (07-02). `bagq query`/`info`/`tables` surface clean teaching messages with exit 1 and no traceback.
- Full suite 254 passed at 97.82% coverage (≥80% gate); `errors.py` 100%; ruff format-check + lint clean; offline guard 7/7 (errors.py covered for heavy-stack AND rosbags).
- Ready for **Phase 8** (Packaging, Docs & Release): pip-installable v0.1, offline-import check, README/usage, version tag.

## Self-Check: PASSED

- Created files exist: `errors.py`, `tests/test_errors.py`, `tests/test_query_errors.py` — all FOUND.
- Task commits exist: `1699f4e`, `62fc4ae`, `2d30a05` — all FOUND.

---
*Phase: 07-cli-teaching-errors*
*Completed: 2026-05-22*
