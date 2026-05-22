# Phase 4: Inspect - Research

**Researched:** 2026-05-22
**Domain:** Bag overview reporting (`bagq info` / `bagq tables`) over the Phase 2 reader + Phase 3 schema, no ROS install
**Confidence:** HIGH

## Summary

Phase 4 builds two read-only overview commands — `bagq info BAG` and `bagq tables BAG` — on top of the existing Phase 2 reader (`RosbagsReader` over `rosbags.highlevel.AnyReader`) and Phase 3 schema layer (`build_table_schema`, `TableNameResolver`, `ColumnDef`/`TableSchema`). The single most important empirical finding: **every datum these commands need is available as O(1) metadata directly from `AnyReader` — no message iteration required.** `AnyReader` exposes `message_count`, `start_time`, `end_time`, and `duration` (whole-bag, nanoseconds) as properties, and `topics` / `connections` give per-topic and per-connection message counts and message types. This was verified by reading the installed `rosbags` 0.11.2 source AND running it against this project's own fixture bags this session. The implication for the planner: `info` and `tables` are cheap, deterministic, and never deserialize a message body — the heavy-blob/large-bag pitfall is avoided by construction.

The architecture must follow design decision 1 (API-first): the inspect capability lives in a new `rosbagger_core` Python module (recommend `rosbagger_core/inspect.py`) that returns backend-neutral dataclasses (`BagInfo` + `TopicInfo`), and the `bagq` CLI commands are thin presentation wrappers that call that API and render with `rich`. This keeps CLI–GUI parity (v2 GUI's Inspect panel reuses the same API) and lets offline tests exercise the API directly (no subprocess). The reader currently exposes `topics`/`connections` but **not** time bounds or the typestore as public properties — the recommended path is to add a small, additive public surface to `RosbagsReader` (a `duration`/`start_time`/`end_time`/`message_count` passthrough and a public `typestore` property) so the inspect module never reaches into `reader._reader`.

Two real edge cases must be handled, both verified empirically: (1) an **empty bag** (zero messages) makes `start_time` return `sys.maxsize` and `duration` go large-negative — guard with `message_count == 0`; (2) a topic carrying **two different message types** makes `TopicInfo.msgtype` return `None`, which makes `build_table_schema(None, ...)` raise `KeyError` — `tables` must skip or fall back to per-connection msgtype. The size semantics differ by format: a ROS 1 `.bag` is a single file (`stat().st_size`); a ROS 2 sqlite/mcap bag is a **directory** (`metadata.yaml` + `.db3`/`.mcap`) whose size is the sum of its files.

**Primary recommendation:** Add a new `rosbagger_core/inspect.py` exposing `BagInfo`/`TopicInfo` dataclasses + a `collect_bag_info(reader) -> BagInfo` function and a `collect_table_schemas(reader) -> list[TableSchema]` function (both O(1)-metadata, no iteration); extend `RosbagsReader` with public `duration`/`start_time`/`end_time`/`message_count`/`typestore` passthroughs; add `info` and `tables` subcommands to the existing `bagq/cli.py` typer `app` as thin `rich`-rendering wrappers. Per-topic Hz = `topic_count / whole_bag_duration_seconds` (documented approximation; guard zero/negative duration).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Open bag, expose topic/type/count/time metadata | `rosbagger-core` reader (`RosbagsReader`) | `rosbags` `AnyReader` | The reader already wraps `AnyReader`; metadata is read off it without deserialization |
| Compute `BagInfo` (per-topic counts, Hz, totals, size) | `rosbagger-core` inspect API (`inspect.py`) | reader | API-first decision 1: capability lives in core, not the CLI |
| Derive table name + column schema per topic | `rosbagger-core` schema (`build_table_schema` + `TableNameResolver`) | reader's `typestore` | Phase 3 already owns name sanitization and schema flattening |
| File-size measurement across formats | `rosbagger-core` inspect API | stdlib `pathlib` | Format-aware (file vs directory) logic belongs with the data model, reusable by GUI |
| Render `info` / `tables` as terminal tables | `bagq` CLI (`cli.py`) | `rich.table.Table` | Thin presentation layer; the API returns data, the CLI formats it |
| `--json` machine-readable output (optional) | `bagq` CLI | stdlib `json` + `dataclasses.asdict` | Presentation choice over the same `BagInfo`; Claude's discretion |

**Why this matters:** The temptation is to put the count/Hz/size computation inline in the CLI command functions. That breaks decision 1 (API-first) and the offline-test strategy (tests would need subprocess). All computation belongs in `rosbagger_core.inspect`; the CLI only renders.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rosbags` | 0.11.2 (installed, verified) | `AnyReader` metadata: `message_count`, `start_time`, `end_time`, `duration`, `topics`, `connections`, `typestore` | Already the project's reader backend (Phase 2); metadata is O(1), no ROS install |
| `rich` | 15.0.0 (installed, verified) | `rich.table.Table` + `rich.console.Console` for terminal table rendering | Already a direct dependency of `bagq` (`rich>=13`); design spec §4.3 names it for table output |
| `typer` | 0.25.1 (installed, verified) | CLI subcommand wiring (`@app.command()`) for `info` / `tables` | Already the `bagq` CLI framework (`typer>=0.15,<1`) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `pathlib` | 3.10+ | File-size measurement (`Path.stat().st_size`, `Path.rglob`, `Path.is_dir`) | Computing bag size for file (ROS1) vs directory (ROS2) layouts |
| stdlib `dataclasses` | 3.10+ | `@dataclass(frozen=True, slots=True)` for `BagInfo`/`TopicInfo`; `asdict` for `--json` | The backend-neutral data model the API returns (mirrors `Message`, `ColumnDef`) |
| stdlib `json` | 3.10+ | `--json` machine-readable output (Claude's discretion option) | If `--json` flag is added to either command |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `rich.table.Table` | `tabulate` | Design spec §4.3 mentions both, but `rich` already ships with `bagq` and renders nicer; no reason to add `tabulate` |
| New `inspect.py` module name | `overview.py` / `metadata.py` | `inspect` shadows the stdlib `inspect` module name — but only as a submodule path (`rosbagger_core.inspect`), which does NOT shadow the top-level stdlib import; still, see Pitfall 6 — prefer `inspect.py` for design-spec naming alignment, OR `bag_info.py` if shadowing concerns the planner |
| Reaching into `reader._reader.typestore` | Add public `typestore` property on `RosbagsReader` | Public property is cleaner (avoids private-attribute coupling) and is a tiny additive change; recommend the property |

**Installation:** No new dependencies. All required libraries (`rosbags`, `rich`, `typer`) are already declared and installed. `bagq` already depends on `rich>=13` and `typer>=0.15,<1`; `rosbagger-core` already depends on `rosbags>=0.11,<0.12`.

**Version verification (this session):**
```
rosbags == 0.11.2   (importlib.metadata, .venv — VERIFIED)
rich    == 15.0.0   (VERIFIED; bagq declares rich>=13)
typer   == 0.25.1   (VERIFIED; bagq declares typer>=0.15,<1)
```

## Package Legitimacy Audit

> No new external packages are installed in this phase. All libraries used (`rosbags`, `rich`, `typer`, stdlib) are already vendored in the project's existing, audited dependency set (verified in `packages/bagq/pyproject.toml` and `packages/rosbagger-core/pyproject.toml`). slopcheck is not applicable — no install step.

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| `rosbags` | PyPI | Already a Phase 2 dependency (`>=0.11,<0.12`), installed 0.11.2 | Pre-approved (no new install) |
| `rich` | PyPI | Already a `bagq` dependency (`>=13`), installed 15.0.0 | Pre-approved (no new install) |
| `typer` | PyPI | Already a `bagq` dependency (`>=0.15,<1`), installed 0.25.1 | Pre-approved (no new install) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INSP-01 | `bagq info BAG` lists each topic with its message type and message count | `reader.topics` → `dict[str, TopicInfo]`; `TopicInfo(msgtype, msgdef, msgcount, connections)` gives msgtype + msgcount per topic, O(1), no iteration (VERIFIED). Multi-msgtype topic → `msgtype is None` (handle: Pitfall 4). |
| INSP-02 | `bagq info BAG` reports duration, approximate per-topic Hz, and size | `reader.duration`/`start_time`/`end_time` (ns, whole-bag, O(1)); per-topic Hz = `topic.msgcount / duration_seconds` (whole-bag span — see Pattern 2 + Pitfall 2); size = file vs directory sum (Pattern 3). Empty-bag guard required (Pitfall 1). |
| INSP-03 | `bagq tables BAG` prints each topic's table name and column schema | `TableNameResolver.resolve(topic)` (Phase 3) → table name; `build_table_schema(msgtype, typestore, topic=topic)` (Phase 3) → `TableSchema.columns`; `ColumnDef.name` + `str(ColumnDef.arrow_type)` for the column listing; `is_heavy_blob` flag to mark/hide blobs (Pattern 4). Needs `reader.typestore` (add public property). |

## Architecture Patterns

### System Architecture Diagram

```
   bagq info BAG / bagq tables BAG   (user command)
                │
                ▼
   ┌─────────────────────────────────────────────┐
   │  bagq/cli.py   (THIN presentation layer)      │
   │  • @app.command() info / tables               │
   │  • parse BAG path arg(s) + --json flag        │
   │  • call core inspect API                      │
   │  • render BagInfo / TableSchema via rich.Table│
   └───────────────┬───────────────────────────────┘
                   │ (data, not formatting)
                   ▼
   ┌─────────────────────────────────────────────┐
   │  rosbagger_core/inspect.py   (the API)        │
   │  collect_bag_info(reader) -> BagInfo          │
   │  collect_table_schemas(reader) -> [TableSchema]│
   │   • reads O(1) metadata only — NO read() loop │
   └───────┬───────────────────────────┬───────────┘
           │                           │
           ▼                           ▼
   ┌──────────────────┐      ┌────────────────────────┐
   │ RosbagsReader     │      │ schema layer (Phase 3)  │
   │ (Phase 2)         │      │ build_table_schema()    │
   │ .topics           │      │ TableNameResolver       │
   │ .connections      │      │ ColumnDef/TableSchema   │
   │ .duration  *NEW   │      └────────────────────────┘
   │ .start/end_time*N │                 ▲
   │ .message_count *N │                 │ typestore
   │ .typestore   *NEW │─────────────────┘
   └───────┬───────────┘
           ▼
   rosbags.highlevel.AnyReader  (O(1) metadata: message_count,
   start_time, end_time, duration, topics, connections, typestore)
           │
           ▼
   on-disk bag(s): ROS1 .bag (file) | ROS2 sqlite/mcap (directory)

   *NEW = small additive public passthrough/property on RosbagsReader
```

A reader can trace `bagq info my.bag` → CLI parses path → `collect_bag_info(reader)` opens the reader and reads `.topics`/`.duration`/file-size → returns `BagInfo` → CLI renders a `rich.Table`. No arrow leg, no `read()` iteration, no message deserialization.

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/
├── inspect.py            # NEW: BagInfo + TopicInfo dataclasses, collect_bag_info(), collect_table_schemas()
├── reader/
│   ├── base.py           # BagReader ABC (add optional time/typestore to the contract — see below)
│   └── rosbags_reader.py # add public duration/start_time/end_time/message_count/typestore passthroughs
└── schema/               # Phase 3, unchanged (consumed read-only)

packages/bagq/src/bagq/
└── cli.py                # EXTEND existing `app`: add @app.command() info + tables
```

> Do NOT add `inspect` to `rosbagger_core/__init__.py` top-level imports — it transitively imports `reader`/`schema` (hence `rosbags`/`pyarrow`), and the offline invariant requires `import rosbagger_core` to stay light (verified in `__init__.py` docstring + `tests/test_offline_guard.py`). Import it explicitly as `from rosbagger_core.inspect import ...` (mirrors how `reader`/`schema` subpackages are used).

### Pattern 1: API-first split (the core architectural requirement)
**What:** The capability lives in `rosbagger_core.inspect`; the CLI calls it and renders. The API returns backend-neutral dataclasses; it never prints.
**When to use:** Both `info` and `tables`.
**Example:**
```python
# rosbagger_core/inspect.py — Source: design decision 1 (API-first), VERIFIED metadata API
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TopicInfo:
    """Per-topic overview row for `bagq info`."""
    topic: str
    msgtype: str | None      # None when the topic carries >1 msgtype (Pitfall 4)
    count: int
    hz: float | None         # None when duration is unknown/zero (Pitfall 1/2)

@dataclass(frozen=True, slots=True)
class BagInfo:
    """Whole-bag overview returned by collect_bag_info()."""
    topics: list[TopicInfo]
    message_count: int
    start_time_ns: int | None   # None on empty bag (Pitfall 1)
    end_time_ns: int | None     # None on empty bag
    duration_ns: int | None     # None on empty bag
    size_bytes: int

def collect_bag_info(reader) -> BagInfo:
    """Read O(1) metadata off an OPEN reader — no message iteration."""
    count = reader.message_count
    if count == 0:                                   # empty-bag guard (Pitfall 1)
        start = end = dur = None
    else:
        start, end, dur = reader.start_time, reader.end_time, reader.duration
    dur_s = (dur / 1e9) if (dur and dur > 0) else None
    topics = [
        TopicInfo(
            topic=name,
            msgtype=info.msgtype,                    # may be None (Pitfall 4)
            count=info.msgcount,
            hz=(info.msgcount / dur_s) if dur_s else None,
        )
        for name, info in sorted(reader.topics.items())
    ]
    return BagInfo(topics, count, start, end, dur, _bag_size_bytes(reader))
```

### Pattern 2: Per-topic Hz from the whole-bag span
**What:** `rosbags` does NOT expose per-topic time bounds (verified: `Connection` fields are `(id, topic, msgtype, msgdef, digest, msgcount, ext, owner)` — no start/end; per-bag readers only carry whole-bag `start_time`/`end_time`). So per-topic Hz uses the **whole-bag** duration: `hz = topic_count / whole_bag_duration_seconds`.
**When to use:** INSP-02 per-topic Hz.
**Tradeoff (document in output/help):** This is an *approximation*. A topic that only published during the first half of the bag will report half its true rate. Computing exact per-topic spans would require a full O(n) iteration tracking first/last `t` per topic — explicitly out of scope for v1 (the design spec says "approximate Hz (count / duration)"). The single-source-of-duration approach matches the spec's formula literally.
**Edge cases:** single message on a topic over zero total duration → `hz = None` (guarded); whole-bag `duration == 0` (all messages same timestamp) → `hz = None`.

### Pattern 3: Format-aware size measurement
**What:** ROS 1 bags are a single `.bag` file; ROS 2 sqlite/mcap bags are a **directory** containing `metadata.yaml` + the data file. Size = file size for a file, or sum of all contained file sizes for a directory.
**When to use:** INSP-02 size.
**Example:**
```python
# Source: VERIFIED against fixtures — ros1.bag=file(9440B); ros2_sqlite/=dir(metadata.yaml+ros2_sqlite.db3); ros2_mcap/=dir(metadata.yaml+ros2_mcap.mcap)
from pathlib import Path

def _path_size_bytes(p: Path) -> int:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size

def _bag_size_bytes(reader) -> int:
    # Multi-bag (READ-05): sum every opened path. Reader exposes its paths.
    return sum(_path_size_bytes(Path(p)) for p in reader.paths)
```
**Multi-bag note:** For multiple bag paths opened as one dataset (READ-05), sum the sizes of all paths. The reader currently stores `self._paths` privately — add a public `paths` property (additive) so inspect can read them without `reader._paths`.

### Pattern 4: `tables` from Phase 3 schema, with heavy-blob marking
**What:** For each topic, resolve the table name (`TableNameResolver`) and build the schema (`build_table_schema(msgtype, typestore, topic=topic)`). List columns from `TableSchema.columns`: each `ColumnDef` gives `.name`, `str(.arrow_type)` (renders as `timestamp[ns]`, `int64`, `list<item: uint8>`, etc. — VERIFIED), and `.is_heavy_blob`.
**When to use:** INSP-03.
**Example:**
```python
# rosbagger_core/inspect.py — Source: VERIFIED end-to-end against fixtures this session
from rosbagger_core.schema import build_table_schema, TableNameResolver

def collect_table_schemas(reader) -> list:
    """Return one TableSchema per topic (Phase 3 objects)."""
    typestore = reader.typestore           # NEW public property (see below)
    resolver = TableNameResolver()
    out = []
    for topic, info in sorted(reader.topics.items()):
        resolver.resolve(topic)            # records mapping; build_table_schema also sanitizes
        if info.msgtype is None:           # multi-msgtype topic (Pitfall 4) — skip or fall back
            continue                       # planner: decide skip vs per-connection fallback
        out.append(build_table_schema(info.msgtype, typestore, topic=topic))
    return out
```
**Heavy-blob rendering:** `TableSchema.column_names()` hides heavy blobs by default; `column_names(include={"data"})` shows them. For `tables`, **show all columns** (the user is asking "what columns exist?") but visually mark heavy blobs (e.g. a `lazy` flag column, dim styling, or a `(blob)` suffix). Use `is_heavy_blob` per `ColumnDef` directly rather than the filtering helper, since the goal is to display every column with its laziness annotated. VERIFIED: `sensor_msgs/msg/Image.data` → `arrow_type=list<item: uint8>`, `is_heavy_blob=True`.

### Pattern 5: Reader public surface additions (small, additive)
**What:** `RosbagsReader` currently exposes only `topics`/`connections` publicly. The inspect API needs duration/time/count and the typestore. Add thin public passthroughs so inspect never touches `reader._reader` or `reader._paths`.
**When to use:** Before/within plan 04-01 and 04-02.
**Example:**
```python
# rosbags_reader.py — additive properties (mirror existing topics/connections guard style)
    @property
    def message_count(self) -> int:
        if self._reader is None:
            raise RuntimeError("RosbagsReader.message_count accessed before open()")
        return self._reader.message_count

    @property
    def duration(self) -> int:        # nanoseconds; meaningless if message_count == 0 (callers guard)
        if self._reader is None:
            raise RuntimeError("RosbagsReader.duration accessed before open()")
        return self._reader.duration

    @property                          # likewise start_time / end_time (ns)
    def typestore(self) -> object:     # rosbags Typestore; loosely typed (base.py stays backend-agnostic)
        if self._reader is None:
            raise RuntimeError("RosbagsReader.typestore accessed before open()")
        return self._reader.typestore

    @property
    def paths(self) -> list:           # the opened bag paths (for size; multi-bag READ-05)
        return list(self._paths)
```
**Contract note:** `BagReader` (the ABC in `base.py`) currently declares only `topics`/`connections` as abstract metadata. The planner may add `duration`/`start_time`/`end_time`/`message_count`/`typestore`/`paths` to the ABC for a future `rosbag2_py` backend, OR keep them concrete-only on `RosbagsReader` for v1. Keeping the ABC backend-agnostic argues for a loose `object`/`int | None` return typing if added to the contract. Either is defensible; concrete-only on `RosbagsReader` is the smaller change and v1 has one backend.

### Pattern 6: typer subcommand structure (extend existing `app`)
**What:** Add `info` and `tables` as `@app.command()` functions in the existing `bagq/cli.py`. Each takes a BAG path argument (and optionally multiple — `list[Path]` — for READ-05). Open `RosbagsReader` via its context manager, call the core API, render.
**Example:**
```python
# bagq/cli.py — extend the existing `app`; import core lazily inside the function (keep module light)
import typer
from pathlib import Path
from typing import List

@app.command()
def info(
    bags: List[Path] = typer.Argument(..., help="One or more bag paths (file or directory)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List topics, message types, counts, duration, approx Hz, and size."""
    from rosbagger_core.inspect import collect_bag_info
    from rosbagger_core.reader import RosbagsReader
    with RosbagsReader(bags) as reader:        # AnyReaderError/FileNotFoundError propagate (Phase 7 owns teaching)
        bag_info = collect_bag_info(reader)
    _render_info(bag_info, json_out)           # rich.Table or json.dumps(asdict(...))
```
**Import discipline:** keep `import rosbagger_core.inspect` / `reader` **inside** the command body, not at module top level — preserves the offline-guard fast `bagq --help` and avoids paying the `rosbags` import on every CLI invocation (matches `cli.py`'s existing "import only typer/rich at top" rule).

### Anti-Patterns to Avoid
- **Iterating `reader.read()` to count messages or find time bounds.** All counts and whole-bag time bounds are O(1) metadata (`message_count`, `topics[*].msgcount`, `duration`). Iterating deserializes every message (slow, loads heavy blobs) for data you already have. VERIFIED: metadata access is faster than iteration even on a 9-message bag; on real bags the gap is enormous.
- **Computing counts/Hz/size inline in the CLI command.** Breaks decision 1 (API-first) and the offline-test strategy. Put it all in `rosbagger_core.inspect`.
- **Reaching into `reader._reader` / `reader._paths` from the inspect module.** Couples to reader internals. Add public properties instead.
- **Calling `build_table_schema(None, ...)`.** Raises `KeyError: None` (VERIFIED). Guard `info.msgtype is None` first (Pitfall 4).
- **Treating the bag path as always a file.** ROS 2 bags are directories. Use `_path_size_bytes` (file-or-dir).
- **Using `header.stamp` for duration.** Use log time `t` (which is what `AnyReader.start_time`/`end_time` are built from). `stamp` is the message's own header time and is `None` for headerless topics; duration must use receive/log time.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-topic message counts | A `read()` loop with a `Counter` | `reader.topics[name].msgcount` (or `Connection.msgcount`) | O(1) metadata, no deserialization; `rosbags` sums across connections/bags already |
| Whole-bag duration / time bounds | Tracking min/max `t` while iterating | `reader.start_time` / `end_time` / `duration` | O(1) properties; `rosbags` computes `min`/`max` across sub-readers |
| Multi-bag count/duration aggregation | Summing per-bag yourself | `AnyReader` already aggregates across opened bags | `message_count = sum(...)`, `topics` merges by name across bags (verified) |
| Table-name sanitization + collisions | A regex in the CLI | `rosbagger_core.schema.TableNameResolver` / `sanitize_table_name` | Phase 3 owns it; handles SQL-safety, leading-digit, case-insensitive collisions |
| Column schema from a msgtype | Walking the message AST | `rosbagger_core.schema.build_table_schema` | Phase 3 owns the flatten walk, dotted columns, LIST/STRUCT, heavy-blob flag |
| Terminal table formatting | Manual column-width / padding | `rich.table.Table` | Already a `bagq` dep; handles alignment, wrapping, styling |
| Bag-format detection (file vs dir, ROS1 vs ROS2) | A file sniffer | `AnyReader` (for reading) + `Path.is_dir()` (for size only) | `AnyReader` already detects format; size only needs file-vs-dir |

**Key insight:** Phases 2 and 3 already did the hard work. Phase 4 is almost entirely **wiring** existing metadata and existing schema objects into two dataclasses and two `rich` tables. The only genuinely new logic is (a) the Hz formula with its guards, (b) format-aware size, and (c) the multi-msgtype/empty-bag edge handling. Resist re-deriving anything the reader or schema layer already provides.

## Runtime State Inventory

> Not applicable — Phase 4 is a greenfield feature addition (two new read-only commands + one new module + additive reader properties). It renames nothing, migrates no stored data, registers no OS state, and reads bags read-only. No grep-invisible runtime state. (Verified: the change set is new code only; no existing identifiers are renamed.)

## Common Pitfalls

### Pitfall 1: Empty bag → garbage time bounds (negative duration)
**What goes wrong:** On a bag with zero messages, `AnyReader.start_time` returns `sys.maxsize` (9223372036854775807) and `end_time` returns `0`, so `duration` is large-negative (−9223372036854775807). VERIFIED this session. `info` would print an absurd duration and NaN/garbage Hz.
**Why it happens:** `start_time = min(reader.start_time for reader in readers)`; an empty reader's `start_time` defaults to `sys.maxsize`. No upstream guard. (Documented in 02-RESEARCH.md Pitfall 3.)
**How to avoid:** Guard on `message_count == 0` → set `start/end/duration` to `None` and all Hz to `None`. Render `None` as `"—"` or `"n/a"`. A zero-connection bag opens cleanly (`topics={}`, `connections=[]`) — `tables` should print "no topics" rather than crash.
**Warning signs:** Negative duration; `start_time` near 9.2e18; Hz of ~0 or NaN.

### Pitfall 2: Per-topic Hz is whole-bag-relative, not per-topic-relative
**What goes wrong:** `rosbags` exposes no per-topic time bounds (verified — `Connection` has no start/end field). If you assume per-topic spans exist, you'll either invent them via a full iteration (slow) or compute wrong values. A topic that published only briefly reports an artificially low Hz.
**Why it happens:** Metadata granularity stops at whole-bag time bounds + per-topic counts.
**How to avoid:** Use `hz = topic_count / whole_bag_duration_seconds` and document it as approximate (the design spec literally says "approximate Hz (count / duration)"). Do NOT iterate to get exact per-topic spans in v1.
**Warning signs:** A planner task that calls `reader.read()` "to compute Hz" — that's the wrong approach.

### Pitfall 3: Size computed as a single `stat()` on a ROS 2 bag
**What goes wrong:** `Path("ros2_sqlite").stat().st_size` on a directory returns the directory inode size (~4 KB), not the bag's data size. VERIFIED: the real content is in `ros2_sqlite.db3` (~30 KB) inside the directory.
**Why it happens:** ROS 2 bags are directories; ROS 1 bags are files.
**How to avoid:** `if path.is_dir(): sum rglob("*") file sizes; else stat().st_size` (Pattern 3).
**Warning signs:** ROS 2 bag size reported as a few KB regardless of message volume.

### Pitfall 4: Multi-message-type topic → `TopicInfo.msgtype is None` → `KeyError`
**What goes wrong:** When one topic carries two different message types (multiple connections with differing `msgtype`), `reader.topics[name].msgtype` is `None` (verified: `rosbags` `summarize()` returns `None` unless all connections share one msgtype). Passing `None` to `build_table_schema` raises `KeyError: None` (VERIFIED). `info` would print `msgtype=None`.
**Why it happens:** A topic *can* have heterogeneous types across a recording session; `rosbags` collapses to `None` rather than guessing.
**How to avoid:** `info` — display `None` as `"<mixed>"` or list the distinct `Connection.msgtype` values (iterate `info.connections` or `reader.connections` filtered by topic). `tables` — skip the topic (with a note) OR build one schema per distinct `Connection.msgtype`. Recommend: `info` shows `<mixed>` with the count still correct; `tables` skips with a one-line note. The fixtures never hit this (each topic has one msgtype), so it needs a synthetic test if the planner wants coverage.
**Warning signs:** `KeyError: None` from `build_table_schema`; `msgtype=None` in info output.

### Pitfall 5: Importing the inspect module at `rosbagger_core/__init__` top level breaks the offline invariant
**What goes wrong:** `rosbagger_core.inspect` transitively imports `reader` (→ `rosbags`) and `schema` (→ `pyarrow`). If `__init__.py` imports it eagerly, `import rosbagger_core` pulls the heavy stack and the offline-guard test (`tests/test_offline_guard.py`) plus the "light top-level" rule break.
**Why it happens:** Convenience re-export instinct.
**How to avoid:** Do NOT add `inspect` to `__init__.py`. Import via `from rosbagger_core.inspect import collect_bag_info` at call sites (the same pattern `reader`/`schema` subpackages already follow — see their `__init__` docstrings). In `bagq/cli.py`, import inside the command body, not at module top.
**Warning signs:** `test_offline_guard.py` failing; `bagq --help` getting slow.

### Pitfall 6: `inspect.py` module name vs stdlib `inspect`
**What goes wrong:** A submodule named `rosbagger_core/inspect.py` is imported as `rosbagger_core.inspect` — this does NOT shadow the top-level stdlib `inspect` (Python resolves `import inspect` to the stdlib, and `from rosbagger_core import inspect` to the submodule). So it is technically safe. BUT inside `inspect.py` itself, a bare `import inspect` would resolve to the stdlib (absolute imports under `from __future__`), which is fine but can confuse readers.
**Why it happens:** Design spec calls the capability "Inspect," so `inspect.py` reads naturally.
**How to avoid:** `inspect.py` is acceptable (no real shadowing). If the planner prefers zero ambiguity, name it `bag_info.py` or `overview.py`. Recommend `inspect.py` for spec alignment; flag the choice for the planner.
**Warning signs:** None at runtime; purely a readability/preference call.

## Code Examples

### Reading whole-bag metadata (O(1), no iteration) — INSP-01 / INSP-02
```python
# Source: VERIFIED against fixtures this session; rosbags 0.11.2 AnyReader properties
with RosbagsReader(bag_path) as reader:
    count = reader.message_count          # 9 (whole bag, summed across bags)
    dur_ns = reader.duration              # 200000001 (end_time - start_time)
    for topic, info in sorted(reader.topics.items()):
        # TopicInfo(msgtype, msgdef, msgcount, connections)
        print(topic, info.msgtype, info.msgcount)   # /cmd_vel Twist 3 ; /imu Imu 3 ; /image Image 3
```

### Building the `tables` output — INSP-03
```python
# Source: VERIFIED end-to-end against fixtures this session
from rosbagger_core.schema import build_table_schema, TableNameResolver
with RosbagsReader(bag_path) as reader:
    typestore = reader.typestore                      # NEW public property
    resolver = TableNameResolver()
    for topic, info in sorted(reader.topics.items()):
        if info.msgtype is None:                      # Pitfall 4 guard
            continue
        table = resolver.resolve(topic)               # /image -> "image"
        schema = build_table_schema(info.msgtype, typestore, topic=topic)
        for col in schema.columns:
            # col.name="data", str(col.arrow_type)="list<item: uint8>", col.is_heavy_blob=True
            tag = " (blob, lazy)" if col.is_heavy_blob else ""
            print(f"  {col.name}: {col.arrow_type}{tag}")
```

### Rendering with rich (CLI presentation only)
```python
# Source: rich 15.0.0 (installed); rich.table.Table is the standard terminal table
from rich.console import Console
from rich.table import Table

def _render_info(bag_info, json_out: bool) -> None:
    if json_out:
        import json, dataclasses
        print(json.dumps(dataclasses.asdict(bag_info), indent=2))
        return
    t = Table(title="Bag overview")
    t.add_column("topic"); t.add_column("msgtype"); t.add_column("count", justify="right"); t.add_column("Hz", justify="right")
    for ti in bag_info.topics:
        hz = f"{ti.hz:.1f}" if ti.hz is not None else "—"
        t.add_row(ti.topic, ti.msgtype or "<mixed>", str(ti.count), hz)
    Console().print(t)
    # then a small summary line: duration, message_count, size (human-readable bytes)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-team throwaway `rosbag info` parsers / one-off Python scripts | `AnyReader` metadata properties (no ROS, no iteration) | `rosbags` ≥ 0.9 | `info`/`tables` are trivial wrappers over library metadata; no script rewriting |
| `rostopic`/`ros2 bag info` (require a ROS install) | `rosbags`-only, offline | This project's premise | Works in CI and on machines with no ROS (CLAUDE.md invariant) |

**Deprecated/outdated:** none relevant — `rosbags` 0.11.2 is current and pinned (`>=0.11,<0.12`). No deprecated APIs are used; `message_count`/`duration`/`topics`/`connections`/`typestore` are stable public surface.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Per-topic Hz should use whole-bag duration (count / whole-bag span), matching the design spec's literal "count / duration" formula, rather than computing exact per-topic spans | Pattern 2 / Pitfall 2 | LOW — spec is explicit ("approximate Hz"); if exact per-topic spans are wanted later, it's an O(n) iteration add. Confirm acceptable approximation. |
| A2 | `tables` should display ALL columns (including heavy blobs, marked) rather than hiding blobs by default | Pattern 4 | LOW — "prints each topic's table name and column schema" implies completeness; the lazy blob is an annotation, not an omission. Confirm presentation preference. |
| A3 | Multi-msgtype topic handling: `info` shows `<mixed>`, `tables` skips with a note | Pitfall 4 | LOW — fixtures never trigger this; it's defensive. Planner may choose per-connection fallback instead. Behavior is a design choice, not a correctness requirement. |
| A4 | Module name `inspect.py` (vs `bag_info.py`/`overview.py`) | Standard Stack / Pitfall 6 | NONE for correctness — purely naming; flagged for planner preference. |
| A5 | Reader gains public `duration`/`start_time`/`end_time`/`message_count`/`typestore`/`paths` properties (concrete-only on `RosbagsReader`, not necessarily added to the `BagReader` ABC) | Pattern 5 | LOW — the alternative (reach into `reader._reader`) works but couples to internals. The ABC-vs-concrete choice affects only the future `rosbag2_py` backend. |
| A6 | `--json` machine-readable output is in-scope as an optional flag (Claude's discretion per the brief) | Standard Stack / Pattern 6 | LOW — explicitly discretionary; can be deferred to a later phase if the planner prefers a minimal v1. |

> No CONTEXT.md exists for this phase, so there are no locked decisions to honor — the above assumptions are open for the planner/discuss-phase to confirm. All are LOW/NONE risk because they are presentation/naming choices, not correctness requirements; the core data path (metadata → dataclass → render) is fully VERIFIED.

## Open Questions

1. **Should `info`/`tables` accept multiple bag paths (READ-05 multi-bag) in v1, or a single bag?**
   - What we know: `RosbagsReader` already accepts an iterable of same-format paths; `AnyReader` aggregates counts/duration; size sums per-path (Pattern 3). The design spec writes `bagq info BAG...` / `bagq tables BAG...` (plural).
   - What's unclear: whether v1 should expose the plural now or keep it single and add multi-bag with the `query` command in Phase 7.
   - Recommendation: accept `list[Path]` (the spec uses `BAG...`), since the reader and metadata already aggregate for free; it's no extra work and matches the spec. Mixed formats (ROS1 + ROS2) raise `AnyReaderError` — let it propagate (Phase 7 owns teaching errors).

2. **Human-readable size formatting (bytes → KB/MB/GB) — in the API or the CLI?**
   - What we know: `BagInfo.size_bytes` is the neutral datum; formatting is presentation.
   - Recommendation: keep raw `size_bytes: int` in the dataclass (so `--json` and the GUI get the number); format to human-readable in the CLI renderer only. Don't put `"1.2 MB"` strings in the API.

3. **`bagq info` summary fields beyond the per-topic table — exact layout?**
   - What we know: INSP-02 needs duration + size at the bag level; the per-topic table covers msgtype/count/Hz.
   - Recommendation: render the per-topic `rich.Table`, then a short footer line (`duration: 12.4s · 9 messages · 30.0 KB`). Exact wording is the planner's/CLI's call. Render `None` (empty bag) fields as `—`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ | 3.10 (.venv) | — |
| `rosbags` | reader metadata | ✓ | 0.11.2 | — |
| `rich` | CLI table rendering | ✓ | 15.0.0 | — |
| `typer` | CLI subcommands | ✓ | 0.25.1 | — |
| `pyarrow` | (transitive via schema, for `arrow_type` objects) | ✓ | ≥18 (declared) | — |
| `tools/make_fixtures.py` | test fixtures (ROS1/ROS2/MCAP bags, no ROS) | ✓ | repo dev tool | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — every dependency is installed and verified this session.

> Note: this dev host sources ROS 2 Humble onto `PYTHONPATH`; per 02-RESEARCH.md and `tests/test_reader.py`, run tests locally with `PYTHONPATH="" uv run pytest ...` to neutralize the host ROS leak. CI is ROS-free and needs no prefix. The new inspect tests should follow the same convention.

## Security Domain

> `security_enforcement` is not set in `.planning/config.json` (treated as enabled). This phase is read-only bag inspection with no auth, no network, no session, and no SQL execution (Phase 5 owns SQL/DuckDB). The relevant surface is input validation of untrusted bag content that becomes displayed/identifier strings.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (no auth surface) |
| V3 Session Management | no | — (no sessions) |
| V4 Access Control | no | — (local CLI, user already has file access) |
| V5 Input Validation | yes | Topic strings (untrusted bag content) → table names via Phase 3 `TableNameResolver`/`sanitize_table_name` (restricts to `[0-9A-Za-z_]`); `info`/`tables` only *display* topic/type strings — no SQL/eval/shell interpolation in this phase |
| V6 Cryptography | no | — (no crypto) |

### Known Threat Patterns for {offline CLI over untrusted bag files}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Hostile topic name (e.g. `/foo; DROP TABLE`) shown in output | Tampering / Injection | `tables` table names go through `sanitize_table_name` (Phase 3, `[0-9A-Za-z_]` allow-list); raw topic strings are only printed to a terminal by `rich`, never executed. No SQL is built in Phase 4. |
| Malicious/oversized bag causing resource exhaustion on inspect | Denial of Service | `info`/`tables` read only O(1) metadata and never iterate/deserialize message bodies — a multi-GB bag is inspected in constant time. (This is a security *benefit* of the metadata-only design.) |
| Heavy-blob columns leaking large binary into terminal | Information disclosure / DoS | `tables` lists the blob column *name/type* only (`data: list<item: uint8>`), never its bytes — it builds schema, not rows. |
| Path traversal via bag path argument | Tampering | The path is a user-supplied local file the invoking user already has OS permission to read; no privilege boundary is crossed. `Path` operations are read-only (`stat`, `rglob`). |

**Key point:** the metadata-only design eliminates the largest risk class by construction — Phase 4 never deserializes a message body, so a hostile or huge bag cannot exhaust memory or surface attacker-controlled binary during inspection.

## Sources

### Primary (HIGH confidence)
- **Installed `rosbags` 0.11.2 runtime, executed against project fixtures this session** — VERIFIED: `AnyReader.message_count`/`start_time`/`end_time`/`duration` are O(1) properties (computed as `min`/`max`/`sum` over sub-readers, no message iteration); `topics` → `dict[str, TopicInfo(msgtype, msgdef, msgcount, connections)]`; `connections` → `Connection(id, topic, msgtype, msgdef, digest, msgcount, ext, owner)` (no per-connection time bounds); `typestore` is a public attribute (`Typestore`); empty-bag `start_time=sys.maxsize`/`end_time=0`/`duration` large-negative; multi-msgtype topic → `TopicInfo.msgtype=None`; `build_table_schema(None,...)` → `KeyError`; file-vs-directory size (ros1.bag=file, ros2 sqlite/mcap=directory with metadata.yaml + data file); end-to-end `tables` pipeline (`reader.typestore` → `build_table_schema` → `TableSchema.columns` with `arrow_type`/`is_heavy_blob`).
- **`.venv/lib/python3.10/site-packages/rosbags/highlevel/anyreader.py`** (installed source) — `duration`/`start_time`/`end_time`/`message_count`/`topics` property implementations (lines 173–219); `self.typestore = get_typestore(...)` (line 86) registered in `open()` (line 147); `topics` `summarize()` returns `msgtype=None` when connections differ.
- **Project source (read this session):** `reader/base.py` (`BagReader` ABC, `Message`), `reader/rosbags_reader.py` (`RosbagsReader`, `_stamp_ns`, current `topics`/`connections` only), `schema/__init__.py`, `schema/model.py` (`ColumnDef`/`TableSchema`, `column_names(include=...)`), `schema/names.py` (`sanitize_table_name`/`TableNameResolver`), `schema/flatten.py` (`build_table_schema(msgtype, typestore, *, topic)` signature + STANDARD_COLUMNS), `bagq/cli.py` (existing `app`), both `pyproject.toml`, `__init__.py` offline-invariant docstrings, `tests/conftest.py` + `tests/test_reader.py` (fixture/test conventions, `PYTHONPATH=""` run requirement), `tools/make_fixtures.py` (fixture topics/types).
- **`.planning/REQUIREMENTS.md`** — INSP-01/02/03 definitions; **`docs/superpowers/specs/2026-05-21-rosbagger-design.md`** §4.1/§4.2 (Inspect overview fields, `bagq info`/`tables`, "pretty table to stdout by default", decision-1 API-first).
- **`.planning/phases/02-bag-reader-layer/02-RESEARCH.md`** — corroborates `AnyReader` metadata API surface, `Connection`/`TopicInfo` NamedTuple fields, and Pitfall 3 (empty-bag time bounds) which this phase consumes directly.

### Secondary (MEDIUM confidence)
- **Ternaris rosbags official docs — Highlevel APIs** (https://ternaris.gitlab.io/rosbags/topics/highlevel.html) — CITED in 02-RESEARCH.md: `AnyReader` unified ROS1/ROS2 access, `messages()` tuple shape, `deserialize`. (Corroborates the primary-source runtime findings; not re-fetched this session as the runtime was authoritative.)

### Tertiary (LOW confidence)
- none — all load-bearing claims were verified against the installed runtime and project source this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries installed and version-verified; no new deps.
- Architecture (API-first split, metadata-only path): HIGH — design decision 1 is explicit; the metadata API is verified to supply every required datum without iteration.
- Pitfalls: HIGH — empty-bag, multi-msgtype, and file-vs-directory size were all reproduced empirically this session.

**Research date:** 2026-05-22
**Valid until:** 2026-06-21 (30 days — stable; `rosbags` pinned `>=0.11,<0.12`, `rich`/`typer` stable. Re-verify only if the `rosbags` pin moves.)
