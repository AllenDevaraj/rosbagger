"""The publish-fork sink — the deserialize→log twin of ``build_publish_sink``.

``build_rerun_sink(rec)`` returns a ``rerun_sink(item)`` closure that the desktop Replay panel
tees alongside the ROS publish sink (Phase 22, plan 22-03): each played ``item`` is published
to ROS (unchanged) AND, while the toggle is on, logged to Rerun here. The sink re-deserializes
the item independently (the same ``get_message`` → ``deserialize_message`` mechanics as
``build_publish_sink``) so the production publish path stays byte-for-byte untouched.

Every ``rclpy`` / ``rosidl_runtime_py`` / ``rerun`` touch is lazy inside the function body —
importing ``rosbagger_rerun.sink`` stays ROS-free AND Rerun-free.
"""

from __future__ import annotations


def build_rerun_sink(rec, *, t0_ns: int | None = None):
    """Build ``(rerun_sink, logged)`` that logs each replay ``item`` to the recording ``rec``.

    ``rerun_sink(item)`` deserializes ``item.cdr`` (lazy ``rclpy``/``rosidl``), stamps the
    ``bag_time`` timeline at ``(item.t_ns - t0)/1e9`` seconds (``t0`` captured from the first
    item, or passed in), and logs every ``(entity_path, archetype)`` from
    :func:`rosbagger_rerun.convert`. A failure on ONE item (bad CDR, unknown type, converter
    error) increments ``logged['errors']`` and is skipped — a single weird message never aborts
    the drive. ``logged['n']`` counts successfully-logged items.

    Verify against the installed rerun-sdk (>=0.31): ``rec.set_time(timeline, *, duration=)`` +
    ``rec.log(path, archetype)`` are the 0.32 names.
    """
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    from .converters import convert

    logged = {"n": 0, "errors": 0}
    state = {"t0": t0_ns}
    classes: dict[str, object] = {}

    def rerun_sink(item) -> None:
        if state["t0"] is None:
            state["t0"] = item.t_ns
        try:
            if item.msgtype not in classes:
                classes[item.msgtype] = get_message(item.msgtype)
            msg = deserialize_message(item.cdr, classes[item.msgtype])
            rec.set_time("bag_time", duration=(item.t_ns - state["t0"]) / 1e9)
            for path, arch in convert(msg, item.msgtype, item.topic):
                rec.log(path, arch)
            logged["n"] += 1
        except Exception:  # noqa: BLE001 - one bad item must not abort the live drive
            logged["errors"] += 1

    return rerun_sink, logged
