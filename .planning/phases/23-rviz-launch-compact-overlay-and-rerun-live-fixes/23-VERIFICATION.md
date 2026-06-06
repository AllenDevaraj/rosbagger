---
phase: 23-rviz-launch-compact-overlay-and-rerun-live-fixes
status: passed
verified: 2026-06-06
mode: inline (gsd-verifier agent not installed; verified by the executor inline per project convention)
---

# Phase 23 — Verification

All 4 plans executed inline (GSD agents not installed) with per-plan offline tests + ruff/format +
offline-import-guard gates green and atomic commits. Full offline suite at phase end: **609 tests,
0 failures, 0 errors, 6 skipped, coverage 87.99%** (≥80% gate) — captured via `--junitxml` because the
intermittent Qt offscreen teardown SIGBUS is a process-exit artifact (documented), not a test failure.

## Success Criteria (from ROADMAP)

1. **Open in RViz toggle + generated `.rviz` + tracked viewer** — ✅ (23-03). `build_rviz_config`
   offline-unit-tested (msgtype→display, Grid+TF, Fixed Frame, unknown skipped, de-dup, QoS, yaml
   round-trip); `rviz_session` launch/close mirrors the rerun lifecycle (monkeypatched Popen/which/kill
   tests); panel builds+writes the config and launches via the module attribute. Live smoke test
   (`-m live`, skipif no rviz2) collected. **Live visual = user sign-off.**
2. **Auto-fidelity (/clock + static re-prime)** — ✅ (23-03). Opening RViz checks both fidelity boxes
   (test); rebuild only when safe (paused; mid-play teaches a one-step re-prime to stay thread-safe —
   documented deviation in 23-03-SUMMARY).
3. **Compact overlay + corner trigger + restore** — ✅ (23-04). `OverlayWindow` controls drive the
   panel's 23-02 API; positionChanged syncs the scrubber; the corner control enters overlay on the
   Replay tab and minimizes elsewhere; exit restores; ✕ quits (headless spy tests). **Live visual =
   user sign-off.**
4. **±5s skip on the Replay bar** — ✅ (23-02). Buttons present; relative seek + end-clamp; works via
   the thread-safe `Replayer.seek`.
5. **Rerun mirror order-independent (+ off-thread spawn, t0 anchor, surfaced errors)** — ✅ (23-01).
   Readiness gate confirmed against rerun-sdk 0.32.2 (port 9876 poll + flush), bounded/never-raises;
   off-thread spawn; `build_rerun_sink(t0_ns=bag start)` wiring proven; drop-count surfaced. The
   end-to-end "Rerun-before-Play shows the image" check is **user sign-off (needs a display)**; the
   existing live `.rrd` mirror lane was updated for the async spawn.
6. **Invariants** — ✅. Offline import graph stays ROS-free AND Qt-free: `rviz_config` is ROS/Qt-free;
   `rviz_session`, `replay_panel`, `overlay`, `main_window`, `rosbagger_rerun.session` import no
   rclpy/rerun at module top (guard assertions in every plan's verify block). Panels stay thin faces;
   suite ≥80%; all pre-existing tests green.

## Outstanding (live + display — user sign-off)
These need a real X11 display + sourced ROS and are the user's manual UAT:
- Open in RViz → rviz2 opens with Image/PointCloud/LaserScan/TF displays bound to the bag topics;
  Play/scrub updates them live; closing the GUI kills rviz2.
- Open in Rerun BEFORE Play → the Image topic appears (the original bug).
- Top-right ⤓ on the Replay tab → overlay; drag the slider → RViz/Rerun translate live; ⛶ restores;
  ⤓ on another tab minimizes normally; ✕ quits.
