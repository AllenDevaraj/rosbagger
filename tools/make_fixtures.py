"""Fixture-bag generator — the single most-reused test artifact in rosbagger.

Using ``rosbags``'s *write* capability (no ROS install required), this module
emits tiny bags in all three target formats:

* ROS 1 (single-file ``.bag``)            via ``rosbags.rosbag1.Writer`` + ``serialize_ros1``
* ROS 2 sqlite3 (``metadata.yaml`` + ``.db3``) via ``rosbags.rosbag2.Writer`` + ``serialize_cdr``
* ROS 2 MCAP (``metadata.yaml`` + ``.mcap``)   via ``rosbags.rosbag2.Writer`` + ``serialize_cdr``

The fixtures carry deliberately **forward-looking** content so Phases 2-3 can
exercise their query features without ever changing the fixtures:

* ``/cmd_vel`` ``geometry_msgs/msg/Twist`` — nested scalars, NO header
  -> dotted-column flattening (QURY-02) and ``stamp`` IS NULL (QURY-04).
* ``/imu``     ``sensor_msgs/msg/Imu``     — ``header.stamp`` + ``orientation_covariance``
  (``float64[9]``) -> stamp extraction (QURY-04) and LIST columns (QURY-03).
* ``/image``   ``sensor_msgs/msg/Image``   — a small ``data`` ``uint8[]`` byte blob
  -> heavy-blob lazy materialization (QURY-07).

OFFLINE INVARIANT: this module imports only ``rosbags`` / ``numpy`` / stdlib —
never ``rclpy`` or ``rosbag2_py``. That is what lets the fixtures (and the whole
test suite) run in ROS-free CI.

API (an internal contract later phases consume)::

    write_ros1_bag(dest_dir)        -> Path  # single-file .bag
    write_ros2_sqlite_bag(dest_dir) -> Path  # ROS 2 sqlite3 bag directory
    write_ros2_mcap_bag(dest_dir)   -> Path  # ROS 2 MCAP bag directory
    write_tf_bag(dest_dir, *, ros1[, storage]) -> Path  # /tf + /tf_static with a seeded gap
    make_all_fixtures(dest_dir)     -> dict[str, Path]  # {"ros1", "ros2_sqlite", "ros2_mcap"}

Run as a module to write the three bags to disk for manual ``bagq`` testing::

    python -m tools.make_fixtures [DEST_DIR]   # DEST_DIR defaults to ./fixtures (gitignored)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
from rosbags.rosbag1 import Writer as Ros1Writer
from rosbags.rosbag2 import StoragePlugin
from rosbags.rosbag2 import Writer as Ros2Writer
from rosbags.typesys import Stores, get_types_from_msg, get_typestore

# Deterministic, reproducible timestamps: 1s, 1.1s, 1.2s ... in nanoseconds.
_T0_NS = 1_000_000_000
_DT_NS = 100_000_000
_N_MSGS = 3

_TOPIC_CMD_VEL = "/cmd_vel"
_TOPIC_IMU = "/imu"
_TOPIC_IMAGE = "/image"
_TOPIC_TF = "/tf"
_TOPIC_TF_STATIC = "/tf_static"

_MSGTYPE_TWIST = "geometry_msgs/msg/Twist"
_MSGTYPE_IMU = "sensor_msgs/msg/Imu"
_MSGTYPE_IMAGE = "sensor_msgs/msg/Image"
_MSGTYPE_TFMESSAGE = "tf2_msgs/msg/TFMessage"

# The TF fixture (write_tf_bag) publishes a dynamic edge over a 24-tick window with
# a contiguous run omitted to seed a deterministic gap. Skipping indices 8..14 leaves
# t=7 then t=15, so the single gap delta is _timestamp_ns(15) - _timestamp_ns(7) ==
# 8 * _DT_NS == 800_000_000 ns; every other inter-arrival delta is exactly _DT_NS.
_TF_N_TICKS = 24
_TF_GAP_START_TICK = 8  # first omitted tick (inclusive)
_TF_GAP_END_TICK = 15  # first tick published again after the gap (exclusive lower bound is 8..14)

# A tiny custom .msg used ONLY by write_def_less_bag (the CLI-04 fixture). Its
# definition is registered to write the bag, then stripped from the .db3 so the bag
# re-opens with no resolvable type defs.
_CUSTOM_MSG = "float64 widget_value\nstring widget_label\n"


def _timestamp_ns(i: int) -> int:
    """Deterministic per-message log timestamp in nanoseconds."""
    return _T0_NS + i * _DT_NS


def _make_header(ts, *, sec: int, nanosec: int, frame_id: str, ros1: bool):
    """Build a ``std_msgs/msg/Header`` for the given typestore.

    ROS 1's ``Header`` has a required ``seq`` field that ROS 2 dropped, so the
    header MUST be built per-format (01-RESEARCH.md Pitfall 3). Do NOT share a
    single message-builder across the two typestores.
    """
    time_t = ts.types["builtin_interfaces/msg/Time"]
    header_t = ts.types["std_msgs/msg/Header"]
    stamp = time_t(sec=sec, nanosec=nanosec)
    if ros1:
        return header_t(seq=0, stamp=stamp, frame_id=frame_id)
    return header_t(stamp=stamp, frame_id=frame_id)


def _twist(ts, i: int):
    """``geometry_msgs/msg/Twist`` — nested scalars, no header (typestore-agnostic)."""
    vector3_t = ts.types["geometry_msgs/msg/Vector3"]
    twist_t = ts.types["geometry_msgs/msg/Twist"]
    return twist_t(
        linear=vector3_t(x=float(i), y=0.0, z=0.0),
        angular=vector3_t(x=0.0, y=0.0, z=0.1 * i),
    )


def _imu(ts, i: int, *, ros1: bool):
    """``sensor_msgs/msg/Imu`` — header WITH stamp + float64[9] covariance arrays."""
    quaternion_t = ts.types["geometry_msgs/msg/Quaternion"]
    vector3_t = ts.types["geometry_msgs/msg/Vector3"]
    imu_t = ts.types["sensor_msgs/msg/Imu"]
    header = _make_header(ts, sec=1 + i, nanosec=i * _DT_NS, frame_id="imu_link", ros1=ros1)
    return imu_t(
        header=header,
        orientation=quaternion_t(x=0.0, y=0.0, z=0.0, w=1.0),
        orientation_covariance=np.zeros(9, dtype=np.float64),
        angular_velocity=vector3_t(x=0.0, y=0.0, z=0.1 * i),
        angular_velocity_covariance=np.zeros(9, dtype=np.float64),
        linear_acceleration=vector3_t(x=0.0, y=0.0, z=9.8),
        linear_acceleration_covariance=np.zeros(9, dtype=np.float64),
    )


def _image(ts, i: int, *, ros1: bool):
    """``sensor_msgs/msg/Image`` — tiny 2x2 RGB, ``data`` is a uint8[] byte blob."""
    image_t = ts.types["sensor_msgs/msg/Image"]
    header = _make_header(ts, sec=1 + i, nanosec=i * _DT_NS, frame_id="camera", ros1=ros1)
    height, width, channels = 2, 2, 3  # 2x2 RGB
    step = width * channels
    data = np.arange(height * step, dtype=np.uint8)  # the heavy-blob placeholder
    return image_t(
        header=header,
        height=np.uint32(height),
        width=np.uint32(width),
        encoding="rgb8",
        is_bigendian=np.uint8(0),
        step=np.uint32(step),
        data=data,
    )


def _transform_stamped(ts, *, parent: str, child: str, sec: int, nanosec: int, ros1: bool):
    """Build a ``geometry_msgs/msg/TransformStamped`` edge ``parent -> child``.

    The PARENT frame goes in ``header.frame_id`` and the CHILD in ``child_frame_id``
    (the tf2 convention). The transform itself is an identity pose (zero translation,
    unit quaternion ``(0,0,0,1)``) — the fixture exercises graph/timing, not geometry.
    """
    transform_stamped_t = ts.types["geometry_msgs/msg/TransformStamped"]
    transform_t = ts.types["geometry_msgs/msg/Transform"]
    vector3_t = ts.types["geometry_msgs/msg/Vector3"]
    quaternion_t = ts.types["geometry_msgs/msg/Quaternion"]
    header = _make_header(ts, sec=sec, nanosec=nanosec, frame_id=parent, ros1=ros1)
    return transform_stamped_t(
        header=header,
        child_frame_id=child,
        transform=transform_t(
            translation=vector3_t(x=0.0, y=0.0, z=0.0),
            rotation=quaternion_t(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )


def _tf_message(ts, transforms: list):
    """Wrap a list of ``TransformStamped`` in a ``tf2_msgs/msg/TFMessage``.

    ``TFMessage`` has a single field ``transforms`` and NO top-level header.
    """
    tfmessage_t = ts.types[_MSGTYPE_TFMESSAGE]
    return tfmessage_t(transforms=transforms)


def _populate(writer, ts, *, ros1: bool) -> None:
    """Add the three forward-looking topics and write ``_N_MSGS`` messages each.

    Works against either the ROS 1 or ROS 2 ``Writer`` because both share the
    ``add_connection(topic, msgtype, typestore=...)`` / ``write(conn, t_ns, raw)``
    surface; only the serializer and per-format header differ.
    """
    serialize = ts.serialize_ros1 if ros1 else ts.serialize_cdr

    cmd_vel_conn = writer.add_connection(_TOPIC_CMD_VEL, _MSGTYPE_TWIST, typestore=ts)
    imu_conn = writer.add_connection(_TOPIC_IMU, _MSGTYPE_IMU, typestore=ts)
    image_conn = writer.add_connection(_TOPIC_IMAGE, _MSGTYPE_IMAGE, typestore=ts)

    for i in range(_N_MSGS):
        t_ns = _timestamp_ns(i)
        writer.write(cmd_vel_conn, t_ns, serialize(_twist(ts, i), _MSGTYPE_TWIST))
        writer.write(imu_conn, t_ns, serialize(_imu(ts, i, ros1=ros1), _MSGTYPE_IMU))
        writer.write(image_conn, t_ns, serialize(_image(ts, i, ros1=ros1), _MSGTYPE_IMAGE))


def write_ros1_bag(dest_dir: Path | str) -> Path:
    """Write a ROS 1 single-file ``.bag`` into ``dest_dir`` and return its path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "ros1.bag"
    ts = get_typestore(Stores.ROS1_NOETIC)
    # rosbags.rosbag1.Writer takes NO version/storage_plugin args (it is a
    # DIFFERENT Writer from the ROS 2 one). Serialize with serialize_ros1.
    with Ros1Writer(path) as writer:
        _populate(writer, ts, ros1=True)
    return path


def _write_ros2_bag(dest_dir: Path, name: str, storage_plugin: StoragePlugin) -> Path:
    """Write a ROS 2 bag directory (sqlite3 or MCAP) and return its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / name
    ts = get_typestore(Stores.ROS2_HUMBLE)
    # version=9 is a REQUIRED keyword-only arg (01-RESEARCH.md Pitfall 1);
    # StoragePlugin is a module-level export of rosbags.rosbag2 (Pitfall 2).
    with Ros2Writer(path, version=9, storage_plugin=storage_plugin) as writer:
        _populate(writer, ts, ros1=False)
    return path


def write_ros2_sqlite_bag(dest_dir: Path | str) -> Path:
    """Write a ROS 2 **sqlite3** bag directory into ``dest_dir`` and return its path."""
    return _write_ros2_bag(Path(dest_dir), "ros2_sqlite", StoragePlugin.SQLITE3)


def write_ros2_mcap_bag(dest_dir: Path | str) -> Path:
    """Write a ROS 2 **MCAP** bag directory into ``dest_dir`` and return its path."""
    return _write_ros2_bag(Path(dest_dir), "ros2_mcap", StoragePlugin.MCAP)


def write_def_less_bag(dest_dir: Path | str, *, msgtype: str = "my_pkg/msg/Widget") -> Path:
    """Write a ROS 2 sqlite bag with a custom type, then strip its embedded definitions.

    Reproduces the CLI-04 condition (07-RESEARCH §7 / Pitfall 5): a normal ROS 2 v9
    sqlite bag is written with a custom ``my_pkg/msg/Widget`` type (registered on a
    fresh typestore so the write succeeds), then its ``message_definitions`` rows are
    DELETED directly from the ``.db3`` via stdlib ``sqlite3``. Re-opening the bag with
    a plain ``AnyReader`` (no ``default_typestore``) then raises
    ``AnyReaderError('Bag contains no type definitions...')`` at ``open()`` — the exact
    signal :class:`~rosbagger_core.errors.UnresolvedTypeError` is wrapped around.

    sqlite3 is the only ``rosbags``-writable format where defs are separable (ROS 1
    embeds them in the bag header, normal ROS 2 v9 stores + auto-registers them), so
    the fixture MUST be a sqlite bag. The ``DELETE`` runs on a file this function just
    created in a throwaway dir — never an untrusted/user bag (threat T-07-06).

    Returns the bag directory path.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "def_less_bag"
    ts = get_typestore(Stores.ROS2_HUMBLE)
    ts.register(get_types_from_msg(_CUSTOM_MSG, msgtype))
    with Ros2Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3) as writer:
        conn = writer.add_connection("/widget", msgtype, typestore=ts)
        widget_t = ts.types[msgtype]
        raw = ts.serialize_cdr(widget_t(widget_value=1.0, widget_label="hi"), msgtype)
        writer.write(conn, _T0_NS, raw)
    db = next(path.glob("*.db3"))
    conn_db = sqlite3.connect(db)
    try:
        conn_db.execute("DELETE FROM message_definitions")  # strip defs -> unresolvable
        conn_db.commit()
    finally:
        conn_db.close()
    return path


def write_ros2_sqlite_bag_defless(dest_dir: Path | str) -> Path:
    """Write a STANDARD-type ROS 2 sqlite bag, then strip its embedded definitions.

    Reproduces a REAL ``rosbag2``-recorded sqlite3 bag: the C++ recorder stores no
    inline message definitions, so re-opening with a plain ``AnyReader`` (no
    ``default_typestore``) raises ``AnyReaderError('Bag contains no type
    definitions...')``. Unlike :func:`write_def_less_bag` (a CUSTOM ``my_pkg/msg/Widget``
    type → unresolvable even WITH a typestore, the CLI-04 ``UnresolvedTypeError`` signal),
    this writes the standard Twist/Imu/Image topics via :func:`_populate`, so re-opening
    WITH ``get_typestore(Stores.ROS2_HUMBLE)`` resolves cleanly. It is the desktop
    replay-panel regression fixture: ``load_items(bag)`` fails, ``load_items(bag,
    default_typestore=ROS2_HUMBLE)`` succeeds.

    The ``DELETE`` runs on a ``.db3`` this function just created in a throwaway dir —
    never an untrusted/user bag (mirrors :func:`write_def_less_bag`, threat T-07-06).
    Returns the bag directory path.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "ros2_sqlite_defless"
    ts = get_typestore(Stores.ROS2_HUMBLE)
    # version=9 + StoragePlugin.SQLITE3 mirror _write_ros2_bag (Pitfalls 1/2); sqlite3 is the
    # only rosbags-writable format whose embedded defs are separable (DELETE-able post-write).
    with Ros2Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3) as writer:
        _populate(writer, ts, ros1=False)
    db = next(path.glob("*.db3"))
    conn_db = sqlite3.connect(db)
    try:
        conn_db.execute("DELETE FROM message_definitions")  # strip defs -> needs a typestore
        conn_db.commit()
    finally:
        conn_db.close()
    return path


def write_capitalized_topic_bag(dest_dir: Path | str, *, topic: str = "/Imu") -> Path:
    """Write a ROS 2 sqlite bag with a single CAPITALIZED topic name (the newA5 fixture).

    The topic sanitizes to a mixed-case table name (``/Imu`` -> ``Imu``), so a lowercase
    SQL reference (``FROM imu``) must resolve case-insensitively — DuckDB folds identifier
    case and the orchestrator forwards the SQL verbatim, so its own pre-flight resolution
    must fold case too. Uses the standard ``sensor_msgs/msg/Imu`` payload (``_imu``) so the
    bag self-describes and needs no ``default_typestore``.

    Returns the bag directory path.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "capitalized_topic"
    ts = get_typestore(Stores.ROS2_HUMBLE)
    with Ros2Writer(path, version=9, storage_plugin=StoragePlugin.SQLITE3) as writer:
        conn = writer.add_connection(topic, _MSGTYPE_IMU, typestore=ts)
        for i in range(_N_MSGS):
            writer.write(conn, _timestamp_ns(i), ts.serialize_cdr(_imu(ts, i, ros1=False), _MSGTYPE_IMU))
    return path


def write_tf_bag(dest_dir: Path | str, *, ros1: bool, storage: str = "sqlite3") -> Path:
    """Write a TF fixture bag (``/tf`` + ``/tf_static``) with a seeded ~800ms gap.

    This is the Phase 9 (TF debugger) test artifact: a bag that proves the analyzer's
    three Success Criteria with no ROS install. It writes ONE bag whose format is chosen
    by ``ros1`` (and, for ROS 2, by ``storage``):

    * ``ros1=True``                       -> ``dest_dir/tf_ros1.bag`` (``storage`` ignored)
    * ``ros1=False, storage="sqlite3"``   -> ``dest_dir/tf_ros2`` (ROS 2 sqlite3 dir)
    * ``ros1=False, storage="mcap"``      -> ``dest_dir/tf_ros2`` (ROS 2 MCAP dir)

    Tests parametrize over all three to exercise every target format (SC3).

    **ROS 1 type registration:** ``Stores.ROS1_NOETIC`` ships ``TransformStamped`` /
    ``Transform`` but NOT ``tf2_msgs/msg/TFMessage`` (verified ``False``), so the ROS 1
    path registers the type first via ``get_types_from_msg`` (round-trip-verified, the
    same idiom as :func:`write_def_less_bag`). ``Stores.ROS2_HUMBLE`` already has it, so
    the ROS 2 path does NOT register.

    **Seeded content** (asserted verbatim by the Phase 9 analyzer test):

    * ``/tf_static``: ONE latched message at ``_timestamp_ns(0)`` carrying a single
      ``map -> odom`` transform. Proves a static edge is kept in the graph but never
      gap-checked.
    * ``/tf`` dynamic edge ``odom -> base_link``: published every ``_DT_NS`` for
      ``i in range(_TF_N_TICKS)`` (24 ticks) with the contiguous block ``8..14`` OMITTED.
      The omission leaves t=7 then t=15, so this edge has exactly ONE inter-arrival
      delta of ``8 * _DT_NS == 800_000_000`` ns and all others equal to ``_DT_NS``.
    * ``/tf`` dynamic edge ``base_link -> laser``: published every ``_DT_NS`` across the
      SAME 24-tick window with NO omission — a clean edge whose deltas are all ``_DT_NS``.

    Both dynamic edges are emitted as a SINGLE ``/tf`` ``TFMessage`` per tick carrying
    whichever transforms are present at that tick (both edges on ticks ``0..7`` and
    ``15..23``; only ``base_link -> laser`` on the omitted ticks ``8..14``). The analyzer
    keys edges by ``(parent, child)``, so co-bundling the two edges in one message is
    equivalent to publishing them separately.

    OFFLINE INVARIANT: imports only ``rosbags`` / ``numpy`` / stdlib (all at module top);
    never ``rclpy`` / ``rosbag2_py``.

    Returns the written bag path (a ``.bag`` file for ROS 1, a bag directory for ROS 2).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if ros1:
        ts = get_typestore(Stores.ROS1_NOETIC)
        # ROS1_NOETIC has no TFMessage — register it (mirrors write_def_less_bag).
        ts.register(
            get_types_from_msg("geometry_msgs/TransformStamped[] transforms\n", _MSGTYPE_TFMESSAGE)
        )
        serialize = ts.serialize_ros1
        path = dest_dir / "tf_ros1.bag"
        writer_cm = Ros1Writer(path)
    else:
        ts = get_typestore(Stores.ROS2_HUMBLE)  # ROS 2 ships TFMessage — no registration.
        serialize = ts.serialize_cdr
        storage_plugin = {
            "sqlite3": StoragePlugin.SQLITE3,
            "mcap": StoragePlugin.MCAP,
        }[storage]
        path = dest_dir / "tf_ros2"
        writer_cm = Ros2Writer(path, version=9, storage_plugin=storage_plugin)

    with writer_cm as writer:
        tf_conn = writer.add_connection(_TOPIC_TF, _MSGTYPE_TFMESSAGE, typestore=ts)
        tf_static_conn = writer.add_connection(_TOPIC_TF_STATIC, _MSGTYPE_TFMESSAGE, typestore=ts)

        # /tf_static: one latched map -> odom transform at t0.
        static_tf = _transform_stamped(ts, parent="map", child="odom", sec=1, nanosec=0, ros1=ros1)
        writer.write(
            tf_static_conn,
            _timestamp_ns(0),
            serialize(_tf_message(ts, [static_tf]), _MSGTYPE_TFMESSAGE),
        )

        # /tf: dynamic edges over a 24-tick window. odom->base_link skips ticks 8..14
        # (seeding the 800ms gap); base_link->laser is published on every tick (clean).
        for i in range(_TF_N_TICKS):
            t_ns = _timestamp_ns(i)
            sec, nanosec = divmod(t_ns, 1_000_000_000)
            transforms = []
            if not (_TF_GAP_START_TICK <= i < _TF_GAP_END_TICK):
                transforms.append(
                    _transform_stamped(
                        ts, parent="odom", child="base_link", sec=sec, nanosec=nanosec, ros1=ros1
                    )
                )
            transforms.append(
                _transform_stamped(
                    ts, parent="base_link", child="laser", sec=sec, nanosec=nanosec, ros1=ros1
                )
            )
            writer.write(tf_conn, t_ns, serialize(_tf_message(ts, transforms), _MSGTYPE_TFMESSAGE))

    return path


def make_all_fixtures(dest_dir: Path | str) -> dict[str, Path]:
    """Write all three fixture bags into ``dest_dir`` and return their paths.

    Returns a dict keyed by ``"ros1"``, ``"ros2_sqlite"``, and ``"ros2_mcap"``.
    Each value is an existing on-disk path (a ``.bag`` file for ROS 1, a bag
    directory for the ROS 2 formats).
    """
    dest_dir = Path(dest_dir)
    return {
        "ros1": write_ros1_bag(dest_dir),
        "ros2_sqlite": write_ros2_sqlite_bag(dest_dir),
        "ros2_mcap": write_ros2_mcap_bag(dest_dir),
    }


def main(argv: list[str] | None = None) -> int:
    """Write the three bags to disk for manual ``bagq`` testing.

    ``DEST_DIR`` defaults to ``./fixtures`` (excluded by ``.gitignore`` — these
    binaries are version-coupled to ``rosbags`` and MUST NOT be committed).
    """
    argv = sys.argv[1:] if argv is None else argv
    dest_dir = Path(argv[0]) if argv else Path("fixtures")
    paths = make_all_fixtures(dest_dir)
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via `python -m tools.make_fixtures`
    raise SystemExit(main())
