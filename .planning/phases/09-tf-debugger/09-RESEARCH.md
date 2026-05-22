# Phase 9: TF Debugger - Research

**Researched:** 2026-05-22
**Domain:** Offline ROS TF (tf2) graph analysis + dropout detection, reusing the v1 bag reader
**Confidence:** HIGH (reuse surface verified against live source + a running interpreter; domain model verified against the actual `rosbags` typestore)

## Summary

Phase 9 ships `rosbagger-tf`: an **offline** analyzer that loads `/tf` + `/tf_static` from any ROS 1 / ROS 2 (sqlite3 + mcap) bag, builds the parent→child transform graph over time, and reports per-edge publish gaps on a timeline/table — with no ROS install. The single requirement is **TF-01**.

The phase is overwhelmingly a **reuse + new-domain-logic** job, not a new-infrastructure job. The v1 reader (`RosbagsReader`, Phase 2) already does every hard part of bag I/O: format detection, multi-bag merge, deserialization, and uniform `Message(topic, t, t_ns, stamp, msgtype, msg)` records. The TF analyzer consumes `reader.read(topics={"/tf", "/tf_static"})` and walks the deserialized `tf2_msgs/msg/TFMessage` payloads. The house architecture is **API-first**: all logic lives in `rosbagger-core` (mirroring `inspect.py`), and the CLI is a thin rich renderer wrapped in the existing `teaching_errors` decorator.

Two findings drive the plan and are both VERIFIED against a live interpreter on this box:
1. **Do NOT route TF through the Phase 5 query layer.** The schema layer flattens `/tf` into a *single* `transforms` LIST-of-STRUCT column (one bag row = one `TFMessage` = a *list* of transforms). Per-edge gap analysis over that requires `UNNEST` + struct-field digging in SQL — strictly worse than iterating the reader stream directly, which is exactly what `inspect.collect_bag_info` already does. Consume the reader stream.
2. **ROS 1 has no `tf2_msgs/msg/TFMessage` in the `rosbags` typestore.** `Stores.ROS1_NOETIC` ships `geometry_msgs/msg/TransformStamped` and `Transform` but NOT `TFMessage` (verified: `TFMessage=False`). ROS 2 ships all three. For ROS 1 *fixtures* you must register the type via `get_types_from_msg("geometry_msgs/TransformStamped[] transforms\n", "tf2_msgs/msg/TFMessage")` (verified round-trip via `serialize_ros1`/`deserialize_ros1`). For *reading real ROS 1 bags*, the bag's own embedded defs supply the type — but a `rosbags`-written ROS 1 fixture has no such defs unless you register them, so this is a real fixture concern (see Test Strategy and Open Q1).

**Primary recommendation:** Add a new `rosbagger-tf` package (workspace member, mirrors `bagq`'s pyproject), with the analysis logic in a `rosbagger_tf` module that consumes the v1 `RosbagsReader` stream and emits a `TfReport` dataclass; render it with rich and wrap the CLI in `teaching_errors`. Detect per-edge gaps via median inter-arrival × a configurable multiplier, with explicit handling of static edges, single-sample edges, and bag boundaries. **The planner MUST resolve the coverage-gate scoping** (`--cov=rosbagger_core --cov=bagq` is hardcoded and would not cover a new package) — see Open Q2.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Open ROS1/ROS2/MCAP bag, deserialize `/tf`+`/tf_static` | v1 Reader (`RosbagsReader`) | — | Phase 2 already owns all bag I/O; TF MUST NOT re-open bags |
| Build parent→child graph over time | `rosbagger-core` analysis module | — | API-first house rule (decision 1); pure-Python, offline-safe |
| Per-edge gap/dropout detection | `rosbagger-core` analysis module | — | Domain logic belongs in core, not the CLI |
| Timeline/table rendering | `bagq`/CLI tier (rich) OR new `rosbagger-tf` CLI | core returns dataclasses | CLI is a thin renderer; all data computed in core |
| Teaching errors (bad path, no TF topics) | CLI tier via `teaching_errors` | `rosbagger_core.errors` typed classes | Established CLI-02/03/04 mechanism |
| Fixture bag with seeded gaps | `tools/make_fixtures.py` (dev) | — | Reuse the Phase 1 generator surface |

## Reuse Map

> Exact module paths + signatures, copied from the live source tree. The TF analyzer is built ON these; it re-implements none of them.

### v1 Bag Reader — THE primary seam (Phase 2)

**Module:** `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py`
**Public API (re-exported from `rosbagger_core.reader.__init__`):** `BagReader`, `Message`, `RosbagsReader`

```python
# rosbagger_core/reader/base.py  — VERIFIED (read in full)
@dataclass(frozen=True, slots=True)
class Message:
    topic: str          # e.g. "/tf"            (connection.topic)
    t: int              # log/receive time, ns
    t_ns: int           # same ns value, explicit
    stamp: int | None   # header.stamp in ns, or None for headerless msgs
    msgtype: str        # e.g. "tf2_msgs/msg/TFMessage"
    msg: object         # the DESERIALIZED message object

class BagReader(abc.ABC):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def read(self, *, topics: set[str] | None = None) -> Iterator[Message]: ...
    @property
    def topics(self) -> Mapping[str, object]: ...        # name -> TopicInfo (msgcount/msgtype)
    @property
    def connections(self) -> Sequence[object]: ...
    @property
    def message_count(self) -> int: ...
    @property
    def duration(self) -> int: ...                       # ns; meaningless if message_count==0
    @property
    def start_time(self) -> int: ...                     # ns
    @property
    def end_time(self) -> int: ...                       # ns
    @property
    def typestore(self) -> object: ...
    @property
    def paths(self) -> list: ...
    def __enter__(self) -> BagReader: ...                # opens
    def __exit__(self, *a) -> bool: ...                  # closes, returns False
```

```python
# rosbagger_core/reader/rosbags_reader.py  — VERIFIED
class RosbagsReader(BagReader):
    def __init__(self, paths: str | Path | Iterable[str | Path], *, default_typestore: object = None) -> None: ...
    # read(topics={...}) does a CONNECTION-LEVEL filter: only those topics are
    # deserialized. read(topics=set()) / unknown topic -> EMPTY stream (NOT all).
```

**How the TF analyzer calls it (the canonical usage, mirrors `bagq info`):**
```python
from rosbagger_core.reader import RosbagsReader
with RosbagsReader(bags) as reader:
    for m in reader.read(topics={"/tf", "/tf_static"}):
        for tfs in m.msg.transforms:               # m.msg is a TFMessage
            parent = tfs.header.frame_id            # PARENT
            child  = tfs.child_frame_id             # CHILD
            edge_time_ns = m.t_ns                   # use the BAG/log time (see Open Q3)
```

Key reader facts (VERIFIED in source):
- `read(topics={...})` filters at the **connection** layer — unreferenced topics are never deserialized. `read(topics=set())` short-circuits to an empty stream (a quirk: `messages(connections=())` would otherwise mean "all", so the reader guards it). An unknown topic name simply matches no connection.
- `_stamp_ns(msg)` is duck-typed: `Message.stamp` is the *first* transform's header stamp pattern only if the msg has a top-level `header` — but **`TFMessage` has NO top-level `header`** (its header is per-`TransformStamped`). So `Message.stamp` will be `None` for `/tf` messages. **Use `m.t_ns` (log time) as the per-message timeline clock, and read each transform's `header.stamp` off `tfs.header.stamp` if you want the sensor stamp.** (See Open Q3 — log time vs header stamp.)
- Multi-bag (`READ-05`) is free: pass a list of paths; `AnyReader` merge-sorts by time.
- `default_typestore=` is the passthrough for legacy/def-less bags.

### Inspect — the closest architectural ANALOG (Phase 4)

**Module:** `packages/rosbagger-core/src/rosbagger_core/inspect.py` — VERIFIED (read in full)
This is the template to copy for `rosbagger-tf`'s core module:
- `collect_bag_info(reader) -> BagInfo` and `collect_table_schemas(reader) -> list[TableSchema]` take an **already-open reader** and return frozen `@dataclass(frozen=True, slots=True)` results.
- Module imports **stdlib only** at top level (`dataclasses`, `pathlib`); the heavy schema/pyarrow imports are **lazy, inside functions**. It is NOT imported by `rosbagger_core/__init__` (offline guard).
- `collect_bag_info` reads ONLY O(1) metadata and never calls `reader.read()`. **The TF analyzer is different — it MUST stream `reader.read()`** (it needs every TF message), so it is NOT O(1). That's expected and fine; just don't list-materialize the stream.

### Query layer — REUSE DECISION: do NOT use it for TF

**Module:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py` — VERIFIED (read in full)
`query(sql, reader, *, backend=None) -> pyarrow.Table`. Recommendation: **the TF analyzer should consume the reader stream directly, not the query layer.** Evidence (VERIFIED against a live interpreter):
- `build_table_schema("tf2_msgs/msg/TFMessage", ts, topic="/tf")` produces a single column `transforms` of type `list<item: struct<header: struct<stamp: struct<sec, nanosec>, frame_id>, child_frame_id, transform: struct<...>>>`. One bag row = one `TFMessage` = a *list* of transforms.
- Per-edge gap analysis (group by `(parent, child)`, compute inter-arrival deltas) over a LIST-of-STRUCT column would require `UNNEST(transforms)` + struct-field projection in SQL — more complex, and it buys nothing over a 20-line Python stream walk.
- The reader's `read(topics={"/tf","/tf_static"})` already gives connection-filtered, deserialized access. That is the right altitude.
- **Cost of this decision:** `rosbagger-tf` does not depend on `duckdb`/`sqlglot` at all — a leaner package. It depends only on `rosbagger-core`'s reader (which pulls `rosbags`).

### Output / formatting conventions (Phase 6)

**Module:** `packages/rosbagger-core/src/rosbagger_core/output/render.py` — VERIFIED
- `rows_for_display(table, *, max_rows=None) -> (names, rows)` and `to_json(table) -> str` are **pyarrow-Table-specific** (temporal-safe coercion of `timestamp[ns]`). The TF report is NOT a pyarrow Table, so these don't directly apply — but the **pattern** does: build a `rich.table.Table`, add columns, add rows, `console.print`.
- The CLI renderers `_render_bag_info` / `_render_table_schemas` / `_render_result` in `bagq/cli.py` are the house style to imitate: a `rich.table.Table` with a title, plus an em-dash (`—`) for missing values.

### CLI framework + teaching errors (Phase 7) — CONFIRMED: typer (not click)

**Module:** `packages/bagq/src/bagq/cli.py` — VERIFIED (read in full)
- Framework is **typer** (`app = typer.Typer(...)`); `click` is present only as a typer dependency (used for the `_PlotCommand` optional-value-flag workaround). `bagq` pyproject: `dependencies = ["rosbagger-core", "typer>=0.15,<1", "rich>=13"]`.
- Commands are thin: lazy-import the core API *inside the body*, call it, render. Top-level CLI imports stay typer/rich-only (offline-guard discipline).
- `teaching_errors(fn)` decorator (applied **below** `@app.command()`): catches the KNOWN typed set + `FileNotFoundError`, prints one red line to stderr via `typer.secho(..., err=True)`, raises `typer.Exit(1)` — **no traceback**. It deliberately does NOT `except Exception` (real bugs must still surface).
- To add a TF error type (e.g. "bag has no `/tf` topics"), follow the 07-02 pattern: a `ValueError` subclass in `rosbagger_core/errors.py` carrying structured data + building its own teaching message, then widen the `teaching_errors` import + `except (...)` tuple by one each.

**Module:** `packages/rosbagger-core/src/rosbagger_core/errors.py` — VERIFIED
- All errors are `ValueError` subclasses, stdlib-only (`difflib` for did-you-mean), carrying `.name`/`.available`/`.suggestions`-style data and building plain-text teaching messages in core. `test_offline_guard.py` asserts this module pulls none of the heavy stack.

### Fixture generator (Phase 1) — the test artifact to extend

**Module:** `tools/make_fixtures.py` — VERIFIED (read in full)
- Writer surface (shared across ROS1 + ROS2): `writer.add_connection(topic, msgtype, typestore=ts)`, `writer.write(conn, t_ns, serialize(msg, msgtype))`.
- ROS 1: `rosbags.rosbag1.Writer` + `ts.serialize_ros1`, typestore `Stores.ROS1_NOETIC`, **Header needs `seq`**.
- ROS 2: `rosbags.rosbag2.Writer(path, version=9, storage_plugin=StoragePlugin.{SQLITE3,MCAP})` + `ts.serialize_cdr`, typestore `Stores.ROS2_HUMBLE`, Header omits `seq`.
- `_make_header(ts, *, sec, nanosec, frame_id, ros1)` already exists and takes `frame_id` — directly reusable for TF transforms.
- `write_def_less_bag(...)` shows the **`get_types_from_msg` + `ts.register(...)`** pattern — exactly what a ROS 1 TF fixture needs (see Test Strategy).
- Deterministic time helpers: `_T0_NS=1_000_000_000`, `_DT_NS=100_000_000`, `_timestamp_ns(i)`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rosbags` | `>=0.11,<0.12` (pinned in root dev group + as a transitive of `rosbagger-core`'s reader) | Open/deserialize bags; `TFMessage` typestore | Already the project's universal reader; no ROS dep `[VERIFIED: root pyproject.toml, dev group]` |
| `typer` | `>=0.15,<1` | TF CLI command | House CLI framework `[VERIFIED: packages/bagq/pyproject.toml]` |
| `rich` | `>=13` | Timeline/table rendering | House table renderer `[VERIFIED: bagq pyproject + cli.py]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `statistics.median` | builtin | Median inter-arrival interval per edge | Gap-detection threshold; no new dep needed `[VERIFIED: stdlib]` |
| `pytest` / `pytest-cov` | `>=8,<10` / `>=6` | Tests + coverage gate | House test stack `[VERIFIED: root dev group]` |

**No new third-party packages are required for Phase 9.** The analysis is pure Python over the existing reader; thresholds use `statistics.median` from the stdlib. This is the lowest-risk path and matches CLAUDE.md (no ROS dep for offline modules).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reader stream walk | Phase 5 `query()` + SQL `UNNEST` | Query layer flattens `/tf` to one LIST-of-STRUCT column; SQL gap analysis is more complex and pulls duckdb/sqlglot into TF for no benefit. Rejected. |
| New `rosbagger-tf` package | New `tf.py` module inside `rosbagger-core` + a `bagq tf` subcommand | A `bagq tf` subcommand is simpler (no new package, auto-covered by the gate) and keeps one CLI. A separate `rosbagger-tf` package matches the ROADMAP naming and the v0.2 "modular cockpit" intent but triggers the coverage-gate gap (Open Q2) and a new console script. **Planner must decide** — see Open Q2. Both are viable; recommend `bagq tf` for v0.2 simplicity unless the modular-package boundary is a hard product requirement. |
| `statistics.median` threshold | Fixed absolute-ms threshold only | Median adapts to each edge's natural rate (10 Hz vs 100 Hz). Offer BOTH: median-multiplier default + optional absolute-ms override. |

## Package Legitimacy Audit

> Phase 9 introduces **no new external packages**. All dependencies (`rosbags`, `typer`, `rich`, `pytest`, `statistics`) are already in the repo's locked manifests and were vetted in prior phases.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `rosbags` | PyPI | mature (existing dep) | — | gitlab.com/ternaris/rosbags | n/a (already vetted Phase 1) | Approved — pre-existing |
| `typer` | PyPI | mature (existing dep) | — | github.com/fastapi/typer | n/a | Approved — pre-existing |
| `rich` | PyPI | mature (existing dep) | — | github.com/Textualize/rich | n/a | Approved — pre-existing |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*No legitimacy gate run was warranted: zero new packages. If the planner adds a new `rosbagger-tf` package, its `dependencies` should be `["rosbagger-core", "typer>=0.15,<1", "rich>=13"]` (mirror `bagq`) — still no new external packages.*

## Architecture Patterns

### System Architecture Diagram

```
bag path(s)
   │
   ▼
RosbagsReader(bags).read(topics={"/tf","/tf_static"})   ← REUSE (Phase 2); connection-filtered
   │   yields Message(topic, t_ns, msg=TFMessage)
   ▼
[ TF ingest ]  for each Message → for each TransformStamped in msg.transforms:
   │              edge_key = (header.frame_id, child_frame_id)   # (parent, child)
   │              record (edge_key, t_ns, is_static = topic == "/tf_static")
   ▼
[ Transform graph + per-edge time series ]
   │   edges: dict[(parent,child) -> EdgeSeries(times=[t_ns...], static=bool)]
   │   graph:  set of (parent,child) directed edges; frames = parents ∪ children
   ▼
[ Gap detector ]  for each DYNAMIC edge:
   │   median_dt = median(diffs(times)); flag gap where dt > multiplier*median_dt (or > abs_ms)
   │   skip static edges; skip single-sample edges; clamp at bag start/end
   ▼
TfReport(edges=[EdgeReport...], frames=[...], gaps=[GapReport...])   ← frozen dataclass (API-first)
   │
   ▼
CLI renderer (rich)  →  edge summary table  +  per-gap timeline rows  +  graph listing
   │   wrapped in @teaching_errors  (no /tf topics → typed ValueError)
   ▼
stdout
```

File-to-implementation mapping is in the Component Responsibilities below — the diagram shows data flow, not files.

### Component Responsibilities

| Component | File (proposed) | Responsibility |
|-----------|-----------------|----------------|
| TF analysis core | `rosbagger_core/tf.py` (if `bagq tf`) OR `packages/rosbagger-tf/src/rosbagger_tf/analyze.py` | Ingest stream, build graph + per-edge series, detect gaps; return `TfReport` |
| Report dataclasses | same module | `EdgeSeries`, `EdgeReport`, `GapReport`, `TfReport` — frozen, slotted |
| CLI command | `bagq/cli.py` `tf` command OR `rosbagger_tf/cli.py` | Thin rich renderer + `teaching_errors` |
| Typed error | `rosbagger_core/errors.py` | `NoTransformsError` (ValueError) when neither `/tf` nor `/tf_static` present |
| Fixture | `tools/make_fixtures.py` | `write_tf_bag(...)` with seeded gaps (ROS1 + ROS2) |

### Recommended Project Structure (if a new package — Option A)
```
packages/rosbagger-tf/
├── pyproject.toml          # name=rosbagger-tf; deps=[rosbagger-core, typer, rich]; script: rosbagger-tf
└── src/rosbagger_tf/
    ├── __init__.py         # __version__ only (stays light, offline guard)
    ├── analyze.py          # core: collect_tf_report(reader) -> TfReport  (API-first)
    └── cli.py              # thin typer app + teaching_errors
```
(Option B — simpler: add `rosbagger_core/tf.py` + a `bagq tf` subcommand; no new package. See Open Q2.)

### Pattern 1: API-first core + thin CLI renderer
**What:** All computation in `rosbagger-core` (or `rosbagger_tf`), returning frozen dataclasses; the CLI only renders.
**When to use:** Always, per house decision 1 (verified in `inspect.py` + `cli.py`).
**Example:**
```python
# Source: mirrors rosbagger_core/inspect.py (VERIFIED in source)
@dataclass(frozen=True, slots=True)
class GapReport:
    parent: str
    child: str
    gap_ns: int          # duration of the gap
    at_ns: int           # bag-relative or absolute start of the gap
    expected_ns: int     # the median interval this gap is measured against

def collect_tf_report(reader) -> TfReport:
    """Stream /tf + /tf_static off an OPEN reader; build graph + detect gaps."""
    edges: dict[tuple[str, str], list[int]] = {}
    static: set[tuple[str, str]] = set()
    for m in reader.read(topics={"/tf", "/tf_static"}):
        is_static = m.topic == "/tf_static"
        for tfs in m.msg.transforms:
            key = (tfs.header.frame_id, tfs.child_frame_id)
            edges.setdefault(key, []).append(m.t_ns)
            if is_static:
                static.add(key)
    ...  # gap detection (see algorithm spec)
```

### Pattern 2: Lazy heavy imports + offline-light top level
**What:** Top-level module imports stdlib only; anything pulling `rosbags` is imported inside functions or never at top level of `__init__`.
**When to use:** Any new core module (offline-guard invariant; `test_offline_guard.py`).
**Note:** `rosbagger_tf.analyze` consuming a *passed-in* reader does not itself need to `import rosbags` — the reader is already open. Keep `rosbagger_tf/__init__` to `__version__` only.

### Pattern 3: Typed teaching error for the empty case
**What:** A `ValueError` subclass that lists what the bag *does* have when `/tf`/`/tf_static` are absent.
**Example:**
```python
# Source: mirrors rosbagger_core/errors.py UnknownTableError (VERIFIED)
class NoTransformsError(ValueError):
    def __init__(self, available_topics: list[str]) -> None:
        self.available = available_topics
        hint = (f" Available topics: {', '.join(sorted(available_topics))}."
                if available_topics else " The bag has no topics.")
        super().__init__(f"Bag has no /tf or /tf_static topics.{hint}")
```

### Anti-Patterns to Avoid
- **Re-opening the bag inside the TF analyzer:** the reader is the seam; accept an open `BagReader`, never construct `AnyReader` directly. (Mirrors `query()`/`inspect` taking `reader`.)
- **Routing TF through `query()` + SQL UNNEST:** the LIST-of-STRUCT shape makes this strictly harder; iterate the stream.
- **Flagging `/tf_static` edges as dropped:** static is published once (latched) and is valid for the whole bag. Static edges contribute to the graph but are NEVER gap-checked.
- **Using `Message.stamp` as the TF clock:** `TFMessage` has no top-level header, so `Message.stamp` is `None` for `/tf`. Use `m.t_ns` (or per-transform `tfs.header.stamp`); decide explicitly (Open Q3).
- **`except Exception` in the CLI:** breaks the no-traceback-for-real-bugs contract (07-RESEARCH Pitfall 4).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Open ROS1/ROS2/MCAP bags | A bag parser / format sniffer | `RosbagsReader` (Phase 2) | Format detection, multi-bag merge, deserialization all done + tested |
| Deserialize `TFMessage` | Manual CDR/ROS1 decode | `reader.read()` yields deserialized `m.msg` | The reader already calls `AnyReader.deserialize` |
| Topic filtering | Read-all-then-filter | `reader.read(topics={"/tf","/tf_static"})` | Connection-level filter; unreferenced topics never deserialized |
| Median / stats | Custom percentile code | `statistics.median` (stdlib) | Correct, tested, zero-dep |
| CLI error formatting | Custom try/except + print | `teaching_errors` + a `ValueError` subclass | House CLI-02/03/04 mechanism, no-traceback contract |
| Fixture bag writing | Hand-rolled bag bytes | `tools/make_fixtures.py` writer helpers | Already writes valid ROS1/ROS2/MCAP, re-openable via AnyReader |

**Key insight:** The only genuinely new code in Phase 9 is (1) the graph/edge-series accumulation, (2) the gap-detection algorithm, and (3) a TF fixture writer. Everything else is glue over verified, tested seams.

## Dropout / Gap Detection Algorithm (implementable spec)

**Input:** for each dynamic edge `(parent, child)`, a time-ordered list of publish timestamps `times = [t0, t1, ... tn]` (nanoseconds, from `m.t_ns`), plus the whole-bag `start_ns`/`end_ns` from the reader.

**Per-edge procedure (dynamic edges only):**
1. **Static skip:** if the edge appears in `/tf_static`, do NOT gap-check it. Record it in the graph as a static edge. (Static is latched — one publish is correct.)
2. **Single-/zero-sample skip:** if `len(times) < 2`, cannot infer a rate → emit no gaps for it, but flag it in the report as `samples=len(times)` (the planner may surface "edge seen only once" as informational, NOT a dropout).
3. **Inter-arrival deltas:** `diffs = [times[i+1] - times[i] for i in range(len(times)-1)]`.
4. **Expected interval:** `expected = statistics.median(diffs)`. Median (not mean) resists the very gaps being detected.
5. **Threshold:** a delta `d` is a gap when `d > multiplier * expected` (default `multiplier = 5.0`, configurable) OR, if an absolute override is set, `d > abs_threshold_ns`. (Offer both; default to the multiplier.)
6. **Emit:** for each offending delta between `times[i]` and `times[i+1]`, emit `GapReport(parent, child, gap_ns=d, at_ns=times[i], expected_ns=expected)`. Report `at_ns` both absolute and bag-relative (`at_ns - start_ns`) so the message reads like the success-criterion example ("odom→base_link unpublished 800ms at t=12.4s").

**Named edge cases (the planner MUST cover each):**
- **Static edges** — never gap-checked (case 1). A `/tf_static` edge that *also* appears in `/tf` (mixed) → treat as dynamic for gap-checking but mark static in the graph; document the tie-break (recommend: presence in `/tf` makes it gap-checkable).
- **Single-sample dynamic edge** — no rate inferable (case 2); informational only.
- **Irregular publishers** — median + multiplier tolerates jitter; a multiplier of 5× avoids false positives on bursty-but-healthy edges. Make it configurable.
- **Bag start/end boundaries** — do NOT synthesize a gap from `start_ns` to the first sample or from the last sample to `end_ns` by default (the publisher may legitimately start late / stop early). Optionally report "edge first seen at +Xs / last seen at −Ys from bag end" as informational. Default: gaps are *between observed samples only*.
- **Two-sample edge** — `diffs` has exactly one element; `median == that element`, so it can never exceed `5×` itself → no false gap. Correct by construction.
- **Multiple parents for one child over time** — TF assumes one parent per child at a time. If `child` appears with two different parents, that is a *graph anomaly* worth surfacing (optional, beyond TF-01's core ask) — at minimum, key edges by `(parent, child)` so the two are distinct series and neither is silently merged.
- **Zero-duration / clock-skew bag** — guard like `inspect.collect_bag_info` does (`duration <= 0` → treat bounds as unknown; don't divide by zero in any rate display).

## Output / Table Format Proposal (consistent with `bagq info`)

Mirror `_render_bag_info`'s house style: a titled `rich.table.Table`, right-justified numerics, em-dash for missing values. Propose **two tables + a header line**:

**1. Edge summary** (one row per edge):
```
TF graph: 4 frames, 3 dynamic edges, 1 static edge   ·   span 0.00s–20.00s

  parent        child        kind     count    rate(Hz)   max gap     gaps
  map           odom         static       1          —         —         —
  odom          base_link    dynamic    198       9.9     0.81s          2
  base_link     laser        dynamic    400      20.0         —          0
```
- `kind`: `static` / `dynamic`; `rate(Hz)` from `count / span_s` (or `—` for static / single-sample); `max gap` = the largest detected gap (or `—`); `gaps` = count of detected gaps.

**2. Gap timeline** (one row per detected gap; the TF-01 deliverable):
```
  parent → child        gap        at (bag t)     at (abs ns)
  odom → base_link       0.80s      t=12.40s       1234...789
  odom → base_link       0.55s      t=15.10s       1234...321
```
- Format gap durations human-readably (ms < 1s, else seconds with 2 decimals) — reuse the *spirit* of `_human_size` (a small `_human_dur` helper in the renderer; presentation-only, like `_human_size`).
- The example string "odom→base_link unpublished 800ms at t=12.4s" maps directly to a gap row.

**Optional `--format json`** (machine-readable): emit the `TfReport` as JSON for the future GUI (Phase 14 consumes module APIs). Not required by TF-01 but cheap and consistent with `bagq query --format json`.

## Test Strategy

> Reuse `tools/make_fixtures.py` to synthesize a bag with `/tf` + `/tf_static` and **seeded gaps**, then assert the three success criteria. The test file follows the `tests/test_reader.py` convention (self-contained `sys.path` insert for `tools`, session-scoped `tmp_path_factory` fixture).

### Fixture: `write_tf_bag(dest_dir, *, ros1: bool) -> Path`
Add to `tools/make_fixtures.py` (reuses `_make_header`, the writer surface, and `_timestamp_ns`):
- **`/tf_static`** (msgtype `tf2_msgs/msg/TFMessage`): one message at `t0` with a single transform `map → odom` (proves static is kept in the graph, never gap-flagged).
- **`/tf`** (dynamic): publish `odom → base_link` at a regular cadence (e.g. every `_DT_NS`), but **omit a contiguous block** of publishes to seed a known gap (e.g. skip indices 8–15 so there is an `~800ms` gap at a known time). Publish a second healthy edge `base_link → laser` with no gap (proves a clean edge reports zero gaps).
- **ROS 2:** `Stores.ROS2_HUMBLE` already has `tf2_msgs/msg/TFMessage` (VERIFIED) — no registration needed; serialize with `serialize_cdr`, Header omits `seq`.
- **ROS 1:** `Stores.ROS1_NOETIC` does **NOT** have `tf2_msgs/msg/TFMessage` (VERIFIED `False`). Register it first (VERIFIED round-trip):
  ```python
  # Source: VERIFIED on this box (rosbags 0.11.x)
  ts = get_typestore(Stores.ROS1_NOETIC)
  ts.register(get_types_from_msg("geometry_msgs/TransformStamped[] transforms\n",
                                  "tf2_msgs/msg/TFMessage"))
  # then serialize_ros1(tfmessage, "tf2_msgs/msg/TFMessage"); ROS1 Header needs seq=0
  ```
  This mirrors the existing `write_def_less_bag` `get_types_from_msg`+`register` pattern.

### Assertions (prove SC1–SC3)
| Success Criterion | Test assertion |
|---|---|
| **SC1** — loads `/tf`+`/tf_static`, builds parent→child graph | `report.frames == {"map","odom","base_link","laser"}`; edges contain `("map","odom")` (static) and `("odom","base_link")`, `("base_link","laser")` (dynamic); static edge flagged `kind=static` |
| **SC2** — per-edge dropouts with timestamps | exactly one `GapReport` for `("odom","base_link")` with `gap_ns ≈ 800_000_000` (±1 sample) at the seeded time; the clean `("base_link","laser")` edge has zero gaps; `("map","odom")` static edge produces NO gap |
| **SC3** — runs on a fixture bag, no ROS install | the whole test runs under `PYTHONPATH="" uv run pytest` (CI is ROS-free); parametrize over `ros1` + both ROS2 storage plugins so all three formats are exercised; `tests/test_offline_guard.py` extended so `import rosbagger_tf` (or `rosbagger_core.tf`) pulls no ROS module |

**Run locally (per MEMORY.md):** `PYTHONPATH="" uv run pytest tests/test_tf.py -q` (bare `uv run pytest` crashes on this ROS-equipped box). CI needs no prefix.

### Coverage
Existing gate is `--cov-fail-under=80` over `--cov=rosbagger_core --cov=bagq` (VERIFIED in root pyproject `addopts`). **If TF logic lands in `rosbagger_core.tf` (Option B), it is auto-covered.** If a new `rosbagger-tf` package is created (Option A), the `addopts` MUST be extended with `--cov=rosbagger_tf` or the new code is invisible to the gate. **This is a required planner action — see Open Q2.**

## Common Pitfalls

### Pitfall 1: ROS 1 has no `TFMessage` type in the rosbags typestore
**What goes wrong:** A naive ROS 1 TF fixture (or assuming symmetry with ROS 2) fails with a `KeyError`/type-not-found at `add_connection`/serialize time.
**Why it happens:** `rosbags` `Stores.ROS1_NOETIC` ships `geometry_msgs/.../TransformStamped` and `Transform` but **not** `tf2_msgs/msg/TFMessage` (VERIFIED). ROS 2 (`Stores.ROS2_HUMBLE`) ships all three.
**How to avoid:** Register the type via `get_types_from_msg("geometry_msgs/TransformStamped[] transforms\n", "tf2_msgs/msg/TFMessage")` before writing a ROS 1 TF fixture (VERIFIED round-trip). Real ROS 1 bags carry embedded defs, so reading a *real* ROS 1 bag is fine — but a `rosbags`-written fixture has no such defs unless registered.
**Warning signs:** `KeyError: 'tf2_msgs/msg/TFMessage'` when building the ROS 1 fixture.

### Pitfall 2: `TFMessage` has no top-level header → `Message.stamp` is `None`
**What goes wrong:** Using `m.stamp` as the per-message timeline clock yields `None` for every `/tf` message; gap math breaks.
**Why it happens:** The reader's `_stamp_ns` reads a top-level `msg.header.stamp`; `TFMessage` has only `transforms` (each `TransformStamped` carries its own `header`). VERIFIED: `TFMessage` fields are `['transforms']`.
**How to avoid:** Use `m.t_ns` (log/receive time) as the timeline clock, or read each transform's own `tfs.header.stamp`. Decide explicitly (Open Q3) and document it. The success-criterion example ("at t=12.4s") implies bag-relative time → `m.t_ns - start_ns` is the natural choice.
**Warning signs:** All gaps reported at `None`/0; rate columns blank.

### Pitfall 3: `/tf` flattens to one LIST-of-STRUCT column in the query layer
**What goes wrong:** Trying to gap-analyze TF via SQL `SELECT ... FROM tf` gives one row per `TFMessage` (a *list* of transforms), not one row per transform.
**Why it happens:** Phase 3/5 maps the message 1:1 to a table row; `transforms` is a `LIST` of `STRUCT` (VERIFIED schema dump).
**How to avoid:** Consume the reader stream directly (this phase's recommended architecture). Don't use `query()`.

### Pitfall 4: Treating `/tf_static` as a dropped dynamic edge
**What goes wrong:** Static transforms (published once, latched) get flagged as "unpublished for 19s" — a false positive on every static edge.
**Why it happens:** Static is published once and is valid forever; a naive gap detector sees one sample then silence.
**How to avoid:** Tag edges by source topic; never gap-check edges seen on `/tf_static`. (Algorithm step 1.)

### Pitfall 5: New module imported by `rosbagger_core/__init__` breaks the offline guard
**What goes wrong:** `test_offline_guard.py` fails because `import rosbagger_core` now pulls `rosbags`.
**Why it happens:** Re-exporting a reader-touching module from the top-level `__init__`.
**How to avoid:** Keep `rosbagger_core/__init__` (and `rosbagger_tf/__init__`) to `__version__` only; import the TF module explicitly at call sites (mirrors `inspect`, `query`, `output`). The TF core module that takes a *passed-in* reader needn't import `rosbags` itself.

### Pitfall 6: New package invisible to the coverage gate
**What goes wrong:** A new `rosbagger-tf` package's lines aren't counted; the 80% gate passes while TF is untested, or a console-script/import wiring bug ships.
**Why it happens:** `addopts` hardcodes `--cov=rosbagger_core --cov=bagq` (VERIFIED).
**How to avoid:** Extend `addopts` with `--cov=rosbagger_tf` (Option A), and add the package as a workspace member + `[tool.uv.sources]` entry. Or use Option B (module in `rosbagger_core`) and avoid the issue entirely.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `tf` (ROS 1, `tf/tfMessage`) | `tf2` (`tf2_msgs/msg/TFMessage`) | ROS Indigo era (~2014) | `/tf` and `/tf_static` are both `tf2_msgs/msg/TFMessage`; the legacy `tf/tfMessage` is obsolete `[CITED: wiki.ros.org/tf2]` |
| Live `tf2_ros.Buffer` lookups | Offline bag-stream analysis | This phase | No ROS install, no live graph; we read recorded `/tf`+`/tf_static` and reconstruct timing offline `[ASSUMED — design intent]` |

**Deprecated/outdated:**
- The ROS 1 `tf` package / `tf/tfMessage` type: superseded by `tf2`. This phase targets `tf2_msgs/msg/TFMessage` only (the type both `/tf` and `/tf_static` carry).

## TF / tf2 Message Model (domain reference)

VERIFIED against the live `rosbags` typestore on this box:
- **`/tf` and `/tf_static` are both `tf2_msgs/msg/TFMessage`.** `TFMessage` fields: `transforms` (a `geometry_msgs/msg/TransformStamped[]`). No top-level header.
- **`geometry_msgs/msg/TransformStamped`** fields: `header` (`std_msgs/msg/Header`), `child_frame_id` (string), `transform` (`geometry_msgs/msg/Transform`).
  - `header.stamp` → `builtin_interfaces/msg/Time` (`sec: int32`, `nanosec: uint32`) — `rosbags` normalizes ROS 1's `secs/nsecs` to `sec/nanosec` (VERIFIED in `_stamp_ns`).
  - `header.frame_id` → the **PARENT** frame.
  - `child_frame_id` → the **CHILD** frame.
  - `transform.translation` → `Vector3 (x,y,z)`, `transform.rotation` → `Quaternion (x,y,z,w)`.
- **Edge model:** each `TransformStamped` is a directed edge `parent (header.frame_id) → child (child_frame_id)`. Key edges by `(parent, child)`. A frame has one parent at a time in a well-formed graph; keying by the pair keeps multi-parent anomalies as distinct series rather than silently merging.
- **Type-name spelling:** the canonical modern spelling in the `rosbags` typestore is `tf2_msgs/msg/TFMessage` (with the `/msg/` infix) for BOTH ROS 1 and ROS 2 once registered. Real ROS 1 bags may record the historical `tf2_msgs/TFMessage`; `rosbags`'s `AnyReader` normalizes type names — but **do not assume**: match `/tf`/`/tf_static` by **topic name**, not by msgtype string, so spelling variance never matters. (See Open Q4.)
- **`/tf_static` semantics:** latched/transient-local — published once (or rarely), valid for the whole bag. Contributes graph edges; must NOT be gap-checked. `[CITED: wiki.ros.org/tf2 — static transforms are published once and considered valid for all time]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default gap multiplier of 5× median is a sensible out-of-the-box threshold | Algorithm | Too sensitive → false-positive gaps; too loose → misses real dropouts. Mitigated by making it configurable. |
| A2 | The TF clock should be bag log time (`m.t_ns`), bag-relative for display | Algorithm/Output, Open Q3 | If users expect *header* stamp timing (sensor time), gap timestamps shift. Surface both or make it a flag. |
| A3 | Match `/tf`+`/tf_static` by topic NAME, not msgtype string | Domain model, Open Q4 | If a bag uses non-standard TF topic names, they're missed. Standard names are near-universal; offer a `--tf-topic` override if needed. |
| A4 | Default boundary behavior: gaps only *between observed samples* (no synthetic start/end gap) | Algorithm edge cases | A late-starting / early-stopping publisher won't be flagged by default; surfaced as informational instead. |
| A5 | `bagq tf` subcommand vs new `rosbagger-tf` package is a planner choice; both satisfy TF-01 | Stack/Open Q2 | ROADMAP names `rosbagger-tf`; if the modular package boundary is a hard requirement, Option B is wrong. |

## Open Questions (RESOLVED)

> All four questions were resolved during plan-phase by the locked decisions (D1–D10) and are reflected in the Phase 9 plans (09-01/09-02/09-03). Inline resolutions below.

1. **ROS 1 TF fixture registration vs. real-bag reading.** — **RESOLVED → D10:** ROS 1 fixtures register `tf2_msgs/msg/TFMessage` via `get_types_from_msg`; real ROS 1 bags use embedded defs (no extra code). Scope is fixture-based per SC3.
   - What we know: ROS 2 typestore has `TFMessage`; ROS 1 does not, but it registers + round-trips via `get_types_from_msg` (VERIFIED). Real ROS 1 bags carry embedded defs.
   - What's unclear: whether the phase needs to *read* arbitrary real ROS 1 TF bags (defs embedded → fine) or only its own fixtures (must register). The success criterion only requires a *fixture* bag.
   - Recommendation: ROS 1 fixture registers the type (Test Strategy). For real-bag robustness, the reader already passes embedded defs through; no extra code needed. Confirm scope at plan time.

2. **`bagq tf` subcommand (Option B) vs new `rosbagger-tf` package (Option A).** — **RESOLVED → D1 (explicit user decision):** Option B — `bagq tf` subcommand with logic in `rosbagger_core/tf.py`, auto-covered by the existing `--cov=rosbagger_core` gate; no new package, no `[tool.uv.sources]`/console-script/`addopts`/`uv.lock` edits.
   - What we know: ROADMAP and the v0.2 "modular cockpit" name the deliverable `rosbagger-tf` (a package + presumably a `rosbagger-tf` console script). The coverage gate (`--cov=rosbagger_core --cov=bagq`) is hardcoded and would not see a new package without an `addopts` edit.
   - What's unclear: whether the product wants a separate installable package/CLI now, or a `bagq tf` subcommand is acceptable for v0.2.
   - Recommendation: If following the ROADMAP literally → Option A (new package), and the planner MUST (a) add it as a `packages/*` workspace member, (b) add `[tool.uv.sources]` + the `rosbagger-tf` console script, (c) extend `addopts` with `--cov=rosbagger_tf`, (d) re-lock `uv.lock`. If pragmatic simplicity is preferred → Option B (`rosbagger_core/tf.py` + `bagq tf`), auto-covered, one CLI. **Resolve before planning** — it changes the plan/wave shape.

3. **Timeline clock: bag log time vs per-transform header stamp.** — **RESOLVED → D3:** bag-relative log time (`m.t_ns - start_ns`); `m.stamp` is `None` for `/tf` so header-stamp timing is not used by default.
   - What we know: `Message.stamp` is `None` for `/tf` (no top-level header); both `m.t_ns` and `tfs.header.stamp` are available.
   - What's unclear: which the user expects for "at t=12.4s".
   - Recommendation: Default to bag-relative log time (`m.t_ns - start_ns`) — robust and always present. Optionally expose header-stamp-based timing later. Document the choice.

4. **TF topic-name matching.** — **RESOLVED → D4:** match `/tf` + `/tf_static` by topic name; optional `--tf-topic`/`--static-topic` overrides (low priority, not required by TF-01).
   - What we know: `/tf` and `/tf_static` are the universal conventions; matching by topic name sidesteps any msgtype-spelling variance (`tf2_msgs/TFMessage` vs `tf2_msgs/msg/TFMessage`).
   - Recommendation: Match by the two standard topic names; consider a `--tf-topic` / `--static-topic` override flag for non-standard recordings (low priority; not required by TF-01).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `rosbags` | reader + TF fixture + type registration | ✓ | 0.11.x (pinned `>=0.11,<0.12`) | — |
| Python | everything | ✓ | ≥3.10 (`.python-version` pins 3.10 floor) | — |
| `typer` / `rich` | CLI + rendering | ✓ | typer >=0.15,<1, rich >=13 | — |
| `pytest` / `pytest-cov` | tests + gate | ✓ | >=8,<10 / >=6 | — |
| ROS install | NOTHING (offline phase) | ✗ (intentional) | — | n/a — phase is offline by design |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. (No ROS install is required and none should be added — CLAUDE.md offline constraint.)

> Note: the dev host has ROS 2 Humble on `PYTHONPATH`; per MEMORY.md, run local tests with `PYTHONPATH=""`. CI is ROS-free.

## Sources

### Primary (HIGH confidence)
- Live source tree (read in full): `reader/base.py`, `reader/rosbags_reader.py`, `reader/__init__.py`, `inspect.py`, `backend/query.py`, `output/render.py`, `errors.py`, `bagq/cli.py`, `schema/__init__.py`, `tools/make_fixtures.py`, root + `bagq` `pyproject.toml`, `.planning/{REQUIREMENTS,ROADMAP,STATE}.md`, `CLAUDE.md`.
- Live interpreter on this box (`PYTHONPATH="" .venv/bin/python`): verified `TFMessage`/`TransformStamped` typestore presence per store; verified field layouts; verified ROS 2 `serialize_cdr` and ROS 1 register-then-`serialize_ros1` round-trips; verified the `/tf` → LIST-of-STRUCT schema flatten; verified `sanitize_table_name("/tf")=="tf"`.

### Secondary (MEDIUM confidence)
- (none required — the domain model was verified directly against the typestore rather than from docs.)

### Tertiary (LOW confidence)
- tf2 conventions (`/tf`+`/tf_static` are `tf2_msgs/msg/TFMessage`; static is latched/valid-for-all-time; `header.frame_id`=parent, `child_frame_id`=child): consistent with standard ROS tf2 documentation (`wiki.ros.org/tf2`, `docs.ros.org` tf2 design). Marked `[CITED]` from training knowledge of the tf2 spec; the *type/field shape* is independently VERIFIED against the typestore above, so the residual uncertainty is only in the prose semantics, which match the verified field names.

## Metadata

**Confidence breakdown:**
- Reuse map (reader/inspect/CLI/fixtures): HIGH — read from live source, signatures copied verbatim.
- Domain model (TFMessage/TransformStamped shape, ROS1-vs-ROS2 type availability): HIGH — verified against the running `rosbags` typestore, including serialize round-trips.
- Architecture recommendation (stream over query layer): HIGH — the LIST-of-STRUCT flatten was reproduced live.
- Gap-detection algorithm: MEDIUM — the algorithm is sound and standard, but the default threshold (5× median) and the clock choice (log time vs header stamp) are design defaults the user/planner should confirm (A1/A2, Open Q3).
- Package-layout decision: MEDIUM — both options work; the ROADMAP names a package but the coverage gate complicates it (Open Q2, blocking for plan shape).

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (stable; the reuse surface is local source and the `rosbags` pin is fixed at `>=0.11,<0.12`). Re-verify only if `rosbags` is unpinned/upgraded or the reader API changes.
