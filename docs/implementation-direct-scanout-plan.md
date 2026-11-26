# HakiOS — Direct GPU Surface Scanout POC

## Objective

Implement an experimental **Direct GPU Surface Scanout** mode for HakiOS on the Samsung Galaxy A51 (Exynos 9611, Mali-G72 MP3).

The goal is to eliminate the current CPU framebuffer-copy bottleneck by allowing the Mali GPU to render into a physically contiguous framebuffer buffer that is directly scanned out by the DECON display controller.

Currently, the rendering pipeline appears to be:

`CoreAnimation → Panfrost/Mali GPU → IOSurface → GPU fence → CPU memcpy/scaling → DECON framebuffer → Display`

The proposed experimental pipeline is:

`CoreAnimation → Panfrost/Mali GPU → Display-compatible framebuffer → GPU fence → DECON IDMA flip → Display`

The existing CPU-copy implementation must remain intact as the fallback.

---

## Phase 1 — Repository Audit (MANDATORY)

Before modifying any code:

1. Inspect the complete existing framebuffer implementation.
2. Trace the framebuffer lifecycle from userland through kernel and DECON.
3. Identify:
   - Framebuffer physical addresses.
   - Buffer allocation and reservation mechanism.
   - Buffer size, stride, format, and resolution.
   - Existing double/triple buffering implementation.
   - DECON IDMA configuration.
   - Existing framebuffer flip mechanism.
   - GPU IOSurface allocation and physical mapping.
   - GPU fence and completion synchronization.
   - Cache coherency requirements.
   - Existing memory barriers.
4. Verify all assumptions directly against source code.

Relevant files include, but are not limited to:

- `xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp`
- `xnu/files/iokit/Kernel/MiniIOSurface.cpp`
- `devices/a51/drivers/gpu/hakios.mali.cpp`
- `devices/a51/soc/configs/a51.config`
- UEFI memory map and framebuffer reservation code.
- Panfrost DRM compatibility layer.
- BackBoard/CoreAnimation surface presentation code.

Do not assume the previously documented physical addresses or register offsets are correct without verifying them against the repository.

Create an audit report:

`docs/direct_gpu_scanout_audit.md`

Include:

- Current pipeline.
- Relevant source locations.
- Confirmed hardware constraints.
- Existing synchronization mechanisms.
- Identified risks.
- Proposed minimal implementation.

Do not begin implementation until the audit is complete.

---

## Phase 2 — Design a Safe Experimental Architecture

Implement direct scanout as an opt-in experimental feature.

Suggested boot argument:

`fb_direct=1`

Default behavior must remain unchanged.

Design a framebuffer state machine:

- `FREE`
- `GPU_RENDERING`
- `READY_FOR_SCANOUT`
- `PENDING_LATCH`
- `SCANNING_OUT`

Never allow the GPU to write into a framebuffer currently being scanned out by DECON.

Never allow DECON to scan a framebuffer whose GPU rendering is incomplete.

Use existing synchronization mechanisms whenever possible.

Do not introduce arbitrary delays as a substitute for GPU fences or display synchronization.

---

## Phase 3 — Framebuffer Compatibility

Before enabling direct scanout, verify that the GPU surface is compatible with the display controller.

Required properties:

- 1080 × 2400 native display resolution.
- BGRA8888 or the exact display-supported format.
- Correct pixel stride.
- Correct buffer size.
- Physically contiguous memory if required by DECON.
- Physical address within the display controller's supported address range.
- Correct memory alignment.
- Correct cache coherency behavior.

Do not assume a normal IOSurface is suitable for direct DECON scanout.

If an IOSurface is allocated outside the reserved framebuffer memory region, do not attempt to scan it out unless the hardware and driver explicitly support its physical address and memory configuration.

---

## Phase 4 — Minimal Proof of Concept

Do not immediately modify the entire CoreAnimation presentation pipeline.

Implement the smallest possible POC first:

1. Select a framebuffer that is not currently being scanned out.
2. Map the framebuffer into Mali GPU address space.
3. Render a simple GPU-generated test pattern.
4. Wait for GPU completion using the existing fence mechanism.
5. Perform any required cache synchronization.
6. Submit the framebuffer to the existing DECON flip mechanism.
7. Wait for the display controller to latch the framebuffer.
8. Verify the output visually and through logs.

Test patterns should include:

- Solid colors.
- Color gradients.
- Checkerboard.
- GPU-rendered moving rectangle.
- Frame counter.

The test should verify that the image is genuinely GPU-rendered and directly scanned out, rather than CPU-copied into another framebuffer.

---

## Phase 5 — Safe DECON Integration

Reuse existing display-controller configuration and framebuffer-switching infrastructure wherever possible.

Do not create a parallel DECON driver unless the existing implementation genuinely cannot support the required operation.

The implementation must:

- Respect existing DECON shadow-register behavior.
- Respect pending framebuffer flips.
- Avoid changing the active framebuffer while unsafe.
- Synchronize flips with VSYNC or the existing display synchronization mechanism.
- Preserve the existing framebuffer format and display configuration.
- Handle failed flips gracefully.
- Prevent framebuffer ownership conflicts.

Do not hardcode register writes based solely on previous audit notes.

Verify every register, bit field, and hardware behavior against the actual source and available hardware documentation.

---

## Phase 6 — CoreAnimation Integration

Only after the standalone GPU scanout POC works:

Investigate whether CoreAnimation/BackBoard can render directly into the reserved scanout buffers.

Possible approaches:

### Approach A — Direct Rendering

CoreAnimation GPU rendering targets a framebuffer already mapped into the Mali GPU address space.

The framebuffer is then submitted directly to DECON after the GPU fence completes.

### Approach B — GPU Blit

CoreAnimation renders to a normal IOSurface.

A GPU blit copies the rendered image into the display framebuffer.

The display framebuffer is then directly scanned out.

This is acceptable if direct rendering into DECON buffers proves incompatible.

The GPU blit must not silently fall back to a CPU memcpy.

### Approach C — Existing CPU Fallback

If direct GPU presentation fails, use the existing CPU-copy pipeline.

Fallback must be automatic and safe.

---

## Phase 7 — Performance Measurement

Establish baseline measurements before implementation.

Measure:

- CPU time spent in `drawRows()`.
- CPU time spent in framebuffer memcpy.
- GPU rendering time.
- Frame presentation latency.
- Frame drops.
- Average FPS.
- CPU utilization.
- Memory bandwidth where measurable.

Compare:

| Metric | Original Pipeline | Direct Scanout |
|---|---|---|
| CPU framebuffer copy | | |
| CPU presentation time | | |
| Average FPS | | |
| Frame drops | | |
| GPU rendering time | | |
| Presentation latency | | |

Do not claim improvements without actual measurements.

Do not assume direct scanout guarantees 60 FPS. GPU rendering, CoreAnimation composition, DECON timing, synchronization, and other bottlenecks may remain.

---

## Phase 8 — Logging and Diagnostics

Add structured logs with a dedicated tag:

`[DirectScanout]`

Log:

- Feature enabled/disabled.
- Framebuffer addresses.
- Framebuffer dimensions.
- Pixel format.
- Stride.
- Buffer ownership transitions.
- GPU fence completion.
- DECON flip submission.
- VSYNC/latch completion.
- Failed compatibility checks.
- Fallback activation.
- GPU/DECON synchronization failures.

Avoid logging every frame permanently.

Add a diagnostic mode that can enable verbose frame-level logging.

---

## Phase 9 — Safety and Rollback

The implementation must be reversible.

Requirements:

- Default boot uses the original pipeline.
- `fb_direct=1` enables experimental mode.
- Failure to initialize direct scanout must revert to the original pipeline.
- No framebuffer reservation changes unless verified necessary.
- No changes to GPU MMU behavior unless required and audited.
- No changes to existing Panfrost job submission.
- No removal of CPU fallback.
- No modifications to unrelated drivers.

If direct scanout fails, the device must remain bootable.

---

## Phase 10 — Final Deliverables

After implementation:

1. List all modified files.
2. Explain each modification.
3. Document the new boot argument.
4. Document the framebuffer state machine.
5. Provide build instructions.
6. Provide testing instructions.
7. Provide rollback instructions.
8. Provide actual test results.
9. Clearly distinguish:
   - Implemented.
   - Compiled.
   - Boot-tested.
   - Hardware-tested.
   - Verified working.
   - Not yet verified.

Update:

`docs/direct_gpu_scanout.md`

---

## Important Engineering Rules

- Inspect before modifying.
- Verify assumptions against actual source.
- Make incremental changes.
- Build after each meaningful change.
- Do not fabricate hardware capabilities.
- Do not invent register offsets.
- Do not replace working code unnecessarily.
- Preserve the original framebuffer pipeline.
- Never use CPU memcpy as a hidden substitute for direct GPU scanout in the experimental path.
- If a technical limitation prevents implementation, explain it and stop at the last verified stage.
- Prioritize a minimal working POC over a large speculative implementation.

## Success Criteria

The POC is successful only when:

1. Mali renders directly into a display-compatible physical framebuffer.
2. GPU completion is synchronized correctly.
3. DECON scans out that same framebuffer.
4. The presentation path does not perform a CPU framebuffer memcpy.
5. Framebuffer ownership is safe.
6. The original pipeline remains functional.
7. The feature can be enabled and disabled independently.
8. Actual hardware testing confirms the behavior.
