"""Reader subpackage — the swappable bag-reader seam.

Re-exports the public API: ``BagReader`` (the ABC seam), ``Message`` (the
uniform per-message record), and ``RosbagsReader`` (impl #1, wrapping
``rosbags.highlevel.AnyReader``).

Note: re-exporting ``RosbagsReader`` means ``import rosbagger_core.reader`` now
pulls in ``rosbags`` — that is expected and fine. The offline-guard invariant
only requires that the TOP-LEVEL ``rosbagger_core`` package stays light: it does
NOT import this subpackage, so ``import rosbagger_core`` remains ROS-free and
``rosbags``-free (Phase 1 decision; ``tests/test_offline_guard.py``).
"""

from .base import BagReader, Message
from .rosbags_reader import RosbagsReader, open_bag

__all__ = ["BagReader", "Message", "RosbagsReader", "open_bag"]
