# Requirements: rosbagger

**Defined:** 2026-05-21
**Core Value:** Query and understand the data inside any ROS bag from one command — without writing a one-off script and without needing ROS installed.

## v1 Requirements

Scope = `rosbagger-core` + `bagq`. Each maps to a roadmap phase.

### Reader

- [x] **READ-01**: Open ROS 2 (sqlite3) bags through a `BagReader` interface with no ROS install
- [x] **READ-02**: Open ROS 2 (MCAP) bags through the same interface
- [x] **READ-03**: Open ROS 1 (`.bag`) files through the same interface
- [x] **READ-04**: Iterate messages as `(topic, t, stamp, msgtype, deserialized fields)`
- [x] **READ-05**: Open multiple bag paths as one logical dataset

### Inspect

- [x] **INSP-01**: `bagq info BAG` lists each topic with its message type and message count
- [x] **INSP-02**: `bagq info BAG` reports bag duration, approximate per-topic Hz, and size
- [x] **INSP-03**: `bagq tables BAG` prints each topic's table name and column schema

### Query

- [x] **QURY-01**: Map each topic to one table with a sanitized name (`/camera/image_raw` → `camera_image_raw`)
- [x] **QURY-02**: Flatten nested scalar fields to dotted, quoted columns (e.g. `"twist.twist.linear.x"`)
- [x] **QURY-03**: Represent arrays as `LIST` columns; arrays of sub-messages as `LIST` of `STRUCT`
- [x] **QURY-04**: Add always-present columns `t` (`TIMESTAMP_NS`), `t_ns` (`BIGINT`), `stamp`, `topic`
- [x] **QURY-05**: Resolve referenced topics from the SQL via `sqlglot` and load only those topics
- [x] **QURY-06**: Execute SQL through DuckDB behind a swappable `QueryBackend` seam
- [x] **QURY-07**: Materialize heavy byte blobs (`Image.data`, `PointCloud2.data`) only when the query references them

### Output

- [x] **OUT-01**: Print query results as a formatted table to stdout by default
- [x] **OUT-02**: Export results to CSV via `-o out.csv`
- [x] **OUT-03**: Export results to Parquet via `-o out.parquet`
- [x] **OUT-04**: `--plot` produces a minimal line chart of numeric result columns vs `t`

### CLI

- [x] **CLI-01**: `bagq query "<SQL>" BAG...` runs a query end-to-end
- [x] **CLI-02**: Unknown table → error lists available topics (did-you-mean)
- [x] **CLI-03**: Unknown column → error shows that table's columns
- [x] **CLI-04**: Unresolvable custom message type → error explains how to register `.msg`/`.idl` definitions

## Definition of Done (v1)

- [x] All v1 requirements implemented and covered by tests (255 passed, 97.82% coverage; >=80% gate) — Phase 8
- [x] Test suite runs with **no ROS install** using `rosbags`-written fixture bags (ROS1 + ROS2 + MCAP)
- [x] `bagq` installs via `pip` and exposes `info` / `tables` / `query` — clean-room `pip install ./packages/rosbagger-core ./packages/bagq` verified, all subcommand `--help` exit 0 (Phase 8 SC1)
- [x] Offline packages import without `rclpy` — neutral-cwd import with `rclpy`/`rosbag2_py`/`tools` all unresolvable (Phase 8 SC2)

> v0.1 tagged `v0.1.0` (annotated, local). The only remaining ship step is the
> human-gated push (`git push origin main && git push origin v0.1.0`) + observing
> GitHub Actions green — blocked on the standing `gh`/push-credential blocker. The
> local CI-equivalent gate is green (the strongest available proxy). See
> `.planning/phases/08-packaging-docs-release/08-01-SUMMARY.md`.

## v2 Requirements

Deferred to later milestones (roadmap modules beyond v1 core+bagq).

### TF Debugger
- **TF-01** ✓ (Phase 9 — Complete): Offline TF dropout/timeline report from `/tf` + `/tf_static`

### Live (record/replay)
- **REC-01** ✓ (Phase 12 — Complete): Live topic discovery + checkbox-select recording (needs rclpy)
- **REP-01**: Replay a bag to ROS topics with transport controls (play/pause/step/seek/rate/loop)

### Replay Playback System (Milestone v0.5)
- **REP-02** (Phase 18 — planned): Live scrubbing — control the `Replayer` (seek/rate/loop/pause) *while playing* via a thread-safe command channel; the desktop playhead tracks in real time and the scrubber drags live (backward drag = jump + forward replay, not a visual rewind)
- **REP-03** (Phase 19 — planned): Snippet (in/out region) loop + a collapsible advanced-controls side sub-panel in the Replay tab; the region is markable by dual `Scrubber` handles AND Set-In/Set-Out buttons
- **REP-04** (Phase 20 — planned): RViz fidelity — opt-in `/clock` publishing (for `use_sim_time`) + re-publish of latched/`transient_local`/`/tf_static` topics after a seek so the scene re-primes
- **REP-05** (Phase 21 — planned): `rosbagger-replay` CLI parity flags (`--start-paused`, `--remap`, `--delay`, `--clock`, bounded region) feasible in the custom publish model; runtime ROS services deferred

### GUI
- **GUI-01** ✓ (Phase 14 — Complete): Five capability-gated panels (record/inspect/query/tf/replay) over module APIs

### Edit / Events
- [x] **EDIT-01**: Trim / drop / merge / downsample / convert (ROS1↔ROS2↔MCAP)
- [x] **EVNT-01**: Event sidecar exposed as a queryable `events` table

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

| Requirement | Phase | Status |
|-------------|-------|--------|
| READ-01 | Phase 2 | Complete |
| READ-02 | Phase 2 | Complete |
| READ-03 | Phase 2 | Complete |
| READ-04 | Phase 2 | Complete |
| READ-05 | Phase 2 | Complete |
| QURY-01 | Phase 3 | Complete |
| QURY-02 | Phase 3 | Complete |
| QURY-03 | Phase 3 | Complete |
| QURY-04 | Phase 3 | Complete |
| QURY-07 | Phase 3 | Complete |
| INSP-01 | Phase 4 | Complete |
| INSP-02 | Phase 4 | Complete |
| INSP-03 | Phase 4 | Complete |
| QURY-05 | Phase 5 | Complete |
| QURY-06 | Phase 5 | Complete |
| OUT-01 | Phase 6 | Complete |
| OUT-02 | Phase 6 | Complete |
| OUT-03 | Phase 6 | Complete |
| OUT-04 | Phase 6 | Complete |
| CLI-01 | Phase 7 | Complete |
| CLI-02 | Phase 7 | Complete |
| CLI-03 | Phase 7 | Complete |
| CLI-04 | Phase 7 | Complete |
| TF-01 | Phase 9 | Complete |
| QURY-08 | Phase 10 | Complete (mechanism in 10-01: backend/alias.py + expand_aliases; WIRED into query() in 10-03 with the single-base-topic gate + alias=True keyword — SC1 `vx`→dotted proven end-to-end across ROS1+ROS2-sqlite+MCAP; the thin `bagq query --no-alias` CLI surface is the final 10-04 polish) |
| QURY-09 | Phase 10 | Complete (materialization in 10-02: restrict= projection filter; WIRED into query() in 10-03 — per-topic restrict=(columns & schema_names)|STANDARD when not star, restrict=None under SELECT*; SC2/SC3 proven across ROS1+ROS2-sqlite+MCAP via a recording backend observing query()'s registered table) |
| EDIT-01 | Phase 11 | Complete (raw-copy trim/drop/keep/downsample/merge in 11-01: streaming AnyReader→Writer edit_bag, lossless across ROS1+ROS2-sqlite3+MCAP; cross-format convert ROS1↔ROS2 in 11-02 via the rosbags converter factory — is_same_wireformat→memoryview identity / generate_message_converter→migrate_bytes for the Header.seq case, NOT hand-rolled; headered /imu+/image DESERIALIZE after convert both directions; thin bagq edit / bagq convert verbs over the core API) |
| EVNT-01 | Phase 11 | Complete (sidecar I/O in 11-03: rosbagger_core.events sidecar_path/add_event/list_events over the fixed v1 schema, reusing the locked DuckDB-COPY writer — SC2; reserved `events` query table in 11-04: query() subtracts `events` from topic resolution and registers the sidecar relation via list_events(reader.paths[0]), empty-schema when absent (Open Q3) — a standard BETWEEN interval join works natively across ROS1+ROS2-sqlite3+MCAP, SC3, no special operator; thin bagq events add/list verbs over the core API, SC2 at the CLI; offline invariant held) |
| REC-01 | Phase 12 | Complete (rosbagger-record live module: package scaffold + lazy ROS boundary + teaching capability errors in 12-01; the verified discover→select→`create_subscription(raw=True)`→`rosbag2_py.SequentialWriter`→bounded/SIGINT stop→finalize record core + MCAP-preferred storage gate in 12-02; the thin `rosbagger-record` CLI [`list` + record verbs, parse-time-constrained `--storage`] + the LIVE integration test in 12-03 — external publisher→bounded record→re-open via the v1 RosbagsReader(default_typestore=ROS2_HUMBLE); the live lane RAN on this box, SC1/SC2/SC3 proven via sqlite3, the MCAP assertion skipif-guarded; offline tier stays ROS-free, guard green) |
| REP-01 | Phase 13 | Built — live SC1 proof PENDING orchestrator run (rosbagger-replay live module: package scaffold + raw-CDR `source.py` seam [v1 AnyReader + ROS1→CDR bridge] in 13-01; the PURE `Replayer` transport scheduler [play/pause/step/seek/rate/loop + monotonic pacing + bounded stop, SC2/SC3 unit-proven ROS-free] in 13-02; the lazy `_require_ros` boundary + `replay.py` rclpy publish front door [`get_message`+`deserialize_message`+`create_publisher().publish`, D-04 VERIFIED] + thin `rosbagger-replay` CLI [`--rate`/`--loop`/`--start`/`--topics`/`--duration`/`--max-messages`; D-10 `--end` folded into `--duration`] + offline-guard extension + the LIVE SC1 test in 13-03. Offline tier green [459 passed, 2 skipped @ 97.37%; live test collected-and-skipped]. SC1 NOT yet signed off — the orchestrator MUST run `tests/test_replay_live.py -m live` in the ROS-sourced lane [W4]; only then REP-01 = Complete) |

**Coverage:**
- v1 requirements: 23 total (all Complete)
- Query-ergonomics additions: QURY-08, QURY-09 (Phase 10; both mapped)
- Edit/Events additions: EDIT-01, EVNT-01 (Phase 11; both Complete)
- Live additions: REC-01 (Phase 12; Complete), REP-01 (Phase 13; Built — live SC1 pending orchestrator run)
- Mapped to phases: 29
- Unmapped: 0 ✓

> Phases 1 (Scaffold & Test Harness) and 8 (Packaging, Docs & Release) are infrastructure phases that carry the Definition of Done rather than specific REQ-IDs.

---
*Requirements defined: 2026-05-21*
*Last updated: 2026-05-21 after initial definition*
