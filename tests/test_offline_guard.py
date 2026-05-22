"""The load-bearing offline-import invariant.

These two tests protect the architectural "universal / no-ROS" promise for the
life of the repo: the offline packages (``rosbagger_core``, ``bagq``) must never
pull in a ROS module, directly or transitively. The ``no_ros`` fixture
(tests/conftest.py) installs a ``sys.meta_path`` blocker so the assertion is
meaningful on both a clean CI runner AND this ROS-equipped dev box.
"""

import importlib
import subprocess
import sys

import pytest

# The heavy query/data stack that MUST stay out of the import graph until a
# backend/schema function is actually called (05-01 W2 — converts the previously
# ad-hoc "light __init__" check into a permanent regression test).
_HEAVY_STACK = {"duckdb", "sqlglot", "pyarrow"}


def test_core_imports_without_ros(no_ros):
    """Under the blocker, ROS modules raise ImportError but the offline packages still import."""
    for mod in ("rclpy", "rosbag2_py"):
        with pytest.raises(ImportError):
            importlib.import_module(mod)
    importlib.import_module("rosbagger_core")  # must still succeed
    importlib.import_module("bagq")


def test_no_ros_leaked_into_sys_modules():
    """Importing the offline packages must not populate sys.modules with any ROS module."""
    import bagq  # noqa: F401
    import rosbagger_core  # noqa: F401

    leaked = [m for m in sys.modules if m.split(".")[0] in {"rclpy", "rosbag2_py"}]
    assert leaked == [], f"offline import pulled in ROS modules: {leaked}"


def _heavy_modules_after_import(*import_targets: str) -> list[str]:
    """Return the heavy-stack modules in sys.modules after importing ``import_targets``.

    Spawned in a FRESH interpreter (with an empty PYTHONPATH to neutralize the
    host ROS leak) so an already-imported duckdb/sqlglot/pyarrow in THIS test
    process — the suite imports all three — cannot mask a real leak. This is the
    same fresh-subprocess technique as test_schema_arrow.py's pyarrow/rosbags
    check, extended to the full heavy query stack.
    """
    imports = "; ".join(f"import {t}" for t in import_targets)
    heavy = sorted(_HEAVY_STACK)
    code = (
        "import sys; "
        f"{imports}; "
        f"heavy={heavy!r}; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in heavy]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": ""},
    )
    return [m for m in result.stdout.strip().split(",") if m]


def test_import_core_does_not_pull_heavy_query_stack():
    """`import rosbagger_core` must NOT load duckdb/sqlglot/pyarrow (light __init__).

    The heavy stack may only load when a backend/schema function is actually
    called — never on the bare top-level import. Regression test for the 05-01
    backend seam (W2): keeps `rosbagger_core/__init__` light forever.
    """
    leaked = _heavy_modules_after_import("rosbagger_core")
    assert leaked == [], f"import rosbagger_core leaked the heavy stack: {leaked}"


def test_import_backend_subpackage_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.backend` must NOT load duckdb/sqlglot/pyarrow either.

    The backend package's ``__init__`` reserves the seam but stays light: duckdb
    only loads via ``import rosbagger_core.backend.duckdb_backend`` (the documented
    entry), not on the package import. Regression test for the 05-01 W2 invariant.
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.backend")
    assert leaked == [], f"import rosbagger_core.backend leaked the heavy stack: {leaked}"


def test_import_output_subpackage_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.output` must NOT load duckdb/sqlglot/pyarrow either.

    The Phase 6 output module (``render.py``/``export.py``) and its re-exporting
    ``__init__`` keep their top levels stdlib-only: pyarrow/duckdb are imported
    INSIDE the function bodies (``rows_for_display``/``to_json``/``write_table``),
    so binding the re-exported names on package import pulls in no heavy stack.
    Regression test for the 06-01 output seam (06-RESEARCH Pitfall 6).
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.output")
    assert leaked == [], f"import rosbagger_core.output leaked the heavy stack: {leaked}"


def test_import_errors_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.errors` must NOT load duckdb/sqlglot/pyarrow.

    The Phase 7 typed errors (``UnknownTableError``/``UnknownColumnError``/
    ``UnresolvedTypeError``) are plain ``ValueError`` subclasses importing only
    stdlib ``difflib`` — they NEVER import the library exceptions they wrap
    (``duckdb.BinderException``/rosbags ``AnyReaderError``), which are caught
    where those libraries are already imported (07-RESEARCH Pitfall 6). This keeps
    ``import rosbagger_core.errors`` light enough that the CLI could even import it
    at top level.
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.errors")
    assert leaked == [], f"import rosbagger_core.errors leaked the heavy stack: {leaked}"


def test_import_errors_does_not_pull_rosbags():
    """`import rosbagger_core.errors` must NOT pull ``rosbags`` either (stdlib-only).

    A fresh subprocess (empty PYTHONPATH neutralizes the host ROS leak) asserts no
    ``rosbags`` module lands in ``sys.modules`` after importing the errors module —
    the ``UnresolvedTypeError`` guidance is a plain string and references no rosbags
    import (07-RESEARCH Pitfall 6 / §3).
    """
    code = (
        "import sys; import rosbagger_core.errors; "
        "leaked=[m for m in sys.modules if m.split('.')[0] == 'rosbags']; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": ""},
    )
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"import rosbagger_core.errors pulled in rosbags: {leaked}"
