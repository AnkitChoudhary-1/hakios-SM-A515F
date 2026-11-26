# Metal feasibility for Galaxy A51

Recorded 21 November 2026 after the unsuccessful UI performance experiment. This is a read-only assessment; no Metal implementation or new device installation was performed.

The owner requests an explanation of porting Metal and explicitly stops resolution reduction, blur suppression and animation changes. Speaker, apps and charging development remain paused. The current iOS session was left running after host log collection.

## Existing implementation and hardware

SM-A515F uses an Exynos 9611 and Mali-G72 MP3, a Bifrost-generation GPU. The A51 already has GPU rendering through Mesa Panfrost/OpenGL ES and HakiosMali; Metal would be another renderer rather than the first enablement of acceleration.

The repository's `devices/a51/metal.args` explicitly excludes A51 support. `docs/reference/metal.md` documents working Metal paths on the POCO X5 Pro's Adreno 642L. The direct `hakios-metal` path uses an AIR-to-NIR frontend, Mesa's Adreno ir3 compiler and Adreno PM4 command packets. The alternative uses metal2vulkan and Turnip, also an Adreno driver. Neither can run unchanged on Mali. POCO benchmark numbers are repository reports, not measurements or predictions for the A51.

## Potential approaches

A custom Mali backend could reuse the Metal frontend and AIR-to-NIR translation, then use Mesa's Bifrost compiler and Mali job/descriptor infrastructure. Necessary work includes shader semantics and resources, textures and formats, render passes and blending, buffer lifetime, IOSurface import/sharing, cache maintenance, fences, and iOS CoreAnimation's private device/plugin integration. Existing A51 driver code supplies part of the memory and submission machinery, but does not establish complete Metal compatibility.

Metal-to-Vulkan-to-PanVK is another research candidate, not a ready shortcut. The installed Mesa 25.0.7 source names G72 in `src/panfrost/lib/pan_props.c` and compiles PanVK architecture 6/7 paths in `src/panfrost/vulkan/meson.build`. However, `panvk_physical_device_init` refuses those paths unless `PAN_I_WANT_A_BROKEN_VULKAN_DRIVER` is set and warns they are not well tested. Darwin integration, required Vulkan extensions, IOSurface sharing and frontend compatibility still need validation. G72 is Bifrost, not Midgard.

CoreAnimation also needs compatible shader libraries. The existing repository's `tools/ca-metallib.py` requires a supplied compatible library alongside QuartzCore's own pipeline variants; availability for this workspace has not been established.

## Expected benefit and validation

Metal may reduce compositor CPU overhead and allow more efficient GPU work. It does not by itself resolve panel-copy bandwidth, synchronization stalls, thermal behavior, CPU scheduling or hardware throughput. Current evidence does not isolate all bottlenecks, so sustained 50–60 FPS at the original render resolution with normal effects cannot be promised.

If implementation is later requested, validate shader compilation and a correct rendered triangle first, then textures/blending/shared surfaces and synchronization, then CoreAnimation. Measure repeated scrolls/transitions and distinct presentation intervals after warm-up at the desired resolution and effects. Sixty FPS requires about 16.7 ms per presented frame; fifty requires 20 ms. Correctness, long stalls and black boxes must be assessed alongside throughput.

This is substantial driver/compiler engineering. Weeks to months or longer is a tentative project scale, not a delivery estimate; an initial feasibility probe and the first working scene would determine whether the remaining effort is practical. No Metal coding or flashing has begun in response to the explanatory question.

## Local source references

Checkout: `/opt/a51-hakios/upstream-a51/hakios` in WSL `A51-KernelBuilder`.

- `devices/a51/metal.args`
- `devices/a51/drivers/gpu/hakios.mali.cpp`
- `docs/reference/metal.md` and `docs/reference/metal-measurements.md`
- `hakios-metal/README.md`, `compiler.hpp` and `render.hpp`
- `userland/src/HakiosMetalCA.m`
- `xnu-deps/build/mesa/mesa-25.0.7/src/panfrost/compiler/meson.build`
- `xnu-deps/build/mesa/mesa-25.0.7/src/panfrost/vulkan/meson.build` and `panvk_physical_device.c`

## 22 November: alternatives preserving resolution, blur and animations

Metal is not the only plausible optimization route. No available hardware result establishes stable 50–60 FPS throughout the UI with all requested effects, and the remaining bottlenecks have not been fully isolated.

1. Optimize the existing Panfrost/OpenGL ES bridge and CoreAnimation interaction: reduce avoidable texture uploads, surface copies/checks, state work and blocking waits while preserving rendering semantics. `userland/src/eagl.c` still performs surface-change checks; its comment records historical CPU cost and an optimization already applied. New gains require current profiling, not repeating that fix or assuming every unchanged surface can safely skip checks.
2. Improve display presentation: evaluate whether DECON/DPP hardware scaling or direct presentation of suitable GPU output buffers can replace the full CPU scale/copy. This requires proving supported formats, addressing/IOMMU mappings, buffer lifetime and synchronization; it is an engineering candidate, not a feature known to work in this port. Existing double/triple buffering and one-worker copy improvements are already present and must not be presented as new fixes.
3. Fix and verify ordinary CPU/GPU DVFS and appropriate scheduling: the current clock worker has received invalid/zero rate replies and refused boosts. Correct voltage/frequency control and thermal handling could recover performance without changing effects. Requested clock arguments are not proof of applied rates, and no overclock or bypass of rate/thermal guards is proposed.

`devices/a51/PORTING.md` records historical OpenGL and display improvements, including a 9.5 ms display-copy measurement and short interactions around 48–62 frame-copy completions/s after double buffering. Those figures precede this workspace's latest tests, are not distinct-presentation measurements, and do not establish current stable UI performance. The latest valid traced workspace run still shows many interactions around 20–40 FPS and owner-reported lag.

Recommended sequence if implementation is later authorized: profile matched full-quality scrolling and transitions, separate CPU/GPU/presentation costs, address the dominant existing-path bottleneck, then decide whether a Metal backend would solve the remaining problem. A simple Metal probe could take weeks if reuse succeeds; a dependable iOS compositor backend is a months-scale research effort, potentially longer or unsuccessful. These are rough effort ranges rather than delivery dates. A working Metal API or triangle alone does not prove a performance improvement. No code, boot settings or device state were changed for this follow-up assessment.

The owner subsequently authorized implementing the alternatives. Source changes, verification and the full-quality hardware test are now tracked in [A51-full-quality-performance.md](A51-full-quality-performance.md). Metal development remains paused. The former low-resolution/effect-suppression experiment has been superseded; its historical files remain for evidence and rollback.
