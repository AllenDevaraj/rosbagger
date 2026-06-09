---
quick_id: 260609-2ry
slug: add-short-rosbagger-command-install-sh-u
description: Add a short `rosbagger` command for the desktop GUI + an install.sh --user global mode, and document the two launch paths.
status: complete
date: 2026-06-09
commits: e85cd00, 6960941, 5ec6bf9
---

# Quick Task 260609-2ry — Summary

## Outcome

The self-contained desktop cockpit now has **two simple launch paths**, both
documented and verified on this machine:

1. **`rosbagger`** — one word, from any terminal:
   ```bash
   ./install.sh --desktop --user     # one-time, global to ~/.local/bin
   rosbagger                         # or: rosbagger /path/to/bag
   ```
2. **`ros2 launch`** — unchanged from 260608-6s3:
   ```bash
   ros2 launch rosbagger_ros desktop.launch.py [bag:=/path/to/bag]
   ```

## What changed

### `feat(desktop)` — short `rosbagger` command (`e85cd00`)
- `packages/rosbagger-desktop/pyproject.toml`: added
  `rosbagger = "rosbagger_desktop.cli:main"` alongside the existing
  `rosbagger-desktop` (both ship). Same argparse-first entry point, so
  `rosbagger --help` builds no Qt object and pulls no ROS.
- The ROS launch file still calls `rosbagger-desktop` (no churn, per plan).

### `feat(install)` — `install.sh --user` global mode (`6960941`)
- New `--user` flag installs the one-transaction spec list into the user site
  (`~/.local/bin`) instead of a venv — no activation, works from any terminal.
  Prints a PATH hint (via `site.getuserbase()`); promotes `rosbagger` in the
  completion hints of both modes.
- **Distro-pip build fix:** `--user` mode seeds `hatchling` + `packaging>=24.2`
  into the user site and builds with `--no-build-isolation`. Under a distro
  system `pip` (here: pip 22.0.2 on Ubuntu), an *isolated* source build picks up
  the OLD system `packaging` (21.3, no `packaging.licenses`) from
  `/usr/lib/python3/dist-packages` and dies on our PEP 639 / Metadata 2.4 license
  fields. Building against the ambient (user-site) toolchain — where a modern
  `packaging` shadows the system one — avoids it. The default venv path is
  unchanged (a fresh venv isolates cleanly).

### `docs` — document the two methods (`5ec6bf9`)
- Root `README.md`: replaced "ROS 2 (optional)" with an **"Open the desktop GUI"**
  section showing both paths plainly; noted `--user` in the install flag list.
- `ros/rosbagger_ros/README.md`: `./install.sh --desktop --user` is now the
  simplest install; the accurate `--no-build-isolation` manual one-liner is in a
  `<details>`.
- `packages/rosbagger-desktop/README.md`: notes the `rosbagger` alias.
- `INSTALL.md`: documents `--user` (incl. the distro system-pip build-deps note).

## Verification (evidence)

- **Built artifact:** `rosbagger_desktop-0.2.0-*.whl` `entry_points.txt` lists
  **both** `rosbagger` and `rosbagger-desktop` → `rosbagger_desktop.cli:main`.
- **Real `--user` install on this box:** `./install.sh --desktop --user` built
  and installed all 6 packages to `~/.local/bin` (previously failed with
  `No module named 'packaging.licenses'` before the `--no-build-isolation` fix).
- **Runs from a neutral cwd:** from `/tmp`, `rosbagger --help` and
  `rosbagger-desktop --help` exit 0 (no Qt window built); `bagq --version` →
  `bagq 0.2.0`; `which rosbagger` → `~/.local/bin/rosbagger`.
- **Offline guarantee intact:** `uv sync --locked` clean (scripts aren't deps —
  `uv.lock` unchanged); `tests/test_offline_guard.py` **22 passed**.
- `bash -n install.sh` clean; `--help` shows `--user`; unknown-flag guard intact.

## Out of scope (unchanged)
- `desktop.launch.py` internals (still calls `rosbagger-desktop`).
- The 7 pip packages stay pure / offline-importable.
- No PyPI publish, no GitHub push (those remain the user's call).

## Heads-up
- This task added the **capability + your local install**. The repo still has
  unpushed commits (this task's three + the prior `rosbagger_ros` work); a
  `git push` is needed before a friend cloning from GitHub gets any of it.
