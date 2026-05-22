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
