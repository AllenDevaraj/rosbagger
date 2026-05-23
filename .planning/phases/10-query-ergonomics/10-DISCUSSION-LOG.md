# Phase 10: Query Ergonomics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-22
**Phase:** 10-query-ergonomics
**Mode:** `--auto` (autonomous — all gray areas auto-selected; recommended option chosen per question, no user prompts)
**Areas discussed:** Alias resolution mechanism, Alias pack scope & contents, Column projection pushdown, JOIN attribution & SC3 verification, `bagq query` surface

---

## Alias resolution mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| sqlglot AST rewrite (before resolution) | Walk the parsed tree, replace matching `exp.Column` with the quoted dotted column, regenerate SQL; rewrite precedes `referenced_*` so projection sees expanded names | ✓ |
| Regex string substitution | Find/replace alias tokens in the raw SQL string | |
| DuckDB views / macros | Define alias columns as DuckDB-side views or macros | |

**Auto-selected:** sqlglot AST rewrite, before table/column resolution.
**Notes:** Reuses the locked sqlglot seam (`resolve.py`); preserves the trusted-SQL boundary (no raw interpolation). Regex was explicitly rejected in Phase 5 ("Don't Hand-Roll" — breaks on CTE/JOIN/quoting). DuckDB views would push aliasing past the trusted seam and couldn't inform topic/column loading.

---

## Alias pack scope & contents

| Option | Description | Selected |
|--------|-------------|----------|
| Per-msgtype built-in pack | Mapping keyed by message type; expand only when the target column exists in the FROM topic; curated built-in set for v1 | ✓ |
| Flat global mapping | One global `alias → dotted column` dict regardless of message type | |
| User-extensible from v1 | Ship a config-file / CLI-registered custom alias mechanism now | |

**Auto-selected:** message-type-keyed built-in pack; expand only when the target column exists; user packs deferred.
**Notes:** The canonical `vx → "twist.twist.linear.x"` is the nav_msgs/Odometry path; Twist's own velocity is the shallower `"twist.linear.x"`. A single global mapping would therefore be wrong for at least one common type, forcing msgtype keying. `topic_to_msgtype` already exists in the orchestrator.

---

## Column projection pushdown

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse the schema filter seam | Generalize `arrow_schema`/`build_arrow_table`/`flatten_message`'s `include=` filter into a projection restrict-set; skip `getattr` for non-projected columns | ✓ |
| Parallel projection path | Build a separate code path for projection independent of the heavy-blob filter | |
| Let DuckDB prune post-load | Materialize everything, rely on DuckDB to drop unused columns | |

**Auto-selected:** reuse/generalize the schema filter seam; standard `t`/`t_ns`/`stamp`/`topic` always kept; `SELECT *` opts out; heavy-blob rule preserved.
**Notes:** The existing heavy-blob `include` + `has_star` machinery is already "materialize a subset, but everything under a star" — projection is the same shape over all columns. Skipping the `reduce(getattr, …)` read for non-projected columns is the real pushdown. "Let DuckDB prune" rejected — it would still materialize unreferenced/heavy columns, failing SC3.

---

## JOIN attribution & SC3 verification

| Option | Description | Selected |
|--------|-------------|----------|
| Over-include + Arrow-schema assertion | Unqualified referenced names applied to each topic (over-include, never under-include); prove SC3 by asserting the materialized Arrow column set on a fixture bag | ✓ |
| Table-qualified attribution now | Resolve each column to its specific topic in JOINs immediately | |
| Benchmark-based proof | Demonstrate SC3 via memory/time measurement | |

**Auto-selected:** over-include on ambiguity (never under-include); deterministic Arrow-schema assertion on a ROS-free fixture bag.
**Notes:** `referenced_columns` is a flat, unqualified name set; applying it per topic over-includes safely (a query never loses a column it needs). Table-qualified attribution is a correctness-neutral refinement, deferred. SC3's "verifiable" is read as an assertion on the materialized column set, not a benchmark.

---

## `bagq query` surface

| Option | Description | Selected |
|--------|-------------|----------|
| On-by-default + `--no-alias` | Aliases expand by default; `--no-alias` disables; projection always-on and transparent | ✓ |
| Opt-in flag | Aliases only expand when a flag is passed | |
| No flag at all | Aliases always on, no escape hatch | |

**Auto-selected:** alias ON by default with a `--no-alias` escape hatch; projection always-on and transparent.
**Notes:** Aliases surface through the existing thin `query` pass-through. `--no-alias` is cheap insurance (rarely needed given existence-gating). Projection changes no results — only what is loaded — so it needs no flag.

---

## Claude's Discretion

- Exact alias-pack contents (which msgtypes / shortcuts ship).
- Function and parameter names; module placement (extend `resolve.py` vs a new `backend/alias.py`).
- Hard constraints on all of the above: the offline-import invariant and the trusted-SQL boundary.

## Deferred Ideas

- User-defined / config-file alias packs.
- Table-qualified projection in JOINs.
- Row-level / predicate pushdown (`WHERE`-time row filtering).
- DuckDB view/macro alias layer (considered and declined).
