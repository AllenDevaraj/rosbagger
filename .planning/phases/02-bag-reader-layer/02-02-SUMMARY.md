---
phase: 02-bag-reader-layer
plan: 02
subsystem: reader
tags: [rosbags, anyreader, ros1, ros2, mcap, bag-reader, generator, offline]

# Dependency graph
requires:
  - phase: 02-01
    provides: "BagReader ABC (open/close/read + topics/connections + __enter__/__exit__) and frozen Message(topic, t, t_ns, stamp, msgtype, msg) in reader/base.py"
provides:
  - "RosbagsReader(BagReader): the v1 concrete reader — a thin adapter over rosbags.highlevel.AnyReader"
  - "Uniform stamp extraction (_stamp_ns): header.stamp -> ns for ROS1+ROS2, None for headerless messages"
  - "Lazy read() generator yielding Message records, time-ordered across all opened bags"
  - "topics/connections metadata exposure without deserialization (feeds Phase 4 Inspect)"
  - "Multi-bag pass-through to AnyReader's built-in merge (READ-05) with Path coercion at the boundary"
  - "reader/__init__.py re-exports RosbagsReader alongside BagReader + Message"
affects: [02-03 reader tests, phase-03 schema/query mapper, phase-04 inspect, phase-07 cli teaching-errors]

# Tech tracking
tech-stack:
  added: []  # rosbags 0.11.2 was locked in Phase 1; this plan installs NO new package
  patterns:
    - "Record-building adapter: iterate AnyReader.messages(), deserialize one msg at a time, yield Message"
    - "Pass-through multi-bag: hand a Sequence[Path] straight to AnyReader (no hand-rolled k-way merge/sort)"
    - "Duck-typed uniform stamp extraction (one code path for ROS1+ROS2; no isinstance, no secs/nsecs branch)"
    - "Module-level rosbags import isolated to rosbags_reader.py (NOT base.py / not top-level rosbagger_core)"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/reader/__init__.py

key-decisions:
  - "v1 lets AnyReaderError/FileNotFoundError propagate unchanged (fail closed); error re-wrapping deferred to Phase 7 (researcher Open Q2)"
  - "read() guards not-opened state with RuntimeError; topics/connections raise the same guard"
  - "default_typestore exposed as an optional passthrough (legacy bags) but not required by any Phase-2 criterion"
  - "No format detection / merge / sort hand-rolled — AnyReader owns all of it (anti-pattern avoided)"

patterns-established:
  - "Adapter glue over AnyReader: ~90% delegation; the project's only real work is Message-shape mapping + stamp derivation"
  - "Offline isolation: rosbags imports live only in this submodule, keeping import rosbagger_core ROS-free"

requirements-completed: [READ-01, READ-02, READ-03, READ-04, READ-05]

# Metrics
duration: 4min
completed: 2026-05-22
---

# Phase 2 Plan 02: RosbagsReader (AnyReader Adapter) Summary

**RosbagsReader(BagReader): a thin rosbags.highlevel.AnyReader adapter that opens ROS1 .bag / ROS2 sqlite3 / ROS2 MCAP through one interface and lazily yields Message records with uniform header.stamp-to-ns derivation.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-22T07:53:20Z
- **Completed:** 2026-05-22T07:57Z (approx)
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 edited)

## Accomplishments
- `RosbagsReader(BagReader)` implemented as impl #1 of the swappable seam: `open`/`close` manage the `AnyReader` lifecycle (idempotent `close`), inherits `__enter__`/`__exit__` from the base ABC.
- `read()` is a lazy generator yielding `Message(topic, t, t_ns, stamp, msgtype, msg)` — deserializing one message at a time, never list-materializing the bag (DoS-resistant per threat T-02-02-D2).
- `_stamp_ns` module helper: one duck-typed code path derives `header.stamp` -> nanoseconds for BOTH ROS1 and ROS2, returning `None` for headerless messages (the `/cmd_vel` Twist case).
- `topics`/`connections` properties expose metadata without deserialization (feeds Phase 4 Inspect); both carry a not-opened `RuntimeError` guard.
- Paths coerced to `Path` at the boundary (single path OR iterable accepted); a list of same-format bags is handed straight to `AnyReader`'s built-in heapq-merge (READ-05) — verified 18-message ascending-timestamp merge across two ROS1 bags.
- `reader/__init__.py` re-exports `RosbagsReader`; `import rosbagger_core` stays rosbags-free (offline guard 2/2 green).

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement RosbagsReader adapter over AnyReader in rosbags_reader.py** — `47efad4` (feat)
2. **Task 2: Re-export RosbagsReader from reader/__init__.py** — `1934b7f` (feat)

**Plan metadata:** (final docs commit — this SUMMARY + STATE.md + ROADMAP.md)

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` (created, 135 lines) — `RosbagsReader(BagReader)` + module-level `_stamp_ns`; the only place `import rosbags` lives in the package.
- `packages/rosbagger-core/src/rosbagger_core/reader/__init__.py` (modified) — added `from .rosbags_reader import RosbagsReader` and `"RosbagsReader"` to `__all__`.

## Decisions Made
- **Fail closed for v1:** `AnyReaderError` / `FileNotFoundError` propagate unchanged from `open()`. A project `BagReaderError` wrapper is the researcher's Open Question #2, deferred to Phase 7 / CLI-04 teaching-errors — not required by any Phase-2 criterion.
- **Not-opened guard:** `read()`/`topics`/`connections` raise a clear `RuntimeError("... before open()")` rather than `AttributeError` on `None`, so misuse is diagnosable.
- **`default_typestore` passthrough:** kept as an optional kwarg for legacy ROS2 bags lacking embedded defs, but modern bags embed their defs and need none.
- Transcribed the verified `_stamp_ns` / record-building logic from 02-RESEARCH.md Code Examples §2 verbatim rather than inventing it; no `heapq`/`sorted`/`.sort` and no ROS imports (`rclpy`/`rosbag2_py`/`rosidl_runtime_py`/`ament_index_python`) appear in the file.

## Deviations from Plan

None — plan executed exactly as written. No code-level deviation rules (1-4) were triggered; the implementation is a faithful transcription of the verified research logic against the existing `BagReader` contract.

Two **plan-authoring discrepancies** were found in verification scaffolding (documented here for the 02-03 test author and the verifier — they are NOT code defects, and no source code was changed to "work around" them):

1. **`/imu` stamp expected value in Task 1 acceptance criteria / `<verification>`.** The plan states "the `/imu` messages have `stamp == 1_000_000_000`". The fixture (`tools/make_fixtures.py:96`) actually writes `header.stamp` as `sec=(1+i), nanosec=(i*1e8)` per message, so the three `/imu` stamps are `[1_000_000_000, 2_100_000_000, 3_200_000_000]`. My `_stamp_ns` produces exactly these values — i.e. the code is correct against the verified formula AND the real fixture data; only the **first** `/imu` message is `1_000_000_000` (which is the single-message probe the research recorded). The plan/research generalized a one-message probe to all three. Smoke test asserts the fixture-accurate values and that `imu[0].stamp == 1_000_000_000`. The load-bearing assertion — `/cmd_vel` (headerless) `stamp is None` — holds exactly.

2. **Task 2 `<verify>` one-liner is internally self-contradictory.** It does `from rosbagger_core.reader import ... RosbagsReader` (which necessarily loads `rosbags`) and then asserts `'rosbags' not in sys.modules` **in the same process** — impossible by construction. The substantive checks pass: AC2 (`import rosbagger_core` alone does NOT load rosbags or the reader subpkg) verified in a fresh process, and the authoritative `tests/test_offline_guard.py` is green (2/2). The real invariant — top-level `import rosbagger_core` stays ROS/rosbags-free while `import rosbagger_core.reader` may load rosbags — holds and matches the offline-guard note. 02-03 should encode AC2 as the fresh-process check, not the contradictory one-liner.

---

**Total deviations:** 0 code deviations. 2 plan-authoring/test-scaffold discrepancies documented (no source workaround applied).
**Impact on plan:** None on the deliverable. All requirements (READ-01..05) met; the discrepancies are in expected-value bookkeeping in the verification text, flagged for 02-03 to encode correctly.

## Issues Encountered
- The literal `grep -qnE "heapq|sorted\(|\.sort\(|rclpy|rosbag2_py"` in the Task 1 `<verify>` line matched my **docstring/comment prose** (which explained that AnyReader does the merge and named the forbidden ROS modules), producing a false "FAIL". Resolved by rewording the docstrings to avoid the trigger tokens — the code never contained any hand-rolled sort/merge or ROS import. After the reword the `<verify>` line reports `OK` and ruff still passes.

## Verification Evidence
- `issubclass(RosbagsReader, BagReader)` true; `inspect.isgeneratorfunction(RosbagsReader.read)` true.
- All three formats (ROS1 .bag, ROS2 sqlite, ROS2 MCAP) open through one interface and yield 9 `Message`s each with topics `{/cmd_vel, /imu, /image}` (READ-01/02/03).
- `_stamp_ns`: `None` for headerless `SimpleNamespace()`; `1_000_000_000` for `sec=1,nanosec=0`; `2_000_000_500` for `sec=2,nanosec=500`.
- READ-05: two ROS1 bags -> 18 messages, `t_ns` globally ascending (AnyReader merge).
- Path coercion: bare `str` and `list[str]` accepted at construction; `read()` before `open()` raises the guard `RuntimeError`.
- `grep` confirms no `heapq`/`sorted`/`.sort`/ROS imports in `rosbags_reader.py`.
- `import rosbagger_core` does not load `rosbags`; `tests/test_offline_guard.py` 2/2 pass.
- Full suite `PYTHONPATH="" uv run pytest -q --no-cov`: 13 passed. `uv run ruff check packages/rosbagger-core/src/`: all checks passed.

## User Setup Required
None — no external service configuration required. (Local file-parsing library; `rosbags` already locked + installed.)

## Next Phase Readiness
- **02-03 (reader tests):** `RosbagsReader` is importable from `rosbagger_core.reader` and proven against all three fixture formats + a two-bag ROS1 merge. 02-03 should: (a) add the fixture-backed three-format coverage + the multi-ROS2 merge test (Open Q1 / A1), (b) assert the fixture-accurate `/imu` stamp series `[1e9, 2.1e9, 3.2e9]` (NOT a flat `1e9`), (c) encode the offline invariant as a fresh-process check on `import rosbagger_core`. This plan adds covered implementation code, so the project-wide `--cov-fail-under=80` gate (currently dipping by design since 02-01) self-resolves once 02-03's tests land.
- **No blockers.** The pre-existing CI coverage-gate dip noted in STATE.md is by design and unchanged by this plan.

## Self-Check: PASSED

- FOUND: `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py`
- FOUND: `.planning/phases/02-bag-reader-layer/02-02-SUMMARY.md`
- FOUND commit: `47efad4` (Task 1)
- FOUND commit: `1934b7f` (Task 2)

---
*Phase: 02-bag-reader-layer*
*Completed: 2026-05-22*
