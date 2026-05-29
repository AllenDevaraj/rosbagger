# Phase 20 Research: Replay RViz Fidelity (/clock + static republish)

**Phase:** 20 (REP-04). Verified by source read on 2026-05-29 (post-Phase-19). Design decided; implement as written. This phase is largely LIVE-ROS, so it follows the Phase-12/13 two-tier strategy: pure offline-testable decision logic + a thin live-marked rclpy boundary.

## 1. Current architecture (anchors)

**`replay.py`** — `build_publish_sink(node)` (`:39-87`) is the SINGLE publish path: builds a lazy per-topic `(msg_cls, publisher)` dict via `get_message`/`create_publisher`, deserializes `item.cdr` via `deserialize_message`, `pub.publish(msg)`, increments a `published={"n":0}` count dict; returns `(sink, published)`. `replay(...)` (`:90-183`) loads items, builds the `Replayer`, maps `--start`→seek, `play()`+`run()`, finalizes the rclpy context in a `finally`. Lazy ROS imports only (offline invariant).

**`source.py`** — `ReplayItem(t_ns, topic, msgtype, cdr)` (frozen, slots). `load_items(...)` materializes a time-ordered list. PURE (rosbags-only, lazy).

**`scheduler.py`** — `Replayer` (Phases 18+19): thread-safe transport + region loop; `seek`, `position_fraction`, `loop_region`. The sink is injected; the scheduler is generic over `.t_ns` items and knows nothing about ROS.

**`__init__.py`** — front door: re-exports `ReplayItem`/`load_items`/`Replayer`/errors/`build_publish_sink`/`replay`/`replay_bag`; `_require_ros()` guard; module top ROS-free.

**`cli.py`** — typer app, lazy-imports the package API in the command body; has `--rate/--loop/--start/--topics/--duration/--max-messages`.

**Live test pattern** (`tests/test_replay_live.py`): `rclpy = pytest.importorskip("rclpy")` + `pytestmark = pytest.mark.live`; an in-process producer (the production front door) + an EXTERNAL subscriber subprocess (own rclpy context) that counts received msgs on stdout. Mirror this for the `/clock` + static-republish live checks.

## 2. The key insight — separate PURE logic from the LIVE boundary (Phase-12/13 pattern)

The decision logic is ROS-free and unit-testable; only `pub.publish()` is live. This keeps CI green AND satisfies SC2 via the explicitly-allowed "unit test over the publish sink's static-tracking" route.

### 2a. Pure tier — `rosbagger_replay/fidelity.py` (NEW, stdlib-only, ROS-free)
- `class StaticTracker`: constructed with a set of static-topic names (default `frozenset({"/tf_static"})`, user-extensible). `record(item: ReplayItem)` stores `item` as the latest for its topic IF `item.topic` is in the static set (cheap dict write per publish). `republish_items() -> list[ReplayItem]` returns the currently-tracked latest items (the set to re-publish after a seek so a fresh subscriber re-primes). `clear()` resets. PURE — operates on `ReplayItem` (which is rosbags-free), imports only stdlib.
- `def clock_stamp_ns(t_ns: int) -> tuple[int, int]`: split an absolute bag t_ns into `(sec, nanosec)` for a `rosgraph_msgs/msg/Clock` `.clock` field. Pure arithmetic (`divmod(t_ns, 1_000_000_000)`); no ROS. (The actual `Clock` message construction is live — but the time math is pure + tested here.)
- Both are trivially offline-testable (no ROS, no Qt) and extend `tests/test_offline_guard.py`'s ROS-free assertion for `rosbagger_replay`.

### 2b. Live tier — extend `build_publish_sink` / `replay` (lazy ROS, in `replay.py`)
- `build_publish_sink(node, *, publish_clock=False, static_topics=frozenset())` (keyword-only, DEFAULT OFF — preserves today's behavior exactly when unused):
  - When `static_topics` non-empty, build a `StaticTracker(static_topics)`; in `sink(item)`, after the normal publish, call `tracker.record(item)`.
  - When `publish_clock`, lazily `get_message("rosgraph_msgs/msg/Clock")`, create a `/clock` publisher once, and in `sink(item)` publish a `Clock` whose `.clock.sec/.nanosec` = `clock_stamp_ns(item.t_ns)` (piggy-back on each publish — simplest correct cadence; a fixed-Hz timer is a deferred nicety). 
  - Return `(sink, published, tracker_or_None)` — but to avoid breaking the existing 2-tuple contract used by the desktop panel + the current tests, prefer: keep returning `(sink, published)` and expose the tracker via a small object/closure attribute, OR add the tracker as a 3rd element ONLY when requested. SAFEST: return a `SinkBundle`/namedtuple-ish but keep `sink, published = build_publish_sink(node)` working — i.e. make any new return element OPTIONAL/back-compatible. The planner picks the least-disruptive shape; the existing `sink, self._published = build_publish_sink(self._node)` call site in replay_panel.py and `sink, published = build_publish_sink(node)` in replay.py MUST keep working unchanged when the new kwargs are not passed.
- A `republish_static(tracker, sink)` helper (or a method on the bundle) the panel/replay calls AFTER a `replayer.seek(...)` to push `tracker.republish_items()` through the sink, so a fresh scene re-primes. (The scheduler does NOT know about this — it is a publish-path concern layered around seek, called from the desktop `_on_seeked` / a future CLI.)

### 2c. Desktop toggles — `replay_panel.py` (thin face)
- Add two checkboxes to the Phase-19 Advanced sub-panel: "Publish /clock" + "Re-publish static on seek". They set panel flags that `_ensure_transport` threads into `build_publish_sink(publish_clock=..., static_topics=...)`. When "re-publish static on seek" is on, `_on_seeked` (after the existing seek) calls the republish helper. Default OFF. No inline color; status via `set_status`.

## 3. Pitfalls
1. DEFAULT OFF — the no-kwargs `build_publish_sink(node)` call must behave EXACTLY as today (the existing live test + the desktop panel rely on it). 2. Back-compatible return shape — don't break `sink, published = build_publish_sink(node)`. 3. Pure tier stays stdlib-only; offline/Qt-free guard green; `import rosbagger_replay` ROS-free. 4. `/clock` message build is lazy (inside the sink/replay body), never at module top. 5. Static re-publish is a publish-path concern layered AROUND seek — the scheduler stays generic (do NOT add ROS to scheduler.py). 6. The fixture bags have no `/tf_static` and nothing latched (Phase-13 "latched caveat") — so a live static-republish test must WRITE a `/tf_static`-bearing fixture or publish one; prefer the PURE StaticTracker unit test for the deterministic SC2 proof and keep the live check minimal. 7. Thin face; no inline color; Phase-18/19 behavior intact.

## 4. Test plan
- **Pure (20-01, CI):** `StaticTracker` records latest-per-static-topic, ignores non-static topics, `republish_items` returns the tracked set, `clear` resets; `clock_stamp_ns` splits t_ns correctly (incl. sub-second + exact-second). Offline-guard extension. → SC2 (unit route) + SC4.
- **Live (20-02, `-m live`):** mirror `test_replay_live.py` — enable `publish_clock`, an external subscriber subprocess receives `/clock` msgs (SC1); enable static-republish on a `/tf_static`-bearing bag, seek, and the subscriber receives the re-published static msg (SC2 live). importorskip + `@pytest.mark.live` (skipped in offline CI). 
- **Desktop (20-03, headless offscreen):** the two toggles exist in the Advanced sub-panel; toggling threads the opt-in into `build_publish_sink` (assert via a sentinel/spy that the kwargs are passed) and a seek-with-static-on calls the republish helper. Offline/Qt-free guard + phase gate ≥80%.

## 5. Plan split
- 20-01 pure fidelity logic (fidelity.py: StaticTracker + clock_stamp_ns, ROS-free, Wave 1).
- 20-02 live publish wiring (build_publish_sink/replay opt-in /clock + static-republish, Wave 2, lazy ROS, live-marked test).
- 20-03 desktop toggles in the Advanced sub-panel (thin face, Wave 3, depends 20-01+20-02).
