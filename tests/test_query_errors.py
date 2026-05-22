"""Fixture-backed tests for the query()-boundary teaching error (CLI-03).

Proves that an unknown COLUMN surfaces as a typed ``UnknownColumnError`` carrying the
referenced table's columns — NOT a raw ``duckdb.BinderException`` — while a valid query
is unaffected (the try/except adds no regression) and the backend still closes on the
error path. Detection is by exception TYPE (``duckdb.BinderException``); the message is
parsed only to recover the column NAME (07-RESEARCH §2).

LOCAL-RUN REQUIREMENT (07-RESEARCH.md): this dev host sources ROS 2 onto ``PYTHONPATH``;
run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_query_errors.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only repo-root package (not an installed dist); put the repo root
# on sys.path here, scoped to this file (mirrors tests/test_reader.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import write_ros1_bag  # noqa: E402  (after sys.path setup)

from rosbagger_core.backend.query import query  # noqa: E402  (3rd-party)
from rosbagger_core.errors import UnknownColumnError  # noqa: E402
from rosbagger_core.reader import RosbagsReader  # noqa: E402


@pytest.fixture(scope="session")
def ros1_bag(tmp_path_factory) -> Path:
    """A single ROS 1 fixture bag (cmd_vel/imu/image) for the column-error tests."""
    return write_ros1_bag(tmp_path_factory.mktemp("query_errors_bag"))


def test_unknown_column_raises_typed_error_listing_columns(ros1_bag: Path) -> None:
    """A bad column raises ``UnknownColumnError`` (not raw BinderException) + lists columns."""
    with (
        RosbagsReader(ros1_bag) as reader,
        pytest.raises(UnknownColumnError) as excinfo,
    ):
        query("SELECT nonexistent_col FROM cmd_vel", reader)
    err = excinfo.value
    assert "nonexistent_col" in str(err)  # the offending column name was recovered
    assert "Columns in cmd_vel:" in str(err)  # that table's columns are listed
    assert "cmd_vel" in err.columns_by_table  # data-carrying


def test_valid_query_still_returns_rows(ros1_bag: Path) -> None:
    """A valid query still returns its 3 rows — the BinderException catch adds no regression."""
    with RosbagsReader(ros1_bag) as reader:
        result = query("SELECT t_ns, topic FROM cmd_vel", reader)
    assert result.num_rows == 3


def test_unknown_column_error_is_value_error(ros1_bag: Path) -> None:
    """Back-compat: the typed column error is still a ``ValueError`` (caught by old handlers)."""
    with (
        RosbagsReader(ros1_bag) as reader,
        pytest.raises(ValueError),  # noqa: PT011  (UnknownColumnError is the ValueError)
    ):
        query("SELECT bogus FROM cmd_vel", reader)
