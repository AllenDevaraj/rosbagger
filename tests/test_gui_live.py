"""LIVE-marked GUI integration test (GUI-01, the ROS-sourced lane) — SKIPPED in offline CI.

This is the TIER-2 LIVE half for the Textual cockpit's two live panels (record / replay):
it drives the REAL ``RosbaggerApp`` headlessly through ``App.run_test()`` / ``Pilot`` on a
sourced ROS 2 environment and proves the live panels actually exercise the production
``rosbagger-record`` / ``rosbagger-replay`` paths — the transport loop, discovery scan, and
the real publish sink behind the GUI's thin face. Unlike ``tests/test_gui.py`` (the ROS-FREE
SC1/SC2/SC3 proof, which exercises only the OFFLINE inspect/query panels + the capability
gate), this needs a REAL ``rclpy`` graph, so it runs ONLY in the ROS-sourced lane and is
SKIPPED in the offline CI.

GATING (so the offline CI stays green — mirrors tests/test_record_live.py / test_replay_live.py):
* ``rclpy = pytest.importorskip("rclpy")`` at the very top SKIPS the whole module in the
  ROS-free uv venv (``PYTHONPATH="" uv run pytest`` hides the host's ROS → import fails →
  skip). The offline gate therefore sees this file COLLECTED-AND-SKIPPED, contributing
  nothing to coverage.
* ``pytestmark = pytest.mark.live`` (the marker registered in the root pyproject) so the
  live lane can select it with ``-m live`` and the offline run shows no unknown-marker
  warning.

VERIFIED LIVE-LANE RECIPE (mirrors 12-VERIFICATION / 13-CONTEXT, swapping the test file):
    source /opt/ros/humble/setup.bash
    PYTHONPATH="packages/rosbagger-gui/src:packages/rosbagger-replay/src:\\
      packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" \\
      python3 -m pytest tests/test_gui_live.py -m live -v
The src-tree prepend on PYTHONPATH lets the system ``python3`` resolve the GUI + live
packages; the ``sys.path`` insert below is belt-and-suspenders so the file also resolves if
only the repo root is on the path.

WHY EXTERNAL PUBLISHER / SUBSCRIBER SUBPROCESSES (the Phase-12/13 pattern): the GUI's record
panel runs ``list_topics`` / ``record`` (each owns ``rclpy.init()``/``shutdown()`` for the
process), and the replay panel builds its OWN rclpy context to publish. A SEPARATE process
for the other actor gives it its own rclpy context (no double-init clash) AND makes it a
genuinely EXTERNAL graph participant, so DDS discovery is really exercised.

PILOT + THREAD WORKERS: the live panels run their blocking ROS calls in
``@work(thread=True)`` workers (Pitfall 1). After triggering a panel action we
``await app.workers.wait_for_complete()`` (or poll the panel's reactive/state) so the worker
finishes before asserting on the widget it updated via ``call_from_thread``.
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

# Belt-and-suspenders src resolution for the ROS-sourced lane (mirrors test_replay_live.py):
# the verified recipe prepends the package src trees on PYTHONPATH; this also covers a lane
# that only has the repo root on the path. Scoped to this file, touching neither conftest nor
# the root pyproject. Harmless when the trees are already importable (the `if` guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT,
    _REPO_ROOT / "packages" / "rosbagger-gui" / "src",
    _REPO_ROOT / "packages" / "rosbagger-replay" / "src",
    _REPO_ROOT / "packages" / "rosbagger-record" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from textual.widgets import SelectionList, Static  # noqa: E402
from tools.make_fixtures import write_ros2_sqlite_bag  # noqa: E402

from rosbagger_gui.app import RosbaggerApp  # noqa: E402  (the App whose live panels we drive)

RECORD_TOPIC = "/telemetry"
RECORD_MSG_TYPE = "std_msgs/msg/String"
REPLAY_TOPIC = "/imu"  # the fixture publishes 3 /imu messages (sensor_msgs/msg/Imu)
N_IMU = 3


# ---------------------------------------------------------------- external actors

# The publisher program for the RECORD panel test (mirrors test_record_live.py): a separate
# process publishing std_msgs/msg/String on /telemetry at ~20Hz until killed, so it is a
# genuinely external graph participant the GUI's discovery scan must find.
_PUBLISHER_SRC = textwrap.dedent(
    """
    import rclpy
    from std_msgs.msg import String

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_gui_live_test_publisher")
        pub = node.create_publisher(String, "/telemetry", 10)
        i = 0
        def tick():
            nonlocal i
            msg = String()
            msg.data = f"telemetry-{i}"
            pub.publish(msg)
            i += 1
        node.create_timer(0.05, tick)  # ~20 Hz
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            node.destroy_node()
            rclpy.shutdown()

    if __name__ == "__main__":
        main()
    """
)

# The subscriber program for the REPLAY panel test (mirrors test_replay_live.py): a separate
# process with its OWN rclpy context (no double-init clash with the panel's publish context)
# that subscribes to /imu, counts received messages for a bounded window, and prints the
# count on its last stdout line.
_SUBSCRIBER_SRC = textwrap.dedent(
    """
    import rclpy
    from sensor_msgs.msg import Imu

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_gui_live_test_subscriber")
        count = {"n": 0}
        def on_msg(_msg):
            count["n"] += 1
        node.create_subscription(Imu, "/imu", on_msg, 10)  # sane default QoS (matches sink)
        print("READY", flush=True)
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


@pytest.fixture
def external_publisher():
    """Spawn the external /telemetry publisher subprocess; terminate it on teardown.

    Yields after a short head-start so DDS discovery has begun by the time the record
    panel's discovery worker runs. Same ``python3`` + sourced ROS env as this test
    (``sys.executable``), so ``rclpy`` / ``std_msgs`` resolve identically.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _PUBLISHER_SRC],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)  # let the publisher advertise before the GUI scans
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)


# ----------------------------------------------------------------- the live tests


async def test_record_panel_discovers_external_topic(external_publisher, tmp_path) -> None:
    """LIVE (record): the record panel's discovery worker finds the external /telemetry topic.

    Launches the real ``RosbaggerApp`` on a sourced ROS 2 env, selects the record panel
    (which is ENABLED because ``rclpy`` is importable), waits for its ``@work(thread=True)``
    discovery worker (which calls the real ``rosbagger_record.list_topics``) to complete, and
    asserts the ``#topic-checklist`` SelectionList was populated with the published
    ``/telemetry`` topic. This exercises the GUI's thin face over the real discovery front
    door — the blocking ROS scan runs in the worker, the result reaches the widget via
    ``call_from_thread``.
    """
    bag = write_ros2_sqlite_bag(tmp_path)
    app = RosbaggerApp(bag_path=bag)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.ros_available is True, "live lane must have rclpy → record panel enabled"

        await pilot.click("#nav-record")
        await pilot.pause()
        # The on_show discovery scan started a thread worker; wait for it to finish so the
        # checklist is populated before asserting (the worker updates it via call_from_thread).
        await app.workers.wait_for_complete()
        await pilot.pause()

        checklist = app.query_one("#topic-checklist", SelectionList)
        option_values = {opt.value for opt in checklist._options}  # noqa: SLF001 - read the option values
        assert RECORD_TOPIC in option_values, (
            f"/telemetry not discovered by the record panel; saw: {sorted(option_values)}"
        )


async def test_replay_panel_publishes_external_subscriber_receives(tmp_path) -> None:
    """LIVE (replay): the replay panel publishes a bag; an external subscriber receives it.

    Builds a ROS 2 sqlite3 fixture (3 ``/imu`` messages), launches the real ``RosbaggerApp``
    over it (so the replay panel sits on the App's shared reader), starts an EXTERNAL
    subscriber subprocess FIRST (subscriber-before-publisher — Pitfall 4), then selects the
    replay panel and presses Play. The panel builds its OWN rclpy context + the SHARED
    ``build_publish_sink`` and drives the pure ``Replayer.run()`` in a thread worker; we wait
    for that worker to finish, then read the subscriber's received ``/imu`` count. Asserting
    the COUNT (a stale/empty/wrong replay would fail) proves the GUI's live publish path works
    end-to-end through the real ``rosbagger-replay`` sink.
    """
    bag = write_ros2_sqlite_bag(tmp_path)

    # External subscriber FIRST (its own rclpy context; no clash with the panel's context).
    proc = subprocess.Popen(
        [sys.executable, "-c", _SUBSCRIBER_SRC],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        ready_line = proc.stdout.readline()
        assert ready_line.strip() == "READY", f"subscriber did not come up: {ready_line!r}"
        time.sleep(1.0)  # DDS discovery settle (Pitfall 4)

        app = RosbaggerApp(bag_path=bag)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.ros_available is True, "live lane must have rclpy → replay panel enabled"

            await pilot.click("#nav-replay")
            await pilot.pause()

            # A fast rate keeps the live run quick + deterministic; set it before Play.
            replay_rate = app.query_one("#replay-rate")
            replay_rate.value = "50.0"
            await pilot.pause()

            # Press Play: the panel builds the transport (its own rclpy ctx + the SHARED
            # build_publish_sink) and drives Replayer.run() in a @work(thread=True) worker.
            await pilot.click("#replay-play")
            await pilot.pause()
            # Wait for the drive worker (the blocking publish loop) to finish.
            await app.workers.wait_for_complete()
            await pilot.pause()

            # The panel reports the published count on the status line at DONE.
            status = str(app.query_one("#replay-status", Static).renderable)
            assert "Done" in status or "published" in status.lower(), (
                f"replay panel did not reach a published/Done terminal status: {status!r}"
            )

        time.sleep(1.0)  # let the subscriber drain in-flight messages before we stop it
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            out, _ = proc.communicate(timeout=10)

    count_lines = [ln for ln in out.splitlines() if ln.startswith("COUNT ")]
    assert count_lines, f"subscriber printed no COUNT line; stdout was:\n{out}"
    received = int(count_lines[-1].split()[1])
    assert received == N_IMU, f"subscriber received {received} /imu msgs, expected {N_IMU}"
