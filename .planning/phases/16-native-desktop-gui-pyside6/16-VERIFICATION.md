---
status: passed
phase: 16-native-desktop-gui-pyside6
verified: 2026-05-25
method: inline (gsd-verifier not installed; orchestrator verified the DoD against the live repo — build/import, headless test suite, isolation diffs, offline+Qt-free guard, and a full code-review fix pass)
must_haves_total: 5
must_haves_verified: 5
plans_complete: 3
requirements: ["(new milestone v0.3 DoD — native window launches; five-panel parity reusing module APIs; package fully isolated; offline+Qt-free guard green; headless pytest-qt ≥80%)"]
---

# Phase 16: Native Desktop GUI (PySide6) — Verification

Phase goal: ship a native desktop GUI as a new isolated `rosbagger-desktop` package (PySide6/Qt) with full parity to the Textual TUI's five panels, reusing the existing module APIs verbatim, without modifying or regressing anything that already exists.

## Success Criteria (verified against the live repo)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| SC1 | Native window launches via console script | `rosbagger-desktop` console script installed; `PYTHONPATH="" uv run rosbagger-desktop --help` exits 0 WITHOUT constructing QApplication (argparse front door); `QMainWindow` shell builds in headless tests | ✓ |
| SC2 | Five panels reach parity reusing module APIs verbatim | inspect_panel (`collect_bag_info`/`collect_table_schemas`), query_panel (`query`/`collect_table_schemas`/`write_table`/errors), tf_panel (`collect_tf_report`/`NoTransformsError`), record_panel (`list_record_topics`/`record_topics`), replay_panel (`Replayer`/`build_publish_sink`/`list_events`); `test_app_has_five_panels` green | ✓ |
| SC3 | Package fully isolated (PySide6 only in rosbagger-desktop, TUI untouched) | `grep PySide6 packages/*/pyproject.toml` → only `rosbagger-desktop`; `git diff 1c9b5d7..HEAD` over the five existing packages → empty (no existing source touched, TUI included) | ✓ |
| SC4 | Offline import graph stays ROS-free AND Qt-free | `tests/test_offline_guard.py` extended with Qt-free assertions (PySide6/shiboken6 blocklist) + per-module live-import guards; `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → 20 passed; ROS imports lazy (inside methods); live panels capability-gated off without rclpy | ✓ |
| SC5 | Headless pytest-qt tests pass at ≥80% coverage | `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` → 485 passed, 4 skipped, 97.37% (≥80% gate); the 2 `@pytest.mark.live` record/replay tests collect-and-skip in the ROS-free venv (expected) | ✓ |

## Definition of Done

- ✓ `rosbagger-desktop [BAG]` spawns a native Qt window (QMainWindow + nav + QStackedWidget, App-owned shared reader, File ▸ Open via QFileDialog)
- ✓ Full five-panel parity with the TUI; every panel is a thin face over the existing module APIs (no new analysis/bag/SQL/ROS logic)
- ✓ Live panels (record/replay) run blocking work on QThread/QObject workers; replay drives the pure `Replayer` through the SHARED `build_publish_sink` (single publish path, D-05)
- ✓ Isolation invariant: PySide6 confined to the new package; offline import graph ROS-free AND Qt-free; existing packages (incl. TUI) untouched
- ✓ All 19 locked decisions (D-01..D-19) implemented

## Code Review + Fixes

16-REVIEW.md (standard depth, 18 files): 2 critical + 6 warning + 4 info. The user elected to fix criticals + warnings. All 8 critical/warning findings were fixed atomically (commits `ce72de0`, `4511fc3`, `39f195d`, `4e4880b`, `4b1aa55`, `6e0ffa7`, `017b465`, `814053e`) with headless regression tests added:
- CR-01 — use-after-free on panel close (null finished QThread refs + guard `stop_thread` against a deleted C++ object).
- CR-02 — replay rate/loop data race (guard `_apply_rate`/`_apply_loop` + disable controls during a drive).
- WR-01 — cross-panel rclpy.init clash (release replay-owned context before a record scan/start).
- WR-03 — export save dialog (QFileDialog) instead of hardcoded CWD path.
- WR-05 — broaden export catch so Arrow errors surface as a status.
- WR-06 — unify replay rate-parsing contract across Play and Enter.
- WR-02 — guard `_finish_record` against a non-2-tuple worker result.
- WR-04 — clear `_bag_path` on a failed open to stay consistent with `reader`.

The 4 info findings were left as tracked, non-blocking follow-ups in 16-REVIEW.md.

## Human Follow-up (not a blocker for local readiness)

The two semantically-sensitive fixes (CR-02 replay control gating, WR-06 rate contract) are locked by headless behavioral tests, but a human should sanity-check the live-ROS replay path on the `-m live` lane (`tests/test_desktop_live.py`) — the offline suite cannot drive a real concurrent `Replayer.run()`. This is the standing live-lane verification, not a code defect.

## Verdict

PASSED — all 5 success criteria verified locally; full five-panel parity achieved with the isolation invariant intact and all critical/warning review findings fixed. Phase goal achieved.
