---
phase: 08-packaging-docs-release
plan: 01
subsystem: infra
tags: [packaging, release, versioning, uv, hatchling, pip, license, readme, v0.1.0]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: "uv workspace, two-package src-layout, [tool.uv.sources] workspace dep, offline-import guard, ROS-free CI, PYTHONPATH='' dev-host neutralizer"
  - phase: 04-inspect
    provides: "bagq info / bagq tables subcommands"
  - phase: 06-output
    provides: "bagq query with -o / --format / --plot sinks"
  - phase: 07-errors-that-teach
    provides: "teaching error messages (no traceback) the README documents"
provides:
  - "rosbagger v0.1.0 — version 0.1.0 across all 4 source sites + re-locked uv.lock"
  - "MIT LICENSE at the repo root"
  - "Expanded README: verified plain-pip install recipe, bagq[plot] extra, uv dev path, per-command quickstart, errors-that-teach, offline/no-ROS guarantee"
  - "Locally-verified release gate (clean-room pip install SC1, offline import SC2, full CI-equivalent gate) + annotated v0.1.0 tag"
affects: [release, publish, future-milestones]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-local-package pip install (both workspace members in one command — pip ignores [tool.uv.sources])"
    - "Re-lock-on-version-bump (uv lock after editing pyproject version, so uv sync --locked stays green)"
    - "Clean-room verification: fresh non-.venv venv + PYTHONPATH='' + neutral cwd for the no-tools assertion"

key-files:
  created:
    - LICENSE
  modified:
    - packages/rosbagger-core/pyproject.toml
    - packages/bagq/pyproject.toml
    - packages/rosbagger-core/src/rosbagger_core/__init__.py
    - packages/bagq/src/bagq/__init__.py
    - uv.lock
    - README.md

key-decisions:
  - "Bumped the 4 version sites by hand + re-locked (rejected hatchling dynamic version for a one-shot bump — no new build config)"
  - "MIT LICENSE, copyright holder 'rosbagger contributors' (generic project holder, no individual named)"
  - "End-user README recipe is non-editable plain pip (both packages, one command); -e is documented only as the uv dev path"
  - "SC3 split honestly: local gate + local v0.1.0 tag done autonomously; push + observe-CI-green recorded as the sole human follow-up (NOT a blocking checkpoint)"

patterns-established:
  - "Pattern 1: Install both local packages in one pip command to resolve the bare intra-workspace dep (pip ignores [tool.uv.sources])"
  - "Pattern 2: Re-run uv lock immediately after a version bump so the committed lockfile matches the manifests (uv sync --locked CI step)"
  - "Pattern 3: Clean-room install verification in a throwaway venv (not .venv) with PYTHONPATH='' and the no-tools/no-rclpy asserts run from a neutral cwd"

requirements-completed:
  - "DoD: bagq installs via pip and exposes info/tables/query"
  - "DoD: offline packages import without rclpy"
  - "DoD: all v1 requirements covered by tests (CI green)"

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 8 Plan 1: Packaging, Docs & Release Summary

**Shipped rosbagger v0.1.0 — bumped both packages to 0.1.0 across all 4 sources + re-locked uv.lock, added an MIT LICENSE, expanded the README with the verified `pip install ./packages/rosbagger-core ./packages/bagq` recipe and a per-command quickstart, and proved the release locally (clean-room pip install SC1, offline no-rclpy/no-tools import SC2, the full CI-equivalent gate at 255 tests / 97.82%, and an annotated `v0.1.0` tag).**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-22T18:34:27Z
- **Completed:** 2026-05-22T18:37:52Z
- **Tasks:** 3
- **Files modified:** 6 (5 modified + 1 created), plus 1 local annotated git tag

## Accomplishments

- Version `0.0.0` -> `0.1.0` in all four source sites (both `pyproject.toml` `version` fields and both `__init__.py` `__version__` assignments); `bagq --version` prints `bagq 0.1.0` and `rosbagger_core.__version__ == "0.1.0"`.
- Re-locked `uv.lock` (both `bagq` and `rosbagger-core` pins now `0.1.0`, lines 121 / 1239) so `uv sync --locked --dev` stays green — the CI step that would otherwise fail on a stale lock.
- Added an MIT `LICENSE` at the repo root.
- Expanded `README.md` with the verified plain-pip install recipe (both local packages in one command), the quoted `bagq[plot]` extra, the `uv sync --locked --dev` dev path, a per-command quickstart for `info`/`tables`/`query` (with the `-o`/`--format`/`--plot` options described accurately), the errors-that-teach behavior, and the offline/no-ROS guarantee — and removed the Phase-1 "lands in a later phase" placeholder.
- Verified the release LOCALLY: clean-room `pip install ./packages/rosbagger-core ./packages/bagq` in a fresh throwaway venv with `bagq --help` + all three subcommand `--help` at exit 0 (SC1); offline `import rosbagger_core, bagq` from a neutral cwd with `rclpy`/`rosbag2_py`/`tools` all `find_spec`==None (SC2); the full CI-equivalent gate green; and an annotated `v0.1.0` tag created locally.

## Task Commits

Each task was committed atomically (Task 3 modifies no source files — its artifact is the local tag + verification, documented here):

1. **Task 1: Bump version to 0.1.0 (4 sites), re-lock uv.lock, add MIT LICENSE** - `99f4be7` (chore)
2. **Task 2: Expand README with verified install recipe, quickstart, offline guarantee** - `936238b` (docs)
3. **Task 3: Clean-room pip verify (SC1/SC2), local CI gate, annotated v0.1.0 tag** - no source commit by design; produced the local annotated tag `v0.1.0` (points at `936238b`) and the verification evidence below.

**Plan metadata:** committed after this SUMMARY (docs: complete plan; includes SUMMARY.md, STATE.md, ROADMAP.md).

## Files Created/Modified

- `LICENSE` - MIT License, "Copyright (c) 2026 rosbagger contributors" (created)
- `packages/rosbagger-core/pyproject.toml` - `version = "0.1.0"`
- `packages/bagq/pyproject.toml` - `version = "0.1.0"`
- `packages/rosbagger-core/src/rosbagger_core/__init__.py` - `__version__ = "0.1.0"`
- `packages/bagq/src/bagq/__init__.py` - `__version__ = "0.1.0"` (the source `bagq --version` reads)
- `uv.lock` - re-locked: both package pins `0.1.0` (so `uv sync --locked` matches the manifests)
- `README.md` - install recipe + per-command usage + errors-that-teach + offline guarantee; placeholder removed

## Verification Results

### Verified locally (autonomous — this plan proves these)

- **Version everywhere:** `bagq --version` -> `bagq 0.1.0`; `rosbagger_core.__version__ == "0.1.0"`; all 4 source sites read `0.1.0`; no `version = "0.0.0"` remains in `uv.lock` or either `pyproject.toml`.
- **Lock in sync:** `PYTHONPATH="" uv sync --locked --dev` exits 0 after the re-lock (the CI install step).
- **SC1 — clean-room pip install:** in a FRESH `python3 -m venv` (NOT `.venv`) with `PYTHONPATH=""`, `pip install ./packages/rosbagger-core ./packages/bagq` installed both (each reporting `0.1.0`); `bagq --help` exit 0; `bagq info|tables|query --help` each exit 0.
- **SC2 — offline import:** from a neutral cwd (`/tmp`) in that venv, `import rosbagger_core, bagq` succeeded with `find_spec('rclpy')`, `find_spec('rosbag2_py')`, and `find_spec('tools')` all `None`, and no `rclpy`/`rosbag2_py` in `sys.modules` — proving no ROS dependency and no `tools/` in either wheel (threat T-08-03 mitigated). Throwaway venv removed afterward.
- **Local CI-equivalent gate (SC3 autonomous half):** under `PYTHONPATH=""` all four steps from `.github/workflows/ci.yml` are green — `uv sync --locked --dev`, `uv run ruff check .` ("All checks passed!"), `uv run ruff format --check .` ("49 files already formatted"), `uv run pytest` (**255 passed, 97.82% coverage**, gate >=80%).
- **Annotated tag (SC3 autonomous half):** `git tag -a v0.1.0` created locally; `git cat-file -t v0.1.0` == `tag`; points at `936238b`.
- **MIT LICENSE:** exists at the repo root; first line is `MIT License`.
- **README:** documents the verified plain-pip recipe, the `bagq[plot]` extra, the uv dev path, the `info`/`tables`/`query` quickstart, errors-that-teach, and the offline/no-ROS guarantee; contains no `pip install bagq` PyPI instruction, no `PYTHONPATH=`, and no "lands in a later phase".

### Awaits push (human follow-up — known recorded gap; SC3 remote half)

**The ONLY thing left to make the milestone fully shipped:**

```bash
git push origin main
git push origin v0.1.0
# then observe the GitHub Actions "ci" run go green
```

**Blocked by:** no `gh` CLI and no push credential in this environment (standing STATE.md blocker; `origin` = `https://github.com/AllenDevaraj/rosbagger.git`). This is intentionally NOT a blocking checkpoint — the plan is `autonomous: true` and everything achievable here is done. The local CI-equivalent gate (run above, all green) is the strongest available proxy that the pushed run will pass: CI runs the identical four steps on Python 3.10 / 3.12 with no ROS installed.

## Decisions Made

- **Hand-bump the 4 version lines + re-lock**, rather than adopt hatchling `dynamic=["version"]` — lowest-risk for a one-shot `0.0.0`->`0.1.0` bump; adds no `[build-system]`/config surface (08-RESEARCH Open Q2).
- **MIT LICENSE**, copyright holder "rosbagger contributors" (generic project holder per the planning constraint — no individual named) (08-RESEARCH Open Q1).
- **End-user README recipe is non-editable plain `pip`** (`pip install ./packages/rosbagger-core ./packages/bagq`); `-e`/editable is documented only as the `uv` developer path. Did NOT promise `pip install bagq` from PyPI (unpublished; v0.1 is local-install only).
- **Kept the `PYTHONPATH=""` dev-host hazard out of the user-facing README** — it is a ROS-sourced-dev-shell note (CONTRIBUTING/dev), not an install step.
- **SC3 split honestly** — local gate + local tag done; push + observe-CI-green documented as the sole human follow-up, not a stalling checkpoint.

## Deviations from Plan

None - plan executed exactly as written.

(Note: STATE.md's continuity text from Phase 7 recorded "254 passed"; the actual current suite is **255 passed** at 97.82%. No discrepancy in this plan — Phase 8 added a test indirectly only via the unchanged suite; the gate and count were observed directly during the local CI gate. No code change was needed.)

## Authentication Gates

None encountered during execution. (The GitHub push credential is a known environment limitation handled as a documented human follow-up above, not an auth gate hit mid-task.)

## Issues Encountered

None. Every step matched the empirically-verified recipes in 08-RESEARCH (the re-lock, the both-packages pip install, the neutral-cwd no-tools assertion, and the full local gate all behaved exactly as researched).

## User Setup Required

None - no external service configuration required for the software itself.

The single remaining human action is the release push (see "Awaits push" above): push `main` + the `v0.1.0` tag and confirm the GitHub Actions run is green. This finalizes the v0.1 milestone.

## Next Phase Readiness

- **v0.1 milestone is autonomously complete** for everything achievable in this environment: versioned, licensed, documented, locally verified, and tagged.
- **Sole remaining gap:** push `main` + `v0.1.0` and observe CI green (blocked on the standing `gh`/push-credential blocker).
- No new dependencies and no runtime code were added; the offline/no-ROS invariant and the >=80% coverage gate are intact.

## Self-Check: PASSED

- All created/modified files exist on disk: `LICENSE`, `README.md`, `uv.lock`, both `pyproject.toml`, both `__init__.py`, and `08-01-SUMMARY.md`.
- Task commits exist: `99f4be7` (Task 1), `936238b` (Task 2).
- Annotated `v0.1.0` tag exists locally (`git cat-file -t v0.1.0` == `tag`).

---
*Phase: 08-packaging-docs-release*
*Completed: 2026-05-22*
