# Phase 5: Query Engine - Research

**Researched:** 2026-05-22
**Domain:** SQL-over-Arrow query execution (DuckDB) + SQL parsing/topic resolution (sqlglot) behind a swappable backend seam
**Confidence:** HIGH

## Summary

Phase 5 builds the `QueryBackend` seam (DuckDB default) that ties together three pieces already shipped in Phases 2-4: the `RosbagsReader` (reads messages), the Phase 3 schema layer (`build_table_schema` + `build_arrow_table` → typed `pyarrow.Table`), and the topic→table_name mapping (`inspect.collect_table_schemas` / `TableNameResolver`). The new work is: (1) parse the user's SQL with `sqlglot` to find which **tables** and **columns** it references, (2) invert the topic→table map to learn which **topics** to load, (3) load **only those topics** into Arrow tables, (4) register each as a named relation in DuckDB and execute the SQL, returning a `pyarrow.Table`. All three success criteria were verified end-to-end this session against the real ROS2-sqlite fixture bag with `duckdb 1.5.3 / sqlglot 30.8.0 / pyarrow 24.0.0`.

Two findings materially shape the plan. **First**, the carry-forward WR-01 crash is **real and reproducible** [VERIFIED: this session]: a message body field literally named `t`/`t_ns`/`stamp`/`topic` produces a `TableSchema` with duplicate column names, and the failure is more subtle than "ArrowInvalid" — `pa.schema()` *allows* duplicate names and DuckDB *silently* auto-renames them (`topic`→`topic_1`), but `build_arrow_table`'s name-keyed `values` dict collapses 8 columns into 5 keys and then raises `ArrowTypeError` when it feeds a body uint8 value into the standard string `topic` column. The fix belongs in `schema/flatten.build_table_schema`: rename any **body** column whose dotted name collides with a reserved standard name (or a prior body name) before constructing `ColumnDef`s — verified working with a suffix scheme that keeps `ros_path` intact so values still extract.

**Second**, achieving success-criterion #2 ("only topics referenced are loaded") **the right way requires a small reader change**. `RosbagsReader.read()` reads and *deserializes* all topics; filtering its output (`if m.topic == X`) still pays full deserialization for every other topic. But the underlying `AnyReader.messages(connections=[...])` accepts a connection filter that yields *only* the selected topics' raw messages — verified to never touch other topics. The clean solution is to add a `connections=`/topic-filter parameter to `RosbagsReader.read()` (or expose a connection-filtered read path) so the backend deserializes only referenced topics.

**Primary recommendation:** In `backend/`, define a `QueryBackend` Protocol/ABC (`register_table(name, arrow)`, `execute(sql) -> pyarrow.Table`, context-manager `close()`), implement `DuckDBBackend` over an in-memory `duckdb.connect()`, and add a top-level orchestrator `query(sql, reader)` that: parses SQL → resolves referenced tables/columns via sqlglot → inverts the topic↔table map → loads only referenced topics (connection-filtered read) → registers each Arrow table → executes → returns Arrow. Use `to_arrow_table()` (NOT the deprecated `fetch_arrow_table()`). Fix WR-01 in `schema/flatten.py` as a prerequisite task with a regression test.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SQL parsing / table+column extraction | `backend/` (resolver) | `schema.identifiers` (quoting) | sqlglot lives behind the backend boundary; identifier quoting already isolated in Phase 3 |
| topic→table mapping + inversion | `backend/` orchestrator | `inspect.collect_table_schemas` (source of truth) | Phase 4 already builds topic→table via shared `TableNameResolver`; Phase 5 reuses and inverts it |
| Load only referenced topics | `reader/` (connection filter) | `backend/` orchestrator drives it | Connection-level filtering is the reader's job (`AnyReader.messages(connections=)`); the backend decides *which* topics |
| Arrow table build per topic | `schema/` (`build_arrow_table`) | — | Already shipped in Phase 3; Phase 5 only supplies the `include` set |
| SQL execution → Arrow | `backend/` (`DuckDBBackend`) | — | DuckDB embedded engine; the only tier that imports `duckdb` |
| Heavy-blob include-set decision | `backend/` resolver | `schema` honors `include=` | Phase 5 computes the column-reference set from SQL; `build_arrow_table`/`arrow_schema` already accept `include=` |
| Reserved-name collision fix (WR-01) | `schema/flatten.py` | — | The duplicate-name defect originates at schema build; must be fixed at the source, not papered over in the backend |

**Why this matters:** The offline invariant (`import rosbagger_core` must stay light) means `duckdb`/`sqlglot` may only be imported *inside* `backend/` modules and inside the functions that use them — never at the top level of `rosbagger_core/__init__`. The seam boundary is also the import boundary.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `duckdb` | 1.5.3 (installed; constraint `>=1.4,<2`) | Embedded SQL engine; registers Arrow tables zero-copy, runs SQL, returns Arrow | Locked by design spec decision 6 + CLAUDE.md; native `LIST`/`STRUCT`, `TIMESTAMP_NS`, Parquet/CSV export |
| `sqlglot` | 30.8.0 (installed; constraint `>=27,<31`) | Parse SQL → extract referenced tables (`exp.Table`) and columns (`exp.Column`); identifier quoting | Pure-Python, dialect-aware (duckdb), already used in Phase 3 `quote_ident` |
| `pyarrow` | 24.0.0 (installed; constraint `>=18`) | The neutral data interchange — `build_arrow_table` output, DuckDB register input, query result | The backend-neutral contract between schema layer and any backend |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `rosbags` | 0.11.2 (installed) | `RosbagsReader` / `AnyReader` — message source; `AnyReader.messages(connections=)` for topic filtering | Loading topics; the connection filter is the key to lazy loading |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DuckDB | Polars `SQLContext` / SQLite | The whole point of the seam (decision 6) is swappability — but DuckDB is the v1 default; do not build a second backend now (YAGNI) |
| sqlglot table extraction | regex / `str.split` | Brittle — fails on CTEs, subqueries, quoting, JOINs; sqlglot is already a locked dep and handles all of these (verified) |

**Installation:** All required packages are already declared in `packages/rosbagger-core/pyproject.toml` (`duckdb>=1.4,<2`, `sqlglot>=27,<31`, `pyarrow>=18`) and installed in `.venv`. **No new dependencies needed for Phase 5.**

**Version verification (this session, `.venv/bin/python`):**
```
duckdb   1.5.3      [VERIFIED: importlib]
sqlglot  30.8.0     [VERIFIED: importlib]
pyarrow  24.0.0     [VERIFIED: importlib]
rosbags  0.11.2     [VERIFIED: importlib.metadata]
python   3.10.12    [VERIFIED]
```

## Package Legitimacy Audit

> No new external packages are installed in Phase 5. All three core libraries are pre-existing, pre-installed, locked dependencies already exercised by Phases 1-4 (`sqlglot`/`pyarrow` in Phase 3, `duckdb` newly *used* here but already declared and installed). slopcheck was not run because no install occurs; the registry-existence + active-use of these packages across prior phases is sufficient.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| duckdb | PyPI | mature (1.x) | very high | github.com/duckdb/duckdb | n/a (no install) | Approved — already installed/locked |
| sqlglot | PyPI | mature | high | github.com/tobymao/sqlglot | n/a (no install) | Approved — already installed/locked, used in Phase 3 |
| pyarrow | PyPI | mature | very high | github.com/apache/arrow | n/a (no install) | Approved — already installed/locked, used in Phase 3 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
   user SQL string ("SELECT t_ns, \"linear.x\" FROM cmd_vel WHERE ...")
        │
        ▼
  ┌─────────────────────────── query(sql, reader) ───────────────────────────┐
  │ orchestrator (top-level fn, e.g. rosbagger_core.query or backend.run)     │
  │                                                                            │
  │  1. sqlglot.parse_one(sql, dialect="duckdb")                               │
  │       ├── find_all(exp.Table)  ─ minus ─ find_all(exp.CTE) alias names     │
  │       │      → {referenced table_names}                                    │
  │       └── find_all(exp.Column) / find_all(exp.Star)                        │
  │              → {referenced column names}  (Star ⇒ "all columns")           │
  │                                                                            │
  │  2. build topic↔table map from reader  (reuse inspect.collect_table_schemas│
  │       logic: shared TableNameResolver over sorted topics)                  │
  │       └── invert: table_name → topic   (unknown table_name ⇒ raise)        │
  │                                                                            │
  │  3. for each referenced topic:                                            │
  │       schema = build_table_schema(msgtype, typestore, topic=topic)         │
  │       include = heavy-blob column names this SQL references (Star ⇒ all)    │
  │       msgs = reader.read(topics={topic})  ◄── connection-filtered (lazy)    │
  │       arrow = build_arrow_table(msgs, schema, include=include)             │
  │       backend.register_table(table_name, arrow)                            │
  │                                                                            │
  │  4. result_arrow = backend.execute(sql)   ── DuckDB ──► pyarrow.Table      │
  └────────────────────────────────────────────────────────────────────┬─────┘
                                                                         ▼
                                                              pyarrow.Table result
                                                       (Phase 6 writes CSV/Parquet/plot;
                                                        Phase 7 CLI renders / teaches errors)

  QueryBackend seam (backend/):
     ┌──────────────────────────────┐
     │ QueryBackend (ABC/Protocol)  │  register_table(name, arrow) / execute(sql)->Table / close()
     └──────────────┬───────────────┘
                    │ default impl
     ┌──────────────▼───────────────┐    future: PolarsBackend / SQLiteBackend / rosbag2_py-fed
     │ DuckDBBackend                │            (slot in behind the same ABC — decision 6)
     │ duckdb.connect() (in-memory) │
     └──────────────────────────────┘
```

File-to-implementation mapping is in Component Responsibilities below.

### Component Responsibilities

| Concern | Where it lives | Notes |
|---------|---------------|-------|
| `QueryBackend` ABC/Protocol | `backend/base.py` (new) | Mirror `reader/base.py` style: abstract `register_table` / `execute` / `close` + inherited `__enter__`/`__exit__` |
| `DuckDBBackend` | `backend/duckdb_backend.py` (new) | `import duckdb` here only; wraps in-memory connection |
| SQL resolver (tables + columns) | `backend/resolve.py` (new) or inside orchestrator | `import sqlglot`/`from sqlglot import exp` here only |
| Orchestrator `query(sql, reader)` | `backend/__init__.py` or a new `query.py` | Ties resolve → topic load → register → execute. **Lazy-imports** the heavy stack so `import rosbagger_core` stays light |
| topic↔table map | reuse `inspect.collect_table_schemas` + `TableNameResolver` | Source of truth already exists; do not reinvent the sanitization |
| Connection-filtered read | `reader/rosbags_reader.py` (small edit) | Add a `topics=`/`connections=` param to `read()` → forward to `AnyReader.messages(connections=...)` |
| WR-01 collision fix | `schema/flatten.py` (`build_table_schema`) | Rename colliding body columns; add regression test |

### Pattern 1: Register an Arrow table as a named DuckDB relation, query → Arrow
**What:** Register each loaded topic's `pyarrow.Table` under its sanitized table name on an in-memory connection, run the SQL, return Arrow.
**When to use:** The core `DuckDBBackend.register_table` + `execute` implementation.
**Example:**
```python
# Source: VERIFIED this session (duckdb 1.5.3) + CITED duckdb.org/docs guides/python/sql_on_arrow
import duckdb
import pyarrow as pa

con = duckdb.connect()                       # in-memory; lifecycle owned by the backend
con.register("cmd_vel", arrow_table)         # zero-copy view named "cmd_vel"
# ... register every referenced topic's table ...
result: pa.Table = con.execute(sql).to_arrow_table()   # NOT fetch_arrow_table (deprecated)
con.close()
```
- `con.register(name, arrow)` creates a queryable view (verified: multi-register + cross-table JOIN works on one connection).
- `to_arrow_table()` is the current method; `fetch_arrow_table()` is **deprecated** in 1.5.3 (emits `DeprecationWarning`) [VERIFIED: this session] [CITED: duckdb.org Export to Apache Arrow].
- `.arrow` and `.fetchall()` also exist; `.fetchall()` returns Python tuples (useful only if a backend wants rows, but the seam returns Arrow).

### Pattern 2: Extract referenced base tables with sqlglot (CTE-safe)
**What:** Parse SQL, collect `exp.Table` names, subtract CTE alias names so a CTE is never mistaken for a topic table.
**When to use:** Step 1 of the orchestrator (QURY-05 table resolution).
**Example:**
```python
# Source: VERIFIED this session (sqlglot 30.8.0)
import sqlglot
from sqlglot import exp

def referenced_tables(sql: str, dialect: str = "duckdb") -> set[str]:
    tree = sqlglot.parse_one(sql, dialect=dialect)
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name not in cte_names}
```
- `exp.Table.name` returns the bare base-table name; `.db` is the schema qualifier (e.g. `main.imu` → `.name == "imu"`, `.db == "main"`) — use `.name`.
- Aliases (`FROM imu AS a`) correctly resolve to `imu`, not `a` (verified).
- JOINs, subqueries, UNION all return the right base tables (verified).
- **Without the CTE subtraction**, `WITH fast AS (...) SELECT * FROM fast` returns `{'fast', 'cmd_vel'}` — `fast` is not a topic and would raise spuriously. The subtraction yields `{'cmd_vel'}` (verified).

### Pattern 3: Extract referenced columns for the heavy-blob `include` set (QURY-07 seam)
**What:** Collect `exp.Column` names from the SQL; if a heavy-blob column (e.g. `data`) is named, add it to the `include=` set passed to `build_arrow_table`. A `SELECT *` (an `exp.Star`) means "include everything for that topic, heavy blobs too."
**When to use:** Step 3 of the orchestrator — computing `include` per topic.
**Example:**
```python
# Source: VERIFIED this session (sqlglot 30.8.0)
from sqlglot import exp

def referenced_columns(tree) -> set[str]:
    return {c.name for c in tree.find_all(exp.Column)}

def has_star(tree) -> bool:
    return bool(list(tree.find_all(exp.Star)))
```
- A quoted dotted column `"linear.x"` parses to `exp.Column.name == "linear.x"` — exactly the dotted ROS column name the schema uses (verified). This is why the heavy-blob `include` key being the dotted column name (Phase 3 decision) lines up perfectly.
- **`SELECT *` produces NO `exp.Column` nodes** but does produce an `exp.Star` (verified). The orchestrator MUST detect `Star` and treat it as "include the heavy blob(s) for any topic touched by that star" — otherwise `SELECT * FROM image` would silently drop `image.data`. (Design decision for the planner: `SELECT *` materializes heavy blobs.)
- A column qualified to a table (`cmd_vel.data`) exposes `.table == "cmd_vel"` — use this when only some referenced topics should get a given blob.

### Pattern 4: Invert the topic→table map; raise on unknown table (QURY-05)
**What:** Phase 3/4 give `topic → table_name` (deterministic, sorted, collision-resolved). Build the full per-bag map, invert it, and look up each SQL table name; an unmapped table name raises a clear error.
**When to use:** Step 2 of the orchestrator.
**Example:**
```python
# Source: VERIFIED this session (mirrors inspect.collect_table_schemas)
from rosbagger_core.schema import TableNameResolver

def topic_table_maps(reader):
    resolver = TableNameResolver()
    topic_to_table, topic_to_msgtype = {}, {}
    for topic, info in sorted(reader.topics.items()):
        if info.msgtype is None:        # multi-msgtype topic — skip (Phase 4 precedent)
            continue
        topic_to_table[topic] = resolver.resolve(topic)
        topic_to_msgtype[topic] = info.msgtype
    table_to_topic = {v: k for k, v in topic_to_table.items()}
    return topic_to_table, table_to_topic, topic_to_msgtype
```
- Inversion is safe because `TableNameResolver` guarantees unique table names (collisions get `_2`, `_3` suffixes), so `{v: k}` never drops a topic (verified on fixtures: `{'cmd_vel':'/cmd_vel','image':'/image','imu':'/imu'}`).
- **Unknown table name** (a SQL table that maps to no topic): raise a clear `ValueError`/custom error listing available table names. **v1 just raises** — Phase 7 owns the "did-you-mean" teaching errors (CLI-02). Note: DuckDB itself would also raise `CatalogException` ("Table ... does not exist! Did you mean ...") if you skipped resolution, but resolving up-front gives a better message and avoids loading nothing.

### Pattern 5: Load ONLY referenced topics via connection filtering (success-criterion #2)
**What:** Read only the messages of referenced topics by passing a connection filter, so unreferenced topics are never deserialized.
**When to use:** Step 3 — the lazy-load that satisfies "only topics referenced are loaded."
**Example:**
```python
# Source: VERIFIED this session (rosbags 0.11.2 AnyReader.messages signature)
# AnyReader.messages(connections=(), start=None, stop=None) -> (Connection, t_ns, bytes)
conns = [c for c in reader.connections if c.topic in referenced_topics]
for connection, t_ns, raw in reader._reader.messages(connections=conns):
    msg = reader._reader.deserialize(raw, connection.msgtype)
    # ... build Message, accumulate per topic ...
```
**Recommended:** add a parameter to `RosbagsReader.read()` (e.g. `read(self, *, topics: set[str] | None = None)`) that forwards a connection filter to `AnyReader.messages(connections=...)`, so the backend uses the public seam rather than reaching into `reader._reader`. This keeps the `BagReader` ABC honest and avoids leaking the `rosbags` internal.

### Anti-Patterns to Avoid
- **Filter-after-read (`for m in reader.read(): if m.topic == X`)** — this deserializes EVERY topic's messages and only then discards them. It produces correct *results* but **violates success-criterion #2** ("only topics referenced are loaded"). Verified: a `/cmd_vel`-only query under this approach still deserialized `/cmd_vel`, `/image`, `/imu`. Use connection filtering instead.
- **Hand-concatenating identifiers into SQL** (`f'SELECT * FROM {table}'`) — use `schema.identifiers.quote_ident` (already shipped, sqlglot-based, injection-safe). The *user's* SQL is the trusted interface; the untrusted input is the table/column names derived from bag content.
- **Using `fetch_arrow_table()`** — deprecated in duckdb 1.5.3; use `to_arrow_table()`.
- **Naively trusting `find_all(exp.Table)`** — it includes CTE alias names; always subtract `exp.CTE` aliases (Pattern 2).
- **Importing `duckdb`/`sqlglot` at `rosbagger_core/__init__` top level** — breaks the offline-import guard's lightness goal. Import inside `backend/` modules / inside functions (the established pattern).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Find tables/columns in SQL | regex / manual tokenizer | `sqlglot.parse_one(...).find_all(exp.Table / exp.Column / exp.Star)` | Handles CTEs, subqueries, JOINs, aliases, quoting, dialects — verified; a regex breaks on the first CTE |
| Quote identifiers safely | `f'"{name}"'` | `schema.identifiers.quote_ident` (already shipped) | Escapes embedded quotes (injection-safe); the f-string form is the documented anti-pattern |
| Multi-bag merge / time order | manual heap-merge | `AnyReader` (already merges) | `RosbagsReader.read()` is already globally time-ordered across bags |
| topic→table_name sanitization | re-sanitize here | `TableNameResolver` / `sanitize_table_name` (Phase 3) | Deterministic, collision-resolved, case-insensitive; reused by Phase 4 |
| ROS type → SQL type mapping | manual CAST table | `build_arrow_table` + DuckDB auto-mapping | Arrow→DuckDB types round-trip exactly (verified); no manual casts |
| Lazy heavy-blob exclusion | custom column skipping | `build_arrow_table(..., include=...)` (Phase 3) | The `include=` seam already exists; Phase 5 only computes the set |

**Key insight:** Phase 5 is overwhelmingly *integration* of already-built, already-tested pieces. The only genuinely new logic is (a) SQL→reference resolution (sqlglot, ~30 lines), (b) the DuckDB register/execute wrapper (~30 lines), (c) the orchestrator wiring, (d) the WR-01 schema fix, and (e) a `read(topics=...)` filter. Resist rebuilding anything the schema/reader layers already do.

## Runtime State Inventory

> Phase 5 is a pure code-addition phase (new `backend/` modules, a small `schema/flatten.py` fix, a small `reader/read()` parameter). It introduces **no** stored data, no live-service config, no OS-registered state, no secrets/env vars, and no renamed strings. The fixture bags are generated fresh per test run (gitignored). N/A — verified by reading the full source tree and the make_fixtures generator.

## Common Pitfalls

### Pitfall 1: Reserved-name column collision (WR-01) — duplicate columns, silent or crashing
**What goes wrong:** A message body field named `t`, `t_ns`, `stamp`, or `topic` collides with the four standard columns `build_table_schema` prepends. The resulting `TableSchema.columns` has duplicate `name`s.
**Why it happens:** `build_table_schema` prepends the four standard columns, then appends body columns by their dotted name with no collision check. Phase 1 fixtures don't trigger it; Phase 5 runs `build_arrow_table` on **arbitrary user bags**, making it reachable.
**Exact failure (VERIFIED this session):**
- `pa.schema()` *accepts* duplicate field names — no error there.
- DuckDB *silently auto-renames* on register (`topic`→`topic_1`, `stamp`→`stamp_1`) — wrong/confusing columns, no error.
- `build_arrow_table` builds a **name-keyed** `values` dict that collapses 8 columns into 5 unique keys, then `pa.array(values['topic'], type=string)` receives the body's uint8 value → `pyarrow.lib.ArrowTypeError: Expected bytes, got a 'int' object`. (Schema `['t','t_ns','stamp','topic','topic','stamp','t','value']` → values dict keys `['t','t_ns','stamp','topic','value']`.)
**How to avoid (recommended fix):** In `schema/flatten.build_table_schema`, after computing the body leaf name, **rename any body column whose name collides with a reserved standard name OR a prior body name** (suffix `_` until unique), keeping `ros_path` unchanged so the value still extracts. VERIFIED working: schema becomes `['t','t_ns','stamp','topic','topic_','stamp_','t_','value']`, body values land in `topic_`/`stamp_`/`t_`, standard columns keep the log time / topic string, DuckDB query succeeds. This is a ~5-line change in `build_table_schema` plus a regression test (build a custom `evil_msgs/msg/Collide` with fields `topic`/`stamp`/`t` via `rosbags.typesys.get_types_from_msg`, assert unique names + correct values).
**Alternative considered:** namespace the standard columns instead (e.g. `_t`, `_topic`) — rejected: it changes the public column names every existing test and the design spec depend on (`t`/`t_ns`/`stamp`/`topic` are the documented always-present columns, QURY-04). Renaming the *body* collision is the minimal, backward-compatible fix.
**Warning signs:** any test that builds a table from a bag whose body has a `t`/`topic`/`stamp` field; an `ArrowTypeError` mentioning "Expected bytes, got a 'int'" or duplicate names in `arrow_schema().names`.
**Note for planner:** Also fix the **name-keyed collapse** robustness in `build_arrow_table`/`flatten_message`. Once `build_table_schema` guarantees unique names, the existing name-keyed dicts are safe again — so the single fix at schema-build time resolves all three layers. No change to `build_arrow_table` is strictly required once names are unique (verified), but add an assertion or comment noting the unique-name invariant it now relies on.

### Pitfall 2: Filtering after read still deserializes everything (success-criterion #2)
**What goes wrong:** Loading topics with `for m in reader.read(): if m.topic in referenced: ...` deserializes every message of every topic — the unreferenced ones are decoded then thrown away.
**Why it happens:** `RosbagsReader.read()` has no topic filter; it calls `AnyReader.messages()` with no `connections` arg and deserializes each message in the loop.
**How to avoid:** Use `AnyReader.messages(connections=[...])` (verified: yields only the selected topics). Add a `topics=`/`connections=` parameter to `RosbagsReader.read()` and forward it. **Verification for the success criterion:** open the 3-topic fixture, query one topic, and assert (e.g. via a counting/instrumented reader or by checking `connections` passed) that the other two topics' messages were never deserialized.
**Warning signs:** a "lazy load" test that passes on result correctness but a memory/IO assertion that fails; deserialization of `/image` (heavy blob) when only `/cmd_vel` was queried.

### Pitfall 3: `SELECT *` drops heavy blobs
**What goes wrong:** `SELECT * FROM image` references no explicit columns, so a naive "include heavy blob iff its name appears in `exp.Column`" rule excludes `image.data` — the user asked for everything but got everything-minus-blob.
**Why it happens:** `SELECT *` emits an `exp.Star`, not `exp.Column` nodes (verified).
**How to avoid:** Detect `exp.Star` (Pattern 3) and, for any topic touched by a star, pass `include=` covering that topic's heavy-blob columns. Decision for the planner: **`SELECT *` materializes heavy blobs** (the user explicitly asked for all columns).
**Warning signs:** `SELECT * FROM image` returns a table missing the `data` column.

### Pitfall 4: Empty result sets and empty topics
**What goes wrong:** A `WHERE` that matches nothing, or a query over a topic with zero messages.
**Why it happens:** Normal SQL semantics.
**How to avoid:** Nothing special — verified that DuckDB returns a 0-row `pyarrow.Table` with the **full schema preserved** (`to_arrow_table()` on an empty result keeps all column names/types). `build_arrow_table([], schema)` also yields a typed empty table (Phase 3 already handles this). The orchestrator and Phase 6 writers must accept 0-row tables.
**Warning signs:** code that indexes `result[0]` or assumes ≥1 row.

### Pitfall 5: DuckDB connection lifecycle
**What goes wrong:** Leaked connections, or querying after `unregister`/`close`.
**Why it happens:** Per-query connection not closed; or reusing a closed connection.
**How to avoid:** The `DuckDBBackend` owns one in-memory `duckdb.connect()` per query (or per backend instance) and closes it via the context-manager `__exit__`/`close()`. Verified: `con.close()` is clean; after `unregister`, the relation raises `CatalogException` (so don't unregister mid-query). Recommend the orchestrator use `with DuckDBBackend() as backend:` so cleanup is guaranteed even on error.
**Warning signs:** `ResourceWarning` on unclosed connections in tests; `CatalogException` from a stale relation.

### Pitfall 6: Nanosecond timestamp display (a Phase 6 concern, flagged here)
**What goes wrong:** `pyarrow`'s `timestamp[ns]` column raises `ValueError: Nanosecond ... not safely convertible to microseconds` when `.to_pylist()` is called in pure Python (no pandas), for ns values outside microsecond resolution.
**Why it happens:** Python's `datetime` has microsecond resolution; pyarrow refuses lossy conversion in `as_py()`/`to_pylist()` without pandas.
**How to avoid:** This is **NOT a query-engine problem** — DuckDB keeps and round-trips `TIMESTAMP_NS` natively, and Arrow→Arrow is lossless (verified). It only bites the **output layer (Phase 6)** if it calls `.to_pylist()` on a `t`/`stamp` column. Flag for Phase 6: use `t_ns` (BIGINT) for display, or cast/format ns explicitly, or rely on DuckDB's own formatting. Phase 5's backend returns Arrow untouched, so it is unaffected — but the planner should note this so Phase 5 tests that *display* results use `t_ns` rather than `to_pylist()` on `t`.
**Warning signs:** a Phase 5 test that prints `table.column("t").to_pylist()` crashing on a real ns timestamp.

## Code Examples

### DuckDB Arrow type round-trip (matches Phase 3 documented mapping)
```python
# Source: VERIFIED this session (duckdb 1.5.3, DESCRIBE on a registered Arrow table)
# Arrow type            -> DuckDB type
# timestamp("ns")       -> TIMESTAMP_NS
# int64()               -> BIGINT
# string()              -> VARCHAR
# float64()             -> DOUBLE
# uint32()              -> UINTEGER
# uint64()              -> UBIGINT      (max value 18446744073709551615 round-trips, no overflow)
# list_(float64())      -> DOUBLE[]     (LIST; 1-indexed: cov[1] is the first element)
# list_(struct(...))    -> STRUCT[]     (LIST of STRUCT)
```

### End-to-end orchestration (the shape Phase 5 implements)
```python
# Source: VERIFIED end-to-end this session against the ROS2-sqlite fixture
import duckdb
from rosbagger_core.schema import build_table_schema, build_arrow_table, TableNameResolver
from rosbagger_core.schema.identifiers import quote_ident
# 1. resolve (Pattern 2/3)  2. invert map (Pattern 4)  3. lazy-load (Pattern 5)
with RosbagsReader(bag) as reader:
    ts = reader.typestore
    # ... build topic_to_table / table_to_topic / topic_to_msgtype (Pattern 4) ...
    referenced_topic = "/cmd_vel"                                  # from resolved tables
    schema = build_table_schema(topic_to_msgtype[referenced_topic], ts, topic=referenced_topic)
    msgs = (m for m in reader.read() if m.topic == referenced_topic)  # ◄ replace with topic-filtered read
    arrow = build_arrow_table(msgs, schema)                        # include= from Pattern 3
    con = duckdb.connect()
    con.register(topic_to_table[referenced_topic], arrow)
    sql = f'SELECT t_ns, {quote_ident("linear.x")} FROM {quote_ident("cmd_vel")} WHERE {quote_ident("linear.x")} > 0.5'
    result = con.execute(sql).to_arrow_table()                     # {'t_ns':[1100000000,1200000000],'linear.x':[1.0,2.0]}
    con.close()
```

### Missing table / column errors (DuckDB native — Phase 7 will improve)
```python
# Source: VERIFIED this session (duckdb 1.5.3)
# SELECT * FROM does_not_exist  -> duckdb.CatalogException:
#     "Table with name does_not_exist does not exist! Did you mean ..."
# SELECT nope FROM cmd_vel      -> duckdb.BinderException:
#     "Referenced column \"nope\" not found in FROM clause! Candidate bindings: ..."
# v1: let these propagate OR pre-resolve tables for a clearer message. Phase 7 owns the
# teaching "did-you-mean" (CLI-02/CLI-03). Phase 5 may raise a plain ValueError on an
# unmapped table name (lists available table names) and let column errors fall through.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `result.fetch_arrow_table()` | `result.to_arrow_table()` | DuckDB recent (≤1.x) | `fetch_arrow_table` deprecated; emits `DeprecationWarning` in 1.5.3 — use `to_arrow_table` [CITED: duckdb.org Export to Apache Arrow] |
| Manual SQL string parsing | `sqlglot` AST `find_all` | n/a (sqlglot mature) | CTE/subquery/JOIN-safe extraction; already a locked dep |

**Deprecated/outdated:**
- `fetch_arrow_table()` / `fetch_record_batch()` / `fetch_arrow_reader()` — replaced by `to_arrow_table()` / `to_arrow_reader()` [CITED: duckdb.org].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SELECT *` should materialize heavy blobs (treat `exp.Star` as "include all columns incl. blobs" for touched topics) | Pattern 3 / Pitfall 3 | If wrong, `SELECT *` would drop `data` columns silently; this is a design decision the planner/discuss should confirm. Low risk — "select all" intuitively means all. |
| A2 | The WR-01 fix should rename the **body** column (suffix), not the standard column | Pitfall 1 | Renaming standard columns instead would break QURY-04's documented `t`/`t_ns`/`stamp`/`topic` contract and many existing tests. The body-rename approach is verified working; the suffix scheme (`_`) is a choice the planner may refine (e.g. `_body` suffix or a documented prefix). |
| A3 | Adding a `topics=`/`connections=` parameter to `RosbagsReader.read()` is acceptable (vs. reaching into `reader._reader`) | Pattern 5 / Pitfall 2 | If the team prefers not to touch the reader seam, the orchestrator can use `reader._reader.messages(connections=...)` directly, but that leaks the `rosbags` internal. The public-seam approach is cleaner; confirm with the planner. |
| A4 | A plain `ValueError` (listing available tables) is acceptable for an unknown table name in v1 | Pattern 4 / Code Examples | Phase 7 owns teaching-errors (CLI-02). If the planner wants a typed exception now, define it in `backend/` — low risk either way. |

## Open Questions (RESOLVED)

*Resolved and threaded into the plans: Q1 → `query(sql, reader, *, backend=None) -> pyarrow.Table` lives in `backend/query.py`; Q2 → accepts an already-open `BagReader` (consistent with Phase 4); Q3 → one in-memory DuckDB connection per call (`with DuckDBBackend()`).*

1. **Where does the orchestrating `query()` live, and what is its signature?**
   - What we know: it must lazy-import the heavy stack; it ties resolve+load+execute together; the design spec describes it as the `bagq query` topic-resolution path.
   - What's unclear: whether it lives in `backend/__init__.py`, a new `backend/query.py`, or as a top-level `rosbagger_core.query` re-export (which would still be lazy-imported). The roadmap's 2-plan split (05-01 seam+DuckDB, 05-02 sqlglot resolution) suggests the resolver and orchestrator land in 05-02 on top of the 05-01 backend.
   - Recommendation: put the ABC + `DuckDBBackend` in `backend/` (05-01), and the resolver + `query(sql, reader)` orchestrator in `backend/query.py` (05-02), re-exported lazily. Signature `query(sql: str, reader: BagReader, *, backend: QueryBackend | None = None) -> pyarrow.Table` so the backend is swappable per call (defaulting to `DuckDBBackend`).

2. **Should `query()` accept a `reader` (already opened) or bag paths (open internally)?**
   - What we know: Phase 6 (output) and Phase 7 (CLI) are the consumers; the CLI takes `BAG...` paths.
   - What's unclear: whether the orchestrator opens the reader or receives an open one.
   - Recommendation: accept an **open `BagReader`** (consistent with `collect_bag_info`/`collect_table_schemas`, which all take an open reader). The CLI/Phase 7 owns the `with RosbagsReader(paths) as reader:` lifecycle. This keeps `query()` reader-backend-agnostic and testable.

3. **Per-query connection vs. per-backend connection.**
   - What we know: in-memory DuckDB connections are cheap; each query registers a fresh set of topic tables.
   - Recommendation: one connection per `query()` call (created in `DuckDBBackend.__init__`/context-enter, closed on exit). Stateless across queries — simplest and avoids stale-relation bugs (Pitfall 5).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| duckdb | SQL execution (QURY-06) | ✓ | 1.5.3 | — |
| sqlglot | table/column resolution (QURY-05) | ✓ | 30.8.0 | — |
| pyarrow | Arrow interchange | ✓ | 24.0.0 | — |
| rosbags | message reading + connection filter | ✓ | 0.11.2 | — |
| python | runtime | ✓ | 3.10.12 (`requires-python>=3.10`) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. (`matplotlib` is absent but is a Phase 6 `--plot`-only extra, not needed here.)

**Test-run note (carried from Phase 2-3 RESEARCH):** This dev host sources ROS 2 Humble onto `PYTHONPATH`, which can crash pytest on collection. Run Phase 5 tests with the host leak neutralized:
```bash
PYTHONPATH="" uv run pytest tests/test_backend_duckdb.py tests/test_backend_resolve.py -q
```
CI is ROS-free and needs no prefix. Never bake the prefix into committed code.

## Security Domain

> `security_enforcement` is not set in `.planning/config.json`; treating as the lighter posture appropriate to an **offline, single-user CLI on local files** (no network, no auth, no multi-tenant data). The relevant ASVS surface is narrow.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Offline CLI; no users/sessions |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Operates on files the invoking user already has OS access to |
| V5 Input Validation | yes | Untrusted bag content (topic strings, field names) → quoted via `sqlglot` `quote_ident` (Phase 3, already shipped). Untrusted message DATA flows Arrow→DuckDB as typed values, never as SQL text |
| V6 Cryptography | no | No secrets, no crypto |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via bag-derived identifiers (hostile topic / field name → table/column) | Tampering | `schema.identifiers.quote_ident` (sqlglot, escapes embedded quotes) — already shipped Phase 3; Phase 5 MUST route every interpolated identifier through it (Pattern 1, Anti-Patterns). VERIFIED: `'x"; DROP TABLE y;--'` → one quoted identifier |
| Malformed/huge bag data → memory blowup | Denial of Service | v1 loads referenced topics **fully** (per design spec — projection pushdown is QURY-09/v2). Document the memory tradeoff; connection-filtering already avoids loading unreferenced topics. Not a v1 blocker |
| User-supplied SQL itself | (by design) | The USER's SQL is the **intended interface**, not an injection vector — this is a local single-user CLI. The trust boundary is bag DATA and bag-derived NAMES, both handled above |

**Note:** The real, already-mitigated injection vector (topic/field names → identifiers) is fully owned by Phase 3's `quote_ident` + `TableNameResolver` allow-list. Phase 5's only security obligation is to **use** them on every interpolated identifier and never f-string a name into SQL.

## Sources

### Primary (HIGH confidence)
- **This session's empirical verification** (`.venv/bin/python`, duckdb 1.5.3 / sqlglot 30.8.0 / pyarrow 24.0.0 / rosbags 0.11.2 against the project's ROS2-sqlite fixture and a custom collision-repro bag): DuckDB Arrow register/query/types/errors/lifecycle; sqlglot table+column+CTE+Star extraction; topic↔table inversion; connection-level lazy filtering; the WR-01 crash repro AND the verified fix; the deprecated `fetch_arrow_table` warning.
- **Codebase** (read in full): `schema/{__init__,flatten,model,names,identifiers,types}.py`, `reader/{base,rosbags_reader,__init__}.py`, `inspect.py`, `backend/__init__.py`, `tools/make_fixtures.py`, `tests/{test_schema_arrow,test_offline_guard,conftest}.py`, all three `pyproject.toml`, `.planning/{REQUIREMENTS.md,config.json}`, design spec.
- **DuckDB official docs** — [Export to Apache Arrow](https://duckdb.org/docs/current/guides/python/export_arrow) and [SQL on Apache Arrow](https://duckdb.org/docs/current/guides/python/sql_on_arrow): confirms `to_arrow_table` is current and `fetch_arrow_table`/`fetch_record_batch`/`fetch_arrow_reader` are deprecated.

### Secondary (MEDIUM confidence)
- WebSearch result aggregation on the DuckDB Arrow API deprecation (cross-checked against the official docs links above).

### Tertiary (LOW confidence)
- None — all load-bearing claims were verified empirically this session or cited to official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified via `importlib` in the project venv; no new deps.
- Architecture: HIGH — every pattern (register/execute, table/column resolution, inversion, lazy connection-filter) executed successfully this session against real fixtures.
- Pitfalls: HIGH — WR-01 crash reproduced AND the fix verified working; the lazy-load gap, `SELECT *` blob drop, empty-set behavior, and ns-timestamp display quirk all empirically confirmed.

**Research date:** 2026-05-22
**Valid until:** 2026-06-21 (30 days; stable mature libraries, all versions locked in pyproject.toml)
