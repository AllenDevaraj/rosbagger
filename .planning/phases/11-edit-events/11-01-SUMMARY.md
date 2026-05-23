---
phase: 11-edit-events
plan: 01
subsystem: edit
tags: [rosbags, anyreader, writer, raw-copy, trim, downsample, merge, mcap, ros1, ros2, offline]

# Dependency graph
requires:
  - phase: 02-reader
    provides: RosbagsReader/AnyReader raw (connection, t_ns, rawdata) stream, connections, typestore, start_time, multi-bag merge (READ-05)
  - phase: 07-teaching-errors
    provides: UnresolvedTypeError teaching error + the no-defs AnyReaderError re-raise pattern in RosbagsReader.open()
  - phase: 01-foundation
    provides: tools/make_fixtures.py proven rosbags Writer pattern (ros1/ros2-sqlite3/mcap) + the 3-format fixture corpus
provides:
  - rosbagger_core.edit subpackage (operations.py + pipeline.py + __init__.py) — the streaming same-format bag-edit engine
  - edit_bag(srcs, dst, ops, *, fmt=None) — AnyReader -> filter -> rosbags Writer driver returning the written message count
  - EditOps — validated trim/drop/keep/downsample(+global) spec with drop/keep mutual exclusion and positive-N validation
  - make_writer(dst, fmt) — output-format Writer selection (is2 = dst.suffix != '.bag', version=9 for ROS2)
  - SC1 raw-copy half proven: trim/drop/keep/downsample/merge outputs re-open AND deserialize across ROS1 + ROS2-sqlite3 + MCAP
affects: [11-02-convert, 11-edit-events, bagq-cli]

# Tech tracking
tech-stack:
  added: []  # zero new dependencies — reuses the locked rosbags 0.11.2 Writer/AnyReader
  patterns:
    - "Streaming raw-copy edit: re-register kept connections once (no orphans), write rawdata losslessly (no decode/re-encode)"
    - "Connection keying by id(conn) for the merge case (ROS2 Connection NamedTuple is unhashable; messages() is identity-stable)"
    - "Output-format Writer selection via the rosbags is2 = dst.suffix != '.bag' rule with an explicit fmt override"
    - "Offline invariant via lazy rosbags imports inside function bodies (mirrors tf/reader/output)"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/edit/__init__.py
    - packages/rosbagger-core/src/rosbagger_core/edit/operations.py
    - packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py
    - tests/test_edit.py
  modified:
    - tests/test_offline_guard.py

key-decisions:
  - "Opened AnyReader directly inside edit_bag (Option a) rather than adding a raw-stream accessor to RosbagsReader — keeps reader.py untouched (file-ownership clean)"
  - "Keyed the writer-connection map by id(conn) not conn.id — merge exposes per-bag connections whose ids COLLIDE (both bags use 0/1/2) and the ROS2 Connection is unhashable"
  - "Deduped writer add_connection by (topic, msgtype) — rosbag1.Writer rejects re-adding an identical connection; one writer connection per unique topic on merge"
  - "Downsample counter keyed per TOPIC (not per source connection) so merged bags share one every-Nth sequence over the combined time-ordered stream"
  - "Open Q2 LOCKED: empty result writes a valid empty bag and edit_bag returns the count (0) — no silent no-op, no special-cased error here (CLI prints the count in 11-02)"

patterns-established:
  - "Raw-copy same-format edit (Pattern 1): kept-connection re-registration + per-message trim/drop/downsample filters + raw write"
  - "Round-trip test contract (SC1/Pitfall 2): re-open via AnyReader AND deserialize every kept message, parametrized over all 3 formats"

requirements-completed: [EDIT-01]

# Metrics
duration: 6min
completed: 2026-05-23
---

# Phase 11 Plan 01: Streaming Edit Pipeline Core Summary

**A streaming `AnyReader` -> filter -> `rosbags` Writer pipeline (`rosbagger_core.edit`) that produces a NEW output bag from raw-copy trim/drop/keep/downsample/merge edits, lossless across ROS1 + ROS2-sqlite3 + MCAP, with outputs that re-open AND deserialize (SC1 raw-copy half).**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-23T09:06:31Z
- **Completed:** 2026-05-23T09:12:16Z
- **Tasks:** 2
- **Files modified:** 5 (4 created, 1 modified; +676 lines)

## Accomplishments
- Built the `rosbagger_core/edit/` subpackage: `EditOps` (validated spec), `edit_bag` (streaming raw-copy driver), `make_writer` (output-format selection) — zero new dependencies.
- trim (D-06) / drop+keep (D-07) / downsample + global downsample (D-08) / implicit multi-bag merge (D-09) all compose in one read->write pass and copy `rawdata` losslessly (D-04 raw-copy half).
- Every operation's output re-opens AND **deserializes** via `AnyReader` across all three formats (the real SC1 contract — re-open is not enough, Pitfall 2), proven by a 26-case parametrized round-trip suite.
- D-05 safety: never mutates the input, refuses to overwrite an input path, surfaces the Phase 7 `UnresolvedTypeError` on a no-defs read, and lets a mixed-format-merge `AnyReaderError` propagate clearly (Pitfall 6).
- Extended the offline-import guard so `import rosbagger_core.edit` leaks none of duckdb/sqlglot/pyarrow and no rosbags.
- Full suite green at **97.37%** coverage (347 tests), ruff clean across the repo.

## Task Commits

Each task was committed atomically (Task 1 is a TDD task: RED test gate -> GREEN implementation):

1. **Task 1 (RED): failing round-trip suite** - `621f423` (test)
2. **Task 1 (GREEN): same-format raw-copy edit pipeline** - `2156df4` (feat)
3. **Task 2: extend offline-import guard for rosbagger_core.edit** - `70a51a5` (test)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/edit/operations.py` - `EditOps` frozen dataclass + per-message predicates (`keeps_topic`/`trim_window_ns`/`downsample_factor`); enforces drop/keep mutual exclusion (D-07) and positive-N (V5).
- `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py` - `edit_bag` streaming driver (AnyReader raw stream -> filter -> Writer, raw-copy) + `make_writer` format selection; overwrite-input guard, no-defs teaching error.
- `packages/rosbagger-core/src/rosbagger_core/edit/__init__.py` - stdlib-light re-export of `edit_bag` / `EditOps` / `make_writer`.
- `tests/test_edit.py` - 26-case round-trip suite: noop/trim/drop/keep/downsample/downsample_all/merge x 3 formats + mutual-exclusion / non-positive-N / overwrite-input / fmt-override / empty-output.
- `tests/test_offline_guard.py` - +2 guards mirroring the tf pair: `test_import_edit_does_not_pull_heavy_query_stack` + `test_import_edit_does_not_pull_rosbags`.

## Decisions Made
- **Opened `AnyReader` directly in `edit_bag`** (CONTEXT Option a) rather than adding a raw-stream accessor to `RosbagsReader` — keeps `reader/rosbags_reader.py` untouched (clean file ownership) while copying its no-defs -> `UnresolvedTypeError` re-raise.
- **Keyed the connection map by `id(conn)` and deduped `add_connection` by `(topic, msgtype)`** — see Deviations (this was the merge fix).
- **Downsample counter is per-topic** so merged bags share one every-Nth sequence across the combined time-ordered stream; the counter only advances on messages that survive the prior trim/drop filters.
- **Open Q2 locked to "write empty bag + return count":** `edit_bag` returns `int` (messages written); an empty-keep / out-of-window trim yields a valid empty bag and `0`, never a silent no-op.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Multi-bag merge crashed / would have mis-mapped connections**
- **Found during:** Task 1 (GREEN — the `-k merge` ROS1 case)
- **Issue:** The first implementation re-registered one writer connection per source connection keyed by `conn.id`. On a merge, `AnyReader` exposes one connection PER source bag, so (a) `rosbag1.Writer` raised `WriterError: Connections can only be added once with same arguments` for the duplicate `/cmd_vel`, and (b) the per-bag connection ids COLLIDE (both bags use id 0/1/2), so keying by `conn.id` would have mapped the second bag's messages to the wrong/clobbered writer connection. A follow-on attempt to key by the `Connection` object itself then failed for ROS2 (`unhashable type: 'list'` — the ROS2 `Connection` NamedTuple carries a list in its `ext`).
- **Fix:** Register the writer connection ONCE per unique `(topic, msgtype)` (a duplicate source connection maps to the same writer connection), and key the source->writer map by `id(conn)` (object identity — the ROS2 Connection is unhashable but `messages()` yields the same objects as `reader.connections`, VERIFIED). Made the downsample counter per-topic to match.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/edit/pipeline.py`
- **Verification:** All 26 `tests/test_edit.py` cases green, including `test_merge_two_bags_doubles_and_orders` across ROS1 + ROS2-sqlite3 + MCAP (18 messages, 2x single-bag, time-ordered, all deserialize).
- **Committed in:** `2156df4` (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug).
**Impact on plan:** The fix was essential for the D-09 merge requirement and the cross-format SC1 contract — without it merge crashed on ROS1 and mis-keyed on ROS2. No scope creep; behavior, tests, and file ownership all stayed within the plan.

## Issues Encountered
- Acceptance-criterion `grep -c "serialize" pipeline.py` had to be 0, but two doc comments used the word "deserialize". Reworded the comments (no logic change) so the literal gate passes while the docstrings still cite the canonical rosbags `is2 = dst.suffix != '.bag'` rule. The raw path never calls `serialize_*`/`deserialize` — it writes `rawdata` directly (D-04 raw-copy half).

## Deferred Issues
- **EDIT-01 left NOT marked complete (intentional).** This plan ships only the raw-copy half (trim/drop/merge/downsample); the **convert** half (ROS1<->ROS2<->MCAP byte translation) is Plan 11-02. `requirements.mark-complete EDIT-01` also reported `not_found` because `.planning/REQUIREMENTS.md` lists EDIT-01 as a flat bullet (no checkbox/traceability table for the handler to flip). The ROADMAP progress (`11. Edit & Events | 1/4 | In Progress`) accurately reflects the partial state; EDIT-01 should be marked complete when 11-02 lands convert.
- `pipeline.py` coverage is 91% — the uncovered lines are the unknown-`fmt` `ValueError` (line 59) and the no-defs/mixed-format read-error branches (lines 123-130). The no-defs `UnresolvedTypeError` re-raise (threat T-11-02 mitigation) is load-bearing; the underlying pattern is already proven by the `RosbagsReader.open()` tests, but a direct edit-boundary test (reusing `write_def_less_bag`) would be a worthwhile add. Total coverage is 97.37% (gate 80%), so not blocking; flagged for a future plan or the verifier.

## User Setup Required
None - no external service configuration required. Local runs use `PYTHONPATH=""` (the dev-host ROS leak workaround); CI is ROS-free.

## Next Phase Readiness
- Plan 11-02 (convert) can now extend `edit_bag` / `make_writer` with the cross-format converter factory (`rosbags.convert.converter.generate_message_converter` / `migrate_bytes`) and add the thin `bagq edit` / `bagq convert` CLI verbs over this core API.
- The raw-copy half of D-04 is done; the convert half (ROS1 <-> ROS2 byte translation, the `Header.seq` migration) is explicitly Plan 11-02's scope and was NOT touched here.
- No blockers.

## Self-Check: PASSED

All created files exist on disk (`edit/__init__.py`, `edit/operations.py`, `edit/pipeline.py`, `tests/test_edit.py`, this SUMMARY) and all three task commits (`621f423`, `2156df4`, `70a51a5`) are in the git log.

---
*Phase: 11-edit-events*
*Completed: 2026-05-23*
