# rosbagger-gui

Textual terminal cockpit for the
[rosbagger](https://github.com/AllenDevaraj/rosbagger) suite — inspect and query
ROS bags from your terminal, with optional live record/replay panels.

The base install is **offline** (no ROS). The live record/replay panels are gated
behind the `[live]` extra and a sourced ROS 2 environment.

## Install

Once published to PyPI:

```bash
pip install rosbagger-gui          # offline cockpit
pip install "rosbagger-gui[live]"  # + live record/replay panels (needs ROS)
```

`rosbagger-gui` depends on `rosbagger-core` (and, with `[live]`, on
`rosbagger-record` + `rosbagger-replay`); until published, co-install the siblings
in one transaction — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
