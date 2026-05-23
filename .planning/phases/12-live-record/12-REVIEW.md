---
phase: 12-live-record
reviewed: 2026-05-23T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - packages/rosbagger-record/src/rosbagger_record/__init__.py
  - packages/rosbagger-record/src/rosbagger_record/discovery.py
  - packages/rosbagger-record/src/rosbagger_record/record.py
  - packages/rosbagger-record/src/rosbagger_record/cli.py
  - packages/rosbagger-record/src/rosbagger_record/errors.py
  - packages/rosbagger-record/pyproject.toml
  - pyproject.toml
  - tests/test_record_unit.py
  - tests/test_record_live.py
  - tests/test_offline_guard.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-05-23
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 12 adds the first live (ROS-requiring) workspace member, `rosbagger-record`: live topic discovery via `rclpy`, subset selection (pure-Python), raw-CDR subscription, and recording through `rosbag2_py.SequentialWriter`, plus a thin typer CLI. I reviewed all ten files at standard depth and cross-checked the project's headline invariants against the actual code and the existing `RosbagsReader` / `bagq` cli / conftest contracts.

**The headline invariant holds.** The offline-import boundary is implemented correctly and robustly: every `rclpy` / `rosbag2_py` / `rosidl_runtime_py` import lives inside a function body across `__init__.py`, `discovery.py`, `record.py`, and `cli.py`; `errors.py` is stdlib-only; `pyproject.toml` correctly omits ROS from `[project.dependencies]`; and `test_offline_guard.py::test_import_record_does_not_pull_ros` regression-locks it via a fresh `PYTHONPATH=""` subprocess that asserts the *import graph* (not just the ambient env) is ROS-free. The core/bagq guards are unchanged and still pass. The submodule-shadow aliases (`record_topics`/`list_record_topics`) are sound and correctly consumed by the CLI. The storage gate is parse-time-constrained (Enum) and fail-closed before any ROS graph spins. The `finally: writer.close()` finalization is correct and proven by a mocked test. The live test genuinely exercises an external-process publisher → bounded record → re-open via the v1 reader, asserting both count and topic.

The issues found are **correctness/robustness defects in the bounded-stop path** (none compromise the offline guarantee or risk a corrupt bag): a falsy-trap that silently turns `--duration 0` into an unbounded record, a wall-clock deadline that is not robust to clock steps, and a coverage gap that lets both ship untested. No Critical issues. No security vulnerabilities — user-supplied topic names and regex/exclude patterns are handled purely as data via stdlib `re`, never shell-interpolated or `eval`'d, and raw CDR bytes pass through without per-type deserialization.

## Warnings

### WR-01: `--duration 0` silently becomes an UNBOUNDED record (falsy-trap)

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:187`
**Issue:** The deadline is computed as `deadline = time.time() + duration if duration else None`. The guard `if duration` is a **truthiness** test, not an `is not None` test, so `duration == 0` (and `0.0`) evaluates falsy and yields `deadline = None`. A user who runs `--duration 0` (a plausible "record nothing / smoke-test the pipeline" or a programmatically-computed zero window) gets an **unbounded** record that only stops on SIGINT or `--max-messages`, the exact opposite of the requested bound.

This is also **internally inconsistent** with the sibling bound: `max_messages=0` is handled correctly because `_should_stop` uses `max_messages is not None` (so `0 >= 0` stops immediately), while `duration=0` does not stop. Two bounds, two different semantics for the same zero input. The public `record(..., duration=...)` and the CLI `--duration` both flow through this single line, so both are affected.

**Fix:** Use an explicit `None` check so a zero window is honored (it will stop on the first `_should_stop` check, since `now >= deadline` is immediately true):
```python
deadline = time.time() + duration if duration is not None else None
```
(Preferably switch `time.time()` to `time.monotonic()` at the same time — see WR-02.)

### WR-02: Bounded-record deadline uses wall clock (`time.time()`), not monotonic

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:187,191`
**Issue:** The `--duration` deadline is built from `time.time()` (the wall clock) and re-read with `time.time()` each spin. Wall-clock time is not monotonic: an NTP step, a manual `date` change, a VM resume, or a leap-second smear during the record window can jump the clock backward or forward. A backward step pushes the effective deadline into the future (the bounded record runs longer than requested, or effectively never reaches the deadline); a forward step ends it early. For a recording tool whose bounded window is a correctness guarantee (and which the live test relies on for determinism), the deadline must be measured against a monotonic clock that is immune to wall-clock adjustments.

**Fix:** Use `time.monotonic()` for both the deadline construction and the per-spin comparison. `_should_stop` already takes `now` and `deadline` as opaque floats, so only `_run` changes:
```python
deadline = time.monotonic() + duration if duration is not None else None
try:
    while rclpy.ok():
        if _should_stop(
            counter["n"], time.monotonic(), max_messages=max_messages, deadline=deadline
        ):
            break
        rclpy.spin_once(node, timeout_sec=0.05)
```

### WR-03: The `_run` bounded-stop loop (and the `duration` falsy bug) ships with zero test coverage

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:164-196`; `tests/test_record_unit.py`
**Issue:** `_should_stop` is unit-tested thoroughly in isolation (`test_should_stop_*`), but `_run` itself — the function that actually computes `deadline = time.time() + duration if duration else None` and drives the spin loop — is **never executed by any test**. The mocked `record()` tests monkeypatch `_run` away entirely (`test_record_finalizes_writer_when_loop_raises` replaces it with `boom`; the empty-selection test bails before reaching it), and the live test only exercises the `--max-messages` path, never `--duration`. Consequently the WR-01 falsy bug (and any future regression in the deadline arithmetic or the loop's check-before-spin ordering) is invisible to the offline suite. `_run` is pure-Python orchestration around a single mockable `rclpy` (the same `MagicMock` injection the other tests use), so it is unit-coverable offline despite the docstring framing the spin wiring as "live-only."

**Fix:** Add a mocked unit test that drives `_run` with `rclpy` injected and asserts the duration path. Make `rclpy.ok()` return True and `spin_once` a no-op, advance a fake clock (monkeypatch `record.time`), and assert the loop terminates at the deadline — and add a regression case asserting `duration=0` stops immediately rather than looping unbounded. Example skeleton:
```python
def test_run_stops_at_duration_deadline(monkeypatch):
    import rosbagger_record.record as ri
    fake_rclpy = MagicMock(); fake_rclpy.ok.return_value = True
    monkeypatch.setitem(sys.modules, "rclpy", fake_rclpy)
    clock = iter([100.0, 100.0, 100.06])  # build, check#1 (<deadline), check#2 (>=)
    monkeypatch.setattr(ri.time, "time", lambda: next(clock))
    ri._run(MagicMock(), {"n": 0}, duration=0.05)  # must return, not hang
```

### WR-04: Empty-selection `ValueError` reaches the user as a raw traceback, not a teaching line

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:260-267`; `packages/rosbagger-record/src/rosbagger_record/cli.py:99-103`
**Issue:** When a user records a topic that is not currently being published (a typo, or a publisher that has not come up), `record()` raises a `ValueError` with a carefully written teaching message ("No live topics matched ... Run `rosbagger-record list` ... or pass --all"). But `@_capability_errors` deliberately catches only `(RosNotAvailableError, McapStorageUnavailableError)` and explicitly does *not* swallow this `ValueError` (documented at cli.py:99-103). So the most common day-one user mistake — naming a topic that is not (yet) published — surfaces as a full Python **traceback** with `ValueError:` at the bottom, contradicting the module's own stated "errors that teach / the difference between a tool and a script" philosophy. The well-crafted teaching message is buried under a stack trace it was written to replace.

This is a judgment call the code makes consciously, hence Warning not Blocker, but the rationale ("a usage error that benefits from the full message", "rare in practice") is weak: an empty-selection mistake is *more* common than a missing ROS install for a user who has already sourced ROS, and the full message is exactly as useful printed as one clean red line. Either the typed-error treatment should extend to this case, or the decision should be re-examined.

**Fix:** Promote the empty-selection failure to a teaching capability error (or a dedicated typed error) and add it to the `@_capability_errors` tuple so it prints as a single stderr line + `Exit(1)`, mirroring `bagq`'s `UnknownTableError`:
```python
# errors.py
class NoTopicsMatchedError(RuntimeError): ...
# record.py: raise NoTopicsMatchedError(...) instead of ValueError(...)
# cli.py: except (RosNotAvailableError, McapStorageUnavailableError, NoTopicsMatchedError) as e:
```
If the current behavior is truly intended, document the user-facing traceback explicitly in the CLI help so the choice is visible.

## Info

### IN-01: Calling the impl `record.record()` with ROS absent raises raw `ImportError`, not the teaching error

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:244-246`
**Issue:** Inside `record()` (the impl), `import rclpy` (line 244) runs before `_check_storage` and before any guard. The teaching `RosNotAvailableError` is only produced by `_require_ros()` in the package front door (`__init__.py`), which the CLI and the public API correctly go through. But any caller that imports and calls `rosbagger_record.record.record(...)` directly in a ROS-free env gets a bare `ModuleNotFoundError: No module named 'rclpy'`. This is acceptable (the impl module is "internal", and the front door is the documented entry), but it is a latent footgun for the Phase-14 GUI or a user script that reaches for the impl. The submodule-shadow comment in `__init__.py` even anticipates callers importing the submodule.
**Fix:** Optional — either call `_check_storage` first (it already lazy-imports `rosbag2_py` and would surface a capability error path) is orthogonal; the cleaner option is to note in the `record.py` module docstring that the package front door (`rosbagger_record.record` / `record_topics`) is the only supported entry and the impl assumes ROS is present.

### IN-02: `discover_topics` ignores `spin_once` return / cannot observe a never-settling graph

**File:** `packages/rosbagger-record/src/rosbagger_record/discovery.py:48-51`
**Issue:** The settle loop spins a fixed `settle_iters` (default 30 × 20ms = ~0.6s) unconditionally and then snapshots the topic map once. There is no early exit once topics appear and no signal if discovery never populates — a slow DDS graph that needs >0.6s is silently under-discovered, and the only feedback is an empty/partial map downstream. This is a deliberate, documented heuristic (12-RESEARCH Pattern 3), so it is Info, not a defect, but the fixed window is a reliability ceiling worth a comment for future tuning (e.g. discover, and if empty, extend the settle).
**Fix:** Optional — none required for this phase. If flakiness appears on slower graphs, consider polling until the map is non-empty up to a max budget rather than a fixed iteration count.

### IN-03: `_make_writer` / `record` do not guard an already-existing output bag path

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:99-118,268`
**Issue:** `out` is passed straight to `StorageOptions(uri=out)` with no pre-check. If the path already exists, `rosbag2_py` raises (surfacing as a non-teaching traceback, since it is not in the `@_capability_errors` set). The `finally` blocks still finalize correctly (no corruption), so this is not a Blocker, but the failure mode is opaque relative to the rest of the module's teaching-error discipline.
**Fix:** Optional — consider an explicit pre-check (`if Path(out).exists(): raise <teaching error>`) so an existing-output mistake reads cleanly, consistent with WR-04's recommendation.

### IN-04: `_check_storage` membership test relies on `get_registered_writers()` returning a real container

**File:** `packages/rosbagger-record/src/rosbagger_record/record.py:65-67`
**Issue:** `storage_id not in available` and `sorted(available)` assume `get_registered_writers()` returns an iterable/sized container (verified to be the case on the target box, and the tests mock it as a `set`). This is correct against the documented rosbag2 API; flagged only as an Info note that the contract is implicit (no isinstance/None guard) — if a future rosbag2 returned `None` or a generator, `sorted()` / `in` would misbehave. No action needed for supported versions.
**Fix:** None required. The verified-API assumption is reasonable for a ROS-runtime-bound helper.

---

_Reviewed: 2026-05-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
