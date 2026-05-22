---
phase: 02-bag-reader-layer
plan: 01
subsystem: reader
tags: [abc, dataclass, bag-reader, seam, offline-invariant, rosbags]

# Dependency graph
requires:
  - phase: 01-scaffold
    provides: uv workspace + editable rosbagger_core + empty reader/ seam + offline-guard test
provides:
  - "BagReader abc.ABC seam (open/close/read + topics/connections + concrete __enter__/__exit__)"
  - "Message frozen dataclass — the uniform per-message record (topic, t, t_ns, stamp, msgtype, msg)"
  - "reader/__init__.py public re-export of BagReader + Message"
affects: [02-02-rosbags-reader, 02-03-reader-tests, 03-schema-mapper, 04-inspect]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ABC seam with concrete context-manager lifecycle (open/close abstracts, shared __enter__/__exit__)"
    - "Frozen+slotted dataclass as the immutable record value object"
    - "Backend-agnostic interface module imports stdlib only (no rosbags/ROS) to preserve the offline invariant"

key-files:
  created:
    - packages/rosbagger-core/src/rosbagger_core/reader/base.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/reader/__init__.py

key-decisions:
  - "Loose Mapping[str, object] / Sequence[object] return types for topics/connections so base.py never names the rosbags TopicInfo/Connection NamedTuples (those arrive in 02-02)"
  - "__exit__ return type annotated bool and returns False (never swallow exceptions)"
  - "No from_anyreader factory or rosbags helper in base.py — backend-agnostic contract only"

patterns-established:
  - "ABC seam + shared lifecycle: abstract open/close/read, concrete __enter__/__exit__ inherited free"
  - "Interface-first phase: 02-01 defines the contract, 02-02 implements it, 02-03 tests it"

requirements-completed: [READ-04]

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 2 Plan 01: Bag Reader Seam Summary

**Stdlib-only BagReader ABC (open/close/read + topics/connections + a concrete context-manager lifecycle) and a frozen six-field Message record, re-exported from `reader/__init__.py` — the swappable, ROS-free contract that RosbagsReader (02-02) implements and 02-03 tests against.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-22T07:46:39Z
- **Completed:** 2026-05-22T07:48:59Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 rewritten)

## Accomplishments

- `reader/base.py`: `Message` is a `@dataclass(frozen=True, slots=True)` with exactly the six fields `topic, t, t_ns, stamp, msgtype, msg` in that order; immutable value object that every reader yields.
- `reader/base.py`: `BagReader(abc.ABC)` — abstract `open`/`close`/`read` + abstract `topics`/`connections` properties (metadata without full deserialization, for Phase 4 Inspect) + concrete `__enter__`/`__exit__` lifecycle inherited free.
- `base.py` imports only stdlib (`abc`, `dataclasses`, `collections.abc`) — no `rosbags`, no ROS — verified by a `sys.modules` scan; the abstract seam is importable without the heavy backend (offline invariant intact).
- `reader/__init__.py` re-exports `BagReader` + `Message` (no concrete reader yet); `import rosbagger_core` still does NOT load the reader subpackage, so the top-level package stays light/ROS-free.
- The load-bearing offline-guard test (`tests/test_offline_guard.py`) still passes (2/2).

## Task Commits

Each task was committed atomically:

1. **Task 1: Define BagReader ABC + Message dataclass in reader/base.py** — `5ed2c8b` (feat)
2. **Task 2: Re-export BagReader + Message from reader/__init__.py** — `ecaa771` (feat)

**Plan metadata:** committed separately with this SUMMARY + STATE.md + ROADMAP.md (docs commit).

## Files Created/Modified

- `packages/rosbagger-core/src/rosbagger_core/reader/base.py` (created, 112 lines) — `BagReader` ABC + `Message` frozen dataclass; the typed, backend-agnostic seam.
- `packages/rosbagger-core/src/rosbagger_core/reader/__init__.py` (rewritten) — replaced the Phase-1 placeholder docstring body with `from .base import BagReader, Message` + `__all__`.

## Decisions Made

- **`topics`/`connections` typed loosely as `Mapping[str, object]` / `Sequence[object]`.** The concrete `rosbags` `TopicInfo`/`Connection` NamedTuples are introduced in 02-02; base.py must not import `rosbags` to name them, so the abstract surface stays backend-agnostic.
- **`__exit__` returns `False`** (annotated `-> bool`) so reader exceptions are never silently swallowed by the context manager.
- **No `from_anyreader`/rosbags helper in base.py** — that adapter logic belongs to `RosbagsReader` (02-02). This file is the contract only.
- Followed the plan's interface spec verbatim (field names/order, abstract surface) — these were fixed in 02-RESEARCH.md Code Examples §2 and Pattern 1, not reinvented.

## Deviations from Plan

None affecting code behavior — both tasks were implemented exactly as specified.

One acceptance-criterion wording adjustment (not a code-behavior deviation):

**1. [Rule 3 - Blocking] Removed the bare token `RosbagsReader` from the `__init__.py` docstring**
- **Found during:** Task 2 (re-export)
- **Issue:** Task 2's acceptance criterion `grep -n "RosbagsReader" .../reader/__init__.py returns nothing` initially matched the word `RosbagsReader` inside explanatory docstring prose ("the concrete `RosbagsReader` lands in 02-02"). No actual import/re-export of the symbol existed — the criterion's intent (per the plan `<action>`: "Do NOT import `RosbagsReader` here") was already met — but the literal grep tripped on prose.
- **Fix:** Rephrased the docstring to "the concrete rosbags-backed reader" so the literal acceptance check passes unambiguously. No functional change.
- **Files modified:** `packages/rosbagger-core/src/rosbagger_core/reader/__init__.py`
- **Verification:** `grep -n "RosbagsReader" .../reader/__init__.py` now returns nothing; re-export + offline guard still pass.
- **Committed in:** `ecaa771` (part of Task 2 commit)

---

**Total deviations:** 1 (acceptance-criterion wording only; zero behavior change)
**Impact on plan:** None. The contract matches the plan's `<interfaces>` block verbatim; no scope creep.

## Issues Encountered

**Project-wide coverage gate (`--cov-fail-under=80`) now fails — EXPECTED and DEFERRED to 02-03.**

- **What:** The full suite (`PYTHONPATH="" uv run pytest`) reports 13/13 tests passing but fails the aggregate `--cov-fail-under=80` gate (drops to ~25%). Cause: `reader/base.py` (31 stmts) and `reader/__init__.py` (2 stmts) are legitimately added but have **no tests yet** — reader tests are explicitly scheduled for **plan 02-03** (per the 02-01 objective "02-03 tests against" and 02-RESEARCH.md).
- **Why this is not fixed here:**
  - The plan 02-01 has exactly two tasks (define base.py, re-export). Writing reader tests now is scope creep into 02-03.
  - The `>=80%` gate value is a **Phase-1-locked decision** (`pyproject.toml [tool.pytest.ini_options] addopts`, comment line 33-34). Weakening it would be a Rule-4 architectural change requiring sign-off — not silently done by an executor.
  - The dip is a known consequence of the planner's interface-first sequencing (02-01 contract → 02-02 impl adds covered code → 02-03 adds tests). It self-resolves at 02-03.
- **No commit hook impact:** there is no active git hook (no `.pre-commit-config.yaml`, only default samples), so the gate did not block either task commit. The gate lives in pytest `addopts` and will trip in **CI** until 02-03 lands.
- **Isolated signals all green:** offline-guard tests pass 2/2 (`--no-cov`); full suite passes 13/13 (`--no-cov`); `ruff check reader/` clean.

> **Action for the orchestrator/verifier:** Do NOT treat this phase as red on the coverage gate in isolation — it is a tracked, by-design transient. Expect green once 02-02 (RosbagsReader, covered code) and 02-03 (reader tests) land. Also logged as a STATE.md blocker.

## User Setup Required

None — no external service configuration required. This plan adds two stdlib-only modules; it installs no packages.

## Next Phase Readiness

- **Ready for 02-02 (`RosbagsReader`):** the `BagReader` ABC + `Message` record are the exact contract `RosbagsReader` implements; 02-02 imports `rosbags` at module level in `reader/rosbags_reader.py` and extends `__all__` here.
- **Ready for 02-03 (reader tests):** the typed seam is in place to test against; 02-03 will also close the coverage-gate gap noted above.
- **Blocker (tracked):** project-wide coverage gate fails in CI until reader tests land (02-03). See Issues Encountered.

## Self-Check: PASSED

- FOUND: `packages/rosbagger-core/src/rosbagger_core/reader/base.py`
- FOUND: `packages/rosbagger-core/src/rosbagger_core/reader/__init__.py`
- FOUND: `.planning/phases/02-bag-reader-layer/02-01-SUMMARY.md`
- FOUND commit `5ed2c8b` (Task 1)
- FOUND commit `ecaa771` (Task 2)

---
*Phase: 02-bag-reader-layer*
*Completed: 2026-05-22*
