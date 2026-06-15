# PLAN — Quick 260615-1n1 — Overhaul cleanup/perf tail

**Goal:** finish the *entire* remaining tail of the codebase overhaul (the cleanup/refactor/perf
findings left after all 35 bugs were fixed in Batches 1–5/7), each as an atomic, tested, ruff-clean
commit; skip-with-rationale anything that proves net-negative; leave the repo green and pushable.
Pushes remain the user's.

## Scope (the remaining review findings)

- **Dead code:** S7 (false-justification `noqa` import), S8 (needless `import_module` param),
  S3 (`EdgeReport` ctor pasted 4× in `collect_tf_report`), S6 (duplicated install.sh tails).
- **Perf:** F3 (per-message loop-invariant work in the decode hot loop), F2 (no LIMIT pushdown).
- **Capability/error dedup (Batch 2e):** R6 (rclpy probe ×3 → core), T7 (hard-coded "humble" ×3
  → distro-aware), R4 (CLI teaching-error decorator ×3), R7 (`RosNotAvailableError` ×2).
- **replay_panel/BagSession refactor (Batch 6):** S5 (`republish_static` ×3), S4 (stringly
  pending-action), S2 (18 pass-through `@property`), R5 (transport view-model dup), R8 (scrubber
  marker math dup), T6 (typed `BagSession` vs `getattr(window())`).
- **Architecture:** T4 (version `0.2.0` hand-duplicated).
- **Deferred-plausible:** newE24 (Rerun viewer PID-diff could SIGTERM a concurrent rviz2).

## Method

1. GSD-quick INLINE (agents not installed): plan + execute here, atomic commit per finding, a
   regression test where offline-testable, `ruff` + targeted tests green before each commit.
2. Two adversarial **verification workflows** (investigate → challenge) to (a) ground every finding
   in *current* code (it had drifted 13 commits since the review) and (b) decide the *subjective*
   refactors (R4/R7/S2/T6/R5/R8) + the newE24 investigation with a defensible APPLY/SKIP verdict —
   so any SKIP is principled, not unilateral.
3. Decision rule: APPLY when it is a clear, low-risk, behavior-preserving win; SKIP (with a written
   rationale) when the benefit is marginal or the risk/diff/coupling outweighs it.
4. Finalize: full offline suite green, PLAN/SUMMARY, STATE.md, report. No push.

## Tasks / success criteria

- [x] Every finding either APPLIED (atomic commit + test) or SKIPPED with a documented reason.
- [x] No user-facing behavior change for any cleanup/perf item (byte-identical output; perf items
      proven identical-result with the optimization on).
- [x] Offline-import + Qt-free invariants preserved; `ruff` clean repo-wide; full suite green.
- [x] Pre-existing ruff debt (unrelated, in untouched files) cleared so CI passes on push.
