# rosbagger

A modular monorepo of ROS bag tooling. Its first deliverable, **`bagq`**, is a
universal "DuckDB-for-bags" SQL CLI that queries ROS 1 / ROS 2 / MCAP bags with
**no ROS install required**, and exports CSV / Parquet / plots.

> Query and understand the data inside any ROS bag from one command — without
> writing a one-off script and without needing ROS installed.

## Layout

This is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
with two independently-installable packages:

| Package | Path | Role |
|---------|------|------|
| `rosbagger-core` | `packages/rosbagger-core/` | Pure-Python offline library (no ROS dependency) |
| `bagq` | `packages/bagq/` | The CLI; depends on `rosbagger-core` |

## Install

### End-user (plain `pip`)

`bagq` depends on `rosbagger-core`, and that dependency resolves from the local
package — so install **both** packages in a **single** `pip` command:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install ./packages/rosbagger-core ./packages/bagq
bagq --help
```

Installing `bagq` alone (`pip install ./packages/bagq`) fails to resolve
`rosbagger-core` — name both. `bagq` is not published to PyPI; v0.1 is a
local install.

For the optional plotting support (matplotlib), add the `plot` extra. Quote it
so your shell does not glob-expand the brackets:

```bash
pip install ./packages/rosbagger-core "./packages/bagq[plot]"
```

### Developer (uv workspace)

Reproducible from the committed `uv.lock`:

```bash
uv sync --locked --dev   # create .venv, install both packages + dev tools
uv run bagq --help       # run the CLI console-script
uv run pytest            # run the test suite
```

## Usage

```bash
# Inspect a bag: per-topic message type, count, approximate Hz, plus duration and size.
bagq info my.bag

# List each topic's SQL table name and column schema (heavy blobs marked lazy).
bagq tables my.bag

# Run SQL over a bag. Default prints a rich table to stdout.
bagq query "SELECT t, t_ns FROM cmd_vel" my.bag

# Show the version.
bagq --version           # -> bagq 0.1.0
```

`bagq query` routes its result to one of several sinks:

- `-o out.csv` / `-o out.parquet` — write a file, picking the format by
  extension. An explicit `-o` always wins over `--format`.
- `--format table|csv|parquet|json` — choose the sink when no `-o` is given:
  `table` (default) renders a rich table; `csv` streams CSV to stdout; `parquet`
  without `-o` errors (it is binary — use `-o out.parquet`); `json` emits
  temporal-safe records.
- `--plot [FILE]` — write a minimal headless line chart of the numeric result
  columns versus time. A bare `--plot` writes `plot.png` in the current
  directory; `--plot FILE` writes that file. (Requires the `plot` extra.)

You can pass more than one bag path to any command (they merge as one
time-ordered dataset). Run `bagq --help` or any subcommand's `--help` for the
full reference; `python -m bagq ...` works too.

## Errors that teach

When a query references an unknown table or column, or a bag carries a custom
message type that cannot be resolved, `bagq` prints a single helpful line (with
a did-you-mean suggestion, the available tables, or the columns in scope) and
exits non-zero — no Python traceback.

## Offline / no ROS

`rosbagger-core` and `bagq` import and run with **no ROS installed** — no
`rclpy`, no `rosbag2_py`. The test suite uses bags written by
[`rosbags`](https://gitlab.com/ternaris/rosbags), so everything (including CI)
runs anywhere without a ROS environment.
