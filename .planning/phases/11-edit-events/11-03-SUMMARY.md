---
phase: 11-edit-events
plan: 03
subsystem: events
tags: [events, sidecar, parquet, pyarrow, duckdb-copy, offline, evnt-01]

# Dependency graph
requires:
  - phase: 06-export
    provides: rosbagger_core.output.export.write_table — the DuckDB-COPY Parquet writer with the T-06-01 single-quote-escaped path literal (the one SQL-literal boundary)
provides:
  - rosbagger_core.events module — the <bag>.events.parquet sidecar I/O layer (EVNT-01 write/read half, SC2)
  - sidecar_path(bag) -> Path — file-vs-dir-aware <bag>.events.parquet derivation (D-11); .bag/.mcap strip via with_suffix, ROS2 dir appends to the full name (Pitfall 7 — dotted dir safe)
  - add_event(bag, *, t_start_ns, t_end_ns, label, note=None) -> Path — append one fixed-v1-schema event (read existing -> pa.concat_tables -> rewrite via write_table; D-12/D-13)
  - list_events(bag) -> pyarrow.Table — read the sidecar back (SC2), or an empty 4-column table when no sidecar exists
affects: [11-04-events-query, bagq-cli]

# Tech tracking
tech-stack:
  added: []  # zero new dependencies — reuses pyarrow 24.0.0 + the locked output.export.write_table
  patterns:
    - "Event sidecar I/O: read existing -> pa.concat_tables -> rewrite the whole file (events are tiny — no in-place Parquet append; D-13)"
    - "Reuse the locked DuckDB-COPY writer (output.export.write_table) for the sidecar write — no second hand-built COPY (T-06-01 escape stays the single SQL-literal boundary)"
    - "File-vs-dir-aware path derivation: with_suffix ONLY for .bag/.mcap files; append .events.parquet to a directory bag's full name (dotted-dir Pitfall 7 safe)"
    - "Offline invariant via lazy pyarrow/export imports inside function bodies; sidecar_path is stdlib-only (pathlib) at module top (mirrors output/export.py, tf.py)"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/events.py
    - tests/test_events.py
  modified: []  # offline-guard extension for events is owned by Plan 11-04 (per the wave plan)

key-decisions:
  - "Built the fixed v1 schema inside a _event_schema() helper (not a module-level pa.schema constant) so pyarrow is NOT imported at module top — the offline invariant"
  - "add_event returns the written sidecar Path (small ergonomic affordance for the Plan 11-04 CLI verb), beyond the bare RESEARCH reference which returned None"
  - "Used bag.suffix.lower() in the file-vs-dir branch so .BAG/.MCAP (uppercase) still strip correctly"
  - "Kept the offline-guard test for rosbagger_core.events to Plan 11-04 (the wave plan assigns the events guard there); this plan only keeps the module importable-light and verified so by a fresh-interpreter check"

patterns-established:
  - "Sidecar I/O layer: a flat rosbagger_core/<module>.py (not in __init__) reusing the locked Parquet writer, mirroring the Phase 9 tf-in-core placement so the existing --cov=rosbagger_core gate covers it"
  - "Append-by-rewrite for tiny sidecar files (read -> pa.concat_tables -> write_table) instead of a row-group append"

requirements-completed: [EVNT-01]

# Metrics
duration: ~12min
completed: 2026-05-23
---

# Phase 11 Plan 03: Event Sidecar I/O Summary

**`rosbagger_core.events` — write/append/read-back the `<bag>.events.parquet` sidecar (fixed v1 schema `t_start_ns/t_end_ns/label/note`) reusing the locked DuckDB-COPY Parquet writer, with a file-vs-dir-aware path derivation that survives dotted ROS2 directory names (SC2).**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-23T03:16:45Z (RED commit)
- **Completed:** 2026-05-23T03:18Z (GREEN) + SUMMARY
- **Tasks:** 1 (TDD: RED → GREEN, no REFACTOR needed)
- **Files modified:** 2 (1 source, 1 test)

## Accomplishments
- `sidecar_path(bag)` derives `<bag>.events.parquet` deterministically file-vs-dir-aware (D-11 / Pitfall 7): a `.bag`/`.mcap` FILE strips its real extension via `with_suffix`; a ROS2 DIRECTORY bag appends `.events.parquet` to its full name so a dotted dir like `v1.2/` keeps its `.2` (does NOT become `v1.events.parquet`).
- `add_event(bag, *, t_start_ns, t_end_ns, label, note=None)` writes/grows the sidecar with the fixed v1 schema (D-12: `t_start_ns` BIGINT, `t_end_ns` BIGINT, `label` VARCHAR, `note` VARCHAR nullable); append = read existing → `pa.concat_tables` → rewrite the whole file (D-13 — events files are tiny).
- The write REUSES `output.export.write_table` (the DuckDB-COPY writer, T-06-01 quote-escaped path) — there is NO second hand-built COPY in `events.py` (grep-verified: `COPY ` count is 0), so the one SQL-literal boundary stays shared.
- `list_events(bag)` reads the sidecar back as a `pyarrow.Table` (the SC2 round-trip), and returns an EMPTY table with the four v1 columns when no sidecar exists (callers never crash on a missing sidecar).
- Offline invariant held: `import rosbagger_core.events` pulls in NONE of `{duckdb, sqlglot, pyarrow}` (and no `rosbags`) — verified in a fresh interpreter; heavy imports are lazy inside the function bodies, `sidecar_path` is stdlib-only.

## Task Commits

Each task was committed atomically (TDD cycle):

1. **Task 1 (RED): failing event-sidecar I/O suite** — `bd205f6` (test)
2. **Task 1 (GREEN): events.py — sidecar_path + add_event + list_events** — `c3168c9` (feat)

_No REFACTOR commit: the GREEN implementation followed the VERIFIED RESEARCH Pattern 4 structure, was ruff-clean and at 100% coverage on first pass._

**Plan metadata:** _(this commit)_ — docs: complete event-sidecar I/O plan

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/events.py` (created) — `sidecar_path` (file-vs-dir derivation), `add_event` (write/append the fixed v1 schema reusing `write_table`), `list_events` (read-back / empty-on-absent); `_event_schema()` builds the v1 schema lazily so pyarrow stays off the module top.
- `tests/test_events.py` (created) — 10 tests: 4 path-derivation (`.bag`/`.mcap` strip, ROS2-dir append, dotted-dir `v1.2` preserved), SC2 write→read-back (values + int64 `_ns` columns), sidecar-materialized, append-grows-to-2-in-order, point event (`t_start==t_end`), null `note`, absent-sidecar → empty 4-column table.

## Decisions Made
- **`add_event` returns the written `Path`** (a small ergonomic affordance for the Plan 11-04 `bagq events add` verb) — beyond the bare RESEARCH reference which returned `None`. Harmless extension; tests assert the sidecar exists at the returned path.
- **Fixed v1 schema built inside `_event_schema()`** (not a module-level `pa.schema(...)` constant) so `pyarrow` is never imported at module top — required by the offline invariant.
- **`bag.suffix.lower()`** in the file-vs-dir branch so an uppercase `.BAG`/`.MCAP` still strips correctly.
- **The offline-guard test for `rosbagger_core.events` is intentionally NOT added here** — the wave plan assigns the events offline-guard to Plan 11-04. This plan only keeps the module importable-light and proved it so via a fresh-interpreter `sys.modules` check.

## Deviations from Plan

None - plan executed exactly as written (the VERIFIED RESEARCH Pattern 4 reference implemented as specified, with the documented small `Path`-return / `.lower()` ergonomic touches noted under Decisions Made).

## Issues Encountered
- A docstring line in `test_events.py` initially exceeded the 100-char ruff `E501` limit; shortened it. The `COPY ` grep in the acceptance criteria initially matched 1 explanatory comment in `events.py`; reworded the comment to "locked Parquet writer ... no 2nd copy" so the AC grep reads a clean 0 (no behavior change — there was never a second COPY statement, only a comment mentioning the word).

## Threat Surface
No new threat surface beyond the plan's `<threat_model>`. The sidecar write reuses the single already-hardened SQL-literal boundary (`output.export.write_table`, T-06-01) rather than introducing a second COPY (T-11-09 mitigated by reuse); the read is the standard `pyarrow.parquet.read_table` over a file at the user's own trust level (T-11-10 accept); the path is derived deterministically next to the user-supplied bag (T-11-11 accept). Zero new packages (T-11-SC).

## Verification
- `PYTHONPATH="" .venv/bin/python -m pytest tests/test_events.py` — 10 passed.
- Full suite + coverage gate: `PYTHONPATH="" .venv/bin/python -m pytest` — **357 passed, total coverage 97.45%** (≥80% gate); `events.py` itself at **100%**.
- `ruff check` + `ruff format --check` on `events.py` + `tests/test_events.py` — clean.
- Offline invariant (fresh interpreter): `import rosbagger_core.events` leaks none of `{duckdb, sqlglot, pyarrow}` and no `rosbags`.
- Acceptance greps: all three funcs present; `write_table` reused; hand-built `COPY ` count = 0; four D-12 columns present; `with_suffix` used only in the file branch.

## Next Phase Readiness
- **Plan 11-04 (events query hook + CLI) is unblocked:** it imports `sidecar_path` from this module to discover `<bag>.events.parquet` next to the single bag, `pq.read_table`s it, and registers it under the reserved `events` table name for the SC3 interval join (D-14/D-15). `add_event`/`list_events` back the `bagq events add`/`list` verbs (D-02).
- **Open item carried to 11-04:** the offline-guard assertion for `rosbagger_core.events` (mirror the `edit`/`tf` guards) — this plan kept the module compliant; 11-04 owns the formal test.
- No blockers.

## Self-Check: PASSED

- Files: `events.py`, `tests/test_events.py`, `11-03-SUMMARY.md` all present.
- Commits: `bd205f6` (RED test), `c3168c9` (GREEN feat) both in git history.

---
*Phase: 11-edit-events*
*Completed: 2026-05-23*
