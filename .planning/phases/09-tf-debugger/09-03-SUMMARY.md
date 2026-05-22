---
phase: 09-tf-debugger
plan: 03
subsystem: tf-cli
tags: [tf, tf2, bagq, cli, rich, teaching-errors, gap-rendering, offline, TF-01]

# Dependency graph
requires:
  - phase: 09-tf-debugger
    plan: 01
    provides: "write_tf_bag fixture (the /tf + /tf_static bag with a seeded ~800ms odom->base_link gap + a clean base_link->laser edge + a latched static map->odom) in all three formats — the SC1/SC2/SC3 test artifact"
  - phase: 09-tf-debugger
    plan: 02
    provides: "rosbagger_core.tf.collect_tf_report(reader, *, gap_multiplier=5.0, gap_ms=None) -> TfReport + frozen TfReport/EdgeReport/GapReport + rosbagger_core.errors.NoTransformsError — the entire TF-01 domain logic the CLI renders"
  - phase: 07-errors
    provides: "bagq teaching_errors wrapper (the one-import + one-except widening recipe) + the no-traceback Exit(1) contract; rosbagger_core.errors house style"
  - phase: 04-inspect
    provides: "bagq cli.py house style — @app.command()+@teaching_errors, lazy core import in the body, with RosbagsReader(bags), _render_* rich tables with em-dash for missing, _human_size presentation analog"
  - phase: 02-reader
    provides: "RosbagsReader(bags) context manager the tf command opens"
provides:
  - "bagq tf BAG [BAG...] — the user-facing TF surface (TF-01): a thin rich renderer over collect_tf_report printing a 'TF edges' summary table + a 'TF gaps' dropout timeline; --gap-multiplier / --gap-ms / --format table|json; NoTransformsError surfaces as a clean Exit(1) via the widened teaching_errors"
  - "_render_tf_report(report, console=None) + _human_dur(ns) presentation helpers in bagq/cli.py (the TF analog of _render_bag_info / _human_size)"
  - "tests/test_tf.py — fixture-backed SC1/SC2/SC3 proof parametrized over ROS 1 + ROS 2 sqlite3 + ROS 2 MCAP, plus the algorithm-knob / NoTransformsError / CLI table+json+error tests"
  - "tests/test_offline_guard.py extended for the TF module (import rosbagger_core.tf pulls no heavy stack and no rosbags)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_human_dur(ns): presentation-only ns->human (sub-second as integer/1-decimal ms, >=1s as 2-decimal s); the API keeps raw ns. The 09-01 seeded 800_000_000 ns gap renders exactly as '800ms'"
    - "Two-table TF render (Decision 8 / RESEARCH proposal): header line ('N frames, N dynamic, N static · span') + 'TF edges' table (parent/child/kind/count/rate(Hz)/max gap/gaps) + 'TF gaps' timeline (parent → child / gap / at (bag t) / at (abs ns)); em-dash for every missing field; 'no gaps detected' line instead of an empty gaps table"
    - "teaching_errors widened by ONE (NoTransformsError) in the lazy import + the except tuple — the same 07-02 recipe; the deliberate absence of `except Exception` is preserved"
    - "bagq tf --format json: dataclasses.asdict(report) with the frames frozenset coerced to a sorted list (consistent with bagq query --format json)"
    - "rate(Hz) derived presentation-side (samples / span_s) — '—' for static / single-sample / non-positive-span edges; the API stores no rate"

key-files:
  created:
    - "tests/test_tf.py — self-contained harness (repo-root sys.path insert; session tmp_path_factory fixtures per format) proving SC1/SC2/SC3 across all three formats; 17 tests"
  modified:
    - "packages/bagq/src/bagq/cli.py — added the tf typer command + _render_tf_report + _human_dur; widened teaching_errors (one import + one except entry) for NoTransformsError; module + wrapper docstrings updated; top level stays typer/rich/click-only"
    - "tests/test_offline_guard.py — added test_import_tf_does_not_pull_heavy_query_stack + test_import_tf_does_not_pull_rosbags (existing tests untouched)"

key-decisions:
  - "bagq tf lives as a subcommand on the existing bagq app (Decision 1) — NO new package, NO pyproject/uv.lock/addopts/console-script edits; auto-covered by the existing --cov=rosbagger_core + --cov=bagq gate"
  - "_human_dur: sub-second renders as ms (integer ms when whole), >=1s as 2-decimal seconds — so the seeded 800ms dropout renders exactly '800ms' (the gap-row assertion target)"
  - "rate(Hz) is a presentation-only derivation (samples / whole-bag span) — the analyzer stores none; '—' for static/single-sample/zero-span edges (no ZeroDivision, no misleading rate)"
  - "Empty gap timeline prints a 'no gaps detected' line, never an empty rich table (mirrors _render_table_schemas' 'no topics' guard / threat T-09-09)"
  - "Defensive tf.py guards `expected <= 0` (line 297-310) and the per-delta `d <= 0: continue` (321) are left uncovered (3 lines, tf.py at 97%): they are unreachable given the >0 pre-filter, and 09-02 deliberately added no coverage pragmas — the >=80% gate is met at 97.76%"

patterns-established:
  - "TF CLI mirrors info/tables/query exactly: @app.command()+@teaching_errors, lazy `from rosbagger_core.tf import collect_tf_report` + `from rosbagger_core.reader import RosbagsReader` in the body, `with RosbagsReader(bags) as reader`, a _render_* rich helper, em-dash for missing — differing only in the second (gaps) table and the json sink"
  - "tests/test_tf.py is a self-contained harness (own repo-root sys.path insert + own session tmp_path_factory fixtures, one bag dir per format) standing alone like test_reader.py; parametrized over [(True,'sqlite3'),(False,'sqlite3'),(False,'mcap')] so SC3 exercises all three formats"

requirements-completed: [TF-01]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 9 Plan 03: TF CLI (`bagq tf`) + SC1/SC2/SC3 Proof Summary

**`bagq tf BAG` — the user-facing TF surface (TF-01): a thin rich renderer over `collect_tf_report` that prints a per-edge "TF edges" summary table plus a "TF gaps" dropout timeline (the seeded `odom → base_link` 800ms dropout shown as a gap row), with `--format json` and a clean `NoTransformsError` Exit(1) on a non-TF bag. The fixture-backed `tests/test_tf.py` proves Phase 9's three Success Criteria across ROS 1 + ROS 2 sqlite3 + ROS 2 MCAP with no ROS install, and the offline guard is extended for the TF module.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-22T23:49:40Z
- **Completed:** 2026-05-22T23:55:00Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- **`bagq tf` subcommand** added to `packages/bagq/src/bagq/cli.py` — mirrors `info`/`tables`/`query`: `@app.command()` + `@teaching_errors`, lazy `collect_tf_report` + `RosbagsReader` import inside the body, `with RosbagsReader(bags) as reader`. Signature: `bags`, `--gap-multiplier` (5.0), `--gap-ms` (None), `--format table|json`. `--format json` emits `dataclasses.asdict(report)` with the `frames` frozenset coerced to a sorted list; a bad `--format` raises `typer.BadParameter` (mirrors `query`).
- **`teaching_errors` widened by one** — `NoTransformsError` added to the lazy `from rosbagger_core.errors import (...)` tuple AND to the `except (...)` tuple; the wrapper body and the deliberate absence of `except Exception` are unchanged (the 07-02 recipe).
- **`_render_tf_report` + `_human_dur`** presentation helpers added (the TF analog of `_render_bag_info` / `_human_size`): a header line (`N frames, N dynamic edges, N static edges · span 0.00s–Xs`), a titled "TF edges" rich table (parent/child/kind/count/rate(Hz)/max gap/gaps; em-dash for missing), and a titled "TF gaps" timeline (`parent → child` / gap / `at (bag t)` / `at (abs ns)`), replaced by a "no gaps detected" line when clean. `_human_dur` renders sub-second as ms (integer ms when whole) so the seeded `800_000_000` ns dropout reads exactly `800ms`.
- **`tests/test_tf.py`** created (17 tests) — a self-contained harness proving SC1 (graph), SC2 (gaps + boundary + bag-relative clock), the `--gap-ms` / large-`--gap-multiplier` knobs, the `NoTransformsError` empty case, single-sample + all-duplicate-timestamp edge guards, and the CLI table+json+error+`no gaps`+bad-format paths. SC1/SC2 are parametrized over all three formats so SC3 exercises ROS 1 + ROS 2 sqlite3 + ROS 2 MCAP.
- **`tests/test_offline_guard.py`** extended with `test_import_tf_does_not_pull_heavy_query_stack` (tf.py is stdlib-only top) and `test_import_tf_does_not_pull_rosbags` (the fresh-subprocess rosbags-leak check) — no existing offline-guard test weakened.
- **Offline-light invariant held both ways** — `import bagq.cli` pulls no `rosbags`/`duckdb`/`pyarrow`/`sqlglot` at module scope (verified), and `import rosbagger_core.tf` pulls neither the heavy stack nor `rosbags`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the bagq tf subcommand + widen teaching_errors** — `36387fe` (feat)
2. **Task 2: Fixture-backed SC1/SC2/SC3 test suite + offline-guard extension** — `7ba7b00` (test)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `packages/bagq/src/bagq/cli.py` (modified) — `tf` typer command + `_render_tf_report` + `_human_dur`; `teaching_errors` lazy import + `except` tuple each gained `NoTransformsError` (no `except Exception` added); module docstring now lists `bagq tf`; wrapper docstring notes the 09-03 widening. Top-level imports remain typer/rich/click-only.
- `tests/test_tf.py` (created) — repo-root `sys.path` insert (scoped); `write_tf_bag`/`make_all_fixtures` import; session `tf_bags` (one bag dir per format) + `non_tf_bag` fixtures; parametrized SC1/SC2 over `[(True,'sqlite3'),(False,'sqlite3'),(False,'mcap')]`; the knob/error/CLI tests; module docstring documents the local `PYTHONPATH=""` run requirement (no env override baked into code).
- `tests/test_offline_guard.py` (modified) — two TF additions appended after `test_import_errors_does_not_pull_rosbags`, reusing the existing `_heavy_modules_after_import` helper and the fresh-subprocess pattern.

## Decisions Made

- **`bagq tf` subcommand, not a new package** (Decision 1) — no `pyproject.toml`/`uv.lock`/`addopts`/console-script edits; `cli.py` is auto-covered by the existing `--cov=bagq` gate, `tf.py` by `--cov=rosbagger_core`.
- **`_human_dur` ms/seconds split** — sub-second as ms (integer ms when whole, one decimal otherwise), `>=1s` as 2-decimal seconds; chosen so the seeded `800_000_000` ns gap renders exactly `800ms` (the gap-row assertion target) while a `12.40s` dropout reads naturally.
- **`rate(Hz)` is a presentation-only derivation** (`samples / whole-bag span`), `—` for static / single-sample / non-positive-span edges — the analyzer stores no rate (consistent with the API keeping raw values; no ZeroDivision and no misleading rate on a static edge).
- **Empty gap timeline prints `no gaps detected`**, never an empty table (mirrors `_render_table_schemas`' `no topics` guard; threat T-09-09).
- **`--format json` coerces only the `frames` frozenset** to a sorted list; every other field is JSON-native via `dataclasses.asdict`, so the payload round-trips through `json.loads` in the test.

## Deviations from Plan

None of substance — plan executed as written. One in-scope correction during test authoring:

### Auto-fixed Issues

**1. [Rule 1 - Test data bug] All-duplicate-timestamp coverage test used a partly-positive delta**
- **Found during:** Task 2 (adding a targeted test for the `tf.py` all-duplicate-timestamp defensive branch to lift coverage off 95%).
- **Issue:** My first version published three identical stamps plus one EARLIER stamp `(1e9, 1e9, 1e9, 999e6)`. After the analyzer's defensive `sorted()`, the sequence is `[999e6, 1e9, 1e9, 1e9]`, whose FIRST delta (`1_000_000` ns) is positive and survives the `> 0` pre-filter — so `expected_ns` was `1_000_000`, NOT `None`, and the `assert expected_ns is None` failed. The analyzer was correct; my test's premise (that backwards-then-duplicate yields an empty `diffs`) was wrong.
- **Fix:** Changed the stub to publish four IDENTICAL log times (`1_000_000_000` ×4) so every inter-arrival delta is exactly 0 and `diffs` is genuinely empty — the real all-duplicate case that exercises the `if not diffs:` branch (tf.py lines 280-293, T-09-03). Renamed the test to `test_all_duplicate_timestamps_no_false_gap_no_zerodivision`.
- **Files modified:** `tests/test_tf.py` (test-only; production code unchanged).
- **Commit:** `7ba7b00` (fixed before the Task 2 commit).

The plan's `<interfaces>` block (the cli house style, the `collect_tf_report` signature, the `TfReport`/`EdgeReport`/`GapReport` field names, the `NoTransformsError` message, the test-harness conventions) matched the live source exactly — no API drift, no missing functionality, no architectural change.

## Issues Encountered

None beyond the test-data fix above. The 09-01 fixture produced exactly the seeded structure in all three formats; the `bagq tf` render matched the RESEARCH "Output / Table Format Proposal" on first run (header + "TF edges" + "TF gaps" with the `odom → base_link` / `800ms` / `t=0.70s` gap row).

## Threat Model Compliance

- **T-09-08 (Information disclosure — missing/non-TF bag):** mitigated as planned — `teaching_errors` (now widened for `NoTransformsError`) catches the no-TF case and `FileNotFoundError` (missing path), printing one red stderr line + `Exit(1)` with NO traceback. Asserted by `test_cli_tf_no_transforms_exits_one_cleanly`: `isinstance(result.exception, SystemExit)` AND `not isinstance(..., NoTransformsError)` (the raw domain error did not escape).
- **T-09-09 (Tampering — render path on edge values):** mitigated — `_render_tf_report` formats only strings (frame ids) and ints (ns, via `_human_dur`); `—` guards every `None` field (static/single-sample edges' rate/max-gap), and an empty gaps list prints `no gaps detected` instead of crashing on an empty table. No eval / format-injection surface.
- **T-09-10 (DoS — `--format json` over a large report):** accepted (unchanged) — `dataclasses.asdict` over a bounded report (one entry per edge/gap); the analyzer already bounded the stream.
- **T-09-SC (installs):** honored — ZERO new packages. `cli.py` adds only stdlib `json`/`dataclasses` + the existing typer/rich; `tests/test_tf.py` adds only `pytest`/`typer.testing` (already dev deps). No install task, no `addopts`/`uv.lock` edit.

**No new threat surface** beyond the planned `tf` command (already covered by T-09-08/09/10/SC). No new network endpoints, auth paths, file-access patterns, or trust-boundary schema changes were introduced.

## Verification Evidence

- **Task 1 verify** (`PYTHONPATH="" uv run pytest tests/test_tf.py -q -k cli`): **5 passed, 12 deselected**, exit 0 — the CLI table (`odom → base_link` + `800ms` + `TF edges`/`TF gaps`), `--format json`, the clean no-TF `Exit(1)`, the `no gaps detected` branch, and the bad-format rejection.
- **Task 2 verify** (`PYTHONPATH="" uv run pytest tests/test_tf.py tests/test_offline_guard.py -q`): all TF + offline-guard tests pass (the only "fail" in isolation is the project coverage gate, which is evaluated over the FULL suite — see below).
- **SC1 (all three formats):** `report.frames == {"map","odom","base_link","laser"}`; `("map","odom")` `static is True`; `("odom","base_link")` and `("base_link","laser")` `static is False`.
- **SC2 (all three formats):** exactly one `("odom","base_link")` gap within ±1 ns of `800_000_000`, `expected_ns == 100_000_000`; zero gaps on `("base_link","laser")`; none on the static `("map","odom")`; `gap.at_rel_ns == gap.at_ns - report.start_ns`; `--gap-ms=300` still flags the dropout; `--gap-multiplier=100` suppresses it.
- **SC3 (offline):** the suite runs under `PYTHONPATH=""` (CI is ROS-free); `import rosbagger_core.tf` leaks no heavy stack and no `rosbags` (both new offline-guard tests green); `bagq tf` prints the edge/gap tables.
- **`NoTransformsError`:** raised on the non-TF `make_all_fixtures` bag with `.available` non-empty and the message naming `/tf` and `/cmd_vel`.
- **Lint/format:** `PYTHONPATH="" uv run ruff check .` clean; `PYTHONPATH="" uv run ruff format --check .` → 51 files already formatted.
- **Full suite:** `PYTHONPATH="" uv run pytest -q` → **274 passed**, total coverage **97.76%** (≥80% gate). `tf.py` at **97%** (3 unreachable defensive lines uncovered, no pragma — consistent with 09-02); `errors.py` and `cli.py` `tf` paths fully covered.

## TF-01 Status

**TF-01 is COMPLETE.** The requirement spanned 09-01 (fixture), 09-02 (analysis core), and 09-03 (CLI surface + SC1/SC2/SC3 proof). The user-facing `bagq tf` command renders the dropout timeline and the SC1/SC2/SC3 tests prove the graph + gap detection on a rosbags fixture across all three formats with no ROS install. Marked complete in this plan's frontmatter and REQUIREMENTS.md.

## Next Phase Readiness

- **Phase 9 is COMPLETE (3/3).** `bagq tf` is the shipped TF debugger surface; the analyzer (`collect_tf_report` + `TfReport`) is API-first and is the natural seam for the Phase 14 GUI to consume (it already exposes `--format json`).
- **No blockers introduced.** The standing milestone-level blocker (the v0.1 push pending `gh`/push auth) is unrelated to Phase 9.

## Self-Check: PASSED

- FOUND: packages/bagq/src/bagq/cli.py (contains `def tf(` + `def _render_tf_report` + `def _human_dur`)
- FOUND: tests/test_tf.py (contains `collect_tf_report` + `parametrize`)
- FOUND: tests/test_offline_guard.py (contains `rosbagger_core.tf`)
- FOUND: commit 36387fe (Task 1, feat)
- FOUND: commit 7ba7b00 (Task 2, test)
- FOUND: .planning/phases/09-tf-debugger/09-03-SUMMARY.md

---
*Phase: 09-tf-debugger*
*Completed: 2026-05-22*
