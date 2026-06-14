"""Default-typestore resolution for legacy (definition-less) ROS 2 bags (T1).

Real ``rosbag2`` recordings embed no inline message definitions, so reading them needs an
explicit typestore. Rather than have each frontend hard-code one (the GUIs each defined a
private ``_ros2_humble_typestore()`` while ``bagq`` passed nothing — so the flagship CLI
could not open a real ``.db3`` at all), this single helper resolves the right ``rosbags``
``Stores`` member from the environment. The reader layer applies it as a FALLBACK only when
a def-less bag is opened with no explicit typestore, so no face has to decide.

OFFLINE INVARIANT: this module is NOT imported by ``rosbagger_core/__init__``, and
``rosbags`` is imported LAZILY inside the functions — so ``import rosbagger_core`` stays
light and ROS-free (``tests/test_offline_guard.py``). ``rosbags`` is a pure-Python locked
dependency, never a ROS module.
"""

from __future__ import annotations

import os

# The fallback store name when ``$ROS_DISTRO`` is unset or names a distro rosbags does not
# ship. ROS2_HUMBLE matches the typestore the GUIs previously hard-coded, so a bag that
# opened in the desktop Inspect tab now opens identically from bagq and the TUI.
_FALLBACK_STORE_NAME = "ROS2_HUMBLE"


def _store_for_distro(distro: str):
    """Map a ROS distro name to a ``rosbags`` ``Stores`` member (pure; unit-testable).

    ``"humble"`` / ``"jazzy"`` -> ``Stores.ROS2_HUMBLE`` / ``Stores.ROS2_JAZZY``; an empty,
    unknown, or ROS 1 (``"noetic"``) distro falls back to ``Stores.ROS2_HUMBLE`` (def-less
    bags only occur for rosbag2, so a ROS 2 fallback is always the right shape).
    """
    from rosbags.typesys import Stores

    name = f"ROS2_{distro.strip().upper()}" if distro and distro.strip() else ""
    return getattr(Stores, name, getattr(Stores, _FALLBACK_STORE_NAME))


def resolve_default_typestore():
    """Return a ``rosbags`` ``Typestore`` for the active ROS 2 distro (``$ROS_DISTRO``).

    Used by the reader as the default-typestore FALLBACK for a definition-less bag opened
    with no explicit typestore. The selection is driven by ``$ROS_DISTRO`` (mapped via
    :func:`_store_for_distro`), defaulting to ROS2_HUMBLE.
    """
    from rosbags.typesys import get_typestore

    return get_typestore(_store_for_distro(os.environ.get("ROS_DISTRO", "")))
