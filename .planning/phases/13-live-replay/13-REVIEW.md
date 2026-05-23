---
phase: 13-live-replay
reviewed: 2026-05-23T00:00:00Z
depth: deep
files_reviewed: 7
files_reviewed_list:
  - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
  - packages/rosbagger-replay/src/rosbagger_replay/errors.py
  - packages/rosbagger-replay/src/rosbagger_replay/source.py
  - packages/rosbagger-replay/src/rosbagger_replay/scheduler.py
  - packages/rosbagger-replay/src/rosbagger_replay/replay.py
  - packages/rosbagger-replay/src/rosbagger_replay/cli.py
  - packages/rosbagger-replay/pyproject.toml
findings:
  critical: 0
  warning: 7
  info: 6
  total: 13
status: issues_found
---

# Phase 13: Live Replay - Code Review Report

**Reviewed:** 2026-05-23
**Depth:** deep (cross-file: __init__ → replay → scheduler → source; tests as contract evidence)
**Files Reviewed:** 7 production source files (+ 3 test files as supporting evidence)
**Status:** issues_found

## Summary

Phase 13 adds the `rosbagger-replay` package: a lazy-ROS front door (`__init__.py`),
teaching errors (`errors.py`), a pure raw-CDR source seam (`source.py`), a pure
transport state machine (`scheduler.py`), the single rclpy publish module
(`replay.py`), and a thin typer CLI (`cli.py`).

I reviewed against the six project invariants. The architectural seams are sound:

- **Invariant 1 (offline import boundary):** HELD. No module-top `rclpy`/`rosbag2_py`/`rosidl_runtime_py` import exists in `__init__.py`, `errors.py`, `source.py`, or `scheduler.py`. Every ROS import is inside a function body (`_require_ros`, `replay()`). The offline-guard tests (`test_import_replay_does_not_pull_ros`, submodule guard) regression-lock it. **No CRITICAL finding here.**
- **Invariant 2 (pure source/scheduler):** HELD. `source.py` imports `rosbags` only, lazily; `scheduler.py` is stdlib-only.
- **Invariant 4 (transport correctness):** Mostly correct, but the `run()` state machine has real edge-case defects in step pacing, the no-items seek case, and a duplicated guard (see WR-01..WR-03).
- **Invariant 3 (try/finally cleanup):** Present, but has a leak path on a `rclpy.init()` double-init and a swallowed-error-during-cleanup concern (WR-04, WR-05).

**No CRITICAL issues found.** The offline boundary — the load-bearing security/architecture invariant of this codebase — holds, and there is no injection/secret/eval/path-traversal surface (the CLI forwards parsed values into a pure-Python API; topic/regex args are never shelled out). The findings below are correctness and robustness defects (WARNING) plus quality nits (INFO).

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `step()` blocks for the full inter-message gap before publishing

**File:** `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py:181-198`
**Issue:** `step()` sets state to `STEPPING`, and `run()` then executes the SAME pacing path as `play()`: for `cursor > 0` it calls `self._sleep(max(0.0, dt_ns / 1e9 / self._rate))` BEFORE publishing the single stepped item. A "step" is an interactive single-advance control (D-09: "publishes exactly the next message then re-pauses"). Sleeping the inter-message Δt first means a step across a 5-second gap blocks the caller for ~5 seconds (or 5/rate) before the one message appears. That is not single-step semantics — step should publish immediately, not pace. The unit tests use `sleep=lambda s: None`, so they never observe this; the bug is invisible to the offline suite.
**Fix:** Skip pacing when stepping — pace only in `PLAYING`:
```python
if self._cursor > 0 and self._state is State.PLAYING:
    dt_ns = self._items[self._cursor].t_ns - self._items[self._cursor - 1].t_ns
    self._sleep(max(0.0, dt_ns / 1e9 / self._rate))
```

### WR-02: `seek()` with `t_offset_ns <= 0` on a non-empty stream still indexes `self._items[0]` correctly, but `seek()` semantics break for a list whose first `t_ns` is itself the baseline only — relative-seek baseline is recomputed every call and is not loop-stable

**File:** `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py:154-159`
**Issue:** `seek(t_offset_ns)` computes `t0 = self._items[0].t_ns` every call and lands the first item with `t_ns >= t0 + t_offset_ns`. After a `loop=True` wraparound the cursor is reset to `0` directly (line 201), never via `seek`, so the baseline is consistent there. But there is a subtler contract gap: `seek` is documented as the SOLE position-setter, yet `run()`'s loop-reset sets `self._cursor = 0` directly — bypassing `seek`. That is fine functionally, but it means an offset-seek is NOT preserved across a loop wrap (a user who seeked to 5s then enabled loop will, on wrap, restart at index 0, not re-seek to 5s). This may be intended, but it is undocumented and the asymmetry ("seek is the only position-setter" vs. the loop-reset writing the cursor directly) is a latent surprise.
**Fix:** Document the loop-reset-vs-seek behavior explicitly (loop restarts at index 0, not at the last seek target), or route the loop reset through a private `_set_cursor(0)` so the single-position-setter invariant is literally true. At minimum add a docstring note on `loop`.

### WR-03: Duplicated up-front bound guard in `run()` — `duration` is checked twice with no intervening state change

**File:** `packages/rosbagger-replay/src/rosbagger_replay/scheduler.py:171-180`
**Issue:** `run()` calls `start_clock = self._clock()` then immediately checks `(self._clock() - start_clock) >= self._duration`. With a real `time.monotonic` clock this evaluates to `~0 >= duration`, so for any `duration > 0` it is a guaranteed no-op (only `duration <= 0` trips it). The block exists solely to handle `duration <= 0` and `max_messages <= 0`. That is correct but the second `self._clock()` call wastes a clock read AND, more importantly, with the injected `_FakeClock` it consumes a tick — which is exactly why a test had to be reworked (per 13-02-SUMMARY deviation 2). The duplicated, tick-consuming guard makes the duration semantics dependent on how many times `_clock()` is called, which is fragile.
**Fix:** Special-case the zero/negative bounds without re-reading the clock:
```python
if self._max_messages is not None and self._max_messages <= 0:
    self._state = State.DONE
    return
if self._duration is not None and self._duration <= 0:
    self._state = State.DONE
    return
start_clock = self._clock()
```
This removes the extra clock read and makes the bound independent of clock-call count.

### WR-04: `rclpy.init()` is unconditional — re-entry / pre-initialized context leaks or crashes

**File:** `packages/rosbagger-replay/src/rosbagger_replay/replay.py:89,128`
**Issue:** `replay()` calls `rclpy.init()` unconditionally and `rclpy.shutdown()` in `finally`. If the process already has an initialized rclpy context — the Phase-14 GUI is explicitly named as a caller of this same `replay_bag()` front door, and a GUI typically owns its own long-lived rclpy context — then `rclpy.init()` raises (or, in some rclpy versions, the `shutdown()` in `finally` tears down the GUI's context out from under it). Invariant 3 ("no path leaks an initialized ROS context") is violated in the re-entrant case: the caller's context is shut down by replay's `finally`. The live test calls it exactly once so this never surfaces in CI.
**Fix:** Guard init/shutdown so replay only manages the context it created:
```python
created_ctx = not rclpy.ok()
if created_ctx:
    rclpy.init()
...
finally:
    if node is not None:
        node.destroy_node()
    if created_ctx:
        rclpy.shutdown()
```

### WR-05: Cleanup in `finally` can mask the original publish exception

**File:** `packages/rosbagger-replay/src/rosbagger_replay/replay.py:123-128`
**Issue:** The `finally` calls `node.destroy_node()` then `rclpy.shutdown()` with no protection. If `replay`/`publish` raised (the path the `finally` exists for), and `node.destroy_node()` or `rclpy.shutdown()` ALSO raises (not uncommon when a context is already torn down or a publisher is mid-flight), the cleanup exception replaces the original — the user sees a confusing rclpy teardown error instead of the real failure, and `destroy_node()` may be skipped if it is `shutdown()` that throws (here destroy runs first, so a `shutdown()` raise leaves the node destroyed but masks the cause). 
**Fix:** Make cleanup best-effort and preserve the primary error:
```python
finally:
    if node is not None:
        try:
            node.destroy_node()
        except Exception:
            pass
    try:
        rclpy.shutdown()
    except Exception:
        pass
```

### WR-06: `set(topics)` in the CLI silently de-duplicates and drops topic ordering; an explicitly-empty `--topics ""` is treated as "all topics"

**File:** `packages/rosbagger-replay/src/rosbagger_replay/cli.py:162`
**Issue:** The CLI passes `topics=set(topics) if topics else None`. The `if topics` truthiness test means an empty list (`topics == []`) — and also a list containing only empty strings is not caught — maps to `None` ("publish everything"). More importantly, if a user passes `--topics ""` (empty string), it becomes `{""}`, which matches no connection and short-circuits to the `NoMessagesToReplayError` — acceptable. The genuine defect: `if topics` conflates "no `--topics` given" (`None` → all) with "given an empty selection." typer with `list[str] | None` yields `None` when omitted and `[]` is not reachable from the CLI, so the practical risk is low, but the `if topics else None` idiom is the WR-01-class truthiness trap the scheduler explicitly avoids (`is not None`). For consistency and to avoid a future regression if the option default changes, use an explicit `None` check.
**Fix:**
```python
topics=set(topics) if topics is not None else None,
```
(Behavior for omitted `--topics` is unchanged; the change removes the truthiness conflation.)

### WR-07: `published["n"]` count can diverge from the scheduler's authoritative count under `loop=True`

**File:** `packages/rosbagger-replay/src/rosbagger_replay/replay.py:91,106,122`
**Issue:** `replay()` returns `published["n"]`, incremented inside the sink. The scheduler also tracks its own `published` counter for the `max_messages` bound. These are independent counters that happen to agree only because the sink is called exactly once per scheduler publish. That coupling is correct today, but the returned value is the SINK's count, not the scheduler's — if a future sink ever drops/filters a message (e.g., a publisher creation failure caught and skipped), the returned count would silently disagree with what the scheduler believes it published, and the `max_messages` bound would over-run. The two-counter design is fragile. Lower severity because today they cannot diverge.
**Fix:** Either return the scheduler's count (expose `replayer` published count) or document that the sink is the source of truth and the scheduler bound counts sink invocations, not successful publishes.

## Info

### IN-01: `source.py` detects ROS 1 connections via fragile class-name string comparison

**File:** `packages/rosbagger-replay/src/rosbagger_replay/source.py:108-109`
**Issue:** `is_ros1 = type(ext).__name__ == "ConnectionExtRosbag1"` keys off a stringified class name. If `rosbags` renames or relocates that class (it is an internal type), the bridge silently stops running and ROS 1 wire bytes would be passed through as if they were CDR — a wrong-format publish that `deserialize_message` would later reject at runtime in the live path. An `isinstance` against the imported type is more robust.
**Fix:** Import the type and use `isinstance(ext, ConnectionExtRosbag1)` (still lazily, inside the function), or guard on a `rosbags`-public attribute rather than the class name.

### IN-02: `default_typestore: object = None` types away the real `rosbags` typestore type

**File:** `packages/rosbagger-replay/src/rosbagger_replay/source.py:67`; `replay.py:46`
**Issue:** Typing the typestore as `object` to keep the offline boundary clean is understandable (avoids a top-level `rosbags` import for the annotation), but `object` gives callers no type help and would mask a wrong-type argument. A `from __future__ import annotations` is already present, so a string/`TYPE_CHECKING` annotation would not bind `rosbags` at runtime.
**Fix:** Use a `TYPE_CHECKING`-guarded import and annotate as `"Typestore | None"` so the offline import stays clean but the type is accurate.

### IN-03: `pubs: dict[str, tuple]` loses the tuple's element types

**File:** `packages/rosbagger-replay/src/rosbagger_replay/replay.py:95`
**Issue:** `dict[str, tuple]` (untyped tuple) gives no static guarantee that the stored value is `(msg_cls, publisher)`. The unpacking `cls, pub = pubs[item.topic]` would not be type-checked.
**Fix:** Annotate as `dict[str, tuple[type, object]]` or a small named tuple/dataclass.

### IN-04: Magic QoS depth `10` is an unexplained literal at the call site

**File:** `packages/rosbagger-replay/src/rosbagger_replay/replay.py:102`
**Issue:** `node.create_publisher(cls, item.topic, 10)` hard-codes the QoS depth as a bare `10`. It is documented in the docstring as "sane default QoS (depth-10 RELIABLE VOLATILE)", but the literal at the call site is a magic number; a named constant (`_DEFAULT_QOS_DEPTH = 10`) self-documents and is the single edit point when per-topic QoS lands (the deferred enhancement).
**Fix:** Hoist to a module constant with a brief comment.

### IN-05: `_as_path_list` re-implements path coercion that already exists in `RosbagsReader`

**File:** `packages/rosbagger-replay/src/rosbagger_replay/source.py:52-60`
**Issue:** The docstring notes this "mirrors `RosbagsReader.__init__` coercion." Two copies of the same str/Path/iterable normalization will drift. Minor duplication; acceptable for the offline-isolation goal (importing the reader is heavier), but worth a note.
**Fix:** Consider exposing the coercion helper from `rosbagger_core` if it is ever needed in a third place; otherwise leave as-is with the existing cross-reference comment.

### IN-06: Live test's 8s subscriber hard-cap can flake under slow DDS discovery

**File:** `tests/test_replay_live.py:104,147,160`
**Issue:** The subscriber spins for a fixed `~8s` hard cap and the parent sleeps `1.0s` for discovery before publishing and `1.0s` after. On a loaded CI box or slow DDS discovery, an 8s window plus fixed sleeps is a timing assumption that can flake (receive < N_IMU). Not a correctness bug in production code (test-only), and the test is gated/skipped offline, but it is a determinism risk for the SC1 sign-off run.
**Fix:** Poll for `count >= N_IMU` with a generous timeout and break early, rather than a fixed window; or assert `received >= N_IMU` if over-delivery from a prior run is impossible (it is, given fresh contexts).

---

_Reviewed: 2026-05-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
