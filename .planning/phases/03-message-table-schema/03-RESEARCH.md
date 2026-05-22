# Phase 3: Message→Table Schema - Research

**Researched:** 2026-05-22
**Domain:** Flattening deserialized `rosbags` message objects into a backend-neutral, DuckDB-friendly table schema (dotted/quoted columns, LIST / LIST-of-STRUCT arrays, always-present time columns, sanitized table names, lazy heavy-blob handling)
**Confidence:** HIGH

## Summary

This phase turns each deserialized `rosbags` message (the `Message.msg` object produced by Phase 2's `RosbagsReader`) into a flat, columnar table description: one table per topic, nested scalars flattened to dotted/quoted columns (`"twist.linear.x"`), arrays as `LIST`, sub-message arrays as `LIST` of `STRUCT`, four always-present columns (`t`, `t_ns`, `stamp`, `topic`), sanitized + collision-resolved table names (`/camera/image_raw` → `camera_image_raw`), and heavy byte blobs (`Image.data`, `PointCloud2.data`) excluded by default. **It produces the schema and the per-row column values; it does NOT load DuckDB or run SQL — that is Phase 5.**

The single most valuable empirical finding: **`rosbags` exposes a clean, structured field-type AST via `typestore.get_msgdef(msgtype).fields`**, a list of `(field_name, FieldDesc)` tuples where `FieldDesc` is built from a 4-member `Nodetype` enum — `BASE` (scalar), `NAME` (sub-message), `ARRAY` (fixed-length), `SEQUENCE` (variable-length). This typestore AST — **not** the dataclass's `f.type` string and **not** runtime `isinstance` sniffing — is the authoritative, recursion-friendly source for the whole flattening algorithm, the type map, and heavy-blob detection. It is identical for ROS 1 and ROS 2 bags (one code path). The deserialized message itself is a `@dataclass` with a `__msgtype__` ClassVar; scalar values come back as native Python `int`/`float`/`str`/`bool` and array values come back as `numpy.ndarray` — both of which `pyarrow` ingests directly.

The second decisive finding: **emit Apache Arrow, not DuckDB SQL DDL.** A round-trip verified this session proved that a `pyarrow` Table with dotted column names, `timestamp('ns')`, `int64`, `uint64`, `list<double>`, and `list<struct<...>>` columns registers into DuckDB and produces *exactly* the spec's target types — `TIMESTAMP_NS`, `BIGINT`, `UBIGINT`, `DOUBLE[]`, `STRUCT(...)[]` — with zero hand-written DDL and full SQL access to quoted dotted columns and 1-indexed `LIST`/`STRUCT` element access. Arrow is `pyarrow` (already a locked dep), is what DuckDB ingests zero-copy, and keeps this phase **backend-neutral** (the swappable-`QueryBackend` seam). This phase should therefore output (a) a backend-neutral **column-spec / `ColumnDef` model** describing each table, and (b) the machinery to build a `pyarrow.Table` (or `RecordBatch`) per topic from a stream of `Message`s — leaving DuckDB registration to Phase 5.

**Primary recommendation:** Build a `schema/` module that, given a `msgtype` string + the reader's `typestore`, walks `get_msgdef(...).fields` recursively to produce (1) a list of flattened `ColumnDef(name, arrow_type, ros_path, is_heavy_blob)` plus the four prepended standard columns, and (2) a `pyarrow.Schema`. Provide a `sanitize_table_name()` + collision resolver, a `flatten_message(msg) -> dict[col_name, value]` row extractor that mirrors the same walk, and a heavy-blob predicate keyed on the structural pattern `SEQUENCE of (uint8|byte|char)`. Emit Arrow; never emit SQL DDL. All claims below are **VERIFIED** by running `rosbags` 0.11.2 + `duckdb` 1.5.3 + `pyarrow` 24.0.0 against this project's fixtures this session, unless tagged `[ASSUMED]`.

## User Constraints

No `CONTEXT.md` exists for this phase (no `/gsd:discuss-phase` was run). Constraints below are drawn from `CLAUDE.md`, `PROJECT.md`, the design spec (§4.1), `REQUIREMENTS.md`, and Phases 1–2's locked decisions — treat them with the same authority as locked decisions.

### Locked Decisions (from design spec / PROJECT.md / REQUIREMENTS.md)
- **One table per topic.** Table name = topic with leading `/` dropped and remaining `/` → `_` (`/camera/image_raw` → `camera_image_raw`). Collisions resolved with a uniqueness check; `bagq tables` (Phase 4) prints the mapping. (design spec §4.1, QURY-01)
- **Nested scalars → dotted, faithful, quoted column names** (`twist.twist.linear.x`). These require SQL quoting (`WHERE "twist.twist.linear.x" > 0.5`). The "alias pack" (`vx` → `"twist.twist.linear.x"`) is explicitly **deferred** (QURY-08, v2). (design spec §4.1 + §7, QURY-02)
- **Arrays → `LIST`; arrays of sub-messages → `LIST` of `STRUCT`.** (design spec §4.1, QURY-03)
- **Always-present columns:** `t` (`TIMESTAMP_NS`, log/receive time), `t_ns` (`BIGINT`, exact ns), `stamp` (`TIMESTAMP_NS` from `header.stamp`, else `NULL`), `topic` (raw string). (design spec §4.1, QURY-04)
- **Heavy byte blobs (`Image.data`, `PointCloud2.data`) materialized only if the query references them.** (design spec §4.1, QURY-07)
- **DuckDB is the DEFAULT backend, behind a swappable `QueryBackend` seam.** DuckDB chosen for embedded SQL + native Parquet/CSV + `LIST`/`STRUCT` types; must be swappable to Polars/SQLite without touching the rest. (design spec §3.3 principle 6, §4.1)
- **Offline / NO-ROS invariant (load-bearing):** offline packages must NEVER import `rclpy`, `rosbag2_py`, `rosidl_runtime_py`, or `ament_index_python`, directly or transitively (design spec §3.2; enforced by `tests/test_offline_guard.py`). `rosbags`, `duckdb`, `pyarrow`, `numpy` are all approved offline deps.
- **Keep `rosbagger_core/__init__.py` light** — do NOT import the heavy stack (`duckdb`, `pyarrow`, `sqlglot`, `rosbags`) at top level; defer into functions/submodules. (Phase 1 decision, `rosbagger_core/__init__.py` docstring)
- **Python ≥ 3.10** (`pyproject.toml requires-python`).

### Claude's Discretion
- The exact public API shape of the `schema/` module (function names, the `ColumnDef`/`TableSchema` container types, dataclass vs NamedTuple).
- Internal module layout under `rosbagger_core/schema/`.
- Whether the row-extraction walk and the schema-building walk share one recursive core or are two parallel walks (this research recommends a shared descriptor — see Pattern 4).
- The dotted-name separator policy for arrays-of-structs (whether sub-fields inside a `STRUCT` keep their short names — they should; only the *top-level* path is dotted — see Pitfall 4).
- Whether heavy-blob columns are *omitted from the schema entirely* by default vs *present-but-deferred* (this research recommends: present in the full `TableSchema` with an `is_heavy_blob` flag, but **excluded** from the default `pyarrow.Schema`/row build unless a caller-supplied `include` set names them — see Pattern 5; Phase 5 drives the `include` set from the parsed SQL).

### Deferred Ideas (OUT OF SCOPE for this phase)
- **DuckDB registration / running SQL / `QueryBackend` impl** — Phase 5 (QURY-05/06). This phase emits Arrow + schema; it must NOT `import duckdb` for execution. (You MAY reference DuckDB type names in docstrings/tests for clarity, and a *test* MAY register an Arrow table to assert the mapped DuckDB types, but the shipped `schema/` code stays backend-neutral.)
- **sqlglot topic resolution / which columns a query references** — Phase 5 (QURY-05). This phase provides the *mechanism* (an `include` parameter / heavy-blob predicate) Phase 5 will drive; it does not parse SQL.
- **Alias pack** (`vx` → `"twist.twist.linear.x"`) — QURY-08, v2.
- **Column projection pushdown** (load only referenced columns) — QURY-09, v2. (Distinct from QURY-07: QURY-07 is *only* about heavy byte blobs; QURY-09 is general projection.)
- **`bagq tables` rendering** of the schema — Phase 4 (INSP-03). This phase produces the schema object Phase 4 will render.
- **Output writers (CSV/Parquet/plot)** — Phase 6.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QURY-01 | Map each topic to one table with a sanitized name (`/camera/image_raw` → `camera_image_raw`) | VERIFIED algorithm: strip leading `/`, replace remaining `/` with `_`; then a collision resolver (lowercase-collision + empty-name + leading-digit edge cases). See Pattern 2 + Code Examples §1. sqlglot `to_identifier(name, quoted=True)` is the identifier-safety tool (Pattern 6). |
| QURY-02 | Flatten nested scalar fields to dotted, quoted columns (`"twist.twist.linear.x"`) | VERIFIED: recursive walk of `typestore.get_msgdef(msgtype).fields`; `Nodetype.BASE` → leaf column, `Nodetype.NAME` → recurse with `parent.child` prefix. Runtime values are native `int`/`float`/`str`/`bool`. See Pattern 4 + Code Examples §2/§3. |
| QURY-03 | Arrays → `LIST`; sub-message arrays → `LIST` of `STRUCT` | VERIFIED: `Nodetype.ARRAY` (fixed) and `Nodetype.SEQUENCE` (variable) both → Arrow `list_(...)`; inner `BASE` → `list<scalar>`, inner `NAME` → `list<struct<...>>`. `tf2_msgs/TFMessage.transforms`, `nav_msgs/Path.poses`, `PointCloud2.fields` are real LIST-of-STRUCT cases. Round-trips to DuckDB `DOUBLE[]` / `STRUCT(...)[]`. See Pattern 4 + Code Examples §3/§4. |
| QURY-04 | Always-present columns `t` (`TIMESTAMP_NS`), `t_ns` (`BIGINT`), `stamp`, `topic` | VERIFIED: prepend four columns; Arrow types `timestamp('ns')`/`int64`/`timestamp('ns')`(nullable)/`string` map to DuckDB `TIMESTAMP_NS`/`BIGINT`/`TIMESTAMP_NS`/`VARCHAR`. Values come straight off the `Message` record (`t`, `t_ns`, `stamp` (may be `None`), `topic`). `stamp` is the top-level column **and** `header.stamp` ALSO appears as nested `"header.stamp.sec"`/`"header.stamp.nanosec"` columns (no conflict — Pitfall 6). See Pattern 3 + Code Examples §5. |
| QURY-07 | Materialize heavy byte blobs (`Image.data`, `PointCloud2.data`) only when referenced | VERIFIED structural predicate: a field is a heavy blob iff its `FieldDesc` is `SEQUENCE of (uint8\|byte\|char)`. Cleanly excludes `Imu.orientation_covariance` (`ARRAY of float64`) and `String.data` (scalar string). Default schema/rows omit blobs; a caller-supplied `include` set (driven by Phase 5's parsed SQL) re-adds them. See Pattern 5 + Code Examples §6. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Field-type introspection (scalars/sub-msgs/arrays/blobs) | `rosbags` typestore (`get_msgdef(mt).fields`) | `schema/` walk | The typestore already parsed the `.msg`/`.idl` into a clean `Nodetype` AST; the schema layer *reads* it, never re-parses wire formats |
| ROS-type → Arrow-type mapping | `schema/` (this phase) | `pyarrow` | A pure lookup table from `Basename` literals → `pa.DataType`; this is the phase's core contribution |
| Flatten nested scalars → dotted column names | `schema/` (this phase) | — | Project logic: recursive name-prefixing; nothing upstream does this |
| Arrays → LIST / sub-msg arrays → LIST of STRUCT | `schema/` (this phase) | `pyarrow` (`list_`, `struct`) | Map the `ARRAY`/`SEQUENCE` AST nodes onto `pa.list_`/`pa.struct`; `pyarrow` owns the type objects |
| Always-present `t`/`t_ns`/`stamp`/`topic` columns | `schema/` (this phase) | `Message` record (Phase 2) | The four values are already on the `Message`; the schema layer prepends the columns + pulls the values |
| Table-name sanitization + collision resolution | `schema/` (this phase) | `sqlglot` (identifier quoting) | Project logic for the `/a/b`→`a_b` rule + uniqueness; `sqlglot.to_identifier(quoted=True)` for SQL-safe quoting |
| Heavy-blob detection + lazy exclusion | `schema/` (this phase) | Phase 5 (drives `include`) | Phase 3 owns the *predicate* + the `include` parameter; Phase 5 owns *deciding which columns the SQL references* |
| Build the columnar table object (Arrow) | `schema/` (this phase) | `pyarrow` | Emit a backend-neutral `pyarrow.Table`/`Schema`; this keeps the `QueryBackend` seam swappable |
| Register table + run SQL + return results | **Phase 5** (`QueryBackend`/DuckDB) | — | OUT OF SCOPE here — DuckDB ingests the Arrow this phase emits |
| Render the schema for humans (`bagq tables`) | **Phase 4** (Inspect) | — | OUT OF SCOPE here — Phase 4 reads the `TableSchema` object |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rosbags` | 0.11.2 (pinned `>=0.11,<0.12`) | The **introspection source**: `typestore.get_msgdef(msgtype).fields` gives the `Nodetype` field AST; `Nodetype` enum from `rosbags.interfaces` | Already locked + installed (Phases 1–2). The typestore is the *authoritative*, recursion-friendly field model — better than the dataclass `f.type` string or runtime `isinstance`. `[VERIFIED: installed runtime + PyPI]` |
| `pyarrow` | 24.0.0 (pinned `>=18`) | The **emission format**: build `pa.Schema` + `pa.Table`/`RecordBatch` per topic; `pa.timestamp('ns')`, `pa.int64`, `pa.list_`, `pa.struct`, etc. | Already locked. DuckDB ingests Arrow **zero-copy**; emitting Arrow keeps Phase 3 backend-neutral and gives Phase 5 the spec's exact DuckDB types for free. `[VERIFIED: installed runtime + round-trip into duckdb]` |
| `sqlglot` | (pinned `>=27,<31`, used in Phase 5) | Identifier quoting/escaping for table+column names: `sqlglot.exp.to_identifier(name, quoted=True).sql(dialect="duckdb")` | Already locked. The *correct* tool to render a dotted/odd column or table name as a SQL-injection-safe quoted identifier (escapes embedded `"`). `[VERIFIED: escapes `weird"name` → `"weird""name"`]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | 2.2.6 (transitive via `rosbags`) | Array field values deserialize to `numpy.ndarray` (`float64[9]` covariance, `uint8[]` data) | When extracting row values for `ARRAY`/`SEQUENCE` fields — `pa.array([ndarray])` builds the `list<>` directly. The schema layer does NOT need to `import numpy` itself (it just passes ndarrays through to `pyarrow`). |
| stdlib `dataclasses` | — | The `ColumnDef`/`TableSchema` containers (the phase's public model); also: deserialized msgs ARE dataclasses with a `__msgtype__` ClassVar | Define the schema model; (optionally) `dataclasses.fields(msg)` is an alternative introspection path but the typestore AST is recommended over it (Alternatives Considered) |
| stdlib `re` | — | Table-name sanitization (`/`→`_`, strip leading `/`, edge-case cleanup) | The `sanitize_table_name` helper |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `typestore.get_msgdef(mt).fields` (the `Nodetype` AST) | `dataclasses.fields(msg)` + parsing the `f.type` string (`'geometry_msgs__msg__Vector3'`, `'np.ndarray[...np.dtype[np.float64]]'`) | The dataclass route requires fragile string-parsing of `f.type` to tell scalar vs sub-msg vs array, and the array-element dtype is buried in a stringified annotation. The typestore AST is already structured (`BASE`/`NAME`/`ARRAY`/`SEQUENCE` + clean `Basename` literals). **Use the typestore AST.** (Both verified this session; the AST is strictly cleaner.) |
| `typestore.get_msgdef(mt).fields` | Runtime `isinstance` sniffing of the deserialized object | Runtime sniffing can't see the *declared* schema for empty sequences (an empty `transforms` list gives no element to sniff) and conflates `int8` vs `int32`. The declared AST gives a stable schema independent of any single message's values (Pitfall 1). **Use the AST for the schema; use runtime values only for row data.** |
| Emit `pyarrow` | Emit DuckDB SQL `CREATE TABLE ... (...)` DDL strings | DDL is DuckDB-specific (breaks the swappable-backend seam), can't carry nested STRUCT cleanly, and forces this phase to know DuckDB. Arrow is backend-neutral and DuckDB-ingestible zero-copy. **Emit Arrow.** |
| Emit `pyarrow` | Emit Polars / pandas DataFrames | DuckDB ingests Arrow most directly; Polars/pandas add a dep and a conversion. Arrow is the lingua franca DuckDB, Parquet (Phase 6), and Polars all speak. **Emit Arrow.** |
| `pa.schema([(name, type), ...])` built field-by-field | `pa.Table.from_pylist(rows)` (let Arrow infer) | Inference is unstable across messages (a topic whose first message has an empty list infers `list<null>`; later messages disagree → ArrowInvalid). **Build the schema explicitly from the typestore, then build arrays against it.** (Pitfall 1.) |

**Installation:** None required — `rosbags`, `pyarrow`, `sqlglot`, `duckdb` are all already in `packages/rosbagger-core/pyproject.toml` `dependencies` and `uv.lock`. `numpy` arrives transitively via `rosbags`. **Nothing to add.**

**Version verification (performed this session):**
```
rosbags  -> 0.11.2   (importlib.metadata; pinned >=0.11,<0.12)   VERIFIED
duckdb   -> 1.5.3    (duckdb.__version__; pinned >=1.4,<2)        VERIFIED
pyarrow  -> 24.0.0   (pyarrow.__version__; pinned >=18)           VERIFIED
numpy    -> 2.2.6    (numpy.__version__; transitive via rosbags) VERIFIED
```

## Package Legitimacy Audit

The phase installs **no new packages** — all four libraries were locked in Phase 1 and verified present this session. Audit run for completeness (`slopcheck` available; PyPI ecosystem):

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `rosbags` | PyPI | ~4 yrs | high (established) | gitlab.com/ternaris/rosbags | (OK — confirmed Phase 2) | Approved (already locked) |
| `pyarrow` | PyPI | ~9 yrs | very high (Apache Arrow) | github.com/apache/arrow | OK | Approved (already locked) |
| `duckdb` | PyPI | ~6 yrs | very high | github.com/duckdb/duckdb | OK | Approved (already locked) — *Phase 5 runtime; this phase keeps it out of shipped code* |
| `sqlglot` | PyPI | ~5 yrs | high | github.com/tobymao/sqlglot | OK | Approved (already locked) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> No `[ASSUMED]` package fallback needed — every dependency is a long-established, high-download Apache/major-OSS project already pinned in the locked `pyproject.toml`/`uv.lock`. No `npm`/cross-ecosystem confusion risk (pure PyPI).

## Architecture Patterns

### System Architecture Diagram

```
   Phase 2 reader stream                          (schema layer is given the typestore +
   ──────────────────────                          one msgtype string per topic, plus a
   RosbagsReader.read() ──► Message(               stream of Message records to turn into rows)
        topic, t, t_ns, stamp,                                  │
        msgtype, msg)  ───────────────────────────────┐        │
                                                       │        │
   reader.typestore (rosbags Typestore) ──────┐        │        │
                                               ▼        ▼        ▼
        ┌──────────────────────────────────────────────────────────────────────┐
        │                       rosbagger_core.schema                            │
        │                                                                        │
        │  (A) SCHEMA BUILD  (once per topic, from the DECLARED type)            │
        │      typestore.get_msgdef(msgtype).fields   ── Nodetype AST ──┐        │
        │        BASE   → scalar leaf      ─────────────────────────┐   │        │
        │        NAME   → recurse w/ "parent.child" dotted prefix    │  │        │
        │        ARRAY  → fixed   ─► pa.list_(elem)                  ▼  ▼        │
        │        SEQUENCE→ variable─► pa.list_(elem)         flatten walk        │
        │          inner BASE → list<scalar>                       │             │
        │          inner NAME → list<struct<...>>                  ▼             │
        │      heavy-blob predicate: SEQUENCE of uint8|byte|char   ColumnDef[]   │
        │                                              ┌───────────┤            │
        │      prepend 4 std cols: t,t_ns,stamp,topic ─┘           │            │
        │      sanitize_table_name(topic) + collision resolver     ▼            │
        │                                               TableSchema(name, cols) │
        │                                                          │            │
        │                              build pa.Schema  ◄──────────┘            │
        │                              (exclude heavy blobs unless `include`)   │
        │                                                                        │
        │  (B) ROW EXTRACT  (per Message, from RUNTIME values, same walk)        │
        │      flatten_message(msg) ─► {col_name: value}                         │
        │        scalar → int/float/str/bool                                     │
        │        sub-msg → recurse                                               │
        │        array  → numpy.ndarray (passed straight to pa.array)            │
        │      + t,t_ns,stamp,topic from the Message record                      │
        └──────────────────────────────────────────────────────────────────────┘
                                   │                         │
                 pa.Table (per topic, backend-neutral)   TableSchema object
                                   │                         │
                                   ▼                         ▼
                        Phase 5 QueryBackend          Phase 4 `bagq tables`
                        (register → DuckDB → SQL)     (render name + columns)
```

File-to-implementation mapping is in the Component Responsibilities table below, not in the diagram.

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/schema/
├── __init__.py        # light public API re-exports (TableSchema, ColumnDef,
│                      #   build_table_schema, sanitize_table_name, ...).
│                      #   May import pyarrow (heavy, but only loaded on
│                      #   `import rosbagger_core.schema`, NOT on `import rosbagger_core`).
├── names.py           # sanitize_table_name(topic) + a TableNameResolver (collision check).
│                      #   Pure stdlib (re); no pyarrow/rosbags import → trivially testable.
├── types.py           # ROS Basename → pa.DataType mapping; the recursive
│                      #   field-AST → (pa.DataType, is_heavy_blob) translator.
│                      #   Imports pyarrow + rosbags.interfaces.Nodetype.
├── flatten.py         # build_table_schema(msgtype, typestore, *, include=...) -> TableSchema
│                      #   + flatten_message(msg) -> dict; the dotted-name walk (schema + rows).
└── model.py           # ColumnDef / TableSchema dataclasses (the public, backend-neutral model).
```
(Layout is Claude's discretion; this split keeps `names.py` pyarrow-free for fast unit tests and isolates the type map.)

| Component | File | Responsibility |
|-----------|------|----------------|
| `ColumnDef` | `schema/model.py` | `(name: str, arrow_type, ros_path: tuple[str,...], is_heavy_blob: bool)` — one flattened column |
| `TableSchema` | `schema/model.py` | `(table_name: str, topic: str, msgtype: str, columns: list[ColumnDef])`; helpers: `arrow_schema(include=...)`, `column_names(include=...)` |
| `sanitize_table_name` | `schema/names.py` | `/a/b` → `a_b`; strip leading `/`, `/`→`_`, edge-case cleanup |
| `TableNameResolver` | `schema/names.py` | Maps topics→unique table names; resolves collisions deterministically |
| ROS→Arrow type map + AST translator | `schema/types.py` | `Basename`→`pa.DataType`; `FieldDesc`→`(pa.DataType, is_heavy_blob)` recursion |
| `build_table_schema` | `schema/flatten.py` | Walk `get_msgdef(mt).fields` → `TableSchema` (prepends the 4 std cols) |
| `flatten_message` | `schema/flatten.py` | Walk a deserialized msg → `{dotted_col: value}` row dict (mirrors the schema walk) |
| public exports | `schema/__init__.py` | Re-export the model + the build/flatten/sanitize entry points |

> **Offline-guard note:** Importing `pyarrow` inside `schema/` is SAFE — `pyarrow` is not a ROS module and the guard only blocks `rclpy`/`rosbag2_py`/`rosidl_runtime_py`/`ament_index_python`. Just keep `rosbagger_core/__init__.py` from importing the `schema` subpackage at top level (mirror the existing `reader` subpackage convention) so `import rosbagger_core` stays light and the guard test stays fast. The `schema` code may `import pyarrow` and `from rosbags.interfaces import Nodetype` freely. **Do NOT `import duckdb` in shipped `schema/` code** — that's Phase 5; it would also slow `bagq --help`.

### Pattern 1: Introspect via the typestore field-AST (not the dataclass string, not runtime sniffing)
**What:** Get the declared field structure from `typestore.get_msgdef(msgtype).fields`, a `list[tuple[str, FieldDesc]]`. `FieldDesc` is `(Nodetype, payload)`:
- `(Nodetype.BASE, (basename, bound))` — a scalar; `basename` ∈ the `Basename` literal set.
- `(Nodetype.NAME, "pkg/msg/Type")` — a nested sub-message (recurse via `get_msgdef`).
- `(Nodetype.ARRAY, (inner_FieldDesc, length))` — a **fixed**-length array.
- `(Nodetype.SEQUENCE, (inner_FieldDesc, bound))` — a **variable**-length array (`bound=0` = unbounded).
**When to use:** For ALL schema/type/blob decisions. It is identical for ROS 1 and ROS 2 bags (one path).
**Example:**
```python
# Source: VERIFIED against fixtures (sensor_msgs/msg/Imu) with rosbags 0.11.2 this session
from rosbags.interfaces import Nodetype   # NOT rosbags.typesys.base

md = typestore.get_msgdef("sensor_msgs/msg/Imu")
for field_name, ftype in md.fields:
    print(field_name, ftype)
# header                  (Nodetype.NAME, 'std_msgs/msg/Header')
# orientation             (Nodetype.NAME, 'geometry_msgs/msg/Quaternion')
# orientation_covariance  (Nodetype.ARRAY, ((Nodetype.BASE, ('float64', 0)), 9))
# angular_velocity        (Nodetype.NAME, 'geometry_msgs/msg/Vector3')
# ...
```

### Pattern 2: Table-name sanitization + deterministic collision resolution
**What:** `sanitize_table_name(topic)`: strip a single leading `/`, replace remaining `/` with `_`. Then a stateful `TableNameResolver` that detects collisions (including case-insensitive collisions, since SQL identifiers are commonly case-folded) and appends a deterministic suffix.
**When to use:** plan 03-01 (QURY-01).
**Example:**
```python
# Source: design spec §4.1 rule + project logic (VERIFIED rule on the canonical example)
import re

def sanitize_table_name(topic: str) -> str:
    name = topic[1:] if topic.startswith("/") else topic   # drop ONE leading '/'
    name = name.replace("/", "_")                            # remaining '/' -> '_'
    name = re.sub(r"[^0-9A-Za-z_]", "_", name)               # any other odd char -> '_'
    if not name:                                             # e.g. topic was "/" 
        name = "topic"
    if name[0].isdigit():                                    # SQL ident can't start with a digit
        name = f"t_{name}"
    return name

# /camera/image_raw -> "camera_image_raw"   (VERIFIED canonical example)
# /tf              -> "tf"
# /a/b             -> "a_b"
```
Collisions (e.g. `/a/b` and `/a.b` both → `a_b`, or `/Foo` vs `/foo` under case-folding) get a deterministic numeric suffix (`a_b`, `a_b_2`, …). The resolver records the topic→name map for Phase 4's `bagq tables`.

### Pattern 3: Prepend the four always-present columns
**What:** Every table starts with `t`, `t_ns`, `stamp`, `topic`, in that order, before the flattened message columns. Their Arrow types are fixed; their values come straight off the `Message` record.
**When to use:** plan 03-02 (QURY-04).
**Example:**
```python
# Source: design spec §4.1 + VERIFIED arrow->duckdb type round-trip this session
import pyarrow as pa

STANDARD_COLUMNS = [
    ("t",     pa.timestamp("ns")),  # -> DuckDB TIMESTAMP_NS  (log/receive time)
    ("t_ns",  pa.int64()),          # -> DuckDB BIGINT         (exact ns)
    ("stamp", pa.timestamp("ns")),  # -> DuckDB TIMESTAMP_NS, NULLABLE (header.stamp or NULL)
    ("topic", pa.string()),         # -> DuckDB VARCHAR
]
# Row values: t=msg.t, t_ns=msg.t_ns, stamp=msg.stamp (may be None), topic=msg.topic
```
**Critical:** `pa.timestamp("ns")` accepts the int-ns directly only via an int64 array reinterpreted, OR pass Python ints into a `timestamp('ns')` array builder — VERIFIED both `t` and `stamp` (with a `None`) materialize as DuckDB `TIMESTAMP_NS` with NULL preserved. Keep `stamp` **nullable** (headerless topics like `/cmd_vel` → all-NULL `stamp`).

### Pattern 4: One recursive walk shared by schema-build and row-extract
**What:** The dotted-name flattening is the *same traversal* for building the schema (from the AST) and extracting a row (from the msg object). Build a list of "leaf descriptors" once — each descriptor knows its dotted column name, its Arrow type, whether it's a heavy blob, and **how to pull its value from a msg** (a tuple of attribute names to follow). Then row extraction is `reduce(getattr, path, msg)` per leaf.
**When to use:** plan 03-02 / 03-03 (QURY-02/03). Recommended over two divergent walks (keeps schema and rows in lockstep).
**Example:**
```python
# Source: project design; AST shape + runtime values VERIFIED this session
from functools import reduce
from rosbags.interfaces import Nodetype

def walk_fields(msgtype, typestore, prefix=()):
    """Yield (dotted_name, path_tuple, arrow_type, is_heavy_blob) leaves."""
    for fname, ftype in typestore.get_msgdef(msgtype).fields:
        path = (*prefix, fname)
        nt = ftype[0]
        if nt == Nodetype.NAME:                       # sub-message -> recurse, dotted
            yield from walk_fields(ftype[1], typestore, path)
        else:                                          # BASE / ARRAY / SEQUENCE -> leaf column
            arrow_type, heavy = arrow_type_of(ftype, typestore)
            yield (".".join(path), path, arrow_type, heavy)

def extract_value(msg, path):
    return reduce(getattr, path, msg)   # e.g. ("linear","x") -> msg.linear.x
```
Note: `header.stamp.sec` / `header.stamp.nanosec` fall out of this walk naturally as nested columns (Header → Time → sec/nanosec), alongside the separately-prepended top-level `stamp` column (Pitfall 6).

### Pattern 5: Heavy-blob lazy exclusion via an `include` set
**What:** Mark each leaf with `is_heavy_blob` (Pattern 1's predicate). The **default** `arrow_schema()` / `flatten_message()` **omit** heavy-blob columns. Callers (Phase 5, from parsed SQL) pass `include={"data"}` (the set of referenced top-level column names) to re-add specific blobs.
**When to use:** plan 03-03 (QURY-07). This is the clean seam Phase 5 drives.
**Example:**
```python
# Source: design spec §4.1 QURY-07; predicate VERIFIED on Image/PointCloud2/CompressedImage
def is_heavy_blob(ftype) -> bool:
    """True iff a variable-length sequence of bytes (uint8|byte|char)."""
    nt, payload = ftype
    if nt == Nodetype.SEQUENCE:
        inner, _bound = payload
        return inner[0] == Nodetype.BASE and inner[1][0] in ("uint8", "byte", "char")
    return False

# TableSchema.arrow_schema(include=None): drop every column where is_heavy_blob and
#   name not in (include or set()).  Phase 5 computes `include` from sqlglot column refs.
```
**Why structural, not name-based:** A name blocklist (`{"data"}`) is brittle — `String.data` is a scalar, not a blob; a custom message could name a blob `payload`. The `SEQUENCE of byte` structure is the real signal and was VERIFIED to correctly include `Image.data`/`PointCloud2.data`/`CompressedImage.data` while excluding `Imu.orientation_covariance` (a fixed `float64[9]`, kept) and `String.data` (a scalar string, kept).

### Pattern 6: SQL-safe identifiers via sqlglot (the security surface)
**What:** Column and table names produced here become SQL identifiers in Phase 5. To render any name (esp. a dotted one, or a frame_id-derived field) as an injection-safe quoted identifier, use `sqlglot`.
**When to use:** Anywhere a name is interpolated into SQL (primarily Phase 5, but Phase 3 should expose a helper / store names so they're quoted, not concatenated raw).
**Example:**
```python
# Source: VERIFIED with sqlglot this session
from sqlglot import exp
def quote_ident(name: str, dialect: str = "duckdb") -> str:
    return exp.to_identifier(name, quoted=True).sql(dialect=dialect)
# 'twist.twist.linear.x'        -> '"twist.twist.linear.x"'
# 'weird"name'                  -> '"weird""name"'        (embedded quote escaped)
# 'twist"; DROP TABLE x;--'     -> '"twist""; DROP TABLE x;--"'  (neutralized)
```

### Anti-Patterns to Avoid
- **Parsing the dataclass `f.type` string** (`'np.ndarray[tuple[int, ...], np.dtype[np.float64]]'`) to recover element types. The typestore AST already has it cleanly (Pattern 1). Verified both exist; the string is strictly worse.
- **Inferring the schema from one message's runtime values** (`pa.Table.from_pylist`). An empty list, an all-default message, or a heterogeneous topic makes inference disagree across messages → `pa.lib.ArrowInvalid`. Build the schema from the *declared* AST, then build arrays against it (Pitfall 1).
- **String-concatenating column/table names into SQL** (`f'... WHERE {col} > 0'`). Quote via `sqlglot` (Pattern 6) — the names are derived from bag content (frame_ids, custom-msg fields) and are an injection surface.
- **Emitting DuckDB DDL.** Breaks the swappable-backend seam and forces this phase to know DuckDB. Emit Arrow (Standard Stack).
- **`import duckdb` in shipped `schema/` code.** Phase 5's job. (A test MAY import it to assert the Arrow→DuckDB type mapping.)
- **Treating `Imu.orientation_covariance` (`float64[9]`) as a heavy blob.** It's a normal fixed array → `LIST`. Only `SEQUENCE of byte` is heavy (Pattern 5).
- **Special-casing ROS 1 vs ROS 2 field naming.** The typestore normalizes both; `header.stamp` is `builtin_interfaces/msg/Time` with `.sec`/`.nanosec` for both (Phase 2 finding, re-confirmed).
- **Dotting the sub-field names *inside* a `LIST<STRUCT>`.** The STRUCT's inner fields keep their short names (`child_frame_id`, not `transforms.child_frame_id`); only the top-level path to the LIST column is dotted (Pitfall 4).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Discovering a message's fields/types/nesting | A `.msg`/`.idl` parser, or `dataclasses.fields` + `f.type` string parsing | `typestore.get_msgdef(msgtype).fields` (`Nodetype` AST) | `rosbags` already parsed the definition into a clean, recursive, ROS1/ROS2-uniform AST. Re-parsing is fragile and redundant. |
| Distinguishing fixed vs variable arrays, scalar vs sub-msg | Heuristics on Python runtime values | `Nodetype.ARRAY` vs `SEQUENCE`, `BASE` vs `NAME` in the AST | The declared structure is unambiguous and value-independent (works for empty sequences). |
| Mapping nested columns → a columnar table with LIST/STRUCT | A custom column store / row encoder | `pyarrow` (`pa.schema`, `pa.list_`, `pa.struct`, `pa.array`) + DuckDB ingest | Arrow has first-class nested types; DuckDB ingests Arrow zero-copy and yields the exact spec types (`TIMESTAMP_NS`/`DOUBLE[]`/`STRUCT(...)[]`). VERIFIED round-trip. |
| Building the ns→TIMESTAMP_NS column | Manual `datetime` conversion | `pa.timestamp('ns')` (DuckDB maps it to `TIMESTAMP_NS`) | Avoids precision loss; ns precision preserved end-to-end. VERIFIED. |
| uint64 / uint32 fields | Casting to int64 (risking overflow) | `pa.uint64()`/`pa.uint32()` (DuckDB `UBIGINT`/`UINTEGER`) | VERIFIED `uint64` max (18446744073709551615) round-trips with no overflow. |
| SQL-safe quoting of dotted/odd identifiers | `f'"{name}"'` hand-quoting | `sqlglot.exp.to_identifier(name, quoted=True)` | Hand-quoting misses embedded-quote escaping (`weird"name`). sqlglot escapes correctly — the injection defense. |
| ndarray → LIST column | Looping to build Python lists | `pa.array([ndarray])` (numpy arrays convert directly to `list<>`) | VERIFIED: `pa.array([np.zeros(9)])` → `list<double>`; zero-copy where possible. |

**Key insight:** This phase is a **translator between two pre-built type systems** — `rosbags`'s `Nodetype` field-AST on the input side and `pyarrow`'s `DataType`s on the output side — plus a small amount of project glue (dotted-name flattening, the four standard columns, table-name sanitization, the heavy-blob predicate). Both type systems are mature and do the heavy lifting; resist re-implementing definition-parsing or a columnar encoder.

## Runtime State Inventory

> **Not applicable** — this is a greenfield feature phase (new `schema/` code over an empty seam package), not a rename/refactor/migration. There is no stored data, live-service config, OS-registered state, secret, or build artifact to migrate.
>
> - **Stored data:** None — verified: the only existing file under `schema/` is an empty docstring-only `__init__.py` (read this session); no prior schema implementation exists.
> - **Live service config:** None — offline, local-file library; no services.
> - **OS-registered state:** None.
> - **Secrets/env vars:** None.
> - **Build artifacts:** None new (no `pyproject.toml`/dependency changes; `rosbagger-core` is already installed editable).

## Common Pitfalls

### Pitfall 1: Schema instability across messages of the same topic (the inference trap)
**What goes wrong:** Building the Arrow schema by inferring from message values (`from_pylist`, or `pa.array(values)` without a declared type) produces a schema that varies message-to-message. The classic failure: a topic whose first observed message has an **empty** variable-length array → `pyarrow` infers `list<null>`; a later message with `float64` elements → `ArrowInvalid: cannot merge`. Heterogeneous/empty messages (e.g. a `nav_msgs/Path` with `poses=[]`) trigger this.
**Why it happens:** The wire/runtime value of one message under-specifies the *declared* type, especially for empty `SEQUENCE`s and unset optionals.
**How to avoid:** Build the schema **once per topic from the declared typestore AST** (Pattern 1/4), never from values. Then build every column array with its explicit `type=` from the schema (`pa.array(values, type=col.arrow_type)`). The schema is stable for the whole topic regardless of any individual message's contents. (VERIFIED: an empty Arrow table built from an explicit schema still registers in DuckDB with full column types.)
**Warning signs:** `pyarrow.lib.ArrowInvalid` on `from_pylist`/`Table.from_arrays`; `list<null>` appearing in a DESCRIBE; a topic that works until the first empty-array message.

### Pitfall 2: `numpy` scalar/array types leaking into Arrow build
**What goes wrong:** Some fields deserialize as numpy scalars (`np.uint32(2)` for `Image.height`) or ndarrays (`np.float64` arrays). Mixing `np.uint32` Python-side with an Arrow `int64()` column, or feeding a 2-D ndarray where a 1-D `list<>` is expected, can raise or silently up/down-cast.
**Why it happens:** `rosbags` returns numpy-typed values for numeric scalars and all arrays (VERIFIED: `Image.height` came back as Python `int` in the fixtures, but covariance/data came back as `np.ndarray`; numpy-scalar leakage is possible for some types/encodings).
**How to avoid:** Pin the Arrow column type from the AST (Pattern 4) and let `pa.array(values, type=...)` do the conversion. For arrays, pass the ndarray straight to `pa.array([ndarray], type=pa.list_(elem))` — VERIFIED this yields the right `list<>` for both `float64[9]` and `uint8[]`. Don't pre-convert with `.tolist()` unless a specific type needs it (it's slower and loses dtype).
**Warning signs:** `ArrowTypeError`/`ArrowInvalid` mentioning numpy dtypes; unexpected widening of `uint8`→`int64`.

### Pitfall 3: Large fixed arrays and the heavy-blob boundary
**What goes wrong:** Treating every array as cheap (loading `PointCloud2.data`, a multi-MB `uint8[]`, for every row) blows memory; OR over-correcting and excluding `Imu.orientation_covariance` (a 9-element `float64[]`) as if it were heavy.
**Why it happens:** "Array" conflates two very different things: a fixed small numeric array (covariance) and a variable byte blob (image/pointcloud payload).
**How to avoid:** The heavy-blob predicate is **only** `SEQUENCE of (uint8|byte|char)` (Pattern 5) — VERIFIED to include `Image.data`/`PointCloud2.data`/`CompressedImage.data` and exclude `orientation_covariance` (an `ARRAY of float64`). Fixed `ARRAY`s and non-byte `SEQUENCE`s are always materialized as `LIST`; only byte sequences are lazy. (Note: `PointCloud2` has BOTH a heavy `data` blob AND a `LIST<STRUCT>` `fields` — the latter is small and always kept.)
**Warning signs:** OOM when querying an image/pointcloud topic without referencing `data`; covariance columns mysteriously missing.

### Pitfall 4: Dotted-name depth and the LIST<STRUCT> name boundary
**What goes wrong:** (a) Flattening *through* a sub-message-array, producing nonsense like `transforms.header.stamp.sec` as a top-level scalar column (impossible — `transforms` is a list). (b) Inconsistent separators or losing field order.
**Why it happens:** The recursion must STOP descending at an `ARRAY`/`SEQUENCE` node — that whole subtree becomes one `LIST` (or `LIST<STRUCT>`) column; you do NOT keep dotting into the struct's fields at the top level.
**How to avoid:** In the walk (Pattern 4), recurse into `Nodetype.NAME` only; at `ARRAY`/`SEQUENCE`, emit a single leaf column whose Arrow type is `list_(elem)` where `elem` may itself be a `pa.struct(...)` built from the inner message's fields (with their **short** names). So `tf2_msgs/TFMessage` → one column `transforms` of type `list<struct<header: struct<...>, child_frame_id: string, transform: struct<...>>>`; the inner names are `header`, `child_frame_id`, not dotted. Preserve declared field order (the AST is ordered). Use `.` consistently as the separator (matches the spec's `"twist.twist.linear.x"`).
**Warning signs:** Column names that dot past a list; duplicate or reordered columns; a `STRUCT` whose inner fields are dotted.

### Pitfall 5: Deeply nested / recursive / self-referential types and unbounded recursion
**What goes wrong:** A pathological or deeply-nested custom message could recurse very deep; a (rare) self-referential definition could recurse infinitely.
**Why it happens:** The flatten walk is recursive over `Nodetype.NAME`.
**How to avoid:** Standard ROS messages are not self-referential and nest only a handful of levels (the deepest common case is `Header → Time → sec/nanosec`, 3 levels, or `PoseStamped → Pose → Point/Quaternion → x/y/z`, ~3). For robustness, the walk MAY carry a `seen: frozenset[str]` of msgtypes-on-the-current-path and stop (or raise a clear error) on a cycle. Not required for any fixture, but cheap insurance for arbitrary user bags. (`[ASSUMED]` that no standard ROS type is self-referential — true for the common interface set; a malicious/odd custom def is the only risk.)
**Warning signs:** `RecursionError`; an absurd column count.

### Pitfall 6: `stamp` appears twice (top-level column AND nested header path) — by design, not a bug
**What goes wrong:** Confusion that the always-present `stamp` column duplicates `"header.stamp.sec"`/`"header.stamp.nanosec"`.
**Why it happens:** QURY-04 mandates a top-level `stamp` (a single `TIMESTAMP_NS` derived from `header.stamp`, or NULL); the flatten walk ALSO emits the header's own nested columns for header-bearing messages.
**How to avoid:** This is intentional and non-conflicting — the names differ (`stamp` vs `header.stamp.sec`). The top-level `stamp` is the convenient query column (already computed by Phase 2's `Message.stamp` as ns, or `None`); the nested `header.stamp.*` columns are the faithful raw fields. Both should exist. Do not suppress the nested header columns. (Headerless topics like `/cmd_vel` have neither a `header.*` column nor a non-NULL `stamp` — `stamp` is all-NULL.)
**Warning signs:** Someone "deduplicating" by dropping `header.stamp.*`; a missing `stamp` column on header-bearing topics.

### Pitfall 7: Table-name collisions and SQL-identifier edge cases
**What goes wrong:** Two topics sanitize to the same name (`/a/b` and `/a.b` → `a_b`), or a topic sanitizes to an invalid SQL identifier (empty, leading digit, reserved word, or differing only by case).
**Why it happens:** The `/`→`_` rule isn't injective; SQL identifiers have rules the raw topic doesn't.
**How to avoid:** Run all names through the `TableNameResolver` (Pattern 2): detect collisions (recommend case-insensitive comparison since many SQL contexts fold case) and append a deterministic suffix; handle empty (`/` → `topic`) and leading-digit (`t_` prefix) cases. Quote at SQL time via `sqlglot` (Pattern 6) so reserved words are safe. Record the topic→name map for `bagq tables` (Phase 4) to print.
**Warning signs:** "table already exists"/ambiguous-table errors in Phase 5; two topics mapping to one table; a table name starting with a digit.

## Code Examples

Verified this session against the project fixtures with `rosbags` 0.11.2, `pyarrow` 24.0.0, `duckdb` 1.5.3 (run with `PYTHONPATH=""`).

### §1 — Table-name sanitization (QURY-01)
```python
# Source: design spec §4.1 rule; canonical example VERIFIED
def sanitize_table_name(topic: str) -> str:
    name = topic[1:] if topic.startswith("/") else topic
    return name.replace("/", "_")
# "/camera/image_raw" -> "camera_image_raw"   ✓ (matches spec exactly)
# "/cmd_vel" -> "cmd_vel" ; "/imu" -> "imu" ; "/tf" -> "tf"
# (Add the re-cleanup + leading-digit + collision-resolver from Pattern 2 for robustness.)
```

### §2 — The introspection API: declared field-AST (the heart of the phase)
```python
# Source: VERIFIED against fixtures this session
from rosbags.interfaces import Nodetype  # NB: import from rosbags.interfaces

# `typestore` is reader.typestore (a rosbags Typestore); the reader exposes it after open().
md = typestore.get_msgdef("geometry_msgs/msg/Twist")
md.fields
# [('linear',  (Nodetype.NAME, 'geometry_msgs/msg/Vector3')),
#  ('angular', (Nodetype.NAME, 'geometry_msgs/msg/Vector3'))]

typestore.get_msgdef("geometry_msgs/msg/Vector3").fields
# [('x', (Nodetype.BASE, ('float64', 0))),
#  ('y', (Nodetype.BASE, ('float64', 0))),
#  ('z', (Nodetype.BASE, ('float64', 0)))]
# => /cmd_vel flattens to columns:
#    "linear.x","linear.y","linear.z","angular.x","angular.y","angular.z"  (all DOUBLE)
```
The deserialized object is also a dataclass (`dataclasses.is_dataclass(msg) is True`, `msg.__msgtype__ == 'geometry_msgs/msg/Twist'`), but **prefer the typestore AST** for schema decisions (Alternatives Considered).

### §3 — ROS Basename → Arrow type map (verified vocabulary)
```python
# Source: ROS base-type vocabulary VERIFIED from rosbags Basename Literal + grep of installed source.
# Full set: bool, byte, char, int8, int16, int32, int64, uint8, uint16, uint32, uint64,
#           float32, float64, (float128 rare), string, (wstring rare)
import pyarrow as pa

ROS_BASE_TO_ARROW = {
    "bool":    pa.bool_(),
    "byte":    pa.uint8(),     # ROS 'byte' == octet
    "char":    pa.uint8(),     # ROS 'char' == uint8 (ROS2) — single octet
    "int8":    pa.int8(),
    "int16":   pa.int16(),
    "int32":   pa.int32(),
    "int64":   pa.int64(),
    "uint8":   pa.uint8(),
    "uint16":  pa.uint16(),
    "uint32":  pa.uint32(),    # -> DuckDB UINTEGER
    "uint64":  pa.uint64(),    # -> DuckDB UBIGINT (VERIFIED no overflow at max)
    "float32": pa.float32(),
    "float64": pa.float64(),   # -> DuckDB DOUBLE
    "string":  pa.string(),    # -> DuckDB VARCHAR
    "wstring": pa.string(),    # [ASSUMED] rare; treat as UTF-8 string
    # "float128": pa.float64(),  # [ASSUMED] extremely rare in ROS; lossy down-map if ever seen
}

def arrow_type_of(ftype, typestore):
    """FieldDesc -> (pa.DataType, is_heavy_blob)."""
    nt, payload = ftype
    if nt == Nodetype.BASE:
        return ROS_BASE_TO_ARROW[payload[0]], False
    if nt == Nodetype.NAME:                       # sub-message in a LIST context -> struct
        fields = [(fn, arrow_type_of(ft, typestore)[0])
                  for fn, ft in typestore.get_msgdef(payload[0]).fields]
        return pa.struct(fields), False
    if nt in (Nodetype.ARRAY, Nodetype.SEQUENCE):  # fixed or variable -> LIST
        inner, _bound = payload
        elem, _ = arrow_type_of(inner, typestore)
        heavy = (nt == Nodetype.SEQUENCE and inner[0] == Nodetype.BASE
                 and inner[1][0] in ("uint8", "byte", "char"))
        return pa.list_(elem), heavy
    raise ValueError(f"unknown Nodetype {nt}")
```

### §4 — LIST and LIST-of-STRUCT cases (QURY-03), verified end-to-end into DuckDB
```python
# Source: VERIFIED — typestore shapes for real LIST<STRUCT> types + arrow->duckdb round-trip
# tf2_msgs/msg/TFMessage:
#   ('transforms', (SEQUENCE, ((NAME, 'geometry_msgs/msg/TransformStamped'), 0)))
#   -> column "transforms" : list<struct<header: struct<...>, child_frame_id: string,
#                                        transform: struct<...>>>
# sensor_msgs/msg/Imu.orientation_covariance:
#   (ARRAY, ((BASE, ('float64', 0)), 9))  -> column "orientation_covariance" : list<double>
#
# DuckDB DESCRIBE of a registered Arrow table with these columns (VERIFIED):
#   orientation_covariance -> DOUBLE[]
#   transforms             -> STRUCT(child_frame_id VARCHAR, x DOUBLE)[]
# Query access (VERIFIED, DuckDB lists are 1-indexed):
#   SELECT orientation_covariance[1]            -> first element
#   SELECT transforms[1].child_frame_id         -> struct field of first list element
```

### §5 — Full per-topic Arrow build with the four standard columns (QURY-04)
```python
# Source: VERIFIED arrow->duckdb mapping this session
import pyarrow as pa

# Suppose build_table_schema produced columns (excluding heavy blobs):
#   t, t_ns, stamp, topic, "linear.x", ..., "orientation_covariance", ...
# Collect per-message values into parallel column lists, then:
schema = pa.schema([
    ("t", pa.timestamp("ns")), ("t_ns", pa.int64()),
    ("stamp", pa.timestamp("ns")), ("topic", pa.string()),
    ("orientation.x", pa.float64()),
    ("orientation_covariance", pa.list_(pa.float64())),
    # ... etc
])
table = pa.table({
    "t":     pa.array(t_values,  pa.timestamp("ns")),
    "t_ns":  pa.array(t_values,  pa.int64()),
    "stamp": pa.array(stamp_values, pa.timestamp("ns")),   # None entries -> NULL
    "topic": pa.array(topic_values, pa.string()),
    "orientation.x": pa.array(ox_values, pa.float64()),
    "orientation_covariance": pa.array(cov_values, pa.list_(pa.float64())),  # cov_values: list[ndarray]
}, schema=schema)

# Phase 5 then: con.register("imu", table)  # zero-copy; DESCRIBE shows TIMESTAMP_NS/BIGINT/...
# Phase 5 query: SELECT "orientation.x", topic, t, stamp FROM imu   # VERIFIED returns rows
```

### §6 — Heavy-blob predicate (QURY-07), verified discrimination
```python
# Source: VERIFIED on Image/PointCloud2/CompressedImage vs covariance/String this session
from rosbags.interfaces import Nodetype

def is_heavy_blob(ftype) -> bool:
    nt, payload = ftype
    if nt == Nodetype.SEQUENCE:
        inner, _bound = payload
        return inner[0] == Nodetype.BASE and inner[1][0] in ("uint8", "byte", "char")
    return False

# VERIFIED results:
#   sensor_msgs/msg/Image.data            (SEQUENCE uint8)   -> True   (excluded by default)
#   sensor_msgs/msg/PointCloud2.data      (SEQUENCE uint8)   -> True   (excluded by default)
#   sensor_msgs/msg/CompressedImage.data  (SEQUENCE uint8)   -> True   (excluded by default)
#   sensor_msgs/msg/Imu.orientation_covariance (ARRAY float64[9]) -> False (kept: LIST<double>)
#   std_msgs/msg/String.data              (BASE string)      -> False (kept: VARCHAR)
```

### §7 — Empty / zero-row topic still yields a typed schema (Pitfall 1 mitigation)
```python
# Source: VERIFIED this session
import pyarrow as pa, duckdb
schema = pa.schema([("t", pa.timestamp("ns")), ("topic", pa.string()), ("x", pa.float64())])
empty = pa.table({"t": pa.array([], pa.timestamp("ns")),
                  "topic": pa.array([], pa.string()),
                  "x": pa.array([], pa.float64())}, schema=schema)
con = duckdb.connect(); con.register("empty_topic", empty)
con.execute("DESCRIBE SELECT * FROM empty_topic").fetchall()
# -> [('t','TIMESTAMP_NS',...), ('topic','VARCHAR',...), ('x','DOUBLE',...)]  (schema intact)
con.execute("SELECT count(*) FROM empty_topic").fetchone()  # -> (0,)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hand-written per-message-type column extractors / one-off flatten scripts | One generic flattener driven by the `rosbags` typestore AST | rosbags typesys matured 2021→2026 | The whole point of `bagq` — no per-type code; any (incl. custom) message flattens generically |
| Convert messages → pandas/CSV → load into SQLite | Build `pyarrow` directly → DuckDB ingests zero-copy | DuckDB+Arrow integration (DuckDB ≥0.3, 2021) matured to 1.x | No intermediate format; native `LIST`/`STRUCT`; ns-precision timestamps preserved |
| Parse `f.type` annotation strings / runtime `isinstance` to guess types | `typestore.get_msgdef(mt).fields` structured `Nodetype` AST | rosbags 0.x typestore API | Robust, value-independent schema (handles empty arrays, custom types) |
| `con.fetch_arrow_table()` for results | `con.to_arrow_table()` | DuckDB ~1.3+ deprecated `fetch_arrow_table` | **Phase 6 note:** use `to_arrow_table()` (a `DeprecationWarning` was observed on `fetch_arrow_table()` in 1.5.3) |

**Deprecated/outdated:**
- `from rosbags.typesys.types import FIELDDEFS` and `from rosbags.typesys.base import Nodetype` — **do not exist** in 0.11.2 (both raised `ImportError`/`ModuleNotFoundError` this session). The correct import is `from rosbags.interfaces import Nodetype` (also re-exported from `rosbags.interfaces.typing`). Field defs come from `typestore.get_msgdef(msgtype).fields`, not a module-level `FIELDDEFS`.
- `duckdb` `fetch_arrow_table()` — deprecated in favor of `to_arrow_table()` (relevant to Phase 6's result handling, noted here so the planner is aware).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `wstring` → `pa.string()` (UTF-8) is acceptable | §3 type map | LOW — `wstring` is vanishingly rare in real ROS bags; no fixture uses it. If a bag has one, worst case is an encoding nuance. |
| A2 | `float128` (if ever encountered) can be lossily mapped to `pa.float64()` | §3 type map | LOW — not in the standard ROS interface set; Arrow has no float128. No fixture uses it. Flag to user if seen. |
| A3 | `byte` and `char` both map to `uint8` (single octet) | §3 type map | LOW — matches ROS2 semantics (`byte`=octet, `char`=uint8) and rosbags' own deserialization (VERIFIED `uint8[]` for `Image.data`); a `char` *array* is still a byte sequence. ROS1 `char`=uint8 too. |
| A4 | No standard ROS message type is self-referential (so the flatten recursion terminates without a cycle guard for stock types) | Pitfall 5 | LOW — true for the standard interface set; only an unusual/malicious *custom* def could recurse. Mitigation (a `seen` set) is cheap and recommended. |
| A5 | Recommending a top-level `stamp` column AND keeping nested `header.stamp.*` columns matches intent | Pitfall 6 / Pattern 3 | LOW — design spec §4.1 explicitly mandates the top-level `stamp`; faithful flattening implies the nested columns. If the team wants header columns suppressed, that's a small config tweak — surface in discuss-phase. |

> Everything else in this research was **VERIFIED** by executing `rosbags` 0.11.2 / `pyarrow` 24.0.0 / `duckdb` 1.5.3 against the project's own fixtures this session, and/or reading the installed library source. No compliance/security/retention assumptions. The five `[ASSUMED]` items above are all low-risk rare-type or design-intent confirmations — none block planning; A5 is the only one worth a one-line user confirmation in discuss-phase.

## Open Questions (RESOLVED)

*All three resolved and carried into the plans: Q1 (emit both t/t_ns) → 03-02 STANDARD_COLUMNS; Q2 (include-set keyed on dotted name) → 03-01/03-03; Q3 (pass typestore explicitly) → `build_table_schema(msgtype, typestore, ...)` in 03-02 + `reader._reader.typestore` downstream.*

1. **What value type does Phase 5 expect for `t`/`stamp` ingestion — int-ns or a datetime?**
   - What we know: `pa.timestamp('ns')` columns map to DuckDB `TIMESTAMP_NS` and a Python-`int`-ns value materializes correctly (VERIFIED via a `1_000_000_000`-ns array → `1970-01-01 00:00:01`). `Message.t`/`t_ns`/`stamp` are ints (or `None` for `stamp`).
   - What's unclear: nothing blocking — both `t` (timestamp) and `t_ns` (raw bigint) are emitted, so a user can query either. The detail (whether to feed the timestamp array as int64-reinterpreted or via datetime) is an implementation choice inside the Arrow build.
   - Recommendation: emit BOTH columns (already required by QURY-04); build the `timestamp('ns')` array from the int-ns values. No user input needed.

2. **Should the heavy-blob `include` set be top-level column names or full dotted paths?**
   - What we know: heavy blobs in the standard set are always top-level fields (`Image.data`, `PointCloud2.data`) — VERIFIED. Phase 5 will derive the referenced set from sqlglot column references.
   - What's unclear: whether a blob could ever be nested inside a sub-message (then `include` would need a dotted key).
   - Recommendation: key `include` on the **dotted column name** (the same string used as the Arrow column name) for uniformity — it degenerates to the bare name for top-level blobs and handles a hypothetical nested blob. This is Claude's discretion; document it in the `build_table_schema` signature so Phase 5 knows the contract.

3. **Where does `schema/` get the `typestore`?**
   - What we know: `RosbagsReader` wraps `AnyReader`, which has `.typestore` (VERIFIED used this session). The reader does not currently expose it on the `BagReader` interface.
   - What's unclear: whether to (a) add a `typestore` property to the reader, (b) pass the `typestore` into the schema functions explicitly, or (c) have the schema layer accept the reader.
   - Recommendation: pass the `typestore` (or a small typed accessor) explicitly into `build_table_schema(msgtype, typestore, ...)` — keeps `schema/` decoupled from the reader and testable in isolation (a test can build a typestore via `rosbags.typesys.get_typestore(Stores.ROS2_HUMBLE)` directly). Phase 4/5 wiring will fetch `reader._reader.typestore` (or a new `BagReader.typestore` property — a small, optional reader addition the planner may schedule). Flag this seam to the planner.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `rosbags` | introspection (`get_msgdef`) + fixtures | ✓ | 0.11.2 | — (the chosen introspection source) |
| `pyarrow` | schema emission (Arrow build) | ✓ | 24.0.0 | — (the chosen emission format) |
| `sqlglot` | identifier quoting (used Phase 5; helper here) | ✓ | (locked `>=27,<31`) | hand-quoting (NOT recommended — injection risk) |
| `duckdb` | **Phase 5 only** (tests may assert mapping) | ✓ | 1.5.3 | — (not in shipped Phase-3 code) |
| `numpy` | array values (transitive via rosbags) | ✓ | 2.2.6 | — |
| Python | runtime | ✓ | 3.10 (`.python-version`) | — |
| `pytest` + fixtures | tests | ✓ | pytest 8.x; `tools/make_fixtures.py` | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

> This phase reads local fixture bags and builds in-memory Arrow — no external services, network, daemons, or ROS runtime. All five libraries are installed and verified working this session (run with `PYTHONPATH=""` per the dev-host ROS-leak note — 02-RESEARCH.md Pitfall 5). No `rclpy`/`rosbag2_py` (forbidden).

## Validation Architecture

> `workflow.nyquist_validation` is **`false`** in `.planning/config.json`. Per the research template, this section is **omitted**. Standard pytest tests still apply: unit-test `sanitize_table_name`/collision-resolver, the ROS→Arrow type map, the flatten walk (dotted names + LIST/STRUCT), the heavy-blob predicate, and the four standard columns — all against the existing `tools/make_fixtures.py` fixtures (`/cmd_vel` Twist, `/imu` Imu w/ `float64[9]` covariance, `/image` Image w/ `uint8[]` data). A test MAY register the built Arrow table into DuckDB to assert the mapped types (`TIMESTAMP_NS`/`BIGINT`/`DOUBLE[]`/`STRUCT(...)[]`) — DuckDB is a dev/test dep here, not shipped Phase-3 import. Run locally with `PYTHONPATH="" uv run pytest`; CI is ROS-free. The ≥80% coverage gate on `rosbagger_core` applies.

## Security Domain

`security_enforcement` is not set in `.planning/config.json`. This is an offline, local-file library — no auth, network, sessions, secrets, or access control. The one real surface is **SQL identifier injection** via bag-derived names (table names from topics, column names from message field names / frame_ids), because those names flow into SQL in Phase 5.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-user/authorization model |
| V5 Input Validation | **yes (partial)** | Bag content (topic names, field names, custom-msg type names) is untrusted external input that becomes SQL identifiers. Control: render every identifier via `sqlglot.exp.to_identifier(name, quoted=True)` (VERIFIED escapes embedded quotes); sanitize table names (Pattern 2); never f-string a raw name into SQL. The field *values* (data blobs, strings) are carried as Arrow data, never executed. |
| V6 Cryptography | no | No crypto — none needed, never hand-roll |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL identifier injection via a malicious topic/field name (`'twist"; DROP TABLE x;--'`) | Tampering | Quote ALL identifiers via `sqlglot.to_identifier(quoted=True)` — VERIFIED to neutralize the example into a safe quoted literal. Sanitize table names; collision-resolve. (Primarily enforced at SQL-build time in Phase 5, but Phase 3 must store names so they're *quotable*, never pre-concatenated.) |
| Memory-exhaustion via huge byte blobs materialized for every row | Denial of Service | The QURY-07 lazy-blob exclusion (Pattern 5) is itself the mitigation: heavy `SEQUENCE of byte` columns are omitted unless explicitly referenced. Build per-topic Arrow incrementally; don't hold all blobs. |
| Malformed/odd custom message definition (deep nesting, cycles) | Denial of Service | Bounded-depth / cycle-guarded flatten recursion (Pitfall 5); `rosbags` already validated the definition on read. |

> No security control here needs a new dependency or any hand-rolled crypto/auth. Posture: **treat bag-derived names as untrusted SQL identifiers (quote via sqlglot), carry field values as inert Arrow data, and use the lazy-blob exclusion as a DoS guard.**

## Sources

### Primary (HIGH confidence)
- **Installed `rosbags` 0.11.2 + `pyarrow` 24.0.0 + `duckdb` 1.5.3, executed against project fixtures this session** (`PYTHONPATH="" .venv/bin/python`). VERIFIED: deserialized msgs are dataclasses with `__msgtype__` ClassVar; `typestore.get_msgdef(mt).fields` returns the `Nodetype` AST (`BASE`/`NAME`/`ARRAY`/`SEQUENCE`); the full `Basename` scalar vocabulary; runtime value types (native `int`/`float`/`str`, ndarrays for arrays) identical ROS1/ROS2; LIST-of-STRUCT shapes for `tf2_msgs/TFMessage`/`nav_msgs/Path`/`PointCloud2.fields`; heavy-blob predicate discrimination (Image/PointCloud2/CompressedImage vs covariance/String); the Arrow→DuckDB type round-trip (`timestamp('ns')`→`TIMESTAMP_NS`, `int64`→`BIGINT`, `uint64`→`UBIGINT` no-overflow, `list<double>`→`DOUBLE[]`, `list<struct>`→`STRUCT(...)[]`); quoted-dotted-column + 1-indexed LIST/STRUCT query access; NULL `stamp` preservation; empty-table schema retention; `register`/`from_arrow`/replacement-scan ingestion; `sqlglot.to_identifier(quoted=True)` quote-escaping; numpy-ndarray → `pa.array` `list<>` conversion.
- **Installed `rosbags` source** — `rosbags.interfaces.typing` (`Nodetype`, `FieldDesc`, `BaseDesc`, `NameDesc`, `Basename` Literal, `Basetype`); `rosbags.typesys.store.Typestore` (`get_msgdef`, `fielddefs`); `Msgdef` (`.fields`, `.cls`). Confirmed `rosbags.typesys.base.Nodetype` and `rosbags.typesys.types.FIELDDEFS` do NOT exist (import errors) — correct import is `rosbags.interfaces`.
- **Project files** — `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §4.1 (the schema rules: one table/topic, sanitized name, dotted columns, LIST/STRUCT, four standard columns, lazy blobs), §3.3 (swappable backend), §7 (alias pack deferred); `.planning/REQUIREMENTS.md` (QURY-01..04/07 scope, QURY-05/06 = Phase 5, QURY-08/09 = v2); `.planning/ROADMAP.md` (Phase 3 = 3 plans: 03-01 names, 03-02 flatten+time, 03-03 LIST/STRUCT+blobs); `.planning/PROJECT.md` (DuckDB default behind seam, flatten-to-dotted decision); `packages/rosbagger-core/src/rosbagger_core/reader/base.py` + `rosbags_reader.py` (the `Message` input + `.typestore` source); `tools/make_fixtures.py` (fixture content: Twist/Imu/Image); `packages/rosbagger-core/pyproject.toml` (locked deps `rosbags`/`duckdb`/`sqlglot`/`pyarrow`); `02-RESEARCH.md` (rosbags details, offline invariant, `PYTHONPATH=""` note); `tests/test_offline_guard.py` + `conftest.py` (the ROS blocker the schema code must not trip); `.planning/config.json` (`nyquist_validation: false`, no `security_enforcement`).

### Secondary (MEDIUM confidence)
- **DuckDB official docs — Python conversion / Arrow import** (https://duckdb.org/docs/current/clients/python/conversion.html ; https://duckdb.org/docs/stable/guides/python/import_arrow) — CITED: `to_arrow_table()`/`to_arrow_reader()` for results; `register()`/`from_arrow()`/replacement-scan for ingest; zero-copy Arrow integration with arbitrarily nested structs/lists/maps. (Corroborates the primary-source round-trip.)
- **DuckDB blog — "DuckDB Quacks Arrow: zero-copy integration"** (https://duckdb.org/2021/12/03/duck-arrow) and **Apache Arrow blog** (https://arrow.apache.org/blog/2021/12/03/arrow-duckdb/) — CITED: zero-copy Arrow↔DuckDB; complex nested types (struct/list/map) supported.

### Tertiary (LOW confidence)
- None relied upon. (WebSearch surfaced the DuckDB/Arrow links above, which were corroborated by the verified round-trip.) The Ternaris `rosbags` docs pages for typesys/highlevel were checked but the public docs do not document the `Nodetype` AST internals — those were verified directly against the installed source/runtime instead, which is more authoritative.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — all deps locked + installed; versions verified directly; no new packages.
- Introspection API (`get_msgdef().fields` / `Nodetype` AST / value types): **HIGH** — every behavior executed against the project's fixtures and confirmed against installed source this session; correct import path (`rosbags.interfaces`) verified by reproducing the wrong-path import errors.
- ROS→Arrow type map: **HIGH for the verified vocabulary** (`bool/int*/uint*/float32/float64/string` + `uint8/byte/char` blobs + the LIST/STRUCT/timestamp/uint64 round-trip), **MEDIUM for rare types** (`wstring`/`float128`/`char`-array nuances — A1/A2/A3, low-risk, no fixture coverage).
- Architecture (Arrow emission, shared walk, lazy-blob `include` seam, name sanitization): **HIGH** — the Arrow→DuckDB round-trip, heavy-blob discrimination, empty-table schema retention, and sqlglot quoting were all verified empirically.
- Pitfalls: **HIGH** — schema-stability/empty-array, numpy leakage boundary, blob vs covariance, dotted-name LIST boundary, and collisions all grounded in verified type-system behavior.

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (30 days). Deps are pinned (`rosbags<0.12`, `duckdb<2`, `pyarrow>=18`), so the API surface is stable for this milestone — re-verify only if a pin is bumped (notably `duckdb` major or `pyarrow` major) or a custom-message edge case (rare base type) surfaces.
