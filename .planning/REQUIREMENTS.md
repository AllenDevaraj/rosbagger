# Requirements: rosbagger

**Defined:** 2026-05-21
**Core Value:** Query and understand the data inside any ROS bag from one command — without writing a one-off script and without needing ROS installed.

## v1 Requirements

Scope = `rosbagger-core` + `bagq`. Each maps to a roadmap phase.

### Reader

- [ ] **READ-01**: Open ROS 2 (sqlite3) bags through a `BagReader` interface with no ROS install
- [ ] **READ-02**: Open ROS 2 (MCAP) bags through the same interface
- [ ] **READ-03**: Open ROS 1 (`.bag`) files through the same interface
- [ ] **READ-04**: Iterate messages as `(topic, t, stamp, msgtype, deserialized fields)`
- [ ] **READ-05**: Open multiple bag paths as one logical dataset

### Inspect

- [ ] **INSP-01**: `bagq info BAG` lists each topic with its message type and message count
- [ ] **INSP-02**: `bagq info BAG` reports bag duration, approximate per-topic Hz, and size
- [ ] **INSP-03**: `bagq tables BAG` prints each topic's table name and column schema

### Query

- [ ] **QURY-01**: Map each topic to one table with a sanitized name (`/camera/image_raw` → `camera_image_raw`)
- [ ] **QURY-02**: Flatten nested scalar fields to dotted, quoted columns (e.g. `"twist.twist.linear.x"`)
- [ ] **QURY-03**: Represent arrays as `LIST` columns; arrays of sub-messages as `LIST` of `STRUCT`
- [ ] **QURY-04**: Add always-present columns `t` (`TIMESTAMP_NS`), `t_ns` (`BIGINT`), `stamp`, `topic`
- [ ] **QURY-05**: Resolve referenced topics from the SQL via `sqlglot` and load only those topics
- [ ] **QURY-06**: Execute SQL through DuckDB behind a swappable `QueryBackend` seam
- [ ] **QURY-07**: Materialize heavy byte blobs (`Image.data`, `PointCloud2.data`) only when the query references them

### Output

- [ ] **OUT-01**: Print query results as a formatted table to stdout by default
- [ ] **OUT-02**: Export results to CSV via `-o out.csv`
- [ ] **OUT-03**: Export results to Parquet via `-o out.parquet`
- [ ] **OUT-04**: `--plot` produces a minimal line chart of numeric result columns vs `t`

### CLI

- [ ] **CLI-01**: `bagq query "<SQL>" BAG...` runs a query end-to-end
- [ ] **CLI-02**: Unknown table → error lists available topics (did-you-mean)
- [ ] **CLI-03**: Unknown column → error shows that table's columns
- [ ] **CLI-04**: Unresolvable custom message type → error explains how to register `.msg`/`.idl` definitions

## Definition of Done (v1)

- All v1 requirements implemented and covered by tests
- Test suite runs with **no ROS install** using `rosbags`-written fixture bags (ROS1 + ROS2 + MCAP)
- `bagq` installs via `pip` and exposes `info` / `tables` / `query`
- Offline packages import without `rclpy`

## v2 Requirements

Deferred to later milestones (roadmap modules beyond v1 core+bagq).

### TF Debugger
- **TF-01**: Offline TF dropout/timeline report from `/tf` + `/tf_static`

### Live (record/replay)
- **REC-01**: Live topic discovery + checkbox-select recording (needs rclpy)
- **REP-01**: Replay a bag to ROS topics with transport controls (play/pause/step/seek/rate/loop)

### GUI
- **GUI-01**: Five capability-gated panels (record/inspect/query/tf/replay) over module APIs

### Edit / Events
- **EDIT-01**: Trim / drop / merge / downsample / convert (ROS1↔ROS2↔MCAP)
- **EVNT-01**: Event sidecar exposed as a queryable `events` table

### Query ergonomics
- **QURY-08**: Alias pack (`vx` → `"twist.twist.linear.x"`) for common message types
- **QURY-09**: Column projection pushdown (load only referenced columns)

## Out of Scope

| Feature | Reason |
|---------|--------|
| 3D visualization (pointclouds, robot model) | rviz / Foxglove / Rerun own it — interop via formats instead |
| Rich timeseries plotting | PlotJuggler / Foxglove own it — `--plot` stays minimal |
| Multi-bag catalog / search | North-star data-platform scope, not near-term |
| `rosbag2_py` reader backend | Add only if a live-workspace custom-msg need appears |

## Traceability

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (all v1 REQ-IDs) | TBD | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 21 ⚠️

---
*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 after initial definition*
