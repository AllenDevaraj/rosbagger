# Phase 19 Research: Replay Snippet Loop & Advanced Controls Panel

**Phase:** 19 (REP-03). Verified by source read on 2026-05-29 (post-Phase-18). Builds directly on Phase 18's thread-safe scheduler + live-scrub desktop. No unknowns — design below is decided; planner/executor implement as written.

## 1. Current architecture (anchors, post-Phase-18)

**scheduler.py (`rosbagger_replay`)** — stdlib-only `Replayer`. Phase 18 added `self._lock` + `self._wake`; all setters are lock-guarded + wake; `run()` holds the lock only for fast reads + cursor advance + transitions. The end-of-stream branch is at the bottom of `run()`'s advance block:
```
if self._cursor >= len(self._items):
    if self._loop:
        self._cursor = 0          # whole-bag loop: rewind to index 0 (WR-02)
    else:
        self._state = State.DONE   # clean end
```
Bound guards (`max_messages`/`duration`) fire BEFORE this branch — DONE wins over loop (W4). `seek(t_offset_ns)` lands the cursor on the first item with `t_ns >= items[0].t_ns + offset`. `position_fraction` = `(items[cursor].t_ns - items[0].t_ns) / span`.

**replay_panel.py (`rosbagger_desktop`)** — `__init__` builds `_status` (QLabel) + `_scrubber` (Scrubber) + a `control_bar` QHBoxLayout (Play/Pause/Step + rate QLineEdit + loop QCheckBox), assembled into a `QVBoxLayout` (status, scrubber, control_bar, stretch). Phase 18 added `_position_timer` (live playhead poll). The panel reaches the window for `reader`/`ros_available`/`default_typestore`. `_bag_span_ns` + `_item_count` set in `_ensure_transport`.

**scrubber.py (`widgets/`)** — `Scrubber(QSlider)`: 0.._RESOLUTION (1000) horizontal slider. `set_position(frac)` (programmatic, `_suppress_emit`-guarded), `position` prop, `set_markers`/`markers` (event ticks), `seeked(float)` on USER value change with `_MARKER_SNAP_FRACTION` snapping, `paintEvent` draws base slider + marker ticks. `_clamp01` helper. Offline-clean (PySide6 + `dataclasses` only).

**theme/qss.py** — `build_qss(tokens) -> str`; objectName/class-keyed selectors; tokens from `theme/tokens.py` (DARK/LIGHT). No inline color anywhere — Phase 19 region/handle colors must be added here as tokens, not literals in the widget.

## 2. Design

### 2a. Scheduler region loop (19-01) — `set_loop_region` / `clear_loop_region` + a run() wrap branch
- Store the region as ABSOLUTE `t_ns` bounds: `self._loop_in_ns: int | None`, `self._loop_out_ns: int | None` (both None = no region). Absolute (not offset) so it shares the `position_fraction` basis the panel maps fractions through.
- `set_loop_region(in_ns, out_ns)`: lock-guarded; normalize so `in_ns <= out_ns`; set both; `self._wake.set()`. `clear_loop_region()`: lock-guarded set both None + wake. (A `loop_region` read property returning `(in,out)|None` for tests.)
- **run() wrap branch** — region-loop is active when BOTH bounds are not None. Replace ONLY the end-of-stream `if self._cursor >= len(self._items)` block's behavior when active, AND add a region-end check: after the advance + bound guards (so W4 still wins — DONE/bound beats region wrap), if region active:
  - compute `wrap = (self._cursor >= len(self._items)) or (self._items[self._cursor].t_ns > self._loop_out_ns)`;
  - if `wrap`: set `self._cursor` to the first index with `t_ns >= self._loop_in_ns` (the same `next(...)` scan `seek` uses; clamp to `len` → if the in-bound is past end, treat as DONE to avoid an infinite empty loop).
  - else fall through (keep playing toward `t_out`).
  When region is NOT active, the existing `_loop` / DONE branch is unchanged.
- Precedence: bound guards (max_messages/duration) checked FIRST (unchanged) → DONE wins (W4). Region wrap takes precedence over the whole-bag `_loop` rewind when a region is set (a region is a more specific intent). Document this.
- Edge cases: empty region (in==out landing on one item) → republishes that item each pass (acceptable; the panel won't normally set a zero-width region); in-bound past end → DONE (no infinite no-publish loop); region set mid-run is thread-safe (lock + wake, honored at the next advance).

### 2b. Scrubber dual handles (19-02)
- State: `self._loop_in: float | None`, `self._loop_out: float | None` (fractions) + an "active drag handle" enum/flag. `set_loop_region(in_frac, out_frac)` / `clear_loop_region()` (programmatic, repaint, NO emit) + a `loop_region` read prop. New signal `region_changed = Signal(float, float)` emitted ONLY on a user handle drag.
- Paint (extend `paintEvent` after the base slider + markers): a semi-transparent shaded rect from `in_frac*width` to `out_frac*width`, plus two handle glyphs (thin vertical bars) at the bounds. Colors come from NEW theme tokens (e.g. `region_fill`, `region_handle`) added to `tokens.py` + `build_qss`/a small palette accessor — NO literal hex in the widget. (QSS can't paint a custom region directly; if the painter needs the color, expose it via a token-derived QColor resolved from a property the QSS sets, or a module-level token import — keep the VALUES in the token module, not inline in scrubber.py.)
- Mouse: override `mousePressEvent` to hit-test near a handle (within ~handle-pixel tolerance of `in`/`out` x); if hit, enter handle-drag mode and on `mouseMoveEvent` update that handle's fraction (clamp; keep `in<=out` by swapping roles or clamping against the other), emit `region_changed(in,out)` on move/release; if NOT near a handle, fall through to the base QSlider behavior (the existing playhead seek). Be careful not to break the existing `seeked` click/drag — only intercept when a handle is grabbed.
- Headless test note: prefer asserting the programmatic `set_loop_region` + the internal hit-test/update helpers + `region_changed` emission via a direct call; real offscreen mouse drags on a QSlider are fiddly.

### 2c. Panel side sub-panel (19-03)
- Add a **collapsible** advanced-controls container to the Replay tab. Simplest robust Qt pattern: a `QToolButton` (checkable, `ToolButtonTextBesideIcon`, arrow indicator) as the header that toggles the visibility of a `QWidget` body (a `QGroupBox` "Advanced" works too). Place it in the existing `QVBoxLayout` after `control_bar` (a side column via `QHBoxLayout` is also fine — "side" per the user; a collapsible right-hand column is the literal ask, but a collapsible section is acceptable and simpler — planner decides, but keep it clearly a distinct sub-panel).
- Body contains: a **"Loop region" QCheckBox** (toggles region-loop on/off — when on with a set region, calls `replayer.set_loop_region`; when off, `clear_loop_region`), and **"Set In" / "Set Out" QPushButtons** that read the live `position_fraction`, set that as the in/out bound on BOTH the scrubber (`set_loop_region`) and the scheduler (when region-loop active). Wire the scrubber's `region_changed` → update the scheduler region (when active) + a status line.
- Region must survive pause/seek/play: store `_loop_in_frac`/`_loop_out_frac` on the panel; re-apply to the (possibly rebuilt) replayer in `_ensure_transport`. Status messages via the shared `set_status` (no inline color).
- Keep the thin-face + offline/Qt-free invariants: every `rosbagger_replay` import stays inside method bodies.

## 3. Pitfalls
1. Preserve ALL Phase-13 + Phase-18 scheduler tests unchanged (region defaults None → behavior identical when unused). 2. Bound guards keep winning over region wrap (W4). 3. Region wrap must not infinite-loop with no publish (in-bound past end → DONE). 4. Region setters lock-guarded + wake (Phase-18 contract). 5. Scrubber must not break the existing playhead `seeked` path — only intercept when a handle is actually grabbed. 6. NO inline color — region/handle colors live in `theme/tokens.py` + qss; the panel/scrubber import token values, never literal hex. 7. Offline/Qt-free guard green; scheduler stdlib-only; panel thin face. 8. Region survives pause/seek/play (panel re-applies on transport rebuild).

## 4. Test plan
**Scheduler (19-01, pure):** region wrap (play past `t_out` → cursor back to in-index, repeats); region+max_messages (bound wins → DONE, W4); clear_loop_region → whole-bag/no-loop branch unchanged; region-loop takes precedence over whole-bag `_loop` when both set; in-bound-past-end → DONE; set-region-mid-run thread-safe (barrier-sleep, like 18-01). Regression: all existing scheduler tests green.
**Scrubber (19-02, headless):** `set_loop_region`/`clear_loop_region` + `loop_region` prop; `region_changed` emitted on a simulated handle update (direct helper call); paint doesn't crash with a region set; programmatic set does NOT emit. Offline guard.
**Panel (19-03, headless):** collapsible sub-panel exists + toggles visibility; Set-In/Set-Out read `position_fraction` and set both scrubber + scheduler region; loop-region checkbox on/off calls `set_loop_region`/`clear_loop_region`; region survives a pause/seek/play cycle (re-applied on `_ensure_transport`). Offline/Qt-free guard + phase gate (`PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest`, ≥80%, ruff).

## 5. Plan split
- 19-01 scheduler region loop (pure, Wave 1).
- 19-02 Scrubber dual handles + region paint + tokens (Wave 1, independent of 19-01).
- 19-03 panel collapsible advanced sub-panel + Set-In/Out + wiring (Wave 2, depends 19-01 + 19-02).
