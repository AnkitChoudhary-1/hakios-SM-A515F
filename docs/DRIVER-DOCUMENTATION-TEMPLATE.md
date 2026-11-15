> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Documentation required alongside future driver work

Use this as a checklist when implementing a loader, platform service, hardware driver or Darwin compatibility component. Create a subsystem document when that work starts; link it from INDEX.md, FILE-MAP.md and the implementation log. This template is planned documentation guidance, not an implemented driver.

## Identity and state

Record the phase, subsystem, target model/board revision, source commit and patch identity. State which operations are implemented, which have executed on the A51, and which are still planned or unknown. Link each claim to the exact build/device run and immutable artifact identity. Distinguish host parser tests, QEMU execution and physical-device evidence.

## Location and configuration

List durable source/header/config/patch paths, generated destination paths and built outputs. Explain the generation/sync step and the command that rebuilds affected files. List compile-time options and runtime boot arguments separately, including defaults, dependencies and effects. Document how a future agent enables one bounded probe and how to disable it again.

## Hardware and firmware provenance

Cite the matching A51 DTS/DTBO nodes, Linux reference paths and source commit. Record base addresses, lengths, IRQs, clocks, resets, power domains, regulators and bus addresses with their evidence. Do not silently borrow another phone's addresses. Identify firmware version, source/location, size, checksum, ABI and loading requirements; distinguish a filename listing from an acquired/validated blob. Keep device identity and unavailable facts explicit.

## Interfaces and data flow

Describe the public kernel API, sysctl/IOKit user-client or service endpoints and user-space caller. Document request/response structures, field sizes, alignment, byte order, ABI version, permitted commands and error codes. Explain the initialization dependency graph and the path from a user request to hardware completion and response.

## Memory, ownership and concurrency

Describe allocation limits, DMA buffers, physical/virtual mappings, page sizes, IOMMU/MMU setup and cache maintenance. State who owns each resource at each stage, how fences/completions transfer ownership and when resources are freed. Record locks, IRQ/workloop context, timeouts, cancellation and error recovery. Identify reserved regions and prove payload/DMA ranges stay within the chosen map.

## Initialization, normal use and shutdown

Document sequencing for power, clocks, reset, firmware, IRQ registration and interface publication. Provide state transitions for normal operations, disconnects, suspend/reset where implemented and retry/fault recovery. Explain partial-initialization cleanup, interrupt quiescence, DMA stop and shutdown order. Record unsupported transitions.

## Validation and debugging

Provide exact recorded host/build/device commands, expected bounded output, observed output and pass/fail criteria. Name the hardware, peripherals, workload, duration and environmental conditions used. Link logs, samples and frame/current/temperature measurements where relevant. Include known failures, log retrieval and reset/return procedure. Do not count a visible switch, compilation or hardware probe as a completed functional test.

## Modification and rollback

Give a concrete example of changing a parameter or operation, its affected files, rebuild command and required regression checks. Explain how to revert the identified commit/patch and restore the preceding test artifact. Preserve original backups and historical results. Add every implementation/configuration change to IMPLEMENTATION-LOG.md and update the current state only when the acceptance gate changes.
