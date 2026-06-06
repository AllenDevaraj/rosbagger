"""Launch + lifecycle for the spawned ``rviz2`` viewer (23-03).

The Open-in-RViz button generates a ``.rviz`` config (``rviz_config.py``) and launches
``rviz2 -d <cfg>`` here. The process is tracked and SIGTERM'd on toggle-off / GUI close / exit so it
dies with the GUI — mirroring ``rosbagger_rerun.session``'s lifecycle. All stdlib; ROS-free
(launching the ``rviz2`` binary is a subprocess, not a Python ROS import). ``rviz2`` comes from the
user's sourced ROS 2 env; there is NO pip-install path (it is not pip-installable).
"""

from __future__ import annotations

# Tracked spawned rviz2 PIDs + the once-installed atexit backstop (mirrors rosbagger_rerun.session).
_TRACKED_RVIZ_PIDS: set[int] = set()
_ATEXIT_INSTALLED = False

# Standard NVIDIA Vulkan ICD locations (presence => an NVIDIA GPU + driver). rviz2 (Ogre/OpenGL) is
# routed onto the dGPU via the PRIME-offload + GLX vendor env (no-op on non-NVIDIA / non-Linux).
_NVIDIA_VULKAN_ICDS = (
    "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "/etc/vulkan/icd.d/nvidia_icd.json",
)
_GPU_OFFLOAD_ENV = (
    ("__NV_PRIME_RENDER_OFFLOAD", "1"),
    ("__VK_LAYER_NV_optimus", "NVIDIA_only"),
    ("__GLX_VENDOR_LIBRARY_NAME", "nvidia"),
)


def rviz_available() -> bool:
    """Whether ``rviz2`` is on PATH — the cheap capability probe (never raises)."""
    import shutil

    return shutil.which("rviz2") is not None


def open_rviz(config_path: str):
    """Launch ``rviz2 -d <config_path>`` as a tracked child, routed onto an NVIDIA dGPU if present.

    Returns the ``subprocess.Popen``. Spawned NON-detached (``start_new_session=False``) so a
    terminal Ctrl-C / SIGHUP reaches it via the shared process group, and tracked so
    :func:`close_rviz` SIGTERMs it on toggle-off / GUI close / atexit. Imports are local.
    """
    import subprocess

    _prefer_gpu()
    proc = subprocess.Popen(["rviz2", "-d", config_path], start_new_session=False)  # noqa: S603,S607
    _track_rviz(proc.pid)
    return proc


def _track_rviz(pid: int) -> None:
    """Remember a spawned rviz2 PID + install the atexit cleanup backstop once."""
    import atexit

    global _ATEXIT_INSTALLED
    _TRACKED_RVIZ_PIDS.add(pid)
    if not _ATEXIT_INSTALLED:
        _ATEXIT_INSTALLED = True
        atexit.register(close_rviz)


def close_rviz() -> None:
    """SIGTERM every tracked rviz2 child + clear the registry (idempotent; no-op when none)."""
    for pid in tuple(_TRACKED_RVIZ_PIDS):
        _terminate_pid(pid)
        _TRACKED_RVIZ_PIDS.discard(pid)


def _terminate_pid(pid: int) -> None:
    """Best-effort SIGTERM + non-blocking reap of a tracked rviz2 child."""
    import os
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, os.WNOHANG)  # reap if it died instantly (else a harmless transient zombie)
    except OSError:
        return  # already gone / not our child


def _nvidia_vulkan_present() -> bool:
    """True iff an NVIDIA Vulkan ICD is installed (the cheap dGPU-present probe)."""
    import os

    return any(os.path.exists(p) for p in _NVIDIA_VULKAN_ICDS)


def _prefer_gpu(env=None) -> None:
    """setdefault the NVIDIA PRIME-offload env so rviz2 renders on the dGPU (no-op otherwise).

    ``setdefault`` means a user who already exported these (their own launch prefix) wins.
    """
    import os

    if env is None:
        env = os.environ
    if not _nvidia_vulkan_present():
        return
    for key, val in _GPU_OFFLOAD_ENV:
        env.setdefault(key, val)
