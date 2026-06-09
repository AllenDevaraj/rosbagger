---
quick_id: 260609-5yl
slug: add-update-sh-one-command-updater-instal
description: One-command `update.sh` (fetch + reinstall + optional colcon rebuild) and `install.sh --reinstall` so same-version updates apply.
status: complete
date: 2026-06-09
commits: 9730f9e, 942654a, b7c76e3
---

# Quick Task 260609-5yl — Summary

## Outcome

Fetching new updates is now **one command** for every consumer — plain clone or
git submodule, ROS or not:

```bash
./update.sh                  # fetch latest + reinstall (defaults to --desktop --user)
```

No separate `git pull` / `git submodule update`. Inside a colcon workspace it also
rebuilds `rosbagger_ros`, so ROS users are immediately ready to `ros2 launch` again.

## What changed

### `feat(install)` — `install.sh --reinstall` (`9730f9e`)
- New `--reinstall` flag adds a second pip pass with `--no-deps --force-reinstall`
  over the local path specs (both venv and `--user`; keeps `--no-build-isolation`
  under `--user`). **Why:** a plain re-install reports "already satisfied" and
  skips packages whose version is unchanged — so code pushed without a version
  bump would silently not apply. The force pass guarantees the new code lands.
  Deps are untouched (the first pass handles them).

### `feat(install)` — `update.sh` (`942654a`)
Run from the rosbagger checkout. Steps:
1. Refuses on a dirty tree unless `--force` (then `git stash -u`).
2. `git fetch` + attach to the default branch (`origin/HEAD`, fallback `main`) +
   `git merge --ff-only` to origin's tip — **handles a submodule's detached HEAD**,
   so no separate `git submodule update`.
3. Re-runs `./install.sh <forwarded flags, default --desktop --user> --reinstall`.
4. In a colcon workspace (`…/src/rosbagger`): `colcon build --symlink-install
   --packages-select rosbagger_ros` when ROS is sourced, else prints that command.
5. Submodule pointer-bump reminder when HEAD moved (`.git` is a file).
- Own flags `--no-build` / `--force`; everything else forwards to `install.sh`.

### `docs` (`b7c76e3`)
- Root `README.md`: new **"Updating"** section. `ros/rosbagger_ros/README.md`:
  **"Updating"** note. Both highlight the `--symlink-install` tip that keeps the
  launch package out of the routine update loop.

## Bug found + fixed during verification
- update.sh first run died right after `git fetch` (exit 1): under `set -euo
  pipefail`, `git symbolic-ref … | sed` **fails** when `origin/HEAD` is unset
  (here it is), and `pipefail` propagated it into the `DEFAULT_BRANCH` assignment →
  `set -e` killed the script. Fixed: drop the pipe, use parameter expansion
  (`${VAR#origin/}`) + `|| true`, and hardened `git fetch` with a clear error.
  Folded into `942654a`.

## Verification (evidence)
- `bash -n` clean on both scripts; `install.sh --help` lists `--reinstall`.
- `./install.sh --desktop --user --reinstall` ran the force pass (uninstalled +
  reinstalled all 6 at 0.2.0); `rosbagger --help` exit 0.
- `./update.sh --no-build --force` → stashed, fetched, force-reinstalled all 6,
  `Update complete.`, **exit 0**; the dirty-tree guard correctly refused (exit 1)
  on the first attempt without `--force`.
- Scope: only `install.sh`, `update.sh`, `README.md`, `ros/rosbagger_ros/README.md`
  changed; **`desktop.launch.py` untouched**; offline guard **22 passed**.

## Out of scope (unchanged)
- The 7 pip packages stay pure / offline-importable (no package code touched).
- `desktop.launch.py` internals.
- No PyPI publish, no version bump (those remain the user's call — and a version
  bump is the clean alternative to `--reinstall` for tagged releases).
