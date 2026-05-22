---
phase: 09-tf-debugger
plan: 01
subsystem: testing
tags: [tf, tf2, rosbags, fixtures, TFMessage, ros1, ros2, mcap, sqlite3]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "tools/make_fixtures.py writer surface (_make_header, _timestamp_ns, _T0_NS/_DT_NS, Ros1Writer/Ros2Writer + serialize_ros1/serialize_cdr, the get_types_from_msg+register idiom in write_def_less_bag)"
  - phase: 02-reader
    provides: "RosbagsReader.read(topics={...}) — used by the verify step to re-open each fixture and walk the TFMessage stream"
provides:
  - "write_tf_bag(dest_dir, *, ros1, storage='sqlite3') -> Path — a /tf + /tf_static fixture writer with a deterministic seeded ~800ms publish gap, emittable in all three target formats (ROS 1 .bag, ROS 2 sqlite3, ROS 2 MCAP)"
  - "_transform_stamped / _tf_message private TF builder helpers (identity-pose TransformStamped + TFMessage wrapper)"
  - "Verified ROS 1 TFMessage registration recipe (get_types_from_msg('geometry_msgs/TransformStamped[] transforms\\n', 'tf2_msgs/msg/TFMessage'))"
affects: [09-02, 09-03, tf-analyzer, gap-detection]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ROS 1 TF fixtures register tf2_msgs/msg/TFMessage (absent from Stores.ROS1_NOETIC) before serializing; ROS 2 (Stores.ROS2_HUMBLE) ships it — no register"
    - "Seeded-gap construction: omit a contiguous tick block (8..14 of 24) so the dynamic edge has exactly ONE inter-arrival delta of 8×_DT_NS=800_000_000 ns, all others _DT_NS"
    - "Co-bundle multiple TF edges in one /tf TFMessage per tick (the analyzer keys by (parent, child), so per-message vs per-edge bundling is equivalent)"

key-files:
  created: []
  modified:
    - "tools/make_fixtures.py — added write_tf_bag + _transform_stamped/_tf_message helpers + TF constants; docstring API block updated"

key-decisions:
  - "Single /tf TFMessage per tick carrying whichever edges are present (both edges on ticks 0..7 & 15..23; only base_link->laser on omitted ticks 8..14) — documented in the docstring"
  - "Re-used the existing write_def_less_bag get_types_from_msg+register idiom for the ROS 1 TFMessage registration (verified round-trip on this box)"
  - "Identity pose for every transform (zero translation, unit quaternion 0,0,0,1) — the fixture exercises graph/timing, not geometry"

patterns-established:
  - "TF fixture writer follows the existing private-helper style (_twist/_imu/_image) and the shared add_connection/write Writer surface; storage plugin parametrized via a closed {sqlite3,mcap} map, ignored when ros1=True"

requirements-completed: [TF-01]

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 9 Plan 01: TF Fixture Writer Summary

**`write_tf_bag` fixture writer — emits `/tf_static` (map→odom) + dynamic `/tf` (odom→base_link with one deterministic 800ms gap, base_link→laser clean) in all three target formats (ROS 1 `.bag`, ROS 2 sqlite3, ROS 2 MCAP), re-openable via the v1 reader with no ROS install.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-22T23:35:44Z
- **Completed:** 2026-05-22T23:38:08Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `write_tf_bag(dest_dir, *, ros1: bool, storage: str = "sqlite3") -> Path` — the Phase 9 test artifact that proves the three TF Success Criteria offline.
- ROS 1 path registers `tf2_msgs/msg/TFMessage` (verified absent from `Stores.ROS1_NOETIC`) via the same `get_types_from_msg` + `ts.register` idiom as `write_def_less_bag`; ROS 2 path uses the typestore's built-in type (no register).
- Seeded a deterministic gap: the dynamic `odom→base_link` edge omits ticks 8..14 of a 24-tick window, leaving exactly ONE inter-arrival delta of `800_000_000` ns and all others `_DT_NS`. The companion `base_link→laser` edge is published every tick (clean, zero gaps). `/tf_static` carries a single latched `map→odom` transform.
- Added `_transform_stamped` / `_tf_message` private builders mirroring the existing `_twist`/`_imu`/`_image` helper style; updated the module docstring's API block to list `write_tf_bag`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add write_tf_bag fixture writer with a seeded ~800ms gap** - `afae33e` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified
- `tools/make_fixtures.py` - Added `write_tf_bag` public writer + `_transform_stamped`/`_tf_message` private builders + TF topic/msgtype/window constants (`_TOPIC_TF`, `_TOPIC_TF_STATIC`, `_MSGTYPE_TFMESSAGE`, `_TF_N_TICKS`, `_TF_GAP_START_TICK`, `_TF_GAP_END_TICK`); listed `write_tf_bag` in the docstring API block. `make_all_fixtures` left untouched.

## Decisions Made
- **Edge bundling:** publish ONE `/tf` `TFMessage` per tick carrying whichever edges are present at that tick (both `odom→base_link` and `base_link→laser` on ticks 0..7 & 15..23; only `base_link→laser` on the omitted ticks 8..14). The analyzer keys edges by `(parent, child)`, so co-bundling is equivalent to publishing the two edges separately. Documented in the function docstring.
- **Gap window:** skip ticks `8..14` (7 ticks) so the surviving delta `_timestamp_ns(15) − _timestamp_ns(7) == 8 × _DT_NS == 800_000_000` ns. N=24 yields a `_DT_NS` median far below the 8×-median gap, so the default 5× multiplier in the Plan 03 analyzer will flag it cleanly.
- **Identity pose** for every transform (zero translation, unit quaternion `(0,0,0,1)`) — the fixture exercises graph topology + timing, not geometry.
- Re-used the existing `write_def_less_bag` `get_types_from_msg` + `ts.register` idiom for the ROS 1 registration rather than inventing a new one.

## Deviations from Plan

None - plan executed exactly as written.

The plan's `<interfaces>` block and RESEARCH facts matched the live source and the running `rosbags` typestore exactly (verified before implementing: ROS1_NOETIC lacks `TFMessage`, ROS2_HUMBLE has it, both have `TransformStamped`, the register recipe round-trips). No bugs, missing functionality, or blockers were encountered.

Note (not a deviation): `ruff format` collapsed three of the new multi-line calls that fit on one line — formatting only, no functional change. Applied to keep the project's `ruff format --check` CI gate green.

## Issues Encountered
None.

## Threat Model Compliance
- **T-09-01 (Tampering — ROS 1 registration string):** mitigated as planned — used the VERIFIED literal `"geometry_msgs/TransformStamped[] transforms\n"` + `"tf2_msgs/msg/TFMessage"`; the verify step re-opens and reads the bag in all three formats, proving the registration produced a deserializable type.
- **T-09-02 / T-09-SC (accepted):** the fixture is tiny (24 ticks × ≤2 edges) and adds zero new packages — both unchanged.
- No new security-relevant surface introduced (dev-only fixture writer over the already-vetted `rosbags` writer; author-controlled deterministic inputs into a tmp dir).

## Verification Evidence
- **Plan verify command** (re-open all three formats, assert frame set `{map, odom, base_link, laser}`): prints `OK`, exit 0.
- **Gap-structure assertion** (all three formats): `/tf_static` = 1 message carrying `map→odom`; `(odom, base_link)` = 17 samples with exactly ONE `800_000_000` ns delta and all others `_DT_NS`; `(base_link, laser)` = 24 samples, all `_DT_NS`, zero `800_000_000` deltas. All pass.
- **Offline invariant:** `import tools.make_fixtures` pulls no `rclpy`/`rosbag2_py` (verified via a `sys.modules` scan).
- **`make_all_fixtures`** keys unchanged: `{ros1, ros2_sqlite, ros2_mcap}`.
- **Full suite:** `PYTHONPATH="" uv run pytest -q` → 255 passed, 97.82% coverage (≥80% gate). `ruff check` + `ruff format --check` both clean on the edited file.

## Next Phase Readiness
- The fixture writer is ready for Plan 09-02 (TF analyzer core `collect_tf_report` over the reader stream) and Plan 09-03 (the analyzer test that asserts SC1–SC3 against this fixture).
- All three formats are exercisable from one writer: `write_tf_bag(d, ros1=True)`, `write_tf_bag(d, ros1=False, storage="sqlite3")`, `write_tf_bag(d, ros1=False, storage="mcap")`.
- No blockers introduced. Standing milestone-level blocker (v0.1 push pending auth) is unrelated to Phase 9.

## Self-Check: PASSED
- FOUND: tools/make_fixtures.py (contains `def write_tf_bag(dest_dir`)
- FOUND: commit afae33e (Task 1, feat)
- FOUND: .planning/phases/09-tf-debugger/09-01-SUMMARY.md

---
*Phase: 09-tf-debugger*
*Completed: 2026-05-22*
