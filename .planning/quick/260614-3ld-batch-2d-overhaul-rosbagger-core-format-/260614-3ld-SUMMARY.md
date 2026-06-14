---
quick_id: 260614-3ld
slug: batch-2d-overhaul-rosbagger-core-format-
description: Batch 2d — one rosbagger_core.format for human_size/human_dur; fixed the bagq GB-cap drift (R2/R3).
status: complete
date: 2026-06-14
commits: 4bca114
---

# Quick Task 260614-3ld — Summary

## Outcome
`human_size`/`human_dur` are no longer triplicated (and no longer drifted). bagq's `_human_size`
had capped at GB — a 2 TiB bag printed `2048.0 GB` while the GUIs printed `2.0 TB` for the same
bag. Now one stdlib-only `rosbagger_core.format` backs all three faces. Full offline suite
**669 passed, 6 skipped**.

## What changed (`4bca114`)
- New `rosbagger_core/format.py`: `human_size` (1024-based, B/KB/MB/GB/TB/PB — divides through,
  no premature GB cap) + `human_dur` (ms/s). NOT imported by `__init__`; stdlib-only (offline-safe).
- All six face copies delegate to it (bagq `cli.py` `_human_size`/`_human_dur`; gui
  `panels/inspect.py` + `panels/tf.py`; desktop `panels/inspect_panel.py` + `panels/tf_panel.py`),
  each lazy-importing the helper INSIDE the function to keep the module top textual-/PySide6-only
  (every panel's documented offline-import invariant).

## Verify
- `test_format.py` (9): size units incl. **2 TiB → "2.0 TB"** (the drift fix) and PB; dur ms/s.
- Updated `test_cli_info.py::test_human_size_formats_units` (it had pinned the old GB cap).
- Full offline suite **669 passed, 6 skipped**; offline guard green (format.py is stdlib-only).

## Out of scope (later)
- The TF-report / inspect-footer ROW formatting is still per-face (framework-coupled to
  rich/Textual/Qt tables); a framework-agnostic `tf_report_rows` is a deeper follow-up.
- 2e error/capability dedup (R4/R6/R7/T7); then Batches 3–7.
