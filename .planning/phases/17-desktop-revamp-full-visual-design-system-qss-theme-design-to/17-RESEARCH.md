# Phase 17: Desktop Revamp — Research

**Researched:** 2026-05-25
**Domain:** PySide6 / Qt Widgets — QSS theming, design tokens, model/view, QThread parity
**Confidence:** HIGH (codebase verified directly; PySide6 6.11.1 + pytest-qt 4.5.0 confirmed installed)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Both halves ship together — visual design system AND engineering parity — across ALL FIVE panels.
- **D-02:** Engineering parity target = the query panel's current bar: heavy/blocking calls off the UI thread on `BlockingWorker`; tabular data via `QAbstractTableModel` + `QTableView` (not `QTableWidgetItem`); status/error surfaces as accessible live regions (with the offscreen-`QAccessible` guard, D-09). Audit inspect/tf/record/replay and close the gaps.
- **D-03:** Full design system. Centralized design tokens (color / spacing / type scale / elevation) are the single source of styling; a QSS theme layer consumes them. NO ad-hoc inline per-widget colors/QSS in panels — styling lives in the theme layer.
- **D-04:** Tokens → QSS mechanism is Claude's discretion (Qt QSS has no native CSS variables). Likely a small in-package Python token module that templates the stylesheet string. MUST stay inside `rosbagger-desktop` — no heavy theming dependency leaking into the offline/Qt-free import graph.
- **D-05:** Ship BOTH a dark and a light theme.
- **D-06:** A runtime toggle flips dark↔light live (no relaunch) and persists across launches (e.g. `QSettings`).
- **D-07:** Palette values are Claude's discretion, chosen against a concrete usage scene (robotics engineer reading bag data at a desk → calm, focused default). Pin OKLCH-derived token values for both themes. Avoid the category-reflex palette.
- **D-08:** ISOLATION: PySide6 + all theming code stay confined to `rosbagger-desktop`. The offline import graph (`import rosbagger_core` / `import bagq`) stays ROS-free AND Qt-free; `tests/test_offline_guard.py` stays green. Existing packages untouched.
- **D-09:** THIN-FACE: panels stay pure faces. ZERO analysis/bag/SQL/ROS logic, NO teaching-message content change. Visual/threading/a11y changes are presentation-only. The `QAccessible` announcement keeps the `platformName() != "offscreen"` guard.
- **D-10:** Single publish path retained — no new replay publish path.

### Claude's Discretion
- Token→QSS templating mechanism (D-04) and persistence mechanism (D-06).
- Exact OKLCH palette values for both themes (D-07).
- Whether a throwaway visual prototype precedes implementation — RECOMMENDED as plan 1.
- Per-panel plan granularity and wave structure.
- Where the toggle lives in the shell (menu / toolbar / status bar).

### Deferred Ideas (OUT OF SCOPE)
- Packaged/double-click installer (PyInstaller / AppImage).
- 3D visualization.
- Live-ROS replay sanity check on the `-m live` lane.
</user_constraints>

## Summary

The codebase is in better shape than the phase brief implies. The query panel already establishes every engineering pattern (lazy `_ResultTableModel`, `BlockingWorker` offload, accessible `_set_status` with the offscreen `QAccessible` guard, `QSplitter` layout). The two LIVE panels (record/replay) already run blocking work on `BlockingWorker` threads. The real engineering-parity work is concentrated in the two OFFLINE panels — **inspect** and **tf** — which both use `QTableWidget`/`QTableWidgetItem` per-cell and call `collect_bag_info`/`collect_table_schemas`/`collect_tf_report` synchronously in `refresh_view` on the UI thread.

For theming: **Qt QSS has no native CSS variables** [VERIFIED: codebase has none; Qt docs confirm]. The leading hypothesis is correct — a **pure-Python token module that format-strings the QSS at runtime** is the right mechanism. It adds zero dependencies, lives entirely in `rosbagger-desktop`, and cannot leak into the offline graph. The two third-party options (`qdarktheme`, `qt-material`) are rejected: each is a runtime dependency added to the package, neither gives the OKLCH-authored bespoke palette D-07 demands, and each is one more import the package carries. A `QPalette`-only approach is also rejected — QSS gives far finer control over the specific widgets in play (`QHeaderView`, `QSplitter`, `QTableView` grid/selection) and the query panel already proves QSS is the project's styling idiom.

Live switching is `app.setStyleSheet(new_qss)` + a `style().unpolish(w)/polish(w)` pass on top-level widgets to flush cached style state; persistence is `QSettings` (NativeFormat → `~/.config/rosbagger/rosbagger-desktop.conf` on Linux, verified). OKLCH → Qt is a design-time concern: author palettes in OKLCH for perceptual reasoning, then bake final sRGB hex strings into the token module — no runtime color-space conversion, no dependency.

**Primary recommendation:** Build a pure-Python `theme/` subpackage in `rosbagger-desktop` (tokens dataclass → QSS template function → `ThemeManager` that owns `setStyleSheet` + `QSettings` persistence + live unpolish/polish). Lift `_ResultTableModel` out of `query_panel.py` into `widgets/` as a shared model. Convert inspect + tf to `QTableView` + a shared/derived model and move their core calls onto `BlockingWorker`. Generalize `_set_status` into a shared status helper. Ship dark + light token sets authored in OKLCH, baked to hex.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Design tokens (color/space/type/elevation) | `theme/tokens.py` (pure data) | — | Single source of styling values (D-03); no Qt import needed, plain dataclasses/dicts |
| Token → QSS string | `theme/qss.py` (pure function) | — | Templating is string work; keep it Qt-free and unit-testable without a QApplication |
| Apply + switch + persist theme | `theme/manager.py` (`ThemeManager`) | `main_window` (owns toggle + manager) | The only tier that touches `QApplication`/`QSettings`; the toggle widget lives in the shell |
| Shared result table model | `widgets/result_model.py` | panels (construct + feed) | Lift `_ResultTableModel`; panels stay thin faces |
| Off-thread core calls | panel method bodies → `BlockingWorker` | `workers.py` (unchanged) | Existing pattern; inspect/tf must adopt it |
| Accessible status surface | shared `widgets` status helper | panels (call it) | Generalize `_set_status`; keep the offscreen guard (D-09) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PySide6 | 6.11.1 (pinned `>=6.10,<6.12`) | Qt Widgets, QSS, QSettings, model/view | Already the package's only Qt dep [VERIFIED: `uv run python -c "import PySide6"` → 6.11.1] |
| pytest-qt | 4.5.0 | Headless `qtbot` driving of real widgets | Existing test harness [VERIFIED: installed] |

**No new runtime dependencies.** Theming is pure-Python + PySide6. This is the load-bearing finding for D-04/D-08.

### Alternatives Considered (theming mechanism)
| Instead of | Could Use | Tradeoff / Why Rejected |
|------------|-----------|-------------------------|
| Pure-Python token→QSS | `pyqtdarktheme` / `qdarktheme` | Adds a runtime dep to `rosbagger-desktop`; ships its own (non-OKLCH, non-bespoke) palette — fights D-07; one more import in the Qt package. [ASSUMED — not installed/verified] |
| Pure-Python token→QSS | `qt-material` | Same: runtime dep, Material palettes (a category-reflex look D-07 warns against), template XML system you'd fight to override. [ASSUMED] |
| QSS templating | `QPalette` only + minimal QSS | `QPalette` can't reach `QHeaderView`/`QSplitter`/`QTableView` grid+selection styling cleanly; the query panel already uses QSS as the idiom — splitting styling across two systems is worse. Use QSS as primary; optionally set a couple of `QPalette` roles for native dialogs. |

**Mechanism decision (D-04): pure-Python token module → QSS f-string/template, applied via `QApplication.setStyleSheet`.** No `pip install` line — it's all first-party code.

## Package Legitimacy Audit

No external packages are installed by this phase. PySide6 and pytest-qt are already present and pinned. **Disposition: N/A — zero new packages.** slopcheck not run (nothing to check).

## Architecture Patterns

### Recommended subpackage structure
```
rosbagger_desktop/
├── theme/                  # NEW — the design system (pure-Python + PySide6 apply layer)
│   ├── __init__.py         # re-export ThemeManager, Theme enum, token sets
│   ├── tokens.py           # OKLCH-authored → baked-hex token dataclasses; DARK + LIGHT instances
│   ├── qss.py              # build_qss(tokens) -> str  (pure function, no QApplication needed)
│   └── manager.py          # ThemeManager: apply/toggle/persist via QApplication + QSettings
├── widgets/
│   ├── result_model.py     # NEW — _ResultTableModel lifted out of query_panel (shared)
│   └── status.py           # NEW — accessible status helper generalized from _set_status
└── panels/                 # inspect/tf converted to QTableView + worker; all reference theme objectNames
```

### Pattern 1: Token module → QSS template (the D-04 mechanism)
**What:** A frozen dataclass of token values per theme; a pure `build_qss(t)` that f-strings them into one stylesheet string keyed by `objectName`/widget class. Tokens authored in OKLCH (comments) but stored as final sRGB hex.
**When to use:** All package styling. Panels set `objectName`s; they never write inline QSS.
```python
# theme/tokens.py  — pure data, no Qt import (unit-testable, offline-clean)
from dataclasses import dataclass

@dataclass(frozen=True)
class Tokens:
    bg: str; surface: str; text: str; text_muted: str
    accent: str; error: str; border: str
    space_sm: int; space_md: int; radius: int
    font_size_base: int; font_size_mono: int

# oklch(0.18 0.01 250) → baked hex (author in OKLCH, store sRGB — see OKLCH section)
DARK = Tokens(bg="#1a1c20", surface="#22252b", text="#e6e8ec", text_muted="#9aa0a8",
              accent="#5aa9e6", error="#e06c75", border="#33373d",
              space_sm=4, space_md=8, radius=4, font_size_base=13, font_size_mono=12)
LIGHT = Tokens(bg="#f6f7f9", surface="#ffffff", text="#1c1f24", text_muted="#5b626b",
               accent="#2f6fb0", error="#c0392b", border="#d6dade",
               space_sm=4, space_md=8, radius=4, font_size_base=13, font_size_mono=12)
```
```python
# theme/qss.py  — pure function; the ONE place QSS strings live (D-03)
def build_qss(t: Tokens) -> str:
    return f"""
    QWidget {{ background: {t.bg}; color: {t.text}; font-size: {t.font_size_base}px; }}
    QTableView {{ background: {t.surface}; gridline-color: {t.border};
                  selection-background-color: {t.accent}; }}
    QHeaderView::section {{ background: {t.surface}; color: {t.text_muted};
                            border: none; border-bottom: 1px solid {t.border};
                            padding: {t.space_sm}px; }}
    QSplitter::handle {{ background: {t.border}; }}
    QLabel#status_error {{ color: {t.error}; border: 1px solid {t.error};
                           padding: {t.space_sm}px; }}
    """
```

### Pattern 2: Live theme switch + persistence (D-06)
**What:** `ThemeManager` owns the active theme, applies it to the running `QApplication`, force-refreshes already-shown widgets, and persists the choice.
**Why the unpolish/polish pass:** `app.setStyleSheet` re-applies, but widgets already painted may cache style data; iterating `app.allWidgets()` (or just the top-level windows) with `style().unpolish(w); style().polish(w); w.update()` flushes it so the flip is visible without relaunch.
```python
# theme/manager.py
from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QApplication
from .qss import build_qss
from .tokens import DARK, LIGHT

class ThemeManager(QObject):
    _KEY = "ui/theme"
    def __init__(self) -> None:
        super().__init__()
        self._name = QSettings().value(self._KEY, "dark")  # persisted choice (D-06)

    def apply(self) -> None:
        tokens = DARK if self._name == "dark" else LIGHT
        app = QApplication.instance()
        app.setStyleSheet(build_qss(tokens))
        for w in app.topLevelWidgets():          # flush cached style on shown widgets
            w.style().unpolish(w); w.style().polish(w); w.update()

    def toggle(self) -> None:
        self._name = "light" if self._name == "dark" else "dark"
        QSettings().setValue(self._KEY, self._name)   # persist immediately
        self.apply()
```
**QSettings setup (do ONCE in `cli.main`, before constructing `ThemeManager`):**
```python
QCoreApplication.setOrganizationName("rosbagger")
QCoreApplication.setApplicationName("rosbagger-desktop")
# → ~/.config/rosbagger/rosbagger-desktop.conf  [VERIFIED on this box]
```

### Pattern 3: Lift the shared result model
`_ResultTableModel` in `query_panel.py` (lines 89–152) is already generic over a `pyarrow.Table`. Move it verbatim to `widgets/result_model.py`, re-export from `widgets/__init__.py`, and have query import it from there. Inspect/tf data is NOT pyarrow Tables (they render dataclass rows) — so for them, EITHER (a) a small sibling `RowsTableModel(headers, rows)` over `list[tuple[str,...]]`, or (b) keep them on a list-of-rows model. Recommendation: add one generic `RowsTableModel` for the dataclass-derived panels; keep the pyarrow model for query. Two small models, both in `widgets/`.

### Anti-Patterns to Avoid
- **Inline per-widget QSS in panels.** D-03 forbids it. The lone current instance is `query_panel._set_status` setting `_STATUS_ERROR_STYLE`/`_STATUS_NEUTRAL_STYLE` (lines 82–83, 318). Generalize it to an `objectName` (`status_error`) toggled in the shared status helper; the COLOR comes from the theme QSS, not a literal in the panel.
- **Subclassing QThread with work in `run()`.** `workers.py` already documents this as the anti-pattern; keep the `QObject`+`moveToThread` form.
- **Converting ns timestamps to datetime in the model.** The existing model `str()`s every cell deliberately (temporal-safe). Preserve this when generalizing.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSS-variable substitution into QSS | A regex `@var` preprocessor | Python f-string/`.format` on a token dataclass | Qt has no QSS variables; f-string is simpler, type-checked, and zero-dep |
| Off-thread core calls | A new threading primitive | The existing `BlockingWorker`/`run_on_thread`/`stop_thread` | Already handles teaching-error contract + teardown discipline |
| Cross-launch persistence | A hand-rolled config file | `QSettings` (NativeFormat) | Standard Qt, atomic, correct Linux path, already verified |
| Lazy table rendering | A fresh model | Lift the existing `_ResultTableModel` | Already lazy, allocation-light, tested |
| Color-space conversion at runtime | An OKLCH→sRGB function in the app | Bake hex at design time | No runtime need; keeps the package dependency-light (D-04) |

**Key insight:** Everything this phase needs already exists in-package or in PySide6. The work is *generalization and styling*, not new infrastructure.

## Per-Panel Engineering-Parity Gap Assessment (D-02)

Bar = query panel: `QTableView`+`QAbstractTableModel`, blocking work on `BlockingWorker`, accessible `_set_status` with offscreen guard.

| Panel | Table rendering | Off-thread? | Status/a11y | Gap to close |
|-------|-----------------|-------------|-------------|--------------|
| **query** (reference) | `QTableView` + lazy `_ResultTableModel` ✅ | `BlockingWorker` ✅ | `_set_status` + offscreen-guarded `QAccessible` ✅ | NONE — source of patterns; lift its model to `widgets/` |
| **inspect** | `QTableWidget`+`QTableWidgetItem` ×2 (bag-info, schemas) ❌ | `collect_bag_info`/`collect_table_schemas` run sync in `refresh_view` on UI thread ❌ | plain `QLabel` header, no `setAccessibleName`, no error style ❌ | Convert both tables to `QTableView`+model; move core calls to a `BlockingWorker`; adopt shared status helper |
| **tf** | `QTableWidget`+`QTableWidgetItem` ×2 (edges, gaps) ❌ | `collect_tf_report` sync in `refresh_view` ❌ | plain `QLabel` status, has teaching `NoTransformsError` text but no a11y name/announce ❌ | Same as inspect: model/view + worker; route `NoTransformsError` through shared accessible status |
| **record** | checkable `QListWidget` (not tabular — OK as-is) | discovery + record both on `BlockingWorker` ✅ | plain `QLabel`, no a11y name/announce ⚠️ | Adopt shared accessible status helper; otherwise threading is already at bar |
| **replay** | `Scrubber` widget (not tabular — OK as-is) | drive loop on `BlockingWorker` ✅ | plain `QLabel`, no a11y name/announce ⚠️ | Adopt shared accessible status helper; threading already at bar |

**Generalizable shape:** `_ResultTableModel` lifts cleanly to `widgets/`. Inspect/tf need a second generic `RowsTableModel` (their rows are dataclasses, not pyarrow). All five panels can share one accessible status helper (generalized `_set_status`). Record/replay are already threaded — they need only the status/a11y + visual (objectName/theme) treatment, NOT a threading rewrite.

## OKLCH → Qt Color (D-07)

**Fact:** Qt accepts sRGB only — `QColor("#rrggbb")`, named colors, or `rgb()`/`hsv()`; QSS color properties take the same. There is **no OKLCH input to Qt** [CITED: Qt QColor / QSS reference]. PySide6 `QColor` does not parse `oklch()`.

**Practical path (recommended): author in OKLCH, bake to hex.**
1. Reason about each token in OKLCH (perceptually uniform lightness/chroma/hue — the impeccable discipline) during design.
2. Convert each OKLCH value to sRGB hex *once, at design time*, using any external tool (a browser devtools color picker, an online OKLCH→hex converter, or a throwaway script).
3. Store the final `#rrggbb` string in `tokens.py`, with the source OKLCH in a comment for future reasoning.

**A runtime conversion helper is NOT worth it:** it adds code/complexity for a value that never changes at runtime, and risks pulling a color library into the Qt package. Keep OKLCH as design-time reasoning; ship hex. (If a tiny pure-Python OKLCH→sRGB function is ever wanted for a prototype, it's ~30 lines of matrix math with no deps — but it is not needed in the shipped product.)

**Palette direction for the usage scene (D-07):** a robotics engineer reading dense bag tables at a desk. Favor a calm, low-chroma neutral surface with one restrained accent (selection/links) and a single semantic error hue. The dark default should be a true neutral-warm dark (not the category-reflex navy/cyan "tool" look). The `DARK`/`LIGHT` values in Pattern 1 are a starting hypothesis to be finalized in the prototype plan — [ASSUMED] exact values pending the prototype.

## Common Pitfalls

### Pitfall 1: Offscreen QAccessible segfault (already mitigated — must preserve)
**What goes wrong:** Posting a `QAccessibleEvent(Alert)` under `QT_QPA_PLATFORM=offscreen` crashes at the C++ level (uncatchable Bus error). [VERIFIED: commit 7e99a5f].
**How to avoid:** Keep the `QGuiApplication.platformName() != "offscreen"` guard when generalizing `_set_status` into the shared status helper. Any new a11y announcement on inspect/tf/record/replay MUST route through this guarded helper.

### Pitfall 2: Stylesheet doesn't visibly flip on live toggle
**What goes wrong:** `setStyleSheet` re-applies but already-shown widgets keep cached style state; the user sees a partial/stale repaint.
**How to avoid:** After `setStyleSheet`, iterate top-level widgets (or `allWidgets()` for thoroughness) and `style().unpolish(w); style().polish(w); w.update()`. Test it via observable state (see Pitfall 4), not pixels.

### Pitfall 3: QSS not cascading to `QHeaderView` / `QSplitter` / `QTableView` internals
**What goes wrong:** Styling `QTableView` doesn't style its header or the splitter handle; they're separate styleable elements.
**How to avoid:** Target them explicitly: `QHeaderView::section`, `QSplitter::handle`, `QTableView` `gridline-color`/`selection-background-color`. The Pattern-1 QSS already shows the selectors. Set `objectName`s on panel-specific widgets so the theme can target them without inline QSS.

### Pitfall 4: Testing a theme headlessly
**What goes wrong:** Offscreen Qt renders no pixels — you can't assert appearance.
**How to avoid (this is fully testable):** Assert *observable state*, not pixels:
- `QApplication.instance().styleSheet()` is non-empty and contains an expected token-derived substring (e.g. the dark `bg` hex) after `ThemeManager.apply()`.
- Unit-test `build_qss(DARK)` / `build_qss(LIGHT)` as **pure strings** with NO QApplication at all — assert each token value appears.
- After `toggle()`, assert `QSettings().value("ui/theme")` flipped and `styleSheet()` now contains the other theme's hex.
- a11y: assert `widget.accessibleName()` / `accessibleDescription()` are set; the announce path stays a no-op offscreen (Pitfall 1).
The pure-string `build_qss` test is the cleanest proof the design system is token-driven (D-03) and needs no Qt event loop.

### Pitfall 5: Bus error at process exit under offscreen (pre-existing, not a failure)
**What goes wrong:** An intermittent `Fatal Python error: Bus error` at interpreter EXIT under offscreen Qt.
**How to avoid:** Per CONTEXT, this is a known teardown artifact — re-run to confirm the clean pass line. Don't chase it as a phase regression.

### Pitfall 6: Offline-guard regression from a stray top-level Qt import
**What goes wrong:** Putting `from PySide6 import ...` somewhere reachable from `rosbagger_core`/`bagq` breaks `test_offline_guard.py::test_import_core_does_not_pull_pyside6`.
**How to avoid:** All theme code lives in `rosbagger-desktop` only (D-08). The `theme/tokens.py` and `theme/qss.py` modules import NO Qt (pure data + string) so they're trivially clean; `theme/manager.py` imports PySide6 but is never reached from the offline packages. Run `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` as the gate.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-qt 4.5.0 (`qtbot`) |
| Config / harness | `tests/test_desktop.py` (offscreen set at module top before PySide6 import), `tests/test_desktop_live.py` |
| Quick run | `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest tests/test_desktop.py -x` |
| Full suite | `PYTHONPATH="" uv run pytest` |
| Offline gate | `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` |

### Phase Requirements → Test Map
| Requirement | Behavior | Test Type | Automated Command | Exists? |
|-------------|----------|-----------|-------------------|---------|
| D-03/D-04 | `build_qss(DARK)`/`build_qss(LIGHT)` contain every token value | unit (no Qt) | `pytest tests/test_desktop.py -k qss` | ❌ Wave 0 |
| D-06 | `ThemeManager.apply()` sets non-empty app stylesheet with token hex | qtbot | `pytest tests/test_desktop.py -k theme_apply` | ❌ Wave 0 |
| D-06 | `toggle()` flips `QSettings` value + stylesheet | qtbot | `pytest tests/test_desktop.py -k theme_toggle` | ❌ Wave 0 |
| D-02 | inspect/tf render via `QTableView` (`.model().rowCount()>0`) | qtbot | `pytest tests/test_desktop.py -k inspect` / `-k tf` | ⚠️ exists for QTableWidget; update to model API |
| D-02 | inspect/tf core calls run off UI thread (worker waitUntil) | qtbot | `pytest tests/test_desktop.py -k inspect_threaded` | ❌ Wave 0 |
| D-09 | offline guard stays green | subprocess | `pytest tests/test_offline_guard.py` | ✅ |

### Wave 0 Gaps
- [ ] `tests/test_desktop.py` — add `build_qss` pure-string tests (no QApplication).
- [ ] `tests/test_desktop.py` — add `ThemeManager` apply/toggle/persist tests (use a `tmp_path` QSettings or set org/app to a temp scope to avoid polluting the dev box's real `~/.config`).
- [ ] Update existing inspect/tf assertions from `QTableWidget.rowCount()` to `.model().rowCount()` once converted.
- [ ] Add worker/`waitUntil` assertions for inspect/tf threaded refresh (mirror query panel's threaded tests).

*Existing harness (offscreen, qtbot, fixture-bag writers) covers the infrastructure — gaps are net-new theme tests + model-API migration of existing panel tests.*

## State of the Art

| Old Approach (current code) | Current Approach (this phase) | Impact |
|-----------------------------|-------------------------------|--------|
| `QTableWidget` + per-cell `QTableWidgetItem` (inspect, tf) | `QTableView` + `QAbstractTableModel` | Lazy, allocation-light; matches query panel bar |
| Inline `_STATUS_ERROR_STYLE` literal in query panel | `objectName` + theme-owned color | Token-driven styling (D-03); no inline QSS |
| Default unstyled Qt | Token-driven dark+light QSS theme | The "looks revamped" goal |
| Sync core calls in inspect/tf `refresh_view` | `BlockingWorker` offload | UI never freezes on a large bag |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `qdarktheme`/`qt-material` add a runtime dep and ship non-bespoke palettes | Alternatives | Low — even if usable they violate the zero-heavy-dep + OKLCH-bespoke intent; recommendation stands regardless |
| A2 | Exact DARK/LIGHT hex token values | OKLCH section / Pattern 1 | Medium — these are starting hypotheses; the prototype plan finalizes them (D-07 is explicitly Claude's discretion) |
| A3 | Inspect/tf core calls are "heavy enough" to warrant threading | Gap assessment | Low — D-02 mandates the pattern regardless of current bag size; threading is the parity bar, not an optimization |

## Open Questions

1. **Where does the theme toggle live in the shell?**
   - What we know: D-06 wants a runtime toggle; CONTEXT says menu/toolbar/status-bar is Claude's discretion.
   - Recommendation: a checkable action in the existing File-adjacent menu bar (add a "View" menu) — lowest-friction, discoverable, no new toolbar chrome. Decide in planning.

2. **One shared `RowsTableModel` vs. per-panel models for inspect/tf?**
   - What we know: query's model is pyarrow-specific; inspect/tf rows are dataclasses.
   - Recommendation: one generic `RowsTableModel(headers, rows)` over `list[tuple[str,...]]` in `widgets/`, plus the lifted pyarrow model for query. Two small models total.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PySide6 | all theming/UI | ✓ | 6.11.1 | — |
| pytest-qt | headless tests | ✓ | 4.5.0 | — |
| X11 display | DoD visual sanity check | (dev box only) | — | offscreen tests prove behavior; human runs `PYTHONPATH="" uv run rosbagger-desktop <bag>` on a real session |

No missing blocking dependencies. No new packages to install.

## Sources

### Primary (HIGH confidence)
- Direct codebase read: `query_panel.py`, `workers.py`, `main_window.py`, `inspect_panel.py`, `tf_panel.py`, `record_panel.py`, `replay_panel.py`, `widgets/`, `cli.py`, `capabilities.py`, `tests/test_offline_guard.py`, `tests/test_desktop.py`.
- `PYTHONPATH="" uv run python -c "import PySide6"` → 6.11.1; pytest-qt 4.5.0 [VERIFIED].
- `QSettings` Linux path verified live → `~/.config/rosbagger/rosbagger-desktop.conf` (NativeFormat) [VERIFIED].
- `git show 7e99a5f` — offscreen QAccessible guard precedent [VERIFIED].

### Secondary (MEDIUM confidence)
- Qt QSS / QColor reference: QSS has no CSS variables; QColor is sRGB-only [CITED: doc.qt.io QStyleSheet / QColor].

## Metadata

**Confidence breakdown:**
- Theming mechanism (D-04): HIGH — codebase confirms zero CSS-var support; pure-Python is unambiguously the right fit, dependency-free.
- Live switch + persistence (D-06): HIGH — QSettings path and setStyleSheet/polish flow verified.
- Per-panel gap assessment (D-02): HIGH — read every panel; gaps are concrete.
- OKLCH→Qt (D-07): HIGH on mechanism (bake hex), MEDIUM on exact values (prototype finalizes).
- Pitfalls: HIGH — segfault guard verified via commit; headless-test strategy proven by existing harness.

**Research date:** 2026-05-25
**Valid until:** ~2026-06-25 (stable — PySide6 pinned, no fast-moving deps)
