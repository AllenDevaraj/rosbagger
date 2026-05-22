---
phase: 02-bag-reader-layer
plan: 03
subsystem: testing
tags: [pytest, rosbags, fixtures, ros1, ros2, mcap, reader, coverage]

# Dependency graph
requires:
  - phase: 02-01
    provides: BagReader ABC + frozen Message record (the contract under test)
  - phase: 02-02
    provides: RosbagsReader (AnyReader adapter) + reader/__init__ re-export (the implementation under test)
  - phase: 01-03
    provides: tools/make_fixtures.py (ROS1/ROS2-sqlite/MCAP fixture-bag generator)
provides:
  - Fixture-backed regression suite for RosbagsReader across all 3 formats (tests/test_reader.py)
  - Verified-fact resolution of research Open Question 1 / Assumption A1 (multi-ROS2 bags merge as one dataset)
  - Restored project-wide coverage above the >=80% gate (96.63% total)
affects: [phase-03-schema, phase-04-inspect, phase-05-query]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Self-contained reader test harness: repo-root sys.path insert + session-scoped tmp_path_factory fixture (mirrors tests/test_fixtures.py; does not reuse its fixture)"
    - "PYTHONPATH='' is a run-time prefix documented in the module docstring only — never baked into committed code or CI"
    - "Multi-bag fixtures write each same-format bag into its own tmp dir to avoid the fixed ros2_sqlite dir-name collision"

key-files:
  created:
    - tests/test_reader.py
  modified: []

key-decisions:
  - "Test-only plan: no source changed — tests validate the pre-existing 02-02 implementation against verified fixture facts"
  - "Stamp assertions match the per-message series exactly: /cmd_vel -> None, /imu+/image -> int, only the FIRST /imu (lowest t_ns) == 1_000_000_000 (NOT all equal)"
  - "No coverage pragmas added (per plan); the 3 uncovered rosbags_reader.py lines are defensive guards far below the 96.63% total"
  - "Added an optional mixed-format test asserting the raw AnyReaderError surfaces (Pitfall 1), since v1 fails closed"

patterns-established:
  - "Parametrized FORMATS = (ros1, ros2_sqlite, ros2_mcap) sweep so every format runs the same record/stamp/metadata assertions"
  - "Merge tests assert both summed message_count (18) and global ascending t_ns ordering for ROS2 and ROS1"

requirements-completed: [READ-01, READ-02, READ-03, READ-04, READ-05]

# Metrics
duration: 4min
completed: 2026-05-22
---

# Phase 2 Plan 03: Fixture-Backed RosbagsReader Test Suite Summary

**A ROS-free regression suite proving RosbagsReader opens ROS1/ROS2-sqlite/ROS2-MCAP, yields Message records with exact stamp derivation, and merges multiple same-format bags into one time-ordered dataset — restoring project coverage to 96.63%.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-22T08:02Z (after the 02-03 must_haves correction commit)
- **Completed:** 2026-05-22T08:06Z
- **Tasks:** 2
- **Files modified:** 1 (tests/test_reader.py created)

## Accomplishments

- Single-format suite: opens all three target formats through `RosbagsReader`, asserts exactly 9 `Message` records each, the three expected topics `{/cmd_vel, /imu, /image}`, well-shaped record fields (`int t == t_ns`, non-None `msg`, non-empty `msgtype`), metadata-only `topics`/`connections` access, and a read-before-open `RuntimeError` guard (READ-01/02/03/04).
- Stamp derivation asserted exactly across all formats: headerless `/cmd_vel` -> `None`; header-bearing `/imu`+`/image` -> `int`; first `/imu` (lowest `t_ns`) == `1_000_000_000` (the per-message series `[1e9, 2.1e9, 3.2e9]`, not a constant).
- Multi-bag merge suite (READ-05): two same-format ROS2 sqlite bags AND two ROS1 bags each read as one dataset of 18 records with globally ascending `t_ns`; merged ROS2 topics report summed `msgcount=6` per topic. This turns research Open Question 1 / Assumption A1 (multi-ROS2 merge) into a verified, committed fact.
- Mixed ROS1+ROS2 in one reader is asserted to raise (Pitfall 1; raw `AnyReaderError` surfaces in v1).
- Restored the project-wide `--cov-fail-under=80` gate: full suite is 30 tests green at **96.63%** total coverage; offline-import guard still 2/2.

## Task Commits

Each task was committed atomically:

1. **Task 1: Single-format reader tests (READ-01/02/03/04)** - `b97c024` (test)
2. **Task 2: Multi-bag merge tests — two ROS2 + two ROS1 (READ-05)** - `e09fae6` (test)

**Plan metadata:** committed separately with STATE.md + ROADMAP.md + REQUIREMENTS.md.

_Note: This is a test-only plan; the implementation under test predates these tests (02-02), so the TDD RED/GREEN collapses — tests were written against the existing, correct implementation and pass on first run._

## Files Created/Modified

- `tests/test_reader.py` - 230-line fixture-backed regression suite for `RosbagsReader`: parametrized single-format tests (open/9-records/topics/fields/stamp/metadata + read-before-open guard) and multi-bag merge tests (two-ROS2, two-ROS1, summed counts, mixed-format raise). Self-contained harness mirrors `tests/test_fixtures.py` (repo-root `sys.path` insert + session `tmp_path_factory` fixture).

## Decisions Made

- **Test-only, no source touched.** The plan's `files_modified` is `tests/test_reader.py` alone; the reader implementation (02-02) is correct, so tests assert verified fixture facts rather than driving new code.
- **Exact stamp series, not a constant.** Per the orchestrator's verified correction (re-confirmed empirically this plan via a direct `RosbagsReader` probe), `/imu` stamps are `[1_000_000_000, 2_100_000_000, 3_200_000_000]`. The test asserts `/cmd_vel -> None`, `/imu`+`/image` -> `int`, and only the first `/imu` (lowest `t_ns`) `== 1_000_000_000`. An "all `/imu` == 1e9" assertion would have failed.
- **No coverage pragmas.** Plan forbids them. `rosbags_reader.py` shows 3 uncovered lines (line 47 = the missing-`sec`/`nanosec` defensive branch; lines 127/134 = the `topics`/`connections` before-open `RuntimeError` guards). All are defensive paths; total coverage is 96.63%, far above the gate, so no pragmas were warranted.
- **Mixed-format test included (optional in plan).** Asserts `RosbagsReader([ros1, ros2]).open()` raises, documenting the Pitfall 1 constraint as v1 fail-closed behavior.
- **Per-bag tmp dirs for merge fixtures.** `write_ros2_sqlite_bag` always names the dir `ros2_sqlite`, so each of the two bags is written into its own `tmp_path_factory.mktemp(...)` directory to avoid a collision (matches 02-RESEARCH.md §3).

## Deviations from Plan

None - plan executed exactly as written.

(Two minor, in-spec adjustments worth noting, neither a deviation: (1) the `tools`/`rosbagger_core` import ordering was set by `ruff --fix` to match the project's isort grouping; (2) Task 1 was committed importing only `make_all_fixtures`, with `write_ros1_bag`/`write_ros2_sqlite_bag` added in Task 2 when first used — this keeps each task's commit ruff-clean, exactly as the plan sequences the two tasks.)

## Issues Encountered

- Initial ruff F401 on `write_ros1_bag`/`write_ros2_sqlite_bag` (imported in Task 1 but only used in Task 2). Resolved by importing them in Task 2 when first consumed, so Task 1's commit is ruff-clean and Task 2 re-adds them — aligned with the plan's task split.

## User Setup Required

None - no external service configuration required. Tests run fully offline; locally they require the `PYTHONPATH=""` run-time prefix to neutralize the host ROS-on-PYTHONPATH leak (documented in the test module docstring), but CI is ROS-free and needs no prefix.

## Next Phase Readiness

- Phase 2 (Bag Reader Layer) is complete: all three success criteria are proven by committed, ROS-free tests, and all five reader requirements (READ-01..05) are verified. The coverage gate is restored.
- Phase 3 (Message->Table Schema) can build on a fully tested `RosbagsReader`: it yields `Message(topic, t, t_ns, stamp, msgtype, msg)` records that Phase 3 will flatten into DuckDB columns (the fixtures already carry the forward-looking Twist/Imu/Image content QURY-02/03/04/07 need).
- No blockers. The two pre-existing concerns from prior plans are now resolved or unaffected: the coverage-gate dip is closed by this plan; the GitHub-push-auth and missing-GSD-agents concerns are infrastructure items, not code blockers.

## Self-Check: PASSED

- FOUND: `tests/test_reader.py`
- FOUND: `.planning/phases/02-bag-reader-layer/02-03-SUMMARY.md`
- FOUND commit: `b97c024` (Task 1)
- FOUND commit: `e09fae6` (Task 2)

---
*Phase: 02-bag-reader-layer*
*Completed: 2026-05-22*
