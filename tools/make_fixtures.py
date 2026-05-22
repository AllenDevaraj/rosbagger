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

_MSGTYPE_TWIST = "geometry_msgs/msg/Twist"
_MSGTYPE_IMU = "sensor_msgs/msg/Imu"
_MSGTYPE_IMAGE = "sensor_msgs/msg/Image"

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
