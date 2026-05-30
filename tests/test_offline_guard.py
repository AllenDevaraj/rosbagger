"""The load-bearing offline-import invariant.

These tests protect the architectural "universal / no-ROS" promise for the life of
the repo: the offline packages (``rosbagger_core``, ``bagq``) must never pull in a
ROS module, directly or transitively. The ``no_ros`` fixture (tests/conftest.py)
installs a ``sys.meta_path`` blocker so the assertion is meaningful on both a clean
CI runner AND this ROS-equipped dev box.

Phase 12 adds the offline↔LIVE boundary (D-11): ``rosbagger_record`` is the first
package that REQUIRES ROS at runtime, but it isolates ``rclpy`` / ``rosbag2_py``
behind LAZY function-body imports so ``import rosbagger_record`` itself stays
ROS-free in the uv venv. ``test_import_record_does_not_pull_ros`` regression-locks
that, and ``test_core_imports_without_ros`` / ``test_no_ros_leaked_into_sys_modules``
confirm adding the live member to the workspace did not regress the core/bagq
guarantee.
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


def test_import_alias_does_not_pull_heavy_data_stack():
    """`import rosbagger_core.backend.alias` must NOT load duckdb/pyarrow (Pitfall 6).

    The Phase 10 alias rewrite (``backend/alias.py``) is a pure ``sqlglot`` AST
    transform plus a dict literal. UNLIKE the other guards in this file, it
    LEGITIMATELY imports ``sqlglot`` at module top — ``sqlglot`` is a pure-Python
    locked dependency, NOT a ROS/data module, exactly like ``backend/resolve.py``
    and ``schema/identifiers.py`` (which already import it eagerly). So this guard
    asserts only that the HEAVY DATA stack — ``duckdb`` and ``pyarrow`` — does not
    leak; ``sqlglot`` appearing in the leak list is expected and fine. The pack is
    a plain dict, so importing the module pulls in neither the query engine
    (``duckdb``) nor the materialization layer (``pyarrow``). Regression test for
    10-RESEARCH Pitfall 6.
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.backend.alias")
    assert "duckdb" not in leaked, f"import rosbagger_core.backend.alias leaked duckdb: {leaked}"
    assert "pyarrow" not in leaked, f"import rosbagger_core.backend.alias leaked pyarrow: {leaked}"


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


def test_import_tf_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.tf` must NOT load duckdb/sqlglot/pyarrow (Decision 9).

    The Phase 9 TF analysis core (``tf.py``) keeps its top level stdlib-only
    (``dataclasses``/``statistics``) and is NEVER imported by ``rosbagger_core/__init__``;
    it consumes a PASSED-IN open reader, so it imports none of the heavy query stack
    (the query layer is deliberately bypassed — 09-RESEARCH Pitfall 3). Regression test
    for the TF offline invariant (09-RESEARCH Pitfall 5).
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.tf")
    assert leaked == [], f"import rosbagger_core.tf leaked the heavy stack: {leaked}"


def test_import_tf_does_not_pull_rosbags():
    """`import rosbagger_core.tf` must NOT pull ``rosbags`` either (no ROS, Pitfall 5).

    A fresh subprocess (empty PYTHONPATH neutralizes the host ROS leak) asserts no
    ``rosbags`` module lands in ``sys.modules`` after ``import rosbagger_core.tf`` — the
    TF core consumes an already-open, already-deserializing reader and imports no
    ``rosbags`` itself (mirrors the errors-module check above).
    """
    code = (
        "import sys; import rosbagger_core.tf; "
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
    assert leaked == [], f"import rosbagger_core.tf pulled in rosbags: {leaked}"


def test_import_edit_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.edit` must NOT load duckdb/sqlglot/pyarrow (Pitfall 5).

    The Phase 11 edit pipeline (``edit/operations.py`` + ``edit/pipeline.py`` and
    the re-exporting ``edit/__init__``) keeps its top level stdlib-only:
    ``operations`` imports only ``dataclasses`` and ``pipeline`` confines its
    ``rosbags`` Writer/Reader imports to function bodies. So re-exporting
    ``edit_bag`` / ``EditOps`` on package import pulls in none of the heavy query
    stack — the same discipline as the ``tf`` / ``output`` guards above. Regression
    test for the 11-RESEARCH offline invariant (Pitfall 5).
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.edit")
    assert leaked == [], f"import rosbagger_core.edit leaked the heavy stack: {leaked}"


def test_import_edit_does_not_pull_rosbags():
    """`import rosbagger_core.edit` must NOT pull ``rosbags`` either (no ROS, Pitfall 5).

    A fresh subprocess (empty PYTHONPATH neutralizes the host ROS leak) asserts no
    ``rosbags`` module lands in ``sys.modules`` after ``import rosbagger_core.edit`` —
    every ``rosbags`` Writer/``AnyReader`` import in ``edit/pipeline.py`` is LAZY
    inside a function body, so the bare module import binds none of it (mirrors the
    tf-module check above).
    """
    code = (
        "import sys; import rosbagger_core.edit; "
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
    assert leaked == [], f"import rosbagger_core.edit pulled in rosbags: {leaked}"


def test_import_events_does_not_pull_heavy_query_stack():
    """`import rosbagger_core.events` must NOT load duckdb/sqlglot/pyarrow (Pitfall 5).

    The Phase 11 event sidecar (``events.py``) keeps its top level stdlib-only
    (``pathlib``): ``pyarrow``/``pyarrow.parquet`` and the ``output.export`` writer
    are imported INSIDE the function bodies (``add_event``/``list_events``/the
    ``_event_schema`` builder), and ``sidecar_path`` is pure ``pathlib``. So
    ``import rosbagger_core.events`` pulls in none of the heavy query stack — the same
    discipline as the ``tf`` / ``edit`` / ``output`` guards above. Regression test for
    the 11-RESEARCH offline invariant (Pitfall 5).
    """
    leaked = _heavy_modules_after_import("rosbagger_core", "rosbagger_core.events")
    assert leaked == [], f"import rosbagger_core.events leaked the heavy stack: {leaked}"


def test_import_events_does_not_pull_rosbags():
    """`import rosbagger_core.events` must NOT pull ``rosbags`` either (no ROS, Pitfall 5).

    A fresh subprocess (empty PYTHONPATH neutralizes the host ROS leak) asserts no
    ``rosbags`` module lands in ``sys.modules`` after ``import rosbagger_core.events`` —
    the events sidecar reads/writes Parquet (``pyarrow``/the DuckDB-COPY writer), never
    a ROS bag, so it imports no ``rosbags`` at all (mirrors the tf/edit-module checks
    above).
    """
    code = (
        "import sys; import rosbagger_core.events; "
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
    assert leaked == [], f"import rosbagger_core.events pulled in rosbags: {leaked}"


def test_import_record_does_not_pull_ros():
    """`import rosbagger_record` must NOT pull rclpy/rosbag2_py (the offline↔live boundary, D-11).

    The Phase 12 live module isolates every ``rclpy`` / ``rosbag2_py`` import inside
    function bodies (``_require_ros`` / ``record`` / ``list_topics`` / the lazy import
    in ``discovery.discover_topics``), and ``errors.py`` / the ``select_topics`` filter
    are pure stdlib. So the bare top-level ``import rosbagger_record`` binds none of
    the ROS stack — the offline guarantee holds even though this package REQUIRES ROS
    at run time (12-RESEARCH Pitfall 5).

    Mechanism (mirrors the rosbags checks above): a FRESH interpreter with
    ``env={"PYTHONPATH": ""}``. The empty ``PYTHONPATH`` neutralizes this dev host's
    ROS-on-``PYTHONPATH`` leak, yet ``rosbagger_record`` is still importable because
    the uv workspace member is installed as an editable ``.pth`` in site-packages
    (which resolves regardless of ``PYTHONPATH``) — so this asserts the package's
    import GRAPH is ROS-free, not merely that ROS is off the path.
    """
    code = (
        "import sys; import rosbagger_record; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'rclpy', 'rosbag2_py'}]; "
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
    assert leaked == [], f"import rosbagger_record pulled in ROS modules: {leaked}"


def _ros_modules_after_import(*import_targets: str) -> list[str]:
    """Return the ROS-runtime modules in sys.modules after importing ``import_targets``.

    Spawned in a FRESH interpreter with ``env={"PYTHONPATH": ""}`` — the empty
    ``PYTHONPATH`` neutralizes this dev host's ROS-on-``PYTHONPATH`` leak, yet the uv
    workspace member is still importable via its editable ``.pth`` in site-packages (which
    resolves regardless of ``PYTHONPATH``) — so this asserts the package's import GRAPH is
    ROS-free, not merely that ROS is off the path. Only the ROS-RUNTIME modules
    (``rclpy`` / ``rosbag2_py``) are checked; ``rosbags`` (a pure-Python locked dep the
    source seam uses) is allowed.
    """
    imports = "; ".join(f"import {t}" for t in import_targets)
    code = (
        "import sys; "
        f"{imports}; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'rclpy', 'rosbag2_py'}]; "
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


def test_import_replay_does_not_pull_ros():
    """`import rosbagger_replay` must NOT pull rclpy/rosbag2_py (the offline↔live boundary, D-12).

    The Phase 13 live module isolates every ``rclpy`` / ``rosidl_runtime_py`` import inside
    function bodies (``_require_ros`` / the lazy front door + the publish sink in
    ``replay.py``), and ``errors.py`` / ``scheduler.py`` are pure stdlib while ``source.py``
    imports ``rosbags`` only (lazily). So the bare top-level ``import rosbagger_replay``
    binds none of the ROS RUNTIME stack — the offline guarantee holds even though this
    package REQUIRES ROS at run time (mirrors ``test_import_record_does_not_pull_ros``).

    Mechanism: a FRESH interpreter with ``env={"PYTHONPATH": ""}`` (the empty PYTHONPATH
    neutralizes this dev host's ROS-on-PYTHONPATH leak; the editable workspace member still
    resolves via its site-packages ``.pth``), so this asserts the package's import GRAPH is
    ROS-free, not merely that ROS is off the path.
    """
    leaked = _ros_modules_after_import("rosbagger_replay")
    assert leaked == [], f"import rosbagger_replay pulled in ROS modules: {leaked}"


def test_import_replay_submodules_do_not_pull_ros():
    """`import rosbagger_replay.scheduler` / `.source` must NOT pull rclpy/rosbag2_py either.

    The pure transport ``scheduler`` (Plan 02) is stdlib-only and the raw-CDR ``source``
    seam (Plan 01) imports ``rosbags`` only (and lazily) — neither touches the ROS RUNTIME.
    Importing both in a fresh ROS-free interpreter must leave ``sys.modules`` free of
    ``rclpy`` / ``rosbag2_py`` (``rosbags`` is an allowed pure-Python dep, not checked here).
    Pinning the submodules — not just the package ``__init__`` — proves the lazy boundary
    holds even if a future edit accidentally imports the ``.replay`` ROS sink eagerly.
    """
    leaked = _ros_modules_after_import("rosbagger_replay.scheduler", "rosbagger_replay.source")
    assert leaked == [], f"import rosbagger_replay submodules pulled in ROS modules: {leaked}"


def test_import_replay_fidelity_does_not_pull_ros():
    """`rosbagger_replay.fidelity` (StaticTracker + clock_stamp_ns) must NOT pull rclpy/rosbag2_py.

    The Phase-20 RViz-fidelity DECISION tier is stdlib-only and operates on the rosbags-free
    ReplayItem — the actual ``pub.publish()`` / ``Clock`` build is the live boundary in
    ``replay.py``. So importing the fidelity module (and the symbols re-exported from the
    front door) binds none of the ROS runtime, mirroring the scheduler/source guards: the
    static-republish + clock-stamp logic stays ROS-free so SC2 has a deterministic CI proof.
    """
    leaked = _ros_modules_after_import("rosbagger_replay.fidelity")
    assert leaked == [], f"import rosbagger_replay.fidelity pulled in ROS modules: {leaked}"


def test_import_gui_does_not_pull_ros():
    """`import rosbagger_gui` / `.app` must NOT pull rclpy/rosbag2_py (the GUI offline invariant).

    The Phase 14 Textual cockpit is a THIN FACE over the module APIs: its package top
    (``rosbagger_gui/__init__``) keeps the only ``rclpy`` touch inside the ``_detect_ros``
    capability probe's BODY; the App shell (``app.py``) imports only ``textual`` + the
    ROS-FREE ``rosbags`` typestore at top level; and the live record/replay panels confine
    every ``rclpy`` / ``rosbagger_record`` / ``rosbagger_replay`` import to worker / method
    bodies. So the bare top-level ``import rosbagger_gui`` (and ``import rosbagger_gui.app``,
    which pulls the offline panels) binds none of the ROS RUNTIME stack — the no-ROS promise
    holds for the new package even though its live panels REQUIRE ROS at run time (mirrors
    ``test_import_replay_does_not_pull_ros`` / ``test_import_record_does_not_pull_ros``).

    Mechanism: a FRESH interpreter with ``env={"PYTHONPATH": ""}`` (the empty PYTHONPATH
    neutralizes this dev host's ROS-on-PYTHONPATH leak; the editable workspace member still
    resolves via its site-packages ``.pth``), so this asserts the package's import GRAPH is
    ROS-free, not merely that ROS is off the path.
    """
    leaked = _ros_modules_after_import("rosbagger_gui", "rosbagger_gui.app")
    assert leaked == [], f"import rosbagger_gui pulled in ROS modules: {leaked}"


def test_import_core_does_not_pull_pyside6():
    """`import rosbagger_core` / `import bagq` must NOT pull PySide6 (the Qt-free invariant, D-04).

    Phase 16 adds the native PySide6 desktop GUI as a NEW isolated package
    (``rosbagger-desktop``); the load-bearing isolation guarantee is that the
    OFFLINE import graph stays not only ROS-free but ALSO Qt-free — a stray
    top-level ``from PySide6 ...`` anywhere reachable from ``rosbagger_core`` /
    ``bagq`` would break the invariant the phase is built to protect (16-RESEARCH
    Pitfall 4). PySide6's binding runtime is ``shiboken6`` (verified after first
    install), so both names are in the blocklist; ``PySide6`` alone already catches
    a leak.

    Mechanism (mirrors the ROS guards above): a FRESH interpreter with
    ``env={"PYTHONPATH": ""}`` — the empty PYTHONPATH neutralizes this dev host's
    ROS-on-PYTHONPATH leak, and the editable workspace members still resolve via
    their site-packages ``.pth`` — so this asserts the import GRAPH is Qt-free.
    """
    code = (
        "import sys; import rosbagger_core; import bagq; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'PySide6', 'shiboken6'}]; "
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
    assert leaked == [], f"offline import pulled in Qt: {leaked}"


def test_import_desktop_cli_does_not_pull_pyside6_or_ros():
    """`import rosbagger_desktop.cli` stays Qt-free AND ROS-free (QApplication is inside main()).

    The desktop cli is an argparse front door (16-01): ``QApplication`` and
    ``MainWindow`` are imported INSIDE :func:`rosbagger_desktop.cli.main` (so
    ``--help`` exits 0 building no Qt, Pitfall 6), the capability probe imports
    ``rclpy`` inside its body (D-09), and the panels lazy-import the core/ROS APIs
    inside method bodies (D-08). So the bare ``import rosbagger_desktop.cli`` binds
    NEITHER the Qt stack (``PySide6`` / ``shiboken6``) NOR the ROS runtime
    (``rclpy`` / ``rosbag2_py``) — regression-locking the help-clean discipline and
    the offline invariant for the new package.

    Mechanism: a FRESH interpreter with ``env={"PYTHONPATH": ""}`` (same technique
    as the ROS / Qt-free guards above).
    """
    code = (
        "import sys; import rosbagger_desktop.cli; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in "
        "{'PySide6', 'shiboken6', 'rclpy', 'rosbag2_py'}]; "
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
    assert leaked == [], f"import rosbagger_desktop.cli pulled Qt/ROS: {leaked}"


def test_import_rerun_bridge_does_not_pull_ros_or_rerun():
    """`import rosbagger_rerun` pulls NO rclpy/rosbag2_py/rerun (Phase 22 offline invariant).

    The Phase 22 bag→Rerun bridge isolates EVERY ``rerun`` / ``rclpy`` /
    ``rosidl_runtime_py`` import inside function bodies (``session`` / ``converters`` /
    ``sink``), so the bare top-level ``import rosbagger_rerun`` binds neither the ROS
    RUNTIME stack NOR the (large) ``rerun`` SDK — the offline import graph stays ROS-free
    AND Rerun-free even though the package REQUIRES both at run time. This is the load-bearing
    isolation guarantee for the new package (mirrors ``test_import_replay_does_not_pull_ros``,
    extended to also block ``rerun``).

    Mechanism: a FRESH interpreter with ``env={"PYTHONPATH": ""}`` (the empty PYTHONPATH
    neutralizes this dev host's ROS-on-PYTHONPATH leak; the editable workspace member still
    resolves via its site-packages ``.pth``), so this asserts the import GRAPH is clean, not
    merely that ROS/rerun are off the path.
    """
    code = (
        "import sys; import rosbagger_rerun; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'rclpy', 'rosbag2_py', 'rerun'}]; "
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
    assert leaked == [], f"import rosbagger_rerun pulled in ROS/rerun modules: {leaked}"
