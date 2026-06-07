# rosbagger-record

Live ROS 2 topic discovery and bag recording for the
[rosbagger](https://github.com/AllenDevaraj/rosbagger) suite.

> **Requires a sourced ROS 2 environment** (e.g. `source /opt/ros/humble/setup.bash`).
> `rclpy` / `rosbag2_py` are provided by your ROS distro and lazy-imported, so the
> package imports cleanly even without ROS — it only needs ROS when you actually record.

## Install

Once published to PyPI:

```bash
pip install rosbagger-record
```

`rosbagger-record` depends on `rosbagger-core`; until published, co-install both
from source in one transaction — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
