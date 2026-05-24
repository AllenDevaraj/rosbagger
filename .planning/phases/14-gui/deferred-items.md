# Phase 14 — Deferred / Out-of-Scope Items

Discoveries logged during execution that are NOT in the current plan's scope.
Do NOT fix these inline (scope boundary) — they are recorded for a later pass.

## 14-06 (Replay panel)

- **`ruff format --check` flags pre-existing files** `packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py`
  and `.../panels/tf.py` as "would reformat" on the current ruff version. These files
  were committed by Plans 14-03/14-04 and are NOT touched by 14-06 (no working-tree
  diff). `ruff check` (lint) is clean across the whole gui src; only the formatter's
  whitespace pass diverges. Out of scope for 14-06 — fix in a dedicated format pass or
  when those panels are next edited.
