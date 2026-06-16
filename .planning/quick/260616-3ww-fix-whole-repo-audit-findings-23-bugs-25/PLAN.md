# PLAN — Quick 260616-3ww — Fix whole-repo audit findings

**Goal:** fix every confirmed finding from the whole-codebase bug+QoL audit (workflow `w43nl4hez`):
23 bugs (2 high, 15 medium, 6 low) + 25 QoL (3 medium, 22 low), grouped into atomic, tested,
ruff-clean commits. Apply clear wins; skip-with-rationale anything net-negative or regression-risky.
Leave the repo green and pushable. **Pushes remain the user's — do NOT push.**

**Method:** GSD-quick INLINE (executor agents not installed). Per group: read → fix → regression
test where offline-testable → `PYTHONPATH="" uv run pytest <file> --no-cov` + targeted ruff → atomic
commit (footer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`). Final:
full offline suite + repo-wide `ruff check packages tests tools` green; SUMMARY + STATE; no push.

## Risk notes (extra care)
- **record_panel `_release_replay_context` removal** — verify record.py's `created_ctx` guard
  actually makes shared-context teardown safe BEFORE removing; else do the safer reorder fix.
- **record.py QoS matching** — must not break existing offline record tests; sensor-data fallback.
- **main_window reader-swap → replay teardown** — live lifecycle; offline-mock + reason, no live verify here.

## Execution groups (≈ one commit each)
### Bugs — High
- [ ] flatten.py:224,308-316 — list-of-STRUCT ArrowTypeError (`SELECT * FROM /tf`) → recursive dict-ify + test
- [ ] gui/panels/query.py:205-232 — malformed SQL crashes TUI → broad except fallback

### Bugs — Medium
- [ ] core/edit/pipeline.py — (a) forward conn.ext metadata (latching/QoS); (b) fmt-suffix ros1 != .bag
- [ ] core/output/render.py — to_json NaN/Inf → null
- [ ] desktop/widgets/result_model.py — gate temporal raw path on timestamp[ns]
- [ ] desktop/main_window.py — reader swap resets replay transport
- [ ] desktop/widgets/scrubber.py — left-click absolute seek (QProxyStyle)
- [ ] desktop/panels/tf_panel.py + inspect_panel.py — superseded-worker identity guard
- [ ] desktop/panels/replay_panel.py — rerun rearm honors toggle-off
- [ ] desktop/panels/record_panel.py — _release_replay_context (verify→remove/reorder)
- [ ] gui/panels/replay.py — teardown stops/awaits drive worker
- [ ] gui/panels/inspect.py — refresh_view error guard
- [ ] replay/scheduler.py — (a) region/loop degenerate busy-spin floor; (b) duration overshoot cap
- [ ] record/record.py — match publisher QoS (BEST_EFFORT capture)
- [ ] rerun/converters.py — unsupported image encoding → generic fallback

### Bugs — Low
- [ ] core/backend/query.py — (a) LIMIT 1.5 ValueError; (b) events case-insensitive reservation
- [ ] core/tf.py — --gap-ms override semantics (or doc)
- [ ] core/schema/types.py — octet mapping + clear error
- [ ] desktop/panels/record_panel.py — discovery rescan guarded vs in-flight record

### QoL — Medium
- [ ] desktop/panels/tf_panel.py + gui/panels/tf.py — TF reader-identity cache
- [ ] gui/panels/replay.py — scrubber playhead animation timer

### QoL — Low
- [ ] core/backend/query.py — stale BinderException comment
- [ ] core/reader/rosbags_reader.py — eager read() guard
- [ ] core/errors.py — UnknownColumnError suggestion dedup
- [ ] core/format.py — human_dur/human_size rounding boundary
- [ ] desktop/panels/replay_panel.py — neutral "Ready to replay" status; closeEvent pip freeze
- [ ] desktop/panels/record_panel.py — Dismiss/Start affordance
- [ ] desktop/widgets/scrubber.py — event-marker tooltip labels
- [ ] desktop/theme/qss.py — checkable button checked/pressed state
- [ ] gui/panels/replay.py + query.py + record.py — bag-switch invalidation + record in-flight guard
- [ ] replay/cli.py — --rate<=0, region help, region-end-without-start
- [ ] record/discovery.py — regex error → typed
- [ ] record/record.py — mistyped topics warning
- [ ] rerun/converters.py — pointcloud NaN/inf filter
- [ ] rerun/session.py — zombie reaping
- [ ] bagq/cli.py — format preflight; plot-sink clean errors; events backwards window guard

## Skipped
- [ ] **rviz_session.py:36-48,69-78 (uncertain)** — SKIP: verifier judged it cosmetic (ResourceWarning
  default-suppressed; transient zombie is the *intentional* documented behavior). No observable impact;
  low value. Document, no change.
