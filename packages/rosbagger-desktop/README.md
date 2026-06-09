# rosbagger-desktop

Native **PySide6 (Qt)** desktop cockpit for the
[rosbagger](https://github.com/AllenDevaraj/rosbagger) suite — browse, query,
replay, and visualize ROS bags in a real desktop window.

The offline panels (inspect / query / tf) need no ROS. The live record/replay
panels and RViz / Rerun visualization light up when a ROS 2 environment is sourced.

## Install

Once published to PyPI:

```bash
pip install rosbagger-desktop
rosbagger [BAG]            # short command (alias of `rosbagger-desktop [BAG]`)
```

This package installs two equivalent console commands — `rosbagger` (short) and
`rosbagger-desktop` (long). Both open the same cockpit.

`rosbagger-desktop` pulls `rosbagger-core`, `rosbagger-record`, `rosbagger-replay`,
and `rosbagger-rerun`; until published, co-install the siblings in one transaction
— see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
