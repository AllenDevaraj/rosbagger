# Roadmap: rosbagger

## Overview

rosbagger v1 builds the offline core and the `bagq` CLI in technical layers: scaffold → reader → schema mapping → inspect → query engine → output → CLI → packaging. Each layer is independently testable with **no ROS install** (tests use `rosbags`-written fixture bags), and they assemble into a SQL-over-bags tool that reads ROS 1 / ROS 2 / MCAP and exports CSV / Parquet / plots.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Scaffold & Test Harness** - Monorepo, packaging, and no-ROS fixture bags (completed 2018-05-22)
- [x] **Phase 2: Bag Reader Layer** - Universal ROS1/ROS2/MCAP reading via rosbags (completed 2018-05-22)
- [x] **Phase 3: Message→Table Schema** - Flatten messages into DuckDB columns (completed 2018-05-22)
- [x] **Phase 4: Inspect** - `bagq info` / `bagq tables` (completed 2018-05-22)
- [x] **Phase 5: Query Engine** - DuckDB backend + sqlglot topic resolution (completed 2018-05-22)
- [x] **Phase 6: Output & Export** - stdout table, CSV, Parquet, minimal plot
- [x] **Phase 7: CLI & Teaching Errors** - `bagq query` end-to-end with helpful errors (completed 2018-05-22)
- [x] **Phase 8: Packaging, Docs & Release** - pip-installable v0.1, offline imports (completed 2018-05-22)

### Milestone v0.2 — Modular cockpit (TF · ergonomics · edit · live · GUI · release)

- [x] **Phase 9: TF Debugger** - offline `/tf` dropout/timeline report (`bagq tf` subcommand) (completed 2018-05-22)
- [x] **Phase 10: Query Ergonomics** - alias pack + column projection pushdown (completed 2018-05-23)
- [x] **Phase 11: Edit & Events** - trim/drop/merge/convert + queryable events sidecar (completed 2018-05-23)
- [x] **Phase 12: Live Record** - live topic discovery + select recording (rclpy) (completed 2018-05-23)
- [x] **Phase 13: Live Replay** - replay a bag to ROS topics with transport controls (rclpy) (completed 2018-05-23)
- [x] **Phase 14: GUI** - capability-gated panels over module APIs (Textual TUI) (completed 2018-05-24)
- [x] **Phase 15: Packaging & Release v0.2** - git/path-installable packages + coherent v0.2.0 versions + per-package install docs (no index publish) (completed 2018-05-25)

### Milestone v0.3 — Desktop cockpit

- [x] **Phase 16: Native Desktop GUI (PySide6)** - native Qt desktop window with full parity to the TUI's five panels, as an isolated new `rosbagger-desktop` package (TUI untouched) (completed 2018-05-25)

### Milestone v0.4 — Desktop revamp

- [ ] **Phase 17: Desktop Revamp** - turn the functional-but-unstyled Qt window into a designed cockpit: a QSS design-token theme with dark+light + runtime toggle, and the query panel's robustness patterns (off-thread work, model/view, accessible status) brought to all five panels

### Milestone v0.5 — Replay Playback System

Turn replay from a fire-and-forget publisher into a real playback system: a live-tracking, drag-while-playing scrubber, snippet (in/out) looping, RViz-faithful seeking (`/clock` + static re-publish), and `ros2 bag play` CLI parity. All work stays behind the established invariants — `rosbagger_replay` ROS-free at module top, the offline import graph ROS-free AND Qt-free, and the desktop panels thin faces over the library.

- [x] **Phase 18: Replay live scrubbing & thread-safe transport** - make the pure `Replayer` safe to control mid-play (thread-safe command channel) so the scrubber drags live and the playhead tracks in real time (completed 2026-05-29)
- [x] **Phase 19: Replay snippet loop & advanced controls panel** - in/out region loop in the scheduler + dual-handle/Set-In-Out Scrubber, housed in a collapsible side sub-panel inside the Replay tab (completed 2026-05-29)
- [ ] **Phase 20: Replay RViz fidelity (clock + static republish)** - publish `/clock` for `use_sim_time` and re-emit latched/`transient_local` + `/tf_static` after a seek so RViz re-primes instead of layering stale state
- [ ] **Phase 21: Replay CLI parity flags** - close the `ros2 bag play` gap feasible in our publish model: `--start-paused`, `--remap`, `--delay`, `--clock`, bounded region `[in,out]`

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
- [x] 11-03-PLAN.md — Events sidecar I/O (`rosbagger_core/events.py`): file-vs-dir-aware `sidecar_path` + `add_event`/`list_events` over `<bag>.events.parquet` (fixed v1 schema), reusing the locked DuckDB-COPY writer; SC2 write/read/append tests -> EVNT-01

**Wave 2** *(blocked on 11-01)*

- [x] 11-02-PLAN.md — Cross-format convert via the `rosbags` converter factory (`is_same_wireformat`/`generate_message_converter`, no hand-rolled migration) wired into `edit_bag` + thin `bagq edit`/`bagq convert` verbs; convert round-trip (deserialize headered msgs) tests both directions -> EDIT-01

**Wave 3** *(blocked on 11-02 + 11-03)*

- [x] 11-04-PLAN.md — Reserved `events`-table hook in `query()` (subtract from topic resolution, register sidecar relation, native `BETWEEN` interval join — SC3) + thin `bagq events add`/`list` verbs (SC2 at the CLI) + events offline-guard extension -> EVNT-01

### Phase 12: Live Record

**Goal**: A live recorder (`rosbagger-record`) — discover live ROS topics and record a selected subset to a bag. Requires `rclpy` (present on host); the offline modules stay ROS-free.
**Depends on**: Phase 2
**Requirements**: REC-01
**Success Criteria** (what must be TRUE):

  1. Discovers currently-published live topics
  2. Records a selected subset to a bag while a publisher is running
  3. The recorded bag re-opens and iterates via the v1 reader

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 12-01-PLAN.md — `rosbagger-record` package scaffold + lazy ROS boundary (D-01/D-03), teaching capability errors, pure-Python topic discovery + subset selection (D-06/D-07), mocked unit tests, offline-guard extension (D-11) + `live` marker -> REC-01

**Wave 2** *(blocked on 12-01)*

- [x] 12-02-PLAN.md — rclpy + rosbag2_py record core: discover→select→`create_subscription(raw=True)`→`SequentialWriter`→bounded/SIGINT stop→finalize (D-04/D-05/D-09); MCAP-preferred-default storage gate + `--storage sqlite3` escape (D-08 refined); mocked unit tests for the gate/stop-loop/finalize-on-error -> REC-01

**Wave 3** *(blocked on 12-02)*

- [x] 12-03-PLAN.md — thin `rosbagger-record` CLI (`list` + record verb, D-02/D-07/D-08/D-09) + LIVE integration test (publisher→bounded record→re-open via v1 reader, SC1/SC2/SC3) gated by `importorskip`+`live`, proven via sqlite3, MCAP assertion skipif-guarded; phase gate (offline suite + ruff + offline guard + live lane) -> REC-01

### Phase 13: Live Replay

**Goal**: A live replayer (`rosbagger-replay`) — publish a bag's messages to real ROS topics with transport controls (play/pause/step/seek/rate/loop). Requires `rclpy`.
**Depends on**: Phase 2
**Requirements**: REP-01
**Success Criteria** (what must be TRUE):

  1. Replays a bag, publishing real ROS topics a subscriber receives
  2. Transport controls work: play/pause/step/seek/rate/loop
  3. Rate scaling and seek land at the expected message/timestamp

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 13-01-PLAN.md — `rosbagger-replay` package scaffold (uv member, console script, no ROS deps; D-01/D-03) + teaching capability errors + the PURE raw-CDR source seam (`source.py`: v1 `AnyReader` raw bytes + ROS1→CDR bridge, D-05) with source unit tests over real fixtures -> REP-01

**Wave 2** *(blocked on 13-01)*

- [x] 13-02-PLAN.md — the PURE `Replayer` transport scheduler (`scheduler.py`: play/pause/step/seek/rate/loop state machine + monotonic pacing + bounded stop, ROS-free; D-06..D-09) + SC2/SC3 unit tests (fake clock + recording sink) -> REP-01

**Wave 3** *(blocked on 13-01 + 13-02)*

- [x] 13-03-PLAN.md — lazy ROS boundary (`__init__.py`) + the rclpy publish SINK (`replay.py`: `get_message`+`deserialize_message`+`create_publisher().publish`, D-04) + thin `rosbagger-replay` CLI (D-02/D-10) + offline-guard extension + the LIVE SC1 integration test (subscriber receives, actually run in the ROS-sourced lane; D-11/D-12) -> REP-01

### Phase 14: GUI

**Goal**: A thin GUI (`rosbagger-gui`, Textual TUI) with five capability-gated panels (record/inspect/query/tf/replay) over the existing module APIs — offline panels always work, live panels light up only when a ROS graph is present.
**Depends on**: Phase 4, Phase 5, Phase 9, Phase 12, Phase 13
**Requirements**: GUI-01
**Success Criteria** (what must be TRUE):

  1. Launches a TUI exposing the five panels over the existing module APIs (no business logic in the GUI)
  2. Capability-gating: live panels (record/replay) disabled without a ROS graph; offline panels (inspect/query/tf) always work
  3. The inspect/query panels drive the real `rosbagger_core` APIs against a fixture bag

**Plans**: 7 plans

Plans:
**Wave 1**

- [x] 14-01-PLAN.md — D-09a: refactor the rclpy publish sink out of `replay.py` into one reusable `build_publish_sink` (single production publish path) + Phase-13 replay regression check -> GUI-01
- [x] 14-02-PLAN.md — `rosbagger-gui` workspace member + Textual App shell (sidebar ListView + ContentSwitcher, D-01), shared open-reader lifecycle (D-02), tier-1 ROS gate + disabled-live panels (D-03/D-04), five panel stubs, console script, dev async plugin -> GUI-01

**Wave 2** *(blocked on 14-02)*

- [x] 14-03-PLAN.md — Inspect panel over `collect_bag_info`/`collect_table_schemas` (D-05) + TF panel over `collect_tf_report` (D-07), thin DataTable renderers -> GUI-01
- [x] 14-04-PLAN.md — Query panel (D-06): SQL input + results DataTable over `query()`, schema/topic Tree click-to-insert, history/re-run, CSV/Parquet export over `write_table` -> GUI-01

**Wave 3** *(blocked on 14-02; 14-06 also on 14-01)*

- [x] 14-05-PLAN.md — Record panel (live, D-04/D-08): tier-2 `discover_topics` scan → topic checklist + start/stop `record()`, all in `@work(thread=True)` workers -> GUI-01
- [x] 14-06-PLAN.md — Replay panel (live, D-09): six transport controls over the pure `Replayer` + the shared `build_publish_sink`, custom scrubber Widget seeking via `Replayer.seek()`, jump-to-event markers from `list_events`, thread worker -> GUI-01

**Wave 4** *(blocked on 14-02..14-06)*

- [x] 14-07-PLAN.md — SC1/SC2/SC3 headless `App.run_test()`/Pilot tests against a fixture bag, `test_import_gui_does_not_pull_ros` offline-guard extension, live-marked record/replay lane, phase gate -> GUI-01

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffold & Test Harness | 3/3 | Complete   | 2018-05-22 |
| 2. Bag Reader Layer | 3/3 | Complete    | 2018-05-22 |
| 3. Message→Table Schema | 3/3 | Complete    | 2018-05-22 |
| 4. Inspect | 2/2 | Complete    | 2018-05-22 |
| 5. Query Engine | 2/2 | Complete    | 2018-05-22 |
| 6. Output & Export | 2/2 | Complete    | 2018-05-22 |
| 7. CLI & Teaching Errors | 2/2 | Complete    | 2018-05-22 |
| 8. Packaging, Docs & Release | 1/1 | Complete    | 2018-05-22 |
| 9. TF Debugger | 3/3 | Complete   | 2018-05-22 |
| 10. Query Ergonomics | 4/4 | Complete    | 2018-05-23 |
| 11. Edit & Events | 4/4 | Complete    | 2018-05-23 |
| 12. Live Record | 3/3 | Complete    | 2018-05-23 |
| 13. Live Replay | 3/3 | Complete    | 2018-05-23 |
| 14. GUI | 7/7 | Complete    | 2018-05-24 |

### Phase 15: Packaging & Release v0.2

**Goal**: Make the v0.2 packages installable into OTHER repos via git+subdirectory and path dependencies — **no PyPI / index publish** (decision: git/path install only). Today the inter-package deps (bare names like `rosbagger-core`) only resolve through the monorepo root `[tool.uv.sources] workspace = true`; outside the repo they don't resolve, so a consuming project can't install them. This phase closes that gap and ships coherent v0.2.0 versions with per-package install docs — the v0.2 equivalent of Phase 8's v0.1 release work, covering the four packages Phase 8 didn't (`rosbagger-record`, `rosbagger-replay`, `rosbagger-gui`, plus a `bagq`/`rosbagger-core` version bump).
**Depends on**: Phase 14
**Requirements**: (Definition of Done — git/path-installable packages, coherent versioning, install docs; infrastructure phase like Phase 8, no new REQ-ID)
**Success Criteria** (what must be TRUE):

  1. Each distributable package builds a wheel via `uv build` (core, bagq, record, replay, gui)
  2. A fresh EXTERNAL venv installs the packages from git+subdirectory / path specs with `rosbagger-core` resolving by spec (not the workspace source) — proven by `rosbagger-gui --help` + `import rosbagger_gui` working outside the monorepo
  3. Per-package install + usage docs exist (git+subdirectory and `[tool.uv.sources]` git/path snippets), including that the GUI's live record/replay panels need `rosbagger-record` / `rosbagger-replay` installed alongside (lazy-imported, not declared deps; consider a `gui` extra)
  4. Versions are coherent at v0.2.0 across all packages (+ re-locked `uv.lock`)
  5. Offline-import invariant + ROS-free core intact; full offline test suite + offline guard still green

**Plans:** 3/3 plans complete

Plans:
**Wave 1**

- [x] 15-01-PLAN.md — Bump all 10 version sites to 0.2.0 + pin sibling deps `>=0.2,<0.3` + add the `rosbagger-gui` `live` extra + re-lock `uv.lock` (D-01/D-02/D-03) -> SC4

**Wave 2** *(blocked on 15-01)*

- [x] 15-02-PLAN.md — Committed `scripts/proof_external_install.sh` (fresh-venv path-install proof) + central `INSTALL.md` (meta/per-package git+subdirectory + path + consumer-source recipes, live note, awaits-push git recipe; D-04) -> SC2/SC3

**Wave 3** *(blocked on 15-01 + 15-02)*

- [x] 15-03-PLAN.md — Release gate (`uv build --all-packages` + `uv sync --locked` + ruff + offline pytest/guard + proof script) + local annotated `v0.2.0` tag; push/git-recipe = sole human follow-up -> SC1/SC2/SC5

### Phase 16: Native Desktop GUI (PySide6)

**Goal:** Ship a native desktop GUI as a new isolated workspace package `rosbagger-desktop` (PySide6/Qt). Running `rosbagger-desktop [BAG]` spawns a real OS window with full parity to the Textual TUI's five panels (inspect/query/tf/record/replay), each a thin face calling the existing `rosbagger_core`/`rosbagger_record`/`rosbagger_replay` APIs verbatim — no new analysis logic. Hard constraint: do not modify or regress anything that already exists — the TUI (`rosbagger-gui`) is untouched, PySide6 is isolated to the new package, and the offline import graph stays both ROS-free AND Qt-free (offline guard extended). Phased internally: offline parity (inspect/query/tf) first, then live parity (record/replay). Full design: `docs/superpowers/specs/2018-05-25-rosbagger-desktop-gui-design.md`.
**Requirements**: (new milestone v0.3 — DoD: native window launches, five panels reach feature parity with the TUI reusing module APIs, package fully isolated, offline+Qt-free guard green, headless pytest-qt tests pass at ≥80%)
**Depends on:** Phase 15
**Plans:** 3/3 plans complete

Plans:
**Wave 1**
- [x] 16-01-PLAN.md — Package skeleton + manifest + root deps/config + re-lock uv.lock + cli (argparse front door) + capabilities (rclpy probe) + QMainWindow shell with Inspect/TF panels + Qt-free offline guard + headless SC1/SC3 tests -> SC1/SC3/SC4/SC5

**Wave 2** *(blocked on 16-01)*
- [x] 16-02-PLAN.md — Query panel (thin face over query() + collect_table_schemas tree + write_table export + teaching errors), registered as an offline panel + headless SC2/SC3 query test -> SC2/SC3/SC5

**Wave 3** *(blocked on 16-02)*
- [x] 16-03-PLAN.md — Increment B live parity: workers.py (QThread/QObject scaffolding) + Qt Scrubber + Record/Replay panels (over rosbagger_record/rosbagger_replay + build_publish_sink + list_events) capability-gated in the shell + five-panel/gate headless tests + @pytest.mark.live record/replay lane + phase gate -> SC2/SC4/SC5

### Phase 17: Desktop Revamp

**Goal:** Transform `rosbagger-desktop` from a functional-but-unstyled default-Qt window into an intentionally designed cockpit — WITHOUT regressing the Phase-16 isolation invariant (PySide6 confined to the package; offline import graph ROS-free AND Qt-free) or the thin-face rule (panels stay pure faces over the module APIs; zero analysis/bag/SQL/ROS logic added). Two halves:

1. **Visual design system** — a centralized QSS theme driven by design tokens (color / spacing / type scale / elevation), applied consistently across the shell + all five panels. Ship a **dark and a light** theme with a runtime toggle (persisted). Replace ad-hoc/no styling with deliberate visual hierarchy, spacing rhythm, and intentional empty/loading/error states. No per-widget inline color; styling lives in the theme layer (the query panel's error-style precedent, generalized).

2. **Cross-panel engineering parity** — bring every panel up to the query panel's robustness bar (quick tasks 260525-is6 / -kj0): long-running work runs off the UI thread on `BlockingWorker`; tabular data uses model/view (`QAbstractTableModel`/`QTableView`) not per-cell widgets; status/error surfaces are accessible live regions (with the offscreen-`QAccessible` guard). Audit inspect / tf / record / replay against these and fix the gaps.

**Requirements** (DoD — to be validated/refined in planning): theme toggle flips dark↔light live and persists across launches; tokens are the single source of styling (no scattered inline QSS/colors); all five panels read from the theme; the four non-query panels have no UI-thread block on their heavy paths and use model/view where they render tables; status surfaces are accessible; isolation invariant + offline/Qt-free guard stay green; headless pytest-qt suite passes at ≥80%; visuals sanity-checked on a real X11 window (offscreen can't prove appearance).

**Depends on:** Phase 16 (the desktop package + thin-face/isolation invariants), quick tasks 260525-is6 + 260525-kj0 (the query-panel patterns this phase generalizes).
**Plans:** 3 plans

**Open scoping notes for planning (`/gsd-plan-phase 17` / `/gsd-discuss-phase 17`):**
- Theme palettes: locked direction is "I choose per usage" (robotics engineer reading bag data at a desk → a calm, focused default); planning should pin actual OKLCH-derived token values for both themes and force a concrete scene per the "theme is never a default" rule.
- Whether a visual prototype precedes implementation (de-risks the both-themes design system) — recommended as plan 1.
- Token/theme mechanism: QSS variables aren't native; decide on a token→QSS approach (e.g. a Python token module that templates the stylesheet, or `qt-material`-style generation) — must stay inside the package, no new heavy deps leaking into the offline graph.

Plans:
- [ ] 17-01-PLAN.md — Theme infrastructure: tokens (DARK+LIGHT) → build_qss → ThemeManager; QSettings identity + live View-menu toggle
- [ ] 17-02-PLAN.md — Shared table models + inspect/tf parity: lift _ResultTableModel, add RowsTableModel + accessible status helper, move inspect/tf to QTableView + BlockingWorker
- [ ] 17-03-PLAN.md — Visual rollout across all five panels: token-driven theming, no inline color, record/replay accessible status, edge states, real-window sanity check

### Phase 18: Replay live scrubbing and thread-safe transport

**Goal:** Make the pure `Replayer` safe to control *while it is playing*, so the desktop scrubber drags live and the playhead tracks in real time — the foundation for a true playback system. Today the panel hard-blocks seek/rate/loop mid-play (`_drive_running()` → "Pause before seeking") because the `Replayer` is a deliberately non-thread-safe state machine driven on a QThread worker (CR-02: `run()` reads/writes `_cursor`/`_state`/`_rate`/`loop`). This phase adds a **thread-safe command channel** (a queue/lock applied between publishes inside `run()`) so seek / set_rate / loop / pause land without a data race, plus a **periodic position signal** so the scrubber playhead moves smoothly during playback (not only at DONE). Hard truth carried into the UX: a backward drag is a *jump-to-earlier-time + forward replay*, not a visual rewind — RViz only reflects forward republish — so the status line communicates "seeking… resuming forward" rather than implying reverse playback. Invariants: `rosbagger_replay` stays ROS-free at module top, the offline import graph stays ROS-free AND Qt-free, the desktop Replay panel stays a thin face, and every existing replay test stays green.
**Requirements**: REP-02 (live scrubbing / thread-safe transport)
**Depends on:** Phase 13 (the `Replayer` + `build_publish_sink`), Phase 16/17 (the desktop Replay panel + `Scrubber` + `BlockingWorker` + theming)
**Success Criteria** (what must be TRUE):

  1. The `Replayer` accepts transport commands (seek / set_rate / loop / pause) while `run()` executes on another thread with NO data race — proven by a threaded unit test (fake clock + recording sink) that seeks mid-run and observes the cursor jump
  2. In the desktop Replay panel, dragging the scrubber while playing seeks live (no "Pause before seeking" rejection) and the playhead advances in real time during playback — proven by a headless pytest-qt test
  3. A backward drag jumps to the earlier timestamp and resumes forward publishing, with a status line that communicates the jump (no claim of reverse playback)
  4. Offline/Qt-free guard green; `import rosbagger_replay` stays ROS-free; full headless suite passes at ≥80%

**Plans:** 2/2 plans complete

Plans:
**Wave 1**
- [x] 18-01-PLAN.md — Scheduler thread-safety (pure, ROS/Qt-free): threading.Lock + Event wake + interruptible default sleep + lock-guarded synchronous setters + run() critical-section restructure with the cursor-unchanged advance guard; threaded race unit test + full Phase-13 regression -> SC1

**Wave 2** *(blocked on 18-01)*
- [x] 18-02-PLAN.md — Desktop live-scrub wiring (thin face): QTimer live playhead + remove the three mid-play guard branches + keep rate/loop enabled mid-play + backward-seek "resuming forward" status; headless pytest-qt tests + offline/Qt-free guard + phase gate -> SC2/SC3/SC4

### Phase 19: Replay snippet loop and advanced controls panel

**Goal:** Let the user loop a sub-region of the bag on repeat, and house the growing replay controls in a dedicated collapsible side sub-panel inside the Replay tab. Adds an **in/out region loop** `[t_in, t_out]` to the `Replayer` — distinct from the existing whole-bag `loop` (which rewinds to index 0): when region-loop is on, playback wraps from `t_out` back to `t_in`. The region is markable BOTH ways the user asked for: dragging **two In/Out handles** on the `Scrubber` AND **Set-In / Set-Out buttons** that snap to the current playhead. The `Scrubber` paints the shaded loop region + two draggable handles (extending its current playhead+markers paint), and a **collapsible side sub-panel** ("the tab on the side") collects the advanced controls (region loop, rate, and the Phase-20 clock/topic toggles) so the main strip stays clean. Builds on Phase 18's thread-safe transport so the region can be set/changed while playing. Thin-face + offline/Qt-free invariants hold; styling uses the Phase-17 theme tokens (no inline color).
**Requirements**: REP-03 (snippet/region loop + advanced controls panel)
**Depends on:** Phase 18 (thread-safe live transport), Phase 17 (theme tokens + accessible status patterns)
**Success Criteria** (what must be TRUE):

  1. `Replayer` supports a loop region: playing wraps from `t_out` back to `t_in` (not index 0) when region-loop is on, and clears cleanly back to whole-bag / no-loop — proven by unit tests (fake clock + recording sink)
  2. The `Scrubber` shows a shaded loop region with two draggable In/Out handles, AND Set-In / Set-Out buttons set the region from the current playhead — a headless pytest-qt test drives both paths and asserts the resulting region
  3. Advanced replay controls live in a collapsible side sub-panel inside the Replay tab (region loop + rate), themed via Phase-17 tokens with accessible status preserved
  4. Region values survive pause/seek/play cycles; offline/Qt-free guard green; full headless suite passes at ≥80%

**Plans:** 3/3 plans complete

Plans:
- [x] 19-01-PLAN.md — Scheduler region loop (pure, ROS/Qt-free) — set_loop_region/clear_loop_region + run() region-wrap branch [wave 1]
- [x] 19-02-PLAN.md — Scrubber dual In/Out handles + shaded region paint + region_fill/region_handle theme tokens [wave 1]
- [x] 19-03-PLAN.md — Panel collapsible advanced sub-panel + Set-In/Out + wiring (survives pause/seek/play) [wave 2, depends 19-01+19-02]

### Phase 20: Replay RViz fidelity (clock + static republish)

**Goal:** Make replay "look right" in RViz across seeks/scrubs. Two mechanisms, both opt-in: (a) **publish `/clock`** (`rosgraph_msgs/Clock` at a configurable Hz, derived from the cursor item's `t_ns`) so downstream `use_sim_time` nodes track bag time instead of wall-clock; and (b) **re-publish latched / `transient_local` topics (and `/tf_static`) after a seek** so a fresh scene re-primes instead of RViz layering stale geometry over new — the concrete fix for the "backward scrub looks wrong" limitation surfaced in Phase 18. Implemented in the publish path (`build_publish_sink` / a small clock + static-tracking layer), surfaced as toggles in the Phase-19 side sub-panel and as CLI flags (wired in Phase 21). Lazy ROS imports only — the offline import graph stays ROS-free; defaults preserve today's behavior (clock off, no forced re-publish).
**Requirements**: REP-04 (RViz fidelity — clock + static re-publish)
**Depends on:** Phase 18 (seek mechanics), Phase 19 (side sub-panel to host the toggles)
**Success Criteria** (what must be TRUE):

  1. With clock publishing enabled, `/clock` is published at the configured rate carrying bag-relative time during replay — proven by a live (`-m live`) test subscribing to `/clock`
  2. After a seek, latched / `transient_local` topics (and `/tf_static`) seen before the seek point are re-published so a fresh subscriber re-primes — proven by a live test, or a unit test over the publish sink's static-tracking
  3. Both behaviors are opt-in via the side sub-panel + matching CLI flags; defaults are unchanged (clock off)
  4. Offline/Qt-free guard green; `import rosbagger_replay` stays ROS-free; full headless suite passes at ≥80%

**Plans:** 3 plans

Plans:
**Wave 1**

- [ ] 20-01-PLAN.md — Pure fidelity logic: `StaticTracker` (latest-per-static-topic, default `/tf_static`) + `clock_stamp_ns` time-split in a new stdlib-only `fidelity.py`, re-exported ROS-free -> SC2 (unit route), SC4

**Wave 2** *(blocked on 20-01)*

- [ ] 20-02-PLAN.md — Live publish wiring: opt-in `publish_clock` + `static_topics` on `build_publish_sink` (lazy ROS, defaults off, back-compatible 2-tuple) + `republish_static` helper + `-m live` test -> SC1, SC2 (live), SC3 (library half)

**Wave 3** *(blocked on 20-01 + 20-02)*

- [ ] 20-03-PLAN.md — Desktop toggles: 'Publish /clock' + 'Re-publish static on seek' QCheckBoxes in the Phase-19 Advanced sub-panel, threaded into `build_publish_sink` + republish-after-seek (thin face) -> SC3 (UI half), SC4

### Phase 21: Replay CLI parity flags

**Goal:** Close the `ros2 bag play` flag gap on the `rosbagger-replay` CLI for the flags that are feasible in our custom publish model (confirmed against Humble's `ros2 bag play --help`): `--start-paused`, `--remap old:=new`, `--delay`, `--clock [Hz]` (wiring Phase-20's publisher), and a **bounded region** `--region-start` / `--region-end` (mapping to the scheduler's in/out region + bound). The CLI stays a thin front door over the library — each flag maps to an existing `Replayer` / `replay()` argument with no second publish path — and teaching errors are preserved. Runtime ROS *services* (`~/seek`, `~/set_rate`, `~/play_next`, `~/burst`) remain deferred: they require a long-lived spinning node, and the GUI already provides interactive control; this is documented as out-of-scope, not silently dropped.
**Requirements**: REP-05 (CLI parity flags)
**Depends on:** Phase 18 (region/seek mechanics), Phase 20 (`/clock` publisher for `--clock`)
**Success Criteria** (what must be TRUE):

  1. `rosbagger-replay --help` exposes `--start-paused`, `--remap`, `--delay`, `--clock`, and bounded-region options; each maps to the library with no new publish path
  2. `--remap` publishes on the remapped topic name; `--start-paused` begins paused; `--delay` sleeps before play; the bounded region plays only `[in,out]` — proven by tests (live where publishing is required, unit where the mapping suffices)
  3. Deferred runtime-service controls are documented as out-of-scope (not silently missing)
  4. Offline/Qt-free guard green; CLI stays thin; full headless suite passes at ≥80%

**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd-plan-phase 21 to break down)
