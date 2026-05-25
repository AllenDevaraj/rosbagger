---
phase: 17-desktop-revamp-full-visual-design-system-qss-theme-design-to
plan: 01
subsystem: rosbagger-desktop (theme/ subpackage + shell wiring)
tags: [theme, qss, design-tokens, qsettings, pyside6, oklch]
requires: []
provides:
  - "rosbagger_desktop.theme.Tokens / DARK / LIGHT (Qt-free design tokens)"
  - "rosbagger_desktop.theme.build_qss (pure token->QSS string, the single styling source — D-03)"
  - "rosbagger_desktop.theme.ThemeManager (apply/toggle/persist via QApplication + QSettings — D-06)"
  - "cli.main org/app identity + initial theme apply"
  - "MainWindow View-menu live Dark/Light toggle"
affects:
  - "17-03 panel visual rollout (consumes tokens + #status_error objectName, replaces query_panel inline _STATUS_ERROR_STYLE)"
tech-stack:
  added: []  # zero new dependencies (D-04) — pure-Python token->QSS + PySide6/QSettings already present
  patterns:
    - "OKLCH-authored, design-time-baked sRGB hex tokens (no runtime color conversion)"
    - "Pure build_qss(tokens) -> str — unit-testable with no QApplication"
    - "ThemeManager unpolish/polish/update live-flip; QSettings ui/theme persistence"
    - "lazy + parented self-constructed ThemeManager to keep MainWindow.__init__ light"
key-files:
  created:
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/__init__.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/tokens.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/qss.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/theme/manager.py
  modified:
    - packages/rosbagger-desktop/src/rosbagger_desktop/cli.py
    - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py
    - tests/test_desktop.py
decisions:
  - "Token->QSS mechanism (D-04): pure-Python frozen Tokens dataclass + build_qss f-string; zero new deps; theme/tokens.py + theme/qss.py import only stdlib (Qt-free)"
  - "Persistence (D-06): QSettings NativeFormat under org=rosbagger app=rosbagger-desktop; garbage ui/theme value degrades to dark default (T-17-01)"
  - "Toggle home (Open Q1): a checkable &View-menu action wired to ThemeManager.toggle — lowest friction, no toolbar chrome"
  - "Self-constructed ThemeManager is lazy + parented to the window (teardown robustness under offscreen Qt)"
metrics:
  duration: ~50m
  tasks: 3
  files_created: 4
  files_modified: 3
  completed: 2026-05-25
---

# Phase 17 Plan 01: Design-Token + QSS Theme Foundation Summary

A Qt-free `theme/` subpackage (frozen `Tokens` + OKLCH-baked DARK/LIGHT palettes, a pure `build_qss(tokens) -> str`, and a `ThemeManager` that applies/toggles/persists via `QApplication` + `QSettings`), wired into `cli.main` (org/app identity + initial apply before `show()`) and the shell (a live, persisted `&View` Dark/Light toggle) — the token-driven styling foundation (D-03) every panel's 17-03 visual rollout consumes, built with zero new dependencies (D-04) and the offline+Qt-free import graph intact (D-08).

## What Was Built

- **`theme/tokens.py`** — a `@dataclass(frozen=True) Tokens` (bg/surface/text/text_muted/accent/error/border + spacing/radius/type-scale) and two concrete palettes: a neutral-warm dark default and a calm low-chroma light (D-07, NOT the category-reflex navy/cyan tool look). Each color authored in OKLCH (in trailing comments) and stored as a baked sRGB `#rrggbb` — no runtime color conversion. Imports ONLY `dataclasses`.
- **`theme/qss.py`** — the pure `build_qss(t: Tokens) -> str`, the single place QSS strings live (D-03). Explicitly targets the non-inheriting elements (17-RESEARCH Pitfall 3): `QTableView` gridline/selection, `QHeaderView::section`, `QSplitter::handle`, plus a `#status_error` objectName selector (which replaces query_panel's inline `_STATUS_ERROR_STYLE` literal in 17-03). Imports NO Qt.
- **`theme/manager.py`** — `ThemeManager(QObject)`: reads `QSettings().value("ui/theme", "dark")`, `apply()` sets the app stylesheet then unpolishes/polishes/updates top-level widgets for a live flip (Pitfall 2), `toggle()` persists the flipped name then applies. A tampered/garbage persisted value degrades to the dark default (T-17-01).
- **`theme/__init__.py`** — re-exports `Tokens/DARK/LIGHT/build_qss` eagerly; `ThemeManager` is bound lazily via `__getattr__` so a token/qss-only consumer can import the package without pulling PySide6 (D-08).
- **`cli.py`** — `main()` now sets `setOrganizationName("rosbagger")` / `setApplicationName("rosbagger-desktop")` (→ `~/.config/rosbagger/rosbagger-desktop.conf`), constructs + `apply()`s a `ThemeManager` before `window.show()`, and hands it to `MainWindow`. Reuses an existing `QApplication.instance()` when present. All Qt imports stay inside `main()` (help path stays Qt-free).
- **`main_window.py`** — accepts an optional `theme_manager`; a directly-built window lazily self-constructs (and parents) one on first access. Adds a `&View` menu with a checkable "Dark theme" action wired to `ThemeManager.toggle`, reflecting the active name in the check state; exposes `theme_manager` / `theme_action` read-only properties.

## How It Works (data flow)

`cli.main` sets QSettings identity → constructs `ThemeManager` (reads persisted `ui/theme`) → `apply()` (`QApplication.setStyleSheet(build_qss(DARK|LIGHT))` + unpolish/polish) → hands manager to `MainWindow` → `&View ▸ Dark theme` triggers `ThemeManager.toggle()` → flips name, persists to `QSettings`, re-`apply()`s live (no relaunch). On next launch the persisted name is honored at construction.

## Tests (all headless, offscreen, ROS-free)

- `test_qss_*` (pure, no QApplication): `build_qss(DARK)`/`build_qss(LIGHT)` carry every baked token hex; DARK ≠ LIGHT; non-inheriting selectors + `#status_error` present; a fresh-interpreter import of `theme.tokens`/`theme.qss` pulls no PySide6 (D-08).
- `test_theme_apply_*` / `test_theme_toggle_*` / `test_theme_honors_persisted_light_*` / `test_theme_tolerates_garbage_*` (qtbot): apply themes the live app with the active bg hex; toggle flips both `QSettings` and the live stylesheet; a pre-persisted "light" is honored; a garbage value degrades to dark (T-17-01).
- `test_cli_main_wires_identity_and_theme`: `cli.main` sets org/app identity and applies a theme before show.
- `test_view_menu_theme_toggle_flips_live` / `test_main_window_builds_without_theme_manager_arg`: the View action flips `theme_manager.name` + the live stylesheet; a no-arg window still builds a themeable window with a working toggle.
- All theme tests scope `QSettings` to a `tmp_path` IniFormat file via a `theme_scope` fixture (T-17-02 — the dev box `~/.config` is never polluted) and reset the global app stylesheet on teardown.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `cli.main` reuses an existing `QApplication` instance**
- **Found during:** Task 2 (the cli test runs under qtbot, which already owns the QApplication singleton; Qt forbids a second instance — `RuntimeError: Please destroy the QApplication singleton`).
- **Fix:** `app = QApplication.instance() or QApplication(...)`. Also correct real-world behavior (never double-construct the app).
- **Files:** `cli.py`. **Commit:** 7733c16.

**2. [Rule 1 - Robustness] Lazy + parented self-constructed `ThemeManager`**
- **Found during:** Final verification — the known intermittent offscreen-Qt teardown Bus error (CONTEXT host note) was observed; investigated whether the new code aggravated it.
- **Finding:** An interleaved A/B comparison against a clean pre-phase worktree (`986745c`) under equal system load showed the crash rate is load-dependent environmental noise, equivalent on both trees (0/10 each when measured fairly) — NOT introduced by this plan. Confirmed clean `498 passed` / `30 passed` lines on re-run, per the documented "re-run to confirm" guidance.
- **Hardening applied anyway:** the self-constructed `ThemeManager` is now built lazily on first access and parented to the window (destroyed with it), keeping `MainWindow.__init__` light for the many unrelated headless tests and avoiding an orphaned QObject through teardown. Theme tests reset the global app stylesheet on teardown so a theme test's global Qt mutation doesn't bleed into a sibling's teardown.
- **Files:** `main_window.py`, `tests/test_desktop.py`. **Commit:** 728cace.

### Note on the `theme_manager` constructor argument (planned, Task 3 → moved to Task 2)
The plan placed the `MainWindow.theme_manager` parameter in Task 3, but Task 2's `cli.main` test depends on it (cli constructs `MainWindow(..., theme_manager=...)`). The parameter was therefore added in the Task 2 commit and the View-menu wiring that uses it in the Task 3 commit — same end state, ordering adjusted so each task's tests pass independently.

## Known Stubs

None — all theme code is fully wired and tested. (Panel-side adoption of `#status_error` / token styling is explicitly 17-03, not this plan; the selector exists and is tested here.)

## Verification

- `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py` → **30 passed** (clean, no Bus error).
- `PYTHONPATH="" uv run pytest` (full blended suite) → **498 passed, 4 skipped**, **total coverage 84.36% ≥ 80%** (gate holds; theme/tokens 100%, theme/qss 100%, theme/manager 96%, cli 100%).
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` → **20 passed** (offline + Qt-free guard green, D-08).
- `PYTHONPATH="" uv run ruff check packages/rosbagger-desktop/src/rosbagger_desktop/` → clean.

## DoD note (visual sanity check — human)

Offscreen tests prove behavior, not appearance. A human visual sanity check on a real X11 session remains part of the phase DoD (CONTEXT specifics): `PYTHONPATH="" uv run rosbagger-desktop <bag>`, then toggle `&View ▸ Dark theme` and confirm the live flip + persistence across relaunch.

## TDD Gate Compliance

Tasks 1 and 2 followed RED → GREEN: a failing `test(...)` commit (0a2f27a, 22044bb) preceded each `feat(...)` GREEN commit (e10193d, 7733c16). Task 3 (`type="auto"`, not tdd) shipped wiring + its qtbot test together (99a1bb2), with a follow-up robustness refactor (728cace).

## Self-Check: PASSED

All four created files exist on disk; all six commits (0a2f27a, e10193d, 22044bb, 7733c16, 99a1bb2, 728cace) are present in git history; the code working tree is clean.
