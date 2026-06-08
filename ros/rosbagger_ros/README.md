# rosbagger_ros

ROS 2 (`ament_python`) bringup for
[rosbagger](https://github.com/AllenDevaraj/rosbagger). One launch file that opens
the self-contained **rosbagger desktop cockpit** inside your sourced ROS
environment:

```bash
ros2 launch rosbagger_ros desktop.launch.py                  # open the GUI
ros2 launch rosbagger_ros desktop.launch.py bag:=/path/bag   # open a bag
```

Launched this way, the GUI inherits your ROS environment, so its live
record / replay / RViz / Rerun features operate on the **same ROS graph** as the
rest of your launch. Closing the GUI window shuts the launch down.

## Build

Clone rosbagger into your colcon workspace's `src/` and build just this package
(`colcon` ignores the 7 pip packages — they carry no `package.xml`):

```bash
cd ~/ros2_ws
git clone https://github.com/AllenDevaraj/rosbagger src/rosbagger
colcon build --packages-select rosbagger_ros
source install/setup.bash
```

## Install the GUI it launches (one-time)

This package only *launches* `rosbagger-desktop` — you must install the rosbagger
tools so that command exists. They must run under a Python that can also import
ROS's `rclpy` / `rosbag2_py` for the **live** features (offline panels work under
any Python). Pick one:

**A. apt-installed ROS (simplest)** — install into the system Python that already
has `rclpy`, in ONE transaction (the packages resolve each other only when
co-named in a single command):

```bash
cd src/rosbagger
pip install --user \
  ./packages/rosbagger-core ./packages/rosbagger-record \
  ./packages/rosbagger-replay ./packages/rosbagger-rerun \
  ./packages/rosbagger-desktop
```

Make sure `~/.local/bin` is on your `PATH` so `rosbagger-desktop` is found.

**B. virtualenv** — let it see ROS by creating it with `--system-site-packages` on
a ROS-sourced shell, then use the repo installer:

```bash
source /opt/ros/humble/setup.bash
python3 -m venv --system-site-packages .venv-ros
. .venv-ros/bin/activate
cd src/rosbagger && ./install.sh --desktop --venv "$VIRTUAL_ENV"
```

> Offline-only? The inspect / query / tf panels need no ROS at all — any Python
> with the packages installed works. Only record / replay / RViz / Rerun need the
> shared-with-ROS Python above.

## Troubleshooting

**`colcon build` fails with** `canonicalize_version() got an unexpected keyword
argument 'strip_trailing_zero'` — your user-site (`~/.local`) has a newer
`setuptools` than your `packaging` (e.g. setuptools 82 + packaging 21). This breaks
*any* `ament_python` build, not just this one. Either bring `packaging` up to match:

```bash
pip install --user -U "packaging>=24"
```

or build once with the system toolchain (ignores `~/.local`):

```bash
PYTHONNOUSERSITE=1 colcon build --packages-select rosbagger_ros
```

## What this package is (and isn't)

- A thin `ament_python` launcher: `package.xml` + `setup.py` + one launch file. No
  application logic.
- It does **not** turn rosbagger into a ROS package — the 7 pip packages stay
  pure-Python and ROS-free to import (the project's offline guarantee). This
  package just adds a `ros2 launch` entry point for the desktop GUI.

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
