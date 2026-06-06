"""Pure ROS-free / Qt-free builder for a minimal RViz 2 ``.rviz`` config (23-03).

The desktop "Open in RViz" button generates a config from the bag's ``(topic, msgtype)`` list and
launches ``rviz2 -d <cfg>``; RViz then subscribes to the live topics the ``Replayer`` already
publishes (no second publish path). This module is PURE — stdlib + ``yaml`` only, NO ROS, NO Qt — so
the msgtype→display mapping is asserted offline. The launch + process lifecycle lives in
``rviz_session.py``; the panel wiring (auto-fidelity, off-thread topic read) in ``replay_panel.py``.
"""

from __future__ import annotations

import yaml

# msgtype → rviz_default_plugins display class. Topics whose msgtype is not here are skipped (still
# published to ROS; no RViz auto-display). Both Image encodings use the Image display.
_DISPLAY_FOR: dict[str, str] = {
    "sensor_msgs/msg/Image": "rviz_default_plugins/Image",
    "sensor_msgs/msg/CompressedImage": "rviz_default_plugins/Image",
    "sensor_msgs/msg/PointCloud2": "rviz_default_plugins/PointCloud2",
    "sensor_msgs/msg/LaserScan": "rviz_default_plugins/LaserScan",
    "tf2_msgs/msg/TFMessage": "rviz_default_plugins/TF",
    "nav_msgs/msg/OccupancyGrid": "rviz_default_plugins/Map",
    "visualization_msgs/msg/Marker": "rviz_default_plugins/Marker",
    "visualization_msgs/msg/MarkerArray": "rviz_default_plugins/MarkerArray",
    "nav_msgs/msg/Odometry": "rviz_default_plugins/Odometry",
    "nav_msgs/msg/Path": "rviz_default_plugins/Path",
}

# Frames preferred as the RViz Fixed Frame, in order, when a TF tree is sampled.
_PREFERRED_FRAMES = ("map", "odom", "base_link")


def _topic_display(name: str, cls: str, topic: str) -> dict:
    """A topic-bound RViz display dict; QoS matches the publisher (RELIABLE/VOLATILE depth-10)."""
    return {
        "Class": cls,
        "Name": name,
        "Enabled": True,
        "Topic": {
            "Value": topic,
            "Depth": 10,
            "History Policy": "Keep Last",
            "Durability Policy": "Volatile",
            "Reliability Policy": "Reliable",
        },
    }


def pick_fixed_frame(topics, tf_frames=None) -> str:
    """Choose the RViz Fixed Frame: prefer map>odom>base_link, else first frame, else 'map'.

    ``tf_frames`` is optional frame ids sampled from ``/tf``. With none (the default) it returns
    ``'map'`` (the user can change it live in RViz). ``topics`` is accepted (unused) so callers can
    pass the same list they hand ``build_rviz_config``.
    """
    frames = list(tf_frames or [])
    if not frames:
        return "map"
    for pref in _PREFERRED_FRAMES:
        if pref in frames:
            return pref
    return frames[0]


def build_rviz_config(topics, fixed_frame: str = "map") -> str:
    """Build a minimal ``.rviz`` YAML config from ``[(topic, msgtype), ...]`` + a fixed frame.

    Always includes a Grid + a TF display; adds one topic-bound display per topic whose msgtype is
    in :data:`_DISPLAY_FOR` (unknown msgtypes skipped; de-duped by ``(class, topic)``; a ``/tf``
    topic adds no 2nd TF display). Returns a ``yaml.safe_dump`` string suitable for ``rviz2 -d``.
    """
    displays: list[dict] = [
        {"Class": "rviz_default_plugins/Grid", "Name": "Grid", "Enabled": True},
        {"Class": "rviz_default_plugins/TF", "Name": "TF", "Enabled": True},
    ]
    seen: set[tuple[str, str]] = set()
    for topic, msgtype in topics:
        cls = _DISPLAY_FOR.get(msgtype)
        if cls is None or cls == "rviz_default_plugins/TF":
            continue  # unknown → skip; /tf already covered by the standalone TF display
        key = (cls, topic)
        if key in seen:
            continue
        seen.add(key)
        displays.append(_topic_display(topic, cls, topic))
    config = {
        "Panels": [{"Class": "rviz_common/Displays", "Name": "Displays"}],
        "Visualization Manager": {
            "Class": "",
            "Global Options": {"Fixed Frame": fixed_frame, "Frame Rate": 30},
            "Displays": displays,
            "Tools": [{"Class": "rviz_default_plugins/MoveCamera"}],
            "Views": {"Current": {"Class": "rviz_default_plugins/Orbit", "Name": "Current View"}},
        },
    }
    return yaml.safe_dump(config, sort_keys=False)
