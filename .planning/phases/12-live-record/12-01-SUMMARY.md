---
phase: 12-live-record
plan: 01
subsystem: rosbagger-record (live)
tags: [record, live, rclpy, offline-boundary, package-scaffold, discovery]
requires:
  - rosbagger-core (v1 reader contract + errors-that-teach pattern)
  - bagq/pyproject.toml (per-package manifest pattern mirrored)
  - tests/test_offline_guard.py (existing _heavy_modules_after_import helper + no_ros fixture)
provides:
  - packages/rosbagger-record/ (uv workspace member; lazy ROS boundary)
  - rosbagger_record.record / list_topics (lazy ROS-bound entry points; impl Plan 02)
  - rosbagger_record.discover_topics / select_topics (discovery + pure-Python selection)
  - rosbagger_record.RosNotAvailableError / McapStorageUnavailableError (teaching capability errors)
  - live pytest marker (registered; Plan 03 live test relies on it)
affects:
  - Plan 12-02 (record.py rclpy/rosbag2_py core builds on _require_ros + discovery)
  - Plan 12-03 (cli.py + test_record_live.py — console script + live marker)
  - Phase 14 GUI Record panel (capability-gates over this package API)
tech-stack:
  added:
    - "rosbagger-record (workspace member; only uv-resolved deps: rosbagger-core + typer>=0.15,<1)"
  patterns:
    - "Lazy ROS-import boundary: rclpy/rosbag2_py imported inside function bodies only (D-03/D-11)"
    - "Teaching capability errors as RuntimeError subclasses (distinct from core's ValueError data errors)"
    - "Pure-Python selection (select_topics) split from the one ROS-bound call (discover_topics)"
    - "Offline-guard regression test reuses fresh-subprocess env={PYTHONPATH: ''}; .pth member resolves while host ROS stays hidden"
key-files:
  created:
    - packages/rosbagger-record/pyproject.toml
    - packages/rosbagger-record/src/rosbagger_record/__init__.py
    - packages/rosbagger-record/src/rosbagger_record/errors.py
    - packages/rosbagger-record/src/rosbagger_record/discovery.py
    - tests/test_record_unit.py
  modified:
    - pyproject.toml (live marker registered; rosbagger-record/src added to ruff src)
    - tests/test_offline_guard.py (+ test_import_record_does_not_pull_ros; docstring widened)
    - uv.lock (re-locked: + rosbagger-record v0.1.0)
decisions:
  - "select_topics precedence: base set (all_topics OR positional present-in-discovered) -> regex include -> exclude; deterministic over discovered insertion order"
  - "uv.lock REQUIRED a re-lock (the members=[packages/*] glob picks up the new member; --locked failed until `uv lock` added rosbagger-record v0.1.0)"
  - "rosbagger_record kept OUT of the --cov gate (gate stays --cov=rosbagger_core --cov=bagq); the live record core can't be covered offline, and adding it would weaken the >=80% gate"
  - "__init__.py re-exports discovery in Task 2 (not Task 1) so each commit is independently importable"
  - "Capability errors are RuntimeError (env/capability state), not ValueError (the core's bad-argument teaching family)"
metrics:
  duration: ~8min
  tasks: 3
  files: 8
  completed: 2026-05-23
---

# Phase 12 Plan 01: rosbagger-record Scaffold + Offline Boundary Summary

Scaffolded the `rosbagger-record` workspace package with a lazy ROS-import boundary so `import rosbagger_record` succeeds in the ROS-free uv venv (no `rclpy`/`rosbag2_py` pulled), shipped teaching capability errors and pure-Python topic discovery + subset selection, and regression-locked the offline↔live boundary with an extended offline guard — establishing the offline/live package seam before any ROS code lands.

## What Was Built

- **`packages/rosbagger-record/` uv workspace member** mirroring `bagq`'s manifest. Its ONLY uv-resolved dependencies are `rosbagger-core` + `typer>=0.15,<1` (D-03); `rclpy`/`rosbag2_py`/`rosidl_runtime_py` are environment-provided and deliberately absent from `[project] dependencies`. Console script `rosbagger-record = "rosbagger_record.cli:app"` declared (cli.py lands Plan 03; hatchling does not import it at build time).
- **`__init__.py` lazy boundary** (verified RESEARCH Pattern 1): `_require_ros()` imports `rclpy`+`rosbag2_py` inside its body and raises the teaching `RosNotAvailableError` from the `ImportError`; `record()`/`list_topics()` are thin lazy delegators (call `_require_ros()` then import the `.record` impl, Plan 02). NO top-level ROS import; the discovery helpers are re-exported (binds no ROS).
- **`errors.py`** — `RosNotAvailableError` ("source your ROS 2 environment …") and `McapStorageUnavailableError(requested, available)` (names the registered writers + the install/`--storage sqlite3` remedy). Both `RuntimeError` subclasses (capability/environment conditions, distinct from the core's `ValueError` data errors). Stdlib-only module top.
- **`discovery.py`** — `discover_topics(node, settle_iters=30, settle_dt=0.02)` (lazy `rclpy`; spins to let DDS discovery settle; `{topic: types[0]}`, typeless dropped) + `select_topics(...)` a pure ROS-free filter. Module top imports only `__future__` + stdlib `re`.
- **`tests/test_record_unit.py`** — 11 mocked unit tests (selection matrix, mocked `discover_topics`, no-ROS capability error).
- **Offline guard extended** + **`live` marker registered**.

## select_topics Precedence (decision)

Documented in the docstring and proven by `test_select_regex_then_exclude_compose`:

1. **Base set** — `all_topics=True` -> every discovered topic; else the positional `topics` that EXIST in `discovered` (missing names silently dropped); `topics=None`/empty with `all_topics=False` -> empty.
2. **Regex include** — keep base-set names matching `re.search(regex, name)`.
3. **Exclude** — drop names matching `re.search(exclude, name)`.

Iterates `discovered` in insertion order throughout (deterministic), preserving each kept topic's type string. `regex`/`exclude` compiled via stdlib `re` only; topic names are pure data — no shell/eval (T-12-02, grep-gated).

## pyproject.toml deps shipped + uv.lock

- `dependencies = ["rosbagger-core", "typer>=0.15,<1"]` — no `rclpy`/`rosbag2_py`/`rosidl` on any non-comment line (D-03 held; T-12-SC: no new third-party PyPI install).
- **uv.lock DID need a re-lock.** Adding the member made `PYTHONPATH="" uv sync --locked --dev` fail ("lockfile needs to be updated"); `PYTHONPATH="" uv lock` added `rosbagger-record v0.1.0` (its only dep, the workspace `rosbagger-core`, was already locked — no new external resolution), after which `uv sync --locked --dev` exits 0 (42 packages). The updated `uv.lock` is committed with Task 1.

## Offline-guard fresh-subprocess env (W3)

`test_import_record_does_not_pull_ros` REUSES the existing inline fresh-subprocess pattern with the plain `env={"PYTHONPATH": ""}` (the same env `_heavy_modules_after_import` and the `rosbags` checks use). The empty `PYTHONPATH` neutralizes the dev host's ROS-on-`PYTHONPATH` leak, yet `import rosbagger_record` STILL resolves because the uv workspace member is installed as an editable `.pth` in site-packages (resolves regardless of `PYTHONPATH`) — verified: a fresh subprocess with `PYTHONPATH=""` imports `rosbagger_record` (rc 0) with `leaked: []`. No ROS-bearing path was added to the subprocess `PYTHONPATH` (that would weaken the guard). The existing `test_core_imports_without_ros` / `test_no_ros_leaked_into_sys_modules` confirm core/bagq stay ROS-free with the live member now installed.

## Offline-suite pass count + coverage

- **Full offline suite: 414 passed @ 97.37% coverage** (`PYTHONPATH="" uv run pytest`), gate `--cov-fail-under=80` reached. Coverage is gated on `rosbagger_core` + `bagq` ONLY — `rosbagger_record` is intentionally NOT in the gate (its live record core can't be exercised offline; the new package's pure-Python unit tests still run, just aren't gated), so the ≥80% gate stays green without being weakened.
- The two target files alone: **26 passed** (11 unit + 15 offline-guard incl. the new test).
- No `Unknown pytest.mark.live` warning (marker registered).
- `ruff check .` + `ruff format --check .` clean (66 files).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Scaffold package + lazy ROS boundary + teaching errors | 070424f | pyproject.toml, __init__.py, errors.py, uv.lock |
| 2 | Topic discovery + pure-Python subset selection | a271bd4 | discovery.py, __init__.py |
| 3 | Mocked unit tests + offline-guard extension + live marker | 8321990 | test_record_unit.py, test_offline_guard.py, pyproject.toml |

## Deviations from Plan

None affecting behavior. Two within-discretion choices worth recording:

- **Commit-boundary ordering of the discovery re-export.** The plan lists `__init__.py` under Task 1 with a "public API re-export" artifact. To keep each commit independently importable (Task 1's verify does `import rosbagger_record`), Task 1's `__init__.py` re-exports only `errors`; Task 2 adds the `discover_topics`/`select_topics` re-export when it creates `discovery.py`. End state matches the artifact spec (both helpers re-exported, `__all__` complete).
- **[Rule 2 — consistency] Added `packages/rosbagger-record/src` to `[tool.ruff].src`.** The plan's Task 3 pyproject edit specified only the `live` marker. Adding the new member to ruff's `src` keeps the workspace lint config consistent (the existing comment states `src` "includes … so ruff also lints" the whole tree) and makes `ruff check .` (no path) cover the package as first-party for import sorting. `addopts`/`--cov` left unchanged per the plan's explicit instruction.

## TDD Gate Compliance

Task 3 carries `tdd="true"`, but this plan is a characterization/regression suite over code that Tasks 1+2 legitimately land FIRST (the plan's `<action>` states: "Tasks 1+2 already provide the code, so these should pass GREEN immediately — if any fails, it reveals a Task 1/2 contract bug to fix there"). All 11 unit tests + the new offline-guard test passed GREEN on first run — confirming the Task 1/2 contracts (no contract bug surfaced). There is therefore no separate RED `test(...)` commit before a GREEN `feat(...)`: the feat commits (070424f, a271bd4) precede the single `test(...)` commit (8321990) by plan design, not by gate violation. Mocks are injected via `monkeypatch.setitem(sys.modules, ...)` (not `mock.patch` string targets, which fail at collection in the ROS-free venv — Pitfall 6).

## Notes for Plan 02 / 03

- `record.py` (Plan 02) must provide `record(...)` and `list_topics(...)` (the `__init__` delegators import them by those names) and do the heavy `rclpy`/`rosbag2_py` import; reuse `_require_ros`, `discover_topics`, `select_topics`, and `McapStorageUnavailableError` (Pattern 5 storage gate). The SC3 re-open assertion should pass `default_typestore=ROS2_HUMBLE` defensively (sqlite3 needs it; MCAP no-op) per 12-RESEARCH Pitfall 2.
- `cli.py` (Plan 03) is the console-script target already declared; `test_record_live.py` uses the now-registered `live` marker + `importorskip("rclpy")` + skip-if-no-mcap.
- The offline guard now asserts `import rosbagger_record` is ROS-free — keep all ROS imports inside function bodies in Plan 02/03 or this test fails.

## Self-Check: PASSED

All five created source files + the SUMMARY exist on disk; all three task commits (070424f, a271bd4, 8321990) are present in the git log.
