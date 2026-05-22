# Phase 8: Packaging, Docs & Release - Research

**Researched:** 2026-05-22
**Domain:** Python packaging (hatchling + uv workspace), plain-`pip` install of a virtual monorepo, release hygiene (versioning, docs, LICENSE, git tag), CI green-gating
**Confidence:** HIGH (the crux recipe + every success criterion was empirically verified in clean throwaway venvs on this exact repo, Python 3.10.12 / pip 22.0.2 / uv 0.11.14)

## Summary

Phase 8 is the FINAL v0.1 phase. The substance is small but the one genuine risk is large: **plain `pip` cannot resolve the intra-workspace dependency.** `bagq`'s `pyproject.toml` declares a bare `dependencies = ["rosbagger-core", ...]`, and the only thing that maps that name to the local package is the ROOT pyproject's `[tool.uv.sources] rosbagger-core = {workspace=true}`. The uv docs are explicit that sources are uv-only: *"sources are only respected by uv. If another tool is used, only the definitions in the standard project tables will be used."* `[CITED: docs.astral.sh/uv/concepts/projects/dependencies]` I proved the consequence empirically — `pip install ./packages/bagq` alone dies with `ERROR: Could not find a version that satisfies the requirement rosbagger-core (from bagq) (from versions: none)` because pip tries PyPI, where it is unpublished.

The fix is to **install both local packages in one `pip` command** so pip sees `rosbagger-core` as a locally-buildable distribution in the same resolution set: `pip install ./packages/rosbagger-core ./packages/bagq` (or `-e` for the dev path). I verified this end-to-end in a clean venv with `PYTHONPATH=""`: both hatchling wheels build, `bagq --help` exits 0, `bagq info/tables/query --help` all exist, `bagq --version` reports the version, `import rosbagger_core, bagq` succeeds with **no rclpy present**, and `tools/` is NOT in either wheel. `bagq[plot]` cleanly pulls matplotlib. All three success criteria are achievable; SC1 and SC2 are fully autonomous, SC3 is split — build/lint/suite/local-tag are autonomous, but **observing CI-green and pushing the tag are blocked by the standing `gh`/push auth blocker.**

Two concrete gotchas the planner must encode: (1) `uv.lock` pins `version = "0.0.0"` for both packages, so bumping the pyproject version WITHOUT re-running `uv lock` makes `uv sync --locked` FAIL in CI; the bump task must re-lock. (2) Version lives in TWO places per package (pyproject `version` + `__init__.py __version__`) — bump both, or adopt hatchling dynamic version to single-source it.

**Primary recommendation:** Bump both packages to `0.1.0` in pyproject AND `__init__.py` (4 edits), re-run `uv lock`, expand the README around the verified `pip install ./packages/rosbagger-core ./packages/bagq` recipe plus the `uv sync` dev path, add a permissive `LICENSE` (MIT) at the repo root, verify the suite/lint/build locally, create an annotated `v0.1.0` git tag locally, and explicitly flag the CI-run + tag-push as human-gated on the auth blocker.

## Project Constraints (from CLAUDE.md)

These are authoritative directives — research recommendations do not contradict them.

- **Python ≥ 3.10.** (Both pyprojects declare `requires-python = ">=3.10"`; dev pinned to 3.10 floor via `.python-version`; CI matrix 3.10/3.12.)
- **No ROS dependency for offline modules.** `rosbagger-core` and `bagq` MUST import without `rclpy`/ROS. (Enforced by `tests/test_offline_guard.py` — a `sys.meta_path` blocker.)
- **Offline tools run anywhere, CI included, with no ROS install.** Packaging must not introduce a ROS dependency or a platform-specific install step.
- **Emit standard formats; never rebuild existing viewers.** (Not directly a packaging concern, but the README must not over-promise visualization.)
- **GSD workflow enforcement:** all file edits go through a GSD command. (Process note for execution, not a packaging artifact.)

## User Constraints (no CONTEXT.md present)

No `*-CONTEXT.md` exists in the phase directory — the project is at `status: ready_to_plan` and the discuss step has not produced locked decisions. The orchestrator-supplied **additional_context** carries the planner's intent and is treated here as soft guidance (NOT locked decisions — the discuss-phase or planner should confirm):

- **Locked-by-roadmap:** 1 plan (`08-01`): "Packaging polish, README/usage, offline-import check, v0.1."
- **Success criteria (from ROADMAP.md / DoD):** (1) `pip install` yields a working `bagq` with `--help`; (2) offline packages import without `rclpy`; (3) CI is green; version tagged 0.1.
- **Soft guidance from additional_context:** bump both packages 0.0.0→0.1.0 (pyproject + `__init__.py`); expand README with verified install recipe + per-command quickstart; create the `v0.1` tag locally but treat push+CI-green as human-gated; consider a LICENSE; keep `tools/` dev-only.

## Architectural Responsibility Map

This phase is packaging/release, not runtime feature work — "tiers" map to packaging layers and the two distributions.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Intra-workspace dep resolution (dev) | Root pyproject `[tool.uv.sources]` | uv resolver | uv-only; never reaches pip/distribution metadata |
| Intra-workspace dep resolution (pip install) | The install command (both pkgs in one set) | pip resolver | pip ignores `[tool.uv.sources]`; both local dists must be in the same resolution |
| Wheel/sdist build | hatchling (per-package `[build-system]`) | `python -m build` / `uv build` | Each package self-builds; auto src-layout detection |
| Console script `bagq` | `bagq` pkg `[project.scripts]` | — | Entry point baked into the bagq wheel |
| Offline-import guarantee | `rosbagger_core/__init__` + `bagq/cli` import discipline | `tests/test_offline_guard.py` | Top-level imports stay light; heavy stack lazy-imported |
| Version single-source | pyproject `version` + `__init__.__version__` (today: duplicated) | hatchling dynamic version (optional) | `bagq --version` reads `bagq.__init__.__version__` |
| Reproducible install | committed `uv.lock` | CI `uv sync --locked` | Lockfile must match manifests or `--locked` fails |
| Release tag | git annotated tag `v0.1.0` | remote push (BLOCKED) | Local creation autonomous; push needs auth |

## Standard Stack

This phase adds NO new runtime packages. The "stack" is the build/release toolchain, all already present in the repo or trivially invoked.

### Core (build & release toolchain)
| Tool | Version (verified) | Purpose | Why Standard |
|------|--------------------|---------|--------------|
| `hatchling` | (build backend, fetched per-build) | Build wheels/sdists for both packages | Already each package's `build-backend`; auto-detects src-layout + hyphen→underscore name with zero extra config `[VERIFIED: built both wheels on this repo]` |
| `uv` | 0.11.14 | Workspace sync, lock, `uv build`, `uv run` (CI driver) | Project's chosen tool; `uv sync --locked` is the CI install `[VERIFIED: command-line]` |
| `pip` | 22.0.2 (system) | The plain-`pip` install path the DoD requires | DoD literally says "installs via `pip`"; verified the recipe `[VERIFIED: clean venv]` |
| `python -m venv` | stdlib (3.10.12) | Clean throwaway venv for the verification gate | Stdlib; no extra dep `[VERIFIED]` |
| `python -m build` / `uv build` | both work | Produce release sdist+wheel | Both produced valid artifacts for both packages `[VERIFIED]` |

### Supporting (release hygiene artifacts)
| Artifact | Purpose | When to Use |
|----------|---------|-------------|
| `LICENSE` (MIT recommended) | Legal clarity for a public repo / future publish | Add at repo root; see Open Questions Q1 |
| `CHANGELOG.md` (optional) | Human-readable 0.1 release notes | Optional for v0.1; nice-to-have |
| Annotated git tag `v0.1.0` | Marks the release commit | Create locally; push gated on auth |
| README "Install"/"Usage" sections | The user-facing doc surface | Required by phase goal |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pip install ./pkg-a ./pkg-b` (both local) | Publish `rosbagger-core` to PyPI first, then `pip install bagq` | Out of scope for v0.1 (local install only); adds a publish step + account setup. The DoD is satisfied by local install. |
| Duplicated `version` in pyproject + `__init__` | hatchling dynamic version (`dynamic=["version"]`, `[tool.hatch.version] path=...`) | Dynamic version single-sources it but adds config + a `dynamic` field; for a one-shot 0.0.0→0.1.0 bump, editing 4 lines is simpler. See Open Q2. |
| MIT LICENSE | Apache-2.0 / BSD-3 | All permissive; MIT is shortest and most common for tooling. User's call. |
| `python -m build` | `uv build --package <name>` | Both verified working; `uv build` is workspace-native and already available (no `build` install). Prefer `uv build` for consistency. |

**Installation (the verified v0.1 recipe — for the README):**
```bash
# End-user install (plain pip, no uv) — BOTH local packages in ONE command:
python3 -m venv .venv && . .venv/bin/activate
pip install ./packages/rosbagger-core ./packages/bagq
# with the optional plotting extra (quote to stop shell glob-expansion of [plot]):
pip install ./packages/rosbagger-core "./packages/bagq[plot]"
bagq --help

# Developer setup (uv workspace — editable, reproducible from uv.lock):
uv sync --locked --dev
uv run bagq --help
uv run pytest
```

**Version verification (performed this session):**
```bash
python3 --version   # Python 3.10.12  [VERIFIED]
pip --version       # pip 22.0.2       [VERIFIED]
uv --version        # uv 0.11.14       [VERIFIED]
```
Built artifact versions observed in the clean install: `duckdb-1.5.3, pyarrow-24.0.0, rosbags-0.11.2, sqlglot-30.8.0, typer-0.25.1, rich-15.0.0, numpy-2.2.6, matplotlib-3.10.9` — all resolve within the pyproject specifiers. `[VERIFIED: clean venv install]`

## Package Legitimacy Audit

This phase installs **no new external packages.** All runtime dependencies were vetted and approved in Phases 1–6 (per STATE.md decision log: rosbags, duckdb, sqlglot, pyarrow, typer, rich, matplotlib — all "Package Legitimacy: Approved"). The two local packages are first-party (`rosbagger-core`, `bagq`).

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| `rosbagger-core` | local (this repo) | First-party | n/a — built from `packages/rosbagger-core` |
| `bagq` | local (this repo) | First-party | n/a — built from `packages/bagq` |
| (all runtime deps) | PyPI | Approved in P1–P6 | No change in P8 |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new installs).
**Packages flagged as suspicious [SUS]:** none.

*slopcheck was not invoked because Phase 8 introduces zero new dependencies. If the planner adds any (e.g., a dynamic-version plugin like `hatch-vcs`), run the Package Legitimacy Gate before that install.*

## Architecture Patterns

### System Architecture Diagram — the install resolution path (THE crux)

```
                    ┌─────────────────────────────────────────────────┐
                    │  DEV PATH (uv)                                   │
  uv sync ─────────►│  reads root pyproject [tool.uv.sources]         │
                    │  rosbagger-core = {workspace=true}              │
                    │  → resolves bagq's "rosbagger-core" dep to the  │
                    │    LOCAL editable package. WORKS.               │
                    └─────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────┐
  pip install       │  RELEASE PATH (plain pip)                       │
   ./bagq  ────────►│  pip IGNORES [tool.uv.sources] (uv-only).       │
   (alone)          │  Sees bare "rosbagger-core" → tries PyPI →      │
                    │  unpublished → ✗ FAILS:                         │
                    │  "No matching distribution found for            │
                    │   rosbagger-core"                               │
                    └─────────────────────────────────────────────────┘
                                       │ FIX
                                       ▼
  pip install       ┌─────────────────────────────────────────────────┐
   ./rosbagger-core │  Both local dists in ONE resolution set.        │
   ./bagq  ────────►│  pip builds rosbagger-core wheel (hatchling),   │
                    │  satisfies bagq's bare dep from THAT wheel.     │
                    │  → installs both + transitive deps. ✓ WORKS.    │
                    │  bagq --help exit 0; import w/o rclpy; no tools/│
                    └─────────────────────────────────────────────────┘
```

### Recommended file changes (this phase touches few files)
```
rosbagger/
├── README.md                                  # EXPAND: install recipe + per-command usage
├── LICENSE                                     # ADD (MIT) — repo root
├── CHANGELOG.md                                # OPTIONAL: 0.1 notes
├── uv.lock                                     # RE-LOCK after version bump (else --locked fails)
├── packages/rosbagger-core/
│   ├── pyproject.toml                          # version 0.0.0 → 0.1.0 (+ optional description/readme/license)
│   └── src/rosbagger_core/__init__.py          # __version__ "0.0.0" → "0.1.0"
└── packages/bagq/
    ├── pyproject.toml                          # version 0.0.0 → 0.1.0 (+ optional description/readme/license)
    └── src/bagq/__init__.py                    # __version__ "0.0.0" → "0.1.0"
```

### Pattern 1: Multi-local-package pip install (resolve the bare intra-workspace dep)
**What:** Pass every local distribution that the others depend on in a single `pip install` invocation so pip's resolver can satisfy bare same-repo deps from locally-built wheels instead of PyPI.
**When to use:** Any time a uv-workspace member is installed with plain pip (the DoD requirement here).
**Example (verified on this repo):**
```bash
# Source: empirically VERIFIED this session in a clean venv with PYTHONPATH=""
python3 -m venv /tmp/t && . /tmp/t/bin/activate
pip install ./packages/rosbagger-core ./packages/bagq   # both, one command
bagq --help            # exit 0
python -c "import rosbagger_core, bagq"   # OK, no rclpy
```

### Pattern 2: Bump version in lockstep across all version sources
**What:** The version string lives in 3 lockfile-relevant locations per package today: `pyproject.toml version`, `src/<pkg>/__init__.py __version__`, and the recorded `version` line in `uv.lock`. Bump all consistently.
**When to use:** The 0.0.0 → 0.1.0 release.
**Example:**
```bash
# Edit the 4 source lines (2 pyproject + 2 __init__), then RE-LOCK so uv.lock matches:
uv lock                       # rewrites uv.lock version lines to 0.1.0
uv sync --locked --dev        # must succeed (proves lock is in sync — CI runs this)
uv run bagq --version         # must print "bagq 0.1.0"
```

### Pattern 3: Clean-room install verification (the SC1/SC2 gate)
**What:** Verify the install in a throwaway venv that is NOT the uv `.venv` and with `PYTHONPATH=""` (to neutralize the host ROS-on-PYTHONPATH leak — Phase 1 decision), then check `--help` exit, subcommand help, version, offline import, and the no-rclpy / no-tools invariants from a NEUTRAL cwd.
**When to use:** As the phase's acceptance gate.
**Example (verified):**
```bash
# Source: VERIFIED this session
export PYTHONPATH=""
python3 -m venv /tmp/verify && /tmp/verify/bin/pip install ./packages/rosbagger-core ./packages/bagq
/tmp/verify/bin/bagq --help                                  # exit 0
for s in info tables query; do /tmp/verify/bin/bagq $s --help >/dev/null; done   # all exit 0
cd /tmp && /tmp/verify/bin/python -c "import rosbagger_core, bagq"                # OK
cd /tmp && /tmp/verify/bin/python -c "import importlib.util as u; assert u.find_spec('rclpy') is None"
cd /tmp && /tmp/verify/bin/python -c "import importlib.util as u; assert u.find_spec('tools') is None"  # MUST run from neutral cwd
```

### Anti-Patterns to Avoid
- **Installing `bagq` alone with pip:** `pip install ./packages/bagq` FAILS (`No matching distribution found for rosbagger-core`). Always pass both. `[VERIFIED]`
- **Bumping `version` without re-locking:** `uv.lock` still says `0.0.0` → `uv sync --locked` fails in CI with a lockfile-mismatch error. Re-run `uv lock`. `[VERIFIED: uv.lock pins version]`
- **Running the verification in the uv `.venv` or the ROS-sourced shell:** the `.venv` already has both packages editable-installed (false pass), and a ROS shell leaks `rclpy`/`tools` onto the path. Use a fresh `venv` + `PYTHONPATH=""`. `[VERIFIED: tools was importable only from repo-root cwd]`
- **Checking `tools` importability from the repo-root cwd:** `''` (cwd) is on `sys.path`, so `./tools/` imports even though it is NOT in any wheel. Run the no-tools check from `/tmp`. `[VERIFIED]`
- **Forgetting to quote `[plot]`:** `pip install ./packages/bagq[plot]` may be glob-expanded by some shells; quote it: `"./packages/bagq[plot]"`. `[VERIFIED extra resolves]`
- **Promising `pip install bagq` from PyPI in the README:** it is unpublished; v0.1 is a local install only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Build wheels/sdists | A custom build script / manual zip | `uv build --package <name>` (or `python -m build`) | hatchling auto-detects src-layout + name mapping; both verified to produce valid artifacts |
| Resolve intra-workspace dep for pip | A `find_links` hack / sys.path shim / vendoring | Install both local packages in one `pip` command | Standard pip behavior; verified; zero extra config |
| Version single-sourcing (if desired) | A regex sed across files at build time | hatchling `dynamic=["version"]` + `[tool.hatch.version] path=...` | Official hatchling feature; reads `__version__` from one file `[CITED: hatch.pypa.io/1.9/version]` |
| Reproducible CI install | Pin every transitive dep by hand | committed `uv.lock` + `uv sync --locked` | Already in place; the lockfile IS the pin |
| Exclude `tools/` from wheels | Custom MANIFEST excludes | Nothing — src-layout already excludes it | `tools/` lives outside both `src/` trees; verified absent from both wheels |

**Key insight:** Almost everything in this phase is "configure correctly and verify," not "build." The single non-obvious thing is the multi-package pip install — and that is a one-line command, not code. The biggest risk is *omitting* the re-lock or the second `__init__.py` edit, not writing something hard.

## Runtime State Inventory

This phase has a rename-like sub-task (the 0.0.0 → 0.1.0 version string) and a release artifact, so a focused inventory applies. After every *source* file is updated, what still carries the old string?

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore stores the version string. Verified: no DB/collection keys on version. | none |
| Live service config | None — no external service holds the version. | none |
| OS-registered state | None — no OS task/service references the version. | none |
| Secrets/env vars | None — no secret/env var encodes the version. | none |
| Build artifacts / lockfile | **`uv.lock` records `version = "0.0.0"` for BOTH packages** (lines 121 + 1239). A source bump without `uv lock` leaves the lock stale → `uv sync --locked` fails in CI. Also: any previously-built wheels/dist (none committed; `dist/` is gitignored). | **`uv lock` after the bump** (data-migration-equivalent: the lock must be regenerated, not just the manifest edited). `[VERIFIED: grep uv.lock]` |
| Version string in source | `version` in 2 pyprojects + `__version__` in 2 `__init__.py` (all "0.0.0") + the `uv.lock` entries above. `bagq --version` reads `bagq.__init__.__version__`. | Edit all 4 source lines; re-lock; assert `bagq --version` prints `0.1.0`. `[VERIFIED: locations]` |

**The canonical question — after every repo file is updated, what runtime systems still have the old string?** Only `uv.lock` (regenerated by `uv lock`) and any locally-built wheels (rebuilt from source; none committed). No external/runtime state.

## Common Pitfalls

### Pitfall 1: `pip install ./packages/bagq` alone fails (the #1 risk)
**What goes wrong:** Installing just `bagq` errors with `ERROR: Could not find a version that satisfies the requirement rosbagger-core (from bagq) (from versions: none)`.
**Why it happens:** pip ignores `[tool.uv.sources]` (uv-only `[CITED: docs.astral.sh/uv]`); the bare `rosbagger-core` dep is sought on PyPI, where it is unpublished.
**How to avoid:** Always install BOTH local packages in one command: `pip install ./packages/rosbagger-core ./packages/bagq`. Document exactly this in the README.
**Warning signs:** Any README/docs/CI step that installs `bagq` without also naming `rosbagger-core`. `[VERIFIED: reproduced the failure]`

### Pitfall 2: Stale `uv.lock` breaks `uv sync --locked` after the version bump
**What goes wrong:** CI step `uv sync --locked --dev` fails with a lockfile-out-of-sync error after `version` is bumped in pyproject but `uv.lock` still says `0.0.0`.
**Why it happens:** `--locked` refuses to proceed if the lockfile does not match the manifests; `uv.lock` pins each workspace member's `version`.
**How to avoid:** Run `uv lock` immediately after editing the pyproject versions, and verify `uv sync --locked --dev` succeeds locally before committing. Commit the regenerated `uv.lock`.
**Warning signs:** A diff that touches `pyproject.toml version` but not `uv.lock`. `[VERIFIED: uv.lock pins version=0.0.0 at lines 121, 1239]`

### Pitfall 3: Version drift between pyproject and `__init__.__version__`
**What goes wrong:** `pyproject.toml` says `0.1.0` (so the wheel metadata is `0.1.0`) but `bagq --version` still prints `0.0.0` because `bagq/__init__.py __version__` was not bumped.
**Why it happens:** The version is duplicated; `bagq --version` reads `bagq.__init__.__version__`, not the dist metadata. `[VERIFIED: cli.py imports __version__ from bagq.__init__]`
**How to avoid:** Bump all 4 source lines together (or adopt hatchling dynamic version — Open Q2). Add an acceptance check: `bagq --version` prints `bagq 0.1.0` AND `import rosbagger_core; assert __version__ == "0.1.0"`.
**Warning signs:** `bagq --version` and the installed wheel METADATA `Version:` disagree.

### Pitfall 4: Verifying in a contaminated environment (false pass / false fail)
**What goes wrong:** The install "passes" in the uv `.venv` (both packages already editable-installed) or "fails"/leaks when run in a ROS-sourced shell (rclpy on PYTHONPATH; `tools` importable from repo-root cwd).
**Why it happens:** The `.venv` is not a clean room; the host has ROS on `PYTHONPATH`; cwd `''` is on `sys.path` so `./tools/` imports.
**How to avoid:** Verify in a fresh `python3 -m venv` (NOT `.venv`), `export PYTHONPATH=""`, and run the no-rclpy/no-tools assertions from a NEUTRAL cwd (`/tmp`).
**Warning signs:** `tools importable: True` from the repo root (benign artifact of cwd-on-path), or `rclpy present: True` (means the shell sourced ROS). `[VERIFIED: tools importable only from repo-root cwd; False from /tmp]`

### Pitfall 5: Treating SC3 ("CI green; tagged 0.1") as fully autonomous
**What goes wrong:** The phase tries to push the tag / observe CI green and stalls, because there is no `gh` CLI and no push credential (standing STATE.md blocker; `origin` set to `https://github.com/AllenDevaraj/rosbagger.git`).
**Why it happens:** GitHub push auth is pending; the runner cannot push.
**How to avoid:** Split SC3 explicitly. **Autonomous:** run the equivalent CI steps LOCALLY (`uv sync --locked --dev` → `uv run ruff check .` → `uv run ruff format --check .` → `uv run pytest`), build the wheels, create the **annotated tag locally** (`git tag -a v0.1.0 -m "..."`). **Human-gated:** `git push origin && git push origin v0.1.0`, then observe the GitHub Actions run go green. Mark the latter as a `checkpoint:human` in the plan. `[VERIFIED: no gh, no creds; local CI-equivalent all green this session]`

## Code Examples

Verified patterns from this session (all run on this exact repo).

### The full local CI-equivalent gate (what proves SC3's autonomous half)
```bash
# Source: VERIFIED this session — all four green
cd /home/the2xman/Desktop/rosbagger
export PYTHONPATH=""
uv sync --locked --dev          # Resolved 41 packages; EXIT 0
uv run ruff check .             # "All checks passed!"; EXIT 0
uv run ruff format --check .    # "49 files already formatted"; EXIT 0
uv run pytest                   # 255 passed, 97.82% coverage (gate 80%); EXIT 0
```

### Build both release artifacts (workspace-native)
```bash
# Source: VERIFIED — produced valid sdist+wheel for both
uv build --package rosbagger-core --out-dir dist/
uv build --package bagq          --out-dir dist/
# bagq wheel contains only bagq/* + entry_points.txt ([console_scripts] bagq = bagq.cli:app); tools/ absent
# rosbagger-core wheel contains the 21 rosbagger_core/* modules; no entry point (library); tools/ absent
```

### hatchling dynamic version (OPTIONAL single-source — Open Q2)
```toml
# Source: CITED hatch.pypa.io/1.9/version — only adopt if you want one version source
[project]
name = "bagq"
dynamic = ["version"]            # remove the static `version = "..."` line
# requires-python, dependencies, scripts unchanged

[tool.hatch.version]
path = "src/bagq/__init__.py"    # default pattern matches __version__ = "x.y.z"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Annotated tag (local; push is human-gated)
```bash
# Autonomous:
git tag -a v0.1.0 -m "rosbagger v0.1.0 — bagq SQL-over-bags CLI (offline ROS1/ROS2/MCAP)"
git tag                          # v0.1.0 listed locally
# Human-gated (BLOCKED on auth):
# git push origin <branch> && git push origin v0.1.0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` + `MANIFEST.in` for src-layout | `pyproject.toml` + hatchling auto src-layout detection | PEP 517/518/621 era | No `setup.py`, no MANIFEST needed; hatchling already in use here |
| Hand-pinned `requirements.txt` for reproducibility | `uv.lock` + `uv sync --locked` | uv maturity (2024+) | Already adopted; the lock is the source of truth |
| Editable installs via `pip install -e` only | uv workspace editable + plain-pip multi-package install for release | uv workspaces (2024+) | Dev uses uv; release uses the verified multi-package pip recipe |

**Deprecated/outdated:**
- `pip install bagq` from PyPI: not applicable — unpublished; v0.1 is local-install only.
- A `setup.py` shim: unnecessary; hatchling + PEP 621 metadata is the standard.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MIT is the appropriate LICENSE (vs Apache-2.0/BSD or none) | Open Q1 | Low — license choice is reversible pre-publish; any permissive license satisfies "clean." User should confirm. |
| A2 | A LICENSE file is *desired* (not strictly required by the DoD) for v0.1 | Open Q1 | Low — DoD lists pip-install/offline-import/CI, not LICENSE. Adding one is hygiene, not a gate. |
| A3 | The discuss-phase / planner will confirm the soft additional_context guidance (no CONTEXT.md exists) | User Constraints | Low — guidance aligns with the roadmap's single 08-01 plan; verified-recipe parts are factual, not preference. |
| A4 | A CHANGELOG is optional for v0.1 | Standard Stack | Low — additional_context calls it optional; not a DoD item. |
| A5 | Adding `description`/`readme`/`license` to the pyprojects is a "clean" nicety, not a v0.1 requirement | Open Q3 | Low — local install works without them (verified); they matter for future PyPI publish (out of scope). |

**Note:** All factual packaging claims (the install recipe, version locations, lock pinning, wheel contents, suite/lint status, tools exclusion, plot extra) are `[VERIFIED]` — not assumed.

## Open Questions (RESOLVED)

*Resolved into 08-01: Q1 → add an MIT LICENSE at the repo root (v0.1 locked choice); Q2 → bump the version in all 4 sites + `uv lock` (no hatchling dynamic version for v0.1); Q3 → defer enriching pyproject metadata (description/readme/license) to a later polish.*

1. **LICENSE — which, and is it in scope?**
   - What we know: No LICENSE file exists anywhere in the repo (verified). The repo has a public `origin`. The DoD does not list a LICENSE.
   - What's unclear: Whether the user wants a LICENSE for v0.1 and which one.
   - Recommendation: Add **MIT** at the repo root (shortest, most common for CLI tooling; matches the "open, universal tool" framing). Cheap, reversible, and the right hygiene for a tagged release. Confirm in discuss/plan. `[ASSUMED]`

2. **Single-source version vs. duplicated bump?**
   - What we know: Version is duplicated in `pyproject.toml` + `__init__.py` per package; `uv.lock` also pins it. `bagq --version` reads `__init__.__version__`. hatchling supports `dynamic=["version"]` reading `__version__` from one file `[CITED]`.
   - What's unclear: Whether to single-source now or just bump 4 lines.
   - Recommendation: For a single 0.0.0→0.1.0 bump, **edit the 4 lines + re-lock** (lowest risk, no new config). If the user expects frequent releases, adopt hatchling dynamic version (set `dynamic=["version"]`, drop the static `version`, add `[tool.hatch.version] path`). Either is fine; flag for the planner to pick one and add the assertion `bagq --version == 0.1.0`.

3. **Enrich pyproject metadata (description/readme/license/authors)?**
   - What we know: Both pyprojects carry only `name`/`version`/`requires-python`/`dependencies` (+ scripts/extras for bagq). Local install works without more (verified).
   - What's unclear: Whether to add `description`, `readme = "README.md"`, `license`, `authors` now.
   - Recommendation: Optional for v0.1 (not a gate). Adding `description` + `readme` is a small, clean improvement and a prerequisite for any future publish (explicitly out of scope). Defer unless the user wants polish.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10 | build/install/test | ✓ | 3.10.12 | — |
| pip | the DoD pip-install path | ✓ | 22.0.2 | — |
| `python -m venv` | clean-room verification | ✓ | stdlib | — |
| uv | sync/lock/build, CI driver | ✓ | 0.11.14 | `python -m build` for build; pip for install |
| `python -m build` | release artifact build | ✓ (via `uvx --from build`) | works | `uv build` (preferred) |
| git | annotated tag, commit | ✓ | repo present; `origin` set | — |
| `gh` CLI | push, observe CI | ✗ | — | **No fallback — human-gated** (standing blocker) |
| GitHub push credential | push branch + tag, trigger CI | ✗ | — | **No fallback — human-gated** |
| matplotlib (`bagq[plot]`) | optional extra verification | ✓ (resolves on install) | 3.10.9 | extra is optional; base install is lean |

**Missing dependencies with no fallback (block part of SC3 — human-gated):**
- `gh` CLI and a push credential. Pushing the branch + `v0.1.0` tag and observing the GitHub Actions run go green CANNOT be done autonomously. The plan must mark the push + CI-observation as `checkpoint:human`.

**Missing dependencies with fallback:**
- `python -m build` is not installed standalone, but `uv build` (preferred, available) and `uvx --from build pyproject-build` both work — verified.

## Security Domain

`security_enforcement` is not set in `.planning/config.json` (absent = enabled by default), but this is a packaging/docs/release phase with **no authentication, session, access-control, network, or cryptography surface**. No new code paths process untrusted input. The existing CI hardening (from Phase 1) is already correct and should be left intact.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a (no auth in offline CLI) |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | no (no new input surface in P8) | (existing: SQL identifier quoting via sqlglot, P3; SQL-literal escape in COPY, P6) |
| V6 Cryptography | no | n/a (no secrets; CI declares none) |
| V14 Configuration / Supply chain | yes (release hygiene) | Pinned CI action versions (`checkout@v4`, `setup-uv@v8`); `uv sync --locked` for tamper-evident installs; least-privilege `permissions: contents: read` — all already in `.github/workflows/ci.yml` (verified). Keep them. |

### Known Threat Patterns for a packaging/release phase
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dependency-confusion (a public `rosbagger-core` shadowing the local one) | Tampering/Spoofing | v0.1 installs from LOCAL paths only (no PyPI fetch of first-party names); the multi-package pip recipe satisfies the dep from the local wheel. If ever published, claim the names on PyPI. |
| Supply-chain drift in CI install | Tampering | `uv sync --locked` from the committed `uv.lock` (already in CI). Re-lock deliberately on the version bump and commit it. |
| Over-privileged CI token | Elevation of Privilege | `permissions: contents: read` already set; no secrets referenced (verified). No change needed for P8. |
| Packaging unintended files (leaking `tools/`, tests, secrets into the wheel) | Information Disclosure | src-layout already scopes wheels to `src/`; verified both wheels contain only their package + metadata, no `tools/`. |

## Sources

### Primary (HIGH confidence)
- **Empirical verification on this repo** (Python 3.10.12 / pip 22.0.2 / uv 0.11.14) — the install recipe (both packages succeed; bagq-alone fails), `bagq --help`/subcommand-help/`--version`, offline import with no rclpy, `tools/` absent from both wheels, `bagq[plot]` resolves matplotlib, `uv build`/`python -m build` produce valid sdist+wheel, `uv sync --locked`/`ruff check`/`ruff format --check`/`pytest` (255 passed, 97.82%), `uv.lock` pins `version=0.0.0`. `[VERIFIED]`
- **uv docs — Managing dependencies / Workspaces** (docs.astral.sh/uv) — "sources are only respected by uv. If another tool is used, only the definitions in the standard project tables will be used." `[CITED]`
- **Hatch docs — Versioning** (hatch.pypa.io/1.9/version) — dynamic version via `[tool.hatch.version] path=...`, default pattern matches `__version__`/`VERSION`. `[CITED]`

### Secondary (MEDIUM confidence)
- WebSearch results corroborating uv `tool.uv.sources` being uv-only and hatchling single-source versioning (multiple sources agree; cross-checked against the official docs above).

### Tertiary (LOW confidence)
- None relied upon.

## Metadata

**Confidence breakdown:**
- Standard stack / toolchain: HIGH — everything verified by running it on this repo.
- The pip-install crux + recipe: HIGH — both the failure and the fix were reproduced empirically and corroborated by official uv docs.
- Versioning / lockfile pitfall: HIGH — `uv.lock` pinning verified by grep; CLI version source verified by reading `cli.py`/`__init__.py`.
- SC3 split (autonomous vs human-gated): HIGH — `gh` absence and local-CI-green both verified; push remains blocked per STATE.md.
- LICENSE/CHANGELOG/metadata recommendations: MEDIUM — factual gaps verified (none exist), but the *choice* is the user's (flagged as assumptions/open questions).

**Research date:** 2026-05-22
**Valid until:** ~2026-06-21 (stable domain; the only moving parts are uv/hatchling minor releases, which would not change the verified recipe).
