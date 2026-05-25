---
phase: 15-packaging-release-v0-2
plan: 01
subsystem: infra
tags: [packaging, uv, workspace, versioning, release, pyproject, lockfile]

# Dependency graph
requires:
  - phase: 08-packaging-docs-release
    provides: v0.1 hand-bump precedent (4 version sites + re-lock; hatchling, no dynamic version)
  - phase: 14-gui
    provides: rosbagger-gui package + live panels that already lazy-import siblings in method bodies
provides:
  - All five workspace packages stamped at version 0.2.0 (5 pyproject + 5 __version__)
  - Four sibling deps pinned by version spec rosbagger-core>=0.2,<0.3 (D-01/D-03)
  - rosbagger-gui declarative [live] extra = rosbagger-record + rosbagger-replay (>=0.2,<0.3) (D-02)
  - record/replay added to [tool.uv.sources] as workspace members (resolves the live extra)
  - uv.lock re-locked at 0.2.0; uv sync --locked --dev green
affects: [15-02, 15-03, packaging, release]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Version spec only at the wheel boundary — no git/path URL baked into [project] dependencies (D-01)"
    - "Declarative opt-in extra ([project.optional-dependencies] live) keeps the base import ROS-free (D-02)"
    - "Any workspace member referenced as a dependency needs a [tool.uv.sources] workspace=true entry"

key-files:
  created: []
  modified:
    - packages/rosbagger-core/pyproject.toml
    - packages/bagq/pyproject.toml
    - packages/rosbagger-record/pyproject.toml
    - packages/rosbagger-replay/pyproject.toml
    - packages/rosbagger-gui/pyproject.toml
    - packages/rosbagger-core/src/rosbagger_core/__init__.py
    - packages/bagq/src/bagq/__init__.py
    - packages/rosbagger-record/src/rosbagger_record/__init__.py
    - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
    - packages/rosbagger-gui/src/rosbagger_gui/__init__.py
    - pyproject.toml
    - uv.lock

key-decisions:
  - "Hand-bumped 10 version sites + re-locked (mirrors Phase 8 v0.1) rather than adopting hatchling dynamic versioning — lowest-risk one-shot bump, no [build-system] surface change"
  - "[Rule 3] Added rosbagger-record + rosbagger-replay to root [tool.uv.sources] (workspace=true) — the new gui [live] extra names them, and uv requires a workspace source for any member referenced as a dependency (they are unpublished)"
  - "Sibling pins are version spec only (rosbagger-core>=0.2,<0.3) — no git/path URL at the wheel boundary (D-01 source-agnostic; baked URL is the explicit anti-pattern / threat T-15-01)"

patterns-established:
  - "Pattern 1: Coherent monorepo release — every member at the same MAJOR.MINOR, every sibling pin >=MINOR,<next-MINOR"
  - "Pattern 2: Live tier is an opt-in extra, never a base dependency — base sync stays ROS-free"

requirements-completed: [SC1, SC4, SC5]

# Metrics
duration: 2min
completed: 2026-05-25
---

# Phase 15 Plan 01: v0.2.0 Release Manifests Summary

**Stamped a coherent v0.2.0 across all five workspace packages, pinned every sibling dep `rosbagger-core>=0.2,<0.3` by version spec, added the declarative `rosbagger-gui[live]` extra, and re-locked uv.lock so `uv sync --locked --dev` stays green and `bagq --version` prints `bagq 0.2.0`.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-25T00:24:30Z
- **Completed:** 2026-05-25T00:25:58Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- 10 version sites bumped 0.1.0 -> 0.2.0 (5 pyproject `version` + 5 package `__version__`); zero 0.1.0 literals remain.
- Four sibling dependency lines (bagq, record, replay, gui) pinned `rosbagger-core>=0.2,<0.3` — version spec only, no git/path URL anywhere in `[project] dependencies`.
- rosbagger-gui gained a declarative `[project.optional-dependencies] live = ["rosbagger-record>=0.2,<0.3", "rosbagger-replay>=0.2,<0.3"]`; its stale "intentionally NOT declared" comment now describes the opt-in `[live]` extra and the ROS-free-base guarantee is preserved.
- uv.lock re-locked at 0.2.0 (all five members updated); `uv sync --locked --dev` green; `bagq --version` -> `bagq 0.2.0`; offline guard re-verified (base `import rosbagger_gui` leaks no rclpy/rosbag2_py).

## Task Commits

Each task was committed atomically:

1. **Task 1: Bump all 10 version sites to 0.2.0** - `a1c63c7` (chore)
2. **Task 2: Pin sibling deps >=0.2,<0.3 and add gui live extra** - `5fdee6b` (feat)
3. **Task 3: Re-lock uv.lock at 0.2.0 and confirm bagq --version** - `508b8f9` (chore)

**Plan metadata:** _(this SUMMARY + STATE/ROADMAP)_ committed separately.

## Files Created/Modified
- `packages/rosbagger-core/pyproject.toml` - version 0.2.0 (sibling deps untouched — core has none)
- `packages/bagq/pyproject.toml` - version 0.2.0 + `rosbagger-core>=0.2,<0.3`
- `packages/rosbagger-record/pyproject.toml` - version 0.2.0 + `rosbagger-core>=0.2,<0.3`
- `packages/rosbagger-replay/pyproject.toml` - version 0.2.0 + `rosbagger-core>=0.2,<0.3`
- `packages/rosbagger-gui/pyproject.toml` - version 0.2.0 + `rosbagger-core>=0.2,<0.3` + `[live]` extra + amended comment
- `packages/*/src/*/__init__.py` (5 files) - `__version__ = "0.2.0"`
- `pyproject.toml` (root) - added record/replay to `[tool.uv.sources]` (Rule 3 fix)
- `uv.lock` - re-locked at 0.2.0 for all five members

## Decisions Made
- Hand-bumped the 10 sites and re-locked (Phase 8 v0.1 precedent) rather than adopting hatchling dynamic versioning — lowest-risk path, no build-system surface change.
- Sibling pins are version spec only — no git/path URL at the manifest boundary (D-01; threat T-15-01 mitigation).
- The gui `live` deps are a declarative opt-in extra, not base dependencies — no `__init__` import added, so the base import stays rclpy-free (D-02; threat T-15-02 mitigation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added record/replay to root `[tool.uv.sources]`**
- **Found during:** Task 3 (re-lock)
- **Issue:** `uv lock` failed — `rosbagger-record`/`rosbagger-replay`, now named in the gui `[live]` extra, were workspace members with no `[tool.uv.sources]` entry, so uv could not resolve them (and they are unpublished, so PyPI resolution would also fail). Error: "included as a workspace member, but is missing an entry in `tool.uv.sources`".
- **Fix:** Added `rosbagger-record = { workspace = true }` and `rosbagger-replay = { workspace = true }` to the root `pyproject.toml` `[tool.uv.sources]` (alongside the existing `rosbagger-core` entry), with a comment explaining why the live extra requires them.
- **Files modified:** `pyproject.toml` (root)
- **Verification:** `uv lock` then succeeded (all five members -> 0.2.0); `uv sync --locked --dev` green; `bagq --version` -> `bagq 0.2.0`.
- **Committed in:** `508b8f9` (Task 3 commit)

This is a config fix (workspace-source wiring), NOT a package install — no external/third-party package was added; the two siblings are first-party workspace members.

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The fix was the natural completion of D-02 — declaring the `live` extra is only resolvable once the named siblings have workspace sources. No scope creep; no external packages introduced (threat T-15-SC "accept" disposition holds).

## Issues Encountered
None beyond the Rule 3 blocking fix documented above.

## User Setup Required
None - no external service configuration required.

## Threat Surface
No new security-relevant surface. Threat register dispositions honored:
- **T-15-01 (URL injection at manifest boundary):** mitigated — version spec only; `grep` confirmed no git/path/`@`/`==` URL in any `[project] dependencies`.
- **T-15-02 (live extra eager ROS import):** mitigated — extra is declarative; no `__init__` edit; base `import rosbagger_gui` verified to leak no rclpy/rosbag2_py.
- **T-15-SC (package installs):** accept — no new external packages; only first-party sibling pins + version bumps.

## Next Phase Readiness
- Manifests are coherent at 0.2.0 with version-spec sibling pins — the prerequisite for Plan 02's external-venv install proof and Plan 03's `uv build` / offline-guard phase gate (SC1/SC5).
- uv.lock is current; no blockers.

## Self-Check: PASSED

- FOUND: `.planning/phases/15-packaging-release-v0-2/15-01-SUMMARY.md`
- FOUND: commit `a1c63c7` (Task 1)
- FOUND: commit `5fdee6b` (Task 2)
- FOUND: commit `508b8f9` (Task 3)

---
*Phase: 15-packaging-release-v0-2*
*Completed: 2026-05-25*
