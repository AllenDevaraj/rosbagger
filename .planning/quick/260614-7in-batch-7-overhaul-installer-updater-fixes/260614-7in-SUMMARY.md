---
quick_id: 260614-7in
slug: batch-7-overhaul-installer-updater-fixes
description: Batch 7 — install.sh/update.sh hardening B1–B7 (PEP 668, --venv, manifest, --help, stash reminder, worktree, colcon $HOME).
status: complete
date: 2026-06-14
commits: 5e740cd
---

# Quick Task 260614-7in — Summary

## Outcome
All seven installer/updater findings fixed (shell-only; verified via `bash -n` + targeted runs).
The headline: **B4** — `./install.sh --user` and bare `./update.sh` no longer fail on
Ubuntu 24.04 / Debian 12+ (PEP 668), which was breaking the exact friend-install flow.

## What changed (`5e740cd`)
- **B4** install.sh: probe the `EXTERNALLY-MANAGED` marker; add `--break-system-packages` to the
  three `--user` pip calls only when present (safe empty-array expansion under `set -u`).
- **B7** install.sh: `--venv` rejects a missing/option-looking value (`--venv --plot` no longer
  eats `--plot`).
- **B2** install.sh writes `.rosbagger-install` (mode/venv/face-flags); update.sh with no flags
  reuses it instead of guessing `--desktop --user` (which installed a divergent `--user` copy
  over a venv install). `.rosbagger-install` gitignored.
- **B3** update.sh: `-h/--help` prints usage and exits BEFORE any fetch/checkout/reinstall.
- **B1** update.sh: a `--force` autostash is reminded on EVERY exit (success or failure) via an
  EXIT trap — it used to scroll away and strand the stash silently.
- **B6** update.sh: branch on whether the local default branch exists → no misleading "a branch
  named main already exists" when it is checked out in another worktree; clear error instead.
- **B5** update.sh: refuse `$HOME`/`/` as the detected colcon workspace (a `~/src/rosbagger`
  clone no longer runs `colcon build` from `$HOME`), and require `colcon` to be installed.

## Verify
- `bash -n` clean on both. `update.sh --help` prints usage, HEAD unchanged. `install.sh
  --venv --plot` → clean error, exit≠0. PEP 668 probe + `${arr[@]+...}` empty-expansion safe
  on bash 5.1. Manifest round-trip parse OK. Real `./install.sh --venv <tmp>` wrote the
  manifest and `bagq` ran from the venv.

## Out of scope
- T4 (version-string sync across ~20 files) — a separate release-tooling task.
