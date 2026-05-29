# Phase 18 Context: Replay Live Scrubbing & Thread-Safe Transport

**Phase:** 18 (REP-02) · **Milestone:** v0.5 — Replay Playback System
**Source:** discovery while the user replayed a real ROS 2 sqlite3 bag in the desktop; decisions locked via AskUserQuestion. Full Goal + 4 Success Criteria live in `ROADMAP.md` (Phase 18 block). Architecture truths in memory `replay-scrub-is-jump-plus-forward`.

## Locked decision

**FULL live scrub** — make the pure `Replayer` thread-safe so seek/rate/loop/pause apply *while playing*, and the playhead tracks live. (User rejected the lighter "auto-pause seek" / "live playhead only" options.) Phase 18 is the FOUNDATION of v0.5; the rest is sequenced into later phases.

## Scope

**In:** (1) thread-safe control surface on `Replayer` (no race on `_cursor`/`_state`/`_rate`/`loop`); (2) live position signal so the desktop playhead advances during playback; (3) desktop: remove the "Pause before seeking/rate/loop" mid-play blocks + wire the live playhead; (4) honest backward-drag status ("seeking... resuming forward").

**Out (deferred):** in/out region loop + side sub-panel -> Phase 19; `/clock` + static re-publish -> Phase 20; CLI parity flags -> Phase 21; in-app 3D/image viz -> permanently out (RViz/Foxglove own it).

## Hard invariants

`rosbagger_replay` no module-top ROS import; offline import graph ROS-free AND Qt-free (`tests/test_offline_guard.py`); scheduler stays stdlib-only (`threading` OK, no ROS/Qt); desktop panel a thin face; Phase-17 tokens, no inline color; `build_publish_sink` untouched.

## Testing

Pure scheduler -> fast deterministic unit tests (fake clock + recording sink) incl. a THREADED race test seeking mid-run. Desktop -> headless pytest-qt (`QT_QPA_PLATFORM=offscreen`). Run with `PYTHONPATH=""` on this ROS box. Gate: blended `--cov=rosbagger_core --cov=bagq --cov=rosbagger_desktop --cov-fail-under=80`. Intermittent SIGBUS at exit = Qt-offscreen teardown artifact (re-run), not a failure.

## Key resolved facts

Scrubber + all six controls + `position_fraction` ALREADY exist — Phase 18 adds concurrency + live position, not the controls. rosbag2's own player has no seek API (our custom `Replayer` is the seek mechanism). Backward scrub = jump + forward republish (RViz reflects forward only — fidelity work is Phase 20).
