# Phase 12: Live Record - Research

**Researched:** 2026-05-23
**Domain:** Live ROS 2 topic discovery + recording (`rclpy` + `rosbag2_py`), isolated behind a new workspace package that keeps the offline tier ROS-free
**Confidence:** HIGH (every API claim was executed against the real ROS 2 Humble on this box; the full publisher→record→re-open path was run end-to-end and SC1/SC2/SC3 verified)

## Summary

This phase adds `rosbagger-record`: discover live ROS 2 topics, record a selected subset to a bag, and prove the recorded bag re-opens via the v1 reader. It is the project's first module that requires a sourced ROS 2 environment. The defining tension — `rclpy`/`rosbag2_py` exist in the system ROS install but are absent from the project `uv` venv — is real and was re-verified (`PYTHONPATH="" uv run python -c "import rclpy"` → `ModuleNotFoundError`; system `python3` with ROS sourced imports both, plus `rosbags`, `pytest`, `numpy`, `rosidl_runtime_py`).

I ran the entire pipeline live on this box and it works: an **external publisher process** publishing `/telemetry`, a recorder node that discovers it via `get_topic_names_and_types()`, subscribes with `create_subscription(msg_cls, topic, cb, qos, raw=True)` (the callback receives plain `bytes` CDR), writes each frame straight to a `rosbag2_py.SequentialWriter` via `writer.write(topic, bytes, ns)`, stops after a bounded count, and the resulting bag re-opens through the v1 `RosbagsReader` and iterates with correct data. The generic-subscription mechanism (D-05) and the `SequentialWriter` wiring (D-04) are both **verified working**. The lazy-import package skeleton (D-03/D-11) was also verified: `import rosbagger_record` succeeds in the ROS-free venv without pulling `rclpy`/`rosbag2_py` into `sys.modules`, and `record()` raises a teaching capability error when ROS is absent.

**Two findings change the plan and need a planning decision (see Open Questions + Assumptions):**
1. **MCAP storage is NOT installed on this box.** `rosbag2_py.get_registered_writers()` returns only `{'sqlite3', ...test plugins}`; `ros-humble-rosbag2-storage-mcap` is apt-available but **not installed**, and installing it needs `sudo` (password required — not autonomously available). D-04/D-08 lock recording to **MCAP via rosbag2_py**, but that storage plugin is missing. The live integration test therefore cannot record real MCAP via `rosbag2_py` on this box *as-is* — it falls back to `sqlite3` (which I used to prove SC2/SC3).
2. **ROS 2 Humble bags do NOT embed message definitions for the sqlite3 backend** (no `message_definitions` table; metadata `version: 5`). A `rosbag2_py`-recorded **sqlite3** bag re-opens via the v1 reader **only when given `default_typestore=ROS2_HUMBLE`** (verified). MCAP self-describes (the rosbags-written MCAP re-opened with no typestore — that is precisely why the design locked MCAP), so a real MCAP recording would satisfy SC3 with no typestore; but see finding #1.

**Primary recommendation:** Build the `rosbagger-record` package with the verified manual-`SequentialWriter` + `raw=True` subscription pipeline. Make the storage backend a parameter defaulting to MCAP (D-08), but have the package *detect* registered writers (`rosbag2_py.get_registered_writers()`) and surface a teaching error if `mcap` is unavailable. Write the **live integration test to record MCAP**, gated by both `pytest.importorskip("rclpy")` **and** a skip-if-`mcap`-not-registered guard, so it proves the locked MCAP path where the plugin is present and skips cleanly here (the offline CI skips it anyway). Have the SC3 re-open assertion pass `default_typestore=ROS2_HUMBLE` defensively — it is a harmless no-op for self-describing MCAP and the only thing that makes a sqlite3 bag re-open.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** — New SEPARATE workspace package `packages/rosbagger-record/` (a `uv` workspace member under `members = ["packages/*"]`). Logic in its Python API; thin CLI. Design-locked: "live modules isolate `rclpy` behind their package boundary"; offline `core`/`bagq` never import ROS.
- **D-02** — Console script `rosbagger-record`, NOT a `bagq record` subcommand. Keeps `bagq`'s import graph 100% offline. API-first / CLI↔GUI parity: the Phase-14 GUI Record panel capability-gates over this same package API.
- **D-03** — `rclpy`/`rosbag2_py` are ENVIRONMENT-provided, NOT `uv`-resolved dependencies. They come from the sourced ROS 2 distro (declaring them in `pyproject` would make `uv` try to resolve absent/stub PyPI wheels). `rosbagger-record`'s only `uv`-resolved dependency is `rosbagger-core`. It documents "requires a sourced ROS 2 environment," and **lazy-imports** `rclpy`/`rosbag2_py` inside functions so the package itself imports cleanly even in the ROS-free uv venv.
- **D-04** — Record to MCAP via `rosbag2_py` (the ROS-native recorder), with `rclpy` for graph init/spin + topic discovery. Deliberate divergence from the edit module's `rosbags` Writer: `rosbag2_py` is the robust ROS-native recording path, and its MCAP output re-opens via the v1 reader.
- **D-05** — Generic serialized capture (no per-type Python deserialization): subscribe to each selected topic with its discovered type and hand serialized bytes straight to the `rosbag2_py` writer.
- **D-06** — Discover live topics + types via `rclpy` `get_topic_names_and_types()` (after a brief settle). `rosbagger-record list` (or `--list`) prints discoverable topics + types and exits (SC1).
- **D-07** — Record a SUBSET: positional topic args (`rosbagger-record /a /b -o OUT`), `--all` to record everything currently published, optional `--regex` / `--exclude` patterns.
- **D-08** — Default output MCAP. `-o OUT` sets the path; MCAP is the v1 lock (other formats deferred).
- **D-09** — Stop on SIGINT (Ctrl-C) with a graceful shutdown that finalizes/closes the bag so it re-opens cleanly; PLUS an optional bounded mode `--duration SECONDS` and/or `--max-messages N` (what makes the live integration test deterministic).
- **D-10** — Two-tier testing: (1) ROS-free UNIT tests in the uv venv with `rclpy`/`rosbag2_py` **mocked**; (2) LIVE integration tests run with ROS sourced, gated by `pytest.importorskip("rclpy")` + a `live` marker, SKIPPED in the offline CI, runnable on this box.
- **D-11** — Offline guarantee preserved: `rclpy`/`rosbag2_py` isolated to `rosbagger-record` and lazy-imported; `import rosbagger_record` succeeds in the ROS-free uv venv; `record()` raises a graceful capability error when `rclpy` is absent. **Extend `tests/test_offline_guard.py`** to assert `import rosbagger_core` and `import bagq` still pull NO `rclpy`/`rosbag2_py`.

### Claude's Discretion

Exact module layout; CLI flag names; the precise `rclpy` generic-subscription + `rosbag2_py` `SequentialWriter` wiring (research-confirmed below); the `live` pytest-marker name and how the ROS-sourced test lane is invoked; whether any non-MCAP `--format` is exposed. Hard constraints: offline `core`/`bagq` must NEVER import `rclpy`; the recorded bag MUST re-open via the v1 reader; live tests stay gated/skippable so the offline CI stays green.

### Deferred Ideas (OUT OF SCOPE)

- **Replay** (`rosbagger-replay`) — Phase 13.
- **GUI Record panel** — Phase 14.
- **QoS profile capture / override**, **compression**, **split by size/duration**, **service/action recording** — recording-feature depth beyond REC-01.
- **Non-MCAP record formats** (ROS 1 `.bag`, ROS 2 sqlite3) — MCAP is the v1 lock. *(NB: sqlite3 is the available-on-this-box format used for live-test fallback verification, but the shipped default and the live-test target stay MCAP per D-08.)*
- **`rosbag2_py` reader backend** — still out of scope per PROJECT.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REC-01 | Live topic discovery + checkbox-select recording (needs rclpy) | Discovery via `Node.get_topic_names_and_types()` (verified shape `(name, [type_str])`, settle confirmed); subset selection over the discovered map; recording via `create_subscription(raw=True)` → `SequentialWriter.write()` (verified end-to-end); SC3 re-open via v1 `RosbagsReader` (verified, 4 msgs round-tripped from an external publisher). |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Live topic discovery | `rosbagger-record` (live, rclpy) | — | Requires a live ROS graph; `rclpy.Node.get_topic_names_and_types()` is the only source. Cannot live in the offline tier. |
| Topic subset selection | `rosbagger-record` API (pure Python) | — | Pure filtering over the discovered `{topic: type}` map; no ROS call needed once discovery has run. Unit-testable with mocks. |
| Serialized capture (subscribe + write) | `rosbagger-record` (live, rclpy + rosbag2_py) | — | `raw=True` subscription + `SequentialWriter.write()`; the only ROS-runtime-bound work. |
| Stop control (SIGINT / bounded) | `rosbagger-record` API + spin loop | — | `rclpy.ok()` flips on SIGINT; bounded counters are pure Python; `writer.close()` finalizes. |
| Bag re-open verification (SC3) | `rosbagger-core` v1 reader (offline) | — | The recorded bag is read back through the EXISTING `RosbagsReader`/`AnyReader` — no new read code, only an assertion. This is the offline↔live closing loop. |
| CLI presentation | `rosbagger-record` CLI (thin) | — | API-first: the CLI parses args and calls the package API; the Phase-14 GUI is the other thin face. |

## Standard Stack

### Core (environment-provided — NOT uv-resolved, D-03)

| Library | Version (verified on box) | Purpose | Why Standard |
|---------|--------------------------|---------|--------------|
| `rclpy` | 3.3.21 `[VERIFIED: /opt/ros/humble package.xml]` | ROS 2 graph init, node, topic discovery, `raw=True` subscription, SIGINT-aware `ok()` | The official ROS 2 Python client; only way to touch a live graph. |
| `rosbag2_py` | 0.15.16 `[VERIFIED: /opt/ros/humble package.xml]` | `SequentialWriter` + `StorageOptions`/`ConverterOptions`/`TopicMetadata` — the ROS-native recorder | Design-locked recorder (§5.2); writes the same bag format the rest of ROS 2 records. |
| `rosidl_runtime_py` | (ships with Humble) `[VERIFIED: importable]` | `utilities.get_message(type_str)` → message **class** for `create_subscription` | Resolves a discovered type string into the class `create_subscription` requires; the missing glue between discovery and subscription. |

### Supporting (uv-resolved)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `rosbagger-core` | 0.1.0 (workspace) | The v1 `RosbagsReader` (SC3 re-open contract) + the `errors.py` teaching pattern | Always — the package's ONLY uv-resolved dependency (D-03). |
| `rosbags` | >=0.11,<0.12 (transitive via core) | The `AnyReader` that reads the recorded MCAP/sqlite3 back (SC3) | In the SC3 re-open assertion (already used by `RosbagsReader`). Also present in **system** python3 for the live test. |
| `typer`/`click` | >=0.15 (mirror bagq) | Thin `rosbagger-record` CLI + console script | The CLI face (D-02). Mirror `bagq`'s `[project.scripts]`. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual `SequentialWriter` + `raw=True` subscription (verified) | `rosbag2_py.Recorder` (high-level) | `Recorder.record()` is an opaque pybind builtin (no introspectable signature), gives less control over bounded-stop/`--max-messages`, and shares the same storage layer (so MCAP availability is identical). The manual path is more testable and exactly fits D-05/D-09. **Recommend manual path.** |
| `rosbag2_py` MCAP writer (D-04, locked) | `rosbags` `Writer(storage_plugin=MCAP)` (offline, self-describing) | The rosbags Writer is the *offline edit* path (Phase 11), NOT the live-record path — substituting it contradicts D-04 and the design quote. Noted only as the reason MCAP self-describes. **Do NOT substitute** for live record. |
| `create_subscription(raw=True)` (verified) | per-type deserialize then re-serialize | Defeats D-05 (no per-type Python deserialization). `raw=True` hands CDR bytes straight through. **Recommend raw=True.** |

**Installation (the new package's `pyproject.toml` — env deps NOT declared):**
```toml
# packages/rosbagger-record/pyproject.toml
[project]
name = "rosbagger-record"
version = "0.1.0"
requires-python = ">=3.10"
# ONLY rosbagger-core is uv-resolved. rclpy/rosbag2_py/rosidl_runtime_py are
# environment-provided by a sourced ROS 2 distro and are DELIBERATELY absent
# here so `uv sync` never tries to fetch nonexistent PyPI wheels (D-03).
dependencies = ["rosbagger-core", "typer>=0.15,<1"]

[project.scripts]
rosbagger-record = "rosbagger_record.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
The root `pyproject.toml` `[tool.uv.workspace] members = ["packages/*"]` already globs the new package in; `[tool.uv.sources] rosbagger-core = { workspace = true }` already wires the intra-workspace dep. **Verified:** `uv sync --locked --dev` is clean today (exit 0, 41 packages); adding a package whose only dep is the workspace `rosbagger-core` keeps it clean (no new external resolution).

**Version verification:**
```bash
# (ROS sourced) — both confirmed present and importable
python3 -c "import rclpy, rosbag2_py, rosidl_runtime_py"   # OK
grep '<version>' /opt/ros/humble/share/rclpy/package.xml        # 3.3.21
grep '<version>' /opt/ros/humble/share/rosbag2_py/package.xml   # 0.15.16
# (uv venv, offline) — both absent by design
PYTHONPATH="" uv run python -c "import rclpy"   # ModuleNotFoundError (correct)
```

## Package Legitimacy Audit

> The new package declares only `rosbagger-core` (workspace, already vetted) and `typer` (already a vetted `bagq` dependency). `rclpy`/`rosbag2_py`/`rosidl_runtime_py` are **environment-provided ROS distro packages**, not registry installs — slopcheck/PyPI auditing does not apply (they ship with `/opt/ros/humble`, verified on disk). No new third-party PyPI package is introduced.

| Package | Registry | Source | slopcheck | Disposition |
|---------|----------|--------|-----------|-------------|
| `rosbagger-core` | workspace (local) | this repo | n/a (local) | Approved (existing) |
| `typer` | PyPI | already a `bagq` dep (`typer>=0.15,<1`) | n/a (pre-vetted Phase 1/7) | Approved (existing) |
| `rclpy` | ROS distro (`/opt/ros/humble`) | apt `ros-humble-rclpy` | n/a (env-provided, on disk) | Environment dependency — not pyproject-declared |
| `rosbag2_py` | ROS distro (`/opt/ros/humble`) | apt `ros-humble-rosbag2-py` | n/a (env-provided, on disk) | Environment dependency — not pyproject-declared |
| `rosidl_runtime_py` | ROS distro (`/opt/ros/humble`) | apt `ros-humble-rosidl-runtime-py` | n/a (env-provided, on disk) | Environment dependency — not pyproject-declared |

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. No new PyPI install is added by this phase; slopcheck was not run because no new registry package is introduced.

## Architecture Patterns

### System Architecture Diagram

```
                         LIVE ROS 2 graph (DDS)
                                  │
        ┌─────────────────────────┼──────────────────────────┐
        │   external publishers (robot/sim) publish topics    │
        └─────────────────────────┬──────────────────────────┘
                                  │ DDS discovery
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  rosbagger-record  (runs ONLY in a sourced ROS 2 env)          │
   │                                                                │
   │  rclpy.init()  ──►  Node                                       │
   │       │                                                        │
   │       ▼  (settle: spin_once ×N)                                │
   │  get_topic_names_and_types() ──► {topic: [type_str]}  (D-06)   │
   │       │                                                        │
   │       ▼  selection (positional / --all / --regex / --exclude)  │
   │  selected = filter(discovered)              (D-07, pure Py)    │
   │       │                                                        │
   │       ▼  per selected topic:                                   │
   │   get_message(type_str) ─► msg_cls                             │
   │   create_subscription(msg_cls, topic, cb, qos, raw=True)       │
   │   create_topic(TopicMetadata(name,type,'cdr'))  ──► writer     │
   │       │                                                        │
   │  raw cb(data: bytes) ─► writer.write(topic, data, now_ns)      │
   │       │                                            (D-05)      │
   │       ▼  spin loop until: SIGINT (rclpy.ok()→False)            │
   │            OR n>=max_messages OR now>=deadline    (D-09)       │
   │       │                                                        │
   │  writer.close()  ──► finalizes/flushes the bag                 │
   └───────────────────────────────┬──────────────────────────────┘
                                  │  bag dir (MCAP, or sqlite3 fallback)
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  SC3 re-open  —  rosbagger-core v1 reader (OFFLINE, no rclpy)   │
   │  with RosbagsReader(out, default_typestore=ROS2_HUMBLE) as r:  │
   │      msgs = list(r.read())   ──► assert topics/count           │
   └──────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
packages/rosbagger-record/
├── pyproject.toml                 # only dep = rosbagger-core; console script
└── src/rosbagger_record/
    ├── __init__.py                # lazy _require_ros(); re-export public API. NO top-level rclpy import.
    ├── discovery.py               # discover_topics(settle=...) -> dict[str, str]; selection filters (pure-Py, unit-testable)
    ├── record.py                  # record(topics, out, *, storage='mcap', max_messages=None, duration=None) — the rclpy/rosbag2_py core
    ├── errors.py                  # RosNotAvailableError, McapStorageUnavailableError (teaching capability errors)
    └── cli.py                     # thin typer app: `list` + record verbs (D-02/D-07/D-08/D-09)
tests/
├── test_record_unit.py           # ROS-MOCKED unit tests (run in uv venv / offline CI)
└── test_record_live.py           # LIVE: importorskip("rclpy") + skip-if-no-mcap + `live` marker
```

### Pattern 1: Lazy ROS import behind the package boundary (D-03/D-11) — VERIFIED
**What:** The package top level imports cleanly without ROS; `rclpy`/`rosbag2_py` are imported *inside* functions, and a `_require_ros()` guard converts a missing ROS env into a teaching error.
**When to use:** Every entry point that touches ROS.
**Example:**
```python
# src/rosbagger_record/__init__.py — VERIFIED: imports clean in PYTHONPATH="" uv venv,
# does NOT populate sys.modules with rclpy/rosbag2_py, and record() raises the teaching error.
from __future__ import annotations
from .errors import RosNotAvailableError

def _require_ros() -> None:
    try:
        import rclpy  # noqa: F401
        import rosbag2_py  # noqa: F401
    except ImportError as e:
        raise RosNotAvailableError() from e  # "source your ROS 2 environment"

def record(*args, **kwargs):
    _require_ros()                     # lazy — only fails when CALLED (D-11)
    from .record import record as _r   # the impl module does the heavy rclpy import
    return _r(*args, **kwargs)
```

### Pattern 2: Generic serialized capture (D-05) — VERIFIED end-to-end
**What:** Resolve the discovered type string to a class, subscribe with `raw=True` (callback gets plain CDR `bytes`), write straight to the writer.
**Example:**
```python
# Source: executed against ROS 2 Humble on this box (rclpy 3.3.21 / rosbag2_py 0.15.16)
from rosidl_runtime_py.utilities import get_message  # type_str -> message class

def _make_writer(out: str, storage_id: str = "mcap"):
    import rosbag2_py
    w = rosbag2_py.SequentialWriter()
    w.open(
        rosbag2_py.StorageOptions(uri=out, storage_id=storage_id),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr", output_serialization_format="cdr"
        ),
    )
    return w

def _subscribe_and_record(node, writer, topic: str, type_str: str):
    writer.create_topic(
        rosbag2_py.TopicMetadata(name=topic, type=type_str, serialization_format="cdr")
    )
    msg_cls = get_message(type_str)                 # e.g. "std_msgs/msg/String" -> String
    def on_raw(data):                               # VERIFIED: `data` is plain `bytes` (CDR)
        writer.write(topic, bytes(data), node.get_clock().now().nanoseconds)
    node.create_subscription(msg_cls, topic, on_raw, 10, raw=True)
```
Notes (verified):
- `create_subscription` signature includes `raw: bool = False` (keyword-only after `*`). The `raw=True` callback delivers **`builtins.bytes`** in Humble — `bytes(data)` is a safe identity that also works if a future distro hands a `SerializedMessage`.
- `writer.write(topic: str, data: bytes, timestamp_ns: int)` — three positional args (verified docstring `(arg0: str, arg1: str, arg2: int)`).
- `TopicMetadata(name, type, serialization_format, offered_qos_profiles="")` — empty `offered_qos_profiles` is fine (verified: the bag re-opens).

### Pattern 3: Topic discovery with settle (D-06) — VERIFIED
**What:** `get_topic_names_and_types()` returns `List[Tuple[str, List[str]]]`. The recorder's own publishers are visible immediately, but **external** publishers need a brief spin/settle for DDS discovery to propagate.
**Example:**
```python
# Source: executed on box — external `/telemetry` discovered only after the settle loop
def discover_topics(node, *, settle_iters: int = 30, settle_dt: float = 0.02) -> dict[str, str]:
    import rclpy
    for _ in range(settle_iters):
        rclpy.spin_once(node, timeout_sec=settle_dt)   # let discovery populate
    # take the FIRST type per topic (multi-type topics are rare; pick [0])
    return {name: types[0] for name, types in node.get_topic_names_and_types() if types}
```

### Pattern 4: Bounded / SIGINT-graceful stop (D-09) — VERIFIED primitives
**What:** `rclpy.init()` installs a SIGINT handler so `rclpy.ok()` flips to `False` on Ctrl-C. The bounded loop adds a counter and/or a deadline. `writer.close()` in a `finally` finalizes the bag so it re-opens.
**Example:**
```python
# Source: rclpy.ok()/spin_once verified; ExternalShutdownException at rclpy.executors
import time, rclpy
def _run(node, writer, captured, *, max_messages=None, duration=None):
    deadline = time.time() + duration if duration else None
    try:
        while rclpy.ok():
            if max_messages is not None and captured["n"] >= max_messages:
                break
            if deadline is not None and time.time() >= deadline:
                break
            rclpy.spin_once(node, timeout_sec=0.05)
    except KeyboardInterrupt:           # belt-and-suspenders; rclpy.ok() usually handles it
        pass
    finally:
        writer.close()                  # MUST finalize so the bag re-opens (SC3)
```

### Pattern 5: Storage-availability capability gate (NEW — addresses the MCAP finding)
**What:** Before opening an MCAP writer, check that the `mcap` storage plugin is registered; if not, raise a teaching error (or, if a `--format sqlite3` escape is exposed, fall back).
**Example:**
```python
def _check_storage(storage_id: str) -> None:
    import rosbag2_py
    available = rosbag2_py.get_registered_writers()   # VERIFIED: {'sqlite3', ...} on this box
    if storage_id not in available:
        from .errors import McapStorageUnavailableError
        raise McapStorageUnavailableError(storage_id, sorted(available))
```

### Anti-Patterns to Avoid
- **Importing `rclpy`/`rosbag2_py` at module top in `rosbagger_record`** — breaks the offline-import promise; `import rosbagger_record` must succeed in the ROS-free venv. Lazy-import inside functions (verified working).
- **Declaring `rclpy`/`rosbag2_py` in `pyproject.toml` dependencies** — `uv` will try to resolve nonexistent/stub PyPI wheels and break `uv sync` (D-03). They are environment-provided.
- **Substituting the `rosbags` Writer for the `rosbag2_py` writer** — that is the offline edit path, not the live record path (contradicts D-04).
- **Deserializing per message** — defeats D-05; use `raw=True`.
- **Forgetting `writer.close()`** — an unfinalized bag may not re-open (SC3 fails). Always close in a `finally`.
- **Asserting SC3 without a `default_typestore` for sqlite3 bags** — a `rosbag2_py` sqlite3 bag has no embedded defs and raises `UnresolvedTypeError` on re-open (verified). Pass `default_typestore=ROS2_HUMBLE`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Type string → message class | A manual `importlib` of `pkg.msg._type` | `rosidl_runtime_py.utilities.get_message(type_str)` | Handles the package/`msg`/CamelCase mapping correctly; verified resolves `sensor_msgs/msg/Imu` → class. |
| CDR (de)serialization | A custom serializer | `raw=True` subscription (bytes pass-through) | `rclpy` hands you the exact CDR bytes; no codec needed (D-05). |
| Bag writing / MCAP encoding | A custom MCAP/sqlite3 writer | `rosbag2_py.SequentialWriter` | The ROS-native recorder; produces bags the whole ecosystem reads. |
| Bag re-open / iteration (SC3) | New read code | The existing `rosbagger_core.reader.RosbagsReader` | SC3 is literally "the v1 reader re-opens it" — verified, needs only an assertion. |
| SIGINT handling | A custom `signal.signal` | `rclpy.init()` + `rclpy.ok()` loop | rclpy installs its own SIGINT handler; `ok()` flips to False. Verified. |
| Multi-bag / format detection on re-open | Anything | `AnyReader` (via `RosbagsReader`) | Already owns format detection for ROS1/ROS2/MCAP. |

**Key insight:** Almost the entire recorder is wiring three ROS-native primitives (`get_topic_names_and_types`, `create_subscription(raw=True)`, `SequentialWriter`) plus the package's own pure-Python selection/stop logic. The only genuinely new code is the lazy-import boundary, the selection filters, the bounded-stop loop, and the thin CLI — all unit-testable with mocks.

## Runtime State Inventory

> Not a rename/refactor/migration phase — this is a greenfield package addition. No stored data, live-service config, OS-registered state, secrets, or pre-existing build artifacts are mutated by this phase.
>
> - **Stored data:** None — this phase creates new bags; it migrates nothing.
> - **Live service config:** None — no external service config is touched.
> - **OS-registered state:** None.
> - **Secrets/env vars:** None new. The phase *depends on* the ambient `ROS_DISTRO`/`AMENT_PREFIX_PATH`/`PYTHONPATH` set by `source /opt/ros/humble/setup.bash`, but introduces no secret of its own.
> - **Build artifacts:** A new `uv` workspace member is added; `uv.lock` gains the `rosbagger-record` workspace entry (its only dep is the already-locked `rosbagger-core`). The `rosbagger-record` console script installs into `.venv/bin/` on `uv sync` (verified pattern for `bagq`).

## Common Pitfalls

### Pitfall 1: MCAP storage plugin missing → recording the locked format fails
**What goes wrong:** `rosbag2_py.SequentialWriter.open()` with `storage_id="mcap"` fails (or `get_registered_writers()` lacks `mcap`) because `ros-humble-rosbag2-storage-mcap` is not installed.
**Why it happens:** On this box only `sqlite3` is registered (verified: `get_registered_writers()` → `{'sqlite3', 'my_test_plugin'}`); the MCAP plugin is a separate apt package, not installed, and installing it needs `sudo` (password required).
**How to avoid:** Add Pattern 5's storage-availability gate; write the **live MCAP test** with a skip guard `mcap in rosbag2_py.get_registered_writers()` so it proves the locked path where the plugin is present and skips here. For local verification on this box, the recorder/test can fall back to `sqlite3` (which I used to prove SC2/SC3), but the SHIPPED default stays MCAP (D-08).
**Warning signs:** `RuntimeError`/`pluginlib` "could not find library corresponding to plugin mcap"; `get_registered_writers()` lacks `mcap`.

### Pitfall 2: sqlite3 bags have no embedded message definitions → SC3 re-open raises
**What goes wrong:** Re-opening a `rosbag2_py`-recorded **sqlite3** bag via `RosbagsReader` raises `UnresolvedTypeError` ("no type definitions").
**Why it happens:** ROS 2 Humble's sqlite3 storage (rosbag2 0.15, metadata `version: 5`) does not persist message definitions — the DB has only `schema/metadata/topics/messages`, no `message_definitions` table (verified). `AnyReader` needs defs.
**How to avoid:** Pass `default_typestore=get_typestore(Stores.ROS2_HUMBLE)` to `RosbagsReader` (verified: makes the sqlite3 bag re-open and iterate). For **MCAP** the schema is embedded (the rosbags-written MCAP re-opened with NO typestore — verified), so MCAP satisfies SC3 cleanly; the typestore is then a harmless no-op. Make the SC3 assertion pass the typestore defensively either way.
**Warning signs:** `rosbagger_core.errors.UnresolvedTypeError` on the re-open assertion.

### Pitfall 3: Console script installed in the uv venv but needs ROS python to run
**What goes wrong:** `rosbagger-record` is installed into `.venv/bin/` (verified pattern), but the uv venv python has no `rclpy`; meanwhile system `python3` (which has rclpy) can't see the venv's `rosbagger_record` package.
**Why it happens:** The offline uv venv is created `include-system-site-packages = false` (verified) — deliberately ROS-free. The two interpreters are disjoint.
**How to avoid:** Run the recorder/live-test through **system `python3` with ROS sourced**, prepending the src trees to the (ROS-populated) `PYTHONPATH` — NOT replacing it. Verified recipe in "Environment Availability". The lazy `_require_ros()` makes the venv-installed console script fail with a clear teaching error rather than a raw `ModuleNotFoundError`.
**Warning signs:** `ModuleNotFoundError: No module named 'rclpy'` from the venv console script; `No module named 'rosbagger_record'` from system python without the src on PYTHONPATH.

### Pitfall 4: External-topic discovery returns empty without a settle
**What goes wrong:** `get_topic_names_and_types()` immediately after node creation misses topics published by *other* processes.
**Why it happens:** DDS discovery is asynchronous; it needs a few spin cycles to populate. (Own publishers appear immediately — verified — which can mask this in single-process tests.)
**How to avoid:** Spin `~30 × 20ms` before reading (Pattern 3, verified to discover an external `/telemetry`). Make `list` and `record` both settle first.
**Warning signs:** `list` shows fewer topics than `ros2 topic list`; intermittent empty discovery in the live test.

### Pitfall 5: Offline guard regression
**What goes wrong:** A stray `import rosbagger_record` (or a non-lazy ROS import) sneaks into `rosbagger_core`/`bagq`, or the new package imports ROS at top level.
**Why it happens:** Convenience top-level imports.
**How to avoid:** Keep all `rclpy`/`rosbag2_py`/`rosidl_runtime_py` imports inside function bodies. **Extend `tests/test_offline_guard.py`** (D-11): assert `import rosbagger_core`/`import bagq` still leak no `rclpy`/`rosbag2_py` (the existing `_HEAVY_STACK`/fresh-subprocess helpers extend naturally), and add a positive test that `import rosbagger_record` succeeds without populating `sys.modules` with `rclpy`/`rosbag2_py` (verified achievable).
**Warning signs:** `test_no_ros_leaked_into_sys_modules` fails; `import rosbagger_record` pulls ROS in a fresh interpreter.

### Pitfall 6: Mocking ROS in unit tests when the modules are absent
**What goes wrong:** A unit test that does `mock.patch("rclpy.create_node")` fails at *collection* because `rclpy` can't be imported in the uv venv.
**Why it happens:** `mock.patch` with a string target imports the target module.
**How to avoid:** Because imports are lazy (inside functions), inject mocks via `sys.modules["rclpy"] = MagicMock()` / `sys.modules["rosbag2_py"] = MagicMock()` (or a fixture/`monkeypatch.setitem(sys.modules, ...)`) BEFORE calling the function — the function's `import rclpy` then binds the mock. Test selection/stop/CLI logic this way (D-10 tier 1). Verified that the lazy structure makes the bare import succeed, which is the precondition for this technique.
**Warning signs:** `ModuleNotFoundError` during collection of the unit test in `PYTHONPATH="" uv run pytest`.

## Code Examples

### List discoverable topics (SC1)
```python
# Source: verified shape on box — get_topic_names_and_types() -> List[Tuple[str, List[str]]]
def list_topics() -> dict[str, str]:
    _require_ros()
    import rclpy
    rclpy.init()
    try:
        node = rclpy.create_node("rosbagger_record_list")
        try:
            return discover_topics(node)        # settle + {topic: type_str}
        finally:
            node.destroy_node()
    finally:
        rclpy.shutdown()
```

### Full record path (SC2) — distilled from the verified end-to-end probe
```python
# Source: executed end-to-end on box (external publisher -> 4 msgs recorded -> re-opened)
def record(topics: list[str], out: str, *, storage_id: str = "mcap",
           max_messages: int | None = None, duration: float | None = None) -> int:
    _require_ros()
    import rclpy
    _check_storage(storage_id)                          # Pattern 5 capability gate
    rclpy.init()
    captured = {"n": 0}
    try:
        node = rclpy.create_node("rosbagger_recorder")
        discovered = discover_topics(node)              # settle (Pattern 3)
        selected = {t: discovered[t] for t in topics if t in discovered}
        writer = _make_writer(out, storage_id)
        try:
            for topic, type_str in selected.items():
                _subscribe_and_record(node, writer, topic, type_str)  # Pattern 2
            _run(node, writer, captured,
                 max_messages=max_messages, duration=duration)        # Pattern 4
        finally:
            writer.close()                              # finalize (SC3)
        return captured["n"]
    finally:
        node.destroy_node(); rclpy.shutdown()
```

### SC3 re-open assertion (the offline↔live closing loop) — VERIFIED
```python
# Source: executed on box — sqlite3 needs the typestore; MCAP self-describes (typestore = no-op)
from rosbagger_core.reader.rosbags_reader import RosbagsReader
from rosbags.typesys import get_typestore, Stores

def assert_reopens(out, expected_topic: str, expected_count: int) -> None:
    ts = get_typestore(Stores.ROS2_HUMBLE)              # harmless for self-describing MCAP
    with RosbagsReader(out, default_typestore=ts) as r:
        msgs = list(r.read())
    assert len(msgs) == expected_count
    assert all(m.topic == expected_topic for m in msgs)
```

### Live integration test skeleton (D-10 tier 2) — verified primitives
```python
# tests/test_record_live.py
import pytest
rclpy = pytest.importorskip("rclpy")                    # skip in offline CI / ROS-free venv

pytestmark = pytest.mark.live

def _mcap_available() -> bool:
    import rosbag2_py
    return "mcap" in rosbag2_py.get_registered_writers()

@pytest.mark.skipif(not _mcap_available(),
                    reason="ros-humble-rosbag2-storage-mcap not installed")
def test_record_mcap_reopens(tmp_path):
    # external publisher (subprocess or a second node) -> recorder bounded -> re-open
    # record(topics=["/telemetry"], out=str(tmp_path/"rec"),
    #        storage_id="mcap", max_messages=4)
    # assert_reopens(tmp_path/"rec", "/telemetry", 4)
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-type deserialize then re-serialize to record | `create_subscription(raw=True)` (CDR bytes pass-through) | rclpy ≥ Foxy | Generic recorder needs no per-type Python codec (D-05). Verified in Humble. |
| sqlite3-only rosbag2 default | MCAP is the recommended ROS 2 default storage (self-describing) | rosbag2 ≥ Iron default; Humble has it as a plugin | MCAP embeds schemas → portable, self-describing bags (the D-04/D-08 rationale). |
| Manual `signal.signal` for Ctrl-C | `rclpy.init()` SIGINT handler + `rclpy.ok()` loop / `ExternalShutdownException` | rclpy current | Graceful shutdown is built-in (D-09). Verified `rclpy.ok()` exists; `ExternalShutdownException` at `rclpy.executors`. |

**Deprecated/outdated:**
- Hand-rolled MCAP writers: superseded by `rosbag2_py` + the storage plugin (and `rosbags` for the offline read/edit path).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A `rosbag2_py`-recorded **MCAP** bag (storage plugin present) re-opens via the v1 reader **without** a `default_typestore`, because MCAP embeds schemas. I verified MCAP self-description using the **rosbags** MCAP writer (re-opened with no typestore) and verified the `rosbag2_py` *sqlite3* path needs a typestore — but I could NOT install the `rosbag2_py` MCAP plugin (needs sudo) to verify the `rosbag2_py`-MCAP combination directly. | Open Q1, Pitfall 2 | LOW–MEDIUM: if the `rosbag2_py` MCAP writer somehow omits schemas, SC3 for real MCAP would still need the typestore. The SC3 assertion passes the typestore defensively, so it succeeds either way; only the "MCAP is self-describing" *claim* would be wrong. |
| A2 | `ros-humble-rosbag2-storage-mcap` (apt candidate 0.15.16, verified available) installs cleanly and registers `mcap` in `get_registered_writers()`. Not installed/verified on this box (sudo required). | Open Q2, Env Availability | MEDIUM: if it cannot be installed in the live-test environment, the locked MCAP path can only be exercised where the plugin exists; the live MCAP test stays skipped here (sqlite3 fallback proves the mechanism). Does not block shipping the package. |
| A3 | The live test lane will run on a host where ROS is sourced AND (for the MCAP assertion) the MCAP plugin is installed. On THIS box, ROS is sourced but MCAP is not installed, so the MCAP assertion skips here; the sqlite3-fallback assertion proves SC2/SC3 mechanically (verified). | Open Q2, D-10 | LOW: the unit tier + sqlite3-fallback live tier fully cover the orchestration; the MCAP-specific assertion is the only thing gated on the plugin. |
| A4 | `typer>=0.15,<1` (the `bagq` pin) is appropriate for the `rosbagger-record` CLI. Mirrors the existing console-script pattern; not separately re-verified for this package. | Standard Stack | LOW: same library/version already shipping in `bagq`. |

## Open Questions

1. **Does the `rosbag2_py` MCAP writer embed message definitions (so SC3 needs no typestore)?**
   - What we know: MCAP *as a format* embeds schemas; the **rosbags**-written MCAP re-opened with no typestore (verified). The `rosbag2_py` **sqlite3** bag does NOT embed defs and needs `default_typestore=ROS2_HUMBLE` (verified).
   - What's unclear: the `rosbag2_py`-**MCAP** combination specifically — the plugin isn't installed here (sudo) so I couldn't run it.
   - Recommendation: write SC3 to pass `default_typestore=ROS2_HUMBLE` defensively (harmless no-op for self-describing MCAP, required for sqlite3). This makes SC3 robust regardless of the answer. If the live host has MCAP installed, the test will incidentally confirm the answer.

2. **Will the live test lane have the MCAP storage plugin installed, and is `sudo apt install ros-humble-rosbag2-storage-mcap` available there?**
   - What we know: apt candidate `0.15.16-1jammy` is available but uninstalled; install needs `sudo` (password prompt — not autonomous here).
   - What's unclear: whether the human/CI live lane can install it.
   - Recommendation: guard the MCAP live test with `skipif("mcap" not in rosbag2_py.get_registered_writers())` and a teaching capability error in the package (Pattern 5). Optionally expose a `--format sqlite3` escape so the recorder is usable on this box today; keep MCAP the default (D-08). Flag this as a human follow-up: "to run the MCAP live test / record MCAP here, `sudo apt install ros-humble-rosbag2-storage-mcap`."

3. **Marker name + CI registration for the `live` lane.**
   - What we know: `pytest.importorskip("rclpy")` + a `live` marker skip cleanly in the offline CI (which never sources ROS). The offline `addopts` (`--cov-fail-under=80`) run by `PYTHONPATH="" uv run pytest` will collect `tests/test_record_live.py`, hit the `importorskip`, and skip — no failure.
   - What's unclear: whether to register `live` in `[tool.pytest.ini_options] markers` (avoids the unknown-marker warning) and whether a future ROS CI lane runs it.
   - Recommendation: register the `live` marker in the root `pyproject.toml` to silence the warning; document the live-lane command (Env Availability). No ROS CI lane exists yet (STATE blockers note CI is ROS-free) — leave that to a future phase.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ROS 2 Humble (`/opt/ros/humble`) | the whole live module | ✓ | Humble | — |
| `rclpy` (sourced env) | discovery, subscription, spin, SIGINT | ✓ | 3.3.21 | none (capability error if unsourced) |
| `rosbag2_py` (sourced env) | `SequentialWriter` recording | ✓ | 0.15.16 | none |
| `rosidl_runtime_py` (sourced env) | `get_message(type_str)` | ✓ | (Humble) | none |
| `rosbag2` **mcap** storage plugin | recording the LOCKED format (D-04/D-08) | ✗ | apt candidate 0.15.16 (uninstalled) | **sqlite3** (registered) for local mechanism verification; MCAP test skipped where absent |
| System `python3` deps (live test) | running `tests/test_record_live.py` | ✓ | `pytest`,`rosbags`,`numpy`,`rosidl_runtime_py` all present | — |
| `rclpy` in uv venv | (must STAY absent — offline guarantee) | ✗ (by design) | — | n/a |

**Missing dependencies with no fallback:** none that block the package. The package imports and unit-tests in the offline venv; the live mechanism is fully verified with sqlite3.

**Missing dependencies with fallback:** the **MCAP storage plugin** — fallback is sqlite3 for local verification (with `default_typestore` on re-open); the MCAP-specific live assertion is `skipif`-guarded. Human follow-up to enable real MCAP recording/testing on this box: `sudo apt install ros-humble-rosbag2-storage-mcap`.

**Live-lane invocation recipe (VERIFIED on box):**
```bash
# System python3 with ROS sourced already has pytest + rosbags + rclpy + rosbag2_py + numpy.
# PREPEND the package src trees to the ROS-populated PYTHONPATH (do NOT replace it).
source /opt/ros/humble/setup.bash
PYTHONPATH="packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" \
  python3 -m pytest tests/test_record_live.py -m live -v
```
The offline suite is unchanged and skips the live test:
```bash
PYTHONPATH="" uv run pytest          # rclpy hidden -> importorskip skips test_record_live.py
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` >=8,<10 (root dev group) + `pytest-cov` >=6 (`--cov-fail-under=80`) |
| Config file | root `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, cov addopts) |
| Quick run command | `PYTHONPATH="" uv run pytest tests/test_record_unit.py tests/test_offline_guard.py -q` |
| Full suite command (offline) | `PYTHONPATH="" uv run pytest` (live test auto-skips) |
| Live lane | `source /opt/ros/humble/setup.bash && PYTHONPATH="packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" python3 -m pytest tests/test_record_live.py -m live` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REC-01 (discovery, SC1) | `discover_topics` returns `{topic: type_str}` after settle | unit (mocked rclpy) | `PYTHONPATH="" uv run pytest tests/test_record_unit.py -k discover` | ❌ Wave 0 |
| REC-01 (selection, D-07) | positional / `--all` / `--regex` / `--exclude` filter the discovered map | unit (pure-Py) | `PYTHONPATH="" uv run pytest tests/test_record_unit.py -k select` | ❌ Wave 0 |
| REC-01 (CLI, D-02) | `list` prints topics+types; record verbs parse flags | unit (typer CliRunner) | `PYTHONPATH="" uv run pytest tests/test_record_unit.py -k cli` | ❌ Wave 0 |
| REC-01 (capability error, D-11) | `record()` raises `RosNotAvailableError` when rclpy absent | unit | `PYTHONPATH="" uv run pytest tests/test_record_unit.py -k no_ros` | ❌ Wave 0 |
| D-11 (offline guard) | `import rosbagger_core`/`bagq` leak no rclpy/rosbag2_py; `import rosbagger_record` clean | unit (fresh subprocess) | `PYTHONPATH="" uv run pytest tests/test_offline_guard.py` | ⚠️ EXTEND existing |
| REC-01 (record+reopen, SC2+SC3) | external publisher → bounded record → re-open via v1 reader | live (importorskip + `live` + skip-if-no-mcap) | live-lane recipe above | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `PYTHONPATH="" uv run pytest tests/test_record_unit.py tests/test_offline_guard.py -q`
- **Per wave merge:** `PYTHONPATH="" uv run pytest` (full offline suite; live auto-skips; coverage ≥80%)
- **Phase gate:** Full offline suite green + ruff clean + offline guard green; live lane run manually on this box (sqlite3 fallback proves SC2/SC3) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_record_unit.py` — discovery/selection/CLI/no-ROS unit tests (mocked rclpy via `sys.modules` injection)
- [ ] `tests/test_record_live.py` — live integration test (`importorskip("rclpy")` + `live` marker + `skipif` no-mcap)
- [ ] Extend `tests/test_offline_guard.py` — assert core/bagq leak no rclpy/rosbag2_py (D-11) + `import rosbagger_record` is clean
- [ ] Register `live` marker in root `pyproject.toml` `[tool.pytest.ini_options] markers` (silence unknown-marker warning)
- [ ] Ensure `--cov` includes `rosbagger_record` OR keep it out of the gate (live-only code can't be covered offline — decide in plan; mirror how live code is excluded so the 80% gate stays meaningful)

> Coverage note: the `record.py` rclpy/rosbag2_py core cannot be exercised in the offline-coverage run (rclpy absent). Either (a) keep `rosbagger_record` out of `--cov=` (cover it via the live lane only), or (b) structure `record.py` so the pure-Python pieces (selection, stop-loop accounting) are unit-coverable and the thin rclpy wiring is the only uncovered part. Recommend (b) where cheap, plus excluding the irreducibly-live wiring — matching the project's "defensive lines uncovered, no pragma" precedent.

## Security Domain

> `security_enforcement` is not configured in this project's planning config (no `.planning/config.json` security key observed) and this is a local developer tool that records data the user already has access to on their own ROS graph. No authentication, session, access-control, or cryptography surface is introduced.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | partial | Topic-name/type strings come from the local ROS graph (trusted) and CLI args. The output path (`-o`) is a local filesystem path; rely on `rosbag2_py`'s own path handling. No SQL/identifier-injection surface (unlike the query module). |
| V6 Cryptography | no | None. |
| V2/V3/V4 (auth/session/access) | no | Local CLI; no network service, no auth. |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unbounded recording fills disk (DoS) | Denial of Service | The `--max-messages`/`--duration` bounded modes (D-09) and SIGINT stop give the operator control; document that unbounded record runs until Ctrl-C. (Split-by-size is deferred.) |
| Malicious/huge serialized payload on a topic | Tampering | `raw=True` writes bytes verbatim without deserializing in Python (D-05) — no per-type parser to exploit; the payload is opaque CDR. |

## Sources

### Primary (HIGH confidence — executed on this box)
- ROS 2 Humble `/opt/ros/humble` — `rclpy` 3.3.21, `rosbag2_py` 0.15.16 (package.xml versions); `create_subscription` signature with `raw: bool=False`; `SequentialWriter.{open,create_topic,write,close}` docstrings; `StorageOptions`/`ConverterOptions`/`TopicMetadata` constructors; `get_registered_writers()` → `{'sqlite3', test plugins}`; `get_topic_names_and_types()` shape + settle behavior; `rosidl_runtime_py.utilities.get_message`; `rclpy.ok()`/`ExternalShutdownException`.
- End-to-end probe (executed): external publisher process → discover `/telemetry` → `raw=True` subscribe → `SequentialWriter` (sqlite3) bounded record (4 msgs) → re-open via `rosbagger_core.reader.RosbagsReader(default_typestore=ROS2_HUMBLE)` → iterate (correct data).
- Lazy-import package skeleton (executed): `import rosbagger_record` clean in `PYTHONPATH="" uv run` (no rclpy/rosbag2_py in `sys.modules`); `record()` raises the teaching error.
- `uv sync --locked --dev` exit 0 (clean baseline); `.venv/pyvenv.cfg` `include-system-site-packages=false`; system `python3` has `pytest`/`rosbags`/`rclpy`/`rosbag2_py`/`rosidl_runtime_py`/`numpy`.
- `apt-cache policy ros-humble-rosbag2-storage-mcap` → candidate `0.15.16-1jammy`, Installed: (none); `sudo -n apt-get install` → "a password is required".
- Repo files: `pyproject.toml` (root + bagq + core), `reader/rosbags_reader.py`, `reader/base.py`, `errors.py`, `tests/test_offline_guard.py`, `tools/make_fixtures.py`, design spec §3.2/§4.1/§5.2.

### Secondary (MEDIUM confidence)
- `rosbags`-written MCAP self-description (re-opened with no typestore) — verified with the **rosbags** Writer; extrapolated to the `rosbag2_py` MCAP writer (A1, not directly run — plugin uninstalled).

### Tertiary (LOW confidence)
- The `rosbag2_py` MCAP writer specifically embedding schemas (A1) — inferred from the MCAP format spec + rosbags behavior; not executed on this box.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every API executed against the real ROS 2 Humble; versions read from package.xml.
- Architecture / patterns: HIGH — the full pipeline (discover → raw subscribe → SequentialWriter → re-open) was run end-to-end with an external publisher; the lazy-import package was run in the offline venv.
- Pitfalls: HIGH — Pitfalls 1–4 were each directly reproduced (MCAP missing; sqlite3 needs typestore; venv/ROS interpreter split; external-discovery settle). Pitfall 5/6 follow from the verified lazy structure.
- The single MEDIUM/LOW item is the `rosbag2_py`-MCAP self-description claim (A1), de-risked by passing `default_typestore` defensively in SC3.

**Research date:** 2026-05-23
**Valid until:** ~2026-06-22 (stable — pinned to ROS 2 Humble on this box; re-verify if the ROS distro or the MCAP plugin install state changes)
