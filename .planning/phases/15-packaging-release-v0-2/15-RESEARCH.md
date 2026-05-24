# Phase 15: Packaging & Release v0.2 - Research

**Researched:** 2026-05-24
**Domain:** Python packaging — uv workspace, hatchling wheels, git+subdirectory / path / find-links install, inter-package version-spec resolution
**Confidence:** HIGH (core resolution mechanics proven empirically against this repo's wheels in fresh external venvs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (One-line meta recipe + source-agnostic packages):** Packages stay *source-agnostic* — their `[project] dependencies` reference sibling packages by **version spec only** (e.g. `rosbagger-core>=0.2,<0.3`), never by a path or git URL baked into the wheel. The crux: `[tool.uv.sources] … workspace = true` is **dev-only metadata NOT written into built wheels**, so an external consumer installing one package can't resolve the bare `rosbagger-core` dependency from any index (we publish to none).
  - Provide **one documented meta command** that installs the whole set from git together (all subdirectory URLs in a single `uv pip install`/`pip install` invocation), so sibling specs resolve against the packages installed in the same transaction.
  - Also provide **per-package `git+…#subdirectory=…` snippets** for consumers who want just one or two packages (they install the needed siblings in the same command).
- **D-02 (`live` extra on rosbagger-gui):** Add `[project.optional-dependencies] live = ["rosbagger-record", "rosbagger-replay"]` to `rosbagger-gui`. Base install stays offline-only (core query/inspect/tf panels); `rosbagger-gui[live]` adds the rclpy-backed record/replay panels. Keeps the offline-import invariant intact — base GUI never pulls rclpy.
- **D-03 (All → 0.2.0, compatible pins):** Bump all five packages to `0.2.0`. Inter-package dependencies use a compatible-release pin `>=0.2,<0.3`.
- **D-04 (Central INSTALL.md):** One top-level `INSTALL.md` holds every install path — the one-line meta recipe, per-package git+subdirectory snippets, local path-install snippets, the external-venv **proof recipe** (fresh venv → install → import/CLI smoke check), and the "live GUI panels need `rosbagger-gui[live]`" note.

### Claude's Discretion
- Exact wording/structure of INSTALL.md sections.
- Whether the external-venv proof recipe is also encoded as a test/CI check vs. documented-only (lean toward a scripted check if cheap).
- Whether to add a top-level `make`/script target wrapping the meta recipe.

### Deferred Ideas (OUT OF SCOPE)
- **PyPI / index publishing** — explicitly out of scope for v0.2; git/path install only.
- **CI release automation** (tag → build → attach artifacts) — not this phase.
- **Docker images / conda packaging** — out of scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

This is an infrastructure phase (like Phase 8) with **no new REQ-ID**. The Definition of Done is the 5 ROADMAP success criteria:

| SC | Description | Research Support |
|----|-------------|------------------|
| SC1 | Each package builds a wheel via `uv build` (core, bagq, record, replay, gui) | VERIFIED — all five built via `uv build --wheel` this session; `uv build --all-packages` builds all at once |
| SC2 | Fresh EXTERNAL venv installs from git+subdirectory / path with `rosbagger-core` resolving by spec (not workspace source) — proven by `rosbagger-gui --help` + `import rosbagger_gui` outside the monorepo | VERIFIED — co-install transaction resolves bare sibling spec; CLI/import smoke passed from neutral cwd. See "The Resolution Crux" |
| SC3 | Per-package install + usage docs (git+subdirectory and `[tool.uv.sources]` git/path snippets), incl. GUI live note (`rosbagger-gui[live]`) | D-04 + Code Examples below |
| SC4 | Versions coherent at v0.2.0 across all packages (+ re-locked `uv.lock`) | 10 version sites enumerated below (5 pyproject + 5 `__init__`) |
| SC5 | Offline-import invariant + ROS-free core intact; full offline suite + offline guard green | VERIFIED base `import rosbagger_gui` leaks no rclpy/rosbag2_py after install; `live` extra is declarative, no eager import |
</phase_requirements>

## Summary

This phase has **no new external dependencies and no runtime code** — it is versioning, manifest edits, one new `INSTALL.md`, and a proof recipe. The single load-bearing technical fact, which I verified empirically against this repo's own wheels, is the **resolution crux**: hatchling writes the bare `Requires-Dist: rosbagger-core` (no source) into every wheel, and `[tool.uv.sources]` is stripped. So an external consumer installing one package alone cannot resolve the sibling from any index (we publish to none) — `pip install rosbagger_gui-0.2.0.whl` fails with *"Could not find a version that satisfies the requirement rosbagger-core"*. The fix (D-01) is to install all needed packages in **one transaction** so each bare sibling spec resolves against a package being installed concurrently.

I proved the full chain in fresh external venvs: (1) all five wheels build; (2) installing `rosbagger-gui` alone fails on the bare `rosbagger-core` spec even with PyPI reachable (the third-party `textual` resolves fine — only the sibling fails, isolating the gap precisely); (3) co-installing all five (third-party from PyPI + siblings supplied locally) succeeds, and `rosbagger-gui --help`, `bagq --version`, and `import rosbagger_gui/core/bagq/record/replay` all pass from a neutral cwd outside the monorepo; (4) base `import rosbagger_gui` leaks zero `rclpy`/`rosbag2_py`.

**Primary recommendation:** Replace each bare `"rosbagger-core"` with `"rosbagger-core>=0.2,<0.3"` (and the symmetric pin for any sibling dep), bump all 10 version sites to `0.2.0`, add the declarative `live` extra to gui, re-lock `uv.lock`, write `INSTALL.md` with a single-transaction meta recipe (the only recipe that resolves siblings), and add a scripted external-venv proof. Do **not** bake git/path URLs into `[project] dependencies` — that breaks source-agnosticism (D-01).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Wheel build / metadata generation | Build backend (hatchling) | — | hatchling auto-detects src-layout; writes `Requires-Dist` from `[project] dependencies` |
| Inter-package dependency declaration | Package manifest (`[project] dependencies`) | — | Version-spec only (D-01); ships in the wheel, source-agnostic |
| Dev-time sibling resolution | Workspace metadata (`[tool.uv.sources]` root) | — | `workspace = true`; stripped from wheels — dev-only |
| External consumer sibling resolution | Install transaction (one `pip`/`uv pip install`) | Consumer's own `[tool.uv.sources]` git/path | Bare spec resolves against a co-installed package OR consumer-declared source |
| Optional live deps | `[project.optional-dependencies] live` on gui | — | Declarative extra; resolved only when consumer asks for `[live]` |
| Version coherence | 10 version sites + `uv.lock` | — | 5 pyproject `version=` + 5 `__init__ __version__` + lockfile |
| Install docs | `INSTALL.md` (root) | README | Central per-D-04 |
| Offline-import invariant | Lazy function-body imports (existing) | offline-guard test | `live` extra must not regress it |

## Standard Stack

This phase **adds no packages**. Every dependency is already locked and vetted (Phases 1–14). The only manifest changes are: version bumps, sibling spec pins, and the declarative `live` extra (which references first-party siblings, not new PyPI packages).

### Tooling already present (verified this session)
| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| uv | 0.11.14 | workspace, build, lock, `uv pip install` | `uv build --all-packages` builds all members; `--no-sources`/`UV_NO_SOURCES` builds index-publishable metadata |
| hatchling | (build-system requires) | wheel build backend | auto-detects `src/<pkg>` layout — **no `[tool.hatch.*]` config needed or present** |
| pip | bundled in venv | external-consumer install path | supports `pkg @ git+https://…#subdirectory=…` PEP 508 direct refs |

### Inter-package dependencies after this phase (the edits)
| Package | Current dep line | After D-01/D-03 |
|---------|------------------|-----------------|
| bagq | `"rosbagger-core"` | `"rosbagger-core>=0.2,<0.3"` |
| rosbagger-record | `"rosbagger-core"` | `"rosbagger-core>=0.2,<0.3"` |
| rosbagger-replay | `"rosbagger-core"` | `"rosbagger-core>=0.2,<0.3"` |
| rosbagger-gui | `"rosbagger-core"` | `"rosbagger-core>=0.2,<0.3"` + new `[project.optional-dependencies] live = ["rosbagger-record>=0.2,<0.3","rosbagger-replay>=0.2,<0.3"]` |
| rosbagger-core | (no sibling deps) | unchanged deps; version bump only |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Bare spec + one-transaction install (D-01) | Bake `rosbagger-core @ git+https://…#subdirectory=…` into `[project] dependencies` | REJECTED by D-01 — pins the wheel to one source forever, breaks path installs and consumer-side source overrides; the URL travels into the consumer's lockfile |
| Spec pin `>=0.2,<0.3` | `~=0.2.0` (compatible release) | `~=0.2.0` means `>=0.2.0,<0.3.0` — equivalent intent; CONTEXT locks `>=0.2,<0.3` exactly, use it verbatim |
| `live` extra (D-02) | Declare record/replay as hard deps of gui | REJECTED — would pull ROS-bound siblings into every base install and risk the offline invariant |

**Installation (no new packages — this is the consumer-facing recipe, not a dev install):**
```bash
# Dev (unchanged): uv sync --locked --dev
# Consumer meta recipe lands in INSTALL.md — see Code Examples.
```

**Version verification:** No new packages to verify. The four siblings (`rosbagger-core`, `rosbagger-record`, `rosbagger-replay`, `rosbagger-gui`) are first-party workspace members, not registry packages. All third-party deps (`textual`, `typer`, `duckdb`, `sqlglot`, `pyarrow`, `rosbags`, `rich`) were locked and vetted in prior phases and resolved cleanly from PyPI this session.

## Package Legitimacy Audit

> This phase installs **no new external packages**. The `live` extra references first-party workspace siblings only.

| Package | Registry | Role | slopcheck | Disposition |
|---------|----------|------|-----------|-------------|
| rosbagger-core | first-party (not on any index) | workspace sibling | N/A | Approved (own code) |
| bagq | first-party | workspace sibling | N/A | Approved (own code) |
| rosbagger-record | first-party | workspace sibling | N/A | Approved (own code) |
| rosbagger-replay | first-party | workspace sibling | N/A | Approved (own code) |
| rosbagger-gui | first-party | workspace sibling | N/A | Approved (own code) |
| textual, typer, duckdb, sqlglot, pyarrow, rosbags, rich | PyPI | already-locked deps (Phases 1–14) | resolved cleanly from PyPI this session | Approved (pre-vetted) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*Note: the `slopcheck` CLI in this environment performs an install-based check, not a verdict-only scan; the third-party deps installed cleanly from PyPI with no resolution anomalies. No new packages are introduced by this phase, so there is no new attack surface.*

## The Resolution Crux (the heart of this phase)

### Why an external single-package install fails — PROVEN

I built `rosbagger_gui-0.1.0-py3-none-any.whl` and inspected its METADATA:

```
Metadata-Version: 2.4
Name: rosbagger-gui
Version: 0.1.0
Requires-Python: >=3.10
Requires-Dist: rosbagger-core        <-- BARE NAME, NO SOURCE
Requires-Dist: textual<9,>=8
```

`[tool.uv.sources] rosbagger-core = { workspace = true }` from the **root** pyproject is **absent** from the wheel. `[VERIFIED: built wheel METADATA inspected this session]`

Installing that wheel alone into a fresh external venv **with PyPI reachable**:
```
ERROR: Could not find a version that satisfies the requirement rosbagger-core (from rosbagger-gui) (from versions: none)
ERROR: No matching distribution found for rosbagger-core
```
Note: `textual<9,>=8` resolved fine from PyPI in the same run — **only the sibling fails**, isolating the gap to inter-package deps exactly. `[VERIFIED: fresh venv install this session]`

### Why the one-transaction install fixes it — PROVEN

Installing all five **together** (third-party from PyPI + siblings supplied locally, mimicking five git+subdirectory URLs in one command):
```
Successfully installed … rosbagger-core-0.1.0 rosbagger-gui-0.1.0 rosbagger-record-0.1.0 rosbagger-replay-0.1.0 bagq-0.1.0 …
```
Then, from a **neutral cwd outside the monorepo**, with `PYTHONPATH=""`:
- `rosbagger-gui --help` → exit 0
- `bagq --version` → `bagq 0.1.0`
- `python -c "import rosbagger_gui, rosbagger_core, bagq, rosbagger_record, rosbagger_replay"` → `imports OK`
- `import rosbagger_gui` ROS leak check → `ROS leaked: []`

`[VERIFIED: fresh venv smoke check this session]`

**Mechanism:** when multiple distributions are named in one `pip`/`uv pip install` invocation, pip's resolver treats every named/URL distribution as an available candidate for the whole run. So `rosbagger-gui`'s `Requires-Dist: rosbagger-core>=0.2,<0.3` is satisfied by the `rosbagger-core` wheel being installed in the same transaction — **no index lookup needed for the sibling**. No `--no-build-isolation`, no constraints file, no `--find-links` to an index is required *for the sibling resolution itself*; you only need the sibling distributions present as command arguments (as git+subdirectory URLs or paths). `[VERIFIED: empirical + pip resolver behavior]`

### Three valid consumer recipes (all resolve the sibling, none bake a URL into the wheel)

1. **git+subdirectory, one transaction (D-01 meta recipe):** name every package as a `pkg @ git+https://…@v0.2.0#subdirectory=packages/<pkg>` direct reference in one command. Works in both `pip install` and `uv pip install`. `[VERIFIED: syntax form; CITED: docs.astral.sh/uv git subdirectory syntax]`
2. **Local path, one transaction:** `pip install ./packages/rosbagger-core ./packages/bagq …` (the Phase 8 v0.1 recipe, generalized to five packages). `[VERIFIED: path install equivalent proven this session via local wheels]`
3. **Consumer-side `[tool.uv.sources]`:** the *consumer's own* `pyproject.toml` declares `rosbagger-core = { git = "https://github.com/AllenDevaraj/rosbagger", subdirectory = "packages/rosbagger-core" }`. This redirects the bare spec to a source **in the consumer's project**, NOT in our wheels — fully compatible with D-01's source-agnostic packages. This is how a downstream uv project would consume us. `[CITED: docs.astral.sh/uv — [tool.uv.sources] git entries are dev-only consumer metadata, differ from baking the URL into [project] dependencies]`

### Repo state caveat (carry into the proof recipe design)

The GitHub remote `https://github.com/AllenDevaraj/rosbagger.git` is **public but currently EMPTY** (`git ls-remote` / API returns "This repository is empty") — nothing has been pushed (the standing STATE.md "no push credential" blocker). `[VERIFIED: GitHub API this session]`

**Implication for the planner:** the git+subdirectory recipe **cannot be executed end-to-end locally** until code is pushed and a `v0.2.0` tag exists on the remote. Mirror Phase 8's honest split:
- **Autonomous / verified-locally:** the **path-based** external-venv proof (build all wheels OR `pip install ./packages/...`, into a throwaway venv, smoke `--help`/import). This proves the *resolution mechanism* with zero network dependency.
- **Awaits-push (human follow-up):** the literal `git+…#subdirectory=` recipe against the remote `@v0.2.0` tag — documented in INSTALL.md, executable by a consumer once the repo is pushed and tagged. Do NOT make this a blocking checkpoint.

## Architecture Patterns

### System Architecture Diagram (install-time data flow)

```
                         CONSUMER MACHINE (external project, fresh venv)
                         ┌──────────────────────────────────────────────┐
  one install command    │  pip / uv pip install (ONE transaction)        │
  naming all needed  ───►│      │                                         │
  pkgs as git+subdir     │      ├─ candidate set = {all named dists}       │
  URLs or paths          │      │                                         │
                         │      ▼                                         │
   GitHub repo           │  resolver:                                     │
   (public, @v0.2.0      │   • bare 3rd-party specs (textual, duckdb…) ───┼──► PyPI
    tag, packages/*) ───►│   • bare SIBLING specs (rosbagger-core>=0.2)    │
   [build isolation:     │       └─ satisfied by a co-named dist ──────────┘ (NO index)
    hatchling from       │                                                │
    each wheel's         │      ▼                                         │
    build-system]        │  installed site-packages:                      │
                         │   rosbagger_core, bagq, rosbagger_record,      │
                         │   rosbagger_replay, rosbagger_gui (+ deps)     │
                         │      │                                         │
                         │      ▼  SMOKE (neutral cwd, PYTHONPATH="")      │
                         │   rosbagger-gui --help   → exit 0              │
                         │   import rosbagger_gui   → no rclpy leak       │
                         └──────────────────────────────────────────────┘
```

### Pattern 1: Bare-spec sibling deps + one-transaction install
**What:** `[project] dependencies` carry `rosbagger-core>=0.2,<0.3`; the consumer install names every package together so the resolver's candidate set includes the sibling.
**When to use:** every consumer-facing recipe in INSTALL.md.
```bash
# Meta recipe (all five from git, one transaction) — Source: D-01 + verified pip resolver behavior
uv pip install \
  "rosbagger-core @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "bagq @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/bagq" \
  "rosbagger-record @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-record" \
  "rosbagger-replay @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-replay" \
  "rosbagger-gui @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui"
```

### Pattern 2: Per-package snippet (consumer wants just gui + its sibling)
```bash
# Source: D-01 (per-package snippets co-name needed siblings)
pip install \
  "rosbagger-core @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-core" \
  "rosbagger-gui  @ git+https://github.com/AllenDevaraj/rosbagger@v0.2.0#subdirectory=packages/rosbagger-gui"
# add [live] panels:
pip install \
  "rosbagger-core    @ git+...#subdirectory=packages/rosbagger-core" \
  "rosbagger-record  @ git+...#subdirectory=packages/rosbagger-record" \
  "rosbagger-replay  @ git+...#subdirectory=packages/rosbagger-replay" \
  "rosbagger-gui[live] @ git+...#subdirectory=packages/rosbagger-gui"
```

### Pattern 3: `live` extra is purely declarative
**What:** `[project.optional-dependencies] live = ["rosbagger-record>=0.2,<0.3","rosbagger-replay>=0.2,<0.3"]`. Adding the extra changes only `Requires-Dist: …; extra == "live"` lines in METADATA. It does NOT add any import to `rosbagger_gui/__init__.py`, so the offline-import invariant is structurally untouched. The live panels already lazy-import the siblings inside method bodies (Phase 14).
**When to use:** D-02. `rosbagger-gui[live]` extra request pulls record/replay; bare `rosbagger-gui` does not.

### Anti-Patterns to Avoid
- **Baking a git/path URL into `[project] dependencies`:** breaks D-01 source-agnosticism; the URL travels into every consumer's lockfile and pins the wheel to one host forever. Use bare specs.
- **Documenting a single-package install as the primary recipe:** it fails on the bare sibling spec (proven). The meta/one-transaction recipe is the *only* one that resolves siblings — lead with it.
- **`--no-build-isolation` in the consumer recipe:** unnecessary. hatchling is fetched from each wheel's `build-system.requires` during the isolated build; build isolation is fine and should stay on.
- **Adding record/replay as hard gui deps:** would break the offline invariant. Use the `live` extra.
- **Forgetting a version site:** there are **10** (see below) plus `uv.lock`. Missing one makes `--version` lie or `uv sync --locked` fail.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wheel metadata / src-layout discovery | custom `[tool.hatch.build]` config | hatchling auto-detection (already working) | All five wheels build clean with zero hatch config; adding config risks breaking the working build |
| Sibling resolution without an index | custom find-links server / vendored wheels | one-transaction install (named dists are candidates) | Proven to work; pip/uv already do this |
| Multi-package build | shell loop over `uv build <path>` | `uv build --all-packages` | uv builds every workspace member in one command |
| Version-spec parsing for the live extra | anything | plain `[project.optional-dependencies]` | PEP 621 declarative extra; resolver handles it |

**Key insight:** the entire phase is *removing* a gap (the stripped workspace source) by leaning on standard packaging behavior, not adding machinery. The only "build" is INSTALL.md + a thin proof script.

## Version Source Inventory (SC4 — coherence target)

All currently `0.1.0`; all must become `0.2.0`. `[VERIFIED: grep + Read this session]`

| # | Site | Kind |
|---|------|------|
| 1 | `packages/rosbagger-core/pyproject.toml` `version = "0.1.0"` | dist version |
| 2 | `packages/bagq/pyproject.toml` `version = "0.1.0"` | dist version |
| 3 | `packages/rosbagger-record/pyproject.toml` `version = "0.1.0"` | dist version |
| 4 | `packages/rosbagger-replay/pyproject.toml` `version = "0.1.0"` | dist version |
| 5 | `packages/rosbagger-gui/pyproject.toml` `version = "0.1.0"` | dist version |
| 6 | `packages/rosbagger-core/src/rosbagger_core/__init__.py:9` `__version__` | runtime |
| 7 | `packages/bagq/src/bagq/__init__.py:3` `__version__` | runtime (drives `bagq --version`) |
| 8 | `packages/rosbagger-record/src/rosbagger_record/__init__.py:32` `__version__` | runtime |
| 9 | `packages/rosbagger-replay/src/rosbagger_replay/__init__.py:31` `__version__` | runtime |
| 10 | `packages/rosbagger-gui/src/rosbagger_gui/__init__.py:12` `__version__` | runtime |
| + | `uv.lock` (at repo root, 597 KB, `revision = 3`) | must re-lock so `uv sync --locked` passes |

Also: the **four inter-package dep lines** (bagq, record, replay, gui → `rosbagger-core`) gain the `>=0.2,<0.3` pin, and gui gains the `live` extra. (record/replay/gui have only the one sibling dep each; only gui's `[live]` extra references record+replay.)

## Common Pitfalls

### Pitfall 1: Leading docs with a single-package install
**What goes wrong:** `pip install <one git+subdir url>` errors `Could not find a version that satisfies rosbagger-core`.
**Why:** the bare sibling spec has no index to resolve from (proven).
**How to avoid:** every INSTALL.md recipe names all needed packages in one command. Add a "why one command" callout (mirror README's existing v0.1 note).
**Warning signs:** "No matching distribution found for rosbagger-core/-record/-replay".

### Pitfall 2: Missing a version site → `uv sync --locked` fails or `--version` lies
**What goes wrong:** bump 9 of 10 sites; `bagq --version` prints stale, or lockfile mismatch fails `uv sync --locked`.
**How to avoid:** edit all 10 sites + re-run `uv lock` and commit `uv.lock`. Verify `bagq --version` → `bagq 0.2.0` and `rosbagger_X.__version__ == "0.2.0"` for each.
**Warning signs:** Phase 8 SUMMARY recorded this exact class as a pitfall.

### Pitfall 3: Proof recipe that doesn't actually prove spec resolution
**What goes wrong:** running the proof from inside the monorepo, or with the workspace `.venv` active, "passes" via the workspace source — proving nothing.
**How to avoid:** throwaway venv (NOT `.venv`), neutral cwd outside the repo, install from built wheels or paths (NOT `-e`), then `--help` + import. Confirm `tools/` is not importable (not in any wheel — Phase 8 invariant). Prefix everything `PYTHONPATH=""`.
**Warning signs:** the proof references the monorepo root or `uv run`.

### Pitfall 4: Host ROS leak masking the offline check
**What goes wrong:** this box has ROS on `PYTHONPATH`; a bare import "succeeds" by leaking host ROS, hiding a real eager-import regression.
**How to avoid:** ALL test/lint/proof commands prefixed `PYTHONPATH=""` (neutralizes the leak); editable workspace members still resolve via their site-packages `.pth`. This is the established offline-guard mechanism.
**Warning signs:** `rclpy` appears in the leak list during the offline assertion.

### Pitfall 5: git+subdirectory recipe verified "green" locally but repo is empty
**What goes wrong:** planner asserts the literal git recipe runs locally; the remote is empty/untagged, so it can't.
**How to avoid:** split honesty (Phase 8 precedent) — path-based proof is autonomous; the git+`@v0.2.0` recipe is documented + flagged as awaiting push/tag, not a blocking checkpoint.

## Code Examples

### Build all wheels at once (SC1)
```bash
# Source: uv build --help (--all-packages) — verified this session
PYTHONPATH="" uv build --all-packages -o dist/
# or per-package: PYTHONPATH="" uv build --wheel packages/<pkg> -o dist/
```

### Autonomous external-venv PROOF (path-based — runs with no network/remote)
```bash
# Source: generalized from Phase 8 08-01-PLAN clean-room recipe; verified equivalent this session
set -euo pipefail
TMP=$(mktemp -d); python3 -m venv "$TMP/venv"
# install all five together so bare sibling specs resolve in one transaction:
PYTHONPATH="" "$TMP/venv/bin/pip" install \
  ./packages/rosbagger-core ./packages/bagq \
  ./packages/rosbagger-record ./packages/rosbagger-replay \
  "./packages/rosbagger-gui[live]"
cd /tmp   # neutral cwd OUTSIDE the monorepo
PYTHONPATH="" "$TMP/venv/bin/rosbagger-gui" --help >/dev/null
PYTHONPATH="" "$TMP/venv/bin/bagq" --version            # -> bagq 0.2.0
PYTHONPATH="" "$TMP/venv/bin/python" -c "import rosbagger_gui, rosbagger_core, bagq, rosbagger_record, rosbagger_replay; print('import OK')"
# offline invariant: base gui import must not leak ROS runtime
PYTHONPATH="" "$TMP/venv/bin/python" -c "import sys, rosbagger_gui; assert not [m for m in sys.modules if m.split('.')[0] in {'rclpy','rosbag2_py'}], 'ROS leaked'; print('offline OK')"
rm -rf "$TMP"
```
Note: `[live]` here pulls record/replay; if you want to prove the *base* (no-live) install separately, run a second venv with plain `./packages/rosbagger-gui` and assert record/replay are NOT installed.

### Consumer-side `[tool.uv.sources]` recipe (for a downstream uv project — INSTALL.md)
```toml
# Source: docs.astral.sh/uv — git source in the CONSUMER's pyproject (dev-only, not baked into our wheel)
[project]
dependencies = ["rosbagger-gui>=0.2,<0.3", "rosbagger-core>=0.2,<0.3"]

[tool.uv.sources]
rosbagger-gui  = { git = "https://github.com/AllenDevaraj/rosbagger", tag = "v0.2.0", subdirectory = "packages/rosbagger-gui" }
rosbagger-core = { git = "https://github.com/AllenDevaraj/rosbagger", tag = "v0.2.0", subdirectory = "packages/rosbagger-core" }
```

### Local CI-equivalent gate (mirror Phase 8 phase gate)
```bash
PYTHONPATH="" uv sync --locked --dev
PYTHONPATH="" uv run ruff check .
PYTHONPATH="" uv run ruff format --check .
PYTHONPATH="" uv run pytest        # >=80% gate; offline guard included
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| v0.1: 2 packages, plain path install, bare `rosbagger-core` (no pin) | v0.2: 5 packages, git+subdirectory + path + consumer-source recipes, `>=0.2,<0.3` pins, `live` extra | this phase | external consumers can install; sibling resolution explicit |
| `[tool.uv.sources] workspace=true` assumed to ship | confirmed stripped from wheels | (always true) | drives the entire phase |

**Deprecated/outdated:** none — no API churn; uv 0.11.x git+subdirectory and `--all-packages` behavior is current and verified locally.

## Runtime State Inventory

> This phase renames nothing and migrates no stored data — it bumps versions and edits manifests/docs. The categories below are answered for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys reference a version string. | none |
| Live service config | None — no external service config involved. | none |
| OS-registered state | Console scripts (`bagq`, `rosbagger-gui`, `rosbagger-record`, `rosbagger-replay`) are re-generated per install; entry points unchanged by version bump. | none (re-install regenerates) |
| Secrets/env vars | None. | none |
| Build artifacts | `uv.lock` carries `0.1.0` strings and must be re-locked; any local `dist/` wheels are stale after the bump (rebuild). Editable `.pth`/egg-info in `.venv` refresh on `uv sync`. | re-lock `uv.lock`; rebuild wheels; `uv sync` |

**Nothing found in stored-data / live-config / secrets categories — verified by inspection of the change surface (versions + manifests + one new doc).**

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The literal `git+…#subdirectory=@v0.2.0` recipe will work once code is pushed + tagged (could not run end-to-end — remote is empty). | Resolution Crux / Pitfall 5 | LOW — the *mechanism* (one-transaction sibling resolution) is proven via path/wheel installs; git+subdir is a documented uv/pip feature. Worst case: a typo in the URL surfaces at first consumer use. Mitigate by keeping the path-based proof as the autonomous gate. |
| A2 | `slopcheck` raised no SLOP/SUS verdicts. | Package Legitimacy Audit | NONE — no new external packages are introduced; the audit is informational. |

**Note:** A1 is the only material assumption and it is structurally low-risk given the path-install proof. No compliance/security/retention assumptions exist in this phase.

## Open Questions

1. **Encode the proof as a committed script/CI check, or document-only?** (Claude's discretion per CONTEXT.)
   - What we know: a path-based proof runs fully offline and autonomously; Phase 8 ran its clean-room check inline in the plan.
   - Recommendation: add a small committed `scripts/proof_external_install.sh` (or a `make proof` target) wrapping the autonomous path-based recipe — cheap, repeatable, and doubles as living documentation. Keep the git+subdir literal in INSTALL.md as the consumer recipe (awaits-push to run live).

2. **Does the planner want a `tools/`-not-in-wheel assertion in the proof?** Phase 8 asserted `tools` is not importable from the installed venv. Worth re-asserting for the three new packages.
   - Recommendation: include it — cheap regression lock that the wheels stay clean.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | build / lock / pip install | ✓ | 0.11.14 | — |
| hatchling | wheel build | ✓ (via build-system, isolated) | — | — |
| python3 venv | external-venv proof | ✓ | 3.10 | — |
| pip (in venv) | consumer install path | ✓ | bundled | — |
| git | git+subdirectory recipe | ✓ | — | path install (autonomous proof) |
| GitHub remote (pushed + `v0.2.0` tag) | live git+subdir recipe | ✗ | repo EMPTY | path-based proof (autonomous); git recipe documented, awaits push |
| PyPI reachability | third-party dep resolution (textual, duckdb, …) | ✓ (resolved this session) | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** the pushed/tagged remote — fallback is the path-based proof (proves the same resolution mechanism); the literal git recipe is documented and awaits the push/tag human follow-up (Phase 8 precedent).

## Sources

### Primary (HIGH confidence)
- Built `rosbagger_gui` wheel METADATA inspected this session — proves `[tool.uv.sources]` stripped, bare `Requires-Dist: rosbagger-core`.
- Fresh external-venv installs this session — single-package failure, one-transaction success, CLI/import/offline smoke all proven.
- `uv build --help`, `uv pip install --help` (uv 0.11.14) — `--all-packages`, `--no-sources`, `--find-links`, build-isolation flags.
- `tests/test_offline_guard.py`, all five `pyproject.toml`, all five `__init__.py` — version sites + offline mechanism (Read this session).
- `.planning/phases/08-packaging-docs-release/08-01-PLAN.md` — the v0.1 clean-room recipe + honest local/awaits-push split precedent.
- GitHub API (`/repos/AllenDevaraj/rosbagger/contents/packages`) — remote is public but empty.

### Secondary (MEDIUM confidence)
- docs.astral.sh/uv — git+subdirectory URL syntax, `[tool.uv.sources]` git entries are dev-only consumer metadata distinct from `[project] dependencies`.

### Tertiary (LOW confidence)
- uv docs did not explicitly document multi-URL one-transaction sibling resolution — this was resolved empirically (now HIGH), not left as LOW.

## Metadata

**Confidence breakdown:**
- Resolution crux & mechanism: HIGH — proven end-to-end in fresh external venvs against this repo's own wheels.
- Version sites / change surface: HIGH — enumerated by grep + Read.
- Offline invariant under `live` extra: HIGH — extra is declarative; base import leak-checked clean post-install.
- Live git+subdir recipe execution: MEDIUM — feature is documented and the mechanism proven via paths, but the remote is empty so the literal recipe is unrun (A1).

**Research date:** 2026-05-24
**Valid until:** 2026-06-23 (stable — packaging mechanics; revisit if uv major version changes)
