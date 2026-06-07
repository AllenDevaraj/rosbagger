# rosbagger-core

Pure-Python **offline** library for reading and querying ROS 1 / ROS 2 / MCAP
bags — **no ROS install required** (no `rclpy`, no `rosbag2_py`). It is the
reader/query engine behind [`bagq`](https://github.com/AllenDevaraj/rosbagger/tree/main/packages/bagq)
and the rest of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) suite.

## Install

```bash
pip install rosbagger-core
```

`rosbagger-core` has only PyPI dependencies, so it installs standalone. (Until
the suite is published to PyPI, install from source — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).)

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
