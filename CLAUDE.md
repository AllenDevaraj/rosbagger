<!-- GSD:project-start source:PROJECT.md -->
## Project

**rosbagger**

rosbagger is a modular monorepo of ROS bag tooling spanning the whole bag lifecycle — record, inspect, query, debug, replay. Its first deliverable, `bagq`, is a universal "DuckDB-for-bags" SQL CLI that queries ROS 1 / ROS 2 / MCAP bags (no ROS install required) and exports CSV / Parquet / plots — replacing the throwaway scripts every robotics team rewrites. It's for robotics engineers across any ROS domain (AVs, drones, AMRs, humanoids, manipulation, research).

**Core Value:** Query and understand the data inside any ROS bag from one command — without writing a one-off script and without needing ROS installed.

### Constraints

- **Tech stack**: Python ≥ 3.10 — `rosbags`, `duckdb` (behind a swappable `QueryBackend` seam), `sqlglot`, `pyarrow`, `matplotlib`, `typer`/`click`. No ROS dependency for offline modules.
- **Compatibility**: must read ROS 1 and ROS 2 (sqlite3 + mcap) bags.
- **Portability**: offline tools run anywhere, CI included, with no ROS install — tests use `rosbags`-written fixture bags.
- **Interop**: emit standard formats (Parquet / CSV / MCAP); never rebuild existing viewers.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
