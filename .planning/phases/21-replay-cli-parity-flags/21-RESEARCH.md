# Phase 21 Research: Replay CLI Parity Flags

**Phase:** 21 (REP-05) · **Milestone:** v0.5 — Replay Playback System (FINAL phase)
**Mode:** confirm-and-anchor. CONTEXT (`21-CONTEXT.md`) already decided the per-flag design;
this doc anchors every decision in the real code at `file:line` and pins the test plan. It does
NOT re-derive scope.

## 1. The code as it stands (anchors)

### CLI — `packages/rosbagger-replay/src/rosbagger_replay/cli.py`
- Thin `typer.Typer` app (`app`, `cli.py:44`); top level imports ONLY `__future__` + stdlib
  `functools` + `typing.Annotated` + `typer` (`cli.py:37-42`) — NO ROS (offline-guard discipline).
- `@_capability_errors` wrapper (`cli.py:54-89`) lazily imports `errors.py` and turns the two
  KNOWN teaching errors (`RosNotAvailableError`, `NoMessagesToReplayError`) into a clean red
  stderr line + `Exit(1)`; a real bug still tracebacks (no bare `except Exception`).
- The single `replay()` command (`cli.py:92-172`). Current flags:
  - `--rate` float = 1.0 (`cli.py:99`)
  - `--loop` bool = False (`cli.py:103`)
  - `--start` / `--seek` float = 0.0 SECONDS (`cli.py:110`)
  - `--topics` list[str]|None = None (`cli.py:118`)
  - `--duration` float|None = None (`cli.py:122`)
  - `--max-messages` int|None = None (`cli.py:134`)
- ROS import stays behind the lazy `from rosbagger_replay import replay_bag as replay_api`
  (`cli.py:158`); the call forwards parsed flags + `set(topics) if topics is not None else None`
  (`cli.py:160-171`) and echoes `Published N messages`.
- `--end`-folded-into-`--duration` precedent: the module docstring (`cli.py:24-34`) + the
  `--duration` help (`cli.py:125-131`) document the deferred t_ns-horizon stop as a deferred
  enhancement, NOT a silent drop. This is the EXACT precedent the bounded-region single-pass
  stop mirrors (CONTEXT §per-flag, region row).

### Library — `packages/rosbagger-replay/src/rosbagger_replay/replay.py`
- `build_publish_sink(node, *, publish_clock=False, static_topics=frozenset())`
  (`replay.py:39`) — the SINGLE production publish path. Lazy `deserialize_message` /
  `get_message` imports inside the body (`replay.py:86-87`). The inner `sink(item)`
  (`replay.py:104-126`) builds one publisher per topic on **`item.topic`** (`replay.py:109`),
  deserializes `item.cdr`, `pub.publish(msg)`, then `published["n"] += 1` (`replay.py:119`),
  then the Phase-20 opt-ins (`tracker.record(item)` / `/clock`). Returns the 2-tuple
  `(sink, published)` with the tracker on `sink.tracker` (`replay.py:131-132`) — the
  back-compat contract: a no-kwargs call + 2-tuple unpacking is byte-for-byte unchanged.
- `republish_static(sink)` (`replay.py:135-152`) — re-pushes `sink.tracker.republish_items()`
  through the SAME sink (publish-path concern, scheduler untouched).
- `replay(bag_paths, *, topics, rate, loop, start, duration, max_messages, default_typestore)`
  (`replay.py:155-165`). The orchestration body:
  - raises `NoMessagesToReplayError` on empty selection BEFORE `rclpy.init()` (`replay.py:202-205`)
  - `created_ctx = not rclpy.ok()` then conditional `rclpy.init()` (`replay.py:212-214`)
  - `node = rclpy.create_node("rosbagger_replayer")` (`replay.py:217`)
  - `sink, published = build_publish_sink(node)` (`replay.py:219`)
  - `replayer = Replayer(items, sink, rate=, loop=, duration=, max_messages=)` (`replay.py:223-230`)
  - `if start: replayer.seek(int(start * 1e9))` (`replay.py:231-232`) — the SECONDS→ns→seek precedent
  - `replayer.play(); replayer.run()` (`replay.py:233-234`); `return published["n"]` (`replay.py:235`)
  - `finally` best-effort `node.destroy_node()` + (only if `created_ctx`) `rclpy.shutdown()`
    (`replay.py:236-247`).

### Front door — `packages/rosbagger-replay/src/rosbagger_replay/__init__.py`
- `replay` / `replay_bag` (`__init__.py:72-86,132`), `build_publish_sink` (`:89-103`),
  `republish_static` (`:106-119`) are lazy delegators behind `_require_ros()` (`:55-69`).
  `replay_bag = replay` (`:132`) is the submodule-shadow-proof alias the CLI imports.
- Module top is ROS-free (`from .errors`, `from .fidelity`, `from .scheduler`, `from .source`
  only — `:27-30`). **No `__init__` change is needed for Phase 21** — `replay_bag` already
  forwards `**kwargs` straight to `replay()`, so new `replay()` params flow through unchanged.

### Scheduler — `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py`
- `Replayer` (`scheduler.py:55`). Mechanisms the region maps onto:
  - `seek(t_offset_ns)` (`scheduler.py:251-271`) — bag-relative ns; lands cursor on first
    `t_ns >= items[0].t_ns + t_offset_ns`; past-end = clean DONE.
  - `set_loop_region(in_ns, out_ns)` (`scheduler.py:274-288`) — ABSOLUTE t_ns bounds; normalizes
    lo/hi; `run()` wraps the snippet from past-`out_ns` back to first-at/after-`in_ns`
    (`scheduler.py:397-412`). DISTINCT from whole-bag `loop` (index-0 rewind), takes precedence.
  - `clear_loop_region()` (`scheduler.py:290-298`).
- The region wrap is a REPEAT (it loops the snippet), NOT a single-pass `[in,out]` stop. The
  scheduler's only bounded STOP is `max_messages` / `duration` (monotonic), NOT a t_ns horizon
  (`scheduler.py:384-389`) — same limitation the cli.py D-10 docstring records for `--end`.

## 2. Per-flag mapping (CONTEXT design, validated against the above)

| Flag | Library param (21-01) | Mechanism (anchor) |
|------|------------------------|--------------------|
| `--clock` | `publish_clock: bool=False` on `replay()` → `build_publish_sink(node, publish_clock=...)` | already wired in the sink (`replay.py:100-102,123-126`); just thread the param at `replay.py:219` |
| `--delay SEC` | `delay: float=0.0` on `replay()` → `time.sleep(delay)` AFTER node build, BEFORE `play()`/`run()` | inserted between `replay.py:219` (sink built, ctx up) and `:233` (`play()`); subscribers discover during the sleep |
| `--remap old:=new` | `remap: dict[str,str]\|None=None` on `replay()` → `build_publish_sink(node, remap=...)` | a NAME LOOKUP inside the existing sink: publish on `remap.get(item.topic, item.topic)` replacing the bare `item.topic` at `replay.py:109` — single publish path preserved |
| `--start-paused`/`-p` | `start_paused: bool=False` on `replay()` → SKIP `replayer.play()` | `Replayer` defaults to `State.PAUSED` (`scheduler.py:136`); not calling `play()` means `run()` publishes 0 and returns PAUSED — a run-to-completion CLI publishes nothing (parity/known-state flag; interactive resume is the GUI) |
| `--region-start`/`--region-end SEC` | `region_start: float\|None`, `region_end: float\|None` on `replay()` → `seek(int(region_start*1e9))` + `set_loop_region(int(region_start*1e9), int(region_end*1e9))` | reuses Phase-19 region (`scheduler.py:251,274`). Pair with `--loop` to repeat the snippet; SINGLE-PASS `[in,out]` stop deferred (mirrors `--end`-folded-into-`--duration`, `cli.py:24-34`) |

Deferred (SC3 — document as out-of-scope, do NOT implement): runtime ROS services `~/seek`,
`~/set_rate`, `~/play_next`, `~/burst`, `~/toggle_paused` (need a long-lived spinning node; the
GUI already provides interactive control); single-pass bounded-region t_ns stop;
`--qos-profile-overrides-path`, `--storage`, `--read-ahead-queue-size`, loaned messages.

## 3. Pitfalls

1. **CLI must stay THIN.** No publish logic in `cli.py`; each flag maps to a `replay()` /
   `build_publish_sink` param. `cli.py` top level stays typer+stdlib (the ROS import stays
   behind the lazy `from rosbagger_replay import replay_bag`, `cli.py:158`). Adding the new
   options must NOT introduce any ROS import at module top.
2. **`remap` is a NAME LOOKUP inside the existing sink — never a second sink.** Replace
   `item.topic` at the publisher-build line (`replay.py:109`) with
   `remap.get(item.topic, item.topic)` when `remap` is set; the `pubs` dict then keys on the
   REMAPPED name so one publisher per remapped target is built once. Static-tracker + /clock
   paths are unaffected (they key off `item.topic` / `item.t_ns`).
3. **`build_publish_sink` back-compat MUST hold.** Add `remap=None` as a NEW keyword-only param
   AFTER the existing `publish_clock`/`static_topics`. A no-kwargs `build_publish_sink(node)`
   call (and the 2-tuple `sink, published = ...` unpacking at `replay.py:219` +
   `replay_panel.py`) must be byte-for-byte unchanged.
4. **`start_paused` semantics for a run-to-completion CLI.** Skipping `play()` means `run()`
   returns immediately in PAUSED with 0 published — this is testable at the scheduler tier
   (a `Replayer` that is never `play()`-ed publishes nothing on `run()`) without ROS. Document
   that interactive resume lives in the GUI (no keyboard mode in this CLI — SC3 deferral).
5. **Region single-pass stop is NOT available without a new scheduler predicate.** Ship the
   `seek` + `set_loop_region` form (repeat with `--loop`) and DOCUMENT the single-pass stop as
   deferred — do not invent a t_ns-horizon stop (CONTEXT: keep it honest; mirror the `--end`
   precedent). The scheduler stays UNCHANGED (Phases 18/19/20 invariant).
6. **Lazy ROS everywhere.** `replay.py`'s `import rclpy` + the sink's `deserialize_message` /
   `get_message` stay inside function bodies. `time.sleep(delay)` uses stdlib `time` (add the
   `import` at the top of `replay.py` body or module top — stdlib is fine; prefer a body-local
   `import time` to keep the diff minimal, OR module top since `time` is stdlib). `import
   rosbagger_replay` must stay ROS-free AND Qt-free (`test_offline_guard.py`).
7. **`--remap` parse format.** `old:=new` (the `ros2 bag play` convention). Parse each
   repeatable `--remap` value by splitting on `:=`; reject a value WITHOUT exactly one `:=` (or
   an empty side) with a clean `typer.BadParameter` / `typer.Exit` — NOT a traceback. Build the
   dict in `cli.py` and forward it as `remap=`.
8. **SIGBUS-at-exit is a Qt teardown artifact** (memory `qt-offscreen-sigbus-at-teardown`):
   re-run / `--junitxml`; not a failure. The `-m live` tests are NOT required for the offline
   gate (skipped via `importorskip rclpy`).

## 4. Test plan

### 21-01 (library, offline + live)
- **Offline unit (no ROS):**
  - `start_paused` → 0 published: drive a pure `Replayer` (the `_items` builder,
    `test_replay_unit.py:162`) WITHOUT calling `play()`, call `run()`, assert the recording
    sink got 0 items and `state is PAUSED` — proving the "skip play()" mapping at the scheduler
    tier.
  - `remap` name lookup in `build_publish_sink`: drive the sink with a FAKE node recording
    `create_publisher(cls, topic, depth)` topic names + a fake `get_message`/`deserialize_message`
    (monkeypatch the lazy imports OR inject via a stub) and a fake `ReplayItem`; assert the
    publisher topic is the REMAPPED name when `remap={"/a":"/b"}` and the bare name otherwise.
    (If the fake-node route proves brittle, this collapses to the live proof — CONTEXT allows
    either.)
- **Offline guard:** `test_offline_guard.py` stays green (no new module-top ROS/Qt import).
- **Live (`-m live`, skipped offline):** mirror `test_replay_fidelity_live.py` /
  `test_replay_live.py` (external subscriber subprocess, own rclpy context, READY→COUNT on
  stdout, ~1s discovery settle): a subscriber on the NEW remapped name receives when the sink is
  built with `remap={old:new}`; a `/clock` subscriber receives with `publish_clock=True`.

### 21-02 (CLI, offline only)
- Mirror the existing CliRunner tests (`test_replay_unit.py:758-851`): `app`, `_runner`,
  monkeypatch `rosbagger_replay.replay_bag` with a spy recording `**kwargs`.
  - `--help` (exit 0) exposes `--clock`, `--delay`, `--remap`, `--start-paused` (+ `-p`),
    `--region-start`, `--region-end` (SC1), and DOCUMENTS the deferred runtime services (SC3).
  - each flag forwards the right kwarg to the spy: `--clock` → `publish_clock=True`; `--delay 2`
    → `delay=2.0`; `--start-paused`/`-p` → `start_paused=True`; `--region-start 1 --region-end 3`
    → `region_start=1.0, region_end=3.0` (SC2 mapping).
  - `--remap a:=b --remap c:=d` → `remap={"a":"b","c":"d"}`.
  - malformed `--remap foo` (no `:=`) → clean error (non-zero exit, no traceback escaping).
- **Phase gate (blended, offline):**
  `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest --cov=rosbagger_core --cov=bagq
  --cov=rosbagger_desktop --cov-fail-under=80` — green ≥80% (re-run on the benign SIGBUS).

## 5. Invariants carried in (CONTEXT §Hard invariants)
- CLI stays THIN; `cli.py` top level typer+stdlib only; ROS behind `_require_ros()`.
- `rosbagger_replay` no module-top ROS import; offline import graph ROS-free AND Qt-free.
- `build_publish_sink` stays the SINGLE publish path (remap = name lookup inside it);
  no-kwargs 2-tuple back-compat + Phase-20 defaults-off preserved.
- `scheduler.py` thread-safety/region (Phases 18/19) + Phase-20 fidelity UNCHANGED.
- ruff line length 100; worktrees OFF (run on main); gsd-verifier not installed (verify inline).

## 6. Plan split (matches CONTEXT)
- **21-01** (wave 1, `depends_on: []`) — `replay()` gains `delay` / `start_paused` /
  `publish_clock` / `remap` / `region_start` / `region_end`; `build_publish_sink` gains
  `remap`. Offline unit tests + offline guard + a `-m live` `--remap`/`--clock` proof.
- **21-02** (wave 2, `depends_on: [21-01]`) — `cli.py` gains `--clock` / `--delay` / `--remap` /
  `--start-paused`(`-p`) / `--region-start` / `--region-end`, parses `old:=new`, forwards to
  `replay_bag`, documents the deferred runtime services. CliRunner unit tests. Phase gate.
