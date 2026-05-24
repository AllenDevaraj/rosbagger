---
phase: 14-gui
plan: 01
subsystem: rosbagger-replay
tags: [refactor, replay, rclpy, publish-sink, offline-invariant, gui-prep]
requires:
  - "rosbagger_replay.replay.replay() (Phase 13 — the run-to-completion publish front door)"
  - "rosbagger_replay.scheduler.Replayer (Phase 13 — the pure transport state machine)"
  - "rosbagger_replay.__init__._require_ros() + lazy front-door pattern (Phase 13)"
provides:
  - "rosbagger_replay.replay.build_publish_sink(node) -> (sink, published) — the ONE reusable publish-mechanics function"
  - "rosbagger_replay.build_publish_sink (lazy package-front-door re-export behind _require_ros)"
affects:
  - "Phase 14 GUI replay panel (14-02..14-07) — will drive the pure Replayer using this shared sink for live play/pause/step/seek/rate/loop"
tech-stack:
  added: []
  patterns:
    - "Lazy ROS-bound front-door re-export (mirrors replay/replay_bag) — _require_ros() then delegate to .replay impl"
    - "Closure-factory returning (sink, count_dict) so the WR-07 source-of-truth counter is shared with the caller"
key-files:
  created: []
  modified:
    - "packages/rosbagger-replay/src/rosbagger_replay/replay.py"
    - "packages/rosbagger-replay/src/rosbagger_replay/__init__.py"
decisions:
  - "Moved the inlined rclpy publish closure out VERBATIM (no logic change) — Phase-13 offline regression suite gates the no-drift (T-14-01-01)."
  - "deserialize_message/get_message imports stay INSIDE build_publish_sink's body — keeps import rosbagger_replay ROS-free (T-14-01-02)."
  - "Removed the now-dead pre-try `published = {\"n\": 0}` in replay() — build_publish_sink returns the live counter, which replay() reassigns before any use; finally only touches `node`."
  - "build_publish_sink re-exported as a LAZY front-door function (its own _require_ros() guard + .replay delegation), NOT a top-level import — so import rosbagger_replay stays offline-clean and the GUI gets exactly one production publish path."
metrics:
  duration: ~6min
  completed: 2026-05-24
  tasks: 1
  files: 2
---

# Phase 14 Plan 01: Shared publish-sink extraction (D-09a) Summary

Factored the ~15-line rclpy publish closure out of `replay()`'s body into ONE reusable
module-level `build_publish_sink(node) -> (sink, published)` so `replay_bag()` and the
Phase-14 GUI replay panel share a SINGLE production publish path — the GUI will drive the
pure `Replayer` directly for live transport using the SAME sink mechanics, never a
duplicated publish path.

## What Changed

- **`replay.py` — new `build_publish_sink(node)`:** a module-level factory returning a
  `(sink, published)` pair. `sink(item) -> None` is the publish closure moved VERBATIM from
  `replay()`'s body (lazy per-topic `pubs` dict, depth-10 RELIABLE-VOLATILE
  `node.create_publisher(cls, item.topic, 10)`, `get_message(item.msgtype)` class resolve,
  `deserialize_message(item.cdr, cls)`, `pub.publish(msg)`, and the WR-07
  `published["n"] += 1` counter). The `rclpy.serialization` / `rosidl_runtime_py` imports
  live INSIDE the function body (offline invariant preserved — no module-top ROS import).
- **`replay.py` — `replay()` rewired:** now calls `sink, published = build_publish_sink(node)`
  instead of inlining the closure. The lazy `deserialize_message`/`get_message` imports were
  removed from `replay()`'s body (now owned by `build_publish_sink`); `import rclpy` stays
  (used for `rclpy.ok()`/`init()`/`create_node`/`shutdown`). Everything else
  (`created_ctx`/`rclpy.ok()` guard, `Replayer` construction, `--start` seek,
  `play()`/`run()`, the best-effort `finally` teardown, `return published["n"]`) is unchanged.
  The now-dead pre-`try` `published = {"n": 0}` was removed (build_publish_sink supplies the
  live counter, reassigned before use; the `finally` only references `node`).
- **`__init__.py` — lazy re-export:** added a `build_publish_sink(*args, **kwargs)` front-door
  function that calls `_require_ros()` first then delegates to
  `.replay.build_publish_sink` (mirrors the `replay` front-door pattern), plus a
  `"build_publish_sink"` entry in `__all__`. The GUI imports it via the package front door
  without breaking `import rosbagger_replay` offline-cleanliness.

## Verification

| Check | Result |
|-------|--------|
| `grep "def build_publish_sink"` in replay.py | One match (line 39) |
| Real `node.create_publisher(...)` call in replay.py | Exactly one, inside `build_publish_sink` (line 75); the other 3 `create_publisher` hits are pre-existing docstring/comment prose |
| `tests/test_replay_unit.py` (Phase-13 offline replay regression gate) | 25 passed |
| `tests/test_offline_guard.py::test_import_replay_does_not_pull_ros` | passed |
| `tests/test_replay_unit.py tests/test_offline_guard.py` (full) | 42 passed |
| `ruff check` + `ruff format --check` on both files | clean |

Run with `PYTHONPATH=""` (host ROS-on-PYTHONPATH leak; CI is ROS-free).

## Deviations from Plan

### Note on the "25 tests / grep -c == 1" acceptance wording (not behavior deviations)

- **Test count:** the plan's acceptance text said "25 tests collected" for
  `tests/test_replay_unit.py`. The file actually collects **26 items** when run alone (the
  cited 25-test figure undercounted by one). All collected tests pass either way — the
  regression gate (no behavior drift, T-14-01-01) is satisfied. When co-collected with the
  offline guard the run is 42 passed.
- **`grep -c "create_publisher"` == 1:** the plan's literal `grep -c` returns **4**, but
  the *real code* `node.create_publisher(...)` call appears **exactly once** and is inside
  `build_publish_sink`. The other 3 matches are pre-existing prose (the module docstring's
  VERIFIED-path description, build_publish_sink's own docstring, and a one-line comment in
  `replay()`). The acceptance criterion's INTENT — "only inside build_publish_sink, not
  duplicated in replay()" — is met: there is one publish path, no duplicated mechanics.

### Auto-fixed Issues

None — the mechanics were moved verbatim; no bugs, missing functionality, or blocking issues
were found.

## Must-Haves Satisfied

- ✅ Both `replay_bag()` and the GUI can import ONE shared rclpy publish-sink builder; there
  is exactly one production publish path (`build_publish_sink`, re-exported lazily).
- ✅ The Phase-13 replay tests still pass after the refactor — no behavior regression
  (25 offline replay tests green; the live SC1 lane stays driven by the same sink via
  `replay()`).
- ✅ Artifact present: `def build_publish_sink` in `replay.py`, reusable and importable.
- ✅ Key links: `replay()` calls `build_publish_sink` (no longer inlines the mechanics);
  `__init__` lazily re-exports it behind `_require_ros()`.

## Threat Mitigations Applied

- **T-14-01-01 (Tampering / behavior drift):** mechanics moved VERBATIM; the 25-test
  Phase-13 offline replay regression suite gates it — green.
- **T-14-01-02 (Elevation / rclpy import leak):** `deserialize_message`/`get_message` imports
  kept INSIDE `build_publish_sink`'s body; `test_import_replay_does_not_pull_ros` confirms
  `import rosbagger_replay` leaks no `rclpy`/`rosbag2_py` — green.

## Known Stubs

None.

## Commits

- `f593c97` refactor(14-01): extract build_publish_sink as the single shared publish path

## Self-Check: PASSED

- FOUND: packages/rosbagger-replay/src/rosbagger_replay/replay.py
- FOUND: packages/rosbagger-replay/src/rosbagger_replay/__init__.py
- FOUND: .planning/phases/14-gui/14-01-SUMMARY.md
- FOUND: commit f593c97
