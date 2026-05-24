# Phase 15: Packaging & Release v0.2 — Discussion Log

**Date:** 2026-05-24
**Mode:** discuss-phase (default, research-before-questions enabled)

This log records the questions asked, options presented, and the user's
selections during phase context-gathering. The distilled decisions live in
`15-CONTEXT.md`; this file preserves the reasoning trail.

---

## Pre-discussion gates

- **Distribution model** (asked during plan-phase hand-off): user chose
  **"Git/path install only"** — no PyPI/index publish for v0.2.
- **Plan-phase context gate:** user chose **"Run discuss-phase first"**,
  deferring planning until context was captured.
- **Research:** user chose **"Research first"** — research runs automatically
  at plan-phase time.
- **Discuss areas:** user selected **all four** gray areas below.

---

## Area 1 — Core / inter-package resolution

**Question:** How should an external consumer's install resolve the bare
inter-package dependency (e.g. `rosbagger-core`) when `[tool.uv.sources]
workspace = true` is dev-only metadata that is not shipped in built wheels?

**Options presented:**
- **One-line meta recipe** *(selected)* — packages stay source-agnostic
  (version-spec deps only); ship one documented command that installs the whole
  set from git in a single transaction, plus per-package git+subdirectory
  snippets.
- Bake git URLs into each package's dependencies — rejected: couples wheels to a
  specific git host/ref, brittle.
- Vendor/relative-path sources in wheels — rejected: not portable for external
  consumers.

**Selected:** One-line meta recipe → **D-01**.

---

## Area 2 — GUI live dependencies

**Question:** How should the GUI pull in the rclpy-backed record/replay packages
without breaking the offline-import invariant?

**Options presented:**
- **Add `live` extra** *(selected)* —
  `[project.optional-dependencies] live = ["rosbagger-record","rosbagger-replay"]`;
  base install stays offline.
- Hard dependency on record/replay — rejected: forces rclpy on every GUI install,
  breaks offline portability.

**Selected:** `live` extra → **D-02**.

---

## Area 3 — Versioning

**Question:** What version scheme across the five packages for the v0.2 cut?

**Options presented:**
- **All → 0.2.0, compatible pins** *(selected)* — every package `0.2.0`;
  inter-package deps pinned `>=0.2,<0.3`.
- Independent per-package versions — rejected: harder to reason about a coherent
  release; overkill pre-1.0.

**Selected:** All → 0.2.0 with compatible pins → **D-03**.

---

## Area 4 — Docs

**Question:** Where do install instructions live?

**Options presented:**
- **Central INSTALL.md** *(selected)* — one top-level doc: meta recipe,
  per-package snippets, path-install, external-venv proof recipe, live-extra note.
- Per-package READMEs only — rejected: duplicated, drifts, no single proof recipe.

**Selected:** Central INSTALL.md → **D-04**.

---

## Outcome

All four selected areas resolved on first pass; user signaled ready for context.
No scope creep, no folded todos, no deferred-todo review. Deferred ideas (PyPI
publish, CI release automation, Docker/conda) noted in `15-CONTEXT.md`.
