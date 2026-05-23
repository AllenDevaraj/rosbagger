# Phase 13: Live Replay - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 13 is rosbagger's **second LIVE phase**: `rosbagger-replay` publishes a bag's messages to real ROS topics with transport controls — play / pause / step / seek / rate / loop. Like `rosbagger-record` (Phase 12) it **requires a sourced ROS 2 environment** (`rclpy`); the offline tier (`rosbagger-core`, `bagq`, edit/events/tf) stays ROS-free. It depends on Phase 2 (the v1 reader) for bag access.

**In scope (REP-01):** replay a bag, publishing real ROS topics a subscriber receives (SC1); the six transport controls all WORK (SC2); rate scaling + seek land at the expected message/timestamp (SC3); a thin `rosbagger-replay` CLI; the offline/CI guarantee preserved; a two-tier test strategy (pure-Python transport scheduler unit-tested ROS-free + a live integration test proving a subscriber receives).

**Out of scope (own phases / deferred):** the GUI Replay panel (Phase 14 — capability-gates over this module's API); `/clock` + `use_sim_time` simulated-clock publishing (v1 paces on wall-clock); topic remapping; per-topic QoS profiles / QoS override; latched/transient-local replay nuance beyond a sane default; record (Phase 12). New capabilities belong in their own phase.

</domain>

<decisions>
## Implementation Decisions

> **`--auto` mode:** every decision below is the recommended default, auto-selected without prompts. Several are **locked by the design spec** (§3 offline/live split + §5.2 "rosbagger-replay … transport controls") and by the **Phase-12 precedent** (the `rosbagger-record` live-package pattern that this phase mirrors).
>
> **Verified context (from Phase 12 + this scout):** `rclpy` imports only from sourced ROS (`/opt/ros/humble/...`), NOT the project uv venv. The v1 reader's `Message.msg` is a **rosbags-deserialized** object (NOT an rclpy/rosidl message), so `rclpy` `publisher.publish()` cannot take it directly — the publish path needs raw CDR → `rclpy.serialization.deserialize_message`. ROS lane reachable here (`create_publisher`, `get_message` available).

### Package, dependencies & CLI surface (mirror Phase 12)

- **D-01 — New SEPARATE workspace package `packages/rosbagger-replay/`** (uv member; `members=["packages/*"]`), mirroring `rosbagger-record`. Logic in its Python API; thin CLI. Design-locked: "live modules isolate rclpy behind their package boundary."
- **D-02 — Console script `rosbagger-replay`** (NOT a `bagq` subcommand — keeps `bagq` 100% offline). API-first / CLI↔GUI parity: the Phase-14 GUI Replay panel capability-gates over this same package API.
- **D-03 — `rclpy` (+ `rosbag2_py`/`rosidl_runtime_py` as needed) are ENVIRONMENT-provided, NOT uv-resolved.** The package's only uv-resolved dependency is `rosbagger-core` (the v1 reader contract) + `typer` — exactly as `rosbagger-record/pyproject.toml` declares. ROS modules are **lazy-imported** inside functions so `import rosbagger_replay` succeeds in the ROS-free uv venv; `replay()` raises a teaching capability error ("source your ROS 2 environment") when `rclpy` is absent.

### Read source & publish mechanism (the primary research item)

- **D-04 — Publish path: raw CDR → `rclpy.serialization.deserialize_message(raw, msg_cls)` → typed `create_publisher(msg_cls, topic, qos).publish(msg)`**, where `msg_cls = rosidl_runtime_py.utilities.get_message(msgtype_str)`. This avoids the rosbags↔rclpy message-class mismatch (the v1 reader's deserialized `msg` is a rosbags object and is NOT directly republishable). One generic publisher is created per selected topic from its discovered type.
- **D-05 — Raw-CDR source = the v1 `rosbags` `AnyReader` (RESOLVED by RESEARCH).** The tentative default (`rosbag2_py.SequentialReader`) was OVERTURNED: it cannot open the project's rosbags-written fixtures on Humble (`RuntimeError: yaml-cpp: bad conversion` — rosbags writes `offered_qos_profiles: []` as a sequence where rosbag2_py expects a scalar). So the live read path uses the **v1 `rosbags` reader** (Phase 2), which natively yields raw CDR bytes for ROS 2 bags, reads all three formats, and is the same reader the rest of the project uses — adding a small raw-bytes seam if the public `read()` only exposes deserialized `Message`s. **Wire-format caveat:** ROS 2 bag raw bytes ARE CDR (fed straight to `rclpy.serialization.deserialize_message`); ROS 1 bag raw bytes are ROS 1 wire format (NOT CDR) and need a `reader.deserialize → typestore.serialize_cdr` bridge before publish (verified). The publish bytes must always be CDR, never a rosbags-deserialized object.

### Transport architecture (the testability decision)

- **D-06 — Split a PURE-PYTHON transport scheduler from the rclpy publish sink.** A `Replayer` (or `TransportScheduler`) owns the state machine + clock math (play/pause/step/seek/rate/loop, inter-message timing) and is **completely ROS-free** — it consumes an ordered stream of `(t_ns, topic, msgtype, payload)` items and a clock, and emits "publish item X now" decisions. The rclpy publish SINK (create publishers, deserialize, publish) is a thin injectable callback. This makes SC2/SC3's control + timing logic unit-testable WITHOUT ROS, and isolates the irreducible rclpy wiring to a tiny live-only surface (the Phase-12 lesson: keep the pure logic out of the ROS layer).
- **D-07 — All six controls live on the `Replayer` API** (`play()`/`pause()`/`step()`/`seek(t)`/`set_rate(x)`/`loop` flag) so SC2 is provable programmatically by a test driving the API. The CLI is a thin face over it.

### Timing / rate / seek / loop / step semantics

- **D-08 — Wall-clock pacing via a MONOTONIC clock** (the Phase-12 WR-02 lesson — never `time.time()`): sleep the inter-message `Δt_ns` between consecutive bag timestamps, divided by `--rate` (rate>1 = faster, <1 = slower). `--rate` scales the schedule (SC3).
- **D-09 — Control semantics:** `pause` holds (stop publishing, keep position); `play` resumes; `step` publishes exactly the next message then re-pauses; `seek(t)` jumps the cursor to the first message at/after bag-relative time `t` (skips intervening messages without publishing) and lands at the expected message (SC3); `loop` restarts from the beginning at end-of-bag; end-without-loop stops cleanly. Seek/rate landing is asserted against expected message indices/timestamps.
- **D-10 — CLI surface:** v1 exposes the non-interactive, scriptable subset — `--rate`, `--loop`, `--start`/`--seek` (offset seconds), optional `--topics` subset, optional `--duration`/`--end`. Interactive keyboard control (live play/pause/step keystrokes) is **Claude's discretion / optional** — the controls are fully exercised via the API in tests regardless, so an interactive TUI is not required for SC2.

### Test strategy & offline guarantee (mirror Phase 12's two-tier)

- **D-11 — Two-tier testing.**
  1. **ROS-free UNIT tests** (uv venv / offline CI): the pure `Replayer`/scheduler — play/pause/step/seek/rate/loop transitions + monotonic timing math with a FAKE clock and a recording sink (no rclpy). This is where SC2 + SC3 *logic* is proven deterministically. Plus CLI parsing with the ROS bits mocked.
  2. **LIVE integration test** (ROS-sourced lane — system python3 with ROS sourced, src trees prepended to `PYTHONPATH`; NOT `PYTHONPATH="" uv run`): a real `rclpy` subscriber → `rosbagger-replay <fixture-bag> --rate <fast> [--duration/--max]` → assert the subscriber RECEIVES the expected messages on the expected topics (SC1), bounded/deterministic. Gated by `pytest.importorskip("rclpy")` + the `live` marker; SKIPPED in the offline CI; **the orchestrator must actually RUN it in the ROS lane** (Phase-12 W4 lesson — a collected-and-skipped result is insufficient for SC1 sign-off).
- **D-12 — Offline guarantee preserved.** `rclpy`/`rosbag2_py` isolated to `rosbagger-replay`, lazy-imported; `import rosbagger_replay` clean in the ROS-free uv venv. **Extend `tests/test_offline_guard.py`** to assert `import rosbagger_replay` (and core/bagq) pull NO `rclpy`/`rosbag2_py`. Keep the new package OUT of the `--cov=rosbagger_core --cov=bagq` gate (the irreducible rclpy publish wiring is live-only; the pure scheduler is unit-covered).

### Claude's Discretion
Exact module layout (mirror `rosbagger_record`: `__init__/cli/replay/errors` + a `transport`/`scheduler` module); CLI flag names; the raw-CDR source choice (rosbag2_py SequentialReader vs a v1-reader raw seam — research-led); default QoS profile; whether to ship an interactive keyboard mode. Hard constraints: offline `core`/`bagq` NEVER import rclpy; the pure transport scheduler MUST be ROS-free + unit-tested; the live test stays gated/skippable so offline CI stays green; SC1 proven by an actually-run live subscriber.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` § "Phase 13: Live Replay" — goal + 3 success criteria (publish real topics a subscriber receives; the six transport controls work; rate/seek land at the expected message/timestamp).
- `.planning/REQUIREMENTS.md` § "Live (record/replay)" — REP-01 (replay a bag to ROS topics with transport controls).
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` — §3 offline/live split + capability-gating (lines ~55–87: "replay publishes real ROS topics they subscribe to"; "Live modules isolate rclpy behind their package boundary"); §5.2 line ~132 ("rosbagger-replay (live) — play a bag → ROS topics with transport controls (play/pause/step/seek/rate/loop); drives rviz / Foxglove").

### Code seams / patterns to mirror (read before planning)
- `packages/rosbagger-record/` (Phase 12 — the live-package TEMPLATE): `pyproject.toml` (rosbagger-core + typer only; rclpy env-provided; `rosbagger-replay = "rosbagger_replay.cli:app"`), `record.py` (lazy ROS imports, monotonic bounded stop, finalize-on-error), `cli.py` (thin typer + `@_capability_errors` + parse-time choice), `errors.py` (teaching capability errors), and the live test `tests/test_record_live.py` + its ROS-sourced run recipe.
- `packages/rosbagger-core/src/rosbagger_core/reader/rosbags_reader.py` + `reader/base.py` — the v1 reader (Phase 2 dependency): `Message(topic, t, t_ns, stamp, msgtype, msg)`, `read(topics=)`, `connections`, `typestore`, `start_time`/`end_time`, `default_typestore`. Note `Message.msg` is a rosbags object (the D-04 republish wrinkle).
- `tests/test_offline_guard.py` — the offline-import invariant to EXTEND for `rosbagger_replay` (reuse the existing plain `PYTHONPATH=""` helper — Phase-12 W3 lesson; do not add ROS-bearing paths).
- `tools/make_fixtures.py` — the fixture bags the live test replays from (ROS 1 / ROS 2-sqlite3 / MCAP).

### Phase-12 lessons that carry forward
- `.planning/phases/12-live-record/12-VERIFICATION.md` + `12-REVIEW.md` — the verified ROS-sourced live-lane invocation, the MCAP-plugin-absent env note (sqlite3 fixtures available), monotonic-not-wallclock (WR-02), actually-run-the-live-lane (W4), and the offline-guard mechanics (W3).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`rosbagger-record` package (Phase 12)** is a near-exact structural template: lazy-ROS package boundary, env-provided rclpy in pyproject, thin typer CLI with `@_capability_errors` + parse-time `Enum` choices, teaching errors, the two-tier test split, and the offline-guard extension. Replay copies the shape and swaps record→publish.
- **v1 reader** (`reader/rosbags_reader.py`): the canonical bag reader (Phase 2 dependency); yields ordered `Message` records with `topic`/`t_ns`/`msgtype`. Used for metadata/validation; the raw-CDR publish source is a research choice (D-05).
- **Phase-12 live-lane recipe** (in `12-VERIFICATION.md`): `source /opt/ros/humble/setup.bash && PYTHONPATH="<src trees>:$PYTHONPATH" python3 -m pytest tests/test_record_live.py -m live` — reused verbatim (swap the test file) for the replay live test.
- **Teaching-error pattern** (`rosbagger_record/errors.py` + `rosbagger_core/errors.py`): reused for the rclpy-absent capability error.

### Established Patterns
- **Offline tier never imports ROS** (verified by `test_offline_guard.py`); rclpy lives ONLY in the live packages, lazy-imported. Phase 12 proved the boundary holds; Phase 13 must keep it.
- **Pure-logic / ROS-sink split:** Phase 12 kept selection/orchestration pure and unit-tested with mocks; Phase 13 extends this to a fully pure transport scheduler — the SC2/SC3 test target.
- **Monotonic, not wall-clock** for any timing/deadline (Phase-12 WR-02). Replay pacing uses `time.monotonic()`.
- **Actually run the live lane** (Phase-12 W4): the orchestrator re-runs the ROS-sourced live test itself; collected-and-skipped is insufficient for SC sign-off.
- **No-ROS fixtures** (`tools/make_fixtures.py`): the live test replays from the existing fixture bags.

### Integration Points
- New `rosbagger_replay` API (a `Replayer` with the 6 controls + a raw-CDR source + an injectable rclpy publish sink) consumed by a thin `rosbagger-replay` CLI; the GUI (Phase 14) capability-gates over the same API.
- Raw-CDR source: `rosbag2_py.SequentialReader` (recommended) or a v1-reader raw seam — research-led (D-05).
- offline-guard extended; rclpy/rosbag2_py lazy-imported behind the package boundary.

</code_context>

<specifics>
## Specific Ideas

- SC1 is proven by a real rclpy SUBSCRIBER receiving published messages in the ROS-sourced lane (mirror Phase 12's live test, inverted: replay publishes, the test subscribes).
- SC2/SC3 logic (pause/step/seek/rate/loop + timing) is proven deterministically by unit tests driving the pure `Replayer` with a fake clock + recording sink — no ROS needed. This is the architectural payoff of the D-06 split.
- A bounded live run (`--duration`/`--max` + a fast `--rate`) keeps the live test deterministic and quick (Phase-12 lesson).
- Reuse the Phase-12 ROS-sourced live-lane command verbatim.

</specifics>

<deferred>
## Deferred Ideas

- **GUI Replay panel** — Phase 14 (capability-gated over this module's API; jump-points from the events sidecar live there too).
- **`/clock` + `use_sim_time`** simulated-clock publishing — v1 paces on wall-clock; sim-time fidelity is a later enhancement.
- **Topic remapping** (`--remap from:=to`) and **per-topic QoS profiles / QoS override** — v1 publishes on original topic names with a sane default QoS.
- **Interactive keyboard transport TUI** — optional/discretion; the API + non-interactive flags cover SC2 for v1.
- **Latched / transient-local replay semantics** beyond a sane default.

</deferred>

---

*Phase: 13-live-replay*
*Context gathered: 2026-05-23*
