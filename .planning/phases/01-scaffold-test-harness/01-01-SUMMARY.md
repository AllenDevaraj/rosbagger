---
phase: 01-scaffold-test-harness
plan: 01
subsystem: infra
tags: [uv-workspace, hatchling, monorepo, packaging, typer, src-layout, python]

# Dependency graph
requires: []
provides:
  - "uv workspace (virtual root) with two editable-installable packages: rosbagger-core and bagq"
  - "rosbagger-core: pure-Python offline library skeleton with reserved reader/schema/backend seam packages"
  - "bagq: CLI package depending on rosbagger-core, exposing the `bagq` console-script (bagq.cli:app)"
  - "Verified, pinned offline dependency set (rosbags/duckdb/sqlglot/pyarrow + typer/rich) introduced with no ROS leakage in metadata"
  - ".venv with both packages editable-installed and dev tooling (ruff, pytest, pytest-cov, rosbags)"
affects: [02-test-harness-ci, 03-reader, 05-query-backend, 07-cli]

# Tech tracking
tech-stack:
  added:
    - "uv workspace (root pyproject.toml, [tool.uv.workspace])"
    - "hatchling build backend (per package)"
    - "rosbags>=0.11,<0.12, duckdb>=1.4,<2, sqlglot>=27,<31, pyarrow>=18 (rosbagger-core deps)"
    - "typer>=0.15,<1, rich>=13 (bagq deps); matplotlib>=3.8 (plot extra)"
    - "ruff, pytest, pytest-cov (dev dependency-group)"
  patterns:
    - "Virtual workspace root (no [project] table) wiring intra-workspace dep via [tool.uv.sources] workspace=true"
    - "src/ layout for both packages (import resolves from installed editable distribution, not the bare source tree)"
    - "Hyphenated distribution name (rosbagger-core) vs underscore import name (rosbagger_core)"
    - "Light package __init__ (no heavy top-level imports); heavy stack deferred into functions"
    - "Empty seam packages reserve future-phase layout (reader/schema/backend)"

key-files:
  created:
    - "pyproject.toml (virtual workspace root)"
    - "packages/rosbagger-core/pyproject.toml"
    - "packages/bagq/pyproject.toml"
    - "packages/rosbagger-core/src/rosbagger_core/__init__.py"
    - "packages/rosbagger-core/src/rosbagger_core/{reader,schema,backend}/__init__.py"
    - "packages/bagq/src/bagq/__init__.py"
    - "packages/bagq/src/bagq/cli.py"
    - ".python-version, .gitignore, README.md"
  modified: []

key-decisions:
  - "Workspace root kept virtual (no [project] table) to avoid uv building the root and complicating uv add"
  - "rich is the single table-output dependency (ships transitively via typer); tabulate dropped"
  - "Dev interpreter pinned to 3.10 (the floor) via .python-version so local dev exercises the minimum supported version"
  - "uv.lock commit deferred to plan 01-02 (file-ownership split); 01-01 owns only the manifests + sources"
  - "bagq ships a minimal runnable typer app (--help/--version) now (O-1 resolved); real subcommands land in Phase 7"

patterns-established:
  - "uv workspace + per-package hatchling backends for an independently-installable monorepo"
  - "src/ layout to make 'imports as an installed package' actually testable (Pitfall 5)"
  - "Offline-only package metadata: neither package declares a ROS or tabulate dependency"

requirements-completed:
  - "SC1: rosbagger-core and bagq import as installed packages"
  - "DoD: bagq installs via pip and exposes a console-script entry point"

# Metrics
duration: 3min
completed: 2026-05-22
---

# Phase 1 Plan 01: Workspace Scaffold Summary

**uv workspace with two editable-installable packages — `rosbagger-core` (offline library, reserved reader/schema/backend seams) and `bagq` (CLI, depends on core, runnable `bagq --help`/`--version`) — on hatchling + src layout, with the pinned offline dependency set and zero ROS in package metadata.**

## Performance

- **Duration:** ~3 min (execution session)
- **Started:** 2026-05-22T06:18:24Z
- **Completed:** 2026-05-22T06:21:24Z
- **Tasks:** 3 (Task 1 supply-chain gate approved in prior dispatch; Tasks 2–3 executed here)
- **Files modified:** 12 created across two task commits

## Accomplishments

- Stood up a virtual uv workspace root wiring `rosbagger-core` as a workspace source and a `dev` dependency-group (ruff, pytest, pytest-cov, rosbags).
- Created both package manifests with the verified, upper-bounded version pins from 01-RESEARCH.md; `rosbagger-core` carries exactly the four offline deps (rosbags/duckdb/sqlglot/pyarrow) and declares no ROS dependency.
- Built the `src/` layout: a light `rosbagger_core` package, three empty seam sub-packages (`reader`/`schema`/`backend`) reserving Phase 2/3/5 layout, and a minimal `bagq` typer app bound to `app`.
- `uv sync` editable-installed both packages with the exact dependency versions documented in research (rosbags 0.11.2, duckdb 1.5.3, sqlglot 30.8.0, pyarrow 24.0.0, typer 0.25.1, rich 15.0.0); the `rosbags` transitive tree (apsw, lz4, numpy, ruamel-yaml, zstandard) is ROS-free as audited.
- `bagq --help` and `bagq --version` run from the console-script and exit 0; `ruff check` and `ruff format --check` pass clean on the new sources.

## Task Commits

Each task was committed atomically:

1. **Task 2: Create the uv workspace root and both package pyproject.toml files** — `f002fc4` (feat)
2. **Task 3: Create src-layout source, seam packages, and the bagq typer app; sync and prove imports** — `4063d80` (feat)

_Task 1 was a `checkpoint:human-verify` supply-chain gate (no files); it was approved in the prior dispatch ("approved") and authorized the first `uv sync`._

**Plan metadata:** committed separately (this SUMMARY + STATE.md + ROADMAP.md).

## Files Created/Modified

- `pyproject.toml` — Virtual workspace root: `[tool.uv.workspace] members=["packages/*"]`, `[tool.uv.sources] rosbagger-core={workspace=true}`, `[dependency-groups] dev`. No `[project]` table.
- `packages/rosbagger-core/pyproject.toml` — `rosbagger-core` 0.0.0, hatchling, offline deps only (no ROS, no tabulate).
- `packages/bagq/pyproject.toml` — `bagq` 0.0.0, hatchling, depends on `rosbagger-core`; `[project.scripts] bagq="bagq.cli:app"`; `plot` extra.
- `packages/rosbagger-core/src/rosbagger_core/__init__.py` — `__version__="0.0.0"`; light (no heavy top-level imports).
- `packages/rosbagger-core/src/rosbagger_core/reader/__init__.py` — empty seam (Phase 2 BagReader).
- `packages/rosbagger-core/src/rosbagger_core/schema/__init__.py` — empty seam (Phase 3 schema mapping).
- `packages/rosbagger-core/src/rosbagger_core/backend/__init__.py` — empty seam (Phase 5 QueryBackend).
- `packages/bagq/src/bagq/__init__.py` — `__version__="0.0.0"`.
- `packages/bagq/src/bagq/cli.py` — minimal typer app `app`; `--help` (no_args_is_help) and `--version` callback. Imports only typer + bagq version.
- `.python-version` — pins dev interpreter to `3.10` (the floor).
- `.gitignore` — venv/cache/build artifacts; ignores generated `fixtures/`/`out/` bags.
- `README.md` — project blurb + two-package layout + `uv sync` / `uv run bagq --help` / `uv run pytest` quickstart + plain-pip fallback.

## Decisions Made

- **Workspace root left virtual** (no `[project]` table) per the locked anti-pattern guidance — keeps `uv add` simple and stops uv from trying to build the root as a package.
- **`uv.lock` not committed in this plan.** `uv sync` generated it, but plan 01-02 explicitly owns the lockfile (it commits `uv.lock` and wires `uv sync --locked` in CI). Left untracked (not gitignored) so 01-02 can commit it. This keeps file ownership clean across the two plans.
- **`rich` over `tabulate`** for table output — rich ships transitively with typer, so tabulate was dropped from the dependency set entirely.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 3 verification command produced a false negative against hatchling's standard editable install**
- **Found during:** Task 3 (uv sync + prove imports)
- **Issue:** The plan's automated verify asserted `'site-packages' in rosbagger_core.__file__ or '.venv' in rosbagger_core.__file__`. hatchling's default PEP 660 editable install uses a `.pth` file that appends `packages/rosbagger-core/src` to `sys.path` (rather than a redirecting import hook), so `rosbagger_core.__file__` legitimately resolves to the `src/` tree. The literal `__file__` substring check therefore fails even though the package is correctly installed — a false negative, not a real packaging defect.
- **Fix:** Verified SC1's true intent (Pitfall 5: "imports resolve from the installed distribution, not from the source tree being on `sys.path[0]` by running pytest at the repo root") with a stronger, environment-independent proof instead of the substring check:
  1. `importlib.metadata` reports both as installed distributions with `dist-info` present under `.venv/.../site-packages/` (genuine PEP 660 editable installs).
  2. Run from `/tmp` (cwd NOT the repo root), both packages still import and `sys.path[0]` is `''` (no repo path) — proving resolution is via the *installed* editable `.pth` entry, not an accidental source-tree-on-`sys.path[0]`.
  3. `bagq --help` and `bagq --version` exit 0 from the console-script.
- **Files modified:** None (verification-only; the source/manifests are correct as written).
- **Verification:** Both `dist-info` dirs present; import from `/tmp` succeeds with repo absent from `sys.path[0]`; `bagq --help`/`--version` exit 0; `ruff check`/`format --check` clean.
- **Committed in:** No code change required — finding documented here. (The actual editable `.pth` wiring lives in `4063d80`'s `uv sync` output.)

**2. [Rule 1 - Bug] Reworded a comment in `rosbagger-core/pyproject.toml` to satisfy the literal "no forbidden token" acceptance grep**
- **Found during:** Task 2 (manifest creation)
- **Issue:** My initial explanatory comment named the forbidden tokens (`rclpy`, `rosbag2_py`, `tabulate`) to document the offline invariant. The acceptance criterion is a literal token scan of the file (`contains NO rclpy, rosbag2_py, or tabulate token`), which matched the prose comment and produced a false positive.
- **Fix:** Reworded the comment to express the same intent ("MUST NOT declare any ROS dependency... the single table-output dependency is rich") without using the literal forbidden token strings. The `dependencies` array never contained any of them.
- **Files modified:** `packages/rosbagger-core/pyproject.toml` (comment only).
- **Verification:** `grep -Eq 'rclpy|rosbag2_py|tabulate'` on the file now returns clean; the four-dep `dependencies` array is unchanged.
- **Committed in:** `f002fc4` (Task 2 commit).

---

**Total deviations:** 2 auto-fixed (2 bug-class). Deviation 1 is a verification-tooling correction (no source change); deviation 2 is a one-line comment reword.
**Impact on plan:** No scope change, no design change. Both deviations reconcile literal verification strings with the correct, standard behavior they were meant to assert. SC1 and the DoD console-script item are fully satisfied.

## Issues Encountered

- The dev host has ROS 2 Humble on `PYTHONPATH` (a known trap from 01-RESEARCH.md). All `uv`/Python invocations in this plan ran with `PYTHONPATH=""` so the offline boundary was not silently crossed; uv's isolated venv reinforces this. The active offline-import guard test lands in plan 01-02.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Workspace, both packages, and the editable `.venv` are in place; SC1 ("both import as installed packages") and the DoD console-script item are satisfied.
- **Handoff to plan 01-02:** `uv sync` produced `uv.lock` (currently untracked by design) — 01-02 owns committing it and adding `[tool.ruff]` / `[tool.pytest.ini_options]` config + the no-ROS CI workflow + the offline-import guard test.
- Seam packages `reader/`, `schema/`, `backend/` are reserved so Phases 2/3/5 plug in without restructuring.
- No blockers.

## Self-Check: PASSED

- Files: all 13 claimed artifacts verified present on disk (3 pyproject.toml, 6 src `__init__`/`cli.py`, `.python-version`, `.gitignore`, `README.md`, this SUMMARY).
- Commits: `f002fc4` (Task 2) and `4063d80` (Task 3) verified in git history.
- Runtime: `uv run bagq --help` / `--version` exit 0; both packages import as installed editable distributions from a non-repo cwd; `ruff check`/`format --check` clean.

---
*Phase: 01-scaffold-test-harness*
*Completed: 2026-05-22*
