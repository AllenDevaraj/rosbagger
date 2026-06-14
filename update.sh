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

usage() {
  cat <<'USAGE'
rosbagger updater — fetch the latest rosbagger and reinstall, in ONE command.

Usage: ./update.sh [install flags...] [--no-build] [--force]

With NO install flags, reuses the flags recorded by your last ./install.sh (the
.rosbagger-install manifest); if none is recorded it defaults to --desktop --user.

  --no-build   Skip the colcon rebuild step (in a colcon workspace)
  --force      Update even with local changes (stashes them; reminds you to restore)
  -h, --help   Show this help and exit (does NOT touch the repo)
USAGE
}

# Split our own flags (--no-build / --force / --help) from the install.sh pass-through.
do_build=1
force=0
passthrough=()
for a in "$@"; do
  case "$a" in
    -h|--help)  usage; exit 0 ;;   # B3: help BEFORE any repo mutation
    --no-build) do_build=0 ;;
    --force)    force=1 ;;
    *)          passthrough+=("$a") ;;
  esac
done

# B2: if the caller named no install flags, reuse the face the LAST install.sh recorded
# (mode + venv + flags) instead of guessing --desktop --user — which silently installed a
# divergent --user copy when the user actually has a venv install. Fall back to the old
# default only when no manifest exists.
if [ ${#passthrough[@]} -eq 0 ]; then
  if [ -f "$ROOT/.rosbagger-install" ]; then
    m_mode=""; m_venv=""; m_flags=""
    while IFS='=' read -r k v; do
      case "$k" in mode) m_mode=$v ;; venv) m_venv=$v ;; flags) m_flags=$v ;; esac
    done < "$ROOT/.rosbagger-install"
    if [ "$m_mode" = user ]; then
      passthrough=(--user $m_flags)              # word-split $m_flags into --plot/--desktop/...
    elif [ "$m_mode" = venv ] && [ -n "$m_venv" ]; then
      passthrough=(--venv "$m_venv" $m_flags)
    else
      passthrough=(--desktop --user)
    fi
    echo ">> reusing recorded install flags: ${passthrough[*]}"
  else
    passthrough=(--desktop --user)
    echo ">> no recorded install (.rosbagger-install) — defaulting to: ${passthrough[*]}"
    echo "   if you installed differently, re-run:  ./update.sh <the flags you installed with>"
  fi
fi

cd "$ROOT"

# B1: if --force stashes the user's work, remind them on EVERY exit path (success OR a
# mid-update failure) — the single inline hint scrolled away under build output and any
# later failure stranded the stash silently. DEFAULT_BRANCH may be unset if we die early.
STASHED=0
DEFAULT_BRANCH=""
_remind_stash() {
  if [ "$STASHED" = 1 ]; then
    echo >&2
    echo "Reminder: --force stashed your uncommitted changes before updating — they are NOT lost." >&2
    echo "  Restore with:  git stash pop   (you are on '${DEFAULT_BRANCH:-the default branch}';" >&2
    echo "  switch back to your branch first if needed)." >&2
  fi
}
trap _remind_stash EXIT

# --- 1. Don't clobber uncommitted work ---
if [ -n "$(git status --porcelain)" ]; then
  if [ "$force" = 1 ]; then
    echo ">> local changes present — stashing them (--force). Restore later with: git stash pop"
    git stash push -u -m "rosbagger update.sh autostash" >/dev/null
    STASHED=1  # B1: the EXIT trap now reminds the user to restore, on success or failure
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
# B6: branch on whether the local default branch already EXISTS, so we never hit the
# misleading "a branch named X already exists" (which happened when X was checked out in
# another linked worktree and the real cause was swallowed by 2>/dev/null).
if git show-ref --verify --quiet "refs/heads/$DEFAULT_BRANCH"; then
  git checkout --quiet "$DEFAULT_BRANCH" || {
    echo "error: could not switch to '$DEFAULT_BRANCH' — is it checked out in another git worktree?" >&2
    echo "       switch this checkout to '$DEFAULT_BRANCH' manually, then re-run." >&2
    exit 1
  }
else
  git checkout --quiet -b "$DEFAULT_BRANCH" --track "origin/$DEFAULT_BRANCH" || {
    echo "error: could not create local '$DEFAULT_BRANCH' tracking 'origin/$DEFAULT_BRANCH'." >&2
    exit 1
  }
fi
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
  # B5: "parent dir is named src" alone matched a personal ~/src/rosbagger, setting WS=$HOME
  # and running `colcon build` from $HOME (crawling the whole home dir, dropping build/install/
  # log/ there). Refuse $HOME and / as the "workspace"; a real colcon ws is a dedicated dir.
  if [ "$WS" = "$HOME" ] || [ "$WS" = "/" ]; then
    echo ">> note: $ROOT looks like a personal clone (workspace would be '$WS'); skipping colcon."
    echo "   In a real colcon workspace ('<ws>/src/rosbagger'), update.sh rebuilds rosbagger_ros."
    WS=""
  fi
fi

if [ "$do_build" = 1 ] && [ -n "$WS" ]; then
  echo
  if [ -n "${ROS_DISTRO:-}" ] && command -v colcon >/dev/null 2>&1; then
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
