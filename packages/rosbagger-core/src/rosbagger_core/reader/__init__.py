"""Reader subpackage — the swappable bag-reader seam.

Re-exports the backend-agnostic public API: ``BagReader`` (the ABC seam) and
``Message`` (the uniform per-message record). The concrete rosbags-backed reader
(wrapping ``rosbags.highlevel.AnyReader``) lands in plan 02-02 and will extend
``__all__`` here.

Note: this re-export pulls in only ``base.py`` (stdlib-only), so importing the
subpackage stays ROS-free. The top-level ``rosbagger_core`` package does NOT
import this subpackage, so ``import rosbagger_core`` stays light (Phase 1
decision; offline-guard invariant).
"""

from .base import BagReader, Message

__all__ = ["BagReader", "Message"]
