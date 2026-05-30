---
quick_id: 260530-ja4
slug: route-spawned-rerun-viewer-onto-nvidia-d
date: 2026-05-30
status: complete
commit: ee34a4a
---

# Quick Task 260530-ja4 — Summary

## What changed
`rosbagger_rerun/session.py`: `open_viewer()` now calls `_prefer_gpu()` before `rec.spawn()`
(spawn mode only; save mode for tests untouched). `_prefer_gpu(env=os.environ)` `setdefault`s the
Vulkan PRIME-offload env (`__NV_PRIME_RENDER_OFFLOAD=1`, `__VK_LAYER_NV_optimus=NVIDIA_only`,
`__GLX_VENDOR_LIBRARY_NAME=nvidia`, `WGPU_POWER_PREF=high`) when `_nvidia_vulkan_present()` (an
NVIDIA Vulkan ICD exists). The spawned viewer inherits the env → renders on the dGPU instead of
llvmpipe/iGPU. `setdefault` ⇒ a user's own exports win; no-op on non-NVIDIA/non-Linux. 3 offline
tests (injected when present, no-op when absent, setdefault respects pre-set key).

## Why
Rerun renders with Vulkan (wgpu); the user's GLX prefix (`__GLX_VENDOR_LIBRARY_NAME`) doesn't
help (OpenGL-only). On their Optimus laptop (RTX 4070) the viewer fell back to software. Now the
app sets the right Vulkan offload env automatically — no launch prefix needed.

## Verification
| Check | Result |
|-------|--------|
| rerun unit + offline guard | **34 passed** |
| Full offline suite | **570 passed, 6 skipped** (+3) |
| import rosbagger_rerun pulls no rerun/rclpy | clean |
| ruff | clean |

## Note
Actual GPU selection can't be verified in CI (no GPU surface) — the env-injection logic is
unit-tested. User confirms on their box by watching the viewer log for `device_type: DiscreteGpu,
name: "NVIDIA GeForce RTX 4070..."` instead of `llvmpipe`.
