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

### Active

<!-- v1 = rosbagger-core + bagq. Hypotheses until shipped. -->

- [ ] Query bag topics with SQL via DuckDB — one table per topic, dotted/quoted columns, `t`/`t_ns`/`stamp`/`topic`
- [ ] Resolve referenced topics from the SQL (sqlglot) and load only those
- [ ] Export query results to CSV and Parquet; minimal `--plot`
- [ ] Teaching errors: unknown table/column → suggestions; unresolvable custom msg → registration guidance

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
*Last updated: 2026-05-22 after Phase 4 (Inspect) completion — `bagq info`/`bagq tables` ship bag overview (INSP-01..03) over O(1) reader metadata + the Phase 3 schema. Reader (P2), schema flattening (P3), and inspect (P4) are validated. Next user-facing capabilities: SQL query engine (Phase 5 — note WR-01 schema-collision guard already landed in P4), export (Phase 6), CLI + teaching errors (Phase 7).*
