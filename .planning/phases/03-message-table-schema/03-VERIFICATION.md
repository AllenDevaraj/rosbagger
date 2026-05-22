---
status: passed
phase: 03-message-table-schema
verified: 2026-05-22
method: inline (gsd-verifier disabled + not installed; orchestrator verified must-haves against the live codebase + ran the suite)
must_haves_total: 4
must_haves_verified: 4
plans_complete: 3
requirements: [QURY-01, QURY-02, QURY-03, QURY-04, QURY-07]
---

# Phase 03: Message→Table Schema — Verification

Phase goal: flatten ROS messages into a DuckDB-friendly (backend-neutral pyarrow) table schema —
sanitized table names, dotted/quoted columns, LIST/STRUCT arrays, always-present time columns,
lazy heavy-blob handling. (Schema only; DuckDB execution is Phase 5.)

## Success Criteria (verified against the live codebase + fixtures)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | A nested message maps to dotted/quoted columns with correct types | `build_table_schema('/cmd_vel' Twist)` → `linear.x..angular.z` (all float64); `quote_ident('weird"name')`→`"weird""name"` | ✓ |
| 2 | Array fields → LIST; sub-message arrays → LIST of STRUCT | `arrow_type_of`: ARRAY/SEQUENCE→`pa.list_`, NAME→`pa.struct`; Imu covariance→`list<double>`; verified LIST<STRUCT> via TFMessage | ✓ |
| 3 | Every table has `t`,`t_ns`,`stamp`,`topic`; `/a/b`→table `a_b` | first 4 columns == `[t,t_ns,stamp,topic]` (timestamp ns / int64 / timestamp ns / string); `sanitize_table_name('/camera/image_raw')`→`camera_image_raw`, `/a/b`→`a_b`, collisions→`a_b_2` | ✓ |
| 4 | Heavy byte blobs excluded unless explicitly requested | structural `is_heavy_blob` (SEQUENCE of uint8/byte/char): `/image data`→excluded by default, re-added via `include={"data"}`; `float64[9]` covariance NOT a blob | ✓ |

## Automated Checks (`PYTHONPATH=""`)

- `uv run pytest`: **88 passed, 96.43% coverage** (gate 80%)
- build (`py_compile` schema/*.py): pass · ruff check + format: clean (23 files)
- End-to-end: `/cmd_vel` Message stream → `pa.Table` (3 rows, dotted columns); offline guard 2/2; `import rosbagger_core` does not load `schema/`

## Non-Blocking Quality Follow-ups (from 03-REVIEW.md — advisory)

- **WR-01 (IMPORTANT — address in/before Phase 5):** `build_arrow_table` raises `ArrowInvalid` if a message body field is literally named `t`/`t_ns`/`stamp`/`topic` (legal in ROS — collides with the injected standard columns). Standard fixtures don't trigger it, but **Phase 5 runs `build_arrow_table` on arbitrary user bags**, so handle the collision (e.g. reserve the 4 standard names and disambiguate/prefix a colliding body column) when wiring the QueryBackend. Carry this into Phase 5 planning.
- WR-02: advertised cycle/recursion guard is non-functional (dead branch in `_walk_fields`; `arrow_type_of` NAME branch unguarded). Mitigated because `rosbags.register()` rejects self-referential defs first. Either implement the guard or drop the claim.
- WR-03: unknown/`float128` base type raises a bare `KeyError` (docstring claims graceful omission) — make it a `ValueError` with field context.
- IN-01/02/03: `build_table_schema` bypasses `TableNameResolver` (per-call, no cross-topic collision resolution — Phase 4/5 should own the resolver); untested defensive branches; duplicated blob predicate.

Resolve with `/gsd:code-review 03 --fix`, or fold WR-01 into Phase 5.

## Notes

- CI execution still pending push/`gh` auth (pre-existing); suite green locally.
- Local runs require `PYTHONPATH=""` (ROS-sourced host); not baked into committed code/CI.
- 03-03 used TDD (RED→GREEN) per the planner's `tdd` task markers.

## Verdict

**PASSED** — all 4 success criteria verified; QURY-01/02/03/04/07 delivered and proven by 88 ROS-free tests at 96.43% coverage. The schema layer emits backend-neutral pyarrow with verified DuckDB round-trip, identifier safety, and the lazy-blob seam for Phase 5. WR-01 is a real latent edge-case crash flagged for Phase 5; the other findings are advisory quality items.
