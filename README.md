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

## Quickstart

```bash
uv sync            # create the .venv and editable-install both packages + dev tools
uv run bagq --help # run the CLI console-script
uv run pytest      # run the test suite
```

### Plain-`pip` fallback (no uv)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e packages/rosbagger-core -e packages/bagq
```

Full documentation lands in a later phase.
