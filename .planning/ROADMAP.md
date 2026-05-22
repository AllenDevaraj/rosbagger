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
- [ ] **Phase 5: Query Engine** - DuckDB backend + sqlglot topic resolution
- [ ] **Phase 6: Output & Export** - stdout table, CSV, Parquet, minimal plot
- [ ] **Phase 7: CLI & Teaching Errors** - `bagq query` end-to-end with helpful errors
- [ ] **Phase 8: Packaging, Docs & Release** - pip-installable v0.1, offline imports

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

- [ ] 05-01: `QueryBackend` seam + DuckDB backend (load tables → run SQL → Arrow)
- [ ] 05-02: sqlglot topic resolution (load only referenced topics)

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

- [ ] 06-01: stdout table + CSV/Parquet export
- [ ] 06-02: minimal `--plot`

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

- [ ] 07-01: `bagq` CLI wiring (typer) for query/info/tables
- [ ] 07-02: Teaching errors (unknown table/column/custom-msg)

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

- [ ] 08-01: Packaging polish, README/usage, offline-import check, v0.1

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffold & Test Harness | 3/3 | Complete   | 2026-05-22 |
| 2. Bag Reader Layer | 3/3 | Complete    | 2026-05-22 |
| 3. Message→Table Schema | 3/3 | Complete    | 2026-05-22 |
| 4. Inspect | 2/2 | Complete   | 2026-05-22 |
| 5. Query Engine | 0/2 | Not started | - |
| 6. Output & Export | 0/2 | Not started | - |
| 7. CLI & Teaching Errors | 0/2 | Not started | - |
| 8. Packaging, Docs & Release | 0/1 | Not started | - |
