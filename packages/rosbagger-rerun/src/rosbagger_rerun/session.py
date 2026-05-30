"""Rerun session lifecycle — the capability probe + viewer/recording builder.

Both functions import ``rerun`` LAZILY inside the body (the offline-import invariant):
``import rosbagger_rerun.session`` stays Rerun-free; ``rerun`` is only touched when a
function actually runs (and only after ``rerun_available()`` has gated it).
"""

from __future__ import annotations


def rerun_available() -> bool:
    """Whether ``rerun-sdk`` is importable — the lazy capability probe (never raises).

    The Rerun analog of ``rosbagger_desktop.capabilities.ros_available()``: the import
    lives INSIDE the body so this module stays Rerun-free at import. The desktop's
    "Open in Rerun" button calls this to decide between opening the viewer and the
    install-on-click path. Returns ``True`` iff ``import rerun`` succeeds.
    """
    try:
        import rerun  # noqa: F401
    except ImportError:
        return False
    return True


def open_viewer(app_id: str = "rosbagger", *, save_path: str | None = None):
    """Build a Rerun ``RecordingStream`` — spawn the viewer, or write a ``.rrd``.

    ``save_path=None`` (default) spawns the bundled Rerun viewer and streams to it
    (the GUI path). A ``save_path`` writes to that ``.rrd`` file with NO viewer process
    (the test path — see ``tests/test_rerun_live.py``). Returns the recording so a
    caller can build a sink against it (:func:`rosbagger_rerun.build_rerun_sink`).

    ``import rerun`` is lazy here (offline invariant). Verify against the installed
    rerun-sdk (>=0.31): ``rerun.RecordingStream`` + ``.spawn()`` / ``.save()`` are the
    0.31 names — confirm if a newer SDK is installed.
    """
    import rerun as rr

    rec = rr.RecordingStream(app_id)
    if save_path is not None:
        rec.save(save_path)
    else:
        rec.spawn()
    return rec
