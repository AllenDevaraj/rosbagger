# Quick 260614-5el — Batch 5: GUI/TUI lifecycle & threading races

The highest-risk overhaul batch. Each finding was re-grounded in CURRENT code and the proposed
fix ADVERSARIALLY VERIFIED by a workflow (8 findings × investigate→verify) — which corrected
several of my initial approaches. The verified fixes (not the originals) are below.

## Verified fixes (atomic commits)

### C2 / C5 — record.py: unconditional rclpy.init()/shutdown() (WR-04) — `record.py`
`record()` (init 259 / shutdown 291) and `list_topics()` (305/313) call `rclpy.init()`/`shutdown()`
unconditionally — killing a SHARED context a live replay node joined, and raising "context already
initialized" on replay-then-record in the TUI. Fix: the proven WR-04 `created_ctx = not rclpy.ok()`
guard (init only if we created it; shutdown only that). Fix the now-contradicting docstrings.
Verifier: fix code CORRECT; mocked tests unaffected. Test: a mocked test asserting init/shutdown
are SKIPPED when `rclpy.ok()` is already True (created_ctx=False) and called when False.

### C1 / C6 / C7 — concurrent sink calls on one node — `replay.py build_publish_sink`
The drive worker calls `sink(item)` on its thread (scheduler releases its lock before publish) while
a UI-thread `republish_static` (live seek/skip, RViz re-prime) also calls `sink(item)` → concurrent
`pub.publish()` + `pubs` mutation + `published['n'] += 1` on one node. **My original fix (pause+stop+
restart the drive thread) was FLAWED** (collides with the async `_on_drive_finished`, regresses the
Phase-18 live-seek-while-playing contract, contradicts `_enable_rviz_fidelity`). Verified fix: serialize
the SINGLE shared sink with a `threading.Lock` inside `build_publish_sink` (wrap the sink body). Never
nests with the scheduler lock (released before the sink call) → no deadlock. Fixes all 3 call sites at
once; the TUI benefits too (same shared path). No drive-lifecycle change.

### C3 — reader closed while offline-panel workers iterate it — `main_window.py`
`_open_reader` closes the old reader, and `closeEvent` closes the reader, while a query/inspect/tf
`BlockingWorker` may still be iterating it (sqlite cursor / mmap'd MCAP) → use-after-free / the known
offscreen SIGBUS. Verified fix (3 edits): import `stop_thread` in the FIRST-PARTY group (ruff isort);
in `_open_reader`, `stop_thread()` the query/inspect/tf threads BEFORE `reader.close()`; in `closeEvent`,
`close()` the inspect/query/tf panels (running their `stop_thread` teardown) BEFORE `reader.close()`.
(Broader than first thought — inspect & tf also run reader-iterating workers.)

### newE21 — stale query result/export after a bag swap — `query_panel.py`
Open bag A, run a slow query, File▸Open bag B → A's result lands / Export writes A's rows under B.
**My generation-counter-in-refresh_view was WRONG** (false-positives on tab switch, misses the
cross-panel path, ignores the export-of-prior-result harm). Verified fix: READER-IDENTITY guards
(`is`, with a HELD reference — sound, unlike F7's id()): `_query_reader` (the reader a run was launched
against — discard a result if it no longer matches `_reader()`), `_result_reader` (the reader
`_last_result` belongs to — `_export` refuses if it no longer matches). UI-thread only; offline-testable.

### F7 — schema tree rebuilt on every Query-tab visit — `query_panel.py` + TUI `query.py`
`showEvent`→`refresh_view` re-walks `collect_table_schemas` each visit. Verifier: severity overstated
(O(1) metadata, µs) and **`id(reader)` keying is UNSOUND** (CPython reuses freed addresses → stale
schema). Fix: cache keyed on the reader OBJECT IDENTITY (held ref, `is`) — rebuild only when the reader
object changes; a new bag (new object) still rebuilds (load-bearing for a hidden panel's next show).

### F1 — full bag decode for scrubber span/markers on the UI thread — `replay_panel.py` + TUI `replay.py`
`_load_markers` calls `load_items()` (full decode) just for first/last timestamps. Fix: use the reader's
O(1) `start_time`/`end_time` for the span. Verifier BLOCKER: must restore an empty-bag guard via
`reader.message_count == 0` (else AnyReader's `2**63-1`/`0` sentinels make garbage fractions when an
events sidecar exists). Caveat (note in comment): `end_time = last+1` / ROS2 `start_time` from metadata
differ ~1ns from the load_items span — sub-pixel, acceptable; no O(1) exact span exists.

### F6 (second half) — TUI query() blocks the event loop — TUI `query.py` + `tests/test_gui.py`
`_run_query` runs `query()` synchronously on the Textual loop. Fix: move to
`@work(exclusive=True, thread=True, group="query-run")` + a `_drive_running`-style re-entrancy GUARD
(the App's ONE shared reader/apsw connection is unsafe for two concurrent query workers; exclusive
alone doesn't help — a cancelled thread keeps iterating). Marshal result/error back via
`call_from_thread`. Verifier: the 2 existing query tests MUST switch `pilot.pause()` →
`await app.workers.wait_for_complete()` (pause() is a CPU-idle heuristic that breaks early while the
worker blocks on I/O → flaky empty table).

### C8 — record close blocks the UI up to ~10s — `record.py` + `record_panel.py`
`stop_thread` does unbounded `wait()`; the record worker's `while rclpy.ok(): spin_once()` loop has no
early-stop, so quit-during-record blocks the UI for the full bounded duration. **My timeout-on-
stop_thread fix was FLAWED** (would abandon a still-running child QThread → SIGABRT + unfinalized bag;
the blocking join is load-bearing for SC3 finalization). Verified fix: a COOPERATIVE early-stop — an
OPT-IN `stop_event` param on `record()`/`_run` (default None = byte-for-byte today); `record_panel`
creates one, passes it, and `.set()`s it in `closeEvent` BEFORE `stop_thread` so the loop exits
promptly, `writer.close()` finalizes the bag, and the unbounded `wait()` joins immediately. No
`stop_thread` change.

## Verification
- Offline suite (`PYTHONPATH=""`) + Qt offscreen (`test_desktop.py`) + TUI (`test_gui.py`).
- ROS-lifecycle fixes (C2/C5/C1/C6/C7/C8) aren't exercised by the offline suite (live tests skipped);
  mocked tests cover the WR-04 + stop_event logic; the rest is code-reasoning + the verified specs.
- Atomic commit per finding; SUMMARY + STATE row at the end.

## Remaining overhaul after this: Batch 6 (replay_panel/BagSession refactor S2/S4/S5/R5/R8/T6),
Batch 2e (error/capability dedup R4/R6/R7/T7), T4 version-sync.
