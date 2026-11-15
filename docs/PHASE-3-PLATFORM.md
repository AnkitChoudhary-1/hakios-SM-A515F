> Publication note: this is a historical workspace document. Current completion decisions are in [PUBLIC-STATUS.md](PUBLIC-STATUS.md); raw local evidence is described in [PUBLICATION.md](PUBLICATION.md).

# Phase 3 single-core platform continuation

Phase 3 remains **IN PROGRESS**, device gate **UNPASSED**. Three qualifying A51 runs remain required. No phone operation occurred during these build and QEMU diagnostics.

## Implemented and build-verified

Selected isolated tree: `/opt/a51-hakios/experimental/phase3-port/20261114T013656044425Z`. Original common/native sources and dependencies remain preserved by `manifests/phase3-workspace.json`.

The Cortex-A53 ARMv8.0 configuration, GICv2 MMIO backend, boot-core/timer sysctls and static Darwin PID 1 are implemented. PID 1 requires a fresh 128-bit nonce, one CPU, matching MIDR and three measured one-second sleeps with increasing interrupt counts. Build `evidence/phase-3/platform-build/20261114T022744940027Z` passes kernel and hello commands. Kernel SHA-256 `c4f1d860dcb793d140562b56c6e89cf2e23c0e277dea22e94ba83454d8eb0797`; hello SHA-256 `14e198c86e624958e64a39a609ea97d6c19fa6b9bcd618191b463262e333e705`. Build success establishes compilation only.

## Execution failures and diagnostic findings

Full boot `evidence/phase-3/platform-qemu/20261114T022820401480Z` reached VM/IOKit setup but timed out at 120 seconds without a physical return record. Serial ends after the unavailable boot framebuffer message. Initial diagnostic `evidence/phase-3/qemu-diagnostics/20261114T023720235624Z` reached `_processor_idle`/`_ml_get_timebase`; timer IRQ and loader log counts were zero.

Expanded diagnostic `evidence/phase-3/qemu-diagnostics/20261114T024202843329Z` failed because QEMU's target XML uses undeclared `xi:include`. `scripts/phase3-qemu-diagnose.py` now adds the missing namespace only to parser input, retains original XML and reads advertised registers over the local GDB socket. Corrected run `evidence/phase-3/qemu-diagnostics/20261114T024440077269Z` captured two snapshots: virtual timer enabled/expired/unmasked; PPI 27 pending; timer IRQ count zero; Group 1 selected; distributor and CPU control 1; HPPIR 1022. No GIC interrupt acknowledgement/deactivation registers were read by the diagnostic.

The original security-disabled QEMU entry exposes a Group 0/Group 1 view inconsistent with the backend's nonsecure EL1 contract. `prototype/a51-platform/qemu_entry.S` now initializes the timer group from EL3 before entering nonsecure EL1, and `scripts/phase3-qemu-platform.py` enables QEMU security and virtualization. This is a host firmware model, not an A51 firmware observation. Corrected full execution **PASSED** in `evidence/phase-3/platform-qemu/20261114T024808085318Z` (run `20261114T024758584731Z-phase3-full-nonsecure-a53-gicv2-qemu`): all 12 checks, PID 1, three measured sleeps, increasing timer IRQ counts and physical return, in 12.724 seconds. The historical nonce is reused only by diagnostics and cannot qualify as a new gate run.

Original `kernel-user.log` is 22,485 bytes, SHA-256 `eed060f27b2e7c05940ea7f18ba08f2a1c6462791c8a99c995440f9dccc76cd5`. Fresh nonce `d9f8ce22b88d4c2aadc696bf22ba0741` identifies this host run; the return record reports reason 0/code 0, Cortex-A53 MIDR `0x410fd034` and 62.5 MHz QEMU counter. The sleeps measured 1,007,124; 1,005,575; and 1,005,598 microseconds with IRQ counts 125→183, 191→250 and 261→317. The expected PID 1 zero-exit panic returned to the physical loader stub. None of these observations is an A51 run.

## Rebuild and validation

From the Windows workspace, use `python hakios-a51/scripts/run.py --label phase3-platform-build -- wsl.exe -d A51-KernelBuilder --cd /opt/a51-hakios -- python3 /mnt/c/Users/Ankit/Desktop/A51/hakios-a51/scripts/phase3-build-platform.py`.

Execute the complete host test with the same wrapper and `scripts/phase3-qemu-platform.py --seconds 120`. It generates a fresh nonce and checks original PID 1/timer logs plus a physical return record. Its result always leaves the A51 gate false. Replays with `scripts/phase3-qemu-diagnose.py --packet <retained-platform-qemu-packet> --seconds 20` retain their diagnostic scope explicitly.

## Remaining hardware contracts and recovery

Repair the existing hardware loader's overlapping/unbounded GNSS copies, stale-register magic write, unbounded UART/log copies and exception-state loss before launching a candidate. Reserved memory labels do not establish exclusive ownership or log persistence. Prior raw RAM capture recovered zero validated XNU log bytes. Establish a bounded attributable per-run capture and return/reset mechanism, then perform three real A51 runs reaching PID 1 with timers and restore/verify the baseline boot/root state. Single boot-core support does not establish multicore support.

Rollback only the indexed host harness/document before copies in `evidence/phase-3/qemu-security-correction/20261114T024757135956Z`; preserve all failed/successful evidence. Kernel source rollback uses the indexed platform adaptation/correction packets or a new isolated tree from the source-preservation inputs. Android boot remains the last verified baseline hash `eb30609a62999e3282ac81e0a5e56411ef12ec1a39c107171bf3e01209c7cb67`.
