"""rosbagger-gui custom widgets.

Reusable Textual widgets the panels embed. ``Scrubber`` is the timeline/playhead
widget the replay panel uses for seek + event-marker jumps (Plan 14-06). These are
PURE textual/stdlib widgets — they hold NO module-API (``rosbagger_*``) logic, so
re-exporting them here pulls in no ROS and no heavy stack (the offline-import
invariant). A widget only emits a position FRACTION; the panel owns the transport
mapping (fraction -> ``Replayer.seek``).
"""

from __future__ import annotations

from .scrubber import Scrubber

__all__ = ["Scrubber"]
