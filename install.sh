#!/usr/bin/env bash
# rosbagger one-command installer.
#
# Creates (or reuses) a virtualenv and installs the rosbagger packages you ask
# for in a SINGLE pip transaction — which is required, because each package pins
# its siblings by bare version spec and nothing is on PyPI yet (see INSTALL.md,
# "Why one command"). Run it from anywhere; paths resolve to this script's repo.
#
# Usage:
#   ./install.sh [--venv DIR | --user] [--plot] [--gui] [--desktop] [--live] [--all]
#
# With no flags it installs the offline CLI: rosbagger-core + bagq.
set -euo pipefail

# Repo root = the directory containing this script (so it works from any CWD).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
PKGS="$ROOT/packages"

VENV="$ROOT/.venv"
plot=0; gui=0; live=0; desktop=0; all=0; user=0; reinstall=0

usage() {
  cat <<'USAGE'
rosbagger installer

Usage: ./install.sh [options]

Options:
  --venv DIR   Target virtualenv directory (default: ./.venv)
  --user       Install into your user site instead of a venv, so the commands
               (rosbagger, bagq, ...) land on ~/.local/bin and work from ANY
               terminal with no activation. (Ignores --venv.)
  --plot       Add the bagq[plot] extra (matplotlib) for `bagq query --plot`
  --gui        Add the offline Textual cockpit (rosbagger-gui)
  --desktop    Add the PySide6 desktop cockpit (rosbagger-desktop + siblings)
  --live       Add live record/replay + the GUI live panels (needs a sourced ROS 2)
  --all        Install everything (plot + desktop + live GUI)
  --reinstall  Force-reinstall the rosbagger packages even at the same version,
               without re-resolving deps (used by update.sh so same-version code
               changes actually apply)
  -h, --help   Show this help

With no flags, installs the offline CLI: rosbagger-core + bagq.
Everything is installed in ONE pip transaction so the siblings co-resolve.
Override the interpreter with PYTHON=/path/to/python3 ./install.sh
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --venv)
      # B7: ${2:?} only rejects empty/unset — a following FLAG (`--venv --plot`) would be
      # swallowed as the directory. Reject a missing or option-looking value explicitly.
      case "${2:-}" in
        ""|-*) echo "error: --venv needs a directory argument (got '${2:-}')" >&2; exit 2 ;;
      esac
      VENV="$2"; shift 2 ;;
    --venv=*) VENV="${1#*=}"; [ -n "$VENV" ] || { echo "error: --venv= needs a directory" >&2; exit 2; }; shift ;;
    --user) user=1; shift ;;
    --reinstall) reinstall=1; shift ;;
    --plot) plot=1; shift ;;
    --gui) gui=1; shift ;;
    --desktop) desktop=1; shift ;;
    --live) live=1; shift ;;
    --all) all=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

# --all is shorthand for everything.
if [ "$all" = 1 ]; then plot=1; live=1; desktop=1; fi

# Resolve which siblings each requested face needs.
need_record=0; need_replay=0; need_rerun=0
gui_mode=0   # 0 = none, 1 = offline gui, 2 = gui with live panels
[ "$gui" = 1 ] && gui_mode=1
if [ "$live" = 1 ]; then gui_mode=2; need_record=1; need_replay=1; fi
if [ "$desktop" = 1 ]; then need_record=1; need_replay=1; need_rerun=1; fi

# Build the one-transaction path-spec list (always core + bagq).
specs=("$PKGS/rosbagger-core")
if [ "$plot" = 1 ]; then specs+=("$PKGS/bagq[plot]"); else specs+=("$PKGS/bagq"); fi
[ "$need_record" = 1 ] && specs+=("$PKGS/rosbagger-record")
[ "$need_replay" = 1 ] && specs+=("$PKGS/rosbagger-replay")
[ "$need_rerun" = 1 ]  && specs+=("$PKGS/rosbagger-rerun")
if [ "$gui_mode" = 2 ]; then specs+=("$PKGS/rosbagger-gui[live]")
elif [ "$gui_mode" = 1 ]; then specs+=("$PKGS/rosbagger-gui"); fi
[ "$desktop" = 1 ] && specs+=("$PKGS/rosbagger-desktop")

# Pick an interpreter.
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: '$PYTHON' not found. Install Python >=3.10 or set PYTHON=..." >&2
  exit 1
fi

# Reconstruct the FACE flags (for the install manifest update.sh reads, B2) — the user's
# original face selection, minus mechanism flags like --user/--venv/--reinstall.
face_flags=()
[ "$plot" = 1 ] && face_flags+=(--plot)
[ "$gui" = 1 ] && face_flags+=(--gui)
[ "$desktop" = 1 ] && face_flags+=(--desktop)
[ "$live" = 1 ] && face_flags+=(--live)
[ "$all" = 1 ] && face_flags+=(--all)

# Record what was installed so `update.sh` (run with no flags) reinstalls the SAME face into
# the SAME target instead of guessing (B2/T5). Written only after a successful install below.
write_manifest() {  # $1 = mode (user|venv)
  {
    echo "mode=$1"
    [ "$1" = venv ] && echo "venv=$VENV"
    echo "flags=${face_flags[*]-}"
  } > "$ROOT/.rosbagger-install" 2>/dev/null || true
}

# PEP 668 (Debian 12+, Ubuntu 23.04+): the system Python ships an EXTERNALLY-MANAGED marker
# and pip>=23 REFUSES `pip install --user` without --break-system-packages — so `--user`
# (and bare `update.sh`) failed outright on a modern Ubuntu. Detect the marker and add the
# flag only when it is actually present (older pip without the marker never sees it). B4.
user_break=()  # extra pip flags for the --user path; empty unless externally-managed
if [ "$user" = 1 ]; then
  _em=$("$PYTHON" - <<'PY' 2>/dev/null || echo False
import os, sysconfig
print(os.path.exists(os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED")))
PY
)
  if [ "$_em" = True ]; then
    user_break=(--break-system-packages)
    echo ">> note: this Python is PEP 668 'externally-managed'; adding --break-system-packages for the --user install."
  fi
fi

# --- User-site (global) install: no venv. Commands land on ~/.local/bin and work
# from ANY terminal with no activation. On a box with ROS, installing into the
# ROS-capable interpreter also lets the live features import rclpy once ROS is
# sourced. --user takes precedence over --venv.
if [ "$user" = 1 ]; then
  echo ">> installing ${#specs[@]} package(s) into your user site (pip --user), one transaction:"
  for s in "${specs[@]}"; do echo "     ${s#"$ROOT"/}"; done
  # Put the build toolchain in the user site, then build with
  # --no-build-isolation so it uses that ambient toolchain. Why: under a distro
  # system pip (Debian/Ubuntu), an ISOLATED build can pick up the OLD system
  # `packaging` from /usr/lib/pythonX/dist-packages and die with
  # "No module named 'packaging.licenses'" — our packages use PEP 639 SPDX
  # licensing (Metadata 2.4), which needs packaging>=24.2. A modern `packaging`
  # in the user site shadows the system one for the ambient build. (The default
  # venv path doesn't need this — a fresh venv isolates cleanly.)
  "$PYTHON" -m pip install --user ${user_break[@]+"${user_break[@]}"} -q "hatchling>=1.18" "packaging>=24.2" || {
    echo "error: could not install build prerequisites (hatchling, packaging>=24.2) into the user site." >&2
    exit 1
  }
  "$PYTHON" -m pip install --user ${user_break[@]+"${user_break[@]}"} --no-build-isolation "${specs[@]}"
  if [ "$reinstall" = 1 ]; then
    # Same-version code changes are skipped by a plain install ("already
    # satisfied"); force just our packages (deps already handled above).
    echo ">> --reinstall: force-reinstalling the rosbagger packages (no deps)"
    "$PYTHON" -m pip install --user ${user_break[@]+"${user_break[@]}"} --no-build-isolation --no-deps --force-reinstall "${specs[@]}"
  fi
  write_manifest user

  USERBIN="$("$PYTHON" -c 'import os, site; print(os.path.join(site.getuserbase(), "bin"))' 2>/dev/null || echo "$HOME/.local/bin")"
  echo
  echo "Done. Commands installed to: $USERBIN"
  case ":$PATH:" in
    *":$USERBIN:"*) : ;;
    *) echo "  NOTE: $USERBIN is not on your PATH yet. Add this to ~/.bashrc:"
       echo "      export PATH=\"$USERBIN:\$PATH\"" ;;
  esac
  echo
  echo "Try it from any terminal:"
  echo "    bagq --help"
  [ "$gui_mode" != 0 ] && echo "    rosbagger-gui [BAG]"
  [ "$desktop" = 1 ] && echo "    rosbagger [BAG]            # the desktop cockpit (= rosbagger-desktop)"
  if [ "$live" = 1 ] || [ "$desktop" = 1 ]; then
    echo
    echo "Live record/replay/RViz/Rerun need a sourced ROS 2 environment, e.g.:"
    echo "    source /opt/ros/humble/setup.bash"
  fi
  exit 0
fi

# Create the venv if it does not already exist (reuse is non-destructive).
if [ ! -x "$VENV/bin/python" ]; then
  echo ">> creating virtualenv at $VENV"
  "$PYTHON" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

echo ">> installing ${#specs[@]} package(s) in one transaction:"
for s in "${specs[@]}"; do echo "     ${s#"$ROOT"/}"; done

"$VPY" -m pip install --upgrade pip >/dev/null 2>&1 || true
"$VPY" -m pip install "${specs[@]}"
if [ "$reinstall" = 1 ]; then
  # Same-version code changes are skipped by a plain install ("already
  # satisfied"); force just our packages (deps already handled above).
  echo ">> --reinstall: force-reinstalling the rosbagger packages (no deps)"
  "$VPY" -m pip install --no-deps --force-reinstall "${specs[@]}"
fi
write_manifest venv

echo
echo "Done. Activate the environment and try it:"
echo "    source $VENV/bin/activate"
echo "    bagq --help"
[ "$gui_mode" != 0 ] && echo "    rosbagger-gui [BAG]"
[ "$desktop" = 1 ] && echo "    rosbagger [BAG]            # the desktop cockpit (= rosbagger-desktop)"
if [ "$live" = 1 ]; then
  echo
  echo "Live record/replay needs a sourced ROS 2 environment, e.g.:"
  echo "    source /opt/ros/humble/setup.bash"
fi
