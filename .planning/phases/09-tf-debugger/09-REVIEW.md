---
phase: 09-tf-debugger
reviewed: 2026-05-22T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - packages/rosbagger-core/src/rosbagger_core/tf.py
  - packages/rosbagger-core/src/rosbagger_core/errors.py
  - packages/bagq/src/bagq/cli.py
  - tools/make_fixtures.py
  - tests/test_tf.py
  - tests/test_offline_guard.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-05-22
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 9 ships the offline TF analyzer (`rosbagger_core.tf.collect_tf_report`) plus the
`bagq tf` renderer, a `write_tf_bag` fixture, and offline-guard tests. The core
gap-detection algorithm is, on the well-formed/happy path, **correct and well-guarded**:
I traced the seeded-fixture arithmetic (median = 100 ms, one 800 ms dropout at 5×),
the static-only skip, the zero/single-sample skip, the `<= 0` (duplicate/backwards
stamp) pre-filter that protects the median, two-sample correctness, the
no-synthetic-boundary-gap rule, and the integer-ns→seconds display — all check out, and
all 26 tests pass. The offline invariant holds (`import rosbagger_core.tf` pulls no
rosbags/duckdb/sqlglot/pyarrow; the lone `NoTransformsError` import is lazy inside the
function body). No security issues: no `eval`/`exec`/shell/`subprocess` in source, no
secrets, and bag-sourced frame ids flow only into rich tables as data (no format/eval
injection). The `write_tf_bag` fixture math is verified sound on all three formats.

The defects are concentrated in two areas: **(1) the `--gap-ms` knob's documented
"override" semantics are not actually implemented** (it is an OR-union with the
multiplier, so a large `--gap-ms` does not suppress multiplier-based gaps as three
docstrings + the CLI help all promise), and **(2) the module advertises hostile-bag
hardening it does not fully deliver** (a `/tf`-named topic carrying a non-`TFMessage`
type raises an uncaught `AttributeError`, and the empty-bag time-bound sentinel slips
past the `isinstance(int)` guard). No Critical/Blocker findings — none of these crash or
corrupt data on supported, well-formed input.

## Warnings

### WR-01: `--gap-ms` does not "override" the multiplier — it is an OR-union with it

**File:** `packages/rosbagger-core/src/rosbagger_core/tf.py:322-324`
**Issue:** The contract is stated three times as an *override*:
- module docstring L184-186: "a delta above `gap_ms` ms is a gap **regardless of the
  multiplier**";
- module docstring L174-175: "(an absolute-ns **override**)";
- CLI help (`cli.py:504-507`): "Absolute gap threshold in milliseconds (**overrides the
  multiplier**)."

But the implementation is a union, not an override:
```python
is_gap = d > multiplier_threshold or (
    abs_threshold_ns is not None and d > abs_threshold_ns
)
```
When `gap_ms` is set, the multiplier branch still fires. Concretely, on the seeded edge
(median 100 ms, 800 ms dropout) with `--gap-ms 5000` (a 5 s absolute threshold the user
chose to *suppress* sensitivity), the documented behavior is "only deltas > 5 s are gaps"
→ the 800 ms dropout is NOT a gap. The code instead evaluates `800ms > 500ms (5×100ms)
OR 800ms > 5000ms` → `True` → the dropout is still flagged via the multiplier the user
asked to override. The two semantics only coincide when `gap_ms` is *tighter* than the
multiplier threshold (which is exactly the only case the tests exercise — see IN-04), so
this divergence ships untested.
**Fix:** Make `gap_ms` truly override the multiplier when set (match the docs), or change
all three docstrings + the CLI help to describe the OR-union "fires if *either* threshold
trips" behavior. To implement the documented override:
```python
# When an absolute threshold is given it REPLACES the multiplier (the documented override).
if abs_threshold_ns is not None:
    is_gap = d > abs_threshold_ns
else:
    is_gap = d > multiplier_threshold
```

### WR-02: No validation of non-positive `--gap-multiplier` / `--gap-ms`; every interval becomes a "gap"

**File:** `packages/bagq/src/bagq/cli.py:495-508` (and `tf.py:314, 322-324`)
**Issue:** `--gap-multiplier` and `--gap-ms` are accepted as raw floats with no lower
bound. `--gap-multiplier 0` (or negative) makes `multiplier_threshold = 0` (or negative),
so `d > threshold` is true for every positive delta → **every inter-arrival on every
dynamic edge is reported as a gap**. `--gap-ms 0` (or negative) does the same via the OR
branch. This is silent nonsense output, not an error. It is inconsistent with the rest of
the CLI, which validates its inputs (e.g. `query` rejects an unknown `--format` with
`typer.BadParameter`).
**Fix:** Reject non-positive thresholds at the CLI boundary (or guard in
`collect_tf_report`), e.g.:
```python
if gap_multiplier <= 0:
    raise typer.BadParameter("--gap-multiplier must be > 0")
if gap_ms is not None and gap_ms <= 0:
    raise typer.BadParameter("--gap-ms must be > 0")
```

### WR-03: Empty-bag time-bound sentinel slips past the `isinstance(int)` guard; misleading comment + garbage span

**File:** `packages/rosbagger-core/src/rosbagger_core/tf.py:233-235` (display fallout at
`cli.py:440-442`)
**Issue:**
```python
start_ns = reader.start_time
end_ns = reader.end_time
rel_base = start_ns if isinstance(start_ns, int) else None
```
The comment (L229-232) claims this "guard[s] the start against a None/garbage value so
the at_rel math never raises." But per `inspect.py` (L106-108) and
`rosbags_reader.py` (L196-203), `AnyReader` returns `sys.maxsize` for `start_time` and a
large-negative value for `end_time`/`duration` on an empty bag — and `sys.maxsize` **is**
an `int`, so it passes the `isinstance(int)` check unmodified. The `start_time` property
is typed `int` (never `None`) in the `BagReader` ABC, so the `else None` branch is
effectively unreachable for the real reader while the actual garbage case is *not*
caught. The reachable trigger: a bag that registers a `/tf` (or `/tf_static`) connection
but writes zero messages — the empty-topic guard (L201-203) passes (the topic exists),
`edge_times` is empty (so the gap math never runs and nothing raises in core), but
`TfReport.start_ns` carries the `sys.maxsize` sentinel. The CLI then prints a corrupt
header: `span_s = (end_ns - start_ns)/1e9` is hugely negative, rendered as
`span 0.00s–-18446744073.71s`. `inspect.py` already guards this exact sentinel via
`message_count == 0`; `tf.py` does not, so the two modules are inconsistent.
**Fix:** Guard the bounds on `reader.message_count == 0` (mirror `inspect.collect_bag_info`)
and set `start_ns`/`end_ns`/`rel_base` to `None` in that case; also fix the comment to
state what is actually guarded:
```python
if reader.message_count == 0:
    start_ns = end_ns = None
else:
    start_ns = reader.start_time
    end_ns = reader.end_time
rel_base = start_ns  # None on an empty bag; an int otherwise
```

### WR-04: Uncaught `AttributeError` on a `/tf`-named topic carrying a non-`TFMessage` type — contradicts the stated hostile-bag hardening

**File:** `packages/rosbagger-core/src/rosbagger_core/tf.py:217-219`
**Issue:** The module docstring (L27-32) markets the analyzer as hardened so "a hostile
bag's NaN/inf transform numerics and huge payloads never reach the gap math (threats
T-09-05 / T-09-06)." But edge discovery matches **by topic name** (Decision 4) and then
blindly dives into the message shape:
```python
for tfs in m.msg.transforms:          # L217
    parent = tfs.header.frame_id      # L218
    child = tfs.child_frame_id        # L219
```
A bag that publishes a *different* message type on a `/tf`/`/tf_static`-named topic (e.g.
`std_msgs/String`), or a malformed `TransformStamped` missing `header`, raises an uncaught
`AttributeError` (`'…' object has no attribute 'transforms'` / `'…' has no attribute
'header'`). `@teaching_errors` deliberately does not catch `AttributeError` (real bugs
must traceback), so the user gets a raw stack trace rather than a teaching message — the
exact "tool, not a script" failure the error layer exists to prevent, on input the module
claims to harden against.
**Fix:** Defensively skip non-conforming messages/transforms rather than assuming the
shape, e.g.:
```python
transforms = getattr(m.msg, "transforms", None)
if transforms is None:
    continue  # a non-TFMessage published on a /tf-named topic — skip, do not crash
for tfs in transforms:
    header = getattr(tfs, "header", None)
    parent = getattr(header, "frame_id", None)
    child = getattr(tfs, "child_frame_id", None)
    if parent is None or child is None:
        continue
    ...
```

## Info

### IN-01: Dead / unreachable `expected <= 0` branch

**File:** `packages/rosbagger-core/src/rosbagger_core/tf.py:296-310`
**Issue:** `diffs` is built with the filter `if b - a > 0` (L277), so every element is
strictly positive. `statistics.median` of an all-positive list is always positive (it is
either a member or the mean of two members). Therefore `if expected <= 0:` (L296) can
never be true — the entire branch (L296-310) is unreachable dead code (coverage confirms
L297-310 are never hit). The comment calls it "defensive," but it guards a
mathematically impossible state; the genuine all-duplicate case is already handled by the
`if not diffs:` branch (L278-293).
**Fix:** Remove the unreachable branch, or if kept for defense-in-depth, drop it to a
single `assert expected > 0` with a comment explaining the L277 filter guarantees it.

### IN-02: `_human_dur` renders `[999_950_000, 999_999_999]` ns as `"1000.0ms"` instead of `"1.00s"`

**File:** `packages/bagq/src/bagq/cli.py:193-196`
**Issue:** The sub-second branch test is on the *unrounded* `ms`, but the format string
rounds:
```python
ms = ns / 1e6
if ms < 1000.0:
    return f"{int(ms)}ms" if ms == int(ms) else f"{ms:.1f}ms"
```
For `ns` in `[999_950_000, 999_999_999]`, `ms` is in `[999.95, 1000.0)` so it takes the
sub-second branch, but `f"{ms:.1f}"` rounds to `1000.0`, printing the nonsensical
`"1000.0ms"` for a duration ~1 ns under one second (it should be `"1.00s"`).
Cosmetic only — never affects gap detection or the seeded 800 ms case.
**Fix:** Compare the rounded value, e.g. branch on `round(ms, 1) < 1000.0`, or switch the
threshold to nanoseconds: `if ns < 1_000_000_000:`.

### IN-03: `GapReport.at_rel_s` is computed but unused; the CLI recomputes the same value

**File:** `packages/rosbagger-core/src/rosbagger_core/tf.py:335` (consumer
`packages/bagq/src/bagq/cli.py:482`)
**Issue:** `collect_tf_report` populates `GapReport.at_rel_s = at_rel_ns / 1e9` (L335,
documented as "convenience for the renderer"), but the renderer ignores it and recomputes
`f"t={g.at_rel_ns / 1e9:.2f}s"` (cli.py:482). The field is dead in the table path (it does
ride along in `--format json` via `asdict`, so it is not fully unused), and the seconds
math is duplicated across the API/CLI boundary.
**Fix:** Either render `g.at_rel_s` in the CLI (drop the duplicated division), or remove
the field if the JSON consumer does not need it.

### IN-04: `test_gap_ms_override_flags_dropout` does not exercise override semantics

**File:** `tests/test_tf.py:166-171`
**Issue:** The test passes `gap_ms = 300` ms while the default multiplier threshold is
`5 × 100 ms = 500 ms`, and asserts only that the 800 ms dropout is flagged. Since
`800 > 500` *and* `800 > 300`, the assertion holds under both the OR-union (actual) and
the override (documented) semantics — the test cannot tell them apart. It therefore does
not actually verify the "absolute override" its name and docstring claim, and it masks
WR-01.
**Fix:** Add a case where the thresholds disagree to pin down the intended semantics —
e.g. `gap_ms` set *above* the multiplier threshold (`--gap-ms 5000` on the 100 ms edge)
and assert whether the 800 ms dropout fires; that test will encode the decision made for
WR-01.

---

_Reviewed: 2026-05-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
