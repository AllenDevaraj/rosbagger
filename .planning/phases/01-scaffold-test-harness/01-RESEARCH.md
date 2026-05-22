# Phase 1: Scaffold & Test Harness - Research

**Researched:** 2026-05-21
**Domain:** Python monorepo packaging + `rosbags` fixture-bag generation + no-ROS test harness
**Confidence:** HIGH (every load-bearing claim verified by installing the real packages in an isolated venv and running the code; versions confirmed against PyPI)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Monorepo of independently-installable packages** (PRD §3.1). Phase 1 scaffolds exactly two: `rosbagger-core` and `bagq`.
- `rosbagger-core` is the pure-Python offline library; `bagq` is the CLI and **depends on `rosbagger-core`**.
- Layout must leave room for future sibling packages (`rosbagger-tf`, `-record`, `-replay`, `-gui`, `-edit`) without restructuring — but those are NOT created in Phase 1.
- **Offline invariant:** `rosbagger-core` and `bagq` **MUST NOT import ROS** (`rclpy`, `rosbag2_py`) — directly or transitively. The dev machine has ROS 2 Humble (`rosbag2_py` importable), so this boundary must be **actively guarded** by a test, not assumed.
- Live packages (`record`/`replay`) isolate `rclpy` behind their own boundary — out of scope for Phase 1.
- **Python ≥ 3.10** (PRD §4.3; CLAUDE.md).
- Each package owns its own `pyproject.toml`; both installable via `pip` (editable installs for local dev).
- **Offline dependency set** (PRD §4.3): `rosbags`, `duckdb`, `sqlglot`, `pyarrow`, `matplotlib` (plot path only), a CLI library, and `rich`/`tabulate` for table output. **No ROS dependency** in either package's metadata.
- `duckdb` is not yet installed locally — Phase 1's packaging work introduces the dependency set.
- DuckDB is the default query backend behind a **swappable `QueryBackend` seam** (PRD §3.3.6, §4.1). Layout should anticipate this seam; the actual backend lands in Phase 5.
- **Lint + format:** `ruff`. **Test runner:** `pytest`. **CI:** must run `pytest` green **with no ROS installed**. **Coverage target ≥ 80%**.
- **Fixture-bag generator** built on `rosbags`'s write capability, emitting tiny bags in **all three formats**: ROS 1 (`.bag`), ROS 2 sqlite3, ROS 2 MCAP. Fixtures are the shared substrate for every later phase.
- Fixture content must be **forward-looking**: rich enough to later exercise nested scalar flattening, array/`LIST` handling, and `header.stamp` extraction (Phases 2–3) — though Phase 1 only asserts bags are produced and re-openable.

### Claude's Discretion
- **Build backend** (hatchling / setuptools / pdm-backend / etc.) — not pinned by the PRD.
- **Monorepo wiring** (uv workspace vs. plain editable installs vs. a root dev install) — pick the simplest approach that satisfies "both packages import as installed packages".
- **CI provider config** — GitHub Actions is implied by convention; exact matrix/steps are open.
- **Test layout**, `ruff` rule selection, and the exact message types / topic names inside the fixture bags.
- **CLI library**: PRD §4.3 says "`typer` or `click`"; ROADMAP plan 07-01 leans **`typer`**. Whether Phase 1 wires a runnable `bagq --help` or just scaffolds an importable package with a placeholder entry point is open — confirm during planning.

### Deferred Ideas (OUT OF SCOPE)
- Reader (`BagReader` + `rosbags` `AnyReader` impl) — Phase 2.
- Message→table schema (sanitized names, dotted/quoted columns, `LIST`/`STRUCT`, time columns, lazy blobs) — Phase 3.
- Inspect (`bagq info` / `bagq tables`) — Phase 4.
- Query engine (`QueryBackend` + DuckDB, `sqlglot` topic resolution) — Phase 5.
- Output & export (stdout table, CSV, Parquet, `--plot`) — Phase 6.
- CLI wiring + teaching errors — Phase 7.
- Packaging polish, docs, v0.1 release — Phase 8.
- Post-v1 modules — `rosbagger-tf`, `-record`, `-replay`, `-gui`, `-edit`, events sidecar.
- Fast-follows — alias pack, projection pushdown, `rosbag2_py` reader backend.
</user_constraints>

<phase_requirements>
## Phase Requirements

Phase 1 is an **infrastructure phase**: it carries the **Definition of Done (v1)** rather than specific REQ-IDs. It builds the substrate that lets Phases 2–8 satisfy the READ/INSP/QURY/OUT/CLI requirements with no ROS install.

| DoD item (this phase enables) | Research Support |
|---|---|
| Test suite runs with **no ROS install** using `rosbags`-written fixture bags (ROS1 + ROS2 + MCAP) | Fixture generator API verified end-to-end (Code Examples §1–4); offline-guard test pattern verified to pass with ROS blocked (Code Examples §5) |
| `bagq` installs via `pip` and exposes commands | uv-workspace + hatchling editable install verified: both packages import, `bagq` console-script runs, depends on `rosbagger-core` (Code Examples §6) |
| Offline packages import without `rclpy` | `rosbags` 0.11.2 transitive dependency tree confirmed ROS-free (`apsw, lz4, numpy, ruamel.yaml, typing_extensions, zstandard`); guard test proves no ROS leaks into `sys.modules` |

**Forward-looking carry (shapes the scaffold for later phases):**
- READ-04 (Phase 2): fixtures must round-trip through `AnyReader` and yield `header.stamp`.
- QURY-02 (Phase 3): fixtures must contain nested scalars (`Twist.linear.x`).
- QURY-03 (Phase 3): fixtures must contain arrays (e.g. `Imu.orientation_covariance`, a 9-element float list).
- QURY-04 (Phase 3): fixtures must contain a message WITH `header.stamp` (Imu) and one WITHOUT (Twist) so `stamp`-is-`NULL` handling can be tested.
- QURY-07 (Phase 3): a fixture with a heavy byte blob (`sensor_msgs/msg/Image.data` or `PointCloud2.data`) so lazy-blob materialization can be tested.
</phase_requirements>

## Summary

Phase 1 is a packaging + test-harness phase with two genuinely tricky pieces and three boring-but-must-get-right ones. The two tricky pieces: (1) the **`rosbags` write API has drifted** — the current stable release (`0.11.2`, May 2026) makes `version=` a *required* keyword argument on the ROS2 `Writer` and selects sqlite3-vs-MCAP via a separate `StoragePlugin` enum, so the example in the published docs is stale and would raise `TypeError`; and (2) the **offline-import guard must work even though the dev machine has ROS on its `PYTHONPATH`** — a naive "try importing rclpy and expect failure" test passes for the wrong reason on a clean CI runner and fails to protect anything on the dev box. Both are solved below with verified, runnable code.

The three boring pieces — a two-package monorepo where `bagq` depends on `rosbagger-core`, a `ruff`+`pytest`+`pytest-cov` config, and a no-ROS GitHub Actions workflow — are all best served by a **uv workspace with hatchling build backends and a `src/` layout**. I built this exact structure, ran `uv sync`, and confirmed both packages import as installed editable packages, the `bagq` console-script runs and resolves its dependency on `rosbagger-core`, and `pytest --cov-fail-under=80` enforces the coverage gate.

**Primary recommendation:** Use a **uv workspace** (root `pyproject.toml` with `[tool.uv.workspace]` + `[tool.uv.sources] rosbagger-core = { workspace = true }`), two member packages under `packages/` each with a **hatchling** build backend and `src/` layout, dev tooling pinned in a root `[dependency-groups] dev = [...]`, all lint/test config centralized in the root `pyproject.toml`, and CI via `astral-sh/setup-uv` → `uv sync --locked` → `uv run pytest`. Pin `rosbags>=0.11,<0.12` and write fixtures with the current `Writer(path, version=9, storage_plugin=...)` API. Guard the offline boundary with a `sys.meta_path` blocker fixture so the test is real on both clean CI and the ROS-equipped dev machine.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Package metadata & dependency declaration | Packaging (pyproject per package) | uv workspace root | Each package is independently installable per PRD §3.1; root only wires the workspace |
| Build / editable install | Build backend (hatchling) | uv (sync/lock) | hatchling builds the wheel; uv orchestrates the multi-package editable env |
| Offline library code | `rosbagger-core` (pure Python) | — | The "offline world" tier; never imports ROS |
| CLI presentation | `bagq` | depends on `rosbagger-core` | CLI is a thin layer over the library (PRD §3.3 API-first) |
| Fixture-bag generation | Dev/test tooling (NOT shipped in either package's runtime path) | `rosbags` writer | Fixtures are a test artifact; the generator is a dev tool, not a product feature |
| Offline-boundary enforcement | Test suite (`pytest`) | `sys.meta_path` guard fixture | The invariant is a *test*, run in CI; it is not runtime code |
| Lint / format / coverage | Tooling config (root `pyproject.toml`) | ruff, pytest-cov | Centralized in the monorepo root; ruff supports hierarchical override if a package ever needs it |

## Standard Stack

All versions below were verified against PyPI on 2026-05-21 via `pip index versions` / `pip install <pkg>==`. "Latest" = newest non-dev/non-rc release available for Python 3.10.

### Core (offline runtime dependencies — go in package metadata)
| Library | Latest (verified) | Recommended pin | Purpose | Why standard |
|---|---|---|---|---|
| `rosbags` | 0.11.2 (2026-05-11) | `>=0.11,<0.12` | Pure-Python ROS1/ROS2/MCAP read **and write**; the fixture generator + future reader | The only no-ROS library that *writes* all three bag formats; PRD-mandated |
| `duckdb` | 1.5.3 | `>=1.4,<2` | Embedded SQL engine, native Parquet/CSV, `LIST`/`STRUCT` types | PRD-mandated default `QueryBackend`; declared now, used in Phase 5 |
| `sqlglot` | 30.8.0 | `>=27,<31` | SQL parsing → topic/table resolution | PRD-mandated; used in Phase 5 |
| `pyarrow` | 24.0.0 | `>=18` | Arrow tables between DuckDB and exporters | PRD-mandated; used in Phases 5–6 |
| `typer` | 0.25.1 | `>=0.15,<1` | CLI framework (`bagq`) | ROADMAP 07-01 leans typer; builds on click, gives typed commands + auto `--help` |
| `rich` | 15.0.0 | `>=13` | Pretty table output to stdout | PRD `rich`/`tabulate`; typer already depends on rich, so it is effectively free |
| `tabulate` | 0.10.0 | (optional) | Lightweight ASCII tables | PRD alternative to rich; **not needed** if rich is used (see Alternatives) |

### Plot-path-only (optional dependency / extra)
| Library | Latest (verified) | Purpose | When to use |
|---|---|---|---|
| `matplotlib` | 3.10.9 (already installed system-wide) | Minimal `--plot` line chart | Phase 6 only; put behind an optional `[project.optional-dependencies] plot` extra so the base install stays lean |

### Dev / tooling (NOT runtime — go in workspace-root dev group)
| Library | Latest (verified) | Recommended pin | Purpose |
|---|---|---|---|
| `ruff` | 0.15.14 | `>=0.15,<0.16` | Lint + format (one tool) |
| `pytest` | 9.0.3 | `>=8,<10` | Test runner |
| `pytest-cov` | 7.1.0 | `>=6` | Coverage measurement + `--cov-fail-under` gate |
| `uv` | 0.11.14 (already installed) | n/a (tool, not dep) | Workspace sync/lock + venv management |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|---|---|---|
| uv workspace | Plain `pip install -e packages/rosbagger-core -e packages/bagq` | Works (verified pattern), but no shared lockfile, no single-command sync, manual ordering. uv workspace is strictly less ceremony. Keep plain-pip as the documented fallback for contributors without uv. |
| hatchling | setuptools / pdm-backend / flit | All work with src-layout. hatchling is uv's default, is fast, needs the least boilerplate, and handles src-layout auto-discovery. setuptools needs explicit `[tool.setuptools.packages.find]`. |
| rich (table output) | tabulate | tabulate is lighter but rich ships transitively with typer anyway, gives color + better wide-table handling, and is the same dep the rest of the CLI uses. Choosing rich means **tabulate can be dropped** from the dep set. |
| typer | click | typer *is* click underneath with type-hint ergonomics; either satisfies PRD. typer recommended per ROADMAP 07-01. |
| `version=9` (ROS2 bag) | `version=8` | v9 is the current default (`Writer.VERSION_LATEST == 9`); v8 is the older rosbag2 metadata layout. Use 9 unless a consumer needs 8. |

**Installation (verified working):**
```bash
# One-time: uv is already present (0.11.14). From repo root:
uv sync                 # creates .venv, editable-installs both packages + dev group
uv run bagq --help      # runs the CLI console-script
uv run pytest           # runs the suite with the coverage gate

# Fallback for contributors without uv (also verified):
python3 -m venv .venv && . .venv/bin/activate
pip install -e packages/rosbagger-core -e packages/bagq
pip install ruff pytest pytest-cov rosbags
```

**Version verification performed:** `rosbags==0.11.2` (PyPI, 2026-05-11, requires-python `>=3.10`), `duckdb==1.5.3`, `sqlglot==30.8.0`, `pyarrow==24.0.0`, `typer==0.25.1`, `rich==15.0.0`, `tabulate==0.10.0`, `ruff==0.15.14`, `pytest==9.0.3`, `pytest-cov==7.1.0`. All confirmed available for Python 3.10.

## Package Legitimacy Audit

> slopcheck was not available in this environment (`pip install slopcheck` not run to avoid mutating the system Python; no network-package install performed for tooling). Per protocol, packages are verified instead by: (a) PyPI registry existence + version check, (b) all are long-established, widely-depended-on projects discovered from the PRD/official docs, and (c) `rosbags`' full transitive tree was installed in an isolated venv and inspected for ROS leakage. None are novel or AI-suggested names. Risk is LOW, but per the package-name provenance rule, packages whose names originate from the PRD (not from official Context7/docs lookups in-session) remain conservatively tagged where noted.

| Package | Registry | Age / maturity | Source repo | Verdict | Disposition |
|---|---|---|---|---|---|
| `rosbags` | PyPI | mature (0.9.0 → 0.11.2 over years; Ternaris) | gitlab.com/ternaris/rosbags | registry-verified; transitive tree inspected, ROS-free | Approved |
| `duckdb` | PyPI | mature (1.x stable) | github.com/duckdb/duckdb | registry-verified | Approved |
| `sqlglot` | PyPI | mature (30.x) | github.com/tobymao/sqlglot | registry-verified | Approved |
| `pyarrow` | PyPI | mature (Apache Arrow) | github.com/apache/arrow | registry-verified | Approved |
| `typer` | PyPI | mature (tiangolo) | github.com/fastapi/typer | registry-verified | Approved |
| `rich` | PyPI | mature (Textualize) | github.com/Textualize/rich | registry-verified | Approved |
| `tabulate` | PyPI | mature | github.com/astanin/python-tabulate | registry-verified | Optional / likely DROPPED in favor of rich |
| `matplotlib` | PyPI | mature; already installed (3.10.9) | github.com/matplotlib/matplotlib | registry-verified + locally present | Approved (plot extra) |
| `ruff` | PyPI | mature (Astral) | github.com/astral-sh/ruff | registry-verified | Approved (dev) |
| `pytest` | PyPI | mature | github.com/pytest-dev/pytest | registry-verified | Approved (dev) |
| `pytest-cov` | PyPI | mature | github.com/pytest-dev/pytest-cov | registry-verified | Approved (dev) |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged [SUS]:** none.
**Transitive watch:** `rosbags` pulls `apsw, lz4, numpy, ruamel.yaml, typing_extensions, zstandard` — **verified ROS-free** by installing in a clean venv and listing the tree. `apsw` (Another Python SQLite Wrapper) is how rosbags reads/writes sqlite3 bags; it is expected, not suspicious. `zstandard`/`lz4` are bag compression codecs. No `mcap` package is pulled — rosbags ships its own MCAP writer.

*Recommendation for the planner: since slopcheck did not run in-session, add one `checkpoint:human-verify` task before the first dependency install that re-runs `pip index versions <pkg>` for each and (optionally) `slopcheck install <pkgs>` if available. This is cheap insurance and matches the protocol's graceful-degradation rule.*

## Architecture Patterns

### System Architecture Diagram

```
                         rosbagger/ (monorepo, uv workspace)
                         root pyproject.toml
                         ├─ [tool.uv.workspace] members = ["packages/*"]
                         ├─ [tool.uv.sources] rosbagger-core = {workspace=true}
                         ├─ [dependency-groups] dev = [ruff, pytest, pytest-cov, rosbags]
                         └─ [tool.ruff] / [tool.pytest.ini_options]   (centralized config)
                                   │
            ┌──────────────────────┴───────────────────────┐
            ▼                                               ▼
  packages/rosbagger-core/                       packages/bagq/
    pyproject.toml  (hatchling, deps: rosbags,     pyproject.toml (hatchling)
       duckdb, sqlglot, pyarrow)                     dependencies = ["rosbagger-core", typer, rich]
    src/rosbagger_core/__init__.py                   [project.scripts] bagq = "bagq.cli:app"
       (placeholder seams: reader/, schema/,         src/bagq/cli.py  ──imports──► rosbagger_core
        backend/ — empty in Phase 1)                          │
            ▲                                                 │ (depends on)
            └─────────────────────────────────────────────────┘

  TEST HARNESS (dev-only, not shipped in either package's runtime path)
  ┌───────────────────────────────────────────────────────────────────┐
  │ tools/  (or tests/fixtures/)                                        │
  │   make_fixtures.py ──uses──► rosbags.rosbag2.Writer (version=9)     │
  │     ├─ StoragePlugin.SQLITE3 ──► r2_sqlite/  (metadata.yaml + .db3)  │
  │     ├─ StoragePlugin.MCAP    ──► r2_mcap/    (metadata.yaml + .mcap) │
  │     └─ rosbags.rosbag1.Writer ─► r1.bag                              │
  │   typestore = get_typestore(Stores.ROS2_HUMBLE / ROS1_NOETIC)       │
  └───────────────────────────────────────────────────────────────────┘
                                   │ produces
                                   ▼
  tests/                                                               
   conftest.py:  no_ros fixture (sys.meta_path blocker)               
                 fixture-bag pytest fixtures (paths to the 3 bags)    
   test_offline_guard.py ──asserts──► rclpy/rosbag2_py NOT importable 
                                       & not in sys.modules           
   test_fixtures.py      ──asserts──► all 3 bags re-open via AnyReader 
                                   │
                                   ▼
  CI (.github/workflows/ci.yml)
   ubuntu-latest, NO ROS installed
   astral-sh/setup-uv → uv sync --locked → uv run ruff check → uv run pytest --cov-fail-under=80
```

### Recommended Project Structure
```
rosbagger/
├── pyproject.toml                 # workspace root: uv workspace + dev group + ruff/pytest config
├── uv.lock                        # single lockfile (commit it)
├── README.md
├── .github/
│   └── workflows/
│       └── ci.yml                 # no-ROS CI
├── packages/
│   ├── rosbagger-core/
│   │   ├── pyproject.toml         # hatchling; runtime deps; NO ROS
│   │   └── src/
│   │       └── rosbagger_core/
│   │           ├── __init__.py    # __version__
│   │           ├── reader/        # empty seam (Phase 2)   — __init__.py only
│   │           ├── schema/        # empty seam (Phase 3)   — __init__.py only
│   │           └── backend/       # empty QueryBackend seam (Phase 5) — __init__.py only
│   └── bagq/
│       ├── pyproject.toml         # hatchling; depends on rosbagger-core; [project.scripts]
│       └── src/
│           └── bagq/
│               ├── __init__.py
│               └── cli.py         # typer app (placeholder `bagq --help` ok for Phase 1)
├── tools/
│   └── make_fixtures.py           # the fixture-bag generator (importable; deterministic)
└── tests/
    ├── conftest.py                # no_ros fixture + fixture-bag path fixtures
    ├── test_offline_guard.py      # the load-bearing invariant test
    └── test_fixtures.py           # all 3 fixtures re-open + carry expected content
```

Note the **package directory name uses a hyphen** (`rosbagger-core/`, distribution name `rosbagger-core`) while the **import package uses an underscore** (`rosbagger_core`). This is normal Python packaging and was verified working.

**Where should the fixture generator live?** Recommendation: a `tools/make_fixtures.py` module that is *importable by tests* and also runnable as `python -m tools.make_fixtures` / `uv run python tools/make_fixtures.py`. Tests call its functions to build bags into a pytest `tmp_path` (deterministic, no committed binaries). Keep it OUT of `rosbagger_core`'s shipped namespace — it is a dev artifact, and shipping a `rosbags`-writer in the core package would not violate the offline rule (rosbags is offline) but would muddy the "core is the library" boundary. (Open question O-2 covers committed vs. generated.)

### Pattern 1: uv workspace with per-package hatchling backends
**What:** A non-package root `pyproject.toml` declares workspace members; each member is an independently buildable hatchling package; intra-workspace dependency resolved via `[tool.uv.sources] ... = { workspace = true }`.
**When to use:** A monorepo of small, independently-installable packages where one depends on another — exactly PRD §3.1.
**Example:** see Code Examples §6 (verified end-to-end).

### Pattern 2: Offline-import guard via `sys.meta_path` blocker
**What:** A pytest fixture installs a meta-path finder that raises `ImportError` for any ROS top-level module, then purges any already-imported ROS modules. The test then asserts (a) `rclpy`/`rosbag2_py` are not importable and (b) `rosbagger_core` + `bagq` still import.
**When to use:** Whenever you must prove "this code path does not touch ROS" on a machine that *has* ROS installed — i.e., the dev machine here. It is also correct (and cheap) on clean CI.
**Why this and not the naive version:** A test that just does `with pytest.raises(ImportError): import rclpy` *passes for the wrong reason* on a clean CI runner (rclpy genuinely absent) and *fails to protect anything* on the dev box (rclpy genuinely present → no error → but that does not prove core avoids it). The blocker makes the test meaningful in both environments.
**Example:** see Code Examples §5 (verified to pass).

### Pattern 3: src-layout
**What:** Code lives under `packages/<pkg>/src/<import_name>/`, not at package root.
**When to use:** Always, for libraries. It prevents accidentally importing the package from the source tree instead of the installed copy (which would mask packaging bugs and make the "imports as an installed package" success criterion untestable). hatchling auto-discovers `src/`.

### Anti-Patterns to Avoid
- **Using the published `rosbags` docs `Writer('/path')` call verbatim.** It omits the now-required `version=` kwarg and will raise `TypeError`. Always pass `version=9`.
- **Selecting MCAP via a non-existent `Writer.StoragePlugin`.** `StoragePlugin` is imported from `rosbags.rosbag2`, not accessed as a `Writer` attribute (verified: `hasattr(Writer, 'StoragePlugin')` is `False`).
- **Reusing one `make_header()` helper across ROS1 and ROS2.** ROS1 `std_msgs/msg/Header` has a required `seq` field that ROS2's does not — a shared helper raises `TypeError: ... missing 1 required positional argument: 'seq'` (encountered live). Make the helper format-aware.
- **Committing binary fixture bags to git** without a regeneration path. Bags are version-coupled to `rosbags`; prefer generating them per-test into `tmp_path`. (See O-2.)
- **A root `[project]` table on the workspace root.** Keep the root a *virtual* workspace (only `[tool.uv.*]` + `[dependency-groups]`); a root `[project]` makes uv try to build the root as a package and complicates `uv add` (encountered live: `uv add` on a virtual root needs `--dev` / dependency-groups).
- **Importing the heavy stack (duckdb/pyarrow) at module top-level in `rosbagger_core/__init__.py`.** Keep `__init__` light so the import-guard test is fast and so `bagq --help` does not pay the duckdb import cost. Defer heavy imports into the functions that use them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Writing ROS1/ROS2/MCAP bags for fixtures | A hand-rolled bag serializer or shelling out to `ros2 bag` | `rosbags` `Writer` + `typestore.serialize_cdr` / `serialize_ros1` | Bag formats (sqlite3 schema, MCAP framing, ROS1 record structure, CDR/ROS1 wire encoding) are intricate and version-specific; `rosbags` is the PRD-mandated, no-ROS implementation |
| Well-known message definitions (Twist, Imu, Header, Image) | Re-declaring `.msg` definitions by hand | `get_typestore(Stores.ROS2_HUMBLE)` / `Stores.ROS1_NOETIC` | The typestore ships all standard message types; no ROS install and no manual definitions needed |
| Multi-package editable install + lockfile | Custom `pip install -e` scripts / Makefile ordering | `uv sync` over a workspace | uv resolves the whole graph, links editable installs, and locks — one command, verified working |
| Lint + format as two tools | black + flake8 + isort | `ruff` (does all three) | One fast tool, one config block; PRD mandates ruff |
| Coverage gate | Parsing coverage output in CI | `pytest-cov --cov-fail-under=80` | Built-in non-zero exit on under-coverage (verified: exits non-zero at 40%) |
| sqlite3 access for bags | stdlib `sqlite3` | (nothing — `rosbags` uses `apsw` internally) | rosbags already handles bag sqlite via `apsw`; you never touch the DB directly in Phase 1 |

**Key insight:** Phase 1 writes almost no domain logic. Its entire value is *correctly wiring mature tools* (rosbags, uv, ruff, pytest) and *proving the offline invariant*. The two places to spend real care are the `rosbags` write-call signature (drifted) and the import-guard test (must be meaningful with ROS present).

## Runtime State Inventory

> Phase 1 is greenfield (creating new files in an empty repo) — not a rename/refactor. This section is included only to record the one piece of *pre-existing host state* that materially affects the design.

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | None — empty repo (only `CLAUDE.md`, `docs/`, `.planning/`, `.git`). Verified by `ls -la`. | none |
| Live service config | None relevant. | none |
| OS-registered state | **ROS 2 Humble is sourced into this shell's environment**: `PYTHONPATH` includes `/opt/ros/humble/lib/python3.10/site-packages` and `/opt/ros/humble/local/lib/python3.10/dist-packages`; `ROS_DISTRO=humble`, `AMENT_PREFIX_PATH=/opt/ros/humble`. Consequence: a bare `python3 -c "import rclpy"` **succeeds** on this machine. This is precisely why the offline guard must use the meta-path blocker, and why local test runs should clear `PYTHONPATH`. | The guard fixture neutralizes it; CI runs ROS-free so it is moot there. Document `PYTHONPATH=""` for local runs (uv's own venv largely isolates this, but the leak is real). |
| Secrets/env vars | None. | none |
| Build artifacts / installed packages | No project package installed yet. System Python has `matplotlib 3.10.9`, `rclpy`, `rosbag2_py` (from ROS). The project venv (uv) is isolated from system site-packages but **not** automatically from `PYTHONPATH`. | Rely on uv venv; clear `PYTHONPATH` for the guard test to be a true test of the clean case. |

## Common Pitfalls

### Pitfall 1: `rosbags` Writer API drift (the #1 landmine)
**What goes wrong:** Code copied from the published rosbags docs (`with Writer('/path') as w:`) raises `TypeError: __init__() missing 1 required keyword-only argument: 'version'` on 0.11.x.
**Why it happens:** The ROS2 `Writer.__init__` signature is now `(self, path, *, version: Literal[8, 9], storage_plugin: StoragePlugin = SQLITE3)`. `version` is required and keyword-only. The docs example predates this.
**How to avoid:** Always call `Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3)` (or `.MCAP`). Pin `rosbags>=0.11,<0.12` so the signature does not shift under you. (Verified signature via `inspect.signature`.)
**Warning signs:** `TypeError` mentioning `version` at writer construction.

### Pitfall 2: `StoragePlugin` import location
**What goes wrong:** `Writer.StoragePlugin.MCAP` → `AttributeError: type object 'Writer' has no attribute 'StoragePlugin'` (encountered live).
**Why it happens:** The enum is a module-level export, not a `Writer` class attribute. (There is also a `Writer.STORAGE_PLUGINS` *dict*, which is a different thing.)
**How to avoid:** `from rosbags.rosbag2 import Writer, StoragePlugin` then `storage_plugin=StoragePlugin.MCAP`. (Verified: `rosbags.rosbag2.StoragePlugin` exists; members `SQLITE3`, `MCAP`.)
**Warning signs:** `AttributeError` on `StoragePlugin`.

### Pitfall 3: ROS1 vs ROS2 `Header` field mismatch
**What goes wrong:** `std_msgs__msg__Header.__init__() missing 1 required positional argument: 'seq'` when reusing a ROS2-shaped header for a ROS1 bag (encountered live).
**Why it happens:** ROS1 `std_msgs/Header` has fields `(seq, stamp, frame_id)`; ROS2 dropped `seq` → `(stamp, frame_id)`.
**How to avoid:** Build headers per-format: ROS1 `Header(seq=0, stamp=..., frame_id=...)`, ROS2 `Header(stamp=..., frame_id=...)`. More generally: do not assume a single message-construction helper works across both typestores.
**Warning signs:** `TypeError` about `seq` (ROS1) or "unexpected keyword argument 'seq'" (ROS2).

### Pitfall 4: The offline guard that proves nothing
**What goes wrong:** `with pytest.raises(ImportError): import rclpy` is green on CI and gives false confidence; on the dev machine (`rclpy` present) it would *fail* — but even "fixing" it to skip-if-present proves nothing about whether `rosbagger_core` pulls ROS in.
**Why it happens:** The test conflates "ROS is absent in this env" with "core does not depend on ROS."
**How to avoid:** Use the `sys.meta_path` blocker fixture (Code Examples §5): block ROS modules, purge them from `sys.modules`, then assert core/bagq still import AND that importing them did not populate `sys.modules` with any ROS module. This is true on both clean CI and the ROS-equipped dev box (both verified-by-construction).
**Warning signs:** A guard test that is `skip`ped or trivially green; a test that only checks the CI environment, not the import graph.

### Pitfall 5: Editable-install false positive from src on `sys.path`
**What goes wrong:** Tests "pass" by importing the package from the source tree rather than the installed distribution, masking a broken `pyproject.toml`.
**Why it happens:** Running pytest from the repo root with a flat layout puts the source dir on `sys.path[0]`.
**How to avoid:** Use `src/` layout (forces import-from-installed) and run via `uv run pytest` (uses the synced venv). Verified: with src-layout, `rosbagger_core.__file__` resolved to the installed editable path.
**Warning signs:** Imports work without ever running `uv sync` / `pip install -e`.

### Pitfall 6: uv picks a different Python than you expect
**What goes wrong:** In a throwaway test, `uv` selected Python 3.12 for the venv even though the project targets ≥3.10 (observed: `python 3.12.13` in pytest output).
**Why it happens:** uv chooses the newest interpreter satisfying `requires-python` unless pinned.
**How to avoid:** Pin the dev interpreter with a `.python-version` file (e.g. `3.10`) or `uv python pin 3.10`, so CI and local match the floor. Test on the floor (3.10) in CI to catch 3.10-incompatible syntax early; optionally matrix 3.10–3.13.
**Warning signs:** Coverage/test output reports an unexpected Python version.

## Code Examples

All examples below were **executed successfully** in an isolated venv with `rosbags==0.11.2` and `PYTHONPATH=""` (no ROS), unless noted.

### 1. Typestore + message construction (ROS2)
```python
# Source: VERIFIED live (rosbags 0.11.2); shape matches https://ternaris.gitlab.io/rosbags/topics/typesys.html
from rosbags.typesys import Stores, get_typestore

ts = get_typestore(Stores.ROS2_HUMBLE)          # ROS1: Stores.ROS1_NOETIC
Twist = ts.types['geometry_msgs/msg/Twist']
Vector3 = ts.types['geometry_msgs/msg/Vector3']
msg = Twist(linear=Vector3(x=1.0, y=0.0, z=0.0),
            angular=Vector3(x=0.0, y=0.0, z=0.1))
raw = ts.serialize_cdr(msg, 'geometry_msgs/msg/Twist')   # ROS1: ts.serialize_ros1(...)
```

### 2. Write a ROS2 **sqlite3** bag
```python
# Source: VERIFIED live (rosbags 0.11.2)
from rosbags.rosbag2 import Writer, StoragePlugin
from rosbags.typesys import Stores, get_typestore

ts = get_typestore(Stores.ROS2_HUMBLE)
mt = 'geometry_msgs/msg/Twist'
with Writer('out/r2_sqlite', version=9, storage_plugin=StoragePlugin.SQLITE3) as w:
    conn = w.add_connection('/cmd_vel', mt, typestore=ts)   # typestore is keyword-only
    for i in range(3):
        t_ns = 1_000_000_000 + i * 100_000_000              # explicit log timestamp (ns)
        m = ts.types['geometry_msgs/msg/Twist'](
            linear=ts.types['geometry_msgs/msg/Vector3'](x=float(i), y=0.0, z=0.0),
            angular=ts.types['geometry_msgs/msg/Vector3'](x=0.0, y=0.0, z=0.1*i))
        w.write(conn, t_ns, ts.serialize_cdr(m, mt))
# Produces directory: out/r2_sqlite/{metadata.yaml, r2_sqlite.db3}   (verified)
```

### 3. Write a ROS2 **MCAP** bag (only the storage_plugin changes)
```python
# Source: VERIFIED live (rosbags 0.11.2)
from rosbags.rosbag2 import Writer, StoragePlugin
with Writer('out/r2_mcap', version=9, storage_plugin=StoragePlugin.MCAP) as w:
    ...  # identical add_connection / write calls as §2
# Produces directory: out/r2_mcap/{metadata.yaml, r2_mcap.mcap}   (verified)
```

### 4. Write a **ROS1** `.bag` (different Writer, ros1 serialization, seq in Header)
```python
# Source: VERIFIED live (rosbags 0.11.2)
from rosbags.rosbag1 import Writer            # NOTE: rosbag1, no version/storage_plugin args
from rosbags.typesys import Stores, get_typestore

ts = get_typestore(Stores.ROS1_NOETIC)
mt = 'geometry_msgs/msg/Twist'
with Writer('out/r1.bag') as w:               # single-file .bag
    conn = w.add_connection('/cmd_vel', mt, typestore=ts)
    for i in range(3):
        m = ts.types['geometry_msgs/msg/Twist'](
            linear=ts.types['geometry_msgs/msg/Vector3'](x=float(i), y=0.0, z=0.0),
            angular=ts.types['geometry_msgs/msg/Vector3'](x=0.0, y=0.0, z=0.1*i))
        w.write(conn, 1_000_000_000 + i*100_000_000, ts.serialize_ros1(m, mt))

# Header for a ROS1 message needs `seq`; ROS2 does NOT:
def make_header(ts, sec, nsec, frame, ros1):
    Header = ts.types['std_msgs/msg/Header']; Time = ts.types['builtin_interfaces/msg/Time']
    t = Time(sec=sec, nanosec=nsec)
    return Header(seq=0, stamp=t, frame_id=frame) if ros1 else Header(stamp=t, frame_id=frame)
```

### 5. Offline-import guard (conftest fixture + test) — the load-bearing invariant
```python
# Source: VERIFIED live — both tests PASS with ROS blocked, and the blocker works even when ROS is installed.
# tests/conftest.py
import sys
import pytest

class _ROSBlocker:
    """Meta-path finder that blocks ROS imports even when ROS is installed on the host."""
    BLOCKED = {"rclpy", "rosbag2_py", "rosidl_runtime_py", "ament_index_python"}
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in self.BLOCKED:
            raise ImportError(f"{name} is blocked: offline package must not import ROS")
        return None

@pytest.fixture
def no_ros(monkeypatch):
    monkeypatch.setattr(sys, "meta_path", [_ROSBlocker(), *sys.meta_path])
    for m in list(sys.modules):
        if m.split(".")[0] in _ROSBlocker.BLOCKED:
            monkeypatch.delitem(sys.modules, m, raising=False)
    yield

# tests/test_offline_guard.py
import importlib, sys, pytest

def test_core_imports_without_ros(no_ros):
    for mod in ("rclpy", "rosbag2_py"):
        with pytest.raises(ImportError):
            importlib.import_module(mod)
    importlib.import_module("rosbagger_core")   # must still succeed
    importlib.import_module("bagq")

def test_no_ros_leaked_into_sys_modules():
    import rosbagger_core  # noqa: F401
    import bagq            # noqa: F401
    leaked = [m for m in sys.modules if m.split(".")[0] in {"rclpy", "rosbag2_py"}]
    assert leaked == [], f"offline import pulled in ROS modules: {leaked}"
```

### 6. uv workspace (verified: both packages editable-install, bagq script runs, depends on core)
```toml
# rosbagger/pyproject.toml  (workspace ROOT — virtual, NO [project] table)
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
rosbagger-core = { workspace = true }

[dependency-groups]
dev = ["ruff>=0.15,<0.16", "pytest>=8,<10", "pytest-cov>=6", "rosbags>=0.11,<0.12"]

[tool.ruff]
line-length = 100
src = ["packages/rosbagger-core/src", "packages/bagq/src", "tools", "tests"]
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]   # pyflakes, pycodestyle, isort, pyupgrade, bugbear, simplify
[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
addopts = "--cov=rosbagger_core --cov=bagq --cov-report=term-missing --cov-fail-under=80"
testpaths = ["tests"]
```
```toml
# packages/rosbagger-core/pyproject.toml
[project]
name = "rosbagger-core"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = ["rosbags>=0.11,<0.12", "duckdb>=1.4,<2", "sqlglot>=27,<31", "pyarrow>=18"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
```toml
# packages/bagq/pyproject.toml
[project]
name = "bagq"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = ["rosbagger-core", "typer>=0.15,<1", "rich>=13"]
[project.scripts]
bagq = "bagq.cli:app"
[project.optional-dependencies]
plot = ["matplotlib>=3.8"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
Verified result of `uv sync` then `uv run python -c "import rosbagger_core, bagq"` and `uv run bagq`:
```
+ bagq==0.0.0 (from .../packages/bagq)
+ rosbagger-core==0.0.0 (from .../packages/rosbagger-core)
core 0.0.0 | bagq 0.0.0
bagq using core 0.0.0          # console-script runs and resolves the core dependency
```

### 7. No-ROS GitHub Actions CI (uv)
```yaml
# .github/workflows/ci.yml — Source: docs.astral.sh/uv/guides/integration/github (verified pattern)
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest          # NO ROS installed here — that is the point
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
      - run: uv python pin ${{ matrix.python-version }}
      - run: uv sync --locked --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest            # --cov-fail-under=80 enforced via pyproject addopts
```

### 8. Forward-looking fixture content (verified to write + round-trip in all 3 formats)
```python
# Source: VERIFIED live — Twist (nested scalars, no header) + Imu (header.stamp + 9-float covariance arrays)
# Re-read via AnyReader: each bag yielded 6 msgs across topics {/cmd_vel, /imu}; imu.header.stamp.sec preserved.
# Topics chosen so Phase 2-3 can later test:
#   /cmd_vel  geometry_msgs/msg/Twist : nested scalars  -> "twist.linear.x" flattening (QURY-02); stamp = NULL (QURY-04)
#   /imu      sensor_msgs/msg/Imu     : header.stamp     -> stamp extraction (QURY-04);
#                                       orientation_covariance (float64[9]) -> LIST column (QURY-03)
# RECOMMEND ALSO ADDING (not yet executed, but same API):
#   /image    sensor_msgs/msg/Image   : .data (uint8[])  -> heavy blob lazy-materialization (QURY-07)
#   /scan     sensor_msgs/msg/LaserScan or PointCloud2    : larger arrays / blob
import numpy as np
imu = ts.types['sensor_msgs/msg/Imu'](
    header=make_header(ts, sec=1, nsec=0, frame='imu_link', ros1=False),
    orientation=ts.types['geometry_msgs/msg/Quaternion'](x=0.0, y=0.0, z=0.0, w=1.0),
    orientation_covariance=np.zeros(9),               # float64[9] -> LIST in Phase 3
    angular_velocity=ts.types['geometry_msgs/msg/Vector3'](x=0.0, y=0.0, z=0.1),
    angular_velocity_covariance=np.zeros(9),
    linear_acceleration=ts.types['geometry_msgs/msg/Vector3'](x=0.0, y=0.0, z=9.8),
    linear_acceleration_covariance=np.zeros(9))
# Re-open any bag:  from rosbags.highlevel import AnyReader
#   with AnyReader([path]) as r: msgs = list(r.messages())  # yields (Connection, t_ns:int, raw:bytes)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| `rosbags` ROS2 `Writer('/path')` with implicit version | `Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3\|.MCAP)` — `version` required, plugin enum | by 0.11.x (current 0.11.2) | Published doc snippets are stale; pin `<0.12` and pass `version` (the central landmine of this phase) |
| Two-tool lint/format (black + flake8 + isort) | `ruff` does lint + format + import-sort | ruff format GA (well established by 2026) | One tool, one config block |
| `pip install -e` per package + manual ordering | `uv sync` over a `[tool.uv.workspace]` | uv workspaces matured 2024–2025; standard by 2026 | Single command, single lockfile, deterministic editable graph |
| `setup.py` / setuptools boilerplate | PEP 621 `[project]` + hatchling, `src/` auto-discovery | mainstream by 2024 | Less boilerplate; uv's default backend |
| flat package layout | `src/` layout | long-standing best practice | Makes "imports as installed package" actually testable |

**Deprecated/outdated:**
- Copy-pasting `Writer('/path')` from the rosbags docs — will `TypeError` on current releases.
- `Writer.StoragePlugin` attribute access — never existed in 0.11.x; import `StoragePlugin` from `rosbags.rosbag2`.
- Reusing a single header/message helper across ROS1 and ROS2 typestores — breaks on the `seq` field.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | typer (over click) is the intended CLI lib | Standard Stack | LOW — CONTEXT lists it as discretion; ROADMAP 07-01 leans typer; swap is trivial in Phase 7 |
| A2 | rich (and dropping tabulate) is acceptable for table output | Standard Stack / Alternatives | LOW — both PRD-sanctioned; rich ships with typer anyway. Confirm in planning if a no-color/minimal-dep stance is wanted |
| A3 | Fixture bags should be generated per-test (not committed binaries) | Project Structure / O-2 | MEDIUM — see Open Question O-2; affects determinism vs. repo cleanliness. User/planner should decide |
| A4 | `version=9` (not 8) for ROS2 fixture bags | Standard Stack | LOW — 9 is `VERSION_LATEST`; only matters if a downstream consumer needs v8 metadata layout |
| A5 | Pinning `rosbags>=0.11,<0.12` is the right ceiling | Standard Stack | LOW-MEDIUM — protects against further API drift, but a future 0.12 may be desirable; revisit when reader lands in Phase 2 |
| A6 | Phase 1 ships a placeholder `bagq --help` (typer app with no real commands) | phase_requirements / O-1 | LOW — explicitly open in CONTEXT; either choice satisfies "imports as installed package" |
| A7 | The empty `reader/`, `schema/`, `backend/` seam packages are wanted in Phase 1 | Project Structure | LOW — anticipates the `QueryBackend` seam (locked decision) and Phases 2/3/5; harmless if planner prefers to defer folder creation |

## Open Questions (RESOLVED)

> All four resolved during planning (Phase 1 plans, committed `b72e917`):
> - **O-1 — RESOLVED:** wire a minimal runnable `bagq --help` (+ `--version`) → 01-01 Task 3.
> - **O-2 — RESOLVED:** session-scoped `tmp_path_factory` fixtures + `tools/make_fixtures.py`; no committed binaries → 01-03.
> - **O-3 — RESOLVED:** CI matrix `["3.10", "3.12"]` + `.python-version` pinned to 3.10 → 01-02 Task 3 / 01-01 Task 2.
> - **O-4 — RESOLVED:** include a tiny `/image` `sensor_msgs/msg/Image` blob in the fixtures now → 01-03 Task 1.

1. **O-1 — Does Phase 1 wire a runnable `bagq --help`, or only a placeholder entry point?**
   - What we know: Either satisfies Success Criterion #1 (both import as installed packages). A typer app with zero commands still exposes `--help`. Verified that a console-script entry point works in the workspace.
   - What's unclear: Whether the planner wants a visible `bagq --help` now (nicer demo) or a bare importable stub (less to undo in Phase 7).
   - Recommendation: Wire a minimal typer app exposing `bagq --help` (and maybe `bagq --version`); it costs ~5 lines, proves the entry point end-to-end, and Phase 7 fills in `query`/`info`/`tables`.

2. **O-2 — Committed fixture bags vs. generated-per-test?**
   - What we know: bags are version-coupled to `rosbags`; generation is fast (sub-second for 3 tiny bags, verified) and deterministic given fixed timestamps.
   - What's unclear: Whether later phases want a *stable on-disk* fixture path (committed) for cross-test reuse and faster iteration, or always-fresh `tmp_path` bags.
   - Recommendation: Generate into a session-scoped pytest `tmp_path_factory` fixture (fresh, deterministic, no binaries in git), and expose the generator as `tools/make_fixtures.py` so a human can also produce on-disk bags for manual `bagq` testing. Revisit if Phase 2+ test runtime becomes a concern.

3. **O-3 — Python version matrix for CI?**
   - What we know: floor is 3.10; uv defaulted to 3.12 locally. matrix is cheap.
   - What's unclear: how many versions to test.
   - Recommendation: matrix `["3.10", "3.12"]` (floor + a current) and pin local dev to 3.10 via `.python-version` so the floor is exercised by default.

4. **O-4 — Should the fixture generator also write a heavy-blob message (Image/PointCloud2) in Phase 1?**
   - What we know: QURY-07 (lazy blob) is a Phase 3 requirement; the Twist+Imu fixtures already cover nested scalars, arrays, and header.stamp (verified). Adding `sensor_msgs/msg/Image` uses the identical API.
   - What's unclear: whether to invest in blob content now or when Phase 3 needs it.
   - Recommendation: Include a tiny `/image` `sensor_msgs/msg/Image` (e.g. 2x2 RGB) in the fixtures now — it is a few lines, makes the fixture "forward-looking" per the locked decision, and saves a fixture change in Phase 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | everything | ✓ | 3.10.12 (meets `>=3.10` floor) | — |
| `uv` | workspace sync/lock + CI | ✓ | 0.11.14 | plain `pip install -e` of both packages (verified) |
| `git` | repo (already initialized) | ✓ | 2.34.1 | — |
| `matplotlib` | `--plot` (Phase 6) | ✓ (system) | 3.10.9 | declare as `plot` extra; not needed for Phase 1 tests |
| `ruff` | lint/format | ✗ (not installed) | — | installed via dev group on `uv sync` |
| `pytest` / `pytest-cov` | tests/coverage | ✗ | — | installed via dev group on `uv sync` |
| `rosbags` | fixture generator + tests | ✗ locally; **PyPI-verified 0.11.2** | — | installed via dev group / package deps; **confirmed installs cleanly with zero ROS deps** |
| `duckdb`, `sqlglot`, `pyarrow`, `typer`, `rich` | core/cli runtime | ✗ | — | installed via package deps on `uv sync`; all PyPI-verified |
| ROS 2 Humble (`rclpy`, `rosbag2_py`) | **must NOT be a dependency** | ✓ present on host (trap) | Humble | N/A — actively guarded against (Pitfall 4) |

**Missing dependencies with no fallback:** none — every missing package is on PyPI (versions verified) and installs via `uv sync`.
**Missing dependencies with fallback:** `uv` itself has a documented plain-`pip` fallback (verified) for contributors who do not use uv.
**Host hazard (not a missing dep):** ROS is on the shell `PYTHONPATH` → bare `python3 -c "import rclpy"` succeeds. Mitigated by uv's isolated venv + the meta-path guard + `PYTHONPATH=""` for local guard runs.

## Security Domain

> `security_enforcement` is absent from `.planning/config.json` (treated as enabled). Phase 1 has **no auth, no network surface, no untrusted input, no cryptography, and no data persistence** — it is dev infrastructure. The only meaningful security surface is **software supply chain** (the new dependency set). ASVS application/web categories (V2–V6) do not apply.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | No auth surface in Phase 1 |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access-controlled resources |
| V5 Input Validation | no (Phase 1) | No external/untrusted input; bag parsing arrives in Phase 2. (Future note: bags are untrusted input — Phase 2 reader should treat malformed bags defensively.) |
| V6 Cryptography | no | No crypto |
| V14 Configuration / Dependency | **yes** | Pin dependency versions; commit `uv.lock`; verify package legitimacy (see Package Legitimacy Audit); CI installs with `uv sync --locked` for reproducible, tamper-evident builds |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| Dependency confusion / typosquatting (10+ new deps) | Tampering / Spoofing | All packages PyPI-verified by name+version; established projects with known repos; commit `uv.lock`; optional `slopcheck` checkpoint before first install (see audit note) |
| Supply-chain drift (unpinned deps changing API/behavior, e.g. the rosbags Writer drift) | Tampering | Version pins with upper bounds (esp. `rosbags<0.12`); `uv sync --locked` in CI; lockfile committed |
| Malicious `postinstall`-style code in a build dep | Tampering | hatchling + the listed deps are pure-metadata installs (no arbitrary build scripts beyond hatchling); pinned + locked |
| (Forward note) Malformed/hostile bag file | Tampering / DoS | Out of scope for Phase 1; Phase 2 reader must handle corrupt bags without crashing the process — flag for Phase 2 research |

## Sources

### Primary (HIGH confidence — verified by running the real packages)
- **Live introspection & execution, `rosbags==0.11.2`** in an isolated venv (`PYTHONPATH=""`): `inspect.signature` of `rosbags.rosbag2.Writer.__init__`, `add_connection`, `write`; `rosbags.rosbag1.Writer`; `rosbags.rosbag2.StoragePlugin` members; `Stores` enum; `AnyReader.__init__/messages/deserialize`; `Connection` fields. Wrote + re-read ROS1/ROS2-sqlite/ROS2-MCAP fixtures with Twist + Imu(header.stamp + covariance arrays).
- **Live build of a 2-package uv workspace**: `uv sync`, both packages editable-installed, `bagq` console-script executed and resolved its `rosbagger-core` dependency; `pytest --cov-fail-under=80` enforced (failed at 40% as designed).
- **Live offline-guard test**: both guard tests PASS with ROS blocked; meta-path blocker confirmed to block `rclpy` even when installed.
- **PyPI registry** (`pip index versions` / `pip install ==`): rosbags 0.11.2, duckdb 1.5.3, sqlglot 30.8.0, pyarrow 24.0.0, typer 0.25.1, rich 15.0.0, tabulate 0.10.0, ruff 0.15.14, pytest 9.0.3, pytest-cov 7.1.0.
- rosbags PyPI metadata (latest 0.11.2, 2026-05-11, requires-python `>=3.10`): https://pypi.org/pypi/rosbags/json

### Secondary (MEDIUM confidence — official docs, cross-checked against live behavior)
- rosbags official docs (Rosbag2 / Rosbag1 / Typesys writer examples): https://ternaris.gitlab.io/rosbags/ — NOTE: the ROS2 `Writer('/path')` example is stale vs. the live 0.11.2 signature; live introspection takes precedence.
- uv GitHub Actions integration: https://docs.astral.sh/uv/guides/integration/github/ and https://github.com/astral-sh/setup-uv
- uv workspaces: https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/ ; https://docs.astral.sh/uv/concepts/projects/workspaces/
- Ruff configuration (select rules, format, hierarchical/monorepo config): https://docs.astral.sh/ruff/configuration/ and https://docs.astral.sh/ruff/settings/

### Tertiary (LOW confidence — community, not load-bearing)
- General Python monorepo patterns: https://www.tweag.io/blog/2023-04-04-python-monorepo-1/ ; https://itnext.io/python-workspaces-monorepos-d1ce81c74818

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package + version verified on PyPI; the full stack relevant to Phase 1 (`rosbags`, uv, ruff, pytest, pytest-cov, typer) installed and exercised.
- rosbags write API: HIGH — verified by `inspect.signature` and by writing+re-reading all three formats; corrects the stale published docs.
- Monorepo packaging: HIGH — built the exact 2-package uv workspace and confirmed both import + `bagq` script runs + dependency resolves.
- Offline-import guard: HIGH — guard tests written and passing; meta-path blocker proven to work with ROS installed.
- ruff/pytest/coverage config: HIGH — `--cov-fail-under` enforcement verified; ruff config from official docs (not executed, but standard).
- CI workflow: MEDIUM — pattern from official uv docs; not run in a real Actions runner this session.
- Forward-looking fixture content: HIGH for Twist+Imu (executed); MEDIUM for the recommended Image/PointCloud2 addition (same API, not yet executed).

**Research date:** 2026-05-21
**Valid until:** ~2026-06-20 (30 days). Re-verify the `rosbags` Writer signature if bumping past 0.11.x — API drift in this library is the dominant risk.
