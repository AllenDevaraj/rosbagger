# Phase 20 Context: Replay RViz Fidelity (/clock + static republish)

**Phase:** 20 (REP-04) · **Milestone:** v0.5 — Replay Playback System
**Source:** user ask — "drag it back and forth and RViz will be affected accordingly too." Phase 18 surfaced the hard truth (memory `replay-scrub-is-jump-plus-forward`): a backward scrub is jump + forward-republish, NOT a visual rewind, and RViz only reflects what we publish from the seek point onward. THIS phase makes a seek "look right" in RViz. Full Goal + 4 SCs live in `ROADMAP.md` (Phase 20 block). Decisions auto-approved under the v0.5 autonomy mandate (memory `v0-5-autonomous-execution-mandate`).

## Scope

Two opt-in mechanisms, both DEFAULT OFF (today's behavior unchanged):

1. **`/clock` publishing** — publish `rosgraph_msgs/msg/Clock` carrying the current item's bag time so downstream `use_sim_time` nodes (incl. RViz) track bag time instead of wall-clock. Configurable rate (Hz) or piggy-backed on each publish.
2. **Static / latched re-publish on seek** — track the latest message per "static" topic (default `/tf_static`; user-extensible) as the stream plays, and after a seek re-publish those latest-seen messages so a fresh scene re-primes in RViz instead of layering stale geometry over new. This is the concrete fix for the "backward scrub looks wrong" limitation from Phase 18.

Surfaced as: opt-in toggles in the Phase-19 Replay sub-panel + matching CLI flags (the CLI flags themselves are Phase 21's `--clock`; this phase provides the library mechanism + a clock flag if it lands naturally).

**Out (deferred):** the remaining CLI parity flags (`--start-paused`/`--remap`/`--delay`/bounded region) → **Phase 21**; synthetic `/tf` (dynamic transform) reconstruction → out of scope (only `/tf_static` + configured latched topics re-publish); in-app 3D viz → permanently out.

## Hard invariants

- `rosbagger_replay` no module-top ROS import — every `rclpy`/`rosidl_runtime_py` import stays inside function bodies behind the `_require_ros` front door. `import rosbagger_replay` stays ROS-free; `tests/test_offline_guard.py` green.
- The **decision logic must be PURE + offline-testable** (mirror Phases 12/13): a static-topic tracker + clock-time computation that are ROS-free and unit-tested with no ROS; only the actual `pub.publish()` is the thin rclpy boundary (live-marked tests).
- `build_publish_sink` stays the SINGLE production publish path — extend it (or layer on it), do not add a second.
- Defaults preserve today's behavior: clock OFF, no forced static re-publish, unless explicitly enabled.
- Desktop panel stays a thin face; no inline color; Phase-18 live scrubbing + Phase-19 region loop intact.

## Success criteria (from ROADMAP Phase 20)

1. With clock publishing enabled, `/clock` is published carrying bag-relative time during replay — proven by a live (`-m live`) test subscribing to `/clock`.
2. After a seek, latched/`transient_local` topics (and `/tf_static`) seen before the seek are re-published so a fresh subscriber re-primes — proven by a live test OR a unit test over the publish sink's static-tracking (SC explicitly allows the unit-test route — prefer it for CI).
3. Both behaviors opt-in via the side sub-panel + matching CLI flags; defaults unchanged (clock off).
4. Offline/Qt-free guard green; `import rosbagger_replay` stays ROS-free; full headless suite ≥80%.

## Testing strategy / host notes

- PURE tier (offline, CI): the static-topic tracker (records latest `ReplayItem` per configured static topic; returns the re-publish set on seek) + clock-time/stamp computation — fast unit tests, no ROS. This satisfies SC2 via the "unit test over static-tracking" route.
- LIVE tier (`-m live`, ROS-sourced lane, `uv run --with pyyaml`): a subscriber receives `/clock` (SC1) and receives the re-published static message after a seek (SC2 live). Mirror the Phase-13 live test (`tests/test_replay_live.py`) — `importorskip` + `@pytest.mark.live`, skipped in the offline lane.
- Desktop toggles: headless pytest-qt (offscreen).
- Run with `PYTHONPATH=""`; gate blended `--cov-fail-under=80`; SIGBUS-at-exit is a Qt teardown artifact (re-run / junitxml). Worktrees OFF.

## Suggested plan split (for the planner)

- **20-01** — pure fidelity logic (ROS-free, Wave 1): a new module (e.g. `rosbagger_replay/fidelity.py`) with a `StaticTracker` (record latest item per configured static-topic set, default `{"/tf_static"}`; `republish_items()` returns the tracked latest items) + a pure clock-stamp helper (t_ns → sec/nanosec). stdlib-only; offline unit tests; offline-guard extension. Satisfies SC2 (unit route) + SC4.
- **20-02** — live publish wiring (lazy ROS, Wave 2): extend `build_publish_sink`/`replay` to optionally (a) publish `/clock` from the current item's t_ns at a configurable cadence, (b) feed each published item to the `StaticTracker` and re-publish the tracked set after a seek. Opt-in params default off. Live-marked test (`/clock` received; static re-published after seek). SC1 + SC2(live) + SC3(library half).
- **20-03** — desktop toggles (thin face, Wave 3): expose "Publish /clock" + "Re-publish static on seek" toggles in the Phase-19 Advanced sub-panel, wired to the library opt-ins; headless tests; phase gate. SC3 (UI half) + SC4.
