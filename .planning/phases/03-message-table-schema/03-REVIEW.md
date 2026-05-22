---
phase: 03-message-table-schema
reviewed: 2026-05-22T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - packages/rosbagger-core/src/rosbagger_core/schema/__init__.py
  - packages/rosbagger-core/src/rosbagger_core/schema/flatten.py
  - packages/rosbagger-core/src/rosbagger_core/schema/identifiers.py
  - packages/rosbagger-core/src/rosbagger_core/schema/model.py
  - packages/rosbagger-core/src/rosbagger_core/schema/names.py
  - packages/rosbagger-core/src/rosbagger_core/schema/types.py
  - tests/test_schema_arrow.py
  - tests/test_schema_flatten.py
  - tests/test_schema_names.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-05-22
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the Phase 3 message-to-table schema layer (`schema/` subpackage) and its three test files. The core data path is correct and well-tested: the ROS Nodetype to pyarrow type map, dotted-name flattening, LIST / LIST-of-STRUCT handling, the four standard columns, the structural heavy-blob predicate, and the lazy `include` seam all behave as specified and were verified empirically against the real `rosbags` ROS 2 Humble typestore and the project fixtures (58 schema tests pass at 93% coverage). The security-critical `quote_ident` SQL-identifier defense (T-03-06) is sound — it correctly doubles embedded quotes across adversarial inputs including `x"; DROP TABLE y;--`, control chars, and backslash combos. The offline-import invariant holds. The timestamp materialization (`t`/`stamp` from raw int-ns) round-trips with no unit error.

Three robustness defects were found, none in the happy path. The most concrete is a duplicate-column crash in `build_arrow_table` when a message body field collides with a standard column name (`t`/`t_ns`/`stamp`/`topic`). The recursion / cycle guard advertised by the module docstrings and the threat model (Pitfall 5, DoS mitigation) is non-functional — `arrow_type_of`'s NAME branch has no guard at all, and the `_walk_fields` `seen` guard routes detected cycles straight back into the unguarded `arrow_type_of`. And `arrow_type_of` raises a bare `KeyError` on unknown / `float128` base types despite docstrings claiming `float128` is gracefully "omitted". Three INFO items cover a latent collision-resolution seam and untested (in one case, untested-AND-broken) defensive branches.

No BLOCKER-severity issues: stock ROS message types do not trigger the warnings, and `rosbags`'s own definition registration fails first on self-referential types, so the recursion gap is not readily exploitable in practice.

## Warnings

### WR-01: `build_arrow_table` crashes when a body field name collides with a standard column name

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py:230-245`
**Issue:** `STANDARD_COLUMNS` prepends fixed names `t`, `t_ns`, `stamp`, `topic`. If a message body has a top-level field with one of those names (legal in ROS — e.g. a custom message with a `string topic` or `int t` field), `build_table_schema` emits two `ColumnDef`s with the same `name` (one standard with empty `ros_path`, one data column). `arrow_schema()` then produces a schema with a duplicate field name, and `build_arrow_table` mishandles it:

```python
kept = [col for col in schema.columns if col.name in arrow_schema.names]   # picks BOTH "topic" cols
values: dict[str, list] = {col.name: [] for col in kept}                   # dict collapses to ONE key
for msg in messages:
    body = flatten_message(msg.msg, schema, include=include)
    for col in kept:                                                       # iterates BOTH "topic" cols
        value = body[col.name] if _is_data_column(col) else getattr(msg, col.name)
        values[col.name].append(value)                                     # appends TWICE per message
```

Each message appends twice to the single `values["topic"]` list, so the array length is `2 * num_rows` for one logical column and `pa.array(...)` against the (length-`num_rows`) schema raises. Verified:

```
arrow_schema.names: ['t', 't_ns', 'stamp', 'topic', 'topic']
ERROR: ArrowInvalid Column 3 named topic expected length 1 but got length 2
```

This is distinct from the intentional `stamp` / `header.stamp.*` coexistence (Pitfall 6), which is safe because those names differ. Note `flatten_message` itself also silently overwrites: its dict comprehension keyed on `col.name` would collapse two same-named data columns into one (last-wins), so even reads are lossy.
**Fix:** Detect and resolve body-field names that collide with the four reserved standard names at schema-build time (prefix or suffix the body column, e.g. emit it as a normal dotted leaf and rename the clashing standard column, or namespace body columns). At minimum, make `build_arrow_table` robust to duplicate names by zipping `schema.columns` to `arrow_schema` fields positionally instead of filtering by `col.name in arrow_schema.names` and keying `values` by name:

```python
kept = [col for col in schema.columns if not col.is_heavy_blob or col.name in (include or set())]
columns: list[list] = [[] for _ in kept]
for msg in messages:
    body = flatten_message(msg.msg, schema, include=include)
    for i, col in enumerate(kept):
        columns[i].append(body[col.name] if _is_data_column(col) else getattr(msg, col.name))
arrays = [pa.array(columns[i], type=field.type) for i, field in enumerate(arrow_schema)]
return pa.table(arrays, schema=arrow_schema)
```
(The deeper fix — disambiguating the column name itself — is preferable so downstream SQL can address both columns.)

### WR-02: Recursion / cycle guard is non-functional — unbounded recursion on self-referential or deeply nested sub-message types

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/types.py:117-123` and `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py:86-92`
**Issue:** The module docstrings (`flatten.py` Pitfall 5, `types.py`) and the phase threat model (RESEARCH "Security Domain": "Malformed/odd custom message definition (deep nesting, cycles) -> DoS", mitigation "cycle-guarded flatten recursion") claim the recursion is cycle-guarded. It is not:

1. `arrow_type_of`'s `NAME` branch (`types.py:117-123`) recurses through `typestore.get_msgdef(submsgtype).fields` with **no cycle guard and no depth bound**. Any self-referential or mutually-recursive type resolved here recurses until `RecursionError`. Verified: `arrow_type_of((Nodetype.NAME, "pkg/msg/A"), ts)` on a self-referential `A` raised `RecursionError`.
2. `_walk_fields`'s `seen` guard (`flatten.py:86-92`) is partly ineffective: even when it *detects* a cycle (`submsgtype in seen`), its fallback calls `arrow_type_of(ftype, typestore)` on the `NAME` node (`flatten.py:89`) — which then recurses infinitely via path #1. For mutual recursion `A->B->A`, `_walk_fields` raised `RecursionError`, not the documented clean stop. (Also note the top-level `msgtype` is never inserted into `seen`, only discovered submessages are.)

So the advertised DoS mitigation does not exist, and the `flatten.py:89-91` cycle-detection branch is dead/ineffective (also uncovered by tests).
**Impact:** Mitigated in practice — `rosbags`'s own `register()` already hits `RecursionError` on a self-referential definition (verified), so such a type cannot be loaded through normal registration; and stock ROS interfaces are not self-referential (RESEARCH A4). A deeply nested but acyclic custom type would still recurse without bound in `arrow_type_of`. Severity is WARNING (a documented defense that is silently absent) rather than BLOCKER.
**Fix:** Either (a) implement the guard for real — thread a `seen`/depth parameter through `arrow_type_of`'s `NAME` recursion and raise a clear `ValueError`/custom error on cycle or excessive depth, and remove the broken `_walk_fields` fallback path; or (b) if the guard is genuinely unnecessary because `rosbags` is the upstream gate, delete the dead `seen` machinery and the cycle-guard docstring claims so the code does not advertise a defense it lacks. Add a test for whichever path is chosen.

### WR-03: `arrow_type_of` raises a bare `KeyError` on unknown / `float128` base types, contradicting the documented graceful behavior

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/types.py:116`
**Issue:** `arrow_type_of` resolves `BASE` types via `ROS_BASE_TO_ARROW[payload[0]]` with no membership check. The `types.py` docstring (lines 44-47) states `'float128'` is "omitted (Arrow has no float128; add a lossy down-map only if a real bag ever surfaces one)", implying graceful handling, but `float128` is simply absent from the map. A message with a `BASE float128` field (or any unknown/future base name) raises an opaque `KeyError`:

```
arrow_type_of((Nodetype.BASE, ('float128', 0)), ts) -> KeyError: 'float128'
arrow_type_of((Nodetype.BASE, ('weird_type', 0)), ts) -> KeyError: 'weird_type'
```

The `KeyError("'float128'")` gives no context about which message/field failed or why, and the docstring oversells the robustness. Note this is inconsistent with the sibling `raise ValueError(f"unknown Nodetype {nt!r}")` at line 131, which does fail clearly.
**Fix:** Replace the bare subscript with an explicit lookup that raises an actionable error (or applies the documented lossy down-map):

```python
basename = payload[0]
try:
    return ROS_BASE_TO_ARROW[basename], False
except KeyError:
    raise ValueError(
        f"unsupported ROS base type {basename!r} (no pyarrow mapping); "
        f"known: {sorted(ROS_BASE_TO_ARROW)}"
    ) from None
```
Reconcile the docstring with the actual behavior (either down-map `float128` to `float64` as the comment suggests, or document that it raises).

## Info

### IN-01: `build_table_schema` does not apply collision resolution; distinct topics can yield identical `table_name`

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py:136-141`
**Issue:** `build_table_schema` sets `table_name=sanitize_table_name(topic)` directly, bypassing `TableNameResolver`. `sanitize_table_name` is not injective (`/a/b` and `/a.b` both -> `a_b`; `/Foo` and `/foo` collide under case-folding; `/2d` and `/t_2d` both -> `t_2d`), so two distinct topics built independently can produce `TableSchema`es with the same `table_name`. Nothing in the current codebase wires the resolver into the schema-build path (verified via grep — `TableNameResolver` is only exercised in isolation by `test_schema_names.py`).
**Fix:** This appears intentional — the resolver is a standalone tool the multi-topic Phase 4/5 wiring is expected to drive, and `build_table_schema` operates per-topic. No change required for this phase, but add a one-line note to the `build_table_schema` docstring stating that cross-topic collision resolution is the caller's responsibility (via `TableNameResolver`), so a future integrator does not assume `table_name` is globally unique.

### IN-02: Defensive branches are untested (one is also broken — see WR-02)

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/types.py:80,131` and `packages/rosbagger-core/src/rosbagger_core/schema/flatten.py:89-91`
**Issue:** Three defensive code paths have no test coverage: `_name_payload`'s tuple-fallback (`types.py:80`, the `payload[0]` branch for a hypothetical non-string NAME payload), the `raise ValueError(f"unknown Nodetype ...")` (`types.py:131`), and the `_walk_fields` cycle-guard branch (`flatten.py:89-91`). The last is doubly concerning because it is both untested and non-functional (WR-02).
**Fix:** Add targeted unit tests with a small fake typestore: one feeding a NAME payload as a 1-tuple to exercise `_name_payload`, one feeding a bogus `Nodetype` to assert the `ValueError`, and one covering whatever cycle-handling behavior WR-02 settles on. These are cheap and would have surfaced WR-02.

### IN-03: `is_heavy_blob` (public) and the inline heavy check in `arrow_type_of` duplicate the same predicate

**File:** `packages/rosbagger-core/src/rosbagger_core/schema/types.py:127-129` and `packages/rosbagger-core/src/rosbagger_core/schema/types.py:147-149`
**Issue:** The heavy-blob structural test (`SEQUENCE` whose inner is a `BASE` in `_BLOB_BASENAMES`) is written twice: inline inside `arrow_type_of` (lines 127-129) and again in the standalone `is_heavy_blob` (lines 147-149). The two are currently consistent, but duplicated logic risks drift if one is updated and the other is not. The public `is_heavy_blob` is also not called anywhere in shipped code (the schema build uses the `heavy` value returned by `arrow_type_of`), only in tests.
**Fix:** Have `arrow_type_of`'s `ARRAY`/`SEQUENCE` branch compute `heavy` by calling `is_heavy_blob(ftype)` (or extract a single shared private helper), so the predicate has one definition. Low priority — both copies are correct today and well-tested.

---

_Reviewed: 2026-05-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
