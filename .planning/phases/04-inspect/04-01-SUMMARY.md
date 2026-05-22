---
phase: 04-inspect
plan: 01
subsystem: api
tags: [rosbags, rich, typer, dataclasses, pathlib, inspect, cli, anyreader]

# Dependency graph
requires:
  - phase: 02-bag-reader-layer
    provides: RosbagsReader/Message + the AnyReader-backed topics/connections metadata seam
  - phase: 01-foundation
    provides: bagq typer app, fixture generator (tools/make_fixtures.py), PYTHONPATH="" run convention, >=80% coverage gate
provides:
  - "rosbagger_core.inspect: backend-neutral BagInfo/TopicInfo + collect_bag_info(reader) reading O(1) AnyReader metadata only"
  - "RosbagsReader additive public properties: message_count, duration, start_time, end_time, typestore, paths (+ matching BagReader ABC declarations)"
  - "bagq info BAG... subcommand: rich topic table (topic/msgtype/count/Hz) + duration/count/size footer"
affects: [04-02, 05-query, 07-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "API-first inspect: all computation in rosbagger_core.inspect; bagq/cli.py only renders (decision 1)"
    - "O(1) metadata-only inspection — never reader.read() (T-04-01 constant-time on hostile/huge bags)"
    - "Lazy core import inside the typer command body to keep bagq --help light"
    - "typing.Annotated for typer Arguments (ruff B008-clean) instead of call-in-default"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/inspect.py
    - tests/test_inspect_info.py
    - tests/test_cli_info.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py
    - packages/rosbagger-core/src/rosbagger_core/reader/base.py
    - packages/bagq/src/bagq/cli.py

key-decisions:
  - "Verified duration of a single fixture is 200_000_001 ns (end 1_200_000_001 - start 1_000_000_000), NOT the round 200_000_000 the plan/RESEARCH interfaces block stated; tests assert the runtime value and Hz via pytest.approx(15.0) (Rule 1 fix)"
  - "Empty-bag guard: message_count==0 -> None start/end/duration (no AnyReader sys.maxsize/large-negative sentinel); every Hz None"
  - "Format-aware size: ROS1 .bag = stat().st_size; ROS2 dir = summed rglob('*') file sizes (not the ~4KB inode); summed across paths (READ-05)"
  - "size_bytes stays a raw int in the API; byte->human (B/KB/MB/GB) formatting is CLI-only (Open Q2)"
  - "Multi-msgtype topic -> TopicInfo.msgtype=None, rendered as <mixed> in the CLI (Pitfall 4); covered via a duck-typed reader stub since no fixture triggers it"
  - "Six reader properties added to the BagReader ABC (loosely typed int/object/list) so a future rosbag2_py backend satisfies the contract without base.py naming a rosbags type"

patterns-established:
  - "API-first split: capability in core dataclasses, CLI is a thin rich renderer"
  - "Metadata-only inspection: O(1) AnyReader reads, zero message-body deserialization"

requirements-completed: [INSP-01, INSP-02]

# Metrics
duration: 7min
completed: 2026-05-22
---

# Phase 4 Plan 01: bagq info (Inspect overview) Summary

**`bagq info BAG...` lists per-topic msgtype/count/approx-Hz + a duration/count/size footer, powered by a new metadata-only `rosbagger_core.inspect` API (BagInfo/TopicInfo + collect_bag_info) and six additive O(1) `RosbagsReader` properties — no message-body iteration, no ROS install.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-22T03:28:35-06:00
- **Completed:** 2026-05-22T03:34:59-06:00
- **Tasks:** 3
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- `rosbagger_core/inspect.py`: frozen+slotted `BagInfo`/`TopicInfo` dataclasses and `collect_bag_info(reader)` that reads ONLY O(1) `AnyReader` metadata (`message_count`, `topics`, `start/end/duration`) — never `reader.read()`, so a multi-GB / decompression-bomb bag is inspected in constant time (threat T-04-01).
- Six additive public properties on `RosbagsReader` (`message_count`/`duration`/`start_time`/`end_time`/`typestore`/`paths`) mirroring the existing before-open guard; matching abstract declarations on the `BagReader` ABC. Phase 2 contract (`read`/`open`/`close`/`topics`/`connections`) untouched.
- `bagq info BAG...` typer command: a `rich.table.Table` of topic/msgtype/count/Hz plus a `duration · N messages · human-size` footer; lazy core import inside the body keeps `bagq --help` light.
- Edge cases handled and tested: empty bag (None bounds + None Hz, no negative-duration garbage), ROS2 directory size (summed contents, not inode), ROS1 file size (`stat().st_size`), and the multi-msgtype `<mixed>` path.
- Full suite **110 passed at 97.63%** coverage (gate >=80% held); `bagq/cli.py` and `inspect.py` both at 100%. Offline guard still 2/2 (`import rosbagger_core` pulls no `rosbags`/`pyarrow`; `inspect` stays out of `__init__`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add additive O(1) metadata properties to RosbagsReader + ABC** - `7eb8af9` (feat)
2. **Task 2: Create inspect.py — BagInfo/TopicInfo + collect_bag_info** - `86475f9` (feat)
3. **Task 3: Add the bagq info typer command (thin rich renderer) + CLI smoke test** - `cd47386` (feat)

_Note: Tasks 1 and 2 were authored TDD (RED test file written first, failing on the missing `inspect` import / absent properties, then GREEN). Because the shared `tests/test_inspect_info.py` imports `inspect` at module level, the Task 1 RED/GREEN was verified via a standalone runtime check; both tasks' assertions live in that one committed file (16 tests)._

## Files Created/Modified
- `packages/rosbagger-core/src/rosbagger_core/inspect.py` - NEW: API-first inspect layer; `BagInfo`/`TopicInfo` dataclasses, `collect_bag_info`, `_path_size_bytes`/`_bag_size_bytes`. stdlib-only (dataclasses/pathlib); no `rosbags`/`pyarrow`/schema import; never calls `read()`.
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` - Added 6 public properties (5 guarded `_reader` passthroughs + `paths` copy).
- `packages/rosbagger-core/src/rosbagger_core/reader/base.py` - Added matching `@abc.abstractmethod` declarations (loosely typed for a future rosbag2_py backend).
- `packages/bagq/src/bagq/cli.py` - Added `info` command, `_render_bag_info` (rich table + footer), `_human_size` (byte->human). rich/Path/Annotated at top; core imported lazily in body.
- `tests/test_inspect_info.py` - NEW: 16 fixture-backed tests (ros1/ros2_sqlite/ros2_mcap) covering both reader properties (Task 1) and `collect_bag_info` (Task 2) incl. empty-bag, dir-vs-inode size, no-`read()`, and multi-msgtype-stub paths.
- `tests/test_cli_info.py` - NEW: 6 `CliRunner` smoke tests (exit 0 + stable data, empty-bag em-dash render, `_human_size` units, `--help` lists `info`, missing-bag non-zero exit).

## Decisions Made
- **Duration is 200_000_001 ns, not 200_000_000** — see Deviations (Rule 1). Tests assert the runtime value; Hz asserted via `pytest.approx(15.0, rel=1e-6)`.
- **Multi-msgtype coverage via a duck-typed stub** — the fixtures never carry a heterogeneous-msgtype topic, so the Pitfall 4 path (`msgtype is None` -> rendered `<mixed>`) is exercised with a minimal `_StubReader`/`_BI` rather than a synthetic bag.
- **`paths` is callable before `open()`** and returns a copy — it reads no `_reader`, so size measurement and multi-bag handling work without opening (and callers cannot mutate internal state).
- **`typing.Annotated` for the `bags` argument** instead of `typer.Argument(...)` in the default, to satisfy ruff's `B008` (the project lints with bugbear).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the fixture duration constant from 200_000_000 to 200_000_001 ns**
- **Found during:** Task 1 / Task 2 (verifying AnyReader metadata against the runtime before writing TDD assertions)
- **Issue:** The plan's `<interfaces>` block and several acceptance criteria asserted `duration == 200_000_000` and `hz == 15.0` exactly. The installed `rosbags` 0.11.2 runtime reports `start_time=1_000_000_000`, `end_time=1_200_000_001`, so `duration=200_000_001` ns (the end stamp carries a +1ns tail). The plan's own RESEARCH Code Example actually shows `dur_ns = reader.duration # 200000001`, contradicting the round figure copied into the interfaces block. Asserting the round value would have produced a guaranteed-failing test and a wrong SUMMARY claim.
- **Fix:** Assert the verified `DURATION_NS = 200_000_001` (and `START_NS`/`END_NS`) in `tests/test_inspect_info.py`; assert per-topic Hz via `pytest.approx(15.0, rel=1e-6)` since `3 / 0.200000001 s` is not exactly `15.0`. No production code changed — `collect_bag_info` faithfully passes through whatever `AnyReader` reports.
- **Files modified:** tests/test_inspect_info.py
- **Verification:** 16/16 inspect tests pass against all three fixture formats; end-to-end `bagq info` footer renders `duration: 0.20s` and Hz `15.0`.
- **Committed in:** 86475f9 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — a transcribed-constant correction in test expectations).
**Impact on plan:** No scope change and no production-code change; the fix only aligns test expectations with the verified runtime so the assertions are true. All other plan instructions executed as written.

## Issues Encountered
- The shared `tests/test_inspect_info.py` imports `rosbagger_core.inspect` at module level, so the Task 1 reader-property tests cannot be collected before `inspect.py` exists. The TDD RED/GREEN for Task 1 was therefore verified via a standalone runtime script (properties report the verified values, before-open guards raise, ABC still instantiable, offline guard holds) before committing; the assertions then live permanently in the committed test file. No impact on the final suite.

## User Setup Required
None - no external service configuration required (read-only bag inspection; no new dependencies — `rosbags`/`rich`/`typer` are pre-existing Phase 1/2 deps).

## Next Phase Readiness
- **04-02 (`bagq tables`)** is unblocked: `RosbagsReader.typestore` (added here) is the property `collect_table_schemas` needs to feed `build_table_schema`; the `sorted(reader.topics.items())` + `info.msgtype is None` guard pattern is established; `inspect.py` is the home module for `collect_table_schemas`.
- The `BagInfo`/`TopicInfo` API and the API-first/metadata-only conventions are reusable by the v2 GUI Inspect panel and by Phase 5/7 query tooling.
- No blockers. (Pre-existing repo-level concerns unchanged: GSD planning agents not installed; GitHub push pending auth — neither affects this plan.)

## Self-Check: PASSED

- Created files all present: `inspect.py`, `tests/test_inspect_info.py`, `tests/test_cli_info.py`, `04-01-SUMMARY.md`.
- All three task commits exist in git: `7eb8af9`, `86475f9`, `cd47386`.
- Key identifiers verified in modified files: `def message_count` (rosbags_reader.py), `class BagInfo` (inspect.py), `def info` (cli.py).

---
*Phase: 04-inspect*
*Completed: 2026-05-22*
