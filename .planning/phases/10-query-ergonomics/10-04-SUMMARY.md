---
phase: 10-query-ergonomics
plan: 04
subsystem: bagq-cli
tags: [cli, no-alias, alias-pack, projection-pushdown, typer, thin-pass-through, phase-gate]

# Dependency graph
requires:
  - phase: 10-03-orchestrator-wiring
    provides: "query(sql, reader, *, alias=True, backend=None) — the alias keyword (D-11) this CLI threads --no-alias onto; aliases ON by default, alias=False is the escape hatch"
  - phase: 07-errors-that-teach
    provides: "@teaching_errors (catches UnknownColumnError -> clean stderr line + Exit(1), no traceback) — the vetted CLI-03 rendering the --no-alias path reuses"
  - phase: 06-output
    provides: "the bagq query command (typer command + _PlotCommand cls + lazy run_query import + -o/--format/--plot routing) this plan adds ONE option to"
provides:
  - "bagq query --no-alias (default False = aliases ON, D-11) — a boolean option forwarded as alias=not no_alias to run_query(); a thin pass-through (no business logic in the CLI)"
  - "QURY-08 CLI surface complete end-to-end: SELECT vx FROM cmd_vel exits 0 + renders linear.x (aliases on); --no-alias exits 1 with a clean UnknownColumnError teaching line (no traceback)"
  - "Phase-10 green-bar gate: full suite 316 passed @ 97.73% (>=80% cov), ruff check + format --check clean, offline-guard 10 passed; SC1/SC2/SC3 confirmed"
affects: [query-ergonomics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Thin-CLI pass-through (decision 1, API-first): a new typer boolean option forwards a Python bool to the orchestrator (alias=not no_alias); the CLI builds no SQL and owns no rewrite logic — the orchestrator owns the trusted-SQL boundary"
    - "Offline-import discipline preserved: the new option adds no module-top import; run_query stays lazy-imported inside the query body, so importing bagq.cli pulls no rosbags/pyarrow/duckdb"
    - "Projection pushdown is transparent — NO CLI flag (D-11): it changes only what is loaded, never the result, so it needs no user control surface"

key-files:
  created: []
  modified:
    - "packages/bagq/src/bagq/cli.py — added the --no-alias boolean option to the query command and forwarded alias=not no_alias on the run_query call; docstring note on aliases-on default + transparent projection"
    - "tests/test_cli_query.py — 3 CliRunner tests (-k no_alias): vx expands by default (exit 0 + linear.x), --no-alias disables (clean Exit 1, no traceback), --no-alias listed in query --help"

key-decisions:
  - "--no-alias is a single typer boolean option appended after --plot, matching the existing Annotated[..., typer.Option(...)] idiom; default False = aliases ON (D-11). The body change is one keyword: run_query(sql, reader) -> run_query(sql, reader, alias=not no_alias). No other change — the _PlotCommand/--plot machinery, -o/--format routing, and the lazy run_query import are untouched."
  - "Projection pushdown gets NO flag (D-11): it is always-on and transparent (changes only what is loaded, never results), so there is nothing for a user to toggle. The plan and CONTEXT D-11 both mandate this; the CLI exposes only the alias escape hatch."
  - "The --no-alias clean-error path reuses the already-shipped @teaching_errors + UnknownColumnError boundary (Phase 7 CLI-03) — no new rendering surface. With expansion off, vx is not a Twist column, DuckDB's binder rejects it, query() re-maps to UnknownColumnError, and @teaching_errors prints one stderr line + Exit(1). Proven via the real CLI binary (Unknown column 'vx'. Columns in cmd_vel: ...) and a CliRunner SystemExit/not-ValueError assertion (the 07/09 no-traceback convention)."
  - "Phase gate run locally with the PYTHONPATH=\"\" prefix (the dev host leaks ROS onto PYTHONPATH; CI is ROS-free and needs no prefix). The offline-guard test file lives at tests/test_offline_guard.py (repo root), not under the package."

requirements-completed: [QURY-08]

# Metrics
duration: 2min
completed: 2026-05-23
---

# Phase 10 Plan 04: bagq query --no-alias CLI Surface + Phase Gate Summary

**Surfaced the alias pack on the `bagq query` command with a `--no-alias` escape hatch (D-11) — a single typer boolean (default False = aliases ON) forwarded as `alias=not no_alias` to the 10-03 orchestrator, a thin pass-through that builds no SQL and adds no module-top import — then ran the phase green-bar gate: the full suite is 316 passed @ 97.73% (≥80% cov), ruff check + format are clean, the offline-guard suite is 10 passed, and the three phase success criteria (SC1 alias resolves, SC2 projection loads only referenced columns, SC3 a single-column query doesn't materialize unreferenced/heavy columns) are all confirmed end-to-end — including the real CLI binary rendering `SELECT vx FROM cmd_vel` as the `linear.x` series and `--no-alias` surfacing a clean `Unknown column 'vx'` teaching line with no traceback.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-23T05:27:23Z
- **Completed:** 2026-05-23T05:29:44Z
- **Tasks:** 2 (Task 1 TDD: RED -> GREEN; Task 2 the phase gate)
- **Files modified:** 2

## Accomplishments

- **`bagq query` gained a `--no-alias` boolean option** (default `False` = aliases ON, D-11), declared in the existing `Annotated[bool, typer.Option("--no-alias", help=...)]` style and appended after `--plot`. The body forwards it as `result = run_query(sql, reader, alias=not no_alias)` — a one-keyword change to the single `run_query` call.
- **Thin pass-through preserved (decision 1, API-first):** the CLI builds no SQL, owns no rewrite logic, and added no module-top import. The orchestrator (10-03) owns the alias rewrite and the trusted-SQL boundary; the CLI only threads a Python bool through. The `_PlotCommand`/`--plot` machinery, the `-o`/`--format` routing, and the lazy `run_query` import are all untouched.
- **Offline-import discipline intact:** importing `bagq.cli` pulls no `rosbags`/`pyarrow`/`duckdb` (verified directly + by the offline-guard suite); `run_query` stays lazy-imported inside the query body.
- **Projection pushdown gets NO flag (D-11):** it is always-on and transparent (changes only what is loaded, never results), so the CLI exposes only the alias escape hatch. The query command's table/`-o`/`--format`/`--plot` behavior is otherwise unchanged.
- **QURY-08 CLI surface is complete end-to-end:** `SELECT vx FROM cmd_vel` (aliases on by default) renders the Twist `linear.x` series `[0.0, 1.0, 2.0]` and exits 0; `--no-alias "SELECT vx FROM cmd_vel"` exits 1 with the clean teaching line `Unknown column 'vx'. Columns in cmd_vel: ...` and no traceback — both demonstrated via the real `bagq` binary.
- **Phase-10 green-bar gate:** full suite **316 passed @ 97.73%** coverage (≥80% gate met; 313 baseline + 3 new CLI tests), `ruff check` + `ruff format --check` clean across all 53 files, offline-guard **10 passed**. SC1/SC2/SC3 confirmed (the orchestrator integration tests for alias/projection/star are green and the real-shell CLI smoke matches).

## Task Commits

Each task was committed atomically (Task 1 followed TDD: test RED -> feat GREEN):

1. **Task 1: Add --no-alias to bagq query and forward it** (TDD)
   - `4ed0e76` (test — RED: 3 failing `-k no_alias` CLI tests)
   - `cd32af2` (feat — GREEN: `--no-alias` option + `alias=not no_alias` forwarding + docstring note)
2. **Task 2: Phase gate — full suite + ruff + offline-guard**
   - `41e037c` (style — ruff-format of the `--no-alias` test invocation surfaced by the gate's `ruff format --check`)

**Plan metadata:** committed separately (`docs(10-04): ...` — SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `packages/bagq/src/bagq/cli.py` — added `no_alias: Annotated[bool, typer.Option("--no-alias", help="Disable the built-in alias pack (e.g. vx → twist.twist.linear.x).")] = False` to the `query` command signature (after `--plot`); changed `result = run_query(sql, reader)` to `result = run_query(sql, reader, alias=not no_alias)`; added a docstring paragraph noting aliases are on by default, `--no-alias` disables them, and projection pushdown is always-on/transparent (no flag). The top-level imports (typer/rich/click only), the `_PlotCommand` class, and the lazy `run_query` import are unchanged.
- `tests/test_cli_query.py` — appended 3 CliRunner tests tagged `-k no_alias`, reusing the existing `ros1_bag` session fixture and `runner`: `test_query_no_alias_default_expands_vx` (aliases on by default -> exit 0, `linear.x` header + `0.0` value rendered), `test_query_no_alias_flag_disables_expansion` (`--no-alias` -> exit 1, output names `vx`, `result.exception` is `SystemExit` and not `ValueError` — the no-traceback convention), and `test_query_help_lists_no_alias_option` (`--no-alias` appears in `bagq query --help`).

## Decisions Made

- **One option, one keyword — no more.** The plan called for a strictly thin surface, and that is what shipped: a single `--no-alias` boolean and a single `alias=not no_alias` keyword on the existing `run_query` call. No business logic entered the CLI; the orchestrator (10-03) remains the sole owner of the alias rewrite and the trusted-SQL boundary (decision 1, API-first).
- **`--no-alias` reuses the vetted error boundary, introduces none.** A `--no-alias` query naming a non-column flows through DuckDB's binder -> `query()`'s `BinderException -> UnknownColumnError` re-map -> the existing `@teaching_errors` (Phase 7 CLI-03) as a clean one-line stderr message + `Exit(1)`. No new rendering or format surface. The test pins the 07/09 no-traceback convention (`isinstance(result.exception, SystemExit)` and not a raw `ValueError`).
- **Default-on alias was already wired (10-03), so one RED test passed immediately.** `test_query_no_alias_default_expands_vx` exercises the aliases-on path, which 10-03 already delivered through `query()`'s `alias=True` default (the CLI's pre-existing `run_query(sql, reader)` call inherited it). The genuinely-new behavior — the `--no-alias` option and its clean-error path — is what failed RED ("No such option '--no-alias'") and was made GREEN by this plan. This is expected, not a fail-fast trip: the flag truly did not exist before this plan.

## Deviations from Plan

None — plan executed exactly as written. The only non-test edit beyond the option + keyword was the docstring note the plan's `<action>` explicitly requested. The `ruff format --check` in the gate (Task 2) collapsed this plan's multi-line `runner.invoke(...)` test call to a single line; that is a style fix on this plan's own edit (Task 2 `<action>` mandates fixing lint/format issues introduced by the plan), committed as `style(10-04): ...`, not a behavioral deviation.

## Threat Model Compliance

All `mitigate`-disposition threats in the plan's register are satisfied:

- **T-10-11 (Tampering — `--no-alias` flag handling):** the flag is a typer boolean; the body forwards `alias=not no_alias` (a Python bool). No string is built, no SQL is touched, the user's SQL argument is forwarded byte-for-byte to the orchestrator (the API-first thin pass-through). Confirmed by `grep -nE "alias=not no_alias"` and the unchanged trusted-SQL boundary.
- **T-10-12 (Information disclosure — error via the `--no-alias` path):** a `--no-alias` query naming a non-column raises `UnknownColumnError`, surfaced by the existing `@teaching_errors` as a clean teaching line (no traceback, no internal paths) — the same CLI-03 boundary shipped in Phase 7. Tested for a clean `Exit(1)` (no raw exception escapes) and demonstrated via the real binary: `Unknown column 'vx'. Columns in cmd_vel: ...`.
- **T-10-SC (Tampering — installs):** zero new packages. `cli.py` adds no module-top import; `run_query` stays lazy-imported. No install task ran, so no package-legitimacy checkpoint applied.

## Issues Encountered

None. The full suite is green (316 passed, 97.73% coverage — exactly the 313 baseline + 3 new CLI tests), the offline-guard suite is green (10 passed; importing `bagq.cli` pulls no `rosbags`/`pyarrow`/`duckdb`), and ruff check + format --check are clean across all 53 files. A momentary tooling friction (`-p no:cov` left the addopts `--cov*` args unrecognized, and the offline-guard path was `tests/` not `packages/rosbagger-core/tests/`) was resolved by using `--no-cov` at the correct repo-root path — no code or test impact.

## Verification Evidence

- Task 1 verify: `PYTHONPATH="" .venv/bin/python -m pytest tests/test_cli_query.py -k no_alias -x` -> **3 passed** (RED first showed "No such option '--no-alias'", exit 2; GREEN after the option was added).
- Acceptance greps: `grep -nE "alias=not no_alias" packages/bagq/src/bagq/cli.py` -> matches (line 399); `grep -n "no-alias" packages/bagq/src/bagq/cli.py` -> the option declaration; `grep -nE "^import pyarrow|^import duckdb|^from rosbagger_core|^import rosbagger_core" packages/bagq/src/bagq/cli.py` -> nothing (offline invariant); `from rosbagger_core.backend.query import query as run_query` -> still lazy in the body.
- Full suite: `PYTHONPATH="" .venv/bin/python -m pytest -q` -> **316 passed, 97.73% coverage** (≥80% gate met; `cli.py` fully covered).
- Lint: `PYTHONPATH="" .venv/bin/ruff check .` -> clean; `PYTHONPATH="" .venv/bin/ruff format --check .` -> clean (53 files).
- Offline-guard: `PYTHONPATH="" .venv/bin/python -m pytest tests/test_offline_guard.py -x --no-cov` -> **10 passed**; a direct `import bagq.cli` leaks no `rosbags`/`pyarrow`/`duckdb`.
- Phase SC1/SC2/SC3: the orchestrator integration tests `tests/test_backend_query.py -k "alias or projection or star"` -> **18 passed**; real-shell SC1 via the actual `bagq` binary: `bagq query "SELECT vx FROM cmd_vel" BAG` -> a `linear.x` table `[0.0, 1.0, 2.0]`, exit 0; `bagq query --no-alias "SELECT vx FROM cmd_vel" BAG` -> `Unknown column 'vx'. Columns in cmd_vel: ...`, exit 1, no traceback.

## Known Stubs

None — this plan adds one boolean CLI option forwarded to an already-wired-and-tested orchestrator keyword. No placeholder values, no unwired data sources, no TODO/FIXME introduced.

## Threat Flags

None — the change introduces no new network endpoint, auth path, file-access pattern, or schema/trust-boundary surface. It forwards a Python bool to an existing API and reuses the existing `@teaching_errors` rendering.

## Next Phase Readiness

- **PHASE 10 COMPLETE (4/4).** QURY-08 (alias pack) and QURY-09 (projection pushdown) are delivered end-to-end with their CLI surface: `bagq query` carries `--no-alias` (aliases on by default), and projection is always-on/transparent. SC1 (alias resolves), SC2 (projection loads only referenced columns), and SC3 (single-column query doesn't materialize unreferenced/heavy columns) are all confirmed; the full suite + ruff + offline-guard gate is green with no regression.
- **Standing project blocker unchanged (not introduced by this plan):** a HUMAN must `git push origin main && git push origin v0.1.0` and observe GitHub Actions green to finalize the v0.1 release (origin = https://github.com/AllenDevaraj/rosbagger.git). This phase's work is local-gate-verified (the strongest available proxy that a pushed CI run will pass).

## Self-Check: PASSED

- Files exist: `packages/bagq/src/bagq/cli.py`, `tests/test_cli_query.py`, `.planning/phases/10-query-ergonomics/10-04-SUMMARY.md` — all FOUND.
- Commits exist: `4ed0e76` (Task1 RED), `cd32af2` (Task1 GREEN), `41e037c` (Task2 style) — all FOUND in git log.
- `cli.py` `contains: "no-alias"` (artifact check) — present (option declaration + docstring + comment). `alias=not no_alias` key-link present (line 399).
- `tests/test_cli_query.py` `contains: "no_alias"` — present (3 tests: `test_query_no_alias_default_expands_vx`, `test_query_no_alias_flag_disables_expansion`, `test_query_help_lists_no_alias_option`).
- TDD gate sequence verified: the `test(...)` RED commit (`4ed0e76`) precedes its `feat(...)` GREEN commit (`cd32af2`).

---
*Phase: 10-query-ergonomics*
*Completed: 2026-05-23*
