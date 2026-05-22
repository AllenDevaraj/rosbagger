"""Unit tests for the Phase 3 backend-neutral schema contract (plan 03-01).

Covers the two interface-defining modules this wave ships:

* ``rosbagger_core.schema.names`` — ``sanitize_table_name`` (the QURY-01 topic ->
  table-name rule: drop one leading ``/``, remaining ``/`` -> ``_``, odd chars ->
  ``_``, empty -> ``"topic"``, leading-digit -> ``t_`` prefix) plus a stateful,
  collision-resolving ``TableNameResolver`` (case-insensitive, deterministic,
  idempotent, and records the topic -> table-name mapping for Phase 4's
  ``bagq tables``).
* ``rosbagger_core.schema.model`` — the backend-neutral ``ColumnDef`` /
  ``TableSchema`` dataclasses (the public model Phase 4 renders and Phase 5
  ingests). ``TableSchema.column_names(include=...)`` filters heavy-blob columns.

These are pure-Python units: NO fixture bags, NO pyarrow, NO duckdb, NO rosbags.
They are what keeps the project coverage gate (``--cov-fail-under=80``) satisfied
for the new ``names.py`` / ``model.py`` lines within this plan.

LOCAL-RUN REQUIREMENT (02/03-RESEARCH.md): this dev host sources ROS 2 Humble
onto ``PYTHONPATH``. Run locally with the host leak neutralized::

    PYTHONPATH="" uv run pytest tests/test_schema_names.py -q

CI is ROS-free, so it needs no prefix; this file bakes in no ``PYTHONPATH``
override (it is a run-time prefix only, never committed code). Unlike
``tests/test_reader.py`` this file imports only the installed ``rosbagger_core``
distribution, so it needs no repo-root ``sys.path`` insert.
"""

from __future__ import annotations

from rosbagger_core.schema.model import ColumnDef, TableSchema
from rosbagger_core.schema.names import TableNameResolver, sanitize_table_name

# ----------------------------------------------------------------------------
# sanitize_table_name (QURY-01)
# ----------------------------------------------------------------------------


def test_sanitize_canonical_example() -> None:
    """The spec's canonical example: /camera/image_raw -> camera_image_raw."""
    assert sanitize_table_name("/camera/image_raw") == "camera_image_raw"


def test_sanitize_fixture_topics() -> None:
    """The three real fixture topics each drop their single leading slash."""
    assert sanitize_table_name("/cmd_vel") == "cmd_vel"
    assert sanitize_table_name("/imu") == "imu"
    assert sanitize_table_name("/image") == "image"


def test_sanitize_nested_topic() -> None:
    """A nested topic: one leading slash dropped, remaining slash -> underscore."""
    assert sanitize_table_name("/a/b") == "a_b"
    assert sanitize_table_name("/tf") == "tf"


def test_sanitize_odd_char_becomes_underscore() -> None:
    """Any character outside [0-9A-Za-z_] (e.g. a dot) becomes an underscore."""
    assert sanitize_table_name("/a.b") == "a_b"


def test_sanitize_empty_result_becomes_topic() -> None:
    """A topic that sanitizes to the empty string (e.g. "/") becomes "topic"."""
    assert sanitize_table_name("/") == "topic"


def test_sanitize_leading_digit_gets_prefix() -> None:
    """A result that would start with a digit gets a ``t_`` prefix (valid SQL ident)."""
    assert sanitize_table_name("/2d_scan") == "t_2d_scan"


def test_sanitize_is_idempotent() -> None:
    """Sanitizing an already-sanitized name is a no-op (stable under re-application)."""
    once = sanitize_table_name("/camera/image_raw")
    assert sanitize_table_name(once) == once
    assert sanitize_table_name("camera_image_raw") == "camera_image_raw"


# ----------------------------------------------------------------------------
# TableNameResolver (QURY-01 collision resolution)
# ----------------------------------------------------------------------------


def test_resolver_resolves_collision_deterministically() -> None:
    """Two topics that sanitize to the same name get distinct, deterministic names."""
    resolver = TableNameResolver()
    assert resolver.resolve("/a/b") == "a_b"
    # "/a.b" also sanitizes to "a_b" -> deterministic numeric suffix.
    assert resolver.resolve("/a.b") == "a_b_2"


def test_resolver_collision_is_case_insensitive() -> None:
    """SQL folds case, so /Foo and /foo collide and get distinct names."""
    resolver = TableNameResolver()
    assert resolver.resolve("/Foo") == "Foo"
    assert resolver.resolve("/foo") == "foo_2"


def test_resolver_is_idempotent() -> None:
    """Resolving the SAME topic twice returns the SAME name (no double-suffix)."""
    resolver = TableNameResolver()
    assert resolver.resolve("/imu") == "imu"
    assert resolver.resolve("/imu") == "imu"


def test_resolver_idempotent_does_not_consume_a_suffix() -> None:
    """Re-resolving a topic must not advance the collision counter for that name."""
    resolver = TableNameResolver()
    assert resolver.resolve("/a/b") == "a_b"
    assert resolver.resolve("/a/b") == "a_b"  # idempotent, no suffix burned
    assert resolver.resolve("/a.b") == "a_b_2"  # the FIRST genuine collision is _2


def test_resolver_records_mapping() -> None:
    """The resolver records every resolved topic -> name (for Phase 4's bagq tables)."""
    resolver = TableNameResolver()
    resolver.resolve("/a/b")
    resolver.resolve("/a.b")
    resolver.resolve("/imu")
    mapping = resolver.mapping
    assert mapping == {"/a/b": "a_b", "/a.b": "a_b_2", "/imu": "imu"}


def test_resolver_mapping_is_a_copy() -> None:
    """The exposed mapping is a copy — mutating it must not corrupt resolver state."""
    resolver = TableNameResolver()
    resolver.resolve("/imu")
    snapshot = resolver.mapping
    snapshot["/hacked"] = "evil"
    assert "/hacked" not in resolver.mapping


# ----------------------------------------------------------------------------
# ColumnDef / TableSchema model
# ----------------------------------------------------------------------------


def test_columndef_round_trips_its_four_fields() -> None:
    """A ColumnDef carries name, arrow_type, ros_path, and is_heavy_blob faithfully."""
    col = ColumnDef(
        name="linear.x",
        arrow_type="float64-placeholder",  # arrow_type is typed `object` (no pyarrow here)
        ros_path=("linear", "x"),
        is_heavy_blob=False,
    )
    assert col.name == "linear.x"
    assert col.arrow_type == "float64-placeholder"
    assert col.ros_path == ("linear", "x")
    assert col.is_heavy_blob is False


def _sample_table_schema() -> TableSchema:
    """An /image-like table: standard cols + a flattened scalar + a heavy `data` blob."""
    return TableSchema(
        table_name="image",
        topic="/image",
        msgtype="sensor_msgs/msg/Image",
        columns=[
            ColumnDef("t", "ts", ("t",), False),
            ColumnDef("topic", "str", ("topic",), False),
            ColumnDef("height", "uint32", ("height",), False),
            ColumnDef("data", "list<uint8>", ("data",), True),
        ],
    )


def test_table_schema_round_trips_its_fields() -> None:
    """A TableSchema carries table_name, topic, msgtype, and its ColumnDef list."""
    schema = _sample_table_schema()
    assert schema.table_name == "image"
    assert schema.topic == "/image"
    assert schema.msgtype == "sensor_msgs/msg/Image"
    assert [c.name for c in schema.columns] == ["t", "topic", "height", "data"]


def test_column_names_omits_heavy_blob_by_default() -> None:
    """column_names() with no include omits is_heavy_blob columns (QURY-07 default)."""
    schema = _sample_table_schema()
    assert schema.column_names() == ["t", "topic", "height"]


def test_column_names_includes_blob_when_named() -> None:
    """column_names(include={"data"}) re-includes the heavy blob by its dotted name."""
    schema = _sample_table_schema()
    assert schema.column_names(include={"data"}) == ["t", "topic", "height", "data"]


def test_column_names_preserves_declared_order() -> None:
    """Column names come back in declared order, not sorted."""
    schema = _sample_table_schema()
    assert schema.column_names(include={"data"}) == ["t", "topic", "height", "data"]


def test_arrow_schema_is_deferred_to_03_03() -> None:
    """arrow_schema is the seam Phase 5 drives; 03-01 leaves it a NotImplementedError stub."""
    import pytest

    schema = _sample_table_schema()
    with pytest.raises(NotImplementedError):
        schema.arrow_schema()
