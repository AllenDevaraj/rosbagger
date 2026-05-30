"""LIVE ``.rrd`` proof for ``rosbagger-rerun`` (Phase 22, RR-2 / D-11 tier 2).

Drives REAL bag items through :func:`rosbagger_rerun.build_rerun_sink` against a SAVE-mode
``RecordingStream`` (``open_viewer(save_path=...)`` — no viewer process) and asserts a non-empty
``.rrd`` is written. This is the end-to-end proof of the deserialize→convert→log path with a real
``rclpy`` graph; the converter MATH is asserted offline in ``test_rerun_unit.py``.

GATING (so the offline CI stays green): ``rclpy = pytest.importorskip("rclpy")`` SKIPS the whole
module in the ROS-free uv venv (and under ``PYTHONPATH=""``), and ``pytestmark =
pytest.mark.live`` lets the ROS lane select it with ``-m live``. COLLECTED-AND-SKIPPED in the
offline gate — contributes nothing to coverage and is NOT required for it.

VERIFIED LIVE-LANE RECIPE (mirrors test_replay_fidelity_live.py):
    source /opt/ros/humble/setup.bash
    uv run --with pyyaml --with lark pytest tests/test_rerun_live.py -m live -v --no-cov
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")  # SKIP the whole module in the ROS-free offline CI

pytestmark = pytest.mark.live

# Belt-and-suspenders src resolution for the ROS-sourced lane (mirrors the other live modules).
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT / "packages" / "rosbagger-replay" / "src",
    _REPO_ROOT / "packages" / "rosbagger-core" / "src",
    _REPO_ROOT / "packages" / "rosbagger-rerun" / "src",
):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from rosbags.typesys import Stores, get_typestore  # noqa: E402  (system python3 has rosbags)
from tools.make_fixtures import write_ros2_sqlite_bag  # noqa: E402

from rosbagger_replay import load_items  # noqa: E402
from rosbagger_rerun import build_rerun_sink, open_viewer  # noqa: E402


def test_build_rerun_sink_writes_rrd(tmp_path):
    """Real bag items through build_rerun_sink (save mode) write a non-empty .rrd (RR-2).

    sqlite3 bags carry no type definitions, so ``load_items`` is handed the ROS2_HUMBLE
    typestore. The fixture's messages exercise the generic fallback (Imu has no rich converter),
    so a non-empty .rrd + ``logged['n'] >= 1`` proves deserialize→convert→log end to end.
    """
    bag = write_ros2_sqlite_bag(tmp_path / "bag")
    rrd = tmp_path / "out.rrd"
    items = load_items(str(bag), default_typestore=get_typestore(Stores.ROS2_HUMBLE))
    assert items, "fixture bag produced no items"

    rclpy.init()
    try:
        rec = open_viewer(save_path=str(rrd))  # SAVE mode — no viewer process
        sink, logged = build_rerun_sink(rec)
        for item in items:
            sink(item)
        rec.flush()  # 0.32 flush(*, timeout_sec=...) — NO `blocking` kwarg
    finally:
        rclpy.shutdown()

    assert rrd.exists(), "no .rrd written"
    assert rrd.stat().st_size > 0, "empty .rrd"
    assert logged["n"] >= 1, f"no items logged (errors={logged.get('errors')})"
