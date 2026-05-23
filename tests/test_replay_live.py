"""LIVE integration test for rosbagger-replay (REP-01 / SC1, D-11 tier 2).

This is the TIER-2 LIVE half of the two-tier strategy (D-11): it proves SC1 — the
PRODUCTION ``replay_bag()`` front door publishes a bag's messages onto live ROS 2 topics
that a real ``rclpy`` subscriber RECEIVES. Unlike the offline ``test_replay_unit.py`` (which
mocks ROS / drives the pure scheduler), this test needs a REAL ``rclpy`` graph, so it runs
ONLY in the ROS-sourced lane and is SKIPPED in the offline CI.

GATING (so the offline CI stays green):
* ``rclpy = pytest.importorskip("rclpy")`` at the very top SKIPS the whole module in the
  ROS-free uv venv (``PYTHONPATH="" uv run pytest`` hides the host's ROS → import fails →
  skip). The offline gate therefore sees this file COLLECTED-AND-SKIPPED, contributing
  nothing to coverage.
* ``pytestmark = pytest.mark.live`` (the marker registered in pyproject) so the live lane
  can select it with ``-m live`` and the offline run shows no unknown-marker warning.

VERIFIED LIVE-LANE RECIPE (mirrors 12-VERIFICATION, swapping the test file):
    source /opt/ros/humble/setup.bash
    PYTHONPATH="packages/rosbagger-replay/src:packages/rosbagger-core/src:$PYTHONPATH" \
      python3 -m pytest tests/test_replay_live.py -m live -v
The src-tree prepend on PYTHONPATH is what lets the system ``python3`` resolve
``rosbagger_replay`` / ``rosbagger_core``; the ``sys.path`` insert below is belt-and-
suspenders so the file also resolves if only the repo root is on the path. THE ORCHESTRATOR
MUST ACTUALLY RUN THIS (Phase-12 W4) — a collected-and-skipped result is insufficient for
SC1 sign-off.

THE COMMITTED APPROACH (BLOCKER-1 + W2 — Phase-12 pattern, INVERTED): the SC1 test exercises
the PRODUCTION ``replay_bag()`` front door as the PUBLISHER, running IN-PROCESS — it owns
``rclpy.init()``/``shutdown()``, builds the per-topic publisher dict, wires the sink, and
handles seek + finally-cleanup, exactly the code the CLI and the Phase-14 GUI call. The
OTHER actor is an EXTERNAL SUBSCRIBER SUBPROCESS — a tiny ``rclpy`` script that inits its
OWN context, subscribes to ``/imu``, counts received messages, and reports the count back
on stdout. The separate PROCESS gives the subscriber its own ``rclpy`` context, so the
in-process ``replay_bag()`` ``rclpy.init()`` does NOT clash (the Phase-12 reason for an
external actor). We do NOT re-build a sink or drive ``load_items`` / ``Replayer`` in the
test — the publish path under test is the shipped ``replay_bag()``, nothing else (a bug in
its real wiring would therefore fail SC1).

LATCHED-TOPIC CAVEAT (deferred): the fixture publishes NONE latched (Open Q2); per-topic
QoS / transient-local replay nuance is a deferred Phase-13 enhancement, so the subscriber
uses the same sane default QoS (depth-10 RELIABLE VOLATILE) as the publisher.
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

# Belt-and-suspenders src resolution for the ROS-sourced lane (mirrors test_record_live.py):
# the verified recipe prepends the package src trees on PYTHONPATH; this also covers a lane
# that only has the repo root on the path. Scoped to this file, touching neither conftest
# nor the root pyproject. Harmless when the trees are already importable (the `if` guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT / "packages" / "rosbagger-replay" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rosbags.typesys import Stores, get_typestore  # noqa: E402  (system python3 has rosbags)
from tools.make_fixtures import write_ros2_sqlite_bag  # noqa: E402

from rosbagger_replay import replay_bag  # noqa: E402  (the PRODUCTION publish front door)

TOPIC = "/imu"  # the fixture publishes 3 /imu messages (sensor_msgs/msg/Imu)
MSG_TYPE = "sensor_msgs/msg/Imu"
N_IMU = 3  # write_ros2_sqlite_bag writes _N_MSGS=3 per topic; assert the subscriber gets all 3


# The subscriber program, run in a SEPARATE process so it has its OWN rclpy context (no
# double-init clash with the in-process replay_bag()) and is a genuinely EXTERNAL graph
# participant. It subscribes to /imu, counts received messages for a bounded window, then
# prints the final count on the LAST stdout line. Kept tiny + dependency-light (only rclpy +
# sensor_msgs, both in the sourced env). The subscriber comes up FIRST (the fixture gives it
# a discovery settle) so the publisher's messages are not missed (Pitfall 4: subscriber-
# before-publisher + DDS discovery; default QoS depth-10 RELIABLE VOLATILE matches the sink).
_SUBSCRIBER_SRC = textwrap.dedent(
    """
    import sys
    import rclpy
    from sensor_msgs.msg import Imu

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_live_test_subscriber")
        count = {"n": 0}
        def on_msg(_msg):
            count["n"] += 1
        node.create_subscription(Imu, "/imu", on_msg, 10)  # sane default QoS (matches sink)
        # Print READY once subscribed so the parent knows discovery can begin.
        print("READY", flush=True)
        # Spin for a bounded window long enough for the parent to settle + replay the 9-msg
        # fixture at --rate 50, then report the count and exit. The parent kills us on teardown.
        deadline = node.get_clock().now().nanoseconds + int(8e9)  # ~8s hard cap
        try:
            while rclpy.ok() and node.get_clock().now().nanoseconds < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
        finally:
            print(f"COUNT {count['n']}", flush=True)
            node.destroy_node()
            rclpy.shutdown()

    if __name__ == "__main__":
        main()
    """
)


def test_sc1_replay_bag_publishes_external_subscriber_receives(tmp_path):
    """SC1: production ``replay_bag()`` publishes; an external subscriber subprocess receives.

    Builds a ROS 2 sqlite3 fixture (3 topics, 3 ``/imu`` messages — NONE latched, Open Q2).
    Starts the EXTERNAL SUBSCRIBER subprocess FIRST and waits for its ``READY`` line + a brief
    discovery settle (Pitfall 4). Then the test process calls the PRODUCTION front door
    ``replay_bag()`` IN-PROCESS — it owns ``rclpy.init()``/``shutdown()``, builds the
    publishers, wires the sink (a bug in any of that real wiring would fail SC1). A fast
    ``rate=50`` keeps it quick; ``max_messages=9`` is belt-and-suspenders against an accidental
    loop. ``default_typestore`` is required for the sqlite3 fixture (harmless for MCAP). After
    replay returns, the subscriber subprocess is stopped and its received ``/imu`` count is read
    from stdout. Asserting the COUNT (a stale/empty/wrong replay would fail) proves SC1.
    """
    bag = write_ros2_sqlite_bag(tmp_path)

    # Start the EXTERNAL subscriber FIRST (subscriber-before-publisher — Pitfall 4). Same
    # python3 + sourced ROS env as this test (sys.executable), so rclpy/sensor_msgs resolve.
    proc = subprocess.Popen(
        [sys.executable, "-c", _SUBSCRIBER_SRC],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        # Wait for the subscriber to announce it is up (its READY line), then a short DDS
        # discovery settle before publishing.
        ready_line = proc.stdout.readline()
        assert ready_line.strip() == "READY", f"subscriber did not come up: {ready_line!r}"
        time.sleep(1.0)  # DDS discovery settle (Pitfall 4)

        # The PRODUCTION publish path under test — NOT a test-built sink. replay_bag() owns
        # rclpy.init()/shutdown(), the publisher dict, the sink, seek + finally cleanup.
        published = replay_bag(
            str(bag),
            rate=50.0,  # fast -> quick, deterministic live run
            max_messages=9,  # belt-and-suspenders against an accidental loop (3 topics x 3)
            default_typestore=get_typestore(Stores.ROS2_HUMBLE),  # required for sqlite3
        )
        assert published == 9, f"replay_bag published {published}, expected 9 (3 topics x 3)"

        # Give the subscriber a moment to drain any in-flight messages, then ask it to report.
        time.sleep(1.0)
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            out, _ = proc.communicate(timeout=10)

    # The subscriber prints "COUNT <n>" as its last line; parse the received /imu count.
    count_lines = [ln for ln in out.splitlines() if ln.startswith("COUNT ")]
    assert count_lines, f"subscriber printed no COUNT line; stdout was:\n{out}"
    received = int(count_lines[-1].split()[1])

    # SC1: the external subscriber RECEIVED the replayed /imu messages published by the
    # production replay_bag() front door. A stale/empty/wrong replay would fail this.
    assert received == N_IMU, f"subscriber received {received} /imu msgs, expected {N_IMU}"
