---
phase: 17-desktop-revamp-full-visual-design-system-qss-theme-design-to
plan: 03
subsystem: rosbagger-desktop (full visual rollout + record/replay a11y parity)
tags: [qss, theme, objectname, design-system, accessibility, d-02, d-03, thin-face]
requires:
  - "17-01: theme/qss.py (build_qss + #status_error selector) + ThemeManager live toggle"
  - "17-02: widgets.set_status shared accessible helper + inspect/tf model/view migration"
provides:
  - "shell chrome themed via objectNames (nav_list / panel_stack / shell_central) + heading selectors in theme/qss.py"
  - "query/inspect/tf section headers marked heading=true (theme-styled, no inline font/color literal)"
  - "record + replay status routed through the shared accessible set_status (D-02 a11y parity); error paths flagged is_error"
  - "record/replay status labels accessibly named + theme-targeted objectNames (record_status / replay_status)"
  - "no_inline_color regression test + live-toggle-restyles-all-five-panels test"
affects:
  - "Task 4 human-verify checkpoint (PENDING): real-window visual sanity check in both themes — the DoD"
tech-stack:
  added: []  # zero new dependencies (RESEARCH Package Legitimacy Audit — N/A)
  patterns:
    - "objectName / dynamic-property (heading=true) keyed theme selectors — ALL color in theme/qss.py (D-03)"
    - "every panel status routed through the one shared accessible set_status helper (D-02)"
    - "deliberate spacing rhythm set on layouts (margins/spacing), NOT inline color/QSS literals"
    - "offscreen-provable live-toggle proof: assert stylesheet bg-hex + manager name, not pixels (Pitfall 4)"
key-files:
  created: []
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/qss.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/tf_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
    - tests/test_desktop.py
decisions:
  - "Query panel's inline _STATUS_ERROR_STYLE/_STATUS_NEUTRAL_STYLE were ALREADY removed in 17-02 (its _set_status delegates to the shared set_status + #status_error objectName); the plan's lines 82-83 reference was stale — no inline color literal remained to remove in any panel at the start of this plan, confirmed by grep"
  - "Section-heading hierarchy expressed via a heading=true DYNAMIC PROPERTY keyed by a theme QSS QLabel[heading=true] selector (not an inline font/color literal) — keeps the single-source rule (D-03)"
  - "Shell chrome themed via three objectNames (nav_list / panel_stack / shell_central) + a fixed-width nav gutter; spacing set on the QHBoxLayout, color in theme/qss.py"
  - "Did NOT add unused objectNames to record/replay storage/control bars — those widgets (QPushButton/QLineEdit/QListWidget/QLabel) already inherit the theme via type selectors; only the load-bearing status-label objectName was added (minimal, correct)"
  - "Live-toggle proof asserts the QApplication stylesheet bg-hex flip + manager name (offscreen-observable) per RESEARCH Pitfall 4 — panels carry empty styleSheet() so the single app sheet reaches all five"
metrics:
  duration: ~35m
  tasks: 4 (3 automated complete; Task 4 human-verify PENDING)
  files_created: 0
  files_modified: 8
  completed: 2026-05-25 (automated tasks)
---

# Phase 17 Plan 03: Full Visual Rollout + Record/Replay A11y Parity Summary

Rolled the 17-01 token-driven QSS theme across the whole cockpit — the shell chrome (nav rail / panel stack / central surface) and all five panels — entirely through objectNames and a `heading=true` dynamic property (zero inline per-widget color literals, D-03), and brought record + replay to the status/a11y bar by routing every `self._status.setText(...)` through the shared accessible `widgets.set_status` helper (failure/teaching/refusal paths flagged `is_error=True`, content + threading unchanged — D-02/D-09). Closes with a live-toggle-restyles-all-five-panels proof, the full headless suite + offline/Qt-free guard green, and the blended ≥80% coverage gate holding. The final DoD step — a human visual sanity check on a real X11 window in both themes — is PENDING (a headless agent cannot prove appearance).

## What Was Built

### Task 1 — shell + query/inspect/tf themed; no inline color (commit d525913)
- **`theme/qss.py`** — extended with shell-chrome selectors (`QListWidget#nav_list` nav rail with selected-row accent, `QWidget#shell_central`, `QStackedWidget#panel_stack`) and a `QLabel[heading="true"]` section-heading selector (slightly larger + muted + 600 weight so dense data tables stay the focal point). All values sourced from the `Tokens` palette — no hard-coded color.
- **`main_window.py`** — gave the nav (`nav_list`), stack (`panel_stack`), and central widget (`shell_central`) their theme objectNames; set a deliberate spacing rhythm (zero-margin central layout, a fixed 180px nav gutter) on the `QHBoxLayout` (not an inline literal).
- **`query_panel.py` / `inspect_panel.py` / `tf_panel.py`** — marked the section/header labels (`History`, inspect header, tf status line) with the `heading=true` dynamic property; gave each panel an 8px margin/spacing rhythm on its `QVBoxLayout`. (Their status lines already carried `query_status`/`inspect_status`/`tf_status` objectNames + `set_status` delegation from 17-02 — no inline color remained to remove.)
- **`tests/test_desktop.py`** — added `test_no_inline_color_in_any_panel_or_shell` (walks every descendant `QWidget` of all five panels + the shell chrome; asserts each `.styleSheet()` is empty — color is the single app-level sheet, D-03/T-17-09) and `test_shell_and_panels_carry_theme_object_names`.

### Task 2 — record + replay status through the accessible helper (commit b135669)
- **`record_panel.py`** — imported `set_status`; named the status label (`record_status` objectName + "Record status" accessibleName + `heading=true`); replaced ALL nine `self._status.setText(...)` sites with `set_status(self._status, ...)`. Error/teaching/invalid-input paths (`_NO_ROS_HINT` in scan + start, "already in flight", "select at least one topic", the discovery-failed slot, the record-failed slot, the unexpected-result guard) flagged `is_error=True`; informational paths (discovering / discovered / no-topics / dismissed / recorded-N) left non-error. The wired `on_failed=self._status.setText` became `_on_discover_failed` (an `is_error=True` slot).
- **`replay_panel.py`** — imported `set_status`; named the status label (`replay_status` + "Replay status" + `heading=true`); replaced ALL `self._status.setText(...)` sites. Error paths (`REPLAY_HINT`, "no bag loaded", invalid-rate via `_validated_rate`, every "pause before…" guard refusal, the three `_ensure_transport` teaching/setup-failed paths, the drive-failed slot) flagged `is_error=True`; informational paths (Playing… / Paused. / Stepped / Rate set / Seeked / Done) left non-error. The wired `on_failed=self._status.setText` became `_on_drive_failed`.
- Every preserved accessor still resolves: record (`status_label`/`topic_list`/`start_button`/`dismiss_button`/`out_input`), replay (`status_label`/`scrubber`/`play_button`/`pause_button`/`step_button`/`rate_input`/`loop_checkbox`). Message CONTENT + threading unchanged (THIN-FACE, D-09 — the `set_status` helper sets `text` verbatim and the offscreen `QAccessible` guard is preserved, D-09/T-17-08).
- **`tests/test_desktop.py`** — `test_record_replay_status_is_accessible_and_error_styled`: both labels expose `accessibleName` + a theme objectName; replay invalid-rate and record no-ROS scan each toggle the `status_error` objectName affordance (offscreen-safe), and a subsequent success restores the base objectName.

### Task 3 — live-toggle proof + regression gate (commit 691c8f2)
- **`tests/test_desktop.py`** — `test_theme_toggle_restyles_all_five_panels_live`: builds `MainWindow` (all five panels), applies the dark default, captures `QApplication.styleSheet()`, fires the View ▸ Dark theme action, and asserts the app stylesheet flipped to the LIGHT bg hex (and dropped DARK) AND `theme_manager.name` flipped — offscreen-provable state per RESEARCH Pitfall 4 (no pixel assertions). Also asserts all five panels are present + carry an empty own-`styleSheet()` (color is app-level), and toggling back restores the DARK bg.

## How It Works (styling data flow)

`ThemeManager.apply()` sets ONE `QApplication.setStyleSheet(build_qss(DARK|LIGHT))` and unpolishes/polishes every top-level widget. Each panel/shell widget carries NO inline stylesheet — it only sets objectNames (`nav_list`, `panel_stack`, `shell_central`, `*_status`) and the `heading=true` dynamic property, which the single app-level QSS targets. A status update calls `set_status(label, text, is_error=...)`, which toggles the `status_error` objectName (color from the theme's `QLabel#status_error` selector) and repolishes the label so the QSS re-evaluates live; on the error path it posts a guarded `QAccessible` Alert. The View-menu toggle re-`apply()`s the other palette, and because color lives in the one app sheet the flip reaches all five panels at once.

## Deviations from Plan

### Note on query_panel's `_STATUS_ERROR_STYLE` (planned removal already done in 17-02 — not a deviation)
The plan's Task 1 directed removing the inline `_STATUS_ERROR_STYLE`/`_STATUS_NEUTRAL_STYLE` literals at query_panel.py lines 82-83. That removal had ALREADY landed in 17-02 (query_panel's `_set_status` delegates to the shared `widgets.set_status` and the error color comes from the theme `#status_error` objectName). A start-of-plan grep confirmed ZERO inline color literals / `setStyleSheet` calls in any panel. Task 1 therefore focused on the still-outstanding work: shell chrome objectNames, section-heading hierarchy, spacing rhythm, and the `no_inline_color` regression test. No code change was needed to "remove" an already-absent literal.

### Auto-fixed Issues
None — no bugs, missing functionality, or blocking issues were discovered. All three automated tasks executed as written (modulo the stale line-reference note above).

## Known Stubs
None — all five panels are fully themed against the live tokens and every status path is wired through the shared accessible helper.

## Threat Flags
None — no new network endpoint, auth path, file-access pattern, or schema change. The register's `mitigate` dispositions are all implemented: T-17-08 (record/replay `QAccessible` Alert stays guarded via the shared `set_status` helper's `platformName() != "offscreen"` check), T-17-09 (the `no_inline_color` test + the grep gate assert per-panel `styleSheet()` empty; all color in theme/qss.py). T-17-10 (low-contrast text) is `accept (human-checked)` — covered by the PENDING Task 4 checkpoint. T-17-SC: zero new packages.

## Verification

- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py` → **37 passed** (clean, no Bus error this run).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → **20 passed** (offline + Qt-free guard green, D-08).
- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` (full blended suite) → **505 passed, 4 skipped**, **total coverage 84.74% ≥ 80%** (gate holds; `Required test coverage of 80% reached. Total coverage: 84.74%`).
- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop/src/rosbagger_desktop/` → clean.
- No inline color: `grep -rnE 'setStyleSheet\(' .../panels/` (minus comments) → nothing (color lives only in theme/qss.py).

## Task 4 — Human Visual Sanity Check (PENDING — the DoD)

**Status: PENDING human verification.** This is a `checkpoint:human-verify` (blocking) step that a headless agent CANNOT satisfy — offscreen tests prove behavior + the offscreen-observable stylesheet/objectName state, but cannot prove appearance, contrast, or the live flip on a real window.

**What the human should do (on a real X11 session, NOT headless):**

1. Launch on a bag: `PYTHONPATH="" uv run rosbagger-desktop <path-to-a-bag>` (any ROS 2 fixture or real bag).
2. Confirm the window opens themed (dark by default) — NOT default-Qt gray. Check the nav rail, tables, header sections, splitter handle, and status line read as a deliberate, calm design (robotics-engineer-at-a-desk, D-07) — not a category-reflex navy/cyan look.
3. Open the **View** menu and toggle to **Light**. The whole window (all five panels) should restyle LIVE with no relaunch. Toggle back to Dark.
4. Quit and relaunch — confirm the last-chosen theme PERSISTED.
5. Click through all five panels (inspect / query / tf / record / replay) in both themes — confirm each looks intentionally styled with readable hierarchy and sensible empty/loading states.
6. Spot-check text legibility (contrast) in both themes (covers T-17-10).

**Resume signal:** Type "approved" if it looks revamped and the toggle flips + persists in both themes, or describe what looks off (specific panel / token / contrast issue) so it can be tuned.

## Self-Check: PASSED

All 8 modified files exist on disk; all three commits (d525913, b135669, 691c8f2) are present in git history; the code working tree is clean; every preserved record/replay accessor resolves; the grep gate confirms no inline `setStyleSheet` in panels.
