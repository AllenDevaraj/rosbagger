---
phase: 10-query-ergonomics
plan: 01
subsystem: api
tags: [sqlglot, ast-rewrite, alias-pack, query, offline-guard, ros]

# Dependency graph
requires:
  - phase: 03-schema
    provides: build_table_schema + TableSchema.columns (the dotted column vocabulary the existence-gate matches against)
  - phase: 05-query-engine
    provides: backend/resolve.py parse() + the sqlglot AST seam expand_aliases sits beside; the offline-import invariant
provides:
  - "backend/alias.py: ALIAS_PACK (msgtype -> {alias: dotted-target}) for Twist/TwistStamped/Odometry/Imu/PoseStamped/Pose"
  - "expand_aliases(tree, msgtype, schema_names): a pure sqlglot tree.transform that expands short aliases to quoted dotted columns, existence-gated (D-04), returns a NEW tree"
  - "offline-guard regression covering import rosbagger_core.backend.alias (no duckdb/pyarrow leak)"
affects: [10-03 orchestrator wiring (calls expand_aliases per referenced topic, owns --no-alias + single-base-topic guard), 10-02 projection pushdown]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alias rewrite as a tree.transform() returning a copy (never mutate-while-walking); replacement built ONLY via exp.column(target, quoted=True) — no f-string/regex (D-01, T-10-01)"
    - "Existence-gate (D-04): expand only when the alias target is in the referenced topic's schema names — a non-resolving short token is a safe no-op"
    - "Module stays offline-safe: top imports are __future__ + sqlglot.exp only (mirrors resolve.py); guarded by a duckdb/pyarrow-only offline test (sqlglot eager-import allowed)"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/backend/alias.py
    - tests/test_backend_alias.py
  modified:
    - tests/test_offline_guard.py

key-decisions:
  - "Module placement: a NEW backend/alias.py (keeps resolve.py single-purpose) per D's discretion + 10-RESEARCH primary recommendation"
  - "Shipped the verified 10-RESEARCH alias-pack table verbatim (6 msgtypes); alias spellings are D-05 discretion, dotted targets re-verified against the live ROS2 Humble typestore"
  - "JOIN/CTE scoping deliberately NOT implemented here — this helper is per-msgtype/per-schema; the single-base-topic guard is the orchestrator's job (Plan 10-03, Open Q1)"

patterns-established:
  - "AST-only alias expansion: exp.Column match + exp.column(quoted=True) replacement inside tree.transform"
  - "duckdb/pyarrow-only offline guard for a module that legitimately imports sqlglot at top (the resolve.py precedent generalized)"

requirements-completed: [QURY-08]

# Metrics
duration: 8min
completed: 2026-05-23
---

# Phase 10 Plan 01: Alias Pack + sqlglot-AST Rewrite Summary

**Built `backend/alias.py` — a built-in msgtype-keyed alias pack plus `expand_aliases`, a pure sqlglot `tree.transform` that rewrites short shortcuts (`vx`) into quoted dotted columns (Twist `vx`→`"linear.x"`, Odometry `vx`→`"twist.twist.linear.x"`), existence-gated so a non-resolving token is a safe no-op.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-23T04:54:02Z
- **Completed:** 2026-05-23T05:02:00Z
- **Tasks:** 3 (plus one coverage-strengthening follow-up commit)
- **Files modified:** 3 (1 created module, 1 created test, 1 extended test)

## Accomplishments

- `ALIAS_PACK` ships the full verified v1 table (geometry/nav/sensor): `geometry_msgs/msg/Twist`, `TwistStamped`, `nav_msgs/msg/Odometry`, `sensor_msgs/msg/Imu`, `geometry_msgs/msg/PoseStamped`, `Pose` — the canonical SC1 cases `Twist.vx → linear.x` and `Odometry.vx → twist.twist.linear.x` both hold.
- `expand_aliases(tree, msgtype, schema_names)` is a pure `tree.transform` (D-01): returns a NEW tree (input unmutated), reaches every clause (SELECT/WHERE/GROUP BY/HAVING/ORDER BY) and function args, preserves output aliases (`vx AS speed` → `"linear.x" AS speed`), and existence-gates (D-04) so unknown/wrong-topic tokens and already-dotted columns are safe no-ops.
- The replacement identifier is built ONLY via `exp.column(target, quoted=True)` — no f-string, no regex, no raw substitution — keeping the trusted-SQL boundary (T-05-04 / T-10-01); grep-gated in the acceptance criteria.
- The offline invariant is extended: `import rosbagger_core.backend.alias` leaks no `duckdb`/`pyarrow` (sqlglot at the module top is allowed — the resolve.py precedent), now a permanent regression test.

## Task Commits

Each task was committed atomically (TDD RED → GREEN for Task 2):

1. **Task 1: Wave 0 — failing alias-rewrite test scaffold** — `cb027bf` (test, RED)
2. **Task 2: backend/alias.py — ALIAS_PACK + expand_aliases AST rewrite** — `522ce7d` (feat, GREEN)
3. **Task 3: Extend the offline-guard for backend.alias** — `3123333` (test)
4. **Follow-up: cover the `_normalize` defensive path** — `c9ab482` (test)

**Plan metadata:** see final `docs(10-01)` commit (SUMMARY + STATE + ROADMAP + REQUIREMENTS).

_Task 2 is a `tdd="true"` task: its RED commit is Task 1's `cb027bf` (scaffold fails on the missing module), its GREEN commit is `522ce7d`. No REFACTOR commit — the implementation was clean and minimal as written._

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/backend/alias.py` — NEW. `ALIAS_PACK` dict literal + `_normalize` (defensive `pkg/Type`→`pkg/msg/Type`, A2) + `expand_aliases`. Imports only `from __future__ import annotations` and `from sqlglot import exp` (offline-safe, mirrors resolve.py).
- `tests/test_backend_alias.py` — NEW. Self-contained harness (repo-root `sys.path` insert, real ROS2 Humble typestore for the existence-gate vocabulary). 13 tests: canonical Twist/Odometry, all-clause (`-k clause`), function-arg, input-immutability, existence-gate (`-k gate` ×3), edge (`-k edge` ×4 incl. already-dotted/output-alias/qualified/normalization).
- `tests/test_offline_guard.py` — EXTENDED by ONE test (`test_import_alias_does_not_pull_heavy_data_stack`); `_HEAVY_STACK` and the 9 pre-existing guards unchanged.

## Decisions Made

- **New `backend/alias.py` module** (not extending `resolve.py`) — keeps `resolve.py` single-purpose ("what does this SQL touch?") and isolates the pack data. Both were valid per D's discretion; this is the 10-RESEARCH primary recommendation.
- **Shipped the 10-RESEARCH alias-pack table verbatim** — re-verified all six msgtypes' dotted targets against the live `ROS2_HUMBLE` typestore via `build_table_schema` before transcribing (every probe matched). Alias spellings are D-05 discretion.
- **No JOIN/CTE scoping here** — this helper is per-msgtype/per-schema; tree-wide expansion is safe because the existence-gate makes a non-resolving short token a no-op. The single-base-topic guard (Open Q1) is the orchestrator's responsibility in Plan 10-03.

## Deviations from Plan

None affecting code behavior — the plan executed as written. Two within-scope refinements during planned work:

1. **Added `test_edge_msgtype_normalization` (coverage of my own added branch).** The `_normalize` defensive `pkg/Type`→`pkg/msg/Type` path (A2, in the plan's `<action>`) had no test, leaving `alias.py` at 79% in isolation. Added one `-k edge` test driving it through the public `expand_aliases`, lifting module coverage to 95% (the one remaining line is the trivially-defensive non-two-segment fall-through, no pragma — consistent with the project's tf.py/types.py defensive-line precedent). Committed in `c9ab482`. Not a deviation rule; it strengthens this task's own tests.
2. **Ruff auto-fix on the new files** (import sort + format) — applied during each task before commit, as the project requires clean `ruff check` / `ruff format --check`.

**Total deviations:** 0 behavior-changing. **Impact:** none — within the plan's stated action and verification.

## Issues Encountered

None. The RED scaffold failed exactly as designed (missing module only, no collection errors), the GREEN implementation passed all 13 alias tests first try, and the offline subprocess check confirmed only `sqlglot` (not `duckdb`/`pyarrow`) lands in `sys.modules`.

## Verification Evidence

- `PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_alias.py tests/test_offline_guard.py -x` → **23 passed**.
- Full suite: `PYTHONPATH="" .venv/bin/python -m pytest -q` → **287 passed, 97.35% coverage** (≥80% gate met; baseline was 274 — +13 new tests).
- `grep -nE "import pyarrow|import duckdb|from rosbagger_core" .../backend/alias.py` → nothing (offline invariant at the source).
- `ruff check` + `ruff format --check` on all three files → clean.
- Canonical one-liner: `ALIAS_PACK['geometry_msgs/msg/Twist']['vx']=='linear.x'` and `ALIAS_PACK['nav_msgs/msg/Odometry']['vx']=='twist.twist.linear.x'` → exits 0.
- Offline subprocess: `import rosbagger_core.backend.alias` → `sqlglot` present, `duckdb`/`pyarrow` absent.

## Next Phase Readiness

- `expand_aliases` is ready for the orchestrator to call in Plan 10-03 (between `parse` and the `referenced_*` calls; gated by `alias=True`, keyed on `topic_to_msgtype`, fed each topic's `TableSchema` column-name set).
- Plan 10-03 owns: per-topic gating, the single-base-topic guard for multi-topic/JOIN/CTE (Open Q1), and the `--no-alias` CLI surface (D-11). None of that is implemented here by design.
- Plan 10-02 (projection pushdown) is independent of this module and unaffected.

## Self-Check: PASSED

- Files verified on disk: `backend/alias.py`, `tests/test_backend_alias.py`, `tests/test_offline_guard.py`, `10-01-SUMMARY.md` — all FOUND.
- Commits verified in git log: `cb027bf` (RED), `522ce7d` (GREEN), `3123333` (offline-guard), `c9ab482` (coverage) — all FOUND.

---
*Phase: 10-query-ergonomics*
*Completed: 2026-05-23*
