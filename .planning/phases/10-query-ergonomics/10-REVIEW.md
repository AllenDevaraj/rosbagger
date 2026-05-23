---
phase: 10-query-ergonomics
reviewed: 2026-05-23T05:40:01Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - packages/rosbagger-core/src/rosbagger_core/backend/alias.py
  - packages/rosbagger-core/src/rosbagger_core/backend/query.py
  - packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
  - packages/rosbagger-core/src/rosbagger_core/schema/model.py
  - packages/bagq/src/bagq/cli.py
  - tests/test_backend_alias.py
  - tests/test_backend_query.py
  - tests/test_cli_query.py
  - tests/test_offline_guard.py
  - tests/test_schema_arrow.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-05-23T05:40:01Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 10 (Query Ergonomics) adds a built-in alias pack with a `sqlglot`-AST rewrite
(`backend/alias.py`), a `restrict=` column-projection filter (`schema/model.py`,
`schema/flatten.py`), wires both into the orchestrator (`backend/query.py`), and adds
a `bagq query --no-alias` flag (`bagq/cli.py`).

**The four project-specific invariants hold under adversarial testing:**

- **Offline-import invariant — HOLDS.** A fresh-subprocess import of
  `rosbagger_core.backend.query` and `rosbagger_core.backend.alias` leaks no `duckdb`
  / `pyarrow`. `alias.py` imports `sqlglot` at module top (sanctioned, pure-Python).
  The 10 offline-guard tests pass.
- **Trusted-SQL boundary — HOLDS.** No f-string / `.format` / `%` SQL construction
  exists in the changed backend files. The alias rewrite builds its replacement
  exclusively via `exp.column(target, quoted=True)`; I verified that path escapes an
  embedded quote (`x"; DROP TABLE y;--` renders as one quoted identifier). The pack
  targets are curated constants regardless.
- **Projection correctness — HOLDS.** `restrict=None` is byte-for-byte the prior
  behavior (verified against `test_schema_arrow.py` regressions); the four standard
  columns are always unioned into `restrict` (verified the registered table for
  `SELECT vx FROM cmd_vel` is exactly `{linear.x,t,t_ns,stamp,topic}`); `SELECT *`
  and qualified `o.*` opt out (`restrict=None`); JOIN projection over-includes
  (qualifier-stripped column union per topic), never under-includes — verified
  end-to-end including `ORDER BY`/`WHERE`/`HAVING`/`GROUP BY` columns absent from
  `SELECT`.
- **Alias gating — HOLDS.** Expansion runs only when `referenced_tables_in(tree)`
  (CTE-subtracted, set-deduplicated) resolves to exactly one base topic, and is
  existence-gated on that topic's schema column names. Self-join / subquery /
  JOIN / no-FROM cases were each traced and behave correctly.

All 81 Phase 10 tests pass. No BLOCKER-class defects (no incorrect results, no
security gap, no crash, no data loss) were found. The findings below are robustness
and quality concerns — the most material is WR-01, a behavior change to the
`--no-alias` escape hatch.

## Warnings

### WR-01: `--no-alias` no longer bypasses sqlglot re-rendering; no raw-SQL fallback remains

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:285`
**Issue:** Phase 10 changed the execute call from `backend.execute(sql)` (the prior
behavior, forwarding the user's raw string) to `backend.execute(tree.sql("duckdb"))`
— it now always re-renders the parsed AST. This is correct *when alias expansion ran*
(the rewritten tree must reach DuckDB), but it also applies on the `alias=False`
(`--no-alias`) path, where `tree` is the unmodified parse of the user's SQL. The
consequence: every query — including `--no-alias` — is now round-tripped through
`sqlglot`'s renderer, and `--no-alias` is no longer a true "send my SQL verbatim"
escape hatch.

Most DuckDB syntax round-trips losslessly or equivalently (I verified `count(*)`,
casts, `LIMIT/OFFSET`, list indexing, `EXCLUDE`, `QUALIFY`, struct/map literals all
re-render to semantically identical SQL). But `sqlglot` *does* rewrite surface syntax
(`x::INTEGER` → `CAST(x AS INT)`, `list_value(1,2,3)` → `[1,2,3]`,
`TABLESAMPLE 10%` → `TABLESAMPLE SYSTEM (10 PERCENT)`). For a tool branded
"DuckDB-for-bags," a user who hits a `sqlglot` round-trip gap or an unsupported-but-
valid DuckDB construct now has **no way to bypass the rewrite** — `--no-alias` only
disables the alias pack, not the AST round-trip. (Note: the *parse* itself already
happened pre-Phase-10 for resolution, so a parse *failure* is a pre-existing risk;
what is new in Phase 10 is forwarding the re-rendered string instead of the original.)

**Fix:** Forward the original `sql` string when no rewrite occurred; only render the
tree when alias expansion actually ran. Track whether expansion happened and choose
the source accordingly:

```python
# Step 4 — alias expansion, track whether it ran.
expanded = False
if alias:
    base_tables = [t for t in referenced_tables_in(tree) if t in table_to_topic]
    if len(base_tables) == 1:
        schema = schemas_by_table[base_tables[0]]
        new_tree = expand_aliases(tree, schema.msgtype, {c.name for c in schema.columns})
        if new_tree is not tree:        # transform copies; cheap identity check
            tree, expanded = new_tree, True
...
# Step 8 — forward the ORIGINAL sql unless a rewrite occurred.
final_sql = tree.sql("duckdb") if expanded else sql
try:
    return backend.execute(final_sql)
```

This keeps the rewritten SQL on the alias path while restoring `--no-alias` (and the
no-op-expansion default path) to verbatim forwarding. Alternatively, document
explicitly that all SQL is normalized through `sqlglot` and that `--no-alias` is not a
raw-SQL bypass — but a code fix is preferable since the docstring (lines 130-135)
currently implies the raw string round-trips unchanged.

### WR-02: `count(*)` (and any aggregate `*`) materializes every heavy blob — robustness/memory risk

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:258-262`
**Issue:** `has_star(tree)` returns `True` for `count(*)` / `avg(*)` / any `exp.Star`
node, not just `SELECT *`. On the `star` branch the code sets `restrict=None` AND
`include=heavy` (the topic's *full* heavy-blob set). So `SELECT count(*) FROM image`
deserializes and materializes the entire `data` blob column for every message — I
confirmed the registered table for `SELECT count(*) FROM image` contains `data`. For a
PointCloud2 / Image topic this can load hundreds of MB to compute a row count, which
contradicts the documented QURY-07 promise that "an explicit projection naming no blob
omits them" — a `count(*)` names no blob.

This is largely **pre-existing** (the prior `include = heavy if star else ...` had the
same conflation, so Phase 10 did not introduce the blob load), and pure performance is
out of v1 review scope. It is flagged as a Warning rather than Info because Phase 10's
new projection machinery is explicitly about *not loading what isn't needed*, and the
`has_star` short-circuit silently defeats that for the very common `count(*)` /
aggregate case — a robustness cliff a user will not expect.

**Fix:** Distinguish a top-level `SELECT *` (the "give me everything, blobs included"
intent) from a star that appears only inside an aggregate. One option: gate the
heavy-blob-include-everything behavior on a star that is a direct projection of the
outermost `SELECT`, e.g.

```python
def _has_projection_star(tree: exp.Expression) -> bool:
    sel = tree.find(exp.Select)
    return bool(sel) and any(isinstance(p, exp.Star) for p in sel.expressions)
```

and use that (instead of the tree-wide `has_star`) to decide `include=heavy` /
`restrict=None`, so `count(*)` falls through to the projection path (`include=heavy &
columns` = `{}` for a blob-free count). Keep the existing `has_star` behavior for the
projection opt-out only where a true projection star is present. (If deferred as
out-of-scope performance, record it explicitly so it is not lost.)

### WR-03: `query()` blanket-catches the binder exception around the whole load+execute block, not just `execute`

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:284-290`
**Issue:** The `try: return backend.execute(tree.sql("duckdb")) except
duckdb_binder_exception()` wraps only `execute` — that part is fine. But note the
*outer* `try` (line 238) spans the entire per-topic load/register loop, and its sole
handler is the `finally` that closes the backend. If `build_arrow_table` or
`reader.read` raises mid-loop (e.g. a malformed message, a typestore mismatch), the
backend is correctly closed, but the partially-registered relations and the half-built
state are silently discarded with the original exception propagating raw. That is
acceptable behavior, but the `_BINDER_COL` regex narrowing (line 287-290) assumes the
`columns_by_table` map is fully populated for *all* referenced tables. It is — the loop
populates `columns_by_table` for every referenced topic before `execute` runs — so the
unknown-column teaching message is complete. No bug today.

The latent risk: `columns_by_table` is keyed by the sanitized table name and lists the
**full** schema columns, but the registered tables only carry the **projected** subset.
If a future change makes the binder error fire on a column that *exists in the schema
but was projected away* (it cannot today, because any referenced column is unioned into
`restrict`), the teaching message would list a column the user "should" be able to
select yet the query failed on. This is defensible now but fragile; the coupling
between "columns advertised in the error" (full schema) and "columns actually
materialized" (projected) is implicit.

**Fix:** No code change required for correctness today. Add a one-line assertion or
comment documenting the invariant that every referenced (non-star) column is
guaranteed present in `restrict`, so the full-schema column listing in
`UnknownColumnError` can never name a column that was silently projected out. This
makes the WR-03 coupling explicit for the next maintainer:

```python
# INVARIANT: restrict ⊇ (referenced columns ∩ schema). So any column the binder
# rejects is genuinely absent from the schema, never merely projected away — the
# full-schema listing in UnknownColumnError is therefore never misleading.
```

## Info

### IN-01: `_normalize` silently no-ops on malformed/empty msgtype rather than signalling

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/alias.py:135-150`
**Issue:** `_normalize("")` returns `""`, `_normalize("a/b/c/d")` returns it unchanged,
and any non-2/3-segment input is returned verbatim. Each then misses the pack lookup
and yields `{}` (a whole-tree no-op). This is the documented, intentional "harmless
no-op via the existence-gate" behavior and is safe. Noted only because a genuinely
malformed `msgtype` reaching this helper indicates an upstream problem (the reader
should always supply `pkg/msg/Type`), and the silent no-op would mask it. Acceptable
as defensive insurance; no action needed unless upstream guarantees weaken.

### IN-02: Repeated `{c.name for c in schema.columns}` recomputation in the hot loop

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:242,256,257`
**Issue:** Inside the per-topic loop, `[c.name for c in schema.columns]` (line 242),
`{c.name for c in schema.columns}` (line 256, `schema_names`), and the heavy-blob set
comprehension (line 257) each re-walk `schema.columns`. The alias step (line 207) also
builds `{c.name for c in schema.columns}` independently. These are tiny (column counts
are small) so it is not a performance finding, but the same derived set is computed up
to four times. Minor duplication; a single `names = {c.name for c in schema.columns}`
reused for `schema_names` and the `columns_by_table` value would tighten it.
**Fix:** Optional — compute the column-name set once per schema (or cache it on the
hoisted `schemas_by_table` entries) and reuse.

### IN-03: `import re` repeated inside individual test functions

**File:** `tests/test_backend_alias.py:88,98,108,149,157,168,191,206` (and similar)
**Issue:** Many alias tests do `import re` *inside* the test body rather than once at
module top. This is harmless (idempotent import) and is a common pytest style, but it
is inconsistent — the file already imports `pytest`, `sys`, `Path` at top. Not a defect.
**Fix:** Optional — hoist `import re` to the module header for consistency.

### IN-04: `count(*)` projection-disable and the `has_star` semantics are undocumented at the call site

**File:** `packages/rosbagger-core/src/rosbagger_core/backend/query.py:258`
**Issue:** The `if star:` branch comment (lines 252-255) explains the `SELECT *`
projection opt-out and the Pitfall-4 reasoning thoroughly, but does not mention that
`has_star` is also `True` for `count(*)` and other aggregate stars — the exact case
behind WR-02. A reader of this branch would reasonably assume `star` means a literal
`SELECT *`. Documenting the broader `has_star` semantics here (or fixing WR-02) would
prevent a future maintainer from re-introducing the assumption.
**Fix:** Add a sentence to the branch comment noting `star` is true for any `exp.Star`
(including `count(*)`), cross-referencing WR-02.

---

_Reviewed: 2026-05-23T05:40:01Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
