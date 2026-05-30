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
        _prefer_gpu()  # 260530-ja4: route the spawned viewer onto an NVIDIA dGPU (no-op otherwise)
        rec.spawn()
    return rec


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
