#!/usr/bin/env bash
# rosbagger updater — fetch the latest rosbagger and reinstall, in ONE command.
#
# Run this from your rosbagger checkout — a plain `git clone`, OR a git submodule
# inside your project (e.g. <ws>/src/rosbagger). It does the whole update for you:
#   1. brings the checkout to the latest commit on the default branch
#      (no separate `git pull` / `git submodule update` needed),
#   2. re-runs ./install.sh with your flags + --reinstall (so the new code is
#      actually applied, even if the version number didn't change),
#   3. if it's sitting in a colcon workspace (.../src/rosbagger), rebuilds the
#      `rosbagger_ros` launch package (when ROS is sourced) or prints the command.
#
# Usage:
#   ./update.sh [install flags...]   # default install flags: --desktop --user
#   ./update.sh --desktop --user     # explicit (same as the default)
#   ./update.sh --all                # update an `--all` install
#   ./update.sh --no-build           # skip the colcon rebuild step
#   ./update.sh --force              # update even with local changes (stashes them)
#
# Pass the SAME install flags you originally installed with.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"

# Split our own flags (--no-build / --force) from the install.sh pass-through.
do_build=1
force=0
passthrough=()
for a in "$@"; do
  case "$a" in
    --no-build) do_build=0 ;;
    --force)    force=1 ;;
    *)          passthrough+=("$a") ;;
  esac
done
# Default install face if the caller named none.
if [ ${#passthrough[@]} -eq 0 ]; then passthrough=(--desktop --user); fi

cd "$ROOT"

# --- 1. Don't clobber uncommitted work ---
if [ -n "$(git status --porcelain)" ]; then
  if [ "$force" = 1 ]; then
    echo ">> local changes present — stashing them (--force). Restore later with: git stash pop"
    git stash push -u -m "rosbagger update.sh autostash" >/dev/null
  else
    echo "error: you have uncommitted changes in $ROOT." >&2
    echo "       commit or stash them first, or re-run with --force to stash them." >&2
    exit 1
  fi
fi

# --- 2. Fetch + move the working tree to the latest default-branch commit ---
# Works for a normal clone (already on a branch) AND a submodule (usually a
# detached HEAD at a pinned commit): we attach to the default branch and
# fast-forward it to origin's tip.
echo ">> fetching latest from origin"
git fetch --quiet origin || { echo "error: 'git fetch origin' failed (network or remote issue)." >&2; exit 1; }

# Resolve the default branch WITHOUT tripping set -e/pipefail when origin/HEAD
# isn't set (common in submodules / fresh clones) — strip the prefix with
# parameter expansion and fall back to main.
DEFAULT_BRANCH="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
DEFAULT_BRANCH="${DEFAULT_BRANCH#origin/}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"

before="$(git rev-parse HEAD)"
git checkout --quiet "$DEFAULT_BRANCH" 2>/dev/null \
  || git checkout --quiet -b "$DEFAULT_BRANCH" --track "origin/$DEFAULT_BRANCH"
git merge --ff-only --quiet "origin/$DEFAULT_BRANCH" || {
  echo "error: could not fast-forward '$DEFAULT_BRANCH' to 'origin/$DEFAULT_BRANCH'." >&2
  echo "       your local branch may have diverged — resolve it manually, then re-run." >&2
  exit 1
}
after="$(git rev-parse HEAD)"

if [ "$before" = "$after" ]; then
  echo ">> already up to date ($(git rev-parse --short HEAD))"
else
  echo ">> updated $(git rev-parse --short "$before") -> $(git rev-parse --short "$after")"
fi

# --- 3. Reinstall the GUI/CLI (idempotent; --reinstall forces same-version code) ---
echo ">> reinstalling: ./install.sh ${passthrough[*]} --reinstall"
./install.sh "${passthrough[@]}" --reinstall

# --- 4. If we're inside a colcon workspace (.../src/rosbagger), refresh the launch pkg ---
WS=""
if [ "$(basename "$(dirname "$ROOT")")" = "src" ]; then
  WS="$(dirname "$(dirname "$ROOT")")"
fi

if [ "$do_build" = 1 ] && [ -n "$WS" ]; then
  echo
  if [ -n "${ROS_DISTRO:-}" ]; then
    echo ">> colcon workspace detected at $WS — rebuilding rosbagger_ros"
    ( cd "$WS" && colcon build --symlink-install --packages-select rosbagger_ros )
    echo "   done — re-source it:  source \"$WS/install/setup.bash\""
  else
    echo ">> colcon workspace detected at $WS, but no ROS is sourced."
    echo "   To rebuild the launch package, source ROS and run:"
    echo "      ( cd \"$WS\" && colcon build --symlink-install --packages-select rosbagger_ros )"
  fi
fi

# --- 5. Submodule pointer reminder (a submodule's .git is a FILE, not a dir) ---
if [ "$before" != "$after" ] && [ -f "$ROOT/.git" ]; then
  echo
  echo "Note: rosbagger is a submodule. To record this update in your project, run"
  echo "      from your project root:  git add <path-to>/rosbagger && git commit -m 'bump rosbagger'"
fi

echo
echo "Update complete."
