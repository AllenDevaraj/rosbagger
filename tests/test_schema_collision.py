"""WR-01 regression: reserved-name column collisions in ``build_table_schema``.

A message BODY field literally named ``t``/``t_ns``/``stamp``/``topic`` collides
with the four always-present standard columns ``build_table_schema`` prepends
(QURY-04). Before the fix the resulting :class:`TableSchema` carried duplicate
column ``name``s, and ``build_arrow_table``'s name-keyed ``values`` dict then
collapsed those columns and raised ``pyarrow.lib.ArrowTypeError`` when it fed a
body ``uint8`` value into the standard string ``topic`` column (05-RESEARCH
Pitfall 1, VERIFIED reproducible).

The fix renames the colliding **body** column (suffix ``_`` until unique) while
preserving its ``ros_path`` so the value still extracts; the four standard
columns are NEVER renamed (they are the documented QURY-04 contract).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized (with coverage, per the project gate)::

    PYTHONPATH="" uv run pytest tests/test_schema_collision.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from rosbags.typesys import Stores, get_typestore
from rosbags.typesys.store import Typestore

# `tools` is a dev-only package at the repo root (NOT an installed distribution),
# so it is not on sys.path under pytest's default import mode. Put the repo root
# on sys.path here — scoped to this test file (mirrors tests/test_schema_arrow.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rosbagger_core.schema.flatten import (  # noqa: E402  (3rd-party stack)
    build_arrow_table,
    build_table_schema,
)

# A custom message whose BODY fields collide with the standard columns:
# `topic`, `stamp`, `t` are all reserved standard-column names, plus a normal
# `value` float64 that must survive untouched. (`t_ns` is exercised via the
# parametrized single-collision test below.)
_COLLIDE_MSGDEF = """
string topic
float64 stamp
int32 t
float64 value
"""

_COLLIDE_TYPE = "evil_msgs/msg/Collide"


def _register_collision_type(typestore: Typestore, msgdef: str, typename: str) -> None:
    """Register a custom collision type into ``typestore`` (idempotent per name)."""
    from rosbags.typesys import get_types_from_msg

    types = get_types_from_msg(msgdef, typename)
    typestore.register(types)


@pytest.fixture
def typestore() -> Typestore:
    """A fresh ROS 2 Humble typestore with the ``evil_msgs/msg/Collide`` type.

    Function-scoped (not session): each test gets a clean typestore so registering
    extra single-field collision types in one test cannot bleed into another.
    """
    ts = get_typestore(Stores.ROS2_HUMBLE)
    _register_collision_type(ts, _COLLIDE_MSGDEF, _COLLIDE_TYPE)
    return ts


@dataclass
class _FakeMessage:
    """Minimal stand-in for a Phase 2 ``Message`` record for build_arrow_table.

    ``build_arrow_table`` reads the four standard columns off the record by name
    (``t``/``t_ns``/``stamp``/``topic``) and the body columns off ``.msg`` via
    each ColumnDef's ``ros_path``. We do NOT need a real deserialized rosbags
    message — only an object exposing the body fields by attribute.
    """

    topic: str
    t: int
    t_ns: int
    stamp: int | None
    msgtype: str
    msg: object


@dataclass
class _CollideBody:
    """The deserialized-body stand-in: exposes the colliding body field names."""

    topic: str
    stamp: float
    t: int
    value: float


# ---------------------------------------------------------------------------
# Behavior 1 — a body field named `topic` is renamed; standard `topic` survives.
# ---------------------------------------------------------------------------


def test_collision_schema_has_no_duplicate_column_names(typestore) -> None:
    """The crafted collision schema's arrow_schema().names has NO duplicates.

    The standard ``topic``/``stamp``/``t`` are preserved AND the colliding body
    fields appear under suffixed names.
    """
    schema = build_table_schema(_COLLIDE_TYPE, typestore, topic="/evil")
    names = schema.arrow_schema().names
    # No duplicates — this is the WR-01 invariant.
    assert len(names) == len(set(names)), f"duplicate column names: {names}"
    # The four standard columns are preserved unrenamed (QURY-04 contract).
    assert names[:4] == ["t", "t_ns", "stamp", "topic"]
    # The colliding body fields are present under suffixed names.
    assert "topic_" in names
    assert "stamp_" in names
    assert "t_" in names
    # The non-colliding body field is untouched.
    assert "value" in names


def test_renamed_body_column_preserves_ros_path(typestore) -> None:
    """The renamed body columns keep the ros_path to their ORIGINAL field name.

    Renaming touches only ``ColumnDef.name`` — ``ros_path``/``arrow_type``/
    ``is_heavy_blob`` are exactly what ``_walk_fields`` produced, so value
    extraction still follows the real attribute (e.g. ``msg.topic``).
    """
    schema = build_table_schema(_COLLIDE_TYPE, typestore, topic="/evil")
    by_name = {c.name: c for c in schema.columns}
    # The renamed body `topic_` still extracts from the message attribute `topic`.
    assert by_name["topic_"].ros_path == ("topic",)
    assert by_name["stamp_"].ros_path == ("stamp",)
    assert by_name["t_"].ros_path == ("t",)
    # The standard `topic` column is sourced off the Message record (empty path).
    assert by_name["topic"].ros_path == ()


# ---------------------------------------------------------------------------
# Behavior 2 — build_arrow_table over the collision type does NOT crash; the
#              standard columns hold the record values, the body columns the body.
# ---------------------------------------------------------------------------


def test_build_arrow_table_over_collision_type_does_not_crash(typestore) -> None:
    """build_arrow_table no longer raises ArrowTypeError on a colliding body.

    The standard ``topic`` column holds the topic string while the renamed body
    column ``topic_`` holds the body's value — they no longer collapse.
    """
    schema = build_table_schema(_COLLIDE_TYPE, typestore, topic="/evil")
    messages = [
        _FakeMessage(
            topic="/evil",
            t=1_000_000_000,
            t_ns=1_000_000_000,
            stamp=None,
            msgtype=_COLLIDE_TYPE,
            msg=_CollideBody(topic="body_topic_0", stamp=1.5, t=7, value=0.5),
        ),
        _FakeMessage(
            topic="/evil",
            t=2_000_000_000,
            t_ns=2_000_000_000,
            stamp=None,
            msgtype=_COLLIDE_TYPE,
            msg=_CollideBody(topic="body_topic_1", stamp=2.5, t=8, value=1.5),
        ),
    ]
    # The pre-fix defect raised pyarrow.lib.ArrowTypeError here.
    table = build_arrow_table(messages, schema)
    assert table.num_rows == 2
    # Standard `topic` column = the topic string off the Message record.
    assert table.column("topic").to_pylist() == ["/evil", "/evil"]
    # Renamed body `topic_` column = the body's string field.
    assert table.column("topic_").to_pylist() == ["body_topic_0", "body_topic_1"]
    # Renamed body `stamp_`/`t_` carry the body values (not the standard ones).
    assert table.column("stamp_").to_pylist() == [1.5, 2.5]
    assert table.column("t_").to_pylist() == [7, 8]
    # The standard `t_ns` BIGINT holds the record log time.
    assert table.column("t_ns").to_pylist() == [1_000_000_000, 2_000_000_000]
    # The non-colliding `value` body column is intact.
    assert table.column("value").to_pylist() == [0.5, 1.5]


# ---------------------------------------------------------------------------
# Behavior 3 — TWO body fields colliding to the same name each get a further
#              suffix (uniqueness is enforced against prior body names too).
# ---------------------------------------------------------------------------


def test_repeated_body_collision_gets_further_suffix(typestore) -> None:
    """Two body fields both named `topic` (one direct, one via a suffix clash).

    A body field literally named ``topic_`` alongside the standard ``topic`` AND
    a body ``topic`` forces a chain: body ``topic`` -> ``topic_`` (clashes std),
    then body ``topic_`` -> ``topic__``. All names stay unique.
    """
    typename = "evil_msgs/msg/DoubleCollide"
    msgdef = "string topic\nstring topic_\n"
    _register_collision_type(typestore, msgdef, typename)
    schema = build_table_schema(typename, typestore, topic="/evil2")
    names = schema.arrow_schema().names
    assert len(names) == len(set(names)), f"duplicate column names: {names}"
    # Standard topic preserved; the two body fields get distinct suffixed names.
    assert names[:4] == ["t", "t_ns", "stamp", "topic"]
    assert "topic_" in names  # body `topic` renamed (clashes the standard topic)
    assert "topic__" in names  # body `topic_` renamed (clashes the renamed body)


@pytest.mark.parametrize("reserved", ["t", "t_ns", "stamp", "topic"])
def test_each_reserved_name_collision_is_renamed(typestore, reserved) -> None:
    """A single body field named after ANY of the four standard columns is renamed."""
    typename = f"evil_msgs/msg/Single_{reserved}"
    msgdef = f"float64 {reserved}\n"
    _register_collision_type(typestore, msgdef, typename)
    schema = build_table_schema(typename, typestore, topic="/single")
    names = schema.arrow_schema().names
    assert len(names) == len(set(names)), f"duplicate column names: {names}"
    # The standard column with this name is still present and unrenamed.
    assert reserved in names
    # The body field is renamed to <reserved>_, preserving its ros_path.
    by_name = {c.name: c for c in schema.columns}
    assert f"{reserved}_" in by_name
    assert by_name[f"{reserved}_"].ros_path == (reserved,)


# ---------------------------------------------------------------------------
# Behavior 4 — a NORMAL msgtype with no collisions is UNCHANGED (no regression).
# ---------------------------------------------------------------------------


def test_normal_twist_schema_is_unchanged_by_the_fix() -> None:
    """geometry_msgs/msg/Twist is a no-op for the fix (no behavior regression).

    arrow_schema().names still begins exactly ["t","t_ns","stamp","topic",...]
    with the dotted body columns in declared order — QURY-01/02/03/04 unaffected.
    """
    ts = get_typestore(Stores.ROS2_HUMBLE)
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    names = schema.arrow_schema().names
    assert names[:5] == ["t", "t_ns", "stamp", "topic", "linear.x"]
    # No spurious suffixing on a collision-free type.
    assert not any(n.endswith("_") for n in names if n not in {"t_ns"})
    assert len(names) == len(set(names))
