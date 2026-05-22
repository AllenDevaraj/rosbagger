# Phase 1: Scaffold & Test Harness - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Source:** PRD Express Path (docs/superpowers/specs/2026-05-21-rosbagger-design.md)

<domain>
## Phase Boundary

Phase 1 builds the **empty-but-working skeleton** that every later phase plugs into.
It ships no bag-querying behavior of its own. It delivers:

1. A **monorepo** containing two independently-installable Python packages —
   `rosbagger-core` (the offline library) and `bagq` (the CLI) — both pip-installable.
2. **Packaging** (`pyproject.toml` per package) so `rosbagger-core` and `bagq` import as
   installed packages.
3. **Dev tooling**: `ruff` (lint + format), `pytest`, and a **CI workflow that runs the
   test suite green with no ROS installed**.
4. A **fixture-bag generator** that uses `rosbags` to *write* tiny bags in all three target
   formats — ROS 1 (`.bag`), ROS 2 sqlite3, and ROS 2 MCAP — so the whole suite (now and in
   every later phase) runs with **no ROS install**.

Out of this phase: any reader, schema-mapping, inspect, query, output, or CLI-command logic.
Those are Phases 2–8. Phase 1 only creates the structure and the test substrate they depend on.

**Success Criteria (must be TRUE at phase end):**
1. `rosbagger-core` and `bagq` import as installed packages.
2. `pytest` runs green in CI with no ROS installed.
3. A generator produces ROS1, ROS2-sqlite, and MCAP fixture bags.
</domain>

<decisions>
## Implementation Decisions

Everything below is a **locked decision** from the PRD / project constraints unless filed under
"Claude's Discretion".

### Monorepo Layout & Packages
- A monorepo of small, **independently-installable** packages (PRD §3.1). Phase 1 scaffolds
  exactly two: `rosbagger-core` and `bagq`.
- `rosbagger-core` is the pure-Python offline library; `bagq` is the CLI and **depends on
  `rosbagger-core`**.
- The layout must leave room for future sibling packages (`rosbagger-tf`, `-record`, `-replay`,
  `-gui`, `-edit`) without restructuring — but those are NOT created in Phase 1.

### Offline / Live Split (architectural invariant — enforce from day one)
- `rosbagger-core` and `bagq` are **offline** packages and **MUST NOT import ROS**
  (`rclpy`, `rosbag2_py`) — directly or transitively (PRD §3.2, §3.3.2; CLAUDE.md portability).
- The dev machine has ROS 2 Humble present (`rosbag2_py` importable), so this boundary must be
  *actively guarded* (e.g., a test asserting offline packages import with no ROS on the path),
  not assumed.
- Live packages (`record`/`replay`) will isolate `rclpy` behind their own boundary — out of
  scope for Phase 1.

### Packaging
- **Python ≥ 3.10** (PRD §4.3; CLAUDE.md).
- Each package owns its own `pyproject.toml`; both installable via `pip` (editable installs for
  local dev).
- **Offline dependency set** (PRD §4.3): `rosbags`, `duckdb`, `sqlglot`, `pyarrow`,
  `matplotlib` (plot path only), a CLI library, and `rich`/`tabulate` for table output.
  **No ROS dependency** in either package's metadata.
- NOTE: `duckdb` is not yet installed in the environment (PROJECT.md Context) — Phase 1's
  packaging work introduces the dependency set.

### Query Backend Seam (preserve in layout, do not implement)
- DuckDB is the default query backend behind a **swappable `QueryBackend` seam** (PRD §3.3.6,
  §4.1). The package layout should anticipate this seam; the actual backend lands in Phase 5.

### Dev Tooling
- **Lint + format:** `ruff`.
- **Test runner:** `pytest`.
- **CI:** must execute `pytest` to green **with no ROS installed** — this is the load-bearing
  guarantee of the whole project's "universal / no-ROS" promise.
- **Coverage target ≥ 80%** (PRD §6; project standard).

### Fixture-Bag Generator (the test harness)
- A generator built on **`rosbags`'s write capability** that emits tiny bags in **all three
  formats**: ROS 1 (`.bag`), ROS 2 sqlite3, and ROS 2 MCAP (PRD §6).
- These fixtures are the shared substrate for every later phase's tests; they are what makes
  no-ROS CI possible.
- Fixture content should be **forward-looking**: include topics/messages rich enough to later
  exercise nested scalar flattening, array/`LIST` handling, and `header.stamp` time extraction
  (Phases 2–3) — even though Phase 1 only asserts the bags are produced and re-openable.

### Claude's Discretion
- **Build backend** (hatchling / setuptools / pdm-backend / etc.) — not pinned by the PRD.
- **Monorepo wiring** (uv workspace vs. plain editable installs vs. a root dev install) — pick
  the simplest approach that satisfies "both packages import as installed packages".
- **CI provider config** — GitHub Actions is implied by convention; exact matrix/steps are open.
- **Test layout**, `ruff` rule selection, and the exact message types / topic names inside the
  fixture bags.
- **CLI library**: PRD §4.3 says "`typer` or `click`"; ROADMAP plan 07-01 leans **`typer`**.
  Whether Phase 1 wires a runnable `bagq --help` or just scaffolds an importable package with a
  placeholder entry point is open — confirm during research/planning.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & v1 Scope
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` — the design spec. For Phase 1 the
  load-bearing sections are §3.1 (monorepo of small packages), §3.2 (offline/live split), §3.3
  (key principles: offline never imports ROS, swappable backend, API-first/CLI–GUI parity),
  §4.3 (v1 dependency set), and §6 (testing strategy — `rosbags`-written fixture bags, no ROS
  in CI, ≥80% coverage).

### Requirements / Definition of Done
- `.planning/REQUIREMENTS.md` — Phase 1 carries the **Definition of Done (v1)** rather than
  specific REQ-IDs: test suite runs with no ROS install using `rosbags` fixture bags
  (ROS1+ROS2+MCAP); `bagq` installs via `pip`; offline packages import without `rclpy`. The full
  v1 REQ set (READ/INSP/QURY/OUT/CLI) informs how the scaffold should be shaped for later phases.

### Roadmap
- `.planning/ROADMAP.md` — Phase 1 section, the 3 success criteria, and the suggested 3-plan
  split (01-01 layout+pyproject, 01-02 dev tooling, 01-03 fixture generator).

### Project Constraints
- `CLAUDE.md` — tech stack (Python ≥ 3.10; `rosbags`/`duckdb`/`sqlglot`/`pyarrow`/`matplotlib`/
  `typer`|`click`; no ROS for offline), compatibility (read ROS1 + ROS2 sqlite3 + MCAP),
  portability (offline tools run anywhere incl. CI with no ROS; tests use `rosbags` fixtures),
  interop (emit standard formats; never rebuild viewers).
</canonical_refs>

<specifics>
## Specific Ideas

- ROADMAP suggests a **3-plan split** for this phase:
  - **01-01**: Monorepo layout + `pyproject.toml` for `rosbagger-core` and `bagq`.
  - **01-02**: Dev tooling — `ruff` (format/lint), `pytest`, CI workflow.
  - **01-03**: Fixture-bag generator (`rosbags` writes ROS1/ROS2/MCAP).
- The fixture generator is the single most reused artifact in the project — every later phase's
  tests depend on it. Treat its API/output paths as a small internal contract worth getting
  right early (deterministic output, a stable location/fixture for pytest to consume).
- A guard test that **offline packages import with no ROS available** directly proves Success
  Criterion #2's spirit and protects the architectural invariant for the life of the project.
- `duckdb` is not yet installed locally (PROJECT.md) — installing the dependency set is part of
  the scaffold.
</specifics>

<deferred>
## Deferred Ideas

These are explicitly later phases / out of scope for Phase 1:

- **Reader** (`BagReader` + `rosbags` `AnyReader` impl) — Phase 2.
- **Message→table schema** (sanitized names, dotted/quoted columns, `LIST`/`STRUCT`, time
  columns, lazy blobs) — Phase 3.
- **Inspect** (`bagq info` / `bagq tables`) — Phase 4.
- **Query engine** (`QueryBackend` + DuckDB, `sqlglot` topic resolution) — Phase 5.
- **Output & export** (stdout table, CSV, Parquet, `--plot`) — Phase 6.
- **CLI wiring + teaching errors** — Phase 7.
- **Packaging polish, docs, v0.1 release** — Phase 8.
- **Post-v1 modules** — `rosbagger-tf`, `-record`, `-replay`, `-gui`, `-edit`, events sidecar.
- **Fast-follows** — alias pack (`vx` → `"twist.twist.linear.x"`), projection pushdown,
  `rosbag2_py` reader backend.
</deferred>

---

*Phase: 01-scaffold-test-harness*
*Context gathered: 2026-05-21 via PRD Express Path*
