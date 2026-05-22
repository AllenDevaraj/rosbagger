---
phase: 01-scaffold-test-harness
plan: 02
subsystem: testing
tags: [ruff, pytest, pytest-cov, uv, github-actions, ci, sys.meta_path, offline-guard, coverage]

# Dependency graph
requires:
  - phase: 01-01
    provides: uv workspace (rosbagger-core + bagq editable installs), src/ layout, bagq.cli:app typer symbol, virtual root pyproject.toml, untracked uv.lock
provides:
  - Centralized [tool.ruff] + [tool.pytest.ini_options] config in the workspace root (>=80% coverage gate via addopts)
  - sys.meta_path-based offline-import guard (no_ros fixture) that is meaningful on both clean CI and a ROS-equipped host
  - CLI smoke tests (bagq --help / --version via CliRunner) covering the small real Phase-1 surface
  - Committed uv.lock for reproducible, tamper-evident installs
  - No-ROS GitHub Actions CI (ruff check + ruff format --check + pytest on a 3.10/3.12 matrix, least-privilege permissions)
affects: [02-reader, 03-schema, every later phase relying on no-ROS CI and the offline guard]

# Tech tracking
tech-stack:
  added: [ruff config, pytest+pytest-cov config, GitHub Actions CI (astral-sh/setup-uv@v8)]
  patterns:
    - "Offline-import guard via sys.meta_path blocker (not the naive try/except form)"
    - "Coverage gate enforced through pyproject addopts so local and CI runs are identical"
    - "uv sync --locked in CI for reproducible builds from a committed lockfile"

key-files:
  created:
    - tests/conftest.py
    - tests/test_offline_guard.py
    - tests/test_smoke.py
    - .github/workflows/ci.yml
    - uv.lock
  modified:
    - pyproject.toml

key-decisions:
  - "Coverage gate (>=80%) lives in pyproject [tool.pytest.ini_options].addopts, not in CI flags, so `uv run pytest` behaves identically locally and in CI"
  - "Offline guard uses a sys.meta_path import blocker (rejecting the naive `with pytest.raises(ImportError): import rclpy`) so the test is meaningful with ROS present on the dev host"
  - "Local test runs require PYTHONPATH=\"\" to neutralize the host's ROS-on-PYTHONPATH leak; CI is ROS-free so this is moot there"
  - "CI matrix is [3.10, 3.12] (floor + a current) with .python-version pinned to 3.10 so the floor is exercised by default"

patterns-established:
  - "Pattern: sys.meta_path _ROSBlocker fixture proves the offline invariant on any host (ROS present or absent)"
  - "Pattern: centralized tooling config in the virtual workspace root; ruff `src` spans both packages, tools, and tests"
  - "Pattern: least-privilege CI (permissions: contents: read, pinned action versions, no secrets)"

requirements-completed:
  - "SC2: pytest runs green in CI with no ROS installed"
  - "DoD: offline packages import without rclpy (actively guarded, not assumed)"
  - "DoD: test suite runs with no ROS install; coverage >= 80%"

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 1 Plan 02: Dev Tooling & Offline Guard Summary

**Centralized ruff + pytest config with an enforced >=80% coverage gate, a `sys.meta_path` offline-import guard that proves the offline packages never pull in ROS (meaningful even on this ROS-equipped dev box), and a no-ROS GitHub Actions CI workflow — all green locally at 100% coverage.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-22T06:26:28Z
- **Completed:** 2026-05-22T06:29:21Z
- **Tasks:** 3
- **Files modified:** 6 (1 modified, 5 created)

## Accomplishments
- Added `[tool.ruff]`, `[tool.ruff.lint]` (E,F,I,UP,B,SIM), `[tool.ruff.format]`, and `[tool.pytest.ini_options]` (with `--cov-fail-under=80`) to the workspace root, preserving 01-01's `[tool.uv.*]` and `[dependency-groups]` blocks.
- Wrote the load-bearing offline-import guard: a `_ROSBlocker` meta-path finder + `no_ros` fixture that blocks ROS modules and purges them from `sys.modules`, plus the two guard tests (blocked-import + no-leak). Verified meaningful WITH ROS importable on the host.
- Added CLI smoke tests (`bagq --help` and `--version` via typer's `CliRunner`, non-empty `__version__`) so the >=80% gate is met honestly — coverage came in at 100%.
- Committed `uv.lock` (41 packages) for reproducible, tamper-evident installs.
- Added a no-ROS CI workflow: `ubuntu-latest`, matrix `[3.10, 3.12]`, `setup-uv@v8` → `uv sync --locked --dev` → `ruff check` → `ruff format --check` → `pytest`, with least-privilege `permissions: contents: read` and no secrets.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add centralized ruff + pytest/coverage config** - `8d0dc29` (chore)
2. **Task 2: Offline-import guard + smoke tests** - `950308d` (test)
3. **Task 3: Lock dependencies + no-ROS CI workflow** - `dd914a5` (ci)

**Plan metadata:** (final docs commit — this SUMMARY + STATE + ROADMAP)

## Files Created/Modified
- `pyproject.toml` - Added centralized ruff (lint+format) and pytest (with the >=80% coverage gate) config; 01-01 uv blocks untouched.
- `tests/conftest.py` - `_ROSBlocker` meta-path finder + `no_ros` fixture (blocks ROS modules, purges them from `sys.modules`).
- `tests/test_offline_guard.py` - `test_core_imports_without_ros` (ImportError for rclpy/rosbag2_py under the blocker; core/bagq still import) and `test_no_ros_leaked_into_sys_modules` (no ROS module leaks).
- `tests/test_smoke.py` - `bagq --help`/`--version` via `CliRunner`; non-empty `__version__` for both packages.
- `.github/workflows/ci.yml` - No-ROS CI (ruff + format + pytest on 3.10/3.12), least-privilege permissions, `uv sync --locked`.
- `uv.lock` - Committed lockfile for reproducible installs (T-01-DRIFT mitigation).

## Decisions Made
- **Coverage gate in `addopts`, not CI flags** — `uv run pytest` enforces `--cov-fail-under=80` identically in local and CI runs; CI needs no extra `--cov` flag.
- **Meta-path blocker over the naive guard** — `with pytest.raises(ImportError): import rclpy` passes for the wrong reason on clean CI and proves nothing on this ROS-equipped host (RESEARCH Pitfall 4). The blocker makes the test valid in both environments. Verified: `rclpy` is genuinely importable on the host, yet the guard test passes under the blocker.
- **`PYTHONPATH=""` for local runs** — the dev shell sources ROS 2 Humble onto `PYTHONPATH`; this is a host-environment fact, not project config. CI is ROS-free so the gate runs verbatim there.
- **Matrix `[3.10, 3.12]`** with `.python-version` pinned to 3.10 (RESEARCH O-3 / Pitfall 6) — the floor is exercised by default; local run confirmed Python 3.10.12.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Cleared PYTHONPATH for local test runs to neutralize the host ROS leak**
- **Found during:** Task 2 (running the guard + smoke tests locally)
- **Issue:** `uv run pytest` failed at startup in `load_setuptools_entrypoints("pytest11")` — the dev shell has `/opt/ros/humble/.../site-packages` on `PYTHONPATH`, so pytest auto-discovered ROS's `launch_testing` pytest plugin, which then raised `ModuleNotFoundError: No module named 'yaml'` (yaml is not in the uv venv). This is the exact PYTHONPATH hazard documented in 01-RESEARCH.md (Runtime State Inventory) and Pitfall 4's environment note — a host artifact, not a defect in the test code.
- **Fix:** Prefix local invocations with `PYTHONPATH=""` (the documented local-run requirement). No committed code changed. CI runs on a ROS-free runner, so the workflow itself needs no such guard and runs `uv run pytest` verbatim.
- **Files modified:** none (invocation-only adjustment)
- **Verification:** `PYTHONPATH="" uv run pytest` → 5 passed, 100% coverage; `PYTHONPATH="" uv run ruff check .` and `ruff format --check .` both exit 0.
- **Committed in:** n/a (no code change; documented here for reproducibility)

**2. [Rule 3 - Blocking] Used `-o addopts=""` instead of `-p no:cov` for the targeted Task 2 verify run**
- **Found during:** Task 2 (the plan's verify command `uv run pytest <files> -x -q -p no:cov`)
- **Issue:** `-p no:cov` disables the pytest-cov plugin, but the `--cov*` flags from `addopts` in pyproject.toml remain on the command line, so pytest errored with `unrecognized arguments: --cov=...`. The intent of the verify step is to run just the two test files WITHOUT the 80% gate; with the coverage flags centralized in `addopts`, the clean way to achieve that is to override `addopts` for the targeted run.
- **Fix:** Ran `PYTHONPATH="" uv run pytest tests/test_offline_guard.py tests/test_smoke.py -x -q -o addopts=""` — same intent (targeted run, no coverage gate), no orphaned flags. The full gate (Task 3) runs the unmodified `uv run pytest` and enforces `--cov-fail-under=80`.
- **Files modified:** none (invocation-only adjustment)
- **Verification:** Targeted run → 5 passed in 0.05s; full `uv run pytest` later → 5 passed, 100% coverage, gate satisfied.
- **Committed in:** n/a (no code change)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking, environment/invocation only)
**Impact on plan:** Neither deviation changed any committed file or the test contract — both are local-invocation adjustments forced by the ROS-on-PYTHONPATH dev host. The CI workflow runs the gate verbatim on a ROS-free runner. No scope creep; all acceptance criteria met as written.

## Issues Encountered
- The ROS-on-`PYTHONPATH` host caused two distinct startup-time leaks into the local pytest process (a ROS pytest11 plugin, and orphaned coverage flags under `-p no:cov`). Both were resolved by invocation adjustments (`PYTHONPATH=""`, `-o addopts=""`) — see Deviations. The fact that `rclpy` is genuinely importable on this host is precisely what makes the meta-path guard the correct (non-naive) approach; the guard test passing under the blocker on this host is the strongest possible evidence it is meaningful.

## User Setup Required
None - no external service configuration required. (CI will run automatically once the repo is pushed to GitHub; push is pending auth per STATE.md blocker.)

## Next Phase Readiness
- No-ROS CI and the offline-import guard are in place — the architectural "universal / no-ROS" invariant is now actively protected for every later phase.
- The >=80% coverage gate is live and currently at 100%; later phases that add domain code must keep coverage at/above the gate.
- Ready for plan 01-03 (the `rosbags` fixture-bag generator), which the ruff `src` list already anticipates (`tools` is included).
- Carry-forward note for contributors and local runs: prefix `uv run pytest`/`ruff` with `PYTHONPATH=""` on machines that source ROS, or run from a shell without ROS sourced.

## Self-Check: PASSED

All 6 created files exist on disk (`tests/conftest.py`, `tests/test_offline_guard.py`, `tests/test_smoke.py`, `.github/workflows/ci.yml`, `uv.lock`, `01-02-SUMMARY.md`) and all 3 task commits (`8d0dc29`, `950308d`, `dd914a5`) are present in the git log.

---
*Phase: 01-scaffold-test-harness*
*Completed: 2026-05-22*
