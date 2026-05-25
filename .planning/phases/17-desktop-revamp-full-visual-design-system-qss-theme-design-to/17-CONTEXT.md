# Phase 17: Desktop Revamp - Context

**Gathered:** 2026-05-25
**Status:** Ready for planning
**Source:** Locked via AskUserQuestion during phase scoping (mirrored from ROADMAP Phase 17 block). No discuss-phase ceremony — the scope decisions below were answered directly by the user.

<domain>
## Phase Boundary

Transform the `rosbagger-desktop` package (the PySide6 Qt window shipped in Phase 16) from a functional-but-unstyled default-Qt application into an intentionally designed cockpit. Two halves, both delivered in this phase:

1. A **visual design system** — a centralized, token-driven QSS theme applied across the window shell and all five panels (inspect / query / tf / record / replay), shipping **both a dark and a light theme** with a **runtime toggle** that persists across launches.
2. **Cross-panel engineering parity** — generalize the robustness patterns already proven on the query panel (quick tasks 260525-is6 and 260525-kj0) to the other four panels: long-running work off the UI thread, model/view for tabular data, accessible status surfaces.

IN SCOPE: theme/token infrastructure inside the package, dark+light palettes, the persisted toggle, per-panel visual + engineering rework, headless tests, a real-window visual sanity check.

OUT OF SCOPE (carryover from Phase 16 deferrals): packaged/double-click installer (PyInstaller/AppImage); 3D visualization; ANY change to the Textual TUI (`rosbagger-gui`); any new analysis/bag/SQL/ROS logic.
</domain>

<decisions>
## Implementation Decisions (locked)

### Scope (user choice: "Visual + engineering, all 5 panels")
- **D-01:** Both halves ship together — visual design system AND engineering parity — across ALL FIVE panels. Not visual-only; not engineering-only.
- **D-02:** Engineering parity target = the query panel's current bar (post is6/kj0): heavy/blocking calls run off the UI thread on the existing `BlockingWorker`; tabular data renders via `QAbstractTableModel` + `QTableView` (not per-cell `QTableWidgetItem`); status/error surfaces are accessible live regions (with the offscreen-`QAccessible` guard, see D-09). Audit inspect/tf/record/replay and close the gaps to this bar.

### Visual depth (user choice: "Full design system")
- **D-03:** A full design system, not a light styling pass. Centralized **design tokens** (color / spacing / type scale / elevation) are the single source of styling; a QSS theme layer consumes them. NO ad-hoc inline per-widget colors/QSS in panels — styling lives in the theme layer (generalize the query panel's error-style precedent).
- **D-04:** Tokens → QSS mechanism is Claude's discretion at plan/research time (Qt QSS has no native CSS variables). Likely a small in-package Python token module that templates the stylesheet string. MUST stay inside `rosbagger-desktop` — no heavy theming dependency leaking into the offline/Qt-free import graph.

### Theme (user choice: "Both + toggle"; direction: "You decide per usage")
- **D-05:** Ship BOTH a dark and a light theme.
- **D-06:** A runtime toggle flips dark↔light live (no relaunch) and **persists** across launches (settle the persistence mechanism in planning — e.g. `QSettings`).
- **D-07:** Actual palette values are Claude's discretion, chosen against a concrete usage scene (a robotics engineer reading bag data at a desk → a calm, focused default), per impeccable's "theme is never a default" rule. Pin OKLCH-derived token values for both themes during planning/prototype. Avoid the category-reflex palette (generic "tool = dark blue").

### Hard invariants (carryover from Phase 16 — non-negotiable)
- **D-08:** ISOLATION: PySide6 + all theming code stay confined to `rosbagger-desktop`. The offline import graph (`import rosbagger_core` / `import bagq`) stays ROS-free AND Qt-free; `tests/test_offline_guard.py` stays green. Existing packages (core/bagq/record/replay/gui — TUI included) stay untouched.
- **D-09:** THIN-FACE: panels remain pure faces over the module APIs. This phase adds ZERO analysis/bag/SQL/ROS logic and changes NO teaching-message content (core still owns those strings). Visual/threading/a11y changes are presentation-only. The `QAccessible` announcement must keep the `platformName() != "offscreen"` guard (posting it from a worker-thread error path segfaults under offscreen Qt — see precedent commit 7e99a5f).
- **D-10:** Single publish path retained — no new replay publish path (D-05 from Phase 16 still holds).

### Claude's Discretion
- Token→QSS templating mechanism (D-04) and persistence mechanism (D-06).
- Exact OKLCH palette values for both themes (D-07).
- Whether a throwaway visual prototype precedes implementation — RECOMMENDED as the first plan to de-risk the both-themes design system before committing (the user picked "full design system" over "decide after a prototype," but a prototype as plan 1 is a sequencing choice, not a scope change).
- Per-panel plan granularity and wave structure.
- Where the toggle lives in the shell (menu / toolbar / status bar).
</decisions>

<specifics>
## Specific Ideas

- The query panel is the reference implementation for BOTH halves: its model/view (`_ResultTableModel`), `BlockingWorker` offload, `QSplitter` layout, and accessible `_set_status(text, *, is_error)` helper are the patterns to generalize. Read it first.
- "Looks revamped" is the user's actual goal — the visual layer is what makes the difference subjectively, so don't let it become an afterthought behind the engineering parity.
- Offscreen headless tests prove behavior, not appearance — a human visual sanity check on a real X11 window (`PYTHONPATH="" uv run rosbagger-desktop <bag>`) is part of the DoD.
</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Reference implementation (the patterns to generalize)
- `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py` — model/view, BlockingWorker offload, QSplitter, accessible error-styled status. The bar all panels must reach.
- `packages/rosbagger-desktop/src/rosbagger_desktop/workers.py` — the `BlockingWorker` QObject+QThread pattern.
- `packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py` — the shell (nav + QStackedWidget, shared reader) where the theme + toggle hook in.
- `.planning/quick/260525-is6-query-panel-threaded-modelview/` and `.planning/quick/260525-kj0-query-panel-layout-a11y/` — the two quick-task SUMMARYs documenting these patterns + gotchas.

### Phase 16 design contract + invariants
- `docs/superpowers/specs/2026-05-25-rosbagger-desktop-gui-design.md` — the authoritative desktop design spec (isolation rules, package layout, panel→API map, threading, testing).
- `.planning/phases/16-native-desktop-gui-pyside6/16-CONTEXT.md` — Phase 16 locked decisions (D-01..D-19) this phase must not violate.

### Isolation guard to keep green
- `tests/test_offline_guard.py` — ROS-free AND Qt-free core import graph assertions.

### Design-thinking skills (installed globally, ~/.claude/skills)
- `pyside6-ui-engineer` — Qt Widgets + UX judgment (theme as a finishing layer over good structure; off-thread work; model/view; accessible names; edge states).
- `impeccable` — visual design system thinking (OKLCH color, "theme is never a default," anti-slop). Web-oriented `live` mode does NOT apply to Qt; its color/hierarchy/token principles do.

### Host constraint
- ROS is sourced globally: prefix every `uv`/`pytest`/`ruff` with `PYTHONPATH=""`; tests run headless with `QT_QPA_PLATFORM=offscreen`. An intermittent `Fatal Python error: Bus error` at process EXIT under offscreen Qt is a known teardown artifact, not a failure — re-run to confirm the clean pass line.
</canonical_refs>

<deferred>
## Deferred Ideas
- Packaged/double-click installer (PyInstaller / AppImage) — future follow-up.
- 3D visualization — permanently out of scope.
- Live-ROS replay sanity check on the `-m live` lane — standing Phase 16 follow-up, not reopened here.
</deferred>

---

*Phase: 17-desktop-revamp-full-visual-design-system-qss-theme-design-to*
*Context locked: 2026-05-25 from user scoping decisions*
