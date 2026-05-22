# Phase 2: Bag Reader Layer - Research

**Researched:** 2026-05-22
**Domain:** Universal ROS bag reading (ROS1 `.bag` / ROS2 sqlite3 / ROS2 MCAP) via the `rosbags` library, no ROS install
**Confidence:** HIGH

## Summary

This phase wraps `rosbags` 0.11.2's `rosbags.highlevel.AnyReader` behind a project-owned `BagReader` interface that yields uniform per-message records `(topic, t, stamp, msgtype, fields)` across all three bag formats. The heavy lifting — format detection, storage-plugin selection, message-definition registration, deserialization, and multi-bag merge — is **already done by `AnyReader`**; the phase's real work is (1) defining a small, swappable interface (so a future `rosbag2_py` backend can slot in), (2) adapting `AnyReader`'s `(connection, timestamp_ns, rawdata)` tuples into the project's record shape, and (3) extracting the four derived fields correctly, especially `stamp` (present only when the message has a `header`).

The single most valuable empirical finding: **`rosbags` normalizes the message `header.stamp` to `builtin_interfaces/msg/Time` with `.sec`/`.nanosec` for BOTH ROS1 and ROS2.** ROS1's native `secs`/`nsecs` naming never surfaces. This means `stamp` extraction is one uniform code path — no ROS1-vs-ROS2 branching at the reader layer. The only ROS1/ROS2 Header difference (`seq`, present in ROS1, absent in ROS2) is irrelevant because the reader extracts only `stamp`, never `seq`.

All findings below are **verified by running the actual installed `rosbags` 0.11.2 against this project's own fixture bags** (`tools/make_fixtures.py`), reading the installed `AnyReader` source, AND cross-checked against the official Ternaris documentation. Confidence is HIGH because the primary source is the runtime itself.

**Primary recommendation:** Define `BagReader` as an `abc.ABC` with a `read()` generator + `topics`/`connections` metadata accessors + context-manager lifecycle; implement `RosbagsReader(BagReader)` as a thin adapter over `AnyReader`. Yield a frozen `Message` dataclass `(topic, t, t_ns, stamp, msgtype, msg)`. Deserialize lazily inside the generator (do not pre-deserialize all messages). Extract `stamp` via duck-typed `header.stamp` access. Accept a `Sequence[Path]` for multi-bag; pass straight to `AnyReader`, which merge-sorts by timestamp.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Open ROS1/ROS2/MCAP, detect format | `rosbags` (`AnyReader`) | `BagReader` interface | `AnyReader` auto-detects via path suffix + `metadata.yaml`; the interface just delegates |
| Register message definitions / typestore | `rosbags` (`AnyReader.open`) | — | `AnyReader` reads embedded defs from the bag and registers them automatically |
| Deserialize raw bytes → message object | `rosbags` (`reader.deserialize`) | `RosbagsReader` | `AnyReader.deserialize` dispatches ros1/cdr by format; reader calls it per-message |
| Uniform record shape `(topic, t, stamp, msgtype, fields)` | `RosbagsReader` (adapter) | `Message` dataclass | This is the phase's actual contribution: adapt `AnyReader` tuples → project record |
| `stamp` extraction from `header.stamp` | `RosbagsReader` | — | Project logic: duck-type `header.stamp`, normalize ns; `AnyReader` does not do this |
| Multi-bag = one logical dataset, time-ordered | `rosbags` (`AnyReader.messages`) | `BagReader` interface | `AnyReader` heapq-merges per-reader streams by timestamp; interface accepts a list of paths |
| Topic / type / count metadata for Inspect | `rosbags` (`AnyReader.topics`/`.connections`) | `BagReader` interface | `AnyReader` summarizes across readers; surface it through the interface for Phase 4 |
| Swappable backend seam (future `rosbag2_py`) | `BagReader` ABC | — | The ABC is the seam; `rosbags` is impl #1, `rosbag2_py` a deferred impl #2 |

## User Constraints

No `CONTEXT.md` exists for this phase (no `/gsd:discuss-phase` was run). Constraints below are drawn from `CLAUDE.md`, `PROJECT.md`, the design spec, and Phase 1's locked decisions — treat them with the same authority as locked decisions.

### Locked Decisions (from PROJECT.md / design spec / Phase 1)
- **Universal reader via `rosbags`, NOT `rosbag2_py`.** `rosbag2_py` is explicitly deferred (REQUIREMENTS.md "Out of Scope": *"`rosbag2_py` reader backend — Add only if a live-workspace custom-msg need appears"*).
- **`BagReader` yields records `(topic, t, stamp, msgtype, msg)`** where `msg` is the deserialized message object (design spec §4.1).
- **Connection/topic/type metadata + message counts must be exposed for Inspect without full deserialization** (design spec §4.1) — Phase 4 consumes this.
- **The interface must be a swappable seam** so a future `rosbag2_py` backend can slot in behind it (design spec §4.1, §3.3 principle 6).
- **Offline / NO-ROS invariant (load-bearing):** offline packages must NEVER import `rclpy`, `rosbag2_py`, `rosidl_runtime_py`, or `ament_index_python`, directly or transitively (design spec §3.2; enforced by `tests/test_offline_guard.py`). `rosbags` is the *approved* offline backend and is explicitly allowed.
- **Python ≥ 3.10** (`pyproject.toml requires-python`).

### Claude's Discretion
- `ABC` vs `typing.Protocol` for the interface (this research recommends `ABC` — see Pattern 1).
- The exact record container (dataclass vs `NamedTuple`) and its field set/order.
- Internal module layout under `rosbagger_core/reader/`.
- Error-wrapping strategy (whether to re-wrap `AnyReaderError` in a project exception).

### Deferred Ideas (OUT OF SCOPE for this phase)
- `rosbag2_py` reader backend (REQUIREMENTS.md Out of Scope).
- Message→table flattening, dotted columns, `LIST`/`STRUCT` (that is **Phase 3**, QURY-01..04/07).
- The `t`/`stamp` **DuckDB column types** (`TIMESTAMP_NS`, `BIGINT`) — that is Phase 3's schema concern. This phase only produces the raw Python values (int ns + optional int ns for stamp).
- Inspect duration/Hz/size reporting (Phase 4) — though the reader exposes the metadata it will use.
- Custom-msg registration *UX* / teaching error (Phase 7, CLI-04) — though this research documents how `rosbags` resolves custom types so the planner understands the boundary.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| READ-01 | Open ROS2 sqlite3 bags via `BagReader`, no ROS install | VERIFIED: `AnyReader([Path('ros2_sqlite')])` opens the fixture, `is2=True`, yields 9 messages. Storage auto-detected from `metadata.yaml`. (Code Examples §1) |
| READ-02 | Open ROS2 MCAP bags, same interface | VERIFIED: `AnyReader([Path('ros2_mcap')])` opens the MCAP fixture identically (`is2=True`, 9 msgs). No code difference vs sqlite — `AnyReader` reads `storage_identifier` from `metadata.yaml`. |
| READ-03 | Open ROS1 `.bag` files, same interface | VERIFIED: `AnyReader([Path('ros1.bag')])` opens the ROS1 fixture, `is2=False`, 9 msgs. Same `messages()`/`deserialize()` surface. |
| READ-04 | Iterate as `(topic, t, stamp, msgtype, deserialized fields)` | VERIFIED: `connection.topic`, `timestamp_ns` (the `t`), `connection.msgtype`, and `reader.deserialize(raw, msgtype)` give the deserialized object. `stamp` derived from `msg.header.stamp` when present (NULL for headerless `/cmd_vel`). (Pattern 2, Code Examples §2) |
| READ-05 | Multiple bag paths as one logical dataset | VERIFIED: multi-ROS1 (two `.bag` files) → 18 msgs, **timestamps merge-sorted ascending across bags**, topics summarized. Multi-ROS2 (two sqlite dirs) ALSO works in 0.11.2 → 18 msgs. (Pitfall 1 documents the ROS1/ROS2 mixing constraint.) |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `rosbags` | 0.11.2 (pinned `>=0.11,<0.12`) | Universal ROS1/ROS2/MCAP reader+typesys; `AnyReader` is the unified read path | Already a locked dep (Phase 1), pure-Python, **zero ROS dependency**, the project's chosen universal-reader decision. `[VERIFIED: PyPI]` released 2026-05-11, supports Py 3.10-3.14, no ROS required |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `abc` | — | Define the `BagReader` ABC seam | Always — the interface base class |
| stdlib `dataclasses` | — | The `Message` record container (`@dataclass(frozen=True, slots=True)`) | The yielded record type |
| stdlib `pathlib` | — | `Path` inputs to `AnyReader` | All path handling (`AnyReader` calls `.exists()`/`.suffix` on inputs — pass `Path`, not `str`) |
| stdlib `typing` | — | `Iterator`/`Iterable`/`Sequence` annotations; optionally `Protocol` (alternative to ABC) | Type hints; matches Phase 1's typed style |

**No new third-party dependency is needed for this phase.** `rosbags` is already installed and locked. `numpy` arrives transitively via `rosbags` (array fields like `orientation_covariance` deserialize to `numpy.ndarray`) but the reader does not need to import it directly.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `rosbags.highlevel.AnyReader` | `rosbags.rosbag1.Reader` + `rosbags.rosbag2.Reader` directly | More control, but you re-implement format dispatch, def-registration, and multi-bag merge that `AnyReader` already does. No benefit for v1. Use `AnyReader`. |
| `rosbags` | `rosbag2_py` (ROS reader) | Requires a ROS install — violates the load-bearing offline invariant. Explicitly deferred. |
| `abc.ABC` for the seam | `typing.Protocol` | `Protocol` is structural (no inheritance needed) but gives weaker construction-time guarantees and no shared `__enter__`/`__exit__`. `ABC` is recommended (Pattern 1). |

**Installation:** None required — `rosbags>=0.11,<0.12` is already in `packages/rosbagger-core/pyproject.toml` `dependencies` and in `uv.lock`. Nothing to add.

**Version verification (performed this session):**
```
importlib.metadata.version('rosbags') -> 0.11.2          # installed in .venv (VERIFIED)
PyPI latest                          -> 0.11.2 (2026-05-11)  # VERIFIED via pypi.org
pip show rosbags Requires            -> typing_extensions, lz4, numpy, apsw, zstandard, ruamel.yaml
                                        # NO rclpy / rosbag2_py — offline invariant holds transitively (VERIFIED)
```

## Package Legitimacy Audit

The phase installs **no new packages** — `rosbags` is the only external runtime dependency and it was locked in Phase 1. Audit run for completeness:

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `rosbags` | PyPI | ~4 yrs (2020→2026) | high (established) | gitlab.com/ternaris/rosbags | **[OK]** | Approved (already locked) |

**Transitive deps of `rosbags`** (informational — pulled via the locked `rosbags` pin, not separately declared): `typing_extensions`, `lz4`, `numpy`, `apsw`, `zstandard`, `ruamel.yaml`. None are ROS packages.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> slopcheck 0.6.1 was available and rated `rosbags` `[OK]` on the PyPI ecosystem. No `[ASSUMED]` fallback needed for this package.

## Architecture Patterns

### System Architecture Diagram

```
                         caller (Phase 3 schema mapper, Phase 4 Inspect, tests)
                                            │
                       opens with a list of bag paths (Sequence[Path])
                                            │
                                            ▼
                ┌──────────────────────────────────────────────────┐
                │  BagReader  (abc.ABC — the swappable seam)         │
                │   • __enter__/__exit__  (context manager)          │
                │   • read() -> Iterator[Message]   (lazy)           │
                │   • topics / connections  (metadata, no deser)     │
                └───────────────▲───────────────────▲───────────────┘
                                │ (impl #1, v1)      │ (impl #2, DEFERRED)
                ┌───────────────┴──────────┐   ┌─────┴────────────────────┐
                │ RosbagsReader            │   │ Rosbag2PyReader (future) │
                │  thin adapter over       │   │  for live-workspace      │
                │  rosbags.AnyReader       │   │  custom msgs rosbags     │
                └───────────────┬──────────┘   │  can't resolve           │
                                │              └──────────────────────────┘
                                ▼
            ┌──────────────────────────────────────────────────────────┐
            │ rosbags.highlevel.AnyReader                                │
            │   open(): detect format (suffix + metadata.yaml),          │
            │           register embedded msg defs into internal typestore│
            │   messages(connections, start, stop)                       │
            │      -> heapq.merge of per-reader streams, sorted by t_ns   │
            │      -> yields (connection, timestamp_ns, rawdata)          │
            │   deserialize(rawdata, msgtype) -> message object           │
            └───────┬──────────────────┬──────────────────┬─────────────┘
                    ▼                  ▼                  ▼
              Reader1 (.bag)    Reader2 (sqlite3)   Reader2 (mcap)
                    │                  │                  │
                    └──────────────────┴──────────────────┘
                         each yields (connection, t_ns, rawdata)

  Per yielded (connection, t_ns, rawdata), RosbagsReader builds a Message:
     topic   = connection.topic
     t_ns    = t_ns                       (int, log/receive time in ns)
     t       = t_ns                       (same int; Phase 3 maps to TIMESTAMP_NS)
     msgtype = connection.msgtype
     msg     = reader.deserialize(rawdata, connection.msgtype)
     stamp   = msg.header.stamp.sec*1e9 + .nanosec   if msg has a header, else None
```

File-to-implementation mapping is in the Component Responsibilities table below, not in the diagram.

### Recommended Project Structure
```
packages/rosbagger-core/src/rosbagger_core/reader/
├── __init__.py     # re-export BagReader, Message, RosbagsReader (light public API
│                   #   for this subpackage; does NOT make rosbagger_core/__init__ heavy)
├── base.py         # BagReader ABC + Message dataclass (no rosbags import — keeps the
│                   #   abstract seam importable without the heavy backend)
└── rosbags_reader.py  # RosbagsReader(BagReader): imports rosbags at MODULE level (fine —
                       #   only loaded when this module is imported, not on `import rosbagger_core`)
```

| Component | File | Responsibility |
|-----------|------|----------------|
| `Message` | `reader/base.py` | Frozen dataclass `(topic, t, t_ns, stamp, msgtype, msg)` — the yielded record |
| `BagReader` | `reader/base.py` | ABC: `read()`, `topics`, `connections`, `__enter__`/`__exit__`, `open`/`close` |
| `RosbagsReader` | `reader/rosbags_reader.py` | Concrete impl wrapping `AnyReader`; owns stamp extraction + record building |
| public exports | `reader/__init__.py` | `from .base import BagReader, Message` + `from .rosbags_reader import RosbagsReader` |

> **Offline-guard note:** `import rosbags` at the top of `rosbags_reader.py` is SAFE. The guard (`tests/test_offline_guard.py`) only blocks `rclpy`/`rosbag2_py`/`rosidl_runtime_py`/`ament_index_python`, and only checks the import graph of `import rosbagger_core` / `import bagq`. As long as `rosbagger_core/__init__.py` does not import the reader subpackage at top level, `import rosbagger_core` stays light and ROS-free. `rosbags` itself pulls in NO ROS modules (verified transitive deps). If `reader/__init__.py` imports `rosbags_reader`, then `import rosbagger_core.reader` will load `rosbags` — that is fine and expected; just keep it out of the top-level `rosbagger_core/__init__.py`.

### Pattern 1: ABC seam with context-manager lifecycle (recommended over Protocol)
**What:** `BagReader(abc.ABC)` declares the abstract contract; concrete readers inherit. The base provides shared `__enter__`/`__exit__` delegating to abstract `open()`/`close()`.
**When to use:** When you have exactly one impl now and want a clean, enforced seam for a second impl later (the design spec's `rosbag2_py` future backend). ABC gives construction-time enforcement of the contract and a place to put shared lifecycle code; `Protocol` does not.
**Example:**
```python
# Source: project design (mirrors rosbags.highlevel.AnyReader's own open/close/__enter__/__exit__)
from __future__ import annotations
import abc
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Message  # the record dataclass


class BagReader(abc.ABC):
    """Swappable bag-reader seam. Impl #1 = RosbagsReader; #2 = rosbag2_py (deferred)."""

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def read(self) -> Iterator[Message]:
        """Lazily yield Message records, time-ordered across all opened bags."""
        ...

    # Shared lifecycle — concrete readers inherit this for free.
    def __enter__(self) -> "BagReader":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
```

### Pattern 2: Record-building adapter with uniform stamp extraction
**What:** The concrete reader iterates `AnyReader.messages()`, deserializes each message, derives the four fields, and yields a `Message`. **Deserialization is lazy** — done one message at a time inside the generator, never eagerly materialized.
**When to use:** This is the core of plan 02-02.
**Example:** see Code Examples §2 (full `RosbagsReader.read()`).

### Pattern 3: Pass-through multi-bag (let `AnyReader` merge)
**What:** Do NOT implement your own multi-bag merge. Accept `Sequence[Path]`, hand it straight to `AnyReader(paths)`. `AnyReader.messages()` heapq-merges the per-bag streams sorted by timestamp (`key=lambda x: x[1]`), so the combined stream is globally time-ordered. Topic metadata is auto-summarized across bags (msgcounts add up; one logical `topics` dict).
**When to use:** plan 02-03 (READ-05).

### Anti-Patterns to Avoid
- **Re-implementing format detection.** `AnyReader` sets `is2 = any(suffix != '.bag')` and reads `storage_identifier` from `metadata.yaml`. Don't sniff files yourself.
- **Re-implementing multi-bag merge / sorting.** `AnyReader.messages()` already merge-sorts. Sorting again wastes time and risks reordering ties.
- **Eagerly listing all messages** (`list(reader.messages())`). The data is large in real bags; `read()` must be a generator. (Tests may `list()` the tiny fixtures — that's fine in tests only.)
- **Importing `rosbags` in `rosbagger_core/__init__.py`.** Keeps the top-level package light and the offline guard fast (Phase 1 decision, design spec).
- **Branching `stamp` extraction on ROS1 vs ROS2 Header.** Unnecessary — `rosbags` normalizes both to `.sec`/`.nanosec` (see Pitfall 2). One code path.
- **Assuming every message has a header.** `/cmd_vel` (Twist) has none → `stamp` must be `None`. Use duck-typed `getattr`, not a type check.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Format detection (ROS1 vs ROS2, sqlite vs MCAP) | A file sniffer / magic-byte reader | `AnyReader` (suffix + `metadata.yaml`) | `AnyReader` already does it correctly for all three; MCAP vs sqlite is read from `metadata.yaml`'s `storage_identifier`, not the caller |
| CDR / ROS1 wire deserialization | A binary parser | `reader.deserialize(raw, msgtype)` | CDR alignment + ROS1 layout are fiddly; `rosbags` generates per-type (de)serializers |
| Message-definition / typestore registration | Hand-loading `.msg`/`.idl` | `AnyReader.open()` (auto) | ROS2 v9 bags **embed** defs; `AnyReader` parses + registers them — even custom types (verified). `default_typestore` only for legacy bags lacking defs |
| Multi-bag merge + global time ordering | A k-way merge | `AnyReader.messages()` (`heapq.merge`) | Already implemented and tested upstream; merges per-reader generators by `t_ns` |
| Topic/type/count summary across bags | Manual aggregation | `AnyReader.topics` / `.connections` | `topics` groups by name across readers and sums msgcounts; gives `TopicInfo(msgtype, msgdef, msgcount, connections)` |
| Time-range / topic filtering of the stream | Manual `if` filters in the loop | `messages(connections=..., start=..., stop=...)` | Built-in args; `connections=[]` disables filtering (verified). Phase 5 will use `connections=` to load only referenced topics |

**Key insight:** This phase is ~90% adapter glue. `rosbags`/`AnyReader` is the engine; the project's job is a thin, well-typed interface and correct `stamp` extraction. Resist re-implementing anything `AnyReader` already provides — every such attempt is strictly worse and risks the offline invariant.

## Runtime State Inventory

> Not applicable — this is a greenfield feature phase (new `reader/` code over an empty seam package), not a rename/refactor/migration. No stored data, live-service config, OS-registered state, secrets, or build artifacts are touched. **None — verified: the only existing file in `reader/` is an empty docstring-only `__init__.py` (read this session); no prior reader implementation exists to migrate.**

## Common Pitfalls

### Pitfall 1: Mixing ROS1 and ROS2 paths in one `AnyReader` raises
**What goes wrong:** `AnyReader([ros1_bag, ros2_dir])` raises `AnyReaderError: Unrecognized storage format '.bag'` (verified). `AnyReader` decides `is2` from `any(suffix != '.bag')`; a mixed list sends a `.bag` into `Reader2`, which rejects it.
**Why it happens:** The official docs state it directly: *"AnyReader gives unified access to a list of either ROS1 or ROS2 bag files, but not a mixture of both."*
**How to avoid:** Document the constraint in the interface. For v1, READ-05 ("multiple bag paths as one logical dataset") covers the realistic case — split recordings of the SAME format. If you want defensive UX, detect a mixed list (suffixes both `== '.bag'` and `!= '.bag'`) and raise a clear project error before constructing `AnyReader`. Otherwise the raw `AnyReaderError` surfaces (acceptable for v1).
**Warning signs:** `AnyReaderError` mentioning storage format; a user passing a `.bag` alongside a ROS2 directory.

### Pitfall 2: `stamp` is NOT present on every message — and ROS1/ROS2 Header naming is already normalized
**What goes wrong:** (a) Calling `msg.header.stamp` on a headerless message (`geometry_msgs/msg/Twist`) raises `AttributeError`. (b) Over-engineering by branching on ROS1 `secs`/`nsecs` vs ROS2 `sec`/`nanosec`.
**Why it happens:** (a) Many message types have no `std_msgs/Header`. The fixtures deliberately include `/cmd_vel` (Twist, no header) precisely to exercise `stamp IS NULL`. (b) A reasonable but wrong assumption from ROS1 knowledge.
**How to avoid:**
- For (a): duck-type. `hdr = getattr(msg, "header", None); st = getattr(hdr, "stamp", None) if hdr else None`; only compute ns if `st` has `sec` and `nanosec`. Yield `stamp=None` otherwise.
- For (b): **VERIFIED** — `rosbags` exposes `header.stamp` as `builtin_interfaces__msg__Time` with `.sec`/`.nanosec` for BOTH ROS1 and ROS2 bags. ROS1's native `secs`/`nsecs` never appears. The ROS1 Header additionally carries `seq` (ROS2 omits it), but the reader never reads `seq`. Use ONE formula: `stamp_ns = st.sec * 1_000_000_000 + st.nanosec`.
**Warning signs:** `AttributeError: ... has no attribute 'header'`; any code path that special-cases ROS1 stamp field names.

### Pitfall 3: `start_time`/`end_time`/`duration` are dangerous on empty bags
**What goes wrong:** On a bag with zero messages, `AnyReader.start_time` returns `sys.maxsize` (9223372036854775807) and `end_time` returns `0`, so `duration` is a large negative number (verified). Iterating yields nothing (correct), but these properties silently return garbage rather than raising.
**Why it happens:** `start_time = min(reader.start_time ...)`; an empty `Reader2`'s `start_time` defaults to maxsize. No guard upstream.
**How to avoid:** This bites **Phase 4 (Inspect duration/Hz)** more than the reader itself, but document it now. If the reader exposes any time-span helper, guard it with `message_count == 0 → return None/0`. For the reader's core `read()`, no special handling is needed (empty stream is correct). A bag with **zero connections** opens cleanly (`message_count=0`, `connections=[]`) — verified, no crash.
**Warning signs:** Negative durations; absurd `start_time` near 9.2e18; a per-topic Hz of effectively zero or NaN.

### Pitfall 4: `default_typestore` and unresolvable custom message types
**What goes wrong:** If a bag has connections whose message definitions are NOT embedded AND no `default_typestore` is given, `AnyReader.open()` raises `AnyReaderError: Bag contains no type definitions. Instantiate AnyReader with a default_typestore argument.`
**Why it happens:** Older/legacy ROS2 bags may lack embedded defs. **However:** modern `rosbags`-written ROS2 v9 bags (and ROS1 bags) **embed** their definitions. Verified: a bag written with a *custom* type `my_pkg/msg/Widget` re-opens and deserializes in a fresh `AnyReader` with no pre-registration — the embedded def is auto-registered.
**How to avoid:** For v1, do nothing special — the fixtures and realistic `rosbags`/`ros2 bag`-written bags embed defs. The interface MAY expose an optional `default_typestore` passthrough for robustness, but it is not required for any Phase-2 success criterion. The "unresolvable custom msg → registration guidance" is **Phase 7 / CLI-04**, not this phase. Document the error string so Phase 7 can catch it.
**Warning signs:** `AnyReaderError` containing "no type definitions"; very old or hand-built ROS2 bags.

### Pitfall 5: Pass `Path`, not `str`; and the local-test `PYTHONPATH` gotcha
**What goes wrong:** (a) `AnyReader.__init__` calls `x.exists()` and `x.suffix` on each path — passing a `str` raises `AttributeError`. (b) On THIS dev host, a bare `pytest`/`python` invocation auto-loads ROS plugins from the sourced `PYTHONPATH` and can crash.
**Why it happens:** (a) `AnyReader` assumes `pathlib.Path`-like inputs. (b) Phase 1 decision: the dev shell sources ROS 2 Humble onto `PYTHONPATH`; CI is ROS-free so it is moot there.
**How to avoid:** (a) Coerce inputs to `Path` at the interface boundary (`[Path(p) for p in paths]`). (b) Run reader tests locally with `PYTHONPATH="" uv run pytest` (or `PYTHONPATH="" .venv/bin/python -m pytest`). All probes this session used `PYTHONPATH=""`. Document this in test/dev notes; CI needs no prefix.
**Warning signs:** `AttributeError: 'str' object has no attribute 'exists'`; pytest crashing on collection only on the dev box, not CI.

## Code Examples

Verified patterns (run against this project's fixtures with `rosbags` 0.11.2 this session).

### §1 — Opening each format and listing topics (READ-01/02/03)
```python
# Source: VERIFIED against tools/make_fixtures.py fixtures + installed AnyReader source
from pathlib import Path
from rosbags.highlevel import AnyReader

# ROS2 sqlite dir, ROS2 MCAP dir, and ROS1 .bag all use the SAME calls.
with AnyReader([Path("ros2_sqlite")]) as reader:   # or ["ros2_mcap"] or ["ros1.bag"]
    print(reader.is2)            # True for ros2 dirs, False for .bag (auto-detected)
    print(reader.message_count)  # 9 for each fixture
    for topic, info in reader.topics.items():
        # info: TopicInfo(msgtype, msgdef, msgcount, connections)
        print(topic, info.msgtype, info.msgcount)
        # -> /cmd_vel geometry_msgs/msg/Twist 3
        # -> /image   sensor_msgs/msg/Image  3
        # -> /imu     sensor_msgs/msg/Imu    3
```

### §2 — The full record-building read loop (READ-04) — core of plan 02-02
```python
# Source: VERIFIED extraction logic; AnyReader API per installed source + official docs
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Message:
    topic: str
    t: int            # log/receive time, nanoseconds (Phase 3 maps -> TIMESTAMP_NS)
    t_ns: int         # same value, explicit ns (Phase 3 -> BIGINT column)
    stamp: int | None # header.stamp in ns, or None when the msg has no header
    msgtype: str
    msg: object       # the deserialized rosbags message object (the "fields")


def _stamp_ns(msg: object) -> int | None:
    """Uniform stamp extraction. Works for ROS1 and ROS2 (rosbags normalizes
    header.stamp to builtin_interfaces/msg/Time with .sec/.nanosec)."""
    header = getattr(msg, "header", None)
    if header is None:
        return None
    st = getattr(header, "stamp", None)
    if st is None or not (hasattr(st, "sec") and hasattr(st, "nanosec")):
        return None
    return st.sec * 1_000_000_000 + st.nanosec


# Inside RosbagsReader.read() — `self._reader` is an opened AnyReader:
def read(self):  # -> Iterator[Message]
    assert self._reader is not None and self._reader.isopen
    for connection, t_ns, rawdata in self._reader.messages():   # time-ordered, lazy
        msg = self._reader.deserialize(rawdata, connection.msgtype)
        yield Message(
            topic=connection.topic,
            t=t_ns,
            t_ns=t_ns,
            stamp=_stamp_ns(msg),
            msgtype=connection.msgtype,
            msg=msg,
        )
```
Verified output against fixtures: `/cmd_vel` → `stamp=None`; `/imu` and `/image` → `stamp = 1*1e9 + 0 = 1_000_000_000` (matches fixture header). `t_ns` for the three messages = `1_000_000_000`, `1_100_000_000`, `1_200_000_000`.

### §3 — Multi-bag as one dataset (READ-05) — core of plan 02-03
```python
# Source: VERIFIED — two ROS1 bags merge-sorted by timestamp; two ROS2 sqlite dirs also work
from pathlib import Path
from rosbags.highlevel import AnyReader

paths = [Path("rec_0.bag"), Path("rec_1.bag")]   # split recording, SAME format
with AnyReader(paths) as reader:
    assert reader.message_count == 18             # 9 + 9 (summed across bags)
    timestamps = [t for _conn, t, _raw in reader.messages()]
    assert timestamps == sorted(timestamps)       # globally time-ordered (heapq.merge)
    # topics summarized across bags: /cmd_vel msgcount=6, nconns=2, etc.
```

### §4 — Metadata-only access for Inspect (no full deserialization) — feeds Phase 4
```python
# Source: VERIFIED — connections/topics are available after open() without iterating messages
with AnyReader([Path("ros2_sqlite")]) as reader:
    for conn in reader.connections:
        # Connection NamedTuple: id, topic, msgtype, msgdef, digest, msgcount, ext, owner
        print(conn.topic, conn.msgtype, conn.msgcount)
    # Aggregate view (merges duplicate topics across multi-bag):
    span_ns = reader.duration            # GUARD: meaningless if message_count == 0 (Pitfall 3)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-format readers (`rosbag` py for ROS1, `rosbag2_py`/`sqlite3` for ROS2) requiring a ROS install | `rosbags.highlevel.AnyReader` — one pure-Python API for ROS1/ROS2/MCAP, no ROS | `rosbags` matured 2021→2026 | Enables the project's entire "no ROS install" promise; this phase depends on it |
| ROS1 `Header.stamp` as `secs`/`nsecs`; ROS2 as `sec`/`nanosec` | `rosbags` normalizes BOTH to `builtin_interfaces/msg/Time` (`sec`/`nanosec`) | rosbags typesys design | Single uniform stamp-extraction path (Pitfall 2) — no version branching |
| Manually loading `.msg`/`.idl` definitions to deserialize | ROS2 v9 + ROS1 bags **embed** defs; `AnyReader` auto-registers (incl. custom types) | rosbag2 v9 metadata + rosbags | Custom-type bags "just work"; explicit registration only for legacy bags (Pitfall 4) |

**Deprecated/outdated:**
- Treating multi-ROS2 as impossible: the constructor docstring says "single rosbag2 recording," but `rosbags` 0.11.2 **does** open multiple ROS2 directories together (verified: 18 msgs from two sqlite dirs), and the official docs say "a list of … ROS2 bag files." Treat multi-ROS2 as supported, but cover it with a fixture-backed test (it is the less-documented path) — see Open Question 1.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Multi-ROS2 (>1 ROS2 directory in one `AnyReader`) is reliable beyond the 2-bag case I tested | State of the Art / Open Q1 | LOW — verified for 2 sqlite dirs; if a 3+/MCAP combo behaved differently, READ-05 multi-ROS2 would need a workaround. Mitigated by a planned fixture test. |

> Only one assumption. Everything else in this research was VERIFIED by running `rosbags` 0.11.2 against the project's fixtures and/or reading the installed source, and CITED against official docs. No compliance/security/retention assumptions exist for this phase.

## Open Questions

1. **Does multi-ROS2 hold for MCAP and for 3+ bags / overlapping time ranges?**
   - What we know: VERIFIED that two ROS2 **sqlite** directories open together and yield a correctly merged 18-message stream. Official docs say `AnyReader` accepts "a list of … ROS2 bag files."
   - What's unclear: I did not exhaustively test two **MCAP** dirs together, a mixed sqlite+MCAP ROS2 set, or 3+ bags with overlapping timestamps.
   - Recommendation: Plan 02-03 should include a fixture-backed test that opens **two ROS2 bags** (at minimum two sqlite, ideally also two MCAP) and asserts merged count + ascending timestamps — turning A1 into a verified fact. `make_all_fixtures` already produces the needed bags; the test can generate a second copy into a separate tmp dir (as the probes did).

2. **Should the reader re-wrap `AnyReaderError` in a project-specific exception?**
   - What we know: `AnyReader` raises `AnyReaderError` (mixed formats, missing defs) and `FileNotFoundError` (missing paths).
   - What's unclear: whether v1 wants a stable `rosbagger_core` exception type for callers/CLI to catch.
   - Recommendation: Claude's discretion. A thin `BagReaderError` wrapper aids Phase 7 teaching-errors (CLI-04 catches the "no type definitions" case), but is not required for any Phase-2 success criterion. If added, preserve the original message.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `rosbags` | the entire reader | ✓ | 0.11.2 (locked `>=0.11,<0.12`) | — (it's the chosen backend) |
| Python | runtime | ✓ | 3.10 (`.python-version`) | — |
| `pytest` + fixtures | reader tests | ✓ | pytest 8.x; fixtures via `tools/make_fixtures.py` | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

> This phase reads local files only — no external services, network, daemons, or ROS runtime. `rosbags` and the fixture generator are already installed and verified working this session. No `rclpy`/`rosbag2_py` needed (and forbidden).

## Validation Architecture

> `workflow.nyquist_validation` is **`false`** in `.planning/config.json`. Per the research template, this section is **omitted**. (Standard pytest tests still apply — see Common Pitfalls §5 for the `PYTHONPATH=""` local-run requirement and the existing `tests/` layout + ≥80% coverage gate on `rosbagger_core`.)

## Security Domain

`security_enforcement` is not set in `.planning/config.json`. This is an offline, local-file-parsing library with no auth, network, sessions, secrets, or access control — most ASVS categories are N/A. The one relevant surface is **untrusted input parsing** (bag files are external binary input).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface (local library) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-user/authorization model |
| V5 Input Validation | partial | Bag files are untrusted input. Mitigation: rely on `rosbags`' battle-tested parsers; surface parse errors as exceptions rather than crashing; never `eval`/exec bag content; treat `data` byte blobs as opaque |
| V6 Cryptography | no | No crypto — never hand-roll any (none needed) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/corrupt bag (decompression bomb, bad CDR) | Denial of Service | Let `rosbags` raise; catch `AnyReaderError`/`FileNotFoundError`; do not pre-load whole bags into memory (lazy `read()` generator). Heavy blobs deferred to Phase 3/QURY-07 |
| Path traversal via supplied bag paths | Tampering | Inputs are user-chosen local paths in a CLI tool — the user already controls their FS. Coerce to `Path`; `AnyReader` checks `.exists()`. No elevation of privilege beyond the invoking user |

> No security control in this phase requires a new dependency or a hand-rolled cryptographic/auth primitive. The dominant security posture is "delegate untrusted-binary parsing to the vetted `rosbags` library and propagate errors cleanly."

## Sources

### Primary (HIGH confidence)
- **Installed `rosbags` 0.11.2 runtime, executed against project fixtures this session** — verified: format detection (`is2`), `messages()` tuple shape `(connection, t_ns, rawdata)`, time-merge ordering, `deserialize()`, `stamp` normalization to `.sec`/`.nanosec` for ROS1+ROS2, headerless-msg → no stamp, empty-bag `start_time`/`end_time` behavior, custom-type auto-registration, multi-ROS1 + multi-ROS2 merge, mixed-format error.
- **`.venv/.../rosbags/highlevel/anyreader.py`** (installed source) — `AnyReader.__init__(paths, *, default_typestore=None)`, `open`/`close`/`__enter__`/`__exit__`, `messages(connections, start, stop)` with `heapq.merge(key=lambda x: x[1])`, `deserialize`, `topics`, `connections`, `start_time`/`end_time`/`duration`/`message_count`.
- **`.venv/.../rosbags/interfaces/__init__.py`** (installed source) — `Connection(id, topic, msgtype, msgdef, digest, msgcount, ext, owner)` and `TopicInfo(msgtype, msgdef, msgcount, connections)` NamedTuples.
- **Project files** — `tests/test_fixtures.py` (AnyReader usage precedent), `tools/make_fixtures.py` (fixture contents), `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §4.1 (record shape + seam mandate), `CLAUDE.md` + `PROJECT.md` (offline invariant, stack), `tests/test_offline_guard.py` + `tests/conftest.py` (the ROS-blocker the reader must not trip), `packages/rosbagger-core/pyproject.toml` (locked dep).

### Secondary (MEDIUM confidence)
- **Ternaris rosbags official docs — Highlevel APIs** (https://ternaris.gitlab.io/rosbags/topics/highlevel.html) — CITED: AnyReader gives "unified access to a list of either ROS1 or ROS2 bag files, but not a mixture of both"; `messages()` yields `(connection, timestamp, rawdata)`; `reader.deserialize(rawdata, connection.msgtype)`; `default_typestore` for legacy ROS2 bags. (Corroborates the primary-source runtime findings.)
- **PyPI — rosbags** (https://pypi.org/project/rosbags/) — VERIFIED: latest 0.11.2 (2026-05-11), Python 3.10-3.14, no special deps, no ROS dependency.

### Tertiary (LOW confidence)
- None relied upon. (WebSearch surfaced the docs/PyPI links above, which were then read directly.)

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — single dep, already locked + installed; version + no-ROS transitive tree verified directly.
- Architecture (interface shape, record building, stamp extraction): **HIGH** — every behavior verified by executing `rosbags` 0.11.2 against the project's own fixtures and reading the installed source.
- Multi-bag (READ-05): **HIGH for ROS1 and 2-bag ROS2** (verified), **MEDIUM for ROS2 MCAP / 3+ bags** (Open Q1, A1) — turned into a concrete planned test.
- Pitfalls: **HIGH** — each pitfall reproduced empirically this session (mixed-format error, headerless stamp, empty-bag time, custom-type registration, `str` vs `Path`).

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (30 days; `rosbags` is pinned `<0.12`, so the API surface is stable for this milestone — re-verify only if the pin is bumped).
