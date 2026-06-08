# rosbagger_ros — ROS 2 bringup package (launch the desktop GUI)

**Date:** 2026-06-08
**Status:** Approved (brainstorming) — ready for planning
**Quick task:** to be assigned by /gsd-quick

## Goal

Let a user clone rosbagger into a ROS 2 (colcon) workspace, `colcon build`, and
open the existing self-contained desktop cockpit with one command:

```bash
ros2 launch rosbagger_ros desktop.launch.py            # empty GUI
ros2 launch rosbagger_ros desktop.launch.py bag:=/path/to/bag
```

Because the GUI launches inside the sourced ROS environment, its live features
(record / replay / RViz / Rerun) automatically operate on the same ROS graph as
the rest of the launch — no extra wiring.

## Non-goals (explicit scope guard)

- **No** node-wrapping of record/replay as individual ROS nodes.
- **No** ament-ification of the 7 existing pip packages — they stay pure-Python /
  uv / offline. The zero-ROS offline guarantee (regression-locked by
  `tests/test_offline_guard.py`) must remain intact.
- **No** TUI launch file (trivial to add later; out of scope now).
- **No** PyPI/ROS-index release of the bringup package.

## Architecture

A single thin **`ament_python`** package, `rosbagger_ros`, living **outside** the
uv workspace so it cannot perturb the pip packaging:

- Location: top-level `ros/rosbagger_ros/` (NOT under `packages/`, whose `*` glob
  is the uv workspace members list). It carries **no** `pyproject.toml`, so
  `uv sync` / `uv build` ignore it entirely; `colcon build` discovers it by its
  `package.xml`.
- It builds to a normal ROS package whose `share/rosbagger_ros/launch/` holds the
  launch file. It contains **no application logic** — it only launches the
  already-installed `rosbagger-desktop` executable.

### File tree

```
ros/rosbagger_ros/
├── package.xml              # format 3, build_type ament_python
├── setup.py                 # installs launch/ + ament marker + package.xml
├── setup.cfg                # script_dir / install_scripts for ament_python
├── resource/rosbagger_ros   # empty ament resource-index marker
├── rosbagger_ros/__init__.py
├── launch/
│   └── desktop.launch.py
└── README.md                # install + usage (the runtime-Python requirement)
```

### `desktop.launch.py` behavior

- Declares one launch argument: `bag` (default `''`).
- Uses an `OpaqueFunction` to build the command at launch time:
  `cmd = ['rosbagger-desktop']`, and appends the bag path **only if** `bag` is
  non-empty (a bare launch opens the GUI with no bag).
- Runs it via `ExecuteProcess(cmd=cmd, output='screen')` — **not** `Node`, because
  `rosbagger-desktop` is a pip console-script on `PATH`, not an ament-registered
  executable.
- Registers `OnProcessExit(target_action=gui) -> EmitEvent(Shutdown())` so closing
  the GUI window cleanly terminates `ros2 launch`.

### `package.xml`

- `format="3"`, `<export><build_type>ament_python</build_type></export>`.
- `name` rosbagger_ros, `version` 0.2.0, `license` MIT, maintainer Allen Devaraj.
- `<exec_depend>ros2launch</exec_depend>`, `<exec_depend>python3</exec_depend>`.
- Comment noting the rosbagger GUI/tools are pip-installed (not a rosdep key) and,
  optionally, `rviz2` for the GUI's RViz feature.

## Runtime requirement (documented, not code)

The launch only execs `rosbagger-desktop`, so it must be on `PATH`. For the GUI's
**live** features it must run under a Python that can also import ROS's `rclpy` /
`rosbag2_py`. Two supported recipes (in the package README):

1. **apt-ROS box (simplest):** one-transaction
   `pip install --user ./packages/rosbagger-core ./packages/rosbagger-record ./packages/rosbagger-replay ./packages/rosbagger-rerun ./packages/rosbagger-desktop`
   → `~/.local/bin/rosbagger-desktop` runs under the system Python that already has
   `rclpy`.
2. **venv:** create with `--system-site-packages` on a ROS-sourced shell so the
   venv sees `rclpy`, then `./install.sh --desktop` into it.

Offline panels (inspect / query / tf) work under any Python; only the live
features need the shared-with-ROS Python. This is a documentation concern, not a
code change.

## Testing

- The package is ROS-only and sits outside `packages/` and pytest `testpaths`, so
  the offline CI / uv suite does not touch it (offline guarantee unaffected).
- Add a no-ROS-needed guard: a `python -c "compile(open(...).read(), ..., 'exec')"`
  syntax check on `desktop.launch.py` (compiles without importing `launch`),
  runnable anywhere including CI.
- Real verification on a ROS-sourced machine (this box has ROS):
  `ros2 launch rosbagger_ros desktop.launch.py --show-args` lists the `bag` arg and
  exits 0; a manual launch opens the GUI.

## Acceptance criteria

1. `ros/rosbagger_ros/` exists with the file tree above; carries no `pyproject.toml`.
2. `uv sync --locked` and `uv build` are unaffected (the new dir is invisible to uv);
   `tests/test_offline_guard.py` still passes (no new ROS coupling in the 7 packages).
3. `colcon build --packages-select rosbagger_ros` succeeds; after
   `source install/setup.bash`, `ros2 launch rosbagger_ros desktop.launch.py --show-args`
   shows the `bag` argument and exits 0.
4. The launch-file syntax-compile check passes with no ROS installed.
5. README documents both install recipes and the `bag:=` usage.
