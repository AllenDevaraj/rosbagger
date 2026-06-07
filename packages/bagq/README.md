# bagq

A universal **DuckDB-for-bags** SQL CLI — query ROS 1 / ROS 2 / MCAP bags and
export CSV / Parquet / plots, with **no ROS install required**.

```bash
bagq info my.bag                                    # topics, types, Hz, duration
bagq tables my.bag                                  # SQL table + column schema
bagq query "SELECT t, t_ns FROM cmd_vel" my.bag     # run SQL over the bag
```

## Install

`bagq` depends on `rosbagger-core`. Once published to PyPI:

```bash
pip install bagq
```

Until then, install both from source in one transaction — see the monorepo
[INSTALL.md](https://github.com/AllenDevaraj/rosbagger/blob/main/INSTALL.md) or run
`./install.sh` in the repo.

## License

MIT — part of the [rosbagger](https://github.com/AllenDevaraj/rosbagger) monorepo.
