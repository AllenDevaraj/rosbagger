---
phase: 12-live-record
plan: 03
subsystem: rosbagger-record (thin CLI + the live SC1/SC2/SC3 proof)
tags: [record, live, cli, typer, rclpy, rosbag2_py, sqlite3, reopen, offline-boundary, parse-time-choice]
requires:
  - rosbagger-record/__init__.py (lazy _require_ros boundary + record()/list_topics() front doors from 12-01/12-02)
  - rosbagger-record/record.py (the verified discover→select→raw-subscribe→SequentialWriter→bounded-stop→finalize core from 12-02)
  - rosbagger-record/discovery.py (discover_topics + pure select_topics from 12-01)
  - rosbagger-record/errors.py (RosNotAvailableError / McapStorageUnavailableError teaching errors from 12-01)
  - rosbagger-core/reader/rosbags_reader.py (the v1 RosbagsReader(default_typestore=...) SC3 re-open contract)
  - tests/test_record_unit.py (12-01/12-02 mocked harness + no_ros fixture — EXTENDED with CLI tests)
  - bagq/cli.py (the thin typer app + @teaching_errors idioms MIRRORED)
provides:
  - rosbagger_record.cli:app (the console-script target `rosbagger-record` — `list` verb + `record` verb over the API)
  - rosbagger_record.cli.Storage (a str Enum {mcap,sqlite3} — the parse-time-constrained --storage choice, W2)
  - rosbagger_record.record_topics / list_record_topics (submodule-shadow-proof front-door aliases)
  - record() now threads all_topics/regex/exclude into its single select_topics call (D-07 over one orchestrator)
  - tests/test_record_live.py (the LIVE SC1/SC2/SC3 proof: external publisher → bounded record → re-open via v1 reader)
affects:
  - Phase 14 GUI Record panel (capability-gates over the SAME record()/list_topics() API; the CLI is the other thin face)
  - closes REC-01 (the offline↔live closing loop is now proven end-to-end on this box)
tech-stack:
  added:
    - "No new uv-resolved deps — typer was already declared in 12-01's pyproject; rclpy/rosbag2_py stay environment-provided"
  patterns:
    - "Parse-time-constrained CLI choice: --storage is a str Enum {mcap,sqlite3} so an invalid value is REJECTED during click parsing (exit 2) BEFORE any ROS work — the threat-model T-12-02 claim made real (W2)"
    - "Submodule-shadow-proof front door: `record_topics`/`list_record_topics` alias the __init__ FUNCTIONS so callers resolve the function even after `import rosbagger_record.record` rebinds the bare `record` attribute to the MODULE (a latent footgun fixed for the CLI/GUI/user scripts)"
    - "Thin CLI capability-error wrapper: @_capability_errors catches ONLY RosNotAvailableError + McapStorageUnavailableError → clean red stderr line + Exit(1); no bare except Exception (real bugs still traceback) — mirrors bagq's teaching_errors"
    - "External publisher as a SUBPROCESS for the live test: its own rclpy context (no double rclpy.init clash with record()) AND a genuinely external graph participant, so the recorder's DDS settle is really exercised"
    - "SC3 re-open defensively passes default_typestore=ROS2_HUMBLE: required for the sqlite3 backend, a harmless no-op for self-describing MCAP (12-RESEARCH Pitfall 2 / Open Q1)"
key-files:
  created:
    - packages/rosbagger-record/src/rosbagger_record/cli.py
    - tests/test_record_live.py
  modified:
    - packages/rosbagger-record/src/rosbagger_record/__init__.py
    - packages/rosbagger-record/src/rosbagger_record/record.py
    - tests/test_record_unit.py
decisions:
  - "SELECTION THREADING (the plan's explicit choice point): record() stays the SINGLE orchestrator. Extended record()'s signature with all_topics/regex/exclude and threaded them straight into its existing select_topics(discovered, ...) call. The CLI forwards flags only — it does NOT call discovery itself nor re-implement selection (API-first, D-02). Chosen over 'CLI pre-resolves then passes a topic list' because that would split the discover→select orchestration across two layers."
  - "--storage is a str Enum (Storage{MCAP,SQLITE3}), NOT a bare str (W2). An invalid --storage value fails at PARSE time (click usage error, exit 2) before any ROS graph spins — making the parse-time constraint the threat model claims real. Default Storage.MCAP (D-08 not weakened)."
  - "Added submodule-shadow-proof aliases record_topics/list_record_topics in __init__.py (Rule 1 fix). `from rosbagger_record import record` resolves to the MODULE (not the function) once `rosbagger_record.record` (the submodule) is imported anywhere in the process — which the unit tests do. The CLI imports the aliases so the front-door FUNCTION resolves regardless of import order; the bare record/list_topics stay the documented public API for the common (submodule-not-pre-imported) case."
  - "Task 3 made NO production-code change: the offline suite + ruff + offline guard + uv sync were all green as-is, so the allowed 'small lint nit' edit to test_record_unit.py was unnecessary. The phase gate is a pure verification capstone (no commit of its own)."
  - "REC-01 marked COMPLETE: the CLI ships and the live lane actually ran on this box (SC1/SC2/SC3 proven via sqlite3; MCAP skipif-guarded), closing the offline↔live loop the phase exists for."
metrics:
  duration: ~10min
  tasks: 3
  files: 5
  completed: 2026-05-23
---

# Phase 12 Plan 03: Thin rosbagger-record CLI + the Live SC1/SC2/SC3 Proof Summary

Shipped the thin `rosbagger-record` console script (`list` verb prints discoverable topics+types; `record` verb records a selected subset over the Plan-02 `record()` API with `--all`/`--regex`/`--exclude`/`-o`/`--storage`/`--duration`/`--max-messages`) and the LIVE integration test that closes the offline↔live loop — an external `std_msgs/String` publisher → bounded `record()` → re-open + iterate via the EXISTING v1 `RosbagsReader(default_typestore=ROS2_HUMBLE)` — then RAN the live lane on this ROS-sourced box (**2 passed, 1 skipped**) proving SC1/SC2/SC3 via the sqlite3 path with the MCAP-specific assertion `skipif`-guarded, all while keeping the CLI thin + import-ROS-free and the offline suite green at 97.37%.

## What Was Built

- **`cli.py` — the thin `rosbagger-record` CLI (Task 1).** A `typer.Typer` app mirroring `bagq/cli.py`: module top imports ONLY `__future__` + stdlib `enum`/`functools` + `typing.Annotated` + `typer` (NO `rclpy`/`rosbag2_py`, NO eager package-API import — the API is lazy-imported INSIDE each command body, behind the package's `_require_ros()` boundary). Two verbs:
  - **`list`** (SC1, D-06) — lazy-imports the front door, calls `list_record_topics()`, prints each `topic\ttype` line sorted; an empty graph prints `no topics discovered`.
  - **`record`** (D-07/D-08/D-09) — positional `topics` (optional, for `--all`); `-o/--output` (required); `--all`/`--regex`/`--exclude` selection flags; `--storage` (the `Storage` Enum, default `mcap`); `--duration`/`--max-messages` bounded-stop. Forwards everything to `record_topics(...)` and prints the captured count.
  - **`@_capability_errors`** — the `bagq.teaching_errors` analog: catches ONLY `RosNotAvailableError` + `McapStorageUnavailableError` → a single red stderr line + `Exit(1)`, no traceback. No bare `except Exception` (real bugs still traceback).
- **`record()` selection threading (Task 1, `record.py`).** Extended `record()` with `all_topics`/`regex`/`exclude` keyword params, threaded straight into its single `select_topics(discovered, ...)` call, so the CLI's `--all`/`--regex`/`--exclude` reach the pure filter while `record()` remains the single discover→select→record orchestrator (the CLI re-implements none of it).
- **`__init__.py` shadow-proof aliases (Task 1).** `record_topics = record` / `list_record_topics = list_topics` — see the deviation below; the CLI imports these so the front-door FUNCTION resolves even after the `record` submodule is imported.
- **`tests/test_record_unit.py` EXTENDED with 8 CLI tests (Task 1)** — typer `CliRunner`, ENV=offline: `--help` for the app + both verbs exit 0; `record --help` shows `--storage` + the `mcap` default; `--storage bogus` is rejected at PARSE time (exit 2); `record` with no `-o` is a parse error (exit 2); `list`/`record` with ROS absent (paired with the `no_ros` meta-path blocker) exit cleanly via `Exit(1)` — `result.exception` is `SystemExit`, never the raw `RosNotAvailableError`; the `Storage` Enum value set is exactly `{mcap, sqlite3}`.
- **`tests/test_record_live.py` — the LIVE SC1/SC2/SC3 proof (Task 2).** `pytest.importorskip("rclpy")` at the top + `pytestmark = pytest.mark.live` so the offline CI skips the whole module; a `sys.path` belt-and-suspenders src prepend for the ROS-sourced lane. An external publisher SUBPROCESS publishes `std_msgs/String` on `/telemetry` at ~20 Hz (own rclpy context). Three tests:
  - **SC1** — `list_record_topics()` discovers `/telemetry` with type `std_msgs/msg/String`.
  - **SC2+SC3 (sqlite3)** — `record_topics([TOPIC], out, storage="sqlite3", max_messages=5)` captures exactly 5 frames; the bag re-opens via `RosbagsReader(out, default_typestore=get_typestore(Stores.ROS2_HUMBLE))` yielding 5 messages ALL on `/telemetry` (asserts BOTH count AND topic — T-12-06). This is the one that RUNS on this box.
  - **SC2+SC3 (mcap)** — the same proof via `storage="mcap"`, decorated `@pytest.mark.skipif(not _mcap_available(), ...)` where `_mcap_available()` checks `"mcap" in rosbag2_py.get_registered_writers()`. SKIPS here (the MCAP plugin is not installed), proving the LOCKED D-08 path where present.

## Selection Threading (the plan's explicit choice point)

The plan asked to "pick the path that keeps `record()` the single orchestrator and document it." **Chosen: extend `record()`'s signature** with `all_topics`/`regex`/`exclude` (keyword-only) and thread them into its existing `select_topics(discovered, topics=topics, all_topics=..., regex=..., exclude=...)` call. The CLI is then a pure pass-through: it parses flags and forwards them, never calling `discover_topics` itself nor re-implementing the base→regex→exclude precedence (which stays entirely in `select_topics`). The rejected alternative — having the CLI discover + resolve a concrete topic list then pass `topics=[...]` — would have split the discover→select orchestration across the CLI and the API, contradicting the API-first single-orchestrator intent (D-02). The empty-selection teaching `ValueError` message was widened to name all four selector inputs.

## --storage as a parse-time-constrained choice (W2)

`--storage` is a `class Storage(str, enum.Enum)` with members `MCAP="mcap"` / `SQLITE3="sqlite3"`, default `Storage.MCAP`. typer renders it as a `[mcap|sqlite3]` choice and click REJECTS any other value during PARSING — `rosbagger-record record /t -o out --storage bogus` exits 2 (usage error) BEFORE any ROS graph spins up. This makes the parse-time constraint the threat model claims (T-12-02) real; a bare `str` option would have accepted `bogus` and only failed deep inside `_check_storage`. Subclassing `str` lets the member pass straight to `record(storage=storage.value)`. D-08's `mcap` default is preserved (not weakened).

## LIVE LANE — the exact command + result (W4)

**Command run (this box IS ROS-equipped):**
```bash
source /opt/ros/humble/setup.bash && \
PYTHONPATH="$PWD/packages/rosbagger-record/src:$PWD/packages/rosbagger-core/src:$PWD/packages/bagq/src:$PWD/tests:$PYTHONPATH" \
  python3 -m pytest tests/test_record_live.py -m live -v --no-cov
```

**Result: `2 passed, 1 skipped in 5.00s`** (ran AUTONOMOUSLY in this harness; verified deterministic across reruns):

| Test | Outcome | Proves |
|------|---------|--------|
| `test_sc1_list_discovers_external_topic` | **PASSED** | SC1 — `/telemetry` + `std_msgs/msg/String` discovered after the settle |
| `test_sc2_sc3_record_sqlite3_then_reopen_via_v1_reader` | **PASSED** | SC2 (5 frames recorded while publishing) + SC3 (re-opened via the v1 reader, 5 msgs all on `/telemetry`) |
| `test_sc2_sc3_record_mcap_then_reopen_via_v1_reader` | **SKIPPED** | the MCAP plugin is not installed here — `skipif` on `get_registered_writers()` worked as designed |

This is an actually-passing live run (NOT collected-and-skipped), so SC2/SC3 are genuinely signed off. The `mcap` variant is the only thing gated on the absent plugin; running it on a host with `ros-humble-rosbag2-storage-mcap` installed is the documented human follow-up (see below).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Thin `rosbagger-record` CLI (`list` + record verbs over the API) | 00c7143 | cli.py, __init__.py, record.py, test_record_unit.py |
| 2 | Live integration test — publisher → bounded record → re-open via v1 reader (SC1/SC2/SC3) | bf5b152 | test_record_live.py |
| 3 | Phase gate — full offline suite + ruff + offline guard + uv sync + live lane | (no code change) | — |

## Verification Results

- **ENV=offline** full offline suite `PYTHONPATH="" uv run pytest` → **429 passed, 1 skipped @ 97.37%** (gate `--cov-fail-under=80` reached, NOT weakened; up from 421 in Plan 02 — +8 CLI tests; the 1 skipped is `test_record_live.py`, collected-and-skipped via `importorskip`, contributing nothing to coverage). No unknown-marker warning (`live` registered in Plan 01).
- **ENV=offline** `PYTHONPATH="" uv run pytest tests/test_record_unit.py -k cli -q` → 8 passed.
- **ENV=offline** `PYTHONPATH="" uv run pytest tests/test_record_live.py` → **1 skipped** (the whole module, via `importorskip("rclpy")` — the offline gate stays green).
- **ENV=offline** `PYTHONPATH="" uv run ruff check .` → All checks passed; `ruff format --check .` → 69 files already formatted.
- **ENV=offline** offline guard `tests/test_offline_guard.py` → 15 passed (`import rosbagger_core`/`bagq`/`rosbagger_record` leak no `rclpy`/`rosbag2_py`); confirmed `import rosbagger_record.cli` also pulls no ROS and the shadow-proof front doors are callable.
- **ENV=offline** `PYTHONPATH="" uv sync --locked --dev` → exit 0 (42 packages; NO re-lock needed — the CLI added no new dependency, `typer` was already declared in Plan 01).
- **ENV=live** the recipe above → **2 passed, 1 skipped** (SC1 + sqlite3 SC2/SC3 pass; mcap variant skips).
- Grep acceptance (all green): no `rosbagger_record` in `packages/bagq/`; no top-level ROS import in `cli.py`; no `SequentialWriter`/`create_subscription`/`get_topic_names_and_types` in the `cli.py` code body (only the docstring NAMES them as what is NOT there); `get_registered_writers` inside the live test's `_mcap_available` skip helper; `RosbagsReader` + `default_typestore` in the live test; `--cov-fail-under=80` still present in `pyproject.toml`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `from rosbagger_record import record` resolved to the MODULE, not the function**
- **Found during:** Task 1 (the first CLI `record`-with-ROS-absent test failed with `TypeError("'module' object is not callable")`).
- **Issue:** `rosbagger_record` exposes BOTH a `record` function (in `__init__.py`) AND a `record` submodule (`record.py`). Once anything in the process does `import rosbagger_record.record` (the unit tests do, via `import rosbagger_record.record as record_impl`), Python rebinds the `rosbagger_record.record` ATTRIBUTE to the MODULE — so a later `from rosbagger_record import record` yields the (non-callable) module. A latent footgun for ANY caller (the CLI, the Phase-14 GUI, a user script) that imports the submodule first, not just the test.
- **Fix:** Added submodule-shadow-proof aliases in `__init__.py` — `record_topics = record` and `list_record_topics = list_topics` (both pointing at the front-door FUNCTIONS) — and had the CLI import those (`from rosbagger_record import record_topics as record_api`). The bare `record`/`list_topics` stay the documented public API for the common case where the submodule is not pre-imported; the aliases are the guaranteed-callable path. Added both to `__all__`.
- **Files modified:** `packages/rosbagger-record/src/rosbagger_record/__init__.py`, `packages/rosbagger-record/src/rosbagger_record/cli.py`.
- **Commit:** 00c7143.

### Within-discretion choices

- **Selection threading** (documented above): extended `record()`'s signature rather than resolving the selection in the CLI — keeps `record()` the single orchestrator (D-02). This is the plan's explicit "pick the path and document it" choice point, not an unplanned deviation.
- **External publisher = subprocess** rather than a second in-process node: `record()`/`list_topics()` each own `rclpy.init()`/`shutdown()`, and `rclpy.init()` cannot run twice in one context; a subprocess gives the publisher its own context AND makes it a genuinely external graph participant (so the DDS settle is really exercised).
- **Task 3 made no code change:** the offline suite + ruff + offline guard + uv sync were green as-is, so the plan's allowed "small lint nit" edit to `test_record_unit.py` was unnecessary; Task 3 is a pure verification capstone with no commit of its own.

## TDD Gate Compliance

This plan's frontmatter is `type: execute` (not `type: tdd`) and no task carries `tdd="true"`, so the RED/GREEN/REFACTOR gate does not apply. The CLI unit tests were written alongside `cli.py` in Task 1 (and surfaced the real shadowing bug above on first run — fixed before commit); the live test in Task 2 is an integration proof, not a unit-TDD cycle. All commits use the correct conventional types (`feat` for the CLI, `test` for the live test).

## Known Stubs

None. The CLI is fully wired to the `record()`/`list_topics()` API; the live test exercises the real recording pipeline end-to-end. The only intentionally-not-run-here code is the `mcap` live variant (skipped because the MCAP storage plugin is not installed on this box — an environment dependency, not a stub), and the irreducible `rclpy`/`rosbag2_py` wiring in `record.py` (proven by the live lane, which RAN).

## Human Follow-up (optional — does NOT block REC-01)

To exercise the LOCKED MCAP path (`test_sc2_sc3_record_mcap_then_reopen_via_v1_reader`, currently skipped) and to record real MCAP bags on this box: `sudo apt install ros-humble-rosbag2-storage-mcap` (apt candidate verified available; install needs `sudo`, not autonomously runnable here). After installing, `mcap` joins `get_registered_writers()` and the mcap variant runs instead of skipping. SC2/SC3 are already proven mechanically via the sqlite3 path, so this is a format-coverage nicety, not a gap in REC-01.

## Self-Check: PASSED

`packages/rosbagger-record/src/rosbagger_record/cli.py` and `tests/test_record_live.py` exist on disk; both task commits (00c7143, bf5b152) are present in `git log`; the full offline suite is green (429 passed, 1 skipped @ 97.37%); the live lane RAN on this box (2 passed, 1 skipped) proving SC1/SC2/SC3.
