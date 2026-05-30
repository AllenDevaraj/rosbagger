"""Offline unit tests for ``rosbagger-rerun``.

No ROS required. ``rerun`` is present via the dev dependency group, so these run in the
standard offline lane (they are NOT ``importorskip("rclpy")``). The package import itself
stays rerun-free (see ``tests/test_offline_guard.py``); these tests exercise the public
surface + (in 22-02) the pure converter helpers + the ``convert()`` dispatch.
"""

from __future__ import annotations

import math
import struct
from types import SimpleNamespace

import pytest

import rosbagger_rerun
from rosbagger_rerun.converters import (
    _entity_path,
    _image_array,
    _laserscan_xyz,
    _numeric_leaves,
    _pointcloud2_xyz,
    convert,
)


def test_import_rosbagger_rerun_is_clean():
    """The package exposes its public surface (22-01 scaffold + 22-02 sink/convert)."""
    assert hasattr(rosbagger_rerun, "rerun_available")
    assert hasattr(rosbagger_rerun, "open_viewer")
    assert hasattr(rosbagger_rerun, "convert")
    assert hasattr(rosbagger_rerun, "build_rerun_sink")


def test_rerun_available_returns_bool():
    """``rerun_available()`` returns a bool and never raises (environment-independent).

    Asserts the PROBE CONTRACT, not the value: it is ``True`` in the dev venv (rerun-sdk in
    the dev group) and ``False`` where rerun is absent — either way it must be a plain bool.
    """
    result = rosbagger_rerun.rerun_available()
    assert isinstance(result, bool)


# --------------------------------------------------------------- pure converter helpers


def test_laserscan_xyz_drops_inf_and_out_of_range():
    """polar→cartesian with finite + [range_min, range_max] filtering (angle_min + i*increment)."""
    scan = SimpleNamespace(
        angle_min=0.0,
        angle_increment=math.pi / 2,
        range_min=0.1,
        range_max=10.0,
        ranges=[1.0, float("inf"), 2.0],  # i=0 keep, i=1 inf drop, i=2 keep at angle=pi
    )
    pts = _laserscan_xyz(scan)
    assert len(pts) == 2
    assert pts[0] == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)
    assert pts[1] == pytest.approx((-2.0, 0.0, 0.0), abs=1e-9)


def test_pointcloud2_xyz_unpacks_float32_points():
    """Two little-endian float32 xyz points unpacked at their field offsets."""
    data = struct.pack("<ffffff", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    fields = [
        SimpleNamespace(name="x", offset=0),
        SimpleNamespace(name="y", offset=4),
        SimpleNamespace(name="z", offset=8),
    ]
    pc = SimpleNamespace(
        fields=fields, is_bigendian=False, point_step=12, width=2, height=1, data=data
    )
    pts = _pointcloud2_xyz(pc)
    assert len(pts) == 2
    assert pts[0] == pytest.approx((1.0, 2.0, 3.0))
    assert pts[1] == pytest.approx((4.0, 5.0, 6.0))


def test_image_array_bgr_reversed_and_depth_kind():
    """rgb8 as-is, bgr8 reversed to rgb, 16UC1 → depth kind."""
    rgb = SimpleNamespace(height=1, width=1, encoding="rgb8", data=bytes([10, 20, 30]))
    arr, kind = _image_array(rgb)
    assert kind == "rgb" and list(arr[0, 0]) == [10, 20, 30]

    bgr = SimpleNamespace(height=1, width=1, encoding="bgr8", data=bytes([10, 20, 30]))
    arr2, _ = _image_array(bgr)
    assert list(arr2[0, 0]) == [30, 20, 10]  # reversed to rgb

    depth = SimpleNamespace(height=1, width=1, encoding="16UC1", data=struct.pack("<H", 500))
    arr3, kind3 = _image_array(depth)
    assert kind3 == "depth" and int(arr3[0, 0]) == 500


def test_numeric_leaves_flattens_and_skips_non_numeric():
    """Nested numeric walk: floats kept, bool/str skipped, array → length only."""
    msg = SimpleNamespace(a=1, b=SimpleNamespace(c=2.5, d="skip"), arr=[1, 2, 3], flag=True)
    leaves = _numeric_leaves(msg)
    assert leaves["a"] == 1.0
    assert leaves["b.c"] == 2.5
    assert leaves["arr.len"] == 3.0
    assert "b.d" not in leaves  # string skipped
    assert "flag" not in leaves  # bool skipped


def test_entity_path_prefers_frame_id_else_topic():
    with_frame = SimpleNamespace(header=SimpleNamespace(frame_id="laser"))
    assert _entity_path(with_frame, "/scan") == "laser"
    no_frame = SimpleNamespace(header=SimpleNamespace(frame_id=""))
    assert _entity_path(no_frame, "/camera/color/image_raw") == "camera/color/image_raw"


# --------------------------------------------------------------- convert() dispatch (needs rerun)


def test_convert_laserscan_returns_points3d_at_frame_path():
    import rerun as rr

    scan = SimpleNamespace(
        angle_min=0.0,
        angle_increment=1.0,
        range_min=0.0,
        range_max=10.0,
        ranges=[1.0],
        header=SimpleNamespace(frame_id="laser"),
    )
    res = convert(scan, "sensor_msgs/msg/LaserScan", "/scan")
    assert len(res) == 1
    path, arch = res[0]
    assert path == "laser"
    assert isinstance(arch, rr.Points3D)


def test_convert_unknown_falls_back_to_textlog():
    import rerun as rr

    weird = SimpleNamespace(x=1.0, header=SimpleNamespace(frame_id=""))
    res = convert(weird, "pkg/msg/Weird", "/weird")
    # generic fallback: a Scalars per numeric leaf + a trailing TextLog, never empty
    assert len(res) >= 1
    last_path, last_arch = res[-1]
    assert isinstance(last_arch, rr.TextLog)
    assert last_path == "weird"  # empty frame_id → topic
