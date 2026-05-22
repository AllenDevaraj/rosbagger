---
status: passed
phase: 06-output-export
verified: 2026-05-22
method: inline (gsd-verifier disabled; orchestrator verified must-haves against the live codebase + ran the suite + end-to-end bagq query)
must_haves_total: 3
must_haves_verified: 3
plans_complete: 2
requirements: [OUT-01, OUT-02, OUT-03, OUT-04]
---

# Phase 06: Output & Export — Verification

Phase goal: render and export query results (`bagq query`): stdout table, CSV/Parquet export, minimal `--plot`.

## Success Criteria (verified against the live codebase + fixtures)

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | Results print as a formatted table to stdout (OUT-01) | `bagq query 'SELECT topic FROM image' BAG` renders a rich table; temporal-safe (`timestamp[ns]`→datetime64 via `to_numpy`); 0-row → `(0 rows)` | ✓ |
| 2 | `-o out.csv` and `-o out.parquet` write correct files (OUT-02/03) | `bagq query ... -o out.csv` → 3 rows read back via csv.DictReader; `-o out.parquet` → 3 rows / 20 cols (incl dotted `orientation.x`) via `pq.read_table`; both via DuckDB `COPY` | ✓ |
| 3 | `--plot` emits a line chart of numeric columns vs `t` (OUT-04) | `bagq query 'SELECT t_ns, "linear.x" FROM cmd_vel' --plot chart.png` → 23.5 KB PNG; headless `Agg`; numeric cols vs `t_ns`; matplotlib graceful-missing | ✓ |

## Automated Checks (`PYTHONPATH=""`)

- `uv run pytest`: **219 passed, 98.04% coverage** (gate 80%); phase-6 modules at 100%
- ruff check + format: clean (44 files); offline guard extended + green (`import rosbagger_core.output`/`bagq.cli` pull no duckdb/pyarrow/matplotlib)
- matplotlib added to the dev group (testable) while staying the `bagq[plot]` extra for the base install; `uv.lock` committed

## Non-Blocking Quality Follow-ups (from 06-REVIEW.md — advisory; carry to Phase 7)

- **WR-02 (PORTABILITY — fold into Phase 7):** `--format csv` WITHOUT `-o` streams via `COPY TO '/dev/stdout'` — writes at OS fd 1 (bypasses `sys.stdout`) and is **non-portable to Windows** (no `/dev/stdout`), contradicting the CLAUDE.md "runs anywhere" constraint. Does NOT affect OUT-02 (the `-o out.csv` *file* path works). Fix: buffer the CSV in core and `echo`/`click.echo` it through Python. Phase 7 touches `cli.py`'s `query` command (teaching errors) — fix it there.
- **WR-01 (robustness — fold into Phase 7):** `export.write_table` parses the `-o` extension via `rsplit(".",1)` over the whole path, so a dotted directory + extensionless file yields a garbage extension/error. Fix: `os.path.splitext(os.path.basename(path))`.
- WR-03: the `--format csv` stdout branch is uncovered (a consequence of WR-02 — fd-level output is invisible to CliRunner). Resolved by the WR-02 fix.
- IN-01..04 (info): `--plot ""` writes a hidden `.png`; `--plot FILE` w/o extension reports a wrong "Wrote" path (matplotlib appends `.png`); `to_json` would `TypeError` on a `binary` column (not reachable via current schema); subset-run coverage-gate artifact (modules are 100%).

Resolve with `/gsd:code-review 06 --fix`, or fold WR-01/WR-02 into Phase 7.

## Notes

- The user's SQL is the trusted local-CLI interface; the one SQL-building surface (`COPY ... TO '<path>'`) escapes `'`→`''` (T-06-01, verified). CI execution still pending push/`gh` auth; suite green locally. Local runs need `PYTHONPATH=""`.

## Verdict

**PASSED** — all 3 success criteria verified; OUT-01..04 delivered by 219 ROS-free tests at 98.04% coverage. `bagq query` renders to stdout, exports correct CSV/Parquet files (the OUT-02/03 `-o` path), and emits a minimal headless plot. WR-02 (csv-to-stdout Windows portability) and WR-01 (extension parsing) are real but non-goal-blocking — carried to Phase 7's CLI work.
