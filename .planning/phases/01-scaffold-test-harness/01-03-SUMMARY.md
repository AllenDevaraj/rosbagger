---
phase: 01-scaffold-test-harness
plan: 03
subsystem: testing
tags: [rosbags, fixtures, ros1, ros2, mcap, sqlite3, pytest, anyreader, numpy]

# Dependency graph
requires:
  - phase: 01-01
    provides: uv workspace with rosbags>=0.11,<0.12 synced; tools/ importable via repo root
  - phase: 01-02
    provides: centralized pytest config (80% coverage gate on rosbagger_core+bagq), tests/conftest.py with no_ros guard, committed uv.lock
provides:
  - Fixture-bag generator (tools/make_fixtures.py) writing ROS1 .bag + ROS2 sqlite3 + ROS2 MCAP with NO ROS install
  - Forward-looking fixture content (/cmd_vel Twist, /imu Imu with header.stamp + float64[9] covariance, /image Image uint8[] blob)
  - Round-trip tests (tests/test_fixtures.py) proving each format re-opens via AnyReader and carries expected content
  - Importable + runnable generator (python -m tools.make_fixtures [DEST]) for manual bagq testing
affects: [02-reader, 03-schema, 04-inspect, 05-query, 06-output, "every later phase's tests consume these fixtures"]

# Tech tracking
tech-stack:
  added: []  # no new deps — rosbags/numpy were already synced by 01-01
  patterns:
    - "Format-aware message builders (ROS1 Header has seq, ROS2 does not — never share a builder across typestores)"
    - "Session-scoped pytest fixture generates bags into tmp_path_factory; no binary bags committed"
    - "Dev-only tools/ package added to sys.path inside the test file (not installed, not in conftest)"

key-files:
  created:
    - tools/__init__.py
    - tools/make_fixtures.py
    - tests/test_fixtures.py
  modified: []

key-decisions:
  - "Generator lives in tools/ (dev artifact, not in rosbagger_core/bagq runtime path); not added to either package's deps"
  - "Fixtures generated per-test into tmp_path_factory — no committed binaries (version-coupled to rosbags; .gitignore excludes fixtures/ and out/)"
  - "Per-format header helper: ROS1 passes seq=0, ROS2 omits it (rosbags 0.11.2 Pitfall 3)"
  - "ROS2 Writer uses verified version=9 (required kwarg) + module-level StoragePlugin (Pitfalls 1-2); ROS1 uses the separate rosbags.rosbag1.Writer"
  - "Image blob included now (2x2 rgb8, 12-byte data) per O-4 — saves a Phase 3 fixture change for QURY-07"

patterns-established:
  - "Format-aware message construction: build std_msgs/msg/Header per typestore (ROS1 seq vs ROS2 no-seq)"
  - "tmp_path_factory session fixture for deterministic, uncommitted fixture bags"
  - "Repo-root sys.path bootstrap inside a test module to import the non-installed dev tools/ package"

requirements-completed:
  - "SC3: a generator produces ROS1, ROS2-sqlite, and MCAP fixture bags"
  - "DoD: test suite runs with no ROS install using rosbags-written fixture bags (ROS1 + ROS2 + MCAP)"

# Metrics
duration: 6min
completed: 2026-05-22
---

# Phase 1 Plan 03: Fixture-Bag Generator Summary

**A no-ROS `rosbags` fixture generator (`tools/make_fixtures.py`) that writes ROS1 `.bag` + ROS2 sqlite3 + ROS2 MCAP bags with forward-looking Twist/Imu/Image content, plus tests that round-trip all three through `AnyReader`.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-22T06:31Z (approx)
- **Completed:** 2026-05-22T06:37Z (approx)
- **Tasks:** 2
- **Files created:** 3

## Accomplishments

- `tools/make_fixtures.py` writes tiny bags in all three target formats with **no ROS installed**, using the verified rosbags 0.11.2 write API (`Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3|.MCAP)` for ROS2; the separate `rosbags.rosbag1.Writer` + `serialize_ros1` for ROS1).
- Fixtures carry **forward-looking content** so Phases 2-3 need no fixture change: `/cmd_vel` `geometry_msgs/msg/Twist` (nested scalars, no header → QURY-02/04), `/imu` `sensor_msgs/msg/Imu` (`header.stamp` + `float64[9]` covariance → QURY-03/04), `/image` `sensor_msgs/msg/Image` (2×2 rgb8, 12-byte `uint8[]` blob → QURY-07).
- `tests/test_fixtures.py` round-trips each format through `rosbags.highlevel.AnyReader`: a parametrized re-open test (≥1 message + tuple-shape assertions), a topic-coverage test, a deserialized `/imu` content test (`header.stamp` + length-9 covariance), and an `/image` blob round-trip test.
- The generator is importable (`from tools.make_fixtures import make_all_fixtures`) and runnable (`python -m tools.make_fixtures [DEST]`) for manual `bagq` use against on-disk bags.
- Full suite: **13 passed, 100% coverage** on the shipped packages (gate ≥80% met); the ROS-free import graph of the generator is proven (no `rclpy`/`rosbag2_py` leak into `sys.modules`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Fixture-bag generator (ROS1 + ROS2 sqlite3 + ROS2 MCAP) with forward-looking content** - `9740e04` (feat)
2. **Task 2: Round-trip tests via AnyReader + content assertions** - `6da2850` (test)

**Plan metadata:** see final `docs(01-03)` commit.

## Files Created/Modified

- `tools/__init__.py` - makes `tools` an importable dev package (so `from tools.make_fixtures import ...` and `python -m tools.make_fixtures` both work); explicitly NOT a runtime dep of either shipped package.
- `tools/make_fixtures.py` - the fixture-bag generator: `write_ros1_bag` / `write_ros2_sqlite_bag` / `write_ros2_mcap_bag` / `make_all_fixtures`, a format-aware `_make_header`, deterministic timestamps, and a `main()` for `python -m tools.make_fixtures`.
- `tests/test_fixtures.py` - session-scoped `fixture_bags` fixture (in this file, not conftest.py) + parametrized re-open / topic / Imu-content / Image-blob tests through `AnyReader`.

## Decisions Made

- **Generator placement in `tools/`** (not `rosbagger_core`): it is a dev artifact, kept out of the shipped runtime path and out of both packages' dependency metadata.
- **No committed binary bags:** bags are version-coupled to `rosbags`, so they are generated per-test into `tmp_path_factory`; `.gitignore` already excludes `fixtures/` and `out/`. Verified zero `*.bag`/`*.db3`/`*.mcap` artifacts in the repo.
- **Per-format header helper:** ROS1 `Header(seq=0, stamp=..., frame_id=...)` vs ROS2 `Header(stamp=..., frame_id=...)` (rosbags 0.11.2 Pitfall 3 — a shared builder raises on the missing `seq`).
- **Verified ROS2 Writer signature:** `version=9` is a required keyword arg and `StoragePlugin` is a module-level export of `rosbags.rosbag2` (Pitfalls 1-2). Confirmed live via `inspect.signature` before writing code.
- **Image blob included now (O-4):** a tiny 2×2 rgb8 Image with a 12-byte `data` array, so the heavy-blob substrate for QURY-07 exists in Phase 1 (same API, saves a Phase 3 change).
- **numpy dtypes pinned** for serialized array/scalar fields (`np.zeros(9, dtype=np.float64)` for covariances; `np.uint32`/`np.uint8` for Image `height`/`width`/`step`/`is_bigendian`; `np.arange(..., dtype=np.uint8)` for `data`) so CDR/ROS1 serialization is unambiguous.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made the dev-only `tools` package importable under pytest**
- **Found during:** Task 2 (round-trip tests)
- **Issue:** `tools` is a directory at the repo root, not an installed distribution like `rosbagger_core`/`bagq`. Under pytest's default import mode (with a `src/` layout and `testpaths=["tests"]`), the repo root is not on `sys.path`, so `from tools.make_fixtures import make_all_fixtures` raised `ModuleNotFoundError: No module named 'tools'` at collection. (My earlier ad-hoc `uv run python -c "from tools..."` succeeded only because invoking python from the repo root puts cwd on `sys.path[0]` — pytest does not.)
- **Fix:** Prepended the repo root (`Path(__file__).resolve().parent.parent`) to `sys.path` inside `tests/test_fixtures.py`, guarded by a membership check, with the `tools` import marked `# noqa: E402`. Scoped to this test file so it touches **neither** `tests/conftest.py` **nor** the root `pyproject.toml` (both owned by plan 01-02). This respects the plan's file-ownership boundary while making the generator importable.
- **Files modified:** tests/test_fixtures.py
- **Verification:** `PYTHONPATH="" uv run pytest tests/test_fixtures.py` → 8 passed; full suite `PYTHONPATH="" uv run pytest` → 13 passed, 100% coverage.
- **Committed in:** 6da2850 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The fix was required for the test to import the generator at all and is the minimal in-file solution that preserves plan 01-02's ownership of `conftest.py` and `pyproject.toml`. No scope creep.

## Issues Encountered

- **Plan's Task 2 verify command (`-p no:cov`) errors out.** `-p no:cov` unregisters the pytest-cov plugin, after which pytest cannot parse the `--cov*` flags that plan 01-02 placed in `addopts`, raising `error: unrecognized arguments: --cov=...`. Worked around at verification time only by clearing addopts (`-o addopts=""`) instead. This is an invocation-only note — no committed code or config was changed (the coverage flags belong to 01-02's `pyproject.toml`).
- **Host ROS-on-PYTHONPATH hazard.** As documented in 01-02's summary, this dev machine sources ROS 2 Humble onto `PYTHONPATH`, which makes bare `pytest`/`python` auto-load ROS's `launch_testing` pytest11 plugin and can leak ROS modules. All local verification runs were prefixed with `PYTHONPATH=""`. This is an invocation-only workaround; nothing was baked into committed code or CI (CI is ROS-free).
- **`rosbags` has no `__version__` attribute** — used `importlib.metadata.version("rosbags")` (→ 0.11.2) during live API verification. Cosmetic; no impact on the deliverable.

## Threat Surface Scan

No new security surface beyond the plan's `<threat_model>`:
- **T-01-FIX-ROS (mitigate):** generator imports only `rosbags`/`numpy`/stdlib — confirmed no `rclpy`/`rosbag2_py` import statement and a ROS-free `sys.modules` after import.
- **T-01-FIX-WRITE (accept):** writes only to a caller-supplied directory (`tmp_path` in tests; `.gitignore`d `fixtures/` for the manual `__main__` default). No path traversal surface.
- **T-01-FIX-BIN (mitigate):** no binary bags committed; `tools/make_fixtures.py` is the regeneration path. Verified zero bag artifacts tracked or untracked.

## Known Stubs

None. The generator is fully wired — every fixture format writes and round-trips through `AnyReader` with real, deserializable content. Nothing is placeholder/empty.

## Next Phase Readiness

- **Phase 2 (Reader):** the three fixture bags are the substrate for `BagReader` + `AnyReader` tests; round-trip + `header.stamp` carry are proven (READ-04).
- **Phase 3 (Schema):** forward-looking content is in place — nested scalars (Twist), `header.stamp`-present (Imu) vs absent (Twist) for `stamp` NULL handling (QURY-04), `float64[9]` covariance for LIST columns (QURY-03), and the Image `uint8[]` blob for lazy materialization (QURY-07). No fixture change should be needed.
- The generator's API (`make_all_fixtures(dest) -> {"ros1","ros2_sqlite","ros2_mcap"}`) is a small internal contract later phases consume.
- **Note for later test authors:** the dev-only `tools` package is importable from tests only because `tests/test_fixtures.py` bootstraps the repo root onto `sys.path`. If a future plan needs `tools` from multiple test modules, consider centralizing that bootstrap (e.g., in `conftest.py` or via a pytest `pythonpath`/`rootdir` setting) — both belong to the pytest-config owner.

## Self-Check: PASSED

- FOUND: tools/__init__.py
- FOUND: tools/make_fixtures.py
- FOUND: tests/test_fixtures.py
- FOUND: .planning/phases/01-scaffold-test-harness/01-03-SUMMARY.md
- FOUND: commit 9740e04 (Task 1)
- FOUND: commit 6da2850 (Task 2)

---
*Phase: 01-scaffold-test-harness*
*Completed: 2026-05-22*
