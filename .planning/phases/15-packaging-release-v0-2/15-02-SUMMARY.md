---
phase: 15-packaging-release-v0-2
plan: 02
subsystem: infra
tags: [packaging, install-docs, proof, external-venv, git-subdirectory, uv, pip, offline-invariant]

# Dependency graph
requires:
  - phase: 15-packaging-release-v0-2
    plan: 01
    provides: "all five packages at v0.2.0, sibling deps pinned rosbagger-core>=0.2,<0.3, gui [live] extra, re-locked uv.lock"
  - phase: 08-packaging-docs-release
    provides: "v0.1 clean-room recipe + honest local/awaits-push split precedent"
provides:
  - "scripts/proof_external_install.sh — autonomous path-based external-venv proof (build/co-install all five into a throwaway venv, smoke CLI + imports + offline invariant + tools-not-in-wheel; prints PROOF OK)"
  - "INSTALL.md — central install + usage docs (D-04): why-one-command callout, one-transaction git meta recipe, per-package git+subdirectory snippets, local path install, consumer-side [tool.uv.sources], rosbagger-gui[live] note, proof recipe, awaits-push flag"
affects: [15-03, packaging, release, docs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One-transaction sibling resolution: name all needed packages in ONE pip/uv pip install so the bare spec resolves against a co-installed candidate (no index)"
    - "Path-based external-venv proof = autonomous gate; literal git+@v0.2.0 recipe documented but flagged awaits-push (remote empty) — Phase 8 honest split"
    - "Every proof venv python/pip/CLI invocation prefixed PYTHONPATH=\"\" to neutralize the host ROS-on-PYTHONPATH leak that would mask the offline assertion"

key-files:
  created:
    - scripts/proof_external_install.sh
    - INSTALL.md
  modified: []

key-decisions:
  - "Encoded the proof as a committed script (RESEARCH Open Q1 recommendation) rather than document-only — cheap, repeatable, doubles as living documentation; runs from any cwd via repo-root resolved from BASH_SOURCE"
  - "Included the tools-not-in-wheel assertion in the proof (RESEARCH Open Q2) — cheap regression lock that the three new wheels stay clean"
  - "Git+@v0.2.0 recipes are DOCUMENTED with an explicit awaits-push flag, NOT a blocking checkpoint — remote is public-but-empty; the path-based proof is the locally-verified gate (Phase 8 precedent, A1 low-risk)"

patterns-established:
  - "Pattern 1: A committed proof script that co-installs into a throwaway non-.venv venv from a neutral cwd is the autonomous gate for external resolvability"
  - "Pattern 2: Install docs lead with the one-transaction recipe + a why-one-command callout; no single-package install is ever presented as primary"

requirements-completed: [SC2, SC3]

# Metrics
duration: 3min
completed: 2026-05-25
---

# Phase 15 Plan 02: External-Install Proof & INSTALL.md Summary

**Proved the v0.2.0 wheel-resolution gap is closed with a committed `scripts/proof_external_install.sh` that co-installs all five packages by local path into a throwaway venv outside the monorepo (PROOF OK: `bagq 0.2.0`, five imports, zero rclpy/rosbag2_py leak, `tools` not importable), and documented every install path in a central `INSTALL.md` — the one-transaction git meta recipe, per-package git+subdirectory snippets, local path install, consumer-side `[tool.uv.sources]`, the `rosbagger-gui[live]` note, and an explicit awaits-push flag on the git recipes.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-25T00:29:05Z
- **Completed:** 2026-05-25T00:32:09Z
- **Tasks:** 2
- **Files created:** 2 (scripts/proof_external_install.sh, INSTALL.md)

## Accomplishments

- `scripts/proof_external_install.sh`: an executable, autonomous, network-free proof that resolves the repo root from its own location (runs from any cwd), creates a throwaway `python3 -m venv` (never `.venv`) with a cleanup trap, co-installs all five packages by local path in ONE `pip` invocation (`rosbagger-core bagq rosbagger-record rosbagger-replay rosbagger-gui[live]`) so the bare sibling spec resolves in-transaction, `cd`s to a neutral cwd outside the monorepo, then runs six smoke checks: `rosbagger-gui --help` exit 0, `bagq --version` == exactly `bagq 0.2.0`, all five imports, the offline invariant (base `import rosbagger_gui` leaks no `rclpy`/`rosbag2_py`), and tools-not-in-wheel (`import tools` raises `ModuleNotFoundError`). Every venv python/pip/CLI invocation is prefixed `PYTHONPATH=""`. Prints exactly `PROOF OK` on success. No `uv run`, no `.venv` reference.
- Proof executed green: all five wheels build, install, and the six smoke checks pass — `PROOF OK` is the final line (verified twice; once via the exact plan-verify pipeline `… | tail -1 | grep -qx "PROOF OK"`).
- `INSTALL.md`: central D-04 docs leading with a "why one command" callout (bare sibling spec has no index → every external install must name all needed packages in one transaction; single-package install fails and is never primary), then the one-transaction git meta recipe (all five `git+…@v0.2.0#subdirectory=packages/<pkg>` URLs, both `uv pip install` and `pip install` forms), per-package git+subdirectory snippets (cli; gui-offline; gui[live] co-naming record+replay+core), the local path-install snippet, the consumer-side `[tool.uv.sources]` recipe (downstream uv project, dev-only, never baked into our wheels), the `rosbagger-gui[live]` live-panel note (D-02 offline base + opt-in extra), a pointer to the proof script with inline steps, and an explicit awaits-push flag on the git+`@v0.2.0` recipes.

## Task Commits

Each task was committed atomically:

1. **Task 1: Commit scripts/proof_external_install.sh** - `33865cc` (feat)
2. **Task 2: Write central INSTALL.md** - `6f093bc` (docs)

**Plan metadata:** _(this SUMMARY + STATE/ROADMAP)_ committed separately.

## Files Created/Modified

- `scripts/proof_external_install.sh` - autonomous path-based external-venv proof (created; executable)
- `INSTALL.md` - central install + usage docs covering every install path (created)

## Decisions Made

- Encoded the proof as a committed script (RESEARCH Open Q1) rather than document-only — repeatable and doubles as living documentation; the repo root is resolved from `BASH_SOURCE` so it runs from any cwd.
- Included the tools-not-in-wheel assertion (RESEARCH Open Q2) — cheap regression lock that the three new wheels stay clean alongside core/bagq.
- The git+`@v0.2.0` recipes are documented with an explicit awaits-push flag, NOT a blocking checkpoint — the public remote is empty, so the literal git recipe cannot run end-to-end locally; the path-based proof is the locally-verified gate (Phase 8 honest-split precedent; RESEARCH A1 is structurally low-risk because the resolution mechanism is proven via the path install).

## Deviations from Plan

None - plan executed exactly as written.

## Authentication Gates

None encountered. (The empty/un-pushed GitHub remote is a known standing environment limitation, handled as the documented awaits-push flag in INSTALL.md — not an auth gate hit mid-task.)

## Issues Encountered

None. The proof behaved exactly as the RESEARCH "Code Examples" predicted: the one-transaction co-install resolved the bare sibling spec, and all six smoke checks passed from the neutral cwd with `PYTHONPATH=""`.

## User Setup Required

None for this plan. The standing milestone follow-up remains: push `main` + a `v0.2.0` tag to `https://github.com/AllenDevaraj/rosbagger` so the documented git+subdirectory recipes run end-to-end (blocked on the standing no-push-credential limitation; not a blocker for this plan).

## Threat Surface

No new security-relevant surface. Threat register dispositions honored:
- **T-15-03 (proof passing via workspace source):** mitigated — fresh `python3 -m venv` (not `.venv`), neutral cwd outside the repo, path install (not `-e`), `PYTHONPATH=""`.
- **T-15-04 (offline assertion masked by host ROS leak):** mitigated — all proof commands prefixed `PYTHONPATH=""`; the assertion scans `sys.modules` for `rclpy`/`rosbag2_py` and the run came back clean.
- **T-15-SC (package installs):** accept — the proof installs only first-party local-path packages + their already-vetted PyPI deps. No new external package surface; INSTALL.md keeps all URLs in install commands / consumer-side sources, never in our `[project] dependencies`.

## Next Phase Readiness

- SC2 (external resolution proven) and SC3 (per-package install/usage docs) are met. The autonomous proof is committed and green; INSTALL.md is complete.
- Plan 03 owns the phase gate (`uv build --all-packages`, the CI-equivalent gate, offline guard) and the milestone close. No blockers.

## Self-Check: PASSED

- FOUND: `scripts/proof_external_install.sh`
- FOUND: `INSTALL.md`
- FOUND: `.planning/phases/15-packaging-release-v0-2/15-02-SUMMARY.md`
- FOUND: commit `33865cc` (Task 1)
- FOUND: commit `6f093bc` (Task 2)

---
*Phase: 15-packaging-release-v0-2*
*Completed: 2026-05-25*
