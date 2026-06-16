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


def test_pointcloud2_xyz_big_endian_and_truncated_buffer():
    """F5: big-endian unpack + a truncated trailing point stops cleanly (vectorized parity).

    The buffer claims 3 points but only carries 2 complete ones plus a 3rd point's x/y (no z):
    the vectorized reader must drop the incomplete point exactly as the old per-point loop did
    (``base + off + 4 > len: break``), and honor ``is_bigendian``.
    """
    full = struct.pack(">ffffff", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)  # 2 complete points (24 bytes)
    partial = struct.pack(">ff", 7.0, 8.0)  # a 3rd point's x,y only — no z (8 bytes)
    fields = [
        SimpleNamespace(name="x", offset=0),
        SimpleNamespace(name="y", offset=4),
        SimpleNamespace(name="z", offset=8),
    ]
    pc = SimpleNamespace(
        fields=fields,
        is_bigendian=True,
        point_step=12,
        width=3,  # claims 3 points; only 2 are complete
        height=1,
        data=full + partial,
    )
    pts = _pointcloud2_xyz(pc)
    assert len(pts) == 2  # the incomplete 3rd point is dropped
    assert pts[0] == pytest.approx((1.0, 2.0, 3.0))
    assert pts[1] == pytest.approx((4.0, 5.0, 6.0))


def test_pointcloud2_xyz_honors_point_step_padding():
    """F5: point_step padding (step > field span) is strided correctly by the structured view."""
    p0 = struct.pack("<fff", 1.5, 2.5, 3.5) + b"\x00\x00\x00\x00"  # 12 data + 4 pad = step 16
    p1 = struct.pack("<fff", -1.0, 0.0, 9.0) + b"\x00\x00\x00\x00"
    fields = [
        SimpleNamespace(name="x", offset=0),
        SimpleNamespace(name="y", offset=4),
        SimpleNamespace(name="z", offset=8),
    ]
    pc = SimpleNamespace(
        fields=fields, is_bigendian=False, point_step=16, width=2, height=1, data=p0 + p1
    )
    pts = _pointcloud2_xyz(pc)
    assert len(pts) == 2
    assert pts[0] == pytest.approx((1.5, 2.5, 3.5))
    assert pts[1] == pytest.approx((-1.0, 0.0, 9.0))


def test_pointcloud2_xyz_drops_non_finite_points():
    """NaN/inf points (organized RGBD/stereo clouds) are dropped, not fed into Points3D (audit qol).

    Invalid returns encoded as NaN otherwise pollute the viewer's auto-bounds/camera framing;
    _laserscan_xyz already filters, so the cloud path is brought to parity.
    """
    # point 0 finite; point 1 has a NaN x; point 2 finite -> only 0 and 2 survive.
    data = struct.pack("<fffffffff", 1.0, 2.0, 3.0, float("nan"), 5.0, 6.0, 7.0, 8.0, 9.0)
    fields = [
        SimpleNamespace(name="x", offset=0),
        SimpleNamespace(name="y", offset=4),
        SimpleNamespace(name="z", offset=8),
    ]
    pc = SimpleNamespace(
        fields=fields, is_bigendian=False, point_step=12, width=3, height=1, data=data
    )
    pts = _pointcloud2_xyz(pc)
    assert pts == [pytest.approx((1.0, 2.0, 3.0)), pytest.approx((7.0, 8.0, 9.0))]


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


def test_convert_image_unsupported_encoding_falls_back_to_generic():
    """An unsupported image encoding falls back to the generic view — the topic never vanishes.

    Regression for the audit bug: _image_array raises ValueError for encodings it does not
    handle (32FC1 float depth, rgba8, yuv422, bayer_*); _convert_image let it escape, the sink
    swallowed it, and the topic disappeared from the viewer. It now mirrors
    _convert_compressed_image's unknown-codec fallback.
    """
    msg = SimpleNamespace(
        height=1,
        width=1,
        encoding="32FC1",  # float depth — a common encoding _image_array does not handle
        data=struct.pack("<f", 1.5),
        header=SimpleNamespace(frame_id="cam"),
    )
    out = convert(msg, "sensor_msgs/msg/Image", "/depth")
    paths = [p for p, _ in out]
    assert out, "an unsupported encoding must still yield a viewable archetype"
    assert "cam" in paths  # the generic TextLog entity (fallback ran, no exception escaped)
    assert any(p.startswith("cam/") for p in paths)  # numeric-leaf Scalars (height/width)


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


# --------------------------------------------------------------- GPU offload (260530-ja4)


def test_prefer_gpu_injects_offload_env_when_nvidia_present(monkeypatch):
    """When an NVIDIA Vulkan ICD is present, _prefer_gpu sets the PRIME-offload env."""
    from rosbagger_rerun import session

    monkeypatch.setattr(session, "_nvidia_vulkan_present", lambda: True)
    env: dict[str, str] = {}
    session._prefer_gpu(env=env)
    assert env["__NV_PRIME_RENDER_OFFLOAD"] == "1"
    assert env["__VK_LAYER_NV_optimus"] == "NVIDIA_only"
    assert env["__GLX_VENDOR_LIBRARY_NAME"] == "nvidia"
    assert env["WGPU_POWER_PREF"] == "high"


def test_prefer_gpu_is_noop_without_nvidia(monkeypatch):
    """No NVIDIA ICD → _prefer_gpu touches nothing (no-op on non-NVIDIA / non-Linux)."""
    from rosbagger_rerun import session

    monkeypatch.setattr(session, "_nvidia_vulkan_present", lambda: False)
    env: dict[str, str] = {}
    session._prefer_gpu(env=env)
    assert env == {}


def test_prefer_gpu_setdefault_respects_user_env(monkeypatch):
    """A user's own exported value wins (setdefault, not overwrite)."""
    from rosbagger_rerun import session

    monkeypatch.setattr(session, "_nvidia_vulkan_present", lambda: True)
    env = {"WGPU_POWER_PREF": "low"}  # user already chose low-power
    session._prefer_gpu(env=env)
    assert env["WGPU_POWER_PREF"] == "low"  # not clobbered
    assert env["__NV_PRIME_RENDER_OFFLOAD"] == "1"  # the rest still added


# --------------------------------------------------- viewer lifecycle: close with GUI (260530-c3p)


def test_child_pids_finds_spawned_child():
    """``_child_pids`` returns this process's direct children (used to capture the viewer PID)."""
    import subprocess

    from rosbagger_rerun import session

    proc = subprocess.Popen(["sleep", "30"])  # noqa: S603,S607 - test fixture child
    try:
        assert proc.pid in session._child_pids()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_close_viewer_terminates_tracked_process():
    """``close_viewer`` SIGTERMs every tracked viewer PID and clears the registry (260530-c3p)."""
    import os
    import signal
    import time

    from rosbagger_rerun import session

    pid = os.fork()
    if pid == 0:  # child: become `sleep` so a SIGTERM cleanly ends it (no pytest state inherited)
        try:
            os.execvp("sleep", ["sleep", "60"])  # noqa: S607
        except Exception:
            os._exit(127)

    session._TRACKED_VIEWER_PIDS.add(pid)
    try:
        session.close_viewer()
        assert pid not in session._TRACKED_VIEWER_PIDS, "registry not cleared"
        gone = False
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                gone = True
                break
            try:  # reap if it is a zombie now (close_viewer's WNOHANG may not have caught it yet)
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    gone = True
                    break
            except ChildProcessError:
                gone = True
                break
            time.sleep(0.02)
        assert gone, "close_viewer did not terminate the tracked viewer child"
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass


def test_open_viewer_spawns_non_detached_and_tracks(monkeypatch):
    """open_viewer spawns the viewer NON-detached and tracks the new child PID (260530-c3p)."""
    import rerun as rr

    from rosbagger_rerun import session

    spawned: dict[str, object] = {}

    class _FakeRec:
        def __init__(self, app_id):
            self.app_id = app_id

        def spawn(self, **kwargs):
            spawned["spawn"] = kwargs

        def save(self, path):
            spawned["save"] = path

    monkeypatch.setattr(rr, "RecordingStream", _FakeRec)
    monkeypatch.setattr(session, "_prefer_gpu", lambda *a, **k: None)
    pid_calls = iter([[], [4242]])  # children before -> {}, after spawn -> {4242}
    monkeypatch.setattr(session, "_child_pids", lambda *a, **k: next(pid_calls))
    tracked: list[set] = []
    monkeypatch.setattr(session, "_track_viewers", lambda pids: tracked.append(set(pids)))
    # 23-01: stub the readiness gate so the test never opens a real socket / waits.
    ready_calls: list = []
    monkeypatch.setattr(session, "_wait_viewer_ready", lambda *a, **k: ready_calls.append((a, k)))

    rec = session.open_viewer()

    assert isinstance(rec, _FakeRec)
    assert spawned["spawn"]["detach_process"] is False  # the fix: non-detached
    assert spawned["spawn"]["port"] == session._VIEWER_GRPC_PORT  # spawn + probe share the port
    assert tracked == [{4242}]  # the new child PID was tracked for cleanup
    assert ready_calls, "open_viewer must gate on viewer readiness before returning (23-01)"


def test_open_viewer_save_mode_does_not_spawn_or_track(monkeypatch, tmp_path):
    """Save mode (tests) stays untouched — no spawn, no viewer tracking (260530-c3p)."""
    import rerun as rr

    from rosbagger_rerun import session

    spawned: dict[str, object] = {}

    class _FakeRec:
        def __init__(self, app_id):
            pass

        def spawn(self, **kwargs):
            spawned["spawn"] = kwargs

        def save(self, path):
            spawned["save"] = path

    monkeypatch.setattr(rr, "RecordingStream", _FakeRec)
    tracked: list = []
    monkeypatch.setattr(session, "_track_viewers", lambda pids: tracked.append(pids))
    # 23-01: save mode must NEVER hit the readiness gate (tests must not block on a socket).
    monkeypatch.setattr(
        session,
        "_wait_viewer_ready",
        lambda *a, **k: pytest.fail("readiness gate must be skipped in save mode"),
    )

    rec = session.open_viewer(save_path=str(tmp_path / "x.rrd"))

    assert isinstance(rec, _FakeRec)
    assert "save" in spawned and "spawn" not in spawned
    assert tracked == []


def test_wait_viewer_ready_is_bounded_and_never_raises():
    """Bounded against a closed port, never raises, still best-effort flushes (23-01)."""
    import time

    from rosbagger_rerun import session

    flushed: list[bool] = []
    rec = SimpleNamespace(flush=lambda *a, **k: flushed.append(True))
    # Port 1 is closed → connect refuses fast; the loop sleeps to the deadline then returns.
    start = time.monotonic()
    ready = session._wait_viewer_ready(rec, port=1, host="127.0.0.1", timeout=0.3)
    elapsed = time.monotonic() - start

    assert ready is False  # never became reachable
    assert elapsed < 1.5  # strictly bounded by the timeout (no hang)
    assert flushed == [True]  # best-effort flush still attempted


def test_wait_viewer_ready_flush_failure_is_suppressed():
    """A recording without a working ``flush`` must not make readiness raise (23-01)."""
    from rosbagger_rerun import session

    def _boom(*_a, **_k):
        raise RuntimeError("flush unavailable")

    rec = SimpleNamespace(flush=_boom)
    # Returns cleanly despite flush blowing up (suppressed); bounded by the tiny timeout.
    assert session._wait_viewer_ready(rec, port=1, timeout=0.1) is False
