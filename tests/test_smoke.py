"""Smoke tests covering the small real surface that exists in Phase 1.

Phase 1 ships almost no domain code (light ``__init__`` modules + a no-command
typer app), so these tests exercise the genuine surface — package versions and
``bagq --help`` via typer's CliRunner — to meet the >=80% coverage gate honestly
rather than by weakening the threshold (01-PLAN.md / 01-RESEARCH.md coverage note).
"""

from typer.testing import CliRunner

import bagq
import rosbagger_core
from bagq.cli import app

runner = CliRunner()


def test_versions_are_nonempty_strings():
    assert isinstance(rosbagger_core.__version__, str)
    assert rosbagger_core.__version__
    assert isinstance(bagq.__version__, str)
    assert bagq.__version__


def test_bagq_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_bagq_version_exits_zero():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert bagq.__version__ in result.output


def test_all_package_versions_resolve_from_installed_metadata():
    """T4: every package's __version__ derives from its installed dist metadata, not a literal.

    Comparing __version__ to importlib.metadata.version(<dist>) proves the single-source wiring
    resolved — a wrong dist name baked into a package would fall back to the 0.0.0+unknown
    sentinel and fail both asserts. All six packages have ROS-free / Qt-free __init__ modules,
    so importing them here is offline-safe.
    """
    from importlib.metadata import version

    import rosbagger_desktop
    import rosbagger_gui
    import rosbagger_record
    import rosbagger_replay

    resolved = {
        "rosbagger-core": rosbagger_core.__version__,
        "bagq": bagq.__version__,
        "rosbagger-gui": rosbagger_gui.__version__,
        "rosbagger-record": rosbagger_record.__version__,
        "rosbagger-replay": rosbagger_replay.__version__,
        "rosbagger-desktop": rosbagger_desktop.__version__,
    }
    for dist, value in resolved.items():
        assert value != "0.0.0+unknown", f"{dist} fell back to the not-installed sentinel"
        assert value == version(dist), f"{dist}.__version__ did not resolve from its metadata"
