"""ROS message → Rerun archetype converters.

Two layers, deliberately split for testability:

1. **Pure helpers** (``_laserscan_xyz`` / ``_pointcloud2_xyz`` / ``_image_array`` /
   ``_numeric_leaves`` / ``_entity_path``) — no ``rerun``, no ROS. The geometry/encoding
   math is asserted EXACTLY offline with duck-typed inputs.
2. **Rerun wrappers** (``_convert_*``) — each does a LAZY ``import rerun`` inside the body and
   wraps a pure helper in the right archetype. ``convert(msg, msgtype, topic)`` dispatches
   msgtype → wrapper, falling back to a generic ``Scalars``/``TextLog`` view so EVERY message
   yields at least one ``(entity_path, archetype)`` (no topic is ever invisible).

Module top imports only stdlib (``math`` / ``struct``); ``rerun`` and ``numpy`` are lazy, so
``import rosbagger_rerun`` stays Rerun-free (offline invariant — tests/test_offline_guard.py).

Archetype/timeline names verified against rerun-sdk 0.32.2: ``Image`` / ``DepthImage`` /
``EncodedImage(contents=, media_type=)`` / ``Points3D`` / ``Transform3D`` / ``Quaternion(xyzw=)`` /
``Scalars`` / ``TextLog``.
"""

from __future__ import annotations

import contextlib
import math
import struct

# --------------------------------------------------------------- pure helpers (no rerun/ROS)


def _entity_path(msg, topic: str) -> str:
    """Entity path = the message's ``header.frame_id`` (no leading ``/``) else the topic.

    Frame-keyed paths give spatial coherence when TF positions the frame; with no TF (and no
    ``header``) the data still logs flat under the topic name and is fully viewable.
    """
    header = getattr(msg, "header", None)
    frame_id = getattr(header, "frame_id", "") if header is not None else ""
    if frame_id:
        return frame_id.lstrip("/")
    return topic.lstrip("/")


def _laserscan_xyz(msg) -> list[tuple[float, float, float]]:
    """LaserScan → list of (x, y, z=0) points; drops inf/nan and out-of-[range_min, range_max]."""
    out: list[tuple[float, float, float]] = []
    for i, r in enumerate(msg.ranges):
        if not math.isfinite(r) or not (msg.range_min <= r <= msg.range_max):
            continue
        angle = msg.angle_min + i * msg.angle_increment
        out.append((r * math.cos(angle), r * math.sin(angle), 0.0))
    return out


def _pointcloud2_xyz(msg) -> list[tuple[float, float, float]]:
    """PointCloud2 → list of (x, y, z) by unpacking float32 x/y/z at their field offsets.

    Assumes float32 x/y/z (the standard layout). Honors ``is_bigendian`` and ``point_step``;
    bounded by ``width*height`` and a data-length guard (a truncated buffer stops cleanly).
    """
    offsets = {f.name: f.offset for f in msg.fields if f.name in ("x", "y", "z")}
    if not all(k in offsets for k in ("x", "y", "z")):
        return []
    endian = ">" if getattr(msg, "is_bigendian", False) else "<"
    data = bytes(msg.data)
    step = msg.point_step
    n = msg.width * msg.height
    ox, oy, oz = offsets["x"], offsets["y"], offsets["z"]
    out: list[tuple[float, float, float]] = []
    for i in range(n):
        base = i * step
        if base + oz + 4 > len(data):
            break
        x = struct.unpack_from(endian + "f", data, base + ox)[0]
        y = struct.unpack_from(endian + "f", data, base + oy)[0]
        z = struct.unpack_from(endian + "f", data, base + oz)[0]
        out.append((x, y, z))
    return out


def _image_array(msg):
    """Image → (numpy ndarray, kind) where kind is 'rgb' | 'mono' | 'depth'.

    rgb8 as-is; bgr8 reversed to rgb (contiguous); mono8/8UC1 → 2D uint8; 16UC1/mono16 → 2D
    uint16 depth. Raises ValueError for an unknown encoding (the generic fallback catches it).
    """
    import numpy as np

    h, w = msg.height, msg.width
    enc = msg.encoding
    buf = bytes(msg.data)
    if enc in ("rgb8", "bgr8"):
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
        if enc == "bgr8":
            arr = np.ascontiguousarray(arr[..., ::-1])
        return arr, "rgb"
    if enc in ("mono8", "8UC1"):
        return np.frombuffer(buf, dtype=np.uint8).reshape(h, w), "mono"
    if enc in ("16UC1", "mono16"):
        return np.frombuffer(buf, dtype=np.uint16).reshape(h, w), "depth"
    raise ValueError(f"unsupported image encoding: {enc}")


def _numeric_leaves(msg, prefix: str = "", _depth: int = 0) -> dict[str, float]:
    """Bounded-depth walk collecting numeric scalar leaves → {dotted_name: float}.

    Recurses up to depth 4 over a message's fields (rosidl ``get_fields_and_field_types`` when
    present, else ``vars``/``dir``). int/float leaves become floats; bool/str are skipped;
    sequences record only their LENGTH (``name.len``), never their contents (no array explosion).
    """
    out: dict[str, float] = {}
    if _depth > 4:
        return out
    getter = getattr(msg, "get_fields_and_field_types", None)
    if callable(getter):
        names = list(getter().keys())
    elif hasattr(msg, "__dict__"):
        names = list(vars(msg).keys())
    else:
        names = [n for n in dir(msg) if not n.startswith("_")]
    for name in names:
        try:
            val = getattr(msg, name)
        except Exception:  # noqa: BLE001 - a property that raises is simply skipped
            continue
        key = f"{prefix}.{name}" if prefix else name
        if isinstance(val, bool) or callable(val):
            continue
        if isinstance(val, (int, float)):
            out[key] = float(val)
        elif isinstance(val, (str, bytes)):
            continue
        elif isinstance(val, (list, tuple)) or hasattr(val, "__len__"):
            with contextlib.suppress(TypeError):
                out[f"{key}.len"] = float(len(val))
        elif hasattr(val, "get_fields_and_field_types") or hasattr(val, "__dict__"):
            out.update(_numeric_leaves(val, key, _depth + 1))
    return out


# --------------------------------------------------------------- rerun wrappers (lazy import)


def _convert_laserscan(msg, topic):
    import rerun as rr

    return [(_entity_path(msg, topic), rr.Points3D(_laserscan_xyz(msg)))]


def _convert_pointcloud2(msg, topic):
    import rerun as rr

    return [(_entity_path(msg, topic), rr.Points3D(_pointcloud2_xyz(msg)))]


def _convert_image(msg, topic):
    import rerun as rr

    arr, kind = _image_array(msg)
    arch = rr.DepthImage(arr) if kind == "depth" else rr.Image(arr)
    return [(_entity_path(msg, topic), arch)]


def _convert_compressed_image(msg, topic):
    import rerun as rr

    fmt = (getattr(msg, "format", "") or "").lower()
    if "png" in fmt:
        media = "image/png"
    elif "jpeg" in fmt or "jpg" in fmt:
        media = "image/jpeg"
    else:
        return _convert_generic(msg, topic)  # unknown codec — don't guess
    return [(_entity_path(msg, topic), rr.EncodedImage(contents=bytes(msg.data), media_type=media))]


def _convert_tf(msg, topic):
    import rerun as rr

    out = []
    for t in msg.transforms:
        tr = t.transform.translation
        rot = t.transform.rotation
        out.append(
            (
                t.child_frame_id.lstrip("/"),
                rr.Transform3D(
                    translation=[tr.x, tr.y, tr.z],
                    rotation=rr.Quaternion(xyzw=[rot.x, rot.y, rot.z, rot.w]),
                ),
            )
        )
    return out


def _convert_generic(msg, topic):
    """Fallback: numeric leaves → ``Scalars`` time series + one ``TextLog`` (always non-empty)."""
    import rerun as rr

    path = _entity_path(msg, topic)
    out = [(f"{path}/{k}", rr.Scalars(v)) for k, v in _numeric_leaves(msg).items()]
    out.append((path, rr.TextLog(type(msg).__name__)))
    return out


_DISPATCH = {
    "sensor_msgs/msg/Image": _convert_image,
    "sensor_msgs/msg/CompressedImage": _convert_compressed_image,
    "sensor_msgs/msg/LaserScan": _convert_laserscan,
    "sensor_msgs/msg/PointCloud2": _convert_pointcloud2,
    "tf2_msgs/msg/TFMessage": _convert_tf,
}


def convert(msg, msgtype: str, topic: str):
    """Dispatch a deserialized message to its rich converter, else the generic fallback.

    Returns a ``list[(entity_path, rerun_archetype)]`` — the rich converters return one tuple
    (TF returns one per transform); the generic fallback returns one ``Scalars`` per numeric
    leaf plus a trailing ``TextLog``. Never returns an empty list.
    """
    return _DISPATCH.get(msgtype, _convert_generic)(msg, topic)
