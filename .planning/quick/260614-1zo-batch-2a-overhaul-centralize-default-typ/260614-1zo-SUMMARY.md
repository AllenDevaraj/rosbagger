---
quick_id: 260614-1zo
slug: batch-2a-overhaul-centralize-default-typ
description: Batch 2a — centralize def-less default-typestore resolution in the reader (T1) + fix open() sub-reader fd leak (newE19), preserving the CLI-04 teaching for custom-type bags.
status: complete
date: 2026-06-14
commits: 6379d19
---

# Quick Task 260614-1zo — Summary

## Outcome

First part of Batch 2 (shared infrastructure): the **typestore decision** is now made once,
in the reader layer, instead of being re-decided or forgotten per face. The headline win —
**`bagq` (and any caller passing no typestore) now opens a real `rosbag2` `.db3`** (which
embeds no message definitions), which it previously could not, while the **CLI-04 teaching
error for custom-type def-less bags is preserved**. The same refactor closes the `open()`
sub-reader fd leak (`newE19`). Full offline suite **639 passed, 6 skipped**.

## What changed (`6379d19`)

### New `rosbagger_core/typestore.py`
- `resolve_default_typestore()` — maps `$ROS_DISTRO` to a rosbags `Stores` member
  (`ROS2_<DISTRO>`), falling back to `ROS2_HUMBLE` when unset/unknown/ROS 1. Pure
  `_store_for_distro()` helper for unit testing. Lazy `rosbags` import; not imported by
  `rosbagger_core/__init__`, so `import rosbagger_core` stays offline-light.

### `RosbagsReader.open()` — fallback-then-verify (T1) + leak fix (newE19)
- **No explicit typestore:** open with the bag's embedded defs; on the specific
  `"no type definitions"` error, fall back to `resolve_default_typestore()` and **verify it
  covers every connection msgtype** (`get_msgdef`). All covered → open (standard real `.db3`
  works everywhere). Any uncovered (a custom type) → close + raise `UnresolvedTypeError` with
  registration guidance (CLI-04 preserved).
- **Explicit typestore** (the GUIs): honored unchanged — no fallback, no coverage verify.
- **newE19:** rosbags opens all sub-readers before raising the post-loop no-defs error, and
  its `close()` asserts `isopen`; the new `_force_close_subreaders()` releases them on every
  discard path so file handles never leak.

## Why fallback-then-verify (empirically confirmed)
A standard def-less bag opened with ROS2_HUMBLE opens and every msgtype resolves via
`get_msgdef`; a custom-type def-less bag opens too but `get_msgdef('my_pkg/msg/Widget')`
raises `KeyError`. So a blanket fallback would have silently opened custom-type bags (failing
later at read, losing the teaching error) — the coverage verify is what keeps CLI-04 honest.

## Verification
- New `tests/test_typestore.py` (10): distro→store mapping + fallbacks; resolver returns a
  usable store.
- New tests in `tests/test_cli_errors.py`: `RosbagsReader` opens a standard def-less bag with
  no typestore and reads `/imu`; `bagq info`/`tables`/`query` exit 0 on it (the T1 win); the
  custom def-less bag still raises `UnresolvedTypeError` at the reader; **25 repeated failed
  opens don't accumulate fds** (`/proc/self/fd` stable) and leave no dangling reader.
- Existing CLI-04 tests (`test_def_less_bag_teaches_registration_for_all_commands`) stay green.
- Full offline suite **639 passed, 6 skipped**; offline guard green.

## Out of scope (later Batch 2 sub-batches)
- **2b** `resolve_topics()` chokepoint — the `bagq edit --keep` data-loss (`T3`).
- **2c** `open_bag()` helper unifying the 3 reader-open sites + the duplicated edit/pipeline
  leak (`T2`); the replay `load_items` path picks up the typestore fallback there.
- **2d** `rosbagger_core.format` (`R2`/`R3`). **2e** error/capability dedup (`R4`/`R6`/`R7`/`T7`).
- Removing the GUIs' now-redundant `_ros2_humble_typestore()` (a follow-up dedup; their
  explicit path is preserved here, so no behavior change yet).
