---
phase: 15-packaging-release-v0-2
plan: 03
subsystem: infra
tags: [packaging, release, phase-gate, uv-build, offline-guard, git-tag, v0.2.0, honest-split]

# Dependency graph
requires:
  - phase: 15-packaging-release-v0-2
    plan: 01
    provides: "all five packages at v0.2.0, sibling pins rosbagger-core>=0.2,<0.3, gui [live] extra, re-locked uv.lock"
  - phase: 15-packaging-release-v0-2
    plan: 02
    provides: "scripts/proof_external_install.sh (PROOF OK) + INSTALL.md"
  - phase: 08-packaging-docs-release
    provides: "v0.1 local-tag + push-as-sole-follow-up honest split precedent"
provides:
  - "Full v0.2 release gate verified green (SC1/SC2/SC5): five 0.2.0 wheels build, uv sync --locked --dev passes, ruff check + format-check clean, full offline pytest suite + offline guard green, proof script prints PROOF OK"
  - "Local annotated v0.2.0 tag (points at bd06d1e; NOT pushed)"
  - "Honest local-vs-awaits-push split recorded: everything verifiable in this environment is done; push + GitHub-Actions observation + the literal git+@v0.2.0 recipe execution are the sole human follow-ups"
affects: [release, publish, future-milestones]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "uv build --all-packages -o dist/ builds all five wheels at once via hatchling src-layout auto-detect (no [tool.hatch.*] config)"
    - "Local CI-equivalent gate (PYTHONPATH= prefix on every step) is the strongest available proxy for the unpushable remote CI run"
    - "Local annotated tag + documented awaits-push follow-up (NOT a blocking checkpoint) — Phase 8 v0.1 honest-split precedent mirrored"

key-files:
  created:
    - .planning/phases/15-packaging-release-v0-2/15-03-SUMMARY.md
  modified: []

key-decisions:
  - "Verification-only plan — no source/manifest edits; Task 1 ran the six-step release gate and Task 2 stamped the local tag + recorded the honest split (Phase 8 v0.1 precedent)"
  - "v0.2.0 tag points at bd06d1e (HEAD = the completed Phase 15 release work: 15-02 close) and is NOT pushed — the standing no-push-credential blocker means push + observe-CI + the literal git+@v0.2.0 recipe are the sole human follow-ups"
  - "SC2's literal git+@v0.2.0#subdirectory recipe is documented-but-awaits-push (remote is public-but-empty); the path-based proof (scripts/proof_external_install.sh, PROOF OK) is the locally-verified equivalent — the resolution MECHANISM is proven (T-15-05 mitigation)"

patterns-established:
  - "Pattern 1: The Phase-15 release gate is the six-step PYTHONPATH= chain (build-all / sync-locked / ruff check / ruff format-check / pytest / proof script) — re-runnable as the milestone sign-off"
  - "Pattern 2: Local tag + awaits-push honest split — local CI-equivalent gate stands in for the remote run; the only gap is the push, recorded not as a checkpoint"

requirements-completed: [SC1, SC2, SC5]

# Metrics
duration: 4min
completed: 2026-05-25
---

# Phase 15 Plan 03: v0.2 Release Gate & Local Tag Summary

**Ran the full v0.2 release gate green — `uv build --all-packages` produced all five 0.2.0 wheels (SC1, no hatch config errors), `uv sync --locked --dev` passed, `ruff check` + `ruff format --check` were clean, the full offline pytest suite passed at 97.37% with the offline guard intact under the new live extra (SC5), and `scripts/proof_external_install.sh` printed `PROOF OK` (SC2) — then stamped a local annotated `v0.2.0` tag and recorded the honest local-vs-awaits-push split (push + observe-CI + the literal git+@v0.2.0 recipe are the sole human follow-ups, mirroring the Phase 8 v0.1 precedent).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-25T00:34:44Z
- **Completed:** 2026-05-25T00:38:xx (approx)
- **Tasks:** 2
- **Files created:** 1 (this SUMMARY); local annotated `v0.2.0` tag (not a tracked file)

## Accomplishments

- **SC1 — five 0.2.0 wheels build:** `PYTHONPATH="" uv build --all-packages -o dist/` exited 0 and produced `rosbagger_core-0.2.0`, `bagq-0.2.0`, `rosbagger_record-0.2.0`, `rosbagger_replay-0.2.0`, `rosbagger_gui-0.2.0` wheels (+ sdists) with NO hatchling config errors — hatchling src-layout auto-detection needs no `[tool.hatch.*]`, and none was added.
- **Lockfile current:** `PYTHONPATH="" uv sync --locked --dev` exited 0 (resolved 67 / checked 64 packages) — the lockfile re-locked at 0.2.0 in 15-01 is current; no "out of date" error.
- **Lint + format clean:** `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .` → "90 files already formatted".
- **SC5 — offline suite + offline guard green under the live extra:** `PYTHONPATH="" uv run pytest` → **466 passed, 3 skipped, 97.37% coverage** (gate >=80%). The SC5 anchor `tests/test_offline_guard.py` (incl. `test_import_gui_does_not_pull_ros`) is green — the 15-01 `rosbagger-gui[live]` extra did NOT regress the base `import rosbagger_gui` ROS-free invariant.
- **SC2 — external resolution proven:** `PYTHONPATH="" bash scripts/proof_external_install.sh` built + co-installed all five packages into a throwaway venv and ran its six smoke checks (`rosbagger-gui --help` exit 0; `bagq --version` == exactly `bagq 0.2.0`; all five imports; offline invariant base `import rosbagger_gui` leaks no rclpy/rosbag2_py; `tools` not in wheel) → final line `PROOF OK`.
- **Plan's full automated verify chain returned `GATE GREEN`** (all six steps re-run end-to-end in one pipeline).
- **Local annotated `v0.2.0` tag created** (`git tag -a v0.2.0`), points at `bd06d1e` (the Phase 15 release HEAD), `git cat-file -t` == `tag`. NOT pushed.

## Task Commits

Task 1 is verification-only (no source edits — the gate evidence is this SUMMARY). Task 2's artifact is the local tag + this SUMMARY:

1. **Task 1: Run the full v0.2 release gate (SC1/SC2/SC5)** — no source commit by design; produced the `GATE GREEN` evidence recorded above.
2. **Task 2: Create local v0.2.0 tag + record the honest split** — produced the local annotated tag `v0.2.0` (points at `bd06d1e`) + this SUMMARY.

**Plan metadata:** _(this SUMMARY + STATE/ROADMAP)_ committed separately (the final docs commit).

## Files Created/Modified

- `.planning/phases/15-packaging-release-v0-2/15-03-SUMMARY.md` — phase-gate evidence + honest local/awaits-push split (created)
- Local annotated `v0.2.0` git tag (not a tracked file; lives in `.git/refs/tags`)
- _(no source or manifest files changed — this is the verify-and-record gate plan)_

## Verification Results

### Verified locally (autonomous — this plan proves these)

- **SC1:** `uv build --all-packages -o dist/` → five 0.2.0 wheels, no hatch config errors.
- **SC2:** `scripts/proof_external_install.sh` → `PROOF OK` (external resolution by spec proven via the in-transaction path install; the resolution MECHANISM is proven).
- **SC4 (carried, re-confirmed):** `uv sync --locked --dev` green — lockfile coherent at 0.2.0.
- **SC5:** full offline suite (466 passed, 3 skipped, 97.37%) + `test_offline_guard.py` green under the live extra.
- **SC3 (carried):** INSTALL.md + per-package install/usage docs exist (15-02).
- **Tag:** local annotated `v0.2.0` exists (`git cat-file -t` == `tag`), points at `bd06d1e`.

### Awaits push (human follow-up — known recorded gap; the sole remaining step)

**The ONLY thing left to make the v0.2 milestone fully shipped:**

```bash
git push origin main
git push origin v0.2.0
# then observe the GitHub Actions "ci" run go green
```

Once pushed, the literal git+subdirectory recipes in `INSTALL.md` (e.g.
`uv pip install "git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/bagq" ...`)
run end-to-end. Until then they are **documented-but-awaits-push** (the remote is
public-but-empty). The path-based proof (`scripts/proof_external_install.sh`,
`PROOF OK`) is the locally-verified equivalent — it proves the resolution mechanism
(one-transaction co-install of the bare sibling spec), which is exactly what the
git recipe exercises once the remote has content.

**Blocked by:** no `gh` CLI and no push credential in this environment (standing
STATE.md blocker; `origin` = `https://github.com/AllenDevaraj/rosbagger.git`). This
is intentionally NOT a blocking checkpoint — the plan is `autonomous: true` and
everything achievable here is done. The local CI-equivalent gate (run above, all
green) is the strongest available proxy that the pushed CI run will pass: CI runs
the identical steps with no ROS installed (so the host PYTHONPATH leak is moot
there). Mirrors the Phase 8 v0.1 honest split.

## Decisions Made

- **Verification-only plan** — no source/manifest edits. Task 1 ran the six-step release gate; Task 2 stamped the local tag and recorded the split. Adding any `[tool.hatch.*]` config was explicitly avoided (hatchling auto-detects the src-layout).
- **`v0.2.0` tag points at `bd06d1e`** (HEAD = the completed Phase 15 release work) and is **NOT pushed** — the standing no-push-credential blocker means push + observe-CI + the literal git recipe execution are the sole human follow-ups.
- **SC2's literal git+@v0.2.0 recipe is documented-but-awaits-push** (T-15-05 mitigation) — only the path-based proof is claimed verified; the git recipe is honestly flagged, not asserted to "work" against an empty remote.

## Deviations from Plan

None - plan executed exactly as written.

## Authentication Gates

None encountered. (The empty/un-pushed GitHub remote is a known standing environment
limitation, handled as the documented awaits-push follow-up above — not an auth gate
hit mid-task.)

## Issues Encountered

None. Every gate step behaved exactly as the 15-RESEARCH "Code Examples" and the
15-01/15-02 summaries predicted: `--all-packages` built all five wheels, the
re-locked lockfile stayed in sync, ruff was clean, the full suite (incl. the offline
guard) passed under the live extra, and the proof script printed `PROOF OK`.

## User Setup Required

None for the software itself. The single remaining human action is the release push
(see "Awaits push" above): push `main` + the `v0.2.0` tag and confirm the GitHub
Actions run is green. This finalizes the v0.2 milestone.

## Threat Surface

No new security-relevant surface (verify-and-record plan). Threat register
dispositions honored:
- **T-15-05 (Repudiation — claiming the git+@v0.2.0 recipe "works" against an empty remote):** mitigated — this SUMMARY records it as awaits-push; only the path-based proof (autonomous) is claimed verified.
- **T-15-06 (Information disclosure — offline regression slipping through under the host ROS leak):** mitigated — the gate ran `PYTHONPATH="" uv run pytest` including `test_offline_guard.py`; the offline guard is green under the live extra.
- **T-15-SC (Tampering — package installs):** accept — no new external packages; the gate only built first-party wheels + re-confirmed the already-vetted locked deps.

## Next Phase Readiness

- **v0.2 milestone is autonomously complete** for everything achievable in this
  environment: all five packages built, the external-install proof green, the full
  offline gate + offline guard green under the live extra, and a local annotated
  `v0.2.0` tag stamped.
- **Sole remaining gap:** push `main` + `v0.2.0` and observe CI green (blocked on the
  standing push-credential blocker). PHASE 15 COMPLETE (3/3).
- No new dependencies and no runtime code were added; the offline/no-ROS invariant and
  the >=80% coverage gate are intact.

## Self-Check: PENDING (filled after write)

---
*Phase: 15-packaging-release-v0-2*
*Completed: 2026-05-25*
