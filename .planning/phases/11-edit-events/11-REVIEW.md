---
phase: 11-edit-events
reviewed: 2026-05-23T09:52:11Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - packages/rosbagger-core/src/rosbagger_core/edit/__init__.py
  - packages/rosbagger-core/src/rosbagger_core/edit/operations.py
  - packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py
  - packages/rosbagger-core/src/rosbagger_core/edit/convert.py
  - packages/rosbagger-core/src/rosbagger_core/events.py
  - packages/rosbagger-core/src/rosbagger_core/backend/query.py
  - packages/bagq/src/bagq/cli.py
  - tests/test_edit.py
  - tests/test_cli_edit.py
  - tests/test_events.py
  - tests/test_cli_events.py
  - tests/test_backend_query.py
  - tests/test_offline_guard.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-05-23T09:52:11Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 11 adds a streaming bag-edit pipeline (`edit/`), cross-format convert via the
`rosbags` migration factory, an event Parquet sidecar (`events.py`), and the reserved
`events`-table hook in the query orchestrator, plus thin `bagq edit`/`convert`/`events`
CLI verbs. The whole suite passes (85 edit/CLI/query tests, 15 events tests; verified by
running them) and the project-specific invariants the implementation set out to satisfy
mostly hold under direct probing:

- **Offline-import invariant:** verified by spawning fresh interpreters —
  `import rosbagger_core.edit` and `import rosbagger_core.events` pull in neither the heavy
  stack nor `rosbags`; `backend.query` stays light. No new eager heavy import found.
- **Don't-hand-roll convert:** `convert.py` delegates entirely to
  `rosbags.convert.converter.is_same_wireformat` / `generate_message_converter` (signatures
  confirmed against the installed `rosbags`); no hand-rolled deserialize→reserialize.
- **Raw-copy correctness:** drop removes orphan connections, downsample counters are
  per-topic over the merged stream, relative-time trim and multi-bag merge ordering work,
  the mixed-format-merge error propagates. Connection-object identity stability (the
  `id(conn)` keying) was empirically confirmed across all three formats.
- **Trusted-output boundary:** the events sidecar reuses `output/export.py`'s
  quote-escaped DuckDB `COPY`; it builds no new SQL literal. The schema round-trips through
  `COPY` without int64/string drift (verified). `sidecar_path` is file-vs-dir-aware and
  survives dotted directory names.

The defects below are concentrated in **boundary behavior the tests do not cover**: a
reserved-name collision that silently hides a real `/events` topic (Critical), and several
robustness/UX gaps where unusual-but-reachable inputs produce raw tracebacks, silent
empty results, or unreadable output bags. None of the happy-path correctness claims were
falsified; every finding is a gap the existing tests step around.

## Critical Issues

### CR-01: A real topic named `/events` is silently shadowed by the reserved sidecar table

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:266-267`
**Issue:** The reserved-name hook computes `events_referenced = _EVENTS_TABLE in tables`
and unconditionally subtracts `events` from topic resolution. But a real bag topic named
`/events` sanitizes (via `TableNameResolver`/`sanitize_table_name`) to the table name
`events` — so any bag that publishes an `/events` topic has that topic **silently replaced
by the event sidecar relation**. The user's real data becomes unreachable with no error.

Confirmed empirically: a ROS 2 bag with a 3-message `/events` topic, queried via
`SELECT * FROM events`, returns **0 rows with the sidecar's 4-column schema**
(`t_start_ns, t_end_ns, label, note`) instead of the 3 Twist rows. The topic's data is
completely invisible and no `UnknownTableError` or warning fires. `/events` is a plausible
real topic name in robotics bags (diagnostics/event streams), so this is a data-access
correctness failure, not a theoretical edge.

**Fix:** Only treat `events` as the reserved sidecar when no real topic maps to it (the
`table_to_topic` map is already built at line 204, well before this point):
```python
# Step 5b — the reserved `events` table (D-14). A REAL topic that sanitizes to
# `events` (e.g. a published `/events` topic) takes precedence over the sidecar so
# its data is never silently hidden; only when no topic owns the name is `events`
# the reserved sidecar.
events_is_real_topic = _EVENTS_TABLE in table_to_topic
events_referenced = _EVENTS_TABLE in tables and not events_is_real_topic
data_tables = tables - ({_EVENTS_TABLE} if events_referenced else set())
```
With this, a real `/events` topic resolves and loads normally; the sidecar is reserved
only when the name is otherwise unclaimed. (Add a regression test: a bag with an `/events`
topic must return that topic's rows from `SELECT * FROM events`.)

## Warnings

### WR-01: `bagq edit`/`convert` to an existing output path dumps a raw `WriterError` traceback

**File:** `packages/bagq/src/bagq/cli.py:658-661` (and `695-698` for `convert`)
**Issue:** When the destination bag already exists, `rosbags`' Writer raises
`WriterError("<path> exists already, not overwriting.")`. That exception is **not** a
`ValueError`, so the `except ValueError` in the `edit`/`convert` body does not catch it,
and it is **not** in the `@teaching_errors` known-error tuple either. Result: re-running
`bagq edit src.bag -o out.bag` (an extremely common mistake) surfaces a full Python
traceback. Verified via CliRunner: `result.exception` is a `WriterError`, exit code 1,
with a traceback rather than a clean message — exactly the "tool vs. script" failure the
`teaching_errors` design explicitly set out to prevent.
**Fix:** Catch the rosbags `WriterError` (and/or `FileExistsError`) at the CLI boundary and
map it to a clean message. Either widen the `except` in the command bodies:
```python
from rosbags.interfaces import WriterError  # or rosbags.rosbag2 / rosbag1 WriterError
try:
    n = edit_bag(srcs, out, ops, fmt=fmt)
except ValueError as e:
    raise typer.BadParameter(str(e)) from None
except WriterError as e:
    typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1) from None
```
or have `edit_bag` pre-check `dst.exists()` and raise a `ValueError` with a clean
"output already exists; choose a new path or remove it" message (the `ValueError` path is
already mapped to `BadParameter`). Add a CLI test asserting a clean non-zero exit (no
`result.exception`) when `-o` points at an existing bag.

### WR-02: A backwards trim window (`start > end`) is accepted and silently produces an empty bag

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/operations.py:90-103`
**Issue:** `EditOps.__post_init__` validates drop/keep mutual exclusion and downsample
positivity, but never checks `trim[0] <= trim[1]`. `EditOps(trim=(5.0, 1.0))` is accepted
and `trim_window_ns` returns the inverted window `(5e9, 1e9)`, for which
`lo <= t_ns <= hi` is never true — so `edit_bag` silently writes an empty bag and reports
`0`. A user who transposes the two arguments (`--trim 5 1`) gets a valid-but-empty output
with no diagnostic. Confirmed: the inverted window is returned without complaint.
**Fix:** Reject a backwards window at construction (defense-in-depth alongside the existing
checks), so the CLI maps it to a clean `BadParameter`:
```python
if self.trim is not None and self.trim[0] > self.trim[1]:
    raise ValueError(
        f"trim window start ({self.trim[0]}) must be <= end ({self.trim[1]})."
    )
```

### WR-03: Contradictory `--format` + suffix produces an unreadable output bag

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py:60-103`
**Issue:** `dst_is_ros2`/`make_writer` let an explicit `fmt` override the suffix, but never
flag a contradiction between them. `edit_bag(src, "out.bag", fmt="sqlite3")` writes a ROS 2
sqlite **directory literally named `out.bag/`** (containing `out.bag.db3` + `metadata.yaml`).
Re-opening that output fails: `AnyReader` sees the `.bag` suffix, treats the directory as a
ROS 1 file, and raises `AnyReaderError: ... Is a directory.`. Confirmed empirically — the
edit returns `n=9` "successfully" but the artifact it produced cannot be read back. The
inverse (`fmt="ros1"` with a `.mcap`/dir suffix) is the same class of footgun.
**Fix:** When `fmt` is explicit, validate it against the suffix and reject (or at minimum
warn on) a contradiction — e.g. `fmt in {"mcap","sqlite3"}` with a `.bag` suffix, or
`fmt=="ros1"` with a `.mcap` suffix / a directory dst. Raising `ValueError` routes through
the CLI's clean `BadParameter` mapping.

### WR-04: Multi-bag `events` query silently reads only the first bag's sidecar

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:332`
**Issue:** `backend.register_table(_EVENTS_TABLE, list_events(reader.paths[0]))` hard-codes
`paths[0]`. `RosbagsReader` happily accepts a list of bags (the merge path), and `query()`
runs fine over a merged reader — but only the **first** bag's `<bag>.events.parquet` is
read; sidecars on the other merged bags are silently ignored. Confirmed: with a merged
reader `[a, b]` where only `b` has an event, `SELECT * FROM events` returns 0 rows. The
docstring calls multi-bag events "deferred," but the behavior is a silent partial result,
not a clear refusal — a user merging bags for a query has no signal their `b`-side events
were dropped.
**Fix:** Either (a) when `len(reader.paths) > 1` and `events` is referenced, raise a clear
error ("event queries are single-bag in v1; query one bag at a time"), or (b) concat the
sidecars across `reader.paths`. Option (a) matches the documented v1 scope while removing
the silent-data-loss surprise.

### WR-05: `edit`/`convert` does not carry the event sidecar to the output bag

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py:122-250`
**Issue:** `edit_bag` copies bag messages only; it never propagates an existing
`<src>.events.parquet` sidecar to `<dst>.events.parquet`. So `bagq edit run.bag -o trimmed.bag`
(or `convert`) produces an output whose `events` table is empty even when the source had
annotated events — the user's events are effectively lost relative to the new bag. This is
a data-continuity gap that interacts with the sidecar design (events "travel with the bag",
per `events.py`'s module docstring) — after an edit they no longer do.
**Fix:** If this is intended v1 scope, document it explicitly in the `edit`/`convert`
docstrings and CLI help ("events sidecars are not copied"). Otherwise, copy/translate the
sidecar after a successful write (translating timestamps when `--trim` shifts the
relative-time origin, which it does not today — trim keeps absolute ns, so a straight copy
is correct for trim/drop/downsample/merge; only document the convert case).

### WR-06: Truncating float→ns conversion can drop a boundary message on the trim edge

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/operations.py:101-102`
**Issue:** `lo = start_ns + int(start_s * 1e9)` and `hi = start_ns + int(end_s * 1e9)` use
`int()` (truncation toward zero) on a float product. For seconds values that are not exactly
representable (e.g. a user passing `--trim 0.0 0.3` where `0.3` is the classic
`0.299999...`/`0.3000...4` float), the truncated ns bound can land one ns short of the
intended inclusive edge, silently excluding a message whose timestamp sits exactly on the
boundary. The fixtures (`0.1`, `0.2`) happen to be exact, so the tests never exercise an
inexact bound. This is a latent off-by-one on the inclusive window edge.
**Fix:** Round rather than truncate for the window bounds, e.g.
`lo = start_ns + round(start_s * 1e9)` / `hi = start_ns + round(end_s * 1e9)`, so a bound
intended to be inclusive is not nudged inward by float error. (Document the rounding so the
behavior is predictable.)

## Info

### IN-01: `_validate_fmt` is called twice on the same `edit_bag` path

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py:69, 89`
**Issue:** `edit_bag` → `dst_is_ros2(dst, fmt)` calls `_validate_fmt(fmt)`, then
`make_writer(dst, fmt)` calls `_validate_fmt(fmt)` again on the same value. Harmless (the
check is cheap and idempotent), but redundant. Minor.
**Fix:** Acceptable as defense-in-depth; if tidying, validate once in `edit_bag` and note
the helpers assume a pre-validated `fmt`.

### IN-02: Downsample-vs-trim ordering ("every Nth of the post-trim stream") is undocumented

**File:** `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py:230-241`
**Issue:** The trim check (`continue`) precedes the downsample counter increment, so the
every-Nth count is over the **post-trim** stream, not the whole topic. Confirmed:
`trim=(0.05,0.25)` + `downsample={'/imu':2}` keeps only the first post-trim `/imu` message.
This is a reasonable semantic, but `EditOps.downsample`'s docstring ("keep every Nth message
of that topic") does not state it is post-trim, and no test pins the interaction — a future
refactor could flip the order without detection.
**Fix:** Document the post-trim semantics on `downsample`/`downsample_factor` and add a test
asserting the trim+downsample interaction so the ordering is locked.

### IN-03: `events add` accepts negative/`end < start` times without validation

**File:** `packages/bagq/src/bagq/cli.py:720-765`, `packages/rosbagger-core/src/rosbagger_core/events.py:98-154`
**Issue:** `events_add` converts `--start`/`--end` seconds to ns and stores them with no
check that `end >= start` (or that times are non-negative). An inverted or negative span is
written verbatim; a later `BETWEEN e.t_start_ns AND e.t_end_ns` interval join against an
inverted span simply matches nothing, silently. Low impact (the sidecar is the user's own
annotation), but a transposed `--start`/`--end` produces a silently inert event.
**Fix:** Validate `end >= start` in `add_event` (raise `ValueError`, mapped cleanly by the
CLI), mirroring the trim-window fix in WR-02.

### IN-04: `events list` / `_render_events` collapse "no sidecar" and "empty sidecar" into one message

**File:** `packages/bagq/src/bagq/cli.py:792-813`
**Issue:** `_render_events` prints "no events" for any 0-row table, so a bag that has never
been annotated and a bag whose sidecar exists but is empty are indistinguishable to the
user. Cosmetic, but a user who just ran `events add` and sees "no events" (e.g. because the
sidecar landed at an unexpected path) gets no hint that a file exists. Minor.
**Fix:** Optional — distinguish the two by checking `sidecar_path(bag).exists()` and
printing e.g. "no events (no sidecar found)" vs. "no events (sidecar is empty)".

---

_Reviewed: 2026-05-23T09:52:11Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
