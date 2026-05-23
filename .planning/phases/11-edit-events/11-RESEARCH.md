# Phase 11: Edit & Events - Research

**Researched:** 2026-05-23
**Domain:** Offline ROS-bag editing (bag→bag via the `rosbags` Writer) + an event sidecar exposed as a queryable, time-joinable `events` table
**Confidence:** HIGH (every cross-format claim verified against the installed `rosbags` 0.11.2 with the project's own fixtures)

## Summary

Phase 11 has two halves that share almost nothing except the offline invariant. The **edit** half is a streaming `AnyReader → rosbags Writer` pipeline; the **events** half is a tiny Parquet sidecar plus a one-name hook into the existing query orchestrator. Both are well within the seams the project already built (Phases 2/5/6/7), and the locked decisions (D-01..D-15) map cleanly onto verified `rosbags` behavior.

The single most valuable finding: **`rosbags` ships its own production converter, `rosbags.convert.convert(...)`, and a per-message converter factory (`rosbags.convert.converter.generate_message_converter`) that already solve every hard cross-format problem** — the ROS1 `Header.seq` field that ROS2 dropped, message-definition generation for the target ROS version, the per-msgtype raw-copy-vs-migrate decision (`is_same_wireformat`), legacy type renames (`tf/msg/tfMessage` → `tf2_msgs/msg/TFMessage`), and storage selection (`dst.suffix != '.bag'`). I verified by direct experiment that a naive deserialize→reserialize convert (the literal reading of D-04) **fails on every headered message** in both directions (`AssertionError`/`AttributeError: 'Header' object has no attribute 'seq'`), while `rosbags`' own migration path handles them. The edit pipeline should therefore **reuse `rosbags`' converter building blocks** (the `create_connections_converters` / `generate_message_converter` pattern) rather than hand-roll the deserialize→reserialize logic D-04 describes — D-04's *intent* (raw-copy when wireformats match, convert only when they differ) is exactly what `is_same_wireformat` + `generate_message_converter` already implement, message-type by message-type. This is the "Don't Hand-Roll" headline of the phase.

The events half is straightforward and fully verified: write the sidecar with the existing `output/export.write_table` (DuckDB COPY, quote-escaped path), read it back with `pyarrow.parquet.read_table`, append by read→`pa.concat_tables`→rewrite, and register it in `query()` under the reserved name `events` after subtracting `events` from the topic-resolution set so it never trips `UnknownTableError`. The interval join (`... ON data.t_ns BETWEEN events.t_start_ns AND events.t_end_ns`) works natively against the registered relation — proven end-to-end against a real fixture bag.

**Primary recommendation:** Build `rosbagger_core/edit/` as a streaming pipeline that mirrors `rosbags.convert.converter`'s connection-mapping + per-msgtype converter pattern (reuse its building blocks where you can import them; otherwise replicate the proven structure), layering the edit filters (trim/drop/keep/downsample) into the message loop. Build `rosbagger_core/events.py` over `output/export.write_table` + `pyarrow.parquet.read_table`. Hook `events` into `query()` as a reserved name that loads the sidecar and registers it like any other relation.

## User Constraints (from CONTEXT.md)

### Locked Decisions

> **`--auto` mode:** every decision below is the recommended default, auto-selected without user prompts.

**Module placement & CLI surface**
- **D-01** — Edit + events logic lives in `rosbagger_core`, NOT a separate `rosbagger-edit` package. e.g. `rosbagger_core/edit/` (operations + pipeline) and `rosbagger_core/events.py` (sidecar I/O). Mirrors the locked Phase 9 "tf-in-core" precedent so the existing `--cov=rosbagger_core` gate covers it. Can split later.
- **D-02** — Thin CLI verbs over the core API (API-first): `bagq edit IN... -o OUT [ops]`, `bagq convert IN -o OUT` (format-change convenience that shares the edit pipeline), `bagq events add <bag> ...`, `bagq events list <bag>`. CLI builds no logic.

**Edit pipeline architecture**
- **D-03** — A single streaming pipeline: `AnyReader` raw stream `(connection, t_ns, rawdata)` → filter/transform → `rosbags` Writer (`add_connection(...)` + `write(conn, t_ns, raw)`). Reuse the writer pattern from `tools/make_fixtures.py`. Reader already exposes `connections`, `typestore`, `start_time`.
- **D-04** — Raw-byte copy when serialization matches; deserialize→reserialize only when converting cross-format. Same-format ops (trim/drop/keep/downsample/merge within one serialization) copy `rawdata` losslessly. Convert ROS 1 ↔ ROS 2 (ros1 ↔ cdr) deserializes via the source typestore and reserializes for the target (rosbags handles message-definition translation). **This is the key architectural split.**
- **D-05** — Never mutate the input; always write a NEW output bag. Re-register each source connection on the writer; an unresolvable custom msgtype surfaces the Phase 7 teaching error.

**Edit operation semantics (compose in one pass)**
- **D-06** — `--trim START END` in seconds RELATIVE to bag start (uses `reader.start_time`): keep messages whose bag-relative time is in `[START, END]`.
- **D-07** — `--drop /topic` and `--keep /topic`, each repeatable and mutually exclusive: `--drop` excludes named topics; `--keep` includes only named topics.
- **D-08** — `--downsample /topic:N` keeps every Nth message of that topic (deterministic; no time-bucketing). Optional global `--downsample N` applies to all topics. Rate-target (Hz) deferred.
- **D-09** — Merge is implicit when multiple input paths are given. Reader already merges multi-bag streams time-ordered (READ-05); pipeline writes one output bag in timestamp order.
- **D-10** — Convert = output-format selection from the `-o` extension (`.bag`/`.mcap`/ROS 2 dir) or explicit `--format`. `bagq convert` is the dedicated verb but shares the `edit` pipeline. All ops compose in a single read→write pass.

**Event sidecar: schema & write path**
- **D-11** — Sidecar path `<bag>.events.parquet`, derived deterministically from the bag path (strip the bag's own extension, append `.events.parquet`; works for a ROS 1 `.bag` file, a ROS 2 directory, and an `.mcap` file).
- **D-12** — Small fixed v1 event schema: `t_start_ns BIGINT`, `t_end_ns BIGINT`, `label VARCHAR`, `note VARCHAR` (nullable). A point/instant event has `t_start_ns == t_end_ns`. The `_ns` columns line up with topic tables' `t_ns`.
- **D-13** — Write path reuses the existing DuckDB-`COPY` Parquet writer (`output/export.py`). `bagq events add` appends a row (read existing → concat new row → rewrite whole Parquet; files are tiny). `bagq events list` reads it back (SC2).

**events table & time-join**
- **D-14** — `events` is a RESERVED table name in the query engine. When the SQL references `events`, `query()` discovers `<bag>.events.parquet` next to the (single) bag and registers it as the `events` relation. v1 is single-bag events; multi-bag deferred. Resolution piggybacks on `backend/resolve.py` `referenced_tables`.
- **D-15** — Time-join is a STANDARD SQL interval join — no special operator: `SELECT i.* FROM imu i JOIN events e ON i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns`. `events` registers like any other DuckDB relation (SC3).

### Claude's Discretion

Exact module layout (`edit/` subpackage vs flat files), function/parameter names, the precise raw-vs-deserialize detection mechanism, and whether `convert` is a distinct verb or `edit --format`. Hard constraints on all: the offline-import invariant (no ROS; heavy imports stay lazy), no-ROS fixture tests (extend `tools/make_fixtures.py` for edit round-trips), the ≥80% coverage gate, and the trusted-input boundary (the output path is the one SQL-literal surface — reuse `output/export.py`'s quote-escape).

### Deferred Ideas (OUT OF SCOPE)

- **Live "mark event now"** — needs `rclpy`; Phases 12–13.
- **GUI timeline markers / jump-points** for events — Phase 14.
- **Rate-target (Hz) downsample** / time-bucketed resampling — v1 ships deterministic every-Nth only.
- **Event import/export** (CSV/JSON ingest, bulk annotation) — v1 ships `events add`/`list` only.
- **Multi-bag events** (which sidecar when several bags are queried) — v1 is single-bag.
- **In-place editing** — always rejected; edits always write a new output bag.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EDIT-01 | Trim / drop / merge / downsample / convert (ROS1↔ROS2↔MCAP) | Streaming `AnyReader → Writer` pipeline verified for raw-copy (same-format, all 3 formats) + convert (via `rosbags` converter building blocks); trim via `reader.start_time`; drop/keep via connection-skip; downsample via per-topic counter; merge via `AnyReader` multi-bag time-ordering — all proven by experiment below |
| EVNT-01 | Event sidecar exposed as a queryable `events` table | Sidecar write/read/append via `output/export.write_table` + `pyarrow.parquet.read_table`; reserved-name detection in `query()` via `referenced_tables`; interval join verified end-to-end against a real fixture bag |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read source bag(s) | `rosbagger_core/reader` (`RosbagsReader`/`AnyReader`) | — | Already the universal-read seam; exposes raw `(connection, t_ns, rawdata)`, `connections`, `typestore`, `start_time`, multi-bag merge |
| Filter/transform messages | `rosbagger_core/edit/` pipeline | — | New offline domain logic (D-01/D-03); composes trim/drop/keep/downsample in one pass |
| Cross-format byte conversion | `rosbags` library (`convert.converter`, `typestore.cdr_to_ros1`/`ros1_to_cdr`, `migrate_message`) | `rosbagger_core/edit/` (orchestration) | Library owns the wireformat/`seq`/msgdef knowledge — do NOT reimplement (Don't Hand-Roll) |
| Write output bag | `rosbags` Writer (`rosbag1.Writer` / `rosbag2.Writer`) | `rosbagger_core/edit/` (format selection) | Proven sink in `make_fixtures.py`; format chosen from `-o`/`--format` |
| CLI verbs (`edit`/`convert`/`events`) | `bagq/cli.py` | — | Thin presentation only (D-02); parse flags, call core API |
| Events sidecar I/O | `rosbagger_core/events.py` | `rosbagger_core/output/export.py` (write) + `pyarrow.parquet` (read) | New module; reuses the locked COPY-Parquet writer for the write side |
| Events table registration | `rosbagger_core/backend/query.py` | `backend/resolve.py` (`referenced_tables`) | The reserved-name hook lives where topic tables are already registered |
| Events interval join | `DuckDBBackend` (standard SQL) | — | No special operator (D-15); `events` is just another registered relation |

## Standard Stack

The phase introduces **no new dependencies**. Every capability is covered by libraries already locked in `pyproject.toml` / `uv.lock`. The new finding is which *modules* of `rosbags` to use.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rosbags` | 0.11.2 [VERIFIED: importlib.metadata] | Read (`AnyReader`), write (`rosbag1.Writer`/`rosbag2.Writer`), **and convert (`rosbags.convert`)** | The project's universal-bag library; already the reader + fixture-writer. Its `convert` submodule is the reference cross-format implementation [VERIFIED: read source at `.venv/.../rosbags/convert/converter.py`] |
| `duckdb` | 1.5.3 [VERIFIED: importlib.metadata] | Sidecar Parquet write (COPY) + events-table interval join | Already the query engine + Parquet writer (`output/export.py`) |
| `pyarrow` | 24.0.0 [VERIFIED: importlib.metadata] | Sidecar read-back (`parquet.read_table`) + the events `pa.table` schema | Already the result-table type + materialization layer |
| `sqlglot` | 30.8.0 [VERIFIED: importlib.metadata] | `referenced_tables` resolution (detect the `events` name) | Already the SQL resolver (`backend/resolve.py`) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `typer` | 0.25.1 [VERIFIED: importlib.metadata] | New `edit`/`convert`/`events` subcommands | The CLI surface (D-02), same idiom as `info`/`tables`/`query`/`tf` |
| `numpy` | 2.2.6 [VERIFIED: importlib.metadata] | Pulled transitively by `rosbags.convert` (default-message construction) | Only via `rosbags`; not a direct edit-module import |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `rosbags.convert.convert(...)` whole-function | Hand-rolled deserialize→reserialize loop (literal D-04) | **Hand-rolled FAILS on every headered message** (the `seq` field, verified). `convert()` is correct but is a *whole-bag* function with its own topic/msgtype filters — it does NOT do trim/downsample, so you can't use it verbatim for `edit`. Best path: reuse its *building blocks* (`generate_message_converter` / `create_connections_converters` pattern) inside your own message loop |
| `pyarrow.parquet.read_table` (sidecar read) | DuckDB `read_parquet('...')` view | Both work for the interval join [VERIFIED]. `pyarrow.parquet.read_table` gives a `pa.Table` you `register_table` exactly like a topic table (uniform with the existing pipeline) — preferred. `read_parquet` keeps the read inside DuckDB but reintroduces a SQL-literal path surface (must quote-escape) |
| Per-topic downsample counter | Time-bucketed/Hz resample | Hz resample is explicitly DEFERRED (D-08); every-Nth is a trivial per-topic counter |

**Installation:** No install step. All packages already present; verified:
```bash
# Confirm pins (already locked):
#   rosbags 0.11.2, duckdb 1.5.3, pyarrow 24.0.0, sqlglot 30.8.0, typer 0.25.1
PYTHONPATH="" uv run python -c "import importlib.metadata as m; print(m.version('rosbags'))"   # -> 0.11.2
```

## Package Legitimacy Audit

> No external packages are installed in this phase. All libraries used are pre-existing locked dependencies (`rosbags`, `duckdb`, `pyarrow`, `sqlglot`, `typer`, `numpy`), verified present in `uv.lock` and importable in the project venv. slopcheck is therefore N/A — there is no install surface to audit.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none — no new installs) | — | N/A |

## Architecture Patterns

### System Architecture Diagram

**Edit pipeline (EDIT-01):**
```
   one or more bag paths (SAME format for merge — see Pitfall 6)
            │
            ▼
   ┌──────────────────────┐
   │  RosbagsReader /      │   raw stream: (connection, t_ns, rawdata)
   │  AnyReader.messages() │   + connections, typestore, start_time
   └──────────┬───────────┘   (multi-bag input is merged time-ordered by AnyReader)
              │
              ▼
   ┌──────────────────────────────────────────────┐
   │  edit message loop (rosbagger_core/edit/)      │
   │  per message:                                  │
   │   1. keep set?  drop/keep topic filter (D-07)  │  ── skip connection entirely if dropped
   │   2. trim?      reader.start_time + [lo,hi] ns  │  ── skip if t_ns out of window (D-06)
   │   3. downsample? per-topic counter % N (D-08)   │  ── skip if not the Nth
   │   4. convert byte payload via per-msgtype       │
   │      converter (memoryview | cdr_to_ros1 |      │  ◀── reuse rosbags converter factory
   │      ros1_to_cdr | migrate_bytes) (D-04)        │      (raw-copy when wireformat matches)
   └──────────┬─────────────────────────────────────┘
              │  write(writer_conn, t_ns, payload)
              ▼
   ┌──────────────────────────────────────────────┐
   │  rosbags Writer chosen by output FORMAT (D-10)  │
   │   .bag   -> rosbag1.Writer(path)                │
   │   .mcap  -> rosbag2.Writer(dir, version=9,      │
   │            storage_plugin=MCAP)                 │
   │   dir    -> rosbag2.Writer(dir, version=9,      │
   │            storage_plugin=SQLITE3)              │
   │  connections re-registered ONCE up front for    │
   │  KEPT topics only (no orphan connections)       │
   └──────────┬─────────────────────────────────────┘
              ▼
        new output bag  ── re-opens via AnyReader (SC1 assertion)
```

**Events sidecar + query (EVNT-01):**
```
  WRITE PATH (bagq events add)                   QUERY PATH (bagq query "... events ...")
  ───────────────────────────                    ─────────────────────────────────────────
  bag path                                        SQL string
     │                                               │
     ▼                                               ▼
  derive <bag>.events.parquet (D-11)             parse -> referenced_tables (sqlglot)
     │                                               │
     ▼                                               ├─ "events" present?
  read existing sidecar (pyarrow) if any              │       │ yes
     │                                                │       ▼
     ▼                                                │   derive sidecar path next to the
  concat new {t_start_ns,t_end_ns,label,note} row     │   single bag (D-14); pq.read_table;
     │                                                │   backend.register_table("events", tbl)
     ▼                                                │
  write_table(combined, sidecar)  ◀── output/export    └─ subtract "events" from the topic-
  (DuckDB COPY, quote-escaped path)                     resolution set so it does NOT raise
                                                        UnknownTableError
                                                          │
  bagq events list -> pq.read_table -> rich table         ▼
                                                  topic tables registered as usual +
                                                  events relation -> backend.execute(SQL)
                                                  interval join works natively (D-15)
```

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/
├── edit/
│   ├── __init__.py        # re-export the public API (e.g. edit_bag / EditOps), stdlib-light
│   ├── pipeline.py        # the streaming read->filter->write driver
│   └── operations.py      # trim/drop/keep/downsample predicates + format selection (or fold into pipeline.py)
├── events.py              # add_event / list_events / sidecar_path; reuses output/export.write_table
├── backend/
│   └── query.py           # MODIFIED: detect reserved "events" name, load+register sidecar
└── ...
tools/make_fixtures.py     # EXTEND: a small helper to write edit-round-trip source bags if the
                           # existing 3-format fixtures are insufficient (they likely suffice)
tests/
├── test_edit.py           # round-trip per op x 3 formats (re-open via AnyReader)
├── test_events.py         # sidecar write/read/append + events-table join
└── test_offline_guard.py  # EXTEND: import rosbagger_core.edit / .events pull no heavy stack/no ROS
```

### Pattern 1: Raw-copy same-format edit (trim/drop/keep/downsample/merge)
**What:** Read raw `(connection, t_ns, rawdata)`, re-register kept connections on the writer once, write the *unmodified* `rawdata`. No typestore round-trip — lossless and fast.
**When to use:** Output serialization == input serialization. That means ROS1→ROS1, **ROS2-sqlite3 ↔ ROS2-MCAP (both CDR — verified raw-copyable)**, and any same-format trim/drop/downsample/merge.
**Example (VERIFIED — re-opens via AnyReader across all 3 formats):**
```python
# Source: verified experiment against rosbags 0.11.2 + project fixtures
from rosbags.highlevel import AnyReader
from rosbags.rosbag2 import Writer, StoragePlugin

with AnyReader([src]) as reader:
    with Writer(out_dir, version=9, storage_plugin=StoragePlugin.SQLITE3) as w:
        # Re-register ONLY kept connections (drop = skip; no orphan connections — verified)
        wconns = {}
        for c in reader.connections:
            if c.topic in dropped_topics:
                continue
            wconns[c.id] = w.add_connection(c.topic, c.msgtype, typestore=reader.typestore)
        counters = {}  # per-topic downsample counter
        for conn, t_ns, raw in reader.messages():     # already time-ordered (incl. multi-bag)
            if conn.id not in wconns:
                continue                               # dropped topic
            if not (lo_ns <= t_ns <= hi_ns):
                continue                               # trim (lo/hi = start_time + START/END*1e9)
            n = downsample_n.get(conn.topic)
            if n:
                keep = counters.get(conn.id, 0) % n == 0
                counters[conn.id] = counters.get(conn.id, 0) + 1
                if not keep:
                    continue
            w.write(wconns[conn.id], t_ns, raw)        # RAW copy — no deserialize
```

### Pattern 2: Cross-format convert (ROS1 ↔ ROS2) — REUSE the rosbags converter factory
**What:** When wireformats differ, you must convert the byte payload per message type. `rosbags` provides a converter *factory* that returns the right callable per msgtype: `memoryview` (identity, same wireformat), `cdr_to_ros1`/`ros1_to_cdr` (byte-level, same field layout), or `migrate_bytes` (full deserialize→migrate-fields→reserialize, used when the field set differs — e.g. `Header.seq`).
**When to use:** ROS1 `.bag` ↔ ROS2 (`-o` extension crosses the ros1/cdr boundary). NOT for sqlite3↔MCAP (both CDR → raw-copy).
**Example (the rosbags reference structure — REUSE, do not reinvent):**
```python
# Source: .venv/.../rosbags/convert/converter.py (generate_message_converter / create_connections_converters)
from functools import partial
from rosbags.convert.converter import is_same_wireformat   # importable building block
# generate_message_converter chooses, PER msgtype:
#   is_same_wireformat AND src_is2==dst_is2  -> memoryview            (raw copy)
#   is_same_wireformat AND src is cdr        -> src_ts.cdr_to_ros1    (byte-level)
#   is_same_wireformat AND src is ros1       -> dst_ts.ros1_to_cdr    (byte-level)
#   else (field set differs, e.g. seq)       -> migrate_bytes(...)    (deser->migrate->reser)
```
**Strongly recommended:** rather than re-deriving this, call the library helpers. The cleanest option if the *only* edit is a format change with optional topic filtering is to call `rosbags.convert.convert(...)` directly (it has `include_topics`/`exclude_topics`/`include_msgtypes`/`exclude_msgtypes`). For `edit` (which also needs trim/downsample), replicate `create_connections_converters` + `generate_message_converter` inside your own loop so you can interleave the trim/downsample filters. (`is_same_wireformat` and `generate_message_converter` live in `rosbags.convert.converter` and are importable.)

### Pattern 3: Output-format selection from the `-o` path (D-10)
**What:** Pick the Writer + storage from the destination path/flag. `rosbags`' own rule (verified in its source) is `is2 = dst.suffix != '.bag'`.
**Example:**
```python
# Source: .venv/.../rosbags/convert/converter.py convert() driver
from pathlib import Path
def make_writer(out: Path, fmt: str | None):
    suffix = out.suffix.lower()
    if fmt == "ros1" or suffix == ".bag":
        from rosbags.rosbag1 import Writer
        return Writer(out)                              # ROS1 single-file .bag
    from rosbags.rosbag2 import Writer, StoragePlugin
    plugin = StoragePlugin.MCAP if (fmt == "mcap" or suffix == ".mcap") else StoragePlugin.SQLITE3
    return Writer(out, version=9, storage_plugin=plugin)  # ROS2 dir (sqlite3) or .mcap
```

### Pattern 4: Events sidecar I/O (D-11/D-12/D-13)
**What:** Write/read/append the tiny Parquet sidecar reusing the locked COPY-Parquet writer.
**Example (VERIFIED end-to-end):**
```python
# Source: verified against output/export.write_table + pyarrow 24.0.0
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from rosbagger_core.output.export import write_table   # DuckDB COPY, quote-escaped path (T-06-01)

_EVENT_SCHEMA = pa.schema([            # D-12 fixed v1 schema
    ("t_start_ns", pa.int64()),
    ("t_end_ns",   pa.int64()),
    ("label",      pa.string()),
    ("note",       pa.string()),       # nullable
])

def sidecar_path(bag: Path) -> Path:   # D-11 — robust against dotted directory names (Pitfall 7)
    bag = Path(bag)
    if bag.suffix in {".bag", ".mcap"}:        # FILE bags: strip the real extension
        return bag.with_suffix(".events.parquet")
    return bag.parent / (bag.name + ".events.parquet")   # DIR bag: append, never strip

def add_event(bag, *, t_start_ns, t_end_ns, label, note=None):
    path = sidecar_path(bag)
    row = pa.table({"t_start_ns": [t_start_ns], "t_end_ns": [t_end_ns],
                    "label": [label], "note": [note]}, schema=_EVENT_SCHEMA)
    if path.exists():
        existing = pq.read_table(path)         # read existing (lazy import pyarrow inside fn)
        combined = pa.concat_tables([existing, row])
    else:
        combined = row
    write_table(combined, str(path))           # rewrite whole file (events are tiny) — D-13

def list_events(bag):
    path = sidecar_path(bag)
    return pq.read_table(path) if path.exists() else _EVENT_SCHEMA.empty_table()
```

### Pattern 5: events reserved-name hook in `query()` (D-14/D-15)
**What:** Detect `events` in the referenced tables, load + register the sidecar, and subtract it from topic resolution so it never raises `UnknownTableError`.
**Example (VERIFIED end-to-end against a real fixture bag — join returns correct rows):**
```python
# Source: verified against backend/query.py + backend/resolve.py + DuckDBBackend
_EVENTS_TABLE = "events"            # reserved name (D-14)

# inside query(), AFTER Step 5 derives `tables` (the rewritten-tree referenced tables):
events_referenced = _EVENTS_TABLE in tables
data_tables = tables - {_EVENTS_TABLE}        # CRITICAL: keep events out of the topic loop
# ... resolve ONLY data_tables to topics (Step 6 loop iterates data_tables, not tables) ...
# ... register topic tables (Step 7) ...
if events_referenced:
    # v1 single-bag (D-14): the sidecar sits next to the single bag path.
    import pyarrow.parquet as pq
    path = sidecar_path(reader.paths[0])
    if path.exists():
        backend.register_table(_EVENTS_TABLE, pq.read_table(path))
    # else: leave unregistered -> DuckDB raises a clean "table events does not exist"
    #       (an empty-table register is an alternative if a friendlier message is wanted)
```
The interval join `... ON i.t_ns BETWEEN e.t_start_ns AND e.t_end_ns` then executes natively — no special operator (D-15). **Verified result:** `imu` at 1.0/1.1/1.3 s joined to an event `[1.0, 1.1] s` returns exactly the 1.0 and 1.1 s rows.

### Anti-Patterns to Avoid
- **Hand-rolling deserialize→reserialize for convert.** It silently produces bags that re-open but fail to *deserialize* headered messages (the `seq` field). Always go through `rosbags`' migration logic (`migrate_bytes`/`generate_message_converter`) or `rosbags.convert.convert`.
- **Registering dropped/unkept connections on the writer.** Re-register only the kept topics' connections, or you get empty connections in the output (and a confusing schema). Verified: skipping the `add_connection` for a dropped topic cleanly removes it.
- **Forwarding `events` into the topic-resolution loop.** It maps to no topic → `UnknownTableError`. Subtract it first (D-14).
- **`Path.with_suffix('.events.parquet')` on a directory bag.** A dotted directory name (`v1.2`) loses its last segment (→ `v1.events.parquet`). Use the file-vs-dir-aware derivation in Pattern 4.
- **Eagerly importing the heavy stack at module top in `edit/`/`events.py`.** Breaks the offline invariant. `import rosbags`/`pyarrow`/`duckdb` stay inside function bodies or in modules not reached by `import rosbagger_core` (mirror `reader/`, `output/export.py`, `backend/query.py`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-format message conversion (ROS1↔ROS2) | A deserialize→reserialize loop | `rosbags.convert.converter.generate_message_converter` / `migrate_bytes` (or `rosbags.convert.convert` whole-bag) | The naive loop FAILS on the ROS1 `Header.seq` field (verified `AssertionError`/`AttributeError`). `rosbags` already does field add/remove migration, legacy renames, default-message fill, array resizing |
| Deciding raw-copy vs convert per message | A hand-coded "is this the same format?" check | `rosbags.convert.converter.is_same_wireformat(...)` | It recursively compares field defs (incl. nested submessages, arrays) — far more correct than a format-string compare |
| Generating the target-ROS message definition for `add_connection` | Building `.msg`/IDL text by hand | `typestore.generate_msgdef(typename, ros_version=...)` (rosbags does this internally; `add_connection(..., typestore=ts)` is enough for known types) | `add_connection(topic, msgtype, typestore=ts)` derives msgdef + md5/RIHS from the typestore — verified sufficient for built-in types |
| Multi-bag merge ordering | A heap/merge-sort over per-bag streams | `AnyReader([b1, b2, ...]).messages()` | Already merges time-ordered (READ-05) — verified globally sorted across 2 bags |
| Parquet write (sidecar) | `pyarrow.parquet.write_table` directly | `rosbagger_core.output.export.write_table` | Reuses the locked DuckDB-COPY path + the one quote-escape SQL-literal boundary (T-06-01) — the trusted-input constraint |
| Time-interval join | A custom interval index/operator | A standard SQL `BETWEEN` join on the registered relation | DuckDB does it natively (D-15) — verified |
| SQL table-name resolution (find `events`) | A regex over the SQL | `backend/resolve.referenced_tables` (sqlglot) | Already CTE-aware and JOIN-aware; `events` appears as a plain table name — verified |

**Key insight:** This phase looks like "writing bags" but the genuinely hard part — cross-format wireformat translation — is already solved inside `rosbags`. The phase's value is the *edit filters* (trim/drop/keep/downsample/merge) layered over the proven read/convert/write machinery, plus a thin events sidecar. Treat `rosbags.convert.converter` as the canonical reference for the convert path.

## Runtime State Inventory

> This phase WRITES new bags and a new sidecar; it does not rename or migrate existing runtime state. The inventory is included for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — edit always writes a NEW output bag (D-05, in-place rejected); events sidecar is a new file next to the bag | None |
| Live service config | None — fully offline, no running ROS graph, no external service | None |
| OS-registered state | None — no daemons, schedulers, or registrations | None |
| Secrets/env vars | None — no new secrets; the only env concern is the existing `PYTHONPATH=""` dev-host prefix for local test runs (CI is ROS-free) | None (document the prefix in test instructions) |
| Build artifacts | New module `rosbagger_core/edit/` + `events.py` are auto-covered by the existing `--cov=rosbagger_core` gate (D-01, the tf-in-core precedent) — no new package, no `pyproject`/`uv.lock`/console-script edits needed | None — verify no new console-script is required (the verbs are subcommands of the existing `bagq` app) |

**Verified:** No runtime state migration is in scope. New bags/sidecars are additive on-disk artifacts.

## Common Pitfalls

### Pitfall 1: Naive cross-format convert produces bags that re-open but fail to deserialize
**What goes wrong:** A deserialize→`serialize_ros1` (or byte-level `cdr_to_ros1`) convert of a ROS2 bag writes a `.bag` that `AnyReader` *opens* and lists topics for — but deserializing any **headered** message (`/imu`, `/image`) raises `AssertionError` / `AttributeError: 'std_msgs__msg__Header' object has no attribute 'seq'`. Headerless messages (`/cmd_vel` Twist) convert fine, masking the bug in a shallow test.
**Why it happens:** ROS1's `std_msgs/Header` has a required `seq` field that ROS2 dropped. A ROS2-shaped message object has no `seq`; serializing it as ROS1 either crashes (deserialize path) or writes a byte stream the ROS1 reader mis-parses (byte path).
**How to avoid:** Use `rosbags`' migration logic. `is_same_wireformat` returns `True` for `std_msgs/msg/Header` *by special-case* but the surrounding message differs, so `generate_message_converter` selects `migrate_bytes`, which fills the missing `seq` from a default message. **Verified:** `rosbags.convert.convert(...)` and the manual `migrate_message` path both round-trip `/imu` and `/image`. (As a last resort, the manual fix `object.__setattr__(msg.header, "seq", 0)` before `serialize_ros1` also works — but prefer the library path.)
**Warning signs:** Your round-trip test only checks `AnyReader` *opens* + lists topics, but never *deserializes* every message. **The SC1 test MUST deserialize at least one message of every topic** (ideally all), not just re-open.

### Pitfall 2: Round-trip test asserts re-open but not re-deserialize
**What goes wrong:** `with AnyReader([out]) as r: r.topics` passes for a structurally-valid-but-semantically-broken bag (see Pitfall 1).
**How to avoid:** In every edit round-trip test, iterate `r.messages()` and call `r.deserialize(raw, conn.msgtype)` for each (or at least one per topic), asserting topic set, message counts, and time range. This is the real SC1 contract ("re-open via AnyReader" means *usable*, not merely *openable*).

### Pitfall 3: ROS1 `Writer.__init__` takes a different signature than ROS2
**What goes wrong:** Passing `version=`/`storage_plugin=` to `rosbags.rosbag1.Writer` raises `TypeError`.
**Why it happens:** They are different classes. `rosbag1.Writer(path)` takes only a path; `rosbag2.Writer(path, *, version: Literal[8,9], storage_plugin=StoragePlugin.SQLITE3)` requires `version` (keyword-only). [VERIFIED: `inspect.signature`]
**How to avoid:** Branch on output format and construct the right Writer (Pattern 3). This is already documented in `make_fixtures.py` (its Pitfall 1/2 notes); reuse that knowledge.

### Pitfall 4: `version=9` is REQUIRED for the ROS2 Writer
**What goes wrong:** `Writer(path, storage_plugin=...)` without `version=` raises a missing-argument error.
**Why it happens:** `version` is keyword-only with no default. [VERIFIED: signature is `(self, path, *, version: Literal[8, 9], storage_plugin=...)`] `make_fixtures.py` uses `version=9`.
**How to avoid:** Always pass `version=9` (the modern ROS2 bag format) for ROS2 outputs.

### Pitfall 5: Heavy imports at module top break the offline invariant
**What goes wrong:** `import rosbagger_core` (or `import bagq`) starts pulling `pyarrow`/`duckdb`/`rosbags`, and `tests/test_offline_guard.py` fails.
**Why it happens:** The guard spawns a fresh interpreter (empty `PYTHONPATH`) and asserts `import rosbagger_core` / subpackages leak none of `{duckdb, sqlglot, pyarrow}`. (`rosbags` is checked separately for `errors`/`tf`.)
**How to avoid:** In `edit/` and `events.py`, keep module tops stdlib-light; `import rosbags`/`pyarrow`/`duckdb` inside function bodies (mirror `reader/rosbags_reader.py`, `output/export.py`, `backend/query.py`). **Extend `test_offline_guard.py`** with `import rosbagger_core.edit` / `import rosbagger_core.events` assertions (the tf/output precedents). NOTE: `reader/rosbags_reader.py` imports `rosbags` at module top legitimately because `rosbagger_core/__init__` does NOT import it — verify your `edit/__init__` likewise stays off the `import rosbagger_core` graph, or keep its `rosbags` import lazy.

### Pitfall 6: Merge requires SAME-format inputs
**What goes wrong:** `bagq edit run.bag run.mcap -o out` (mixing ROS1 + ROS2 inputs) raises `AnyReaderError: Unrecognized storage format '.bag'`.
**Why it happens:** `AnyReader` (and READ-05) only merges homogeneous inputs. [VERIFIED: mixed ROS1+ROS2 → `AnyReaderError`]
**How to avoid:** Document and enforce that multi-input merge (D-09) requires same-format inputs — surface a clear error (it already propagates as `AnyReaderError`; consider a teaching message). Same-format multi-bag merge IS time-ordered automatically. [VERIFIED: 2-bag merge globally sorted]

### Pitfall 7: Sidecar path derivation strips dotted directory names
**What goes wrong:** `Path('/data/v1.2').with_suffix('.events.parquet')` → `/data/v1.events.parquet` (drops `.2`).
**Why it happens:** `with_suffix` treats the last `.segment` of a directory name as an extension.
**How to avoid:** Strip the extension ONLY for `.bag`/`.mcap` *files*; for directory bags, append `.events.parquet` to the full name (Pattern 4 `sidecar_path`). [VERIFIED both branches]

### Pitfall 8: `--drop` / `--keep` mutual exclusion and the empty-keep edge
**What goes wrong:** `--keep` with zero matching topics writes an empty bag silently; `--drop` + `--keep` together is ambiguous.
**Why it happens:** D-07 makes them mutually exclusive but the CLI must enforce it; an empty connection set is a valid (if useless) output.
**How to avoid:** Reject `--drop` + `--keep` in the same invocation (a `typer.BadParameter`). For an empty result, either error or write an empty bag — pick one and test it. (Note: the reader's `read(topics=set())` short-circuits to empty — the edit pipeline filters at the connection layer instead, so confirm the empty-keep behavior explicitly.)

## Code Examples

(Verified patterns are inline in **Architecture Patterns** above — Pattern 1 raw-copy, Pattern 2 convert factory, Pattern 3 format selection, Pattern 4 sidecar I/O, Pattern 5 events hook.) Two additional verified signatures the planner will reference:

### rosbags Writer signatures (pin to 0.11.2)
```python
# Source: inspect.signature against installed rosbags 0.11.2 [VERIFIED]
rosbags.rosbag1.Writer.__init__(self, path: Path | str) -> None
rosbags.rosbag1.Writer.add_connection(self, topic, msgtype, *, typestore=None, msgdef=None,
                                       md5sum=None, callerid=None, latching=None) -> Connection
rosbags.rosbag1.Writer.write(self, connection: Connection, timestamp: int, data: bytes | memoryview) -> None

rosbags.rosbag2.Writer.__init__(self, path, *, version: Literal[8, 9],
                                storage_plugin: StoragePlugin = StoragePlugin.SQLITE3) -> None
rosbags.rosbag2.Writer.add_connection(self, topic, msgtype, *, typestore=None, msgdef=None,
                                      rihs01=None, serialization_format='cdr',
                                      offered_qos_profiles: Sequence[Qos] = ()) -> Connection
rosbags.rosbag2.Writer.write(self, connection: Connection, timestamp: int, data: bytes | memoryview) -> None

# StoragePlugin = {SQLITE3, MCAP}  [VERIFIED]
# Connection (rosbags.interfaces) NamedTuple fields: id, topic, msgtype, msgdef, digest,
#   msgcount, ext, owner   (ext = ConnectionExtRosbag1{callerid,latching} | ConnectionExtRosbag2{serialization_format,offered_qos_profiles})
```

### rosbags typestore byte-level converters (pin to 0.11.2)
```python
# Source: inspect.signature against installed rosbags 0.11.2 [VERIFIED]
typestore.cdr_to_ros1(raw: bytes | memoryview, typename: str) -> memoryview   # byte-level, no deser
typestore.ros1_to_cdr(raw: bytes | memoryview, typename: str) -> memoryview   # byte-level, no deser
typestore.serialize_cdr(message, typename, *, little_endian=True) -> memoryview
typestore.serialize_ros1(message, typename) -> memoryview
typestore.generate_msgdef(typename, ros_version=1) -> tuple[str, str]
# WARNING: cdr_to_ros1 / ros1_to_cdr are byte-level and DO NOT handle the seq-field
#          difference -> they raise AssertionError on headered messages. Use them ONLY via
#          generate_message_converter, which falls back to migrate_bytes when fields differ.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hand-write cross-format conversion | `rosbags.convert` module (built into the dependency) | Present in rosbags 0.11.2 | Reuse it; do not reimplement (Don't Hand-Roll) |
| `con.fetch_arrow_table()` | `con.execute(sql).to_arrow_table()` | duckdb 1.x | Already adopted in `DuckDBBackend`; the events relation registers the same way |
| ROS2 bag `version=8` | `version=9` | ROS2 Iron+ | `make_fixtures.py` already uses `version=9`; new edit outputs should too |

**Deprecated/outdated:**
- Byte-level `cdr_to_ros1`/`ros1_to_cdr` as a *standalone* convert path: works only for messages whose field sets are identical across ROS versions (i.e. effectively headerless or already-`seq`-free types). For general convert, `migrate_bytes` is the correct path — `generate_message_converter` picks between them automatically.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `rosbags.convert.converter.is_same_wireformat` and `generate_message_converter` are importable as public-enough building blocks (they have no leading underscore and are module-level) | Pattern 2 / Don't Hand-Roll | LOW — if a future rosbags version moves them, fall back to calling `rosbags.convert.convert(...)` whole-bag for the pure-convert case, or replicate the ~40-line factory. They exist and work in 0.11.2 [VERIFIED by reading source + running migrate path] |
| A2 | The existing 3 fixtures (`write_ros1_bag`/`write_ros2_sqlite_bag`/`write_ros2_mcap_bag`) suffice for edit round-trip tests; a new fixture helper is likely unnecessary | Recommended Structure | LOW — they cover all 3 formats and the headered/headerless/array/blob cases. A merge test needs two same-format bags (write the fixture twice to different dirs) |
| A3 | Leaving `events` unregistered when the sidecar is absent yields an acceptable DuckDB "table does not exist" error (vs. registering an empty table) | Pattern 5 | LOW — both are valid; the planner/discuss may prefer registering an empty-schema table for a friendlier message. Either is a small, local choice |
| A4 | `bagq edit`/`convert`/`events` are subcommands of the existing `bagq` typer app (no new console-script / `pyproject` entry needed), matching the `bagq tf` precedent | Runtime State Inventory / Structure | LOW — `bagq tf` (Phase 9) added a subcommand with no `pyproject`/`uv.lock`/console-script edits (per STATE.md); same applies here |

**Note:** No `[ASSUMED]` claims touch compliance, security standards, retention, or performance targets. The cross-format and events behaviors are all `[VERIFIED]` by direct experiment against the installed `rosbags` 0.11.2 and the project's own modules.

## Open Questions

1. **Convert path: reuse `rosbags.convert.convert` whole-function vs. replicate its factory inside the edit loop?**
   - What we know: `convert()` does format-change + topic/msgtype include/exclude, and handles everything correctly. But it does NOT do trim or downsample, and it owns its own reader+writer lifecycle.
   - What's unclear: whether the planner wants `bagq convert` (pure format change) to call `convert()` directly (simplest, most robust) while `bagq edit` uses the replicated factory + filter loop — i.e. two code paths — or unify on one replicated pipeline.
   - Recommendation: **`bagq convert` (no trim/downsample) → call `rosbags.convert.convert(...)` directly** (it even has the topic filters for drop/keep). **`bagq edit` (with filters) → replicate `create_connections_converters` + `generate_message_converter` in the streaming loop.** This minimizes hand-rolled convert logic while supporting the full edit op set. (Both share `make_writer` from Pattern 3.) Confirm in discuss-phase / planning.

2. **Empty-keep / empty-output behavior (Pitfall 8): error or write an empty bag?**
   - What we know: an empty connection set produces a valid empty output bag; D-07 makes `--drop`/`--keep` mutually exclusive.
   - What's unclear: the desired UX when filters select zero topics or zero messages (trim window outside the bag).
   - Recommendation: write the (empty) output and print a count, OR raise a teaching error — pick one in planning and test it. Reject `--drop` + `--keep` together as a `BadParameter`.

3. **events sidecar absent at query time (Pattern 5 / A3): unregistered (DuckDB error) vs empty-table register?**
   - What we know: both work; the join just returns zero rows for an empty table, or DuckDB errors for an unregistered name.
   - Recommendation: register an empty-schema `events` table when the sidecar is absent (so `SELECT * FROM events` and joins behave predictably and the error, if any, is about columns not existence). Minor; planner's call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `rosbags` | edit read/write/convert | ✓ | 0.11.2 | — |
| `rosbags.convert` submodule | cross-format convert | ✓ (imports no ROS; pulls numpy) | bundled with rosbags 0.11.2 | — |
| `duckdb` | sidecar Parquet write + events join | ✓ | 1.5.3 | — |
| `pyarrow` | sidecar read-back + events schema | ✓ | 24.0.0 | — |
| `sqlglot` | detect `events` in SQL | ✓ | 30.8.0 | — |
| `typer`/`click`/`rich` | CLI verbs | ✓ | 0.25.1 / 8.4.1 / 15.0.0 | — |
| `numpy` | transitive (rosbags convert default-message) | ✓ | 2.2.6 | — |
| ROS install (`rclpy`/`rosbag2_py`) | — | intentionally ABSENT | — | N/A — offline invariant; tests use `rosbags`-written fixtures |

**Missing dependencies with no fallback:** None — every required library is present and verified importable.
**Missing dependencies with fallback:** None.

**Local-run note:** Per the user's MEMORY, bare `uv run pytest` crashes on this ROS-equipped box (the dev shell leaks ROS onto `PYTHONPATH`). Prefix local runs with `PYTHONPATH=""` (e.g. `PYTHONPATH="" uv run pytest`). CI is ROS-free and needs no prefix.

## Validation Architecture

> `workflow.nyquist_validation` is not present in `.planning/config.json` → treated as ENABLED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8,<10 [VERIFIED: pyproject `[dependency-groups].dev`] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `PYTHONPATH="" uv run pytest tests/test_edit.py -x` (and `tests/test_events.py`) |
| Full suite command | `PYTHONPATH="" uv run pytest` (runs with `--cov=rosbagger_core --cov=bagq --cov-fail-under=80`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EDIT-01 | trim keeps only in-window messages (relative to `start_time`) | unit/integration | `pytest tests/test_edit.py -k trim -x` | ❌ Wave 0 |
| EDIT-01 | drop/keep removes/retains exactly the named topics (no orphan connections) | integration | `pytest tests/test_edit.py -k "drop or keep" -x` | ❌ Wave 0 |
| EDIT-01 | downsample keeps every Nth message per topic (deterministic) | unit | `pytest tests/test_edit.py -k downsample -x` | ❌ Wave 0 |
| EDIT-01 | merge of two same-format bags writes one time-ordered output | integration | `pytest tests/test_edit.py -k merge -x` | ❌ Wave 0 |
| EDIT-01 | convert ROS1→ROS2 and ROS2→ROS1 round-trips (headered msgs DESERIALIZE — Pitfall 1) | integration | `pytest tests/test_edit.py -k convert -x` | ❌ Wave 0 |
| EDIT-01 | every edit output re-opens AND re-deserializes via AnyReader, across all 3 formats (SC1) | integration (parametrized) | `pytest tests/test_edit.py -k roundtrip -x` | ❌ Wave 0 |
| EVNT-01 | sidecar written then read back; append grows the row count (SC2) | integration | `pytest tests/test_events.py -k "sidecar or append" -x` | ❌ Wave 0 |
| EVNT-01 | `events` table queryable; interval join returns correct rows (SC3) | integration | `pytest tests/test_events.py -k "join or query" -x` | ❌ Wave 0 |
| EVNT-01 | `events` reserved name does NOT raise UnknownTableError | unit | `pytest tests/test_events.py -k reserved -x` | ❌ Wave 0 |
| (invariant) | `import rosbagger_core.edit` / `.events` pull no heavy stack / no ROS | unit | `pytest tests/test_offline_guard.py -x` | ✅ extend existing |

### Sampling Rate
- **Per task commit:** `PYTHONPATH="" uv run pytest tests/test_edit.py tests/test_events.py -x`
- **Per wave merge:** `PYTHONPATH="" uv run pytest` (full suite, coverage gate)
- **Phase gate:** Full suite green at ≥80% coverage before `/gsd:verify-work`. SC1/SC2/SC3 each have an explicit parametrized assertion (the SC1 test MUST deserialize, not just re-open — Pitfall 2).

### Wave 0 Gaps
- [ ] `tests/test_edit.py` — covers EDIT-01 (trim/drop/keep/downsample/merge/convert + SC1 round-trip across 3 formats)
- [ ] `tests/test_events.py` — covers EVNT-01 (sidecar write/read/append + events-table reserved-name + interval join SC2/SC3)
- [ ] `tests/test_offline_guard.py` — EXTEND with `import rosbagger_core.edit` / `import rosbagger_core.events` no-heavy-stack + no-rosbags assertions (mirror the tf/output guards)
- [ ] Fixtures: reuse `make_fixtures.py`'s 3-format helpers; for merge, write a fixture twice to two dirs. (No framework install needed — pytest is present.)

## Security Domain

> `security_enforcement` is not set in `.planning/config.json` → treated as ENABLED. This is a local single-user offline CLI; the threat surface is small and well-characterized by prior phases.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Single-user local files |
| V5 Input Validation | yes | The output **path** is the one SQL-literal surface (events sidecar via DuckDB COPY) — reuse `output/export.py`'s `'`→`''` quote-escape (T-06-01). Topic names from bags become connection identifiers, not SQL — the Writer takes them as plain strings (no injection surface). `--downsample /topic:N` must validate `N` is a positive int |
| V6 Cryptography | no | No crypto in scope |
| V12 File / Resource | partial | Edit reads user-supplied bag paths and writes a user-supplied output path. Path traversal disposition is *accept* (local single-user CLI — consistent with T-06-02). Never write in-place (D-05) — the output is always a distinct new path; consider refusing to overwrite the input path |

### Known Threat Patterns for {offline bag edit + Parquet sidecar + DuckDB query}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious path in events sidecar write breaks/injects the COPY statement | Tampering | `output/export._copy_to` already single-quote-escapes the path literal (T-06-01) — reuse it verbatim (D-13); never build a second COPY |
| Hostile topic name from an untrusted bag escaping into SQL/identifier | Injection | Edit never puts topic names into SQL (it passes them to `Writer.add_connection` as data). The events table is registered under the fixed reserved name `events` (no bag-derived identifier). Topic→table identifiers on the query side already go through `TableNameResolver`'s `[0-9A-Za-z_]` allow-list (T-03-01) |
| Bag with unresolvable custom msgtype crashes the edit-write with a traceback | DoS / poor UX | Surface the Phase 7 `UnresolvedTypeError` teaching error (D-05) at the read/convert boundary — `AnyReader.open()` already raises the "no type definitions" `AnyReaderError` that `RosbagsReader.open()` maps to `UnresolvedTypeError` |
| Overwriting the input bag (data loss) | Tampering | D-05 forbids in-place edit; enforce that the resolved output path differs from every input path (a clear error otherwise) |
| Untrusted Parquet sidecar read (a hand-crafted `<bag>.events.parquet`) | Tampering | Local single-user file the user owns (same trust level as the bag) — disposition *accept*, consistent with the project's local-CLI threat model. `pyarrow.parquet.read_table` is the standard reader; the fixed v1 schema (D-12) means unexpected columns simply aren't referenced |

## Sources

### Primary (HIGH confidence)
- **Installed `rosbags` 0.11.2 source + `inspect.signature`** — Writer/`add_connection`/`write` signatures for ROS1 & ROS2, `StoragePlugin`, `Connection`/`ConnectionExt*`/`MessageDefinition` NamedTuples, typestore `cdr_to_ros1`/`ros1_to_cdr`/`serialize_*`/`generate_msgdef`. [VERIFIED via project venv]
- **`.venv/.../rosbags/convert/converter.py`** (read in full) — `convert()`, `create_connections_converters`, `generate_message_converter`, `is_same_wireformat`, `migrate_message`, `migrate_bytes`, `STATIC_MSGTYPE_RENAMES`, `is2 = dst.suffix != '.bag'`. The authoritative cross-format reference.
- **Direct experiments against project fixtures** (`tools/make_fixtures.py` bags) — raw-copy round-trip (ROS2 sqlite→sqlite, sqlite→MCAP) re-opens+deserializes; convert ROS1→ROS2 (deser→reser) PASS; convert ROS2→ROS1 naive FAIL (`seq`) and library/seq-patch PASS; multi-bag merge time-ordered; mixed-format merge rejected; events sidecar write/read/append; events-table reserved-name + interval join end-to-end.
- **Project source** — `reader/rosbags_reader.py`, `reader/base.py`, `output/export.py`, `backend/query.py`, `backend/resolve.py`, `backend/base.py`, `backend/duckdb_backend.py`, `errors.py`, `bagq/cli.py`, `tests/test_offline_guard.py`, `tests/conftest.py`, `schema/names.py`. [VERIFIED by reading]
- **`uv.lock` / `pyproject.toml`** — version pins (`rosbags>=0.11,<0.12` → 0.11.2; duckdb 1.5.3; pyarrow 24.0.0; sqlglot 30.8.0; coverage gate `--cov-fail-under=80`). [VERIFIED]
- **`.planning/phases/11-edit-events/11-CONTEXT.md`** — locked decisions D-01..D-15. [Authoritative]

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — Phase 9 tf-in-core precedent (subcommand, no pyproject/console-script edits), Phase 7 teaching-error pattern, offline-guard discipline.

### Tertiary (LOW confidence)
- None — all load-bearing claims were verified by experiment or source reading; no unverified web sources were relied upon.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version pinned and verified importable; no new deps; module-level findings (`rosbags.convert`) read from source.
- Architecture: HIGH — raw-copy, convert, merge, sidecar I/O, and events-table join all proven by direct experiment against the installed library and real fixtures.
- Pitfalls: HIGH — the `seq` cross-format failure, mixed-format merge rejection, and dotted-directory sidecar bug were each reproduced; the offline-invariant and Writer-signature pitfalls come from project source + `inspect`.

**Research date:** 2026-05-23
**Valid until:** 2026-06-22 (30 days — stable; the only volatility is a future `rosbags` major bump, pinned out by `<0.12`).
