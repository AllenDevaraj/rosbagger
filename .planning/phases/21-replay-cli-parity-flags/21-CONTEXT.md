# Phase 21 Context: Replay CLI Parity Flags

**Phase:** 21 (REP-05) · **Milestone:** v0.5 — Replay Playback System (FINAL phase)
**Source:** user ask — "there are multiple CLI cmds for replaying rosbag itself right like -l means loop… do we have all those command features?" Decisions auto-approved under the v0.5 autonomy mandate (memory `v0-5-autonomous-execution-mandate`). Full Goal + 4 SCs in `ROADMAP.md` Phase 21 block.

## Scope

Close the `ros2 bag play` flag gap on the `rosbagger-replay` CLI for the flags feasible in our custom publish model. The CLI is a THIN front door over `replay_bag()` (`cli.py` → `rosbagger_replay.replay`); each flag maps to an existing library mechanism — NO new publish path, NO re-implemented logic.

## Per-flag feasibility (verified against the current code)

Current `replay(bag_paths, *, topics, rate, loop, start, duration, max_messages, default_typestore)` and `build_publish_sink(node, *, publish_clock=False, static_topics=frozenset())` (Phase 20). Current CLI flags: `--rate --loop --start/--seek --topics --duration --max-messages`.

- **`--clock`** — EASY. `build_publish_sink` already takes `publish_clock` (Phase 20). Thread a `publish_clock: bool` param through `replay()` → `build_publish_sink(node, publish_clock=...)`; add `--clock` (bool flag) to the CLI. (A per-Hz cadence stays deferred — Phase 20 piggybacks /clock on each publish; document `--clock` as "publish /clock per message".)
- **`--delay SECONDS`** — EASY. Add `delay: float = 0.0` to `replay()`; `time.sleep(delay)` AFTER `rclpy.init()`/node build but BEFORE `replayer.play()`/`run()` (so subscribers can discover). Add `--delay`. Pure plumbing.
- **`--remap old:=new` (repeatable)** — MODERATE (real library addition). Add `remap: dict[str,str] | None` to `build_publish_sink`: when publishing, create the publisher on `remap.get(item.topic, item.topic)` (the remapped name) instead of `item.topic`. Thread `remap` through `replay()`. Parse `old:=new` pairs in the CLI into a dict. The static-tracker/clock paths are unaffected. Single publish path preserved (the remap is a name lookup inside the existing sink).
- **`--start-paused` / `-p`** — EASY but SEMANTICS NOTE. Add `start_paused: bool = False` to `replay()`; when True, do NOT call `replayer.play()` before `run()` (the Replayer defaults to PAUSED), so a run-to-completion CLI invocation publishes 0 and returns immediately in the PAUSED state. For a NON-interactive CLI this means "build the transport but publish nothing until resumed" — there is no keyboard resume in our CLI (runtime services are deferred — SC3), so `--start-paused` at the CLI is mostly a parity/known-state flag; document that interactive resume lives in the GUI. Still testable: with `start_paused=True`, `replay_bag(...)` returns 0 (nothing published) — assert via the CLI mock + a scheduler-level unit test.
- **bounded region `--region-start SEC` / `--region-end SEC`** — MODERATE. "Plays only [in,out]". The scheduler has `set_loop_region` (Phase 19, wraps a snippet on repeat) + `seek`. For a run-to-completion CLI, "play [in,out] ONCE" = `seek(region_start)` then stop when the cursor passes `region_end`. The scheduler's bounded stop is monotonic-duration / max_messages, NOT a t_ns horizon, so the cleanest mapping that REUSES existing mechanism: `seek(region_start)` + `set_loop_region(in,out)` + `--loop` to repeat the snippet (the documented snippet-loop), OR (if no loop) compute a `max_messages`/`duration` bound from the region. DECISION FOR THE PLANNER: prefer mapping `--region-start`/`--region-end` to `seek(start)` + `set_loop_region` and REQUIRE/imply `--loop` for repeat (document that a bounded single-pass region is the same deferred t_ns-horizon stop noted in the cli.py D-10 docstring). Keep it honest: if a clean single-pass [in,out] stop isn't available without a new scheduler predicate, ship the region+loop form and document the single-pass as deferred (mirroring the existing `--end`-folded-into-`--duration` precedent). The planner picks the least-invasive mapping that reuses existing scheduler API.
- **DEFERRED (SC3, document as out-of-scope, do NOT implement):** runtime ROS services (`~/seek`, `~/set_rate`, `~/play_next`, `~/burst`, `~/toggle_paused`) — they need a long-lived spinning node; the GUI already provides interactive control. `--qos-profile-overrides-path`, `--storage`, `--read-ahead-queue-size`, loaned messages — out of scope (per the earlier investigation table).

## Hard invariants
- CLI stays THIN: each flag maps to a `replay()`/`build_publish_sink` param; no publish logic in cli.py; `cli.py` top level stays typer+stdlib only (offline-guard discipline — the ROS import stays behind `_require_ros()`).
- `rosbagger_replay` no module-top ROS import; offline import graph ROS-free AND Qt-free; `build_publish_sink` stays the SINGLE publish path (the `remap` is a name lookup inside it, not a second sink); its no-kwargs back-compat (the 2-tuple + Phase-20 defaults-off) preserved.
- `scheduler.py` thread-safety + region semantics (Phases 18/19) and Phase-20 fidelity unchanged.

## Success criteria (from ROADMAP Phase 21)
1. `rosbagger-replay --help` exposes `--start-paused`, `--remap`, `--delay`, `--clock`, bounded-region options; each maps to the library with no new publish path.
2. `--remap` publishes on the remapped topic; `--start-paused` begins paused; `--delay` sleeps before play; the bounded region plays only `[in,out]` — proven by tests (live where publishing is required, unit where the mapping suffices).
3. Deferred runtime-service controls documented as out-of-scope (not silently missing).
4. Offline/Qt-free guard green; CLI stays thin; full headless suite ≥80%.

## Testing strategy / host notes
- CLI flag→param mapping is unit-testable by MOCKING the front door (the existing `cli.py` tests in `tests/test_replay_unit.py` use typer's `CliRunner` + monkeypatch `rosbagger_replay.replay_bag`). Assert each flag forwards the right kwarg. `--help` text exposure is a pure CliRunner assertion (no ROS).
- `--remap` actual republish-on-new-name is a LIVE proof (extend `tests/test_replay_fidelity_live.py` or `test_replay_live.py`, `-m live`); the CLI mapping is the unit proof.
- `replay()` param additions (`delay`/`start_paused`/`remap`/`publish_clock`/region) — small unit tests where mockable; the rclpy parts via the live lane.
- Run with `PYTHONPATH=""`; gate blended `--cov-fail-under=80`; SIGBUS-at-exit is a Qt teardown artifact (re-run / junitxml). Worktrees OFF; ruff line length 100; gsd-verifier not installed (verify inline).

## Suggested plan split (planner decides final shape; keep it ~2 plans to stay lean)
- **21-01** — library param plumbing: `replay()` gains `delay`/`start_paused`/`publish_clock`/`remap`/region params (mapping to existing mechanisms: delay=sleep-before-play, start_paused=skip play(), publish_clock→build_publish_sink, remap→build_publish_sink topic remap, region→seek+set_loop_region); `build_publish_sink` gains `remap`. Unit tests (scheduler/mock level) + offline guard. A `-m live` `--remap`/`--clock` republish proof.
- **21-02** — CLI surface: add `--clock`/`--delay`/`--remap`/`--start-paused`/`--region-start`/`--region-end` to `cli.py`, parse `--remap old:=new`, forward to `replay_bag`; document deferred runtime services in the CLI help/docstring; CliRunner unit tests (flag exposure + kwarg forwarding via a mocked front door). Phase gate.
