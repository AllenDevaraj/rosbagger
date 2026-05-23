"""rosbagger-record: live ROS 2 topic discovery + subset recording (REC-01).

This is rosbagger's FIRST module that requires a sourced ROS 2 environment
(``rclpy`` + ``rosbag2_py``). The whole offline tier (``rosbagger_core``, ``bagq``)
stays ROS-free — this package must not compromise that.

OFFLINE-IMPORT BOUNDARY (D-03/D-11) — the load-bearing discipline of this module:
``import rosbagger_record`` MUST succeed in the ROS-free uv venv WITHOUT pulling
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` into ``sys.modules``. So this
file imports NO ROS at module top. Every ROS import lives INSIDE a function body,
behind :func:`_require_ros`, which converts a missing ROS install into the teaching
:class:`RosNotAvailableError` (instead of a raw ``ModuleNotFoundError``). The
public ``record`` / ``list_topics`` entry points are thin lazy delegators to the
``.record`` impl module (which does the heavy ``rclpy`` / ``rosbag2_py`` import) and
land in Plan 02; the pure-Python ``discover_topics`` / ``select_topics`` selection
logic lives in ``.discovery`` (Plan 01, this wave) and is unit-testable with mocks.

``test_offline_guard.py`` regression-locks the boundary: it asserts a fresh
interpreter that does ``import rosbagger_record`` leaks no ``rclpy`` / ``rosbag2_py``
(and that ``import rosbagger_core`` / ``import bagq`` stay ROS-free too).
"""

from __future__ import annotations

from .discovery import discover_topics, select_topics
from .errors import McapStorageUnavailableError, RosNotAvailableError

__version__ = "0.1.0"

# Public API: the teaching capability errors, the lazy ROS-bound entry points
# (record / list_topics — impl in .record, Plan 02), and the pure-Python discovery
# + selection helpers (discover_topics / select_topics). Re-exporting the discovery
# helpers binds NO ROS — discovery.py imports rclpy only inside discover_topics'
# body, and select_topics is pure.
__all__ = [
    "McapStorageUnavailableError",
    "RosNotAvailableError",
    "discover_topics",
    "list_topics",
    "record",
    "select_topics",
]


def _require_ros() -> None:
    """Lazy ROS-availability guard (D-03/D-11).

    Imports ``rclpy`` and ``rosbag2_py`` INSIDE the function body so the package
    top level stays ROS-free. Converts the ``ImportError`` raised in a ROS-free
    environment into the teaching :class:`RosNotAvailableError`, preserving the
    original cause. Call this at the top of every entry point that touches ROS,
    BEFORE importing the heavy ``.record`` impl module.
    """
    try:
        import rclpy  # noqa: F401
        import rosbag2_py  # noqa: F401
    except ImportError as exc:
        raise RosNotAvailableError() from exc


def record(*args: object, **kwargs: object) -> object:
    """Record a selected subset of live topics to a bag (REC-01 / SC2).

    Lazy front door: checks ROS availability (raising the teaching
    :class:`RosNotAvailableError` when ROS is absent — D-11), then delegates to the
    ``rclpy`` / ``rosbag2_py`` implementation in ``.record`` (Plan 02). Keeping the
    heavy import behind ``_require_ros()`` is what lets ``import rosbagger_record``
    succeed offline.
    """
    _require_ros()
    from .record import record as _record

    return _record(*args, **kwargs)


def list_topics(*args: object, **kwargs: object) -> object:
    """List currently discoverable live topics + their types (REC-01 / SC1).

    Lazy front door mirroring :func:`record`: requires ROS (teaching error if
    absent), then delegates to the ``.record`` implementation (Plan 02).
    """
    _require_ros()
    from .record import list_topics as _list_topics

    return _list_topics(*args, **kwargs)
