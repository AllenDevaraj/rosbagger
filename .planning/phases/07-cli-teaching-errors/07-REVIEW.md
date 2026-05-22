---
phase: 07-cli-teaching-errors
reviewed: 2026-05-22T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - packages/bagq/src/bagq/__main__.py
  - packages/bagq/src/bagq/cli.py
  - packages/rosbagger-core/src/rosbagger_core/backend/query.py
  - packages/rosbagger-core/src/rosbagger_core/errors.py
  - packages/rosbagger-core/src/rosbagger_core/output/__init__.py
  - packages/rosbagger-core/src/rosbagger_core/output/export.py
  - packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py
  - tests/test_cli_errors.py
  - tests/test_cli_query.py
  - tests/test_errors.py
  - tests/test_offline_guard.py
  - tests/test_output_export.py
  - tests/test_query_errors.py
  - tools/make_fixtures.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-05-22
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 7 adds a stdlib-only typed-error module (`rosbagger_core/errors.py`), a
`teaching_errors` CLI wrapper, a `duckdb.BinderException` → `UnknownColumnError`
mapping in `query()`, an `AnyReaderError` "no type definitions" → `UnresolvedTypeError`
wrap at the reader boundary, and the WR-01/WR-02 export fixes. The architecture is
sound on most of its stated invariants — I verified empirically (with `PYTHONPATH=""`):

- **Offline invariant holds** — `import rosbagger_core.errors`, `import
  rosbagger_core.backend.query`, and `import bagq.cli` each leak ZERO heavy-stack
  modules (duckdb/sqlglot/pyarrow/rosbags/matplotlib). Lazy-import discipline is intact.
- **`teaching_errors` does NOT swallow real bugs** — a `KeyError` propagates as a
  traceback; only the three typed errors + `FileNotFoundError` are caught. Verified.
- **Backend lifecycle is correct on the error path** — the default backend closes via
  `finally` even on the `BinderException` re-raise; a caller-supplied backend is NOT
  closed by `query()`. Verified with a spy backend.
- **The `"no type definitions"` substring matches** the actual rosbags message
  (`'Bag contains no type definitions. Instantiate AnyReader with a default_typestore
  argument.'`); `FileNotFoundError` is never caught at the reader. Verified.
- **WR-01 (splitext basename) and WR-02 (buffered CSV, temp-file cleanup)** both work;
  CSV output has a clean single trailing newline; the temp file is unlinked.
- All 56 Phase 7 tests pass; ruff is clean.

**However**, the central new behavior — the `BinderException` → `UnknownColumnError`
mapping — has a correctness defect that the test suite does not catch: catching
`duckdb.BinderException` *by type* is too coarse, because DuckDB raises that same type
for GROUP BY / HAVING misuse (not just unknown columns). Those valid-column-but-malformed
queries are mislabeled to the user as `Unknown column '?'`, which is actively misleading.
This is the one BLOCKER. The remaining findings are robustness/quality WARNINGs and INFO.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `BinderException` is caught by type, but DuckDB raises it for non-column errors too — GROUP BY / HAVING mistakes are mislabeled as `Unknown column '?'`

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:193-198`

**Issue:** The phase intends to catch ONLY the unknown-column case, and the docstrings
assert "catch it by TYPE (robust)". But `duckdb.BinderException` is *not* specific to
unknown columns — DuckDB raises the **same exception type** for GROUP BY / HAVING errors
(and other binder-stage failures). The code maps every `BinderException` to
`UnknownColumnError`. Because the `_BINDER_COL` regex only matches the
`Referenced column "X" not found` message, these other binder errors miss the regex and
degrade the column name to `"?"`, producing a message that tells the user a column does
not exist when it does — and hides the real error.

Verified end-to-end against a real fixture bag:

```
query('SELECT "linear.x", COUNT(*) FROM cmd_vel', reader)
# raises UnknownColumnError:
#   Unknown column '?'. Columns in cmd_vel: t, t_ns, stamp, topic,
#   linear.x, linear.y, linear.z, angular.x, angular.y, angular.z
```

Here `linear.x` is a perfectly valid column; the actual error is "must appear in the
GROUP BY clause". Reporting `Unknown column '?'` is incorrect, user-facing behavior —
it actively misdirects debugging. Two distinct DuckDB messages were confirmed to take
this path: `column "a" must appear in the GROUP BY clause...` and
`column zzz must appear in the GROUP BY clause or be used in an aggregate function...`
(HAVING). The existing test (`test_query_errors.py`) only ever exercises a literally
unknown column (`nonexistent_col`), so the over-catch went undetected.

**Fix:** Narrow the re-map to *actually-unknown-column* binder errors. Match on the
message (the same regex already used to extract the name) and re-raise only when it hits;
otherwise let the original `BinderException` propagate unchanged (it is a genuine SQL
error the user should see verbatim):

```python
try:
    return backend.execute(sql)
except duckdb_binder_exception() as e:
    m = _BINDER_COL.search(str(e))
    if m is None:
        raise  # not an unknown-column error (e.g. GROUP BY/HAVING) — surface as-is
    raise UnknownColumnError(m.group(1), columns_by_table) from e
```

(If the team wants the `"?"` graceful-degradation kept for genuine unknown-column
messages that the regex somehow fails to parse, gate it on a positive
`"not found in FROM clause"` substring check instead of treating *all* `BinderException`s
as column errors.) Either way, add a test asserting a GROUP BY mistake does NOT raise
`UnknownColumnError`.

## Warnings

### WR-01: `RosbagsReader.open()` leaks the partially-opened `AnyReader` when type resolution fails

**File:** `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py:102-113`

**Issue:** `open()` constructs a local `reader = AnyReader(...)`, calls `reader.open()`
inside a `try`, and only assigns `self._reader = reader` *after* a successful open. When
`reader.open()` raises (the `UnresolvedTypeError` wrap, or any other re-raised
`AnyReaderError`), `self._reader` stays `None`, so the subsequent `close()` /
`__exit__` is a no-op and the local `reader` is never closed. For a multi-bag open where
an earlier sub-reader has already opened its sqlite/file handle before a later bag fails
type resolution, that handle can leak (no `reader.close()` is ever called on the failed
instance). Verified that `self._reader is None` after a failed open and that `close()`
becomes a no-op.

**Fix:** Close the local reader on the failure path before propagating:

```python
reader = AnyReader(self._paths, default_typestore=self._default_typestore)
try:
    reader.open()
except AnyReaderError as e:
    reader.close()  # release any partially-opened sub-reader handles
    if "no type definitions" in str(e):
        from rosbagger_core.errors import UnresolvedTypeError
        raise UnresolvedTypeError(str(e)) from e
    raise
self._reader = reader
```

(Wrap the `reader.close()` defensively if rosbags can raise on closing a not-fully-open
reader.)

### WR-02: The `"no type definitions"` substring match is brittle and could mislabel future / unrelated reader errors

**File:** `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py:106`

**Issue:** The trigger for `UnresolvedTypeError` is a bare substring test on the exception
*message* (`if "no type definitions" in str(e)`). This is the only thing distinguishing
the type-registration case from every other `AnyReaderError`. It is correct for the
current rosbags version (verified: the message is `'Bag contains no type definitions...'`),
but it is locale-/version-fragile in exactly the way the sibling `query.py` comment warns
against ("catch by TYPE, robust across locales/versions"). A wording change in a future
rosbags release silently turns CLI-04 into a generic uncaught `AnyReaderError`, OR — if
some unrelated future message happens to contain the phrase — mislabels a different
failure as a type-registration problem. Note this is the *inverse* design choice from
CR-01's "catch by type", and the asymmetry is worth a deliberate decision.

**Fix:** This is acceptable for v1 (rosbags exposes no narrower exception subclass for
this case), but harden it: anchor the match more tightly (e.g.
`"no type definitions" in str(e)` AND it is the documented `AnyReaderError`, plus a
regression test that pins the rosbags message), and add a comment that this is a
message-sniff requiring re-verification on each rosbags bump. At minimum, keep the
existing `test_def_less_bag_*` fixtures green as the canary.

### WR-03: `--plot` with no numeric columns surfaces a raw `ValueError` traceback to the user

**File:** `packages/bagq/src/bagq/cli.py:364-368` (and `output/plot.py:94-95`)

**Issue:** `plot_table()` raises a bare `ValueError("Nothing to plot: need a t/t_ns
column and >=1 numeric result column.")` when the result has no numeric column (e.g.
`bagq query "SELECT topic FROM cmd_vel" bag --plot`). The `teaching_errors` wrapper
catches only `UnknownTableError`/`UnknownColumnError`/`UnresolvedTypeError` (specific
`ValueError` subclasses) and `FileNotFoundError` — NOT a bare `ValueError`. So this
user-facing "nothing to plot" condition prints a full Python traceback instead of a clean
message. The cli docstring explicitly says this `ValueError` "PROPAGATES" by design, so
this matches stated intent — but the stated intent contradicts the phase's own goal of
"clean message + Exit(1), NEVER dump a Python traceback (the difference between a tool and
a script)." A nothing-to-plot is expected user input, not a programming bug.

**Fix:** Either (a) make `plot_table` raise a typed teaching error (a new
`NothingToPlotError(ValueError)` added to `errors.py` and to the wrapper's `except`
tuple), or (b) catch the plot-specific `ValueError`/`RuntimeError` locally in the `query`
command body and present it via `typer.secho(..., err=True); raise typer.Exit(1)`. Option
(a) is consistent with the API-first split the phase espouses.

### WR-04: `write_csv_stream` retains a `/dev/stdout` default that is the exact footgun WR-02 was created to remove

**File:** `packages/rosbagger-core/src/rosbagger_core/output/export.py:128-144`

**Issue:** `write_csv_stream(table, path="/dev/stdout")` is kept "for back-compat", but
its default value is the non-portable, CliRunner-uncapturable `/dev/stdout` path that the
whole WR-02 work exists to eliminate. The CLI no longer calls it, but it remains a public,
re-exported symbol (`output/__init__.py:41`) whose default invites a future caller to
reintroduce the Windows-breaking / capture-breaking behavior. A retained deprecated
function is fine; a retained deprecated *default that is itself the bug* is a latent trap.
The only test exercising it (`test_write_csv_stream_writes_csv_to_extensionless_target`)
passes an explicit temp path, so the dangerous default is never exercised.

**Fix:** Make the `path` argument required (drop the `/dev/stdout` default) so callers
must supply a real path, and/or emit a `DeprecationWarning` directing them to
`write_csv_to_string`. If true back-compat for the default is required, document loudly
that `/dev/stdout` is unsupported on Windows and uncapturable.

## Info

### IN-01: `UnknownColumnError` regex-miss degrades the column name to `'?'`, which is uninformative even on the legitimate path

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:196-197`,
`packages/rosbagger-core/src/rosbagger_core/errors.py:74`

**Issue:** When `_BINDER_COL` fails to parse the column out of the DuckDB message, the
error reports `Unknown column '?'`. Verified `difflib.get_close_matches("?", cols)`
returns `[]`, so no false suggestion appears — but the user sees a literal `'?'` as the
offending column. On the legitimate unknown-column path this is rare (the regex matches
the standard message), but combined with CR-01 it becomes the *common* output. Once CR-01
is fixed (so only true unknown-column messages reach this constructor), the `'?'` fallback
should essentially never fire; if it still can, consider omitting the
`Unknown column '?'.` lead line and printing only the available columns.

**Fix:** After CR-01's narrowing, the `"?"` path is mostly dead; keep it but reword to
avoid quoting a literal `?` (e.g. "A referenced column was not found." + the column list)
when the name could not be recovered.

### IN-02: Several CLI error tests assert only `exit_code != 0` without checking the message content

**File:** `tests/test_cli_query.py:114-119, 122-127`

**Issue:** `test_query_format_parquet_without_output_errors` and
`test_query_unknown_format_errors` assert only `result.exit_code != 0`. The task
emphasizes error tests should assert message content + exit code. These two do not verify
the teaching content (the parquet guard's "specify -o out.parquet" hint, or the unknown-
format "use table|csv|parquet|json" list), so a regression that changed the message to
something useless — or returned a different non-zero code for the wrong reason — would
still pass. (The typed-error tests in `test_cli_errors.py` DO assert content and are
good models.)

**Fix:** Add `assert "out.parquet" in result.output` and
`assert "table|csv|parquet|json" in result.output` (or the relevant substrings) to pin
the teaching messages.

### IN-03: No test exercises the `BinderException` over-catch (the gap that hid CR-01)

**File:** `tests/test_query_errors.py` (whole file)

**Issue:** `test_query_errors.py` tests exactly one error shape — a literally unknown
column (`nonexistent_col`/`bogus`) — and one happy path. There is no negative test
asserting that a *non*-column `BinderException` (GROUP BY / HAVING / type error) is NOT
converted to `UnknownColumnError`. This is precisely why CR-01 slipped through. Confirmed
by grep: no test references GROUP BY / HAVING / aggregate against the query path.

**Fix:** Add a test such as:
```python
def test_group_by_misuse_is_not_relabeled_as_unknown_column(ros1_bag):
    with RosbagsReader(ros1_bag) as reader, pytest.raises(Exception) as ei:
        query('SELECT "linear.x", COUNT(*) FROM cmd_vel', reader)
    assert not isinstance(ei.value, UnknownColumnError)
    assert "GROUP BY" in str(ei.value)  # the real error survives
```
This both guards CR-01's fix and documents the intended boundary.

---

_Reviewed: 2026-05-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
