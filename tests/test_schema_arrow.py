"""End-to-end Arrow-build tests for Phase 3 plan ``03-03``.

These prove the row-extraction + ``pyarrow.Table`` build half of the schema
layer against the REAL fixture corpus and the REAL ``rosbags`` ROS 2 Humble
typestore:

* ``schema/model.py`` — ``TableSchema.arrow_schema(include=...)`` now returns a
  real ``pyarrow.Schema`` honoring the lazy heavy-blob ``include`` set (QURY-07).
* ``schema/identifiers.py`` — ``quote_ident`` renders an injection-safe quoted
  SQL identifier via ``sqlglot`` (the T-03-06 tampering defense).
* ``schema/flatten.py`` — ``flatten_message`` extracts row values by ``ros_path``
  and ``build_arrow_table`` turns a stream of ``Message`` into a typed
  ``pyarrow.Table`` (dotted columns, LIST / LIST-of-STRUCT, lazy blobs;
  QURY-03/07).
* ``schema/__init__.py`` — the public re-exports mirror ``reader/__init__.py``.

LOCAL-RUN REQUIREMENT (02-RESEARCH.md Pitfall 5): this dev host sources ROS 2
Humble onto ``PYTHONPATH``, which can pull ROS plugins into the test process and
crash pytest on collection. Run these tests locally with the host leak
neutralized (with coverage, per the project gate)::

    PYTHONPATH="" uv run pytest tests/test_schema_arrow.py -q

CI is ROS-free, so it needs NO prefix — and this file bakes in NO ``PYTHONPATH``
override (it is a run-time prefix only, never committed code).
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from rosbags.typesys import Stores, get_typestore

from rosbagger_core.schema.flatten import build_table_schema
from rosbagger_core.schema.identifiers import quote_ident


@pytest.fixture(scope="session")
def typestore():
    """The real ROS 2 Humble typestore (no bag needed for schema-only tests)."""
    return get_typestore(Stores.ROS2_HUMBLE)


# ---------------------------------------------------------------------------
# Task 1 — TableSchema.arrow_schema(include=...) + the sqlglot identifier helper
# ---------------------------------------------------------------------------


def test_arrow_schema_returns_pyarrow_schema_with_std_columns(typestore) -> None:
    """arrow_schema() returns a real pa.Schema with the four standard columns."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    arrow = schema.arrow_schema()
    assert isinstance(arrow, pa.Schema)
    assert arrow.names[:4] == ["t", "t_ns", "stamp", "topic"]
    assert arrow.field("t").type == pa.timestamp("ns")
    assert arrow.field("t_ns").type == pa.int64()
    assert arrow.field("stamp").type == pa.timestamp("ns")
    assert arrow.field("topic").type == pa.string()


def test_arrow_schema_field_order_matches_declared_columns(typestore) -> None:
    """The Arrow field order matches the TableSchema column order (std cols first)."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    arrow = schema.arrow_schema()
    assert arrow.names == [
        "t",
        "t_ns",
        "stamp",
        "topic",
        "linear.x",
        "linear.y",
        "linear.z",
        "angular.x",
        "angular.y",
        "angular.z",
    ]
    assert arrow.field("linear.x").type == pa.float64()


def test_arrow_schema_stamp_field_is_nullable(typestore) -> None:
    """The `stamp` field stays nullable (headerless topics get an all-NULL stamp)."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    arrow = schema.arrow_schema()
    assert arrow.field("stamp").nullable is True


def test_arrow_schema_omits_heavy_blob_by_default(typestore) -> None:
    """arrow_schema() omits the heavy Image.data blob column by default (QURY-07)."""
    schema = build_table_schema("sensor_msgs/msg/Image", typestore, topic="/image")
    arrow = schema.arrow_schema()
    assert "data" not in arrow.names


def test_arrow_schema_includes_heavy_blob_when_named(typestore) -> None:
    """arrow_schema(include={'data'}) re-adds the heavy blob as list<uint8>."""
    schema = build_table_schema("sensor_msgs/msg/Image", typestore, topic="/image")
    arrow = schema.arrow_schema(include={"data"})
    assert "data" in arrow.names
    assert arrow.field("data").type == pa.list_(pa.uint8())


def test_arrow_schema_include_key_is_dotted_column_name(typestore) -> None:
    """The include key is the dotted column name (Open Q2); a non-matching key is a no-op."""
    schema = build_table_schema("sensor_msgs/msg/Image", typestore, topic="/image")
    # An unrelated include key must NOT smuggle the blob back in.
    arrow = schema.arrow_schema(include={"not_a_real_column"})
    assert "data" not in arrow.names


def test_quote_ident_quotes_a_dotted_identifier() -> None:
    """quote_ident wraps a dotted column name in double quotes (RESEARCH Pattern 6)."""
    assert quote_ident("twist.twist.linear.x") == '"twist.twist.linear.x"'


def test_quote_ident_escapes_embedded_quote() -> None:
    """An embedded double-quote is escaped by doubling (the injection defense)."""
    assert quote_ident('weird"name') == '"weird""name"'


def test_quote_ident_neutralizes_sql_injection() -> None:
    """A malicious identifier is neutralized into ONE quoted identifier (T-03-06)."""
    malicious = 'x"; DROP TABLE y;--'
    quoted = quote_ident(malicious)
    # The whole thing is one quoted identifier: starts and ends with a quote, and
    # the embedded quote is doubled (escaped), so no SQL statement can break out.
    assert quoted.startswith('"') and quoted.endswith('"')
    assert quoted == '"x""; DROP TABLE y;--"'
