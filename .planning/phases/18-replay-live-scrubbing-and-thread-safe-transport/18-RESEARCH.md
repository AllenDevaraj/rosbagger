# Phase 18 Research: Replay Live Scrubbing & Thread-Safe Transport

**Phase:** 18 (REP-02). Verified by source read + a parallel investigation workflow (2026-05-28). No unknowns remain; the design below is decided. Planner/executor: implement as written.

## 1. Current architecture (anchors)

**scheduler.py (`rosbagger_replay`)** — `Replayer` is stdlib-only (imports `time`, `enum`, `collections.abc`). 4-state machine `State{PLAYING,PAUSED,STEPPING,DONE}` (`:45`), starts PAUSED (`:112`). Controls: `play`(`:150`) `pause`(`:154`) `step`(`:158`) `set_rate`(`:162`) `seek(t_offset_ns)`(`:168-182`, the ONLY position-setter, W3); `loop` is a plain public attr (`:108`). Reads: `state`(`:115`) `cursor`(`:121`) `position_fraction`(`:126-142`, TIME fraction [0,1]) `rate`(`:145`). `run()`(`:185-237`) blocking: per item beyond the first sleeps `dt_ns/1e9/rate` via the INJECTABLE `self._sleep`(`:210-212`); bound guards (`max_messages`/`duration`, `is not None`) fire BEFORE the loop reset -> DONE wins over loop (W4, `:217-232`); seek-past-end -> cursor==len -> clean DONE (Pitfall 6, `:233-237`). `clock`/`sleep` injected for tests.

**replay.py** — `replay()` builds `Replayer`, maps `--start` sec -> `seek(int(start*1e9))`(`:166`), then `play()`+`run()`; calls controls SYNCHRONOUSLY before run() (must stay synchronous when not running). `build_publish_sink`(`:39-87`) is the single publish path — UNTOUCHED by Phase 18.

**replay_panel.py (`rosbagger_desktop`)** — module top imports only PySide6+stdlib+local (offline/Qt-free, `:35-57`). Has Play/Pause/Step, rate QLineEdit, loop QCheckBox, `Scrubber.seeked(fraction)` (`:93-120`). `_ensure_transport`(`:230`) lazy-builds Replayer+sink. `_start_drive`(`:498`) runs `run()` on a BlockingWorker/QThread; `_on_drive_done`(`:555`) pushes final playhead+status; `_on_drive_finished`(`:540`) clears ref + re-enables controls. `_on_seeked`(`:423`) -> seek + `_update_position`. `_update_position`(`:443`) reads `position_fraction` -> `scrubber.set_position`.

## 2. The two gaps

- **A — no live playhead:** `_update_position()` only runs on seek and at DONE; `run()` blocks the worker with no mid-flight position -> playhead sits still then snaps to end.
- **B — controls blocked mid-play:** `_on_seeked`(`:431`), `_apply_rate`(`:387`), `_apply_loop`(`:412`) reject when `_drive_running()`; `_start_drive` also DISABLES rate+loop (`:519-520`). Root cause: `Replayer` is non-thread-safe (CR-02) — `run()` reads/writes `_cursor`/`_state`/`_rate`/`loop` on the worker; UI-thread mutation races (esp. cursor read-modify-write `:214-215` vs concurrent `seek`).

## 3. Recommended design

### 3a. Scheduler thread-safety (lock + interruptible wait + advance guard)
Chosen over a command-queue because it PRESERVES synchronous control semantics (existing tests call `seek()` then read `cursor` immediately) while making run() race-free + responsive.
- `__init__`: add `self._lock = threading.Lock()` and `self._wake = threading.Event()`.
- Setters stay SYNCHRONOUS but lock-guarded: wrap `play/pause/step/set_rate/seek` bodies in `with self._lock:` and call `self._wake.set()` after mutating; convert `loop` to a property whose setter mutates under the lock + wakes (keep the name `loop` so `replayer.loop = x` is unchanged). Reads stay lock-free (atomic single-attr).
- Interruptible pacing WITHOUT breaking the seam: keep the `sleep` param injectable; if not overridden, bind the DEFAULT `self._sleep` to a method `_interruptible_sleep(s)` = `self._wake.wait(timeout=s); self._wake.clear()`. Tests still inject a recording sleep.
- `run()` restructure: hold the lock ONLY for fast cursor/state/rate reads + cursor advance + bound/loop/DONE transitions; NEVER across `sink()` or `sleep()`. Advance with the cursor-unchanged guard: `if self._cursor == idx: self._cursor = idx + 1` (fixes the lost-update at `:214-215`). Re-read state after the wait (honor a pause/seek that arrived mid-wait). Preserve W3/W4/WR-01/WR-02 + zero/neg special-case + Pitfall 6 + step=one-then-pause + D-08 pacing.

### 3b. Live playhead (desktop) — QTimer
No scheduler change for position (cursor read is atomic). Add a UI-thread `QTimer` started in `_start_drive`, stopped in `_on_drive_finished` AND `closeEvent`, firing ~60ms -> `_update_position()`. Ensure programmatic `set_position` does NOT re-emit `seeked` (check `widgets/`; add a guard if needed).

### 3c. Remove mid-play blocks + backward honesty (desktop)
Delete the `_drive_running()` rejection in `_on_seeked`/`_apply_rate`/`_apply_loop`; stop disabling rate+loop in `_start_drive` (`:519-520`) and keep them enabled. `_on_seeked` while playing -> just `replayer.seek(...)` + status "Seeking to N% — resuming forward." (jump + forward replay, never a rewind claim).

## 4. Pitfalls

1. Preserve ALL existing Phase-13 scheduler tests unchanged (synchronous path observable behavior identical). 2. Don't reorder W4. 3. Keep sleep/clock injectable; only the default sleep becomes interruptible. 4. NEVER hold the lock across sink()/sleep(). 5. scheduler stdlib-only (threading OK). 6. offline/Qt-free guard green; `import rosbagger_replay` ROS-free. 7. thin face; QTimer lifecycle tied to the drive. 8. no inline color (shared `set_status`). 9. cursor advance MUST be locked (read-modify-write).

## 5. Test plan

**Scheduler (pure):** threaded race test (SC1) — run() on a thread with a fake barrier-sleep; main thread seeks mid-run; assert next item at/after target + cursor advanced from there (no lost update); also mid-run set_rate + pause take effect. Regression: all existing scheduler tests green unchanged.
**Desktop (headless pytest-qt, offscreen):** live playhead advances mid-play (SC2a); live seek with no "Pause before seeking" + `replayer.seek` spied with right offset (SC2b/SC3); backward fraction -> "resuming forward" status (SC3); rate+loop stay enabled mid-play. Offline guard green.
**Gate:** `PYTHONPATH="" QT_QPA_PLATFORM=offscreen uv run pytest` green; blended coverage >=80%; ruff clean.

## 6. Plan split
- 18-01 scheduler thread-safety (pure, Wave 1). - 18-02 desktop live-scrub wiring (thin face, Wave 2, blocked on 18-01).
