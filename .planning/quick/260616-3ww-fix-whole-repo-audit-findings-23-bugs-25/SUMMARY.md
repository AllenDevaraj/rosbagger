# SUMMARY — Quick 260616-3ww — Fix whole-repo audit findings

**Date:** 2026-06-16 · **Status:** complete · **Commits:** 28 fix/refactor + 1 docs (plan/report)
= 29 (5e2940b … b826c64, on top of pushed base 911a2b1).

Acted on every finding from the whole-codebase bug+QoL audit (workflow `w43nl4hez`, 23 finder
units → adversarial verify → ranked report; raw report at `AUDIT-REPORT.json`). **47 of 48
confirmed findings APPLIED** (atomic commit + regression test where offline-testable), **1
confirmed + the 1 uncertain finding SKIPPED with rationale**. Full offline suite **665 non-Qt +
99 Qt = 764 passed / 6 skipped**; `ruff` clean repo-wide; +~45 regression tests.

## Applied — by package
### rosbagger-core (10 commits)
- **flatten.py** (bug/HIGH): materialize LIST-of-STRUCT columns — `SELECT * FROM /tf` (Path /
  PoseArray / MarkerArray) no longer ArrowTypeError-crashes.
- **edit/pipeline.py** (2× bug/med): forward conn.ext (ROS1 latching / ROS2 QoS) on the raw-copy
  path; broaden the `--format ros1` suffix guard to `!= '.bag'`.
- **output/render.py** (bug/med): `to_json` sanitizes NaN/±inf → null (valid strict JSON).
- **backend/query.py** (2× bug/low + qol/low): guard non-integer LIMIT pushdown; case-fold the
  events-sidecar reservation; fix the stale BinderException comment.
- **tf.py** (bug/low): `--gap-ms` now OVERRIDES the multiplier (the CLI contract).
- **schema/types.py** (bug/low): map ROS2-IDL `octet`; clear error on an unmapped base type.
- **format.py** (qol/low): round-aware unit rollover (no "1000.0ms" / "1024.0 KB").
- **errors.py** (qol/low): dedup UnknownColumnError did-you-mean across JOINed tables.
- **reader/rosbags_reader.py** (qol/low): `read()` validates eagerly at call time.

### rosbagger-replay (2) — scheduler busy-spin floor + duration-overshoot cap (2× bug/med);
CLI `--rate`/`--region-*` up-front validation + corrected help (3× qol/low).
### rosbagger-record (2) — match publisher QoS so BEST_EFFORT topics are captured (bug/med) +
warn on unpublished requested topics (qol); typed InvalidPatternError for a bad --regex (qol).
### rosbagger-rerun (2) — generic-fallback unsupported image encodings (bug/med) + drop
non-finite cloud points (qol); bounded reap so viewers leave no zombie (qol).
### bagq (1) — preflight --format before the query; clean plot-sink errors; reject a backwards
`events add` window (3× qol/low).
### rosbagger-gui / TUI (4) — malformed-SQL no longer crashes the cockpit (bug/HIGH); InspectPanel
custom-type guard (bug/med); replay teardown stops the drive worker + playhead animation +
transport-cache invalidation; query stale-result clear; record in-flight guard.
### rosbagger-desktop / Qt (6) — result_model renders only timestamp[ns] via the raw path
(bug/med); scrubber absolute left-click + marker tooltips (bug/med + qol); generation-guard
superseded refresh workers (bug/med+low) + TF reader cache (qol, both frontends); reset replay
transport on bag swap (bug/med) + cancelled-Rerun-toggle bail (bug/med) + ready status; remove the
harmful `_release_replay_context` (bug/med); record discovery-vs-record guard (bug/low) + Dismiss
affordance (qol); checkable-button checked/pressed QSS state (qol).

## Skipped — with rationale
- **replay_panel.py closeEvent pip-freeze (qol/low)** — SKIP (deferred). The fix swaps the
  on-click pip install from `subprocess.run` to a `Popen` the closeEvent can `terminate()` — a
  non-trivial, LIVE-only subprocess-management change verifiable only in the ROS lane. The
  symptom is a rare *slow close* (only if the window is closed DURING an on-click rerun-sdk
  install), not a crash or data loss. Deferred as net-risk under a do-no-harm bar; the other two
  replay_panel findings (rerun-rearm bug, status qol) ARE fixed.
- **rviz_session.py:36-48 (uncertain)** — SKIP. The verifier judged it cosmetic: the dropped-Popen
  ResourceWarning is default-suppressed, and the transient zombie is the *intentional* documented
  behavior (mirrors the rerun module, whose worse accumulating-zombie variant WAS fixed here).
  No observable impact; left as-is.

## Verification
- Per finding: targeted test file(s) + `ruff`; ROS-lifecycle/live items reasoned + offline-mocked
  (the live lane is not exercised here). New tests across test_schema_arrow / test_gui / test_edit /
  test_output_render / test_backend_query / test_tf / test_format / test_errors / test_reader /
  test_replay_unit / test_record_unit / test_rerun_unit / test_cli_query / test_cli_events /
  test_desktop.
- Full offline suite: **665 (non-Qt) + 99 (test_desktop.py, Qt offscreen)** = 764 passed, 6 skipped.
  The Qt suite was tallied in small chunks + per-test because the **non-deterministic Qt-offscreen
  teardown abort** (documented artifact, worse with rerun-sdk in the venv) crashes the full-file run
  at a VARIABLE point; every test passes in isolation and **zero real failures** were observed.
- `ruff check packages tests tools` clean (CI scope, locked ruff).

## Remaining
Only the user's `git push` (29 commits; base = pushed 911a2b1). Pushes are the user's.
