"""Fixture-backed tests for ``collect_table_schemas`` (the ``bagq tables`` API, INSP-03).

These prove the inspect API resolves each topic to its sanitized table name and
column schema via the Phase 3 schema layer, over all three fixture formats, using
ONLY O(1) metadata + the typestore — never iterating message bodies (threat
T-04-05). They also pin the two render-relevant facts the CLI depends on:

* the four standard columns (``t``/``t_ns``/``stamp``/``topic``) lead every table,
* ``/image``'s ``data`` column is a heavy blob with arrow type ``list<item: uint8>``,

and the multi-msgtype guard (threat T-04-08 / Pitfall 4): a topic whose
``TopicInfo.msgtype is None`` is SKIPPED, never passed to ``build_table_schema``
(which would raise ``KeyError: None``).

LOCAL-RUN REQUIREMENT (04-RESEARCH.md): this dev host sources ROS 2 Humble onto
``PYTHONPATH``; run locally with the leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_inspect_tables.py -q

CI is ROS-free and needs no prefix; this file bakes in NO ``PYTHONPATH`` override.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# `tools` is a dev-only repo-root package (not an installed distribution); put the
# repo root on sys.path here, scoped to this file (mirrors tests/test_reader.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    write_ros1_bag,
    write_ros2_mcap_bag,
    write_ros2_sqlite_bag,
)

from rosbagger_core.inspect import collect_table_schemas  # noqa: E402  (3rd-party)
from rosbagger_core.reader import RosbagsReader  # noqa: E402  (3rd-party)

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")

# Verified fixture facts (04-RESEARCH.md): each bag carries /cmd_vel (Twist),
# /imu (Imu), /image (Image). Table names sanitize to cmd_vel / imu / image.
EXPECTED_TABLE_NAMES = {"cmd_vel", "imu", "image"}
EXPECTED_MSGTYPE_BY_TABLE = {
    "cmd_vel": "geometry_msgs/msg/Twist",
    "imu": "sensor_msgs/msg/Imu",
    "image": "sensor_msgs/msg/Image",
}


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir.

    Each format written into its OWN subdir (the ROS 2 writers reuse a fixed dir
    name, so a shared parent would collide — see 02-03's decision log).
    """
    root = tmp_path_factory.mktemp("inspect_tables")
    return {
        "ros1": write_ros1_bag(root / "ros1"),
        "ros2_sqlite": write_ros2_sqlite_bag(root / "ros2_sqlite"),
        "ros2_mcap": write_ros2_mcap_bag(root / "ros2_mcap"),
    }


@pytest.mark.parametrize("fmt", FORMATS)
def test_collect_table_schemas_returns_one_per_topic(
    fmt: str, fixture_bags: dict[str, Path]
) -> None:
    """Three TableSchema, one per topic, with sanitized names + matching topic/msgtype."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        schemas = collect_table_schemas(reader)

    assert len(schemas) == 3
    by_name = {s.table_name: s for s in schemas}
    assert set(by_name) == EXPECTED_TABLE_NAMES
    for name, schema in by_name.items():
        assert schema.topic == f"/{name}"
        assert schema.msgtype == EXPECTED_MSGTYPE_BY_TABLE[name]


@pytest.mark.parametrize("fmt", FORMATS)
def test_collect_table_schemas_sorted_by_topic(fmt: str, fixture_bags: dict[str, Path]) -> None:
    """The list is ordered by topic name (sorted(reader.topics))."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        schemas = collect_table_schemas(reader)
    topics = [s.topic for s in schemas]
    assert topics == sorted(topics)
    assert topics == ["/cmd_vel", "/image", "/imu"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_image_schema_has_standard_columns_then_heavy_blob_data(
    fmt: str, fixture_bags: dict[str, Path]
) -> None:
    """``/image`` leads with t/t_ns/stamp/topic and carries a heavy-blob ``data`` column."""
    with RosbagsReader(fixture_bags[fmt]) as reader:
        schemas = collect_table_schemas(reader)
    image = next(s for s in schemas if s.table_name == "image")

    names = [c.name for c in image.columns]
    assert names[:4] == ["t", "t_ns", "stamp", "topic"]

    data = next(c for c in image.columns if c.name == "data")
    assert data.is_heavy_blob is True
    assert str(data.arrow_type) == "list<item: uint8>"


def test_multi_msgtype_topic_is_skipped_not_crashing(fixture_bags: dict[str, Path]) -> None:
    """A topic with ``msgtype is None`` is omitted; build_table_schema(None,...) is never called.

    Uses a lightweight stub exposing ``.typestore`` (the REAL fixture typestore so
    the surviving topic builds a genuine schema) and a ``.topics`` dict with one
    None-msgtype entry beside a normal one. Asserts the None topic is absent and
    NO exception (would be ``KeyError: None``) is raised — threat T-04-08.
    """
    from dataclasses import dataclass

    @dataclass
    class _TopicInfo:
        msgtype: str | None
        msgcount: int

    class _StubReader:
        """Minimal duck-typed reader: only ``.typestore`` + ``.topics`` are read."""

        def __init__(self, typestore) -> None:
            self.typestore = typestore
            self.topics = {
                "/image": _TopicInfo(msgtype="sensor_msgs/msg/Image", msgcount=3),
                "/mixed": _TopicInfo(msgtype=None, msgcount=5),  # heterogeneous topic
            }

        def read(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("collect_table_schemas must not iterate messages")

    with RosbagsReader(fixture_bags["ros1"]) as real_reader:
        typestore = real_reader.typestore
        schemas = collect_table_schemas(_StubReader(typestore))

    table_names = {s.table_name for s in schemas}
    assert table_names == {"image"}  # /mixed (None msgtype) skipped, no crash


def test_collect_table_schemas_does_not_read_messages(fixture_bags: dict[str, Path]) -> None:
    """The API reads metadata only — monkeypatching reader.read to raise proves it (T-04-05)."""
    with RosbagsReader(fixture_bags["ros1"]) as reader:

        def _boom(*args, **kwargs):  # pragma: no cover - executed only if violated
            raise AssertionError("collect_table_schemas must not call reader.read()")

        reader.read = _boom  # type: ignore[method-assign]
        schemas = collect_table_schemas(reader)

    assert len(schemas) == 3  # built purely from metadata + typestore


def test_collect_table_schemas_resolves_table_name_collisions(
    fixture_bags: dict[str, Path],
) -> None:
    """Two topics sanitizing to one base name get DISTINCT table names (CR-01 / T-03-01/02).

    ``/a/b`` and ``/a.b`` both sanitize to ``a_b``; ``collect_table_schemas`` must
    feed them through a SHARED ``TableNameResolver`` so the second is de-duplicated
    to ``a_b_2`` rather than silently aliasing onto the first's ``a_b``. Mirrors the
    multi-msgtype stub style above: a lightweight reader exposing the REAL fixture
    typestore (so both topics build genuine schemas) and a ``.topics`` dict whose
    two distinct topics carry a known single msgtype (``geometry_msgs/msg/Twist``).
    """
    from dataclasses import dataclass

    @dataclass
    class _TopicInfo:
        msgtype: str | None
        msgcount: int

    class _StubReader:
        """Minimal duck-typed reader: only ``.typestore`` + ``.topics`` are read."""

        def __init__(self, typestore) -> None:
            self.typestore = typestore
            # Two DISTINCT topics that both sanitize to the base name "a_b".
            self.topics = {
                "/a/b": _TopicInfo(msgtype="geometry_msgs/msg/Twist", msgcount=3),
                "/a.b": _TopicInfo(msgtype="geometry_msgs/msg/Twist", msgcount=3),
            }

        def read(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("collect_table_schemas must not iterate messages")

    with RosbagsReader(fixture_bags["ros1"]) as real_reader:
        typestore = real_reader.typestore
        schemas = collect_table_schemas(_StubReader(typestore))

    table_names = [s.table_name for s in schemas]
    # No two schemas share a table name (the data-integrity guarantee).
    assert len(table_names) == len(set(table_names)), table_names
    # Deterministic collision resolution in sorted topic order: "/a.b" sorts
    # before "/a/b" (ASCII '.' < '/'), so it claims the base name "a_b" first.
    assert set(table_names) == {"a_b", "a_b_2"}
    by_topic = {s.topic: s.table_name for s in schemas}
    assert by_topic == {"/a.b": "a_b", "/a/b": "a_b_2"}
