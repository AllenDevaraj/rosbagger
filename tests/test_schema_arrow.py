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

import sys
from pathlib import Path

import pyarrow as pa
import pytest
from rosbags.typesys import Stores, get_typestore

# `tools` is a dev-only package at the repo root (NOT an installed distribution),
# so it is not on sys.path under pytest's default import mode. Put the repo root
# on sys.path here — scoped to this test file (mirrors tests/test_reader.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.make_fixtures import (  # noqa: E402  (after sys.path setup)
    make_all_fixtures,
    write_tf_bag,
)

from rosbagger_core.inspect import collect_table_schemas  # noqa: E402  (3rd-party stack)
from rosbagger_core.reader import RosbagsReader  # noqa: E402  (3rd-party stack)
from rosbagger_core.schema.flatten import (  # noqa: E402
    build_arrow_table,
    build_table_schema,
    flatten_message,
)
from rosbagger_core.schema.identifiers import quote_ident  # noqa: E402

FORMATS = ("ros1", "ros2_sqlite", "ros2_mcap")


@pytest.fixture(scope="session")
def typestore():
    """The real ROS 2 Humble typestore (no bag needed for schema-only tests)."""
    return get_typestore(Stores.ROS2_HUMBLE)


@pytest.fixture(scope="session")
def fixture_bags(tmp_path_factory) -> dict[str, Path]:
    """Generate all three fixture bags once into a throwaway session tmp dir."""
    dest = tmp_path_factory.mktemp("schema_arrow_bags")
    return make_all_fixtures(dest)


def _read_topic(bag_path: Path, topic: str):
    """Open ``bag_path``, return ``(messages_for_topic, typestore)``.

    The typestore is reached via ``reader._reader.typestore`` after ``open()``
    (research Open Question 3) — the schema is built from the SAME typestore the
    messages were deserialized with.
    """
    with RosbagsReader(bag_path) as reader:
        ts = reader._reader.typestore
        msgs = [m for m in reader.read() if m.topic == topic]
    msgs.sort(key=lambda m: m.t_ns)
    return msgs, ts


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


# ---------------------------------------------------------------------------
# Task 2 — flatten_message row extractor + build_arrow_table from a Message stream
# ---------------------------------------------------------------------------


def test_flatten_message_extracts_dotted_scalar_values(fixture_bags) -> None:
    """flatten_message pulls each non-standard leaf by ros_path (e.g. msg.linear.x)."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    # Fixture content: linear.x = i (0.0, 1.0, 2.0); angular.z = 0.1*i.
    row0 = flatten_message(msgs[0].msg, schema)
    assert row0["linear.x"] == 0.0
    assert row0["angular.z"] == 0.0
    row2 = flatten_message(msgs[2].msg, schema)
    assert row2["linear.x"] == 2.0
    assert row2["angular.z"] == pytest.approx(0.2)
    # The standard columns are NOT part of the per-message body extraction.
    assert "t" not in row0
    assert "topic" not in row0


def test_flatten_message_omits_heavy_blob_by_default(fixture_bags) -> None:
    """flatten_message omits the heavy data blob unless its name is in include."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/image")
    schema = build_table_schema("sensor_msgs/msg/Image", ts, topic="/image")
    row = flatten_message(msgs[0].msg, schema)
    assert "data" not in row
    row_with = flatten_message(msgs[0].msg, schema, include={"data"})
    assert "data" in row_with


def test_build_arrow_table_schema_matches_arrow_schema(fixture_bags) -> None:
    """build_arrow_table(...).schema == schema.arrow_schema(include=...)."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    table = build_arrow_table((m for m in msgs), schema)
    assert isinstance(table, pa.Table)
    assert table.schema.equals(schema.arrow_schema())
    assert table.num_rows == len(msgs)


def test_build_arrow_table_cmd_vel_dotted_column_values(fixture_bags) -> None:
    """A built /cmd_vel Table's "linear.x" column equals the per-message series."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    table = build_arrow_table(msgs, schema)
    assert table.column("linear.x").to_pylist() == [m.msg.linear.x for m in msgs]
    # Standard columns come straight off the Message.
    assert table.column("topic").to_pylist() == ["/cmd_vel"] * len(msgs)
    assert table.column("t_ns").to_pylist() == [m.t_ns for m in msgs]


def test_build_arrow_table_standard_time_columns_typed(fixture_bags) -> None:
    """t/stamp are timestamp('ns'); a headerless topic gets an all-NULL stamp."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    table = build_arrow_table(msgs, schema)
    assert table.schema.field("t").type == pa.timestamp("ns")
    assert table.schema.field("stamp").type == pa.timestamp("ns")
    # /cmd_vel is headerless -> every stamp is NULL.
    assert table.column("stamp").to_pylist() == [None] * len(msgs)
    # t_ns is the raw int64 series.
    assert table.schema.field("t_ns").type == pa.int64()


def test_build_arrow_table_imu_covariance_is_list_double(fixture_bags) -> None:
    """A built /imu Table has orientation_covariance as a list<double> column."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/imu")
    schema = build_table_schema("sensor_msgs/msg/Imu", ts, topic="/imu")
    table = build_arrow_table(msgs, schema)
    cov = table.schema.field("orientation_covariance")
    assert cov.type == pa.list_(pa.float64())
    # Each row is the fixture's 9-element zero covariance.
    first = table.column("orientation_covariance").to_pylist()[0]
    assert first == [0.0] * 9


def test_build_arrow_table_imu_stamp_off_the_message(fixture_bags) -> None:
    """The /imu top-level stamp/t come straight off each Message (Pitfall 6)."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/imu")
    schema = build_table_schema("sensor_msgs/msg/Imu", ts, topic="/imu")
    table = build_arrow_table(msgs, schema)
    # stamp materializes from the int-ns values as TIMESTAMP_NS (non-NULL here).
    assert table.column("stamp").null_count == 0
    assert table.column("t_ns").to_pylist() == [m.t_ns for m in msgs]


def test_build_arrow_table_image_blob_lazy_by_default(fixture_bags) -> None:
    """A built /image Table omits "data" by default; include={'data'} re-adds it."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/image")
    schema = build_table_schema("sensor_msgs/msg/Image", ts, topic="/image")
    default_table = build_arrow_table(msgs, schema)
    assert "data" not in default_table.schema.names
    with_blob = build_arrow_table(msgs, schema, include={"data"})
    assert "data" in with_blob.schema.names
    assert with_blob.schema.field("data").type == pa.list_(pa.uint8())
    assert with_blob.column("data").to_pylist()[0] == list(range(12))  # 2x2x3 ramp


def test_build_arrow_table_empty_stream_yields_typed_empty_table(typestore) -> None:
    """A zero-message stream still yields a Table with the full typed schema (RESEARCH §7)."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    table = build_arrow_table([], schema)
    assert isinstance(table, pa.Table)
    assert table.num_rows == 0
    assert table.schema.equals(schema.arrow_schema())
    assert "linear.x" in table.schema.names


# ---------------------------------------------------------------------------
# Task 3 — public schema/__init__ re-exports + end-to-end fixture pipeline,
#          LIST<STRUCT>, lazy blob, and the offline-import invariant.
# ---------------------------------------------------------------------------


def test_schema_package_reexports_public_api() -> None:
    """schema/__init__.py re-exports the public API and lists it in __all__."""
    import rosbagger_core.schema as schema_pkg

    expected = {
        "ColumnDef",
        "TableSchema",
        "build_table_schema",
        "build_arrow_table",
        "flatten_message",
        "sanitize_table_name",
        "TableNameResolver",
        "quote_ident",
    }
    assert expected <= set(schema_pkg.__all__)
    for name in expected:
        assert hasattr(schema_pkg, name), f"schema package missing {name}"


@pytest.mark.parametrize("fmt", FORMATS)
def test_end_to_end_imu_table_across_formats(fixture_bags, fmt) -> None:
    """reader -> schema -> Arrow Table works on /imu for all three formats.

    Asserts the standard columns plus the orientation_covariance list<double>,
    proving the full pipeline (the typestore reached via reader._reader.typestore).
    """
    msgs, ts = _read_topic(fixture_bags[fmt], "/imu")
    schema = build_table_schema("sensor_msgs/msg/Imu", ts, topic="/imu")
    table = build_arrow_table(msgs, schema)
    assert table.num_rows == len(msgs) == 3
    # Standard columns present and sourced off the Message.
    assert {"t", "t_ns", "stamp", "topic"} <= set(table.schema.names)
    assert table.column("topic").to_pylist() == ["/imu"] * 3
    # orientation_covariance is a list<double> with the fixture's 9-zero rows.
    assert table.schema.field("orientation_covariance").type == pa.list_(pa.float64())
    assert table.column("orientation_covariance").to_pylist()[0] == [0.0] * 9
    # /imu carries header.stamp -> top-level stamp is non-NULL.
    assert table.column("stamp").null_count == 0


def test_list_of_struct_transforms_has_short_inner_field_names(typestore) -> None:
    """A LIST<STRUCT> `transforms` column has SHORT struct inner names (RESEARCH §4/Pitfall 4)."""
    schema = build_table_schema("tf2_msgs/msg/TFMessage", typestore, topic="/tf")
    by_name = {c.name: c for c in schema.columns}
    assert "transforms" in by_name  # one LIST column, NOT dotted into
    transforms = by_name["transforms"]
    # list<struct<...>>
    assert pa.types.is_list(transforms.arrow_type)
    struct_type = transforms.arrow_type.value_type
    assert pa.types.is_struct(struct_type)
    inner_names = {struct_type.field(i).name for i in range(struct_type.num_fields)}
    # Inner names are SHORT (child_frame_id), never dotted (transforms.child_frame_id).
    assert "child_frame_id" in inner_names
    assert "header" in inner_names
    assert "transform" in inner_names
    assert not any(n.startswith("transforms.") for n in inner_names)
    # The walk did NOT emit dotted columns past the list either.
    assert not any(n.startswith("transforms.") for n in by_name)


def test_list_of_struct_arrow_schema_builds(typestore) -> None:
    """A LIST<STRUCT> column survives the arrow_schema build (no inference)."""
    schema = build_table_schema("tf2_msgs/msg/TFMessage", typestore, topic="/tf")
    arrow = schema.arrow_schema()
    assert pa.types.is_list(arrow.field("transforms").type)
    assert pa.types.is_struct(arrow.field("transforms").type.value_type)


def test_build_arrow_table_tf_list_of_struct_materializes(tmp_path) -> None:
    """A non-empty LIST<STRUCT> column (TFMessage.transforms) builds without ArrowTypeError.

    Regression for the audit HIGH bug: ``build_arrow_table`` passed deserialized
    ``rosbags`` sub-message *objects* straight into
    ``pa.array(..., type=list_(struct(...)))``, which raised ``ArrowTypeError`` —
    so ``SELECT * FROM /tf`` (and Path / PoseArray / MarkerArray / DiagnosticArray,
    all common topics) crashed. The schema build was tested; the data
    materialization of a non-empty sub-message array was not. The fix recursively
    converts the object tree to dict/list builtins keyed by the struct's declared
    field names. (Format-independent — it operates on already-deserialized objects.)
    """
    bag = write_tf_bag(tmp_path, ros1=False, storage="sqlite3")
    msgs, ts = _read_topic(bag, "/tf")
    assert msgs, "fixture must publish /tf messages"
    schema = build_table_schema("tf2_msgs/msg/TFMessage", ts, topic="/tf")

    table = build_arrow_table(msgs, schema)  # must NOT raise ArrowTypeError

    assert table.num_rows == len(msgs)
    transforms = table.column("transforms").to_pylist()
    # Each row is a list of struct dicts with SHORT inner field names.
    first = transforms[0]
    assert isinstance(first, list) and len(first) >= 1
    elem = first[0]
    assert isinstance(elem, dict)
    assert {"header", "child_frame_id", "transform"} <= set(elem)
    # The seeded child frames round-trip through the struct materialization.
    child_frames = {tf["child_frame_id"] for row in transforms for tf in row}
    assert {"base_link", "laser"} <= child_frames
    # Nested struct-in-struct (transform.translation.x) survived as a builtin float.
    assert isinstance(elem["transform"]["translation"]["x"], float)


def test_arrow_type_of_maps_octet_to_uint8() -> None:
    """The ROS 2 IDL 'octet' base type maps to uint8 (was a bare KeyError before the fix)."""
    from rosbags.interfaces import Nodetype

    from rosbagger_core.schema.types import arrow_type_of

    arrow_type, heavy = arrow_type_of((Nodetype.BASE, ("octet", 0)), None)
    assert arrow_type == pa.uint8()
    assert heavy is False


def test_arrow_type_of_unknown_base_raises_clear_valueerror() -> None:
    """An unmapped base type raises a clear ValueError naming it, not a bare KeyError."""
    from rosbags.interfaces import Nodetype

    from rosbagger_core.schema.types import arrow_type_of

    with pytest.raises(ValueError, match="madeup"):
        arrow_type_of((Nodetype.BASE, ("madeup", 0)), None)


def test_top_level_import_does_not_leak_pyarrow_or_rosbags() -> None:
    """`import rosbagger_core` (top level) pulls in NO pyarrow/rosbags (offline graph).

    Spawned in a FRESH interpreter so an already-imported pyarrow/rosbags in this
    test process (the suite imports both) cannot mask a leak. This re-asserts the
    offline invariant for the schema subpackage: the top-level package must not
    import `schema` (which DOES pull pyarrow), mirroring the `reader` convention.
    """
    import subprocess

    code = (
        "import sys; import rosbagger_core; "
        "leaked=[m for m in sys.modules if m.split('.')[0] in {'pyarrow','rosbags'}]; "
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": ""},
    )
    leaked = [m for m in result.stdout.strip().split(",") if m]
    assert leaked == [], f"top-level import rosbagger_core leaked: {leaked}"


def test_importing_schema_subpackage_is_allowed_to_pull_pyarrow() -> None:
    """Importing rosbagger_core.schema MAY pull pyarrow (like reader/__init__).

    This documents the seam: the subpackage is heavy-by-design; only the
    top-level package stays light. We just assert the subpackage imports cleanly.
    """
    import importlib

    mod = importlib.import_module("rosbagger_core.schema")
    assert mod.build_arrow_table is build_arrow_table


# ---------------------------------------------------------------------------
# Phase 10 / QURY-09 — projection ``restrict=`` filter, composed (ANDed) with the
# heavy-blob ``include=`` filter (D-06). The four standard columns are NOT
# auto-added by these functions: D-07's always-materialized guarantee is enforced
# UPSTREAM by the orchestrator (Plan 10-03) unioning {t,t_ns,stamp,topic} into the
# restrict set. A bare ``restrict={"linear.x"}`` here legitimately yields exactly
# ``["linear.x"]``. ``restrict=None`` is byte-for-byte today's behavior.
# Run locally with the host ROS leak neutralized:
#   PYTHONPATH="" .venv/bin/python -m pytest tests/test_schema_arrow.py -k restrict -x
# ---------------------------------------------------------------------------


# --- Task 1: restrict= on TableSchema.arrow_schema + column_names -------------


def test_arrow_schema_restrict_keeps_only_named_data_column(typestore) -> None:
    """arrow_schema(restrict={"linear.x"}) yields EXACTLY ["linear.x"] (no auto std cols)."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    arrow = schema.arrow_schema(restrict={"linear.x"})
    # The standard cols (t/t_ns/stamp/topic) are NOT auto-added here — the
    # orchestrator (Plan 10-03) unions them into restrict (D-07). With a bare
    # {"linear.x"} ONLY linear.x survives.
    assert arrow.names == ["linear.x"]
    assert isinstance(arrow, pa.Schema)


def test_arrow_schema_restrict_none_is_todays_default(typestore) -> None:
    """arrow_schema(restrict=None) is byte-identical to today's arrow_schema()."""
    schema = build_table_schema("geometry_msgs/msg/Twist", typestore, topic="/cmd_vel")
    assert schema.arrow_schema(restrict=None).equals(schema.arrow_schema())
    # And declared order is preserved (std cols first, then the body cols).
    assert schema.arrow_schema(restrict=None).names == [
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


def test_arrow_schema_restrict_and_include_compose_for_heavy_blob(typestore) -> None:
    """The two filters AND: a heavy blob needs BOTH include AND restrict to survive (D-06)."""
    schema = build_table_schema("sensor_msgs/msg/Image", typestore, topic="/image")
    # data (heavy) in BOTH include and restrict -> kept; t in restrict (light) -> kept.
    both = schema.arrow_schema(include={"data"}, restrict={"data", "t"})
    assert set(both.names) == {"data", "t"}
    # data heavy + NOT in include -> dropped, EVEN THOUGH it is in restrict (ANDed).
    light_only = schema.arrow_schema(include=set(), restrict={"data", "t"})
    assert light_only.names == ["t"]
    assert "data" not in light_only.names


def test_column_names_restrict_mirrors_arrow_schema_names(typestore) -> None:
    """column_names(restrict=...) mirrors arrow_schema(restrict=...).names for the same args."""
    schema = build_table_schema("sensor_msgs/msg/Image", typestore, topic="/image")
    for include, restrict in (
        (None, {"linear.x"}),  # a name absent from Image -> empty
        (None, {"height", "width"}),
        (None, None),  # the default path
        ({"data"}, {"data", "t", "height"}),
        (set(), {"data", "t"}),  # heavy dropped (not included)
    ):
        names = schema.column_names(include=include, restrict=restrict)
        arrow_names = schema.arrow_schema(include=include, restrict=restrict).names
        assert names == arrow_names, (include, restrict)


# --- Task 2: restrict= on flatten_message + build_arrow_table (skipped read) ---


def test_flatten_message_restrict_returns_only_named_column(fixture_bags) -> None:
    """flatten_message(restrict={"linear.x"}) returns ONLY linear.x (others not iterated)."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    row = flatten_message(msgs[0].msg, schema, restrict={"linear.x"})
    assert set(row) == {"linear.x"}
    assert "linear.y" not in row
    assert "angular.z" not in row


def test_flatten_message_restrict_skips_the_read_proven_by_spy() -> None:
    """The pushdown: a non-restricted column's reduce(getattr,...) NEVER runs.

    A spy message whose ``.angular`` raises on attribute access proves that
    ``flatten_message(stub, schema, restrict={"linear.x"})`` never touches
    ``angular`` — the literal skipped read (D-06 / Pattern 3). Belt-and-suspenders
    over the column-set assertion (research A4): the value is provably never read.
    """

    class _Linear:
        # All three linear scalars are reachable (the Twist schema reads
        # linear.x/y/z BEFORE angular.* in declared order).
        x = 7.0
        y = 8.0
        z = 9.0

    class _SpyMsg:
        linear = _Linear()

        @property
        def angular(self):  # touching angular at all blows up
            raise AssertionError("angular was read off the message — pushdown failed")

    schema = build_table_schema(
        "geometry_msgs/msg/Twist", get_typestore(Stores.ROS2_HUMBLE), topic="/cmd_vel"
    )
    # restrict to linear.x only: angular.* must never be reduced, so no raise.
    row = flatten_message(_SpyMsg(), schema, restrict={"linear.x"})
    assert row == {"linear.x": 7.0}
    # And the control: WITHOUT restrict, the same spy DOES touch angular and raises.
    with pytest.raises(AssertionError, match="angular was read"):
        flatten_message(_SpyMsg(), schema)


def test_build_arrow_table_restrict_projects_single_column(fixture_bags) -> None:
    """build_arrow_table(restrict={"linear.x"}) -> Table with exactly that column; values match."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/cmd_vel")
    schema = build_table_schema("geometry_msgs/msg/Twist", ts, topic="/cmd_vel")
    table = build_arrow_table(msgs, schema, restrict={"linear.x"})
    assert table.column_names == ["linear.x"]
    # Fixture content: linear.x = i (0.0, 1.0, 2.0).
    assert table.column("linear.x").to_pylist() == [0.0, 1.0, 2.0]
    # Regression: restrict=None reproduces today's full-column Table.
    full = build_arrow_table(msgs, schema, restrict=None)
    assert full.schema.equals(schema.arrow_schema())
    assert "angular.z" in full.column_names


def test_build_arrow_table_restrict_composes_with_heavy_blob(fixture_bags) -> None:
    """build_arrow_table threads restrict AND include for heavy blobs (D-06)."""
    msgs, ts = _read_topic(fixture_bags["ros2_sqlite"], "/image")
    schema = build_table_schema("sensor_msgs/msg/Image", ts, topic="/image")
    # data (heavy) in BOTH include and restrict, plus t -> both materialized.
    both = build_arrow_table(msgs, schema, include={"data"}, restrict={"data", "t"})
    assert set(both.column_names) == {"data", "t"}
    assert both.schema.field("data").type == pa.list_(pa.uint8())
    # include=set(), restrict={"t"}: data heavy + NOT included -> absent.
    no_blob = build_arrow_table(msgs, schema, include=set(), restrict={"t"})
    assert no_blob.column_names == ["t"]
    assert "data" not in no_blob.column_names


# --- Task 3: the bagq tables / collect_table_schemas path is unaffected -------


def test_tables_path_unaffected_by_restrict_param(fixture_bags) -> None:
    """``bagq tables`` (collect_table_schemas) is provably unchanged by the new restrict param.

    The D-06 "the only production caller of the schema filter is backend/query.py;
    bagq tables / collect_table_schemas never passes restrict" guarantee. Since
    those functions default ``restrict=None``, ``column_names()`` (no restrict)
    must still list EVERY non-heavy column in declared order and exclude the heavy
    blob — exactly today's behavior. The /image table is the meaningful case: it
    carries the only heavy blob (``data``) among the fixture topics.
    """
    with RosbagsReader(fixture_bags["ros2_sqlite"]) as reader:
        schemas = collect_table_schemas(reader)
    by_name = {s.table_name: s for s in schemas}

    # /image: the non-heavy columns in declared order, with the heavy `data`
    # blob omitted by the default (restrict=None, include=None) path — unchanged.
    image = by_name["image"]
    assert image.column_names() == [
        "t",
        "t_ns",
        "stamp",
        "topic",
        "header.stamp.sec",
        "header.stamp.nanosec",
        "header.frame_id",
        "height",
        "width",
        "encoding",
        "is_bigendian",
        "step",
    ]
    # The heavy blob is excluded by default and re-included only via include=
    # (the QURY-07 rule), with restrict still None — no behavior change.
    assert "data" not in image.column_names()
    assert "data" in image.column_names(include={"data"})

    # And the no-arg call equals the explicit restrict=None call for every topic
    # (the default path is byte-for-byte the projection-disabled path).
    for schema in schemas:
        assert schema.column_names() == schema.column_names(restrict=None)
        assert schema.arrow_schema().equals(schema.arrow_schema(restrict=None))
