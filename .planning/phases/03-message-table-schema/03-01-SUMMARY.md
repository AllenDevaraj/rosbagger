---
phase: 03-message-table-schema
plan: 01
subsystem: schema
tags: [dataclass, table-name, sanitization, collision-resolution, backend-neutral, sql-identifier]

# Dependency graph
requires:
  - phase: 02-bag-reader-layer
    provides: "Message record (topic/t/t_ns/stamp/msgtype/msg) — the per-row source these tables describe; reader/base.py frozen-dataclass style mirrored here"
provides:
  - "sanitize_table_name(topic): the QURY-01 topic->table-name rule (/camera/image_raw -> camera_image_raw), with empty/leading-digit/odd-char edge handling"
  - "TableNameResolver: idempotent, case-insensitive, deterministic collision resolver that records the topic->name mapping for Phase 4 (bagq tables)"
  - "ColumnDef / TableSchema: the backend-neutral public schema model (one column / one table) consumed by 03-02, 03-03, Phase 4, Phase 5"
  - "TableSchema.column_names(include=...): the heavy-blob lazy-exclusion filter (QURY-07), keyed on the dotted column name"
  - "arrow_schema(include=...): the declared NotImplementedError seam Phase 5 drives (pyarrow build deferred to 03-03)"
affects: [03-02-flatten-time, 03-03-list-struct-blobs, 04-inspect-bagq-tables, 05-querybackend-duckdb]

# Tech tracking
tech-stack:
  added: []  # stdlib-only (re, dataclasses); no new packages — locked deps unchanged
  patterns:
    - "Backend-neutral model: arrow_type typed as object so model.py imports no pyarrow (keeps the offline-import graph light, model trivially unit-testable)"
    - "Interface-first wave: ship the public contract (model + names) pyarrow-free so 03-02/03-03 implement against a fixed shape"
    - "Deferred seam as a documented NotImplementedError stub (arrow_schema) rather than an absent method"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/schema/model.py
    - packages/rosbagger-core/src/rosbagger_core/schema/names.py
    - tests/test_schema_names.py
  modified: []

key-decisions:
  - "arrow_type typed as object (not pyarrow.DataType) so model.py stays stdlib-only — the offline import graph and unit tests stay light; the real pyarrow type lands when 03-02/03-03 populate ColumnDef instances"
  - "include keys on the dotted column name (research Open Q2): degenerates to the bare name for the standard top-level blobs (Image.data/PointCloud2.data) and handles a hypothetical nested blob uniformly"
  - "TableNameResolver compares collisions case-insensitively (name.lower()) because SQL folds identifier case — /Foo and /foo are treated as colliding"
  - "Resolver is idempotent and does NOT burn a collision suffix on re-resolve (the topic->name dict is the source of truth; the used-name set advances only on a genuinely new name)"
  - "mapping property returns a copy (dict(self._mapping)) so Phase 4 cannot mutate resolver state"
  - "arrow_schema left as NotImplementedError('filled in 03-03') — pyarrow build intentionally deferred to keep this plan pyarrow-free"

patterns-established:
  - "Pattern 1: backend-neutral schema model (object-typed arrow_type) — Phase 4/5 build against a shape that needs no heavy import to describe"
  - "Pattern 2: heavy-blob lazy exclusion via an include set keyed on dotted name — column_names() omits is_heavy_blob columns unless named (QURY-07 seam Phase 5 drives)"
  - "Pattern 3: deterministic + idempotent + case-insensitive table-name collision resolution recording the topic->name mapping"

requirements-completed: [QURY-01]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 3 Plan 01: Schema Names + Model Contract Summary

**Backend-neutral `ColumnDef`/`TableSchema` model and the QURY-01 topic->table-name sanitizer + idempotent, case-insensitive, collision-resolving `TableNameResolver` — both stdlib-only, with `arrow_schema` left as the `NotImplementedError` seam plan 03-03 fills.**

## Performance

- **Duration:** ~5 min
- **Completed:** 2026-05-22
- **Tasks:** 3
- **Files created:** 3

## Accomplishments
- `sanitize_table_name(topic)` implements the verified QURY-01 rule: drop one leading `/`, remaining `/`->`_`, any char outside `[0-9A-Za-z_]`->`_`, empty result->`"topic"`, leading-digit->`t_` prefix. `/camera/image_raw` -> `camera_image_raw` (canonical example asserted by name).
- `TableNameResolver`: stateful, idempotent, case-insensitive, deterministic collision resolver (`a_b`, then `a_b_2`, ...) that records the topic->table-name mapping (exposed as a copy) for Phase 4's `bagq tables`.
- `ColumnDef` / `TableSchema`: the backend-neutral public model (one flattened column / one per-topic table) every later Phase 3 plan produces and Phase 4/5 consume; `arrow_type` typed as `object` so the module imports no pyarrow.
- `TableSchema.column_names(include=...)` honors the QURY-07 heavy-blob filter (omit `is_heavy_blob` columns unless named) keyed on the dotted column name; `arrow_schema(include=...)` is a documented `NotImplementedError` stub deferred to 03-03.
- Offline invariant preserved and re-verified: `import rosbagger_core` loads neither `schema/` submodules nor the heavy stack; `names.py`/`model.py` import only stdlib. Full suite 49 passed at 97.86% coverage (gate `--cov-fail-under=80` held; both new modules at 100%).

## Task Commits

Each task was committed atomically:

1. **Task 1: Define the ColumnDef / TableSchema model contract** - `0909432` (feat)
2. **Task 2: Implement sanitize_table_name + collision-resolving TableNameResolver** - `ac83079` (feat)
3. **Task 3: Unit-test the model + names against the spec examples and fixture topics** - `c46acb0` (test)

_Note: this plan's tasks are marked `tdd="true"`. The shared verify command (`pytest tests/test_schema_names.py`) requires the test file, so the full test suite was authored first (RED — confirmed `ModuleNotFoundError: rosbagger_core.schema.model`), then the two modules implemented (GREEN — 19 passed), then committed in declared-file order (model -> names -> tests). The RED commit is folded into the Task 3 test commit because the plan assigns the single test file to Task 3._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/schema/model.py` - Backend-neutral `ColumnDef`/`TableSchema` frozen dataclasses; `column_names(include=...)` heavy-blob filter; `arrow_schema` NotImplementedError stub. Stdlib-only (`dataclasses`).
- `packages/rosbagger-core/src/rosbagger_core/schema/names.py` - `sanitize_table_name` (QURY-01 rule) + `TableNameResolver` (idempotent, case-insensitive, deterministic collisions; copied `mapping` accessor). Stdlib-only (`re`).
- `tests/test_schema_names.py` - 19 pure-Python unit tests covering canonical/fixture sanitization, edge cases, resolver collisions/idempotency/mapping, and the model's four-field round-trip + `column_names` include/exclude + `arrow_schema` stub.

## Decisions Made
- **`arrow_type: object` (not `pyarrow.DataType`):** keeps `model.py` stdlib-only so the offline import graph stays light and the model is trivially unit-testable. The real pyarrow type is supplied by callers in 03-02/03-03; the model only describes the table shape.
- **`include` keyed on the dotted column name (research Open Q2):** uniform — degenerates to the bare name for the standard top-level blobs (`Image.data`, `PointCloud2.data`) and handles a hypothetical nested blob without an API change.
- **Case-insensitive collision detection (`name.lower()`):** SQL folds identifier case, so `/Foo` and `/foo` are treated as colliding (covered by `test_resolver_collision_is_case_insensitive`).
- **Idempotency does not consume a suffix:** the topic->name dict is the source of truth; re-resolving an already-seen topic returns its first name and never advances the suffix counter (covered by `test_resolver_idempotent_does_not_consume_a_suffix`).
- **`mapping` returns a copy:** `dict(self._mapping)` so a caller (Phase 4) cannot corrupt resolver state.
- **`arrow_schema` left stubbed:** raises `NotImplementedError("filled in 03-03")` — the pyarrow build is intentionally deferred so this interface-defining wave stays pyarrow-free.

## Deviations from Plan

None - plan executed exactly as written. (Two non-functional polish steps within scope: ran `ruff format`/`ruff check` on the three new files before committing so the repo's lint/format hooks pass on the main working tree — `model.py`'s `column_names` list comprehension was collapsed to one line to satisfy the 100-char formatter; no behavior change.)

## Issues Encountered
- The shared verify command (`pytest tests/test_schema_names.py`) is owned by Task 3 but referenced by Tasks 1 and 2, so a strict per-task RED/GREEN-then-commit ordering isn't possible while honoring each task's declared `<files>`. Resolved by writing the full test suite first for the RED gate, implementing both modules to GREEN, then committing in declared-file order (model, names, tests). All gates observed (RED `ModuleNotFoundError` confirmed before implementation; GREEN 19 passed after).
- The dev host sources ROS 2 Humble onto `PYTHONPATH`; all local `pytest`/`python`/`ruff` invocations were prefixed `PYTHONPATH=""` per the host-hazard note. This is invocation-only — no `PYTHONPATH` override is baked into committed code or CI.

## User Setup Required
None - no external service configuration required. (No new packages; the locked offline stack is unchanged.)

## Next Phase Readiness
- The public schema contract is pinned: 03-02 can build `TableSchema`/`ColumnDef` instances from the `rosbags` typestore AST (prepend the four standard columns, flatten nested scalars to dotted columns) and 03-03 can fill `arrow_schema` and the LIST/STRUCT + heavy-blob Arrow build against this fixed shape.
- `TableNameResolver.mapping` is the topic->table-name record Phase 4's `bagq tables` will print.
- Open seam carried forward (research Open Q3, unchanged): `schema/` takes the `typestore` explicitly; downstream wiring (03-02 / Phase 4-5) fetches `reader._reader.typestore` or adds an optional `BagReader.typestore` property — a small reader addition the planner may schedule. No blocker for this plan.

## Self-Check: PASSED

- Files verified on disk: `schema/model.py`, `schema/names.py`, `tests/test_schema_names.py`, `03-01-SUMMARY.md` — all FOUND.
- Commits verified in git log: `0909432` (model), `ac83079` (names), `c46acb0` (tests) — all FOUND.
- Full suite re-run with coverage: 49 passed, 97.86% total, gate `--cov-fail-under=80` held (new modules 100%). Offline guard still green (2/2); `import rosbagger_core` loads no `schema/` submodule or heavy stack.

---
*Phase: 03-message-table-schema*
*Completed: 2026-05-22*
