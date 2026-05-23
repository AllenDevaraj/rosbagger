# Phase 13: Live Replay - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 13-live-replay
**Mode:** `--auto` (autonomous — all gray areas auto-selected; recommended option chosen per question, no prompts)
**Areas discussed:** Package/deps/CLI surface, Read-source & publish mechanism, Transport architecture, Timing/rate/seek/loop/step semantics, Test strategy & offline guarantee

**Mirrors Phase 12** (`rosbagger-record`): same live-package boundary, env-provided rclpy, two-tier testing. **Key wrinkle:** the v1 reader's `Message.msg` is a rosbags object (not an rclpy/rosidl message), so the publish path needs raw CDR → `rclpy.serialization.deserialize_message` → typed publish.

---

## Package, dependencies & CLI surface

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `rosbagger-replay` pkg + `rosbagger-replay` script; ROS env-provided + lazy | Mirror rosbagger-record exactly | ✓ |
| `bagq replay` capability-gated subcommand | Add replay to bagq | |
| rclpy as a uv pyproject dep | Let uv resolve ROS | |

**Auto-selected:** separate `packages/rosbagger-replay/` + `rosbagger-replay` console script; rclpy env-provided + lazy-imported.
**Notes:** Design-locked + Phase-12 precedent. `bagq replay` would pull rclpy into bagq's offline graph; uv-resolved rclpy isn't a usable wheel (proven in Phase 12).

---

## Read-source & publish mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| raw CDR → `rclpy.serialization.deserialize_message` → typed `create_publisher().publish()` | Source raw bytes (rosbag2_py SequentialReader recommended), deserialize with rclpy, publish typed | ✓ |
| Publish the v1 reader's rosbags-deserialized `msg` directly | Reuse reader output as-is | |
| Re-serialize the rosbags msg to CDR + raw publish | Round-trip through rosbags serialization | |

**Auto-selected:** raw CDR → rclpy deserialize → typed publish via `get_message(type)`; raw-CDR source is research-led (recommended `rosbag2_py.SequentialReader`, mirroring record).
**Notes:** The v1 reader's `Message.msg` is a ROSBAGS object — rclpy `publish()` needs an rclpy/rosidl message, so it can't be published directly (rejected option 2). Raw CDR + rclpy deserialize is the clean, ROS-native path and avoids a re-serialize round-trip (option 3 fragile). Research confirms whether the raw source is rosbag2_py's reader or a v1-reader raw seam.

---

## Transport architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Split a PURE transport scheduler (state machine + clock) from the rclpy publish sink | Pure `Replayer` owns play/pause/step/seek/rate/loop; rclpy publish is an injectable callback | ✓ |
| Monolithic rclpy node owns transport + publish | Everything in one ROS node | |
| Wrap `rosbag2_py.Player`'s built-in controls | Rely on the rosbag2 player API | |

**Auto-selected:** split a pure-Python `Replayer`/scheduler (ROS-free, all 6 controls on its API) from a thin injectable rclpy publish sink.
**Notes:** This is THE testability decision — it makes SC2/SC3 logic unit-testable without ROS (fake clock + recording sink) and isolates rclpy to a tiny surface (the Phase-12 pure-logic/ROS-sink lesson). Monolithic node rejected (untestable offline). `rosbag2_py.Player` rejected — its Python control surface for play/pause/step/seek is opaque/incomplete in Humble; a custom loop gives all 6 controls cleanly.

---

## Timing / rate / seek / loop / step semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Monotonic-paced inter-message Δt ÷ rate; seek=jump-to-t; step=one-then-pause; loop=restart | Wall-clock pacing on a monotonic clock, scaled by --rate | ✓ |
| Wall-clock `time.time()` pacing | Pace on system clock | |
| `/clock` + use_sim_time simulated-time replay | Publish a simulated clock | |

**Auto-selected:** monotonic-clock pacing of inter-message Δt_ns ÷ `--rate`; `pause` holds, `play` resumes, `step` = next-msg-then-pause, `seek(t)` jumps to first msg ≥ t, `loop` restarts at end.
**Notes:** Monotonic (not `time.time()`) per Phase-12 WR-02. `/clock`/use_sim_time deferred (v1 = wall-clock pacing) — keeps the phase focused; sim-time is a fidelity enhancement. Rate/seek landing asserted against expected message indices/timestamps (SC3).

---

## Test strategy & offline guarantee

| Option | Description | Selected |
|--------|-------------|----------|
| Two-tier: pure scheduler unit tests (ROS-free) + live subscriber integration test (ROS-sourced, gated) | Mirror Phase 12; pure transport tested in uv venv, SC1 proven by a real subscriber | ✓ |
| Live tests only | Require ROS for all tests | |
| Mock everything | Never run a real subscriber | |

**Auto-selected:** two-tier — (1) ROS-free unit tests of the pure `Replayer` (play/pause/step/seek/rate/loop + monotonic timing with a fake clock + recording sink) prove SC2/SC3 logic; (2) `live`-marked, `importorskip("rclpy")`-gated integration test (real subscriber receives replayed messages, SC1) run in the ROS-sourced lane, skipped in offline CI. Extend `test_offline_guard.py`; keep the package out of the `--cov` gate.
**Notes:** Same shape as Phase 12, inverted (replay publishes, the test subscribes). The pure-scheduler split (D-06) is what makes SC2/SC3 deterministically testable without ROS. The orchestrator MUST actually run the live lane (Phase-12 W4) — collected-and-skipped is insufficient for SC1.

---

## Claude's Discretion

- Exact module layout (mirror `rosbagger_record`: `__init__/cli/replay/errors` + a `transport`/`scheduler` module); CLI flag names.
- The raw-CDR source choice (rosbag2_py SequentialReader vs a v1-reader raw seam) — research-led.
- Default QoS profile; whether to ship an interactive keyboard transport mode.
- Hard constraints: offline core/bagq never import rclpy; the pure scheduler is ROS-free + unit-tested; live test gated/skippable; SC1 proven by an actually-run subscriber.

## Deferred Ideas

- GUI Replay panel (Phase 14).
- `/clock` + use_sim_time simulated-clock replay.
- Topic remapping; per-topic QoS profiles / override.
- Interactive keyboard transport TUI.
- Latched / transient-local replay semantics beyond a sane default.
