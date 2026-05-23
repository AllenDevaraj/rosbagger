# Phase 13: Live Replay - Research

**Researched:** 2026-05-23
**Domain:** Live ROS 2 bag replay — publish a bag's messages to real ROS topics with transport controls (play/pause/step/seek/rate/loop), behind a new `rclpy`-isolated workspace package that keeps the offline tier ROS-free.
**Confidence:** HIGH (every publish-path API claim was executed against the real ROS 2 Humble on this box; the full `bag → raw CDR → deserialize_message → publish → subscriber receives` loop was run end-to-end and SC1 verified with a project fixture bag)

## Summary

Phase 13 adds `rosbagger-replay`: read a bag and publish its messages onto a live ROS 2 graph with transport controls, proving a real subscriber receives them. It is the project's SECOND live module (after `rosbagger-record`, Phase 12), and it mirrors that package almost exactly — same lazy-`rclpy` boundary, same env-provided-not-uv-resolved dependency rule, same two-tier test split, same offline-guard extension. The decisions are LOCKED (D-01..D-12); this research confirms the concrete HOW and surfaces two findings that change the recommended read-source choice.

**The publish path (D-04) is VERIFIED end-to-end on this box.** I wrote a ROS 2 sqlite3 fixture bag (via the existing `tools.make_fixtures`), read its raw CDR bytes, deserialized each to a typed `rclpy` message, published on `create_publisher(msg_cls, topic, qos)`, and a separate subscriber node received all 3 `/imu` messages with the correct payload (`linear_acceleration.z == 9.8`). The chain `raw_cdr → rclpy.serialization.deserialize_message(raw, get_message(type_str)) → publisher.publish(msg)` works exactly as D-04 specifies. I also CONFIRMED the D-04 rationale directly: a rosbags-deserialized `Message.msg` (`rosbags.usertypes.sensor_msgs__msg__Imu`) is NOT republishable — `rclpy.serialization.serialize_message` raises `AttributeError: type object 'type' has no attribute '_TYPE_SUPPORT'` on it. You must publish from raw CDR, not from `Message.msg`.

**Two findings change the D-05 raw-CDR source choice (the primary research item):**

1. **`rosbag2_py.SequentialReader` CANNOT open the project's `rosbags`-written fixture bags on Humble.** `reader.open(StorageOptions(...), ConverterOptions(...))` raises `RuntimeError: Exception on parsing info file: yaml-cpp: error at line 25, column 29: bad conversion`. Root cause: `rosbags` writes `metadata.yaml` with `offered_qos_profiles: []` (an empty YAML *sequence*), but Humble's `rosbag2_py` metadata parser expects `offered_qos_profiles` to be a *string* scalar. So the CONTEXT's "recommended default" of `rosbag2_py.SequentialReader` for the live read side does NOT work against the fixtures the live test must replay. (The same incompatibility is why Phase 12 RECORDED through `rosbag2_py` but re-opened through the v1 `rosbags` reader — the two reader stacks disagree on metadata format.)

2. **The v1 `rosbags` `AnyReader` already exposes raw CDR bytes natively, and it works for all three formats + is the SAME reader the rest of the project uses.** `AnyReader.messages()` yields `(connection, t_ns, rawdata: bytes)` where, for ROS 2 bags, `rawdata` IS the CDR payload `deserialize_message` accepts (verified: 52-byte CDR for `/cmd_vel`, fed straight through). It reads sqlite3, MCAP (self-describing, no typestore needed), AND ROS 1 — uniformly, with no ROS install on the read side.

**Primary recommendation:** Use the **v1 `rosbags` `AnyReader` as the raw-CDR source** (NOT `rosbag2_py.SequentialReader`), via a thin "raw bytes" accessor. For ROS 2 bags, `rawdata` is already CDR — pass it straight to `deserialize_message`. For ROS 1 bags, `rawdata` is ROS 1 wire format (a 320→332-byte size difference proves it is NOT CDR), so bridge it: `reader.deserialize(rawdata, msgtype)` → `typestore.serialize_cdr(obj, msgtype)` → CDR (verified working). Build the pure-Python `Replayer` scheduler exactly as D-06 specifies (state machine + monotonic clock + injectable sink), unit-test SC2/SC3 with a fake clock and a recording sink, and prove SC1 with a ROS-sourced live test that mirrors Phase 12's recipe inverted (replay publishes, a real `rclpy` subscriber receives).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01** — New SEPARATE workspace package `packages/rosbagger-replay/` (uv member; `members=["packages/*"]`), mirroring `rosbagger-record`. Logic in its Python API; thin CLI. Design-locked: "live modules isolate rclpy behind their package boundary."
- **D-02** — Console script `rosbagger-replay` (NOT a `bagq` subcommand — keeps `bagq` 100% offline). API-first / CLI↔GUI parity: the Phase-14 GUI Replay panel capability-gates over this same package API.
- **D-03** — `rclpy` (+ `rosbag2_py`/`rosidl_runtime_py` as needed) are ENVIRONMENT-provided, NOT uv-resolved. The package's only uv-resolved dependency is `rosbagger-core` + `typer`. ROS modules are lazy-imported inside functions so `import rosbagger_replay` succeeds in the ROS-free uv venv; `replay()` raises a teaching capability error when `rclpy` is absent.
- **D-04** — Publish path: raw CDR → `rclpy.serialization.deserialize_message(raw, msg_cls)` → typed `create_publisher(msg_cls, topic, qos).publish(msg)`, where `msg_cls = rosidl_runtime_py.utilities.get_message(msgtype_str)`. The v1 reader's deserialized `msg` is a rosbags object and is NOT directly republishable. One generic publisher per selected topic from its discovered type.
- **D-05** — Raw-CDR source (RESEARCH to confirm cleanest path): CONTEXT's recommended default is `rosbag2_py.SequentialReader`; research decides between that and a small raw-bytes seam added to the v1 reader. Either way the publish bytes must be raw CDR, not a rosbags-deserialized object. **[Research resolves this: use the v1 `rosbags` reader's raw bytes, NOT `rosbag2_py.SequentialReader` — see Finding 1 / Architecture Patterns.]**
- **D-06** — Split a PURE-PYTHON transport scheduler from the rclpy publish sink. A `Replayer`/`TransportScheduler` owns the state machine + clock math (play/pause/step/seek/rate/loop, inter-message timing) and is completely ROS-free — it consumes an ordered stream of `(t_ns, topic, msgtype, payload)` items + a clock and emits "publish item X now" decisions. The rclpy publish SINK is a thin injectable callback. Makes SC2/SC3 unit-testable WITHOUT ROS.
- **D-07** — All six controls live on the `Replayer` API (`play()`/`pause()`/`step()`/`seek(t)`/`set_rate(x)`/`loop` flag) so SC2 is provable programmatically. The CLI is a thin face over it.
- **D-08** — Wall-clock pacing via a MONOTONIC clock (the Phase-12 WR-02 lesson — never `time.time()`): sleep the inter-message `Δt_ns` between consecutive bag timestamps, divided by `--rate` (rate>1 = faster, <1 = slower). `--rate` scales the schedule (SC3).
- **D-09** — Control semantics: `pause` holds (stop publishing, keep position); `play` resumes; `step` publishes exactly the next message then re-pauses; `seek(t)` jumps the cursor to the first message at/after bag-relative time `t` (skips intervening messages without publishing) and lands at the expected message (SC3); `loop` restarts from the beginning at end-of-bag; end-without-loop stops cleanly. Seek/rate landing is asserted against expected message indices/timestamps.
- **D-10** — CLI surface: v1 exposes the non-interactive, scriptable subset — `--rate`, `--loop`, `--start`/`--seek` (offset seconds), optional `--topics` subset, optional `--duration`/`--end`. Interactive keyboard control is Claude's discretion / optional — the controls are fully exercised via the API in tests regardless.
- **D-11** — Two-tier testing. (1) ROS-free UNIT tests (uv venv / offline CI): the pure `Replayer`/scheduler — play/pause/step/seek/rate/loop transitions + monotonic timing math with a FAKE clock and a recording sink (no rclpy). This is where SC2 + SC3 *logic* is proven deterministically. Plus CLI parsing with the ROS bits mocked. (2) LIVE integration test (ROS-sourced lane): a real `rclpy` subscriber → `rosbagger-replay <fixture-bag> --rate <fast> [--duration/--max]` → assert the subscriber RECEIVES the expected messages on the expected topics (SC1), bounded/deterministic. Gated by `pytest.importorskip("rclpy")` + the `live` marker; SKIPPED in the offline CI; the orchestrator must actually RUN it (Phase-12 W4 lesson).
- **D-12** — Offline guarantee preserved. `rclpy`/`rosbag2_py` isolated to `rosbagger-replay`, lazy-imported; `import rosbagger_replay` clean in the ROS-free uv venv. Extend `tests/test_offline_guard.py` to assert `import rosbagger_replay` (and core/bagq) pull NO `rclpy`/`rosbag2_py`. Keep the new package OUT of the `--cov=rosbagger_core --cov=bagq` gate.

### Claude's Discretion

Exact module layout (mirror `rosbagger_record`: `__init__/cli/replay/errors` + a `transport`/`scheduler` module); CLI flag names; **the raw-CDR source choice** (rosbag2_py SequentialReader vs a v1-reader raw seam — research-led, RESOLVED below); default QoS profile; whether to ship an interactive keyboard mode. Hard constraints: offline `core`/`bagq` NEVER import rclpy; the pure transport scheduler MUST be ROS-free + unit-tested; the live test stays gated/skippable so offline CI stays green; SC1 proven by an actually-run live subscriber.

### Deferred Ideas (OUT OF SCOPE)

- **GUI Replay panel** — Phase 14 (capability-gated over this module's API; jump-points from the events sidecar live there too).
- **`/clock` + `use_sim_time`** simulated-clock publishing — v1 paces on wall-clock; sim-time fidelity is a later enhancement.
- **Topic remapping** (`--remap from:=to`) and **per-topic QoS profiles / QoS override** — v1 publishes on original topic names with a sane default QoS.
- **Interactive keyboard transport TUI** — optional/discretion; the API + non-interactive flags cover SC2 for v1.
- **Latched / transient-local replay semantics** beyond a sane default.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REP-01 | Replay a bag to ROS topics with transport controls (play/pause/step/seek/rate/loop) | Publish path VERIFIED end-to-end on this box: v1 `rosbags` `AnyReader` raw CDR → `deserialize_message(raw, get_message(type_str))` → `create_publisher(...).publish(msg)` → real subscriber receives (SC1). The six controls + monotonic timing live on a pure-Python `Replayer` over an ordered `(t_ns, topic, msgtype, payload)` stream with an injectable clock + sink (SC2/SC3, unit-testable offline). Seek = first msg ≥ t; rate scales the sleep; step = one-then-pause; loop = restart — all pure scheduler logic. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read bag → ordered raw-CDR stream | `rosbagger-core` v1 reader (OFFLINE, no rclpy) | `rosbagger-replay` thin raw-seam | The EXISTING `rosbags` `AnyReader` already yields `(connection, t_ns, rawdata)` time-ordered across formats. Reading is offline; only the publish is live. Reuse the v1 reader — do NOT add a `rosbag2_py` reader (it can't even open the fixtures — Finding 1). |
| Transport state machine (play/pause/step/seek/rate/loop) | `rosbagger-replay` `Replayer` (PURE Python) | — | D-06: the SC2/SC3 logic is ROS-free, consumes a clock + an ordered item stream, emits publish decisions. Unit-testable with a fake clock + recording sink. |
| Inter-message pacing (monotonic Δt ÷ rate) | `rosbagger-replay` `Replayer` (PURE Python) | — | D-08: `time.monotonic()` sleep of `Δt_ns / rate`. Pure arithmetic; tested with a fake clock. |
| ROS 1 → CDR bridge (when replaying a `.bag`) | `rosbagger-replay` (rosbags `serialize_cdr`) | `rosbagger-core` typestore | ROS 1 raw bytes are ROS 1 wire format, NOT CDR (Finding 3). Re-serialize via the reader's typestore before `deserialize_message`. Uses `rosbags` (already a core dep), not `rclpy`. |
| CDR → typed msg → publish (the SINK) | `rosbagger-replay` (live, rclpy) | — | D-04: the only ROS-runtime-bound work. `get_message` + `deserialize_message` + `create_publisher(...).publish()`. A thin injectable callback (D-06). |
| CLI presentation | `rosbagger-replay` CLI (thin) | — | API-first: the CLI parses flags and calls the package API; the Phase-14 GUI is the other thin face. |

## Standard Stack

### Core (environment-provided — NOT uv-resolved, D-03)

| Library | Version (verified on box) | Purpose | Why Standard |
|---------|--------------------------|---------|--------------|
| `rclpy` | 3.3.21 `[VERIFIED: /opt/ros/humble package.xml — Phase 12]` | Graph init, node, `create_publisher`, `rclpy.serialization.deserialize_message`/`serialize_message`, SIGINT-aware `ok()` | The official ROS 2 Python client; only way to publish to a live graph. |
| `rosidl_runtime_py` | (ships with Humble) `[VERIFIED: importable on box this session]` | `utilities.get_message(type_str)` → message **class** for `create_publisher` + `deserialize_message` | Resolves a discovered type string into the class the publish path needs. |

> NOTE: unlike Phase 12, `rosbag2_py` is **NOT recommended** for the read side (Finding 1). It is still importable on the box, but the replay read path uses the offline `rosbags` reader. If a future need arises, `rosbag2_py.SequentialReader` exposes `open`/`has_next`/`read_next`/`seek`/`get_all_topics_and_types`/`set_filter` `[VERIFIED: dir() on box]` — but it cannot parse the project's `rosbags`-written fixtures.

### Supporting (uv-resolved)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `rosbagger-core` | 0.1.0 (workspace) | The v1 `RosbagsReader`/`AnyReader` (the raw-CDR + metadata source) + the typestore (ROS 1→CDR bridge) + the `errors.py` teaching pattern | Always — the package's primary uv-resolved dependency (D-03). |
| `rosbags` | >=0.11,<0.12 (transitive via core) | `AnyReader.messages()` (raw CDR) + `typestore.serialize_cdr` (ROS 1 bridge) + `reader.deserialize` | The read side. Already used by `RosbagsReader`; also present in **system** python3 for the live lane. |
| `typer`/`click` | >=0.15,<1 (mirror record/bagq) | Thin `rosbagger-replay` CLI + console script | The CLI face (D-02). Mirror `rosbagger-record`'s `[project.scripts]`. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| v1 `rosbags` `AnyReader` raw bytes (recommended) | `rosbag2_py.SequentialReader` (CONTEXT's stated default) | **DOES NOT WORK on the fixtures** — `rosbag2_py` rejects the `rosbags`-written `metadata.yaml` (`offered_qos_profiles: []` → "bad conversion", Finding 1). Even if it worked, it adds a second reader stack, only reads ROS 2 (not ROS 1), and duplicates format detection the v1 reader already owns. **Use the v1 reader.** |
| One generic publisher per topic from discovered type (D-04) | Deserialize-then-publish-typed-object | The rosbags object is NOT republishable (`_TYPE_SUPPORT` missing — VERIFIED). Must go through raw CDR → `deserialize_message`. **Use D-04 exactly.** |
| Pure-Python `Replayer` + injectable sink (D-06) | rclpy timer-driven publishing inside the node | A timer-driven design buries the SC2/SC3 control logic inside the ROS layer where it can't be unit-tested offline. D-06's split is the architectural payoff. **Keep the scheduler pure.** |
| Default QoS depth-10 VOLATILE/RELIABLE | Per-topic QoS replay from `conn.ext.offered_qos_profiles` | The original QoS is available on `conn.ext.offered_qos_profiles` but per-topic QoS override is DEFERRED (CONTEXT). A sane default (depth 10, RELIABLE, VOLATILE) is received by a normally-subscribed node (VERIFIED). **Use the default; note the latching caveat.** |

**Installation (the new package's `pyproject.toml` — env deps NOT declared; mirror `rosbagger-record`):**
```toml
# packages/rosbagger-replay/pyproject.toml
[project]
name = "rosbagger-replay"
version = "0.1.0"
requires-python = ">=3.10"
# ONLY rosbagger-core (the v1 reader + typestore, resolved via the root
# [tool.uv.sources] workspace source) and typer are uv-resolved. NOTHING ROS
# goes here (D-03): rclpy / rosidl_runtime_py are environment-provided by the
# sourced ROS 2 distro and lazy-imported inside function bodies.
dependencies = ["rosbagger-core", "typer>=0.15,<1"]

[project.scripts]
rosbagger-replay = "rosbagger_replay.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
The root `[tool.uv.workspace] members = ["packages/*"]` already globs the new package in; `[tool.uv.sources] rosbagger-core = { workspace = true }` already wires the intra-workspace dep `[VERIFIED: root pyproject.toml]`. Adding a package whose only external dep is the already-locked `typer` keeps `uv sync` clean (the identical change Phase 12 made for `rosbagger-record`).

**Version verification:**
```bash
# (ROS sourced) — confirmed present and importable THIS session
python3 -c "import rclpy, rosidl_runtime_py; from rclpy.serialization import deserialize_message"   # OK
# (uv venv, offline) — rclpy absent by design (Phase 12 verified)
PYTHONPATH="" uv run python -c "import rclpy"   # ModuleNotFoundError (correct)
```

## Package Legitimacy Audit

> The new package declares only `rosbagger-core` (workspace, already vetted) and `typer` (already a vetted `bagq`/`rosbagger-record` dependency). `rclpy`/`rosidl_runtime_py` are environment-provided ROS distro packages, not registry installs — slopcheck/PyPI auditing does not apply (they ship with `/opt/ros/humble`, verified on disk this session). No new third-party PyPI package is introduced.

| Package | Registry | Source | slopcheck | Disposition |
|---------|----------|--------|-----------|-------------|
| `rosbagger-core` | workspace (local) | this repo | n/a (local) | Approved (existing) |
| `typer` | PyPI | already a `bagq`/`record` dep (`typer>=0.15,<1`) | n/a (pre-vetted) | Approved (existing) |
| `rclpy` | ROS distro (`/opt/ros/humble`) | apt `ros-humble-rclpy` | n/a (env-provided, on disk) | Environment dependency — not pyproject-declared |
| `rosidl_runtime_py` | ROS distro (`/opt/ros/humble`) | apt `ros-humble-rosidl-runtime-py` | n/a (env-provided, on disk) | Environment dependency — not pyproject-declared |

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. No new PyPI install is added by this phase; slopcheck was not run because no new registry package is introduced.

## Architecture Patterns

### System Architecture Diagram

```
   ┌──────────────────────────────────────────────────────────────┐
   │  OFFLINE read side  —  rosbagger-core v1 reader (no rclpy)     │
   │                                                                │
   │  RosbagsReader / AnyReader.messages()                          │
   │     ──► ordered (connection, t_ns, rawdata: bytes)            │
   │            │  (time-ordered across all bags; lazy)            │
   │            ▼  per message:                                     │
   │   ROS 2 bag?  rawdata IS CDR ───────────────────┐  (verified) │
   │   ROS 1 bag?  rawdata is ROS1 wire ─► reader.deserialize       │
   │               ─► typestore.serialize_cdr ─► CDR ─┤  (bridge)   │
   │            ▼                                      ▼            │
   │   item = (t_ns, topic, msgtype, cdr_bytes)   (ordered stream)  │
   └───────────────────────────┬──────────────────────────────────┘
                                │  ordered list/iterator of items
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  PURE-PYTHON Replayer / scheduler  (ROS-FREE, unit-testable)   │
   │                                            (D-06/D-07/D-08/D-09)│
   │  state: PLAYING | PAUSED | STEPPING | DONE                     │
   │  cursor: index into the ordered item list                     │
   │  rate: float (×speed)   loop: bool                             │
   │  clock: injectable (time.monotonic in prod / fake in tests)    │
   │  sink:  injectable callback publish(item) (rclpy in prod /     │
   │         recording list in tests)                               │
   │                                                                │
   │  run():  while not DONE:                                       │
   │    if PAUSED: wait/return control                              │
   │    item = items[cursor]                                        │
   │    Δt = (item.t_ns - prev.t_ns) / rate   ──► sleep on clock    │
   │    sink(item)            # "publish now"                       │
   │    cursor += 1                                                 │
   │    if STEPPING: -> PAUSED  (step = one-then-pause, D-09)       │
   │    if cursor == len: loop? cursor=0 : DONE   (D-09)            │
   │  seek(t): cursor = first i where items[i].t_ns >= t0 + t (D-09)│
   │  set_rate(x), play(), pause(), step()  -> mutate state         │
   └───────────────────────────┬──────────────────────────────────┘
                  sink(item)    │  (the ONLY ROS-bound surface)
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  LIVE publish SINK  (rosbagger-replay, rclpy)        (D-04)    │
   │  per topic (once): msg_cls = get_message(item.msgtype)        │
   │                    pub = node.create_publisher(msg_cls, topic, │
   │                                                  qos=10)       │
   │  per item: msg = deserialize_message(item.cdr, msg_cls)       │
   │            pub.publish(msg)                                    │
   └───────────────────────────┬──────────────────────────────────┘
                                │  DDS
                                ▼
              external subscriber (rviz / Foxglove / the live test)
                       RECEIVES the published topics (SC1)
```

### Recommended Project Structure (mirror `rosbagger_record`)
```
packages/rosbagger-replay/
├── pyproject.toml                 # only deps = rosbagger-core + typer; console script
└── src/rosbagger_replay/
    ├── __init__.py                # lazy _require_ros(); re-export public API + submodule-shadow aliases. NO top-level rclpy import.
    ├── source.py                  # load_items(bag_paths, *, topics=None, default_typestore=None) -> list[ReplayItem]; the v1-reader raw-CDR seam + ROS1→CDR bridge (PURE: rosbags only, no rclpy)
    ├── scheduler.py               # Replayer/TransportScheduler — the pure state machine + monotonic pacing (D-06..D-09). ROS-FREE.
    ├── replay.py                  # replay(...) — the rclpy publish SINK + wiring (the ONLY rclpy module)
    ├── errors.py                  # RosNotAvailableError, NoMessagesToReplayError (teaching capability errors; stdlib-only)
    └── cli.py                     # thin typer app: replay verb (D-02/D-10) + @_capability_errors
tests/
├── test_replay_unit.py           # ROS-FREE unit tests: the pure Replayer (play/pause/step/seek/rate/loop + timing) with a fake clock + recording sink (SC2/SC3 logic); CLI parsing mocked; source.py over fixture bags
└── test_replay_live.py           # LIVE: importorskip("rclpy") + `live` marker — real subscriber receives published topics (SC1)
```

### Pattern 1: Lazy ROS import behind the package boundary (D-03/D-12) — mirror Phase 12, VERIFIED pattern
**What:** The package top level imports cleanly without ROS; `rclpy`/`rosidl_runtime_py` are imported *inside* functions; a `_require_ros()` guard converts a missing ROS env into a teaching error.
```python
# src/rosbagger_replay/__init__.py — mirrors rosbagger_record/__init__.py exactly
from __future__ import annotations
from .errors import RosNotAvailableError
from .source import load_items          # PURE (rosbags only) — safe at top level
from .scheduler import Replayer         # PURE — safe at top level

def _require_ros() -> None:
    try:
        import rclpy  # noqa: F401
    except ImportError as exc:
        raise RosNotAvailableError() from exc

def replay(*args, **kwargs):
    _require_ros()                       # lazy — only fails when CALLED (D-12)
    from .replay import replay as _replay
    return _replay(*args, **kwargs)

# Submodule-shadow-proof alias (Phase 12 lesson — `replay.py` submodule shadows the
# `replay` function attribute after `import rosbagger_replay.replay`):
replay_bag = replay
```
> NOTE the Phase-12 footgun (12-REVIEW IN-01 + the `record_topics`/`list_record_topics` aliases): name the impl module something OTHER than the public function, OR provide a shadow-proof alias (`replay_bag`) that the CLI imports. Recommend naming the impl module `replay.py` and exporting `replay_bag` alias (matching the `record`/`record_topics` precedent).

### Pattern 2: The raw-CDR source seam (D-05 — RESOLVED) — VERIFIED end-to-end
**What:** Read the bag through the v1 `rosbags` reader and yield `(t_ns, topic, msgtype, cdr_bytes)` items. For ROS 2 bags `rawdata` is already CDR; for ROS 1 bags, bridge via the typestore. PURE — imports `rosbags` only, never `rclpy`.
```python
# src/rosbagger_replay/source.py — VERIFIED on box (ROS 2 sqlite3 fixture round-trip)
# Source: executed against ROS 2 Humble this session; rosbags AnyReader.messages()
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ReplayItem:
    t_ns: int
    topic: str
    msgtype: str
    cdr: bytes

def load_items(bag_paths, *, topics=None, default_typestore=None) -> list[ReplayItem]:
    from rosbags.highlevel import AnyReader
    items: list[ReplayItem] = []
    reader = AnyReader(_as_path_list(bag_paths), default_typestore=default_typestore)
    reader.open()
    try:
        # connection-level filter (reuse the v1 reader's QURY-05 pattern) if topics given
        conns = reader.connections
        if topics is not None:
            conns = [c for c in conns if c.topic in topics]
            if not conns:
                return []
        for conn, t_ns, rawdata in reader.messages(connections=conns):
            ext = getattr(conn, "ext", None)
            is_ros1 = type(ext).__name__ == "ConnectionExtRosbag1"
            if is_ros1:
                # ROS 1 raw bytes are ROS 1 wire format, NOT CDR (Finding 3) — bridge:
                obj = reader.deserialize(rawdata, conn.msgtype)
                cdr = bytes(reader.typestore.serialize_cdr(obj, conn.msgtype))
            else:
                cdr = bytes(rawdata)          # ROS 2: rawdata IS CDR (VERIFIED)
            items.append(ReplayItem(t_ns, conn.topic, conn.msgtype, cdr))
    finally:
        reader.close()
    return items   # AnyReader.messages() is already time-ordered across bags
```
Notes (verified this session):
- ROS 2 sqlite3 fixture: `rawdata` is 52-byte CDR for `/cmd_vel`; fed straight to `deserialize_message` → correct payload.
- MCAP fixture: `AnyReader([mcap]).messages()` yields CDR with NO `default_typestore` needed (self-describing).
- ROS 1 fixture: `rawdata` is 320 bytes (ROS 1 wire); `deserialize → serialize_cdr` → 332-byte CDR → `deserialize_message` OK.
- For very large bags, prefer streaming (a generator) over a materialized `list` — but a list is fine for the bounded fixtures and makes `seek`/index-landing (D-09 SC3) trivial. Recommend: load to a list for v1 (fixtures are tiny); document the streaming option.

### Pattern 3: The pure transport scheduler (D-06..D-09) — the SC2/SC3 unit-test target
**What:** A ROS-free state machine over the ordered item list, with an injectable clock and sink. This is where play/pause/step/seek/rate/loop + monotonic pacing live and are unit-tested deterministically.
```python
# src/rosbagger_replay/scheduler.py — PURE (no rclpy); unit-tested with a fake clock + recording sink
from __future__ import annotations
import time
from enum import Enum
from collections.abc import Callable

class State(Enum):
    PLAYING = "playing"; PAUSED = "paused"; STEPPING = "stepping"; DONE = "done"

class Replayer:
    def __init__(self, items, sink: Callable[[object], None], *,
                 clock=time.monotonic, sleep=time.sleep, rate: float = 1.0,
                 loop: bool = False, start: int = 0):
        self._items = items            # list[ReplayItem], time-ordered
        self._sink = sink              # publish(item) — injectable (rclpy in prod, list.append in tests)
        self._clock = clock            # injectable monotonic clock (D-08; fake in tests)
        self._sleep = sleep            # injectable sleep (no-op/recording in tests)
        self._rate = rate
        self.loop = loop
        self._cursor = start
        self._state = State.PAUSED

    # --- the six controls (D-07) ---
    def play(self):  self._state = State.PLAYING
    def pause(self): self._state = State.PAUSED
    def step(self):  self._state = State.STEPPING          # publish exactly one, then pause (D-09)
    def set_rate(self, x: float):
        if x <= 0: raise ValueError("rate must be > 0")
        self._rate = x
    def seek(self, t_offset_ns: int):
        # jump cursor to the first message at/after bag-relative time t (D-09) — skip, don't publish
        t0 = self._items[0].t_ns if self._items else 0
        target = t0 + t_offset_ns
        self._cursor = next((i for i, it in enumerate(self._items) if it.t_ns >= target),
                            len(self._items))

    def _publish_current(self):
        self._sink(self._items[self._cursor])
        self._cursor += 1

    def run(self):
        """Drive the schedule to completion (or until paused, for the API-driven tests)."""
        while self._state in (State.PLAYING, State.STEPPING) and self._cursor < len(self._items):
            if self._cursor > 0:
                dt_ns = self._items[self._cursor].t_ns - self._items[self._cursor - 1].t_ns
                self._sleep(max(0.0, dt_ns / 1e9 / self._rate))    # monotonic pacing / rate (D-08)
            stepping = self._state is State.STEPPING
            self._publish_current()
            if stepping:
                self._state = State.PAUSED                          # step = one-then-pause (D-09)
                return
            if self._cursor >= len(self._items):
                if self.loop:
                    self._cursor = 0                                # loop restart (D-09)
                else:
                    self._state = State.DONE                        # clean end (D-09)
```
> Test seam (D-11 tier 1): inject `clock`/`sleep` fakes + a `sink=collected.append`. Assert: `step()` publishes exactly one then PAUSED; `seek(t)` lands `_cursor` on the first item ≥ t (SC3); `set_rate(2.0)` halves the slept Δt (SC3 — assert the recorded sleep arguments); `loop=True` restarts; `pause()` mid-run holds the cursor; end-without-loop reaches DONE. NONE of this needs ROS.

### Pattern 4: The live publish SINK (D-04) — VERIFIED end-to-end on box
**What:** The thin rclpy callback. Per topic (once) create a generic publisher; per item deserialize the CDR to a typed message and publish.
```python
# src/rosbagger_replay/replay.py — the ONLY rclpy module. Source: executed end-to-end on box.
from __future__ import annotations

def replay(bag_paths, *, topics=None, rate=1.0, loop=False, start=0.0,
           duration=None, max_messages=None, default_typestore=None) -> int:
    _require_ros_done_by_frontdoor = None   # front door (__init__.replay) already called _require_ros()
    import rclpy
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    from .source import load_items
    from .scheduler import Replayer
    from .errors import NoMessagesToReplayError

    items = load_items(bag_paths, topics=topics, default_typestore=default_typestore)
    if not items:
        raise NoMessagesToReplayError(bag_paths=bag_paths, topics=topics)

    rclpy.init()
    node = None
    published = {"n": 0}
    try:
        node = rclpy.create_node("rosbagger_replayer")
        pubs: dict[str, tuple] = {}        # topic -> (msg_cls, publisher)
        def sink(item) -> None:
            if item.topic not in pubs:
                cls = get_message(item.msgtype)                 # VERIFIED resolver
                pubs[item.topic] = (cls, node.create_publisher(cls, item.topic, 10))
            cls, pub = pubs[item.topic]
            msg = deserialize_message(item.cdr, cls)            # raw CDR -> typed (VERIFIED)
            pub.publish(msg)                                    # subscriber receives (VERIFIED)
            published["n"] += 1
        # seek to --start offset before playing (D-09/D-10)
        replayer = Replayer(items, sink, rate=rate, loop=loop)
        if start:
            replayer.seek(int(start * 1e9))
        replayer.play()
        replayer.run()                      # bounded variants: see "duration/max" note below
        return published["n"]
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
```
> Bounded-stop for the live test (D-10/D-11): `--max-messages`/`--duration` make the live run deterministic (mirror Phase 12's WR-01/WR-02 lessons). Implement the bound INSIDE the scheduler loop (a monotonic deadline + a published counter) using the `is not None` guard (NOT truthiness — WR-01) and `time.monotonic()` (NOT wall clock — WR-02). For SC1 the live test can simply replay the whole tiny fixture (9 msgs) at a fast `--rate`; a `--max-messages` cap is the belt-and-suspenders against an accidental `--loop`.

### Anti-Patterns to Avoid
- **Using `rosbag2_py.SequentialReader` for the read side** — it CANNOT open the project's `rosbags`-written fixtures on Humble (Finding 1: `metadata.yaml` "bad conversion"). Use the v1 `rosbags` reader.
- **Publishing `Message.msg` (the rosbags object) directly** — it has no `_TYPE_SUPPORT`; `rclpy` rejects it (VERIFIED). Go through raw CDR → `deserialize_message` (D-04).
- **Feeding ROS 1 raw bytes to `deserialize_message`** — they are ROS 1 wire format, not CDR (Finding 3). Bridge via `reader.deserialize` → `typestore.serialize_cdr`.
- **`time.time()` for pacing/deadlines** — Phase-12 WR-02: a clock step breaks the schedule. Use `time.monotonic()` (D-08).
- **`if duration:` truthiness for the bounded stop** — Phase-12 WR-01: `--duration 0` silently becomes unbounded. Use `if duration is not None`.
- **Putting transport logic inside the rclpy node/timer** — defeats D-06's testability payoff. Keep the scheduler pure.
- **Importing `rclpy`/`rosidl_runtime_py` at module top in `rosbagger_replay`** — breaks the offline-import promise; `import rosbagger_replay` must succeed in the ROS-free venv. Lazy-import inside functions (Phase 12 verified pattern).
- **Declaring `rclpy` in `pyproject.toml`** — `uv` will try to resolve a nonexistent PyPI wheel. Environment-provided (D-03).
- **Empty selection / empty bag → raw traceback** — Phase-12 WR-04: raise a typed `NoMessagesToReplayError` caught by `@_capability_errors` for a clean teaching line.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bag read + format detection + time-ordering | A new `rosbag2_py` reader path | The EXISTING `rosbagger_core` v1 reader (`AnyReader`) | It already reads ROS1/ROS2/MCAP uniformly, merge-sorts by timestamp, and yields raw CDR — and `rosbag2_py` can't even open the fixtures (Finding 1). |
| Type string → message class | Manual `importlib` of `pkg.msg._type` | `rosidl_runtime_py.utilities.get_message(type_str)` | Verified resolver; handles the package/`msg`/CamelCase mapping. |
| CDR → typed ROS message | A custom CDR decoder | `rclpy.serialization.deserialize_message(raw, cls)` | The ROS-native deserializer; round-trips the bag's CDR (VERIFIED). |
| ROS 1 wire → CDR conversion | A hand-rolled transcoder | `reader.deserialize` + `typestore.serialize_cdr` (rosbags) | rosbags owns both wire formats and the typestore; verified bridge. (Same factory Phase 11's `convert` used.) |
| SIGINT handling | A custom `signal.signal` | `rclpy.init()` + `rclpy.ok()` loop (if the run loop spins ROS) | rclpy installs its own SIGINT handler (Phase 12 verified). For a pure-scheduler-driven replay, a `KeyboardInterrupt` try/except + `finally` shutdown suffices. |
| Monotonic pacing | A busy-wait | `time.monotonic()` + `time.sleep(Δt/rate)` (injectable) | `time.sleep` granularity is ~1ms here (VERIFIED: 1ms sleep → 1.06ms), adequate for replay pacing; busy-wait wastes CPU. |

**Key insight:** Almost the entire replayer is (a) the EXISTING v1 reader for the source, (b) a pure-Python state machine you fully control and unit-test, and (c) three ROS-native primitives (`get_message`, `deserialize_message`, `create_publisher().publish()`) for the sink. The only genuinely new live code is the ~15-line sink + the lazy-import boundary. The scheduler is the bulk of the new logic and is 100% offline-testable.

## Runtime State Inventory

> Not a rename/refactor/migration phase — this is a greenfield package addition (mirrors Phase 12). No stored data, live-service config, OS-registered state, secrets, or pre-existing build artifacts are mutated.
>
> - **Stored data:** None — replay READS existing bags; it writes nothing. (Verified: the source path is read-only `AnyReader`.)
> - **Live service config:** None — no external service config is touched. Replay publishes to the ambient DDS graph but registers no persistent config.
> - **OS-registered state:** None.
> - **Secrets/env vars:** None new. The phase *depends on* the ambient `ROS_DISTRO`/`AMENT_PREFIX_PATH`/`PYTHONPATH` set by `source /opt/ros/humble/setup.bash`, but introduces no secret of its own.
> - **Build artifacts:** A new `uv` workspace member is added; `uv.lock` gains the `rosbagger-replay` workspace entry (its only external dep is the already-locked `typer`). The `rosbagger-replay` console script installs into `.venv/bin/` on `uv sync` (verified pattern for `bagq`/`rosbagger-record`).

## Common Pitfalls

### Pitfall 1: `rosbag2_py.SequentialReader` rejects the project's fixture bags (the read-source trap)
**What goes wrong:** `reader.open(StorageOptions(uri=bag, storage_id="sqlite3"), ConverterOptions(...))` raises `RuntimeError: Exception on parsing info file: yaml-cpp: error at line 25, column 29: bad conversion`.
**Why it happens:** `rosbags`-written `metadata.yaml` emits `offered_qos_profiles: []` (empty YAML *sequence*); Humble's `rosbag2_py` parser expects that field to be a *string* scalar (`VERIFIED on box this session`). The two reader stacks disagree on the metadata schema — the same reason Phase 12 recorded via `rosbag2_py` but re-opened via `rosbags`.
**How to avoid:** Use the v1 `rosbags` `AnyReader` for the read side (Pattern 2). It reads the fixtures cleanly and yields raw CDR. Do NOT use `rosbag2_py.SequentialReader` for replay.
**Warning signs:** `yaml-cpp: ... bad conversion` at `reader.open()`.

### Pitfall 2: ROS 1 bag raw bytes are NOT CDR
**What goes wrong:** Feeding a ROS 1 bag's `rawdata` to `rclpy.serialization.deserialize_message` produces garbage or raises — the message is malformed.
**Why it happens:** `AnyReader.messages()` returns the storage-native raw bytes. For a ROS 1 `.bag` these are ROS 1 wire format (`VERIFIED: 320 bytes for /imu` vs the 332-byte CDR), which lacks the 4-byte CDR encapsulation header and uses a different field layout.
**How to avoid:** Detect ROS 1 connections (`type(conn.ext).__name__ == "ConnectionExtRosbag1"`) and bridge: `reader.deserialize(rawdata, msgtype)` → `reader.typestore.serialize_cdr(obj, msgtype)` (`VERIFIED round-trip → deserialize_message OK`). For ROS 2 bags, pass `rawdata` straight through.
**Warning signs:** A subscriber receives messages but the fields are wrong/corrupt; `deserialize_message` raises on ROS 1 input.

### Pitfall 3: A rosbags-deserialized object is not republishable (the D-04 reason)
**What goes wrong:** Trying to `publisher.publish(message.msg)` (the v1 reader's `.msg`) or `serialize_message(message.msg)` raises `AttributeError: type object 'type' has no attribute '_TYPE_SUPPORT'`.
**Why it happens:** `Message.msg` is a `rosbags.usertypes.*` object, NOT an `rclpy`/`rosidl` message class — it has no ROS type-support (`VERIFIED on box`).
**How to avoid:** Never publish from `Message.msg`. Publish from raw CDR: `deserialize_message(cdr, get_message(msgtype))` → `publish` (D-04, VERIFIED end-to-end).
**Warning signs:** `_TYPE_SUPPORT` AttributeError; "This might be a ROS 1 message" hint in the error.

### Pitfall 4: QoS mismatch — a subscriber misses messages
**What goes wrong:** A subscriber doesn't receive published messages, or only receives some.
**Why it happens:** Publisher/subscriber QoS incompatibility (e.g. publishing BEST_EFFORT to a RELIABLE subscriber, or a late-joining subscriber on a VOLATILE topic missing already-published messages).
**How to avoid:** Use a sane default QoS — depth 10, RELIABLE, VOLATILE (the integer `10` shorthand in `create_publisher(cls, topic, 10)` gives exactly this; `VERIFIED: a default subscriber received all messages`). For the live test, start the subscriber BEFORE replaying and add a brief discovery settle (`~0.5s`, VERIFIED) so the publisher↔subscriber match completes before the first publish. Per-topic QoS replay (`conn.ext.offered_qos_profiles` is available) and TRANSIENT_LOCAL/latching are DEFERRED (CONTEXT) — document the latching caveat: a topic originally latched (e.g. `/tf_static`, `/map`) replayed VOLATILE won't be seen by a subscriber that joins after the publish.
**Warning signs:** Live test flaky/zero received; works only when subscriber starts first.

### Pitfall 5: Timing — busy-wait vs sleep, and rate=0
**What goes wrong:** CPU spins at 100% during replay, or `--rate 0` divides by zero.
**Why it happens:** Polling the clock in a tight loop instead of sleeping; not validating `rate > 0`.
**How to avoid:** `time.sleep(Δt_ns / 1e9 / rate)` (sleep granularity ~1ms here, VERIFIED — adequate). Validate `set_rate(x)`/`--rate` with `x > 0` (raise `ValueError`). The injectable `sleep` makes this a no-op in unit tests so SC2/SC3 run instantly.
**Warning signs:** High CPU during replay; `ZeroDivisionError` on `--rate 0`.

### Pitfall 6: End-of-bag + loop edge; seek-past-end; empty selection
**What goes wrong:** Off-by-one at the last message; `seek` past the end crashes; an empty `--topics` selection or empty bag produces an opaque error.
**Why it happens:** Boundary handling in the cursor logic.
**How to avoid:** `seek` lands `_cursor = len(items)` when no message is ≥ t (clean DONE, not a crash — Pattern 3). `loop` resets `_cursor = 0` only at true end-of-stream. Empty selection/empty bag → raise the typed `NoMessagesToReplayError` BEFORE `rclpy.init()` (Phase-12 WR-04 lesson — clean teaching line, not a traceback). Unit-test each boundary with the fake clock.
**Warning signs:** `IndexError` at end-of-bag; replay hangs on an empty bag; raw traceback for a mistyped topic.

### Pitfall 7: Offline guard regression (the headline invariant)
**What goes wrong:** A stray top-level `rclpy`/`rosidl_runtime_py` import sneaks into `rosbagger_replay` (or `source.py`/`scheduler.py` import `rclpy`).
**Why it happens:** Convenience top-level imports; putting the sink in the same module as the scheduler.
**How to avoid:** Keep `rclpy`/`rosidl_runtime_py` imports inside `replay.py` function bodies only; `source.py` imports `rosbags` (allowed — it pulls no ROS, like `rosbags_reader.py`); `scheduler.py`/`errors.py` are stdlib-only. **Extend `tests/test_offline_guard.py`** (D-12): add `test_import_replay_does_not_pull_ros` (fresh `PYTHONPATH=""` subprocess asserts `import rosbagger_replay` leaks no `rclpy`/`rosbag2_py`), mirroring the existing `test_import_record_does_not_pull_ros` verbatim.
**Warning signs:** `test_import_replay_does_not_pull_ros` fails; `import rosbagger_replay` pulls ROS in a fresh interpreter.

## Code Examples

### SC1 end-to-end (executed on box this session — the verified proof)
```python
# Source: RUN on box — ROS 2 sqlite3 fixture -> raw CDR -> deserialize_message -> publish -> subscriber received 3/3 /imu msgs (lin_acc_z == 9.8)
from rosbags.highlevel import AnyReader
from rosbags.typesys import get_typestore, Stores
import rclpy
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

ts = get_typestore(Stores.ROS2_HUMBLE)            # only needed if the bag lacks embedded defs
items = []
with AnyReader([bag], default_typestore=ts) as r:
    for conn, t_ns, rawdata in r.messages():
        items.append((conn.topic, conn.msgtype, t_ns, bytes(rawdata)))

rclpy.init()
node = rclpy.create_node("replay_probe")
pubs = {}
for topic, mt, t_ns, raw in items:
    pubs.setdefault(topic, node.create_publisher(get_message(mt), topic, 10))
for topic, mt, t_ns, raw in items:
    pub = pubs[topic]
    pub.publish(deserialize_message(raw, get_message(mt)))   # VERIFIED received
```

### Live integration test skeleton (D-11 tier 2) — mirror Phase 12's recipe inverted
```python
# tests/test_replay_live.py — VERIFIED primitives; mirrors tests/test_record_live.py inverted.
import pytest
rclpy = pytest.importorskip("rclpy")              # skip in offline CI / ROS-free venv
pytestmark = pytest.mark.live

# (belt-and-suspenders src-tree path insert, like test_record_live.py)
# A real subscriber node spins in the test; rosbagger-replay publishes the fixture; assert received.
def test_sc1_replay_publishes_to_subscriber(tmp_path):
    from tools.make_fixtures import write_ros2_sqlite_bag
    from rosbags.typesys import get_typestore, Stores
    from std_msgs.msg import String  # or the fixture's real types via get_message
    bag = write_ros2_sqlite_bag(tmp_path)
    received = {"imu": 0}
    rclpy.init()
    sub_node = rclpy.create_node("replay_live_sub")
    from rosidl_runtime_py.utilities import get_message
    sub_node.create_subscription(get_message("sensor_msgs/msg/Imu"), "/imu",
                                 lambda m: received.__setitem__("imu", received["imu"] + 1), 10)
    # ... spin sub_node in a thread, then call rosbagger_replay.replay_bag(bag, rate=50,
    #     default_typestore=get_typestore(Stores.ROS2_HUMBLE)) ...
    # assert received["imu"] == 3  (the fixture has 3 /imu messages)
    rclpy.shutdown()
```
> Two-process caveat (Phase-12 lesson): `replay()` owns `rclpy.init()`/`shutdown()`, which can't run twice in one context. Either (a) run the subscriber in a SEPARATE process (like Phase 12's external publisher) and have replay `init`/`shutdown` in-process, or (b) have the test own the single `rclpy` context and inject the node/publishers into the sink (cleaner — the D-06 sink injection makes this natural). Recommend (b) for replay: pass a sink that uses a test-owned node, so the test fully controls one `rclpy` context and avoids the double-init clash.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `rosbag2_py` for both record AND replay read | `rosbag2_py` for record; `rosbags` `AnyReader` for replay read | This phase (Finding 1) | `rosbag2_py` can't parse `rosbags`-written bags on Humble; the offline reader is the portable, format-agnostic source. |
| Publish a deserialized message object | Publish from raw CDR via `deserialize_message` | rclpy current | A generic replayer needs no per-type Python codec and no rosbags↔rclpy class bridge (D-04). |
| Wall-clock pacing | Monotonic-clock pacing | Phase-12 WR-02 | Clock steps don't break the replay schedule (D-08). |

**Deprecated/outdated:**
- The CONTEXT's stated "recommended default" of `rosbag2_py.SequentialReader` for the read side — superseded by the v1 `rosbags` reader (Finding 1). D-05 explicitly left this to research; this is the research resolution.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A default QoS of depth-10 RELIABLE VOLATILE is received by a normally-subscribed node for the live test. | Pitfall 4, Standard Stack | LOW — VERIFIED end-to-end on box (subscriber received all 3 /imu). The only un-exercised case is latched/TRANSIENT_LOCAL topics for late subscribers, which is explicitly DEFERRED. |
| A2 | Loading the bag into a materialized `list[ReplayItem]` is acceptable for v1 (fixtures are tiny; makes seek/index-landing trivial). | Pattern 2 | LOW — true for the fixtures and the SC tests. For a multi-GB real bag a streaming source would be needed, but that is a v2 concern (and seek would then re-read). Flagged so the planner can note "list for v1; streaming deferred." |
| A3 | The ROS1→CDR bridge (`reader.deserialize` → `serialize_cdr`) is correct for all fixture message types, not just `/imu`. | Pattern 2, Pitfall 2 | LOW–MEDIUM — VERIFIED for `/imu` (headered) this session; the same `serialize_cdr` factory round-trips `/cmd_vel`/`/image` in Phase 11's convert tests. Header.seq (ROS1-only field) is dropped by the typestore conversion, which is correct for CDR. |
| A4 | The live test can own a single `rclpy` context and inject a test-node sink, avoiding the double-`rclpy.init()` clash. | Code Examples (live test) | LOW — the D-06 sink injection is designed exactly for this; if `replay()` insists on owning `rclpy.init()`, fall back to the Phase-12 separate-process pattern (also proven). |

## Open Questions (RESOLVED)

1. **Materialized list vs streaming source for large bags.**
   - What we know: a `list[ReplayItem]` is trivial and correct for the fixtures (VERIFIED) and makes `seek`/index-landing (SC3) O(1) lookups.
   - What's unclear: whether a real multi-GB bag should stream (and how `seek` would then work — re-open + skip).
   - Recommendation: ship the list for v1 (fixtures + SC tests are tiny); document streaming + re-seek as a deferred enhancement. Does not block REP-01.

2. **Latched/TRANSIENT_LOCAL topics (e.g. `/tf_static`, `/map`).**
   - What we know: replayed VOLATILE, a subscriber that joins AFTER the publish won't see them; per-topic QoS replay is DEFERRED (CONTEXT).
   - What's unclear: whether the live test should touch a latched topic (the fixtures' `/tf_static` is in the separate `write_tf_bag` fixture, not the default three-topic bag).
   - Recommendation: use the default three-topic fixture (`/cmd_vel`, `/imu`, `/image` — none latched) for the SC1 live test; note the latching caveat in the CLI help and defer TRANSIENT_LOCAL handling.

3. **Whether `--start` is a pure scheduler `seek` or a reader-level skip.**
   - What we know: `seek(t)` on the materialized list is O(n) scan to the first item ≥ t (Pattern 3, trivial).
   - What's unclear: nothing blocking — `--start` maps cleanly to `replayer.seek(int(start*1e9))` before `play()`.
   - Recommendation: implement `--start`/`--seek` as `Replayer.seek()`; SC3 asserts the cursor lands on the expected index/timestamp.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ROS 2 Humble (`/opt/ros/humble`) | the whole live module | ✓ | Humble | — |
| `rclpy` (sourced env) | publish, graph init, SIGINT | ✓ | 3.3.21 | none (capability error if unsourced) |
| `rclpy.serialization.deserialize_message` | CDR → typed msg (D-04) | ✓ | (Humble) | none |
| `rosidl_runtime_py.utilities.get_message` | type str → class (D-04) | ✓ | (Humble) | none |
| `rosbags` `AnyReader` (read side) | the raw-CDR source (D-05) | ✓ (uv venv + system python3) | >=0.11,<0.12 | none — this IS the source |
| `rosbag2_py` reader | (CONTEXT's stated default — NOT used) | ✓ present but **rejects fixtures** | 0.15.16 | the `rosbags` reader (the chosen path) |
| System `python3` deps (live test) | running `tests/test_replay_live.py` | ✓ | `pytest`,`rosbags`,`rclpy`,`rosidl_runtime_py`,`numpy` present (Phase 12) | — |
| `rclpy` in uv venv | (must STAY absent — offline guarantee) | ✗ (by design) | — | n/a |
| `rosbag2` **mcap** storage plugin | (NOT needed — replay reads MCAP via `rosbags`, no plugin) | ✗ | — | `rosbags` reads MCAP natively (no rosbag2 plugin required) |

**Missing dependencies with no fallback:** none. The replay read path uses the offline `rosbags` reader (works for all three fixture formats, no MCAP plugin needed); the publish path uses `rclpy`/`rosidl_runtime_py` (both present, VERIFIED this session).

**Missing dependencies with fallback:** the `rosbag2_py` reader is present but rejects the fixtures — the chosen `rosbags` reader is the path, not a fallback.

**Live-lane invocation recipe (mirror Phase 12, swap the test file — VERIFIED recipe):**
```bash
# System python3 with ROS sourced has pytest + rosbags + rclpy + rosidl_runtime_py + numpy.
# PREPEND the package src trees to the ROS-populated PYTHONPATH (do NOT replace it).
source /opt/ros/humble/setup.bash
PYTHONPATH="packages/rosbagger-replay/src:packages/rosbagger-core/src:$PYTHONPATH" \
  python3 -m pytest tests/test_replay_live.py -m live -v
```
The offline suite is unchanged and skips the live test:
```bash
PYTHONPATH="" uv run pytest          # rclpy hidden -> importorskip skips test_replay_live.py
```
> LOCAL-RUN NOTE (from MEMORY): a bare `uv run pytest` crashes on this ROS-equipped box — prefix offline runs with `PYTHONPATH=""`.

## Validation Architecture

> `workflow.nyquist_validation` is `false` in `.planning/config.json`, so the full Nyquist section is optional. Including the test-map skeleton below because the two-tier strategy (D-11) is itself a locked decision and the planner needs the command surface.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` >=8,<10 + `pytest-cov` >=6 (`--cov=rosbagger_core --cov=bagq --cov-fail-under=80`) `[VERIFIED: root pyproject.toml]` |
| Config file | root `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`; `live` marker already registered) |
| Quick run command | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py tests/test_offline_guard.py -q` |
| Full suite command (offline) | `PYTHONPATH="" uv run pytest` (live test auto-skips) |
| Live lane | `source /opt/ros/humble/setup.bash && PYTHONPATH="packages/rosbagger-replay/src:packages/rosbagger-core/src:$PYTHONPATH" python3 -m pytest tests/test_replay_live.py -m live` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REP-01 (source, D-05) | `load_items` yields ordered `(t_ns, topic, msgtype, cdr)` for ROS2 sqlite3/MCAP + ROS1 (bridge) | unit (rosbags only, real fixtures) | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k source` | ❌ Wave 0 |
| REP-01 (controls, SC2) | play/pause/step/seek/rate/loop transitions on the pure `Replayer` (fake clock + recording sink) | unit (ROS-free) | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k scheduler` | ❌ Wave 0 |
| REP-01 (timing/seek landing, SC3) | rate scales slept Δt; seek lands on first item ≥ t; step = one-then-pause; loop restarts | unit (ROS-free) | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k 'rate or seek or loop or step'` | ❌ Wave 0 |
| REP-01 (CLI, D-02/D-10) | `replay` verb parses `--rate/--loop/--start/--topics/--duration/--max-messages` | unit (typer CliRunner, ROS mocked) | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k cli` | ❌ Wave 0 |
| REP-01 (capability error, D-12) | `replay()` raises `RosNotAvailableError` when rclpy absent; empty bag → `NoMessagesToReplayError` | unit | `PYTHONPATH="" uv run pytest tests/test_replay_unit.py -k 'no_ros or empty'` | ❌ Wave 0 |
| D-12 (offline guard) | `import rosbagger_replay` leaks no rclpy/rosbag2_py; core/bagq still ROS-free | unit (fresh subprocess) | `PYTHONPATH="" uv run pytest tests/test_offline_guard.py -k replay` | ⚠️ EXTEND existing |
| REP-01 (publish→receive, SC1) | real subscriber receives the replayed fixture topics | live (importorskip + `live`) | live-lane recipe above | ❌ Wave 0 |

### Wave 0 Gaps
- [ ] `tests/test_replay_unit.py` — source (real fixtures) + pure-`Replayer` (fake clock + recording sink) + CLI (mocked) + capability-error unit tests
- [ ] `tests/test_replay_live.py` — live SC1 integration test (`importorskip("rclpy")` + `live` marker)
- [ ] Extend `tests/test_offline_guard.py` — add `test_import_replay_does_not_pull_ros` (mirror `test_import_record_does_not_pull_ros`)
- [ ] `live` marker — already registered in root `pyproject.toml` (no change needed)
- [ ] Coverage gate — keep `rosbagger_replay` OUT of `--cov=` (D-12; the live sink can't be covered offline; the pure scheduler IS covered by the unit tier). Mirror how Phase 12 kept `rosbagger_record` out of the gate.

## Security Domain

> `security_enforcement` is not configured in `.planning/config.json` and this is a local developer tool that replays bags the user already has on their own ROS graph. No authentication, session, access-control, or cryptography surface is introduced. (Mirrors Phase 12's assessment.)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | partial | Bag path + `--topics`/`--rate`/`--start` are CLI args; `--rate` validated `> 0` (Pitfall 5); topic names from the bag are trusted data. Raw CDR is deserialized via `rclpy.serialization.deserialize_message` (the ROS-native parser, same trust as any ROS node consuming the topic). No SQL/identifier-injection surface. |
| V6 Cryptography | no | None. |
| V2/V3/V4 (auth/session/access) | no | Local CLI; no network service, no auth. |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Replaying a hostile/malformed CDR payload | Tampering | `deserialize_message` is the same parser every ROS node uses; the bag is the user's own (trusted) data. A malformed payload fails deserialization locally — no privilege boundary crossed. |
| Unbounded `--loop` replay floods the graph (DoS) | Denial of Service | `--duration`/`--max-messages` bounds + Ctrl-C give the operator control; document that `--loop` runs until stopped (mirrors Phase-12's bounded-record discipline). |

## Sources

### Primary (HIGH confidence — executed on this box THIS session)
- ROS 2 Humble `/opt/ros/humble` — `rclpy` 3.3.21 / `rosidl_runtime_py` importable; `rclpy.serialization.deserialize_message`/`serialize_message`; `rosidl_runtime_py.utilities.get_message`; `Node.create_publisher`/`create_subscription`; `rosbag2_py.get_registered_writers()` → `{sqlite3, my_test_plugin}` / `get_registered_readers()` → `{sqlite3, my_test_plugin, my_read_only_test_plugin}` (no MCAP); `rosbag2_py.SequentialReader` methods (`open/has_next/read_next/seek/get_all_topics_and_types/set_filter/reset_filter/get_metadata`); QoS policy enums (`QoSDurabilityPolicy`/`QoSReliabilityPolicy`).
- **End-to-end SC1 probe (executed):** ROS 2 sqlite3 fixture (`tools.make_fixtures.write_ros2_sqlite_bag`) → `AnyReader.messages()` raw CDR → `deserialize_message(raw, get_message(type_str))` → `create_publisher(...).publish()` → a separate subscriber node received all 3 `/imu` messages (`linear_acceleration.z == 9.8`).
- **Finding 1 (executed):** `rosbag2_py.SequentialReader.open(StorageOptions, ConverterOptions)` on the `rosbags`-written sqlite3 fixture → `RuntimeError: yaml-cpp: bad conversion` at the `offered_qos_profiles: []` line; dumped the offending `metadata.yaml`.
- **Finding 3 (executed):** ROS 1 fixture `rawdata` is 320 bytes (ROS 1 wire) vs 332-byte CDR; `reader.deserialize → typestore.serialize_cdr → deserialize_message` bridge round-trips OK. MCAP fixture `AnyReader` raw bytes are CDR with no typestore.
- **D-04 rationale (executed):** `serialize_message(rosbags.usertypes.* obj)` → `AttributeError: '_TYPE_SUPPORT'`.
- Timing: `time.sleep(0.001)` → ~1.06ms actual (sleep granularity adequate for pacing).
- Repo files (read this session): `13-CONTEXT.md`, `REQUIREMENTS.md`, `12-RESEARCH.md`/`12-VERIFICATION.md`/`12-REVIEW.md`, all `rosbagger-record/src/*` + `pyproject.toml`, `rosbagger-core/reader/{rosbags_reader,base}.py`, `tests/test_record_live.py`, `tests/test_offline_guard.py`, `tools/make_fixtures.py`, design spec §3/§5.2, root `pyproject.toml`, `.planning/config.json`.

### Secondary (MEDIUM confidence)
- Phase-12 verified ROS-sourced live-lane recipe + the MCAP-plugin-absent env note + WR-01/WR-02/WR-04 lessons (carried forward verbatim; the live-lane mechanics re-confirmed by the same `source + PYTHONPATH prepend` pattern).

### Tertiary (LOW confidence)
- The ROS1→CDR bridge correctness for `/cmd_vel`/`/image` specifically (verified for `/imu` this session; the `serialize_cdr` factory round-tripped all three in Phase 11's convert tests — A3).

## Metadata

**Confidence breakdown:**
- Publish path (D-04) / SC1: HIGH — the full `bag → raw CDR → deserialize_message → publish → subscriber receives` loop was executed end-to-end on the real ROS 2 Humble this session.
- Raw-CDR source (D-05): HIGH — the `rosbag2_py` rejection AND the `rosbags` raw-CDR success were both executed; the choice is evidence-driven, not inferred.
- Scheduler design (D-06..D-09): HIGH (design) — the state machine is pure Python the team fully controls; the timing primitive (`monotonic`+`sleep`) was sanity-checked. The exact transitions are unit-testable offline (the whole point of D-06).
- ROS1 bridge (D-05 ROS1 path): MEDIUM–HIGH — verified for `/imu`; extrapolated to the other two via Phase 11 precedent (A3).
- Pitfalls: HIGH — Pitfalls 1/2/3/4/5 were each directly reproduced or measured on the box.

**Research date:** 2026-05-23
**Valid until:** ~2026-06-22 (stable — pinned to ROS 2 Humble on this box + the existing `rosbags` reader; re-verify if the ROS distro or `rosbags` major version changes)
