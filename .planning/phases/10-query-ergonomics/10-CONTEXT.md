# Phase 10: Query Ergonomics - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 10 makes `bagq` SQL queries **terser** and **leaner** by adding two ergonomics features to the EXISTING query pipeline (`rosbagger_core.backend.query.query` → `resolve` → `schema` → `DuckDBBackend`), surfaced through the existing `bagq query` command — **no new command, no new engine**:

- **QURY-08 — Alias pack:** short, message-type-aware shortcuts in user SQL expand to full dotted columns (canonical example `vx` → `"twist.twist.linear.x"` on an Odometry topic).
- **QURY-09 — Column projection pushdown:** a query materializes only the columns it references (plus the standard time columns), instead of building every non-heavy column of each referenced topic.

Both are optimizations/sugar over already-shipped behavior (Phases 3 + 5).

**In scope:** alias expansion in user SQL; loading/materializing only referenced columns; a verifiable single-column query that does not materialize unreferenced/heavy columns; the thin `bagq query` surface for both.

**Out of scope (own phases / deferred):** user-defined / config-file alias packs; row-level predicate pushdown (filtering rows before Arrow build); DuckDB-side view/macro layers; any change to the swappable-`QueryBackend` contract; new output formats. New capabilities belong in their own phase.

</domain>

<decisions>
## Implementation Decisions

> **`--auto` mode:** every decision below is the recommended default, auto-selected without user prompts. Each is grounded in the locked sqlglot-AST seam and the existing heavy-blob `include=` column filter.

### Alias resolution (QURY-08)

- **D-01 — Mechanism: sqlglot AST rewrite, NOT string substitution or DuckDB views.** Expand aliases by walking the parsed `sqlglot` tree and replacing each matching `exp.Column` with the full dotted column as a *quoted* identifier, then regenerate SQL from the rewritten tree. Reuses the locked sqlglot AST seam (`backend/resolve.py`) and preserves the trust boundary (no raw string interpolation; threat T-05-04). A regex was explicitly rejected in Phase 5 ("Don't Hand-Roll" — breaks on CTE/JOIN/quoting); the same reasoning applies to rewriting.
- **D-02 — Pipeline placement: rewrite BEFORE table/column resolution.** Order is `parse → expand aliases → (referenced_tables / referenced_columns / has_star) on the rewritten tree → load → execute`. Mandatory so projection pushdown (D-06) and the existing heavy-blob `include` logic see the EXPANDED dotted names. The orchestrator forwards the rewritten SQL to `backend.execute`.

### Alias pack scope & contents (QURY-08)

- **D-03 — Keyed by message type, applied per referenced topic.** The pack is a built-in mapping from msgtype family → {alias → dotted column}, e.g. `nav_msgs/msg/Odometry`: `vx`→`"twist.twist.linear.x"`; `geometry_msgs/msg/Twist`(+`TwistStamped`): `vx`→`"twist.linear.x"`/`"linear.x"`; `sensor_msgs/msg/Imu`: angular-velocity / linear-acceleration shortcuts. `topic_to_msgtype` already exists in the orchestrator. A flat global pack is **rejected**: the canonical `vx → "twist.twist.linear.x"` is the Odometry path while Twist's is shallower — one global mapping would be wrong for at least one common type.
- **D-04 — Expand only when the target column EXISTS in the referenced topic's schema.** An alias that doesn't resolve against the FROM topic's `TableSchema` is left untouched (DuckDB then raises the normal teaching error). Safe no-op on unrelated topics.
- **D-05 — v1 ships a built-in pack only (not user-extensible).** Curated shortcuts for common geometry / nav / sensor types. User-defined alias packs (config file / CLI) are a deferred idea.

### Column projection pushdown (QURY-09)

- **D-06 — Reuse the schema filter seam; add a projection (restrict) set alongside the heavy-blob `include` set.** Compute the referenced-column set from the (alias-expanded) tree; per topic, materialize only columns whose dotted name is in that set. Generalize `TableSchema.arrow_schema` / `build_arrow_table` / `flatten_message` to accept the projection set (mirror the existing `include=` filter rather than a parallel path). `flatten_message` must SKIP `reduce(getattr, …)` for non-projected columns so unreferenced values are never read off the message — that skipped read is the actual "pushdown."
- **D-07 — The four standard columns (`t`/`t_ns`/`stamp`/`topic`) are ALWAYS materialized.** Cheap, and they anchor ordering, `--plot` (vs `t_ns`), and time-joins; a `SELECT vx` must still be plottable. Heavy blobs keep today's rule (materialized only when referenced or under a star).
- **D-08 — `SELECT *` (incl. qualified `t.*`) disables pushdown for that topic.** A star means "everything," so it materializes all non-heavy columns exactly as today. Reuses the existing `has_star` signal.

### Column attribution & verification (QURY-09 / SC3)

- **D-09 — Over-include on JOIN ambiguity (never under-include).** `referenced_columns` is a flat, unqualified name set. Apply it to each referenced topic independently — keep any column whose dotted name is in the set. A name present in two joined topics is materialized in both (safe over-inclusion); nothing a query needs is ever dropped. Table-qualified projection is a deferred refinement.
- **D-10 — Prove SC3 by asserting the materialized Arrow schema.** A ROS-free fixture-bag test asserts that a single-column query's loaded `pyarrow.Table` carries exactly the projected column ∪ the four standard columns, and excludes unreferenced + heavy columns. This is the verifiable, deterministic proof SC3 demands (project norm: `rosbags`-written fixtures, no ROS install).

### `bagq query` surface

- **D-11 — Alias expansion is ON by default with a `--no-alias` escape hatch; projection pushdown is always on and transparent.** Aliases surface through the existing `query` command (a thin pass-through to `rosbagger_core`); `--no-alias` disables expansion if it ever surprises a user (rarely needed given D-04's existence-gating). Projection pushdown changes no results — only what is loaded — so it needs no flag.

### Claude's Discretion
The exact alias-pack contents (which msgtypes / shortcuts ship), function and parameter names, and module placement (extend `resolve.py` vs a new `backend/alias.py`) are left to research + planning. The offline-import invariant and the trusted-SQL boundary are HARD constraints on all of them.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition & requirements
- `.planning/ROADMAP.md` § "Phase 10: Query Ergonomics" — goal + the three success criteria (alias resolves shortcuts; projection loads only referenced columns; single-column query verifiably doesn't materialize unreferenced/heavy columns).
- `.planning/REQUIREMENTS.md` § "Query ergonomics" — QURY-08 (alias pack) and QURY-09 (projection pushdown).
- `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §7 "Open questions / fast-follows" — the canonical design intent for both features (alias pack "for common message types"; projection pushdown "load only referenced columns, not whole topics").

### Code seams to extend (read before planning)
- `packages/rosbagger-core/src/rosbagger_core/backend/resolve.py` — the locked sqlglot AST seam (`parse`/`referenced_tables_in`/`referenced_columns`/`has_star`). Alias rewrite extends this; projection consumes `referenced_columns`.
- `packages/rosbagger-core/src/rosbagger_core/backend/query.py` — the orchestrator that wires parse→resolve→load→execute, owns `topic_to_msgtype`, the `include=` heavy-blob set, and the trust-boundary contract. Both features wire in here.
- `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py` — `flatten_message` / `build_arrow_table` (the materialization path projection must restrict).
- `packages/rosbagger-core/src/rosbagger_core/schema/model.py` — `TableSchema.arrow_schema(include=)` / `column_names(include=)` (the filter seam to generalize for projection).
- `packages/bagq/src/bagq/cli.py` — the `query` command (thin pass-through; `--no-alias` flag surface).

### Offline / trust constraints (hard)
- `packages/rosbagger-core/tests/test_offline_guard.py` — the offline-import invariant: `import rosbagger_core` / `rosbagger_core.backend` must not pull duckdb/pyarrow/sqlglot eagerly. Alias + projection code obeys the same lazy-import discipline (`sqlglot` top-level import is allowed in `resolve.py` — it is pure-Python, not a ROS module).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/resolve.py` (`parse`, `referenced_columns`, `has_star`): already returns the exact dotted column names the schema uses (a quoted dotted column `"linear.x"` → `exp.Column.name == "linear.x"`). Projection pushdown consumes `referenced_columns` directly; alias rewrite adds one tree transform alongside these.
- `backend/query.py` `_topic_table_maps` → `topic_to_msgtype`: the per-topic message type the alias pack must key on, already computed before any load.
- `schema/model.py` `arrow_schema(include=)` / `column_names(include=)` and `flatten.py` `build_arrow_table(include=)` / `flatten_message(include=)`: a proven, declared-order column-filter seam (currently for heavy blobs) to generalize into projection.
- The heavy-blob `include` machinery + `has_star` already implement "materialize a subset of columns, but everything under `SELECT *`" — projection pushdown is the same shape applied to all columns.

### Established Patterns
- **sqlglot AST, never regex** for SQL understanding/rewriting (`resolve.py` docstring; threat model). Alias expansion MUST be an AST transform.
- **Trusted-SQL boundary:** user SQL is forwarded to `execute` as-is; the orchestrator interpolates no identifiers. Alias rewrite stays inside sqlglot (quoted identifiers via the AST) so it introduces no injection surface.
- **Offline-import invariant:** the heavy stack (duckdb/pyarrow/sqlglot) is imported lazily inside functions; module tops stay stdlib-light. New code follows suit.
- **Lazy per-topic load** via `reader.read(topics={topic})` then `build_arrow_table`: projection narrows what each load materializes; the connection-filtered topic load is unchanged.
- **Schema is value-independent / declared-order**, with a unique-name invariant (WR-01) — projection filtering by name is safe and order-preserving.

### Integration Points
- Alias rewrite: a new step in `query()` between `parse` and the `referenced_*` calls; pack lookup keyed by `topic_to_msgtype`, gated on the topic's `TableSchema` column names (already built per topic).
- Projection: thread a projection set from `query()` into `build_arrow_table` / `arrow_schema` / `flatten_message`; standard columns always kept; star opts out; heavy-blob rule preserved.
- CLI: `--no-alias` boolean on `bagq query`, passed through to the orchestrator (default: aliases on).

</code_context>

<specifics>
## Specific Ideas

- Canonical alias example to support exactly: `vx` → `"twist.twist.linear.x"` (nav_msgs/Odometry). This confirms message-type-keyed expansion (Twist's own velocity is the shallower `"twist.linear.x"` / `"linear.x"`).
- SC3's "verifiable" is read as: a deterministic assertion on the materialized Arrow table's column set for a single-column query (not a benchmark) — fixture-bag, ROS-free.

</specifics>

<deferred>
## Deferred Ideas

- **User-defined / config-file alias packs** (project- or user-level custom shortcuts, CLI-registered) — v1 ships a built-in pack only; make it extensible in a later ergonomics pass.
- **Table-qualified projection** (attribute columns to a specific topic in JOINs instead of over-including) — a correctness-neutral optimization; the current rule over-includes safely.
- **Row-level / predicate pushdown** (filter rows during Arrow build, e.g. `WHERE` on `t_ns`) — a different, larger optimization; out of scope for QURY-09's column projection.
- **DuckDB view/macro alias layer** — rejected for v1 (pushes aliasing past the trusted seam and can't inform topic/column loading); noted only as a considered-and-declined alternative.

</deferred>

---

*Phase: 10-query-ergonomics*
*Context gathered: 2026-05-22*
