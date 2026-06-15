# SUMMARY — Quick 260615-1n1 — Overhaul cleanup/perf tail

**Date:** 2026-06-15 · **Status:** complete · **Commits:** 42f5389, 7628aa8, 9020df7, ba5c074,
c5644d0, 0783d92, 437047a, 3052cbc, bfe3896, b1a0f2d, 0175760, 8074526, 0494e17

The final tail of the whole-codebase overhaul. All 35 *bugs* were already fixed (Batches 1–5/7);
this task closed the remaining cleanup / refactor / perf findings. Every finding was re-grounded
in *current* code (it had drifted 13 commits since the original review) and the **subjective**
refactors were adjudicated by an adversarial investigate→challenge **workflow** so each SKIP is
principled. **12 findings applied** (atomic commit + regression test where offline-testable),
**6 skipped with documented rationale**, plus a separate chore clearing pre-existing ruff debt.
Full offline suite **721 passed / 6 skipped**; `ruff` clean repo-wide.

## Applied (12)

| # | Finding | Commit | What |
|---|---------|--------|------|
| S7 | dead import | 42f5389 | dropped the TUI drive-worker's unused `Replayer` import whose `# noqa: F401 - bind for the State import below` justification was false |
| S8 | dead param | 7628aa8 | `_record_teaching_errors()` imports `rosbagger_record` directly instead of taking a needless `import_module` arg both callers fed identically |
| S3 | dup ctor | 9020df7 | module-level `_edge_report()` factory collapses the 4× `EdgeReport(...)` (3 byte-identical degenerate branches + the real one) in `collect_tf_report` |
| S5 | dup block | ba5c074 | `_republish_static_if_enabled()` replaces the static-republish guard pasted in `_on_seeked`/`_skip`/`_reprime_rviz_static` |
| S4 | stringly dispatch | c5644d0 | `_pending_action` holds the bound method (`self._play`/`self._step`) not a `"play"`/`"step"` token; finish handler is `if pending: pending()` |
| R6 | dup probe | 0783d92 | `rosbagger_core.capabilities.module_importable("rclpy")` shared by the TUI `_detect_ros` and desktop `ros_available` (lazy — offline invariant holds) |
| T7 | hard-coded distro | 437047a | `ros_distro()` (reads `$ROS_DISTRO`, falls back to `humble`) makes the record/replay remedy strings distro-aware; lazy import keeps errors.py module-top stdlib-only |
| S6 | dup shell tail | 3052cbc | `print_try_commands()` factors the shared "try it" lines from the install.sh `--user`/`--venv` tails; `return 0` keeps it safe under `set -e` |
| T4 | dup version | bfe3896 | each package `__version__` now derives from `importlib.metadata.version(<dist>)` (pyproject is the single source); `PackageNotFoundError` → `0.0.0+unknown` sentinel |
| F3 | hot-loop work | b1a0f2d | `build_arrow_table` hoists the per-column `(name, is_data, bound-append)` plan out of the per-message loop (byte-identical output) |
| F2 | LIMIT pushdown | 0175760 | `_safe_limit_head()` detects a bare single-table `SELECT … LIMIT k [OFFSET m]` and islices the lazy message stream to `k+m`; bails on any filter/sort/agg/join/etc. |
| R8 | dup marker math | 8074526 | `event_marker_fractions()` in core shares the `(t−start)/span` scrubber-marker mapping (+ zero-span guard + `str(label)`) across the Qt and TUI panels |

## Skipped (6) — with rationale (adversarially verified)

- **R4** (CLI teaching-error decorator ×3): the only shared code is the typer-coupled
  `secho + Exit(1)` skeleton — can't live in core (no typer dep); the caught-error tuples are
  disjoint (`ValueError` vs `RuntimeError` families, two distinct `RosNotAvailableError`s); bagq
  has an extra `FileNotFoundError` branch. Net-negative; the smallest helper makes call sites
  *longer*.
- **R7** (`RosNotAvailableError` ×2): the two messages differ on purpose (record names
  `rosbag2_py` + "recording"; replay only `rclpy` + "replaying"). Consolidation needs a new core
  public symbol across the version boundary, yields **zero** line savings (a subclass stub is
  longer), and the only line-saving variant collapses the two classes into one object — a silent
  `isinstance` widening.
- **S2** (18 `@property` accessors): not behavior-preserving — tests reach BOTH the private fields
  (`panel._rate_input`, `_scrubber`, `_region_checkbox`) and the public names; the property is the
  bridge. `status_label` is a cross-panel facade that *decouples* the public name from the private
  field (`self._header` in inspect_panel). Flattening breaks ~11 test sites, loses read-only
  protection of signal-wired widgets, and the docstrings carry context.
- **T6** (typed `BagSession` vs `getattr(window())`): no type checker in CI (ruff only), so a
  "typed" accessor buys nothing; `MainWindow.reader` is deliberately `object | None` for the
  lazy-import invariant; the `getattr(..., default)` is load-bearing for parentless-panel +
  duck-typed-window tests (a `cast`-based accessor would `AttributeError` them). Safe variant is
  negligible-value churn across 5 `QWidget` subclasses.
- **R5** (transport view-model dup): the real view-model (the pure `Replayer`) is already
  single-sourced; only ~10 leaf display strings duplicate, and they're diverging. No clean home —
  the panels are sibling packages with no dep edge, and `rosbagger-replay` is only the GUI's
  `[live]` extra, so a module-top shared import would `ModuleNotFoundError` in a base GUI install
  (a clean-venv break the dev workspace masks).
- **newE24** (Rerun viewer PID-diff): **refuted as framed.** `_child_pids()` keeps only *direct*
  children, so a terminal-launched rviz2 is never captured; the only residual is a narrow same-app
  race (open-Rerun on a worker thread while open-RViz Popens a direct child) and it's recoverable.
  The requested "track the exact PID" fix is *impossible* — rerun-sdk's `spawn()` returns `None`
  and births the process in the Rust binding — and the only alternative (filter the diff by exe
  name) is a *worse* regression: any name mismatch makes `close_viewer` a no-op and the viewer
  leaks past GUI close (the exact 260530-c3p orphan bug). Left as-is.

newA3 (arrow_type recursion) remains REFUTED/dropped from the original review.

## Also — pre-existing lint debt cleared (0494e17, separate chore)

A full-repo `ruff check packages tests tools` (under the locked ruff 0.15.14 = CI's) surfaced 15
findings that **pre-date this task** (present at 4ec581c, in files the overhaul never touched) —
missed because per-finding checks ran per-file. All fixed behavior-preservingly (B905
`strict=False`, SIM105 `contextlib.suppress`, B009, SIM117, I001, 8× E501 reflow) so the push
won't fail CI.

## Verification

- Two adversarial workflows: a 18-finding grounding pass (died on a transient 529 overload — all
  findings were instead grounded inline) and a 7-finding judgment-call pass (14 agents, clean) that
  returned APPLY=[R8], SKIP=[R4,R7,S2,T6,R5,newE24] — matching the inline analysis and correcting
  an initial over-call on newE24.
- Per-finding: `ruff` + the targeted test file(s); ROS-lifecycle/live items reasoned + offline-mocked
  (live tests skipped offline). New tests: F2 (full `_safe_limit_head` detection table + LIMIT/OFFSET
  vs full-scan + decode-stops-early, ×3 formats), R6/T7 (`test_core_capabilities.py`), T4 (all-six
  `__version__` resolve from metadata), R8 (endpoint/midpoint + zero-span), S8.
- Full offline suite: **629 (non-Qt) + 92 (`test_desktop.py`, Qt offscreen) = 721 passed**, 6 skipped.
  `ruff` clean across `packages tests tools`. Offline-import + Qt-free guards green.

## Remaining overhaul

**None.** All 35 bugs (prior batches) + all confirmed cleanup/refactor/perf findings are resolved or
skipped-with-rationale. Only the user's `git push` remains (pushes are the user's).
