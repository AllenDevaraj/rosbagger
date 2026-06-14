# SUMMARY — Quick 260614-5el — Batch 5: GUI/TUI lifecycle & threading races

**Date:** 2026-06-14 · **Status:** complete · **Commits:** b40810f, 16456a1, a965385, 180f0a2, 4d0fb07, 06d15d7, a051b2b, 546d502

The highest-risk overhaul batch (teardown/threading/rclpy-lifecycle). Each finding was
re-grounded in current code and the proposed fix **adversarially verified by a workflow**
(8 findings × investigate→verify, 18 agents) — which corrected my initial approach on
nearly every tricky one. The *verified* fixes shipped, each with a regression test where
offline-testable and an atomic commit. Full offline suite **687 passed / 5 skipped**.

## Fixes

### C2 / C5 — record.py WR-04 re-entrant rclpy lifecycle (CORRECTNESS) · b40810f
`record()`/`list_topics()` called `rclpy.init()`/`shutdown()` unconditionally → killed a shared
replay context (C2) and raised "context already initialized" on replay-then-record (C5). Now the
proven `created_ctx = not rclpy.ok()` guard. Standalone CLI unchanged. 3 mocked tests.

### C1 / C6 / C7 — serialize the shared publish sink (CRASH) · 16456a1
The drive worker and a UI-thread `republish_static` (seek/skip/RViz re-prime) both called
`sink()` on one node → InvalidHandle / use-after-free. A `threading.Lock` inside
`build_publish_sink` now serializes the publish (never nests with the scheduler lock). Fixes all
3 republish sites + the TUI (shared path). **Replaced my flawed pause+stop+restart-drive fix.**

### C3 — join offline-panel workers before closing the reader (CRASH) · a965385
`_open_reader`/`closeEvent` closed the shared reader while query/inspect/tf `BlockingWorker`
threads still iterated it (use-after-free / SIGBUS). Now `stop_thread()`s them first / closes the
panels first. **Broader than first thought (inspect+tf too).** Ordering-contract test.

### newE21 — discard/refuse stale query results after a bag swap (DATA) · 180f0a2
Reader-identity guards (`_query_reader`/`_result_reader`, `is` + held ref) drop a result whose
reader was swapped (File▸Open) and refuse export of a prior bag's rows. **Replaced my flawed
generation-counter** (false-positived on tab switches, missed cross-panel + export). 2 tests.

### F7 — cache the query schema tree by reader identity (PERF) · 4d0fb07
Rebuilt on every Query-tab visit; now cached on the reader OBJECT (held ref + `is` — **not
`id()`**, which the verifier showed is unsound: freed-address reuse → stale schema). Both panels.
Desktop + TUI tests.

### F6 (second half) — TUI query off the event loop (PERF) · 06d15d7
`query()` ran synchronously on the Textual loop. Now `@work(exclusive=True, thread=True,
group="query-run")` + a re-entrancy guard (the shared apsw handle is unsafe for two concurrent
query workers; exclusive alone insufficient). The 2 existing query tests switched to
`await app.workers.wait_for_complete()` (pause() is a CPU-idle heuristic that breaks early on I/O).

### F1 — replay markers via O(1) reader times, not a full decode (PERF) · a051b2b
`_load_markers` called `load_items` (full decode) just for first/last timestamps. Now uses
`reader.start_time`/`end_time` + an empty-bag guard (`message_count == 0`, else the `2**63-1`/`0`
sentinels make garbage — cf. newA8). Both panels. The obsolete typestore-threading test replaced.

### C8 — cooperative early-stop so quit-during-record doesn't freeze the UI · 546d502
`stop_thread` quit()+wait() couldn't break the recorder's native spin loop → up to ~10s UI freeze
on quit. An OPT-IN `stop_event` on `record()`/`_run` (default None = unchanged) lets `closeEvent`
end the loop promptly; the bag still finalizes. **Replaced my flawed stop_thread-timeout** (would
abandon a running QThread → SIGABRT + unfinalized bag). 2 mocked tests.

## Verification
- `tests/test_record_unit.py` 35 · `tests/test_desktop.py` 91 · `tests/test_gui.py` 8 — all pass.
- Full offline suite: 596 (non-Qt) + 91 (`test_desktop.py`, Qt offscreen) = **687 passed**, 5 skipped.
- ROS-lifecycle fixes (C2/C5/C1/C6/C7/C8) aren't run by the offline suite (live tests skipped);
  mocked tests cover the WR-04 + stop_event logic; the rest is the verified specs + code reasoning.
- Offline-import guard unaffected (threading is stdlib; the GUI/record imports stay lazy).

## Remaining overhaul
Batch 6 (replay_panel/BagSession refactor S2/S4/S5/R5/R8/T6), Batch 2e (error/capability dedup
R4/R6/R7/T7), T4 version-sync.
