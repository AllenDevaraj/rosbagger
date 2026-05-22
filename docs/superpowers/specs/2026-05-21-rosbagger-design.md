# rosbagger — Design Spec

- **Date:** 2026-05-21
- **Status:** Draft for review
- **Scope of this spec:** Full system vision + detailed v1 design

---

## 1. Problem & motivation

Every robotics team that touches ROS bags rewrites the same two throwaway tools:

1. **Ad-hoc bag querying** — "pull `/odom` velocity where it exceeds 0.5, dump to CSV/plot." Today this is a one-off Python script per question — the "50 scripts every team writes."
2. **TF debugging** — "which transform stopped publishing, and when?" One of the most common ROS pain points, with no good *offline* tool.

These needs are near-universal across ROS domains (AVs, drones, AMRs/warehouse, quadrupeds, humanoids, manipulation, agriculture, maritime/subsea, space, medical, academia). Existing tools — Foxglove, PlotJuggler, `rosbags`, `kappe`, `ros2 bag` — are strong at visualization and conversion, but there is **no SQL-over-bags CLI** and **no dedicated offline TF-dropout timeline**. `rosbagger` targets those two gaps first — querying in v1, TF debugging as the very next module — then grows into a modular cockpit for the whole bag lifecycle.

## 2. Goals & non-goals

**Goals**
- A universal, **no-ROS-required** core that reads ROS1 / ROS2 / MCAP bags.
- `bagq`: query bags with SQL → CSV / Parquet / plot. **(v1)**
- A modular monorepo so each tool installs independently and the system grows by adding small packages.
- An eventual GUI that is a *complete* face over every CLI capability.

**Non-goals (YAGNI)**
- Not rebuilding 3D visualization — rviz / Foxglove own it.
- Not rebuilding rich timeseries plotting — PlotJuggler / Foxglove own it. `--plot` is a convenience only.
- Not a multi-bag data platform / catalog — named as a north-star, not built.

## 3. Architecture

### 3.1 Monorepo of small, independently-installable packages

```
rosbagger/   (monorepo of small, independently-installable packages)

  OFFLINE world — pure Python, no ROS, pip-install anywhere
  ┌──────────────────────────────────────────────────────────┐
  │ rosbagger-core                                             │
  │   • BagReader interface ──(impl)──► rosbags (ROS1/2/MCAP)  │
  │   • msg → table flattening (scalars→cols, arrays→LIST,     │
  │                             + t / t_ns / stamp / topic)    │
  │   • QueryBackend seam   ──(default)──► DuckDB              │
  │   • output writers: CSV · Parquet · plot                   │
  │   • Inspect (bag overview)                                 │
  └───────────▲────────────────────────▲─────────────────────┘
              │                         │
   ┌──────────┴────────┐   ┌────────────┴─────────────┐
   │ bagq  (CLI) ★v1   │   │ rosbagger-tf (analysis)  │
   │ SQL → CSV/parquet/ │   │ /tf timeline + dropout   │
   │ plot               │   │ report (a query pack)    │
   └────────────────────┘   └──────────────────────────┘

  LIVE world — needs rclpy / ROS running
  ┌──────────────────────────┐   ┌──────────────────────────┐
  │ rosbagger-record         │   │ rosbagger-replay         │
  │ topic discovery + select │   │ play bag → ROS topics    │
  │ → record (rosbag2_py)    │   │ transport: play/pause/   │
  │                          │   │ step/seek/rate/loop      │
  └──────────────────────────┘   └──────────────────────────┘
              ▲                                ▲
              └───────────────┬────────────────┘
                     ┌────────┴─────────┐
                     │ rosbagger-gui    │  5 capability-gated panels:
                     │ thin face over   │  Record · Inspect · Query ·
                     │ module APIs      │  TF · Replay
                     └──────────────────┘

  rviz / Foxglove / PlotJuggler interop = free: emit Parquet/CSV/MCAP
  they already read; replay publishes real ROS topics they subscribe to.
```

### 3.2 Two worlds

- **Offline** (`core`, `bagq`, `tf`, `edit`, `events`): pure Python, **never import ROS**. Run anywhere, on ROS1/ROS2/MCAP bags. This preserves the "universal" promise.
- **Live** (`record`, `replay`): depend on `rclpy` / ROS; installed and run only where ROS exists (the robot / sim machine).

This split is the spine of the repo. Recording happens on the robot; analysis happens on a laptop — often different machines.

### 3.3 Key principles

1. **API-first / CLI–GUI parity.** Every capability lives in a module's Python API. The CLI and the GUI are both *thin presentation layers* over the same API; neither owns logic. This structurally guarantees "everything in the terminal is in the GUI" (and vice-versa). Interaction adapts to medium — a SQL string in the terminal ↔ a query box + Run in the GUI; `--trim START END` ↔ a draggable timeline range.
2. **Offline modules never import ROS.**
3. **Live modules isolate `rclpy`** behind their package boundary.
4. **Capability-gated GUI / graceful degradation.** Offline panels (Inspect/Query/TF) always work; live panels (Record/Replay) light up only when a live ROS graph is present.
5. **Interop via formats, not integrations.** Emit Parquet/CSV/MCAP; replay publishes real ROS topics. rviz / Foxglove / PlotJuggler consume these for free.
6. **Swappable query backend.** A `QueryBackend` seam; DuckDB is the default (embedded SQL + native Parquet/CSV + `LIST`/`STRUCT` types). Can swap to Polars/SQLite without touching the rest.

## 4. v1 scope — `rosbagger-core` + `bagq`

### 4.1 `rosbagger-core`

**`BagReader` interface** — yields records `(topic, t, stamp, msgtype, msg)`.
- Implementation: `rosbags` `AnyReader` → one uniform path for ROS1/ROS2/MCAP, no ROS install. `msg` is the deserialized message object.
- Connection/topic/type metadata + message counts exposed for Inspect without full deserialization.
- Future backend: `rosbag2_py` behind the same interface, for live-workspace custom messages `rosbags` cannot resolve.

**Message → table mapping**
- One table per topic. Table name = topic with leading `/` dropped and remaining `/` → `_` (`/camera/image_raw` → `camera_image_raw`). Collisions resolved with a uniqueness check; `bagq tables` prints the mapping.
- Nested scalar fields flattened to **dotted, faithful** column names (`twist.twist.linear.x`). These require quoting in SQL: `WHERE "twist.twist.linear.x" > 0.5`.
- Arrays → DuckDB `LIST` columns; arrays of sub-messages → `LIST` of `STRUCT`.
- Heavy byte blobs (`Image.data`, `PointCloud2.data`) are only materialized if the query references them.
- Always-present columns: `t` (`TIMESTAMP_NS`, log/receive time), `t_ns` (`BIGINT`, exact ns), `stamp` (`TIMESTAMP_NS` from `header.stamp`, else `NULL`), `topic` (raw string).

**`QueryBackend` seam** — default DuckDB. Loads selected topic tables, runs the SQL, returns Arrow.

**Output writers** — CSV, Parquet (native via DuckDB `COPY ... TO`), and a minimal plot helper (matplotlib).

**Inspect** — bag overview: topics, message types, message counts, duration (first/last timestamp), approximate Hz (count / duration), file size.

### 4.2 `bagq` CLI

- `bagq info BAG...` — the Inspect overview ("what's in here?").
- `bagq tables BAG...` — each topic → its table name + column schema (so users know what to type).
- `bagq query "<SQL>" BAG... [-o OUT.{csv,parquet}] [--plot [FILE]] [--format table|csv|parquet|json]`
  - **Topic resolution:** parse the SQL with `sqlglot` → find referenced tables → load *only those topics* into the backend → execute. (v1: load referenced topics fully; column projection pushdown is a later optimization.)
  - **Multiple bags:** opened as one logical dataset (handy for split recordings).
- **Outputs:** pretty table to stdout by default; `-o` writes CSV/Parquet; `--plot` produces an intentionally-minimal line chart (numeric result columns vs `t`) — not a PlotJuggler rebuild.
- **Errors that teach:** unknown table → list available topics (did-you-mean); unknown column → show that table's columns; unresolvable custom msg type → explain how to register its `.msg`/`.idl` definitions with `rosbags`.

### 4.3 Dependencies (v1)

Python ≥ 3.10, `rosbags`, `duckdb`, `sqlglot`, `pyarrow`, `matplotlib` (plot only), a CLI lib (`typer` or `click`), and `rich`/`tabulate` for table output. **No ROS dependency.**

## 5. Roadmap (post-v1)

Sequenced; each is a small package with a defined seam. Order is a starting point, not fixed.

1. **`rosbagger-tf`** (offline) — load `/tf` + `/tf_static` tables, build the transform graph over time, detect dropouts/gaps → timeline ("frame X missing at t=12.4s; parent Y unpublished for 800ms"). A query-pack/analysis on `core`.
2. **`rosbagger-record`** (live) — discover active topics + their types from the ROS graph, checkbox-select, record to MCAP via `rosbag2_py`.
3. **`rosbagger-replay`** (live) — play a bag → ROS topics with transport controls (play / pause / step / seek / rate / loop); drives rviz / Foxglove.
4. **`rosbagger-gui`** — one app, five capability-gated panels: Record · Inspect · Query · TF · Replay. Thin face over module APIs; graceful degradation without ROS.
5. **`rosbagger-edit`** (offline, bag→bag) — trim time range, drop/keep topics, merge, downsample, convert ROS1↔ROS2↔MCAP. CLI verbs (`bagq edit` / `bagq convert`) + GUI Edit/Export.
6. **annotations / events** — events `(t_start, t_end, label, …)` stored in a sidecar (`<bag>.events.parquet`), exposed by `core` as a table `events` (queryable + JOINable against data by time). Live "mark event now" appends to the sidecar; the GUI draws markers across the Inspect/TF timelines and jump-points in Replay. Not a separate engine — another table + a thin write path.

**North-star (not committed):** multi-bag catalog / search across many files (data-platform territory).

## 6. Testing strategy

- **No ROS in CI:** `rosbags` can *write* tiny fixture bags (ROS1 + ROS2 + MCAP), so the whole suite runs without a ROS install.
- **Unit:** message→table flattening, table-name sanitization, time extraction, SQL table-extraction (sqlglot).
- **Integration:** fixture bags → `bagq query` → assert result tables / exports.
- **E2E:** CLI invocations → CSV/Parquet output correctness.
- Coverage target per project standards (≥ 80%).

## 7. Open questions / fast-follows

- **Alias pack** (`vx` → `"twist.twist.linear.x"`, etc. for common message types) — more valuable now that columns are quoted. Fast-follow after v1.
- **Projection pushdown** (load only referenced columns, not whole topics) — optimization if large bags strain memory.
- **`rosbag2_py` reader backend** — add when live-workspace custom messages need it.
