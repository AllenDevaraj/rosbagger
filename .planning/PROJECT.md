# rosbagger

## What This Is

rosbagger is a modular monorepo of ROS bag tooling spanning the whole bag lifecycle — record, inspect, query, debug, replay. Its first deliverable, `bagq`, is a universal "DuckDB-for-bags" SQL CLI that queries ROS 1 / ROS 2 / MCAP bags (no ROS install required) and exports CSV / Parquet / plots — replacing the throwaway scripts every robotics team rewrites. It's for robotics engineers across any ROS domain (AVs, drones, AMRs, humanoids, manipulation, research).

## Core Value

Query and understand the data inside any ROS bag from one command — without writing a one-off script and without needing ROS installed.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- [x] Read ROS1 / ROS2 / MCAP bags through one interface with no ROS install (rosbags backend) — *Validated in Phase 2 (READ-01..05): `BagReader`/`RosbagsReader`, 30 ROS-free tests*
- [x] Inspect a bag: topics, message types, counts, duration, approx Hz, size — *Validated in Phase 4 (INSP-01..03): `bagq info` + `bagq tables`, O(1) metadata, API-first*
- [x] Query bag topics with SQL via DuckDB — one table per topic, dotted/quoted columns, `t`/`t_ns`/`stamp`/`topic` — *Validated in Phases 3+5 (QURY-01..06): `query(sql, reader)` over a swappable `QueryBackend`, end-to-end across all 3 formats*
- [x] Resolve referenced topics from the SQL (sqlglot) and load only those — *Validated in Phase 5 (QURY-05): sqlglot resolver + connection-filtered `read(topics=)`*
- [x] Export query results to CSV and Parquet; minimal `--plot` — *Validated in Phase 6 (OUT-01..04): `bagq query` stdout table + CSV/Parquet via DuckDB COPY + headless `--plot`*
- [x] Teaching errors: unknown table/column → suggestions; unresolvable custom msg → registration guidance — *Validated in Phase 7 (CLI-01..04): `bagq` CLI + did-you-mean / column listing / msg-registration guidance, clean Exit(1)*
- [x] Offline TF dropout/timeline report from `/tf` + `/tf_static` — *Validated in Phase 9 (TF-01): `bagq tf` + `rosbagger_core.tf.collect_tf_report` — parent→child graph + per-edge median×multiplier gap detection, rich table + `--format json`, 274 ROS-free tests across ROS 1 / ROS 2 sqlite3 / MCAP*
- [x] Terser + leaner queries: message-type alias pack (`vx` → `"twist.twist.linear.x"`) and column projection pushdown — *Validated in Phase 10 (QURY-08/09): `rosbagger_core.backend.alias` (sqlglot-AST rewrite, existence-gated, single-base-topic) + `restrict=` projection across the schema layer wired into `query()`; `bagq query --no-alias`; a single-column query materializes only the referenced + 4 standard columns (recording-backend proof across ROS 1 / ROS 2 sqlite3 / MCAP); 319 ROS-free tests*
- [x] Offline bag editing + queryable events: trim/drop/keep/downsample/merge/convert (ROS1↔ROS2↔MCAP) and a `<bag>.events.parquet` sidecar exposed as a time-joinable `events` table — *Validated in Phase 11 (EDIT-01/EVNT-01): `rosbagger_core.edit` (streaming `AnyReader→filter→rosbags Writer`; raw-copy when wireformats match, library-migration convert — never hand-rolled) + `rosbagger_core.events` + a reserved `events`-table hook in `query()` (native `BETWEEN` interval join); thin `bagq edit`/`convert`/`events {add,list}` verbs; 402 ROS-free tests; code review's 1 critical (`/events` topic shadowing) + 4 warnings fixed*

### Active

<!-- v0.2 "Modular cockpit" (Phases 9–14). Hypotheses until shipped. -->

- *v0.2 "Modular cockpit" milestone in progress — Phases 9 (TF debugger) + 10 (query ergonomics) + 11 (edit & events) ✓ validated above; Phases 12–14 pending (live record/replay, GUI — these need `rclpy`, except the GUI's offline panels).*

### Out of Scope

<!-- Explicit boundaries with reasoning. -->

- 3D visualization (pointclouds, robot model) — rviz / Foxglove / Rerun own it; interop via formats instead
- Rich timeseries plotting — PlotJuggler / Foxglove own it; `--plot` stays intentionally minimal
- Live recording & replay (v1) — deferred to `rosbagger-record` / `rosbagger-replay` (live, needs rclpy)
- GUI (v1) — deferred to `rosbagger-gui` (thin face over module APIs, capability-gated)
- Multi-bag catalog / search — north-star, not near-term

## Context

- **Environment:** ROS 2 Humble present (`rosbag2_py` importable), but offline modules must NOT depend on ROS. As of Phase 1, the uv workspace is scaffolded and the pinned offline stack (`rosbags`, `duckdb`, `sqlglot`, `pyarrow`, `typer`/`rich`) is installed; a `sys.meta_path` guard test actively proves no ROS leaks into the offline import graph. (Local `pytest`/`ruff` runs need a `PYTHONPATH=""` prefix because the dev shell sources ROS onto `PYTHONPATH`; CI is ROS-free.)
- **Design spec:** full vision + detailed v1 design committed at `docs/superpowers/specs/2026-05-21-rosbagger-design.md`.
- **Landscape researched:** `rosbags` (universal reader/writer, no ROS), MCAP (default ROS2 format), `kappe`, PlotJuggler, Foxglove, Rerun (viz + dataframe API — treated as an interop/viz target; validates the "query your robot data" direction).
- **Architecture:** monorepo of small packages; **offline** (core/bagq/tf/edit/events) vs **live** (record/replay) split; GUI is a thin face over module APIs.

## Constraints

- **Tech stack**: Python ≥ 3.10 — `rosbags`, `duckdb` (behind a swappable `QueryBackend` seam), `sqlglot`, `pyarrow`, `matplotlib`, `typer`/`click`. No ROS dependency for offline modules.
- **Compatibility**: must read ROS 1 and ROS 2 (sqlite3 + mcap) bags.
- **Portability**: offline tools run anywhere, CI included, with no ROS install — tests use `rosbags`-written fixture bags.
- **Interop**: emit standard formats (Parquet / CSV / MCAP); never rebuild existing viewers.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Universal reader via `rosbags` (not `rosbag2_py`) | No ROS needed; reads ROS1/2/MCAP; matches the "universal" goal | — Pending |
| DuckDB as default query backend, behind a seam | Embedded SQL + native Parquet/CSV + LIST/STRUCT types | — Pending |
| Flatten messages to dotted, quoted columns | Faithful to message structure; alias pack (`vx`) as a fast-follow | — Pending |
| Build v1 = `core` + `bagq` first | Highest leverage; the TF debugger later reuses the same engine | — Pending |
| Monorepo of small packages | Independent installs; isolate `rclpy` to live modules only | — Pending |
| API-first: CLI & GUI are thin layers over module APIs | Structurally guarantees terminal↔GUI capability parity | — Pending |
| `--plot` stays minimal; matplotlib is the optional `bagq[plot]` extra, plotting numeric cols vs `t_ns` headless (Agg) | Don't rebuild PlotJuggler/Foxglove; keep the base install lean + offline; t_ns avoids the ns→datetime crash | ✓ Phase 6 (OUT-04) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-23 — **v0.2 "Modular cockpit" — Phase 11 (Edit & Events) complete.** rosbagger can now edit bags and annotate them: `bagq edit` (trim/drop/keep/downsample/merge) + `bagq convert` produce valid re-openable bags across ROS1↔ROS2↔MCAP (raw-copy when wireformats match, the `rosbags` library migration path for cross-format — never hand-rolled), and `bagq events add`/`list` write a `<bag>.events.parquet` sidecar that `query()` exposes as a reserved, time-joinable `events` table (native `BETWEEN` interval join). 402 ROS-free tests at ~97% coverage across all three formats; code review's 1 critical (`/events` topic shadowing) + 4 material warnings fixed (see `11-REVIEW.md`/`11-VERIFICATION.md`; WR-04 multi-bag events + WR-05 sidecar-travels-with-edit deferred). Remaining v0.2 phases: 12–13 live record/replay, 14 GUI (the live work needs `rclpy`). 4 phases done in v0.2; 11 phases done overall.*
*v0.1 (complete, all 8 phases): `bagq` v0.1.0 — read ROS1/ROS2/MCAP → inspect → SQL via DuckDB → export CSV/Parquet/plot, errors that teach, no ROS install; pip-installable, MIT, `v0.1.0` tagged locally. **Standing maintainer step:** `git push origin main && git push origin v0.1.0` + confirm CI green (no push credential in the build environment).*
