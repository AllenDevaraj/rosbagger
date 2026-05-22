"""Fixture-backed tests for the ROS->Arrow type map + the flattening walk (Phase 3).

These prove plan ``03-02``'s two halves against the REAL ``rosbags`` ROS 2 Humble
typestore (no bag/reader needed — the schema is derived from the *declared*
message type, research Open Question 3):

* ``schema/types.py`` — ``ROS_BASE_TO_ARROW`` + ``arrow_type_of`` (BASE -> scalar,
  NAME -> ``pa.struct``, ARRAY/SEQUENCE -> ``pa.list_``) and the structural
  ``is_heavy_blob`` predicate (QURY-03 type side, QURY-07).
* ``schema/flatten.py`` — ``build_table_schema`` walking ``get_msgdef().fields``
  into dotted scalar columns, prepending the four standard ``t``/``t_ns``/``stamp``/
  ``topic`` columns (QURY-02, QURY-04).

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized (with coverage, per the project gate)::

    PYTHONPATH="" uv run pytest tests/test_schema_flatten.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from rosbags.interfaces import Nodetype
from rosbags.typesys import Stores, get_typestore

from rosbagger_core.schema.flatten import (  # noqa: E402  (3rd-party stack)
    STANDARD_COLUMNS,
    build_table_schema,
)
from rosbagger_core.schema.model import TableSchema  # noqa: E402
from rosbagger_core.schema.types import (  # noqa: E402
    ROS_BASE_TO_ARROW,
    arrow_type_of,
    is_heavy_blob,
)


@pytest.fixture(scope="session")
def typestore():
    """The real ROS 2 Humble typestore.

    Built directly (no bag/reader) because the schema is derived from the
    declared message type, not from any message's values (research Open
    Question 3 / Pitfall 1). Session-scoped: the store is immutable here.
    """
    return get_typestore(Stores.ROS2_HUMBLE)


def _field(typestore, msgtype: str, field_name: str):
    """Pull the raw ``FieldDesc`` for one field of a declared message type."""
    for fname, ftype in typestore.get_msgdef(msgtype).fields:
        if fname == field_name:
            return ftype
    raise AssertionError(f"{msgtype} has no field {field_name!r}")


# ---------------------------------------------------------------------------
# Task 1 — the ROS Basename -> Arrow type map + arrow_type_of + is_heavy_blob
# ---------------------------------------------------------------------------


def test_type_map_base_scalars_have_verified_arrow_types() -> None:
    """ROS_BASE_TO_ARROW covers the verified scalar vocabulary (RESEARCH §3)."""
    assert ROS_BASE_TO_ARROW["float64"] == pa.float64()
    assert ROS_BASE_TO_ARROW["float32"] == pa.float32()
    assert ROS_BASE_TO_ARROW["uint64"] == pa.uint64()  # -> DuckDB UBIGINT, no overflow
    assert ROS_BASE_TO_ARROW["uint32"] == pa.uint32()  # -> DuckDB UINTEGER
    assert ROS_BASE_TO_ARROW["int64"] == pa.int64()
    assert ROS_BASE_TO_ARROW["bool"] == pa.bool_()
    assert ROS_BASE_TO_ARROW["string"] == pa.string()
    # ROS byte/char are single octets -> uint8.
    assert ROS_BASE_TO_ARROW["byte"] == pa.uint8()
    assert ROS_BASE_TO_ARROW["char"] == pa.uint8()
    assert ROS_BASE_TO_ARROW["uint8"] == pa.uint8()


def test_type_map_arrow_type_of_base(typestore) -> None:
    """A BASE FieldDesc resolves to its scalar Arrow type with heavy=False."""
    assert arrow_type_of((Nodetype.BASE, ("float64", 0)), typestore) == (pa.float64(), False)
    assert arrow_type_of((Nodetype.BASE, ("uint64", 0)), typestore) == (pa.uint64(), False)
    assert arrow_type_of((Nodetype.BASE, ("string", 0)), typestore) == (pa.string(), False)


def test_type_map_arrow_type_of_array_is_list_not_heavy(typestore) -> None:
    """A fixed float64[9] array (Imu covariance) -> list<double>, NOT heavy."""
    cov = _field(typestore, "sensor_msgs/msg/Imu", "orientation_covariance")
    arrow_type, heavy = arrow_type_of(cov, typestore)
    assert arrow_type == pa.list_(pa.float64())
    assert heavy is False


def test_type_map_arrow_type_of_sequence_of_uint8_is_heavy_list(typestore) -> None:
    """A variable uint8[] sequence (Image.data) -> list<uint8> flagged heavy."""
    data = _field(typestore, "sensor_msgs/msg/Image", "data")
    arrow_type, heavy = arrow_type_of(data, typestore)
    assert arrow_type == pa.list_(pa.uint8())
    assert heavy is True


def test_type_map_arrow_type_of_name_is_struct_with_short_inner_names(typestore) -> None:
    """A NAME (sub-message) -> pa.struct keeping SHORT inner names (Pitfall 4)."""
    vec3 = (Nodetype.NAME, "geometry_msgs/msg/Vector3")
    arrow_type, heavy = arrow_type_of(vec3, typestore)
    assert arrow_type == pa.struct([("x", pa.float64()), ("y", pa.float64()), ("z", pa.float64())])
    assert heavy is False


def test_heavy_blob_true_for_image_data(typestore) -> None:
    """is_heavy_blob: True for Image.data (SEQUENCE of uint8)."""
    assert is_heavy_blob(_field(typestore, "sensor_msgs/msg/Image", "data")) is True


def test_heavy_blob_false_for_covariance_and_string(typestore) -> None:
    """is_heavy_blob: False for a fixed float64[] array and a scalar string."""
    cov = _field(typestore, "sensor_msgs/msg/Imu", "orientation_covariance")
    assert is_heavy_blob(cov) is False  # ARRAY of float64 is NOT heavy (Pitfall 3)
    string_data = _field(typestore, "std_msgs/msg/String", "data")
    assert is_heavy_blob(string_data) is False  # BASE string is NOT heavy


# ---------------------------------------------------------------------------
# Task 2 — build_table_schema: dotted-name walk + the four standard columns
# ---------------------------------------------------------------------------


def test_build_table_schema_returns_table_schema_with_sanitized_name(typestore) -> None:
    """build_table_schema -> a TableSchema carrying topic, msgtype, sanitized name."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    assert isinstance(schema, TableSchema)
    assert schema.table_name == "cmd_vel"  # sanitize_table_name("/cmd_vel")
    assert schema.topic == "/cmd_vel"
    assert schema.msgtype == "geometry_msgs/msg/Twist"


def test_twist_flattens_to_six_dotted_double_columns(typestore) -> None:
    """Twist -> the six dotted Vector3 columns after the 4 std cols, all float64."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    names = [c.name for c in schema.columns]
    assert names[4:] == [
        "linear.x",
        "linear.y",
        "linear.z",
        "angular.x",
        "angular.y",
        "angular.z",
    ]
    for col in schema.columns[4:]:
        assert col.arrow_type == pa.float64()
        assert col.is_heavy_blob is False
    # ros_path is the attribute chain to pull the value (research Pattern 4).
    by_name = {c.name: c for c in schema.columns}
    assert by_name["linear.x"].ros_path == ("linear", "x")
    assert by_name["angular.z"].ros_path == ("angular", "z")


def test_first_four_columns_are_the_standard_columns(typestore) -> None:
    """Every schema starts with t, t_ns, stamp, topic with the verified types."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    assert [c.name for c in schema.columns][:4] == ["t", "t_ns", "stamp", "topic"]
    std = schema.columns[:4]
    assert std[0].arrow_type == pa.timestamp("ns")  # t        -> TIMESTAMP_NS
    assert std[1].arrow_type == pa.int64()  # t_ns     -> BIGINT
    assert std[2].arrow_type == pa.timestamp("ns")  # stamp    -> TIMESTAMP_NS (nullable)
    assert std[3].arrow_type == pa.string()  # topic    -> VARCHAR
    for col in std:
        assert col.ros_path == ()
        assert col.is_heavy_blob is False


def test_standard_columns_constant_matches_spec() -> None:
    """STANDARD_COLUMNS is the fixed [t, t_ns, stamp, topic] spec (QURY-04)."""
    assert [
        ("t", pa.timestamp("ns")),
        ("t_ns", pa.int64()),
        ("stamp", pa.timestamp("ns")),
        ("topic", pa.string()),
    ] == STANDARD_COLUMNS


def test_imu_has_top_level_stamp_and_nested_header_columns(typestore) -> None:
    """Imu: top-level std `stamp` AND nested header.stamp.* both exist (Pitfall 6)."""
    schema = build_table_schema("sensor_msgs/msg/Imu", typestore, topic="/imu")
    names = [c.name for c in schema.columns]
    assert "stamp" in names  # the prepended standard column
    assert "header.stamp.sec" in names  # the faithful nested field
    assert "header.stamp.nanosec" in names
    assert "header.frame_id" in names  # header descends into its scalar leaves


def test_imu_covariance_is_a_single_list_double_leaf(typestore) -> None:
    """Imu.orientation_covariance is ONE list<double> leaf (recursion stops at ARRAY)."""
    schema = build_table_schema("sensor_msgs/msg/Imu", typestore, topic="/imu")
    by_name = {c.name: c for c in schema.columns}
    assert "orientation_covariance" in by_name  # not dotted into
    cov = by_name["orientation_covariance"]
    assert cov.arrow_type == pa.list_(pa.float64())
    assert cov.is_heavy_blob is False
    # The walk descends into the orientation sub-message (dotted scalar leaves)...
    assert "orientation.x" in by_name
    assert by_name["orientation.x"].arrow_type == pa.float64()
    # ...but does NOT produce a dotted column inside the covariance array.
    assert not any(n.startswith("orientation_covariance.") for n in by_name)
