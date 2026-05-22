---
status: passed
phase: 07-cli-teaching-errors
verified: 2026-05-22
method: inline (gsd-verifier disabled; orchestrator verified must-haves against the live codebase + ran the suite + CR-01 fixed before completion)
must_haves_total: 3
must_haves_verified: 3
plans_complete: 2
requirements: [CLI-01, CLI-02, CLI-03, CLI-04]
---

# Phase 07: CLI & Teaching Errors — Verification

Phase goal: wire `query`/`info`/`tables` into the `bagq` CLI with errors that teach.

## Success Criteria (verified against the live codebase + fixtures)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | `bagq query "<SQL>" BAG...` works end-to-end from the shell (CLI-01) | real-shell `python -m bagq query ... BAG` exit 0; `teaching_errors` wrapper → typed errors print cleanly + `Exit(1)` (no traceback); `bagq/__main__.py` added | ✓ |
| 2 | Unknown table → available topics (did-you-mean); unknown column → that table's columns (CLI-02/03) | "Unknown table 'cmdvel'. Did you mean: cmd_vel?"; "Unknown column 'bogus_col'. Columns in cmd_vel: t, t_ns, stamp, topic, linear.x, ..." | ✓ |
| 3 | Unresolvable custom msg → registration guidance (CLI-04) | def-less bag (`write_def_less_bag`) via `bagq info` → exit 1 + "This bag has no embedded message definitions ... cannot be resolved" + registration hint | ✓ |

## Automated Checks (`PYTHONPATH=""`)

- `uv run pytest`: **255 passed, 97.82% coverage** (gate 80%); `errors.py` 100%
- ruff check + format: clean (49 files); offline guard extended + green (`import rosbagger_core.errors` pulls no duckdb/sqlglot/pyarrow/rosbags — difflib only)
- Carry-forward from Phase 6 FIXED here: WR-02 (`--format csv` now buffered + portable, CliRunner-capturable, `/dev/stdout` dropped), WR-01 (`splitext(basename)` extension parse)

## Code-Review Findings (07-REVIEW.md)

- **CR-01 (CRITICAL) — FIXED** (`cf2a637`/`ff33ac8`): `query()` caught `duckdb.BinderException` by type and ALWAYS mapped to `UnknownColumnError`, so a misgrouped query (`SELECT "linear.x", COUNT(*) FROM cmd_vel`) was mislabeled "Unknown column '?'". Now re-maps ONLY when the `_BINDER_COL` regex matches a real unknown column; otherwise re-raises the original `BinderException`. Regression test added; backend still closes on both paths. (Incidentally closed IN-01 — dropped the dead `"?"` fallback.)
- WARNING (advisory, open): `UnresolvedTypeError` relies on a substring match of the rosbags message (brittle if rosbags changes wording — pinned for this milestone); `--plot` errors (matplotlib-missing `RuntimeError`, no-numeric-cols `ValueError`) aren't caught by `teaching_errors`, so they traceback rather than print cleanly; a now-unused `/dev/stdout`-era code path may remain in `output/export.py`.
- INFO: weak `!= 0`-only assertions in a couple of error tests; a missing negative test.

Resolve advisory items with `/gsd:code-review 07 --fix`, or fold the `--plot`-clean-error + dead-path cleanup into a later polish.

## Notes

- API-first preserved: typed framework-free `ValueError` subclasses in stdlib-only `rosbagger_core/errors.py`; the `bagq` CLI owns presentation. CI execution still pending push/`gh` auth; suite green locally. Local runs need `PYTHONPATH=""`.

## Verdict

**PASSED** — all 3 success criteria verified; CLI-01..04 delivered by 255 ROS-free tests at 97.82% coverage. `bagq query`/`info`/`tables` run end-to-end with errors that teach (did-you-mean tables, column listing, custom-msg registration guidance). The critical BinderException over-catch (CR-01) was fixed with a regression test before completion, so misgrouped/other SQL errors surface truthfully instead of being mislabeled.
