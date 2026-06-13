"""Fixture-backed tests for the query()-boundary teaching error (CLI-03).

Proves that an unknown COLUMN surfaces as a typed ``UnknownColumnError`` carrying the
referenced table's columns — NOT a raw ``duckdb.BinderException`` — while a valid query
is unaffected (the try/except adds no regression) and the backend still closes on the
error path. Detection is by exception TYPE (``duckdb.BinderException``), then NARROWED by
message: only a genuine ``Referenced column "X" not found`` re-maps to
``UnknownColumnError``; every OTHER BinderException (GROUP BY / HAVING / other binder-stage
error) re-raises unchanged so the real error surfaces — NOT a misleading "Unknown column"
(CR-01). The message is parsed only to recover the column NAME (07-RESEARCH §2).

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


def test_group_by_misuse_is_not_relabeled_as_unknown_column(ros1_bag: Path) -> None:
    """CR-01 regression: a VALID-column-but-misgrouped query must NOT be mislabeled.

    ``duckdb.BinderException`` is raised for GROUP BY / HAVING misuse too — NOT only for
    unknown columns. ``linear.x`` is a real cmd_vel column; the actual fault is "must
    appear in the GROUP BY clause". Catching BinderException by type and ALWAYS mapping to
    ``UnknownColumnError`` reported a misleading ``Unknown column '?'`` and hid the real
    error. The fix narrows the re-map to genuine unknown-column messages (the ``_BINDER_COL``
    regex) and re-raises every other BinderException unchanged. Assert this query does NOT
    become an ``UnknownColumnError`` and that the real GROUP BY error survives verbatim.
    """
    with (
        RosbagsReader(ros1_bag) as reader,
        pytest.raises(Exception) as excinfo,  # noqa: PT011  (asserting it is NOT the typed error)
    ):
        query('SELECT "linear.x", COUNT(*) FROM cmd_vel', reader)
    err = excinfo.value
    # The defect: this was relabeled as UnknownColumnError 'Unknown column ?'. It must not be.
    assert not isinstance(err, UnknownColumnError)
    assert "Unknown column" not in str(err)  # NOT the teaching message
    assert "GROUP BY" in str(err)  # the real DuckDB binder error surfaces verbatim


def test_query_mixed_type_topic_raises_truthful_error(tmp_path: Path) -> None:
    """A topic recorded with >1 msgtype across merged bags raises MixedTypeTopicError (newE22).

    rosbags collapses the differing types to msgtype=None, so the orchestrator skips the
    topic — and a query against it previously failed with UnknownTableError listing only
    the OTHER tables, reading as 'the data is missing'. It now raises a truthful
    MixedTypeTopicError naming the topic.
    """
    from tools.make_fixtures import write_mixed_type_topic_bags

    from rosbagger_core.errors import MixedTypeTopicError

    a, b = write_mixed_type_topic_bags(tmp_path)
    with RosbagsReader([a, b]) as reader:
        # Sanity: rosbags reports the merged /status as mixed-type (msgtype None).
        assert reader.topics["/status"].msgtype is None
        with pytest.raises(MixedTypeTopicError) as excinfo:
            query("SELECT * FROM status", reader)
    assert excinfo.value.topic == "/status"
    assert "more than one message type" in str(excinfo.value)


def test_query_mixed_type_error_is_value_error(tmp_path: Path) -> None:
    """MixedTypeTopicError stays a ValueError (so existing handlers keep catching it)."""
    from tools.make_fixtures import write_mixed_type_topic_bags

    a, b = write_mixed_type_topic_bags(tmp_path)
    with RosbagsReader([a, b]) as reader:
        with pytest.raises(ValueError):
            query("SELECT * FROM status", reader)


def test_query_events_multi_bag_raises_not_silently_wrong(tmp_path: Path) -> None:
    """Referencing `events` with >1 bag open raises MultiBagEventsError (newE23).

    The events sidecar is per-bag and loaded for reader.paths[0] only; joining one bag's
    events against the merged multi-bag stream silently dropped the other bags' events.
    The orchestrator now refuses rather than return a quietly-wrong result.
    """
    from rosbagger_core.errors import MultiBagEventsError

    a = write_ros1_bag(tmp_path / "a")
    b = write_ros1_bag(tmp_path / "b")
    with RosbagsReader([a, b]) as reader:
        with pytest.raises(MultiBagEventsError) as excinfo:
            query("SELECT * FROM events", reader)
    assert excinfo.value.n_bags == 2


def test_query_events_single_bag_still_works(tmp_path: Path) -> None:
    """The single-bag events path is unaffected by the multi-bag guard (newE23 regression)."""
    a = write_ros1_bag(tmp_path / "solo")
    with RosbagsReader(a) as reader:
        result = query("SELECT * FROM events", reader)  # empty sidecar -> 0 rows, no error
    assert result.num_rows == 0
