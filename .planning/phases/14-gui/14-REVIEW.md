---
phase: 14-gui
reviewed: 2026-05-24T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - packages/rosbagger-gui/src/rosbagger_gui/app.py
  - packages/rosbagger-gui/src/rosbagger_gui/cli.py
  - packages/rosbagger-gui/src/rosbagger_gui/__init__.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/__init__.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/inspect.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/query.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/record.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py
  - packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py
  - packages/rosbagger-gui/src/rosbagger_gui/widgets/__init__.py
  - packages/rosbagger-gui/src/rosbagger_gui/widgets/scrubber.py
  - packages/rosbagger-replay/src/rosbagger_replay/__init__.py
  - packages/rosbagger-replay/src/rosbagger_replay/replay.py
findings:
  critical: 0
  warning: 6
  info: 6
  total: 12
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-05-24
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the Phase-14 Textual GUI (`rosbagger-gui`) and the two shared-publish-path
changes in `rosbagger-replay`. The offline-import invariant (D-03) holds across all
panels: every `rosbagger_core` / `rosbagger_record` / `rosbagger_replay` / `rclpy`
symbol is lazy-imported inside a method or worker body, and the module tops are
textual-only (verified file-by-file). The thin-face contract is largely respected —
panels forward SQL/paths/topics verbatim and never build SQL, pick formats, or
re-implement analysis. The shared publish-path contract is honored: the replay panel
drives the pure `Replayer` through `build_publish_sink` (the single Plan-14-01 sink)
and inlines no publisher mechanics; no second publish path exists.

No BLOCKER-class defects were proven (no injection, no hardcoded secret, no crash on
the happy path, no publish-path duplication). However several correctness and
contract defects degrade the replay panel and a few panels carry unreachable or
misleading code. The two highest-value findings are the scrubber position/seek
fraction-base mismatch (WR-01) and the unreachable rate-validation branch whose
docstring promises behavior the code does not deliver (WR-02).

## Warnings

### WR-01: Scrubber playhead uses index-fraction but seek/markers use time-fraction — they disagree

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:273,283,322-325`
**Issue:** Three pieces of the replay timeline use two different fraction bases. A
seek maps the click fraction onto **time**:
`t_offset_ns = int(event.fraction * self._bag_span_ns)` (line 273), where
`_bag_span_ns = items[-1].t_ns - items[0].t_ns`. Event markers are likewise computed
as time-fractions `(start - bag_start_ns) / span` (lines 322-325). But
`_update_position` reflects the cursor onto the playhead by **index**:
`fraction = min(1.0, cursor / self._item_count)` (line 283). Unless items are
perfectly uniform in time, these bases diverge: a marker rendered at time-fraction
0.5 will not coincide with the playhead position the cursor produces when the
scheduler reaches that item, and seeking to a marker will leave the playhead visibly
off the marker. For real bags (bursty topics, mixed rates) the playhead and markers
drift apart.
**Fix:** Derive the playhead fraction from time, not index, so all three agree:
```python
def _update_position(self) -> None:
    if self._replayer is None or self._item_count == 0 or self._bag_span_ns <= 0:
        return
    cursor = self._replayer.cursor
    if cursor >= self._item_count:          # DONE / seek-past-end lands at len(items)
        fraction = 1.0
    else:
        items = self._replayer_items()      # add a public time accessor on Replayer
        fraction = min(1.0, (items[cursor].t_ns - items[0].t_ns) / self._bag_span_ns)
    self.query_one("#replay-scrubber", Scrubber).position = fraction
```
Prefer adding a public time/position accessor to `Replayer` over reaching into
`_items` from the panel, to keep the thin-face boundary clean.

### WR-02: Rate-validation branch is unreachable; invalid rate is silently coerced to 1.0

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:241-245,254-261`
**Issue:** `on_input_submitted` wraps `set_rate(self._read_rate())` in
`try/except ValueError` and the module docstring promises *"an invalid entry is
rejected with a teaching status"* (lines 56-58). But `_read_rate` (lines 254-261)
catches its own `ValueError` and returns `1.0`, and clamps any `value <= 0` to `1.0`
— so it can never return a value that makes `set_rate` raise. The `except ValueError`
branch (line 244) and the "Invalid rate" status are dead code, and a user who types
`abc` or `-2` gets a silent reset to 1.0 reported as "Rate set to 1." — the opposite
of the documented teaching behavior. `_play`/`_step` similarly display
`self._read_rate()` (already coerced) as if it were the user's value.
**Fix:** Parse once and branch on validity instead of silently coercing:
```python
def on_input_submitted(self, event: Input.Submitted) -> None:
    if event.input.id != "replay-rate" or self._replayer is None:
        return
    raw = self.query_one("#replay-rate", Input).value.strip()
    try:
        rate = float(raw)
        self._replayer.set_rate(rate)        # raises ValueError on <= 0
    except ValueError:
        self._show_status(f"Invalid rate {raw!r}: enter a number > 0.")
        return
    self._show_status(f"Rate set to {rate:g}.")
```
Keep `_read_rate`'s coercion only for the initial ctor default, or align it with this
validation.

### WR-03: "Stop" does not stop — `record()` keeps recording for up to the full bounded window

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/record.py:45,240-256`
**Issue:** `_stop_record` calls `self.workers.cancel_group(self, "record-run")` and
resets the controls to "Stopped." But `record_topics` runs in a thread worker and has
**no in-process interrupt hook** — `worker.cancel()` only flags the worker and
suppresses the late `call_from_thread` callback (lines 227/231/235). The real
`record()` spin loop ends only when its bounded `duration`
(`_DEFAULT_RECORD_SECONDS = 10.0`, line 45) elapses. So after the user presses Stop,
the recorder keeps capturing for up to ~10s and the output bag still contains those
post-Stop messages — the UI says "Stopped." while recording continues. The docstring
acknowledges this, but the gap between the affordance ("Stop") and the behavior is a
correctness/UX defect, not merely a note.
**Fix:** Either (a) expose a cooperative stop on the record front door (a
`threading.Event` / `should_stop` callback `record()` polls in its spin loop) and
signal it from `_stop_record`, or (b) relabel the control/status to reflect reality
(disable "Stop", show "Recording up to Ns — finalizes automatically") so the UI does
not claim an immediate stop it cannot deliver.

### WR-04: `_load_markers` eagerly builds the rclpy context on `on_show`, before any Play

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:89-97,308-318`
**Issue:** The module contract states the transport (rclpy context + node +
publishers) is "built lazily on first Play" (lines 76-78). But `on_show` calls
`_load_markers` (line 97), which — when the event sidecar has rows — calls
`self._ensure_transport()` (line 310) purely to learn `bag_start_ns`/`span` for marker
placement. That side-effect runs `rclpy.init()` and `create_node(...)` the moment the
user merely navigates to the Replay tab. This contradicts the "first Play" lazy-build
contract: simply viewing the panel allocates a live ROS node and publishers the user
never asked to create, and a transport build failure now surfaces on tab-switch
rather than on Play. Note `_load_markers` already re-calls `load_items(bag)` on lines
314-318, so the timestamps it needs are available without the transport.
**Fix:** Compute marker fractions from `load_items(bag)` alone; do not build the
publish transport in the marker path:
```python
items = load_items(bag)
if not items:
    return
bag_start_ns = items[0].t_ns
span = max(1, items[-1].t_ns - bag_start_ns)
# ... build marks ... ; do NOT call self._ensure_transport() here
```
Keep transport construction on the Play / Step / seek paths only.

### WR-05: `open_bag` / launch open path raises out without a teaching catch

**File:** `packages/rosbagger-gui/src/rosbagger_gui/app.py:105-142`
**Issue:** `_open_reader` (lines 108-121) calls `RosbagsReader(path, ...).open()` with
no `try/except`. The `__init__` docstring (lines 69-75) explicitly defers reader
opening to `on_mount` so a bad bag path "can surface in the UI rather than crashing
construction" — but `_open_reader` itself does not catch `open()` failures. On the
`on_mount` launch path (line 106) an unreadable/corrupt `<bag-path>` raises out of
`on_mount` and crashes the App during startup; via the `open_bag` picker seam
(line 130) it raises out of the message handler. Neither path teaches; both surface a
traceback, contradicting the stated intent.
**Fix:** Wrap the open and surface failures to the UI:
```python
def _open_reader(self, path: Path) -> None:
    if self.reader is not None:
        self.reader.close()
        self.reader = None
    reader = RosbagsReader(path, default_typestore=_ros2_humble_typestore())
    try:
        reader.open()
    except Exception as exc:                 # teaching, not a crash
        self.notify(f"Could not open {path}: {exc}", severity="error")
        return
    self.reader = reader
    self._bag_path = path
```

### WR-06: Step + Play share one `exclusive=True` worker group — a Step during Play can be dropped or interrupt playback

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:212-233,332`
**Issue:** Both `_play` and `_step` call `self._drive_worker()`, which is decorated
`@work(exclusive=True, thread=True, group="replay-run")` (line 332). With
`exclusive=True`, starting a second worker in the same group cancels the first. So a
user who clicks Step while a Play worker is mid-run cancels the in-flight playback
worker (the cancel path on lines 360-361 returns without pushing a terminal status),
and conversely the interleaving of `replayer.step()` (sets `STEPPING`) and a running
`run()` loop is racy: the state mutation happens on the UI thread while `run()` reads
`self._state` on the worker thread without synchronization. The scheduler is a plain
(non-thread-safe) state machine, so concurrent `step()`/`play()`/`pause()` calls from
the UI thread against a `run()` executing on the worker thread can interleave in
ways the scheduler contract does not define.
**Fix:** Guard transport calls so Step/Play are only issued when no drive worker is
running (e.g. check `self.workers` for a running `replay-run` worker before issuing a
new control), or document and enforce that controls are applied only between run
segments. At minimum, make Pause/Step/Play mutations and the worker's state reads
coordinate through a lock or a single owning thread.

## Info

### IN-01: Unused `Replayer` import kept alive only by a `noqa`

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:349`
**Issue:** `from rosbagger_replay import Replayer  # noqa: F401 - bind for the State
import below` imports `Replayer` purely as an unused symbol; the `State` import on
line 350 is independent and does not require `Replayer` bound. This is a genuinely
unused import preserved only by the `noqa`.
**Fix:** Delete line 349; keep only `from rosbagger_replay.scheduler import State`.

### IN-02: Storage choice read by stringifying the RadioButton label instead of its id

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/record.py:61-65,163-171`
**Issue:** `_selected_storage` reads `radio.pressed_button.label`, stringifies it, and
membership-tests against `_STORAGES`. The RadioButtons already carry stable ids
(`storage-mcap`, `storage-sqlite3`); matching on the human-facing label is fragile — a
label tweak silently breaks the mapping and falls back to "mcap".
**Fix:** Match on `pressed.id` (`"storage-sqlite3"` -> `"sqlite3"`) or store the
storage value as the RadioButton's value/name rather than reparsing the label.

### IN-03: History SQL stashed on a private `_sql` attribute of a framework widget

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/query.py:149,223-224`
**Issue:** History entries carry the raw SQL on an ad-hoc `item._sql` attribute
(`# noqa: SLF001`) and `on_list_view_selected` reads it via `getattr(..., "_sql",
None)`. Monkey-patching a private attribute onto a framework `ListItem` is brittle (a
future Textual `__slots__` or attribute collision breaks it silently).
**Fix:** Subclass `ListItem` with an explicit `sql: str` field, or maintain a parallel
`list[str]` history indexed by the ListView position.

### IN-04: Loop toggle before transport build is a silent no-op

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:247-252`
**Issue:** `on_switch_changed` forwards the loop toggle to `self._replayer.loop` only
when `self._replayer is not None`; otherwise it does nothing. `_ensure_transport`
re-reads the switch value at build time (line 162), so the toggle is not lost across a
build — but a toggle while `_replayer is None` produces no user feedback, so the user
cannot tell whether the toggle "took."
**Fix:** Optional: store the desired loop state on an instance attribute applied in
`_ensure_transport`, and/or echo the toggle to the status line so the affordance has
feedback even before the first Play.

### IN-05: `_published["n"]` hard-codes another module's internal dict key

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/replay.py:365`
**Issue:** `published = self._published["n"] if self._published else 0` assumes the
sink's count dict always has key `"n"`. `build_publish_sink` does return `{"n": 0}`
(`replay.py:66`), so this holds today, but the panel hard-codes the internal key shape
of another module — a thin-face leak. If `build_publish_sink` renames the key the
panel raises `KeyError` inside the worker.
**Fix:** Have `build_publish_sink` return an object/accessor (e.g. a small dataclass
with `.count`) so the count contract is explicit rather than a shared magic key.

### IN-06: `_human_dur` `int(ms)` cast can misrender near-integral millisecond values

**File:** `packages/rosbagger-gui/src/rosbagger_gui/panels/tf.py:37-40`
**Issue:** `_human_dur` returns `f"{int(ms)}ms"` when `ms == int(ms)` else
`f"{ms:.1f}ms"`. A float division landing at `999.9999999 ms` (rather than a clean
`1000.0`) would still render in milliseconds and the `int()`/equality test can read
misleadingly at boundaries. Presentation-only, low impact.
**Fix:** Round consistently (`round(ms, 1)`) or compare with a small tolerance before
the `int` cast.

---

_Reviewed: 2026-05-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
