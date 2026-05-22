---
phase: 04-inspect
plan: 02
subsystem: api
tags: [rosbags, rich, typer, schema, table-schema, inspect, cli, heavy-blob]

# Dependency graph
requires:
  - phase: 04-inspect
    provides: rosbagger_core.inspect module + RosbagsReader.typestore/topics public properties (04-01)
  - phase: 03-schema-flatten
    provides: build_table_schema / TableNameResolver / TableSchema / ColumnDef (name, arrow_type, is_heavy_blob)
  - phase: 02-bag-reader-layer
    provides: RosbagsReader/Message context-manager over AnyReader (topics metadata)
  - phase: 01-foundation
    provides: bagq typer app, fixture generator (tools/make_fixtures.py), PYTHONPATH="" run convention, >=80% coverage gate
provides:
  - "rosbagger_core.inspect.collect_table_schemas(reader) -> list[TableSchema]: per-topic sanitized table name + column schema from O(1) metadata + the typestore, multi-msgtype topics skipped"
  - "bagq tables BAG... subcommand: per-topic 'topic -> table_name' heading + rich column table (name / arrow type / lazy-blob marker), heavy blobs shown and annotated"
affects: [05-query, 07-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "API-first inspect: schema resolution in rosbagger_core.inspect via the Phase 3 layer; bagq/cli.py only renders (decision 1)"
    - "O(1) metadata + typestore only — collect_table_schemas never reader.read() (T-04-05 constant-time schema, not rows)"
    - "Multi-msgtype guard: TopicInfo.msgtype is None -> skip the topic (never pass None to build_table_schema -> KeyError) (Pitfall 4 / T-04-08)"
    - "Heavy blobs SHOWN + annotated lazy via ColumnDef.is_heavy_blob directly, not column_names(include=...) (Pattern 4 / A2)"
    - "Lazy core import inside the typer command body to keep bagq --help light"

key-files:
  created:
    - tests/test_inspect_tables.py
    - tests/test_cli_tables.py
  modified:
    - packages/rosbagger-core/src/rosbagger_core/inspect.py
    - packages/bagq/src/bagq/cli.py

key-decisions:
  - "collect_table_schemas returns Phase 3 TableSchema objects directly (decision 1 / Pattern 4) — no new dataclass; the CLI reads col.name / str(col.arrow_type) / col.is_heavy_blob and renders"
  - "Schema API imported LAZILY inside collect_table_schemas (mirrors 04-01) so inspect.py's top level stays stdlib-only and import rosbagger_core never pulls schema/pyarrow (Pitfall 5; offline guard 2/2 held)"
  - "Multi-msgtype topic (msgtype is None) is SKIPPED in tables (Pitfall 4 / A3 chose skip over per-connection fallback); proven via a duck-typed reader stub since no fixture triggers it"
  - "tables shows ALL columns including heavy blobs, marked 'lazy (blob)' (A2 confirmed) — uses ColumnDef.is_heavy_blob, never reads the blob bytes (T-04-07)"
  - "TableNameResolver.resolve(topic) is called to record the mapping/share collision state, but build_table_schema also sanitizes and is the source of the table_name on each TableSchema"
  - "orientation_covariance (ARRAY float64[9] -> list<item: double>) is correctly NOT marked lazy; only the SEQUENCE-of-uint8 Image.data (list<item: uint8>) is — confirms is_heavy_blob is structural, not a name blocklist"

patterns-established:
  - "API-first split: schema overview lives in core, CLI is a thin rich renderer"
  - "Metadata-only inspection extends to schema: O(1) topics + typestore, zero message-body deserialization"

requirements-completed: [INSP-03]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 4 Plan 2: bagq tables Summary

`bagq tables BAG...` prints each topic's sanitized table name and full column schema (name + arrow type, heavy blobs shown and marked `lazy (blob)`) by wiring a new metadata-only `collect_table_schemas` core API to the Phase 3 schema layer, with a thin rich renderer (INSP-03). Phase 4 complete (2/2).

## What Was Built

### Task 1 — `collect_table_schemas` in `inspect.py` (TDD, commit `cd16554`)
Added `collect_table_schemas(reader) -> list[TableSchema]` to the existing `rosbagger_core/inspect.py`. It reads `reader.typestore` and iterates `sorted(reader.topics.items())`, and for each single-msgtype topic resolves the table name (`TableNameResolver`) and appends `build_table_schema(info.msgtype, typestore, topic=topic)`. The result is a list of Phase 3 `TableSchema` whose `columns` carry `name` / `arrow_type` / `is_heavy_blob` for the CLI. The schema API is imported **lazily inside the function** so `inspect.py`'s top level stays stdlib-only (Pitfall 5). A topic whose `TopicInfo.msgtype is None` (multi-msgtype) is **skipped**, never passed to `build_table_schema` (which raises `KeyError: None`). The function never calls `reader.read()`. Followed RED → GREEN: the RED run failed on `ImportError: cannot import name 'collect_table_schemas'`; GREEN landed all 11 tests.

`tests/test_inspect_tables.py` (created): parametrized across `ros1` / `ros2_sqlite` / `ros2_mcap` — asserts 3 `TableSchema` with `table_name ∈ {cmd_vel, image, imu}`, matching `topic`/`msgtype`, sorted-by-topic order, the `/image` schema leading with `t`/`t_ns`/`stamp`/`topic` and a `data` column with `is_heavy_blob is True` and `str(arrow_type) == "list<item: uint8>"`. Plus a multi-msgtype guard test (duck-typed stub reader with a `None`-msgtype topic → omitted, no `KeyError`) and a no-`read()` guard (monkeypatch `reader.read` to raise).

### Task 2 — `bagq tables` command + smoke test (commit `34749c3`)
Extended `packages/bagq/src/bagq/cli.py` with an `@app.command() def tables(...)` mirroring `info`: lazily imports `collect_table_schemas` + `RosbagsReader` inside the body, opens the reader via its context manager, and renders via a new `_render_table_schemas` helper. The helper prints a `topic → table_name` heading then a `rich.table.Table` of every column (`name`, `str(arrow_type)`, and a `lazy (blob)` marker driven by `col.is_heavy_blob`) — heavy blobs are **shown and annotated, never hidden** (A2 / Pattern 4); an empty schema list prints `no topics`. `AnyReaderError`/`FileNotFoundError` propagate (Phase 7). The module docstring was updated to mention both subcommands.

`tests/test_cli_tables.py` (created): `CliRunner` smoke tests — `tables BAG` exits 0 and `result.stdout` contains `cmd_vel`/`imu`/`image`, the column `t_ns`, and the blob column `data`; the `lazy` blob marker is present; `--help` lists both `info` and `tables`; a missing bag exits non-zero; the `no topics` render branch.

Manual render confirmed the verified facts: `/cmd_vel → cmd_vel` with `linear.x..`; `/image → image` with `data: list<item: uint8>` marked `lazy (blob)`; `/imu → imu` with `orientation_covariance: list<item: double>` correctly **not** marked lazy (structural heavy-blob detection, not a name blocklist).

## Deviations from Plan

None — the plan executed exactly as written. 04-RESEARCH.md §1 had pre-verified the entire pipeline (`reader.typestore` → `build_table_schema` → `TableSchema.columns`, plus the multi-msgtype `KeyError`) against the runtime this session, so no bugs, missing functionality, or blocking issues surfaced. The Phase 3 schema layer and 04-01's reader properties supplied everything needed; Phase 4's only work was wiring (per RESEARCH "Phase 4 is almost entirely wiring").

## Authentication Gates

None — offline bag inspection, no auth/network/secrets surface.

## Verification

- `PYTHONPATH="" uv run pytest tests/test_inspect_tables.py -q` — 11 passed
- `PYTHONPATH="" uv run pytest tests/test_cli_tables.py -q` — 5 passed
- `PYTHONPATH="" uv run pytest -q` (full suite, coverage gate `--cov-fail-under=80` incl. `--cov=bagq`) — **126 passed at 97.84%**; `cli.py` and `inspect.py` both 100%
- `PYTHONPATH="" uv run pytest tests/test_offline_guard.py -q` — 2 passed (`import rosbagger_core` pulls no `rosbags`/`pyarrow`; schema import stays lazy inside `collect_table_schemas`)
- `PYTHONPATH="" uv run ruff check .` — All checks passed
- Manual: `bagq tables <ros1 fixture>` prints all three table names + column schemas with `data` marked lazy (INSP-03)

> Note on single-file coverage: running one test file alone trips the project-wide 80% gate (it can't exercise the whole tree); the **full-suite** run is the authoritative gate and passed at 97.84%. This is the by-design behavior documented since 02-03.

## Threat Model Outcomes

| Threat ID | Disposition | How handled |
|-----------|-------------|-------------|
| T-04-05 (DoS — huge bag) | mitigated | `collect_table_schemas` reads only `reader.topics` metadata + the declared msgtype/typestore; never `reader.read()`. Proven by `test_collect_table_schemas_does_not_read_messages` (monkeypatched `read` raises). |
| T-04-06 (injection — hostile topic name) | mitigated | Table names go through Phase 3 `TableNameResolver`/`sanitize_table_name` (`[0-9A-Za-z_]` allow-list); `tables` only prints them. No SQL built in Phase 4. |
| T-04-07 (heavy-blob disclosure) | mitigated | `tables` lists the blob column's NAME + TYPE only (`data: list<item: uint8>`), annotated lazy — never the bytes (no row materialization). |
| T-04-08 (crash — multi-msgtype) | mitigated | `info.msgtype is None` skipped before `build_table_schema`; proven by `test_multi_msgtype_topic_is_skipped_not_crashing`. |
| T-04-SC (supply chain) | mitigated | No new packages — `rosbags`/`rich`/`typer` already audited. No install step. |

## Known Stubs

None — `collect_table_schemas` returns real `TableSchema` objects wired to live reader metadata and the typestore; the CLI renders them directly. No placeholder/empty-data paths.

## Self-Check: PASSED

All created/modified files exist on disk (`inspect.py`, `cli.py`, `tests/test_inspect_tables.py`, `tests/test_cli_tables.py`, `04-02-SUMMARY.md`); both per-task commits (`cd16554`, `34749c3`) are present in the git log.
