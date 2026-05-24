---
phase: quick-260524-hg7
plan: 01
subsystem: rosbagger-gui
tags: [gui, textual, css, layout, regression-test]
requires: []
provides: ["InspectPanel/TfPanel fill-height layout", "GUI-01 blank-panel regression guard"]
affects: ["packages/rosbagger-gui/src/rosbagger_gui/app.tcss", "tests/test_gui.py"]
tech-stack:
  added: []
  patterns: ["widget-type CSS selector for bare-Widget panels (mirrors Scrubber rule)", "rendered region.height assertion as a visibility regression signal"]
key-files:
  created: []
  modified:
    - packages/rosbagger-gui/src/rosbagger_gui/app.tcss
    - tests/test_gui.py
decisions:
  - "Fix is layout/CSS only — no panel .py logic touched; panels stay thin faces"
  - "Descendant DataTable selectors scoped to InspectPanel/TfPanel so the working QueryPanel layout is untouched (T-hg7-02 mitigation)"
  - "Assert rendered region.height > 0, not row_count, as the regression signal — a height-0 DataTable is invisible despite having rows"
metrics:
  duration: ~3min
  completed: 2026-05-24
---

# Quick Task 260524-hg7: Fix Inspect/TF Blank Panels Summary

CSS-only fill-height fix for the `InspectPanel` / `TfPanel` blank-render regression, plus a headless `region.height > 0` test that fails if either panel collapses to height 0 again.

## What Was Done

`InspectPanel` and `TfPanel` extend a bare `textual.widget.Widget` with no height rule (no `DEFAULT_CSS`, nothing in `app.tcss`), so Textual laid them out at `height: 0` and their populated DataTables rendered invisible. `QueryPanel` renders correctly only because it extends `Vertical`, which flexes inside the `Horizontal { height: 1fr }` shell. Data was reaching the tables all along — it was purely a layout collapse, and the prior SC3 test asserted only `row_count`, never rendered height, which is why it shipped.

### Task 1 — Fill-height CSS rules (`app.tcss`, commit `90e7b03`)
- Added `InspectPanel, TfPanel { height: 1fr; width: 1fr; }` type-selector rules (mirroring the existing `Scrubber { ... }` type-selector pattern) so the bare-Widget panels fill the `ContentSwitcher` instead of collapsing.
- Added `InspectPanel DataTable, TfPanel DataTable { height: 1fr; }` — a descendant selector scoped to these two panels only, so `#bag-info`/`#table-schemas` and `#tf-edges`/`#tf-gaps` each take a flexing share while the `Static` headers stay auto-height.
- Comment above the rules notes the Phase-14 blank-panel regression and the bare-Widget vs `QueryPanel(Vertical)` root cause.
- No `.py` files touched (panels stay thin faces).

### Task 2 — Rendered-height regression test (`tests/test_gui.py`, commit `53e1ff5`)
- Added `test_inspect_and_tf_panels_render_with_height` using the same `bag` fixture and `RosbaggerApp` / `run_test()` / `Pilot` harness as the other tests, following the PAUSE-BEFORE-ASSERT convention.
- Inspect: clicks `#nav-inspect`, asserts `#bag-info` `region.height > 0` (the precise regression signal) AND `row_count >= 1` (table is both visible and carrying real core data).
- TF: clicks `#nav-tf`, asserts `#tf-edges` `region.height > 0` only — the fixture bag has no `/tf`, so "no transforms" is a valid empty state and `row_count` is not asserted.
- Reused the existing `DataTable` import; no new imports added.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- `PYTHONPATH="" uv run pytest tests/test_gui.py -q` — 5 passed (incl. the new height regression test and the SC3 query test). (The single-file coverage FAIL is a per-file artifact of the 80% addopts gate, not a regression — confirmed by the full-suite run below.)
- `PYTHONPATH="" uv run pytest -m "not live" -q` — 466 passed, 3 skipped, 97.37% coverage (baseline 465 passed → +1 new test, gate ≥80% held). QueryPanel SC3 test still green (T-hg7-02 mitigation verified).
- `PYTHONPATH="" uv run ruff check . && PYTHONPATH="" uv run ruff format --check .` — clean, 90 files.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: packages/rosbagger-gui/src/rosbagger_gui/app.tcss (InspectPanel/TfPanel rules present)
- FOUND: tests/test_gui.py (region.height assertions present)
- FOUND: commit 90e7b03 (Task 1)
- FOUND: commit 53e1ff5 (Task 2)
</content>
</invoke>
