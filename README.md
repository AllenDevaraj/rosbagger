# rosbagger

A modular monorepo of ROS bag tooling. Its headline tool, **`bagq`**, is a
universal "DuckDB-for-bags" SQL CLI that queries ROS 1 / ROS 2 / MCAP bags with
**no ROS install required**, and exports CSV / Parquet / plots.

> Query and understand the data inside any ROS bag from one command — without
> writing a one-off script and without needing ROS installed.

## Quick start

Clone, then install the offline CLI with the one-command installer:

```bash
git clone https://github.com/AllenDevaraj/rosbagger
cd rosbagger
./install.sh                 # creates .venv and installs bagq + rosbagger-core
source .venv/bin/activate
bagq info my.bag
```

Prefer plain `pip`? The packages aren't on PyPI yet, so install from the local
checkout — and **name both in one command** (see [Why one command](#why-one-command)):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install ./packages/rosbagger-core ./packages/bagq
```

## Usage (`bagq`)

```bash
# Inspect a bag: per-topic message type, count, approximate Hz, duration, size.
bagq info my.bag

# List each topic's SQL table name and column schema.
bagq tables my.bag

# Run SQL over a bag (default prints a rich table; -o writes CSV/Parquet by extension).
bagq query "SELECT t, t_ns FROM cmd_vel" my.bag
bagq query "SELECT * FROM cmd_vel" my.bag -o out.parquet

# Plot numeric columns vs time (needs the `plot` extra).
bagq query "SELECT t, linear.x FROM cmd_vel" my.bag --plot speed.png
```

Pass more than one bag to any command and they merge as one time-ordered dataset.
When a query names an unknown table or column, `bagq` prints one helpful line (with
a did-you-mean) and exits non-zero — no Python traceback. Run `bagq --help` for the
full reference.

## The suite

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) of seven
independently-installable packages (all **v0.2.0**):

| Package | Role | Needs ROS? |
|---------|------|------------|
| `rosbagger-core` | Pure-Python offline reader / query engine | no |
| `bagq` | The DuckDB-for-bags SQL CLI | no |
| `rosbagger-gui` | Textual terminal cockpit | no (live panels via `[live]`) |
| `rosbagger-desktop` | Native PySide6 desktop cockpit | no (live/viz need sourced ROS) |
| `rosbagger-record` | Live ROS 2 topic discovery + recording | sourced ROS 2 |
| `rosbagger-replay` | Live ROS 2 replay with transport controls | sourced ROS 2 |
| `rosbagger-rerun` | Bag → Rerun visualization bridge | no (lazy) |

`rosbagger-core` and `bagq` import and run with **no ROS installed** — no `rclpy`,
no `rosbag2_py`. The live packages need a sourced ROS 2 environment, but only
lazy-import `rclpy` at call time, so importing them stays ROS-free and the offline
tools never pull ROS. The test suite (and CI) runs anywhere using bags written by
[`rosbags`](https://gitlab.com/ternaris/rosbags).

## Install

`./install.sh` covers the common cases:

```bash
./install.sh            # offline CLI: bagq + rosbagger-core
./install.sh --plot     # + matplotlib for `bagq query --plot`
./install.sh --gui      # + the offline Textual cockpit
./install.sh --desktop  # + the PySide6 desktop cockpit
./install.sh --live     # + live record/replay (needs a sourced ROS 2)
./install.sh --all      # everything
./install.sh --help     # all flags (incl. --venv DIR, --user)
```

<a name="why-one-command"></a>
**Why one command?** Each package pins its sibling (`rosbagger-core`) by version
spec only; the workspace source that resolves siblings is stripped from built
wheels, and nothing is on PyPI yet. So a lone `pip install ./packages/bagq` can't
find `rosbagger-core` and fails — you must **name every package you need in one
`pip` invocation**. The installer does this for you. For the full matrix (git
installs, downstream uv projects, the `[live]` extra), see [INSTALL.md](./INSTALL.md).

## Open the desktop GUI

Two ways to launch the self-contained desktop cockpit — pick whichever fits:

**1. `rosbagger` — from any terminal.** Install once into your user site and the
command is on your `PATH` everywhere, no venv to activate:

```bash
./install.sh --desktop --user      # installs to ~/.local/bin
rosbagger                          # open the cockpit  (or: rosbagger /path/to/bag)
```

(Prefer a venv? `./install.sh --desktop`, then `source .venv/bin/activate` and run
`rosbagger`. `rosbagger-desktop` is the same command under its long name.)

**2. `ros2 launch` — inside your ROS 2 project.** The repo ships a thin bringup
package, `rosbagger_ros` (under [`ros/`](./ros/rosbagger_ros/)). Drop it in a colcon
workspace, build just that package, and launch:

```bash
colcon build --packages-select rosbagger_ros
ros2 launch rosbagger_ros desktop.launch.py [bag:=/path/to/bag]
```

Either way the GUI runs inside your sourced ROS environment, so its live
record / replay / RViz / Rerun features share your ROS graph. Setup details (and
the one-time GUI install the launch file needs) are in
[`ros/rosbagger_ros/README.md`](./ros/rosbagger_ros/README.md). The 7 Python
packages stay ROS-free — `rosbagger_ros` is only a launcher.

## Updating

Already installed it? Pull the latest and reinstall in **one command**, from your
rosbagger checkout:

```bash
./update.sh                  # fetch latest + reinstall (defaults to --desktop --user)
```

`update.sh` brings the checkout to the latest commit — works whether rosbagger is
a plain clone **or a git submodule** (no separate `git pull` / `git submodule
update`) — then re-runs `./install.sh … --reinstall` so the new code applies even
when the version number is unchanged. Pass the same install flags you used (e.g.
`./update.sh --all`). Inside a colcon workspace it also rebuilds `rosbagger_ros`
for you (or prints the `colcon build` command when ROS isn't sourced). Tip: build
the launch package once with `colcon build --symlink-install` and routine updates
won't need a rebuild at all.

## Development

```bash
uv sync --locked --dev   # create .venv, install all packages + dev tools
uv run bagq --help
uv run pytest
```

## Publishing

The packages are PyPI-ready (valid metadata, `twine check`-clean). To publish them,
see [PUBLISHING.md](./PUBLISHING.md). Once published, the one-command caveat goes
away — siblings resolve from PyPI and `pip install bagq` just works.

## License

[MIT](./LICENSE).
