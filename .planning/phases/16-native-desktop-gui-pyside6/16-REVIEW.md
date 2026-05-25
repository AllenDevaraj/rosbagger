---
phase: 16-native-desktop-gui-pyside6
reviewed: 2026-05-25T09:25:09Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - packages/rosbagger-desktop/pyproject.toml
  - packages/rosbagger-desktop/src/rosbagger_desktop/__init__.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/capabilities.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/cli.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/__init__.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/panels/tf_panel.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/__init__.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py
  - packages/rosbagger-desktop/src/rosbagger_desktop/workers.py
  - pyproject.toml
  - tests/test_desktop.py
  - tests/test_desktop_live.py
  - tests/test_offline_guard.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-05-25T09:25:09Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 16 adds the isolated PySide6 desktop GUI (`rosbagger-desktop`). The isolation invariant
is well-executed: every `rosbagger_core`/`rosbagger_record`/`rosbagger_replay`/`rclpy`/PySide6
import is confined to a method, worker, or `cli.main` body, and the offline-guard regression
tests (`test_import_core_does_not_pull_pyside6`, `test_import_desktop_cli_does_not_pull_pyside6_or_ros`)
lock that in. The thin-frontend fidelity is also good — panels forward verbatim to the named
core APIs and `build_publish_sink` is reused as the single publish path.

The defects concentrate in **Qt thread teardown** and the **replay state machine's concurrency
discipline**, which is exactly where the phase flagged the highest risk. Two issues are
ship-blocking: a use-after-free on panel close (the kept QThread ref is `deleteLater`'d but
never nulled, so `stop_thread` touches a destroyed C++ object), and an unguarded data race where
the rate/loop controls mutate the running `Replayer` from the UI thread mid-`run()` — directly
contradicting the panel's own "only mutate between run segments" invariant.

## Critical Issues

### CR-01: `stop_thread` on close touches a `deleteLater`'d (destroyed) QThread — use-after-free

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/workers.py:119-121`, `packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py:147-151`, `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py:166-170`

**Issue:** `run_on_thread` wires `thread.finished → thread.deleteLater` (workers.py:121) but the
panels keep the Python wrapper in `self._discover_thread` / `self._record_thread` /
`self._drive_thread` and **never reset it to `None` after the worker finishes**. Once a worker
completes normally, the underlying C++ `QThread` is destroyed by `deleteLater`, but the stale
Python reference remains. On panel `closeEvent`, `stop_thread(self._drive_thread)` calls
`thread.isRunning()` (workers.py:136) on that already-deleted C++ object, which raises
`RuntimeError: Internal C++ object (PySide6.QtCore.QThread) already deleted`. Because this fires
inside `closeEvent`, it can abort window teardown / crash on shutdown after any completed
record, discovery, or replay run. This is the precise "destroyed-while-running" / dangling-handle
class the phase set out to avoid, just inverted (dangling-after-finished).

**Fix:** Null the kept reference when the thread finishes, before `deleteLater` runs, and guard
`stop_thread` against a deleted object. In each panel pass an `on_finished` (or extend
`run_on_thread`) that clears the ref:

```python
# replay_panel._start_drive (and the two record_panel call sites)
def _clear_drive_thread() -> None:
    self._drive_thread = None

self._drive_thread, _ = run_on_thread(
    self, worker,
    on_result=self._on_drive_done,
    on_failed=self._status.setText,
    on_finished=self._clear_drive_thread,   # runs on finished, before deleteLater
)
```

and harden the helper:

```python
def stop_thread(thread: QThread | None) -> None:
    if thread is None:
        return
    try:
        running = thread.isRunning()
    except RuntimeError:   # C++ object already deleted
        return
    if running:
        thread.quit()
        thread.wait()
```

Note `on_finished` is connected AFTER `thread.quit`/`worker.deleteLater` in `run_on_thread`
ordering — ensure the ref-clear is connected to `worker.finished` so it runs on the UI thread
before the C++ thread object is collected. (Connecting the clear-slot via the existing
`on_finished` parameter, which is wired at workers.py:116-117 before the teardown chain, is
sufficient and runs on the UI thread.)

### CR-02: rate / loop controls mutate the running `Replayer` from the UI thread mid-`run()` — data race

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py:328-349` (`_apply_rate`, `_apply_loop`), wired at `:112-113`

**Issue:** The panel's own contract (`_drive_running` docstring, replay_panel.py:281-291) states
the `Replayer` is a non-thread-safe state machine that must only be mutated **between** run
segments, and it correctly guards `_play` / `_step` / `_on_seeked` with `_drive_running()`. But
`_apply_rate` and `_apply_loop` are **not guarded** and their controls are **never disabled
during a drive**: `returnPressed` on the rate line-edit (`:112`) and `toggled` on the loop
checkbox (`:113`) fire on the UI thread at any time. While `Replayer.run()` executes on the
worker thread it reads `self._rate` every iteration (scheduler.py:212) and `self.loop` at the
end-of-stream branch (scheduler.py:228); `_apply_rate` writes `_rate` via `set_rate`
(replay_panel.py:340) and `_apply_loop` writes `self.loop` directly (replay_panel.py:349). A
user pressing Enter in the rate box or toggling loop while playing is an unsynchronized
read/write of the scheduler's mutable state from two threads — the exact undefined interleaving
the Play/Step guard was added to prevent. Pause is legitimately allowed (the loop reads state at
a boundary), but rate/loop have no such single-word-atomicity guarantee in the loop logic.

**Fix:** Guard both handlers the same way as the other transport controls — ignore (or queue) the
mutation while a drive worker runs, with a teaching status:

```python
def _apply_rate(self) -> None:
    if self._replayer is None:
        return
    if self._drive_running():
        self._status.setText("Pause before changing the rate (a play worker is running).")
        return
    raw = self._rate_input.text().strip()
    try:
        rate = float(raw)
        self._replayer.set_rate(rate)
    except ValueError:
        self._status.setText(f"Invalid rate {raw!r}: enter a number > 0.")
        return
    self._status.setText(f"Rate set to {rate:g}.")

def _apply_loop(self, checked: bool) -> None:
    if self._replayer is None:
        return
    if self._drive_running():
        self._status.setText("Pause before toggling loop (a play worker is running).")
        return
    self._replayer.loop = checked
```

(Alternatively disable the rate input + loop checkbox while `_drive_running()` and re-enable on
`_on_drive_done`, mirroring the record panel's Start/Dismiss enable/disable.)

## Warnings

### WR-01: Cross-panel `rclpy.init()` clash breaks record discovery after replay builds its context

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py:173-178, 256-263`; interacts with `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py:201-260`

**Issue:** The replay panel's `_ensure_transport` calls `rclpy.init()` (replay_panel.py:239) and
keeps the context alive until `closeEvent`/teardown. The record panel's worker callables call
`list_record_topics()` and `record_topics(...)`, both of which delegate to `record.py` /
`list_topics`, which call `rclpy.init()` **unconditionally** (record.py:259) with no
already-initialized guard. So if a user visits Replay and presses Play/Step/seek (building the
replay context), then switches to Record, the on-show discovery scan's `rclpy.init()` raises
`RuntimeError: Failed to initialize rclpy: context already initialized` (or similar). The worker
catches it as a generic `Exception` and surfaces a teaching string, so it does not crash — but
recording/discovery becomes silently non-functional for the rest of the session whenever the
replay transport is live. The replay panel adopted the re-entrant `rclpy.ok()` guard (WR-04) for
exactly this reason; the record path has no equivalent and the two panels share one process
context.

**Fix:** This is rooted in `rosbagger_record.record` not guarding `rclpy.init()`, which is out of
this phase's edited files — but the desktop integration is what surfaces it. Mitigate in-panel by
tearing down the replay transport before a record scan/start (e.g. call
`self.window().replay_panel._teardown_transport()` when only the panel-created context exists), or
better, file a follow-up against `rosbagger_record.record` to use the same `rclpy.ok()`-aware
init/shutdown discipline as `replay_panel._ensure_transport`. At minimum, document the limitation
in the panel docstring so the teaching-error path is understood as expected, not a mystery.

### WR-02: `_finish_record` unpacks the worker result with no shape guard

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py:295-298`

**Issue:** `_finish_record` does `captured, out = result` on the `result` signal payload. The
worker's success path emits `(captured, out)` (record_panel.py:263), so the happy path is fine.
But `result` is typed `object` and the unpack will raise `TypeError`/`ValueError` if the worker
ever returns a non-2-tuple (e.g. a future change to `record_topics`'s return, or `record_topics`
returning a bare int as it historically did — `record()` returns `int`, and the panel only wraps
it into a tuple in its own closure). The slot runs on the UI thread with no try/except, so a
shape mismatch becomes an unhandled exception in the Qt event loop rather than a teaching status.

**Fix:** Defensively validate or keep the wrapping contract tight and assert it:

```python
def _finish_record(self, result: object) -> None:
    if not (isinstance(result, tuple) and len(result) == 2):
        self._status.setText(f"Recorded (unexpected result: {result!r})")
        return
    captured, out = result
    self._status.setText(f"Recorded {captured} message(s) → {out}")
```

### WR-03: Query/record exports write to fixed CWD-relative paths — silent overwrite, no picker

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py:58-59, 124-125, 297-319`

**Issue:** Export CSV/Parquet always write to the hardcoded relative paths `"query_result.csv"` /
`"query_result.parquet"` in the process CWD (query_panel.py:58-59), bound via lambdas at
:124-125. Every export silently overwrites the previous file, the destination depends on wherever
the GUI was launched from (unpredictable for a windowed app launched via a desktop entry), and the
user is given no `QFileDialog.getSaveFileName` to choose a location — unlike the bag-open paths,
which correctly use `QFileDialog`. The phase scope explicitly calls out "QFileDialog usage" as a
resource-handling concern. The success status reports the bare relative path, compounding the
"where did my file go?" problem.

**Fix:** Use a save dialog so the user controls the destination (and the extension still drives the
format via `write_table`):

```python
def _export(self, default_name: str, filter_: str) -> None:
    if self._last_result is None:
        self._status.setText("Run a query first, then export.")
        return
    path, _ = QFileDialog.getSaveFileName(self, "Export query result", default_name, filter_)
    if not path:
        return
    from rosbagger_core.output.export import write_table
    try:
        write_table(self._last_result, path)
    except (ValueError, OSError) as exc:
        self._status.setText(str(exc))
        return
    self._status.setText(f"Exported {self._last_result.num_rows} row(s) → {path}")
```

### WR-04: `_open_reader` leaves the window with NO reader after a failed open, but stale `_bag_path` semantics are inconsistent

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/main_window.py:169-190`

**Issue:** On a failed `reader.open()`, the code closes the prior reader (`self.reader = None`,
:180-181), constructs the new `RosbagsReader`, and on failure returns early (:187-188) leaving
`self.reader = None` — good. But `self._bag_path` from a previously-opened bag is **not** cleared,
so after a failed re-open the window reports a `reader is None` (panels show empty state) while
`_bag_path` still points at the old bag. Any code that trusts `_bag_path` as "the currently loaded
bag" (none today, but the replay panel reads `reader.paths`, and `_bag_path` is otherwise dead
state) will be inconsistent. Additionally the newly-constructed-but-unopened `RosbagsReader` on the
failure path is dropped without `.close()` — harmless for the current rosbags reader (open() failed
so no handle), but fragile if `RosbagsReader.__init__` ever acquires a resource.

**Fix:** Clear `_bag_path` on the failure return and only set it on success (it already is set only
on success at :190 — so just add the clear):

```python
except Exception as exc:  # noqa: BLE001
    QMessageBox.warning(self, "Could not open bag", f"Could not open {path}: {exc}")
    self._bag_path = None
    return
```

### WR-05: `_export` catches `(ValueError, OSError)` but `write_table` can raise other errors that crash the GUI

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py:314-318`

**Issue:** The export handler only catches `(ValueError, OSError)`. `write_table` serializes a
`pyarrow.Table` and a real-world write can raise other exception types (e.g. `pyarrow.ArrowInvalid`
/ `ArrowNotImplementedError` for an unwritable column type, `PermissionError` is an `OSError`
subclass so that's covered, but Arrow's exceptions are not `ValueError`/`OSError`). An uncaught
Arrow exception here propagates into the Qt event loop as an unhandled exception rather than a
teaching status, contradicting the panel's stated "any error is surfaced to the status label rather
than crashing the GUI" (docstring :304-305).

**Fix:** Broaden the catch to match the docstring's promise (mirroring the worker's
surface-as-teaching-text policy):

```python
try:
    write_table(self._last_result, path)
except Exception as exc:  # noqa: BLE001 - present as teaching text, never crash the GUI
    self._status.setText(f"Export failed: {exc}")
    return
```

### WR-06: `_read_rate` silently coerces an invalid/blank rate to 1.0 at transport-build time, contradicting the "never silently coerce" rule

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/replay_panel.py:192-199` vs `:328-344`

**Issue:** `_apply_rate` (the returnPressed handler) deliberately REJECTS an invalid rate with a
teaching status rather than coercing (docstring :329-333, "never silently coerced to 1.0"). But
`_ensure_transport` builds the `Replayer` with `rate=self._read_rate()` (:244), and `_read_rate`
**does** silently coerce a non-numeric or `<= 0` entry to `1.0` (:198-199). So if the user types
an invalid rate and presses **Play** (instead of Enter), the panel silently plays at 1.0 with no
teaching feedback — the two code paths disagree on the contract for the same widget. The
`_play`/`_step` status lines even report `rate {self._read_rate():g}` (:304), which would show
`1.0` while the input box shows the invalid text, masking the discrepancy.

**Fix:** Validate the rate once at Play/Step entry with the same teaching rejection as
`_apply_rate`, and have `_ensure_transport` use the validated value (or refuse to build on an
invalid rate):

```python
def _validated_rate(self) -> float | None:
    raw = self._rate_input.text().strip()
    try:
        value = float(raw)
    except ValueError:
        self._status.setText(f"Invalid rate {raw!r}: enter a number > 0.")
        return None
    if value <= 0:
        self._status.setText(f"Invalid rate {raw!r}: enter a number > 0.")
        return None
    return value
```

and gate `_play`/`_step` on it before `_ensure_transport`.

## Info

### IN-01: `_SQL_ROLE` reused as both history-SQL role and tree-column role — overloaded constant

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/query_panel.py:62, 199, 212, 219, 294`

**Issue:** `_SQL_ROLE = int(Qt.UserRole)` is documented as "the verbatim SQL on a history row / column on a tree leaf" and is used to store both a column name (tree leaf, :199) and a full SQL string (history item, :294). They live on different widgets so there's no collision today, but the single overloaded name obscures intent and invites a future bug if the two widgets are ever merged or a shared model is introduced.

**Fix:** Split into `_SQL_ROLE` (history) and `_COLUMN_ROLE` (tree leaf), both `int(Qt.UserRole)`, for clarity.

### IN-02: `_human_size` caps at TB and `_human_dur` boundary at exactly 1000ms

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/inspect_panel.py:32-43`; `packages/rosbagger-desktop/src/rosbagger_desktop/panels/tf_panel.py:33-44`

**Issue:** `_human_size` divides through B/KB/MB/GB then falls through to a TB format — a >1024 TB bag would print e.g. "2048.0 TB" rather than PB (not a real concern for bags, presentation only). `_human_dur` switches from ms to seconds at `ms < 1000.0`; exactly 1000.0 ms prints as "1.00s" (correct), but values like 999.5 ms print "999.5ms" — fine, just noting the boundary is presentation-only and matches the TUI.

**Fix:** None required (presentation parity with the TUI is the intent); noted for completeness.

### IN-03: `_DEFAULT_RECORD_SECONDS` and snap/resolution constants are reasonable but undocumented as tunables

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/panels/record_panel.py:53`; `packages/rosbagger-desktop/src/rosbagger_desktop/widgets/scrubber.py:37,41`

**Issue:** The bounded record window is hardcoded to 10s with no UI control to change it — the panel records "up to 10s" with no way for the user to set a longer/shorter bound. This is a usability limitation rather than a bug (the bound is the DoS mitigation), but it is surfaced only in a status string.

**Fix:** Consider a duration spinbox in a later plan; for now the constant is acceptable. No code change required.

### IN-04: `cli.main` builds `QApplication` argv inconsistently between the two argv branches

**File:** `packages/rosbagger-desktop/src/rosbagger_desktop/cli.py:54`

**Issue:** `QApplication(sys.argv if argv is None else [sys.argv[0], *argv])` — when invoked as a
real console script (`argv is None`) it passes the full `sys.argv` (including the parsed bag path)
to Qt; when invoked programmatically with an explicit `argv` it reconstructs `[sys.argv[0], *argv]`.
Qt will see the bag-path positional as an unrecognized argument in the `argv is None` path. Qt
generally ignores unknown args, so this is benign today, but the two branches having different
argv shapes is a latent inconsistency.

**Fix:** Pass a Qt-only argv in both branches (e.g. `[sys.argv[0]]`), since the bag path is already
consumed by argparse and Qt does not need it.

---

_Reviewed: 2026-05-25T09:25:09Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
