---
status: passed
phase: 15-packaging-release-v0-2
verified: 2026-05-24
method: inline (gsd-verifier not installed; orchestrator verified the DoD against the live repo incl. an autonomous external-venv proof and the full local CI-equivalent gate)
must_haves_total: 5
must_haves_verified: 5
plans_complete: 3
requirements: ["(Definition of Done — git/path-installable packages, coherent versioning, install docs; infrastructure phase like Phase 8, no new REQ-ID)"]
---

# Phase 15: Packaging & Release v0.2 — Verification

Phase goal: make the v0.2 packages git/path-installable into other repos with coherent versioning and central install docs (no index publish — user decision; mirrors Phase 8's v0.1 work for the four packages it didn't cover).

## Success Criteria (verified against the live repo)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| SC1 | All five wheels build | `PYTHONPATH="" uv build --all-packages -o dist/` → 5 × 0.2.0 wheels (core, bagq, record, replay, gui); no hatchling config errors (15-03 gate) | ✓ |
| SC2 | External venv resolves the bare sibling spec by transaction | `scripts/proof_external_install.sh` re-run by orchestrator → `PROOF OK`: fresh `python3 -m venv` outside the monorepo, one-transaction path install, `rosbagger-gui --help` exit 0, `bagq --version` → `bagq 0.2.0`, five imports, offline invariant, `tools` not importable | ✓ |
| SC3 | Per-package install + usage docs exist | `INSTALL.md` present: one-transaction git+subdirectory meta recipe, per-package snippets, path install, consumer-side `[tool.uv.sources]`, `rosbagger-gui[live]` note, proof pointer, awaits-push flag (grep checks pass) | ✓ |
| SC4 | Versions coherent at 0.2.0 + re-locked | 10 sites (5 pyproject `version` + 5 `__version__`) at 0.2.0; 4 sibling deps pinned `rosbagger-core>=0.2,<0.3`; gui `[live]` extra; `uv.lock` re-locked; `uv sync --locked --dev` green | ✓ |
| SC5 | Offline suite + guard green under the live extra | `PYTHONPATH="" uv run pytest` → 466 passed, 3 skipped, 97.37% (>=80% gate); `tests/test_offline_guard.py` incl. `test_import_gui_does_not_pull_ros` green after the live extra was added | ✓ |
| — | Local `v0.2.0` tag (not pushed) | Annotated tag `v0.2.0` exists ("rosbagger v0.2.0 — Modular cockpit…"); confirmed absent from remote | ✓ (local) / ⏸ (remote, human-gated) |

## Definition of Done

- ✓ All five packages git/path-installable into an external project (sibling spec resolves in one transaction; proven by the path-based proof — the resolution MECHANISM is verified)
- ✓ Coherent v0.2.0 versioning across all five packages + re-locked lockfile
- ✓ Central INSTALL.md documents every install path
- ✓ Base `import rosbagger_gui` stays ROS-free after the declarative `live` extra (SC5 offline guard)
- ✓ No git/path URL baked into any `[project] dependencies` (version spec only — D-01)

## Automated Checks (15-03 release gate, all green, every step `PYTHONPATH=""`)

- `uv build --all-packages` → five 0.2.0 wheels
- `uv sync --locked --dev` → lockfile current
- `uv run ruff check .` + `ruff format --check .` → clean (90 files)
- `uv run pytest` → 466 passed / 3 skipped / 97.37%
- `scripts/proof_external_install.sh` → `PROOF OK`

## Code Review

15-REVIEW.md: 0 blocker, 4 warning, 2 info (advisory). No blocking findings — warnings are hardening nits (unbounded `pyarrow>=18`/`rich>=13` upper caps, proof venv pip-upgrade, a step-count doc/script mismatch). Tracked for a future hardening pass; none gate the release.

## Sole Human Follow-up (remote half — NOT a blocker for local readiness)

`git push origin main && git push origin v0.2.0`, then confirm GitHub Actions goes green and run the literal `git+…@v0.2.0#subdirectory=…` recipe end-to-end. Blocked in this environment by the standing no-push-credential limitation (`origin = https://github.com/AllenDevaraj/rosbagger.git`, public but empty). The path-based proof + local CI-equivalent gate are the locally-verified equivalents; this is the one step the maintainer must run.

## Verdict

PASSED — all 5 success criteria verified locally; phase goal achieved. Remote push is the documented, human-gated follow-up (Phase 8 honest-split precedent).
