# Phase 14: GUI - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 14 ships `rosbagger-gui`: a **thin Textual TUI** with five capability-gated panels — **record / inspect / query / tf / replay** — that are a **face over the existing module APIs**, with **no business logic in the GUI**. Offline panels (inspect / query / tf) always work in the ROS-free uv venv; live panels (record / replay) light up only when a ROS graph is present. It is the final v0.2 "Modular cockpit" phase and depends on Phase 4 (inspect), Phase 5 (query), Phase 9 (tf), Phase 12 (record), Phase 13 (replay).

**In scope (GUI-01):**
- A Textual TUI launching five panels over the existing module APIs (SC1).
- Capability-gating: live panels disabled without a ROS graph; offline panels always work (SC2).
- The inspect/query panels drive the real `rosbagger_core` APIs against a fixture bag (SC3).
- A new `rosbagger-gui` workspace package that stays **offline-importable** (live packages lazy-imported behind the gating).

**Out of scope / deferred (own phases or backlog — see Deferred Ideas):** 3D / pointcloud / robot-model visualization (rviz / Foxglove / Rerun own it — Out of Scope in PROJECT.md); rich timeseries plotting beyond the existing minimal export path; any NEW business logic (must live in the module APIs, never the GUI); multi-bag catalog/search. New capabilities belong in their own phase.

</domain>

<decisions>
## Implementation Decisions

> The user is the visionary; these are HOW decisions on top of the roadmap-locked facts (Textual TUI, five panels, the offline/live capability split, the thin-face/no-business-logic rule). The thin-face rule is **non-negotiable**: every panel calls an existing module API — "rich" below means richer UI affordances over those APIs, never new logic in the GUI.

### Layout & navigation
- **D-01 — Sidebar + content pane.** A left nav list of the five panels; the selected panel renders in the main content pane (IDE-style). Not tabbed-only, not a tiled dashboard.

### Bag selection / session model
- **D-02 — Launch-arg AND an in-TUI file/path picker.** `rosbagger-gui <bag-path>` loads a bag at startup; an in-TUI picker lets the user open/switch bags without relaunching. All offline panels (inspect/query/tf) share the one currently-loaded bag. The launch-arg path is what SC3 exercises (inspect/query against a fixture bag); the picker is part of v1, not deferred.

### Capability-gating UX & ROS detection
- **D-03 — Live panels visible but disabled + teaching hint.** Record/replay panels always appear in the sidebar but render greyed/disabled with a teaching hint ("source your ROS 2 environment to enable") when no ROS graph is present — mirrors the CLI's teaching-error ethos (`RosNotAvailableError`). Not hidden.
- **D-04 — Tiered ROS detection.** `import rclpy` succeeding (ROS 2 sourced) *enables* the live tabs; *opening* the record panel then runs a live topic-discovery scan (`rosbagger_record.discovery.discover_topics`) to populate its checklist. Cheap gate up front, accurate scan on demand. A panel-level live capability error still fires if the graph turns out empty.

### Panel depth & interactivity ("rich/interactive", all over existing APIs)
- **D-05 — Inspect panel:** rich read view over `collect_bag_info` / `collect_table_schemas` (topics, types, counts, duration, approx Hz, size).
- **D-06 — Query panel:** SQL input + results table over the existing `query()` backend, **plus all of:** query history + re-run, a schema/topic browser tree (from `collect_table_schemas` / `collect_bag_info`; click a column to insert into SQL), and CSV/Parquet export buttons over the existing output/export path.
- **D-07 — TF panel:** report view over `collect_tf_report` (parent→child graph + per-edge gap detection), reusing the existing rich-table rendering shape.
- **D-08 — Record panel (live):** topic checklist populated by the on-open discovery scan (D-04) + start/stop, over the `rosbagger_record.record` / `list_topics` API.
- **D-09 — Replay panel (live):** **full transport controls** — play / pause / step / seek / rate / loop — wired live to the existing `Replayer` state machine, **plus a scrubber timeline** (wired to `Replayer.seek()`) **and jump-to-event markers** sourced from the `<bag>.events.parquet` sidecar (the jump-points Phase 13 explicitly punted to this phase).
  - **D-09a — Shared publish sink (resolved post-research).** Full interactive transport requires the GUI to drive the pure `Replayer` directly (the `replay_bag()` front door is fire-and-go and exposes no mid-playback control). To keep a SINGLE production publish path and honor the "never re-implement the publish path" rule: **refactor the ~15-line rclpy publish sink out of `rosbagger_replay/replay.py` into one reusable function that BOTH `replay_bag()` and the GUI import.** The GUI supplies that shared sink to the `Replayer` (whose injectable, re-entrant-safe design exists for exactly this). No duplicated publish mechanics; the GUI stays a thin face.

### Claude's Discretion
- TUI testing strategy — use Textual's `Pilot` / `App.run_test()` to drive panels headless against a fixture bag (the mechanism for proving SC3); research item for the planner.
- Keeping `rosbagger-gui` offline-importable: live panels import `rosbagger_record` / `rosbagger_replay` lazily behind the gating, and `tests/test_offline_guard.py` is extended to assert `import rosbagger_gui` pulls no `rclpy` / `rosbag2_py` (Phase 12/13 pattern).
- Exact module layout, widget composition, keyboard bindings/shortcuts, theme, and the empty-state when launched with no bag and nothing picked yet (panels prompt to open a bag).
- Whether the GUI's own coverage stays out of the `--cov=rosbagger_core --cov=bagq` gate, mirroring the live-package precedent (D-12 of Phase 13) — planner's call given how much pure logic the GUI has (should be near-zero by the thin-face rule).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` § "Phase 14: GUI" — goal + 3 success criteria (launch a TUI exposing five panels over module APIs with no business logic; capability-gating of live vs offline panels; inspect/query drive the real `rosbagger_core` APIs against a fixture bag).
- `.planning/REQUIREMENTS.md` — GUI-01 ("Five capability-gated panels (record/inspect/query/tf/replay) over module APIs").
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` — §3 offline/live split + capability-gating; the "API-first: CLI & GUI are thin layers over module APIs" key decision (also in `.planning/PROJECT.md` Key Decisions). GUI is described as "a thin face over module APIs, capability-gated".

### Module APIs each panel sits over (read before planning)
- `packages/rosbagger-core/src/rosbagger_core/inspect.py` — `collect_bag_info(reader)` → `BagInfo`/`TopicInfo`, `collect_table_schemas(reader)` (inspect panel + the query panel's schema browser, D-05/D-06).
- `packages/rosbagger-core/src/rosbagger_core/backend/` + `schema/` + `output/` — the `query()` SQL backend (over a swappable `QueryBackend`) and the CSV/Parquet export path (query panel, D-06).
- `packages/rosbagger-core/src/rosbagger_core/tf.py` — `collect_tf_report(...)` → `TfReport`/`EdgeReport`/`GapReport` (tf panel, D-07).
- `packages/rosbagger-core/src/rosbagger_core/events.py` — the `<bag>.events.parquet` sidecar (replay panel jump-to-event markers, D-09).
- `packages/rosbagger-core/src/rosbagger_core/reader/` (`rosbags_reader.py`, `base.py`) — the v1 reader the offline panels load a bag through (D-02 shared bag).
- `packages/rosbagger-record/src/rosbagger_record/` — `record()`, `list_topics()`, `discovery.discover_topics`/`select_topics`, `errors.RosNotAvailableError` (record panel, D-04/D-08).
- `packages/rosbagger-replay/src/rosbagger_replay/` — `replay.replay` / the `replay_bag()` front door, `scheduler.Replayer` (the six transport controls + `seek()`), `source.load_items`, `errors.RosNotAvailableError`/`NoMessagesToReplayError` (replay panel, D-09).

### Patterns / seams to mirror
- `packages/rosbagger-replay/pyproject.toml` + `packages/rosbagger-record/pyproject.toml` — the workspace-member shape: `rosbagger-core` (+ thin CLI dep) uv-resolved, `rclpy`/`rosbag2_py` ENV-provided + lazy-imported, console-script entry point. `rosbagger-gui` mirrors this and adds `textual`.
- `tests/test_offline_guard.py` — the offline-import invariant to EXTEND for `rosbagger_gui` (reuse the plain `PYTHONPATH=""` helper; do not add ROS-bearing paths).
- `tools/make_fixtures.py` — the ROS-free fixture bags the inspect/query panels test against (SC3) and the replay panel can demo from.
- `.planning/phases/13-live-replay/13-CONTEXT.md` + `.planning/phases/12-live-record/12-VERIFICATION.md` — the live-package template, the offline-guard mechanics, and the ROS-sourced live-lane recipe (for any live-panel integration test).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Every panel's logic already exists as a module API** — the GUI is genuinely a face: inspect (`collect_bag_info`/`collect_table_schemas`), query (`query()` + export), tf (`collect_tf_report`), record (`record`/`list_topics`/`discover_topics`), replay (`replay_bag` + `Replayer`). No new business logic should be written in Phase 14.
- **`rosbagger-record` / `rosbagger-replay` package shape** — the exact template for a workspace package that isolates ROS behind a lazy boundary; `rosbagger-gui` copies the pyproject/lazy-import structure and adds `textual`.
- **Teaching-error pattern** (`*/errors.py` `RosNotAvailableError`) — reused for the disabled-live-panel hint (D-03).
- **Existing rich-table rendering** in the `bagq` CLI / `tf`/`inspect` output — informs how panels display tabular data in Textual.

### Established Patterns
- **Offline tier never imports ROS** (enforced by `test_offline_guard.py`). `rosbagger-gui` MUST stay offline-importable: live panels lazy-import `rosbagger_record`/`rosbagger_replay`; the guard is extended to cover the GUI package.
- **API-first / CLI↔GUI parity** — structurally guarantees the GUI can't outrun the modules; this is the phase's central invariant.
- **Two-tier testing** (Phase 12/13) — offline panels unit/integration-tested ROS-free with Textual's `Pilot` against fixture bags (SC3); any live-panel test stays gated/skippable so offline CI stays green.

### Integration Points
- New `rosbagger_gui` package → Textual `App` with a sidebar + content layout (D-01); each panel widget calls one module API.
- Live panels reach `rosbagger_record` / `rosbagger_replay` (env-provided rclpy, lazy); tiered detection (D-04) decides enabled/disabled state.
- Offline panels share one loaded bag via the v1 reader (D-02).

</code_context>

<specifics>
## Specific Ideas

- The replay panel's **jump-to-event** markers come from the `events` sidecar — this is the realization of the jump-points Phase 13's CONTEXT deferred to Phase 14.
- The query panel's **schema/topic browser** should let the user click a column to insert it into the SQL box — write SQL without leaving the TUI.
- "Rich/interactive" was chosen deliberately, but bounded by the thin-face rule: rich UI, zero new logic. If a desired affordance would need logic that doesn't exist in a module API, that's a signal it belongs in the module (or a future phase), not the GUI.

</specifics>

<deferred>
## Deferred Ideas

- **3D / pointcloud / robot-model visualization** — rviz / Foxglove / Rerun own it (PROJECT.md Out of Scope); interop via formats, not in the TUI.
- **Rich timeseries plotting in the TUI** — `--plot` stays intentionally minimal; PlotJuggler/Foxglove own this.
- **Multi-bag catalog / search across many bags** — north-star, not this phase (offline panels share one loaded bag in v1).
- **Topic remapping / per-topic QoS in the replay panel** — inherited deferral from Phase 13; v1 replay panel uses the module's sane defaults.
- **Interactive `/clock` + `use_sim_time` simulated-clock replay** — Phase 13 deferral; v1 paces on wall-clock.

None of the discussion strayed outside the GUI domain — the above are pre-existing project-level deferrals reaffirmed here.

</deferred>

---

*Phase: 14-gui*
*Context gathered: 2026-05-23*
