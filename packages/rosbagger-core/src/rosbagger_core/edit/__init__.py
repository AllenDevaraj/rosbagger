"""``rosbagger_core.edit`` — the offline same-format bag-edit pipeline (Plan 11-01).

Public API (re-exported here so callers write ``from rosbagger_core.edit import
edit_bag, EditOps``):

* :class:`~rosbagger_core.edit.operations.EditOps` — the validated spec for the
  same-format operations (trim / drop / keep / downsample, D-06/07/08).
* :func:`~rosbagger_core.edit.pipeline.edit_bag` — the streaming
  ``AnyReader -> filter -> rosbags Writer`` driver that produces a NEW output bag
  (never in-place, D-05) whose kept messages re-open AND deserialize via
  ``AnyReader`` across ROS 1 / ROS 2-sqlite3 / MCAP (SC1, raw-copy half).
* :func:`~rosbagger_core.edit.pipeline.make_writer` — the output-format Writer
  selection (``is2 = dst.suffix != '.bag'``, D-10).

OFFLINE INVARIANT (11-RESEARCH Pitfall 5): re-exporting these names pulls in NO
``rosbags`` / ``duckdb`` / ``pyarrow`` — ``operations`` is stdlib-only and
``pipeline`` confines every heavy import to function bodies. Like ``tf`` /
``reader`` / ``output``, this subpackage is NOT imported by
``rosbagger_core/__init__``; import it explicitly at call sites. The offline guard
(``tests/test_offline_guard.py``) enforces that ``import rosbagger_core.edit``
leaks neither the heavy stack nor ``rosbags``.
"""

from __future__ import annotations

from .operations import EditOps
from .pipeline import edit_bag, make_writer

__all__ = ["EditOps", "edit_bag", "make_writer"]
