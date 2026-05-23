# Phase 12: Live Record - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 12 is rosbagger's **first LIVE phase**: `rosbagger-record` discovers currently-published ROS topics and records a selected subset to a bag. Unlike Phases 1–11 (offline, ROS-free), this module **requires a sourced ROS 2 environment** (`rclpy` + `rosbag2_py`). The offline tier (`rosbagger-core`, `bagq`, edit/events/tf) stays ROS-free — this phase must not compromise that.

**In scope (REC-01):** live topic discovery (name + type); selecting a subset; recording it to a bag while a publisher runs; the recorded bag re-opens and iterates via the v1 reader; a thin `rosbagger-record` CLI; a test strategy that keeps the offline CI green while still proving the live path on a ROS-equipped box.

**Out of scope (own phases / deferred):** replay (Phase 13); the GUI Record panel (Phase 14 — capability-gates over this module's API); QoS-profile capture/override; compression; split-by-size/duration; service/action recording; recording to ROS 1 / sqlite3 (MCAP is the v1 lock); a `rosbag2_py` *reader* backend (still out per PROJECT). New capabilities belong in their own phase.

</domain>

<decisions>
## Implementation Decisions

> **`--auto` mode:** every decision below is the recommended default, auto-selected without prompts. Most are **locked by the design spec** (§3 offline/live split + §5.2 "record to MCAP via rosbag2_py") and by the verified runtime reality below.
>
> **Verified runtime reality (the defining constraint):** `rclpy` imports from the system ROS install (`/opt/ros/humble/...`) but is **absent from the project's `uv` venv** (`PYTHONPATH="" uv run python -c "import rclpy"` → `ModuleNotFoundError`). `rclpy`/`rosbag2_py` ship with the ROS distro, not as usable PyPI wheels — so the live module runs in a *sourced-ROS* environment, a different runtime than the offline uv venv.

### Package, dependencies & CLI surface

- **D-01 — New SEPARATE workspace package `packages/rosbagger-record/`** (a `uv` workspace member, `members = ["packages/*"]`). Logic in its Python API; thin CLI. Design-locked: "live modules isolate `rclpy` behind their package boundary"; offline `core`/`bagq` never import ROS.
- **D-02 — Console script `rosbagger-record`, NOT a `bagq record` subcommand.** Keeps `bagq`'s import graph 100% offline (no `rclpy` anywhere in its closure). API-first / CLI↔GUI parity: the Phase-14 GUI Record panel capability-gates over this same package API.
- **D-03 — `rclpy`/`rosbag2_py` are ENVIRONMENT-provided, NOT `uv`-resolved dependencies.** They come from the sourced ROS 2 distro (declaring them in `pyproject` would make `uv` try to resolve absent/stub PyPI wheels — verified absent from the uv venv). `rosbagger-record`'s only `uv`-resolved dependency is `rosbagger-core` (for the v1 reader contract). It documents "requires a sourced ROS 2 environment," and **lazy-imports** `rclpy`/`rosbag2_py` inside functions so the package itself imports cleanly even in the ROS-free uv venv.

### Recording mechanism

- **D-04 — Record to MCAP via `rosbag2_py`** (the design's explicit choice — the ROS-native recorder), with **`rclpy`** for graph init/spin + topic discovery. This is a deliberate divergence from the edit module's `rosbags` Writer: `rosbag2_py` is the robust ROS-native recording path, and its MCAP output re-opens via the v1 reader (`rosbags` `AnyReader` reads MCAP) — satisfying SC3 with no extra round-trip.
- **D-05 — Generic serialized capture (no per-type Python deserialization):** subscribe to each selected topic with its discovered type and hand serialized bytes straight to the `rosbag2_py` writer. (Research confirms the exact `rclpy` generic-subscription + `rosbag2_py` `SequentialWriter` wiring against ROS 2 Humble.)

### Topic discovery & selection

- **D-06 — Discover live topics + types via `rclpy` `get_topic_names_and_types()`** (after a brief settle so discovery populates). `rosbagger-record list` (or `--list`) prints discoverable topics + types and exits (SC1).
- **D-07 — Record a SUBSET:** positional topic args (`rosbagger-record /a /b -o OUT`), `--all` to record everything currently published, optional `--regex` / `--exclude` patterns. (The GUI's "checkbox-select" is the same selection over the same API.)

### Output format & stop control

- **D-08 — Default output MCAP** (ROS 2 default; design records to MCAP). `-o OUT` sets the path. **Refined by RESEARCH (env reality):** MCAP stays the *preferred default*, but a `--storage {mcap,sqlite3}` **capability escape** is added because the MCAP `rosbag2_py` storage plugin is not installed on this box (needs `sudo`) — without the escape the recorder can't run or be tested here. The MCAP-specific path is `skipif`-guarded on `rosbag2_py.get_registered_writers()`; SC2/SC3 are proven via the available sqlite3 path. (sqlite3 is therefore an in-scope capability escape, NOT a general multi-format feature — see Deferred.)
- **D-09 — Stop on SIGINT (Ctrl-C) with a graceful shutdown** that finalizes/closes the bag so it re-opens cleanly; PLUS an optional bounded mode `--duration SECONDS` and/or `--max-messages N`. The bounded mode is what makes the live integration test deterministic (record exactly N messages / T seconds, then exit and assert).

### Test strategy & offline guarantee (CRITICAL — the defining decision of this phase)

- **D-10 — Two-tier testing.**
  1. **ROS-free UNIT tests** run in the uv venv / existing offline CI: topic-selection logic, CLI parsing, and record orchestration with `rclpy`/`rosbag2_py` **mocked** (enabled by D-03's lazy imports). These keep the offline coverage gate meaningful.
  2. **LIVE integration tests** run with **ROS sourced** (system Python / a ROS-aware env — NOT `PYTHONPATH="" uv run`): a real `rclpy` publisher → `rosbagger-record --duration/--max-messages` → re-open + iterate via the v1 reader (proves SC2 + SC3 end-to-end). Gated by `pytest.importorskip("rclpy")` + a `live` marker; **SKIPPED in the offline CI**; runnable on this ROS 2 Humble box.
- **D-11 — Offline guarantee preserved.** `rclpy`/`rosbag2_py` are isolated to `rosbagger-record` and lazy-imported; `import rosbagger_record` succeeds in the ROS-free uv venv (no eager ROS import), and its `record()` raises a graceful capability error ("source your ROS 2 environment") when `rclpy` is absent. **Extend `tests/test_offline_guard.py`** to assert `import rosbagger_core` and `import bagq` still pull NO `rclpy`/`rosbag2_py`.

### Claude's Discretion
Exact module layout; CLI flag names; the precise `rclpy` generic-subscription + `rosbag2_py` `SequentialWriter` wiring (research-confirmed); the `live` pytest-marker name and how the ROS-sourced test lane is invoked (and whether it joins a future ROS CI lane); whether any non-MCAP `--format` is exposed. Hard constraints: offline `core`/`bagq` must NEVER import `rclpy`; the recorded bag MUST re-open via the v1 reader; live tests stay gated/skippable so the offline CI stays green.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` § "Phase 12: Live Record" — goal + 3 success criteria (discover live topics; record a selected subset while a publisher runs; recorded bag re-opens + iterates via the v1 reader).
- `.planning/REQUIREMENTS.md` § "Live (record/replay)" — REC-01 (live topic discovery + checkbox-select recording, needs rclpy).
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` — §3 the offline/live split diagram + principles (lines ~55–97: "Live (record, replay) depend on rclpy / ROS, installed and run only where ROS exists"; "Live modules isolate rclpy behind their package boundary"; "capability-gated / graceful degradation"); §5.2 line ~131 ("rosbagger-record (live) — discover active topics + their types, checkbox-select, record to MCAP via rosbag2_py").

### Code seams / patterns to follow (read before planning)
- `pyproject.toml` (root) — the `[tool.uv.workspace] members = ["packages/*"]` + `[tool.uv.sources] rosbagger-core = { workspace = true }` pattern a new package follows.
- `packages/bagq/pyproject.toml` — the per-package `[project]` deps + `[project.scripts]` console-script pattern (`rosbagger-record` mirrors `bagq = "bagq.cli:app"`).
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` + `reader/base.py` — the v1 reader the recorded MCAP must re-open + iterate through (SC3 contract).
- `tests/test_offline_guard.py` — the offline-import invariant to EXTEND (assert core/bagq pull no rclpy/rosbag2_py).
- `packages/rosbagger-core/src/rosbagger_core/errors.py` — the teaching-error pattern (graceful "source your ROS 2 environment" capability error).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **v1 reader** (`reader/rosbags_reader.py`): `rosbags` `AnyReader` reads ROS 2 MCAP, so a `rosbag2_py`-recorded MCAP re-opens + iterates with the EXISTING reader — SC3 needs no new read code, only an assertion.
- **uv workspace + console-script pattern** (`bagq/pyproject.toml`): the template for `packages/rosbagger-record/` (its own `[project]` + `[project.scripts] rosbagger-record = ...`).
- **Teaching-error pattern** (`errors.py`): reused for the graceful "rclpy not found — source ROS 2" capability message.

### Established Patterns
- **Offline tier never imports ROS** (verified by `test_offline_guard.py`); rclpy/rosbag2_py live ONLY in `rosbagger-record`, lazy-imported. This phase is the first test of the offline/live boundary — it must hold.
- **API-first / thin CLI / CLI↔GUI parity:** record logic in the package API; the CLI (and the Phase-14 GUI) are thin faces.
- **`PYTHONPATH=""` inversion:** offline tests need `PYTHONPATH=""` to HIDE the leaked ROS; the LIVE tests need the OPPOSITE (ROS on the path / system Python). The two suites run in different environments — a key planning consideration.

### Integration Points
- New `rosbagger-record` API (discover/select/record) consumed by a thin `rosbagger-record` CLI; recorded MCAP validated through the v1 reader.
- `rosbag2_py` `SequentialWriter` (MCAP storage) fed by `rclpy` generic subscriptions; `rclpy` graph for `get_topic_names_and_types`.
- offline-guard extended; rclpy/rosbag2_py lazy-imported behind the package boundary.

</code_context>

<specifics>
## Specific Ideas

- The recorded bag's re-open contract is literally the v1 reader: a live test records, then does `with RosbagsReader(out) as r: list(r.read())` and asserts the expected topics/messages — closing the offline↔live loop.
- A bounded record mode (`--max-messages`/`--duration`) is essential for a deterministic live integration test (record exactly N, exit, assert N).
- Design quote pinning the mechanism: "record to MCAP via rosbag2_py" — do NOT substitute the rosbags Writer here (it's the offline-edit path, not the live-record path).

</specifics>

<deferred>
## Deferred Ideas

- **Replay** (`rosbagger-replay`, transport controls) — Phase 13 (also needs rclpy).
- **GUI Record panel** — Phase 14 (capability-gated over this module's API).
- **QoS profile capture / override**, **compression**, **split by size/duration**, **service/action recording** — recording-feature depth beyond REC-01.
- **Non-MCAP record formats as a general feature** (ROS 1 `.bag`, format menus) — MCAP is the preferred default. (The `--storage sqlite3` capability escape in D-08 is the one exception, forced by the missing MCAP plugin; it is not a general multi-format offering.)
- **`rosbag2_py` reader backend** — still out of scope per PROJECT (add only if a live-workspace custom-msg read need appears).

</deferred>

---

*Phase: 12-live-record*
*Context gathered: 2026-05-23*
