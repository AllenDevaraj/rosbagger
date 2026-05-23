# Phase 10: Query Ergonomics - Research

**Researched:** 2026-05-22
**Domain:** sqlglot AST rewriting + pyarrow column projection over the existing `bagq` query pipeline
**Confidence:** HIGH (every load-bearing claim verified in-session against the pinned sqlglot 30.8.0 and real `rosbags`-built fixture schemas)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Alias resolution (QURY-08)**
- **D-01 — Mechanism: sqlglot AST rewrite, NOT string substitution or DuckDB views.** Expand aliases by walking the parsed `sqlglot` tree and replacing each matching `exp.Column` with the full dotted column as a *quoted* identifier, then regenerate SQL from the rewritten tree. Reuses the locked sqlglot AST seam (`backend/resolve.py`) and preserves the trust boundary (no raw string interpolation; threat T-05-04). A regex was explicitly rejected in Phase 5 ("Don't Hand-Roll" — breaks on CTE/JOIN/quoting); the same reasoning applies to rewriting.
- **D-02 — Pipeline placement: rewrite BEFORE table/column resolution.** Order is `parse → expand aliases → (referenced_tables / referenced_columns / has_star) on the rewritten tree → load → execute`. Mandatory so projection pushdown (D-06) and the existing heavy-blob `include` logic see the EXPANDED dotted names. The orchestrator forwards the rewritten SQL to `backend.execute`.

**Alias pack scope & contents (QURY-08)**
- **D-03 — Keyed by message type, applied per referenced topic.** The pack is a built-in mapping from msgtype family → {alias → dotted column}, e.g. `nav_msgs/msg/Odometry`: `vx`→`"twist.twist.linear.x"`; `geometry_msgs/msg/Twist`(+`TwistStamped`): `vx`→`"twist.linear.x"`/`"linear.x"`; `sensor_msgs/msg/Imu`: angular-velocity / linear-acceleration shortcuts. `topic_to_msgtype` already exists in the orchestrator. A flat global pack is **rejected**.
- **D-04 — Expand only when the target column EXISTS in the referenced topic's schema.** An alias that doesn't resolve against the FROM topic's `TableSchema` is left untouched (DuckDB then raises the normal teaching error). Safe no-op on unrelated topics.
- **D-05 — v1 ships a built-in pack only (not user-extensible).** Curated shortcuts for common geometry / nav / sensor types. User-defined alias packs (config file / CLI) are a deferred idea.

**Column projection pushdown (QURY-09)**
- **D-06 — Reuse the schema filter seam; add a projection (restrict) set alongside the heavy-blob `include` set.** Compute the referenced-column set from the (alias-expanded) tree; per topic, materialize only columns whose dotted name is in that set. Generalize `TableSchema.arrow_schema` / `build_arrow_table` / `flatten_message` to accept the projection set. `flatten_message` must SKIP `reduce(getattr, …)` for non-projected columns so unreferenced values are never read off the message — that skipped read is the actual "pushdown."
- **D-07 — The four standard columns (`t`/`t_ns`/`stamp`/`topic`) are ALWAYS materialized.** Heavy blobs keep today's rule (materialized only when referenced or under a star).
- **D-08 — `SELECT *` (incl. qualified `t.*`) disables pushdown for that topic.** Reuses the existing `has_star` signal.

**Column attribution & verification (QURY-09 / SC3)**
- **D-09 — Over-include on JOIN ambiguity (never under-include).** `referenced_columns` is a flat, unqualified name set. Apply it to each referenced topic independently. Table-qualified projection is a deferred refinement.
- **D-10 — Prove SC3 by asserting the materialized Arrow schema.** A ROS-free fixture-bag test asserts that a single-column query's loaded `pyarrow.Table` carries exactly the projected column ∪ the four standard columns, and excludes unreferenced + heavy columns.

**`bagq query` surface**
- **D-11 — Alias expansion is ON by default with a `--no-alias` escape hatch; projection pushdown is always on and transparent.** Projection pushdown changes no results — only what is loaded — so it needs no flag.

### Claude's Discretion
The exact alias-pack contents (which msgtypes / shortcuts ship), function and parameter names, and module placement (extend `resolve.py` vs a new `backend/alias.py`) are left to research + planning. The offline-import invariant and the trusted-SQL boundary are HARD constraints on all of them.

### Deferred Ideas (OUT OF SCOPE)
- **User-defined / config-file alias packs** — v1 ships a built-in pack only.
- **Table-qualified projection** (attribute columns to a specific topic in JOINs instead of over-including) — current rule over-includes safely.
- **Row-level / predicate pushdown** (filter rows during Arrow build, e.g. `WHERE` on `t_ns`) — different, larger optimization; out of scope.
- **DuckDB view/macro alias layer** — rejected for v1 (pushes aliasing past the trusted seam, can't inform topic/column loading).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QURY-08 | Alias pack (`vx` → `"twist.twist.linear.x"`) for common message types | `## Architecture Patterns` Pattern 1 (sqlglot rewrite, VERIFIED); `## Code Examples` ex. 1–3; `## Alias Pack v1 Contents` (verified dotted paths per msgtype); pipeline placement in Pattern 4 |
| QURY-09 | Column projection pushdown (load only referenced columns) | `## Architecture Patterns` Pattern 2 (restrict-set threading); `## Code Examples` ex. 4–5; `## Don't Hand-Roll`; SC3 proof in `## Validation Architecture` |
</phase_requirements>

## Summary

Phase 10 adds two pure-Python, offline-safe optimizations to the **already-shipped** `bagq` query pipeline. Both ride on seams that Phases 3 and 5 deliberately built: the `sqlglot` AST resolver (`backend/resolve.py`) and the declared-order, name-keyed column filter (`TableSchema.arrow_schema(include=)` / `build_arrow_table(include=)` / `flatten_message(include=)`). No new command, no new engine, no new dependency.

**Alias expansion (QURY-08)** is a single `tree.transform()` over the parsed SQL that replaces each matching short `exp.Column` with a quoted dotted `exp.column(target, quoted=True)`, gated on the target existing in the referenced topic's `TableSchema`. The mechanics are fully verified against the pinned **sqlglot 30.8.0**: `transform` returns a copy (no mutate-while-walking hazard), the rewrite reaches every clause (SELECT/WHERE/GROUP BY/HAVING/ORDER BY/function args), already-dotted columns parse to a `.name` containing the dots (so they never collide with short aliases), and qualified `o.vx` round-trips to `"o"."twist.twist.linear.x"`. The expansion must run BEFORE `referenced_columns`/`has_star` (D-02) so projection sees the dotted names.

**Projection pushdown (QURY-09)** generalizes the existing heavy-blob `include=` filter into a second, orthogonal `restrict=` set: the referenced (alias-expanded) column names, unioned with the four always-present standard columns, applied per topic. `flatten_message` skips `reduce(getattr, …)` for any column not in the restrict set — that *skipped read* is the literal pushdown. A `SELECT *` (or `t.*`) sets `restrict=None`, restoring today's full-materialization behavior. The only production caller of these three functions is `backend/query.py:184`; `inspect.collect_table_schemas` does NOT call them, so a default-`None` `restrict=` parameter leaves `bagq tables` completely unaffected.

**SC3** is a deterministic, ROS-free fixture-bag assertion (D-10): I proved end-to-end that `SELECT vx FROM cmd_vel` over a `rosbags`-written ROS2 bag materializes exactly `{linear.x, t, t_ns, stamp, topic}` and excludes `angular.z`/`linear.y` — no DuckDB and no spy needed; the `pyarrow.Table.column_names` assertion suffices.

**Primary recommendation:** Put the alias pack + rewrite in a new stdlib-light `backend/alias.py` (keeps `resolve.py` single-purpose); add a `restrict: set[str] | None = None` parameter to `arrow_schema` / `column_names` / `build_arrow_table` / `flatten_message` composed with the existing `include=`; wire both into `backend/query.py` between `parse` and the `referenced_*` calls; thread a `--no-alias` boolean through `bagq query`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Parse user SQL → AST | `backend/resolve.py` (`parse`) | — | Already the single parse seam; reused unchanged |
| Alias lookup (msgtype → {alias→dotted}) | new `backend/alias.py` (the pack data + rewrite fn) | — | Pure data + one AST transform; stdlib + sqlglot only, offline-safe |
| Alias rewrite orchestration (per-topic gating) | `backend/query.py` (`query`) | `backend/alias.py` | Orchestrator owns `topic_to_msgtype` + per-topic `TableSchema`; alias.py is a pure helper it calls |
| Referenced-column / star analysis | `backend/resolve.py` (`referenced_columns`/`has_star`) | — | Runs on the REWRITTEN tree (D-02); no change to the functions themselves |
| Projection (restrict) filter | `schema/model.py` + `schema/flatten.py` | — | Generalizes the existing `include=` filter; the skipped `reduce(getattr,...)` is the pushdown |
| Projection threading | `backend/query.py` (`query`) | — | Computes the restrict set from referenced cols + standard cols, passes to `build_arrow_table` |
| CLI surface (`--no-alias`) | `bagq/cli.py` (`query`) | — | Thin pass-through; one boolean option forwarded to `run_query` |

**Note:** Every responsibility lands in the *offline* tier (`rosbagger_core` + `bagq`). No live/ROS tier is touched. The `QueryBackend` contract (`backend/base.py`) is **not** modified — both features sit upstream of `backend.execute`.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlglot` | **30.8.0** (pinned `>=27,<31`) | Parse + transform + regenerate SQL for alias rewrite | Already the locked SQL-understanding dependency (`resolve.py`, `identifiers.py`); pure-Python, offline-safe at module top |
| `pyarrow` | `>=18` | The `restrict`-filtered Arrow build | Already the materialization layer; projection narrows what it builds |
| `rosbags` | `>=0.11,<0.12` | Typestore → `TableSchema` (drives the existence-gate + the dotted column vocabulary) | Already the reader/typestore source |

**No new dependency is required.** Both features are built entirely from the existing stack. `duckdb` (`>=1.4,<2`) is untouched and stays lazily imported.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (stdlib) `functools.reduce` | — | Already used in `flatten_message` for the attribute walk | The projection's skipped-read happens by simply not iterating a non-restricted column |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tree.transform(fn)` | `for col in tree.find_all(exp.Column): col.replace(...)` | `find_all` + in-place `replace` mutates while walking the same tree — fragile and order-dependent. `transform` returns a clean copy (VERIFIED original unchanged). Use `transform`. |
| New `backend/alias.py` module | Extend `backend/resolve.py` | Both are valid (D's discretion). A new module keeps `resolve.py` single-purpose ("what does this SQL touch?") and isolates the pack data; recommended. Either obeys the offline rule (both pure sqlglot). |
| Add `restrict=` param to existing fns | Parallel `build_arrow_table_projected(...)` path | A parallel path duplicates the heavy-blob/standard-column logic and risks drift. Generalizing the one filter (composed with `include=`) is the locked D-06 choice. |

**Installation:** No install step. No `pyproject.toml` / `uv.lock` change. (Verified: `sqlglot 30.8.0`, `requires-python >=3.10`, deps `rosbags>=0.11,<0.12 / duckdb>=1.4,<2 / sqlglot>=27,<31 / pyarrow>=18` all already present.)

**Version verification:** `sqlglot.__version__ == "30.8.0"` confirmed in-session via `.venv/bin/python -c "import sqlglot; print(sqlglot.__version__)"`. The `uv.lock` pin (line 1330) and core `pyproject.toml` constraint (line 10) agree.

## Package Legitimacy Audit

> Phase 10 installs **no new packages**. All three libraries it uses are already locked dependencies of `rosbagger-core`, present in `uv.lock`, and exercised by the 274-test suite. No slopcheck/registry verification needed — nothing new is added to the dependency graph.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `sqlglot` | PyPI (already locked) | mature | — | github.com/tobymao/sqlglot | n/a (no install) | Already a dependency — no change |
| `pyarrow` | PyPI (already locked) | mature | — | github.com/apache/arrow | n/a (no install) | Already a dependency — no change |
| `rosbags` | PyPI (already locked) | mature | — | gitlab.com/ternaris/rosbags | n/a (no install) | Already a dependency — no change |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                    bagq query "<SQL>" BAG... [--no-alias]
                                  │
                                  ▼
                  ┌──────────────────────────────────┐
                  │  bagq/cli.py  query()             │  thin pass-through:
                  │  forwards alias_enabled boolean   │  --no-alias -> alias=False
                  └──────────────────┬─────────────────┘
                                     ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  backend/query.py  query(sql, reader, *, alias=True, backend=) │
        │                                                                 │
        │   1. tree = parse(sql)                  ← resolve.py (unchanged) │
        │   2. topic_to_msgtype + per-topic TableSchema  (built early)    │
        │      ┌── if alias: ─────────────────────────────────────────┐  │
        │   3. │   tree = expand_aliases(tree, topic_to_msgtype,       │  │
        │      │            schemas_by_table)   ← NEW backend/alias.py  │  │
        │      │       • find each unqualified exp.Column               │  │
        │      │       • look up alias in the topic's pack (by msgtype) │  │
        │      │       • EXISTENCE-GATE: target ∈ TableSchema names      │  │
        │      │       • replace w/ exp.column(target, quoted=True)     │  │
        │      └──────────────────────────────────────────────────────┘  │
        │   4. tables = referenced_tables_in(tree)   ┐ run on the          │
        │      columns = referenced_columns(tree)    ├ REWRITTEN tree      │
        │      star    = has_star(tree)              ┘ (D-02)              │
        │   5. per referenced topic:                                      │
        │        restrict = None if star else (columns & schema_names)|STD│
        │        include  = heavy if star else (heavy & columns)          │
        │        arrow = build_arrow_table(msgs, schema,                  │
        │                    include=include, restrict=restrict)  ← D-06   │
        │   6. backend.execute(tree.sql("duckdb"))   trusted SQL forwarded │
        └───────────────────────────────┬────────────────────────────────┘
                                         ▼
              ┌─────────────────────────────────────────────────┐
              │ schema/flatten.py build_arrow_table /            │
              │   flatten_message  (restrict= filter)            │
              │   • standard cols (t/t_ns/stamp/topic) ALWAYS    │
              │   • data col kept iff name ∈ restrict (or None)  │
              │   • SKIP reduce(getattr,...) for dropped cols ←──┼─ the pushdown
              │   • heavy blob still gated by include=           │
              └────────────────────┬─────────────────────────────┘
                                   ▼
                          pyarrow.Table (projected)
                                   │
                                   ▼
                       DuckDBBackend.execute → result Arrow
```

### Recommended Project Structure

```
packages/rosbagger-core/src/rosbagger_core/
├── backend/
│   ├── alias.py        # NEW: ALIAS_PACK data + expand_aliases(tree, ...) — stdlib + sqlglot only
│   ├── resolve.py      # UNCHANGED (parse / referenced_* / has_star)
│   └── query.py        # EDIT: call expand_aliases (gated by `alias`), compute + thread restrict
├── schema/
│   ├── model.py        # EDIT: arrow_schema(include=, restrict=) / column_names(include=, restrict=)
│   └── flatten.py      # EDIT: build_arrow_table(..., restrict=) / flatten_message(..., restrict=)
packages/bagq/src/bagq/
└── cli.py              # EDIT: `query` gains `--no-alias` -> run_query(sql, reader, alias=not no_alias)
tests/
├── test_backend_alias.py   # NEW: alias rewrite unit + existence-gate + edge cases
├── test_backend_query.py   # EXTEND: alias+projection integration
├── test_schema_arrow.py    # EXTEND: restrict= filter on arrow_schema/build_arrow_table; SC3 proof
├── test_cli_query.py       # EXTEND: --no-alias surface
└── test_offline_guard.py   # EXTEND: import rosbagger_core.backend.alias pulls no heavy stack
```

### Pattern 1: Alias rewrite as a `tree.transform()` (QURY-08)

**What:** Replace each unqualified short `exp.Column` whose name is an alias in the topic's pack — and whose target exists in that topic's `TableSchema` — with a quoted dotted `exp.column(target, quoted=True)`. Use `tree.transform(fn)`; it returns a NEW tree (original untouched).

**When to use:** Once, in `query()`, after `parse` and after the per-topic schemas are known, only when `alias=True`.

**Example:**
```python
# Source: VERIFIED in-session against sqlglot 30.8.0
from sqlglot import exp

def _rewrite(node, topic_pack, schema_names):
    if isinstance(node, exp.Column) and not node.table and node.name in topic_pack:
        target = topic_pack[node.name]
        if target in schema_names:               # D-04 existence-gate
            return exp.column(target, quoted=True)  # -> "twist.twist.linear.x"
    return node

new_tree = tree.transform(lambda n: _rewrite(n, topic_pack, schema_names))
rewritten_sql = new_tree.sql(dialect="duckdb")
```
VERIFIED: `'SELECT vx FROM cmd_vel'` → `'SELECT "linear.x" FROM cmd_vel'`; reaches WHERE/GROUP BY/HAVING/ORDER BY (`'SELECT vx FROM odom WHERE vx>0 GROUP BY vx HAVING vx<10 ORDER BY vx'` → all five `vx` become `"twist.twist.linear.x"`); inside functions (`avg(vx)` → `AVG("twist.twist.linear.x")`); output alias preserved (`vx AS speed` → `"linear.x" AS speed`).

### Pattern 2: `restrict=` filter composed with `include=` (QURY-09)

**What:** A second, orthogonal name-set filter alongside the heavy-blob `include=`. A column is materialized iff:
`(NOT heavy_blob OR name ∈ include)  AND  (restrict is None OR name ∈ restrict)`.
Standard columns and heavy blobs are folded into `restrict` by the orchestrator so the four standard names are always present and the existing star/heavy semantics are preserved.

**When to use:** Always on (transparent, D-11). The orchestrator passes `restrict=None` under a star (D-08) to restore today's behavior.

**Example (the model.py filter, composed):**
```python
# Source: derived from existing model.py (arrow_schema) + D-06
def arrow_schema(self, include=None, restrict=None):
    import pyarrow as pa
    inc = include or set()
    fields = [
        pa.field(col.name, col.arrow_type, nullable=True)
        for col in self.columns
        if (not col.is_heavy_blob or col.name in inc)
        and (restrict is None or col.name in restrict)
    ]
    return pa.schema(fields)
```

### Pattern 3: `flatten_message` skips the read for dropped columns (the literal pushdown)

**What:** `flatten_message` already iterates only the columns it will emit and calls `reduce(getattr, col.ros_path, msg)` per emitted column. Adding the `restrict` predicate to its comprehension means a non-restricted column is never iterated, so its `reduce(getattr, ...)` never runs — the value is never read off the deserialized message. D-06 calls this skipped read "the actual pushdown."

**Example:**
```python
# Source: existing flatten_message + D-06 restrict predicate
def flatten_message(msg, schema, *, include=None, restrict=None):
    allowed = include or set()
    return {
        col.name: reduce(getattr, col.ros_path, msg)
        for col in schema.columns
        if _is_data_column(col)
        and (not col.is_heavy_blob or col.name in allowed)
        and (restrict is None or col.name in restrict)   # skip the read
    }
```

### Pattern 4: Pipeline ordering — rewrite BEFORE resolution (D-02)

**What:** The expansion must mutate the tree before `referenced_columns`/`has_star` run, so the projection (D-06) and heavy-blob include sets see DOTTED names. In `query()` today the order is `parse → referenced_*`; insert the alias step between them, but note the per-topic `TableSchema` (needed for the existence-gate) is currently built *later* (step 4 loop). The plan must hoist schema construction (or at least the per-topic column-name sets) earlier so the gate can run before resolution.

**Sequencing constraint for the planner:** `topic_to_msgtype` is available right after `_topic_table_maps` (no load needed). But the existence-gate needs each topic's `TableSchema.column_names` — those come from `build_table_schema(msgtype, typestore, topic=topic)`, which is O(1) metadata (no `reader.read()`), so it is cheap to build early. Build the schemas once, up front, keyed by table name; reuse them in both the alias gate AND the load loop (avoids double-building).

### Anti-Patterns to Avoid

- **Mutating the tree via `find_all` + in-place `replace` while iterating:** use `tree.transform()` which returns a copy (VERIFIED original tree unchanged after transform).
- **Rewriting against the wrong scope in a CTE / `FROM cte_alias`:** a naive whole-tree rewrite expands `vx` even in `SELECT vx FROM fast` where `fast` is a CTE (VERIFIED: it does). The existence-gate (D-04) mitigates this ONLY if you gate against the *base topic* schemas, not the CTE — see Pitfall 2. Multi-FROM/JOIN handling per D-09 = over-include safely.
- **String-substituting the alias:** forbidden by the trust boundary (T-05-04) and breaks on quoting/CTE/JOIN. AST only.
- **Importing `pyarrow`/`duckdb` at the top of `backend/alias.py`:** breaks the offline invariant. `alias.py` imports only `from sqlglot import exp` (pure-Python, offline-safe — mirrors `resolve.py`/`identifiers.py`).
- **Adding a `restrict=` filter that drops standard columns:** D-07 requires `t/t_ns/stamp/topic` always present. Fold them into the restrict set in the orchestrator (`restrict |= {"t","t_ns","stamp","topic"}`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Find/replace columns in SQL | A regex over the SQL string | `tree.transform()` + `exp.Column` matching | Phase 5 already rejected regex (CTE/JOIN/quoting break it); threat T-05-04 forbids string interpolation |
| Build a quoted dotted identifier | `f'"{target}"'` | `exp.column(target, quoted=True)` (or `exp.to_identifier(target, quoted=True)`) | f-string misses embedded-quote escaping (the `identifiers.quote_ident` lesson, T-03-06); sqlglot escapes correctly |
| A second column-materialization path | `build_arrow_table_projected(...)` | Generalize the existing `include=` filter with `restrict=` | A parallel path duplicates the standard-column + heavy-blob + unique-name logic and drifts (D-06) |
| Detect `SELECT *` | Scan the SQL text for `*` | `has_star(tree)` (existing) | Already correct for qualified `t.*` too (VERIFIED) |
| Skip reading an unreferenced field | A post-build column drop on the Arrow table | The `restrict` predicate in `flatten_message` | Post-build drop still *reads* the value (no pushdown); the comprehension predicate skips the `reduce(getattr,...)` entirely |

**Key insight:** Both features are *filters over already-built seams*, not new machinery. The single most important discipline is composing the new `restrict=` set with the existing `include=` set (rather than replacing it), and running the alias rewrite before resolution so the two filters see the dotted names.

## Common Pitfalls

### Pitfall 1: Rewriting the output alias instead of the column
**What goes wrong:** Worrying that `SELECT vx AS speed` will mangle the user's chosen output name `speed`.
**Why it happens:** Misreading the AST — `speed` is an `exp.Alias`, not an `exp.Column`.
**How to avoid:** Only match `exp.Column` nodes (VERIFIED: `vx AS speed` → the `vx` is `exp.Column`, `speed` is `exp.Alias.name`; rewrite yields `"linear.x" AS speed`). No special handling needed.
**Warning signs:** A test asserting the output column name changed.

### Pitfall 2: CTE / `FROM <cte_alias>` over-rewriting
**What goes wrong:** `WITH fast AS (SELECT vx FROM odom WHERE vx>1) SELECT vx FROM fast` — a whole-tree rewrite expands BOTH the inner `vx` (correct: it's on `odom`) AND the outer `SELECT vx FROM fast` (the CTE `fast` exposes a column literally named `vx`, so expanding it to `"twist.twist.linear.x"` would break the query — `fast` has no such column). VERIFIED: a naive transform rewrites all three `vx`.
**Why it happens:** `transform` walks the entire tree with no scope awareness; `topic_to_msgtype` only knows base topics, not CTE-projected names.
**How to avoid:** The existence-gate (D-04) is the safety net, but it must gate against the **base-topic** schemas only. For v1's single-FROM canonical case this is a non-issue (one topic, unambiguous). For multi-topic/CTE, the safe-and-simple rule consistent with D-09 (over-include, never break) is: **only expand an alias when at least one referenced base topic's pack contains it AND its target exists in that topic's schema** — and apply the same expansion tree-wide (the over-include of D-09). A column already named `vx` projected out of a CTE is NOT in any base topic's schema under its *target* dotted name, so the gate leaves the outer reference untouched ONLY if you key the gate on "is `vx` an alias AND does `target` exist," not "does `vx` exist." Recommend: **scope alias expansion to the canonical single-base-topic case for v1**, and for any query with >1 distinct referenced base topic OR any CTE, document that expansion still applies tree-wide but is existence-gated so it is a safe no-op on names that don't resolve. Flag this as the one place to write focused tests (single-FROM happy path; a CTE re-exposing an alias-named column; a JOIN of two topics).
**Warning signs:** A CTE query that worked with `--no-alias` but fails with aliases on.

### Pitfall 3: Standard columns dropped by projection
**What goes wrong:** `SELECT vx` projects to `{linear.x}` and the result Table has no `t`/`stamp`, breaking `--plot` (which needs `t_ns`) and ordering.
**Why it happens:** Forgetting D-07.
**How to avoid:** The orchestrator must union the four standard names into the restrict set: `restrict = (columns & schema_names) | {"t","t_ns","stamp","topic"}`. VERIFIED end-to-end that this yields `{linear.x, t, t_ns, stamp, topic}`.
**Warning signs:** `--plot` fails on an aliased single-column query.

### Pitfall 4: `restrict` breaking the `SELECT *` contract
**What goes wrong:** A `SELECT *` produces NO `exp.Column` nodes (VERIFIED), so `referenced_columns` is empty; a naive `restrict = columns | STD` would then materialize only the four standard columns — silently dropping every body column under a star.
**Why it happens:** `restrict` derived from an empty referenced-column set under a star.
**How to avoid:** D-08: when `has_star(tree)` is true, pass `restrict=None` (the "materialize everything non-heavy" path, exactly today's behavior). Only compute a restrict set when NOT a star.
**Warning signs:** `SELECT * FROM cmd_vel` returns only `t/t_ns/stamp/topic`.

### Pitfall 5: Qualified star `o.*` polluting the referenced-column set
**What goes wrong:** `SELECT o.* FROM odom AS o` parses to an `exp.Column` with `.name == '*'` (VERIFIED) AND an `exp.Star`. `referenced_columns` would include `'*'`.
**Why it happens:** sqlglot models a qualified star as a column whose name is `*`.
**How to avoid:** `has_star` already returns true here (VERIFIED), so D-08 routes it to `restrict=None` before the `'*'` name matters. No extra handling needed, but the planner should add a test asserting `o.*` disables projection for that topic. (The `'*'` would also never match a real schema column, so even if it leaked into a restrict set it is harmless — but the star path short-circuits first.)

### Pitfall 6: `import rosbagger_core.backend.alias` leaking the heavy stack
**What goes wrong:** A careless top-level `import pyarrow` (or importing `query.py`) in `alias.py` would break the offline invariant.
**Why it happens:** Habit.
**How to avoid:** `alias.py` imports only `from __future__ import annotations` and `from sqlglot import exp` (pure-Python, offline-safe — same as `resolve.py`/`identifiers.py`). The pack is a plain dict literal. Add a regression test to `test_offline_guard.py`: `_heavy_modules_after_import("rosbagger_core", "rosbagger_core.backend.alias")` must be `[]`. (`backend/__init__.py` adds NO eager import, so the subpackage import stays light — VERIFIED pattern.)
**Warning signs:** The offline-guard subprocess test reports `sqlglot` is fine but `pyarrow`/`duckdb` leaked.

## Code Examples

Verified patterns from in-session experiments against sqlglot 30.8.0 and real fixture schemas.

### Example 1: Read column name + table qualifier
```python
# Source: VERIFIED sqlglot 30.8.0
tree = sqlglot.parse_one('SELECT o.vx FROM odom AS o', dialect="duckdb")
for c in tree.find_all(exp.Column):
    c.name    # 'vx'        (the bare column name; a quoted dotted col -> 'twist.twist.linear.x')
    c.table   # 'o'         (the qualifier; '' when unqualified)
```

### Example 2: Build the quoted dotted replacement
```python
# Source: VERIFIED sqlglot 30.8.0
exp.column("twist.twist.linear.x", quoted=True).sql(dialect="duckdb")
#   -> '"twist.twist.linear.x"'
# preserving a qualifier:
exp.column("twist.twist.linear.x", table="o", quoted=True).sql(dialect="duckdb")
#   -> '"o"."twist.twist.linear.x"'
```

### Example 3: Already-dotted columns are immune (no double-expansion)
```python
# Source: VERIFIED sqlglot 30.8.0
tree = sqlglot.parse_one('SELECT "twist.twist.linear.x" FROM odom', dialect="duckdb")
[c.name for c in tree.find_all(exp.Column)]   # ['twist.twist.linear.x']
# .name CONTAINS the dots, so it never equals a short alias like 'vx' -> safe no-op
```

### Example 4: The full orchestrator restrict computation
```python
# Source: composed from query.py + D-06/D-07/D-08, VERIFIED end-to-end on a fixture
STANDARD = {"t", "t_ns", "stamp", "topic"}
# ... per referenced topic, with `schema` already built:
schema_names = {c.name for c in schema.columns}
heavy = {c.name for c in schema.columns if c.is_heavy_blob}
if star:
    include, restrict = heavy, None                 # D-08: star -> materialize all non-heavy + blobs
else:
    include  = heavy & columns                      # existing QURY-07 rule (unchanged)
    restrict = (columns & schema_names) | STANDARD  # D-06 + D-07
arrow = build_arrow_table(msgs, schema, include=include, restrict=restrict)
```

### Example 5: SC3 proof (the test shape D-10 demands)
```python
# Source: VERIFIED end-to-end on a rosbags-written ROS2 sqlite fixture, NO ROS, NO DuckDB
# SELECT vx FROM cmd_vel  (Twist; pack maps vx -> linear.x)
arrow = build_arrow_table(reader.read(topics={"/cmd_vel"}), proj_schema)
assert set(arrow.column_names) == {"linear.x", "t", "t_ns", "stamp", "topic"}
assert "angular.z" not in arrow.column_names    # unreferenced light col NOT materialized
assert "linear.y"  not in arrow.column_names
# An Arrow-schema assertion is SUFFICIENT — no spy on flatten_message needed,
# because a column absent from the Table proves its reduce(getattr) never ran.
```

## Alias Pack v1 Contents (VERIFIED dotted paths)

Every dotted path below was produced by `build_table_schema(msgtype, ROS2_HUMBLE_typestore, topic=...)` in-session — they are the EXACT column names the flatten walk emits, so the existence-gate (D-04) will match. Keys are the canonical `pkg/msg/Type` string (see Pitfall: msgtype normalization).

| msgtype | Suggested aliases → dotted target | Notes |
|---------|-----------------------------------|-------|
| `nav_msgs/msg/Odometry` | `vx`→`twist.twist.linear.x`, `vy`→`twist.twist.linear.y`, `vz`→`twist.twist.linear.z`, `wx`→`twist.twist.angular.x`, `wy`→`twist.twist.angular.y`, `wz`→`twist.twist.angular.z`, `px`→`pose.pose.position.x`, `py`→`pose.pose.position.y`, `pz`→`pose.pose.position.z`, `qx`→`pose.pose.orientation.x`, `qy`→`pose.pose.orientation.y`, `qz`→`pose.pose.orientation.z`, `qw`→`pose.pose.orientation.w` | The **canonical** `vx`→`twist.twist.linear.x` (CONTEXT specifics). Double-nested. |
| `geometry_msgs/msg/Twist` | `vx`→`linear.x`, `vy`→`linear.y`, `vz`→`linear.z`, `wx`→`angular.x`, `wy`→`angular.y`, `wz`→`angular.z` | Shallowest (no header, no wrapper). The `/cmd_vel` fixture is this type. |
| `geometry_msgs/msg/TwistStamped` | `vx`→`twist.linear.x`, `vy`→`twist.linear.y`, `vz`→`twist.linear.z`, `wx`→`twist.angular.x`, `wy`→`twist.angular.y`, `wz`→`twist.angular.z` | One wrapper level (`twist.`). Confirms message-type-keyed pack is mandatory (D-03). |
| `sensor_msgs/msg/Imu` | `ax`→`linear_acceleration.x`, `ay`→`linear_acceleration.y`, `az`→`linear_acceleration.z`, `wx`→`angular_velocity.x`, `wy`→`angular_velocity.y`, `wz`→`angular_velocity.z`, `qx`→`orientation.x`, `qy`→`orientation.y`, `qz`→`orientation.z`, `qw`→`orientation.w` | The `/imu` fixture is this type. Note `wx/wy/wz` here = angular velocity (vs Twist's). |
| `geometry_msgs/msg/PoseStamped` | `px`→`pose.position.x`, `py`→`pose.position.y`, `pz`→`pose.position.z`, `qx`→`pose.orientation.x`, `qy`→`pose.orientation.y`, `qz`→`pose.orientation.z`, `qw`→`pose.orientation.w` | One wrapper (`pose.`). |
| `geometry_msgs/msg/Pose` | `px`→`position.x`, `py`→`position.y`, `pz`→`position.z`, `qx`→`orientation.x` … `qw`→`orientation.w` | Bare pose (no header). |

**Pack design recommendation:** A flat `dict[str, dict[str, str]]` literal in `backend/alias.py`, keyed by the full `pkg/msg/Type`. The exact alias *names* are Claude's discretion (D-05) — the table above is a verified, sufficient v1 set covering the three fixture types (`Twist`, `Imu`, `Image` has no scalar-velocity aliases) plus the canonical Odometry case the success criteria name. The existence-gate means shipping an alias for a type a bag doesn't carry is harmless.

**Heavy-blob note:** Among all these types, only `Image.data` (`sensor_msgs/msg/Image`) is a heavy blob (VERIFIED: `uint8[]` SEQUENCE). `Odometry.pose.covariance` / `twist.covariance` (`float64[36]`) and `Imu.*_covariance` (`float64[9]`) are fixed-length ARRAYs → LIST columns, NOT heavy blobs. So projection and heavy-blob filtering are genuinely orthogonal here.

## Runtime State Inventory

> Phase 10 is a **greenfield code-feature addition** to an existing pipeline — it stores no data, registers no OS state, and renames nothing. The Runtime State Inventory categories are addressed for completeness:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified by reading CONTEXT (both features are in-memory query-time transforms; no datastore, no persisted index) | none |
| Live service config | None — verified; offline tool, no external services | none |
| OS-registered state | None — verified; no scheduled tasks/daemons | none |
| Secrets/env vars | None — verified; no new config. (Local test runs need `PYTHONPATH=""` per MEMORY, but that is a pre-existing dev-host hazard, not new state.) | none |
| Build artifacts | None — verified; no `pyproject.toml`/`uv.lock` change (no new dependency), so no reinstall/egg-info concern | none |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` (+ `pytest-cov`, coverage gate `>=80%` in `addopts`) |
| Config file | root `pyproject.toml` (`[tool.pytest.ini_options]`; `--cov=rosbagger_core --cov=bagq --cov-fail-under=80`) |
| Quick run command | `PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_alias.py tests/test_schema_arrow.py -x` |
| Full suite command | `PYTHONPATH="" .venv/bin/python -m pytest -q` (baseline: **274 passed, 97.76%**, VERIFIED this session) |

> **LOCAL-RUN REQUIREMENT (MEMORY + every prior phase):** this dev box sources ROS 2 onto `PYTHONPATH`; prefix local runs with `PYTHONPATH=""`. CI is ROS-free and needs no prefix. New test files must bake in NO `PYTHONPATH` override (mirrors `test_cli_query.py`).

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QURY-08 | `vx`→`"twist.twist.linear.x"` (Odometry) and shallower for Twist/TwistStamped; rewrite via AST | unit | `pytest tests/test_backend_alias.py -x` | ❌ Wave 0 |
| QURY-08 | Existence-gate: unknown alias / wrong-topic alias left untouched (no-op) | unit | `pytest tests/test_backend_alias.py -k gate -x` | ❌ Wave 0 |
| QURY-08 | `--no-alias` disables expansion (CLI surface) | integration | `pytest tests/test_cli_query.py -k no_alias -x` | ⚠️ extend |
| QURY-08 | Edge cases: CTE/JOIN no-op safety, `AS speed` preserved, already-dotted immune, function args | unit | `pytest tests/test_backend_alias.py -k edge -x` | ❌ Wave 0 |
| QURY-09 | `restrict=` filter on `arrow_schema`/`build_arrow_table`/`flatten_message` | unit | `pytest tests/test_schema_arrow.py -k restrict -x` | ⚠️ extend |
| QURY-09 / SC3 | Single-column query materializes exactly `{col} ∪ {t,t_ns,stamp,topic}`, excludes heavy/unreferenced (ROS-free fixture, all 3 formats) | integration | `pytest tests/test_backend_query.py -k projection -x` | ⚠️ extend |
| QURY-09 | `SELECT *` (and `o.*`) disables projection (full materialization) | integration | `pytest tests/test_backend_query.py -k star -x` | ⚠️ extend |
| both | `import rosbagger_core.backend.alias` pulls no heavy stack | unit | `pytest tests/test_offline_guard.py -k alias -x` | ⚠️ extend |

### Sampling Rate
- **Per task commit:** `PYTHONPATH="" .venv/bin/python -m pytest tests/test_backend_alias.py tests/test_schema_arrow.py tests/test_backend_query.py -x`
- **Per wave merge:** `PYTHONPATH="" .venv/bin/python -m pytest -q` (full suite green; coverage ≥80%)
- **Phase gate:** Full suite green + `ruff check` + `ruff format --check` clean before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_backend_alias.py` — covers QURY-08 (rewrite mechanics, existence-gate, edge cases). NEW file. Self-contained harness (repo-root `sys.path` insert + `tools.make_fixtures`), mirrors `test_cli_query.py`.
- [ ] Extend `tests/test_schema_arrow.py` — `restrict=` filter unit tests on `arrow_schema`/`build_arrow_table`/`flatten_message` (QURY-09).
- [ ] Extend `tests/test_backend_query.py` — SC3 projection integration parametrized over ROS1 + ROS2-sqlite + MCAP (per project norm); `SELECT *` disables projection.
- [ ] Extend `tests/test_cli_query.py` — `--no-alias` surface (CliRunner, asserts stable data only — no rich box-drawing).
- [ ] Extend `tests/test_offline_guard.py` — `import rosbagger_core.backend.alias` heavy-stack regression (one `_heavy_modules_after_import` call).
- Framework install: none (pytest already present).

## Security Domain

> `security_enforcement` config not located in `.planning/` (no `config.json` found in repo). Treating as enabled per the absent=enabled rule. The relevant security surface for this phase is narrow: it sits entirely upstream of `backend.execute` and the existing trust boundary.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local single-user CLI; no auth surface |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-tenant boundary |
| V5 Input Validation | **yes** | User SQL is the trusted interface (T-05-04) but bag-derived NAMES are untrusted; alias targets are interpolated as **quoted identifiers via `exp.column(..., quoted=True)`** — never raw strings. The alias pack values are author-controlled constants, not user input. |
| V6 Cryptography | no | No crypto in scope |

### Known Threat Patterns for {sqlglot AST rewrite over a local CLI}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via alias-target string | Tampering | Build the replacement with `exp.column(target, quoted=True)` inside the AST (VERIFIED escapes/quotes); never f-string. Same as the locked T-03-06 / T-05-04 boundary. The orchestrator still interpolates NO identifier itself — it forwards `tree.sql("duckdb")`. |
| Alias pack as an injection vector | Tampering | The pack is a hard-coded dict of author-chosen dotted names (D-05, not user-extensible in v1) — no untrusted data flows into it. |
| Existence-gate bypass exposing a wrong column | Information disclosure (mild) | Gate strictly on `target in TableSchema.column_names`; a miss leaves the original token, surfacing the normal `UnknownColumnError` teaching path (CLI-03) — no silent wrong-column read. |
| DoS via pathological SQL | DoS | Out of scope / unchanged — `transform` is O(nodes); the projection only ever *reduces* work vs today. No new unbounded recursion (sqlglot owns parse depth). |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `vx` not available; users type `WHERE "twist.twist.linear.x" > 0.5` | Alias pack expands `vx` per msgtype | Phase 10 (this) | Terser queries; design spec §7 fast-follow realized |
| Whole referenced topic materialized (design §4.2: "v1 load referenced topics fully; projection pushdown is a later optimization") | Only referenced columns + standard cols materialized | Phase 10 (this) | Less memory/CPU per query; the §7 "load only referenced columns" item realized |
| `sqlglot` `exp.column(name, quoted=True)` API | Same — stable across the `>=27,<31` range; VERIFIED on 30.8.0 | — | No migration risk within the pin |

**Deprecated/outdated:** None relevant. (Note: `rosbags` `AnyReader` normalizes ROS1 msgtypes to the `pkg/msg/Type` form — so there is no longer a `pkg/Type` variant to special-case; see Assumptions.)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact alias *names* (`vx`/`wz`/`ax`/`px`/`qw`/…) shipped in the v1 pack are reasonable defaults; the user did not enumerate them (D-05 left contents to research). The dotted *targets* are VERIFIED. | Alias Pack v1 Contents | Low — names are bikeshed-level; existence-gate makes a bad/absent alias a harmless no-op. discuss-phase may want to confirm the alias vocabulary. |
| A2 | `rosbags` normalizes ROS1 msgtypes to `pkg/msg/Type` (so the pack can key on that single form). VERIFIED for `Twist`/`Imu`/`Image` against both ROS1 and ROS2-sqlite fixtures this session. | State of the Art / Pitfalls | Low — verified on the three fixture types; a defensive normalization in the lookup (strip-then-`/msg/`-insert) is cheap insurance if an exotic custom-msg path differs. |
| A3 | For multi-topic/JOIN/CTE queries, expansion applies tree-wide but is existence-gated, making it a safe no-op on non-resolving names (consistent with D-09 over-include). The CANONICAL/tested case is single-FROM. | Pitfall 2 | Medium — a JOIN where the SAME short alias is valid on two different msgtypes with DIFFERENT targets is ambiguous. v1 recommendation: scope the *gate* to single-base-topic queries and document multi-topic as best-effort. The planner should write an explicit test and may choose to expand only when exactly one base topic is referenced (safest). |
| A4 | An Arrow-`column_names` assertion is sufficient proof for SC3 (no `flatten_message` spy needed). VERIFIED: a column absent from the Table cannot have had its `reduce(getattr)` run, since `build_arrow_table` builds arrays only for kept columns. | Validation Architecture / Code Example 5 | Low — verified end-to-end. A spy is available as a stronger belt-and-suspenders option if desired. |
| A5 | `security_enforcement` is enabled (no `.planning/config.json` found; absent=enabled). | Security Domain | Low — the security surface is narrow and already covered by the existing T-05-04/T-03-06 boundary. |

## Open Questions

1. **Multi-topic / JOIN alias ambiguity (the one real design choice left)**
   - What we know: single-FROM (the canonical case) is unambiguous and fully verified. `referenced_columns` is a flat unqualified set (D-09 over-includes for projection, which is safe).
   - What's unclear: when a JOIN references two topics whose packs both define `wx` with DIFFERENT targets (e.g. Twist's `angular.x` vs Imu's `angular_velocity.x`), a tree-wide rewrite can't know which the user meant for an unqualified `wx`.
   - Recommendation: For v1, **expand aliases only when exactly one distinct base topic is referenced** (the existence-gate then has an unambiguous schema). For >1 base topic, leave short tokens untouched (the user can write the dotted column or qualify it). This is strictly safe, matches D-04's "safe no-op," and keeps the canonical case fully working. The planner should encode this as an explicit guard + test. (Qualified `o.wx` could still expand using `o`'s resolved topic — a nice-to-have, deferrable.)

2. **Alias pack vocabulary sign-off**
   - What we know: the verified targets are correct; the alias spellings are discretionary (D-05).
   - What's unclear: whether the user prefers a specific naming convention (e.g. `vx` vs `lin_x`).
   - Recommendation: ship the table above as the default; surface it in discuss-phase if naming matters. Existence-gating de-risks any choice.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `sqlglot` | Alias rewrite | ✓ | 30.8.0 | — (already locked) |
| `pyarrow` | Projection build | ✓ | (locked `>=18`) | — |
| `rosbags` | Fixture schemas + typestore | ✓ | (locked `>=0.11,<0.12`) | — |
| `duckdb` | Execute (unchanged) | ✓ | (locked `>=1.4,<2`) | — |
| `pytest` + `tools.make_fixtures` | Tests (ROS1/ROS2-sqlite/MCAP fixtures) | ✓ | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.
(Baseline full suite ran clean this session: 274 passed, 97.76% coverage, ≥80% gate met.)

## Sources

### Primary (HIGH confidence)
- **In-session sqlglot 30.8.0 experiments** — `find_all(exp.Column)` name/table, `exp.column(..., quoted=True)`, `tree.transform` copy semantics, clause coverage, CTE/qualified-star/output-alias behavior. All claims tagged VERIFIED come from these runs.
- **In-session `build_table_schema` runs** against `ROS2_HUMBLE` typestore — every dotted column path in the Alias Pack table and the heavy-blob classification.
- **In-session end-to-end SC3 proof** on a `rosbags`-written ROS2 sqlite fixture (`tools.make_fixtures.write_ros2_sqlite_bag`) — alias rewrite → existence-gate → projection → Arrow `column_names` assertion.
- Repo source (read this session): `backend/resolve.py`, `backend/query.py`, `schema/flatten.py`, `schema/model.py`, `schema/types.py`, `schema/identifiers.py`, `schema/__init__.py`, `backend/__init__.py`, `rosbagger_core/__init__.py`, `bagq/cli.py`, `tests/test_offline_guard.py`, `tests/conftest.py` (header), `tests/test_cli_query.py` (header), `tools/make_fixtures.py` (msgtype list).
- `.planning/phases/10-query-ergonomics/10-CONTEXT.md` (locked D-01..D-11), `.planning/REQUIREMENTS.md` (QURY-08/09), `.planning/STATE.md`, `docs/superpowers/specs/2026-05-21-rosbagger-design.md` §4.2/§7.
- `uv.lock` (sqlglot 30.8.0, line 1330) + `packages/rosbagger-core/pyproject.toml` (deps + `requires-python>=3.10`).

### Secondary (MEDIUM confidence)
- None required — every load-bearing claim was verifiable directly against the pinned local stack, so no WebSearch/Context7 lookup was needed.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependency; versions read from `uv.lock`/`pyproject.toml` and `sqlglot.__version__` confirmed locally.
- Architecture (sqlglot rewrite + restrict threading): HIGH — every mechanic verified in-session against sqlglot 30.8.0 and real fixture schemas, including the full end-to-end flow.
- Pitfalls: HIGH — the CTE over-rewrite, qualified-star, standard-column, and `SELECT *` pitfalls were each reproduced empirically.
- Alias pack contents: HIGH for the dotted *targets* (built from the typestore); MEDIUM for the alias *spellings* (discretionary per D-05; see Assumption A1).
- Multi-topic ambiguity handling: MEDIUM — single-FROM fully verified; JOIN/CTE handling is a documented v1-scope recommendation (Open Q1 / Assumption A3) for the planner to lock.

**Research date:** 2026-05-22
**Valid until:** 2026-06-21 (stable — pinned dependencies, no fast-moving external surface; the sqlglot API used is stable across the `>=27,<31` pin range)
