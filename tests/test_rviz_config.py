"""Offline unit tests for the pure RViz config builder (23-03).

No ROS, no Qt, no qtbot — ``rosbagger_desktop.rviz_config`` is stdlib + yaml only. Asserts the
msgtype→display mapping, the always-present Grid+TF, unknown-msgtype skipping, de-dup, the Fixed
Frame, and the ``pick_fixed_frame`` heuristic.
"""

from __future__ import annotations

import yaml

from rosbagger_desktop.rviz_config import build_rviz_config, pick_fixed_frame


def _displays(cfg_str: str) -> list[dict]:
    return yaml.safe_load(cfg_str)["Visualization Manager"]["Displays"]


def test_each_supported_msgtype_maps_to_its_display():
    topics = [
        ("/camera/image_raw", "sensor_msgs/msg/Image"),
        ("/scan", "sensor_msgs/msg/LaserScan"),
        ("/points", "sensor_msgs/msg/PointCloud2"),
        ("/map", "nav_msgs/msg/OccupancyGrid"),
        ("/markers", "visualization_msgs/msg/MarkerArray"),
        ("/odom", "nav_msgs/msg/Odometry"),
        ("/plan", "nav_msgs/msg/Path"),
    ]
    by_class = {d["Class"]: d for d in _displays(build_rviz_config(topics, "map"))}
    assert "rviz_default_plugins/Image" in by_class
    assert by_class["rviz_default_plugins/Image"]["Topic"]["Value"] == "/camera/image_raw"
    # QoS matches the publisher (RELIABLE/VOLATILE depth-10) so RViz actually receives the data.
    assert by_class["rviz_default_plugins/Image"]["Topic"]["Reliability Policy"] == "Reliable"
    assert by_class["rviz_default_plugins/Image"]["Topic"]["Durability Policy"] == "Volatile"
    for cls in (
        "rviz_default_plugins/LaserScan",
        "rviz_default_plugins/PointCloud2",
        "rviz_default_plugins/Map",
        "rviz_default_plugins/MarkerArray",
        "rviz_default_plugins/Odometry",
        "rviz_default_plugins/Path",
    ):
        assert cls in by_class, cls


def test_compressed_image_maps_to_image_display():
    cfg = build_rviz_config([("/cam/compressed", "sensor_msgs/msg/CompressedImage")], "map")
    classes = [d["Class"] for d in _displays(cfg)]
    assert "rviz_default_plugins/Image" in classes


def test_grid_and_tf_always_present_even_empty():
    classes = [d["Class"] for d in _displays(build_rviz_config([], "map"))]
    assert "rviz_default_plugins/Grid" in classes
    assert "rviz_default_plugins/TF" in classes


def test_unknown_msgtype_skipped_but_grid_tf_remain():
    displays = _displays(build_rviz_config([("/chatter", "std_msgs/msg/String")], "map"))
    classes = [d["Class"] for d in displays]
    assert "rviz_default_plugins/Grid" in classes
    assert "rviz_default_plugins/TF" in classes
    assert all(d.get("Topic", {}).get("Value") != "/chatter" for d in displays)


def test_tf_topic_does_not_duplicate_tf_display():
    displays = _displays(build_rviz_config([("/tf", "tf2_msgs/msg/TFMessage")], "map"))
    tf_count = sum(1 for d in displays if d["Class"] == "rviz_default_plugins/TF")
    assert tf_count == 1


def test_fixed_frame_set_and_roundtrips():
    cfg = yaml.safe_load(build_rviz_config([], "odom"))
    assert cfg["Visualization Manager"]["Global Options"]["Fixed Frame"] == "odom"


def test_duplicate_topics_deduped():
    topics = [("/scan", "sensor_msgs/msg/LaserScan"), ("/scan", "sensor_msgs/msg/LaserScan")]
    displays = _displays(build_rviz_config(topics, "map"))
    scans = [d for d in displays if d["Class"].endswith("LaserScan")]
    assert len(scans) == 1


def test_pick_fixed_frame_prefers_map_then_odom_then_baselink():
    assert pick_fixed_frame([], ["base_link", "odom", "map", "laser"]) == "map"
    assert pick_fixed_frame([], ["base_link", "odom", "laser"]) == "odom"
    assert pick_fixed_frame([], ["base_link", "laser"]) == "base_link"
    assert pick_fixed_frame([], ["laser", "camera"]) == "laser"
    assert pick_fixed_frame([], None) == "map"
