"""LIVE integration test for rosbagger-record (REC-01 / SC1+SC2+SC3, D-10 tier 2).

This is the TIER-2 LIVE half of the two-tier strategy (D-10): it proves the offline↔live
closing loop the whole phase exists for — an EXTERNAL publisher → bounded ``record()`` →
re-open + iterate via the EXISTING v1 ``RosbagsReader`` (no new read code). Unlike the
offline ``test_record_unit.py`` (which mocks ROS), this test needs a REAL ``rclpy`` graph,
so it runs ONLY in the ROS-sourced lane and is SKIPPED in the offline CI.

GATING (so the offline CI stays green):
* ``rclpy = pytest.importorskip("rclpy")`` at the very top SKIPS the whole module in the
  ROS-free uv venv (``PYTHONPATH="" uv run pytest`` hides the host's ROS → import fails →
  skip). The offline gate therefore sees this file COLLECTED-AND-SKIPPED, contributing
  nothing to coverage.
* ``pytestmark = pytest.mark.live`` (the marker registered in Plan 01's pyproject) so the
  live lane can select it with ``-m live`` and the offline run shows no unknown-marker
  warning.
* The MCAP-specific assertion is ``@pytest.mark.skipif`` -guarded on
  ``rosbag2_py.get_registered_writers()`` — on THIS box only ``sqlite3`` is registered
  (the ``ros-humble-rosbag2-storage-mcap`` plugin is not installed), so the sqlite3 path
  carries the SC2/SC3 proof here and the MCAP variant skips cleanly (12-RESEARCH Pitfall 1).

VERIFIED LIVE-LANE RECIPE (12-RESEARCH "Environment Availability"):
    source /opt/ros/humble/setup.bash
    PYTHONPATH="packages/rosbagger-record/src:packages/rosbagger-core/src:$PYTHONPATH" \
      python3 -m pytest tests/test_record_live.py -m live -v
The src-tree prepend on PYTHONPATH is what lets the system ``python3`` resolve
``rosbagger_record`` / ``rosbagger_core``; the ``sys.path`` insert below is belt-and-
suspenders so the file also resolves if only the repo root is on the path.

WHY THE PUBLISHER IS A SUBPROCESS (not a second in-process node): ``record()`` and
``list_topics()`` each own ``rclpy.init()`` / ``rclpy.shutdown()`` for the process, and
``rclpy.init()`` cannot run twice in one context. Publishing from a SEPARATE process gives
it its own rclpy context (no double-init clash) AND makes the publisher genuinely EXTERNAL,
so the recorder's DDS settle (12-RESEARCH Pattern 3 / Pitfall 4) is really exercised —
external publishers are not visible immediately after node creation.
"""

from __future__ import annotations

import sys
import textwrap
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")  # SKIP the whole module in the ROS-free offline CI

pytestmark = pytest.mark.live

# Belt-and-suspenders src resolution for the ROS-sourced lane: the verified recipe prepends
# the package src trees on PYTHONPATH; this also covers a lane that only has the repo root
# on the path. Scoped to this file (mirrors tests/test_tf.py), touching neither conftest nor
# the root pyproject. Harmless when the trees are already importable (the `if` guards it).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT / "packages" / "rosbagger-record" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rosbags.typesys import Stores, get_typestore  # noqa: E402  (system python3 has rosbags)

from rosbagger_core.reader.rosbags_reader import RosbagsReader  # noqa: E402
from rosbagger_record import list_record_topics, record_topics  # noqa: E402

TOPIC = "/telemetry"
MSG_TYPE = "std_msgs/msg/String"
N_MESSAGES = 5  # bounded count -> deterministic SC2 (record exactly N, then assert N)


def _available_storage() -> str:
    """The registered storage backend to record through on THIS box (sqlite3 here).

    Prefers ``mcap`` (the shipped default, D-08) when its plugin is registered, else falls
    back to ``sqlite3`` (the capability escape registered everywhere) so the mechanism is
    provable on a box without the MCAP plugin. The MCAP-specific assertion is separately
    ``skipif`` -guarded; this just picks what the SC2/SC3 proof records through here.
    """
    import rosbag2_py

    writers = rosbag2_py.get_registered_writers()
    return "mcap" if "mcap" in writers else "sqlite3"


def _mcap_available() -> bool:
    """True iff the ``mcap`` rosbag2 storage plugin is registered (12-RESEARCH Pitfall 1)."""
    import rosbag2_py

    return "mcap" in rosbag2_py.get_registered_writers()


# The publisher program, run in a SEPARATE process so it has its own rclpy context and is a
# genuinely EXTERNAL graph participant. Publishes std_msgs/msg/String on /telemetry at ~20Hz
# until killed. Kept tiny + dependency-light (only rclpy + std_msgs, both in the sourced env).
_PUBLISHER_SRC = textwrap.dedent(
    """
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    def main():
        rclpy.init()
        node = rclpy.create_node("rosbagger_live_test_publisher")
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


@pytest.fixture
def external_publisher():
    """Spawn the external /telemetry publisher subprocess; terminate it on teardown.

    Yields after a short head-start so DDS discovery has begun by the time the recorder's
    own settle runs. The subprocess uses the SAME ``python3`` + sourced ROS env this test
    runs under (``sys.executable``), so ``rclpy`` / ``std_msgs`` resolve identically.
    """
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-c", _PUBLISHER_SRC],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)  # let the publisher come up + start advertising before we record
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=5)


def test_sc1_list_discovers_external_topic(external_publisher):
    """SC1: ``list_topics()`` discovers the external ``/telemetry`` with its type.

    Proves the discovery front door (D-06): with the external publisher running, the
    recorder's settle finds ``/telemetry`` and maps it to ``std_msgs/msg/String``. This is
    exactly what the ``rosbagger-record list`` CLI verb prints.
    """
    discovered = list_record_topics()
    assert TOPIC in discovered, f"/telemetry not discovered; saw: {sorted(discovered)}"
    assert discovered[TOPIC] == MSG_TYPE


def test_sc2_sc3_record_sqlite3_then_reopen_via_v1_reader(external_publisher, tmp_path):
    """SC2+SC3 (the closing loop): bounded record → re-open + iterate via the v1 reader.

    SC2: with the external publisher running, ``record(max_messages=N)`` discovers the
    topic (after the settle), captures EXACTLY ``N`` frames, and finalizes the bag.
    SC3: the recorded bag re-opens through the EXISTING ``RosbagsReader`` (no new read code)
    with ``default_typestore=ROS2_HUMBLE`` (required for the sqlite3 backend; a harmless
    no-op for self-describing MCAP — 12-RESEARCH Pitfall 2 / Open Q1), and iterating yields
    ``N`` messages ALL on ``/telemetry``. Asserting BOTH the count and the topic means a
    stale/empty/wrong bag would fail (T-12-06).
    """
    out = str(tmp_path / "rec")
    storage = _available_storage()

    n = record_topics([TOPIC], out, storage=storage, max_messages=N_MESSAGES)
    assert n == N_MESSAGES, f"expected {N_MESSAGES} captured, got {n}"

    # SC3 re-open through the v1 reader — the offline↔live contract, no new read code.
    ts = get_typestore(Stores.ROS2_HUMBLE)  # required for sqlite3; no-op for MCAP
    with RosbagsReader(out, default_typestore=ts) as reader:
        msgs = list(reader.read())

    assert len(msgs) == N_MESSAGES, f"re-opened {len(msgs)} msgs, expected {N_MESSAGES}"
    assert all(m.topic == TOPIC for m in msgs), "a re-opened message was not on /telemetry"


@pytest.mark.skipif(
    not _mcap_available(),
    reason="ros-humble-rosbag2-storage-mcap not installed (only sqlite3 registered here)",
)
def test_sc2_sc3_record_mcap_then_reopen_via_v1_reader(external_publisher, tmp_path):
    """SC2+SC3 via the LOCKED MCAP format (D-08) — runs only where the plugin is registered.

    Mirrors the sqlite3 proof but records through ``storage="mcap"``. SKIPPED on this box
    (the MCAP plugin is not installed). Where the plugin IS present this proves the shipped
    default path end-to-end; MCAP self-describes, so the ``default_typestore`` passed below
    is the same harmless defensive no-op (12-RESEARCH Pitfall 2 / Open Q1).
    """
    out = str(tmp_path / "rec_mcap")

    n = record_topics([TOPIC], out, storage="mcap", max_messages=N_MESSAGES)
    assert n == N_MESSAGES

    ts = get_typestore(Stores.ROS2_HUMBLE)  # harmless no-op for self-describing MCAP
    with RosbagsReader(out, default_typestore=ts) as reader:
        msgs = list(reader.read())

    assert len(msgs) == N_MESSAGES
    assert all(m.topic == TOPIC for m in msgs)
