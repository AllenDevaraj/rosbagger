# Phase 11: Edit & Events - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-23
**Phase:** 11-edit-events
**Mode:** `--auto` (autonomous — all gray areas auto-selected; recommended option chosen per question, no user prompts)
**Areas discussed:** Module placement & CLI surface, Edit pipeline architecture, Edit operation semantics, Event sidecar schema & write path, events table & time-join

---

## Module placement & CLI surface

| Option | Description | Selected |
|--------|-------------|----------|
| edit+events in `rosbagger_core` + thin bagq verbs | `rosbagger_core/edit/` + `events.py`; `bagq edit`/`convert`/`events` are presentation only | ✓ |
| Separate `rosbagger-edit` package | New monorepo package with its own coverage gate | |
| Logic in the CLI | Put edit/event logic directly in bagq | |

**Auto-selected:** edit+events in `rosbagger_core`, thin `bagq edit`/`convert`/`events {add,list}` verbs.
**Notes:** Mirrors the locked Phase 9 decision (TF in `rosbagger_core/tf.py`, not a separate package) so the `--cov=rosbagger_core` gate covers it; API-first keeps CLI↔GUI parity. Separate package deferred.

---

## Edit pipeline architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Streaming AnyReader→transform→Writer; raw-copy, deserialize only on convert | Copy raw bytes losslessly when serialization matches; deserialize→reserialize for cross-format convert | ✓ |
| Always deserialize→reserialize | Deserialize every message even for same-format edits | |
| External tool (kappe / ros2 bag) | Shell out to an existing converter | |

**Auto-selected:** streaming pipeline; raw-byte copy when format matches, deserialize→reserialize only on convert; never mutate input.
**Notes:** Raw-copy is lossless + fast and avoids the typestore round-trip for trim/drop/downsample/merge. Reuses the `tools/make_fixtures.py` writer pattern + the reader's raw `AnyReader` stream. "Always deserialize" rejected (slower, lossy risk); shelling out rejected (offline-Python, no external dep, "never rebuild but own the pipeline").

---

## Edit operation semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Compose ops in one pass; trim=relative-sec, drop/keep, every-Nth downsample, implicit merge, convert via -o/--format | One read→write pass applies all requested transforms | ✓ |
| Separate subcommand per operation | `bagq trim`, `bagq drop`, `bagq merge`, … each its own pass | |
| Absolute-ns trim + rate-target downsample now | Heavier semantics up front | |

**Auto-selected:** compose in one pass; `--trim` relative seconds, `--drop`/`--keep` repeatable+exclusive, `--downsample /topic:N` (every Nth), merge implicit on multi-input, convert via output format.
**Notes:** One-pass composition is efficient and matches `bagq edit ... [ops]`. Relative-seconds trim is ergonomic (uses `reader.start_time`). Rate-target downsample / absolute-ns trim deferred to keep v1 deterministic and small.

---

## Event sidecar schema & write path

| Option | Description | Selected |
|--------|-------------|----------|
| `<bag>.events.parquet` via DuckDB-COPY writer; {t_start_ns,t_end_ns,label,note}; add/list | Reuse `output/export.py`; small fixed schema; append = read+concat+rewrite | ✓ |
| Rich/extensible event schema (arbitrary columns, JSON metadata) | Open schema from day one | |
| SQLite sidecar instead of Parquet | Store events in a `.db` sidecar | |

**Auto-selected:** `<bag>.events.parquet` via the existing Parquet writer; schema `{t_start_ns, t_end_ns, label, note}`; `bagq events add` (read+concat+rewrite) + `bagq events list`.
**Notes:** Design spec names `<bag>.events.parquet` explicitly; reusing `output/export.py` keeps it a "thin write path." Small fixed schema satisfies EVNT-01; rich/open schema deferred. Parquet (not SQLite) so the query engine reads it natively and it round-trips losslessly.

---

## events table & time-join

| Option | Description | Selected |
|--------|-------------|----------|
| Reserved `events` table; query() auto-discovers the sidecar; standard interval JOIN | `events` registers like any DuckDB relation; join on `t_ns BETWEEN t_start_ns AND t_end_ns` | ✓ |
| Custom time-join operator / function | A bespoke `EVENTS_AT(t)` UDF or join syntax | |
| Require explicit `--events PATH` flag | User passes the sidecar path each query | |

**Auto-selected:** reserved `events` table name; `query()` auto-discovers `<bag>.events.parquet`; standard SQL interval join (single-bag v1).
**Notes:** "Another table + a thin write path" (design spec) — registering `events` as an ordinary relation means native joins/filters/aggregations with no new engine. Auto-discovery (vs an explicit flag) keeps the ergonomics consistent with topic tables. Multi-bag events deferred.

---

## Claude's Discretion

- Exact module layout (`edit/` subpackage vs flat files); function/parameter names.
- The precise raw-vs-deserialize detection mechanism.
- Whether `convert` is a distinct verb or `edit --format`.
- Hard constraints on all: offline-import invariant, no-ROS fixture tests, ≥80% coverage, trusted-input/output-path boundary.

## Deferred Ideas

- Live "mark event now" (rclpy; Phases 12–13).
- GUI timeline markers / jump-points (Phase 14).
- Rate-target (Hz) downsample / time-bucketed resampling.
- Event import/export (CSV/JSON, annotate-from-query).
- Multi-bag events.
- In-place editing (always write a new output).
