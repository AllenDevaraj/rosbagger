---
phase: 04-inspect
reviewed: 2026-05-22
depth: standard
files_reviewed: 8
status: issues_found
critical: 1
warning: 2
info: 2
total: 5
---

# Phase 04: Inspect — Code Review

Reviewed 8 files at standard depth (empirically probed against fixtures). Offline invariant holds, O(1)/no-`read()` contract holds, empty-bag guard / multi-msgtype skip / Hz division guard / format-aware size all correct. Defects are in collision handling and negative-duration rendering.

## CR-01 (CRITICAL — fixed in this phase) — table-name collision resolution is dead code
`inspect.py` `collect_table_schemas` builds a `TableNameResolver` and calls `resolver.resolve(topic)` but **discards the result**; the stored `table_name` comes from `build_table_schema` → `sanitize_table_name`, which does NO collision resolution. Two distinct topics that sanitize identically (`/a/b` and `/a.b` → `a_b`) both get `table_name="a_b"` instead of `a_b`/`a_b_2` — distinct topics silently alias to one table. Data-integrity defect for the Phase 5 SQL surface; violates the documented T-03-01/T-03-02 guarantee.
**Fix:** use the resolver's return value as the table name (`dataclasses.replace(schema, table_name=resolver.resolve(topic))`), + regression test with two colliding topics. **RESOLVED in 04-03 fix commit.**

## WR-01 (WARNING — fixed in this phase) — negative whole-bag duration renders as `-1.00s`
When `count>0`, `BagInfo.duration_ns = reader.duration` is stored raw; on merged multi-bag reads with clock skew `AnyReader.duration` can be negative, and the CLI footer renders `-1.00s`. The Hz path already guards `duration_ns > 0`; `duration_ns` itself does not.
**Fix:** collapse non-positive duration to `None` in `BagInfo` (footer then renders `—`), + skewed-clock test. **RESOLVED in 04-03 fix commit.**

## WR-02 (WARNING — advisory) — empty-bag test couples to fixture quirk
`test_collect_bag_info_empty_bag_*` asserts `info.topics == []`, which only holds because the empty fixture declares no connections; `collect_bag_info` does not filter zero-count topics. Tests fixture emptiness, not the guard. Drop the assertion or add a "declared connection, zero messages" test.

## IN-01 (INFO — advisory) — multi-bag size double-counts duplicate paths
`_bag_size_bytes` sums over `reader.paths` without de-dup; passing the same bag twice doubles `size_bytes`. Consider `{p.resolve() for p in reader.paths}`.

## IN-02 (INFO — advisory) — unreachable TB branch in `_human_size` (harmless, `# pragma: no cover`).

Resolve advisory items with `/gsd:code-review 04 --fix` or fold into a later phase.
