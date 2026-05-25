#!/usr/bin/env bash
#
# proof_external_install.sh — autonomous, path-based external-install proof.
#
# Proves the v0.2.0 wheel-resolution gap is closed WITHOUT any network/remote
# dependency: it co-installs all five workspace packages by local path into a
# THROWAWAY venv (never the workspace .venv), then smoke-checks the CLI, the
# imports, the offline invariant, and that tools/ is not in any wheel — all
# from a neutral cwd OUTSIDE the monorepo.
#
# Why a single pip invocation: each package's wheel carries a bare sibling spec
# (e.g. rosbagger-core>=0.2,<0.3) with NO source baked in ([tool.uv.sources] is
# dev-only and stripped from wheels). We publish to no index, so the sibling
# resolves only when the co-installed package is present as a command argument
# in the same transaction. Naming all five at once is the resolution crux.
#
# HOST NOTE: this dev box sources ROS onto PYTHONPATH, which leaks into a bare
# `python`/`pip` and would silently mask the offline assertion. EVERY venv
# python/pip/CLI invocation below is therefore prefixed `PYTHONPATH=""`.
#
# On success, the final line is exactly `PROOF OK` and the exit code is 0.
# Any failed assertion aborts early (set -e) with a nonzero exit.

set -euo pipefail

# Resolve the repo root from this script's own location, so the proof runs from
# any cwd (NOT a hardcoded absolute path). scripts/ lives at the repo root.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

if [ ! -d "${REPO_ROOT}/packages/rosbagger-core" ]; then
  echo "FATAL: could not locate packages/ under repo root ${REPO_ROOT}" >&2
  exit 1
fi

# Throwaway venv — NEVER the workspace .venv. Cleaned up on any exit.
TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT
VENV="${TMP}/venv"
python3 -m venv "${VENV}"
PY="${VENV}/bin/python"
PIP="${VENV}/bin/pip"

echo "==> Co-installing all five packages by local path into ${VENV} (one transaction)"
# ONE pip invocation naming all five local paths — the bare sibling spec
# (rosbagger-core>=0.2,<0.3) resolves against the co-installed rosbagger-core.
# rosbagger-gui[live] additionally pulls record+replay via the declarative extra.
PYTHONPATH="" "${PIP}" install \
  "${REPO_ROOT}/packages/rosbagger-core" \
  "${REPO_ROOT}/packages/bagq" \
  "${REPO_ROOT}/packages/rosbagger-record" \
  "${REPO_ROOT}/packages/rosbagger-replay" \
  "${REPO_ROOT}/packages/rosbagger-gui[live]"

# Neutral cwd OUTSIDE the monorepo — so nothing can resolve via workspace source.
cd "${TMP}"

echo "==> [1/6] rosbagger-gui --help exits 0"
PYTHONPATH="" "${VENV}/bin/rosbagger-gui" --help >/dev/null

echo "==> [2/6] bagq --version is exactly 'bagq 0.2.0'"
BAGQ_VERSION=$(PYTHONPATH="" "${VENV}/bin/bagq" --version)
if [ "${BAGQ_VERSION}" != "bagq 0.2.0" ]; then
  echo "FATAL: expected 'bagq 0.2.0', got '${BAGQ_VERSION}'" >&2
  exit 1
fi

echo "==> [3/6] all five packages import"
PYTHONPATH="" "${PY}" -c \
  "import rosbagger_gui, rosbagger_core, bagq, rosbagger_record, rosbagger_replay"

echo "==> [4/6] offline invariant: base import rosbagger_gui leaks no rclpy/rosbag2_py"
PYTHONPATH="" "${PY}" - <<'PYEOF'
import sys
import rosbagger_gui  # noqa: F401  base import must stay ROS-free
leaked = [m for m in sys.modules if m.split(".")[0] in {"rclpy", "rosbag2_py"}]
assert not leaked, f"ROS leaked into sys.modules after import rosbagger_gui: {leaked}"
PYEOF

echo "==> [5/6] tools-not-in-wheel: import tools raises ModuleNotFoundError"
PYTHONPATH="" "${PY}" - <<'PYEOF'
try:
    import tools  # noqa: F401  dev-only; must NOT ship in any wheel
except ModuleNotFoundError:
    pass
else:
    raise SystemExit("FATAL: 'tools' is importable from the installed venv — it leaked into a wheel")
PYEOF

echo "==> [6/6] all smoke checks passed"
echo "PROOF OK"
