# rosbagger-rerun

Bag-to-[Rerun](https://rerun.io) visualization bridge for the
[rosbagger](https://github.com/AllenDevaraj/rosbagger) suite — converts ROS 2
messages into Rerun archetypes so a replay can be live-mirrored into the Rerun viewer.

Importing the package pulls **no ROS and no Rerun** (both are lazy-imported). The
Rerun viewer SDK is an optional `[sdk]` extra, installed on demand.

## Install

Once published to PyPI:

```bash
pip install rosbagger-rerun          # converter only
pip install "rosbagger-rerun[sdk]"   # + the Rerun viewer SDK
```

Until published, install from source — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md).

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
