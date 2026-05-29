"""rosbagger-replay: live ROS 2 bag replay with transport controls (REP-01).

This is rosbagger's SECOND module that requires a sourced ROS 2 environment
(``rclpy``). The whole offline tier (``rosbagger_core``, ``bagq``) and this
package's PURE layers (the raw-CDR ``source`` seam + the transport ``scheduler``)
stay ROS-free — this package must not compromise that.

OFFLINE-IMPORT BOUNDARY (D-03/D-12) — the load-bearing discipline of this module:
``import rosbagger_replay`` MUST succeed in the ROS-free uv venv WITHOUT pulling
``rclpy`` / ``rosbag2_py`` / ``rosidl_runtime_py`` into ``sys.modules``. So this
file imports NO ROS at module top — only the stdlib-only teaching errors and the
pure ``source`` seam (rosbags-only) + the pure transport ``scheduler``. Every ROS
import lives INSIDE a function body, behind :func:`_require_ros`, which converts a
missing ROS install into the teaching :class:`RosNotAvailableError` (instead of a
raw ``ModuleNotFoundError``). The public ``replay`` entry point is a thin lazy
delegator to the ``.replay`` impl module (which does the heavy ``rclpy`` /
``rosidl_runtime_py`` import); the pure raw-CDR ``source`` seam (Plan 01) and the
pure transport ``scheduler`` (Plan 02) are ROS-free and re-exported at top level.

``test_offline_guard.py`` (extended in Plan 03) regression-locks the boundary: it
asserts a fresh interpreter that does ``import rosbagger_replay`` leaks no ``rclpy``
/ ``rosbag2_py`` (and that ``import rosbagger_core`` / ``import bagq`` stay ROS-free).
"""

from __future__ import annotations

from .errors import NoMessagesToReplayError, RosNotAvailableError
from .fidelity import StaticTracker, clock_stamp_ns
from .scheduler import Replayer
from .source import ReplayItem, load_items

__version__ = "0.2.0"

# Public API: the teaching capability errors, the pure raw-CDR source seam
# (ReplayItem + load_items), the pure transport scheduler (Replayer), the pure RViz-fidelity
# decision tier (StaticTracker + clock_stamp_ns, Phase 20), and the lazy ROS-bound front door
# (replay / replay_bag — impl in .replay). Re-exporting errors / source / scheduler / fidelity
# binds NO ROS — errors.py and fidelity.py are stdlib-only, source.py imports rosbags only
# (lazily inside load_items), and scheduler.py is stdlib-only.
__all__ = [
    "NoMessagesToReplayError",
    "ReplayItem",
    "Replayer",
    "RosNotAvailableError",
    "StaticTracker",
    "build_publish_sink",
    "clock_stamp_ns",
    "load_items",
    "replay",
    "replay_bag",
    "republish_static",
]


def _require_ros() -> None:
    """Lazy ROS-availability guard (D-03/D-12).

    Imports ``rclpy`` INSIDE the function body so the package top level stays
    ROS-free. Converts the ``ImportError`` raised in a ROS-free environment into the
    teaching :class:`RosNotAvailableError`, preserving the original cause. Call this
    at the top of the entry point that touches ROS, BEFORE importing the heavy
    ``.replay`` impl module. Checking ``rclpy`` here is sufficient —
    ``rosidl_runtime_py`` ships with the same ROS distro and is imported inside
    ``replay.py``.
    """
    try:
        import rclpy  # noqa: F401
    except ImportError as exc:
        raise RosNotAvailableError() from exc


def replay(*args: object, **kwargs: object) -> object:
    """Replay a bag's messages to live ROS 2 topics with transport controls (REP-01 / SC1).

    Lazy front door: checks ROS availability (raising the teaching
    :class:`RosNotAvailableError` when ROS is absent — D-12), then delegates to the
    ``rclpy`` / ``rosidl_runtime_py`` publish implementation in ``.replay`` (this
    plan). Keeping the heavy import behind ``_require_ros()`` is what lets
    ``import rosbagger_replay`` succeed offline. This is the SINGLE production publish
    front door the CLI, the Phase-14 GUI, and the SC1 live test all drive — there is
    no second publish path.
    """
    _require_ros()
    from .replay import replay as _replay

    return _replay(*args, **kwargs)


def build_publish_sink(*args: object, **kwargs: object) -> object:
    """Build the single rclpy publish sink shared by ``replay()`` and the GUI (D-09a).

    Lazy front door: checks ROS availability (raising the teaching
    :class:`RosNotAvailableError` when ROS is absent — D-12), then delegates to
    :func:`rosbagger_replay.replay.build_publish_sink`, which does the heavy
    ``rclpy.serialization`` / ``rosidl_runtime_py`` import inside its body. Keeping the
    import behind ``_require_ros()`` is what lets ``import rosbagger_replay`` succeed
    offline. The Phase-14 GUI imports the publish mechanics through THIS package front
    door so there is exactly one production publish path — never a duplicated sink.
    """
    _require_ros()
    from .replay import build_publish_sink as _build_publish_sink

    return _build_publish_sink(*args, **kwargs)


def republish_static(*args: object, **kwargs: object) -> object:
    """Re-push a sink's tracked static items after a seek (Phase-20 RViz fidelity, REP-04).

    Lazy front door over :func:`rosbagger_replay.replay.republish_static`: re-publishes the
    latest static-topic messages a :func:`build_publish_sink` (with ``static_topics``) tracked,
    so a fresh subscriber re-primes its scene after a replay seek. ``republish_static`` itself
    only drives the given sink (it imports no ROS), but it lives in ``.replay`` (which does the
    lazy rclpy import for the sink), so it is exposed through the same lazy front door + guard
    to keep ``import rosbagger_replay`` ROS-free.
    """
    _require_ros()
    from .replay import republish_static as _republish_static

    return _republish_static(*args, **kwargs)


# Submodule-shadow-proof alias to the lazy front-door FUNCTION above.
#
# WHY: ``rosbagger_replay`` exposes both a ``replay`` FUNCTION (this module) and a
# ``replay`` SUBMODULE (``replay.py``). Importing the submodule anywhere in the process
# (e.g. ``import rosbagger_replay.replay``) rebinds the ``rosbagger_replay.replay``
# ATTRIBUTE to the MODULE, so a later ``from rosbagger_replay import replay`` resolves to
# the module (not callable) — a latent footgun for any caller (the CLI, the Phase-14 GUI,
# a user script) that happens to import the submodule first. Callers that need the
# guaranteed-callable front door import ``replay_bag``; ``replay`` stays the documented
# public API for the common case where the submodule is not pre-imported.
replay_bag = replay
