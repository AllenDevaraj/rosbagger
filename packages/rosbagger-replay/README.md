# rosbagger-replay

Live ROS 2 bag replay with play / pause / step / seek / rate / loop transport
controls for the [rosbagger](https://github.com/AllenDevaraj/rosbagger) suite.

> **Requires a sourced ROS 2 environment** (e.g. `source /opt/ros/humble/setup.bash`).
> `rclpy` is provided by your ROS distro and lazy-imported, so the package imports
> cleanly even without ROS — it only needs ROS when you actually replay.

## Install

Once published to PyPI:

```bash
pip install rosbagger-replay
```

`rosbagger-replay` depends on `rosbagger-core`; until published, co-install both
from source in one transaction — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
