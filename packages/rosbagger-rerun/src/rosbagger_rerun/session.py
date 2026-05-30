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

    260530-c3p: the spawned viewer is launched with ``detach_process=False`` so it shares this
    process's group/session (a terminal Ctrl-C / SIGHUP reaches it directly) and stays our direct
    child (so :func:`close_viewer` can kill it on window-close / atexit). The default
    ``detach_process=True`` ``setsid``'s it into its own session, leaving it running after the GUI
    closes — the behavior the user reported.
    """
    import rerun as rr

    rec = rr.RecordingStream(app_id)
    if save_path is not None:
        rec.save(save_path)
        return rec
    _prefer_gpu()  # 260530-ja4: route the spawned viewer onto an NVIDIA dGPU (no-op otherwise)
    # 260530-c3p: spawn NON-detached + record the new child PID(s) so the viewer dies with the GUI.
    before = set(_child_pids())
    rec.spawn(detach_process=False)
    _track_viewers(set(_child_pids()) - before)
    return rec


# 260530-c3p: tie the spawned Rerun viewer's lifetime to THIS (the desktop) process. The viewer is
# spawned non-detached (open_viewer), so a terminal Ctrl-C/SIGHUP already reaches it via the shared
# process group; this registry + close_viewer cover the window-close / normal-exit paths.
_TRACKED_VIEWER_PIDS: set[int] = set()
_ATEXIT_INSTALLED = False


def _child_pids(pid: int | None = None) -> list[int]:
    """PIDs of this process's DIRECT children via ``/proc`` (Linux); ``[]`` on non-Linux / error.

    Used by :func:`open_viewer` to capture the spawned viewer's PID by diffing children across the
    spawn — robust to the viewer's process name. Reads ``/proc/<pid>/stat`` and takes ``ppid`` (the
    field after the parenthesized ``comm``, which may itself contain spaces/``)``).
    """
    import os

    parent = os.getpid() if pid is None else pid
    children: list[int] = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return children
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as fh:
                data = fh.read()
            # ``comm`` (field 2) is parenthesized + may contain spaces/")"; split after the last ")"
            ppid = int(data[data.rindex(b")") + 1 :].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == parent:
            children.append(int(name))
    return children


def _track_viewers(pids) -> None:
    """Remember spawned viewer PIDs + install the ``atexit`` cleanup backstop once (260530-c3p)."""
    import atexit

    global _ATEXIT_INSTALLED
    _TRACKED_VIEWER_PIDS.update(pids)
    if _TRACKED_VIEWER_PIDS and not _ATEXIT_INSTALLED:
        _ATEXIT_INSTALLED = True
        atexit.register(close_viewer)


def close_viewer() -> None:
    """Terminate every tracked spawned Rerun viewer — the close/exit hook (260530-c3p).

    Called from the desktop's ``_close_rerun`` / ``closeEvent`` AND (registered once) at interpreter
    exit, so the viewer dies when the GUI window is closed or the process exits normally.
    Idempotent: a viewer already gone — or never spawned (save mode) — is a no-op. Ctrl-C / SIGHUP
    already reach the viewer directly via the shared process group (it is spawned non-detached)."""
    for pid in tuple(_TRACKED_VIEWER_PIDS):
        _terminate_pid(pid)
        _TRACKED_VIEWER_PIDS.discard(pid)


def _terminate_pid(pid: int) -> None:
    """Best-effort ``SIGTERM`` + non-blocking reap of a viewer child (260530-c3p)."""
    import os
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, os.WNOHANG)  # reap if it died instantly (else a harmless transient zombie)
    except OSError:
        return  # already gone / not our child


# Standard NVIDIA Vulkan ICD locations (presence ⇒ an NVIDIA GPU + driver are installed).
_NVIDIA_VULKAN_ICDS = (
    "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "/etc/vulkan/icd.d/nvidia_icd.json",
)

# PRIME-offload env that routes a Vulkan (wgpu) app onto the NVIDIA dGPU on an Optimus laptop.
# GLX vars alone don't help (Rerun is Vulkan, not OpenGL) — the Vulkan offload + power-pref do.
_GPU_OFFLOAD_ENV = (
    ("__NV_PRIME_RENDER_OFFLOAD", "1"),
    ("__VK_LAYER_NV_optimus", "NVIDIA_only"),
    ("__GLX_VENDOR_LIBRARY_NAME", "nvidia"),
    ("WGPU_POWER_PREF", "high"),
)


def _nvidia_vulkan_present() -> bool:
    """True iff an NVIDIA Vulkan ICD is installed (the cheap dGPU-present probe)."""
    import os

    return any(os.path.exists(p) for p in _NVIDIA_VULKAN_ICDS)


def _prefer_gpu(env=None) -> None:
    """Set PRIME-offload env so the spawned Rerun viewer renders on the NVIDIA dGPU.

    Rerun's viewer renders with Vulkan (wgpu); on an Optimus laptop it otherwise falls back to the
    iGPU or software (llvmpipe). When an NVIDIA Vulkan ICD is present we ``setdefault`` the offload
    env into ``env`` (default ``os.environ``) — so the viewer subprocess, which inherits the process
    environment, uses the dGPU. ``setdefault`` means a user who already exported these (their own
    launch prefix) wins. No-op on non-NVIDIA / non-Linux boxes.
    """
    import os

    if env is None:
        env = os.environ
    if not _nvidia_vulkan_present():
        return
    for key, val in _GPU_OFFLOAD_ENV:
        env.setdefault(key, val)
