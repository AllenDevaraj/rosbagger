# Phase 11: Edit & Events - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 11 adds two **offline** capabilities to rosbagger, both building on the v1 reader (Phase 2) and query engine (Phase 5):

- **EDIT-01 — Bag editing (bag→bag):** trim / drop / keep / merge / downsample / convert across ROS 1 ↔ ROS 2-sqlite3 ↔ MCAP, via the `rosbags` Writer. Output bags must re-open via `AnyReader`.
- **EVNT-01 — Event sidecar → queryable table:** events `(t_start, t_end, label, …)` stored in a sidecar `<bag>.events.parquet`, exposed by the query engine as a reserved `events` table that is time-JOINable against topic data.

Surface = **thin** `bagq edit` / `bagq convert` / `bagq events {add,list}` verbs over a `rosbagger_core` API (API-first; no business logic in the CLI). Both features stay ROS-free (offline tier).

**In scope:** the five edit operations producing valid re-openable bags; the events sidecar written and read back; the `events` table queryable and interval-JOINable against data by time; thin CLI verbs; no-ROS fixture round-trip tests.

**Out of scope (own phases / deferred):** live "mark event now" (needs `rclpy` → Phases 12–13); GUI timeline markers / jump-points (Phase 14); rate-target (Hz) downsample; event import/export formats (CSV/JSON); multi-bag events; in-place editing (always write a new output). New capabilities belong in their own phase.

</domain>

<decisions>
## Implementation Decisions

> **`--auto` mode:** every decision below is the recommended default, auto-selected without user prompts. Each is grounded in the existing reader/writer/export/query seams and the locked Phase 9 "tf-in-core" precedent.

### Module placement & CLI surface

- **D-01 — Edit + events logic lives in `rosbagger_core`, NOT a separate `rosbagger-edit` package.** e.g. `rosbagger_core/edit/` (operations + pipeline) and `rosbagger_core/events.py` (sidecar I/O). Mirrors the locked Phase 9 decision (TF went in `rosbagger_core/tf.py`, not a separate package, so the existing `--cov=rosbagger_core` gate covers it and the monorepo stays simple). Can split into its own package later if needed.
- **D-02 — Thin CLI verbs over the core API (API-first):** `bagq edit IN... -o OUT [ops]`, `bagq convert IN -o OUT` (format-change convenience that shares the edit pipeline), `bagq events add <bag> ...`, `bagq events list <bag>`. The CLI builds no logic — it parses flags and calls the `rosbagger_core` API (matches the design spec's `bagq edit` / `bagq convert` verbs and the CLI↔GUI parity principle).

### Edit pipeline architecture

- **D-03 — A single streaming pipeline:** `AnyReader` raw stream `(connection, t_ns, rawdata)` → filter/transform → `rosbags` Writer (`add_connection(topic, msgtype, typestore=...)` + `write(conn, t_ns, raw)`). Reuse the writer pattern already proven in `tools/make_fixtures.py` (ROS 1 = `rosbags.rosbag1.Writer`; ROS 2 sqlite3/MCAP = `rosbags.rosbag2.Writer` with `storage_plugin`). The reader already exposes `connections`, `typestore`, and `start_time`.
- **D-04 — Raw-byte copy when serialization matches; deserialize→reserialize only when converting cross-format.** Same-format ops (trim/drop/keep/downsample/merge within one serialization) copy `rawdata` losslessly with no typestore round-trip. Convert ROS 1 ↔ ROS 2 (ros1 ↔ cdr) deserializes via the source typestore and reserializes for the target format (rosbags handles the message-definition translation). This is the key architectural split.
- **D-05 — Never mutate the input; always write a NEW output bag.** Re-register each source connection on the writer from the reader's `connections`/`typestore`; an unresolvable custom msgtype surfaces the Phase 7 teaching error (msg-registration guidance), not a traceback.

### Edit operation semantics (compose in one pass)

- **D-06 — `--trim START END` in seconds RELATIVE to bag start** (ergonomic; uses `reader.start_time`): keep messages whose bag-relative time is in `[START, END]`. (Mirrors how the TF report uses bag-relative `t`.)
- **D-07 — `--drop /topic` and `--keep /topic`, each repeatable and mutually exclusive:** `--drop` excludes the named topics; `--keep` includes only the named topics.
- **D-08 — `--downsample /topic:N` keeps every Nth message of that topic** (deterministic; no time-bucketing). Rate-target (Hz) downsample is deferred. An optional global `--downsample N` may apply to all topics.
- **D-09 — Merge is implicit when multiple input paths are given.** The reader already merges multi-bag streams time-ordered (READ-05); the pipeline writes one output bag in timestamp order.
- **D-10 — Convert = output-format selection** from the `-o` extension (`.bag`/`.mcap`/ROS 2 dir) or an explicit `--format`. `bagq convert` is the dedicated verb for the pure format-change case but shares the `edit` pipeline. All operations compose in a single read→write pass.

### Event sidecar: schema & write path

- **D-11 — Sidecar path `<bag>.events.parquet`, derived deterministically** from the bag path (strip the bag's own extension, append `.events.parquet`; works for a ROS 1 `.bag` file, a ROS 2 directory, and an `.mcap` file).
- **D-12 — Small fixed v1 event schema:** `t_start_ns BIGINT`, `t_end_ns BIGINT`, `label VARCHAR`, `note VARCHAR` (nullable). A point/instant event has `t_start_ns == t_end_ns`. The `_ns` columns line up with the topic tables' `t_ns` so interval joins are natural (a TIMESTAMP_NS rendering of t_start/t_end is acceptable too).
- **D-13 — Write path reuses the existing DuckDB-`COPY` Parquet writer** (`rosbagger_core/output/export.py`). `bagq events add <bag> --start S --end E --label L [--note N]` appends a row (read the existing sidecar → concat the new row → rewrite the whole Parquet; events files are tiny). `bagq events list <bag>` reads it back (satisfies SC2).

### events table & time-join

- **D-14 — `events` is a RESERVED table name in the query engine.** When the SQL references `events`, `query()` discovers `<bag>.events.parquet` next to the (single) bag and registers it as the `events` relation — the design's "another table + a thin write path." v1 is single-bag events; multi-bag events are deferred. (Resolution piggybacks on the existing `backend/resolve.py` `referenced_tables` set.)
- **D-15 — Time-join is a STANDARD SQL interval join — no special operator.** Documented pattern: `SELECT i.* FROM imu i JOIN events e ON i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns`. Because `events` registers like any other DuckDB relation, joins/filters/aggregations work natively (satisfies SC3).

### Claude's Discretion
Exact module layout (`edit/` subpackage vs flat files), function/parameter names, the precise raw-vs-deserialize detection mechanism, and whether `convert` is a distinct verb or `edit --format`. Hard constraints on all: the offline-import invariant (no ROS; heavy imports stay lazy), no-ROS fixture tests (extend `tools/make_fixtures.py` for edit round-trips), the ≥80% coverage gate, and the trusted-input boundary (the output path is the one SQL-literal surface — reuse `output/export.py`'s quote-escape).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` § "Phase 11: Edit & Events" — goal + the three success criteria (valid re-openable bags from trim/drop/merge/downsample/convert; sidecar written+read back; `events` table queryable + time-JOINable).
- `.planning/REQUIREMENTS.md` § "Edit / Events" — EDIT-01 (trim/drop/merge/downsample/convert) and EVNT-01 (event sidecar → queryable `events` table).
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §5.5 (`rosbagger-edit` — offline bag→bag verbs `bagq edit`/`bagq convert`) and §6 (annotations/events — `<bag>.events.parquet`, exposed as a `events` table, JOINable by time; "another table + a thin write path").

### Code seams to extend (read before planning)
- `tools/make_fixtures.py` — the proven `rosbags` Writer pattern (ROS 1 `rosbags.rosbag1.Writer`; ROS 2 `rosbags.rosbag2.Writer` + `storage_plugin`; `add_connection`/`write`/`serialize_*`). The edit-write path mirrors this; extend it for edit round-trip fixtures.
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` + `reader/base.py` — the `BagReader`/`AnyReader` adapter: raw `(connection, t_ns, rawdata)` stream, `connections`, `typestore`, `start_time`/`end_time`. The edit pipeline's source.
- `packages/rosbagger-core/src/rosbagger_core/output/export.py` — `write_table(table, path)` (Parquet via DuckDB `COPY`, with the path quote-escape). Reused to write/read the events sidecar.
- `packages/rosbagger-core/src/rosbagger_core/backend/query.py` + `backend/resolve.py` — the query orchestrator + `referenced_tables` resolver. The `events` table hooks in here (reserved name → discover sidecar → register relation).
- `packages/rosbagger-core/src/rosbagger_core/errors.py` — the Phase 7 teaching-error pattern (unresolvable msgtype → registration guidance), reused on the edit-write boundary.
- `packages/bagq/src/bagq/cli.py` — the thin CLI; add `edit` / `convert` / `events` verbs in the existing typer/rich idiom.

### Offline / test constraints (hard)
- `packages/rosbagger-core/tests/test_offline_guard.py` (repo-root `tests/test_offline_guard.py`) — the offline-import invariant: new modules must not eagerly import the heavy stack; `import rosbagger_core` stays light. Extend the guard for the new modules.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Writer pattern** (`tools/make_fixtures.py`): ROS 1 vs ROS 2 `Writer`, `add_connection(topic, msgtype, typestore=...)`, `write(conn, t_ns, raw)`, `serialize_ros1`/`serialize_cdr`, `StoragePlugin.SQLITE3`/MCAP. Directly reusable for the edit-write path.
- **Reader raw stream** (`reader/rosbags_reader.py`): wraps `AnyReader` whose native tuples are `(connection, t_ns, rawdata)` — the lossless raw-copy source for same-format edits; exposes `connections`/`typestore`/`start_time` for re-registration and relative trim.
- **Parquet writer** (`output/export.py` `write_table`): DuckDB `COPY` to `.parquet`/`.csv` with a safe path quote-escape — reused verbatim for the `<bag>.events.parquet` sidecar.
- **Query orchestrator + resolver** (`backend/query.py`, `backend/resolve.py`): one-table-per-topic registration keyed on `referenced_tables`; the `events` table is a parallel registration when that reserved name appears.
- **Teaching errors** (`errors.py`, Phase 7): `UnresolvedTypeError` / did-you-mean — reused at the edit-write boundary for unregistered custom msgs.

### Established Patterns
- **Offline-import invariant:** module tops stay stdlib-light; duckdb/pyarrow imported lazily inside functions (mirror `backend/query.py`, `output/export.py`). New edit/events modules follow suit and extend `test_offline_guard.py`.
- **API-first / thin CLI:** all logic in the `rosbagger_core` API; `bagq` verbs are presentation only (CLI↔GUI parity).
- **No-ROS fixtures:** all tests use `rosbags`-written fixture bags (ROS 1 + ROS 2-sqlite3 + MCAP); edit round-trips assert re-open via `AnyReader` with no ROS install. Local runs need `PYTHONPATH=""`.
- **tf-in-core precedent (Phase 9):** new offline capability goes in `rosbagger_core`, surfaced via a thin `bagq` subcommand — same shape here.

### Integration Points
- Edit: new `rosbagger_core/edit/` API consumed by thin `bagq edit`/`bagq convert`; source = reader's raw `AnyReader` stream; sink = `rosbags` Writer chosen by output format.
- Events write: `rosbagger_core/events.py` add/list over `<bag>.events.parquet` using `output/export.py`.
- Events query: `query()` detects the reserved `events` table (via `resolve.referenced_tables`), loads the sidecar, registers it; standard interval join against topic tables on `t_ns`.

</code_context>

<specifics>
## Specific Ideas

- SC1 acceptance: every edit output must re-open via `rosbags` `AnyReader` (the project's universal-read contract) — assert this directly in fixture round-trip tests across all three formats.
- Canonical events sidecar: `<bag>.events.parquet`; canonical time-join: `... FROM imu i JOIN events e ON i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns`.
- Convert is the cross-format case that forces deserialize→reserialize; trim/drop/downsample/merge within one format should stay raw-copy (lossless, fast).

</specifics>

<deferred>
## Deferred Ideas

- **Live "mark event now"** (append to the sidecar from a running ROS graph) — needs `rclpy`; belongs with live record/replay (Phases 12–13).
- **GUI timeline markers / jump-points** for events — Phase 14 (GUI).
- **Rate-target (Hz) downsample** and time-bucketed resampling — v1 ships deterministic every-Nth only.
- **Event import/export** (CSV/JSON ingest, bulk annotation from a query result) — v1 ships `events add`/`list` only.
- **Multi-bag events** (which sidecar when several bags are queried) — v1 is single-bag.
- **In-place editing** — always rejected; edits always write a new output bag.

</deferred>

---

*Phase: 11-edit-events*
*Context gathered: 2026-05-23*
