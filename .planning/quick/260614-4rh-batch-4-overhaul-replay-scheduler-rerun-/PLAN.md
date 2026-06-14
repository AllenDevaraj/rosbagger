# Quick 260614-4rh — Batch 4: replay scheduler + rerun converter bugs

Part of the whole-codebase overhaul (review pipeline, 55 confirmed findings). Batch 4
covers the replay scheduler + rerun converter correctness/performance bugs. Each fix gets
a regression test and an atomic commit.

## Findings in this batch

### newD9 — region loop: bag-relative offsets compared against absolute t_ns (CORRECTNESS)
`Replayer.set_loop_region(in_ns, out_ns)` documents+stores **absolute** t_ns, but BOTH callers
pass **bag-relative** offsets:
- CLI `replay.py:273` → `set_loop_region(int(region_start*1e9), int(region_end*1e9))` (seconds from bag start)
- Desktop `replay_panel.py:1067` (`_region_abs_ns`) → `int(frac*bag_span_ns)` (t0-relative)

`seek(t_offset_ns)` already takes a **relative** offset (adds `items[0].t_ns` internally). The
region setter's absolute contract is the odd one out, so on a real bag (t0 = huge ROS stamp)
`items[cursor].t_ns > _loop_out_ns` is ALWAYS true → the scheduler wraps after every publish.
Fixture tests only used t0==0 streams, masking it.

**Fix:** make `set_loop_region` treat its bounds as **bag-relative** (add `items[0].t_ns`
internally, exactly like `seek`). Both callers become correct with one change and the two
position-setters share one basis. Update docstrings + the desktop/CLI comments. New regression
test with a NON-zero t0 stream.

### newD13 — single-item / zero-span loop busy-spins at 100% CPU (QoL/perf)
In `run()`, `do_pace = cursor > 0 ...`. A loop wrap rewinds the cursor to 0, so for a one-message
(or all-equal-timestamp) looping bag the cursor is ALWAYS 0 → never paces → republishes as fast
as the CPU allows.

**Fix:** add `_is_zero_span_loop()` (looping active AND `items[-1].t_ns == items[0].t_ns`) and,
when a wrap republish has no Δt to pace by, floor the republish interval to a CPU-friendly
`_DEGENERATE_LOOP_PERIOD_S` (scaled by rate). Normal multi-item pacing is untouched (the new
branch only fires for a genuine zero-span loop after the first publish). New regression test
asserts the floor sleep is applied (a recording sleep) instead of spinning.

### newD16 — TUI replay panel silently coerces a bad rate to 1.0 on Play (QoL)
The desktop panel already validates-or-rejects (`_validated_rate`, tested). The TUI
`gui/panels/replay.py` `_read_rate()` silently coerces a non-numeric / `<=0` entry to 1.0 at
transport-build time (line 163) and reports `"Playing… rate 1"` — the Enter handler teaches but
Play does not.

**Fix:** mirror the desktop contract — `_parse_rate()` raises on bad/`<=0`; `_ensure_transport`
validates up front and teaches `"Invalid rate …"` + refuses to build; `_play` reports the
Replayer's ACTUAL rate. Remove the silent `_read_rate`. New GUI test.

### F4 — `seek` linear-scans the whole item list under the lock (perf)
`seek` (and the region in-bound scan) do an O(n) `next(i for ...)` under `_lock`. Items are
non-decreasing in t_ns, so a binary search is O(log n) and shortens lock hold time on a large bag.

**Fix:** `_first_index_at_or_after(t_ns)` via `bisect.bisect_left(..., key=lambda it: it.t_ns)`
(Python ≥3.10, a project floor). Used by `seek` + the region wrap scan. Identical semantics
(first item ≥ target; `len` past the end).

### F5 — rerun `_pointcloud2_xyz` does 3 `struct.unpack_from` per point (perf)
Per-point Python unpack is O(n) interpreter overhead — minutes for a 100k+ point cloud.

**Fix:** vectorize with a NumPy structured-dtype view over the buffer (one C-level pass),
honoring `is_bigendian`, `point_step`, field offsets, and the truncated-buffer guard exactly.
`struct` drops from the module (numpy stays lazy-imported inside the helper — rerun/offline
invariant intact). New big-endian + truncation test.

## Verification
- `PYTHONPATH="" uv run pytest tests/test_replay_unit.py tests/test_rerun_unit.py tests/test_gui.py -q --no-cov`
- Full offline suite green; offline-import guard unaffected (numpy lazy; scheduler stdlib-only).
- Atomic commit per logical fix; SUMMARY.md + STATE.md row at the end.
