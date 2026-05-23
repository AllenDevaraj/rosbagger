---
phase: 10-query-ergonomics
plan: 02
subsystem: api
tags: [pyarrow, projection-pushdown, column-projection, schema, sqlglot, duckdb]

# Dependency graph
requires:
  - phase: 03-schema
    provides: "TableSchema.arrow_schema(include=)/column_names(include=) + build_arrow_table(include=)/flatten_message(include=) — the declared-order, name-keyed heavy-blob column-filter seam this plan generalizes"
  - phase: 05-query
    provides: "backend/query.py:184 — the SOLE production caller of build_arrow_table/arrow_schema; confirms a default restrict=None leaves bagq tables untouched"
provides:
  - "restrict= (column-projection) parameter on TableSchema.arrow_schema / TableSchema.column_names — composed (ANDed) with the existing heavy-blob include= filter (D-06)"
  - "restrict= on flatten_message — the literal skipped-read pushdown: a non-restricted data column's reduce(getattr, ros_path, msg) never runs"
  - "restrict= on build_arrow_table — threaded into BOTH arrow_schema(...) (single source of truth for kept columns) AND flatten_message(...)"
  - "A spy-proven unit guarantee that an unreferenced/heavy value is never read off the message under restrict"
affects: [10-03-orchestrator-wiring, query-ergonomics, projection-pushdown]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Orthogonal composed filter: keep iff (NOT heavy OR name∈include) AND (restrict is None OR name∈restrict) — generalize the one filter, never a parallel build_arrow_table_projected path (D-06)"
    - "Projection-by-skipped-read: the pushdown is the comprehension predicate skipping reduce(getattr,...), NOT a post-build drop_columns/.select (which would still read the value)"
    - "restrict=None = byte-for-byte today's behavior — a transparent default so every existing caller (inspect.collect_table_schemas / bagq tables) is provably unaffected"

key-files:
  created: []
  modified:
    - "packages/rosbagger-core/src/rosbagger_core/schema/model.py — arrow_schema(include=, restrict=) + column_names(include=, restrict=)"
    - "packages/rosbagger-core/src/rosbagger_core/schema/flatten.py — flatten_message(..., restrict=) + build_arrow_table(..., restrict=)"
    - "tests/test_schema_arrow.py — 9 new tests (4 model + 4 flatten + 1 bagq-tables regression)"

key-decisions:
  - "Standard columns (t/t_ns/stamp/topic) are NOT special-cased in these four functions — D-07's always-materialized guarantee is enforced upstream by the orchestrator unioning them into restrict (Plan 10-03), so a bare restrict={\"linear.x\"} legitimately yields exactly [\"linear.x\"]"
  - "restrict is keyword-only and defaults to None on all four functions; composed (ANDed) with include=, never replacing it — a heavy blob in restrict but not include is still dropped"
  - "build_arrow_table threads the SINGLE restrict value into both schema.arrow_schema(...) and flatten_message(...) so the kept-column set and the value arrays cannot drift"
  - "No post-build drop_columns/.select path — the pushdown is the skipped read (grep-gated absent)"

patterns-established:
  - "Composed orthogonal column filters in the schema layer: include (heavy-blob, QURY-07) AND restrict (projection, QURY-09) over an already-declared, value-independent, declared-order schema"
  - "Spy-based pushdown proof: a stub message whose non-restricted attribute raises proves the value-read is genuinely skipped (belt-and-suspenders over the column-set assertion, research A4)"

requirements-completed: [QURY-09]

# Metrics
duration: 5min
completed: 2026-05-23
---

# Phase 10 Plan 02: Column Projection Pushdown (restrict= filter) Summary

**Generalized the schema layer's heavy-blob `include=` column filter into a second, orthogonal `restrict=` projection filter (QURY-09) across `arrow_schema`/`column_names`/`flatten_message`/`build_arrow_table` — where `flatten_message` simply never reads a non-restricted column off the message (the literal pushdown), and `restrict=None` is byte-for-byte today's behavior so `bagq tables` is provably untouched.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-23T05:07:13Z
- **Completed:** 2026-05-23T05:12:08Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `TableSchema.arrow_schema` and `TableSchema.column_names` gained a keyword-only `restrict: set[str] | None = None` parameter; both apply the composed predicate `(not heavy or name∈include) AND (restrict is None or name∈restrict)` (D-06).
- `flatten_message` gained `restrict=` and SKIPS `reduce(getattr, col.ros_path, msg)` for any data column not in the restrict set — the literal "pushdown" (an unreferenced/heavy value is never read off the message). Proven by a spy whose `.angular` raises on access yet `flatten_message(stub, schema, restrict={"linear.x"})` does NOT raise.
- `build_arrow_table` gained `restrict=` and threads the single value into BOTH `schema.arrow_schema(include=, restrict=)` (the single source of truth for kept columns) AND `flatten_message(..., restrict=)`.
- `restrict=None` reproduces today's exact behavior — pinned by a dedicated regression test (`test_tables_path_unaffected_by_restrict_param`) asserting `collect_table_schemas` / `column_names()` still lists every non-heavy column and excludes the heavy `data` blob (the D-06 "only caller is query.py; bagq tables untouched" guarantee).
- Offline-import invariant preserved: `pyarrow` stays imported INSIDE `arrow_schema` (no module-top heavy import); offline-guard suite stays green (10 passed).

## Task Commits

Each task was committed atomically (TDD: test → feat per behavior-adding task):

1. **Task 1: restrict= on TableSchema.arrow_schema + column_names**
   - `6481cba` (test — RED: failing restrict= tests)
   - `e33f767` (feat — GREEN: composed restrict filter in model.py)
2. **Task 2: restrict= on flatten_message + build_arrow_table (the skipped-read pushdown)**
   - `5eee5bd` (test — RED: failing restrict= tests incl. the spy)
   - `11ddcc2` (feat — GREEN: skipped-read pushdown in flatten.py + test-only spy fix)
3. **Task 3: Regression — full schema suite + bagq tables untouched**
   - `7d5e69a` (test — `test_tables_path_unaffected_by_restrict_param`)

**Plan metadata:** committed separately (docs: complete plan — SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/schema/model.py` — `arrow_schema(include=, restrict=)` and `column_names(include=, restrict=)`: extended both comprehension predicates to the composed `(not heavy or in include) AND (restrict is None or in restrict)` form; docstrings document the orthogonal projection filter, cite D-06, note `restrict=None` = today and that standard columns are the orchestrator's job (D-07). `pyarrow` import unchanged (inside `arrow_schema`).
- `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py` — `flatten_message(..., restrict=)`: the dict-comprehension predicate now skips the `reduce(getattr,...)` for non-restricted data columns (the pushdown). `build_arrow_table(..., restrict=)`: threads `restrict` into the one `arrow_schema(...)` call (kept-set lockstep) and the per-message `flatten_message(...)` call. No `drop_columns`/`.select` added.
- `tests/test_schema_arrow.py` — 9 new tests: 4 on `arrow_schema`/`column_names` (single-column projection yields exactly the named subset; `restrict=None` regression; the include∧restrict composition; `column_names` mirrors `arrow_schema.names`), 4 on `flatten_message`/`build_arrow_table` (single-column flatten; the spy pushdown proof; single-column Table with matching fixture values + `restrict=None` regression; heavy-blob composition), and 1 `bagq tables` no-op regression. Added `collect_table_schemas` to the imports.

## Decisions Made
- **Standard columns are not special-cased here.** Per D-07 (and the threat register T-10-04), the always-materialized guarantee for `t`/`t_ns`/`stamp`/`topic` is enforced by the orchestrator (Plan 10-03) unioning them into the restrict set — NOT hard-coded in these four functions. A bare `restrict={"linear.x"}` correctly yields only `["linear.x"]` at this unit level; the standard-column safety net is integration-tested in 10-03. Tests assert this exact behavior.
- **Composed, not replaced.** `restrict` is ANDed with the existing heavy-blob `include` filter rather than replacing it, so today's heavy-blob/star semantics are fully preserved and a heavy blob in `restrict` but not `include` is still dropped (verified by the composition tests).
- **Pushdown = skipped read, not post-build drop.** Followed the "Don't Hand-Roll" guidance (T-10-05): the comprehension predicate skips the `reduce(getattr,...)` itself; no `drop_columns`/`.select` was introduced (grep-gated absent), since a post-build drop would still read the value.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Spy stub in the pushdown test reached `linear.y` before `angular`**
- **Found during:** Task 2 (the GREEN run of `test_flatten_message_restrict_skips_the_read_proven_by_spy`)
- **Issue:** The spy's `_Linear` stub initially exposed only `.x`. The Twist schema reads data columns in declared order (`linear.x`, `linear.y`, `linear.z`, then `angular.*`), so the **no-restrict control assertion** raised `AttributeError: '_Linear' object has no attribute 'y'` on `linear.y` instead of the intended `AssertionError("angular was read")` on `angular`. The production pushdown was already correct (the `restrict={"linear.x"}` path passed); only the test's control arm probed the wrong attribute first.
- **Fix:** Gave `_Linear` `x`/`y`/`z` so the no-restrict control walk reaches `angular.x` and raises there (proving the control genuinely touches `angular`, while the restricted call provably does not). Production code unchanged.
- **Files modified:** `tests/test_schema_arrow.py` (test-only)
- **Verification:** `PYTHONPATH="" .venv/bin/python -m pytest tests/test_schema_arrow.py -k restrict -x` → 8 passed.
- **Committed in:** `11ddcc2` (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 test-only bug). 
**Impact on plan:** Test-only fix to make the spy's control arm prove the intended property; zero production-code impact, no scope creep. Plan executed exactly as written otherwise.

## Issues Encountered
None beyond the test-only spy fix above. All acceptance-criteria greps passed: the composed predicate appears in `model.py` (≥2), the skipped-read predicate is present in `flatten.py` (≥1), `build_arrow_table` threads `restrict` into its single `arrow_schema(...)` call, no `drop_columns`/`.select(` was introduced, and no top-level `import pyarrow` exists in `model.py`.

## Verification Evidence
- `PYTHONPATH="" .venv/bin/python -m pytest tests/test_schema_arrow.py tests/test_schema_flatten.py tests/test_inspect_tables.py -x` → **60 passed**.
- Full suite: `PYTHONPATH="" .venv/bin/python -m pytest -q` → **297 passed, 97.69% coverage** (≥80% gate met; `model.py` now 100%). Baseline before this plan was 287 passed.
- Offline-import guard: `tests/test_offline_guard.py` → **10 passed** (no eager duckdb/pyarrow leak; `import pyarrow` stays inside `arrow_schema`).
- `ruff check` + `ruff format --check` on `model.py`, `flatten.py`, `tests/test_schema_arrow.py` → clean.
- `restrict=None` proven a true no-op: `column_names() == column_names(restrict=None)` and the `arrow_schema` equivalent for every fixture topic; `collect_table_schemas` output unchanged.

## Known Stubs
None — this plan is pure filter generalization of an existing seam. No placeholder values, no unwired data sources, no TODO/FIXME introduced.

## User Setup Required
None — no external service configuration, no new dependency (`pyarrow` already locked).

## Next Phase Readiness
- The materialization mechanism for projection pushdown is complete, self-contained in the schema layer, and fully unit-tested. **Plan 10-03 (orchestrator wiring) is unblocked**: it computes the restrict set from the alias-expanded SQL via `referenced_columns`, unions the four standard columns (D-07), applies it per-topic / over-includes on JOINs (D-09), passes `restrict=None` under a `SELECT *` (D-08), and threads it into `build_arrow_table` at `backend/query.py:184`. The SC3 end-to-end fixture assertion (D-10) lands there.
- QURY-09 mechanism is DONE; full QURY-09 traceability completes when 10-03 wires it into `query()`.
- Standing project blocker unchanged (not introduced by this plan): HUMAN must `git push origin main && git push origin v0.1.0` and observe GitHub Actions green to finalize the v0.1 release.

## Self-Check: PASSED

- Files exist: `schema/model.py`, `schema/flatten.py`, `tests/test_schema_arrow.py` — all FOUND.
- Commits exist: `6481cba` (test/Task1 RED), `e33f767` (feat/Task1 GREEN), `5eee5bd` (test/Task2 RED), `11ddcc2` (feat/Task2 GREEN), `7d5e69a` (test/Task3) — all FOUND in git log.
- All four functions carry the new `restrict: set[str] | None = None` parameter; `restrict` appears in both source files (artifacts `contains: "restrict"` satisfied).
- TDD gate sequence verified for both behavior-adding tasks: `test(...)` RED commit precedes the `feat(...)` GREEN commit.

---
*Phase: 10-query-ergonomics*
*Completed: 2026-05-23*
