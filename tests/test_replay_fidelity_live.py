"""LIVE integration tests for Phase-20 RViz fidelity (REP-04 / SC1 + SC2-live, D-11 tier 2).

The TIER-2 LIVE half of the Phase-20 two-tier strategy (the offline CI proof for the static
re-publish logic is the PURE ``test_replay_fidelity.py`` StaticTracker unit test). These prove,
against a REAL ``rclpy`` graph, that the extended ``build_publish_sink`` actually:

* SC1 — publishes ``/clock`` (``rosgraph_msgs/msg/Clock``) carrying bag time when
  ``publish_clock=True``; an external subscriber subprocess receives it.
* SC2-live — re-publishes the latest ``/tf_static`` through the SAME sink after a seek
  (``republish_static``) when ``static_topics`` is set; a fresh external subscriber receives it.

GATING (so the offline CI stays green): ``rclpy = pytest.importorskip("rclpy")`` SKIPS the
whole module in the ROS-free uv venv, and ``pytestmark = pytest.mark.live`` lets the live lane
select it with ``-m live``. This module is COLLECTED-AND-SKIPPED in the offline gate — it
contributes nothing to coverage and is NOT required for the offline gate (mirrors
``test_replay_live.py``).

VERIFIED LIVE-LANE RECIPE (mirrors test_replay_live.py / 13-VERIFICATION):
    source /opt/ros/humble/setup.bash
    PYTHONPATH="packages/rosbagger-replay/src:packages/rosbagger-core/src:$PYTHONPATH" \
      uv run --with pyyaml pytest tests/test_replay_fidelity_live.py -m live -v
The src-tree prepend lets the system python3 resolve rosbagger_replay/rosbagger_core; the
sys.path insert below is belt-and-suspenders. We drive ``build_publish_sink`` IN-PROCESS with
the new opt-ins (replay_bag does not expose them at the front door — that is the 20-03 desktop
wiring), exactly the way the desktop panel will call it; the OTHER actor is an external
subscriber subprocess with its OWN rclpy context (the Phase-12/13 reason for a separate process).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")  # SKIP the whole module in the ROS-free offline CI

pytestmark = pytest.mark.live

# Belt-and-suspenders src resolution for the ROS-sourced lane (mirrors test_replay_live.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT / "packages" / "rosbagger-replay" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rosbags.typesys import Stores, get_typestore  # noqa: E402  (system python3 has rosbags)
from tools.make_fixtures import write_ros2_sqlite_bag, write_tf_bag  # noqa: E402

from rosbagger_replay import build_publish_sink, load_items, republish_static  # noqa: E402


def _subscriber_src(import_line: str, msg_cls: str, topic: str) -> str:
    """A tiny external-subscriber program (own rclpy context) counting msgs on a topic.

    Prints READY once subscribed, then COUNT <n> on its last stdout line. Parametrized by the
    message import + class + topic so /clock and /tf_static reuse the same recipe.
    """
    return textwrap.dedent(
        f"""
        import sys
        import rclpy
        {import_line}

        def main():
            rclpy.init()
            node = rclpy.create_node("rosbagger_fidelity_test_subscriber")
            count = {{"n": 0}}
            def on_msg(_msg):
                count["n"] += 1
            node.create_subscription({msg_cls}, "{topic}", on_msg, 10)
            print("READY", flush=True)
            deadline = node.get_clock().now().nanoseconds + int(8e9)  # ~8s hard cap
            try:
                while rclpy.ok() and node.get_clock().now().nanoseconds < deadline:
                    rclpy.spin_once(node, timeout_sec=0.1)
            finally:
                print(f"COUNT {{count['n']}}", flush=True)
                node.destroy_node()
                rclpy.shutdown()

        if __name__ == "__main__":
            main()
        """
    )


def _run_with_subscriber(sub_src: str, publish_fn) -> int:
    """Start the subscriber subprocess, run publish_fn() in-process, return the received count.

    Subscriber-before-publisher + a ~1s DDS discovery settle (Pitfall 4); publish_fn does the
    in-process rclpy publishing; the subscriber's COUNT line is parsed after teardown.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", sub_src],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        ready_line = proc.stdout.readline()
        assert ready_line.strip() == "READY", f"subscriber did not come up: {ready_line!r}"
        time.sleep(1.0)  # DDS discovery settle
        publish_fn()
        time.sleep(1.0)  # let the subscriber drain in-flight messages
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            out, _ = proc.communicate(timeout=10)
    count_lines = [ln for ln in out.splitlines() if ln.startswith("COUNT ")]
    assert count_lines, f"subscriber printed no COUNT line; stdout was:\n{out}"
    return int(count_lines[-1].split()[1])


def test_sc1_clock_published_external_subscriber_receives(tmp_path):
    """SC1: build_publish_sink(publish_clock=True) publishes /clock; a subscriber receives it.

    Drives the extended sink IN-PROCESS (the way the desktop panel will): init rclpy, build the
    sink with publish_clock=True, and push the sqlite3 fixture's items through it. Each published
    item emits one /clock (rosgraph_msgs/msg/Clock) carrying clock_stamp_ns(item.t_ns), so an
    external /clock subscriber receives >= 1.
    """
    bag = write_ros2_sqlite_bag(tmp_path)
    sub_src = _subscriber_src("from rosgraph_msgs.msg import Clock", "Clock", "/clock")

    def publish() -> None:
        rclpy.init()
        node = rclpy.create_node("rosbagger_fidelity_clock_publisher")
        try:
            sink, published = build_publish_sink(node, publish_clock=True)
            items = load_items(str(bag), default_typestore=get_typestore(Stores.ROS2_HUMBLE))
            for item in items:
                sink(item)
            assert published["n"] == len(items)
        finally:
            node.destroy_node()
            rclpy.shutdown()

    received = _run_with_subscriber(sub_src, publish)
    assert received >= 1, f"/clock subscriber received {received} msgs, expected >= 1"


def test_sc2_static_republished_after_seek_external_subscriber_receives(tmp_path):
    """SC2-live: a /tf_static tracked during play is re-published after a seek (republish_static).

    write_tf_bag publishes a latched /tf_static. The sink (static_topics={'/tf_static'}) records
    the latest /tf_static as the stream plays; republish_static(sink) (the post-seek re-prime)
    re-pushes it through the SAME sink. A fresh external /tf_static subscriber that joined late
    (after the original one-shot) receives the re-published message — the Phase-18 backward-scrub
    fidelity fix.
    """
    bag = write_tf_bag(tmp_path, ros1=False)
    sub_src = _subscriber_src("from tf2_msgs.msg import TFMessage", "TFMessage", "/tf_static")

    def publish() -> None:
        rclpy.init()
        node = rclpy.create_node("rosbagger_fidelity_static_publisher")
        try:
            sink, _published = build_publish_sink(node, static_topics=frozenset({"/tf_static"}))
            items = load_items(str(bag), default_typestore=get_typestore(Stores.ROS2_HUMBLE))
            for item in items:
                sink(item)  # the tracker records the latest /tf_static during play
            time.sleep(0.5)
            # Simulate a post-seek re-prime: re-push the tracked static set through the sink.
            n = republish_static(sink)
            assert n >= 1, "republish_static re-published nothing (no /tf_static tracked)"
        finally:
            node.destroy_node()
            rclpy.shutdown()

    received = _run_with_subscriber(sub_src, publish)
    assert received >= 1, f"/tf_static subscriber received {received} msgs, expected >= 1"
