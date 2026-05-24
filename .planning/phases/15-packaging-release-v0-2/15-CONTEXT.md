# Phase 15: Packaging & Release v0.2 - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes all five workspace packages **git/path-installable** into an
external project's virtualenv and stamps a **coherent v0.2.0 release** across
the monorepo. It is an infrastructure phase (like Phase 8) — no new runtime
feature, no new REQ-ID.

**Delivers:**
- Each package (`rosbagger-core`, `bagq`, `rosbagger-record`, `rosbagger-replay`,
  `rosbagger-gui`) installs cleanly into a fresh external venv via
  `pip`/`uv pip install` from a `git+…#subdirectory=…` URL or a local path,
  with its inter-package dependencies resolving from a published version spec
  rather than the workspace-only `[tool.uv.sources]` table.
- A documented **one-line meta recipe** that installs the whole set together.
- A `live` optional-dependency extra on `rosbagger-gui` that pulls in the
  rclpy-backed record/replay packages on demand.
- All five packages versioned `0.2.0` with compatible inter-package pins.
- A central `INSTALL.md` covering every install path plus an external-venv
  proof recipe.

**Does NOT deliver:** publishing to PyPI / any package index, CI release
automation, conda packaging, Docker images, or new query/GUI functionality.

</domain>

<decisions>
## Implementation Decisions

### Core / inter-package resolution
- **D-01 (One-line meta recipe + source-agnostic packages):** Packages stay
  *source-agnostic* — their `[project] dependencies` reference sibling packages
  by **version spec only** (e.g. `rosbagger-core>=0.2,<0.3`), never by a path or
  git URL baked into the wheel. The crux this resolves: `[tool.uv.sources]
  … workspace = true` is **dev-only metadata that is NOT written into built
  wheels**, so an external consumer installing one package can't resolve the bare
  `rosbagger-core` dependency from any index (we publish to none).
  - Provide **one documented meta command** that installs the whole set from git
    together (all subdirectory URLs in a single `uv pip install`/`pip install`
    invocation), so the sibling specs resolve against the packages installed in
    the same transaction.
  - Also provide **per-package `git+…#subdirectory=…` snippets** for consumers
    who want just one or two packages (they install the needed siblings in the
    same command).

### GUI live dependencies
- **D-02 (`live` extra on rosbagger-gui):** Add
  `[project.optional-dependencies] live = ["rosbagger-record", "rosbagger-replay"]`
  to `rosbagger-gui`. Base install stays offline-only (core query/inspect/tf
  panels); `rosbagger-gui[live]` adds the rclpy-backed record/replay panels.
  Keeps the offline-import invariant intact — base GUI never pulls rclpy.

### Versioning
- **D-03 (All → 0.2.0, compatible pins):** Bump all five packages to `0.2.0`.
  Inter-package dependencies use a compatible-release pin `>=0.2,<0.3` so a
  0.2.x sibling satisfies the spec but a future 0.3 breaking line does not.

### Docs
- **D-04 (Central INSTALL.md):** One top-level `INSTALL.md` holds every install
  path — the one-line meta recipe, per-package git+subdirectory snippets, local
  path-install snippets, the external-venv **proof recipe** (fresh venv →
  install → import/CLI smoke check), and the "live GUI panels need
  `rosbagger-gui[live]`" note.

### Claude's Discretion
- Exact wording/structure of INSTALL.md sections.
- Whether the external-venv proof recipe is also encoded as a test/CI check vs.
  documented-only (lean toward a scripted check if cheap).
- Whether to add a top-level `make`/script target wrapping the meta recipe.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap / phase definition
- `.planning/ROADMAP.md` §"Phase 15: Packaging & Release v0.2" (line ~401) —
  Goal, depends-on-Phase-14, 5 success criteria, DoD as infrastructure phase.

### Package manifests (the files this phase edits)
- `pyproject.toml` (repo root) — `[tool.uv.workspace]` member list and the
  `[tool.uv.sources] … workspace = true` table that does NOT ship in wheels
  (the resolution gap D-01 addresses).
- `packages/rosbagger-core/pyproject.toml` — base offline library; nothing
  depends inward on it except via spec.
- `packages/bagq/pyproject.toml` — CLI; depends on rosbagger-core.
- `packages/rosbagger-record/pyproject.toml` — live (rclpy) package.
- `packages/rosbagger-replay/pyproject.toml` — live (rclpy) package.
- `packages/rosbagger-gui/pyproject.toml` — Textual TUI; gains the `live` extra.

No external specs beyond the above — requirements fully captured in decisions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Established Patterns
- **uv workspace, src-layout, hatchling backend.** All five packages already
  build as wheels via `uv build`; console scripts (`bagq`, `rosbagger-gui`, …)
  are declared in `[project.scripts]`.
- **`[tool.uv.sources] … workspace = true`** wires inter-package deps for local
  dev. This is the wheel-resolution gap: that table is stripped from built
  artifacts, so external installs need version-spec deps (D-01) to resolve.
- **Offline-import invariant** (enforced by the offline guard test): rclpy is
  lazy-imported inside method bodies; base packages import ROS-free. The `live`
  extra (D-02) must not break this — base `rosbagger-gui` stays rclpy-free.

### Integration Points
- Root `[tool.uv.workspace]` member list — versions/specs must stay coherent
  with per-package manifests after the 0.2.0 bump.
- The offline guard test must remain green after adding the `live` extra.

### Host / tooling constraints (carry into execution)
- Run tests/lint with `PYTHONPATH=""` prefix on this box (ROS is sourced
  globally and breaks bare `uv run pytest`); invoke ruff as `uv run ruff`.

</code_context>

<specifics>
## Specific Ideas

- The external-venv proof recipe should genuinely create a throwaway venv,
  install from git+subdirectory (or local path), and run a CLI/import smoke
  check — proving the wheel-resolution gap is actually closed, not assumed.

</specifics>

<deferred>
## Deferred Ideas

- **PyPI / index publishing** — explicitly out of scope for v0.2; git/path
  install only. A future release phase if/when public distribution is wanted.
- **CI release automation** (tag → build → attach artifacts) — not this phase.
- **Docker images / conda packaging** — out of scope.

</deferred>

---

*Phase: 15-Packaging & Release v0.2*
*Context gathered: 2026-05-24*
