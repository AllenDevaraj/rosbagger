"""rosbagger-desktop panels — each a self-contained ``QWidget`` over a named module API.

OFFLINE-IMPORT INVARIANT (D-08): every ``rosbagger_core`` / ``rosbagger_record`` /
``rosbagger_replay`` / ``rclpy`` import lives INSIDE a method (or worker) body — never
at a panel module's top level — so importing a panel pulls in no heavy / ROS stack.
"""

from __future__ import annotations
