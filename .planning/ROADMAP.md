# Roadmap: rosbagger

## Overview

rosbagger v1 builds the offline core and the `bagq` CLI in technical layers: scaffold → reader → schema mapping → inspect → query engine → output → CLI → packaging. Each layer is independently testable with **no ROS install** (tests use `rosbags`-written fixture bags), and they assemble into a SQL-over-bags tool that reads ROS 1 / ROS 2 / MCAP and exports CSV / Parquet / plots.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Scaffold & Test Harness** - Monorepo, packaging, and no-ROS fixture bags (completed 2026-05-22)
- [x] **Phase 2: Bag Reader Layer** - Universal ROS1/ROS2/MCAP reading via rosbags (completed 2026-05-22)
- [x] **Phase 3: Message→Table Schema** - Flatten messages into DuckDB columns (completed 2026-05-22)
- [x] **Phase 4: Inspect** - `bagq info` / `bagq tables` (completed 2026-05-22)
- [x] **Phase 5: Query Engine** - DuckDB backend + sqlglot topic resolution (completed 2026-05-22)
- [x] **Phase 6: Output & Export** - stdout table, CSV, Parquet, minimal plot
- [x] **Phase 7: CLI & Teaching Errors** - `bagq query` end-to-end with helpful errors (completed 2026-05-22)
- [x] **Phase 8: Packaging, Docs & Release** - pip-installable v0.1, offline imports (completed 2026-05-22)

### Milestone v0.2 — Modular cockpit (TF · ergonomics · edit · live · GUI)

- [x] **Phase 9: TF Debugger** - offline `/tf` dropout/timeline report (`bagq tf` subcommand) (completed 2026-05-22)
- [x] **Phase 10: Query Ergonomics** - alias pack + column projection pushdown (completed 2026-05-23)
- [ ] **Phase 11: Edit & Events** - trim/drop/merge/convert + queryable events sidecar
- [ ] **Phase 12: Live Record** - live topic discovery + select recording (rclpy)
- [ ] **Phase 13: Live Replay** - replay a bag to ROS topics with transport controls (rclpy)
- [ ] **Phase 14: GUI** - capability-gated panels over module APIs (Textual TUI)

## Phase Details

### Phase 1: Scaffold & Test Harness

**Goal**: Monorepo skeleton (`rosbagger-core`, `bagq`), packaging, dev tooling, and a fixture-bag generator so every later phase tests with no ROS install.
**Depends on**: Nothing (first phase)
**Requirements**: (infrastructure — supports Definition of Done)
**Success Criteria** (what must be TRUE):

  1. `rosbagger-core` and `bagq` import as installed packages
  2. `pytest` runs green in CI with no ROS installed
  3. A generator produces ROS1, ROS2-sqlite, and MCAP fixture bags

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Monorepo layout + pyproject for `rosbagger-core` and `bagq` (uv workspace, src-layout, hatchling, console script, importable packages) -> SC1

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Dev tooling: ruff (lint+format), pytest + pytest-cov (>=80%), no-ROS GitHub Actions CI, and the sys.meta_path offline-import guard -> SC2
- [x] 01-03-PLAN.md — Fixture-bag generator: rosbags writes tiny ROS1/ROS2-sqlite/MCAP bags, re-openable via AnyReader, forward-looking content -> SC3

### Phase 2: Bag Reader Layer

**Goal**: A `BagReader` interface with a `rosbags` implementation that opens ROS1/ROS2/MCAP and iterates messages uniformly.
**Depends on**: Phase 1
**Requirements**: READ-01, READ-02, READ-03, READ-04, READ-05
**Success Criteria** (what must be TRUE):

  1. Reader opens ROS2 sqlite, ROS2 MCAP, and ROS1 bags
  2. Iterating yields `(topic, t, stamp, msgtype, fields)` per message
  3. Multiple bag paths read as one logical dataset

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — `BagReader` ABC seam + frozen `Message` record dataclass (topic, t, t_ns, stamp, msgtype, msg); ROS-free abstract contract -> READ-04

**Wave 2** *(blocked on 02-01)*

- [x] 02-02-PLAN.md — `RosbagsReader(BagReader)`: thin `AnyReader` adapter opening ROS1/ROS2-sqlite/ROS2-MCAP, lazy record-building read loop, uniform `stamp` extraction, multi-bag pass-through -> READ-01/02/03/04/05

**Wave 3** *(blocked on 02-02)*

- [x] 02-03-PLAN.md — Fixture-backed reader test suite across all 3 formats + multi-bag merge (two ROS2 + two ROS1 bags), resolving the multi-ROS2 open question -> READ-01/02/03/04/05

### Phase 3: Message→Table Schema

**Goal**: Flatten ROS messages into a DuckDB-friendly table schema — dotted/quoted columns, LIST arrays, standard time columns, sanitized table names.
**Depends on**: Phase 2
**Requirements**: QURY-01, QURY-02, QURY-03, QURY-04, QURY-07
**Success Criteria** (what must be TRUE):

  1. A nested message maps to dotted/quoted columns with correct types
  2. Array fields become LIST columns; sub-message arrays become LIST of STRUCT
  3. Every table has `t`, `t_ns`, `stamp`, `topic`; `/a/b` → table `a_b`
  4. Heavy byte blobs are excluded unless explicitly requested

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Topic→table name sanitization (`/a/b`→`a_b`, collision-resolving `TableNameResolver`) + the backend-neutral `ColumnDef`/`TableSchema` model contract -> QURY-01

**Wave 2** *(blocked on 03-01)*

- [x] 03-02-PLAN.md — ROS→Arrow type map + recursive `get_msgdef().fields` flatten walk → dotted columns, LIST/STRUCT types, heavy-blob flag, and the four standard `t`/`t_ns`/`stamp`/`topic` columns -> QURY-02/03/04

**Wave 3** *(blocked on 03-02)*

- [x] 03-03-PLAN.md — Row extraction + `build_arrow_table` (pyarrow Table from a Message stream), lazy heavy-blob `include` seam, sqlglot identifier quoting, and the public `schema/` API -> QURY-03/07

### Phase 4: Inspect

**Goal**: Bag overview commands built on the reader + schema.
**Depends on**: Phase 3
**Requirements**: INSP-01, INSP-02, INSP-03
**Success Criteria** (what must be TRUE):

  1. `bagq info BAG` lists topics, message types, and counts
  2. `bagq info BAG` shows duration, approx Hz, and size
  3. `bagq tables BAG` prints each topic's table name and columns

**Plans**: 2 plans

Plans:
**Wave 1**

- [x] 04-01-PLAN.md — `bagq info`: `rosbagger_core/inspect.py` (`BagInfo`/`TopicInfo` + `collect_bag_info`) over O(1) AnyReader metadata + additive reader properties; thin `bagq info` rich command -> INSP-01/02

**Wave 2** *(blocked on 04-01)*

- [x] 04-02-PLAN.md — `bagq tables`: `collect_table_schemas` (TableNameResolver + build_table_schema per topic, multi-msgtype skip); thin `bagq tables` rich command -> INSP-03

### Phase 5: Query Engine

**Goal**: A swappable `QueryBackend` (DuckDB default) that loads only the topics a query references and runs SQL.
**Depends on**: Phase 3
**Requirements**: QURY-05, QURY-06
**Success Criteria** (what must be TRUE):

  1. A `SELECT` over a topic returns correct rows via DuckDB
  2. Only topics referenced in the SQL are loaded (via sqlglot)
  3. The query backend is swappable behind the seam interface

**Plans**: 2 plans

Plans:

**Wave 1**

- [x] 05-01-PLAN.md — `QueryBackend` ABC seam + `DuckDBBackend` (register Arrow → run SQL → Arrow via `to_arrow_table`) + the WR-01 collision fix in `build_table_schema` -> QURY-06

**Wave 2** *(blocked on 05-01)*

- [x] 05-02-PLAN.md — sqlglot topic resolution + `query(sql, reader)` orchestrator (load only referenced topics via `read(topics=)`, register, execute) -> QURY-05/06

### Phase 6: Output & Export

**Goal**: Render and export query results.
**Depends on**: Phase 5
**Requirements**: OUT-01, OUT-02, OUT-03, OUT-04
**Success Criteria** (what must be TRUE):

  1. Results print as a formatted table to stdout
  2. `-o out.csv` and `-o out.parquet` write correct files
  3. `--plot` emits a line chart of numeric columns vs `t`

**Plans**: 2 plans

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — `rosbagger_core.output` (temporal-safe rich render + CSV/Parquet via DuckDB `COPY`) + thin `bagq query "<SQL>" BAG [-o OUT] [--format table|csv|parquet|json]` command -> OUT-01/02/03

**Wave 2** *(blocked on 06-01)*

- [x] 06-02-PLAN.md — minimal `--plot [FILE]`: headless (Agg) matplotlib line chart of numeric cols vs `t_ns`; matplotlib added to the dev group + `pytest.importorskip`; graceful `ImportError` → install `bagq[plot]` -> OUT-04

### Phase 7: CLI & Teaching Errors

**Goal**: Wire `query`/`info`/`tables` into the `bagq` CLI with errors that teach.
**Depends on**: Phase 4, Phase 5, Phase 6
**Requirements**: CLI-01, CLI-02, CLI-03, CLI-04
**Success Criteria** (what must be TRUE):

  1. `bagq query "<SQL>" BAG...` works end-to-end from the shell
  2. Unknown table lists available topics; unknown column lists that table's columns
  3. Unresolvable custom msg prints registration guidance

**Plans**: 2 plans

Plans:
**Wave 1**

- [x] 07-01-PLAN.md — CLI finalization: shared `teaching_errors` catch mechanism (clean message + `Exit(1)`, no traceback) across query/info/tables + WR-01 (splitext) and WR-02 (portable buffered CSV) fixes in `output/export.py`; real-shell smoke -> CLI-01

**Wave 2** *(blocked on 07-01)*

- [x] 07-02-PLAN.md — Teaching errors: stdlib-only `errors.py`; `UnknownTableError` did-you-mean (CLI-02); `UnknownColumnError` from `BinderException` listing that table's columns (CLI-03); `UnresolvedTypeError` at the reader boundary + def-less fixture (CLI-04); CLI presents all three -> CLI-02/03/04

### Phase 8: Packaging, Docs & Release

**Goal**: Make v0.1 installable and clean.
**Depends on**: Phase 7
**Requirements**: (Definition of Done — pip install, offline imports, CI)
**Success Criteria** (what must be TRUE):

  1. `pip install` yields a working `bagq` with `--help`
  2. Offline packages import without `rclpy`
  3. CI is green; version tagged 0.1

**Plans**: 1 plan

Plans:

- [x] 08-01-PLAN.md — Version bump 0.0.0→0.1.0 (4 sources + re-lock uv.lock) + MIT LICENSE + expanded README (verified pip recipe, per-command usage, offline guarantee) + clean-room pip-install verification (SC1/SC2) + local CI-equivalent gate + local `v0.1.0` tag; push+observe-CI documented as the sole human follow-up (SC3 split) -> SC1/SC2/SC3

### Phase 9: TF Debugger

**Goal**: An offline TF analyzer that loads `/tf` + `/tf_static`, builds the transform graph over time, and reports dropouts/gaps on a timeline — reusing the v1 reader, no ROS install. Surface = a `bagq tf` subcommand with logic in `rosbagger_core/tf.py` (locked decision; no separate `rosbagger-tf` package, so the existing `--cov=rosbagger_core` gate covers it).
**Depends on**: Phase 2, Phase 5
**Requirements**: TF-01
**Success Criteria** (what must be TRUE):

  1. Loads `/tf` + `/tf_static` and builds the parent→child transform graph
  2. Detects per-edge dropouts/gaps and reports them with timestamps (e.g. "odom→base_link unpublished 800ms at t=12.4s")
  3. Output is a timeline/table; runs on a fixture bag with no ROS install

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 09-01-PLAN.md — `write_tf_bag` fixture writer in `tools/make_fixtures.py`: `/tf_static` map→odom + dynamic `/tf` odom→base_link (seeded ~800ms gap) + clean base_link→laser, across ROS1/ROS2-sqlite/MCAP (ROS1 registers `tf2_msgs/msg/TFMessage`) -> TF-01
- [x] 09-02-PLAN.md — `rosbagger_core/tf.py` core: frozen `TfReport`/`EdgeReport`/`GapReport` + `collect_tf_report(reader)` (stream `/tf`+`/tf_static`, build parent→child graph, median×multiplier gap detection with all edge cases) + `NoTransformsError` in `errors.py` -> TF-01

**Wave 2** *(blocked on 09-01 + 09-02)*

- [x] 09-03-PLAN.md — `bagq tf` subcommand (rich edge-summary + gap-timeline tables, `--gap-multiplier`/`--gap-ms`/`--format json`, `NoTransformsError` via `teaching_errors`) + fixture-backed SC1/SC2/SC3 tests across all three formats + offline-guard extension for the TF module -> TF-01

### Phase 10: Query Ergonomics

**Goal**: Make `bagq` queries terser and faster — an alias pack for common message fields and column projection pushdown so a query loads only the columns it references.
**Depends on**: Phase 3, Phase 5
**Requirements**: QURY-08, QURY-09
**Success Criteria** (what must be TRUE):

  1. Alias pack resolves common shortcuts (e.g. `vx` → `"twist.twist.linear.x"`) in user SQL
  2. Column projection pushdown loads only referenced columns (not whole topics)
  3. Verifiable: a single-column query does not materialize unreferenced/heavy columns

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 10-01-PLAN.md — Built-in alias pack + `expand_aliases` sqlglot-AST rewrite in new `backend/alias.py` (existence-gated, offline-safe) + offline-guard extension -> QURY-08
- [x] 10-02-PLAN.md — Projection `restrict=` filter generalized onto `arrow_schema`/`column_names`/`build_arrow_table`/`flatten_message` (the skipped-read pushdown) -> QURY-09

**Wave 2** *(blocked on 10-01 + 10-02)*

- [x] 10-03-PLAN.md — Wire both into `query()`: hoist per-topic schema build, single-base-topic alias gate (Open Q1), compute+thread the restrict set (D-06/07/08), forward rewritten SQL; SC3 proof across all three formats -> QURY-08/09

**Wave 3** *(blocked on 10-03)*

- [x] 10-04-PLAN.md — `bagq query --no-alias` surface (aliases on by default, projection transparent; D-11) + full-suite/ruff/offline-guard phase gate -> QURY-08

### Phase 11: Edit & Events

**Goal**: Offline bag editing (trim/drop/merge/downsample/convert across ROS1↔ROS2↔MCAP via the `rosbags` writer) plus an event sidecar exposed as a queryable, time-joinable `events` table.
**Depends on**: Phase 2, Phase 5
**Requirements**: EDIT-01, EVNT-01
**Success Criteria** (what must be TRUE):

  1. trim/drop/merge/downsample/convert produce valid bags that re-open via `AnyReader`
  2. An event sidecar (`<bag>.events.parquet`) is written and read back
  3. The `events` table is queryable and JOINable against data by time

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 11-01-PLAN.md — Edit core: streaming `AnyReader → filter → rosbags Writer` pipeline (`rosbagger_core/edit/`) with raw-copy trim/drop/keep/downsample/merge + format selection; round-trip (re-open + deserialize) tests across ROS1/ROS2-sqlite3/MCAP + offline-guard extension -> EDIT-01
- [ ] 11-03-PLAN.md — Events sidecar I/O (`rosbagger_core/events.py`): file-vs-dir-aware `sidecar_path` + `add_event`/`list_events` over `<bag>.events.parquet` (fixed v1 schema), reusing the locked DuckDB-COPY writer; SC2 write/read/append tests -> EVNT-01

**Wave 2** *(blocked on 11-01)*

- [ ] 11-02-PLAN.md — Cross-format convert via the `rosbags` converter factory (`is_same_wireformat`/`generate_message_converter`, no hand-rolled migration) wired into `edit_bag` + thin `bagq edit`/`bagq convert` verbs; convert round-trip (deserialize headered msgs) tests both directions -> EDIT-01

**Wave 3** *(blocked on 11-02 + 11-03)*

- [ ] 11-04-PLAN.md — Reserved `events`-table hook in `query()` (subtract from topic resolution, register sidecar relation, native `BETWEEN` interval join — SC3) + thin `bagq events add`/`list` verbs (SC2 at the CLI) + events offline-guard extension -> EVNT-01

### Phase 12: Live Record

**Goal**: A live recorder (`rosbagger-record`) — discover live ROS topics and record a selected subset to a bag. Requires `rclpy` (present on host); the offline modules stay ROS-free.
**Depends on**: Phase 2
**Requirements**: REC-01
**Success Criteria** (what must be TRUE):

  1. Discovers currently-published live topics
  2. Records a selected subset to a bag while a publisher is running
  3. The recorded bag re-opens and iterates via the v1 reader

**Plans**: TBD (set at plan-phase)

### Phase 13: Live Replay

**Goal**: A live replayer (`rosbagger-replay`) — publish a bag's messages to real ROS topics with transport controls (play/pause/step/seek/rate/loop). Requires `rclpy`.
**Depends on**: Phase 2
**Requirements**: REP-01
**Success Criteria** (what must be TRUE):

  1. Replays a bag, publishing real ROS topics a subscriber receives
  2. Transport controls work: play/pause/step/seek/rate/loop
  3. Rate scaling and seek land at the expected message/timestamp

**Plans**: TBD (set at plan-phase)

### Phase 14: GUI

**Goal**: A thin GUI (`rosbagger-gui`, Textual TUI) with five capability-gated panels (record/inspect/query/tf/replay) over the existing module APIs — offline panels always work, live panels light up only when a ROS graph is present.
**Depends on**: Phase 4, Phase 5, Phase 9, Phase 12, Phase 13
**Requirements**: GUI-01
**Success Criteria** (what must be TRUE):

  1. Launches a TUI exposing the five panels over the existing module APIs (no business logic in the GUI)
  2. Capability-gating: live panels (record/replay) disabled without a ROS graph; offline panels (inspect/query/tf) always work
  3. The inspect/query panels drive the real `rosbagger_core` APIs against a fixture bag

**Plans**: TBD (set at plan-phase)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffold & Test Harness | 3/3 | Complete   | 2026-05-22 |
| 2. Bag Reader Layer | 3/3 | Complete    | 2026-05-22 |
| 3. Message→Table Schema | 3/3 | Complete    | 2026-05-22 |
| 4. Inspect | 2/2 | Complete    | 2026-05-22 |
| 5. Query Engine | 2/2 | Complete    | 2026-05-22 |
| 6. Output & Export | 2/2 | Complete    | 2026-05-22 |
| 7. CLI & Teaching Errors | 2/2 | Complete    | 2026-05-22 |
| 8. Packaging, Docs & Release | 1/1 | Complete    | 2026-05-22 |
| 9. TF Debugger | 3/3 | Complete   | 2026-05-22 |
| 10. Query Ergonomics | 4/4 | Complete    | 2026-05-23 |
| 11. Edit & Events | 1/4 | In Progress|  |
| 12. Live Record | 0/? | Not started | - |
| 13. Live Replay | 0/? | Not started | - |
| 14. GUI | 0/? | Not started | - |
