"""Unit + fixture tests for the SQL resolver and connection-filtered read (05-02 Task 1).

Two cooperating pieces of the query orchestrator are proven here:

* ``backend/resolve.py`` — ``sqlglot``-based SQL inspection:
  ``referenced_tables`` (CTE-subtracted base names; QURY-05 table resolution),
  ``referenced_columns`` (the heavy-blob ``include`` driver; QURY-07 seam),
  ``has_star`` (``SELECT *`` ⇒ "include blobs"; 05-RESEARCH Pitfall 3).
* ``reader/rosbags_reader.py`` — ``read(topics={...})`` is a CONNECTION-LEVEL
  filter: only the named topics are deserialized, the others are never decoded.
  This is the success-criterion-#2 proof (QURY-05) — verified by monkeypatching
  ``deserialize`` to record every msgtype it is asked to decode and asserting the
  unreferenced topics never appear (filter-after-read would; 05-RESEARCH Pitfall 2).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized::

    PYTHONPATH="" uv run pytest tests/test_backend_resolve.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only package at the repo root (NOT an installed distribution),
# so it is not on sys.path under pytest's default import mode. Put the repo root
# on sys.path here — scoped to this test file (mirrors tests/test_reader.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import make_all_fixtures  # noqa: E402  (after sys.path setup)

from rosbagger_core.backend.resolve import (  # noqa: E402  (3rd-party stack)
    has_star,
    parse,
    referenced_columns,
    referenced_tables,
)
from rosbagger_core.reader import RosbagsReader  # noqa: E402

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")
EXPECTED_TOPICS = {"/cmd_vel", "/imu", "/image"}


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("resolve_bags")
    return make_all_fixtures(dest)


# ---------------------------------------------------------------------------
# referenced_tables — base names, alias→base, CTE subtraction, JOIN
# ---------------------------------------------------------------------------


def test_referenced_tables_simple_select() -> None:
    """A bare ``FROM cmd_vel`` resolves to exactly that base table name."""
    assert referenced_tables("SELECT * FROM cmd_vel") == {"cmd_vel"}


def test_referenced_tables_alias_resolves_to_base() -> None:
    """An alias (``FROM imu AS a``) resolves to the BASE name ``imu``, not ``a``."""
    assert referenced_tables("SELECT a.x FROM imu AS a") == {"imu"}


def test_referenced_tables_subtracts_cte_alias() -> None:
    """A CTE alias is NOT a topic table — it is subtracted (05-RESEARCH Pattern 2).

    Without subtraction this would wrongly be ``{"fast", "cmd_vel"}``; the CTE
    name ``fast`` maps to no topic and would raise spuriously in the orchestrator.
    """
    sql = "WITH fast AS (SELECT * FROM cmd_vel) SELECT * FROM fast"
    assert referenced_tables(sql) == {"cmd_vel"}


def test_referenced_tables_join_returns_both_base_names() -> None:
    """A JOIN across two tables returns BOTH base table names."""
    sql = "SELECT c.t_ns, i.t_ns FROM cmd_vel AS c JOIN imu AS i ON c.t_ns = i.t_ns"
    assert referenced_tables(sql) == {"cmd_vel", "imu"}


# ---------------------------------------------------------------------------
# referenced_columns + has_star — the heavy-blob include driver
# ---------------------------------------------------------------------------


def test_referenced_columns_includes_quoted_dotted_name() -> None:
    """A quoted dotted column ``"linear.x"`` parses to that exact column name."""
    cols = referenced_columns(parse('SELECT t_ns, "linear.x" FROM cmd_vel'))
    assert "t_ns" in cols
    assert "linear.x" in cols


def test_has_star_true_for_select_star() -> None:
    """``SELECT *`` is detected as a star (it emits NO exp.Column, only exp.Star)."""
    assert has_star(parse("SELECT * FROM image")) is True


def test_has_star_false_for_explicit_columns() -> None:
    """An explicit column list is NOT a star, so blobs are not auto-included."""
    assert has_star(parse("SELECT data FROM image")) is False


def test_select_star_has_no_referenced_columns() -> None:
    """``SELECT *`` produces an empty referenced-columns set (only has_star fires)."""
    tree = parse("SELECT * FROM image")
    assert referenced_columns(tree) == set()
    assert has_star(tree) is True


def test_parse_is_reused_for_columns_and_star() -> None:
    """``parse`` returns a tree that feeds BOTH column + star helpers (parse once)."""
    tree = parse('SELECT t_ns, "linear.x" FROM cmd_vel WHERE "linear.x" > 0.5')
    assert "linear.x" in referenced_columns(tree)
    assert has_star(tree) is False


# ---------------------------------------------------------------------------
# read(topics=) — connection-level filter (success criterion #2 / QURY-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_read_topics_filter_yields_only_requested_topic(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """``read(topics={"/cmd_vel"})`` yields ONLY the 3 /cmd_vel messages."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        msgs = list(reader.read(topics={"/cmd_vel"}))
    assert len(msgs) == 3
    assert {m.topic for m in msgs} == {"/cmd_vel"}


@pytest.mark.parametrize("fmt", FORMATS)
def test_read_topics_filter_never_deserializes_other_topics(
    fixture_bags: dict[str, Path], fmt: str
) -> None:
    """Unreferenced topics are NEVER deserialized (the QURY-05 proof; Pitfall 2).

    Monkeypatch the underlying ``deserialize`` to record every msgtype it is
    asked to decode. After a ``/cmd_vel``-only read, the recorded msgtypes must be
    exactly three ``geometry_msgs/msg/Twist`` and contain NO Imu or Image — proving
    the filter happens at the connection layer, before deserialization, not after.
    """
    with RosbagsReader(fixture_bags[fmt]) as reader:
        decoded: list[str] = []
        real_deserialize = reader._reader.deserialize

        def recording_deserialize(rawdata, msgtype):
            decoded.append(msgtype)
            return real_deserialize(rawdata, msgtype)

        reader._reader.deserialize = recording_deserialize
        msgs = list(reader.read(topics={"/cmd_vel"}))

    assert len(msgs) == 3
    assert decoded == ["geometry_msgs/msg/Twist"] * 3
    assert "sensor_msgs/msg/Imu" not in decoded
    assert "sensor_msgs/msg/Image" not in decoded


@pytest.mark.parametrize("fmt", FORMATS)
def test_read_without_topics_is_unchanged(fixture_bags: dict[str, Path], fmt: str) -> None:
    """``read()`` with no topics still yields ALL topics, time-ordered (no regression)."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        msgs = list(reader.read())
    assert len(msgs) == 9
    assert {m.topic for m in msgs} == EXPECTED_TOPICS
    t_ns_seq = [m.t_ns for m in msgs]
    assert t_ns_seq == sorted(t_ns_seq)


def test_read_topics_empty_set_yields_nothing(fixture_bags: dict[str, Path]) -> None:
    """An empty/unknown topic filter matches no connection → empty stream (not an error)."""
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        assert list(reader.read(topics=set())) == []
        assert list(reader.read(topics={"/does_not_exist"})) == []
