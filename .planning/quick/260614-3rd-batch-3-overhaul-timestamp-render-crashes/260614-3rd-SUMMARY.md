---
quick_id: 260614-3rd
slug: batch-3-overhaul-timestamp-render-crashes
description: Batch 3 — temporal-safe query rendering (SW1/SW2) + TUI row cap (F6).
status: complete
date: 2026-06-14
commits: d5e8fb1
---

# Quick Task 260614-3rd — Summary

## Outcome
`SELECT * FROM imu` (or any time-column query) no longer crashes the GUIs. Desktop rendered the
`t`/`stamp` columns blank with per-cell traceback spam (SW1); the TUI raised outside its run
handler and broke the query action (SW2). Both now render via the temporal-safe path, and the
TUI table is bounded (F6). Full offline suite **671 passed, 6 skipped**.

## What changed (`d5e8fb1`)
- **SW1** `desktop/widgets/result_model.py`: `data()` renders `timestamp[ns]` cells via
  `numpy.datetime64(scalar.value, "ns")` (the raw ns int — `.as_py()` raises on sub-µs ns).
  Temporal column indices precomputed in `__init__`/`set_table` (metadata-only); the lazy
  per-cell model is preserved (no full materialization).
- **SW2** `gui/panels/query.py` `_fill_results`: uses core `rows_for_display` (temporal-safe)
  instead of `table.to_pylist()`.
- **F6**: `rows_for_display(max_rows=1000)` caps the on-screen DataTable; the status line notes
  "showing first N" when truncated; export still writes the full `_last_result`.

## Verify
- `test_desktop.py`: `_ResultTableModel` renders `t` as a datetime string + `t_ns` as int (SW1).
- `test_gui.py`: TUI `SELECT * FROM imu` lands 3 rows in `results` (SW2 — would crash before).
- Full offline suite **671 passed, 6 skipped**.

## Deferred
- The TUI query still runs `query()` synchronously on the event loop (F6's second half) — a
  full-bag decode can briefly freeze the TUI; the worker-thread move folds into the GUI/TUI
  threading batch (with the C1–C8 lifecycle races).
