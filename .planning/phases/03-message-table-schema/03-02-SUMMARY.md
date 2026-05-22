---
phase: 03-message-table-schema
plan: 02
subsystem: database
tags: [rosbags, pyarrow, arrow, schema, nodetype, duckdb-types, flatten]

# Dependency graph
requires:
  - phase: 03-01
    provides: "ColumnDef/TableSchema backend-neutral model + sanitize_table_name (table-name derivation)"
  - phase: 02
    provides: "Message record (t/t_ns/stamp/topic source) + RosbagsReader exposing the typestore (reader._reader.typestore)"
provides:
  - "schema/types.py — ROS_BASE_TO_ARROW (verified Basename->pyarrow scalar map), arrow_type_of(ftype, typestore) (BASE->scalar, NAME->pa.struct, ARRAY/SEQUENCE->pa.list_), and the structural is_heavy_blob predicate"
  - "schema/flatten.py — build_table_schema(msgtype, typestore, *, topic) walking get_msgdef().fields into dotted scalar columns + the four prepended standard columns (t, t_ns, stamp, topic); STANDARD_COLUMNS constant; _walk_fields recursion"
  - "tests/test_schema_flatten.py — fixture-backed tests (real ROS2 Humble typestore) for the type map, dotted-column flattening, standard columns, and heavy-blob discrimination"
affects: [03-03, "05-query-engine", "04-inspect"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Translate between two mature type systems (rosbags Nodetype AST -> pyarrow DataType); no definition re-parsing"
    - "Schema derived from the DECLARED type AST (value-independent), never from a single message's runtime values"
    - "One shared recursive walk (_walk_fields) yields leaf descriptors carrying ros_path for 03-03's row extractor"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/schema/types.py
    - packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
    - tests/test_schema_flatten.py
  modified: []

key-decisions:
  - "Nodetype.NAME payload is the bare type-name string (verified vs research §3's payload[0]); _name_payload tolerates a tuple shape defensively but the bare string is the observed reality"
  - "Recursion descends ONLY into Nodetype.NAME and STOPS at ARRAY/SEQUENCE (one LIST/LIST-of-STRUCT leaf, never dotted into) — Pitfall 4 / DoS mitigation T-03-04"
  - "Top-level stamp column coexists with nested header.stamp.* columns (no dedup) — Pitfall 6"
  - "is_heavy_blob is structural (SEQUENCE of uint8|byte|char), NOT a name blocklist — Image.data flagged; Imu covariance + String.data not"
  - "STANDARD_COLUMNS nullability (stamp) is an Arrow-field property applied at the 03-03 pyarrow.Schema build, not on the backend-neutral ColumnDef"
  - "Cycle guard (seen frozenset) added as cheap insurance (Pitfall 5); no standard ROS type exercises it"

patterns-established:
  - "Pattern: arrow_type_of returns (pa.DataType, is_heavy_blob) so the walk gets both type and blob flag in one call"
  - "Pattern: build_table_schema prepends the 4 std ColumnDefs (empty ros_path) then appends one ColumnDef per walked leaf, preserving declared AST order"

requirements-completed: [QURY-02, QURY-03, QURY-04]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 3 Plan 02: ROS→Arrow type map + flattening walk Summary

**ROS Nodetype-AST → pyarrow type translator (`arrow_type_of` + `ROS_BASE_TO_ARROW` + structural `is_heavy_blob`) and the recursive `build_table_schema` that flattens a message into dotted columns with the four standard `t`/`t_ns`/`stamp`/`topic` columns prepended.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-22T08:46:02Z
- **Completed:** 2026-05-22T08:50:11Z
- **Tasks:** 3
- **Files modified:** 3 (all created)

## Accomplishments
- `schema/types.py`: the verified ROS `Basename` → `pyarrow` scalar map plus `arrow_type_of(ftype, typestore)` (BASE→scalar, NAME→`pa.struct` with SHORT inner names, ARRAY/SEQUENCE→`pa.list_`) and the structural `is_heavy_blob` predicate (QURY-03 type side, QURY-07 predicate).
- `schema/flatten.py`: `build_table_schema(msgtype, typestore, *, topic)` walking `typestore.get_msgdef(msgtype).fields` into dotted scalar columns (`linear.x`, `header.stamp.sec`) with the four standard columns prepended in fixed order (QURY-02, QURY-04); recursion stops at arrays so a `float64[9]` covariance is one `list<double>` leaf (QURY-03).
- `tests/test_schema_flatten.py`: 13 fixture-backed tests against the real ROS 2 Humble typestore covering the type map, dotted flattening, the standard columns, the top-level-`stamp`/nested-`header.stamp.*` coexistence, and heavy-blob discrimination.
- Full suite green (62 passed) at 95.88% coverage (gate ≥80% held); offline light-import invariant re-verified (`import rosbagger_core` loads no `schema/`, no `duckdb`/`pyarrow`/`rosbags`).

## Task Commits

Each task was committed atomically:

1. **Task 1: ROS→Arrow type map + arrow_type_of + is_heavy_blob** - `4567b78` (feat) — RED+GREEN landed together (type_map/heavy_blob tests + `types.py`)
2. **Task 2: build_table_schema flattening walk + standard columns** - `91b0269` (feat) — RED+GREEN landed together (flatten tests + `flatten.py`)
3. **Task 3: Fixture-backed test suite** - delivered across `4567b78`/`91b0269` (see Deviations) — the complete `tests/test_schema_flatten.py` is in-tree, all behaviors covered

**Plan metadata:** _(this docs commit)_

_Note: TDD tasks here combined the RED test write and GREEN implementation into one commit per task because the test file is a single shared artifact built up incrementally; each commit message documents both halves._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/schema/types.py` - `ROS_BASE_TO_ARROW` map, `arrow_type_of` translator, `is_heavy_blob` predicate; imports `pyarrow` + `rosbags.interfaces.Nodetype` only (no duckdb).
- `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py` - `STANDARD_COLUMNS`, `_walk_fields` recursion (NAME-only descent, stop at ARRAY/SEQUENCE, cycle guard), `build_table_schema` producing a `TableSchema`.
- `tests/test_schema_flatten.py` - fixture-backed tests using `get_typestore(Stores.ROS2_HUMBLE)` directly (no bag/reader); `-k "type_map"` and `-k "heavy_blob"` each select passing tests.

## Decisions Made
- **NAME payload shape:** the verified `rosbags` 0.11.2 runtime stores a `Nodetype.NAME` payload as the bare type-name string (`'geometry_msgs/msg/Vector3'`), NOT the 1-tuple that research §3's `payload[0]` snippet implied. Used the string directly via a small `_name_payload` helper that still tolerates a tuple wrapper defensively. (See Deviations Rule 1.)
- **Recursion boundary:** descend only into `Nodetype.NAME`; emit one `LIST`/`LIST`-of-`STRUCT` leaf at `ARRAY`/`SEQUENCE` (Pitfall 4 + threat T-03-04 DoS mitigation). Added a `seen` frozenset cycle guard (Pitfall 5) as cheap insurance.
- **`stamp` duplication is intentional** (Pitfall 6): the prepended top-level `stamp` and the faithful nested `header.stamp.sec`/`header.stamp.nanosec` columns both exist; not de-duplicated.
- **Nullability** of `stamp` is deferred to the 03-03 pyarrow build (it is an Arrow-field property), keeping `STANDARD_COLUMNS` and the `ColumnDef`s backend-neutral.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the Nodetype.NAME payload extraction (research §3 `payload[0]` was wrong for the verified runtime)**
- **Found during:** Task 1 (types.py — transcribing `arrow_type_of`)
- **Issue:** RESEARCH §3 wrote the `NAME` branch as `typestore.get_msgdef(payload[0]).fields`. Empirical check against `rosbags` 0.11.2 (and the fixtures) showed the `NAME` payload is the bare type-name **string** (`'geometry_msgs/msg/Vector3'`), so `payload[0]` would have been the single character `'g'` and `get_msgdef` would have failed. The PLAN's `<action>` text said `payload` (correct); the verbatim research snippet said `payload[0]`.
- **Fix:** Resolve the sub-message type via a `_name_payload(payload)` helper that returns the string directly and only falls back to `payload[0]` if a (future) tuple shape ever appears. Same correction applied in `flatten.py`'s `_walk_fields` (`ftype[1] if isinstance(ftype[1], str) else ftype[1][0]`).
- **Files modified:** packages/rosbagger-core/src/rosbagger_core/schema/types.py, packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
- **Verification:** `arrow_type_of((Nodetype.NAME, 'geometry_msgs/msg/Vector3'), ts)` returns `pa.struct([("x",float64()),("y",float64()),("z",float64())])`; Twist flattens to the six dotted Vector3 columns; full suite green.
- **Committed in:** `4567b78` (Task 1) and `91b0269` (Task 2)

### Process Note (not a code deviation)

**Task 3's deliverable (the comprehensive test file) was authored incrementally across the Task 1 and Task 2 commits** rather than as a separate third commit. The test file is a single shared artifact and strict TDD wrote each section's tests immediately before its implementation (RED→GREEN per task). At Task 3 there was no remaining file delta — fabricating an empty commit would add no information. All Task-3 behaviors (type-map asserts, dotted-column asserts, standard-column asserts, Imu nested-header coexistence, heavy-blob discrimination via real `get_msgdef().fields`) are present and passing, and the `-k "type_map"` / `-k "heavy_blob"` filters each select passing tests as the plan requires.

---

**Total deviations:** 1 auto-fixed (1 bug). Plus 1 process note (no code impact).
**Impact on plan:** The bug fix was required for correctness — the verbatim research snippet would not have run against the real `rosbags` API. No scope creep; all plan deliverables shipped exactly as specified.

## Issues Encountered
- `ruff format` reflowed one `types.py` boolean expression and `ruff check` flagged one SIM300 Yoda-condition in a test assert; both auto-applied (format + `--fix`) to keep the linter green. No logic change.

## Coverage / Known Stubs
- New-code coverage: `types.py` 93% (uncovered: the `_name_payload` tuple-fallback branch and the defensive `raise ValueError` for an impossible 5th Nodetype), `flatten.py` 88% (uncovered: the `seen`-set cycle-guard branch). All three are intentional defensive guards with no fixture trigger — matching the established 02-03 precedent of leaving defensive branches uncovered without adding pragmas. Total project coverage 95.88%, well above the ≥80% gate.
- No stubs that block the plan goal. `TableSchema.arrow_schema()` remains the documented `NotImplementedError("filled in 03-03")` stub from 03-01 — by design; this plan produces the `TableSchema`/columns only, and the live `pyarrow.Table` build is 03-03's deliverable.

## Next Phase Readiness
- 03-03 can now build the per-topic `pyarrow.Table`: each `ColumnDef` carries its `arrow_type` and `ros_path`, so the row extractor walks `ros_path` to pull values and the heavy-blob `include` seam (already on `TableSchema.column_names`) drives lazy materialization. `STANDARD_COLUMNS` gives 03-03 the exact std-column Arrow types.
- No blockers. Offline invariant intact; no new dependencies.

---
*Phase: 03-message-table-schema*
*Completed: 2026-05-22*

## Self-Check: PASSED

- Files: `schema/types.py`, `schema/flatten.py`, `tests/test_schema_flatten.py`, `03-02-SUMMARY.md` — all FOUND.
- Commits: `4567b78` (Task 1), `91b0269` (Task 2) — both FOUND in git history.
