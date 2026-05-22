---
phase: 09-tf-debugger
plan: 02
subsystem: tf-analysis
tags: [tf, tf2, gap-detection, dropout, TFMessage, transform-graph, api-first, offline]

# Dependency graph
requires:
  - phase: 02-reader
    provides: "RosbagsReader / BagReader.read(topics={...}) + Message(topic, t_ns, msg) — collect_tf_report consumes a PASSED-IN open reader and walks the deserialized TFMessage stream"
  - phase: 04-inspect
    provides: "inspect.py module-shape analog (frozen+slotted dataclasses, collect_*(reader) over an open reader, stdlib-only top level, NOT in __init__, defensive bounds guard)"
  - phase: 07-errors
    provides: "errors.py house style (ValueError subclasses, stdlib-only/difflib-only, data-carrying, teaching message built in __init__) + the teaching_errors widening recipe (Plan 03 will use it)"
  - phase: 09-tf-debugger
    plan: 01
    provides: "write_tf_bag fixture (the /tf + /tf_static bag with a seeded ~800ms odom->base_link gap + a clean base_link->laser edge) the verify steps analyze"
provides:
  - "rosbagger_core.tf.collect_tf_report(reader, *, gap_multiplier=5.0, gap_ms=None) -> TfReport — the entire TF-01 domain logic: parent->child graph + per-edge time series + median-inter-arrival x multiplier (or absolute gap_ms) dropout detection over the v1 reader stream"
  - "Frozen+slotted TfReport(frames, edges, gaps, start_ns, end_ns) / EdgeReport(parent, child, static, samples, first_ns, last_ns, expected_ns, max_gap_ns, gap_count) / GapReport(parent, child, gap_ns, at_ns, at_rel_ns, at_rel_s, expected_ns)"
  - "rosbagger_core.errors.NoTransformsError(available_topics) — stdlib-only data-carrying ValueError raised when a bag has neither /tf nor /tf_static"
affects: [09-03, tf-cli, gap-rendering]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TF clock = m.t_ns (log time), bag-relative for display (at_rel_ns = at_ns - start_ns); TFMessage has no top-level header so Message.stamp is None for /tf (Decision 3 / Pitfall 2)"
    - "Match /tf + /tf_static by TOPIC NAME, never by msgtype string (Decision 4) — sidesteps tf2_msgs/TFMessage vs tf2_msgs/msg/TFMessage spelling variance"
    - "Gap = median(inter-arrival diffs) x multiplier (default 5.0) OR absolute gap_ms override; deltas <=0 dropped before the median, expected<=0 short-circuits — no ZeroDivision / false gap (T-09-03)"
    - "MIXED-edge tie-break: an edge on BOTH /tf and /tf_static is static=True in the graph yet still gap-checked (presence on /tf makes it gap-checkable)"
    - "Empty-input teaching error: guard reads reader.topics (O(1) metadata), never the stream, before any walk (Decision 7)"

key-files:
  created:
    - "packages/rosbagger-core/src/rosbagger_core/tf.py — TF analysis core (collect_tf_report + TfReport/EdgeReport/GapReport + gap algorithm); 364 lines; stdlib-only top level; NOT in __init__"
  modified:
    - "packages/rosbagger-core/src/rosbagger_core/errors.py — added NoTransformsError(ValueError) (stdlib-only, .available data, teaching message naming /tf and /tf_static)"

key-decisions:
  - "TF logic lives in rosbagger_core.tf (Decision 1) — auto-covered by the existing --cov=rosbagger_core gate; NO new package, NO manifest/addopts/uv.lock edits"
  - "Consume the v1 reader stream directly, NOT the Phase 5 query layer (Decision 2 / Pitfall 3) — query() flattens /tf to one LIST-of-STRUCT column; the stream walk is simpler and pulls no duckdb/sqlglot"
  - "Gap-detection: median (not mean) resists the very gaps being detected; default 5x multiplier tolerates jitter; absolute gap_ms is an optional override (Decision 6 / A1)"
  - "Gaps are between OBSERVED samples only (A4) — no synthetic gap from bag start to the first sample or last sample to bag end"
  - "GapReport carries both at_ns (absolute) and at_rel_ns/at_rel_s (bag-relative) so the CLL can render 'at t=12.4s' without re-deriving (Decision 3)"
  - "EdgeReport.static is True for any edge seen on /tf_static (graph truth) but gap_count is still computed when the edge is ALSO on /tf (mixed tie-break)"

patterns-established:
  - "TF analyzer mirrors inspect.py exactly (frozen+slotted dataclasses + collect_*(reader) + stdlib-only top + out of __init__), differing only in that it MUST stream reader.read() (it needs every TF message) where collect_bag_info is O(1)"
  - "Threat-driven defensive math: key edges on (parent, child) strings + times on m.t_ns ints ONLY — transform.translation/.rotation numerics (NaN/inf) never reach the gap math (T-09-05); empty transforms list contributes no edges"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 9 Plan 02: TF Analysis Core (collect_tf_report) Summary

**`rosbagger_core.tf.collect_tf_report(reader)` — the entire TF-01 domain logic: it streams `/tf` + `/tf_static` off the passed-in v1 reader, builds the parent->child transform graph + per-edge publish-time series, and detects per-edge dropouts via median-inter-arrival x multiplier (default 5x, or an absolute `gap_ms` override), returning a frozen `TfReport`; the empty case is a typed `NoTransformsError`. Imports no ROS; the CLI (Plan 03) only renders.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-22T23:41:18Z
- **Completed:** 2026-05-22T23:44:58Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- **`NoTransformsError`** added to `errors.py` — a stdlib-only, data-carrying `ValueError` (matching the `UnknownTableError`/`UnknownColumnError` house style) that stores the bag's topics on `.available` and builds a teaching message naming `/tf` and `/tf_static`, listing the available topics (sorted) when present or noting "the bag has no topics" when empty. No new import; the `errors.py` offline invariant is preserved.
- **`rosbagger_core/tf.py`** created — the API-first TF analysis core mirroring `inspect.py`:
  - Frozen+slotted **`TfReport`** (`frames`, `edges`, `gaps`, `start_ns`, `end_ns`), **`EdgeReport`** (`parent`, `child`, `static`, `samples`, `first_ns`, `last_ns`, `expected_ns`, `max_gap_ns`, `gap_count`), **`GapReport`** (`parent`, `child`, `gap_ns`, `at_ns`, `at_rel_ns`, `at_rel_s`, `expected_ns`).
  - **`collect_tf_report(reader, *, gap_multiplier=5.0, gap_ms=None)`** — empty-topic guard first (reads `reader.topics`, O(1), raises `NoTransformsError`), then a connection-filtered stream walk keying edges by `(parent, child)` and timing by `m.t_ns`, tagging static by topic name, with full per-edge gap detection.
- **Every RESEARCH gap edge case is guarded**: static skip, zero/single-sample skip, `<=0`-delta drop before the median, `expected<=0` short-circuit, no synthetic boundary gaps, mixed `/tf`+`/tf_static` tie-break (static in the graph yet gap-checked), and distinct series for self-edges / multi-parent children.
- **Offline invariant held both ways**: `import rosbagger_core` stays ROS-free, and `import rosbagger_core.tf` pulls no `rosbags`/`duckdb`/`sqlglot`/`pyarrow` (stdlib-only top level: `dataclasses`, `statistics`); `__init__.py` untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add NoTransformsError to errors.py** - `04c95bc` (feat)
2. **Task 2: Create rosbagger_core/tf.py — graph build + gap detection + TfReport** - `38d185b` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/errors.py` (modified) — added `NoTransformsError(ValueError)`: `.available` data + teaching message naming the TF topics; no other class changed; no new import (still `difflib`-only).
- `packages/rosbagger-core/src/rosbagger_core/tf.py` (created, 364 lines) — module docstring in the `inspect.py` house style (API-first / OFFLINE INVARIANT / "DOES stream `reader.read()` unlike O(1) `collect_bag_info`"); the three frozen+slotted dataclasses; `collect_tf_report`; module-level constants `_TOPIC_TF`/`_TOPIC_TF_STATIC`/`_DEFAULT_GAP_MULTIPLIER`/`_NS_PER_MS`. NOT added to `__init__.py` (Decision 9).

## Decisions Made

- **`expected_ns` typed `int`** in `GapReport`/`EdgeReport`: `statistics.median` of an even-length integer list can return a float, so the stored `expected_ns` is `int(expected)` (the gap THRESHOLD comparison uses the exact float `expected` to avoid a rounding-boundary flake; only the displayed/stored value is the int). For the Plan-01 fixture (`_DT_NS = 100_000_000` everywhere) the median is exact, so `expected_ns == 100_000_000`.
- **`at_rel_s` precomputed** on `GapReport` (`at_rel_ns / 1e9`) as a renderer convenience, alongside the raw `at_rel_ns` int — the CLI can use either without re-deriving (Decision 3).
- **`gap_ms` is MILLISECONDS** (converted to ns via `_NS_PER_MS = 1_000_000` internally) — matches the planned `--gap-ms` CLI flag name; the `<action>` text said "absolute ns override" but named the parameter `gap_ms`, so the unit is ms and the conversion lives in the analyzer.
- **`static` set vs `dynamic` set both tracked** during the walk so the mixed tie-break is exact: `static = (key in static_keys)` (graph truth, drives `EdgeReport.static`), `gap_checkable = (key in dynamic_keys)` (presence on `/tf`, drives whether gaps are computed). A static-only edge is `gap_checkable == False` and is never gap-checked.

## Deviations from Plan

None of substance — plan executed as written. One in-scope lint fix:

### Auto-fixed Issues

**1. [Rule 3 - Blocking lint gate] `zip()` without explicit `strict=`**
- **Found during:** Task 2 (running the project's `ruff check` gate, which has bugbear `B` enabled per `pyproject.toml select`).
- **Issue:** My two consecutive-pairs walks `zip(ordered, ordered[1:])` triggered ruff `B905` ("zip without explicit strict"). The house convention (`output/render.py`) always passes an explicit `strict=`.
- **Fix:** Added `strict=False` to both `zip()` calls (the two iterables intentionally differ in length by one — `strict=True` would be semantically wrong here; `zip` must stop at the shorter). Added a one-line comment on each explaining why.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/tf.py`
- **Commit:** `38d185b` (folded into the Task 2 commit — the fix was applied before the commit).

The plan's `<interfaces>` block (the `Message`/`BagReader` contract, the `NoTransformsError` shape, the canonical stream-walk) matched the live source exactly; no API drift, no missing functionality, no architectural change.

## Issues Encountered

None. The Plan-01 fixture produced exactly the seeded structure (one `800_000_000` ns gap on `odom->base_link` at bag-relative `t=0.70s`, zero gaps on the clean `base_link->laser` edge and the static `map->odom` edge) in all three formats.

## Threat Model Compliance

- **T-09-03 (DoS — backwards/duplicate timestamps):** mitigated — deltas `<= 0` are dropped before `statistics.median`, and `expected <= 0` short-circuits the gap math. Verified: a synthetic edge with duplicate AND backwards stamps produces no `ZeroDivision` and no false gap; an all-duplicate-timestamp edge records `expected_ns is None`, 0 gaps (informational).
- **T-09-04 (DoS — single/zero-sample edge):** mitigated — `samples < 2` short-circuits to a no-gap informational `EdgeReport`; the median is never taken over an empty `diffs` list. Verified with a one-publish synthetic edge.
- **T-09-05 (Tampering — NaN/inf numerics, empty `transforms`):** mitigated — the analyzer keys edges on `frame_id`/`child_frame_id` (strings) and times on `m.t_ns` (int) ONLY; it never reads `transform.translation`/`.rotation`, so NaN/inf cannot enter the gap math. An empty `transforms` list contributes no edges (inner loop doesn't execute).
- **T-09-06 (DoS — unbounded per-edge series, accepted):** unchanged — per-edge lists store only int timestamps + `(str, str)` keys (never message bodies); accepted residual for a local single-pass analyzer over the operator's own bag.
- **T-09-07 (self-edge / multi-parent):** mitigated — keying by `(parent, child)` keeps a `parent==child` self-edge and a child's two parents as DISTINCT series. Verified with a synthetic reader.
- **T-09-SC (installs, accepted):** honored — zero new packages; `tf.py` imports only `dataclasses` + `statistics`, `errors.py` only `difflib`. No install task.

## Verification Evidence

- **Task 1 verify** (`NoTransformsError` shape): prints `OK`, exit 0. Plus: `import rosbagger_core.errors` pulls no heavy stack; the empty case has no "Available topics:" list and notes "no topics".
- **Task 2 verify** (Plan-01 ROS 2 sqlite fixture): prints `OK`, exit 0 — `frames == {"map","odom","base_link","laser"}`; exactly one `GapReport` for `("odom","base_link")` within ±1 ns of `800_000_000`; zero gaps on `("base_link","laser")` and static `("map","odom")`; the `("map","odom")` `EdgeReport` is `static is True`, `gap_count == 0`.
- **Extended verify (all three formats — ROS 1, ROS 2 sqlite, ROS 2 MCAP):** identical graph + gap; `gap.expected_ns == 100_000_000`; `gap.at_ns - gap.at_rel_ns == start_ns`; edges sorted by `(parent, child)`, gaps sorted by `at_ns`. `NoTransformsError` raised on a non-TF bag (`write_ros2_sqlite_bag`) with `.available == sorted(topics)`. `gap_ms=50.0` flags every 100ms-cadence delta on the clean edge (23 gaps).
- **Edge cases (synthetic readers):** single-sample (samples=1, 0 gaps); two-sample (median == lone delta, 0 false gaps); duplicate+backwards stamps (no ZeroDivision); all-duplicate (expected None); mixed `/tf`+`/tf_static` (static=True AND 1 gap); static-only with long silence (never gap-checked); self-edge + multi-parent (distinct series). All pass.
- **Offline invariant:** `import rosbagger_core` clean (no heavy, no ROS); `import rosbagger_core.tf` clean in a fresh subprocess; `__init__.py` unchanged.
- **Lint/format:** `ruff check` + `ruff format --check` clean on both files.
- **Full suite:** `PYTHONPATH="" uv run pytest -q` → **255 passed**, total coverage **85.46%** (≥80% gate). `tf.py` shows 0% and `errors.py`'s new lines uncovered — BY DESIGN: the plan defers all tests to Plan 03 (interface-first sequencing, same pattern as Phase 02; the gate was never weakened and still passes).

## Next Phase Readiness

- **Plan 09-03** (TF CLI `bagq tf` + the analyzer test asserting SC1–SC3) can now: import `collect_tf_report` / `TfReport` / `EdgeReport` / `GapReport` from `rosbagger_core.tf`; render the two-table + header layout from the RESEARCH "Output / Table Format Proposal"; widen `teaching_errors` by one import + one `except` entry for `NoTransformsError`; expose `--gap-multiplier` / `--gap-ms`; and add the `tests/test_tf.py` suite (which will lift `tf.py` + the new `errors.py` lines to coverage). The fixture (`write_tf_bag`, all three formats) is ready.
- **No blockers introduced.** The standing milestone-level blocker (v0.1 push pending `gh`/push auth) is unrelated to Phase 9.

## TF-01 Status

TF-01 is NOT yet marked complete — the analysis CORE ships here, but the requirement's CLI surface (the `bagq tf` command + the SC1–SC3 test) lands in Plan 09-03. The plan frontmatter lists `requirements: [TF-01]` but TF-01 spans 09-01/02/03; marking it complete waits for 09-03.

## Self-Check: PASSED

- FOUND: packages/rosbagger-core/src/rosbagger_core/tf.py (contains `def collect_tf_report` + `class TfReport`/`EdgeReport`/`GapReport`)
- FOUND: packages/rosbagger-core/src/rosbagger_core/errors.py (contains `class NoTransformsError(ValueError):`)
- FOUND: commit 04c95bc (Task 1, feat)
- FOUND: commit 38d185b (Task 2, feat)
- FOUND: .planning/phases/09-tf-debugger/09-02-SUMMARY.md

---
*Phase: 09-tf-debugger*
*Completed: 2026-05-22*
