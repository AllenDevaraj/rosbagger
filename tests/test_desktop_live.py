"""LIVE-marked desktop GUI integration test (Phase 16 / SC5, the ROS-sourced lane).

This is the TIER-2 LIVE half for the native PySide6 cockpit's two live panels (record /
replay): it drives the REAL :class:`~rosbagger_desktop.main_window.MainWindow` headlessly via
the pytest-qt ``qtbot`` fixture (the Qt analog of the TUI's ``App.run_test()`` / ``Pilot``) on
a sourced ROS 2 environment and proves the live panels actually exercise the production
``rosbagger-record`` / ``rosbagger-replay`` paths — the discovery scan, the bounded record,
and the real ``build_publish_sink`` publish loop behind the GUI's thin face. Unlike
``tests/test_desktop.py`` (the ROS-FREE SC1/SC2/SC3 proof, which exercises only the OFFLINE
inspect/query/tf panels + the capability gate), this needs a REAL ``rclpy`` graph, so it runs
ONLY in the ROS-sourced lane and is SKIPPED in the offline CI.

GATING (so the offline CI stays green — mirrors tests/test_gui_live.py):
* ``rclpy = pytest.importorskip("rclpy")`` at the very top SKIPS the whole module in the
  ROS-free uv venv (``PYTHONPATH="" uv run pytest`` hides the host's ROS → import fails →
  skip). The offline gate therefore sees this file COLLECTED-AND-SKIPPED, contributing nothing
  to coverage.
* ``pytestmark = pytest.mark.live`` (the marker registered in the root pyproject) so the live
  lane can select it with ``-m live`` and the offline run shows no unknown-marker warning.

VERIFIED LIVE-LANE RECIPE (mirrors test_gui_live.py, swapping the test file):
    source /opt/ros/humble/setup.bash
    PYTHONPATH="packages/rosbagger-desktop/src:packages/rosbagger-replay/src:\\
      packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" \\
      QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_desktop_live.py -m live -v

WHY EXTERNAL PUBLISHER / SUBSCRIBER SUBPROCESSES (the Phase-12/13/14 pattern): the record
panel runs ``list_record_topics`` / ``record_topics`` (each owns ``rclpy.init()``/``shutdown()``
for the process), and the replay panel builds its OWN rclpy context to publish. A SEPARATE
process for the other actor gives it its own rclpy context (no double-init clash) AND makes it
a genuinely EXTERNAL graph participant, so DDS discovery is really exercised.

QTBOT + THREAD WORKERS: the live panels run their blocking ROS calls on ``QThread``
``BlockingWorker``s (Pitfall 1). After triggering a panel action we ``qtbot.waitSignal`` on the
worker's ``finished`` signal (the pytest-qt analog of awaiting the Textual worker) so the
worker completes before asserting on the widget it updated via its UI-thread slot.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # BEFORE any PySide6 import (Pitfall 3)

import subprocess  # noqa: E402
import sys  # noqa: E402
import textwrap  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

rclpy = pytest.importorskip("rclpy")  # SKIP the whole module in the ROS-free offline CI

pytestmark = pytest.mark.live

# Belt-and-suspenders src resolution for the ROS-sourced lane (mirrors test_gui_live.py): the
# verified recipe prepends the package src trees on PYTHONPATH; this also covers a lane that
# only has the repo root on the path. Scoped to this file, touching neither conftest nor the
# root pyproject. Harmless when the trees are already importable (the `if` guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT,
    _REPO_ROOT / "packages" / "rosbagger-desktop" / "src",
    _REPO_ROOT / "packages" / "rosbagger-replay" / "src",
    _REPO_ROOT / "packages" / "rosbagger-record" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from PySide6.QtCore import Qt  # noqa: E402
from tools.make_fixtures import write_ros2_sqlite_bag  # noqa: E402

from rosbagger_desktop.main_window import MainWindow  # noqa: E402  (the window we drive live)

RECORD_TOPIC = "/telemetry"

# The publisher program for the RECORD panel test (mirrors test_gui_live.py): a separate
# process publishing std_msgs/msg/String on /telemetry at ~20Hz until killed, so it is a
# genuinely external graph participant the GUI's discovery scan must find.
_PUBLISHER_SRC = textwrap.dedent(
    """
    import rclpy
    from std_msgs.msg import String

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_desktop_live_test_publisher")
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

# The subscriber program for the REPLAY panel test (mirrors test_gui_live.py): a separate
# process with its OWN rclpy context (no double-init clash with the panel's publish context)
# that subscribes to /imu, counts received messages for a bounded window, and prints the count
# on its last stdout line.
_SUBSCRIBER_SRC = textwrap.dedent(
    """
    import rclpy
    from sensor_msgs.msg import Imu

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_desktop_live_test_subscriber")
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

    Yields after a short head-start so DDS discovery has begun by the time the record panel's
    discovery worker runs. Same ``python3`` + sourced ROS env as this test (``sys.executable``),
    so ``rclpy`` / ``std_msgs`` resolve identically.
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


def test_record_panel_discovers_external_topic(qtbot, external_publisher, tmp_path: Path) -> None:
    """LIVE (record): the record panel's discovery worker finds the external /telemetry topic.

    Builds a ROS 2 fixture, launches the real ``MainWindow`` on it (so record is ENABLED
    because ``rclpy`` is importable), shows the record panel (which starts the discovery
    ``QThread`` worker calling the real ``rosbagger_record.list_record_topics``), waits for the
    worker thread to finish, and asserts the topic checklist was populated with the published
    ``/telemetry`` topic. This exercises the GUI's thin face over the real discovery front door
    — the blocking ROS scan runs on the worker, the result reaches the widget via its UI-thread
    slot.
    """
    bag = write_ros2_sqlite_bag(tmp_path)
    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)
    assert window.ros_available is True, "live lane must have rclpy → record panel enabled"

    panel = window.record_panel
    panel.show()  # triggers the on-show discovery scan (starts the QThread worker)
    panel._scan_topics()

    # Wait for the discovery worker thread to finish populating the checklist.
    def _has_topics() -> bool:
        return panel.topic_list.count() > 0

    qtbot.waitUntil(_has_topics, timeout=15000)

    values = {
        panel.topic_list.item(row).data(int(Qt.UserRole)) for row in range(panel.topic_list.count())
    }
    assert RECORD_TOPIC in values, (
        f"/telemetry not discovered by the record panel; saw: {sorted(values)}"
    )


def test_replay_panel_publishes_external_subscriber_receives(qtbot, tmp_path: Path) -> None:
    """LIVE (replay): the replay panel publishes a bag; an external subscriber receives it.

    Builds a ROS 2 sqlite3 fixture (3 ``/imu`` messages), starts an EXTERNAL subscriber
    subprocess FIRST (subscriber-before-publisher — Pitfall 4), launches the real
    ``MainWindow`` over the bag, sets a fast rate, and presses Play. The panel builds its OWN
    rclpy context + the SHARED ``build_publish_sink`` and drives the pure ``Replayer.run()`` on
    a ``QThread`` worker; we wait for the worker to finish, then assert the panel reached a
    published/Done terminal status — proving the GUI's live publish path works end-to-end
    through the real ``rosbagger-replay`` sink.
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

        window = MainWindow(bag_path=str(bag))
        qtbot.addWidget(window)
        assert window.ros_available is True, "live lane must have rclpy → replay panel enabled"

        panel = window.replay_panel
        panel.show()  # fire showEvent (ROS gate + marker load); full-window visibility is NOT
        # needed because Play is triggered programmatically below — and showing the whole window
        # offscreen aggravates the known Qt-offscreen teardown crash.
        # A fast rate keeps the live run quick + deterministic; set it before Play.
        panel.rate_input.setText("50.0")

        # Press Play via the button's programmatic ``click()`` rather than ``qtbot.mouseClick``: a
        # synthetic coordinate click is silently dropped on a non-visible widget (offscreen, the
        # panel is not the current stacked page), so it would no-op and never fire ``_play`` —
        # exactly how the worker-GC regression slipped through. ``click()`` emits ``clicked``
        # directly, so the panel builds the transport (its own rclpy ctx + the SHARED
        # build_publish_sink) and drives Replayer.run() on a QThread worker. This makes the test a
        # real regression: it times out pre-fix (drive worker GC'd → 0 published), passes post-fix.
        panel.play_button.click()

        # Wait for the drive worker (the blocking publish loop) to finish and report DONE.
        def _is_done() -> bool:
            status = panel.status_label.text().lower()
            return "done" in status or "published" in status

        qtbot.waitUntil(_is_done, timeout=15000)

        status = panel.status_label.text()
        assert "Done" in status or "published" in status.lower(), (
            f"replay panel did not reach a published/Done terminal status: {status!r}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)


def test_replay_panel_rerun_mirror_writes_rrd(qtbot, tmp_path: Path, monkeypatch) -> None:
    """LIVE (Phase 22 / RR-3): toggling Open-in-Rerun then Play mirrors the publish into a .rrd.

    Monkeypatches ``rosbagger_rerun.open_viewer`` to a SAVE-mode ``RecordingStream`` (writes a
    ``.rrd``, no viewer process), toggles the mirror on (so ``_open_rerun`` builds the rerun sink),
    then presses Play. The drive tees every published item into the rerun sink; after the drive
    reaches Done we flush and assert the ``.rrd`` is non-empty — proving the publish path AND the
    rerun tee both fire from one Play (additive; the ROS publish path is unchanged).
    """
    import rerun as rr

    import rosbagger_rerun

    bag = write_ros2_sqlite_bag(tmp_path)
    rrd = tmp_path / "mirror.rrd"

    def _save_viewer(app_id: str = "rosbagger", *, save_path: str | None = None):
        rec = rr.RecordingStream(app_id)
        rec.save(str(rrd))  # SAVE mode — no viewer process spawns under test
        return rec

    monkeypatch.setattr(rosbagger_rerun, "open_viewer", _save_viewer)

    window = MainWindow(bag_path=str(bag))
    qtbot.addWidget(window)
    assert window.ros_available is True, "live lane must have rclpy → replay panel enabled"

    panel = window.replay_panel
    panel.show()  # showEvent (ROS gate + markers); full-window show aggravates the offscreen crash
    panel.rate_input.setText("50.0")  # fast + deterministic

    panel.rerun_button.click()  # toggle ON → _open_rerun → patched open_viewer (save mode)
    assert panel._rerun_sink is not None, "mirror sink was not built on toggle-on"

    panel.play_button.click()  # publish to ROS AND tee into the rerun sink

    def _is_done() -> bool:
        status = panel.status_label.text().lower()
        return "done" in status or "published" in status

    qtbot.waitUntil(_is_done, timeout=15000)

    panel._close_rerun()  # flush the recording to the .rrd

    assert rrd.exists(), "no .rrd written by the mirror"
    assert rrd.stat().st_size > 0, "empty .rrd — the tee did not log anything"
